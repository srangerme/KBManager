from __future__ import annotations

from pathlib import Path
from typing import Any

from kbmanager.contracts import ApiStatus
from kbmanager.interface import SlashCommandInterface


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


def _success(operation: str, **extra: Any) -> dict[str, Any]:
    result = {
        "status": "success",
        "operation": operation,
        "objects": {"created": [], "updated": [], "deprecated": []},
        "diffs": [],
        "warnings": [],
        "errors": [],
        "review": {"required": False, "options": []},
        "next_actions": [],
    }
    result.update(extra)
    return result


def _needs_llm(
    operation: str,
    token: str,
    *,
    required_context: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "needs_llm",
        "operation": operation,
        "objects": {"created": [], "updated": [], "deprecated": []},
        "diffs": [],
        "warnings": [],
        "errors": [],
        "review": {"required": False, "options": []},
        "next_actions": [],
        "llm_request": {
            "purpose": operation,
            "required_context": required_context or [],
        },
        "resume": {"operation": operation, "token": token},
    }


def _needs_llm_with_prompt(operation: str, token: str) -> dict[str, Any]:
    result = _needs_llm(operation, token)
    result["llm_request"] = {
        "purpose": operation,
        "required_context": [],
        "prompt": {
            "sections": [
                {
                    "role": "system",
                    "name": "kbmanager_system_prompt",
                    "content": "system",
                }
            ]
        },
    }
    return result


def _candidate(candidate_id: str = "knowledge-20260520-001") -> dict[str, Any]:
    return {
        "id": candidate_id,
        "path": f"candidates/pending/{candidate_id}.md",
        "frontmatter": {
            "id": candidate_id,
            "title": "Candidate",
            "suggested_tags": ["ai"],
            "suggested_kb_ids": [],
            "relations": [],
        },
        "body": "Candidate body.",
        "references": [],
    }


def _review_assist() -> dict[str, Any]:
    return {
        "summary": "assist",
        "evidence_review": [],
        "suggested_kb_ids": [],
        "recommendations": [],
    }


def _merge_assist() -> dict[str, Any]:
    return {
        "merged_body": "Merged draft.",
        "tags": [],
        "kb_ids": [],
        "relations": [],
        "evidence_review": [],
    }


def _source_prompt_rewrite() -> dict[str, Any]:
    return {
        "rewritten_prompt": "Focus on deployment risks and summarize as bullet points.",
        "intent_summary": "Summarize deployment risks.",
        "constraints": ["Use bullet points."],
        "warnings": [],
    }


def test_source_add_orchestrates_two_llm_resumes() -> None:
    api = MockApi(
        {
            "kb.source.add": [
                _needs_llm("kb.source.add", "source-token"),
                _success("kb.source.add", source_ids=["source-20260520-001"]),
            ],
            "kb.candidate.create": [
                _needs_llm("kb.candidate.create", "candidate-token"),
                _success("kb.candidate.create", candidate_ids=["knowledge-20260520-001"]),
            ],
        }
    )
    interface = SlashCommandInterface(api=api)

    result = interface.kb_source_add(
        "incoming.md",
        source_llm_result={"summary": "source"},
        candidate_llm_result={"candidates": []},
    )

    assert result.to_dict()["status"] == "success"
    assert [name for name, _ in api.calls] == [
        "kb.source.add",
        "kb.source.add",
        "kb.candidate.create",
        "kb.candidate.create",
    ]
    assert api.calls[1][1]["resume_token"] == "source-token"


def test_source_add_uses_api_required_context_for_source_ingest_input_path() -> None:
    api = MockApi(
        {
            "kb.source.add": [
                _needs_llm(
                    "kb.source.add",
                    "source-token",
                    required_context=["data/attachments/url-captures/exported.pdf"],
                ),
                _success("kb.source.add", source_ids=["source-20260520-001"]),
            ],
            "kb.candidate.create": [
                _needs_llm("kb.candidate.create", "candidate-token"),
                _success("kb.candidate.create", candidate_ids=["knowledge-20260520-001"]),
            ],
        }
    )
    llm = MockLlm(
        {
            "source_ingest": {"summary": "source"},
            "create_candidate": {"candidates": []},
        }
    )
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_source_add("https://example.com/research/article")

    assert result.to_dict()["status"] == "success"
    assert llm.calls[0]["context"]["input_path"] == (
        "data/attachments/url-captures/exported.pdf"
    )
    assert api.calls[0][1]["input_path"] == "https://example.com/research/article"
    assert api.calls[1][1]["input_path"] == "https://example.com/research/article"
    assert api.calls[3][1]["resume_token"] == "candidate-token"


