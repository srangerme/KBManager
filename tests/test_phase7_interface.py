from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kbmanager.interface import InteractionInterface


class MockApi:
    def __init__(self, results: dict[str, list[dict[str, Any]]]) -> None:
        self.results = {name: list(items) for name, items in results.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((operation, kwargs))
        return self.results[operation].pop(0)


class MockLlm:
    def __init__(self, results: dict[str, dict[str, Any]] | None = None) -> None:
        self.results = results or {}
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.results.get(kwargs["purpose"], {})


def _api_result(status: str, operation: str, **extra: Any) -> dict[str, Any]:
    result = {
        "status": status,
        "operation": operation,
        "objects": {"created": [], "updated": [], "deprecated": []},
        "diffs": [],
        "warnings": [],
        "errors": [],
        "review": {"required": status == "needs_review", "options": []},
        "next_actions": [],
    }
    result.update(extra)
    return result


def _success(operation: str, **extra: Any) -> dict[str, Any]:
    return _api_result("success", operation, **extra)


def _needs_llm(operation: str, token: str) -> dict[str, Any]:
    return _api_result(
        "needs_llm",
        operation,
        llm_request={"purpose": operation, "required_context": [], "prompt": {"sections": []}},
        resume={"operation": operation, "token": token},
    )


def _candidate(candidate_id: str = "knowledge-20260520-001") -> dict[str, Any]:
    return {
        "id": candidate_id,
        "path": f"candidates/pending/{candidate_id}.md",
        "frontmatter": {
            "id": candidate_id,
            "title": "Candidate",
            "summary": "Candidate summary.",
            "evidence": [{"source_id": "source-1", "locator": "l", "quote": "q"}],
            "bindto": [
                {"kb_id": "kb-1", "outline_id": "canonical", "node_id": "sec1", "reason": "Fits."}
            ],
            "outline_change_suggestions": [],
        },
        "body": "Candidate body.",
        "references": [],
    }


def _review_assist() -> dict[str, Any]:
    return {"summary": "assist", "evidence_review": [], "bindto": [], "recommendations": []}


def _merge_assist() -> dict[str, Any]:
    return {
        "merged_summary": "Merged summary.",
        "merged_content": "Merged content.",
        "evidence": [{"source_id": "source-1", "locator": "l", "quote": "q"}],
        "bindto": [
            {"kb_id": "kb-1", "outline_id": "canonical", "node_id": "sec1", "reason": "Fits."}
        ],
        "evidence_review": [],
    }


def test_source_add_orchestrates_source_llm_resume_only() -> None:
    api = MockApi(
        {
            "kb.source.add": [
                _needs_llm("kb.source.add", "source-token"),
                _success("kb.source.add", source_ids=["source-1"]),
            ],
        }
    )
    llm = MockLlm(
        {
            "source_ingest": {"input_path": "input.md", "summary": "s", "cleaned_content": "c"},
        }
    )

    result = InteractionInterface(api=api, llm=llm).kb_source_add("input.md")

    assert result.to_dict()["status"] == "success"
    assert [call[0] for call in api.calls] == [
        "kb.source.add",
        "kb.source.add",
    ]


def test_interface_logs_llm_input_and_output(tmp_path: Path) -> None:
    api = MockApi(
        {
            "kb.note.add": [
                _needs_llm("kb.note.add", "note-token"),
                _success("kb.note.add", note_id="note-1"),
            ],
        }
    )
    llm = MockLlm({"note_title": {"title": "Generated note"}})

    result = InteractionInterface(root=tmp_path, api=api, llm=llm).kb_note_add(content="Body")

    assert result.to_dict()["status"] == "success"
    log_files = list((tmp_path / ".claude/log").glob("*.json"))
    assert len(log_files) == 1
    record = json.loads(log_files[0].read_text(encoding="utf-8"))
    assert record["purpose"] == "note_title"
    assert record["input"]["context"] == {"content": "Body"}
    assert record["output"] == {"title": "Generated note"}


def test_candidate_review_waits_for_decision_after_assist() -> None:
    api = MockApi({"kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())]})

    result = InteractionInterface(api=api).kb_candidate_review("knowledge-1")

    assert result.to_dict()["status"] == "needs_review"
    assert result.to_dict()["review_assist"]["summary"] == "Candidate summary."


def test_candidate_accept_passes_new_review_payload() -> None:
    api = MockApi(
        {
            "kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())],
            "kb.knowledge.accept": [_success("kb.knowledge.accept")],
        }
    )

    result = InteractionInterface(api=api).kb_candidate_review(
        "knowledge-1",
        decision="accept",
        reviewed_markdown={
            "title": "Accepted",
            "summary": "Summary.",
            "content": "Content.",
            "evidence": [{"source_id": "source-1", "locator": "l", "quote": "q"}],
            "bindto": [
                {"kb_id": "kb-1", "outline_id": "canonical", "node_id": "sec1", "reason": "Fits."}
            ],
        },
    )

    assert result.to_dict()["status"] == "success"
    kwargs = api.calls[-1][1]
    assert "kb_ids" not in kwargs
    assert kwargs["bindto"][0]["node_id"] == "sec1"


def test_candidate_merge_uses_reviewed_payload_without_merge_assist(tmp_path: Path) -> None:
    (tmp_path / "knowledge/atomic").mkdir(parents=True)
    (tmp_path / "knowledge/atomic/knowledge-target.md").write_text(
        "---\n"
        "id: knowledge-target\n"
        "type: knowledge\n"
        "title: Target\n"
        "status: accepted\n"
        "summary: Target summary.\n"
        "evidence: []\n"
        "bindto: []\n"
        "created: 2026-05-20\n"
        "updated: 2026-05-20\n"
        "---\n"
        "\n"
        "Target body.\n",
        encoding="utf-8",
    )
    api = MockApi(
        {
            "kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())],
            "kb.knowledge.merge": [_success("kb.knowledge.merge")],
        }
    )

    result = InteractionInterface(root=tmp_path, api=api).kb_candidate_review(
        "knowledge-1",
        decision="merge",
        merge_targets=["knowledge-target"],
        reviewed_markdown=_merge_assist(),
    )

    assert result.to_dict()["status"] == "success"
    assert api.calls[-1][0] == "kb.knowledge.merge"


def test_knowledgebase_create_orchestrates_single_create_review(tmp_path: Path) -> None:
    (tmp_path / "input.md").write_text("# KB seed\n\n- Topic A\n", encoding="utf-8")
    api = MockApi(
        {
            "kb.knowledgebase.create.prepare": [
                _needs_llm("kb.knowledgebase.create.prepare", "kb-token"),
                _api_result(
                    "success",
                    "kb.knowledgebase.create.prepare",
                    reviewed_payload={
                        "description": "d",
                        "tags": [],
                        "scope": {"includes": ["i"], "excludes": []},
                        "default_outline_id": "canonical",
                        "outlines": [
                            {
                                "id": "canonical",
                                "title": "Main",
                                "description": "Main outline.",
                                "status": "active",
                                "nodes": [],
                            }
                        ],
                    },
                ),
            ],
        }
    )
    llm = MockLlm(
        {
            "knowledgebase_create": {
                "description": "d",
                "tags": [],
                "scope": {"includes": ["i"], "excludes": []},
                "default_outline_id": "canonical",
                "outlines": [
                    {
                        "id": "canonical",
                        "title": "Main",
                        "description": "Main outline.",
                        "status": "active",
                        "nodes": [],
                    }
                ],
            }
        }
    )

    result = InteractionInterface(root=tmp_path, api=api, llm=llm).kb_knowledgebase_create(
        title="KB",
        input_path="input.md",
    )

    assert result.to_dict()["status"] == "needs_review"
    assert [call[0] for call in api.calls] == [
        "kb.knowledgebase.create.prepare",
        "kb.knowledgebase.create.prepare",
    ]
    assert llm.calls[0]["llm_request"]["purpose"] == "kb.knowledgebase.create.prepare"


def test_read_only_list_workflows_display_markdown(tmp_path: Path) -> None:
    (tmp_path / "indexes").mkdir()
    (tmp_path / "indexes/kb-index.md").write_text("# KB\n", encoding="utf-8")

    result = InteractionInterface(root=tmp_path).kb_knowledgebase_list()

    assert result.to_dict()["displayed_in_claude"][0]["content"] == "# KB\n"
