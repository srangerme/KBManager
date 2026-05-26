from __future__ import annotations

import re
from pathlib import Path

import kbmanager.application as application
from kbmanager.application import (
    candidate_create,
    candidate_defer,
    init_workspace,
    knowledge_accept,
    knowledge_deprecate,
    knowledge_merge,
    knowledge_reject,
    source_add,
)
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _source_llm_result(input_path: str = "incoming.md") -> dict[str, object]:
    return {
        "input_path": input_path,
        "title": "Source Title",
        "summary": "A useful source summary.",
        "cleaned_content": f"# Cleaned\n\nSource: {input_path}\n\nUseful cleaned content.",
        "tags": ["ai"],
        "authors": ["Author"],
    }


def _candidate_llm_result(source_id: str, candidate_id: str) -> dict[str, object]:
    return {
        "candidates": [
            {
                "id": candidate_id,
                "title": f"Candidate {candidate_id}",
                "body": "A candidate fact extracted from the source.",
                "source_refs": [source_id],
                "evidence": [
                    {
                        "source_id": source_id,
                        "locator": "section 1",
                        "quote": "Useful cleaned content.",
                    }
                ],
                "suggested_tags": ["ai"],
                "suggested_kb_ids": ["kb-20260520-001"],
                "relations": [],
            }
        ]
    }


def _create_source(tmp_path: Path) -> str:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n\nOriginal material.", encoding="utf-8")
    token = source_add(tmp_path, input_path="incoming.md").to_dict()["resume"]["token"]
    result = source_add(
        tmp_path,
        input_path="incoming.md",
        resume_token=token,
        llm_result=_source_llm_result(),
    )
    assert result.to_dict()["status"] == "success"
    return result.to_dict()["source"]["id"]


def _create_knowledgebase(tmp_path: Path, kb_id: str = "kb-20260520-001") -> None:
    path = tmp_path / f"knowledge/bases/{kb_id}.md"
    if path.exists():
        return
    ObjectRepository(Workspace(tmp_path)).write_markdown(
        f"knowledge/bases/{kb_id}.md",
        MarkdownDocument(
            frontmatter={
                "id": kb_id,
                "type": "knowledge-base",
                "title": "Research",
                "status": "active",
                "description": "Research knowledge.",
                "knowledge_ids": [],
                "tags": [],
                "created": "2026-05-20",
                "updated": "2026-05-20",
            },
            body="\n## Description\n\nResearch knowledge.\n",
        ),
    )


def _create_candidate(tmp_path: Path, candidate_id: str = "knowledge-20260520-001") -> str:
    source_id = _create_source(tmp_path)
    _create_knowledgebase(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=_candidate_llm_result(source_id, candidate_id),
    )
    assert result.to_dict()["status"] == "success"
    return candidate_id


def test_accept_without_user_review_needs_review_and_does_not_write(tmp_path: Path) -> None:
    candidate_id = _create_candidate(tmp_path)

    result = knowledge_accept(tmp_path, candidate_id=candidate_id)

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert data["review"] == {
        "required": True,
        "options": ["accept", "reject", "defer", "merge"],
    }
    assert (tmp_path / f"candidates/pending/{candidate_id}.md").is_file()
    assert not (tmp_path / f"knowledge/atomic/{candidate_id}.md").exists()


def test_accept_promotes_pending_candidate_to_knowledge(tmp_path: Path) -> None:
    candidate_id = _create_candidate(tmp_path)

    result = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
        title="Accepted Knowledge",
        body="Reviewed knowledge body.",
        tags=["reviewed"],
        kb_ids=[],
        relations=[],
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["knowledge_id"] == candidate_id
    assert not (tmp_path / f"candidates/pending/{candidate_id}.md").exists()
    knowledge_file = tmp_path / f"knowledge/atomic/{candidate_id}.md"
    assert knowledge_file.is_file()
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        f"knowledge/atomic/{candidate_id}.md"
    )
    assert document.frontmatter["type"] == "knowledge"
    assert document.frontmatter["status"] == "accepted"
    assert document.frontmatter["review_decision"] == "accept"
    assert document.frontmatter["tags"] == ["reviewed"]
    assert document.frontmatter["kb_ids"] == []
    assert "Reviewed knowledge body." in document.body
    assert TIMESTAMP_RE.match(document.frontmatter["created"])
    assert TIMESTAMP_RE.match(document.frontmatter["updated"])
    assert TIMESTAMP_RE.match(document.frontmatter["reviewed_at"])


