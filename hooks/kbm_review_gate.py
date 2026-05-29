#!/usr/bin/env python3
"""Claude Code PreToolUse hook for KBManager review-gated writes."""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any

REVIEW_GATED_OPERATIONS = {
    "kb.source.deprecate": ("source_id",),
    "kb.candidate.defer": ("candidate_id",),
    "kb.knowledge.accept": ("candidate_id",),
    "kb.knowledge.reject": ("candidate_id",),
    "kb.knowledge.merge": ("candidate_id", "target_knowledge_id"),
    "kb.knowledge.deprecate": ("knowledge_id",),
    "kb.knowledgebase.create": ("knowledgebase_id", "title"),
    "kb.knowledgebase.outline.create": ("knowledgebase_id",),
    "kb.knowledgebase.outline.set_default": ("knowledgebase_id", "outline_id"),
    "kb.knowledgebase.outline.archive": ("knowledgebase_id", "outline_id"),
    "kb.note.deprecate": ("note_id",),
}


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = event.get("tool_input", {}).get("command")
    if not isinstance(command, str):
        return 0
    parsed = _parse_kbm_helper_call(command)
    if parsed is None:
        return 0
    operation, payload = parsed
    if operation not in REVIEW_GATED_OPERATIONS:
        return 0
    if payload is None:
        _print_decision(
            "deny",
            f"KBManager review-gated operation {operation} requires a JSON payload.",
        )
        return 0
    _print_decision("ask", _review_reason(operation, payload))
    return 0


def _parse_kbm_helper_call(command: str) -> tuple[str, dict[str, Any] | None] | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    script_index = None
    for index, token in enumerate(tokens):
        if token.endswith("/scripts/kbmanager_plugin.py") or token == "scripts/kbmanager_plugin.py":
            script_index = index
            break
    if script_index is None or script_index + 1 >= len(tokens):
        return None
    operation = tokens[script_index + 1]
    payload: dict[str, Any] | None = {}
    if script_index + 2 < len(tokens):
        raw_payload = tokens[script_index + 2]
        if not raw_payload.startswith("-"):
            try:
                loaded = json.loads(raw_payload)
            except json.JSONDecodeError:
                return operation, None
            if not isinstance(loaded, dict):
                return operation, None
            payload = loaded
    return operation, payload


def _review_reason(operation: str, payload: dict[str, Any]) -> str:
    keys = REVIEW_GATED_OPERATIONS[operation]
    parts = [f"{key}={payload[key]}" for key in keys if key in payload]
    summary = ", ".join(parts) if parts else "no object id in payload"
    return f"KBManager approval required for {operation}: {summary}"


def _print_decision(permission_decision: str, reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": permission_decision,
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
