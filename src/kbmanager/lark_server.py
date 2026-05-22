"""User-side Feishu/Lark message server for KBManager."""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from kbmanager import application
from kbmanager.contracts import ApiStatus

SUPPORTED_FILE_SUFFIXES = {".md", ".pdf"}
MAX_LLM_ATTEMPTS = 3
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
LOGGER = logging.getLogger(__name__)


class ReplyClient(Protocol):
    def reply(self, message_id: str | None, chat_id: str | None, text: str) -> None:
        """Reply to the source message or chat."""


class FileDownloader(Protocol):
    def download_file(self, file: IncomingFile, temp_dir: Path) -> Path:
        """Download or copy an incoming file into the task temp directory."""


@dataclass(frozen=True)
class LarkSettings:
    app_id: str
    app_secret: str
    remote: str = "origin"
    branch: str = "main"
    ack_only: bool = True


@dataclass(frozen=True)
class IncomingFile:
    name: str
    path: Path | None = None
    file_key: str | None = None
    message_id: str | None = None


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: str
    user_id: str
    message_id: str | None
    text: str = ""
    files: tuple[IncomingFile, ...] = ()


@dataclass(frozen=True)
class MessageBlock:
    kind: str
    chat_id: str
    user_id: str
    message_id: str | None
    content: str
    files: tuple[IncomingFile, ...] = ()


@dataclass(frozen=True)
class Job:
    job_id: str
    block: MessageBlock


@dataclass(frozen=True)
class JobResult:
    success: bool
    message: str
    commit_message: str | None = None
    object_ids: tuple[str, ...] = ()
    stash_ref: str | None = None


class MessageAccumulator:
    """Convert each incoming Feishu/Lark message into an independent task block."""

    def __init__(self) -> None:
        pass

    def ingest(self, message: IncomingMessage) -> list[MessageBlock]:
        text = (message.text or "").strip()
        if not text and not message.files:
            return []
        kind = "source"
        content = text
        if text.lower().startswith("note"):
            kind = "note"
            content = text[4:].strip()
        return [
            MessageBlock(
                kind=kind,
                chat_id=message.chat_id,
                user_id=message.user_id,
                message_id=message.message_id,
                content=content,
                files=message.files,
            )
        ]


class LlmOutputParseError(RuntimeError):
    def __init__(self, message: str, *, raw_output: str, debug_log: Path) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.debug_log = debug_log