def test_source_add_user_prompt_waits_for_review_before_api_call() -> None:
    api = MockApi({})
    llm = MockLlm({"source_ingest_prompt_rewrite": _source_prompt_rewrite()})
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_source_add("incoming.md", user_prompt="Look for deployment risks.")

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert data["opened_in_vscode"] == []
    assert data["requested_in_claude"] == [
        {
            "kind": "source_ingest_prompt",
            "action": "review_source_ingest_prompt",
            "instructions": (
                "Reply with approve to use the rewritten prompt, or provide revised prompt text."
            ),
        }
    ]
    assert data["draft"]["rewritten_prompt"] == (
        "Focus on deployment risks and summarize as bullet points."
    )
    assert api.calls == []
    assert llm.calls[0]["purpose"] == "source_ingest_prompt_rewrite"


def test_source_add_confirmed_user_prompt_is_appended_to_source_ingest_request() -> None:
    api = MockApi(
        {
            "kb.source.add": [
                _needs_llm_with_prompt("kb.source.add", "source-token"),
                _success("kb.source.add", source_ids=["source-20260520-001"]),
            ],
            "kb.candidate.create": [
                _needs_llm("kb.candidate.create", "candidate-token"),
                _success("kb.candidate.create", candidate_ids=["knowledge-20260520-001"]),
            ],
        }
    )
    llm = MockLlm(
        {
            "source_ingest": {"summary": "source"},
            "create_candidate": {"candidates": []},
        }
    )
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_source_add(
        "incoming.md",
        user_prompt="Focus on risks.",
        confirm_user_prompt=True,
        reviewed_user_prompt={
            "rewritten_prompt": "Focus only on deployment risks.",
        },
    )

    data = result.to_dict()
    assert data["status"] == "success"
    source_call = llm.calls[0]
    assert source_call["purpose"] == "source_ingest"
    assert source_call["context"]["user_ingest_prompt"] == "Focus only on deployment risks."
    assert source_call["llm_request"]["user_ingest_prompt"] == (
        "Focus only on deployment risks."
    )
    assert source_call["llm_request"]["prompt"]["sections"][-1] == {
        "role": "user",
        "name": "confirmed_user_ingest_prompt",
        "content": "Focus only on deployment risks.",
    }
    assert api.calls[1][1]["resume_token"] == "source-token"


def test_source_add_invalid_prompt_rewrite_returns_failed_without_api_call() -> None:
    api = MockApi({})
    llm = MockLlm({"source_ingest_prompt_rewrite": {"intent_summary": "missing prompt"}})
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_source_add("incoming.md", user_prompt="Focus on risks.")

    data = result.to_dict()
    assert data["status"] == "failed"
    assert data["errors"][0]["purpose"] == "source_ingest_prompt_rewrite"
    assert api.calls == []


def test_init_command_calls_init_api() -> None:
    api = MockApi({"kb.init": [_success("kb.init", next_actions=["Next."])]})
    interface = SlashCommandInterface(api=api)

    result = interface.kb_init()

    assert result.to_dict()["status"] == "success"
    assert api.calls == [("kb.init", {"dry_run": False})]


def test_init_command_forwards_dry_run() -> None:
    api = MockApi({"kb.init": [_success("kb.init")]})
    interface = SlashCommandInterface(api=api)

    result = interface.kb_init(dry_run=True)

    assert result.to_dict()["status"] == "success"
    assert api.calls == [("kb.init", {"dry_run": True})]


