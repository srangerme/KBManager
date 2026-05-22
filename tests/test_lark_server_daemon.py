from __future__ import annotations

from pathlib import Path
from typing import Any

from kbmanager import lark_server_daemon as daemon


class FakeCompleted:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class FakePopen:
    def __init__(self, pid: int = 4321, returncode: int | None = None) -> None:
        self.pid = pid
        self._returncode = returncode

    def poll(self) -> int | None:
        return self._returncode


def test_process_marker_is_workspace_specific(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()

    assert daemon.process_marker(tmp_path).startswith("kbmanager-lark-server:")
    assert daemon.process_marker(tmp_path) != daemon.process_marker(other)


def test_find_processes_matches_marker_and_server_module(monkeypatch) -> None:
    marker = "kbmanager-lark-server:abc"
    output = f"""
      111 python3 -m kbmanager.lark_server --process-name {marker}
      112 python3 -m kbmanager.lark_server --process-name other
      113 python3 -m kbmanager.lark_server_daemon start --process-name {marker}
      114 grep {marker}
    """

    def run(command: list[str], **kwargs: Any) -> FakeCompleted:
        assert command == ["ps", "-eo", "pid=,args="]
        return FakeCompleted(output)

    monkeypatch.setattr(daemon.subprocess, "run", run)
    monkeypatch.setattr(daemon.os, "getpid", lambda: 999)
    monkeypatch.setattr(daemon.os, "getppid", lambda: 998)

    assert [item.pid for item in daemon.find_processes(marker)] == [111]


def test_start_stops_existing_process_and_writes_pid(monkeypatch, tmp_path: Path) -> None:
    marker = daemon.process_marker(tmp_path)
    ps_outputs = [
        f"111 python3 -m kbmanager.lark_server --process-name {marker}\n",
        "",
    ]
    killed: list[tuple[int, int]] = []
    popen_calls: list[dict[str, Any]] = []

    def run(command: list[str], **kwargs: Any) -> FakeCompleted:
        return FakeCompleted(ps_outputs.pop(0) if ps_outputs else "")

    def kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))

    def popen(command: list[str], **kwargs: Any) -> FakePopen:
        popen_calls.append({"command": command, "kwargs": kwargs})
        return FakePopen(222)

    monkeypatch.setattr(daemon.subprocess, "run", run)
    monkeypatch.setattr(daemon.os, "kill", kill)
    monkeypatch.setattr(daemon.subprocess, "Popen", popen)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)

    result = daemon.start(tmp_path)

    assert result["pid"] == 222
    assert result["stopped_pids"] == [111]
    assert killed[0][0] == 111
    assert (tmp_path / ".lark/server.pid").read_text(encoding="utf-8") == "222\n"
    assert "--process-name" in popen_calls[0]["command"]
    assert marker in popen_calls[0]["command"]
    assert popen_calls[0]["kwargs"]["start_new_session"] is True
    assert (tmp_path / ".lark/logs/server.log").is_file()


def test_start_reports_failed_when_child_exits_immediately(monkeypatch, tmp_path: Path) -> None:
    def run(command: list[str], **kwargs: Any) -> FakeCompleted:
        return FakeCompleted("")

    def popen(command: list[str], **kwargs: Any) -> FakePopen:
        return FakePopen(222, returncode=1)

    monkeypatch.setattr(daemon.subprocess, "run", run)
    monkeypatch.setattr(daemon.subprocess, "Popen", popen)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)

    result = daemon.start(tmp_path)

    assert result["status"] == "failed"
    assert result["returncode"] == 1
    assert not (tmp_path / ".lark/server.pid").exists()


def test_stop_uses_process_scan_not_only_pid_file(monkeypatch, tmp_path: Path) -> None:
    marker = daemon.process_marker(tmp_path)
    (tmp_path / ".lark").mkdir()
    (tmp_path / ".lark/server.pid").write_text("999\n", encoding="utf-8")
    ps_outputs = [
        f"111 python3 -m kbmanager.lark_server --process-name {marker}\n",
        "",
    ]
    killed: list[int] = []

    def run(command: list[str], **kwargs: Any) -> FakeCompleted:
        return FakeCompleted(ps_outputs.pop(0) if ps_outputs else "")

    monkeypatch.setattr(daemon.subprocess, "run", run)
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: killed.append(pid))

    result = daemon.stop(tmp_path)

    assert result["stopped_pids"] == [111]
    assert killed == [111]
    assert not (tmp_path / ".lark/server.pid").exists()


def test_status_uses_process_scan_and_reports_stale_pid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    marker = daemon.process_marker(tmp_path)
    (tmp_path / ".lark").mkdir()
    (tmp_path / ".lark/server.pid").write_text("999\n", encoding="utf-8")

    def run(command: list[str], **kwargs: Any) -> FakeCompleted:
        return FakeCompleted(f"111 python3 -m kbmanager.lark_server --process-name {marker}\n")

    monkeypatch.setattr(daemon.subprocess, "run", run)

    result = daemon.status(tmp_path)

    assert result["running"] is True
    assert result["pids"] == [111]
    assert result["pid_file"] == "999"