class ClaudeCliLlm:
    def __init__(self, root: Path, *, timeout_seconds: int = 600) -> None:
        self.root = root
        self.timeout_seconds = timeout_seconds

    def complete(self, llm_request: dict[str, Any]) -> dict[str, Any]:
        prompt = _llm_prompt_text(llm_request)
        purpose = llm_request.get("purpose")
        request_id = llm_request.get("id")
        debug_log = _claude_debug_log_path(self.root, purpose, request_id)
        LOGGER.info(
            "running claude request purpose=%s id=%s debug_log=%s",
            purpose,
            request_id,
            debug_log,
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--permission-mode",
                    "bypassPermissions",
                    "--debug-file",
                    str(debug_log),
                    "--add-dir",
                    str(self.root),
                ],
                cwd=self.root,
                check=False,
                capture_output=True,
                input=prompt,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            LOGGER.error(
                "claude request timed out purpose=%s id=%s elapsed=%.2fs timeout=%ss "
                "debug_log=%s",
                purpose,
                request_id,
                elapsed,
                self.timeout_seconds,
                debug_log,
            )
            raise RuntimeError(
                f"claude -p timed out after {self.timeout_seconds}s; debug log: {debug_log}"
            ) from exc
        elapsed = time.monotonic() - started
        LOGGER.info(
            "claude request exited purpose=%s id=%s returncode=%s elapsed=%.2fs "
            "stdout_bytes=%s stderr_bytes=%s debug_log=%s",
            purpose,
            request_id,
            completed.returncode,
            elapsed,
            len(completed.stdout.encode("utf-8")),
            len(completed.stderr.encode("utf-8")),
            debug_log,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            LOGGER.error(
                "claude request failed purpose=%s id=%s debug_log=%s detail=%s",
                purpose,
                request_id,
                debug_log,
                stderr[:1000],
            )
            raise RuntimeError(f"claude -p failed: {stderr}; debug log: {debug_log}")
        try:
            result = _parse_structured_output(completed.stdout)
        except Exception as exc:
            LOGGER.exception(
                "failed to parse claude output purpose=%s id=%s debug_log=%s stdout_preview=%r",
                purpose,
                request_id,
                debug_log,
                completed.stdout[:1000],
            )
            raise LlmOutputParseError(
                f"failed to parse claude output: {exc}; debug log: {debug_log}",
                raw_output=completed.stdout,
                debug_log=debug_log,
            ) from exc
        LOGGER.info(
            "claude request completed purpose=%s id=%s debug_log=%s",
            purpose,
            request_id,
            debug_log,
        )
        return result


class GitRunner:
    def __init__(self, root: Path, *, remote: str = "origin", branch: str = "main") -> None:
        self.root = root
        self.remote = remote
        self.branch = branch

    def prepare(self, job_id: str) -> str | None:
        stash_ref: str | None = None
        if self._status():
            message = f"kbmanager-lark-{job_id}"
            before = self._stash_top()
            LOGGER.info("stashing dirty worktree job_id=%s", job_id)
            self._run(["git", "stash", "push", "-u", "-m", message])
            after = self._stash_top()
            stash_ref = after or before or message
            LOGGER.info("created stash job_id=%s stash_ref=%s", job_id, stash_ref)
        LOGGER.info("updating branch remote=%s branch=%s", self.remote, self.branch)
        self._run(["git", "fetch", self.remote, self.branch])
        self._run(["git", "checkout", self.branch])
        self._run(["git", "pull", "--ff-only", self.remote, self.branch])
        return stash_ref

    def commit_and_push(self, message: str) -> None:
        if not self._status():
            raise RuntimeError("task produced no git changes")
        LOGGER.info("committing task changes message=%s", message)
        self._run(["git", "add", "--all"])
        self._run(["git", "commit", "-m", message])
        self._run(["git", "push", self.remote, self.branch])
        LOGGER.info("pushed task changes remote=%s branch=%s", self.remote, self.branch)

    def _status(self) -> str:
        return self._run(["git", "status", "--porcelain"]).strip()

    def _stash_top(self) -> str | None:
        result = self._run(["git", "stash", "list"])
        first = result.splitlines()[0] if result.splitlines() else ""
        return first.split(":", 1)[0] if first else None

    def _run(self, command: list[str]) -> str:
        completed = subprocess.run(
            command,
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"{' '.join(command)} failed: {detail}")
        return completed.stdout


class JobProcessor:
    def __init__(
        self,
        root: Path,
        *,
        llm: ClaudeCliLlm | None = None,
        git: GitRunner | None = None,
        downloader: FileDownloader | None = None,
        ack_only: bool = False,
    ) -> None:
        self.root = root
        self.llm = llm or ClaudeCliLlm(root)
        self.git = git
        self.downloader = downloader
        self.ack_only = ack_only

    def process(self, job: Job) -> JobResult:
        if self.ack_only:
            LOGGER.info(
                "ack-only job success job_id=%s kind=%s chat_id=%s",
                job.job_id,
                job.block.kind,
                job.block.chat_id,
            )
            return JobResult(success=True, message=f"{job.block.kind} ack-only success")

        temp_dir = Path(tempfile.mkdtemp(prefix=f"kbmanager-lark-{job.job_id}-"))
        stash_ref: str | None = None
        try:
            LOGGER.info(
                "starting job job_id=%s kind=%s chat_id=%s",
                job.job_id,
                job.block.kind,
                job.block.chat_id,
            )
            if self.git is not None:
                stash_ref = self.git.prepare(job.job_id)
            if job.block.kind == "note":
                result = self._process_note(job.block)
            else:
                result = self._process_source(job.block, temp_dir)
            if self.git is not None:
                self.git.commit_and_push(result.commit_message or _fallback_commit_message(job))
            return JobResult(
                success=True,
                message=result.message,
                commit_message=result.commit_message,
                object_ids=result.object_ids,
                stash_ref=stash_ref,
            )
        except Exception as exc:
            LOGGER.exception(
                "job failed job_id=%s kind=%s stash_ref=%s",
                job.job_id,
                job.block.kind,
                stash_ref,
            )
            return JobResult(
                success=False,
                message=str(exc),
                stash_ref=stash_ref,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            LOGGER.info("removed job temp dir job_id=%s path=%s", job.job_id, temp_dir)

    def _process_note(self, block: MessageBlock) -> JobResult:
        content = block.content.strip()
        if not content:
            raise ValueError("note content is empty")
        LOGGER.info("calling kb.note.add needs_llm")
        first = application.note_add(self.root, content=content, needs_llm=True).to_dict()
        if first["status"] == ApiStatus.NEEDS_LLM.value:
            first = self._resume_with_llm_retry(
                "note add",
                first,
                lambda llm_result: application.note_add(
                    self.root,
                    content=content,
                    needs_llm=True,
                    resume_token=first["resume"]["token"],
                    llm_result=llm_result,
                ).to_dict(),
            )
        _raise_if_not_success(first, "note add")
        note = first.get("note") or {}
        title = _string(note.get("title")) or _string(first.get("summary")) or "Add note"
        note_id = _string(first.get("note_id")) or _string(note.get("id"))
        return JobResult(
            success=True,
            message="note added",
            commit_message=title,
            object_ids=(note_id,) if note_id else (),
        )

    def _process_source(self, block: MessageBlock, temp_dir: Path) -> JobResult:
        input_path = _source_input_path(block, temp_dir, self.downloader)
        LOGGER.info("calling kb.source.add input_path=%s", input_path)
        first = application.source_add(self.root, input_path=input_path).to_dict()
        if first["status"] == ApiStatus.NEEDS_LLM.value:
            first = self._resume_with_llm_retry(
                "source add",
                first,
                lambda llm_result: application.source_add(
                    self.root,
                    input_path=input_path,
                    resume_token=first["resume"]["token"],
                    llm_result=llm_result,
                ).to_dict(),
            )
        _raise_if_not_success(first, "source add")
        source_ids = list(first.get("source_ids", []))
        LOGGER.info("calling kb.candidate.create source_ids=%s", source_ids)
        candidate = application.candidate_create(self.root, source_ids=source_ids).to_dict()
        if candidate["status"] == ApiStatus.NEEDS_LLM.value:
            candidate = self._resume_with_llm_retry(
                "candidate create",
                candidate,
                lambda llm_result: application.candidate_create(
                    self.root,
                    source_ids=source_ids,
                    resume_token=candidate["resume"]["token"],
                    llm_result=llm_result,
                ).to_dict(),
            )
        _raise_if_not_success(candidate, "candidate create")
        candidate_ids = list(candidate.get("candidate_ids", []))
        summary = _source_commit_message(first, candidate)
        return JobResult(
            success=True,
            message="source added",
            commit_message=summary,
            object_ids=tuple(str(item) for item in [*source_ids, *candidate_ids]),
        )

    def _resume_with_llm_retry(
        self,
        stage: str,
        needs_llm_result: dict[str, Any],
        resume: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        llm_request = needs_llm_result["llm_request"]
        result: dict[str, Any] = needs_llm_result
        for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
            LOGGER.info(
                "calling llm for %s attempt=%s max_attempts=%s",
                stage,
                attempt,
                MAX_LLM_ATTEMPTS,
            )
            try:
                llm_result = self.llm.complete(llm_request)
            except LlmOutputParseError as exc:
                if attempt == MAX_LLM_ATTEMPTS:
                    LOGGER.warning(
                        "%s failed to parse llm output after %s attempts",
                        stage,
                        MAX_LLM_ATTEMPTS,
                    )
                    raise
                LOGGER.warning(
                    "%s failed to parse llm output attempt=%s error=%s",
                    stage,
                    attempt,
                    exc,
                )
                llm_request = _llm_parse_retry_request(llm_request, attempt + 1, exc)
                continue
            LOGGER.info("resuming %s attempt=%s", stage, attempt)
            result = resume(llm_result)
            if result.get("status") == ApiStatus.SUCCESS.value:
                return result
            if attempt == MAX_LLM_ATTEMPTS:
                LOGGER.warning("%s failed after %s llm attempts", stage, MAX_LLM_ATTEMPTS)
                return result
            LOGGER.warning(
                "%s rejected llm result attempt=%s status=%s errors=%s",
                stage,
                attempt,
                result.get("status"),
                result.get("errors") or [],
            )
            llm_request = _llm_retry_request(llm_request, attempt + 1, llm_result, result)
        return result


class Worker:
    def __init__(self, processor: JobProcessor, replies: ReplyClient) -> None:
        self.processor = processor
        self.replies = replies
        self.jobs: queue.Queue[Job] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, block: MessageBlock) -> str:
        job_id = uuid.uuid4().hex[:12]
        self.jobs.put(Job(job_id=job_id, block=block))
        LOGGER.info("queued job job_id=%s kind=%s chat_id=%s", job_id, block.kind, block.chat_id)
        self.replies.reply(
            block.message_id,
            block.chat_id,
            f"{block.kind} [{job_id}] 已收到，正在处理",
        )
        return job_id

    def _run(self) -> None:
        while True:
            job = self.jobs.get()
            try:
                result = self.processor.process(job)
                prefix = f"{job.block.kind} [{job.job_id}]"
                if result.success:
                    LOGGER.info("job succeeded job_id=%s kind=%s", job.job_id, job.block.kind)
                    ids = f"：{', '.join(result.object_ids)}" if result.object_ids else ""
                    stash = f"\n已保留 stash：{result.stash_ref}" if result.stash_ref else ""
                    self.replies.reply(
                        job.block.message_id,
                        job.block.chat_id,
                        f"{prefix} 已添加{ids}{stash}",
                    )
                else:
                    LOGGER.info("job failed reply job_id=%s kind=%s", job.job_id, job.block.kind)
                    stash = f"\n已保留 stash：{result.stash_ref}" if result.stash_ref else ""
                    self.replies.reply(
                        job.block.message_id,
                        job.block.chat_id,
                        f"{prefix} 添加失败：{result.message}{stash}",
                    )
            finally:
                self.jobs.task_done()


def load_settings(root: Path) -> LarkSettings:
    path = root / ".lark/settings.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("missing .lark/settings.json; copy settings.json.example first") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f".lark/settings.json is not valid JSON: {exc}") from exc
    app_id = _string(raw.get("app_id"))
    app_secret = _string(raw.get("app_secret"))
    if not app_id or not app_secret:
        raise RuntimeError(".lark/settings.json must include app_id and app_secret")
    return LarkSettings(
        app_id=app_id,
        app_secret=app_secret,
        remote=_string(raw.get("remote")) or "origin",
        branch=_string(raw.get("branch")) or "main",
        ack_only=_bool(raw.get("ack_only"), default=True),
    )


def run_server(root: Path, *, process_name: str = "") -> None:
    configure_logging(root)
    try:
        settings = load_settings(root)
        LOGGER.info(
            "starting lark server root=%s remote=%s branch=%s process_name=%s",
            root,
            settings.remote,
            settings.branch,
            process_name,
        )
        lark_client = LarkReplyClient(settings)
        accumulator = MessageAccumulator()
        worker = Worker(
            JobProcessor(
                root,
                git=GitRunner(root, remote=settings.remote, branch=settings.branch),
                downloader=lark_client,
                ack_only=settings.ack_only,
            ),
            lark_client,
        )
        worker.start()
        lark_client.connect(
            lambda message: [worker.submit(block) for block in accumulator.ingest(message)]
        )
        LOGGER.info("lark websocket start returned; keeping server process alive")
        _sleep_forever()
    except Exception:
        LOGGER.exception("lark server crashed")
        raise


def configure_logging(root: Path) -> Path:
    log_dir = root / ".lark/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "server.log"
    logging.disable(logging.NOTSET)
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOGGER.setLevel(logging.INFO)
    LOGGER.disabled = False
    LOGGER.propagate = False
    LOGGER.addHandler(handler)
    return log_path


class LarkReplyClient:
    def __init__(self, settings: LarkSettings) -> None:
        self.settings = settings
        self._client: Any | None = None

    def reply(self, message_id: str | None, chat_id: str | None, text: str) -> None:
        if self._client is None:
            LOGGER.warning("skip lark reply because client is not initialized chat_id=%s", chat_id)
            return
        import lark_oapi as lark

        if message_id:
            request = (
                lark.BaseRequest.builder()
                .http_method(lark.HttpMethod.POST)
                .uri(f"/open-apis/im/v1/messages/{message_id}/reply")
                .token_types({lark.AccessTokenType.TENANT})
                .body(
                    {
                        "msg_type": "text",
                        "content": json.dumps({"text": text}, ensure_ascii=False),
                    }
                )
                .build()
            )
            response = self._client.request(request)
            if response.success():
                LOGGER.info("sent lark reply message_id=%s chat_id=%s", message_id, chat_id)
            else:
                LOGGER.error(
                    "failed to send lark reply message_id=%s chat_id=%s code=%s msg=%s",
                    message_id,
                    chat_id,
                    getattr(response, "code", ""),
                    getattr(response, "msg", ""),
                )
        else:
            LOGGER.warning("skip lark reply because message_id is empty chat_id=%s", chat_id)

    def download_file(self, file: IncomingFile, temp_dir: Path) -> Path:
        if self._client is None or not file.file_key:
            raise RuntimeError(f"cannot download file: {file.name}")
        import lark_oapi as lark

        message_id = file.message_id or ""
        request = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.GET)
            .uri(f"/open-apis/im/v1/messages/{message_id}/resources/{file.file_key}")
            .token_types({lark.AccessTokenType.TENANT})
            .queries([("type", "file")])
            .build()
        )
        response = self._client.request(request)
        if not response.success():
            raise RuntimeError(f"failed to download file {file.name}: {response.msg}")
        target = temp_dir / file.name
        target.write_bytes(response.raw.content)
        LOGGER.info("downloaded lark file name=%s target=%s", file.name, target)
        return target

    def connect(self, on_message: Any) -> None:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        from lark_oapi.ws import Client as WsClient

        self._client = (
            lark.Client.builder()
            .app_id(self.settings.app_id)
            .app_secret(self.settings.app_secret)
            .build()
        )

        def receive(data: P2ImMessageReceiveV1) -> None:
            try:
                LOGGER.info("received lark im.message event")
                LOGGER.info("lark event raw=%s", _safe_lark_json(lark, data))
                message = _incoming_from_lark_event(data)
                if message is not None:
                    LOGGER.info(
                        "parsed lark message chat_id=%s user_id=%s message_id=%s text=%r files=%s",
                        message.chat_id,
                        message.user_id,
                        message.message_id,
                        message.text[:200],
                        [file.name for file in message.files],
                    )
                    on_message(message)
                else:
                    LOGGER.warning("ignored lark event because it did not contain a message")
            except Exception:
                LOGGER.exception("failed to handle lark im.message event")

        handler = (
            lark.EventDispatcherHandler.builder("", "", lark.LogLevel.INFO)
            .register_p2_im_message_receive_v1(receive)
            .build()
        )
        ws_client = WsClient(
            self.settings.app_id,
            self.settings.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )
        LOGGER.info("connecting lark websocket")
        ws_client.start()


