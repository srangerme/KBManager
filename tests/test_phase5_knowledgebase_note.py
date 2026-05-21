from __future__ import annotations

import re
from pathlib import Path

from kbmanager.application import (
    init_workspace,
    knowledgebase_create,
    note_add,
    note_deprecate,
    note_get,
)
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _write_source(tmp_path: Path, source_id: str = "source-20260520-001") -> str:
    repository = ObjectRepository(Workspace(tmp_path))
    repository.write_markdown(
        f"data/raw/md/{source_id}.md",
        MarkdownDocument(
            frontmatter={
                "id": source_id,
                "type": "source",
                "title": "Source",
                "status": "raw",
                "created": "2026-05-20",
                "updated": "2026-05-20",
            },
            body="\n## Source\n\nBody\n",
        ),
    )
    return source_id


def test_knowledgebase_create_requires_user_approve(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    result = knowledgebase_create(
        tmp_path,
        title="Research",
        description="Research knowledge.",
        acceptance_criteria="Only reviewed research knowledge belongs here.",
    )

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert data["review"] == {"required": True, "options": ["approve", "revise"]}
    assert sorted(path.name for path in (tmp_path / "knowledge/bases").iterdir()) == [
        "KBM.ignore"
    ]


def test_knowledgebase_create_writes_reviewed_base(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    result = knowledgebase_create(
        tmp_path,
        knowledgebase_id="kb-20260520-001",
        title="Research",
        description="Research knowledge.",
        acceptance_criteria="Only reviewed research knowledge belongs here.",
        tags=["research"],
        body="Reviewed criteria.",
        decision="approve",
        reviewed_by="user",
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["knowledgebase_id"] == "kb-20260520-001"
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        "knowledge/bases/kb-20260520-001.md"
    )
    assert document.frontmatter["type"] == "knowledge-base"
    assert document.frontmatter["status"] == "active"
    assert (
        document.frontmatter["acceptance_criteria"]
        == "Only reviewed research knowledge belongs here."
    )
    assert document.frontmatter["knowledge_ids"] == []
    assert document.frontmatter["review_decision"] == "approve"
    assert document.frontmatter["tags"] == ["research"]
    assert "Reviewed criteria." in document.body
    assert TIMESTAMP_RE.match(document.frontmatter["created"])
    assert TIMESTAMP_RE.match(document.frontmatter["updated"])
    assert TIMESTAMP_RE.match(document.frontmatter["reviewed_at"])


def test_knowledgebase_create_auto_id_includes_title_slug(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    result = knowledgebase_create(
        tmp_path,
        title="研究 Research KB!",
        description="Research knowledge.",
        acceptance_criteria="Only reviewed research knowledge belongs here.",
        decision="approve",
        reviewed_by="user",
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert re.match(r"^kb-\d{8}-001-研究-research-kb$", data["knowledgebase_id"])
    assert data["path"] == f"knowledge/bases/{data['knowledgebase_id']}.md"
    assert (tmp_path / data["path"]).is_file()


def test_knowledgebase_create_rejects_duplicate_id_and_title(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    first = knowledgebase_create(
        tmp_path,
        knowledgebase_id="kb-20260520-001",
        title="Research",
        description="Research knowledge.",
        acceptance_criteria="Only reviewed research knowledge belongs here.",
        decision="approve",
        reviewed_by="user",
    )
    assert first.to_dict()["status"] == "success"

    duplicate_id = knowledgebase_create(
        tmp_path,
        knowledgebase_id="kb-20260520-001",
        title="Other",
        description="Other knowledge.",
        acceptance_criteria="Only other knowledge belongs here.",
        decision="approve",
        reviewed_by="user",
    )
    duplicate_title = knowledgebase_create(
        tmp_path,
        knowledgebase_id="kb-20260520-002",
        title="research",
        description="Other knowledge.",
        acceptance_criteria="Only other knowledge belongs here.",
        decision="approve",
        reviewed_by="user",
    )

    assert duplicate_id.to_dict()["status"] == "failed"
    assert "already exists" in duplicate_id.to_dict()["errors"][0]["message"]
    assert duplicate_title.to_dict()["status"] == "failed"
    assert "title already exists" in duplicate_title.to_dict()["errors"][0]["message"]


def test_note_add_get_and_deprecate_moves_without_deleting(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    added = note_add(
        tmp_path,
        note_id="note-20260520-001",
        title="Inbox Note",
        content="Remember this.",
        tags=["inbox"],
    )
    assert added.to_dict()["status"] == "success"
    assert (tmp_path / "notes/inbox/note-20260520-001.md").is_file()

    fetched = note_get(tmp_path, note_id="note-20260520-001")
    gate = note_deprecate(tmp_path, note_id="note-20260520-001", reason="No longer needed.")
    deprecated = note_deprecate(
        tmp_path,
        note_id="note-20260520-001",
        reason="No longer needed.",
        decision="deprecate",
        reviewed_by="user",
    )

    assert fetched.to_dict()["note"]["frontmatter"]["status"] == "inbox"
    assert gate.to_dict()["status"] == "needs_review"
    assert deprecated.to_dict()["status"] == "success"
    assert not (tmp_path / "notes/inbox/note-20260520-001.md").exists()
    deprecated_file = tmp_path / "notes/deprecated/note-20260520-001.md"
    assert deprecated_file.is_file()
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        "notes/deprecated/note-20260520-001.md"
    )
    assert document.frontmatter["status"] == "deprecated"
    assert document.frontmatter["deprecated_reason"] == "No longer needed."
    assert TIMESTAMP_RE.match(document.frontmatter["updated"])
    assert TIMESTAMP_RE.match(document.frontmatter["reviewed_at"])
    assert TIMESTAMP_RE.match(document.frontmatter["deprecated_at"])


def test_note_add_with_binding_uses_bound_directory(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    source_id = _write_source(tmp_path)

    result = note_add(
        tmp_path,
        note_id="note-20260520-001",
        content="Bound note.",
        bindings=[{"type": "source", "id": source_id}],
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["note"]["frontmatter"]["status"] == "bound"
    assert data["note"]["frontmatter"]["bindings"] == [{"type": "source", "id": source_id}]
    assert TIMESTAMP_RE.match(data["note"]["frontmatter"]["created"])
    assert TIMESTAMP_RE.match(data["note"]["frontmatter"]["updated"])
    assert (tmp_path / "notes/bound/note-20260520-001.md").is_file()


def test_note_add_optional_llm_title_summary_flow(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    gate = note_add(
        tmp_path,
        note_id="note-20260520-001",
        content="Raw note body.",
        needs_llm=True,
    )
    token = gate.to_dict()["resume"]["token"]
    result = note_add(
        tmp_path,
        note_id="note-20260520-001",
        content="Raw note body.",
        needs_llm=True,
        resume_token=token,
        llm_result={"title": "LLM Note", "summary": "Short summary."},
    )

    data = result.to_dict()
    assert gate.to_dict()["status"] == "needs_llm"
    assert data["status"] == "success"
    assert data["note"]["frontmatter"]["title"] == "LLM Note"
    assert data["note"]["frontmatter"]["summary"] == "Short summary."


def test_note_add_rejects_missing_binding_object(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    result = note_add(
        tmp_path,
        note_id="note-20260520-001",
        content="Bound note.",
        bindings=[{"type": "source", "id": "source-20260520-999"}],
    )

    assert result.to_dict()["status"] == "failed"
    assert "object not found" in result.to_dict()["errors"][0]["message"]
    assert not (tmp_path / "notes/bound/note-20260520-001.md").exists()


def test_note_deprecate_requires_reason_after_review(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    note_add(tmp_path, note_id="note-20260520-001", content="Remember this.")

    result = note_deprecate(
        tmp_path,
        note_id="note-20260520-001",
        decision="deprecate",
        reviewed_by="user",
    )

    assert result.to_dict()["status"] == "failed"
    assert "requires a non-empty reason" in result.to_dict()["errors"][0]["message"]
    assert (tmp_path / "notes/inbox/note-20260520-001.md").is_file()
