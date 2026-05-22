"""Detached process manager for the KBManager Feishu/Lark server."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROCESS_PREFIX = "kbmanager-lark-server"
STOP_TIMEOUT_SECONDS = 5.0
START_CHECK_SECONDS = 0.5


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str


def process_marker(root: str | Path) -> str:
    resolved = str(Path(root).resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return f"{PROCESS_PREFIX}:{digest}"


def start(root: str | Path) -> dict[str, Any]:
    workspace = Path(root).resolve()
    marker = process_marker(workspace)
    log_path = _log_path(workspace)
    pid_path = _pid_path(workspace)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    stopped = _stop_marker(marker)
    _remove_stale_pid(pid_path)

    env = os.environ.copy()
    env["PYTHONPATH"] = _child_pythonpath()
    command = [
        sys.executable,
        "-u",
        "-m",
        "kbmanager.lark_server",
        "--root",
        str(workspace),
        "--process-name",
        marker,
    ]
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[daemon] starting {' '.join(command)}\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
    time.sleep(START_CHECK_SECONDS)
    return_code = process.poll()
    if return_code is not None:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"[daemon] child exited during startup returncode={return_code}\n")
        return {
            "status": "failed",
            "pid": process.pid,
            "returncode": return_code,
            "process_name": marker,
            "stopped_pids": [item.pid for item in stopped],
            "pid_path": str(pid_path),
            "log_path": str(log_path),
        }
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    return {
        "status": "started",
        "pid": process.pid,
        "process_name": marker,
        "stopped_pids": [item.pid for item in stopped],
        "pid_path": str(pid_path),
        "log_path": str(log_path),
    }


def stop(root: str | Path) -> dict[str, Any]:
    workspace = Path(root).resolve()
    marker = process_marker(workspace)
    stopped = _stop_marker(marker)
    pid_path = _pid_path(workspace)
    if pid_path.exists():
        pid_path.unlink()
    return {
        "status": "stopped",
        "process_name": marker,
        "stopped_pids": [item.pid for item in stopped],
        "pid_path": str(pid_path),
        "log_path": str(_log_path(workspace)),
    }


def status(root: str | Path) -> dict[str, Any]:
    workspace = Path(root).resolve()
    marker = process_marker(workspace)
    processes = find_processes(marker)
    pid_path = _pid_path(workspace)
    pid_file = pid_path.read_text(encoding="utf-8").strip() if pid_path.is_file() else None
    return {
        "status": "running" if processes else "stopped",
        "running": bool(processes),
        "process_name": marker,
        "pids": [item.pid for item in processes],
        "pid_file": pid_file,
        "pid_path": str(pid_path),
        "log_path": str(_log_path(workspace)),
        "settings_path": str(workspace / ".lark/settings.json"),
    }


def find_processes(marker: str) -> list[ProcessInfo]:
    completed = subprocess.run(
        ["ps", "-eo", "pid=,args="],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    current_pid = os.getpid()
    parent_pid = os.getppid()
    matches: list[ProcessInfo] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid in {current_pid, parent_pid}:
            continue
        if (
            marker in command
            and "kbmanager.lark_server_daemon" not in command
            and "kbmanager.lark_server" in command
        ):
            matches.append(ProcessInfo(pid=pid, command=command))
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the KBManager Feishu/Lark server.")
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument(
        "--root",
        default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
        help="KBManager workspace root.",
    )
    args = parser.parse_args(argv)

    actions = {"start": start, "stop": stop, "status": status}
    result = actions[args.action](args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False))
    return 0


def _stop_marker(marker: str) -> list[ProcessInfo]:
    processes = find_processes(marker)
    for process in processes:
        _signal_process(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not find_processes(marker):
            return processes
        time.sleep(0.1)
    for process in find_processes(marker):
        _signal_process(process.pid, signal.SIGKILL)
    return processes


def _signal_process(pid: int, sig: signal.Signals) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return


def _remove_stale_pid(pid_path: Path) -> None:
    if pid_path.exists():
        pid_path.unlink()


def _pid_path(root: Path) -> Path:
    return root / ".lark/server.pid"


def _log_path(root: Path) -> Path:
    return root / ".lark/logs/server.log"


def _child_pythonpath() -> str:
    package_root = Path(__file__).resolve().parents[2]
    candidates = [package_root / "src", package_root / "python", package_root]
    entries = [str(path.resolve()) for path in candidates if path.is_dir()]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        entries.append(existing)
    return os.pathsep.join(entries)


if __name__ == "__main__":
    raise SystemExit(main())
