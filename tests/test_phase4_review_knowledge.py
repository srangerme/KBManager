from __future__ import annotations

from pathlib import Path

from kbmanager.application import (
    candidate_create,
    candidate_defer,
    init_workspace,
    knowledge_accept,
    knowledge_deprecate,
    knowledge_merge,
    knowledge_reject,
    knowledgebase_create,
    knowledgebase_init,
    source_add,
)
from kbmanager.repository import ObjectRepository
from kbmanager.workspace import Workspace


def _setup_candidate(
    tmp_path: Path,
    candidate_id: str = "knowledge-20260520-001",
) -> tuple[str, str, dict]:
    init_workspace(tmp_path)
    (tmp_path / "source.md").write_text("# Source\n", encoding="utf-8")
    first_source = source_add(tmp_path, input_path="source.md").to_dict()
    source = source_add(
        tmp_path,
        input_path="source.md",
        resume_token=first_source["resume"]["token"],
        llm_result={
            "input_path": "source.md",
            "summary": "Source summary.",
            "cleaned_content": "source.md cleaned",
        },
    ).to_dict()
    source_id = source["source"]["id"]

    (tmp_path / "kb.md").write_text("# KB\n", encoding="utf-8")
    kb_title = f"Research KB {candidate_id}"
    kb_id = knowledgebase_create(tmp_path, title=kb_title).to_dict()["knowledgebase_id"]
    kb_init = knowledgebase_init(tmp_path, knowledgebase_id=kb_id, input_path="kb.md").to_dict()
    kb_payload = {
        "description": "Research.",
        "tags": [],
        "scope": {"includes": ["research"], "excludes": []},
        "outline": [{"id": "sec1", "title": "Section 1"}],
    }
    knowledgebase_init(
        tmp_path,
        knowledgebase_id=kb_id,
        input_path="kb.md",
        resume_token=kb_init["resume"]["token"],
        llm_result=kb_payload,
        review={"decision": "approve"},
        reviewed_payload=kb_payload,
    )
    candidate_payload = {
        "title": "Candidate",
        "summary": "Candidate summary.",
        "content": "Candidate content.",
        "evidence": [{"source_id": source_id, "locator": "section 1", "quote": "quote"}],
        "bindto": [{"kb_id": kb_id, "outline_node": "sec1", "reason": "Fits."}],
        "outline_change_suggestions": [],
    }
    first_candidate = candidate_create(tmp_path, source_ids=[source_id]).to_dict()
    candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=first_candidate["resume"]["token"],
        llm_result={"candidates": [{"id": candidate_id, **candidate_payload}]},
    )
    return candidate_id, kb_id, candidate_payload


def test_accept_requires_review_and_promotes_candidate(tmp_path: Path) -> None:
    candidate_id, kb_id, payload = _setup_candidate(tmp_path)

    gate = knowledge_accept(tmp_path, candidate_id=candidate_id).to_dict()
    result = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
        title="Accepted",
        summary=payload["summary"],
        content=payload["content"],
        evidence=payload["evidence"],
        bindto=payload["bindto"],
    ).to_dict()

    assert gate["status"] == "needs_review"
    assert result["status"] == "success"
    assert result["bindto"][0]["kb_id"] == kb_id
    assert not (tmp_path / "candidates/pending" / f"{candidate_id}.md").exists()
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        f"knowledge/atomic/{candidate_id}.md"
    )
    assert document.frontmatter["type"] == "knowledge"
    assert document.frontmatter["summary"] == "Candidate summary."
    assert "kb_ids" not in document.frontmatter
    assert "relations" not in document.frontmatter


def test_accept_rejects_evidence_not_from_candidate(tmp_path: Path) -> None:
    candidate_id, _, payload = _setup_candidate(tmp_path)
    bad_evidence = [
        {"source_id": payload["evidence"][0]["source_id"], "locator": "x", "quote": "x"}
    ]

    result = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
        title="Accepted",
        summary=payload["summary"],
        content=payload["content"],
        evidence=bad_evidence,
        bindto=payload["bindto"],
    ).to_dict()

    assert result["status"] == "failed"
    assert "candidate evidence" in result["errors"][0]["message"]


