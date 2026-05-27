from __future__ import annotations

from pathlib import Path

from kbmanager.application import candidate_create, init_workspace, source_add
from kbmanager.interface import SlashCommandInterface
from kbmanager.prompts import assemble_prompt, load_system_prompt, schema_for_output


def _source_llm_result(input_path: str = "incoming.md") -> dict[str, object]:
    return {
        "input_path": input_path,
        "summary": "A useful source summary.",
        "cleaned_content": f"Source: {input_path}\nUseful cleaned content.",
    }


def _create_source(tmp_path: Path) -> str:
    init_workspace(tmp_path, entrypoint="claude_code", dry_run=False)
    (tmp_path / "incoming.md").write_text("# Raw\n", encoding="utf-8")
    first = source_add(
        tmp_path, entrypoint="claude_code", dry_run=False, input_path="incoming.md"
    ).to_dict()
    resumed = source_add(
        tmp_path,
        entrypoint="claude_code",
        dry_run=False,
        input_path="incoming.md",
        resume_token=first["resume"]["token"],
        llm_result=_source_llm_result(),
    ).to_dict()
    return resumed["source"]["id"]


def test_builtin_prompt_loads_new_candidate_model_metadata() -> None:
    prompt = load_system_prompt("candidate-create")

    assert prompt.version == "1"
    assert prompt.metadata["api"] == "kb.candidate.create"
    assert "bindto" in prompt.text
    assert "outline_change_suggestions" in prompt.text
    assert "Use `bindto: []` when there is no suitable knowledgebase outline node" in prompt.text
    assert "child_of" not in prompt.text


def test_candidate_schema_uses_bindto_and_outline_suggestions() -> None:
    schema = schema_for_output("candidate_draft_list")
    candidate_schema = schema["properties"]["candidates"][0]

    assert "summary" in candidate_schema
    assert "content" in candidate_schema
    assert "bindto" in candidate_schema
    assert "relations" not in candidate_schema


def test_prompt_assembly_includes_output_schema() -> None:
    prompt = assemble_prompt(
        system_prompt="candidate-create",
        user_input={"source_ids": ["source-1"]},
        object_context={"required_context": ["source-1"]},
        output_schema="candidate_draft_list",
        constraints=["must_include_evidence"],
    )

    assert prompt["system_prompt"] == "candidate-create"
    schema_section = prompt["sections"][-1]["content"]["schema"]
    assert schema_section["properties"]["candidates"][0]["bindto"]


def test_candidate_llm_output_cannot_create_accepted_knowledge(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    first = candidate_create(
        tmp_path, entrypoint="claude_code", dry_run=False, source_ids=[source_id]
    ).to_dict()

    result = candidate_create(
        tmp_path,
        entrypoint="claude_code",
        dry_run=False,
        source_ids=[source_id],
        resume_token=first["resume"]["token"],
        llm_result={
            "candidates": [
                {
                    "id": "knowledge-20260520-001",
                    "type": "knowledge",
                    "status": "accepted",
                    "title": "Accepted",
                    "summary": "Summary.",
                    "content": "Content.",
                    "evidence": [
                        {"source_id": source_id, "locator": "section 1", "quote": "quote"}
                    ],
                    "bindto": [],
                    "outline_change_suggestions": [],
                }
            ]
        },
    ).to_dict()

    assert result["status"] == "failed"
    assert "must not create accepted knowledge" in result["errors"][0]["message"]


def test_candidate_draft_without_evidence_is_rejected(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)
    first = candidate_create(
        tmp_path, entrypoint="claude_code", dry_run=False, source_ids=[source_id]
    ).to_dict()

    result = candidate_create(
        tmp_path,
        entrypoint="claude_code",
        dry_run=False,
        source_ids=[source_id],
        resume_token=first["resume"]["token"],
        llm_result={
            "candidates": [
                {
                    "id": "knowledge-20260520-001",
                    "title": "No Evidence",
                    "summary": "Summary.",
                    "content": "Content.",
                    "evidence": [],
                    "bindto": [],
                    "outline_change_suggestions": [],
                }
            ]
        },
    ).to_dict()

    assert result["status"] == "failed"
    assert "evidence must be a non-empty list" in result["errors"][0]["message"]


def test_candidate_create_llm_request_includes_source_context(tmp_path: Path) -> None:
    source_id = _create_source(tmp_path)

    first = candidate_create(
        tmp_path, entrypoint="claude_code", dry_run=False, source_ids=[source_id]
    ).to_dict()

    source_context = first["llm_request"]["prompt"]["sections"][1]["content"]["source_context"]
    assert source_context[0]["id"] == source_id
    assert "Useful cleaned content." in source_context[0]["cleaned_content"]
    assert source_context[0]["cleaned_path"].startswith("data/cleaned/")


def test_interface_rejects_invalid_merge_assist_schema(tmp_path: Path) -> None:
    (tmp_path / "knowledge/atomic").mkdir(parents=True)
    (tmp_path / "knowledge/atomic/knowledge-2.md").write_text(
        "---\n"
        "id: knowledge-2\n"
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

    class MockApi:
        def call(self, operation: str, **kwargs: object) -> dict[str, object]:
            return {
                "status": "success",
                "operation": operation,
                "objects": {"created": [], "updated": [], "deprecated": []},
                "diffs": [],
                "warnings": [],
                "errors": [],
                "review": {"required": False, "options": []},
                "next_actions": [],
                "candidate": {
                    "id": "knowledge-1",
                    "frontmatter": {
                        "title": "Candidate",
                        "summary": "s",
                        "evidence": [],
                        "bindto": [],
                    },
                    "body": "body",
                },
            }

    class MockLlm:
        def complete(self, **kwargs: object) -> dict[str, object]:
            if kwargs["purpose"] == "candidate_review_assist":
                return {"summary": "s", "evidence_review": [], "bindto": [], "recommendations": []}
            return {"merged_body": "old"}

    result = (
        SlashCommandInterface(root=tmp_path, api=MockApi(), llm=MockLlm())
        .kb_candidate_review(
            "knowledge-1",
            decision="merge",
            merge_targets=["knowledge-2"],
            reviewed_markdown={"summary": "s", "content": "c", "evidence": [], "bindto": []},
        )
        .to_dict()
    )

    assert result["status"] == "failed"
    assert "merged_summary" in result["errors"][0]["message"]
