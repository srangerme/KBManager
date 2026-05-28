from __future__ import annotations

from pathlib import Path

from kbmanager.application import (
    candidate_create,
    candidate_get,
    candidate_next_pending,
    init_workspace,
    knowledgebase_create,
    source_add,
    source_deprecate,
)
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace


def _source_llm_result(input_path: str = "incoming.md") -> dict[str, object]:
    return {
        "input_path": input_path,
        "title": "Source Title",
        "summary": "A useful source summary.",
        "cleaned_content": f"# Cleaned\n\nSource: {input_path}\n\nUseful cleaned content.",
        "tags": ["ai"],
    }


def _create_source(tmp_path: Path) -> str:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n\nOriginal material.", encoding="utf-8")
    first = source_add(
        tmp_path, input_path="incoming.md"
    ).to_dict()
    resumed = source_add(
        tmp_path,
        input_path="incoming.md",
        resume_token=first["resume"]["token"],
        llm_result=_source_llm_result(),
    ).to_dict()
    assert resumed["status"] == "success"
    return resumed["source"]["id"]


def _create_active_kb(tmp_path: Path) -> str:
    payload = {
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
    result = knowledgebase_create(
        tmp_path,
        title="Research KB",
        review={"decision": "approve"},
        **payload,
    ).to_dict()
    assert result["status"] == "success"
    return result["knowledgebase_id"]


def _candidate_llm_result(source_id: str, kb_id: str) -> dict[str, object]:
    return {
        "candidates": [
            {
                "id": "knowledge-20260520-001",
                "title": "Candidate Title",
                "summary": "Candidate summary.",
                "content": "A candidate fact extracted from the source.",
                "evidence": [
                    {"source_id": source_id, "locator": "section 1", "quote": "Useful content."}
                ],
                "bindto": [
                    {
                        "kb_id": kb_id,
                        "outline_id": "canonical",
                        "node_id": "sec1",
                        "reason": "Fits.",
                    }
                ],
                "outline_change_suggestions": [],
            }
        ]
    }


def test_source_add_needs_llm_does_not_write(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")

    result = source_add(
        tmp_path, input_path="incoming.md"
    ).to_dict()

    assert result["status"] == "needs_llm"
    assert result["llm_request"]["system_prompt"] == "source-ingest"
    assert not list((tmp_path / "data/raw/md").glob("source-*.md"))


def test_source_add_resume_writes_source_and_cleaned(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)

    assert (tmp_path / "data/raw/md" / f"{source_id}.md").is_file()
    assert (
        (tmp_path / "data/cleaned" / f"{source_id}.md")
        .read_text(encoding="utf-8")
        .startswith("# Cleaned")
    )


def test_candidate_create_writes_pending_candidate_with_bindto(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    kb_id = _create_active_kb(tmp_path)
    first = candidate_create(
        tmp_path, source_ids=[source_id]
    ).to_dict()

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=first["resume"]["token"],
        llm_result=_candidate_llm_result(source_id, kb_id),
    ).to_dict()

    assert result["status"] == "success"
    assert result["candidate_ids"] == ["knowledge-20260520-001"]
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        "candidates/pending/knowledge-20260520-001.md"
    )
    assert document.frontmatter["summary"] == "Candidate summary."
    assert document.frontmatter["bindto"] == [
        {"kb_id": kb_id, "outline_id": "canonical", "node_id": "sec1", "reason": "Fits."}
    ]
    assert "relations" not in document.frontmatter
    assert "suggested_kb_ids" not in document.frontmatter


def test_candidate_create_rejects_invalid_bindto_outline_node(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    kb_id = _create_active_kb(tmp_path)
    first = candidate_create(
        tmp_path, source_ids=[source_id]
    ).to_dict()
    llm_result = _candidate_llm_result(source_id, kb_id)
    llm_result["candidates"][0]["bindto"][0]["node_id"] = "missing"

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=first["resume"]["token"],
        llm_result=llm_result,
    ).to_dict()

    assert result["status"] == "failed"
    assert "node_id does not exist" in result["errors"][0]["message"]


def test_candidate_create_rejects_archived_source_status(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    repository = ObjectRepository(Workspace(tmp_path))
    document = repository.read_markdown(f"data/raw/md/{source_id}.md")
    frontmatter = dict(document.frontmatter)
    frontmatter["status"] = "archived"
    repository.write_markdown(
        f"data/raw/md/{source_id}.md",
        MarkdownDocument(frontmatter=frontmatter, body=document.body),
        overwrite=True,
    )

    result = candidate_create(
        tmp_path, source_ids=[source_id]
    ).to_dict()

    assert result["status"] == "failed"
    assert "raw or deprecated" in result["errors"][0]["message"]


def test_candidate_get_and_next_pending(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    kb_id = _create_active_kb(tmp_path)
    first = candidate_create(
        tmp_path, source_ids=[source_id]
    ).to_dict()
    candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=first["resume"]["token"],
        llm_result=_candidate_llm_result(source_id, kb_id),
    )

    got = candidate_get(
        tmp_path, candidate_id="knowledge-20260520-001"
    ).to_dict()
    next_pending = candidate_next_pending(
        tmp_path
    ).to_dict()

    assert got["status"] == "success"
    assert next_pending["candidate"]["id"] == "knowledge-20260520-001"


def test_source_deprecate_reports_evidence_impacts(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    kb_id = _create_active_kb(tmp_path)
    first = candidate_create(
        tmp_path, source_ids=[source_id]
    ).to_dict()
    candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=first["resume"]["token"],
        llm_result=_candidate_llm_result(source_id, kb_id),
    )

    result = source_deprecate(
        tmp_path,
        source_id=source_id,
        decision="deprecate",
        reason="Superseded.",
    ).to_dict()

    assert result["status"] == "success"
    assert result["impacts"][0]["fields"] == "evidence"