def test_accept_updates_knowledgebase_membership(tmp_path: Path) -> None:
    candidate_id = _create_candidate(tmp_path)

    result = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
        title="Accepted Knowledge",
        body="Reviewed knowledge body.",
        tags=["reviewed"],
        kb_ids=["kb-20260520-001"],
        relations=[],
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["warnings"] == []
    kb_document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        "knowledge/bases/kb-20260520-001.md"
    )
    assert kb_document.frontmatter["knowledge_ids"] == [candidate_id]
    assert "knowledge/bases/kb-20260520-001.md" in data["objects"]["updated"]


def test_accept_requires_reviewed_content_after_user_decision(tmp_path: Path) -> None:
    candidate_id = _create_candidate(tmp_path)

    result = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
    )

    data = result.to_dict()
    assert data["status"] == "failed"
    assert "reviewed title, body, tags, kb_ids, and relations" in data["errors"][0]["message"]
    assert (tmp_path / f"candidates/pending/{candidate_id}.md").is_file()
    assert not (tmp_path / f"knowledge/atomic/{candidate_id}.md").exists()


def test_accept_rejects_missing_reviewed_kb_and_relation_refs(tmp_path: Path) -> None:
    candidate_id = _create_candidate(tmp_path)

    missing_kb = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
        title="Accepted Knowledge",
        body="Reviewed knowledge body.",
        tags=[],
        kb_ids=["kb-20260520-404"],
        relations=[],
    )
    missing_relation = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
        title="Accepted Knowledge",
        body="Reviewed knowledge body.",
        tags=[],
        kb_ids=[],
        relations=[{"type": "related_to", "target": "knowledge-20260520-404"}],
    )

    assert missing_kb.to_dict()["status"] == "failed"
    assert missing_relation.to_dict()["status"] == "failed"
    assert (tmp_path / f"candidates/pending/{candidate_id}.md").is_file()
    assert not (tmp_path / f"knowledge/atomic/{candidate_id}.md").exists()


def test_reject_and_defer_require_review_and_move_candidate(tmp_path: Path) -> None:
    rejected_id = _create_candidate(tmp_path, "knowledge-20260520-001")
    deferred_id = _create_candidate(tmp_path, "knowledge-20260520-002")

    reject_gate = knowledge_reject(tmp_path, candidate_id=rejected_id)
    defer_gate = candidate_defer(tmp_path, candidate_id=deferred_id)
    rejected = knowledge_reject(
        tmp_path,
        candidate_id=rejected_id,
        decision="reject",
        reviewed_by="user",
        reason="Not useful.",
    )
    deferred = candidate_defer(
        tmp_path,
        candidate_id=deferred_id,
        decision="defer",
        reviewed_by="user",
        reason="Needs more evidence.",
    )

    assert reject_gate.to_dict()["status"] == "needs_review"
    assert defer_gate.to_dict()["status"] == "needs_review"
    assert rejected.to_dict()["status"] == "success"
    assert deferred.to_dict()["status"] == "success"
    rejected_doc = ObjectRepository(Workspace(tmp_path)).read_markdown(
        f"candidates/rejected/{rejected_id}.md"
    )
    deferred_doc = ObjectRepository(Workspace(tmp_path)).read_markdown(
        f"candidates/deferred/{deferred_id}.md"
    )
    assert rejected_doc.frontmatter["status"] == "rejected"
    assert rejected_doc.frontmatter["review"]["decision"] == "reject"
    assert deferred_doc.frontmatter["status"] == "deferred"
    assert deferred_doc.frontmatter["review"]["decision"] == "defer"
    assert not (tmp_path / f"candidates/pending/{rejected_id}.md").exists()
    assert not (tmp_path / f"candidates/pending/{deferred_id}.md").exists()


