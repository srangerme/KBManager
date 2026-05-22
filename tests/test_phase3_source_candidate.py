from __future__ import annotations

import re
from pathlib import Path

import kbmanager.application as application
from kbmanager.application import (
    candidate_create,
    candidate_get,
    candidate_next_pending,
    init_workspace,
    source_add,
    source_deprecate,
)
from kbmanager.errors import RepositoryError
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _non_placeholder_names(path: Path) -> list[str]:
    return sorted(item.name for item in path.iterdir() if item.name != "KBM.ignore")


def _source_llm_result(input_path: str = "incoming.md") -> dict[str, object]:
    return {
        "input_path": input_path,
        "title": "Source Title",
        "summary": "A useful source summary.",
        "cleaned_content": f"# Cleaned\n\nSource: {input_path}\n\nUseful cleaned content.",
        "tags": ["ai"],
        "authors": ["Author"],
    }


def _candidate_llm_result(
    source_id: str,
    candidate_id: str = "knowledge-20260520-001",
) -> dict[str, object]:
    return {
        "candidates": [
            {
                "id": candidate_id,
                "title": "Candidate Title",
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
                "suggested_kb_ids": [],
            }
        ]
    }


def _create_source(tmp_path: Path) -> str:
    init_workspace(tmp_path)
    input_file = tmp_path / "incoming.md"
    input_file.write_text("# Raw\n\nOriginal material.", encoding="utf-8")
    first = source_add(tmp_path, input_path="incoming.md")
    token = first.to_dict()["resume"]["token"]
    resumed = source_add(
        tmp_path,
        input_path="incoming.md",
        resume_token=token,
        llm_result=_source_llm_result(),
    )
    assert resumed.to_dict()["status"] == "success"
    return resumed.to_dict()["source"]["id"]


