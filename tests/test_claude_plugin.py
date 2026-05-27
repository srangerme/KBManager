from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND_DIR = REPO_ROOT / "commands"


DOCUMENTED_COMMANDS = [
    "candidate-review.md",
    "check.md",
    "clean.md",
    "init.md",
    "knowledgebase-create.md",
    "knowledgebase-list.md",
    "knowledgebase-map.md",
    "knowledgebase-outline-archive.md",
    "knowledgebase-outline-create.md",
    "knowledgebase-outline-set-default.md",
    "lark-server-start.md",
    "lark-server-status.md",
    "lark-server-stop.md",
    "note-add.md",
    "note-deprecate.md",
    "note-list.md",
    "note-view.md",
    "source-add.md",
    "source-deprecate.md",
]

COMMAND_REQUIRED_FIELDS = {
    "init.md": ["dry_run"],
    "source-add.md": ["input_path"],
    "source-deprecate.md": ["source_id", "reason", "decision", "reviewed_by"],
    "candidate-review.md": ["candidate_id", "decision"],
    "note-add.md": ["content"],
    "note-view.md": ["note_id"],
    "note-deprecate.md": ["note_id", "reason", "decision", "reviewed_by"],
    "knowledgebase-create.md": [
        "title",
        "input_path",
        "review",
        "description",
        "tags",
        "scope",
        "default_outline_id",
        "outlines",
    ],
    "knowledgebase-outline-create.md": ["knowledgebase_id", "input_path", "outline", "review"],
    "knowledgebase-outline-set-default.md": ["knowledgebase_id", "outline_id", "review"],
    "knowledgebase-outline-archive.md": ["knowledgebase_id", "outline_id", "review"],
}

COMMAND_OPTIONAL_FIELDS = {
    "init.md": ["dry_run"],
    "source-add.md": ["title", "tags", "authors"],
    "candidate-review.md": ["candidate_id", "reason", "merge_targets"],
    "note-add.md": ["title"],
    "knowledgebase-create.md": ["knowledgebase_id"],
    "knowledgebase-outline-create.md": ["knowledgebase_id", "input_path"],
    "knowledgebase-outline-set-default.md": ["knowledgebase_id", "outline_id"],
    "knowledgebase-outline-archive.md": ["knowledgebase_id", "outline_id"],
    "knowledgebase-list.md": ["knowledgebase_id"],
    "knowledgebase-map.md": ["knowledgebase_id"],
}

WRITE_COMMANDS = {
    "source-add.md",
    "source-deprecate.md",
    "candidate-review.md",
    "note-add.md",
    "note-deprecate.md",
    "knowledgebase-create.md",
    "knowledgebase-outline-create.md",
    "knowledgebase-outline-set-default.md",
    "knowledgebase-outline-archive.md",
}

CLAUDE_REVIEW_COMMANDS = {
    "candidate-review.md",
    "note-add.md",
    "knowledgebase-create.md",
    "knowledgebase-outline-create.md",
    "knowledgebase-outline-set-default.md",
    "knowledgebase-outline-archive.md",
}

READ_ONLY_DISPLAY_COMMANDS = {
    "knowledgebase-list.md",
    "note-list.md",
    "note-view.md",
}

CONFIRMATION_COMMANDS = {
    "source-deprecate.md",
    "candidate-review.md",
    "note-deprecate.md",
    "knowledgebase-create.md",
}


def test_claude_plugin_manifest_is_valid_json() -> None:
    manifest = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text())

    assert manifest["name"] == "kbm"
    assert manifest["commands"] == "./commands/"
    assert manifest["skills"] == "./skills/"


def test_claude_plugin_packages_deep_research_skill() -> None:
    skill = REPO_ROOT / "skills/knowledgebase-deep-research-prompt/SKILL.md"

    text = skill.read_text(encoding="utf-8")
    assert "name: knowledgebase-deep-research-prompt" in text
    assert "description" in text
    assert "original URLs" in text


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


def test_claude_plugin_commands_exist_for_documented_lifecycle() -> None:
    commands = {path.name for path in COMMAND_DIR.glob("*.md")}

    assert commands == set(DOCUMENTED_COMMANDS)


def test_documented_commands_keep_alphabetical_order() -> None:
    docs = (REPO_ROOT / "docs/ClaudePlugin.md").read_text(encoding="utf-8")
    command_block = re.search(r"```txt\n(/kbm:[\s\S]+?)\n```", docs)
    assert command_block is not None

    commands = [
        line.split()[0].removeprefix("/kbm:") + ".md"
        for line in command_block.group(1).splitlines()
    ]

    assert commands == DOCUMENTED_COMMANDS
    assert commands == sorted(commands)


