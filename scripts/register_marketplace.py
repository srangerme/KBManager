#!/usr/bin/env python3
"""Register this Claude Code plugin in a local marketplace."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKETPLACE_ROOT = Path("/home/sranger/codes/claude-code-marketplace")
MARKETPLACE_NAME = "sranger-marketplace"
PLUGIN_LINK = Path("plugins/kbm")
LEGACY_PLUGIN_NAMES = {"kbmanager"}
PLUGIN_DIRS = (
    ".claude-plugin",
    "commands",
    "docs",
    "scripts",
    "skills",
    "src",
    "system-prompts",
)
PLUGIN_FILES = (
    "pyproject.toml",
)
COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
)


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


def _remove_existing_plugin_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _copy_plugin_files(source_root: Path, target_root: Path) -> None:
    _remove_existing_plugin_target(target_root)
    target_root.mkdir(parents=True)

    for relative_dir in PLUGIN_DIRS:
        source = source_root / relative_dir
        target = target_root / relative_dir
        if not source.is_dir():
            raise SystemExit(f"required plugin directory missing: {source}")
        shutil.copytree(source, target, ignore=COPY_IGNORE)

    for relative_file in PLUGIN_FILES:
        source = source_root / relative_file
        target = target_root / relative_file
        if not source.is_file():
            raise SystemExit(f"required plugin file missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def register_plugin(marketplace_root: Path, repo_root: Path = REPO_ROOT) -> Path:
    marketplace_path = marketplace_root / ".claude-plugin/marketplace.json"
    plugin_root = marketplace_root / PLUGIN_LINK
    entry = _plugin_entry(repo_root)

    plugin_root.parent.mkdir(parents=True, exist_ok=True)
    _copy_plugin_files(repo_root, plugin_root)

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
