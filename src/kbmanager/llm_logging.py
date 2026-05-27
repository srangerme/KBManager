"""Workspace-local LLM input/output logging."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_llm_log(
    root: str | Path,
    *,
    purpose: str | None,
    input_payload: Any,
    output_payload: Any | None = None,
    error: str | None = None,
) -> Path:
    """Write one LLM call record under ``.claude/log`` and return its path."""

    workspace = Path(root)
    log_dir = workspace / ".claude" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    filename = f"{timestamp}-{_safe_filename_part(purpose, 'llm')}-{uuid.uuid4().hex[:8]}.json"
    path = log_dir / filename
    record: dict[str, Any] = {
        "timestamp": timestamp,
        "purpose": purpose,
        "input": _jsonable(input_payload),
        "output": _jsonable(output_payload),
    }
    if error is not None:
        record["error"] = error
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def monotonic_call_id() -> str:
    """Return a short unique ID suitable for correlating related log records."""

    return f"{time.monotonic_ns()}-{uuid.uuid4().hex[:8]}"


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_jsonable(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return repr(value)
    return value


def _safe_filename_part(value: Any, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = default
    safe = "".join(char if char.isalnum() or char in "-_." else "-" for char in text)
    return safe.strip("-")[:80] or default
