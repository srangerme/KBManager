from __future__ import annotations

from pathlib import Path

from kbmanager.application import index_rebuild, init_workspace
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace


def _repository(tmp_path: Path) -> ObjectRepository:
    return ObjectRepository(Workspace(tmp_path))


def _write_markdown(
    tmp_path: Path,
    relative_path: str,
    frontmatter: dict[str, object],
    body: str = "\n## Body\n\nContent.\n",
) -> None:
    _repository(tmp_path).write_markdown(
        relative_path,
        MarkdownDocument(frontmatter=frontmatter, body=body),
    )


def _seed_index_objects(tmp_path: Path) -> None:
    _write_markdown(
        tmp_path,
        "data/raw/md/source-20260520-001.md",
        {
            "id": "source-20260520-001",
            "type": "source",
            "title": "Source One",
            "status": "raw",
            "summary": "Source summary.",
            "tags": ["source-tag"],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "data/raw/md/source-20260520-002.md",
        {
            "id": "source-20260520-002",
            "type": "source",
            "title": "Deprecated Source",
            "status": "deprecated",
            "summary": "Deprecated source summary.",
            "tags": ["deprecated-tag"],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "knowledge/bases/kb-20260520-001.md",
        {
            "id": "kb-20260520-001",
            "type": "knowledge-base",
            "title": "Research KB",
            "status": "active",
            "description": "Research knowledge.",
            "knowledge_ids": ["knowledge-20260520-001"],
            "tags": ["kb-tag"],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "knowledge/atomic/knowledge-20260520-001.md",
        {
            "id": "knowledge-20260520-001",
            "type": "knowledge",
            "title": "Accepted Knowledge",
            "status": "accepted",
            "tags": ["accepted-tag"],
            "source_refs": ["source-20260520-001"],
            "evidence": [
                {
                    "source_id": "source-20260520-001",
                    "locator": "section 1",
                    "quote": "Content.",
                }
            ],
            "kb_ids": ["kb-20260520-001"],
            "relations": [],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "knowledge/atomic/knowledge-20260520-099.md",
        {
            "id": "knowledge-20260520-099",
            "type": "knowledge",
            "title": "Deprecated Knowledge",
            "status": "deprecated",
            "tags": ["deprecated-tag"],
            "source_refs": ["source-20260520-002"],
            "evidence": [
                {
                    "source_id": "source-20260520-002",
                    "locator": "section 9",
                    "quote": "Deprecated.",
                }
            ],
            "kb_ids": [],
            "relations": [{"type": "related", "target": "knowledge-20260520-001"}],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "candidates/pending/knowledge-20260520-002.md",
        {
            "id": "knowledge-20260520-002",
            "type": "candidate",
            "title": "Pending Candidate",
            "status": "pending",
            "source_refs": ["source-20260520-001"],
            "note_refs": [],
            "suggested_tags": ["candidate-tag"],
            "suggested_kb_ids": ["kb-20260520-001"],
            "evidence": [
                {
                    "source_id": "source-20260520-001",
                    "locator": "section 2",
                    "quote": "Content.",
                }
            ],
            "relations": [],
            "review": {
                "reviewed_by": None,
                "reviewed_at": None,
                "decision": None,
                "reason": None,
            },
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "notes/bound/note-20260520-001.md",
        {
            "id": "note-20260520-001",
            "type": "note",
            "title": "Bound Note",
            "status": "bound",
            "bindings": [{"type": "knowledge", "id": "knowledge-20260520-001"}],
            "tags": ["note-tag"],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "notes/deprecated/note-20260520-099.md",
        {
            "id": "note-20260520-099",
            "type": "note",
            "title": "Deprecated Note",
            "status": "deprecated",
            "bindings": [{"type": "source", "id": "source-20260520-002"}],
            "tags": ["deprecated-tag"],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )


def test_index_rebuild_dry_run_returns_diffs_without_writing(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_index_objects(tmp_path)
    original = (tmp_path / "indexes/knowledge-index.md").read_text(encoding="utf-8")

    result = index_rebuild(tmp_path, dry_run=True)

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["issues"] == []
    assert any(diff["path"] == "indexes/knowledge-index.md" for diff in data["diffs"])
    assert (tmp_path / "indexes/knowledge-index.md").read_text(encoding="utf-8") == original
    assert "Accepted Knowledge" in next(
        diff["after"] for diff in data["diffs"] if diff["path"] == "indexes/knowledge-index.md"
    )


def test_index_rebuild_repairs_damaged_indexes_from_objects(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_index_objects(tmp_path)
    (tmp_path / "indexes/knowledge-index.md").write_text("corrupt index\n", encoding="utf-8")

    result = index_rebuild(tmp_path)

    data = result.to_dict()
    assert data["status"] == "success"
    assert "Accepted Knowledge" in (tmp_path / "indexes/knowledge-index.md").read_text(
        encoding="utf-8"
    )
    assert "corrupt index" not in (tmp_path / "indexes/knowledge-index.md").read_text(
        encoding="utf-8"
    )
    assert "Source One" in (tmp_path / "indexes/source-index.md").read_text(encoding="utf-8")
    assert "Deprecated Source" not in (tmp_path / "indexes/source-index.md").read_text(
        encoding="utf-8"
    )
    assert "Pending Candidate" in (tmp_path / "indexes/review-queue.md").read_text(encoding="utf-8")
    assert (tmp_path / "indexes/knowledgebase/kb-20260520-001-knowledge-index.md").is_file()


def test_index_rebuild_hides_deprecated_objects_from_list_indexes(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_index_objects(tmp_path)

    result = index_rebuild(tmp_path)

    assert result.to_dict()["status"] == "success"
    index_paths = [
        "indexes/source-index.md",
        "indexes/knowledge-index.md",
        "indexes/tag-index.md",
        "indexes/relation-index.yml",
        "indexes/kb-index.md",
        "indexes/note-index.md",
        "indexes/knowledgebase/kb-20260520-001-knowledge-index.md",
    ]
    combined = "\n".join(
        (tmp_path / path).read_text(encoding="utf-8") for path in index_paths
    )
    assert "Deprecated Source" not in combined
    assert "Deprecated Knowledge" not in combined
    assert "Deprecated Note" not in combined
    assert "source-20260520-002" not in combined
    assert "knowledge-20260520-099" not in combined
    assert "note-20260520-099" not in combined


def test_index_rebuild_supports_scope_and_object_id(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_index_objects(tmp_path)
    (tmp_path / "indexes/source-index.md").write_text("bad source\n", encoding="utf-8")
    (tmp_path / "indexes/knowledge-index.md").write_text("bad knowledge\n", encoding="utf-8")

    source_only = index_rebuild(tmp_path, scope="source")
    kb_only = index_rebuild(
        tmp_path,
        scope="knowledgebase",
        object_id="kb-20260520-001",
        dry_run=True,
    )

    assert source_only.to_dict()["status"] == "success"
    assert "Source One" in (tmp_path / "indexes/source-index.md").read_text(encoding="utf-8")
    assert (tmp_path / "indexes/knowledge-index.md").read_text(encoding="utf-8") == (
        "bad knowledge\n"
    )
    assert {
        "indexes/kb-index.md",
        "indexes/knowledgebase/kb-20260520-001-knowledge-index.md",
    } == {diff["path"] for diff in kb_only.to_dict()["diffs"]}


def test_index_rebuild_rejects_task_scope(tmp_path: Path) -> None:
    init_workspace(tmp_path)

    result = index_rebuild(tmp_path, scope="task")

    assert result.to_dict()["status"] == "failed"
    assert "task" not in result.to_dict()["errors"][0]["message"]


def test_index_rebuild_reports_consistency_issues(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _write_markdown(
        tmp_path,
        "candidates/pending/knowledge-20260520-001.md",
        {
            "id": "knowledge-20260520-001",
            "type": "candidate",
            "title": "Candidate",
            "status": "pending",
            "source_refs": ["source-20260520-404"],
            "note_refs": [],
            "suggested_tags": [],
            "suggested_kb_ids": [],
            "evidence": [
                {
                    "source_id": "source-20260520-404",
                    "locator": "section 1",
                    "quote": "Missing.",
                }
            ],
            "relations": [],
            "review": {
                "reviewed_by": None,
                "reviewed_at": None,
                "decision": None,
                "reason": None,
            },
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "knowledge/atomic/knowledge-20260520-001.md",
        {
            "id": "knowledge-20260520-001",
            "type": "knowledge",
            "title": "Knowledge",
            "status": "accepted",
            "tags": [],
            "source_refs": [],
            "evidence": [],
            "kb_ids": [],
            "relations": [],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )

    result = index_rebuild(tmp_path, dry_run=True)

    data = result.to_dict()
    issue_codes = {issue["code"] for issue in data["issues"]}
    assert data["status"] == "success"
    assert "candidate_knowledge_id_conflict" in issue_codes
    assert "duplicate_id" in issue_codes
    assert "missing_reference" in issue_codes


def test_index_rebuild_reports_knowledgebase_membership_mismatches(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _write_markdown(
        tmp_path,
        "knowledge/bases/kb-20260520-001.md",
        {
            "id": "kb-20260520-001",
            "type": "knowledge-base",
            "title": "Research KB",
            "status": "active",
            "description": "Research knowledge.",
            "knowledge_ids": ["knowledge-20260520-001"],
            "tags": [],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "knowledge/bases/kb-20260520-002.md",
        {
            "id": "kb-20260520-002",
            "type": "knowledge-base",
            "title": "Practice KB",
            "status": "active",
            "description": "Practice knowledge.",
            "knowledge_ids": [],
            "tags": [],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "knowledge/atomic/knowledge-20260520-001.md",
        {
            "id": "knowledge-20260520-001",
            "type": "knowledge",
            "title": "Accepted Knowledge",
            "status": "accepted",
            "tags": [],
            "source_refs": [],
            "evidence": [],
            "kb_ids": ["kb-20260520-002"],
            "relations": [],
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )

    result = index_rebuild(tmp_path, dry_run=True)

    data = result.to_dict()
    mismatches = [
        issue
        for issue in data["issues"]
        if issue["code"] == "knowledgebase_membership_mismatch"
    ]
    assert data["status"] == "success"
    assert {
        ("kb-20260520-001", "knowledge_ids", "knowledge-20260520-001"),
        ("knowledge-20260520-001", "kb_ids", "kb-20260520-002"),
    } == {
        (issue["object_id"], issue["field"], issue["target_id"])
        for issue in mismatches
    }