def test_non_pending_candidate_cannot_be_accepted(tmp_path: Path) -> None:
    candidate_id = _create_candidate(tmp_path)
    candidate_defer(
        tmp_path,
        candidate_id=candidate_id,
        decision="defer",
        reviewed_by="user",
        reason="Later.",
    )

    result = knowledge_accept(
        tmp_path,
        candidate_id=candidate_id,
        decision="accept",
        reviewed_by="user",
    )

    assert result.to_dict()["status"] == "failed"
    assert not (tmp_path / f"knowledge/atomic/{candidate_id}.md").exists()


def test_merge_updates_target_knowledge_and_rejects_source_candidate(tmp_path: Path) -> None:
    target_id = _create_candidate(tmp_path, "knowledge-20260520-001")
    knowledge_accept(
        tmp_path,
        candidate_id=target_id,
        decision="accept",
        reviewed_by="user",
        title="Base Knowledge",
        body="Base reviewed body.",
        tags=["base"],
        kb_ids=[],
        relations=[],
    )
    candidate_id = _create_candidate(tmp_path, "knowledge-20260520-002")

    result = knowledge_merge(
        tmp_path,
        candidate_id=candidate_id,
        target_knowledge_id=target_id,
        decision="merge",
        reviewed_by="user",
        body="Merged reviewed body.",
        tags=["base", "merged"],
        kb_ids=[],
        relations=[{"type": "agrees", "target": target_id}],
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["knowledge_id"] == target_id
    assert "replacement_refs" not in data
    repository = ObjectRepository(Workspace(tmp_path))
    target_doc = repository.read_markdown(f"knowledge/atomic/{target_id}.md")
    candidate_doc = repository.read_markdown(f"candidates/rejected/{candidate_id}.md")
    assert target_doc.frontmatter["tags"] == ["base", "merged"]
    assert target_doc.frontmatter["kb_ids"] == []
    assert target_doc.frontmatter["relations"] == [{"type": "agrees", "target": target_id}]
    assert "Merged reviewed body." in target_doc.body
    assert candidate_doc.frontmatter["status"] == "rejected"
    assert candidate_doc.frontmatter["review"]["decision"] == "merge"
    assert "replacement_refs" not in candidate_doc.frontmatter
    assert not (tmp_path / f"knowledge/atomic/{candidate_id}.md").exists()


def test_merge_syncs_knowledgebase_membership_changes(tmp_path: Path) -> None:
    _create_knowledgebase(tmp_path, "kb-20260520-002")
    target_id = _create_candidate(tmp_path, "knowledge-20260520-001")
    knowledge_accept(
        tmp_path,
        candidate_id=target_id,
        decision="accept",
        reviewed_by="user",
        title="Base Knowledge",
        body="Base reviewed body.",
        tags=["base"],
        kb_ids=["kb-20260520-001"],
        relations=[],
    )
    candidate_id = _create_candidate(tmp_path, "knowledge-20260520-002")

    result = knowledge_merge(
        tmp_path,
        candidate_id=candidate_id,
        target_knowledge_id=target_id,
        decision="merge",
        reviewed_by="user",
        body="Merged reviewed body.",
        tags=["base", "merged"],
        kb_ids=["kb-20260520-002"],
        relations=[],
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["warnings"] == []
    repository = ObjectRepository(Workspace(tmp_path))
    old_kb = repository.read_markdown("knowledge/bases/kb-20260520-001.md")
    new_kb = repository.read_markdown("knowledge/bases/kb-20260520-002.md")
    assert old_kb.frontmatter["knowledge_ids"] == []
    assert new_kb.frontmatter["knowledge_ids"] == [target_id]


def test_merge_requires_reviewed_content_after_user_decision(tmp_path: Path) -> None:
    target_id = _create_candidate(tmp_path, "knowledge-20260520-001")
    knowledge_accept(
        tmp_path,
        candidate_id=target_id,
        decision="accept",
        reviewed_by="user",
        title="Base Knowledge",
        body="Base reviewed body.",
        tags=["base"],
        kb_ids=[],
        relations=[],
    )
    candidate_id = _create_candidate(tmp_path, "knowledge-20260520-002")

    result = knowledge_merge(
        tmp_path,
        candidate_id=candidate_id,
        target_knowledge_id=target_id,
        decision="merge",
        reviewed_by="user",
    )

    data = result.to_dict()
    assert data["status"] == "failed"
    assert "merge requires reviewed body" in data["errors"][0]["message"]
    assert (tmp_path / f"candidates/pending/{candidate_id}.md").is_file()


def test_merge_rolls_back_target_knowledge_when_candidate_move_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_id = _create_candidate(tmp_path, "knowledge-20260520-001")
    knowledge_accept(
        tmp_path,
        candidate_id=target_id,
        decision="accept",
        reviewed_by="user",
        title="Base Knowledge",
        body="Base reviewed body.",
        tags=["base"],
        kb_ids=[],
        relations=[],
    )
    candidate_id = _create_candidate(tmp_path, "knowledge-20260520-002")
    target_file = tmp_path / f"knowledge/atomic/{target_id}.md"
    original_target = target_file.read_text(encoding="utf-8")

    def fail_candidate_move(*args, **kwargs):
        raise OSError("simulated candidate move failure")

    monkeypatch.setattr(application, "_move_candidate_document", fail_candidate_move)

    result = knowledge_merge(
        tmp_path,
        candidate_id=candidate_id,
        target_knowledge_id=target_id,
        decision="merge",
        reviewed_by="user",
        body="Merged reviewed body.",
        tags=["base", "merged"],
        kb_ids=[],
        relations=[{"type": "agrees", "target": target_id}],
    )

    assert result.to_dict()["status"] == "failed"
    assert target_file.read_text(encoding="utf-8") == original_target
    assert (tmp_path / f"candidates/pending/{candidate_id}.md").is_file()
    assert not (tmp_path / f"candidates/rejected/{candidate_id}.md").exists()


def test_deprecate_knowledge_records_deprecation_metadata(tmp_path: Path) -> None:
    deprecated_id = _create_candidate(tmp_path, "knowledge-20260520-001")
    knowledge_accept(
        tmp_path,
        candidate_id=deprecated_id,
        decision="accept",
        reviewed_by="user",
        title="Deprecated Knowledge",
        body="Deprecated reviewed body.",
        tags=[],
        kb_ids=[],
        relations=[],
    )

    gate = knowledge_deprecate(tmp_path, knowledge_id=deprecated_id)
    result = knowledge_deprecate(
        tmp_path,
        knowledge_id=deprecated_id,
        decision="deprecate",
        reviewed_by="user",
        reason="Superseded.",
    )

    assert gate.to_dict()["status"] == "needs_review"
    assert gate.to_dict()["review"]["options"] == ["deprecate", "revise"]
    data = result.to_dict()
    assert data["status"] == "success"
    assert "replacement_refs" not in data
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        f"knowledge/atomic/{deprecated_id}.md"
    )
    assert document.frontmatter["status"] == "deprecated"
    assert document.frontmatter["deprecated_reason"] == "Superseded."
    assert "replacement_refs" not in document.frontmatter
    assert TIMESTAMP_RE.match(document.frontmatter["updated"])
    assert TIMESTAMP_RE.match(document.frontmatter["reviewed_at"])
    assert TIMESTAMP_RE.match(document.frontmatter["deprecated_at"])
