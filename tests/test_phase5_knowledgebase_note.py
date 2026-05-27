from __future__ import annotations

from pathlib import Path

from kbmanager.application import (
    clean_inspect,
    init_workspace,
    knowledgebase_create,
    note_add,
    note_deprecate,
    note_get,
)
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace


def _kb_payload() -> dict[str, object]:
    return {
        "description": "Research knowledge.",
        "tags": ["research"],
        "scope": {"includes": ["research"], "excludes": ["misc"]},
        "default_outline_id": "canonical",
        "outlines": [
            {
                "id": "canonical",
                "title": "Main",
                "description": "Main outline.",
                "status": "active",
                "nodes": [{"id": "sec1", "title": "Section 1"}],
            }
        ],
    }


def test_knowledgebase_create_requires_review_then_writes_active_kb_and_outlines(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)

    gate = knowledgebase_create(tmp_path, title="Research KB", **_kb_payload()).to_dict()
    final = knowledgebase_create(
        tmp_path,
        title="Research KB",
        review={"decision": "approve"},
        **_kb_payload(),
    ).to_dict()

    assert gate["status"] == "needs_review"
    assert final["status"] == "success"
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(final["path"])
    assert document.frontmatter["status"] == "active"
    assert "outline" not in document.frontmatter
    outlines_file = tmp_path / final["outlines_file"]
    assert outlines_file.is_file()
    assert "sec1" in outlines_file.read_text(encoding="utf-8")


def test_knowledgebase_create_rejects_duplicate_id_and_title(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    first = knowledgebase_create(
        tmp_path,
        title="Research KB",
        review={"decision": "approve"},
        **_kb_payload(),
    ).to_dict()

    duplicate_id = knowledgebase_create(
        tmp_path,
        title="Other KB",
        knowledgebase_id=first["knowledgebase_id"],
        review={"decision": "approve"},
        **_kb_payload(),
    ).to_dict()
    duplicate_title = knowledgebase_create(
        tmp_path,
        title="Research KB",
        review={"decision": "approve"},
        **_kb_payload(),
    ).to_dict()

    assert duplicate_id["status"] == "failed"
    assert duplicate_title["status"] == "failed"


def test_note_add_get_and_deprecate_moves_without_deleting(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    added = note_add(tmp_path, content="A useful note.", title="Note").to_dict()

    got = note_get(tmp_path, note_id=added["note_id"]).to_dict()
    gate = note_deprecate(tmp_path, note_id=added["note_id"], reason="Old.").to_dict()
    deprecated = note_deprecate(
        tmp_path,
        note_id=added["note_id"],
        reason="Old.",
        decision="deprecate",
        reviewed_by="user",
    ).to_dict()

    assert got["status"] == "success"
    assert gate["status"] == "needs_review"
    assert deprecated["status"] == "success"
    assert (tmp_path / "notes/deprecated" / f"{added['note_id']}.md").is_file()


def test_clean_inspect_reports_current_schema_drift_only(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    added = note_add(tmp_path, content="A useful note.", title="Note").to_dict()
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(added["path"])
    frontmatter = dict(document.frontmatter)
    frontmatter["unexpected"] = "drift"
    path = tmp_path / added["path"]
    path.write_text(
        ObjectRepository.render_markdown(
            MarkdownDocument(frontmatter=frontmatter, body=document.body)
        ),
        encoding="utf-8",
    )

    data = clean_inspect(tmp_path).to_dict()

    assert data["status"] == "needs_llm"
    assert data["differences"][0]["kind"] == "unexpected_fields"
    assert data["differences"][0]["fields"] == ["unexpected"]
