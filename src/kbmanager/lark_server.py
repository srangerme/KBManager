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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from kbmanager import application
from kbmanager.contracts import ApiStatus
from kbmanager.repository import ObjectRepository
from kbmanager.workspace import Workspace

SUPPORTED_FILE_SUFFIXES = {".md", ".pdf"}
MAX_LLM_ATTEMPTS = 3
LARK_TEXT_REPLY_LIMIT = 3500
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
LOGGER = logging.getLogger(__name__)


class ReplyClient(Protocol):
    def reply(self, message_id: str | None, chat_id: str | None, text: str) -> None:
        """Reply to the source message or chat."""

    def reply_markdown(self, message_id: str | None, chat_id: str | None, markdown: str) -> None:
        """Reply with Markdown rendered as Feishu/Lark rich text."""

    def send_file(self, message_id: str | None, chat_id: str | None, path: Path) -> None:
        """Send a local file to the source message or chat."""


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
    files: tuple[Path, ...] = ()
    markdown: bool = False
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
        command = _parse_lark_command(text)
        if command is not None and not message.files:
            kind, content = command
        elif text.lower().startswith("note"):
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


class ClaudeTextCli:
    def __init__(self, root: Path, *, timeout_seconds: int = 600) -> None:
        self.root = root
        self.timeout_seconds = timeout_seconds

    def complete(self, question: str) -> str:
        debug_log = _claude_debug_log_path(self.root, "lark_ask", uuid.uuid4().hex[:8])
        prompt = _ask_prompt(question)
        LOGGER.info("running claude ask debug_log=%s", debug_log)
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
            raise RuntimeError(
                f"claude -p ask timed out after {self.timeout_seconds}s; debug log: {debug_log}"
            ) from exc
        elapsed = time.monotonic() - started
        LOGGER.info(
            "claude ask exited returncode=%s elapsed=%.2fs debug_log=%s",
            completed.returncode,
            elapsed,
            debug_log,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"claude -p ask failed: {detail}; debug log: {debug_log}")
        return completed.stdout.strip() or "(Claude Code returned an empty answer.)"


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
        ask_llm: ClaudeTextCli | None = None,
        git: GitRunner | None = None,
        downloader: FileDownloader | None = None,
        ack_only: bool = False,
    ) -> None:
        self.root = root
        self.llm = llm or ClaudeCliLlm(root)
        self.ask_llm = ask_llm or ClaudeTextCli(root)
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
            if job.block.kind in {"help", "list", "view", "ask"}:
                return self._process_command(job.block)
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

    def _process_command(self, block: MessageBlock) -> JobResult:
        try:
            if block.kind == "help":
                return JobResult(success=True, message=_help_text())
            if block.kind == "list":
                return JobResult(
                    success=True,
                    message=_list_text(self.root, block.content),
                    markdown=True,
                )
            if block.kind == "view":
                text, files = _view_object(self.root, block.content)
                return JobResult(success=True, message=text, files=files, markdown=True)
            if block.kind == "ask":
                question = block.content.strip()
                if not question:
                    raise ValueError("ask question is empty")
                return JobResult(
                    success=True,
                    message=self.ask_llm.complete(question),
                    markdown=True,
                )
        except Exception as exc:
            LOGGER.exception("command failed kind=%s", block.kind)
            return JobResult(success=False, message=str(exc))
        return JobResult(success=False, message=f"unsupported command: {block.kind}")

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
        if block.kind in {"help", "list", "view"}:
            LOGGER.info("processing sync command job_id=%s kind=%s", job_id, block.kind)
            result = self.processor.process(Job(job_id=job_id, block=block))
            self._reply_result(job_id, block, result, include_prefix=False)
            return job_id
        self.jobs.put(Job(job_id=job_id, block=block))
        LOGGER.info("queued job job_id=%s kind=%s chat_id=%s", job_id, block.kind, block.chat_id)
        self.replies.reply_markdown(
            block.message_id,
            block.chat_id,
            _queued_reply(block.kind, job_id),
        )
        return job_id

    def _reply_result(
        self,
        job_id: str,
        block: MessageBlock,
        result: JobResult,
        *,
        include_prefix: bool,
    ) -> None:
        prefix = f"{block.kind} [{job_id}]"
        if result.success:
            if block.kind in {"note", "source"}:
                ids = f"：{', '.join(result.object_ids)}" if result.object_ids else ""
                stash = f"\n已保留 stash：{result.stash_ref}" if result.stash_ref else ""
                text = f"{prefix} 已添加{ids}{stash}"
            else:
                text = f"{prefix}\n{result.message}" if include_prefix else result.message
            self.replies.reply_markdown(block.message_id, block.chat_id, text)
            for path in result.files:
                try:
                    self.replies.send_file(block.message_id, block.chat_id, path)
                except Exception as exc:
                    LOGGER.exception("failed to send result file path=%s", path)
                    self.replies.reply_markdown(
                        block.message_id,
                        block.chat_id,
                        f"文件发送失败：{path}\n{exc}",
                    )
        else:
            stash = f"\n已保留 stash：{result.stash_ref}" if result.stash_ref else ""
            text = f"{prefix} 失败：{result.message}{stash}" if include_prefix else result.message
            self.replies.reply_markdown(block.message_id, block.chat_id, text)

    def _run(self) -> None:
        while True:
            job = self.jobs.get()
            try:
                result = self.processor.process(job)
                LOGGER.info(
                    "job finished job_id=%s kind=%s success=%s",
                    job.job_id,
                    job.block.kind,
                    result.success,
                )
                self._reply_result(job.job_id, job.block, result, include_prefix=True)
            finally:
                self.jobs.task_done()