def test_reject_and_defer_move_candidate(tmp_path: Path) -> None:
    candidate_id, _, _ = _setup_candidate(tmp_path)
    rejected = knowledge_reject(
        tmp_path,
        candidate_id=candidate_id,
        decision="reject",
        reviewed_by="user",
        reason="No.",
    ).to_dict()
    assert rejected["status"] == "success"
    assert (tmp_path / "candidates/rejected" / f"{candidate_id}.md").exists()

    candidate_id, _, _ = _setup_candidate(tmp_path, candidate_id="knowledge-20260520-002")
    deferred = candidate_defer(
        tmp_path,
        candidate_id=candidate_id,
        decision="defer",
        reviewed_by="user",
        reason="Later.",
    ).to_dict()
    assert deferred["status"] == "success"
    assert (tmp_path / "candidates/deferred" / f"{candidate_id}.md").exists()


def test_merge_updates_target_and_rejects_source_candidate(tmp_path: Path) -> None:
    target_id, _, payload = _setup_candidate(tmp_path, "knowledge-20260520-001")
    knowledge_accept(
        tmp_path,
        candidate_id=target_id,
        decision="accept",
        reviewed_by="user",
        title="Target",
        summary=payload["summary"],
        content=payload["content"],
        evidence=payload["evidence"],
        bindto=payload["bindto"],
    )
    candidate_id, _, candidate_payload = _setup_candidate(tmp_path, "knowledge-20260520-002")

    result = knowledge_merge(
        tmp_path,
        candidate_id=candidate_id,
        target_knowledge_id=target_id,
        decision="merge",
        reviewed_by="user",
        title="Merged",
        summary="Merged summary.",
        content="Merged content.",
        evidence=candidate_payload["evidence"],
        bindto=candidate_payload["bindto"],
    ).to_dict()

    assert result["status"] == "success"
    assert result["knowledge_id"] == target_id
    assert (tmp_path / "candidates/rejected" / f"{candidate_id}.md").exists()
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        f"knowledge/atomic/{target_id}.md"
    )
    assert document.frontmatter["summary"] == "Merged summary."


def test_merge_rejects_evidence_that_does_not_reference_source(tmp_path: Path) -> None:
    target_id, _, payload = _setup_candidate(tmp_path, "knowledge-20260520-001")
    knowledge_accept(
        tmp_path,
        candidate_id=target_id,
        decision="accept",
        reviewed_by="user",
        title="Target",
        summary=payload["summary"],
        content=payload["content"],
        evidence=payload["evidence"],
        bindto=payload["bindto"],
    )
    candidate_id, _, candidate_payload = _setup_candidate(tmp_path, "knowledge-20260520-002")

    result = knowledge_merge(
        tmp_path,
        candidate_id=candidate_id,
        target_knowledge_id=target_id,
        decision="merge",
        reviewed_by="user",
        title="Merged",
        summary="Merged summary.",
        content="Merged content.",
        evidence=[
            {"source_id": target_id, "locator": "section 1", "quote": "not a source"}
        ],
        bindto=candidate_payload["bindto"],
    ).to_dict()

    assert result["status"] == "failed"
    assert "source objects only" in result["errors"][0]["message"]


def test_deprecate_knowledge_records_metadata(tmp_path: Path) -> None:
    candidate_id, _, payload = _setup_candidate(tmp_path)
    knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
        title="Accepted",
        summary=payload["summary"],
        content=payload["content"],
        evidence=payload["evidence"],
        bindto=payload["bindto"],
    )

    result = knowledge_deprecate(
        tmp_path,
        knowledge_id=candidate_id,
        decision="deprecate",
        reviewed_by="user",
        reason="Old.",
    ).to_dict()

    assert result["status"] == "success"
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        f"knowledge/atomic/{candidate_id}.md"
    )
    assert document.frontmatter["status"] == "deprecated"
