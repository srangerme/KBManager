"""Slash command orchestration layer.

This module is the first-layer boundary described by ``docs/Interface.md``.
It coordinates user-facing commands into second-layer ``kb.*`` API calls, but
does not write object files itself.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import kbmanager.application as application
from kbmanager.contracts import ApiStatus
from kbmanager.prompts import assemble_prompt, schema_for_output
from kbmanager.repository import ObjectRepository


@dataclass(frozen=True)
class ApiCallRecord:
    name: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status}


@dataclass(frozen=True)
class InterfaceResult:
    status: str
    summary: str
    api_calls: list[ApiCallRecord] = field(default_factory=list)
    objects: dict[str, list[str]] = field(
        default_factory=lambda: {"created": [], "updated": [], "deprecated": []}
    )
    opened_in_vscode: list[str] = field(default_factory=list)
    displayed_in_claude: list[dict[str, str]] = field(default_factory=list)
    requested_in_claude: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status,
            "summary": self.summary,
            "api_calls": [call.to_dict() for call in self.api_calls],
            "objects": {
                "created": list(self.objects.get("created", [])),
                "updated": list(self.objects.get("updated", [])),
                "deprecated": list(self.objects.get("deprecated", [])),
            },
            "opened_in_vscode": list(self.opened_in_vscode),
            "displayed_in_claude": [dict(item) for item in self.displayed_in_claude],
            "requested_in_claude": [dict(item) for item in self.requested_in_claude],
            "errors": list(self.errors),
            "next_actions": list(self.next_actions),
        }
        result.update(self.extra)
        return result


class ApiClient(Protocol):
    def call(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        """Call a second-layer API operation and return its serialized result."""


class LlmClient(Protocol):
    def complete(
        self,
        *,
        purpose: str,
        llm_request: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        user_input: str | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a structured LLM result for an orchestration step."""