def test_command_files_match_slash_command_flowchart() -> None:
    flowchart = (REPO_ROOT / "docs/SlashCommand流程图.md").read_text(encoding="utf-8")
    command_names = re.findall(r"## \d+\. `/([^`]+)`", flowchart)
    expected_files = set()
    for name in command_names:
        tokens = [token for token in name.split() if not token.startswith(("<", "["))]
        expected_files.add("-".join(tokens) + ".md")

    assert expected_files == set(DOCUMENTED_COMMANDS)

    command_files = []
    for name in command_names:
        tokens = [token for token in name.split() if not token.startswith(("<", "["))]
        command_files.append("-".join(tokens) + ".md")
    assert command_files == DOCUMENTED_COMMANDS


def test_command_api_operations_are_supported_by_plugin_helper() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import kbmanager_plugin

    supported = set(kbmanager_plugin._operation_map())
    operation_refs: set[str] = set()
    for path in COMMAND_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        operation_refs.update(re.findall(r"\bkb\.[a-z._]+", text))

    assert operation_refs <= supported


def test_lark_server_commands_use_daemon_only() -> None:
    for filename in ("lark-server-start.md", "lark-server-status.md", "lark-server-stop.md"):
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8")
        assert "scripts/kbmanager_lark_server.py" in text
        assert "kb.note.add" not in text
        assert "kb.source.add" not in text


def test_all_commands_document_required_and_optional_inputs() -> None:
    missing_required = []
    for filename, fields in COMMAND_REQUIRED_FIELDS.items():
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8")
        for field in fields:
            if field not in text:
                missing_required.append((filename, field))

    missing_optional = []
    for filename, fields in COMMAND_OPTIONAL_FIELDS.items():
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8")
        for field in fields:
            if field not in text:
                missing_optional.append((filename, field))
        if "optional" not in text.casefold() and "可选" not in text and "省略" not in text:
            missing_optional.append((filename, "<optional marker>"))

    assert missing_required == []
    assert missing_optional == []


def test_commands_with_user_review_use_claude_code_contract() -> None:
    for filename in CLAUDE_REVIEW_COMMANDS:
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8")
        assert "Claude Code" in text
        assert "code --wait" not in text
        assert "parse" in text.casefold()
        assert "until the user has replied" in text


def test_read_only_display_commands_use_claude_code_display() -> None:
    for filename in READ_ONLY_DISPLAY_COMMANDS:
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8")
        assert "Claude Code" in text
        assert "code --reuse-window" not in text


def test_note_view_displays_full_markdown_content() -> None:
    text = (COMMAND_DIR / "note-view.md").read_text(encoding="utf-8")

    assert "complete note Markdown content directly in Claude Code" in text
    assert "Show the full Markdown file content by default" in text
    assert "Do not replace the note body with a summary" in text


def test_commands_with_write_or_status_changes_have_review_gate_contract() -> None:
    for filename in CONFIRMATION_COMMANDS:
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8")
        assert "confirm" in text.casefold() or "approval" in text.casefold()
        assert "reviewed_by" in text or "user review" in text.casefold()


def test_write_commands_document_index_strategy_after_success() -> None:
    missing = []
    for filename in WRITE_COMMANDS:
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8")
        if "kb.index.rebuild" not in text and "/check" not in text:
            missing.append(filename)

    assert missing == []


def test_list_commands_document_deprecated_entries_are_hidden() -> None:
    for filename in ("note-list.md", "knowledgebase-list.md"):
        text = (COMMAND_DIR / filename).read_text(encoding="utf-8").casefold()
        assert "hide deprecated" in text


def test_note_add_command_always_uses_llm_before_write() -> None:
    text = (COMMAND_DIR / "note-add.md").read_text(encoding="utf-8")

    assert "Always call `kb.note.add` first with `needs_llm: true`" in text
    assert "Always use the note title LLM flow before writing the note" in text
    assert "Never pass `title: \"\"`" in text


def test_plugin_docs_explain_user_level_permission_allowlist() -> None:
    text = (REPO_ROOT / "docs/ClaudePlugin.md").read_text(encoding="utf-8")

    assert "~/.claude/settings.json" in text
    assert '"Bash(python3 */scripts/kbmanager_plugin.py *)"' in text
    assert "does not bypass KBManager review gates" in text


def test_commands_with_user_review_writes_wait_for_claude_code_reply() -> None:
    expected = {
        "note-add.md": "Do not call `kb.note.add` until the user has replied",
        "knowledgebase-create.md": (
            "Do not call `kb.knowledgebase.create` until the user has replied"
        ),
        "candidate-review.md": (
            "never call the write API until the user has replied"
        ),
    }

    for filename, guardrail in expected.items():
        command = (REPO_ROOT / "commands" / filename).read_text(encoding="utf-8")
        assert "Claude Code" in command
        assert "code --wait" not in command
        assert guardrail in command


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
            '{"dry_run": true}',
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
            '{"dry_run": true}',
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


def test_knowledgebase_map_command_omits_empty_knowledgebase_id() -> None:
    text = (COMMAND_DIR / "knowledgebase-map.md").read_text(encoding="utf-8")

    assert "kb.knowledgebase.map '{}' --pretty" in text
    assert 'do not pass an empty string' in text
