#!/usr/bin/env python3
"""Claude Code PreToolUse hook for KBManager review-gated writes."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
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
            f"KBManager review-gated operation {operation} requires a valid JSON payload file.",
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
    payload: dict[str, Any] | None = None
    if script_index + 2 < len(tokens):
        payload_file = tokens[script_index + 2]
        if not payload_file.startswith("-"):
            payload = _load_payload_file(Path(payload_file))
    return operation, payload


def _load_payload_file(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _review_reason(operation: str, payload: dict[str, Any]) -> str:
    keys = REVIEW_GATED_OPERATIONS[operation]
    parts = [f"{key}={payload[key]}" for key in keys if key in payload]
    summary = ", ".join(parts) if parts else "no object id in payload"
    if operation == "kb.knowledgebase.create":
        return _knowledgebase_create_review_reason(operation, summary, payload)
    formatted_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        f"KBManager approval required for {operation}: {summary}\n\n"
        f"Payload:\n```json\n{formatted_payload}\n```"
    )


def _knowledgebase_create_review_reason(
    operation: str,
    summary: str,
    payload: dict[str, Any],
) -> str:
    lines = [
        f"KBManager approval required for {operation}: {summary}",
        "",
        "## Knowledgebase",
        f"- Title: {_display_value(payload.get('title'))}",
    ]
    if payload.get("knowledgebase_id") is not None:
        lines.append(f"- Knowledgebase ID: {_display_value(payload.get('knowledgebase_id'))}")
    lines.extend(
        [
            f"- Description: {_display_value(payload.get('description'))}",
            f"- Tags: {_display_list(payload.get('tags'))}",
            f"- Scope includes: {_display_list(_scope_list(payload, 'includes'))}",
            f"- Scope excludes: {_display_list(_scope_list(payload, 'excludes'))}",
            f"- Default outline: {_display_value(payload.get('default_outline_id'))}",
            "",
            "## Outlines",
        ]
    )
    outlines = payload.get("outlines")
    if not isinstance(outlines, list) or not outlines:
        lines.append("- (no outlines)")
        return "\n".join(lines)
    for outline in outlines:
        if not isinstance(outline, dict):
            lines.append("- (invalid outline)")
            continue
        title = _display_value(outline.get("title"))
        status = _display_value(outline.get("status", "active"))
        lines.append(f"- {title} ({status})")
        nodes = outline.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            lines.append("  - (no nodes)")
            continue
        lines.extend(_outline_node_title_lines(nodes, indent=2))
    return "\n".join(lines)


def _outline_node_title_lines(nodes: list[Any], *, indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for node in nodes:
        if not isinstance(node, dict):
            lines.append(f"{prefix}- (untitled node)")
            continue
        title = node.get("title")
        label = title.strip() if isinstance(title, str) and title.strip() else "(untitled node)"
        lines.append(f"{prefix}- {label}")
        children = node.get("children")
        if isinstance(children, list) and children:
            lines.extend(_outline_node_title_lines(children, indent=indent + 2))
    return lines


def _scope_list(payload: dict[str, Any], key: str) -> Any:
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        return None
    return scope.get(key)


def _display_list(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "(none)"
    return ", ".join(_display_value(item) for item in value)


def _display_value(value: Any) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return value.strip() or "(none)"
    return str(value)


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