def _sleep_forever() -> None:
    while True:
        time.sleep(3600)


def _claude_debug_log_path(root: Path, purpose: Any, request_id: Any) -> Path:
    log_dir = root / ".lark/logs/claude"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = (
        f"{timestamp}-{_safe_filename_part(purpose, 'unknown')}-"
        f"{_safe_filename_part(request_id, uuid.uuid4().hex[:8])}.log"
    )
    return log_dir / filename


def _safe_filename_part(value: Any, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = default
    safe = "".join(char if char.isalnum() or char in "-_." else "-" for char in text)
    return safe.strip("-")[:80] or default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the KBManager Feishu/Lark server.")
    parser.add_argument("--root", default=os.getcwd(), help="KBManager workspace root")
    parser.add_argument("--process-name", default="", help="Process marker used by the daemon.")
    args = parser.parse_args(argv)
    run_server(Path(args.root).resolve(), process_name=args.process_name)
    return 0


def _source_input_path(
    block: MessageBlock,
    temp_dir: Path,
    downloader: FileDownloader | None = None,
) -> str:
    files = [
        file for file in block.files if Path(file.name).suffix.lower() in SUPPORTED_FILE_SUFFIXES
    ]
    if block.files and len(files) != len(block.files):
        unsupported = ", ".join(file.name for file in block.files if file not in files)
        raise ValueError(f"unsupported source file type: {unsupported}")
    if len(files) > 1:
        raise ValueError("source accepts one Markdown/PDF file per message block")
    if files:
        file = files[0]
        target = temp_dir / file.name
        if file.path is not None:
            shutil.copy2(file.path, target)
        elif downloader is not None:
            target = downloader.download_file(file, temp_dir)
        else:
            raise ValueError(f"source file is not available locally: {file.name}")
        return str(target)
    content = block.content.strip()
    if not content:
        raise ValueError("source content is empty")
    if _is_url(content):
        return content
    target = temp_dir / "input.md"
    target.write_text(content, encoding="utf-8")
    return str(target)


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://")) and " " not in value.strip()


def _llm_prompt_text(llm_request: dict[str, Any]) -> str:
    return (
        "Return only JSON matching the requested output schema.\n\n"
        f"LLM request:\n{json.dumps(llm_request, ensure_ascii=False, indent=2)}\n"
    )


def _llm_retry_request(
    llm_request: dict[str, Any],
    attempt: int,
    previous_llm_result: dict[str, Any],
    api_result: dict[str, Any],
) -> dict[str, Any]:
    retry_request = dict(llm_request)
    retry_request["retry_feedback"] = {
        "attempt": attempt,
        "instruction": (
            "The previous LLM output was rejected by the KBManager API. "
            "Use the API errors below to fix the output. Return only JSON, "
            "with no explanation and no Markdown fence. The JSON must still match "
            "the original output_schema and output_schema_definition. Only fix the "
            "invalid fields; do not change the original task goal, input paths, "
            "source or note references, evidence constraints, or review gate constraints."
        ),
        "previous_llm_result": previous_llm_result,
        "api_status": api_result.get("status"),
        "api_operation": api_result.get("operation"),
        "api_errors": api_result.get("errors") or [],
    }
    return retry_request


def _llm_parse_retry_request(
    llm_request: dict[str, Any],
    attempt: int,
    error: LlmOutputParseError,
) -> dict[str, Any]:
    retry_request = dict(llm_request)
    retry_request["retry_feedback"] = {
        "attempt": attempt,
        "instruction": (
            "The previous LLM output could not be parsed by the KBManager server. "
            "Use the parse error and raw output below to fix the output. Return only JSON, "
            "with no explanation and no Markdown fence. The JSON must still match "
            "the original output_schema and output_schema_definition. Only fix formatting "
            "or invalid structure; do not change the original task goal, input paths, "
            "source or note references, evidence constraints, or review gate constraints."
        ),
        "previous_raw_output": error.raw_output,
        "parse_error": str(error),
        "debug_log": str(error.debug_log),
    }
    return retry_request


def _parse_structured_output(output: str) -> dict[str, Any]:
    text = output.strip()
    candidates = [text, *_structured_output_candidates(text)]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return _parse_structured_output_candidate(candidate)
        except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("LLM output is empty")


def _parse_structured_output_candidate(text: str) -> dict[str, Any]:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM output must be a structured mapping")
    return parsed


def _structured_output_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    candidates.extend(match.group(1).strip() for match in JSON_FENCE_RE.finditer(text))
    json_object = _first_json_object(text)
    if json_object:
        candidates.append(json_object)
    return candidates


def _first_json_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].strip()
        start = text.find("{", start + 1)
    return None