def test_source_add_needs_llm_does_not_write(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")

    result = source_add(tmp_path, input_path="incoming.md")

    data = result.to_dict()
    assert data["status"] == "needs_llm"
    assert data["llm_request"]["system_prompt"] == "source-ingest"
    assert data["llm_request"]["required_context"] == ["incoming.md"]
    assert data["resume"]["operation"] == "kb.source.add"
    assert _non_placeholder_names(tmp_path / "data/raw/md") == []
    assert _non_placeholder_names(tmp_path / "data/cleaned") == []


def test_source_add_dry_run_still_returns_needs_llm(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")

    result = source_add(tmp_path, input_path="incoming.md", dry_run=True)

    assert result.to_dict()["status"] == "needs_llm"
    assert _non_placeholder_names(tmp_path / "data/raw/md") == []


def test_source_add_resume_writes_source_and_cleaned(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)

    source_file = tmp_path / "data/raw/md" / f"{source_id}.md"
    cleaned_file = tmp_path / "data/cleaned" / f"{source_id}.md"
    assert source_file.is_file()
    assert cleaned_file.read_text(encoding="utf-8") == (
        "# Cleaned\n\nSource: incoming.md\n\nUseful cleaned content."
    )
    text = source_file.read_text(encoding="utf-8")
    assert f"id: {source_id}" in text
    assert "summary: A useful source summary." in text
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(f"data/raw/md/{source_id}.md")
    assert TIMESTAMP_RE.match(document.frontmatter["created"])
    assert TIMESTAMP_RE.match(document.frontmatter["updated"])
    assert TIMESTAMP_RE.match(document.frontmatter["imported_at"])
    assert TIMESTAMP_RE.match(document.frontmatter["cleaned"]["generated_at"])


def test_source_add_accepts_pdf_outside_workspace(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    external_pdf = (tmp_path.parent / f"{tmp_path.name}-external.pdf").resolve()
    external_pdf.write_bytes(b"%PDF-1.4\nexternal")
    input_ref = str(external_pdf)

    first = source_add(tmp_path, input_path=external_pdf)
    first_data = first.to_dict()

    assert first_data["status"] == "needs_llm"
    assert first_data["llm_request"]["required_context"] == [input_ref]
    token = first_data["resume"]["token"]

    result = source_add(
        tmp_path,
        input_path=external_pdf,
        resume_token=token,
        llm_result=_source_llm_result(input_ref),
    )

    data = result.to_dict()
    assert data["status"] == "success"
    source_id = data["source"]["id"]
    stored_pdf = tmp_path / "data/raw/pdf" / f"{source_id}.pdf"
    assert stored_pdf.read_bytes() == b"%PDF-1.4\nexternal"
    metadata = ObjectRepository(Workspace(tmp_path)).read_meta(
        f"data/raw/pdf/{source_id}.pdf"
    )
    assert metadata["source_type"] == "pdf"
    assert metadata["cleaned"]["input_path"] == input_ref


def test_source_add_accepts_url_source(tmp_path: Path, monkeypatch) -> None:
    init_workspace(tmp_path)
    source_url = "https://example.com/research/article"
    monkeypatch.setattr(
        application,
        "_download_url_as_html",
        lambda url: (
            "<!doctype html>\n"
            "<html><body><article><h1>Downloaded</h1>"
            "<p>Downloaded article body.</p></article></body></html>\n"
        ),
    )
    first = source_add(tmp_path, input_path=source_url)
    first_data = first.to_dict()
    token = first_data["resume"]["token"]

    assert first_data["llm_request"]["context_documents"] == [
        {
            "input_path": source_url,
            "content": (
                "<!doctype html>\n"
                "<html><body><article><h1>Downloaded</h1>"
                "<p>Downloaded article body.</p></article></body></html>\n"
            ),
        }
    ]

    result = source_add(
        tmp_path,
        input_path=source_url,
        resume_token=token,
        llm_result=_source_llm_result(source_url),
    )

    data = result.to_dict()
    assert data["status"] == "success"
    source_id = data["source"]["id"]
    metadata = ObjectRepository(Workspace(tmp_path)).read_meta(
        f"data/raw/html/{source_id}.html"
    )
    assert metadata["source_type"] == "url"
    assert metadata["cleaned"]["input_path"] == source_url
    html = (tmp_path / "data/raw/html" / f"{source_id}.html").read_text(encoding="utf-8")
    assert "Downloaded article body." in html
    assert (tmp_path / "data/cleaned" / f"{source_id}.md").is_file()


def test_source_add_url_download_failure_requests_pdf_or_markdown_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    init_workspace(tmp_path)
    source_url = "https://example.com/research/article"

    def blocked_download(url: str) -> str:
        raise RepositoryError(f"could not download URL source: {url}: 403 Forbidden")

    def blocked_pdf_export(workspace: Workspace, url: str) -> Path:
        raise RepositoryError(f"could not export URL as PDF with Playwright: {url}: blocked")

    monkeypatch.setattr(application, "_download_url_as_html", blocked_download)
    monkeypatch.setattr(
        application,
        "_download_url_as_pdf_with_playwright",
        blocked_pdf_export,
    )

    result = source_add(tmp_path, input_path=source_url)

    data = result.to_dict()
    assert data["status"] == "failed"
    assert "Playwright PDF export failed" in data["errors"][0]["suggestion"]
    assert "data/failed" in data["errors"][0]["message"]
    assert "Review the matching report under data/failed." in data["next_actions"]
    reports = list((tmp_path / "data/failed").glob("url-*.json"))
    assert len(reports) == 1
    report = reports[0].read_text(encoding="utf-8")
    assert source_url in report
    assert "403 Forbidden" in report
    assert "source_added" in report


def test_source_add_url_download_failure_uses_playwright_pdf_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    init_workspace(tmp_path)
    source_url = "https://example.com/research/article"

    def blocked_download(url: str) -> str:
        raise RepositoryError(f"could not download URL source: {url}: 403 Forbidden")

    def exported_pdf(workspace: Workspace, url: str) -> Path:
        path = workspace.ensure_parent("data/attachments/url-captures/exported.pdf")
        path.write_bytes(b"%PDF-1.4\nexported")
        return path

    monkeypatch.setattr(application, "_download_url_as_html", blocked_download)
    monkeypatch.setattr(application, "_download_url_as_pdf_with_playwright", exported_pdf)

    first = source_add(tmp_path, input_path=source_url)
    first_data = first.to_dict()
    captured_path = "data/attachments/url-captures/exported.pdf"
    token = first_data["resume"]["token"]

    assert first_data["llm_request"]["required_context"] == [captured_path]
    assert "context_documents" not in first_data["llm_request"]

    result = source_add(
        tmp_path,
        input_path=source_url,
        resume_token=token,
        llm_result=_source_llm_result(captured_path),
    )

    data = result.to_dict()
    assert data["status"] == "success"
    source_id = data["source"]["id"]
    metadata = ObjectRepository(Workspace(tmp_path)).read_meta(
        f"data/raw/pdf/{source_id}.pdf"
    )
    assert metadata["source_type"] == "url_pdf"
    assert metadata["source_url"] == source_url
    assert metadata["cleaned"]["input_path"] == captured_path
    stored_pdf = tmp_path / "data/raw/pdf" / f"{source_id}.pdf"
    assert stored_pdf.read_bytes() == b"%PDF-1.4\nexported"
    assert not list((tmp_path / "data/failed").glob("url-*.json"))


def test_source_add_rejects_llm_result_without_matching_input_path(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")
    token = source_add(tmp_path, input_path="incoming.md").to_dict()["resume"]["token"]

    result = source_add(
        tmp_path,
        input_path="incoming.md",
        resume_token=token,
        llm_result=_source_llm_result("other.md"),
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "data/raw/md") == []


def test_source_add_rejects_cleaned_content_without_input_path(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")
    token = source_add(tmp_path, input_path="incoming.md").to_dict()["resume"]["token"]
    llm_result = _source_llm_result()
    llm_result["cleaned_content"] = "# Cleaned\n\nUseful cleaned content."

    result = source_add(
        tmp_path,
        input_path="incoming.md",
        resume_token=token,
        llm_result=llm_result,
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "data/raw/md") == []


def test_source_add_directory_treats_each_supported_file_as_source(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    batch = tmp_path / "incoming"
    batch.mkdir()
    (batch / "a.md").write_text("# A\n", encoding="utf-8")
    (batch / "b.pdf").write_bytes(b"%PDF")
    (batch / "ignore.txt").write_text("ignore", encoding="utf-8")

    first = source_add(tmp_path, input_path="incoming")
    token = first.to_dict()["resume"]["token"]
    result = source_add(
        tmp_path,
        input_path="incoming",
        resume_token=token,
        llm_result={
            "sources": [
                _source_llm_result("incoming/a.md"),
                _source_llm_result("incoming/b.pdf"),
            ]
        },
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert len(data["source_ids"]) == 2
    assert len(_non_placeholder_names(tmp_path / "data/raw/md")) == 1
    assert len(list((tmp_path / "data/raw/pdf").glob("*.pdf"))) == 1
    assert len(list((tmp_path / "data/raw/pdf").glob("*.meta.yml"))) == 1
    assert len(_non_placeholder_names(tmp_path / "data/cleaned")) == 2


def test_source_add_resume_token_must_match(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")

    result = source_add(
        tmp_path,
        input_path="incoming.md",
        resume_token="resume-wrong",
        llm_result=_source_llm_result(),
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "data/raw/md") == []


def test_source_add_rejects_invalid_user_metadata(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")

    bad_tags = source_add(tmp_path, input_path="incoming.md", tags="ai")  # type: ignore[arg-type]
    bad_authors = source_add(
        tmp_path,
        input_path="incoming.md",
        authors=["Author", 123],  # type: ignore[list-item]
    )
    bad_title = source_add(tmp_path, input_path="incoming.md", title="")

    assert bad_tags.to_dict()["status"] == "failed"
    assert "tags must be a list of strings" in bad_tags.to_dict()["errors"][0]["message"]
    assert bad_authors.to_dict()["status"] == "failed"
    assert "authors must be a list of strings" in bad_authors.to_dict()["errors"][0]["message"]
    assert bad_title.to_dict()["status"] == "failed"
    assert "title must be a non-empty string" in bad_title.to_dict()["errors"][0]["message"]
    assert _non_placeholder_names(tmp_path / "data/raw/md") == []


def test_candidate_create_needs_llm_does_not_write(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)

    result = candidate_create(tmp_path, source_ids=[source_id])

    data = result.to_dict()
    assert data["status"] == "needs_llm"
    assert data["llm_request"]["system_prompt"] == "candidate-create"
    assert data["llm_request"]["required_context"] == [source_id]
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_dry_run_still_returns_needs_llm(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)

    result = candidate_create(tmp_path, source_ids=[source_id], dry_run=True)

    data = result.to_dict()
    assert data["status"] == "needs_llm"
    assert data["llm_request"]["system_prompt"] == "candidate-create"
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_warns_when_source_is_deprecated(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    source_file = tmp_path / "data/raw/md" / f"{source_id}.md"
    text = source_file.read_text(encoding="utf-8")
    source_file.write_text(text.replace("status: raw", "status: deprecated"), encoding="utf-8")

    result = candidate_create(tmp_path, source_ids=[source_id])

    data = result.to_dict()
    assert data["status"] == "needs_llm"
    assert data["warnings"] == [
        f"source {source_id} is deprecated; user review should confirm reuse."
    ]


def test_source_deprecate_requires_review_and_reports_impacts(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=_candidate_llm_result(source_id),
    )

    gate = source_deprecate(tmp_path, source_id=source_id, reason="Superseded.")
    result = source_deprecate(
        tmp_path,
        source_id=source_id,
        decision="deprecate",
        reviewed_by="user",
        reason="Superseded.",
    )

    data = result.to_dict()
    assert gate.to_dict()["status"] == "needs_review"
    assert data["status"] == "success"
    assert data["source_id"] == source_id
    assert data["impacts"] == [
        {
            "object_id": "knowledge-20260520-001",
            "object_type": "candidate",
            "status": "pending",
            "fields": "source_refs, evidence",
        }
    ]
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(f"data/raw/md/{source_id}.md")
    assert document.frontmatter["status"] == "deprecated"
    assert document.frontmatter["deprecated_reason"] == "Superseded."


def test_candidate_create_resume_writes_pending_candidate(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    first = candidate_create(tmp_path, source_ids=[source_id])
    token = first.to_dict()["resume"]["token"]

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=_candidate_llm_result(source_id),
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["candidate_ids"] == ["knowledge-20260520-001"]
    assert data["suggested_tags"] == ["ai"]
    assert data["suggested_kb_ids"] == []
    assert data["candidates"] == [
        {
            "id": "knowledge-20260520-001",
            "suggested_tags": ["ai"],
            "suggested_kb_ids": [],
        }
    ]
    candidate_file = tmp_path / "candidates/pending/knowledge-20260520-001.md"
    assert candidate_file.is_file()
    text = candidate_file.read_text(encoding="utf-8")
    assert "type: candidate" in text
    assert "status: pending" in text
    assert "task_refs" not in text
    assert f"- {source_id}" in text
    document = ObjectRepository(Workspace(tmp_path)).read_markdown(
        "candidates/pending/knowledge-20260520-001.md"
    )
    assert TIMESTAMP_RE.match(document.frontmatter["created"])
    assert TIMESTAMP_RE.match(document.frontmatter["updated"])


def test_candidate_create_rejects_missing_evidence_reference(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(source_id)
    bad_result["candidates"][0]["evidence"][0]["source_id"] = "source-20990101-001"

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_rejects_evidence_without_snippet(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(source_id)
    del bad_result["candidates"][0]["evidence"][0]["quote"]

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_rejects_invalid_llm_field_shape(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(source_id)
    bad_result["candidates"][0]["suggested_tags"] = "ai"

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_rejects_relation_target_that_is_not_knowledge(
    tmp_path: Path,
) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(source_id)
    bad_result["candidates"][0]["relations"] = [{"type": "supports", "target": source_id}]

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    data = result.to_dict()
    assert data["status"] == "failed"
    assert "relation target must be knowledge" in data["errors"][0]["message"]
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_relation_target_error_explains_expected_shape(
    tmp_path: Path,
) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(source_id)
    bad_result["candidates"][0]["relations"] = [{"type": "supports"}]

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    data = result.to_dict()
    assert data["status"] == "failed"
    message = data["errors"][0]["message"]
    assert "relations must be [] when there are no relations" in message
    assert "{'type': 'related_to', 'target': 'knowledge-YYYYMMDD-001'}" in message
    assert "relation.target must be an existing knowledge ID" in message
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_rejects_missing_suggested_knowledgebase(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(source_id)
    bad_result["candidates"][0]["suggested_kb_ids"] = ["kb-20260520-404"]

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    data = result.to_dict()
    assert data["status"] == "failed"
    assert "object not found" in data["errors"][0]["message"]
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_accepts_existing_suggested_knowledgebase(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    ObjectRepository(Workspace(tmp_path)).write_markdown(
        "knowledge/bases/kb-20260520-001.md",
        MarkdownDocument(
            frontmatter={
                "id": "kb-20260520-001",
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
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    llm_result = _candidate_llm_result(source_id)
    llm_result["candidates"][0]["suggested_kb_ids"] = ["kb-20260520-001"]

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=llm_result,
    )

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["suggested_kb_ids"] == ["kb-20260520-001"]


def test_candidate_create_must_preserve_requested_source_refs(tmp_path: Path) -> None:
    first_source_id = _create_source(tmp_path)
    second_source_id = _create_source(tmp_path)
    token = candidate_create(
        tmp_path,
        source_ids=[first_source_id, second_source_id],
    ).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(first_source_id)

    result = candidate_create(
        tmp_path,
        source_ids=[first_source_id, second_source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_create_rolls_back_partial_batch_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    result = _candidate_llm_result(source_id)
    result["candidates"].append(
        {
            "id": "knowledge-20260520-002",
            "title": "Second Candidate",
            "body": "Another candidate fact extracted from the source.",
            "source_refs": [source_id],
            "evidence": [
                {
                    "source_id": source_id,
                    "locator": "section 2",
                    "quote": "Another useful cleaned content.",
                }
            ],
        }
    )
    writes = 0
    original_write = ObjectRepository.write_markdown

    def fail_second_write(self, path, document, *, overwrite=False):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated write failure")
        return original_write(self, path, document, overwrite=overwrite)

    monkeypatch.setattr(application.ObjectRepository, "write_markdown", fail_second_write)

    response = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=result,
    )

    assert response.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_id_cannot_duplicate_knowledge_id(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    existing = tmp_path / "knowledge/atomic/knowledge-20260520-001.md"
    existing.write_text(
        "---\n"
        "id: knowledge-20260520-001\n"
        "type: knowledge\n"
        "title: Existing\n"
        "status: accepted\n"
        "created: 2026-05-20\n"
        "updated: 2026-05-20\n"
        "---\n"
        "Existing\n",
        encoding="utf-8",
    )
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=_candidate_llm_result(source_id),
    )

    assert result.to_dict()["status"] == "failed"
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_id_must_use_knowledge_prefix(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    bad_result = _candidate_llm_result(source_id, candidate_id="source-20260520-999")

    result = candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=bad_result,
    )

    data = result.to_dict()
    assert data["status"] == "failed"
    assert "invalid candidate ID" in data["errors"][0]["message"]
    assert _non_placeholder_names(tmp_path / "candidates/pending") == []


def test_candidate_get_and_next_pending(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=_candidate_llm_result(source_id),
    )

    got = candidate_get(tmp_path, candidate_id="knowledge-20260520-001").to_dict()
    next_pending = candidate_next_pending(tmp_path).to_dict()

    assert got["status"] == "success"
    assert got["candidate"]["frontmatter"]["source_refs"] == [source_id]
    assert got["candidate"]["references"][0]["id"] == source_id
    assert next_pending["status"] == "success"
    assert next_pending["operation"] == "kb.candidate.next_pending"
    assert next_pending["candidate"]["id"] == "knowledge-20260520-001"


def test_candidate_next_pending_rejects_pending_candidate_in_wrong_directory(
    tmp_path: Path,
) -> None:
    source_id = _create_source(tmp_path)
    token = candidate_create(tmp_path, source_ids=[source_id]).to_dict()["resume"]["token"]
    candidate_create(
        tmp_path,
        source_ids=[source_id],
        resume_token=token,
        llm_result=_candidate_llm_result(source_id),
    )
    source = tmp_path / "candidates/pending/knowledge-20260520-001.md"
    target = tmp_path / "candidates/deferred/knowledge-20260520-001.md"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    source.unlink()

    result = candidate_next_pending(tmp_path)

    assert result.to_dict()["status"] == "failed"
    assert "outside candidates/pending" in result.to_dict()["errors"][0]["message"]
