from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kbmanager import lark_server


class FakeApiResult:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        return self.data


class FakeLlm:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def complete(self, llm_request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(llm_request)
        return {"ok": True}


class AttemptLlm:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def complete(self, llm_request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(llm_request)
        return {"attempt": len(self.requests)}


class ParseFailThenAttemptLlm:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.requests: list[dict[str, Any]] = []

    def complete(self, llm_request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(llm_request)
        if len(self.requests) <= self.failures:
            raise lark_server.LlmOutputParseError(
                "failed to parse claude output: bad json; debug log: debug.log",
                raw_output="not json",
                debug_log=Path("debug.log"),
            )
        return {"attempt": len(self.requests)}


class FakeDownloader:
    def download_file(self, file: lark_server.IncomingFile, temp_dir: Path) -> Path:
        target = temp_dir / file.name
        target.write_text("downloaded source", encoding="utf-8")
        return target


class FakeCompleted:
    returncode = 0
    stdout = '{"title": "Generated", "summary": "Done"}'
    stderr = ""


class FakeFailedCompleted:
    returncode = 1
    stdout = ""
    stderr = "claude failed"


class FakeTextCompleted:
    returncode = 0
    stdout = "Plain answer"
    stderr = ""


class FailingGit:
    def prepare(self, job_id: str) -> str | None:
        raise AssertionError("git should not run in ack-only mode")

    def commit_and_push(self, message: str) -> None:
        raise AssertionError("git should not run in ack-only mode")


def _needs_llm(operation: str, token: str) -> dict[str, Any]:
    return {
        "status": "needs_llm",
        "operation": operation,
        "objects": {"created": [], "updated": [], "deprecated": []},
        "diffs": [],
        "warnings": [],
        "errors": [],
        "review": {"required": False, "options": []},
        "next_actions": [],
        "llm_request": {"purpose": operation, "prompt": {"sections": []}},
        "resume": {"operation": operation, "token": token},
    }


def _success(operation: str, **extra: Any) -> dict[str, Any]:
    result = {
        "status": "success",
        "operation": operation,
        "objects": {"created": [], "updated": [], "deprecated": []},
        "diffs": [],
        "warnings": [],
        "errors": [],
        "review": {"required": False, "options": []},
        "next_actions": [],
    }
    result.update(extra)
    return result


def _failed(operation: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "operation": operation,
        "objects": {"created": [], "updated": [], "deprecated": []},
        "diffs": [],
        "warnings": [],
        "errors": [{"code": "invalid_llm_result", "message": message}],
        "review": {"required": False, "options": []},
        "next_actions": [],
    }


def test_message_accumulator_treats_plain_text_as_source() -> None:
    accumulator = lark_server.MessageAccumulator()

    blocks = accumulator.ingest(
        lark_server.IncomingMessage("chat", "user", "m1", " Plain source text ")
    )

    assert len(blocks) == 1
    assert blocks[0].kind == "source"
    assert blocks[0].content == "Plain source text"


def test_message_accumulator_treats_note_prefix_as_note() -> None:
    accumulator = lark_server.MessageAccumulator()

    blocks = accumulator.ingest(
        lark_server.IncomingMessage("chat", "user", "m1", " note Remember this. ")
    )

    assert len(blocks) == 1
    assert blocks[0].kind == "note"
    assert blocks[0].content == "Remember this."


def test_message_accumulator_note_prefix_is_case_insensitive() -> None:
    accumulator = lark_server.MessageAccumulator()

    blocks = accumulator.ingest(
        lark_server.IncomingMessage("chat", "user", "m1", "NOTE Remember this.")
    )

    assert len(blocks) == 1
    assert blocks[0].kind == "note"
    assert blocks[0].content == "Remember this."


def test_message_accumulator_treats_file_only_message_as_source() -> None:
    accumulator = lark_server.MessageAccumulator()
    file = lark_server.IncomingFile("paper.md", file_key="file-key")

    blocks = accumulator.ingest(
        lark_server.IncomingMessage("chat", "user", "m1", "", files=(file,))
    )

    assert len(blocks) == 1
    assert blocks[0].kind == "source"
    assert blocks[0].content == ""
    assert blocks[0].files == (file,)


def test_message_accumulator_ignores_empty_message_without_files() -> None:
    accumulator = lark_server.MessageAccumulator()

    assert accumulator.ingest(lark_server.IncomingMessage("chat", "user", "m1", "  ")) == []


def test_message_accumulator_no_longer_treats_slash_source_as_protocol() -> None:
    accumulator = lark_server.MessageAccumulator()

    blocks = accumulator.ingest(
        lark_server.IncomingMessage("chat", "user", "m1", "/source first line")
    )

    assert len(blocks) == 1
    assert blocks[0].kind == "source"
    assert blocks[0].content == "/source first line"


def test_message_accumulator_recognizes_lark_commands() -> None:
    accumulator = lark_server.MessageAccumulator()

    cases = {
        "help": ("help", ""),
        "view note-20260525-001": ("view", "note-20260525-001"),
        "list kb": ("list", "kb"),
        "ask what is here?": ("ask", "what is here?"),
    }

    for text, expected in cases.items():
        blocks = accumulator.ingest(lark_server.IncomingMessage("chat", "user", "m1", text))
        assert len(blocks) == 1
        assert (blocks[0].kind, blocks[0].content) == expected


def test_note_job_uses_needs_llm_resume(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def note_add(root: Path, **kwargs: Any) -> FakeApiResult:
        calls.append(kwargs)
        if "resume_token" not in kwargs:
            return FakeApiResult(_needs_llm("kb.note.add", "note-token"))
        return FakeApiResult(
            _success(
                "kb.note.add",
                note_id="note-20260522-001",
                note={"id": "note-20260522-001", "title": "Captured note"},
            )
        )

    monkeypatch.setattr(lark_server.application, "note_add", note_add)

    processor = lark_server.JobProcessor(tmp_path, llm=FakeLlm())
    result = processor.process(
        lark_server.Job(
            job_id="job1",
            block=lark_server.MessageBlock("note", "chat", "user", "m1", "Remember this."),
        )
    )

    assert result.success
    assert result.commit_message == "Captured note"
    assert result.object_ids == ("note-20260522-001",)
    assert calls[1]["resume_token"] == "note-token"


def test_note_job_retries_invalid_llm_result_with_feedback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    resume_attempts = 0

    def note_add(root: Path, **kwargs: Any) -> FakeApiResult:
        nonlocal resume_attempts
        if "resume_token" not in kwargs:
            return FakeApiResult(_needs_llm("kb.note.add", "note-token"))
        resume_attempts += 1
        if resume_attempts < 3:
            return FakeApiResult(_failed("kb.note.add", f"bad llm result {resume_attempts}"))
        return FakeApiResult(
            _success(
                "kb.note.add",
                note_id="note-20260522-001",
                note={"id": "note-20260522-001", "title": "Captured note"},
            )
        )

    monkeypatch.setattr(lark_server.application, "note_add", note_add)

    llm = AttemptLlm()
    processor = lark_server.JobProcessor(tmp_path, llm=llm)
    result = processor.process(
        lark_server.Job(
            job_id="job-retry",
            block=lark_server.MessageBlock("note", "chat", "user", "m1", "Remember this."),
        )
    )

    assert result.success
    assert len(llm.requests) == 3
    retry_feedback = llm.requests[1]["retry_feedback"]
    assert retry_feedback["previous_llm_result"] == {"attempt": 1}
    assert retry_feedback["api_errors"][0]["message"] == "bad llm result 1"
    assert "Return only JSON" in retry_feedback["instruction"]
    assert "output_schema" in retry_feedback["instruction"]
    assert llm.requests[2]["retry_feedback"]["previous_llm_result"] == {"attempt": 2}


def test_source_job_retries_candidate_llm_result(monkeypatch, tmp_path: Path) -> None:
    candidate_resume_attempts = 0

    def source_add(root: Path, **kwargs: Any) -> FakeApiResult:
        return FakeApiResult(
            _success(
                "kb.source.add",
                source_ids=["source-20260522-001"],
                source={"summary": "Useful source summary"},
            )
        )

    def candidate_create(root: Path, **kwargs: Any) -> FakeApiResult:
        nonlocal candidate_resume_attempts
        if "resume_token" not in kwargs:
            return FakeApiResult(_needs_llm("kb.candidate.create", "candidate-token"))
        candidate_resume_attempts += 1
        if candidate_resume_attempts == 1:
            return FakeApiResult(_failed("kb.candidate.create", "missing evidence"))
        return FakeApiResult(
            _success("kb.candidate.create", candidate_ids=["knowledge-20260522-001"])
        )

    monkeypatch.setattr(lark_server.application, "source_add", source_add)
    monkeypatch.setattr(lark_server.application, "candidate_create", candidate_create)

    llm = AttemptLlm()
    processor = lark_server.JobProcessor(tmp_path, llm=llm)
    result = processor.process(
        lark_server.Job(
            job_id="job-candidate-retry",
            block=lark_server.MessageBlock("source", "chat", "user", "m1", "Plain text source."),
        )
    )

    assert result.success
    assert len(llm.requests) == 2
    retry_feedback = llm.requests[1]["retry_feedback"]
    assert retry_feedback["api_operation"] == "kb.candidate.create"
    assert retry_feedback["api_errors"][0]["message"] == "missing evidence"
    assert "no Markdown fence" in retry_feedback["instruction"]


def test_llm_retry_stops_after_three_total_attempts(monkeypatch, tmp_path: Path) -> None:
    resume_attempts = 0

    def note_add(root: Path, **kwargs: Any) -> FakeApiResult:
        nonlocal resume_attempts
        if "resume_token" not in kwargs:
            return FakeApiResult(_needs_llm("kb.note.add", "note-token"))
        resume_attempts += 1
        return FakeApiResult(_failed("kb.note.add", f"bad llm result {resume_attempts}"))

    monkeypatch.setattr(lark_server.application, "note_add", note_add)

    llm = AttemptLlm()
    processor = lark_server.JobProcessor(tmp_path, llm=llm)
    result = processor.process(
        lark_server.Job(
            job_id="job-retry-exhausted",
            block=lark_server.MessageBlock("note", "chat", "user", "m1", "Remember this."),
        )
    )

    assert not result.success
    assert len(llm.requests) == 3
    assert resume_attempts == 3
    assert "bad llm result 3" in result.message


def test_note_job_retries_unparseable_llm_output_with_feedback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def note_add(root: Path, **kwargs: Any) -> FakeApiResult:
        calls.append(kwargs)
        if "resume_token" not in kwargs:
            return FakeApiResult(_needs_llm("kb.note.add", "note-token"))
        return FakeApiResult(
            _success(
                "kb.note.add",
                note_id="note-20260522-001",
                note={"id": "note-20260522-001", "title": "Captured note"},
            )
        )

    monkeypatch.setattr(lark_server.application, "note_add", note_add)

    llm = ParseFailThenAttemptLlm(failures=1)
    processor = lark_server.JobProcessor(tmp_path, llm=llm)
    result = processor.process(
        lark_server.Job(
            job_id="job-parse-retry",
            block=lark_server.MessageBlock("note", "chat", "user", "m1", "Remember this."),
        )
    )

    assert result.success
    assert len(llm.requests) == 2
    assert len(calls) == 2
    retry_feedback = llm.requests[1]["retry_feedback"]
    assert retry_feedback["previous_raw_output"] == "not json"
    assert "bad json" in retry_feedback["parse_error"]
    assert "Return only JSON" in retry_feedback["instruction"]
    assert "output_schema" in retry_feedback["instruction"]


def test_unparseable_llm_output_stops_after_three_total_attempts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    resume_attempts = 0

    def note_add(root: Path, **kwargs: Any) -> FakeApiResult:
        nonlocal resume_attempts
        if "resume_token" in kwargs:
            resume_attempts += 1
        return FakeApiResult(_needs_llm("kb.note.add", "note-token"))

    monkeypatch.setattr(lark_server.application, "note_add", note_add)

    llm = ParseFailThenAttemptLlm(failures=3)
    processor = lark_server.JobProcessor(tmp_path, llm=llm)
    result = processor.process(
        lark_server.Job(
            job_id="job-parse-exhausted",
            block=lark_server.MessageBlock("note", "chat", "user", "m1", "Remember this."),
        )
    )

    assert not result.success
    assert len(llm.requests) == 3
    assert resume_attempts == 0
    assert "failed to parse claude output" in result.message


def test_ack_only_job_skips_git_and_api(monkeypatch, tmp_path: Path) -> None:
    def note_add(root: Path, **kwargs: Any) -> FakeApiResult:
        raise AssertionError("api should not run in ack-only mode")

    monkeypatch.setattr(lark_server.application, "note_add", note_add)

    processor = lark_server.JobProcessor(tmp_path, git=FailingGit(), ack_only=True)
    result = processor.process(
        lark_server.Job(
            job_id="job-ack",
            block=lark_server.MessageBlock("note", "chat", "user", "m1", "Remember this."),
        )
    )

    assert result.success
    assert result.message == "note ack-only success"
    assert result.object_ids == ()


def test_ack_only_applies_to_lark_command(monkeypatch, tmp_path: Path) -> None:
    def read_text(path: Path, encoding: str = "utf-8") -> str:
        raise AssertionError("command should not read files in ack-only mode")

    monkeypatch.setattr(Path, "read_text", read_text)

    processor = lark_server.JobProcessor(tmp_path, git=FailingGit(), ack_only=True)
    result = processor.process(
        lark_server.Job(
            job_id="job-ack-help",
            block=lark_server.MessageBlock("help", "chat", "user", "m1", ""),
        )
    )

    assert result.success
    assert result.message == "help ack-only success"


def test_source_job_uses_tmp_input_and_cleans_it(monkeypatch, tmp_path: Path) -> None:
    seen_input_parent: Path | None = None
    seen_input_exists = False

    def source_add(root: Path, **kwargs: Any) -> FakeApiResult:
        nonlocal seen_input_parent, seen_input_exists
        input_path = kwargs["input_path"]
        if "resume_token" not in kwargs:
            seen_input_parent = Path(input_path).parent
            seen_input_exists = Path(input_path).is_file()
            return FakeApiResult(_needs_llm("kb.source.add", "source-token"))
        return FakeApiResult(
            _success(
                "kb.source.add",
                source_ids=["source-20260522-001"],
                source={"summary": "Useful source summary"},
            )
        )

    def candidate_create(root: Path, **kwargs: Any) -> FakeApiResult:
        if "resume_token" not in kwargs:
            return FakeApiResult(_needs_llm("kb.candidate.create", "candidate-token"))
        return FakeApiResult(
            _success("kb.candidate.create", candidate_ids=["knowledge-20260522-001"])
        )

    monkeypatch.setattr(lark_server.application, "source_add", source_add)
    monkeypatch.setattr(lark_server.application, "candidate_create", candidate_create)

    processor = lark_server.JobProcessor(tmp_path, llm=FakeLlm())
    result = processor.process(
        lark_server.Job(
            job_id="job2",
            block=lark_server.MessageBlock("source", "chat", "user", "m1", "Plain text source."),
        )
    )

    assert result.success
    assert seen_input_exists
    assert seen_input_parent is not None
    assert not seen_input_parent.exists()
    assert result.object_ids == ("source-20260522-001", "knowledge-20260522-001")


def test_source_job_downloads_lark_file_into_task_tmp(monkeypatch, tmp_path: Path) -> None:
    seen_input: Path | None = None

    def source_add(root: Path, **kwargs: Any) -> FakeApiResult:
        nonlocal seen_input
        input_path = kwargs["input_path"]
        if "resume_token" not in kwargs:
            seen_input = Path(input_path)
            return FakeApiResult(_needs_llm("kb.source.add", "source-token"))
        return FakeApiResult(
            _success(
                "kb.source.add",
                source_ids=["source-20260522-001"],
                source={"summary": "Downloaded file source"},
            )
        )

    def candidate_create(root: Path, **kwargs: Any) -> FakeApiResult:
        if "resume_token" not in kwargs:
            return FakeApiResult(_needs_llm("kb.candidate.create", "candidate-token"))
        return FakeApiResult(_success("kb.candidate.create", candidate_ids=[]))

    monkeypatch.setattr(lark_server.application, "source_add", source_add)
    monkeypatch.setattr(lark_server.application, "candidate_create", candidate_create)

    processor = lark_server.JobProcessor(tmp_path, llm=FakeLlm(), downloader=FakeDownloader())
    result = processor.process(
        lark_server.Job(
            job_id="job3",
            block=lark_server.MessageBlock(
                "source",
                "chat",
                "user",
                "m1",
                "",
                files=(lark_server.IncomingFile("paper.md", file_key="file-key"),),
            ),
        )
    )

    assert result.success
    assert seen_input is not None
    assert not seen_input.parent.exists()


def test_claude_cli_runs_in_workspace_with_bypass_permissions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def run(command: list[str], **kwargs: Any) -> FakeCompleted:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeCompleted()

    monkeypatch.setattr(lark_server.subprocess, "run", run)

    result = lark_server.ClaudeCliLlm(tmp_path).complete(
        {"id": "llm-1", "purpose": "note_title_summary", "prompt": {"sections": []}}
    )

    assert result == {"title": "Generated", "summary": "Done"}
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"]["input"].startswith("Return only JSON")
    assert captured["command"][:4] == [
        "claude",
        "-p",
        "--permission-mode",
        "bypassPermissions",
    ]
    assert "--add-dir" in captured["command"]
    assert str(tmp_path) in captured["command"]
    assert captured["command"][-1] == str(tmp_path)
    assert "--debug-file" in captured["command"]
    debug_file = Path(captured["command"][captured["command"].index("--debug-file") + 1])
    assert debug_file.parent == tmp_path / ".lark/logs/claude"
    assert debug_file.name.startswith("20")
    assert "note_title_summary" in debug_file.name
    assert "llm-1" in debug_file.name
    assert debug_file.parent.is_dir()


def test_claude_cli_failure_mentions_debug_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def run(command: list[str], **kwargs: Any) -> FakeFailedCompleted:
        return FakeFailedCompleted()

    monkeypatch.setattr(lark_server.subprocess, "run", run)

    try:
        lark_server.ClaudeCliLlm(tmp_path).complete(
            {"id": "llm-2", "purpose": "source_ingest", "prompt": {"sections": []}}
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected claude failure")

    assert "claude -p failed" in message
    assert "claude failed" in message
    assert str(tmp_path / ".lark/logs/claude") in message


def test_claude_cli_timeout_mentions_debug_log(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def run(command: list[str], **kwargs: Any) -> FakeCompleted:
        raise lark_server.subprocess.TimeoutExpired(command, timeout=1)

    monkeypatch.setattr(lark_server.subprocess, "run", run)

    try:
        lark_server.ClaudeCliLlm(tmp_path, timeout_seconds=1).complete(
            {"id": "llm-3", "purpose": "source_ingest", "prompt": {"sections": []}}
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected claude timeout")

    assert "claude -p timed out after 1s" in message
    assert str(tmp_path / ".lark/logs/claude") in message


def test_claude_text_cli_returns_plain_stdout_and_uses_read_only_prompt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def run(command: list[str], **kwargs: Any) -> FakeTextCompleted:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeTextCompleted()

    monkeypatch.setattr(lark_server.subprocess, "run", run)

    result = lark_server.ClaudeTextCli(tmp_path).complete("What do we know?")

    assert result == "Plain answer"
    prompt = captured["kwargs"]["input"]
    assert "不得创建、修改、删除、移动任何文件" in prompt
    assert "不得执行 git commit、git push" in prompt
    assert "不要触发任何 UI 确认" in prompt
    assert "What do we know?" in prompt
    assert not prompt.startswith("Return only JSON")
    assert captured["kwargs"]["cwd"] == tmp_path


def test_parse_structured_output_accepts_json_fence_with_surrounding_text() -> None:
    output = """I inspected the source.

```json
{"input_path": "1.pdf", "summary": "A source", "cleaned_content": "Cleaned"}
```
"""

    result = lark_server._parse_structured_output(output)

    assert result["input_path"] == "1.pdf"
    assert result["summary"] == "A source"


def test_parse_structured_output_accepts_embedded_json_object() -> None:
    output = (
        "Done:\n"
        '{"input_path": "1.pdf", "summary": "A source", "cleaned_content": "Cleaned"}'
        "\nNo further changes."
    )

    result = lark_server._parse_structured_output(output)

    assert result["input_path"] == "1.pdf"
    assert result["cleaned_content"] == "Cleaned"


def test_configure_logging_writes_to_lark_logs(tmp_path: Path) -> None:
    log_path = lark_server.configure_logging(tmp_path)

    lark_server.LOGGER.info("test log line")
    for handler in lark_server.LOGGER.handlers:
        handler.flush()

    assert log_path == tmp_path / ".lark/logs/server.log"
    assert "test log line" in log_path.read_text(encoding="utf-8")


class RecordingReplies:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.markdowns: list[str] = []
        self.files: list[Path] = []

    def reply(self, message_id: str | None, chat_id: str | None, text: str) -> None:
        self.texts.append(text)

    def reply_markdown(
        self,
        message_id: str | None,
        chat_id: str | None,
        markdown: str,
    ) -> None:
        self.markdowns.append(markdown)

    def send_file(self, message_id: str | None, chat_id: str | None, path: Path) -> None:
        self.files.append(path)


class FakeLarkResponse:
    def __init__(self, ok: bool, *, file_key: str = "", msg: str = "failed") -> None:
        self._ok = ok
        self.msg = msg
        self.data = {"file_key": file_key} if file_key else {}

    def success(self) -> bool:
        return self._ok


def test_worker_replies_to_help_synchronously(tmp_path: Path) -> None:
    replies = RecordingReplies()
    worker = lark_server.Worker(lark_server.JobProcessor(tmp_path), replies)

    job_id = worker.submit(lark_server.MessageBlock("help", "chat", "user", "m1", ""))

    assert job_id
    assert replies.texts == []
    assert len(replies.markdowns) == 1
    assert "view <id>" in replies.markdowns[0]
    assert replies.files == []
    assert worker.jobs.empty()


def test_worker_replies_to_list_with_markdown(tmp_path: Path) -> None:
    index = tmp_path / "indexes/note-index.md"
    index.parent.mkdir(parents=True)
    index.write_text("# Note Index\n\n| ID | Title |\n| --- | --- |\n", encoding="utf-8")
    replies = RecordingReplies()
    worker = lark_server.Worker(lark_server.JobProcessor(tmp_path), replies)

    worker.submit(lark_server.MessageBlock("list", "chat", "user", "m1", "note"))

    assert replies.texts == []
    assert replies.markdowns == ["# Note Index\n\n| ID | Title |\n| --- | --- |\n"]


def test_worker_queues_ask_with_specific_ack(tmp_path: Path) -> None:
    replies = RecordingReplies()
    worker = lark_server.Worker(lark_server.JobProcessor(tmp_path), replies)

    worker.submit(lark_server.MessageBlock("ask", "chat", "user", "m1", "Question?"))

    assert replies.texts == []
    assert len(replies.markdowns) == 1
    assert "正在生成回答" in replies.markdowns[0]
    assert not worker.jobs.empty()


def test_worker_replies_to_completed_ask_with_markdown(tmp_path: Path) -> None:
    class FakeAsk:
        def complete(self, question: str) -> str:
            return "# Answer\n\n- item"

    replies = RecordingReplies()
    processor = lark_server.JobProcessor(tmp_path, ask_llm=FakeAsk())
    worker = lark_server.Worker(processor, replies)
    worker.submit(lark_server.MessageBlock("ask", "chat", "user", "m1", "Question?"))

    job = worker.jobs.get_nowait()
    result = processor.process(job)
    worker._reply_result(job.job_id, job.block, result, include_prefix=True)

    assert replies.markdowns == [
        f"ask [{job.job_id}] 已收到，正在生成回答",
        f"ask [{job.job_id}]\n# Answer\n\n- item",
    ]


def test_list_command_reads_expected_indexes(tmp_path: Path) -> None:
    kb_index = tmp_path / "indexes/kb-index.md"
    kb_index.parent.mkdir(parents=True)
    kb_index.write_text("# KBs\n", encoding="utf-8")
    kb_detail = tmp_path / "indexes/knowledgebase/kb-20260525-001-knowledge-index.md"
    kb_detail.parent.mkdir(parents=True)
    kb_detail.write_text("# KB Detail\n", encoding="utf-8")
    note_index = tmp_path / "indexes/note-index.md"
    note_index.write_text("# Notes\n", encoding="utf-8")

    assert lark_server._list_text(tmp_path, "kb") == "# KBs\n"
    assert lark_server._list_text(tmp_path, "kb-20260525-001") == "# KB Detail\n"
    assert lark_server._list_text(tmp_path, "note") == "# Notes\n"


def test_view_markdown_object_returns_full_markdown(tmp_path: Path) -> None:
    note = tmp_path / "notes/inbox/note-20260525-001.md"
    note.parent.mkdir(parents=True)
    text = (
        "---\n"
        "id: note-20260525-001\n"
        "type: note\n"
        "title: Note\n"
        "status: inbox\n"
        "created: 2026-05-25T00:00:00\n"
        "updated: 2026-05-25T00:00:00\n"
        "---\n"
        "## Note\n"
        "Body\n"
    )
    note.write_text(text, encoding="utf-8")

    result, files = lark_server._view_object(tmp_path, "note-20260525-001")

    assert result == text
    assert files == ()


def test_view_pdf_source_returns_metadata_and_file(tmp_path: Path) -> None:
    pdf = tmp_path / "data/raw/pdf/source-20260525-001.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    meta = pdf.with_suffix(".meta.yml")
    meta.write_text(
        "id: source-20260525-001\n"
        "type: source\n"
        "title: PDF\n"
        "source_type: pdf\n"
        "status: raw\n"
        "path: data/raw/pdf/source-20260525-001.pdf\n"
        "created: 2026-05-25T00:00:00\n"
        "updated: 2026-05-25T00:00:00\n",
        encoding="utf-8",
    )

    result, files = lark_server._view_object(tmp_path, "source-20260525-001")

    assert "source-20260525-001" in result
    assert "data/raw/pdf/source-20260525-001.pdf" in result
    assert files == (pdf,)


def test_split_text_reply_chunks_long_text() -> None:
    text = "x" * (lark_server.LARK_TEXT_REPLY_LIMIT + 10)

    chunks = lark_server._split_text_reply(text)

    assert len(chunks) == 2
    assert "".join(chunks) == text


def test_markdown_to_lark_post_formats_headings_and_tables() -> None:
    post = lark_server._markdown_to_lark_post(
        "# Title\n\n| ID | Title | Status |\n| --- | --- | --- |\n| note-1 | First | inbox |\n"
    )

    assert post["zh_cn"]["title"] == "Title"
    content = post["zh_cn"]["content"]
    assert content[0][0]["text"] == "Title"
    assert "bold" in content[0][0]["style"]
    rendered = "\n".join(row[0].get("text", "") for row in content if row)
    assert "• note-1" in rendered
    assert "• Title: First" in rendered
    assert "• Status: inbox" in rendered


def test_expand_markdown_tables_uses_indented_bullets() -> None:
    expanded = lark_server._expand_markdown_tables(
        "# Notes\n\n| ID | Title | Status |\n| --- | --- | --- |\n| note-1 | First | inbox |\n"
    )

    assert expanded == "# Notes\n\n- note-1\n  - Title: First\n  - Status: inbox"


def test_lark_reply_client_reply_markdown_uses_post_and_falls_back_to_text() -> None:
    sent: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, request: Any) -> FakeLarkResponse:
            self.calls += 1
            sent.append({"uri": request.uri, "body": request.body})
            if self.calls == 1:
                return FakeLarkResponse(False, msg="post rejected")
            return FakeLarkResponse(True)

    client = lark_server.LarkReplyClient(lark_server.LarkSettings("app", "secret"))
    client._client = FakeClient()

    client.reply_markdown("message-id", "chat-id", "# Title\n\nBody")

    assert sent[0]["body"]["msg_type"] == "post"
    assert json.loads(sent[0]["body"]["content"])["zh_cn"]["title"] == "Title"
    assert sent[1]["body"]["msg_type"] == "text"
    assert json.loads(sent[1]["body"]["content"]) == {"text": "# Title\n\nBody"}


def test_lark_reply_client_plain_reply_also_uses_post() -> None:
    sent: list[dict[str, Any]] = []

    class FakeClient:
        def request(self, request: Any) -> FakeLarkResponse:
            sent.append({"uri": request.uri, "body": request.body})
            return FakeLarkResponse(True)

    client = lark_server.LarkReplyClient(lark_server.LarkSettings("app", "secret"))
    client._client = FakeClient()

    client.reply("message-id", "chat-id", "source [job] 已收到，正在处理")

    assert len(sent) == 1
    assert sent[0]["body"]["msg_type"] == "post"


def test_lark_reply_client_send_file_falls_back_to_chat(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []
    uploaded: list[dict[str, Any]] = []

    class FakeFileResource:
        def create(self, request: Any) -> FakeLarkResponse:
            body = request.body
            uploaded.append(
                {
                    "file_type": body.file_type,
                    "file_name": body.file_name,
                    "file_closed": body.file.closed,
                }
            )
            return FakeLarkResponse(True, file_key="file-key")

    class FakeV1:
        def __init__(self) -> None:
            self.file = FakeFileResource()

    class FakeIm:
        def __init__(self) -> None:
            self.v1 = FakeV1()

    class FakeClient:
        def __init__(self) -> None:
            self.im = FakeIm()

        def request(self, request: Any) -> FakeLarkResponse:
            sent.append(
                {
                    "uri": request.uri,
                    "queries": getattr(request, "queries", []),
                    "body": request.body,
                }
            )
            if request.uri.endswith("/reply"):
                return FakeLarkResponse(False, msg="reply file rejected")
            return FakeLarkResponse(True)

    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF")
    client = lark_server.LarkReplyClient(lark_server.LarkSettings("app", "secret"))
    client._client = FakeClient()

    client.send_file("message-id", "chat-id", path)

    assert [item["uri"] for item in sent] == [
        "/open-apis/im/v1/messages/message-id/reply",
        "/open-apis/im/v1/messages",
    ]
    assert uploaded == [
        {"file_type": "stream", "file_name": "report.pdf", "file_closed": False}
    ]
    assert sent[0]["body"]["msg_type"] == "file"
    assert sent[1]["body"]["receive_id"] == "chat-id"


def test_run_server_keeps_process_alive_after_connect_returns(monkeypatch, tmp_path: Path) -> None:
    settings_dir = tmp_path / ".lark"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        '{"app_id": "cli_x", "app_secret": "secret"}',
        encoding="utf-8",
    )
    slept = False

    class FakeClient:
        def __init__(self, settings: lark_server.LarkSettings) -> None:
            self.settings = settings

        def reply(self, message_id: str | None, chat_id: str | None, text: str) -> None:
            return

        def reply_markdown(
            self,
            message_id: str | None,
            chat_id: str | None,
            markdown: str,
        ) -> None:
            return

        def download_file(self, file: lark_server.IncomingFile, temp_dir: Path) -> Path:
            raise AssertionError("not used")

        def send_file(self, message_id: str | None, chat_id: str | None, path: Path) -> None:
            raise AssertionError("not used")

        def connect(self, on_message: Any) -> None:
            return

    def sleep_forever() -> None:
        nonlocal slept
        slept = True
        raise KeyboardInterrupt

    monkeypatch.setattr(lark_server, "LarkReplyClient", FakeClient)
    monkeypatch.setattr(lark_server, "_sleep_forever", sleep_forever)

    try:
        lark_server.run_server(tmp_path)
    except KeyboardInterrupt:
        pass

    assert slept


def test_load_settings_defaults_to_ack_only(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".lark"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        '{"app_id": "cli_x", "app_secret": "secret"}',
        encoding="utf-8",
    )

    settings = lark_server.load_settings(tmp_path)

    assert settings.ack_only is True


def test_lark_server_module_has_main_entrypoint() -> None:
    source = Path(lark_server.__file__).read_text(encoding="utf-8")

    assert 'if __name__ == "__main__"' in source
    assert "main()" in source
