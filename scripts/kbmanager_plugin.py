#!/usr/bin/env python3
"""Internal Claude Code plugin bridge for KBManager API calls.

This script is not a public CLI. It exists so plugin slash commands can invoke
the packaged Python API from Claude Code's Bash tool and receive stable JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _bootstrap_import_path() -> None:
    plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parents[1]))
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    candidates = [
        plugin_root / "src",
        plugin_root / "python",
    ]
    if project_dir:
        candidates.append(Path(project_dir) / "src")
    for candidate in candidates:
        if candidate.is_dir():
            sys.path.insert(0, str(candidate.resolve()))


def _operation_map() -> dict[str, Callable[..., Any]]:
    _bootstrap_import_path()
    from kbmanager import application

    return {
        "kb.init": application.init_workspace,
        "kb.source.add": application.source_add,
        "kb.source.deprecate": application.source_deprecate,
        "kb.candidate.create": application.candidate_create,
        "kb.candidate.get": application.candidate_get,
        "kb.candidate.next_pending": application.candidate_next_pending,
        "kb.candidate.defer": application.candidate_defer,
        "kb.knowledge.accept": application.knowledge_accept,
        "kb.knowledge.reject": application.knowledge_reject,
        "kb.knowledge.merge": application.knowledge_merge,
        "kb.knowledge.deprecate": application.knowledge_deprecate,
        "kb.knowledgebase.create": application.knowledgebase_create,
        "kb.knowledgebase.map": application.knowledgebase_map,
        "kb.note.add": application.note_add,
        "kb.note.get": application.note_get,
        "kb.note.deprecate": application.note_deprecate,
        "kb.index.rebuild": application.index_rebuild,
        "kb.clean.inspect": application.clean_inspect,
    }


def _load_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"payload must be valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("payload must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a KBManager API operation.")
    parser.add_argument("operation", help="Operation name, for example kb.init")
    parser.add_argument("payload", nargs="?", default="{}", help="JSON object of API keyword args")
    parser.add_argument(
        "--root",
        default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
        help="Workspace root. Defaults to CLAUDE_PROJECT_DIR or current directory.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    operations = _operation_map()
    if args.operation not in operations:
        valid = ", ".join(sorted(operations))
        raise SystemExit(f"unsupported operation: {args.operation}. Valid operations: {valid}")

    payload = _load_payload(args.payload)
    root = payload.pop("root", args.root)
    result = operations[args.operation](root, **payload)
    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
