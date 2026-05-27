from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND_DIR = REPO_ROOT / "commands"


def test_claude_plugin_manifest_is_valid_json() -> None:
    manifest = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text())

    assert manifest["name"] == "kbm"
    assert manifest["commands"] == "./commands/"
    assert manifest["skills"] == "./skills/"


def test_claude_plugin_exposes_only_ask_command() -> None:
    assert {path.name for path in COMMAND_DIR.glob("*.md")} == {"ask.md"}

    command = (COMMAND_DIR / "ask.md").read_text(encoding="utf-8")
    assert "only KBManager\nslash command" in command
    assert "scripts/kbmanager_plugin.py" in command
    assert "entrypoint" in command
    assert "dry_run" in command


def test_claude_plugin_packages_kbm_skills() -> None:
    skill_names = {path.name for path in (REPO_ROOT / "skills").iterdir() if path.is_dir()}

    assert skill_names == {
        "kbm-api-ui",
        "kbm-basic",
        "kbm-candidate-workflows",
        "kbm-kb-outline-workflows",
        "kbm-knowledgebase-workflows",
        "kbm-maintenance-workflows",
        "kbm-note-workflows",
        "kbm-research-on",
        "kbm-source-workflows",
    }
    for name in skill_names:
        text = (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert f"name: {name}" in text
        assert "description:" in text


def test_register_marketplace_script_adds_current_plugin(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import register_marketplace

    marketplace_path = register_marketplace.register_plugin(tmp_path)
    marketplace = json.loads(marketplace_path.read_text())
    plugin = marketplace["plugins"][0]
    manifest = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text())

    assert marketplace["name"] == "sranger-marketplace"
    assert plugin["name"] == "kbm"
    assert plugin["source"] == "./plugins/kbm"
    assert plugin["version"] == manifest["version"]
    assert (tmp_path / "plugins/kbm").resolve() == REPO_ROOT


def test_register_marketplace_script_replaces_existing_plugin(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import register_marketplace

    register_marketplace.register_plugin(tmp_path)
    register_marketplace.register_plugin(tmp_path)

    marketplace = json.loads((tmp_path / ".claude-plugin/marketplace.json").read_text())
    plugins = [plugin for plugin in marketplace["plugins"] if plugin["name"] == "kbm"]
    assert len(plugins) == 1


def test_register_marketplace_script_removes_legacy_plugin_alias(tmp_path: Path) -> None:
    marketplace_path = tmp_path / ".claude-plugin/marketplace.json"
    marketplace_path.parent.mkdir(parents=True)
    marketplace_path.write_text(
        json.dumps(
            {
                "name": "sranger-marketplace",
                "plugins": [
                    {
                        "name": "kbmanager",
                        "source": "./plugins/kbmanager",
                        "version": "0.1.7",
                    }
                ],
            }
        )
    )

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import register_marketplace

    register_marketplace.register_plugin(tmp_path)

    marketplace = json.loads(marketplace_path.read_text())
    assert [plugin["name"] for plugin in marketplace["plugins"]] == ["kbm"]


def test_command_api_operations_are_supported_by_plugin_helper() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import kbmanager_plugin

    supported = set(kbmanager_plugin._operation_map())
    command = (COMMAND_DIR / "ask.md").read_text(encoding="utf-8")

    for operation in {
        "kb.init",
        "kb.source.add",
        "kb.candidate.create",
        "kb.note.add",
        "kb.index.rebuild",
        "kb.clean.inspect",
    }:
        assert operation in supported
    assert "kb.*" in command


def test_claude_plugin_package_does_not_contain_user_data_roots() -> None:
    forbidden = {".lark", "data", "knowledge", "candidates", "notes", "indexes"}

    for name in forbidden:
        assert not (REPO_ROOT / name).exists()


def test_plugin_helper_invokes_api_with_project_dir(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/kbmanager_plugin.py"),
            "kb.init",
            '{"entrypoint": "claude_code", "dry_run": true}',
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    result = json.loads(completed.stdout)
    assert result["status"] == "success"
    assert result["operation"] == "kb.init"
    assert not (tmp_path / "data").exists()


def test_plugin_helper_does_not_inject_missing_api_contract(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/kbmanager_plugin.py"),
            "kb.init",
            "{}",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    result = json.loads(completed.stdout)
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "missing_entrypoint"


def test_plugin_helper_does_not_import_kbmanager_from_project_dir(tmp_path: Path) -> None:
    project_src = tmp_path / "src/kbmanager"
    project_src.mkdir(parents=True)
    (project_src / "__init__.py").write_text(
        "raise RuntimeError('project kbmanager must not be imported')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/kbmanager_plugin.py"),
            "kb.init",
            '{"entrypoint": "claude_code", "dry_run": true}',
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    result = json.loads(completed.stdout)
    assert result["status"] == "success"


def test_plugin_helper_rejects_unknown_operation(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/kbmanager_plugin.py"),
            "kb.unknown",
            "{}",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode != 0
    assert "unsupported operation" in completed.stderr