def _raise_if_not_success(result: dict[str, Any], stage: str) -> None:
    if result.get("status") == ApiStatus.SUCCESS.value:
        return
    errors = result.get("errors") or []
    if errors and isinstance(errors[0], dict):
        raise RuntimeError(f"{stage} failed: {errors[0].get('message')}")
    raise RuntimeError(f"{stage} failed with status {result.get('status')}")


def _source_commit_message(source: dict[str, Any], candidate: dict[str, Any]) -> str:
    source_payload = source.get("source") if isinstance(source.get("source"), dict) else {}
    summary = _string(source_payload.get("summary"))
    ids = ", ".join(str(item) for item in candidate.get("candidate_ids", []))
    if summary:
        return summary[:100]
    if ids:
        return f"Add source candidates {ids}"
    return "Add source"


def _fallback_commit_message(job: Job) -> str:
    return f"Add {job.block.kind} from Lark {job.job_id}"


def _incoming_from_lark_event(data: Any) -> IncomingMessage | None:
    event = getattr(data, "event", None)
    message = getattr(event, "message", None)
    if message is None:
        LOGGER.warning("lark event has no message field event=%s", type(event).__name__)
        return None
    content = _message_text(getattr(message, "content", ""))
    files = _message_files(message, getattr(message, "content", ""))
    sender = getattr(event, "sender", None)
    sender_id = getattr(sender, "sender_id", None)
    return IncomingMessage(
        chat_id=_string(getattr(message, "chat_id", "")),
        user_id=(
            _string(getattr(sender_id, "open_id", ""))
            or _string(getattr(sender, "sender_id", ""))
        ),
        message_id=_string(getattr(message, "message_id", "")),
        text=content,
        files=files,
    )


def _message_files(message: Any, raw_content: Any) -> tuple[IncomingFile, ...]:
    message_type = _string(getattr(message, "message_type", ""))
    if message_type != "file":
        return ()
    payload = _json_object(raw_content)
    file_key = _string(payload.get("file_key"))
    name = _string(payload.get("file_name")) or _string(payload.get("name")) or file_key
    if not file_key or not name:
        return ()
    return (
        IncomingFile(
            name=name,
            file_key=file_key,
            message_id=_string(getattr(message, "message_id", "")),
        ),
    )


def _message_text(raw: Any) -> str:
    if isinstance(raw, str):
        payload = _json_object(raw)
        if isinstance(payload, dict):
            return _string(payload.get("text")) or raw
    return _string(raw)


def _safe_lark_json(lark: Any, data: Any) -> str:
    try:
        return lark.JSON.marshal(data)
    except Exception as exc:
        return f"<could not marshal event: {exc}>"


def _json_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _bool(value: Any, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


if __name__ == "__main__":
    raise SystemExit(main())
