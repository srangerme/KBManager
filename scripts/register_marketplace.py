#!/usr/bin/env python3
"""Register this Claude Code plugin in a local marketplace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKETPLACE_ROOT = Path("/home/sranger/codes/claude-code-marketplace")
MARKETPLACE_NAME = "sranger-marketplace"
PLUGIN_LINK = Path("plugins/kbm")
LEGACY_PLUGIN_NAMES = {"kbmanager"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _plugin_entry(repo_root: Path) -> dict[str, Any]:
    manifest = _read_json(repo_root / ".claude-plugin/plugin.json")
    return {
        "name": manifest["name"],
        "source": f"./{PLUGIN_LINK.as_posix()}",
        "description": manifest.get("description", ""),
        "version": manifest["version"],
        "author": manifest.get("author", {"name": "sranger"}),
        "category": "Productivity",
        "tags": manifest.get("keywords", ["claude-code"]),
    }


def register_plugin(marketplace_root: Path, repo_root: Path = REPO_ROOT) -> Path:
    marketplace_path = marketplace_root / ".claude-plugin/marketplace.json"
    plugin_link = marketplace_root / PLUGIN_LINK
    entry = _plugin_entry(repo_root)

    plugin_link.parent.mkdir(parents=True, exist_ok=True)
    if plugin_link.is_symlink() or not plugin_link.exists():
        if plugin_link.exists() or plugin_link.is_symlink():
            plugin_link.unlink()
        plugin_link.symlink_to(repo_root.resolve(), target_is_directory=True)
    elif plugin_link.resolve() != repo_root.resolve():
        raise SystemExit(f"{plugin_link} exists and does not point to {repo_root.resolve()}")

    if marketplace_path.exists():
        marketplace = _read_json(marketplace_path)
    else:
        marketplace = {
            "name": MARKETPLACE_NAME,
            "owner": {"name": "sranger"},
            "description": "Local Claude Code plugins by sranger.",
            "plugins": [],
        }

    marketplace["name"] = MARKETPLACE_NAME
    marketplace.setdefault("owner", {"name": "sranger"})
    marketplace.setdefault("description", "Local Claude Code plugins by sranger.")

    plugins = marketplace.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise SystemExit(f"{marketplace_path} field 'plugins' must be a list")

    removed_names = LEGACY_PLUGIN_NAMES | {entry["name"]}
    plugins[:] = [plugin for plugin in plugins if plugin.get("name") not in removed_names]
    plugins.append(entry)
    plugins.sort(key=lambda plugin: plugin["name"])

    _write_json(marketplace_path, marketplace)
    return marketplace_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register KBManager in a local Claude marketplace."
    )
    parser.add_argument(
        "--marketplace-root",
        type=Path,
        default=DEFAULT_MARKETPLACE_ROOT,
        help=f"Marketplace root directory. Defaults to {DEFAULT_MARKETPLACE_ROOT}.",
    )
    args = parser.parse_args()

    marketplace_path = register_plugin(args.marketplace_root)
    print(f"Registered kbm in {marketplace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
