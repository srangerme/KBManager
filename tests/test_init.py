from __future__ import annotations

from pathlib import Path

import kbmanager.application as application
from kbmanager.application import (
    INIT_DIRECTORIES,
    INIT_FILES,
    SYSTEM_TEMPLATE_FILES,
    init_workspace,
    system_template_text,
)


def test_init_dry_run_does_not_write(tmp_path: Path) -> None:
    result = init_workspace(tmp_path, entrypoint="claude_code", dry_run=True)

    assert result.to_dict()["status"] == "success"
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / ".claude").exists()
    assert "data/raw/md" in result.to_dict()["objects"]["created"]


def test_init_creates_workspace_structure_and_indexes(
    tmp_path: Path,
) -> None:
    result = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)

    assert result.to_dict()["status"] == "success"
    for directory in INIT_DIRECTORIES:
        assert (tmp_path / directory).is_dir()
    assert (tmp_path / "data/failed").is_dir()
    assert (tmp_path / "data/attachments/url-captures").is_dir()
    for placeholder in application.INIT_DIRECTORY_PLACEHOLDER_FILES:
        path = tmp_path / placeholder
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == ""
    for file_path, content in INIT_FILES.items():
        path = tmp_path / file_path
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == content
    assert not (tmp_path / ".lark").exists()
    assert not (tmp_path / "run_lark_server.py").exists()
    assert not (tmp_path / "templates").exists()
    assert not (tmp_path / ".claude").exists()


def test_init_is_idempotent_for_compatible_existing_files(tmp_path: Path) -> None:
    first = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)
    index = tmp_path / "indexes/source-index.md"
    before = index.stat().st_mtime_ns

    second = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)

    assert first.to_dict()["status"] == "success"
    assert second.to_dict()["status"] == "success"
    assert second.to_dict()["objects"]["created"] == []
    assert index.stat().st_mtime_ns == before


def test_init_ignores_user_templates_file(tmp_path: Path) -> None:
    conflict = tmp_path / "templates"
    conflict.write_text("user file", encoding="utf-8")

    result = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)

    assert result.to_dict()["status"] == "success"
    assert (tmp_path / "templates").read_text(encoding="utf-8") == "user file"
    assert not (tmp_path / ".claude").exists()


def test_init_ignores_user_templates_directory(
    tmp_path: Path,
) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "source.md").write_text("user template", encoding="utf-8")

    result = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)

    assert result.to_dict()["status"] == "success"
    assert (templates / "source.md").read_text(encoding="utf-8") == "user template"


def test_system_templates_are_package_resources() -> None:
    assert set(SYSTEM_TEMPLATE_FILES) == {
        "source.md",
        "source-meta.yml",
        "candidate.md",
        "knowledge.md",
        "knowledge-base.md",
        "note.md",
    }
    assert "type: source" in system_template_text("source.md")
    assert "type: note" in system_template_text("note.md")


def test_init_detects_parent_path_file_conflict_before_writing(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.write_text("user file", encoding="utf-8")

    dry_run = init_workspace(tmp_path, entrypoint="claude_code", dry_run=True)
    result = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)

    assert dry_run.to_dict()["status"] == "failed"
    assert result.to_dict()["status"] == "failed"
    assert data.read_text(encoding="utf-8") == "user file"
    assert not (tmp_path / "templates").exists()
    assert any("parent path is not a directory" in item for item in result.to_dict()["warnings"])


def test_init_write_failure_rolls_back_created_files_and_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    writes = 0
    original_write = application._write_new_text_atomic

    def fail_after_first_write(path: Path, text: str) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated write failure")
        original_write(path, text)

    monkeypatch.setattr(application, "_write_new_text_atomic", fail_after_first_write)

    result = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)

    assert result.to_dict()["status"] == "failed"
    assert list(tmp_path.iterdir()) == []


def test_init_outputs_do_not_include_user_knowledge_objects(tmp_path: Path) -> None:
    result = init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)

    assert result.to_dict()["status"] == "success"
    assert not (tmp_path / "tasks").exists()
    assert not (tmp_path / "templates/task-agent.md").exists()
    assert not (tmp_path / "indexes/task-index.md").exists()
    assert "task-index.md" not in (tmp_path / "indexes/manifest.yml").read_text(encoding="utf-8")
    assert sorted(path.name for path in (tmp_path / "data/raw/md").iterdir()) == ["KBM.ignore"]
    assert sorted(path.name for path in (tmp_path / "data/raw/pdf").iterdir()) == ["KBM.ignore"]
    assert sorted(path.name for path in (tmp_path / "candidates/pending").iterdir()) == [
        "KBM.ignore"
    ]
    assert sorted(path.name for path in (tmp_path / "knowledge/atomic").iterdir()) == ["KBM.ignore"]
    assert sorted(path.name for path in (tmp_path / "knowledge/bases").iterdir()) == ["KBM.ignore"]
    assert sorted(path.name for path in (tmp_path / "notes/active").iterdir()) == ["KBM.ignore"]


def test_init_requires_entrypoint_and_dry_run(tmp_path: Path) -> None:
    missing_entrypoint = init_workspace(tmp_path, dry_run=True).to_dict()
    missing_dry_run = init_workspace(tmp_path, entrypoint="claude_code").to_dict()
    wrong_entrypoint = init_workspace(
        tmp_path,
        entrypoint="external_chat",
        dry_run=True,
    ).to_dict()

    assert missing_entrypoint["status"] == "failed"
    assert missing_entrypoint["errors"][0]["code"] == "missing_entrypoint"
    assert missing_dry_run["status"] == "failed"
    assert missing_dry_run["errors"][0]["code"] == "missing_dry_run"
    assert wrong_entrypoint["status"] == "failed"
    assert wrong_entrypoint["errors"][0]["code"] == "unsupported_entrypoint"
