from __future__ import annotations

from pathlib import Path

import pytest

from kbmanager.errors import RepositoryError
from kbmanager.object_paths import ObjectPaths
from kbmanager.workspace import Workspace


def test_resolves_known_object_paths(tmp_path: Path) -> None:
    paths = ObjectPaths(Workspace(tmp_path))

    assert paths.source_markdown("source-1.md") == tmp_path / "data/raw/md/source-1.md"
    assert paths.source_pdf("source-1.pdf") == tmp_path / "data/raw/pdf/source-1.pdf"
    assert paths.source_html("source-1.html") == tmp_path / "data/raw/html/source-1.html"
    assert paths.candidate("knowledge-1.md") == tmp_path / "candidates/pending/knowledge-1.md"
    assert (
        paths.candidate(
            "knowledge-1.md",
            status="rejected",
        )
        == tmp_path / "candidates/rejected/knowledge-1.md"
    )
    assert paths.knowledge("knowledge-1.md") == tmp_path / "knowledge/atomic/knowledge-1.md"
    assert paths.knowledgebase("kb-1.md") == tmp_path / "knowledge/bases/kb-1.md"
    assert paths.note("note-1.md", status="bound") == tmp_path / "notes/bound/note-1.md"
    assert paths.note("note-1.md", status="archived") == tmp_path / "notes/archive/note-1.md"
    assert paths.index("source-index.md") == tmp_path / "indexes/source-index.md"
    assert paths.index("relation-index.yml") == tmp_path / "indexes/relation-index.yml"
    assert (
        paths.knowledgebase_index("kb-1-knowledge-index.md")
        == tmp_path / "indexes/knowledgebase/kb-1-knowledge-index.md"
    )


def test_rejects_filename_with_directory(tmp_path: Path) -> None:
    paths = ObjectPaths(Workspace(tmp_path))

    with pytest.raises(RepositoryError, match="must not include directories"):
        paths.knowledge("../knowledge-1.md")


def test_rejects_wrong_suffix(tmp_path: Path) -> None:
    paths = ObjectPaths(Workspace(tmp_path))

    with pytest.raises(RepositoryError, match="must end with .md"):
        paths.candidate("knowledge-1.txt")


def test_rejects_unknown_candidate_status(tmp_path: Path) -> None:
    paths = ObjectPaths(Workspace(tmp_path))

    with pytest.raises(RepositoryError, match="unsupported candidate status"):
        paths.candidate("knowledge-1.md", status="accepted")


def test_rejects_unknown_note_status(tmp_path: Path) -> None:
    paths = ObjectPaths(Workspace(tmp_path))

    with pytest.raises(RepositoryError, match="unsupported note status"):
        paths.note("note-1.md", status="archive")


def test_rejects_unknown_index_suffix(tmp_path: Path) -> None:
    paths = ObjectPaths(Workspace(tmp_path))

    with pytest.raises(RepositoryError, match="index filename must end"):
        paths.index("manifest.json")
