from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_claude_plugin_manifest_is_valid_json() -> None:
    manifest = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text())

    assert manifest["name"] == "kbm"
    assert "commands" not in manifest
    assert manifest["skills"] == "./skills/"


def test_claude_plugin_exposes_no_commands() -> None:
    assert not (REPO_ROOT / "commands").exists()


def test_claude_plugin_packages_kbm_skills() -> None:
    skill_names = {path.name for path in (REPO_ROOT / "skills").iterdir() if path.is_dir()}

    assert skill_names == {
        "kbm-candidate",
        "kbm-download-paper-pdf",
        "kbm-kb",
        "kbm-maintenance",
        "kbm-note",
        "kbm-research-on",
        "kbm-source",
    }
    for name in skill_names:
        text = (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert f"name: {name}" in text
        assert "description:" in text


def test_kbm_download_paper_pdf_has_no_bundled_scripts_requirement() -> None:
    download_skill_dir = REPO_ROOT / "skills/kbm-download-paper-pdf"
    text = (download_skill_dir / "SKILL.md").read_text(encoding="utf-8")

    assert not (download_skill_dir / "scripts").exists()
    assert "下载后目录核验" in text
    assert "最终报告只能根据 `/tmp/kbm-downloads` 中实际存在且通过核验的本次下载文件生成" in text
    assert "如果下载命令曾返回成功，但目录核验找不到有效文件" in text


def test_kbm_skills_forbid_plugin_resource_edits_in_normal_workflows() -> None:
    required = [
        "普通用户 workflow 中，不得修改 plugin 提供的",
        "`SKILL.md`",
        "`references/`",
        "`system-prompts/`",
        "`src/kbmanager/`",
        "`scripts/kbmanager_plugin.py`",
        "只有用户明确要求进行 plugin 开发或维护时，才允许修改这些资源",
    ]

    for skill_path in sorted((REPO_ROOT / "skills").glob("kbm-*/SKILL.md")):
        text = skill_path.read_text(encoding="utf-8")
        for phrase in required:
            assert phrase in text, f"{phrase!r} missing from {skill_path}"


def test_knowledgebase_workflow_does_not_ingest_source_context() -> None:
    knowledgebase_skill = (
        REPO_ROOT / "skills/kbm-kb/SKILL.md"
    ).read_text(encoding="utf-8")
    source_skill = (REPO_ROOT / "skills/kbm-source/SKILL.md").read_text(
        encoding="utf-8"
    )
    kb_reference = (
        REPO_ROOT / "skills/kbm-kb/references/kb.knowledgebase.create.md"
    ).read_text(encoding="utf-8")
    source_reference = (
        REPO_ROOT / "skills/kbm-source/references/kb.source.add.md"
    ).read_text(encoding="utf-8")

    for text in (knowledgebase_skill, source_skill, kb_reference, source_reference):
        assert "kb.source.add" in text
    assert "不得调用 `kb.source.add`" in knowledgebase_skill
    assert "不得调用 `kb.candidate.create`" in knowledgebase_skill
    assert "改用 kbm-kb 而不是 source lifecycle" in source_skill
    assert "不创建 source/candidate" in knowledgebase_skill
    assert "不得调用 `kb.source.add`" in kb_reference
    assert "不得调用 `kb.candidate.create`" in kb_reference


def test_api_references_are_split_by_operation() -> None:
    expected_references = {
        "kbm-source": {"kb.source.add.md", "kb.source.deprecate.md"},
        "kbm-candidate": {
            "kb.candidate.create.md",
            "kb.candidate.defer.md",
            "kb.candidate.get.md",
            "kb.candidate.next_pending.md",
            "kb.knowledge.accept.md",
            "kb.knowledge.deprecate.md",
            "kb.knowledge.merge.md",
            "kb.knowledge.reject.md",
        },
        "kbm-kb": {
            "kb.knowledgebase.create.md",
            "kb.knowledgebase.map.md",
            "kb.knowledgebase.outline.archive.md",
            "kb.knowledgebase.outline.create.md",
            "kb.knowledgebase.outline.set_default.md",
        },
        "kbm-note": {
            "kb.note.add.md",
            "kb.note.deprecate.md",
            "kb.note.get.md",
        },
        "kbm-maintenance": {
            "kb.clean.inspect.md",
            "kb.index.rebuild.md",
            "kb.init.md",
        },
    }

    for skill, references in expected_references.items():
        reference_dir = REPO_ROOT / "skills" / skill / "references"
        assert {path.name for path in reference_dir.iterdir()} == references
        for reference in references:
            text = (reference_dir / reference).read_text(encoding="utf-8")
            assert "## 用途" in text
            assert "## 载荷" in text
            assert "## 硬规则" in text
            assert "流程：" not in text

    for old_reference in {
        "skills/kbm-source/references/source-workflows.md",
        "skills/kbm-candidate/references/candidate-review-workflows.md",
        "skills/kbm-kb/references/kb-outline-workflows.md",
        "skills/kbm-note/references/note-workflows.md",
        "skills/kbm-maintenance/references/maintenance-workflows.md",
        "skills/kbm-research-on/references/research-on-workflow.md",
    }:
        assert not (REPO_ROOT / old_reference).exists()

    source_reference = (
        REPO_ROOT / "skills/kbm-source/references/kb.source.add.md"
    ).read_text(encoding="utf-8")
    candidate_reference = (
        REPO_ROOT / "skills/kbm-candidate/references/kb.knowledge.accept.md"
    ).read_text(encoding="utf-8")

    assert "不得自行下载、打开、浏览、打印、导出、抓取、保存或重试" in (
        source_reference
    )
    assert "必须等待用户 approve 或 edited reviewed content" in candidate_reference


def test_skills_reference_api_files_from_workflows() -> None:
    source_skill = (REPO_ROOT / "skills/kbm-source/SKILL.md").read_text(
        encoding="utf-8"
    )
    candidate_skill = (REPO_ROOT / "skills/kbm-candidate/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "意图流程图" in source_skill
    assert "references/kb.source.add.md" in source_skill
    assert "../kbm-candidate/references/kb.candidate.create.md" in source_skill
    assert "references/kb.knowledge.accept.md" in candidate_skill
    assert "没有明确用户决定时，绝不 accept、reject、defer 或 merge" in (
        candidate_skill
    )


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
    plugin_root = tmp_path / "plugins/kbm"
    assert plugin_root.is_dir()
    assert not plugin_root.is_symlink()
    assert not (plugin_root / "commands").exists()
    assert (plugin_root / "skills/kbm-source/references/kb.source.add.md").is_file()
    assert (plugin_root / "scripts/kbmanager_plugin.py").is_file()
    assert (plugin_root / "src/kbmanager/application.py").is_file()
    assert (plugin_root / "system-prompts/source-ingest.md").is_file()


def test_register_marketplace_script_copies_only_plugin_package(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import register_marketplace

    register_marketplace.register_plugin(tmp_path)

    plugin_root = tmp_path / "plugins/kbm"
    assert {path.name for path in plugin_root.iterdir()} == {
        "pyproject.toml",
        "scripts",
        "skills",
        "src",
        "system-prompts",
    }
    assert (plugin_root / "scripts/kbmanager_plugin.py").is_file()
    assert (plugin_root / "scripts/register_marketplace.py").is_file()
    assert not (plugin_root / ".claude-plugin").exists()
    assert not (plugin_root / "README.md").exists()
    assert not (plugin_root / "docs").exists()
    assert not (plugin_root / "tests").exists()
    assert not (plugin_root / ".git").exists()
    assert not (plugin_root / ".pytest_cache").exists()
    assert not (plugin_root / ".ruff_cache").exists()


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

    for operation in {
        "kb.init",
        "kb.source.add",
        "kb.candidate.create",
        "kb.note.add",
        "kb.index.rebuild",
        "kb.clean.inspect",
    }:
        assert operation in supported


def test_claude_plugin_package_does_not_contain_user_data_roots(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import register_marketplace

    register_marketplace.register_plugin(tmp_path)
    plugin_root = tmp_path / "plugins/kbm"
    forbidden = {".lark", "data", "knowledge", "candidates", "notes", "indexes"}

    for name in forbidden:
        assert not (plugin_root / name).exists()


def test_plugin_helper_invokes_api_with_project_dir(tmp_path: Path) -> None:
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
    assert result["status"] == "success"
    assert result["operation"] == "kb.init"
    assert (tmp_path / "data").exists()


def test_plugin_helper_rejects_removed_api_contract_fields(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/kbmanager_plugin.py"),
            "kb.init",
            '{"entry' + 'point": "claude_code", "dry' + '_run": true}',
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode != 0
    assert "unexpected keyword argument" in completed.stderr


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
            "{}",
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
