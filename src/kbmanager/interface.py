"""Claude Code interaction orchestration layer.

This module is the first-layer boundary described by ``docs/Interface.md``.
It coordinates user-facing workflows into second-layer ``kb.*`` API calls, but
does not write object files itself.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import kbmanager.application as application
from kbmanager.contracts import ApiStatus
from kbmanager.llm_logging import write_llm_log
from kbmanager.prompts import schema_for_output
from kbmanager.repository import ObjectRepository
from kbmanager.workspace import Workspace


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


class LoggedLlmClient:
    """Record every delegated LLM request and response in the workspace."""

    def __init__(self, root: str | Path, delegate: LlmClient) -> None:
        self.root = Path(root)
        self.delegate = delegate

    def complete(
        self,
        *,
        purpose: str,
        llm_request: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        user_input: str | None = None,
        prompt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_payload = {
            "purpose": purpose,
            "llm_request": llm_request,
            "context": context,
            "user_input": user_input,
            "prompt": prompt,
        }
        try:
            result = self.delegate.complete(
                purpose=purpose,
                llm_request=llm_request,
                context=context,
                user_input=user_input,
                prompt=prompt,
            )
        except Exception as exc:
            write_llm_log(self.root, purpose=purpose, input_payload=input_payload, error=str(exc))
            raise
        write_llm_log(
            self.root, purpose=purpose, input_payload=input_payload, output_payload=result
        )
        return result


class InteractionInterface:
    def __init__(
        self,
        root: str | Path = ".",
        *,
        api: ApiClient | None = None,
        llm: LlmClient | None = None,
    ) -> None:
        self.root = Path(root)
        self.api = api or ApplicationApiClient(root)
        self.llm = LoggedLlmClient(self.root, llm) if llm is not None else None

    def kb_init(self) -> InterfaceResult:
        calls: list[ApiCallRecord] = []
        result = self._call(calls, "kb.init")
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
                        "source_ingest_prompt",
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
                    "source_ingest_prompt",
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

        return self._from_api_result(
            source,
            calls,
            "Added source.",
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
            if next_pending["status"] != ApiStatus.SUCCESS.value or not next_pending.get(
                "candidate"
            ):
                return self._from_api_result(next_pending, calls, "No pending candidate available.")
            candidate_id = next_pending["candidate"]["id"]

        candidate = self._call(calls, "kb.candidate.get", candidate_id=candidate_id)
        if candidate["status"] != ApiStatus.SUCCESS.value:
            return self._from_api_result(candidate, calls, "Candidate lookup failed.")

        candidate_payload = candidate["candidate"]
        displayed = [_display_payload_markdown(self.root, candidate_payload)]
        assist = _candidate_review_guidance(candidate_payload)
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
                reason=reason,
            )
        elif decision == "defer":
            result = self._call(
                calls,
                "kb.candidate.defer",
                candidate_id=candidate_id,
                decision="defer",
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
            try:
                _knowledge_payload(self.root, merge_targets[0])
            except (OSError, ValueError) as exc:
                return InterfaceResult(
                    status=ApiStatus.FAILED.value,
                    summary="Merge review target knowledge lookup failed.",
                    api_calls=calls,
                    displayed_in_claude=displayed,
                    errors=[{"code": "target_knowledge_not_found", "message": str(exc)}],
                )
            if reviewed_markdown is None:
                return InterfaceResult(
                    status=ApiStatus.NEEDS_REVIEW.value,
                    summary="Merge review requires user-reviewed merge content.",
                    api_calls=calls,
                    displayed_in_claude=displayed,
                    requested_in_claude=[
                        _claude_request(
                            "reviewed_markdown",
                            "merge_candidate",
                            "Provide reviewed merge Markdown frontmatter and body.",
                        )
                    ],
                    next_actions=[
                        "Provide reviewed summary, content, evidence, and bindto for the merge."
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
                "kb.knowledge.merge",
                candidate_id=candidate_id,
                target_knowledge_id=merge_targets[0],
                decision="merge",
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
        create_result = self._call(
            calls,
            "kb.knowledgebase.create",
            title=title,
            input_path=input_path,
            knowledgebase_id=knowledgebase_id,
        )
        if create_result["status"] == ApiStatus.NEEDS_LLM.value:
            llm_result = init_llm_result or self._complete_llm(
                "knowledgebase_create",
                create_result.get("llm_request"),
                {"title": title, "input_path": str(input_path)},
            )
            create_result = self._call(
                calls,
                "kb.knowledgebase.create",
                title=title,
                input_path=input_path,
                knowledgebase_id=knowledgebase_id,
                resume_token=create_result["resume"]["token"],
                llm_result=llm_result,
            )
        if create_result["status"] == ApiStatus.NEEDS_REVIEW.value:
            draft = create_result.get("reviewed_payload") or create_result.get(
                "knowledgebase_draft", {}
            )
            reviewed = _knowledgebase_review_payload(reviewed_markdown, draft)
            if approve:
                create_result = self._call(
                    calls,
                    "kb.knowledgebase.create",
                    title=title,
                    knowledgebase_id=knowledgebase_id,
                    description=reviewed.get("description"),
                    tags=reviewed.get("tags", []),
                    scope=reviewed.get("scope"),
                    default_outline_id=reviewed.get("default_outline_id"),
                    outlines=reviewed.get("outlines"),
                    review={"decision": "approve"},
                )
                return self._from_api_result(
                    create_result,
                    calls,
                    "Created knowledgebase.",
                    extra={"draft": reviewed},
                )
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
                extra={"draft": reviewed},
            )
        return self._from_api_result(
            create_result,
            calls,
            "Created knowledgebase.",
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
                next_actions=["Run kb.index.rebuild before opening the knowledgebase index."],
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
                next_actions=["Run kb.index.rebuild before opening the note index."],
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


def _knowledge_payload(root: Path, knowledge_id: str) -> dict[str, Any]:
    workspace = Workspace(root)
    repository = ObjectRepository(workspace)
    matches = [
        record
        for record in repository.iter_object_metadata()
        if record.object_id == knowledge_id and record.metadata.get("type") == "knowledge"
    ]
    if not matches:
        raise ValueError(f"target knowledge not found: {knowledge_id}")
    if len(matches) > 1:
        raise ValueError(f"target knowledge ID is duplicated: {knowledge_id}")
    record = matches[0]
    document = repository.read_markdown(workspace.relative(record.path))
    return {
        "id": knowledge_id,
        "path": str(workspace.relative(record.path)),
        "frontmatter": document.frontmatter,
        "body": document.body,
    }


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


def _candidate_review_guidance(candidate: dict[str, Any]) -> dict[str, Any]:
    frontmatter = dict(candidate.get("frontmatter", {}))
    return {
        "summary": frontmatter.get("summary", ""),
        "evidence_review": frontmatter.get("evidence", []),
        "bindto": frontmatter.get("bindto", []),
        "outline_change_suggestions": frontmatter.get("outline_change_suggestions", []),
        "recommendations": [
            "Human reviewer must choose accept, reject, defer, or merge.",
            "Review assistance is read-only and is not user approval.",
        ],
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
        if (
            not isinstance(frontmatter.get("default_outline_id"), str)
            or not frontmatter["default_outline_id"].strip()
        ):
            return (
                "knowledgebase_create_draft.frontmatter.default_outline_id "
                "must be a non-empty string"
            )
        if not isinstance(frontmatter.get("outlines"), list):
            return "knowledgebase_create_draft.frontmatter.outlines must be a list"
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
    prompt = user_prompt.strip()
    if not prompt:
        raise ValueError("source ingest prompt must be non-empty")
    warnings = []
    lowered = prompt.casefold()
    unsafe_markers = ("ignore system", "bypass", "fabricate", "make up", "skip review")
    if any(marker in lowered for marker in unsafe_markers):
        warnings.append(
            "Prompt may conflict with KBManager boundaries; source ingest rules "
            "remain authoritative."
        )
    return {
        "rewritten_prompt": prompt,
        "intent_summary": "Use the confirmed temporary source-ingest guidance.",
        "constraints": [
            "Must not override KBManager system prompt, schema, evidence, or review rules."
        ],
        "warnings": warnings,
    }


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
    "kb.knowledgebase.outline.create": application.knowledgebase_outline_create,
    "kb.knowledgebase.outline.set_default": application.knowledgebase_outline_set_default,
    "kb.knowledgebase.outline.archive": application.knowledgebase_outline_archive,
    "kb.knowledgebase.map": application.knowledgebase_map,
    "kb.note.add": application.note_add,
    "kb.note.get": application.note_get,
    "kb.note.deprecate": application.note_deprecate,
    "kb.index.rebuild": application.index_rebuild,
    "kb.clean.inspect": application.clean_inspect,
}
