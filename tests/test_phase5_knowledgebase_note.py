from __future__ import annotations

from pathlib import Path

import pytest

from kbmanager.application import (
    init_workspace,
    knowledgebase_create,
    knowledgebase_create_prepare,
    note_add,
    note_deprecate,
    note_get,
)
from kbmanager.repository import ObjectRepository
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


def test_knowledgebase_create_writes_active_kb_and_outlines_after_hook_review(
    tmp_path: Path,
) -> None:
    init_workspace(tmp_path)

    final = knowledgebase_create(
        tmp_path,
        title="Research KB",
        **_kb_payload(),
    ).to_dict()

    assert final["status"] == "success"
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(final["path"])
    assert document.frontmatter["status"] == "active"
    assert "outline" not in document.frontmatter
    outlines_file = tmp_path / final["outlines_file"]
    assert outlines_file.is_file()
    assert "sec1" in outlines_file.read_text(encoding="utf-8")


def test_knowledgebase_create_prepare_llm_draft_does_not_write(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "kb-seed.md").write_text("# Seed\n\n- Topic A\n", encoding="utf-8")

    first = knowledgebase_create_prepare(
        tmp_path,
        title="Research KB",
        input_path="kb-seed.md",
    ).to_dict()
    resumed = knowledgebase_create_prepare(
        tmp_path,
        title="Research KB",
        input_path="kb-seed.md",
        resume_token=first["resume"]["token"],
        llm_result={"frontmatter": _kb_payload(), "body": "Draft body."},
    ).to_dict()

    assert first["status"] == "needs_llm"
    assert first["llm_request"]["system_prompt"] == "knowledgebase-create"
    assert first["llm_request"]["output_schema"] == "knowledgebase_create_draft"
    user_input = first["llm_request"]["prompt"]["sections"][1]["content"]
    assert "Topic A" in user_input["knowledgebase_create_input"]["content"]
    assert not list((tmp_path / "knowledge/bases").glob("kb-*.md"))
    assert resumed["status"] == "success"
    assert resumed["reviewed_payload"]["description"] == "Research knowledge."


def test_knowledgebase_create_rejects_invalid_resume_token(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "kb-seed.md").write_text("# Seed\n", encoding="utf-8")

    result = knowledgebase_create_prepare(
        tmp_path,
        title="Research KB",
        input_path="kb-seed.md",
        resume_token="bad-token",
        llm_result={"frontmatter": _kb_payload(), "body": "Draft body."},
    ).to_dict()

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "invalid_resume_token"


def test_knowledgebase_create_old_combined_api_shape_is_removed(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    with pytest.raises(TypeError):
        knowledgebase_create(
            tmp_path,
            title="Research KB",
            input_path="kb-seed.md",
        )


def test_knowledgebase_create_rejects_duplicate_id_and_title(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    first = knowledgebase_create(
        tmp_path,
        title="Research KB",
        **_kb_payload(),
    ).to_dict()

    duplicate_id = knowledgebase_create(
        tmp_path,
        title="Other KB",
        knowledgebase_id=first["knowledgebase_id"],
        **_kb_payload(),
    ).to_dict()
    duplicate_title = knowledgebase_create(
        tmp_path,
        title="Research KB",
        **_kb_payload(),
    ).to_dict()

    assert duplicate_id["status"] == "failed"
    assert duplicate_title["status"] == "failed"


def test_note_add_get_and_deprecate_moves_without_deleting(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    added = note_add(
        tmp_path, content="A useful note.", title="Note"
    ).to_dict()

    got = note_get(
        tmp_path, note_id=added["note_id"]
    ).to_dict()
    deprecated = note_deprecate(
        tmp_path,
        note_id=added["note_id"],
        reason="Old.",
    ).to_dict()

    assert got["status"] == "success"
    assert got["note"]["body"] == "\n## Note\n\nA useful note.\n"
    assert deprecated["status"] == "success"
    assert (tmp_path / "notes/deprecated" / f"{added['note_id']}.md").is_file()