class ApplicationApiClient:
    """Adapter from operation names to local application API functions."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = root

    def call(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        function = _APPLICATION_OPERATIONS[operation]
        return function(self.root, **kwargs).to_dict()


class SlashCommandInterface:
    def __init__(
        self,
        root: str | Path = ".",
        *,
        api: ApiClient | None = None,
        llm: LlmClient | None = None,
        reviewed_by: str = "user",
    ) -> None:
        self.root = Path(root)
        self.api = api or ApplicationApiClient(root)
        self.llm = llm
        self.reviewed_by = reviewed_by

    def kb_init(self, *, dry_run: bool = False) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        result = self._call(calls, "kb.init", dry_run=dry_run)
        return self._from_api_result(result, calls, "Initialized KBManager workspace.")

    def kb_source_add(
        self,
        input_path: str | Path,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
        authors: list[str] | None = None,
        user_prompt: str | None = None,
        reviewed_user_prompt: str | dict[str, Any] | None = None,
        confirm_user_prompt: bool = False,
        source_llm_result: dict[str, Any] | None = None,
        candidate_llm_result: dict[str, Any] | None = None,
    ) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        confirmed_prompt: str | None = None
        if user_prompt is not None and user_prompt.strip():
            if not confirm_user_prompt:
                try:
                    draft = _source_ingest_prompt_draft(user_prompt, self.llm)
                except ValueError as exc:
                    return _invalid_llm_result(
                        calls,
                        [],
                        "Source ingest prompt rewrite returned an invalid result.",
                        "source_ingest_prompt_rewrite",
                        str(exc),
                    )
                return InterfaceResult(
                    status=ApiStatus.NEEDS_REVIEW.value,
                    summary="Source ingest prompt is waiting for user input in Claude Code.",
                    api_calls=calls,
                    requested_in_claude=[
                        _claude_request(
                            "source_ingest_prompt",
                            "review_source_ingest_prompt",
                            "Reply with approve to use the rewritten prompt, "
                            "or provide revised prompt text.",
                        )
                    ],
                    next_actions=[
                        "Approve or revise the rewritten source ingest prompt in Claude Code."
                    ],
                    extra={"draft": draft},
                )
            try:
                confirmed_prompt = _confirmed_source_ingest_prompt(
                    user_prompt,
                    reviewed_user_prompt,
                    self.llm,
                )
            except ValueError as exc:
                return _invalid_llm_result(
                    calls,
                    [],
                    "Source ingest prompt rewrite returned an invalid result.",
                    "source_ingest_prompt_rewrite",
                    str(exc),
                )

        source = self._call(
            calls,
            "kb.source.add",
            input_path=input_path,
            title=title,
            tags=tags,
            authors=authors,
        )
        if source["status"] != ApiStatus.NEEDS_LLM.value:
            return self._from_api_result(source, calls, "Source add did not reach LLM boundary.")

        source_llm_request = _source_ingest_llm_request(
            source.get("llm_request"),
            confirmed_prompt,
        )
        source_llm_result = source_llm_result or self._complete_llm(
            "source_ingest",
            source_llm_request,
            {
                "input_path": _source_ingest_input_path(source_llm_request, input_path),
                "user_ingest_prompt": confirmed_prompt,
            },
        )
        source = self._call(
            calls,
            "kb.source.add",
            input_path=input_path,
            title=title,
            tags=tags,
            authors=authors,
            resume_token=source["resume"]["token"],
            llm_result=source_llm_result,
        )
        if source["status"] != ApiStatus.SUCCESS.value:
            return self._from_api_result(source, calls, "Source add failed after resume.")

        source_ids = list(source.get("source_ids", []))
        candidate = self._call(calls, "kb.candidate.create", source_ids=source_ids)
        if candidate["status"] != ApiStatus.NEEDS_LLM.value:
            return self._from_api_result(
                candidate,
                calls,
                "Candidate create did not reach LLM boundary.",
            )

        candidate_llm_result = candidate_llm_result or self._complete_llm(
            "create_candidate",
            candidate.get("llm_request"),
            {"source_ids": source_ids},
        )
        candidate = self._call(
            calls,
            "kb.candidate.create",
            source_ids=source_ids,
            resume_token=candidate["resume"]["token"],
            llm_result=candidate_llm_result,
        )
        return self._from_api_result(
            candidate,
            calls,
            "Added source and created candidate drafts.",
            extra={"source": source, "candidate": candidate},
        )

    def kb_source_deprecate(
        self,
        source_id: str,
        *,
        reason: str,
        confirm: bool = False,
    ) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        if not confirm:
            return InterfaceResult(
                status=ApiStatus.NEEDS_REVIEW.value,
                summary="Source deprecation is waiting for explicit user confirmation.",
                api_calls=calls,
                next_actions=["Confirm source deprecation after reviewing the impact."],
                extra={"source_id": source_id, "reason": reason},
            )
        result = self._call(
            calls,
            "kb.source.deprecate",
            source_id=source_id,
            reason=reason,
            decision="deprecate",
            reviewed_by=self.reviewed_by,
        )
        return self._from_api_result(result, calls, "Deprecated source.")

    def kb_candidate_review(
        self,
        candidate_id: str | None = None,
        *,
        decision: str | None = None,
        reason: str | None = None,
        reviewed_markdown: str | dict[str, Any] | None = None,
        merge_targets: list[str] | None = None,
    ) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        if candidate_id is None:
            next_pending = self._call(calls, "kb.candidate.next_pending")
            if (
                next_pending["status"] != ApiStatus.SUCCESS.value
                or not next_pending.get("candidate")
            ):
                return self._from_api_result(next_pending, calls, "No pending candidate available.")
            candidate_id = next_pending["candidate"]["id"]

        candidate = self._call(calls, "kb.candidate.get", candidate_id=candidate_id)
        if candidate["status"] != ApiStatus.SUCCESS.value:
            return self._from_api_result(candidate, calls, "Candidate lookup failed.")

        candidate_payload = candidate["candidate"]
        displayed = [_display_payload_markdown(self.root, candidate_payload)]
        if self.llm is None:
            return InterfaceResult(
                status=ApiStatus.FAILED.value,
                summary="Candidate review requires LLM review assistance.",
                api_calls=calls,
                displayed_in_claude=displayed,
                errors=[
                    {
                        "code": "missing_llm",
                        "message": "candidate review assist must run before a review decision",
                    }
                ],
                next_actions=["Configure an LLM client and rerun candidate review."],
                extra={"candidate": candidate_payload},
            )

        assist = self.llm.complete(
            purpose="candidate_review_assist",
            context={"candidate": candidate_payload},
            prompt=assemble_prompt(
                system_prompt="candidate-review-assist",
                user_input={"candidate_id": candidate_id, "decision": decision},
                object_context={"candidate": candidate_payload},
                output_schema="candidate_review_assist",
                constraints=["read_only", "must_not_bypass_review_gate"],
            ),
        )
        assist_error = _validate_llm_output("candidate_review_assist", assist)
        if assist_error is not None:
            return _invalid_llm_result(
                calls,
                [],
                "Candidate review assist returned an invalid result.",
                "candidate_review_assist",
                assist_error,
                displayed_in_claude=displayed,
            )
        review_draft = _review_payload(None, candidate_payload)

        if decision is None:
            return InterfaceResult(
                status=ApiStatus.NEEDS_REVIEW.value,
                summary="Candidate review is waiting for an explicit user decision.",
                api_calls=calls,
                displayed_in_claude=displayed,
                next_actions=["Choose accept, reject, defer, or merge."],
                extra={
                    "candidate": candidate_payload,
                    "review_assist": assist,
                    "review_draft": review_draft,
                },
            )

        if decision == "reject":
            result = self._call(
                calls,
                "kb.knowledge.reject",
                candidate_id=candidate_id,
                decision="reject",
                reviewed_by=self.reviewed_by,
                reason=reason,
            )
        elif decision == "defer":
            result = self._call(
                calls,
                "kb.candidate.defer",
                candidate_id=candidate_id,
                decision="defer",
                reviewed_by=self.reviewed_by,
                reason=reason,
            )
        elif decision == "accept":
            if reviewed_markdown is None:
                return InterfaceResult(
                    status=ApiStatus.NEEDS_REVIEW.value,
                    summary="Accept review is waiting for user input in Claude Code.",
                    api_calls=calls,
                    displayed_in_claude=displayed,
                    requested_in_claude=[
                        _claude_request(
                            "reviewed_markdown",
                            "accept_candidate",
                            "Reply with approve to use the draft, or provide reviewed "
                            "Markdown frontmatter and body.",
                        )
                    ],
                    next_actions=[
                        "Review the accept draft in Claude Code and reply with approve "
                        "or edited Markdown."
                    ],
                    extra={
                        "candidate": candidate_payload,
                        "review_assist": assist,
                        "review_draft": review_draft,
                    },
                )
            reviewed = _review_payload(reviewed_markdown, candidate_payload)
            result = self._call(
                calls,
                "kb.knowledge.accept",
                candidate_id=candidate_id,
                decision="accept",
                reviewed_by=self.reviewed_by,
                reason=reason,
                title=reviewed.get("title"),
                summary=reviewed.get("summary"),
                content=reviewed.get("content"),
                evidence=reviewed.get("evidence"),
                bindto=reviewed.get("bindto"),
            )
        elif decision == "merge":
            if not merge_targets:
                return InterfaceResult(
                    status=ApiStatus.FAILED.value,
                    summary="Merge review requires at least one target knowledge ID.",
                    api_calls=calls,
                    displayed_in_claude=displayed,
                    errors=[
                        {
                            "code": "missing_merge_target",
                            "message": "merge_targets is required",
                        }
                    ],
                )
            merge_assist = self.llm.complete(
                purpose="knowledge_merge_assist",
                context={
                    "candidate": candidate_payload,
                    "target_knowledge_id": merge_targets[0],
                },
                prompt=assemble_prompt(
                    system_prompt="knowledge-merge-assist",
                    user_input={
                        "candidate_id": candidate_id,
                        "target_knowledge_id": merge_targets[0],
                        "reason": reason,
                    },
                    object_context={
                        "candidate": candidate_payload,
                        "target_knowledge_id": merge_targets[0],
                    },
                    output_schema="knowledge_merge_assist",
                    constraints=["proposal_only", "final_payload_must_be_user_reviewed"],
                ),
            )
            merge_error = _validate_llm_output("knowledge_merge_assist", merge_assist)
            if merge_error is not None:
                return _invalid_llm_result(
                    calls,
                    [],
                    "Knowledge merge assist returned an invalid result.",
                    "knowledge_merge_assist",
                    merge_error,
                    displayed_in_claude=displayed,
                )
            if reviewed_markdown is None:
                return InterfaceResult(
                    status=ApiStatus.NEEDS_REVIEW.value,
                    summary="Merge review is waiting for user input in Claude Code.",
                    api_calls=calls,
                    displayed_in_claude=displayed,
                    requested_in_claude=[
                        _claude_request(
                            "reviewed_markdown",
                            "merge_candidate",
                            "Reply with approve to use the merge draft, or provide reviewed "
                            "Markdown frontmatter and body.",
                        )
                    ],
                    next_actions=[
                        "Review the merge draft in Claude Code and reply with approve "
                        "or edited Markdown."
                    ],
                    extra={
                        "candidate": candidate_payload,
                        "review_assist": assist,
                        "merge_assist": merge_assist,
                        "review_draft": {
                            **review_draft,
                            "summary": merge_assist["merged_summary"],
                            "content": merge_assist["merged_content"],
                            "evidence": merge_assist["evidence"],
                            "bindto": merge_assist["bindto"],
                        },
                    },
                )
            reviewed = _review_payload(reviewed_markdown, candidate_payload)
            result = self._call(
                calls,
                "kb.knowledge.merge",
                candidate_id=candidate_id,
                target_knowledge_id=merge_targets[0],
                decision="merge",
                reviewed_by=self.reviewed_by,
                reason=reason,
                title=reviewed.get("title"),
                summary=reviewed.get("summary"),
                content=reviewed.get("content"),
                evidence=reviewed.get("evidence"),
                bindto=reviewed.get("bindto"),
            )
        else:
            return InterfaceResult(
                status=ApiStatus.FAILED.value,
                summary=f"Unsupported candidate review decision: {decision}",
                api_calls=calls,
                displayed_in_claude=displayed,
                errors=[{"code": "invalid_decision", "message": decision}],
            )

        return self._from_api_result(
            result,
            calls,
            "Candidate review completed.",
            displayed_in_claude=displayed,
            extra={
                "candidate": candidate_payload,
                "review_assist": assist,
                "review_draft": review_draft,
                **({"merge_assist": merge_assist} if decision == "merge" else {}),
            },
        )

    def kb_knowledgebase_create(
        self,
        *,
        title: str,
        input_path: str | Path,
        knowledgebase_id: str | None = None,
        init_llm_result: dict[str, Any] | None = None,
        reviewed_markdown: str | dict[str, Any] | None = None,
        approve: bool = False,
    ) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        created = self._call(
            calls,
            "kb.knowledgebase.create",
            title=title,
            knowledgebase_id=knowledgebase_id,
        )
        if created["status"] != ApiStatus.SUCCESS.value:
            return self._from_api_result(created, calls, "Knowledgebase create failed.")
        kb_id = created["knowledgebase_id"]
        init_result = self._call(
            calls,
            "kb.knowledgebase.init",
            knowledgebase_id=kb_id,
            input_path=input_path,
        )
        if init_result["status"] != ApiStatus.NEEDS_LLM.value:
            return self._from_api_result(
                init_result,
                calls,
                "Knowledgebase init did not reach LLM boundary.",
            )
        init_llm_result = init_llm_result or self._complete_llm(
            "knowledgebase_create",
            init_result.get("llm_request"),
            {"knowledgebase_id": kb_id, "input_path": str(input_path)},
        )
        reviewed = _knowledgebase_review_payload(reviewed_markdown, init_llm_result)
        review = {"decision": "approve", "reviewed_by": self.reviewed_by} if approve else None
        init_result = self._call(
            calls,
            "kb.knowledgebase.init",
            knowledgebase_id=kb_id,
            input_path=input_path,
            resume_token=init_result["resume"]["token"],
            llm_result=init_llm_result,
            review=review,
            reviewed_payload=reviewed if approve else None,
        )
        if init_result["status"] == ApiStatus.NEEDS_REVIEW.value:
            return InterfaceResult(
                status=ApiStatus.NEEDS_REVIEW.value,
                summary="Knowledgebase draft is waiting for user input in Claude Code.",
                api_calls=calls,
                requested_in_claude=[
                        _claude_request(
                            "reviewed_markdown",
                            "init_knowledgebase",
                            "Reply with approve to use the draft, or provide reviewed "
                            "structured fields.",
                        )
                ],
                next_actions=["Approve or revise the knowledgebase draft in Claude Code."],
                extra={"created": created, "draft": init_result.get("draft")},
            )
        return self._from_api_result(
            init_result,
            calls,
            "Created and initialized knowledgebase.",
            extra={"created": created, "initialized": init_result},
        )

    def kb_knowledgebase_list(self, knowledgebase_id: str | None = None) -> InterfaceResult:
        path = (
            f"indexes/knowledgebase/{knowledgebase_id}-knowledge-index.md"
            if knowledgebase_id
            else "indexes/kb-index.md"
        )
        if not (self.root / path).is_file():
            return InterfaceResult(
                status=ApiStatus.NEEDS_REVIEW.value,
                summary="Knowledgebase index is missing.",
                next_actions=["Run /kb-check before opening the knowledgebase index."],
                extra={"missing_index": path},
            )
        return InterfaceResult(
            status=ApiStatus.SUCCESS.value,
            summary="Displayed knowledgebase index.",
            displayed_in_claude=[_display_markdown_path(self.root, path)],
        )

    def kb_knowledgebase_map(
        self,
        knowledgebase_id: str | None = None,
        *,
        output_path: str | Path | None = None,
    ) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        result = self._call(
            calls,
            "kb.knowledgebase.map",
            knowledgebase_id=knowledgebase_id,
            output_path=output_path,
        )
        opened = [result["path"]] if result.get("path") else []
        return self._from_api_result(
            result,
            calls,
            "Generated knowledgebase map.",
            opened_in_vscode=opened,
            displayed_in_claude=[],
        )

    def kb_note_add(
        self,
        *,
        content: str | None = None,
        title: str | None = None,
    ) -> InterfaceResult:
        if content is None:
            return InterfaceResult(
                status=ApiStatus.NEEDS_REVIEW.value,
                summary="Note add is waiting for user input in Claude Code.",
                requested_in_claude=[
                    _claude_request(
                        "note_markdown",
                        "add_note",
                        "Reply with note Markdown content and an optional title.",
                    )
                ],
                next_actions=["Provide the note content in Claude Code."],
            )
        calls: list[ApiCallRecord] = []
        result = self._call(
            calls,
            "kb.note.add",
            content=content,
            title=title,
            needs_llm=True,
        )
        if result["status"] == ApiStatus.NEEDS_LLM.value:
            llm_result = self._complete_llm(
                "note_title",
                result.get("llm_request"),
                {"content": content},
            )
            result = self._call(
                calls,
                "kb.note.add",
                content=content,
                title=title,
                needs_llm=True,
                resume_token=result["resume"]["token"],
                llm_result=llm_result,
            )
        return self._from_api_result(result, calls, "Added note.")

    def kb_note_list(self) -> InterfaceResult:
        path = "indexes/note-index.md"
        if not (self.root / path).is_file():
            return InterfaceResult(
                status=ApiStatus.NEEDS_REVIEW.value,
                summary="Note index is missing.",
                next_actions=["Run /kb-check before opening the note index."],
                extra={"missing_index": path},
            )
        return InterfaceResult(
            status=ApiStatus.SUCCESS.value,
            summary="Displayed note index.",
            displayed_in_claude=[_display_markdown_path(self.root, path)],
        )

    def kb_note_view(self, note_id: str) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        result = self._call(calls, "kb.note.get", note_id=note_id)
        displayed = [_display_note_payload(self.root, result["note"])] if result.get("note") else []
        return self._from_api_result(
            result,
            calls,
            "Displayed note.",
            displayed_in_claude=displayed,
        )

    def kb_note_deprecate(
        self,
        note_id: str,
        *,
        reason: str,
        confirm: bool = False,
    ) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        if not confirm:
            return InterfaceResult(
                status=ApiStatus.NEEDS_REVIEW.value,
                summary="Note deprecation is waiting for explicit user confirmation.",
                api_calls=calls,
                next_actions=["Confirm note deprecation after reviewing the note."],
                extra={"note_id": note_id, "reason": reason},
            )
        result = self._call(
            calls,
            "kb.note.deprecate",
            note_id=note_id,
            reason=reason,
            decision="deprecate",
            reviewed_by=self.reviewed_by,
        )
        return self._from_api_result(result, calls, "Deprecated note.")

    def kb_check(self) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        result = self._call(calls, "kb.index.rebuild")
        return self._from_api_result(result, calls, "Rebuilt indexes and checked consistency.")

    def kb_clean(self) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        result = self._call(calls, "kb.clean.inspect")
        if result["status"] == ApiStatus.NEEDS_LLM.value:
            llm_result = self._complete_llm(
                "clean_migration_plan",
                result.get("llm_request"),
                {"differences": result.get("llm_request", {}).get("prompt", "")},
            )
            result = dict(result)
            result["migration_plan"] = llm_result
        return self._from_api_result(result, calls, "Inspected workspace for clean migration.")

    def _call(self, calls: list[ApiCallRecord], operation: str, **kwargs: Any) -> dict[str, Any]:
        result = self.api.call(operation, **kwargs)
        calls.append(ApiCallRecord(operation, result.get("status", "unknown")))
        return result

    def _complete_llm(
        self,
        purpose: str,
        llm_request: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError(f"LLM result required for {purpose}")
        return self.llm.complete(
            purpose=purpose,
            llm_request=llm_request,
            context=context,
            prompt=llm_request.get("prompt") if llm_request else None,
        )

    def _from_api_result(
        self,
        result: dict[str, Any],
        calls: list[ApiCallRecord],
        summary: str,
        *,
        opened_in_vscode: list[str] | None = None,
        displayed_in_claude: list[dict[str, str]] | None = None,
        requested_in_claude: list[dict[str, str]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> InterfaceResult:
        merged_extra = dict(extra or {})
        for key, value in result.items():
            if key not in {
                "status",
                "operation",
                "objects",
                "diffs",
                "warnings",
                "errors",
                "review",
                "next_actions",
            }:
                merged_extra.setdefault(key, value)
        return InterfaceResult(
            status=result["status"],
            summary=summary,
            api_calls=calls,
            objects=result.get("objects", {"created": [], "updated": [], "deprecated": []}),
            opened_in_vscode=opened_in_vscode or [],
            displayed_in_claude=displayed_in_claude or [],
            requested_in_claude=requested_in_claude or [],
            errors=result.get("errors", []),
            next_actions=result.get("next_actions", []),
            extra=merged_extra,
        )


def _display_markdown_path(root: Path, relative_path: str) -> dict[str, str]:
    return {
        "path": relative_path,
        "format": "markdown",
        "content": (root / relative_path).read_text(encoding="utf-8"),
    }


def _display_payload_markdown(root: Path, payload: dict[str, Any]) -> dict[str, str]:
    path = str(payload.get("path", ""))
    if path and (root / path).is_file():
        return _display_markdown_path(root, path)
    return {
        "path": path,
        "format": "markdown",
        "content": str(payload.get("body", "")),
    }


def _display_note_payload(root: Path, note: dict[str, Any]) -> dict[str, str]:
    return _display_payload_markdown(root, note)


def _claude_request(kind: str, action: str, instructions: str) -> dict[str, str]:
    return {
        "kind": kind,
        "action": action,
        "instructions": instructions,
    }


def _review_payload(
    reviewed_markdown: str | dict[str, Any] | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(reviewed_markdown, dict):
        payload = dict(reviewed_markdown)
        payload.setdefault("body", candidate.get("body", ""))
        return payload
    if isinstance(reviewed_markdown, str):
        document = ObjectRepository.parse_markdown(reviewed_markdown, source="<review>")
        payload = dict(document.frontmatter)
        payload["body"] = document.body
        return payload

    frontmatter = dict(candidate.get("frontmatter", {}))
    return {
        "title": frontmatter.get("title"),
        "summary": frontmatter.get("summary"),
        "content": candidate.get("body"),
        "evidence": frontmatter.get("evidence", []),
        "bindto": frontmatter.get("bindto", []),
    }


def _validate_llm_output(schema_name: str, result: Any) -> str | None:
    if not isinstance(result, dict):
        return "LLM result must be a mapping."
    schema = schema_for_output(schema_name)
    required = schema.get("required", [])
    if isinstance(required, list):
        for field in required:
            if field not in result:
                return f"LLM result is missing required field: {field}"
    if schema_name == "knowledge_merge_assist":
        if not isinstance(result.get("merged_summary"), str) or not result[
            "merged_summary"
        ].strip():
            return "knowledge_merge_assist.merged_summary must be a non-empty string"
        if not isinstance(result.get("merged_content"), str) or not result[
            "merged_content"
        ].strip():
            return "knowledge_merge_assist.merged_content must be a non-empty string"
        if not _is_mapping_list(result.get("evidence")):
            return "knowledge_merge_assist.evidence must be a list of mappings"
        if not _is_mapping_list(result.get("bindto")):
            return "knowledge_merge_assist.bindto must be a list of mappings"
        if not isinstance(result.get("evidence_review"), list):
            return "knowledge_merge_assist.evidence_review must be a list"
    if schema_name == "candidate_review_assist":
        if not isinstance(result.get("summary"), str) or not result["summary"].strip():
            return "candidate_review_assist.summary must be a non-empty string"
        if not isinstance(result.get("evidence_review"), list):
            return "candidate_review_assist.evidence_review must be a list"
        if not _is_mapping_list(result.get("bindto")):
            return "candidate_review_assist.bindto must be a list of mappings"
        if not isinstance(result.get("recommendations"), list):
            return "candidate_review_assist.recommendations must be a list"
    if schema_name == "source_ingest_prompt_rewrite":
        if not isinstance(result.get("rewritten_prompt"), str) or not result[
            "rewritten_prompt"
        ].strip():
            return "source_ingest_prompt_rewrite.rewritten_prompt must be a non-empty string"
        if not isinstance(result.get("intent_summary"), str) or not result[
            "intent_summary"
        ].strip():
            return "source_ingest_prompt_rewrite.intent_summary must be a non-empty string"
        if not _is_string_list(result.get("constraints")):
            return "source_ingest_prompt_rewrite.constraints must be a list of strings"
        if not _is_string_list(result.get("warnings")):
            return "source_ingest_prompt_rewrite.warnings must be a list of strings"
    if schema_name == "knowledgebase_create_draft":
        frontmatter = result.get("frontmatter")
        if not isinstance(frontmatter, dict):
            return "knowledgebase_create_draft.frontmatter must be a mapping"
        for field in ("description",):
            if not isinstance(frontmatter.get(field), str) or not frontmatter[field].strip():
                return f"knowledgebase_create_draft.frontmatter.{field} must be a non-empty string"
        if not _is_string_list(frontmatter.get("tags", [])):
            return "knowledgebase_create_draft.frontmatter.tags must be a list of strings"
        if not isinstance(frontmatter.get("scope"), dict):
            return "knowledgebase_create_draft.frontmatter.scope must be a mapping"
        if not isinstance(frontmatter.get("outline"), list):
            return "knowledgebase_create_draft.frontmatter.outline must be a list"
        if not isinstance(result.get("body"), str) or not result["body"].strip():
            return "knowledgebase_create_draft.body must be a non-empty string"
    return None


def _invalid_llm_result(
    calls: list[ApiCallRecord],
    opened: list[str],
    summary: str,
    purpose: str,
    message: str,
    *,
    displayed_in_claude: list[dict[str, str]] | None = None,
) -> InterfaceResult:
    return InterfaceResult(
        status=ApiStatus.FAILED.value,
        summary=summary,
        api_calls=calls,
        opened_in_vscode=opened,
        displayed_in_claude=displayed_in_claude or [],
        errors=[
            {
                "code": "invalid_llm_result",
                "message": message,
                "purpose": purpose,
            }
        ],
        next_actions=["Retry the LLM step with output that matches the required schema."],
    )


def _knowledgebase_review_payload(
    reviewed_markdown: str | dict[str, Any] | None,
    draft: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(reviewed_markdown, dict):
        return dict(reviewed_markdown)
    if isinstance(reviewed_markdown, str):
        document = ObjectRepository.parse_markdown(reviewed_markdown, source="<review>")
        payload = dict(document.frontmatter)
        return payload
    if isinstance(draft.get("frontmatter"), dict):
        return dict(draft["frontmatter"])
    return dict(draft)


def _source_ingest_prompt_draft(
    user_prompt: str,
    llm: LlmClient | None,
) -> dict[str, Any]:
    if llm is None:
        raise ValueError("LLM client is required to rewrite source ingest prompt")
    result = llm.complete(
        purpose="source_ingest_prompt_rewrite",
        context={"user_prompt": user_prompt},
        prompt=assemble_prompt(
            system_prompt="source-ingest-prompt-rewrite",
            user_input={"user_prompt": user_prompt},
            object_context={},
            output_schema="source_ingest_prompt_rewrite",
            constraints=[
                "rewrite_only",
                "requires_user_approval",
                "must_not_override_kbmanager_system_prompt",
            ],
        ),
    )
    error = _validate_llm_output("source_ingest_prompt_rewrite", result)
    if error is not None:
        raise ValueError(error)
    return result


def _confirmed_source_ingest_prompt(
    user_prompt: str,
    reviewed_user_prompt: str | dict[str, Any] | None,
    llm: LlmClient | None,
) -> str:
    if isinstance(reviewed_user_prompt, str) and reviewed_user_prompt.strip():
        return reviewed_user_prompt.strip()
    if isinstance(reviewed_user_prompt, dict):
        value = reviewed_user_prompt.get("rewritten_prompt")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(_source_ingest_prompt_draft(user_prompt, llm)["rewritten_prompt"]).strip()


def _source_ingest_llm_request(
    llm_request: dict[str, Any] | None,
    user_ingest_prompt: str | None,
) -> dict[str, Any] | None:
    if llm_request is None or not user_ingest_prompt:
        return llm_request
    enhanced = copy.deepcopy(llm_request)
    prompt = enhanced.get("prompt")
    if isinstance(prompt, dict):
        sections = prompt.setdefault("sections", [])
        if isinstance(sections, list):
            sections.append(
                {
                    "role": "user",
                    "name": "confirmed_user_ingest_prompt",
                    "content": user_ingest_prompt,
                }
            )
    enhanced["user_ingest_prompt"] = user_ingest_prompt
    return enhanced


def _source_ingest_input_path(
    llm_request: dict[str, Any] | None,
    fallback: str | Path,
) -> str:
    if isinstance(llm_request, dict):
        required_context = llm_request.get("required_context")
        if (
            isinstance(required_context, list)
            and len(required_context) == 1
            and isinstance(required_context[0], str)
            and required_context[0].strip()
        ):
            return required_context[0]
    return str(fallback)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_mapping_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


_APPLICATION_OPERATIONS = {
    "kb.init": application.init_workspace,
    "kb.source.add": application.source_add,
    "kb.source.deprecate": application.source_deprecate,
    "kb.candidate.create": application.candidate_create,
    "kb.candidate.get": application.candidate_get,
    "kb.candidate.next_pending": application.candidate_next_pending,
    "kb.candidate.defer": application.candidate_defer,
    "kb.knowledge.accept": application.knowledge_accept,
    "kb.knowledge.reject": application.knowledge_reject,
    "kb.knowledge.merge": application.knowledge_merge,
    "kb.knowledge.deprecate": application.knowledge_deprecate,
    "kb.knowledgebase.create": application.knowledgebase_create,
    "kb.knowledgebase.init": application.knowledgebase_init,
    "kb.knowledgebase.map": application.knowledgebase_map,
    "kb.note.add": application.note_add,
    "kb.note.get": application.note_get,
    "kb.note.deprecate": application.note_deprecate,
    "kb.index.rebuild": application.index_rebuild,
    "kb.clean.inspect": application.clean_inspect,
}