def _parse_lark_command(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    folded = stripped.casefold()
    if folded == "help":
        return ("help", "")
    for name in ("view", "list", "ask"):
        prefix = f"{name} "
        if folded.startswith(prefix):
            return (name, stripped[len(prefix) :].strip())
    return None


def _queued_reply(kind: str, job_id: str) -> str:
    if kind == "ask":
        return f"ask [{job_id}] 已收到，正在生成回答"
    return f"{kind} [{job_id}] 已收到，正在处理"


def _help_text() -> str:
    return """KBManager 飞书端命令：

help
  显示这份帮助。

view <id>
  查看对象内容。支持 note-*、knowledge-*、kb-*、source-*。
  source 是 PDF/HTML 时会同时尝试发送源文件。

list kb
  列出 knowledge base。

list <kb-id>
  列出指定 knowledge base 下的 knowledge，例如 list kb-20260525-001。

list note
  列出 note。

ask <question>
  让 Claude Code 基于当前用户侧 git 工作区回答问题。

其他文本默认按 source 导入；以 note 开头的文本按 note 添加。"""


def _list_text(root: Path, target: str) -> str:
    item = target.strip()
    if not item:
        raise ValueError("list requires a target: kb, <kb-id>, or note")
    folded = item.casefold()
    if folded == "kb":
        return _read_workspace_text(root, "indexes/kb-index.md")
    if folded == "note":
        return _read_workspace_text(root, "indexes/note-index.md")
    if item.startswith("kb-"):
        return _read_workspace_text(root, f"indexes/knowledgebase/{item}-knowledge-index.md")
    raise ValueError("list target must be kb, note, or a kb-* ID")


def _view_object(root: Path, object_id: str) -> tuple[str, tuple[Path, ...]]:
    item = object_id.strip()
    if not item:
        raise ValueError("view requires an object ID")
    workspace = Workspace(root)
    repository = ObjectRepository(workspace)
    record = _find_record(repository, item)
    if record.object_type not in {"note", "knowledge", "knowledge-base", "source"}:
        raise ValueError(f"view does not support object type: {record.object_type}")
    if record.path.suffix.lower() == ".md":
        return record.path.read_text(encoding="utf-8"), ()
    resource_path = _resource_for_meta_path(record.path)
    metadata_text = yaml.safe_dump(record.metadata, sort_keys=False, allow_unicode=True).rstrip()
    text = (
        f"# {record.object_id}\n\n"
        f"Source file: {workspace.relative(resource_path)}\n\n"
        "```yaml\n"
        f"{metadata_text}\n"
        "```"
    )
    return text, (resource_path,)


def _read_workspace_text(root: Path, relative_path: str) -> str:
    workspace = Workspace(root)
    path = workspace.resolve(relative_path)
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {relative_path}; run /kbm:check first")
    return path.read_text(encoding="utf-8")


def _find_record(repository: ObjectRepository, object_id: str) -> application.ObjectRecord:
    matches = [record for record in _records(repository) if record.object_id == object_id]
    if not matches:
        raise ValueError(f"object not found: {object_id}")
    if len(matches) > 1:
        paths = ", ".join(str(path.path) for path in matches)
        raise ValueError(f"duplicate object ID: {object_id}; {paths}")
    return matches[0]


def _records(repository: ObjectRepository) -> list[application.ObjectRecord]:
    records: list[application.ObjectRecord] = []
    for record in repository.iter_object_metadata():
        records.append(
            application.ObjectRecord(
                object_id=record.object_id,
                object_type=record.object_type,
                status=str(record.metadata.get("status", "")),
                path=record.path,
                metadata=record.metadata,
            )
        )
    return records


def _resource_for_meta_path(meta_path: Path) -> Path:
    if meta_path.parent.name in {"pdf", "html"}:
        suffix = f".{meta_path.parent.name}"
        return meta_path.with_name(meta_path.name.removesuffix(".meta.yml") + suffix)
    return meta_path.with_name(meta_path.name.removesuffix(".meta.yml"))


def _split_text_reply(text: str) -> list[str]:
    if len(text) <= LARK_TEXT_REPLY_LIMIT:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunk = remaining[:LARK_TEXT_REPLY_LIMIT]
        break_at = max(chunk.rfind("\n"), chunk.rfind(" "))
        if break_at > LARK_TEXT_REPLY_LIMIT // 2:
            chunk = remaining[:break_at]
        chunks.append(chunk)
        remaining = remaining[len(chunk) :].lstrip()
    return chunks


def _split_markdown_reply(markdown: str) -> list[str]:
    try:
        from lark_oapi.channel.outbound import split_with_code_fences
    except Exception:
        return _split_text_reply(markdown)
    return split_with_code_fences(markdown, limit=LARK_TEXT_REPLY_LIMIT) or [markdown]


def _markdown_to_lark_post(markdown: str) -> dict[str, Any]:
    markdown = _expand_markdown_tables(markdown)
    try:
        from lark_oapi.channel.outbound import markdown_to_post_ast
    except Exception:
        return {
            "zh_cn": {
                "title": _markdown_title(markdown),
                "content": [[{"tag": "text", "text": markdown}]],
            }
        }
    return markdown_to_post_ast(
        markdown,
        title=_markdown_title(markdown),
        table_mode="off",
        tag_md_mode="structured",
    )


def _expand_markdown_tables(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        if _is_markdown_table_start(lines, index):
            table_lines: list[str] = []
            while index < len(lines) and _is_markdown_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1
            output.extend(_table_to_indented_bullets(table_lines))
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output)


def _is_markdown_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return _is_markdown_table_row(lines[index]) and _is_markdown_table_separator(lines[index + 1])


def _is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_markdown_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _table_to_indented_bullets(lines: list[str]) -> list[str]:
    rows = [_table_cells(line) for line in lines]
    if len(rows) < 2:
        return lines
    headers = rows[0]
    body_rows = rows[2:]
    if not headers or not body_rows:
        return lines
    rendered: list[str] = []
    for row_index, row in enumerate(body_rows, start=1):
        primary = row[0] if row else ""
        rendered.append(f"- {primary or f'Row {row_index}'}")
        for column_index, header in enumerate(headers):
            if column_index == 0:
                continue
            value = row[column_index] if column_index < len(row) else ""
            rendered.append(f"  - {header}: {value}")
        rendered.append("")
    while rendered and rendered[-1] == "":
        rendered.pop()
    return rendered


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _markdown_title(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title[:80]
    return ""


def _ask_prompt(question: str) -> str:
    return f"""你是运行在用户侧 git 工作区中的 KBManager 飞书问答助手。

回答用户问题时遵守以下规则：
- 可以读取当前工作区中的文件来回答问题。
- 不得创建、修改、删除、移动任何文件。
- 不得运行会修改状态的命令。
- 不得执行 git commit、git push 或其他提交/推送操作。
- 如果需要用户确认、选择或澄清，不要触发任何 UI 确认；把需要确认的问题作为最终文本回复。
- 返回普通文本；不要返回 JSON；不要用 Markdown fence 包裹整个答案。

用户问题：
{question}
"""


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
        self.reply_markdown(message_id, chat_id, text)

    def reply_markdown(self, message_id: str | None, chat_id: str | None, markdown: str) -> None:
        for chunk in _split_markdown_reply(markdown):
            if not self._reply_markdown_chunk(message_id, chat_id, chunk):
                self._reply_chunk(message_id, chat_id, chunk)

    def _reply_chunk(self, message_id: str | None, chat_id: str | None, text: str) -> None:
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

    def _reply_markdown_chunk(
        self,
        message_id: str | None,
        chat_id: str | None,
        markdown: str,
    ) -> bool:
        if self._client is None:
            LOGGER.warning(
                "skip lark markdown reply because client is not initialized chat_id=%s",
                chat_id,
            )
            return True
        if not message_id:
            LOGGER.warning(
                "skip lark markdown reply because message_id is empty chat_id=%s",
                chat_id,
            )
            return False
        import lark_oapi as lark

        post = _markdown_to_lark_post(markdown)
        request = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.POST)
            .uri(f"/open-apis/im/v1/messages/{message_id}/reply")
            .token_types({lark.AccessTokenType.TENANT})
            .body(
                {
                    "msg_type": "post",
                    "content": json.dumps(post, ensure_ascii=False),
                }
            )
            .build()
        )
        response = self._client.request(request)
        if response.success():
            LOGGER.info("sent lark markdown reply message_id=%s chat_id=%s", message_id, chat_id)
            return True
        LOGGER.warning(
            "failed to send lark markdown reply; fallback to text message_id=%s chat_id=%s msg=%s",
            message_id,
            chat_id,
            getattr(response, "msg", ""),
        )
        return False

    def send_file(self, message_id: str | None, chat_id: str | None, path: Path) -> None:
        if self._client is None:
            raise RuntimeError("cannot send file because lark client is not initialized")
        import lark_oapi as lark

        file_key = self._upload_file(lark, path)
        if message_id and self._send_file_reply(lark, message_id, chat_id, file_key):
            return
        if not chat_id:
            raise RuntimeError("cannot send file without chat_id")
        request = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.POST)
            .uri("/open-apis/im/v1/messages")
            .token_types({lark.AccessTokenType.TENANT})
            .queries([("receive_id_type", "chat_id")])
            .body(
                {
                    "receive_id": chat_id,
                    "msg_type": "file",
                    "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
                }
            )
            .build()
        )
        response = self._client.request(request)
        if not response.success():
            raise RuntimeError(f"failed to send file to chat: {response.msg}")

    def _upload_file(self, lark: Any, path: Path) -> str:
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        with path.open("rb") as file:
            request = (
                CreateFileRequest.builder()
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type("stream")
                    .file_name(path.name)
                    .file(file)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.file.create(request)
        if not response.success():
            raise RuntimeError(f"failed to upload file {path}: {response.msg}")
        data = getattr(response, "data", None)
        file_key = _string(getattr(data, "file_key", "")) if data is not None else ""
        if not file_key and isinstance(data, dict):
            file_key = _string(data.get("file_key"))
        if not file_key:
            raise RuntimeError(f"file upload response had no file_key: {path}")
        return file_key

    def _send_file_reply(
        self,
        lark: Any,
        message_id: str,
        chat_id: str | None,
        file_key: str,
    ) -> bool:
        request = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.POST)
            .uri(f"/open-apis/im/v1/messages/{message_id}/reply")
            .token_types({lark.AccessTokenType.TENANT})
            .body(
                {
                    "msg_type": "file",
                    "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
                }
            )
            .build()
        )
        response = self._client.request(request)
        if response.success():
            LOGGER.info("sent lark file reply message_id=%s chat_id=%s", message_id, chat_id)
            return True
        LOGGER.warning(
            "failed to send lark file reply; fallback to chat message_id=%s chat_id=%s msg=%s",
            message_id,
            chat_id,
            getattr(response, "msg", ""),
        )
        return False

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
