from __future__ import annotations

from pathlib import Path

from kbmanager.application import index_rebuild, init_workspace, knowledgebase_map
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace


def _repo(tmp_path: Path) -> ObjectRepository:
    return ObjectRepository(Workspace(tmp_path))


def _write_markdown(
    tmp_path: Path,
    relative_path: str,
    frontmatter: dict[str, object],
    body: str = "\n## Body\n\nContent.\n",
) -> None:
    _repo(tmp_path).write_markdown(
        relative_path,
        MarkdownDocument(frontmatter=frontmatter, body=body),
    )


def _seed_new_model(tmp_path: Path, *, bad_outline: bool = False) -> None:
    _write_markdown(
        tmp_path,
        "data/raw/md/source-20260520-001.md",
        {
            "id": "source-20260520-001",
            "type": "source",
            "title": "Source One",
            "source_type": "markdown",
            "status": "raw",
            "path": "data/raw/md/source-20260520-001.md",
            "summary": "Source summary.",
            "cleaned": {},
            "deprecated_at": None,
            "deprecated_reason": None,
            "tags": ["source-tag"],
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
            "tags": ["kb-tag"],
            "scope": {"includes": ["research"], "excludes": []},
            "outline": [{"id": "sec1", "title": "Section 1"}],
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
            "summary": "Knowledge summary.",
            "evidence": [
                {"source_id": "source-20260520-001", "locator": "section 1", "quote": "Content."}
            ],
            "bindto": [
                {
                    "kb_id": "kb-20260520-001",
                    "outline_node": "missing" if bad_outline else "sec1",
                    "reason": "Fits.",
                }
            ],
            "deprecated_at": None,
            "deprecated_reason": None,
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )
    _write_markdown(
        tmp_path,
        "notes/active/note-20260520-001.md",
        {
            "id": "note-20260520-001",
            "type": "note",
            "title": "Active Note",
            "status": "active",
            "deprecated_at": None,
            "deprecated_reason": None,
            "created": "2026-05-20",
            "updated": "2026-05-20",
        },
    )


def test_index_rebuild_derives_knowledgebase_members_from_bindto(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_new_model(tmp_path)

    result = index_rebuild(tmp_path).to_dict()

    assert result["status"] == "success"
    kb_index = (tmp_path / "indexes/knowledgebase/kb-20260520-001-knowledge-index.md").read_text(
        encoding="utf-8"
    )
    assert "knowledge-20260520-001" in kb_index
    assert result["issues"] == []


def test_index_rebuild_reports_invalid_bindto_outline_node(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_new_model(tmp_path, bad_outline=True)

    result = index_rebuild(tmp_path, dry_run=True).to_dict()

    assert result["status"] == "success"
    assert result["issues"][0]["code"] == "invalid_bindto_outline_node"


def test_index_rebuild_dry_run_does_not_write(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_new_model(tmp_path)
    before = (tmp_path / "indexes/knowledge-index.md").read_text(encoding="utf-8")

    result = index_rebuild(tmp_path, dry_run=True).to_dict()

    assert result["status"] == "success"
    assert (tmp_path / "indexes/knowledge-index.md").read_text(encoding="utf-8") == before


def test_knowledgebase_map_writes_outline_bindto_mermaid(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    _seed_new_model(tmp_path)
    output = tmp_path / "map.md"

    result = knowledgebase_map(
        tmp_path,
        knowledgebase_id="kb-20260520-001",
        output_path=output,
    ).to_dict()

    markdown = output.read_text(encoding="utf-8")
    assert result["status"] == "success"
    assert "```mermaid" in markdown
    assert "Section 1" in markdown
    assert "Accepted Knowledge" in markdown
