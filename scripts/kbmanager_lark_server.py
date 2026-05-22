#!/usr/bin/env python3
"""Claude Code plugin bridge for the KBManager Feishu/Lark server daemon."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap_import_path() -> None:
    plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parents[1]))
    for candidate in (plugin_root / "src", plugin_root / "python"):
        if candidate.is_dir():
            sys.path.insert(0, str(candidate.resolve()))


def main(argv: list[str] | None = None) -> int:
    _bootstrap_import_path()
    from kbmanager import lark_server_daemon

    return lark_server_daemon.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
