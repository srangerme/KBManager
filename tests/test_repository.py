from __future__ import annotations

import pytest

from kbmanager.errors import RepositoryError, WorkspacePathError
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace


def metadata(object_id: str = "source-1", object_type: str = "source") -> dict[str, object]:
    return {
        "id": object_id,
        "type": object_type,
        "title": "Example",
        "status": "raw",
        "created": "2026-05-20",
        "updated": "2026-05-20",
    }


def test_reads_markdown_frontmatter_and_body(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    path = workspace.ensure_parent("data/raw/md/example.md")
    path.write_text(
        "---\n"
        "id: source-1\n"
        "type: source\n"
        "title: Example\n"
        "status: raw\n"
        "created: '2026-05-20'\n"
        "updated: '2026-05-20'\n"
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )

    document = repository.read_markdown("data/raw/md/example.md")

    assert document.frontmatter == metadata()
    assert document.body == "# Body\n"


def test_writes_markdown_frontmatter_and_body(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    repository.write_markdown(
        "candidates/pending/knowledge-1.md",
        MarkdownDocument(
            frontmatter={
                **metadata("knowledge-1", "candidate"),
                "status": "pending",
                "tags": ["ai"],
            },
            body="## Candidate\n",
        ),
    )

    text = (workspace.root / "candidates/pending/knowledge-1.md").read_text(encoding="utf-8")
    assert text == (
        "---\n"
        "id: knowledge-1\n"
        "type: candidate\n"
        "title: Example\n"
        "status: pending\n"
        "created: '2026-05-20'\n"
        "updated: '2026-05-20'\n"
        "tags:\n"
        "- ai\n"
        "---\n"
        "## Candidate\n"
    )


def test_missing_frontmatter_fails(repository: ObjectRepository, workspace: Workspace) -> None:
    path = workspace.ensure_parent("data/raw/md/no-frontmatter.md")
    path.write_text("# Body\n", encoding="utf-8")

    with pytest.raises(RepositoryError, match="missing YAML frontmatter"):
        repository.read_markdown("data/raw/md/no-frontmatter.md")


def test_invalid_frontmatter_yaml_fails(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    path = workspace.ensure_parent("data/raw/md/bad.md")
    path.write_text("---\nid: [unterminated\n---\n# Body\n", encoding="utf-8")

    with pytest.raises(RepositoryError, match="invalid YAML frontmatter"):
        repository.read_markdown("data/raw/md/bad.md")


def test_markdown_object_must_not_have_sidecar_meta(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    md_path = workspace.ensure_parent("data/raw/md/example.md")
    md_path.write_text(
        "---\n"
        "id: source-1\n"
        "type: source\n"
        "title: Example\n"
        "status: raw\n"
        "created: 2026-05-20\n"
        "updated: 2026-05-20\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    (workspace.root / "data/raw/md/example.meta.yml").write_text("id: source-1\n", encoding="utf-8")

    with pytest.raises(RepositoryError, match="must not have sidecar"):
        repository.read_markdown("data/raw/md/example.md")


def test_pdf_source_reads_and_writes_sidecar_meta(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    pdf = workspace.ensure_parent("data/raw/pdf/example.pdf")
    pdf.write_bytes(b"%PDF")

    meta_path = repository.write_meta(
        "data/raw/pdf/example.pdf",
        {**metadata(), "source_type": "pdf"},
    )

    assert meta_path == workspace.root / "data/raw/pdf/example.meta.yml"
    assert repository.read_meta("data/raw/pdf/example.pdf") == {
        "id": "source-1",
        "type": "source",
        "title": "Example",
        "status": "raw",
        "created": "2026-05-20",
        "updated": "2026-05-20",
        "source_type": "pdf",
    }


def test_markdown_resource_rejects_meta_api(repository: ObjectRepository) -> None:
    with pytest.raises(RepositoryError, match="frontmatter"):
        repository.write_meta("data/raw/md/example.md", {"id": "source-1"})


def test_write_rejects_path_escape(repository: ObjectRepository) -> None:
    with pytest.raises(WorkspacePathError):
        repository.write_markdown(
            "../outside.md",
            MarkdownDocument(frontmatter=metadata("x"), body="body\n"),
        )


def test_atomic_write_does_not_touch_other_files(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    other = workspace.ensure_parent("data/raw/md/other.md")
    other.write_text("keep me", encoding="utf-8")

    repository.write_markdown(
        "data/raw/md/example.md",
        MarkdownDocument(frontmatter=metadata(), body="body\n"),
    )

    assert other.read_text(encoding="utf-8") == "keep me"


def test_missing_required_frontmatter_field_fails(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    path = workspace.ensure_parent("data/raw/md/missing-type.md")
    path.write_text(
        "---\n"
        "id: source-1\n"
        "title: Example\n"
        "status: raw\n"
        "created: 2026-05-20\n"
        "updated: 2026-05-20\n"
        "---\n"
        "# Body\n",
        encoding="utf-8",
    )

    with pytest.raises(RepositoryError, match="missing required metadata fields.*type"):
        repository.read_markdown("data/raw/md/missing-type.md")


def test_write_rejects_existing_target_without_overwrite(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    existing = workspace.ensure_parent("data/raw/md/example.md")
    existing.write_text("user content", encoding="utf-8")

    with pytest.raises(RepositoryError, match="target already exists"):
        repository.write_markdown(
            "data/raw/md/example.md",
            MarkdownDocument(frontmatter=metadata(), body="body\n"),
        )

    assert existing.read_text(encoding="utf-8") == "user content"


def test_write_allows_explicit_overwrite(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    existing = workspace.ensure_parent("data/raw/md/example.md")
    existing.write_text(
        "---\n"
        "id: source-1\n"
        "type: source\n"
        "title: Old\n"
        "status: raw\n"
        "created: 2026-05-20\n"
        "updated: 2026-05-20\n"
        "---\n"
        "old\n",
        encoding="utf-8",
    )

    repository.write_markdown(
        "data/raw/md/example.md",
        MarkdownDocument(frontmatter=metadata(), body="new\n"),
        overwrite=True,
    )

    assert repository.read_markdown("data/raw/md/example.md").body == "new\n"


def test_markdown_write_preserves_body_exactly(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    repository.write_markdown(
        "data/raw/md/example.md",
        MarkdownDocument(frontmatter=metadata(), body="\n# Heading\n\nBody\n"),
    )

    document = repository.read_markdown("data/raw/md/example.md")

    assert document.body == "\n# Heading\n\nBody\n"


def test_write_meta_rejects_missing_resource(repository: ObjectRepository) -> None:
    with pytest.raises(RepositoryError, match="resource file not found"):
        repository.write_meta("data/raw/pdf/missing.pdf", metadata())


def test_read_meta_rejects_missing_resource(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    meta_path = workspace.ensure_parent("data/raw/pdf/missing.meta.yml")
    meta_path.write_text(
        "id: source-1\n"
        "type: source\n"
        "title: Example\n"
        "status: raw\n"
        "created: 2026-05-20\n"
        "updated: 2026-05-20\n",
        encoding="utf-8",
    )

    with pytest.raises(RepositoryError, match="resource file not found"):
        repository.read_meta("data/raw/pdf/missing.pdf")


def test_move_file_updates_source_and_target_state(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    source = workspace.ensure_parent("candidates/pending/knowledge-1.md")
    source.write_text("candidate", encoding="utf-8")

    target = repository.move_file(
        "candidates/pending/knowledge-1.md",
        "candidates/deferred/knowledge-1.md",
    )

    assert target == workspace.root / "candidates/deferred/knowledge-1.md"
    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "candidate"


def test_move_file_rejects_existing_target_without_overwrite(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    source = workspace.ensure_parent("candidates/pending/knowledge-1.md")
    source.write_text("candidate", encoding="utf-8")
    target = workspace.ensure_parent("candidates/deferred/knowledge-1.md")
    target.write_text("existing", encoding="utf-8")

    with pytest.raises(RepositoryError, match="target already exists"):
        repository.move_file(
            "candidates/pending/knowledge-1.md",
            "candidates/deferred/knowledge-1.md",
        )

    assert source.exists()
    assert target.read_text(encoding="utf-8") == "existing"


def test_scans_workspace_and_finds_duplicate_ids(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    repository.write_markdown(
        "data/raw/md/source.md",
        MarkdownDocument(frontmatter=metadata("duplicate-id", "source"), body="source\n"),
    )
    repository.write_markdown(
        "knowledge/atomic/knowledge.md",
        MarkdownDocument(
            frontmatter={**metadata("duplicate-id", "knowledge"), "status": "accepted"},
            body="knowledge\n",
        ),
    )
    repository.write_markdown(
        "notes/active/note.md",
        MarkdownDocument(
            frontmatter={**metadata("note-1", "note"), "status": "active"},
            body="note\n",
        ),
    )

    duplicates = repository.find_duplicate_ids()

    assert set(duplicates) == {"duplicate-id"}
    assert {path.name for path in duplicates["duplicate-id"]} == {"source.md", "knowledge.md"}


def test_scans_pdf_sidecar_metadata(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    pdf = workspace.ensure_parent("data/raw/pdf/example.pdf")
    pdf.write_bytes(b"%PDF")
    repository.write_meta("data/raw/pdf/example.pdf", {**metadata(), "source_type": "pdf"})

    ids = repository.scan_object_ids()

    assert list(ids) == ["source-1"]
    assert ids["source-1"] == [workspace.root / "data/raw/pdf/example.meta.yml"]


def test_pdf_source_without_sidecar_meta_fails_scan(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    pdf = workspace.ensure_parent("data/raw/pdf/example.pdf")
    pdf.write_bytes(b"%PDF")

    with pytest.raises(RepositoryError, match="raw source has no sidecar metadata"):
        repository.scan_object_ids()


def test_sidecar_meta_without_resource_fails_scan(
    repository: ObjectRepository,
    workspace: Workspace,
) -> None:
    meta_path = workspace.ensure_parent("data/raw/pdf/missing.meta.yml")
    meta_path.write_text(
        "id: source-1\n"
        "type: source\n"
        "title: Example\n"
        "status: raw\n"
        "created: 2026-05-20\n"
        "updated: 2026-05-20\n",
        encoding="utf-8",
    )

    with pytest.raises(RepositoryError, match="metadata sidecar has no resource file"):
        repository.scan_object_ids()