def test_candidate_review_waits_for_decision_before_status_change_api() -> None:
    api = MockApi({"kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())]})
    llm = MockLlm({"candidate_review_assist": _review_assist()})
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_candidate_review("knowledge-20260520-001")

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert [name for name, _ in api.calls] == ["kb.candidate.get"]
    assert data["opened_in_vscode"] == []
    assert data["displayed_in_claude"] == [
        {
            "path": "candidates/pending/knowledge-20260520-001.md",
            "format": "markdown",
            "content": "Candidate body.",
        }
    ]
    assert llm.calls[0]["purpose"] == "candidate_review_assist"


def test_candidate_review_requires_llm_assist_before_decision_api() -> None:
    api = MockApi({"kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())]})
    interface = SlashCommandInterface(api=api)

    result = interface.kb_candidate_review(
        "knowledge-20260520-001",
        decision="reject",
        reason="No.",
    )

    data = result.to_dict()
    assert data["status"] == "failed"
    assert data["errors"][0]["code"] == "missing_llm"
    assert [name for name, _ in api.calls] == ["kb.candidate.get"]


def test_candidate_review_decision_branches_call_expected_api() -> None:
    cases = [
        (
            "accept",
            "kb.knowledge.accept",
            {
                "reviewed_markdown": {
                    "title": "T",
                    "body": "B",
                    "tags": [],
                    "kb_ids": [],
                    "relations": [],
                }
            },
        ),
        ("reject", "kb.knowledge.reject", {"reason": "No."}),
        ("defer", "kb.candidate.defer", {"reason": "Later."}),
        (
            "merge",
            "kb.knowledge.merge",
            {
                "merge_targets": ["knowledge-20260520-999"],
                "reviewed_markdown": {"body": "B", "tags": [], "kb_ids": [], "relations": []},
            },
        ),
    ]

    for decision, expected_operation, kwargs in cases:
        api = MockApi(
            {
                "kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())],
                expected_operation: [_success(expected_operation)],
            }
        )
        llm = MockLlm(
            {
                "candidate_review_assist": _review_assist(),
                "knowledge_merge_assist": _merge_assist(),
            }
        )
        interface = SlashCommandInterface(api=api, llm=llm)

        result = interface.kb_candidate_review(
            "knowledge-20260520-001",
            decision=decision,
            **kwargs,
        )

        assert result.to_dict()["status"] == "success"
        assert [name for name, _ in api.calls] == ["kb.candidate.get", expected_operation]
        assert api.calls[1][1]["decision"] == decision
        assert api.calls[1][1]["reviewed_by"] == "user"
        assert llm.calls[0]["purpose"] == "candidate_review_assist"


def test_candidate_accept_requires_reviewed_markdown_before_api_call() -> None:
    candidate = _candidate()
    candidate["frontmatter"]["suggested_kb_ids"] = ["kb-20260520-001"]
    api = MockApi({"kb.candidate.get": [_success("kb.candidate.get", candidate=candidate)]})
    llm = MockLlm({"candidate_review_assist": _review_assist()})
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_candidate_review(
        "knowledge-20260520-001",
        decision="accept",
    )

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert [name for name, _ in api.calls] == ["kb.candidate.get"]
    assert data["opened_in_vscode"] == []
    assert data["requested_in_claude"] == [
        {
            "kind": "reviewed_markdown",
            "action": "accept_candidate",
            "instructions": (
                "Reply with approve to use the draft, or provide reviewed Markdown "
                "frontmatter and body."
            ),
        }
    ]
    assert data["review_draft"]["kb_ids"] == ["kb-20260520-001"]


def test_candidate_merge_requires_reviewed_markdown_before_api_call() -> None:
    api = MockApi({"kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())]})
    llm = MockLlm(
        {
            "candidate_review_assist": _review_assist(),
            "knowledge_merge_assist": _merge_assist(),
        }
    )
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_candidate_review(
        "knowledge-20260520-001",
        decision="merge",
        merge_targets=["knowledge-20260520-999"],
    )

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert [name for name, _ in api.calls] == ["kb.candidate.get"]
    assert data["opened_in_vscode"] == []
    assert data["requested_in_claude"] == [
        {
            "kind": "reviewed_markdown",
            "action": "merge_candidate",
            "instructions": (
                "Reply with approve to use the merge draft, or provide reviewed Markdown "
                "frontmatter and body."
            ),
        }
    ]


def test_candidate_review_without_id_loads_next_pending_before_get() -> None:
    api = MockApi(
        {
            "kb.candidate.next_pending": [
                _success("kb.candidate.next_pending", candidate=_candidate())
            ],
            "kb.candidate.get": [_success("kb.candidate.get", candidate=_candidate())],
        }
    )
    llm = MockLlm({"candidate_review_assist": _review_assist()})
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_candidate_review()

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert [name for name, _ in api.calls] == [
        "kb.candidate.next_pending",
        "kb.candidate.get",
    ]


def test_note_add_without_content_requests_markdown_in_claude_without_api_call() -> None:
    api = MockApi({})
    interface = SlashCommandInterface(api=api)

    result = interface.kb_note_add()

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert data["opened_in_vscode"] == []
    assert data["requested_in_claude"] == [
        {
            "kind": "note_markdown",
            "action": "add_note",
            "instructions": "Reply with note Markdown content and an optional title.",
        }
    ]
    assert api.calls == []


def test_note_add_with_content_always_uses_llm_title_flow() -> None:
    api = MockApi(
        {
            "kb.note.add": [
                _needs_llm("kb.note.add", "note-token"),
                _success("kb.note.add", note_id="note-20260520-001"),
            ]
        }
    )
    llm = MockLlm({"note_title": {"title": "LLM Note"}})
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_note_add(content="Only body.")

    assert result.to_dict()["status"] == "success"
    assert api.calls == [
        (
            "kb.note.add",
            {
                "content": "Only body.",
                "title": None,
                "needs_llm": True,
            },
        ),
        (
            "kb.note.add",
            {
                "content": "Only body.",
                "title": None,
                "needs_llm": True,
                "resume_token": "note-token",
                "llm_result": {"title": "LLM Note"},
            },
        ),
    ]
    assert llm.calls[0]["purpose"] == "note_title"


def test_note_add_with_user_title_still_uses_llm_title_flow() -> None:
    api = MockApi(
        {
            "kb.note.add": [
                _needs_llm("kb.note.add", "note-token"),
                _success("kb.note.add", note_id="note-20260520-001"),
            ]
        }
    )
    llm = MockLlm({"note_title": {"title": "LLM Note"}})
    interface = SlashCommandInterface(api=api, llm=llm)

    result = interface.kb_note_add(content="Only body.", title="User Title")

    assert result.to_dict()["status"] == "success"
    assert api.calls[0][1]["title"] == "User Title"
    assert api.calls[0][1]["needs_llm"] is True
    assert api.calls[1][1]["title"] == "User Title"
    assert api.calls[1][1]["needs_llm"] is True


def test_note_view_displays_note_payload_in_claude() -> None:
    api = MockApi(
        {
            "kb.note.get": [
                _success(
                    "kb.note.get",
                    note={
                        "id": "note-20260520-001",
                        "path": "notes/active/note-20260520-001.md",
                        "body": "Note body.",
                    },
                )
            ]
        }
    )
    interface = SlashCommandInterface(api=api)

    result = interface.kb_note_view("note-20260520-001")

    data = result.to_dict()
    assert data["status"] == "success"
    assert data["opened_in_vscode"] == []
    assert data["displayed_in_claude"] == [
        {
            "path": "notes/active/note-20260520-001.md",
            "format": "markdown",
            "content": "Note body.",
        }
    ]
    assert api.calls == [("kb.note.get", {"note_id": "note-20260520-001"})]


def test_knowledgebase_create_without_approval_requests_review_in_claude() -> None:
    interface = SlashCommandInterface()

    result = interface.kb_knowledgebase_create(
        title="Research",
        description="Research notes.",
        acceptance_criteria="Reviewed items only.",
        tags=["research"],
    )

    data = result.to_dict()
    assert data["status"] == "needs_review"
    assert data["opened_in_vscode"] == []
    assert data["requested_in_claude"] == [
        {
            "kind": "reviewed_markdown",
            "action": "create_knowledgebase",
            "instructions": (
                "Reply with approve to use the draft, or provide reviewed Markdown "
                "frontmatter and body."
            ),
        }
    ]
    assert data["draft"]["frontmatter"]["title"] == "Research"


def test_knowledgebase_create_with_approval_calls_create_api() -> None:
    api = MockApi({"kb.knowledgebase.create": [_success("kb.knowledgebase.create")]})
    interface = SlashCommandInterface(api=api)

    result = interface.kb_knowledgebase_create(
        title="Research",
        description="Research notes.",
        acceptance_criteria="Reviewed items only.",
        tags=["research"],
        reviewed_markdown={
            "title": "Reviewed Research",
            "description": "Reviewed description.",
            "acceptance_criteria": "Reviewed criteria.",
            "tags": ["reviewed"],
            "body": "Reviewed body.",
        },
        approve=True,
    )

    assert result.to_dict()["status"] == "success"
    assert api.calls == [
        (
            "kb.knowledgebase.create",
            {
                "title": "Reviewed Research",
                "description": "Reviewed description.",
                "acceptance_criteria": "Reviewed criteria.",
                "tags": ["reviewed"],
                "body": "Reviewed body.",
                "decision": "approve",
                "reviewed_by": "user",
            },
        )
    ]


def test_source_and_note_deprecate_require_confirmation_before_api_call() -> None:
    api = MockApi({})
    interface = SlashCommandInterface(api=api)

    source = interface.kb_source_deprecate("source-20260520-001", reason="Old.")
    note = interface.kb_note_deprecate("note-20260520-001", reason="Old.")

    assert source.to_dict()["status"] == "needs_review"
    assert note.to_dict()["status"] == "needs_review"
    assert api.calls == []


def test_source_and_note_deprecate_call_api_after_confirmation() -> None:
    api = MockApi(
        {
            "kb.source.deprecate": [_success("kb.source.deprecate")],
            "kb.note.deprecate": [_success("kb.note.deprecate")],
        }
    )
    interface = SlashCommandInterface(api=api)

    source = interface.kb_source_deprecate(
        "source-20260520-001",
        reason="Old.",
        confirm=True,
    )
    note = interface.kb_note_deprecate(
        "note-20260520-001",
        reason="Old.",
        confirm=True,
    )

    assert source.to_dict()["status"] == "success"
    assert note.to_dict()["status"] == "success"
    assert [name for name, _ in api.calls] == ["kb.source.deprecate", "kb.note.deprecate"]


def test_check_rebuilds_indexes_directly() -> None:
    api = MockApi(
        {
            "kb.index.rebuild": [
                _success(
                    "kb.index.rebuild",
                    issues=[],
                    index_paths=["indexes/knowledge-index.md"],
                )
            ]
        }
    )
    interface = SlashCommandInterface(api=api)

    result = interface.kb_check()

    assert result.to_dict()["status"] == ApiStatus.SUCCESS.value
    assert api.calls == [("kb.index.rebuild", {})]


def test_read_only_commands_display_markdown_in_claude_without_api(tmp_path: Path) -> None:
    (tmp_path / "indexes/knowledgebase").mkdir(parents=True)
    (tmp_path / "indexes/kb-index.md").write_text(
        "# Knowledge Base Index\n",
        encoding="utf-8",
    )
    (tmp_path / "indexes/note-index.md").write_text("# Note Index\n", encoding="utf-8")
    api = MockApi({})
    interface = SlashCommandInterface(root=tmp_path, api=api)

    knowledgebase = interface.kb_knowledgebase_list().to_dict()
    note = interface.kb_note_list().to_dict()

    assert knowledgebase["opened_in_vscode"] == []
    assert knowledgebase["displayed_in_claude"] == [
        {
            "path": "indexes/kb-index.md",
            "format": "markdown",
            "content": "# Knowledge Base Index\n",
        }
    ]
    assert note["opened_in_vscode"] == []
    assert note["displayed_in_claude"] == [
        {
            "path": "indexes/note-index.md",
            "format": "markdown",
            "content": "# Note Index\n",
        }
    ]
    assert api.calls == []


def test_read_only_list_commands_prompt_check_when_indexes_are_missing(tmp_path: Path) -> None:
    api = MockApi({})
    interface = SlashCommandInterface(root=tmp_path, api=api)

    knowledgebase = interface.kb_knowledgebase_list().to_dict()
    note = interface.kb_note_list().to_dict()

    assert knowledgebase["status"] == "needs_review"
    assert knowledgebase["missing_index"] == "indexes/kb-index.md"
    assert note["status"] == "needs_review"
    assert note["missing_index"] == "indexes/note-index.md"
    assert api.calls == []
