"""Application API entry points."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

import yaml

from kbmanager.contracts import ApiResult, ApiStatus, ObjectChanges, ReviewRequest
from kbmanager.errors import KBManagerError, RepositoryError, WorkspacePathError
from kbmanager.prompts import prompt_descriptor
from kbmanager.repository import MarkdownDocument, ObjectRepository
from kbmanager.workspace import Workspace

INIT_OPERATION = "kb.init"
SOURCE_ADD_OPERATION = "kb.source.add"
SOURCE_DEPRECATE_OPERATION = "kb.source.deprecate"
CANDIDATE_CREATE_OPERATION = "kb.candidate.create"
CANDIDATE_GET_OPERATION = "kb.candidate.get"
CANDIDATE_NEXT_PENDING_OPERATION = "kb.candidate.next_pending"
CANDIDATE_DEFER_OPERATION = "kb.candidate.defer"
KNOWLEDGE_ACCEPT_OPERATION = "kb.knowledge.accept"
KNOWLEDGE_REJECT_OPERATION = "kb.knowledge.reject"
KNOWLEDGE_MERGE_OPERATION = "kb.knowledge.merge"
KNOWLEDGE_DEPRECATE_OPERATION = "kb.knowledge.deprecate"
KNOWLEDGEBASE_CREATE_OPERATION = "kb.knowledgebase.create"
KNOWLEDGEBASE_OUTLINE_CREATE_OPERATION = "kb.knowledgebase.outline.create"
KNOWLEDGEBASE_OUTLINE_SET_DEFAULT_OPERATION = "kb.knowledgebase.outline.set_default"
KNOWLEDGEBASE_OUTLINE_ARCHIVE_OPERATION = "kb.knowledgebase.outline.archive"
KNOWLEDGEBASE_MAP_OPERATION = "kb.knowledgebase.map"
NOTE_ADD_OPERATION = "kb.note.add"
NOTE_GET_OPERATION = "kb.note.get"
NOTE_DEPRECATE_OPERATION = "kb.note.deprecate"
INDEX_REBUILD_OPERATION = "kb.index.rebuild"
CLEAN_INSPECT_OPERATION = "kb.clean.inspect"

INIT_DIRECTORIES = (
    "data/raw/md",
    "data/raw/pdf",
    "data/cleaned",
    "data/attachments",
    "candidates/pending",
    "candidates/rejected",
    "candidates/deferred",
    "knowledge/atomic",
    "knowledge/bases",
    "notes/active",
    "notes/deprecated",
    "indexes/knowledgebase",
)
INIT_DIRECTORY_PLACEHOLDER = "KBM.ignore"


def _all_init_directories() -> tuple[str, ...]:
    directories: set[str] = set()
    for relative_dir in INIT_DIRECTORIES:
        path = Path(relative_dir)
        parts = path.parts
        for index in range(1, len(parts) + 1):
            directories.add(str(Path(*parts[:index])))
    return tuple(sorted(directories))


SYSTEM_TEMPLATE_PACKAGE = "kbmanager.templates"
SYSTEM_TEMPLATE_FILES = (
    "source.md",
    "source-meta.yml",
    "candidate.md",
    "knowledge.md",
    "knowledge-base.md",
    "note.md",
)

INIT_INDEX_FILES = {
    "indexes/manifest.yml": """version: 1
generated_from: object_files
indexes:
  - source-index.md
  - knowledge-index.md
  - tag-index.md
  - kb-index.md
  - note-index.md
  - review-queue.md
""",
    "indexes/source-index.md": "# Source Index\n\n",
    "indexes/knowledge-index.md": "# Knowledge Index\n\n",
    "indexes/tag-index.md": "# Tag Index\n\n",
    "indexes/kb-index.md": "# Knowledge Base Index\n\n",
    "indexes/note-index.md": "# Note Index\n\n",
    "indexes/review-queue.md": "# Review Queue\n\n",
}
INIT_DIRECTORY_PLACEHOLDER_FILES = {
    f"{directory}/{INIT_DIRECTORY_PLACEHOLDER}": "" for directory in _all_init_directories()
}
INIT_FILES = {**INIT_INDEX_FILES, **INIT_DIRECTORY_PLACEHOLDER_FILES}


def system_template_text(name: str) -> str:
    """Return a KBManager-owned object template bundled with the package."""

    if name not in SYSTEM_TEMPLATE_FILES:
        raise ValueError(f"unknown system template: {name}")
    return (
        importlib.resources.files(SYSTEM_TEMPLATE_PACKAGE)
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


@dataclass(frozen=True)
class InitPlan:
    create_directories: list[str]
    create_files: list[str]
    existing: list[str]
    conflicts: list[str]


@dataclass(frozen=True)
class ObjectRecord:
    object_id: str
    object_type: str
    status: str
    path: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SourceInput:
    path: Path
    relative_path: str
    source_kind: str
    title_hint: str


SUPPORTED_SOURCE_SUFFIXES = {".md", ".pdf"}
ID_RE = re.compile(r"^[a-z]+-\d{8}-\d{3}(?:-[^\W_]+(?:-[^\W_]+)*)?$")
INDEX_SCOPES = {
    "all",
    "source",
    "candidate",
    "knowledge",
    "knowledgebase",
    "note",
    "review_queue",
    "tag",
}
INDEX_MARKDOWN_PATHS = (
    "indexes/source-index.md",
    "indexes/knowledge-index.md",
    "indexes/tag-index.md",
    "indexes/kb-index.md",
    "indexes/note-index.md",
    "indexes/review-queue.md",
)
INDEX_YAML_PATHS: tuple[str, ...] = ()
BINDTO_SHAPE = (
    "bindto must be [] when there are no knowledgebase bindings, or mappings like "
    "{'kb_id': 'kb-YYYYMMDD-001-title', 'outline_id': 'outline-id', "
    "'node_id': 'node-id', "
    "'reason': 'reviewed binding reason'}"
)
EVIDENCE_SHAPE = (
    "evidence items must be mappings like {'source_id': '<requested-source-or-note-id>', "
    "'locator': '<section/page/line>', 'quote': '<verbatim support>'}; object_id or id may "
    "be used instead of source_id"
)


def init_workspace(
    root: str | Path = ".",
) -> ApiResult:
    """Initialize a controlled KBManager workspace."""

    try:
        workspace = Workspace(root)
        plan = _plan_init(workspace)
    except (KBManagerError, OSError) as exc:
        return ApiResult.failed(
            INIT_OPERATION,
            "invalid_workspace",
            str(exc),
            "Choose a writable directory inside the target workspace.",
        )

    if plan.conflicts:
        return ApiResult.failed(
            INIT_OPERATION,
            "init_conflict",
            "Initialization found incompatible existing paths.",
            "Move or rename the conflicting paths, then run kb.init again.",
            diffs=_plan_diffs(plan),
            warnings=plan.conflicts,
        )

    created_paths: list[Path] = []
    try:
        for directory in plan.create_directories:
            path = workspace.resolve(directory)
            _create_directory(path, workspace.root, created_paths)

        for relative_path in plan.create_files:
            path = workspace.resolve(relative_path)
            _write_new_text_atomic(path, INIT_FILES[relative_path])
            created_paths.append(path)
    except (OSError, KBManagerError) as exc:
        _rollback_created(created_paths)
        return ApiResult.failed(
            INIT_OPERATION,
            "init_write_failed",
            str(exc),
            "Check directory permissions and rerun kb.init.",
        )

    return ApiResult.success(
        INIT_OPERATION,
        objects=ObjectChanges(created=plan.create_directories + plan.create_files),
        diffs=_plan_diffs(plan),
        warnings=[],
        next_actions=["Add sources with kb.source.add when you are ready."],
    )


def source_add(
    root: str | Path = ".",
    *,
    input_path: str | Path,
    title: str | None = None,
    tags: list[str] | None = None,
    authors: list[str] | None = None,
    resume_token: str | None = None,
    llm_result: dict[str, Any] | None = None,
) -> ApiResult:
    """Add a local Markdown/PDF source through the source-ingest LLM boundary."""

    try:
        workspace = Workspace(root)
        _validate_source_add_input(title=title, tags=tags, authors=authors)
        source_inputs = _source_inputs(workspace, input_path)
        token_payload = {
            "input_path": str(Path(input_path)),
            "inputs": [source.relative_path for source in source_inputs],
            "title": title,
            "tags": tags or [],
            "authors": authors or [],
        }
    except (KBManagerError, OSError) as exc:
        suggestion, next_actions = _source_add_input_failure_recovery()
        return ApiResult.failed(
            SOURCE_ADD_OPERATION,
            "invalid_input",
            str(exc),
            suggestion,
            next_actions=next_actions,
        )

    if resume_token is None:
        result = _needs_llm(
            SOURCE_ADD_OPERATION,
            purpose="source_ingest",
            system_prompt="source-ingest",
            required_context=[source.relative_path for source in source_inputs],
            output_schema=(
                "source_ingest_result" if len(source_inputs) == 1 else "source_ingest_result_list"
            ),
            constraints=[
                "summary_required",
                "cleaned_content_required",
                "cleaned_content_must_reference_input_path",
                "metadata_suggestions_must_not_override_fact_fields",
            ],
            token_payload=token_payload,
        )
        context_documents = _source_context_documents(source_inputs)
        if context_documents:
            result.extra["llm_request"]["context_documents"] = context_documents
        return result

    if resume_token != _resume_token(SOURCE_ADD_OPERATION, token_payload):
        return _failed(
            SOURCE_ADD_OPERATION,
            "invalid_resume_token",
            "Resume token does not match this source.add request.",
            "Restart kb.source.add and use the returned resume token.",
        )

    try:
        repository = ObjectRepository(workspace)
        parsed_sources = _validate_source_llm_results(llm_result, source_inputs)
        records = _plan_source_records(
            repository,
            source_inputs,
            parsed_sources,
            title,
            tags,
            authors,
        )
        created = [
            path
            for record in records
            for path in (record["source_relative"], record["cleaned_relative"])
        ]
        diffs = [
            {"action": "create", "kind": kind, "path": path}
            for record in records
            for kind, path in (
                ("source", record["source_relative"]),
                ("cleaned", record["cleaned_relative"]),
            )
        ]
        _write_source_records_atomic(workspace, repository, records)
    except (KBManagerError, OSError) as exc:
        return _failed(
            SOURCE_ADD_OPERATION,
            "source_write_failed",
            str(exc),
            "Fix the LLM result or file conflict, then resume again.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        SOURCE_ADD_OPERATION,
        objects=ObjectChanges(created=created),
        diffs=diffs,
        next_actions=["Create candidates with kb.candidate.create for the new source IDs."],
        extra={
            "source_ids": [record["source_id"] for record in records],
            "source": {
                "id": records[0]["source_id"],
                "summary": records[0]["parsed"]["summary"],
                "cleaned_path": records[0]["cleaned_relative"],
            },
            "sources": [
                {
                    "id": record["source_id"],
                    "summary": record["parsed"]["summary"],
                    "cleaned_path": record["cleaned_relative"],
                }
                for record in records
            ],
        },
    )


def source_deprecate(
    root: str | Path = ".",
    *,
    source_id: str,
    decision: str | None = None,
    reason: str | None = None,
) -> ApiResult:
    """Mark a source as deprecated after user review."""

    if not _has_review_decision(decision, "deprecate"):
        return _needs_review(SOURCE_DEPRECATE_OPERATION, ["deprecate", "revise"])

    try:
        if not isinstance(reason, str) or not reason.strip():
            raise RepositoryError("source deprecate requires a non-empty reason")
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _find_single_object(repository, source_id, expected_type="source")
        today = _today()
        frontmatter = dict(record.metadata)
        frontmatter.update(
            {
                "status": "deprecated",
                "deprecated_at": today,
                "deprecated_reason": reason.strip(),
                "reviewed_at": today,
                "review_decision": "deprecate",
                "updated": today,
            }
        )
        relative_path = str(workspace.relative(record.path))
        impacts = _source_deprecation_impacts(repository, source_id)
        diffs = [{"action": "update", "kind": "source", "path": relative_path}]
        _write_source_metadata(repository, workspace, record, frontmatter)
    except (KBManagerError, OSError) as exc:
        return _failed(
            SOURCE_DEPRECATE_OPERATION,
            "source_deprecate_failed",
            str(exc),
            "Provide an existing source ID, user deprecate decision, and reason.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        SOURCE_DEPRECATE_OPERATION,
        objects=ObjectChanges(deprecated=[relative_path]),
        diffs=diffs,
        extra={
            "source_id": source_id,
            "impacts": impacts,
        },
    )


def candidate_create(
    root: str | Path = ".",
    *,
    source_ids: list[str] | None = None,
    resume_token: str | None = None,
    llm_result: dict[str, Any] | None = None,
) -> ApiResult:
    """Create pending candidates through the candidate-create LLM boundary."""

    source_ids = source_ids or []
    token_payload = {"source_ids": source_ids}

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        upstream = _validate_source_refs(repository, source_ids)
        active_kbs = _active_knowledgebase_context(repository)
        source_context = _candidate_source_context(repository, upstream)
        warnings = _deprecated_source_warnings(upstream)
    except (KBManagerError, OSError) as exc:
        return _failed(
            CANDIDATE_CREATE_OPERATION,
            "invalid_reference",
            str(exc),
            "Provide at least one existing source reference.",
        )

    if resume_token is None:
        return _needs_llm(
            CANDIDATE_CREATE_OPERATION,
            purpose="create_candidate",
            system_prompt="candidate-create",
            required_context=[record.object_id for record in upstream],
            output_schema="candidate_draft_list",
            constraints=[
                "must_preserve_upstream_refs",
                "must_include_evidence",
                "must_not_create_accepted_knowledge",
                "must_use_existing_outline_id_and_node_id_for_bindto",
            ],
            token_payload={
                **token_payload,
                "active_knowledgebases": active_kbs,
                "source_context": source_context,
            },
            warnings=warnings,
        )

    if resume_token != _resume_token(
        CANDIDATE_CREATE_OPERATION,
        {
            **token_payload,
            "active_knowledgebases": active_kbs,
            "source_context": source_context,
        },
    ):
        return _failed(
            CANDIDATE_CREATE_OPERATION,
            "invalid_resume_token",
            "Resume token does not match this candidate.create request.",
            "Restart kb.candidate.create and use the returned resume token.",
        )

    try:
        drafts = _validate_candidate_llm_result(llm_result)
        records = _plan_candidate_records(repository, drafts, source_ids)
        created = [f"candidates/pending/{record['id']}.md" for record in records]
        diffs = [{"action": "create", "kind": "candidate", "path": path} for path in created]
        _write_candidate_records_atomic(repository, records)
    except (KBManagerError, OSError) as exc:
        return _failed(
            CANDIDATE_CREATE_OPERATION,
            "candidate_write_failed",
            str(exc),
            "Fix the LLM result, evidence, or ID conflict, then resume again.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        CANDIDATE_CREATE_OPERATION,
        objects=ObjectChanges(created=created),
        diffs=diffs,
        warnings=warnings,
        next_actions=[
            "Review pending candidates with kb.candidate.next_pending or kb.candidate.get."
        ],
        extra=_candidate_create_response_extra(records),
    )


def candidate_get(
    root: str | Path = ".",
    *,
    candidate_id: str,
) -> ApiResult:
    """Return a candidate object and its referenced object summaries."""

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _find_single_object(repository, candidate_id, expected_type="candidate")
        document = repository.read_markdown(workspace.relative(record.path))
        references = _candidate_reference_summaries(repository, document.frontmatter)
    except (KBManagerError, OSError) as exc:
        return _failed(
            CANDIDATE_GET_OPERATION,
            "candidate_not_found",
            str(exc),
            "Provide an existing candidate ID.",
        )

    return ApiResult.success(
        CANDIDATE_GET_OPERATION,
        extra={
            "candidate": {
                "id": candidate_id,
                "path": str(workspace.relative(record.path)),
                "frontmatter": document.frontmatter,
                "body": document.body,
                "body_summary": _summarize_text(document.body),
                "references": references,
            }
        },
    )


def candidate_next_pending(
    root: str | Path = ".",
) -> ApiResult:
    """Return the oldest pending candidate."""

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        pending = [
            record
            for record in _all_records(repository)
            if record.object_type == "candidate" and record.status == "pending"
        ]
        misplaced = [
            record
            for record in pending
            if workspace.relative(record.path).parts[:2] != ("candidates", "pending")
        ]
        if misplaced:
            paths = ", ".join(str(workspace.relative(record.path)) for record in misplaced)
            raise RepositoryError(f"pending candidate outside candidates/pending: {paths}")
        if not pending:
            return ApiResult.success(
                CANDIDATE_NEXT_PENDING_OPERATION,
                next_actions=["No pending candidates are available."],
                extra={"candidate": None},
            )
        pending.sort(key=lambda item: (str(item.metadata.get("created", "")), item.path.name))
    except (KBManagerError, OSError) as exc:
        return _failed(
            CANDIDATE_NEXT_PENDING_OPERATION,
            "candidate_scan_failed",
            str(exc),
            "Fix invalid candidate files and try again.",
        )

    result = candidate_get(
        workspace.root,
        candidate_id=pending[0].object_id,
    ).to_dict()
    return ApiResult.success(
        CANDIDATE_NEXT_PENDING_OPERATION,
        extra={"candidate": result["candidate"]},
    )


def knowledge_accept(
    root: str | Path = ".",
    *,
    candidate_id: str,
    decision: str | None = None,
    reason: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    content: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    bindto: list[dict[str, Any]] | None = None,
) -> ApiResult:
    """Promote a pending candidate to accepted knowledge after user review."""

    if not _has_review_decision(decision, "accept"):
        return _needs_review(KNOWLEDGE_ACCEPT_OPERATION, ["accept", "reject", "defer", "merge"])

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _pending_candidate_record(repository, workspace, candidate_id)
        document = repository.read_markdown(workspace.relative(record.path))
        _validate_required_accept_content(
            title=title,
            summary=summary,
            content=content,
            evidence=evidence,
            bindto=bindto,
        )
        reviewed_evidence = evidence or []
        _validate_reviewed_evidence_from_candidate(reviewed_evidence, document.frontmatter)
        _validate_bindto(repository, bindto or [])
        today = _today()
        accepted_frontmatter = {
            "id": candidate_id,
            "type": "knowledge",
            "title": title or document.frontmatter["title"],
            "status": "accepted",
            "summary": summary,
            "evidence": reviewed_evidence,
            "bindto": bindto or [],
            "reviewed_at": today,
            "review_decision": "accept",
            "review_reason": reason,
            "deprecated_at": None,
            "deprecated_reason": None,
            "created": document.frontmatter.get("created", today),
            "updated": today,
        }
        knowledge_path = f"knowledge/atomic/{candidate_id}.md"
        if workspace.resolve(knowledge_path).exists():
            raise RepositoryError(f"knowledge already exists: {knowledge_path}")
        accepted_body = _knowledge_body(content, document.body)
        diffs = [
            {"action": "create", "kind": "knowledge", "path": knowledge_path},
            {
                "action": "remove",
                "kind": "candidate",
                "path": str(workspace.relative(record.path)),
            },
        ]
        _promote_candidate_to_knowledge(
            repository,
            record.path,
            knowledge_path,
            MarkdownDocument(frontmatter=accepted_frontmatter, body=accepted_body),
        )
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGE_ACCEPT_OPERATION,
            "accept_failed",
            str(exc),
            "Review a pending candidate and provide an accept decision.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGE_ACCEPT_OPERATION,
        objects=ObjectChanges(
            created=[knowledge_path],
        ),
        diffs=diffs,
        extra={"knowledge_id": candidate_id, "bindto": accepted_frontmatter["bindto"]},
    )


def knowledge_reject(
    root: str | Path = ".",
    *,
    candidate_id: str,
    decision: str | None = None,
    reason: str | None = None,
) -> ApiResult:
    """Reject a candidate after user review."""

    if not _has_review_decision(decision, "reject"):
        return _needs_review(KNOWLEDGE_REJECT_OPERATION, ["reject", "revise"])
    return _move_reviewed_candidate(
        root,
        operation=KNOWLEDGE_REJECT_OPERATION,
        candidate_id=candidate_id,
        target_status="rejected",
        decision="reject",
        reason=reason,
    )


def candidate_defer(
    root: str | Path = ".",
    *,
    candidate_id: str,
    decision: str | None = None,
    reason: str | None = None,
) -> ApiResult:
    """Defer a pending candidate after user review."""

    if not _has_review_decision(decision, "defer"):
        return _needs_review(CANDIDATE_DEFER_OPERATION, ["defer", "accept", "reject"])
    return _move_reviewed_candidate(
        root,
        operation=CANDIDATE_DEFER_OPERATION,
        candidate_id=candidate_id,
        target_status="deferred",
        decision="defer",
        reason=reason,
    )


def knowledge_merge(
    root: str | Path = ".",
    *,
    candidate_id: str,
    target_knowledge_id: str,
    decision: str | None = None,
    reason: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    content: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    bindto: list[dict[str, Any]] | None = None,
) -> ApiResult:
    """Merge a reviewed candidate into an existing knowledge object."""

    if not _has_review_decision(decision, "merge"):
        return _needs_review(KNOWLEDGE_MERGE_OPERATION, ["merge", "reject", "revise"])

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        candidate_record = _pending_candidate_record(repository, workspace, candidate_id)
        knowledge_record = _find_single_object(
            repository,
            target_knowledge_id,
            expected_type="knowledge",
        )
        if knowledge_record.status != "accepted":
            raise RepositoryError(f"target knowledge must be accepted: {target_knowledge_id}")
        _validate_required_merge_content(
            summary=summary,
            content=content,
            evidence=evidence,
            bindto=bindto,
        )
        source_ids = _validate_evidence_references_sources(repository, evidence or [])
        _validate_evidence(repository, evidence or [], source_ids)
        _validate_bindto(repository, bindto or [])
        candidate_document = repository.read_markdown(workspace.relative(candidate_record.path))
        knowledge_document = repository.read_markdown(workspace.relative(knowledge_record.path))
        today = _today()
        merged_frontmatter = dict(knowledge_document.frontmatter)
        merged_frontmatter.update(
            {
                "title": title or knowledge_document.frontmatter["title"],
                "summary": summary,
                "evidence": evidence or [],
                "bindto": bindto or [],
                "reviewed_at": today,
                "review_decision": "merge",
                "review_reason": reason,
                "updated": today,
            }
        )
        rejected_candidate = _reviewed_candidate_document(
            candidate_document,
            status="rejected",
            decision="merge",
            reason=reason,
        )
        knowledge_relative = str(workspace.relative(knowledge_record.path))
        rejected_relative = f"candidates/rejected/{candidate_id}.md"
        diffs = [
            {"action": "update", "kind": "knowledge", "path": knowledge_relative},
            {"action": "move", "kind": "candidate", "path": rejected_relative},
        ]
        _merge_candidate_into_knowledge(
            repository,
            workspace,
            candidate_record.path,
            rejected_relative,
            rejected_candidate,
            knowledge_relative,
            MarkdownDocument(
                frontmatter=merged_frontmatter,
                body=_knowledge_body(content, knowledge_document.body),
            ),
            knowledge_document,
        )
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGE_MERGE_OPERATION,
            "merge_failed",
            str(exc),
            "Review a pending candidate and provide an accepted target knowledge ID.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGE_MERGE_OPERATION,
        objects=ObjectChanges(
            updated=[
                knowledge_relative,
                rejected_relative,
            ]
        ),
        diffs=diffs,
        extra={
            "knowledge_id": target_knowledge_id,
            "rejected_candidate_id": candidate_id,
            "bindto": merged_frontmatter["bindto"],
        },
    )


def knowledge_deprecate(
    root: str | Path = ".",
    *,
    knowledge_id: str,
    decision: str | None = None,
    reason: str | None = None,
) -> ApiResult:
    """Mark accepted knowledge as deprecated after user review."""

    if not _has_review_decision(decision, "deprecate"):
        return _needs_review(KNOWLEDGE_DEPRECATE_OPERATION, ["deprecate", "revise"])

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _find_single_object(repository, knowledge_id, expected_type="knowledge")
        if record.status != "accepted":
            raise RepositoryError(f"knowledge must be accepted before deprecation: {knowledge_id}")
        document = repository.read_markdown(workspace.relative(record.path))
        frontmatter = dict(document.frontmatter)
        today = _today()
        frontmatter.update(
            {
                "status": "deprecated",
                "deprecated_at": today,
                "deprecated_reason": reason,
                "reviewed_at": today,
                "review_decision": "deprecate",
                "updated": today,
            }
        )
        relative_path = str(workspace.relative(record.path))
        diffs = [{"action": "update", "kind": "knowledge", "path": relative_path}]
        repository.write_markdown(
            relative_path,
            MarkdownDocument(frontmatter=frontmatter, body=document.body),
            overwrite=True,
        )
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGE_DEPRECATE_OPERATION,
            "deprecate_failed",
            str(exc),
            "Provide an accepted knowledge ID and a user deprecation decision.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGE_DEPRECATE_OPERATION,
        objects=ObjectChanges(deprecated=[relative_path]),
        diffs=diffs,
        extra={"knowledge_id": knowledge_id},
    )


def knowledgebase_create(
    root: str | Path = ".",
    *,
    title: str,
    input_path: str | Path | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    scope: dict[str, Any] | None = None,
    default_outline_id: str | None = None,
    outlines: list[dict[str, Any]] | None = None,
    review: dict[str, Any] | None = None,
    knowledgebase_id: str | None = None,
    resume_token: str | None = None,
    llm_result: dict[str, Any] | None = None,
) -> ApiResult:
    """Create a knowledge base through LLM draft, review, and approved write gates."""

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        _validate_knowledgebase_input(
            repository,
            title=title,
            knowledgebase_id=knowledgebase_id,
        )

        has_reviewed_payload = _has_knowledgebase_create_payload(
            description=description,
            scope=scope,
            default_outline_id=default_outline_id,
            outlines=outlines,
        )

        if resume_token is None and not has_reviewed_payload:
            if input_path is None:
                return _needs_review(
                    KNOWLEDGEBASE_CREATE_OPERATION,
                    ["approve", "revise", "reject"],
                )
            input_context = _knowledgebase_create_input_context(workspace, input_path)
            token_payload = _knowledgebase_create_token_payload(
                title=title,
                input_path=input_path,
                knowledgebase_id=knowledgebase_id,
                input_context=input_context,
            )
            return _needs_llm(
                KNOWLEDGEBASE_CREATE_OPERATION,
                purpose="knowledgebase_create",
                system_prompt="knowledgebase-create",
                required_context=["knowledgebase_create_input"],
                output_schema="knowledgebase_create_draft",
                constraints=[
                    "draft_only",
                    "human_review_required",
                    "must_not_create_source_or_candidate",
                    "preserve_meaningful_outline_hierarchy",
                ],
                token_payload=token_payload,
            )

        if resume_token is not None:
            if input_path is None:
                raise RepositoryError("knowledgebase create resume requires input_path")
            input_context = _knowledgebase_create_input_context(workspace, input_path)
            token_payload = _knowledgebase_create_token_payload(
                title=title,
                input_path=input_path,
                knowledgebase_id=knowledgebase_id,
                input_context=input_context,
            )
            if resume_token != _resume_token(KNOWLEDGEBASE_CREATE_OPERATION, token_payload):
                return _failed(
                    KNOWLEDGEBASE_CREATE_OPERATION,
                    "invalid_resume_token",
                    "Resume token does not match this knowledgebase.create request.",
                    "Restart kb.knowledgebase.create and use the returned resume token.",
                )
            payload = _validate_knowledgebase_create_payload(llm_result)
            return _needs_review(
                KNOWLEDGEBASE_CREATE_OPERATION,
                ["approve", "revise", "reject"],
                extra={
                    "knowledgebase_draft": payload,
                    "knowledgebase_create_input": input_context,
                    "reviewed_payload": payload,
                },
            )

        if not _review_approved(review):
            reviewed_payload = None
            if has_reviewed_payload:
                reviewed_payload = _validate_knowledgebase_create_payload(
                    {
                        "description": description,
                        "tags": tags or [],
                        "scope": scope,
                        "default_outline_id": default_outline_id,
                        "outlines": outlines,
                    }
                )
            return _needs_review(
                KNOWLEDGEBASE_CREATE_OPERATION,
                ["approve", "revise", "reject"],
                extra=({"reviewed_payload": reviewed_payload} if reviewed_payload else None),
            )

        payload = _validate_knowledgebase_create_payload(
            {
                "description": description,
                "tags": tags or [],
                "scope": scope,
                "default_outline_id": default_outline_id,
                "outlines": outlines,
            }
        )
        today = _today()
        kb_id = knowledgebase_id or _next_titled_id(repository, "kb", title)
        relative_path = f"knowledge/bases/{kb_id}.md"
        outlines_relative_path = _default_outlines_file(relative_path)
        if workspace.resolve(relative_path).exists():
            raise RepositoryError(f"knowledge base path already exists: {relative_path}")
        if workspace.resolve(outlines_relative_path).exists():
            raise RepositoryError(
                f"knowledgebase outlines file already exists: {outlines_relative_path}"
            )
        outline_document = _outlines_document(
            kb_id,
            payload["default_outline_id"],
            payload["outlines"],
        )
        manifest = _outline_manifest(outline_document["outlines"])
        frontmatter = {
            "id": kb_id,
            "type": "knowledge-base",
            "title": title.strip(),
            "status": "active",
            "description": payload["description"],
            "tags": payload["tags"],
            "scope": payload["scope"],
            "default_outline_id": payload["default_outline_id"],
            "outlines_file": outlines_relative_path,
            "outlines": manifest,
            "reviewed_at": str((review or {}).get("reviewed_at") or today),
            "review_decision": "approve",
            "created": today,
            "updated": today,
        }
        document = MarkdownDocument(
            frontmatter=frontmatter,
            body=_knowledgebase_body(payload["description"], payload["scope"], manifest),
        )
        diffs = [
            {"action": "create", "kind": "knowledge-base", "path": relative_path},
            {"action": "create", "kind": "knowledgebase-outlines", "path": outlines_relative_path},
        ]
        repository.write_markdown(relative_path, document)
        _write_yaml_file(workspace, outlines_relative_path, outline_document)
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGEBASE_CREATE_OPERATION,
            "knowledgebase_create_failed",
            str(exc),
            "Provide a reviewed knowledgebase payload with description, scope, and outlines.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGEBASE_CREATE_OPERATION,
        objects=ObjectChanges(created=[relative_path, outlines_relative_path]),
        diffs=diffs,
        extra={
            "knowledgebase_id": kb_id,
            "path": relative_path,
            "outlines_file": outlines_relative_path,
        },
    )


def knowledgebase_outline_create(
    root: str | Path = ".",
    *,
    knowledgebase_id: str,
    outline: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> ApiResult:
    """Create a new outline for an active knowledge base."""

    if not _review_approved(review):
        return _needs_review(
            KNOWLEDGEBASE_OUTLINE_CREATE_OPERATION, ["approve", "revise", "reject"]
        )
    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        kb_record = _find_single_object(
            repository,
            knowledgebase_id,
            expected_type="knowledge-base",
        )
        if kb_record.status != "active":
            raise RepositoryError(f"knowledgebase is archived: {knowledgebase_id}")
        outline = _validate_single_outline(outline)
        document = repository.read_markdown(workspace.relative(kb_record.path))
        today = _today()
        frontmatter = dict(document.frontmatter)
        outlines_document = _read_outlines_file(workspace, kb_record)
        existing_ids = {item["id"] for item in outlines_document["outlines"]}
        if outline["id"] in existing_ids:
            raise RepositoryError(f"outline already exists: {outline['id']}")
        outlines_document["outlines"].append(outline)
        frontmatter.update(
            {
                "outlines": _outline_manifest(outlines_document["outlines"]),
                "updated": today,
            }
        )
        relative_path = str(workspace.relative(kb_record.path))
        outlines_relative_path = _outlines_file_for_record(workspace, kb_record)
        updated_document = MarkdownDocument(
            frontmatter=frontmatter,
            body=_knowledgebase_body(
                str(frontmatter.get("description", "")),
                dict(frontmatter.get("scope", {})),
                frontmatter["outlines"],
            ),
        )
        diffs = [
            {"action": "update", "kind": "knowledge-base", "path": relative_path},
            {"action": "update", "kind": "knowledgebase-outlines", "path": outlines_relative_path},
        ]
        repository.write_markdown(relative_path, updated_document, overwrite=True)
        _write_yaml_file(workspace, outlines_relative_path, outlines_document, overwrite=True)
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGEBASE_OUTLINE_CREATE_OPERATION,
            "knowledgebase_outline_create_failed",
            str(exc),
            "Provide an active knowledgebase ID and a reviewed outline payload.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGEBASE_OUTLINE_CREATE_OPERATION,
        objects=ObjectChanges(updated=[relative_path, outlines_relative_path]),
        diffs=diffs,
        extra={
            "knowledgebase_id": knowledgebase_id,
            "outline_id": outline["id"],
            "path": relative_path,
            "outlines_file": outlines_relative_path,
        },
    )


def knowledgebase_outline_set_default(
    root: str | Path = ".",
    *,
    knowledgebase_id: str,
    outline_id: str,
    review: dict[str, Any] | None = None,
) -> ApiResult:
    """Set the default outline for an active knowledge base."""

    if not _review_approved(review):
        return _needs_review(
            KNOWLEDGEBASE_OUTLINE_SET_DEFAULT_OPERATION,
            ["approve", "revise", "reject"],
        )
    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        kb_record = _find_single_object(
            repository, knowledgebase_id, expected_type="knowledge-base"
        )
        if kb_record.status != "active":
            raise RepositoryError(f"knowledgebase must be active: {knowledgebase_id}")
        document = repository.read_markdown(workspace.relative(kb_record.path))
        outlines_document = _read_outlines_file(workspace, kb_record)
        outline = _outline_by_id(outlines_document, outline_id)
        if outline.get("status") != "active":
            raise RepositoryError(f"default outline must be active: {outline_id}")
        today = _today()
        outlines_document["default_outline_id"] = outline_id
        frontmatter = dict(document.frontmatter)
        frontmatter.update({"default_outline_id": outline_id, "updated": today})
        relative_path = str(workspace.relative(kb_record.path))
        outlines_relative_path = _outlines_file_for_record(workspace, kb_record)
        updated_document = MarkdownDocument(
            frontmatter=frontmatter,
            body=_knowledgebase_body(
                str(frontmatter.get("description", "")),
                dict(frontmatter.get("scope", {})),
                frontmatter.get("outlines", []),
            ),
        )
        diffs = [
            {"action": "update", "kind": "knowledge-base", "path": relative_path},
            {"action": "update", "kind": "knowledgebase-outlines", "path": outlines_relative_path},
        ]
        repository.write_markdown(relative_path, updated_document, overwrite=True)
        _write_yaml_file(workspace, outlines_relative_path, outlines_document, overwrite=True)
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGEBASE_OUTLINE_SET_DEFAULT_OPERATION,
            "knowledgebase_outline_set_default_failed",
            str(exc),
            "Provide an active knowledgebase ID and an active outline ID.",
        )
    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGEBASE_OUTLINE_SET_DEFAULT_OPERATION,
        objects=ObjectChanges(updated=[relative_path, outlines_relative_path]),
        diffs=diffs,
        extra={"knowledgebase_id": knowledgebase_id, "outline_id": outline_id},
    )


def knowledgebase_outline_archive(
    root: str | Path = ".",
    *,
    knowledgebase_id: str,
    outline_id: str,
    review: dict[str, Any] | None = None,
    allow_existing_bindings: bool = False,
) -> ApiResult:
    """Archive a non-default outline."""

    if not _review_approved(review):
        return _needs_review(
            KNOWLEDGEBASE_OUTLINE_ARCHIVE_OPERATION,
            ["approve", "revise", "reject"],
        )
    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        kb_record = _find_single_object(
            repository, knowledgebase_id, expected_type="knowledge-base"
        )
        if kb_record.status != "active":
            raise RepositoryError(f"knowledgebase must be active: {knowledgebase_id}")
        document = repository.read_markdown(workspace.relative(kb_record.path))
        outlines_document = _read_outlines_file(workspace, kb_record)
        if outlines_document.get("default_outline_id") == outline_id:
            raise RepositoryError("cannot archive the default outline; set another default first")
        outline = _outline_by_id(outlines_document, outline_id)
        bound = _knowledge_bound_to_outline(repository, knowledgebase_id, outline_id)
        if bound and not allow_existing_bindings:
            raise RepositoryError(
                "outline has existing knowledge bindings: " + ", ".join(sorted(bound))
            )
        today = _today()
        outline["status"] = "archived"
        frontmatter = dict(document.frontmatter)
        frontmatter.update(
            {"outlines": _outline_manifest(outlines_document["outlines"]), "updated": today}
        )
        relative_path = str(workspace.relative(kb_record.path))
        outlines_relative_path = _outlines_file_for_record(workspace, kb_record)
        updated_document = MarkdownDocument(
            frontmatter=frontmatter,
            body=_knowledgebase_body(
                str(frontmatter.get("description", "")),
                dict(frontmatter.get("scope", {})),
                frontmatter["outlines"],
            ),
        )
        diffs = [
            {"action": "update", "kind": "knowledge-base", "path": relative_path},
            {"action": "update", "kind": "knowledgebase-outlines", "path": outlines_relative_path},
        ]
        repository.write_markdown(relative_path, updated_document, overwrite=True)
        _write_yaml_file(workspace, outlines_relative_path, outlines_document, overwrite=True)
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGEBASE_OUTLINE_ARCHIVE_OPERATION,
            "knowledgebase_outline_archive_failed",
            str(exc),
            "Provide a non-default outline ID and resolve existing bindings if needed.",
        )
    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGEBASE_OUTLINE_ARCHIVE_OPERATION,
        objects=ObjectChanges(updated=[relative_path, outlines_relative_path]),
        diffs=diffs,
        extra={
            "knowledgebase_id": knowledgebase_id,
            "outline_id": outline_id,
            "bound_knowledge": sorted(bound),
        },
    )


def knowledgebase_map(
    root: str | Path = ".",
    *,
    knowledgebase_id: str | None = None,
    output_path: str | Path | None = None,
) -> ApiResult:
    """Generate a temporary Mermaid knowledge hierarchy map."""

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        records = _all_records(repository)
        markdown, issues = _knowledgebase_map_markdown(records, workspace, knowledgebase_id)
        target = Path(output_path) if output_path is not None else _temporary_map_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGEBASE_MAP_OPERATION,
            "knowledgebase_map_failed",
            str(exc),
            "Provide an existing knowledgebase ID or omit it to map all accepted knowledge.",
        )

    return ApiResult.success(
        KNOWLEDGEBASE_MAP_OPERATION,
        warnings=_issue_warnings(issues),
        extra={
            "path": str(target),
            "markdown": markdown,
            "issues": issues,
            "knowledgebase_id": knowledgebase_id,
        },
    )


def note_add(
    root: str | Path = ".",
    *,
    content: str,
    title: str | None = None,
    note_id: str | None = None,
    needs_llm: bool = False,
    resume_token: str | None = None,
    llm_result: dict[str, Any] | None = None,
) -> ApiResult:
    """Add an active note."""

    try:
        llm_note: dict[str, Any] = {}
        title = title.strip() if isinstance(title, str) and title.strip() else None
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        _validate_note_input(
            repository,
            content=content,
            title=title,
            note_id=note_id,
        )
        token_payload = {
            "content": content,
            "title": title,
            "note_id": note_id,
        }
        if needs_llm and resume_token is None:
            return _needs_llm(
                NOTE_ADD_OPERATION,
                purpose="note_title",
                system_prompt="note-title",
                required_context=["note.content"],
                output_schema="note_title",
                constraints=[
                    "title_required",
                    "must_not_change_note_content",
                ],
                token_payload=token_payload,
            )
        if resume_token is not None:
            if resume_token != _resume_token(NOTE_ADD_OPERATION, token_payload):
                raise RepositoryError("Resume token does not match this note.add request.")
            llm_note = _validate_note_llm_result(llm_result)
            title = title or llm_note["title"]
        today = _today()
        new_note_id = note_id or _next_id(repository, "note")
        status = "active"
        relative_path = f"notes/{status}/{new_note_id}.md"
        if workspace.resolve(relative_path).exists():
            raise RepositoryError(f"note path already exists: {relative_path}")
        note_title = (
            title.strip() if isinstance(title, str) and title.strip() else _note_title(content)
        )
        frontmatter = {
            "id": new_note_id,
            "type": "note",
            "title": note_title,
            "status": status,
            "deprecated_at": None,
            "deprecated_reason": None,
            "created": today,
            "updated": today,
        }
        document = MarkdownDocument(
            frontmatter=frontmatter,
            body=_note_body(content),
        )
        diffs = [{"action": "create", "kind": "note", "path": relative_path}]
        repository.write_markdown(relative_path, document)
    except (KBManagerError, OSError) as exc:
        return _failed(
            NOTE_ADD_OPERATION,
            "note_add_failed",
            str(exc),
            "Provide non-empty note content.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        NOTE_ADD_OPERATION,
        objects=ObjectChanges(created=[relative_path]),
        diffs=diffs,
        extra=_note_response_extra(new_note_id, relative_path, document),
    )


def note_get(
    root: str | Path = ".",
    *,
    note_id: str,
) -> ApiResult:
    """Return a note object by ID."""

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _find_single_object(repository, note_id, expected_type="note")
        relative_path = str(workspace.relative(record.path))
        document = repository.read_markdown(relative_path)
    except (KBManagerError, OSError) as exc:
        return _failed(
            NOTE_GET_OPERATION,
            "note_not_found",
            str(exc),
            "Provide an existing note ID.",
        )

    return ApiResult.success(
        NOTE_GET_OPERATION,
        extra={"note": _note_payload(note_id, relative_path, document)},
    )


def note_deprecate(
    root: str | Path = ".",
    *,
    note_id: str,
    reason: str | None = None,
    decision: str | None = None,
) -> ApiResult:
    """Mark a note deprecated and move it to notes/deprecated."""

    if not _has_review_decision(decision, "deprecate"):
        return _needs_review(NOTE_DEPRECATE_OPERATION, ["deprecate", "revise"])

    try:
        if not isinstance(reason, str) or not reason.strip():
            raise RepositoryError("note deprecate requires a non-empty reason")
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _find_single_object(repository, note_id, expected_type="note")
        source_relative = str(workspace.relative(record.path))
        document = repository.read_markdown(source_relative)
        today = _today()
        frontmatter = dict(document.frontmatter)
        _clean_note_frontmatter(frontmatter)
        frontmatter.update(
            {
                "status": "deprecated",
                "deprecated_at": today,
                "deprecated_reason": reason.strip(),
                "reviewed_at": today,
                "review_decision": "deprecate",
                "updated": today,
            }
        )
        deprecated_relative = f"notes/deprecated/{note_id}.md"
        diffs = [
            {
                "action": "move",
                "kind": "note",
                "from": source_relative,
                "path": deprecated_relative,
            }
        ]
        _move_or_update_note_document(
            repository,
            record.path,
            source_relative,
            deprecated_relative,
            MarkdownDocument(frontmatter=frontmatter, body=document.body),
        )
    except (KBManagerError, OSError) as exc:
        return _failed(
            NOTE_DEPRECATE_OPERATION,
            "note_deprecate_failed",
            str(exc),
            "Provide an existing note ID, user deprecate decision, and reason.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        NOTE_DEPRECATE_OPERATION,
        objects=ObjectChanges(deprecated=[deprecated_relative]),
        diffs=diffs,
        extra={"note_id": note_id, "path": deprecated_relative},
    )


def clean_inspect(
    root: str | Path = ".",
) -> ApiResult:
    """Inspect workspace drift from the current object layout and schema."""

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        differences = _clean_differences(workspace, repository)
    except (KBManagerError, OSError) as exc:
        return _failed(
            CLEAN_INSPECT_OPERATION,
            "clean_inspect_failed",
            str(exc),
            "Fix unreadable object files, then inspect again.",
        )

    if not differences:
        return ApiResult.success(
            CLEAN_INSPECT_OPERATION,
            extra={"differences": [], "migration_required": False},
            next_actions=["No migration plan is needed."],
        )

    result = _needs_llm(
        CLEAN_INSPECT_OPERATION,
        purpose="clean_migration_plan",
        system_prompt="clean-migration-plan",
        required_context=["clean.differences"],
        output_schema="clean_migration_plan",
        constraints=[
            "plan_only",
            "user_confirmation_required_before_file_changes",
            "clean_command_may_edit_files_after_confirmation",
        ],
        token_payload={
            "differences": differences,
            "current_version_expectations": _clean_expectations(),
        },
        warnings=_clean_warnings(differences),
    )
    extra = dict(result.extra)
    extra["differences"] = differences
    extra["migration_required"] = True
    return ApiResult(
        status=result.status,
        operation=result.operation,
        objects=result.objects,
        diffs=result.diffs,
        warnings=result.warnings,
        errors=result.errors,
        review=result.review,
        next_actions=result.next_actions,
        extra=extra,
    )


def index_rebuild(
    root: str | Path = ".",
    *,
    scope: str = "all",
    object_id: str | None = None,
) -> ApiResult:
    """Rebuild derived indexes from object files and report consistency issues."""

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        _validate_index_scope(scope)
        records = _all_records(repository)
        if object_id is not None:
            _find_single_object(repository, object_id)
        issues = _consistency_issues(records, workspace)
        planned_indexes = _filter_index_files(
            _build_index_files(records, workspace),
            scope=scope,
            object_id=object_id,
        )
        diffs = _index_diffs(workspace, planned_indexes)
        updated = [diff["path"] for diff in diffs if diff["action"] in {"create", "update"}]
        _write_index_files(workspace, planned_indexes)
    except (KBManagerError, OSError) as exc:
        return _failed(
            INDEX_REBUILD_OPERATION,
            "index_rebuild_failed",
            str(exc),
            "Fix invalid object files, then rebuild indexes again.",
        )

    return ApiResult.success(
        INDEX_REBUILD_OPERATION,
        objects=ObjectChanges(updated=updated),
        diffs=diffs,
        warnings=_issue_warnings(issues),
        extra={"issues": issues, "index_paths": sorted(planned_indexes)},
    )


def _build_index_files(records: list[ObjectRecord], workspace: Workspace) -> dict[str, str]:
    visible_records = _without_deprecated(records)
    sources = _records_by_type(visible_records, "source")
    candidates = _records_by_type(visible_records, "candidate")
    knowledge = _records_by_type(visible_records, "knowledge")
    knowledgebases = _records_by_type(visible_records, "knowledge-base")
    notes = _records_by_type(visible_records, "note")

    indexes = {
        "indexes/source-index.md": _source_index(sources, workspace),
        "indexes/knowledge-index.md": _knowledge_index(knowledge, workspace),
        "indexes/tag-index.md": _tag_index(visible_records),
        "indexes/kb-index.md": _kb_index(knowledgebases, knowledge, workspace),
        "indexes/note-index.md": _note_index(notes, workspace),
        "indexes/review-queue.md": _review_queue_index(candidates, workspace),
    }
    for kb_record in knowledgebases:
        kb_id = kb_record.object_id
        indexes[f"indexes/knowledgebase/{kb_id}-knowledge-index.md"] = (
            _knowledgebase_knowledge_index(kb_record, knowledge, workspace)
        )
    return indexes


def _knowledgebase_map_markdown(
    records: list[ObjectRecord],
    workspace: Workspace,
    knowledgebase_id: str | None,
) -> tuple[str, list[dict[str, str]]]:
    visible_records = _without_deprecated(records)
    knowledgebases = [
        record
        for record in _records_by_type(visible_records, "knowledge-base")
        if record.status == "active"
    ]
    if knowledgebase_id is not None:
        knowledgebases = [
            record for record in knowledgebases if record.object_id == knowledgebase_id
        ]
        if not knowledgebases:
            raise RepositoryError(f"knowledgebase not found: {knowledgebase_id}")
    knowledge = [
        record
        for record in _records_by_type(visible_records, "knowledge")
        if record.status == "accepted"
    ]
    issues = _bindto_consistency_issues(knowledgebases, knowledge, workspace)

    title = (
        "Knowledgebase Map"
        if knowledgebase_id is None
        else f"Knowledgebase Map: {knowledgebase_id}"
    )
    lines = [
        f"# {title}",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    if not knowledgebases:
        lines.append('  empty["No active knowledgebase"]')
    for kb_record in knowledgebases:
        kb_node = _mermaid_node_id(kb_record.object_id)
        lines.append(f'  {kb_node}["{_mermaid_label(kb_record)}"]')
        outlines_document = _read_outlines_file(workspace, kb_record)
        default_outline_id = kb_record.metadata.get("default_outline_id")
        outline = _outline_by_id(outlines_document, str(default_outline_id))
        outline_nodes = _outline_nodes_with_labels(outline.get("nodes", []))
        for node_id, label, parent_id in outline_nodes:
            outline_node = _mermaid_node_id(f"{kb_record.object_id}-{node_id}")
            label_text = (
                f"{escape(label, quote=True)}<br/><code>{escape(node_id, quote=True)}</code>"
            )
            lines.append(f'  {outline_node}["{label_text}"]')
            parent_node = (
                kb_node
                if parent_id is None
                else _mermaid_node_id(f"{kb_record.object_id}-{parent_id}")
            )
            lines.append(f"  {parent_node} --> {outline_node}")
        for knowledge_record in knowledge:
            for binding in knowledge_record.metadata.get("bindto", []):
                if not isinstance(binding, dict) or binding.get("kb_id") != kb_record.object_id:
                    continue
                knowledge_node = _mermaid_node_id(knowledge_record.object_id)
                lines.append(f'  {knowledge_node}["{_mermaid_label(knowledge_record)}"]')
                if binding.get("outline_id") != default_outline_id:
                    continue
                outline_node = _mermaid_node_id(f"{kb_record.object_id}-{binding.get('node_id')}")
                lines.append(f"  {outline_node} --> {knowledge_node}")
    lines.extend(["```", ""])
    if issues:
        lines.extend(["## Issues", ""])
        for issue in issues:
            lines.append(f"- `{issue['object_id']}`: {issue['message']}")
        lines.append("")
    return "\n".join(lines), issues


def _mermaid_tree_edges(
    roots: list[ObjectRecord],
    children: dict[str, list[ObjectRecord]],
) -> list[str]:
    edges: list[str] = []
    visited: set[str] = set()

    def walk(record: ObjectRecord) -> None:
        if record.object_id in visited:
            return
        visited.add(record.object_id)
        for child in children.get(record.object_id, []):
            edges.append(
                f"  {_mermaid_node_id(record.object_id)} --> {_mermaid_node_id(child.object_id)}"
            )
            walk(child)

    for root in roots:
        walk(root)
    return edges


def _record_sort_key(record: ObjectRecord) -> tuple[str, str]:
    return (_metadata_text(record, "title").casefold(), record.object_id)


def _mermaid_node_id(object_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", object_id)


def _mermaid_label(record: ObjectRecord) -> str:
    title = escape(_metadata_text(record, "title") or record.object_id, quote=True)
    object_id = escape(record.object_id, quote=True)
    return f"{title}<br/><code>{object_id}</code>"


def _temporary_map_path() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.gettempdir()) / f"kbmanager-knowledgebase-map-{stamp}.md"


def _validate_index_scope(scope: str) -> None:
    if scope not in INDEX_SCOPES:
        raise RepositoryError("index scope must be one of: " + ", ".join(sorted(INDEX_SCOPES)))


def _filter_index_files(
    planned_indexes: dict[str, str],
    *,
    scope: str,
    object_id: str | None,
) -> dict[str, str]:
    if scope == "all":
        return planned_indexes

    scope_paths = {
        "source": {"indexes/source-index.md"},
        "candidate": {
            "indexes/review-queue.md",
            "indexes/tag-index.md",
        },
        "knowledge": {
            "indexes/knowledge-index.md",
            "indexes/tag-index.md",
        },
        "knowledgebase": {"indexes/kb-index.md"},
        "note": {"indexes/note-index.md"},
        "review_queue": {"indexes/review-queue.md"},
        "tag": {"indexes/tag-index.md"},
    }[scope]

    if scope == "knowledgebase":
        kb_indexes = {path for path in planned_indexes if path.startswith("indexes/knowledgebase/")}
        if object_id is not None:
            kb_indexes = {f"indexes/knowledgebase/{object_id}-knowledge-index.md"} & set(
                planned_indexes
            )
        scope_paths = scope_paths | kb_indexes

    return {path: content for path, content in planned_indexes.items() if path in scope_paths}


def _records_by_type(records: list[ObjectRecord], object_type: str) -> list[ObjectRecord]:
    return sorted(
        [record for record in records if record.object_type == object_type],
        key=lambda record: (record.object_id, str(record.path)),
    )


def _without_deprecated(records: list[ObjectRecord]) -> list[ObjectRecord]:
    return [record for record in records if record.status != "deprecated"]


def _source_index(records: list[ObjectRecord], workspace: Workspace) -> str:
    lines = [
        "# Source Index",
        "",
        "| ID | Title | Status | Tags | Path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    record.status,
                    _join_strings(record.metadata.get("tags", [])),
                    str(workspace.relative(record.path)),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _knowledge_index(records: list[ObjectRecord], workspace: Workspace) -> str:
    lines = [
        "# Knowledge Index",
        "",
        "| ID | Title | Status | Summary | Knowledge Bases | Path |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    record.status,
                    _metadata_text(record, "summary"),
                    _join_strings(
                        _knowledgebase_ids_from_bindto(record.metadata.get("bindto", []))
                    ),
                    str(workspace.relative(record.path)),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _tag_index(records: list[ObjectRecord]) -> str:
    by_tag: dict[str, list[str]] = {}
    for record in records:
        if record.object_type != "note":
            for tag in _string_items(record.metadata.get("tags", [])):
                by_tag.setdefault(tag, []).append(record.object_id)
        for tag in _string_items(record.metadata.get("suggested_tags", [])):
            by_tag.setdefault(tag, []).append(record.object_id)
    lines = ["# Tag Index", "", "| Tag | Objects |", "| --- | --- |"]
    for tag in sorted(by_tag, key=str.casefold):
        lines.append(_table_row([tag, ", ".join(sorted(set(by_tag[tag])))]))
    return "\n".join(lines) + "\n"


def _kb_index(
    knowledgebases: list[ObjectRecord],
    knowledge: list[ObjectRecord],
    workspace: Workspace,
) -> str:
    lines = [
        "# Knowledge Base Index",
        "",
        "| ID | Title | Status | Knowledge Count | Tags | Path |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in knowledgebases:
        bound_knowledge_ids = _bound_knowledge_ids_for_base(record, knowledge)
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    record.status,
                    str(len(bound_knowledge_ids)),
                    _join_strings(record.metadata.get("tags", [])),
                    str(workspace.relative(record.path)),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _note_index(records: list[ObjectRecord], workspace: Workspace) -> str:
    lines = [
        "# Note Index",
        "",
        "| ID | Title | Status | Path |",
        "| --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    _note_status(record.status),
                    str(workspace.relative(record.path)),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _review_queue_index(records: list[ObjectRecord], workspace: Workspace) -> str:
    pending = [record for record in records if record.status == "pending"]
    lines = [
        "# Review Queue",
        "",
        "| ID | Title | Created | Sources | Path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in sorted(
        pending,
        key=lambda item: (str(item.metadata.get("created", "")), item.object_id),
    ):
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    str(record.metadata.get("created", "")),
                    _join_strings(_source_ids_from_evidence(record.metadata.get("evidence", []))),
                    str(workspace.relative(record.path)),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _knowledgebase_knowledge_index(
    kb_record: ObjectRecord,
    knowledge: list[ObjectRecord],
    workspace: Workspace,
) -> str:
    bound_knowledge_ids = set(_bound_knowledge_ids_for_base(kb_record, knowledge))
    lines = [
        f"# Knowledge Index: {kb_record.object_id}",
        "",
        "| ID | Title | Status | Tags | Path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in knowledge:
        if record.object_id not in bound_knowledge_ids:
            continue
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    record.status,
                    _join_strings(record.metadata.get("tags", [])),
                    str(workspace.relative(record.path)),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _bound_knowledge_ids_for_base(
    kb_record: ObjectRecord,
    knowledge: list[ObjectRecord],
) -> list[str]:
    bound_ids: set[str] = set()
    for record in knowledge:
        if kb_record.object_id in _knowledgebase_ids_from_bindto(record.metadata.get("bindto", [])):
            bound_ids.add(record.object_id)
    return sorted(bound_ids)


def _index_diffs(workspace: Workspace, planned_indexes: dict[str, str]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for relative_path, content in sorted(planned_indexes.items()):
        path = workspace.resolve(relative_path)
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == content:
                diffs.append({"action": "keep", "kind": "index", "path": relative_path})
            else:
                diffs.append(
                    {
                        "action": "update",
                        "kind": "index",
                        "path": relative_path,
                        "before": current,
                        "after": content,
                    }
                )
        else:
            diffs.append(
                {
                    "action": "create",
                    "kind": "index",
                    "path": relative_path,
                    "after": content,
                }
            )
    return diffs


def _write_index_files(workspace: Workspace, planned_indexes: dict[str, str]) -> None:
    for relative_path, content in sorted(planned_indexes.items()):
        path = workspace.ensure_parent(relative_path)
        _write_text_atomic_overwrite(path, content)


def _write_text_atomic_overwrite(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _consistency_issues(records: list[ObjectRecord], workspace: Workspace) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    by_id: dict[str, list[ObjectRecord]] = {}
    for record in records:
        by_id.setdefault(record.object_id, []).append(record)

    for object_id, matches in sorted(by_id.items()):
        if len(matches) > 1:
            issues.append(
                {
                    "code": "duplicate_id",
                    "object_id": object_id,
                    "message": f"duplicate object ID: {object_id}",
                    "paths": ", ".join(str(workspace.relative(match.path)) for match in matches),
                }
            )
        types = {match.object_type for match in matches}
        if "candidate" in types and "knowledge" in types:
            issues.append(
                {
                    "code": "candidate_knowledge_id_conflict",
                    "object_id": object_id,
                    "message": f"candidate and knowledge share ID: {object_id}",
                }
            )

    for record in records:
        _append_reference_issues(record, by_id, issues)
        if record.object_type == "knowledge-base":
            _append_knowledgebase_outline_issues(record, workspace, issues)
    knowledgebases = [
        record
        for record in records
        if record.object_type == "knowledge-base" and record.status == "active"
    ]
    knowledge = [
        record
        for record in records
        if record.object_type == "knowledge" and record.status == "accepted"
    ]
    issues.extend(_bindto_consistency_issues(knowledgebases, knowledge, workspace))
    return issues


def _append_knowledgebase_outline_issues(
    record: ObjectRecord,
    workspace: Workspace,
    issues: list[dict[str, str]],
) -> None:
    if "outline" in record.metadata:
        issues.append(
            {
                "code": "legacy_outline_field",
                "object_id": record.object_id,
                "field": "outline",
                "message": f"{record.object_id} uses legacy outline frontmatter",
            }
        )
    try:
        _read_outlines_file(workspace, record)
    except RepositoryError as exc:
        issues.append(
            {
                "code": "invalid_outlines_file",
                "object_id": record.object_id,
                "field": "outlines_file",
                "message": str(exc),
            }
        )


def _append_reference_issues(
    record: ObjectRecord,
    by_id: dict[str, list[ObjectRecord]],
    issues: list[dict[str, str]],
) -> None:
    field_types = {}
    for field_name, expected_type in field_types.items():
        for target_id in _string_items(record.metadata.get(field_name, [])):
            _append_missing_or_type_issue(
                record,
                field_name,
                target_id,
                expected_type,
                by_id,
                issues,
            )

    for evidence in record.metadata.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        target_id = evidence.get("source_id") or evidence.get("object_id") or evidence.get("id")
        if isinstance(target_id, str):
            _append_missing_reference_issue(record, "evidence", target_id, by_id, issues)


def _bindto_consistency_issues(
    knowledgebases: list[ObjectRecord],
    knowledge: list[ObjectRecord],
    workspace: Workspace,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    kb_by_id = {record.object_id: record for record in knowledgebases}
    outline_docs: dict[str, dict[str, Any]] = {}
    for record in knowledge:
        bindto = record.metadata.get("bindto", [])
        if not isinstance(bindto, list):
            issues.append(
                {
                    "code": "invalid_bindto_shape",
                    "object_id": record.object_id,
                    "field": "bindto",
                    "message": f"{record.object_id}.bindto must be a list",
                }
            )
            continue
        for item in bindto:
            if not isinstance(item, dict):
                issues.append(
                    {
                        "code": "invalid_bindto_shape",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "message": f"{record.object_id}.bindto entries must be mappings",
                    }
                )
                continue
            kb_id = item.get("kb_id")
            outline_id = item.get("outline_id")
            node_id = item.get("node_id")
            if "outline_node" in item:
                issues.append(
                    {
                        "code": "legacy_outline_node_field",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "target_id": str(item.get("outline_node")),
                        "message": f"{record.object_id}.bindto uses legacy outline_node",
                    }
                )
                continue
            if not isinstance(kb_id, str) or kb_id not in kb_by_id:
                issues.append(
                    {
                        "code": "invalid_bindto_kb",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "target_id": str(kb_id),
                        "message": (
                            f"{record.object_id}.bindto references missing active "
                            f"knowledgebase {kb_id}"
                        ),
                    }
                )
                continue
            if not isinstance(outline_id, str) or not outline_id.strip():
                issues.append(
                    {
                        "code": "invalid_bindto_outline_id",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "target_id": str(outline_id),
                        "message": f"{record.object_id}.bindto missing outline_id",
                    }
                )
                continue
            if not isinstance(node_id, str) or not node_id.strip():
                issues.append(
                    {
                        "code": "invalid_bindto_node_id",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "target_id": str(node_id),
                        "message": f"{record.object_id}.bindto missing node_id",
                    }
                )
                continue
            try:
                if kb_id not in outline_docs:
                    outline_docs[kb_id] = _read_outlines_file(workspace, kb_by_id[kb_id])
                outline = _outline_by_id(outline_docs[kb_id], outline_id)
            except RepositoryError as exc:
                issues.append(
                    {
                        "code": "invalid_bindto_outline_id",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "target_id": str(outline_id),
                        "message": str(exc),
                    }
                )
                continue
            if outline.get("status") == "archived":
                issues.append(
                    {
                        "code": "bindto_archived_outline",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "target_id": outline_id,
                        "message": (
                            f"{record.object_id}.bindto references archived outline "
                            f"{outline_id}"
                        ),
                    }
                )
            if node_id not in _outline_node_ids(outline.get("nodes", [])):
                issues.append(
                    {
                        "code": "invalid_bindto_node_id",
                        "object_id": record.object_id,
                        "field": "bindto",
                        "target_id": node_id,
                        "message": (
                            f"{record.object_id}.bindto references missing node "
                            f"{kb_id}/{outline_id}/{node_id}"
                        ),
                    }
                )
    bound = {record.object_id for record in knowledge if record.metadata.get("bindto")}
    for record in knowledge:
        if record.object_id not in bound:
            issues.append(
                {
                    "code": "unbound_knowledge",
                    "object_id": record.object_id,
                    "field": "bindto",
                    "message": f"{record.object_id} is not bound to any knowledgebase outline node",
                }
            )
    return issues


def _append_missing_or_type_issue(
    record: ObjectRecord,
    field_name: str,
    target_id: str,
    expected_type: str,
    by_id: dict[str, list[ObjectRecord]],
    issues: list[dict[str, str]],
) -> None:
    if _append_missing_reference_issue(record, field_name, target_id, by_id, issues):
        return
    if not any(target.object_type == expected_type for target in by_id[target_id]):
        issues.append(
            {
                "code": "reference_type_mismatch",
                "object_id": record.object_id,
                "field": field_name,
                "target_id": target_id,
                "message": (
                    f"{record.object_id}.{field_name} references {target_id}, "
                    f"but no {expected_type} object has that ID"
                ),
            }
        )


def _append_missing_reference_issue(
    record: ObjectRecord,
    field_name: str,
    target_id: str,
    by_id: dict[str, list[ObjectRecord]],
    issues: list[dict[str, str]],
) -> bool:
    if target_id in by_id:
        return False
    issues.append(
        {
            "code": "missing_reference",
            "object_id": record.object_id,
            "field": field_name,
            "target_id": target_id,
            "message": f"{record.object_id}.{field_name} references missing object {target_id}",
        }
    )
    return True


def _issue_warnings(issues: list[dict[str, str]]) -> list[str]:
    return [issue["message"] for issue in issues]


def _metadata_text(record: ObjectRecord, field_name: str) -> str:
    value = record.metadata.get(field_name, "")
    return value if isinstance(value, str) else str(value)


def _string_items(value: Any) -> list[str]:
    return value if _is_string_list(value) else []


def _join_strings(value: Any) -> str:
    return ", ".join(_string_items(value))


def _knowledgebase_ids_from_bindto(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("kb_id"), str):
            kb_id = item["kb_id"]
            if kb_id not in ids:
                ids.append(kb_id)
    return ids


def _table_row(values: list[str]) -> str:
    return "| " + " | ".join(_escape_table_cell(value) for value in values) + " |"


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _needs_review(
    operation: str,
    options: list[str],
    *,
    extra: dict[str, Any] | None = None,
) -> ApiResult:
    return ApiResult(
        status=ApiStatus.NEEDS_REVIEW,
        operation=operation,
        review=ReviewRequest(required=True, options=options),
        next_actions=["Provide a user review decision before retrying this operation."],
        extra=extra or {},
    )


def _has_review_decision(decision: str | None, expected: str) -> bool:
    return decision == expected


def _pending_candidate_record(
    repository: ObjectRepository,
    workspace: Workspace,
    candidate_id: str,
) -> ObjectRecord:
    record = _find_single_object(repository, candidate_id, expected_type="candidate")
    if record.status != "pending":
        raise RepositoryError(f"candidate must be pending: {candidate_id}")
    if workspace.relative(record.path).parts[:2] != ("candidates", "pending"):
        raise RepositoryError(f"pending candidate outside candidates/pending: {candidate_id}")
    return record


def _validate_review_content(
    *,
    title: str | None,
    summary: str | None,
    content: str | None,
    evidence: list[dict[str, Any]] | None,
    bindto: list[dict[str, Any]] | None,
) -> None:
    if title is not None and not title.strip():
        raise RepositoryError("reviewed title must be non-empty when provided; expected string")
    if summary is not None and not summary.strip():
        raise RepositoryError("reviewed summary must be non-empty when provided; expected string")
    if content is not None and not content.strip():
        raise RepositoryError("reviewed content must be non-empty when provided; expected string")
    if evidence is not None and not _is_mapping_list(evidence):
        raise RepositoryError(EVIDENCE_SHAPE)
    if bindto is not None and not _is_mapping_list(bindto):
        raise RepositoryError(BINDTO_SHAPE)


def _validate_existing_refs(
    repository: ObjectRepository,
    object_ids: list[str],
    field_name: str,
) -> None:
    if not _is_string_list(object_ids):
        raise RepositoryError(f"{field_name} must be a list of strings; use [] when empty")
    for object_id in object_ids:
        _find_single_object(repository, object_id)


def _validate_required_accept_content(
    *,
    title: str | None,
    summary: str | None,
    content: str | None,
    evidence: list[dict[str, Any]] | None,
    bindto: list[dict[str, Any]] | None,
) -> None:
    _validate_review_content(
        title=title,
        summary=summary,
        content=content,
        evidence=evidence,
        bindto=bindto,
    )
    if title is None or summary is None or content is None or evidence is None or bindto is None:
        raise RepositoryError(
            "accept requires reviewed title, summary, content, evidence, and bindto; "
            "pass bindto as [] or binding mappings"
        )
    if not evidence:
        raise RepositoryError("accept evidence must reference at least one source")


def _validate_required_merge_content(
    *,
    summary: str | None,
    content: str | None,
    evidence: list[dict[str, Any]] | None,
    bindto: list[dict[str, Any]] | None,
) -> None:
    _validate_review_content(
        title=None,
        summary=summary,
        content=content,
        evidence=evidence,
        bindto=bindto,
    )
    if summary is None or content is None or evidence is None or bindto is None:
        raise RepositoryError(
            "merge requires reviewed summary, content, evidence, and bindto; "
            "pass bindto as [] or binding mappings"
        )


def _knowledge_body(reviewed_body: str | None, fallback_body: str) -> str:
    body = reviewed_body if reviewed_body is not None else fallback_body
    if not body.startswith("\n"):
        body = "\n" + body
    if not body.endswith("\n"):
        body += "\n"
    return body


def _reviewed_candidate_document(
    document: MarkdownDocument,
    *,
    status: str,
    decision: str,
    reason: str | None,
) -> MarkdownDocument:
    frontmatter = dict(document.frontmatter)
    today = _today()
    frontmatter.update(
        {
            "type": "candidate",
            "status": status,
            "review": {
                "reviewed_at": today,
                "decision": decision,
                "reason": reason,
            },
            "updated": today,
        }
    )
    return MarkdownDocument(frontmatter=frontmatter, body=document.body)


def _move_reviewed_candidate(
    root: str | Path,
    *,
    operation: str,
    candidate_id: str,
    target_status: str,
    decision: str,
    reason: str | None,
) -> ApiResult:
    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _pending_candidate_record(repository, workspace, candidate_id)
        document = repository.read_markdown(workspace.relative(record.path))
        reviewed_document = _reviewed_candidate_document(
            document,
            status=target_status,
            decision=decision,
            reason=reason,
        )
        source_relative = str(workspace.relative(record.path))
        target_relative = f"candidates/{target_status}/{candidate_id}.md"
        diffs = [
            {
                "action": "move",
                "kind": "candidate",
                "from": source_relative,
                "path": target_relative,
            }
        ]
        _move_candidate_document(
            repository,
            workspace,
            record.path,
            target_relative,
            reviewed_document,
        )
    except (KBManagerError, OSError) as exc:
        return _failed(
            operation,
            "candidate_review_failed",
            str(exc),
            "Review a pending candidate and provide the matching user decision.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        operation,
        objects=ObjectChanges(updated=[target_relative]),
        diffs=diffs,
        extra={"candidate_id": candidate_id, "candidate_status": target_status},
    )


def _promote_candidate_to_knowledge(
    repository: ObjectRepository,
    candidate_path: Path,
    knowledge_path: str,
    knowledge_document: MarkdownDocument,
) -> None:
    created: list[Path] = []
    try:
        target = repository.write_markdown(knowledge_path, knowledge_document)
        created.append(target)
        candidate_path.unlink()
    except Exception:
        _rollback_created(created)
        raise


def _move_candidate_document(
    repository: ObjectRepository,
    workspace: Workspace,
    source_path: Path,
    target_relative: str,
    document: MarkdownDocument,
) -> None:
    created: list[Path] = []
    try:
        target = repository.write_markdown(target_relative, document)
        created.append(target)
        source_path.unlink()
    except Exception:
        _rollback_created(created)
        raise


def _merge_candidate_into_knowledge(
    repository: ObjectRepository,
    workspace: Workspace,
    candidate_path: Path,
    rejected_relative: str,
    rejected_candidate: MarkdownDocument,
    knowledge_relative: str,
    merged_knowledge: MarkdownDocument,
    original_knowledge: MarkdownDocument,
) -> None:
    knowledge_updated = False
    try:
        repository.write_markdown(knowledge_relative, merged_knowledge, overwrite=True)
        knowledge_updated = True
        _move_candidate_document(
            repository,
            workspace,
            candidate_path,
            rejected_relative,
            rejected_candidate,
        )
    except Exception:
        if knowledge_updated:
            repository.write_markdown(
                knowledge_relative,
                original_knowledge,
                overwrite=True,
            )
        raise


def _validate_knowledgebase_input(
    repository: ObjectRepository,
    *,
    title: str,
    knowledgebase_id: str | None,
) -> None:
    if not isinstance(title, str) or not title.strip():
        raise RepositoryError("knowledge base title must be a non-empty string")
    if knowledgebase_id is not None:
        if not ID_RE.match(knowledgebase_id) or not knowledgebase_id.startswith("kb-"):
            raise RepositoryError(
                f"invalid knowledge base ID: {knowledgebase_id}; expected kb-YYYYMMDD-001 "
                "or kb-YYYYMMDD-001-title-slug"
            )
        if knowledgebase_id in _id_paths(repository):
            raise RepositoryError(f"knowledge base ID already exists: {knowledgebase_id}")
    normalized_title = title.strip().casefold()
    for record in _all_records(repository):
        if (
            record.object_type == "knowledge-base"
            and str(record.metadata.get("title", "")).strip().casefold() == normalized_title
        ):
            raise RepositoryError(f"knowledge base title already exists: {title.strip()}")


def _knowledgebase_body(description: str, scope: dict[str, Any], outlines: Any) -> str:
    scope_text = yaml.safe_dump(scope, sort_keys=False, allow_unicode=True).strip()
    outlines_text = yaml.safe_dump(outlines, sort_keys=False, allow_unicode=True).strip()
    return (
        f"\n## Description\n\n{description.strip()}\n\n"
        f"## Scope\n\n```yaml\n{scope_text}\n```\n\n"
        f"## Outlines\n\n```yaml\n{outlines_text}\n```\n\n"
        "## Derived Member View\n"
    )


def _has_knowledgebase_create_payload(
    *,
    description: str | None,
    scope: dict[str, Any] | None,
    default_outline_id: str | None,
    outlines: list[dict[str, Any]] | None,
) -> bool:
    return any(value is not None for value in (description, scope, default_outline_id, outlines))


def _knowledgebase_create_token_payload(
    *,
    title: str,
    input_path: str | Path,
    knowledgebase_id: str | None,
    input_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": title,
        "input_path": str(input_path),
        "knowledgebase_id": knowledgebase_id,
        "knowledgebase_create_input": input_context,
    }


def _knowledgebase_create_input_context(
    workspace: Workspace,
    input_path: str | Path,
) -> dict[str, Any]:
    input_text = str(input_path)
    resolved = _resolve_external_input(workspace.root, input_path)
    if resolved.is_file():
        return {
            "input_path": input_text,
            "input_kind": "file",
            "resolved_path": str(resolved),
            "content": resolved.read_text(encoding="utf-8"),
        }
    if resolved.is_dir():
        documents = []
        for path in sorted(resolved.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".yaml", ".yml"}:
                documents.append(
                    {
                        "path": str(path),
                        "content": path.read_text(encoding="utf-8"),
                    }
                )
        return {
            "input_path": input_text,
            "input_kind": "directory",
            "resolved_path": str(resolved),
            "documents": documents,
        }
    return {
        "input_path": input_text,
        "input_kind": "missing",
        "content": "",
        "warning": "Input path was not readable when assembling the LLM request.",
    }


def _resolve_external_input(root: Path, input_path: str | Path) -> Path:
    path = Path(input_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    workspace_path = (root / path).resolve()
    if workspace_path.exists():
        return workspace_path
    return path.resolve()


def _validate_knowledgebase_create_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RepositoryError(
            "knowledgebase create payload must include description, tags, scope, "
            "default_outline_id, and outlines"
        )
    if "frontmatter" in payload and isinstance(payload["frontmatter"], dict):
        payload = payload["frontmatter"]
    description = payload.get("description")
    tags = payload.get("tags", [])
    scope = payload.get("scope")
    default_outline_id = payload.get("default_outline_id")
    outlines = payload.get("outlines")
    if not isinstance(description, str) or not description.strip():
        raise RepositoryError("knowledgebase description must be a non-empty string")
    if not _is_string_list(tags):
        raise RepositoryError("knowledgebase tags must be a list of strings")
    if not isinstance(scope, dict):
        raise RepositoryError("knowledgebase scope must be a mapping with includes/excludes")
    if not _is_string_list(scope.get("includes")) or not _is_string_list(scope.get("excludes")):
        raise RepositoryError("knowledgebase scope.includes and scope.excludes must be lists")
    if not isinstance(default_outline_id, str) or not default_outline_id.strip():
        raise RepositoryError("knowledgebase default_outline_id must be a non-empty string")
    outlines = _validate_outlines(outlines, default_outline_id.strip())
    return {
        "description": description.strip(),
        "tags": tags,
        "scope": {"includes": scope["includes"], "excludes": scope["excludes"]},
        "default_outline_id": default_outline_id.strip(),
        "outlines": outlines,
    }


def _validate_outlines(outlines: Any, default_outline_id: str) -> list[dict[str, Any]]:
    if not isinstance(outlines, list) or not outlines:
        raise RepositoryError("knowledgebase outlines must be a non-empty list")
    result: list[dict[str, Any]] = []
    seen_outline_ids: set[str] = set()
    active_outline_ids: set[str] = set()
    for item in outlines:
        outline = _validate_single_outline(item)
        outline_id = outline["id"]
        if outline_id in seen_outline_ids:
            raise RepositoryError(f"duplicate outline id: {outline_id}")
        seen_outline_ids.add(outline_id)
        if outline["status"] == "active":
            active_outline_ids.add(outline_id)
        result.append(outline)
    if default_outline_id not in active_outline_ids:
        raise RepositoryError("default_outline_id must reference an active outline")
    return result


def _validate_single_outline(outline: Any) -> dict[str, Any]:
    if not isinstance(outline, dict):
        raise RepositoryError("outline must be a mapping")
    outline_id = outline.get("id")
    title = outline.get("title")
    description = outline.get("description", "")
    status = outline.get("status", "active")
    nodes = outline.get("nodes", [])
    if not isinstance(outline_id, str) or not outline_id.strip():
        raise RepositoryError("outline.id must be a non-empty string")
    if not isinstance(title, str) or not title.strip():
        raise RepositoryError("outline.title must be a non-empty string")
    if not isinstance(description, str):
        raise RepositoryError("outline.description must be a string")
    if status not in {"active", "draft", "archived"}:
        raise RepositoryError("outline.status must be active, draft, or archived")
    if not isinstance(nodes, list):
        raise RepositoryError("outline.nodes must be a list")
    _validate_outline_node_ids(nodes)
    clean = dict(outline)
    clean.update(
        {
            "id": outline_id.strip(),
            "title": title.strip(),
            "description": description,
            "status": status,
            "nodes": nodes,
        }
    )
    return clean


def _validate_outline_node_ids(nodes: list[Any]) -> None:
    seen: set[str] = set()

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            raise RepositoryError("outline nodes must be mappings with explicit id")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise RepositoryError("outline node.id must be a non-empty string")
        if node_id in seen:
            raise RepositoryError(f"duplicate outline node id: {node_id}")
        seen.add(node_id)
        children = node.get("children", [])
        if children is None:
            return
        if not isinstance(children, list):
            raise RepositoryError("outline node.children must be a list")
        for child in children:
            visit(child)

    for node in nodes:
        visit(node)


def _default_outlines_file(kb_relative_path: str) -> str:
    path = Path(kb_relative_path)
    return str(path.with_name(f"{path.stem}-outlines.yml"))


def _outlines_document(
    kb_id: str,
    default_outline_id: str,
    outlines: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kb_id": kb_id,
        "default_outline_id": default_outline_id,
        "outlines": outlines,
    }


def _outline_manifest(outlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": outline["id"],
            "title": outline["title"],
            "description": outline.get("description", ""),
            "status": outline.get("status", "active"),
        }
        for outline in outlines
    ]


def _outlines_file_for_record(workspace: Workspace, record: ObjectRecord) -> str:
    value = record.metadata.get("outlines_file")
    if not isinstance(value, str) or not value.strip():
        raise RepositoryError(f"{record.object_id} missing outlines_file")
    expected = _default_outlines_file(str(workspace.relative(record.path)))
    if value != expected:
        raise RepositoryError(f"{record.object_id}.outlines_file must be {expected}")
    return value


def _read_outlines_file(workspace: Workspace, record: ObjectRecord) -> dict[str, Any]:
    relative_path = _outlines_file_for_record(workspace, record)
    path = workspace.resolve(relative_path)
    if not path.exists():
        raise RepositoryError(f"knowledgebase outlines file not found: {relative_path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RepositoryError(f"invalid outlines YAML in {relative_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RepositoryError(f"outlines file must contain a mapping: {relative_path}")
    if data.get("kb_id") != record.object_id:
        raise RepositoryError(f"outlines file kb_id mismatch for {record.object_id}")
    default_outline_id = data.get("default_outline_id")
    if default_outline_id != record.metadata.get("default_outline_id"):
        raise RepositoryError(f"default_outline_id mismatch for {record.object_id}")
    outlines = _validate_outlines(data.get("outlines"), str(default_outline_id))
    manifest = _outline_manifest(outlines)
    if manifest != record.metadata.get("outlines"):
        raise RepositoryError(f"outline manifest mismatch for {record.object_id}")
    return {
        "kb_id": record.object_id,
        "default_outline_id": default_outline_id,
        "outlines": outlines,
    }


def _write_yaml_file(
    workspace: Workspace,
    relative_path: str,
    data: dict[str, Any],
    *,
    overwrite: bool = False,
) -> None:
    path = workspace.ensure_parent(relative_path)
    if path.exists() and not overwrite:
        raise RepositoryError(f"path already exists: {relative_path}")
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    _write_text_atomic_overwrite(path, text)


def _outline_by_id(outlines_document: dict[str, Any], outline_id: str) -> dict[str, Any]:
    if not isinstance(outline_id, str) or not outline_id.strip():
        raise RepositoryError("outline_id must be a non-empty string")
    for outline in outlines_document.get("outlines", []):
        if isinstance(outline, dict) and outline.get("id") == outline_id:
            return outline
    raise RepositoryError(f"outline not found: {outline_id}")


def _knowledge_bound_to_outline(
    repository: ObjectRepository,
    kb_id: str,
    outline_id: str,
) -> set[str]:
    bound: set[str] = set()
    for record in _all_records(repository):
        if record.object_type != "knowledge" or record.status != "accepted":
            continue
        for item in record.metadata.get("bindto", []):
            if (
                isinstance(item, dict)
                and item.get("kb_id") == kb_id
                and item.get("outline_id") == outline_id
            ):
                bound.add(record.object_id)
    return bound


def _review_approved(review: dict[str, Any] | None) -> bool:
    return isinstance(review, dict) and review.get("decision") == "approve"


def _source_ids_from_evidence(evidence: list[Any]) -> list[str]:
    ids: list[str] = []
    for item in evidence:
        if isinstance(item, dict):
            value = item.get("source_id") or item.get("object_id") or item.get("id")
            if isinstance(value, str) and value not in ids:
                ids.append(value)
    return ids


def _validate_reviewed_evidence_from_candidate(
    evidence: list[dict[str, Any]],
    candidate_frontmatter: dict[str, Any],
) -> None:
    candidate_keys = {
        (
            item.get("source_id") or item.get("object_id") or item.get("id"),
            item.get("locator"),
            item.get("quote") or item.get("excerpt") or item.get("snippet"),
        )
        for item in candidate_frontmatter.get("evidence", [])
        if isinstance(item, dict)
    }
    for item in evidence:
        key = (
            item.get("source_id") or item.get("object_id") or item.get("id"),
            item.get("locator"),
            item.get("quote") or item.get("excerpt") or item.get("snippet"),
        )
        if key not in candidate_keys:
            raise RepositoryError("accepted evidence must come from the candidate evidence")


def _outline_node_ids(outline: Any) -> set[str]:
    ids: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node_id = node.get("id")
            if isinstance(node_id, str) and node_id.strip():
                ids.add(node_id)
            children = node.get("children", [])
            if isinstance(children, list):
                for child in children:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(outline)
    return ids


def _outline_nodes_with_labels(outline: Any) -> list[tuple[str, str, str | None]]:
    nodes: list[tuple[str, str, str | None]] = []

    def visit(node: Any, parent_id: str | None = None, fallback: str = "") -> None:
        if isinstance(node, dict):
            node_id = node.get("id")
            title = node.get("title") or node_id
            current_id = str(node_id)
            if current_id:
                nodes.append((current_id, str(title), parent_id))
            children = node.get("children")
            if isinstance(children, list):
                for index, child in enumerate(children):
                    visit(child, current_id, f"{current_id}/{index}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, parent_id, str(index))

    visit(outline)
    return nodes


def _active_knowledgebase_context(repository: ObjectRepository) -> list[dict[str, Any]]:
    records = [
        record
        for record in _all_records(repository)
        if record.object_type == "knowledge-base" and record.status == "active"
    ]
    context: list[dict[str, Any]] = []
    for record in records:
        outlines_document = _read_outlines_file(repository.workspace, record)
        context.append(
            {
                "id": record.object_id,
                "title": record.metadata.get("title"),
                "description": record.metadata.get("description"),
                "tags": record.metadata.get("tags", []),
                "scope": record.metadata.get("scope", {}),
                "default_outline_id": record.metadata.get("default_outline_id"),
                "outlines": outlines_document.get("outlines", []),
            }
        )
    return context


def _candidate_source_context(
    repository: ObjectRepository,
    records: list[ObjectRecord],
) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    workspace = repository.workspace
    for record in records:
        metadata = dict(record.metadata)
        source_item: dict[str, Any] = {
            "id": record.object_id,
            "path": str(workspace.relative(record.path)),
            "status": record.status,
            "source_type": metadata.get("source_type"),
            "title": metadata.get("title"),
            "summary": metadata.get("summary"),
            "tags": metadata.get("tags", []),
            "cleaned": metadata.get("cleaned", {}),
        }
        cleaned_path = _cleaned_path_from_source_metadata(metadata)
        if cleaned_path is not None:
            source_item["cleaned_path"] = cleaned_path
            source_item["cleaned_content"] = _read_optional_workspace_text(workspace, cleaned_path)
        if record.path.suffix.lower() == ".md":
            try:
                document = repository.read_markdown(workspace.relative(record.path))
            except RepositoryError:
                document = None
            if document is not None:
                source_item["source_body"] = document.body
        context.append(source_item)
    return context


def _cleaned_path_from_source_metadata(metadata: dict[str, Any]) -> str | None:
    cleaned = metadata.get("cleaned")
    if isinstance(cleaned, dict) and isinstance(cleaned.get("path"), str):
        return cleaned["path"]
    return None


def _read_optional_workspace_text(workspace: Workspace, relative_path: str) -> str:
    try:
        return workspace.resolve(relative_path).read_text(encoding="utf-8")
    except OSError as exc:
        return f"<unreadable: {exc}>"


def _validate_outline_change_suggestions(
    repository: ObjectRepository,
    suggestions: list[dict[str, Any]],
) -> None:
    for item in suggestions:
        kb_id = item.get("kb_id")
        if not isinstance(kb_id, str) or not kb_id.strip():
            raise RepositoryError("outline_change_suggestions[].kb_id is required")
        record = _find_single_object(repository, kb_id)
        if record.object_type != "knowledge-base" or record.status != "active":
            raise RepositoryError(
                f"outline_change_suggestions[].kb_id must reference active knowledge-base: {kb_id}"
            )
        outline_id = item.get("outline_id")
        if outline_id is not None:
            outlines_document = _read_outlines_file(repository.workspace, record)
            _outline_by_id(outlines_document, str(outline_id))
        for field in ("reason", "suggested_change"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise RepositoryError(f"outline_change_suggestions[].{field} is required")


def _validate_note_input(
    repository: ObjectRepository,
    *,
    content: str,
    title: str | None,
    note_id: str | None,
) -> None:
    if not isinstance(content, str) or not content.strip():
        raise RepositoryError("note content must be a non-empty string")
    if title is not None and not title.strip():
        raise RepositoryError("note title must be non-empty when provided; omit it to derive one")
    if note_id is not None:
        if not ID_RE.match(note_id) or not note_id.startswith("note-"):
            raise RepositoryError(
                f"invalid note ID: {note_id}; expected note-YYYYMMDD-001 or "
                "note-YYYYMMDD-001-title-slug"
            )
        if note_id in _id_paths(repository):
            raise RepositoryError(f"note ID already exists: {note_id}")


def _validate_note_llm_result(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RepositoryError("llm_result must be a mapping like {'title': '<note title>'}")
    title = result.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RepositoryError("llm_result.title must be a non-empty string")
    return {
        "title": title.strip(),
    }


def _note_title(content: str) -> str:
    for line in content.splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            return candidate[:80]
    return "Untitled Note"


def _note_body(content: str) -> str:
    body = content.strip()
    if body.startswith("## Note"):
        return f"\n{body}\n"
    return f"\n## Note\n\n{body}\n"


def _note_response_extra(
    note_id: str,
    relative_path: str,
    document: MarkdownDocument,
) -> dict[str, Any]:
    return {
        "note_id": note_id,
        "path": relative_path,
        "note": _note_payload(note_id, relative_path, document),
    }


def _note_payload(
    note_id: str,
    relative_path: str,
    document: MarkdownDocument,
) -> dict[str, Any]:
    frontmatter = dict(document.frontmatter)
    _clean_note_frontmatter(frontmatter)
    return {
        "id": note_id,
        "path": relative_path,
        "frontmatter": frontmatter,
        "body": document.body,
    }


def _clean_note_frontmatter(frontmatter: dict[str, Any]) -> None:
    for field in ("bindings", "tags", "summary"):
        frontmatter.pop(field, None)
    frontmatter["status"] = _note_status(str(frontmatter.get("status", "")))


def _note_status(status: str) -> str:
    return "deprecated" if status == "deprecated" else "active"


def _clean_expectations() -> dict[str, Any]:
    return {
        "directories": list(INIT_DIRECTORIES),
        "object_schemas": {
            object_type: {
                "required_fields": sorted(schema["required"]),
                "allowed_fields": sorted(schema["allowed"]),
            }
            for object_type, schema in _clean_object_schemas().items()
        },
        "note": {
            "directories": ["notes/active", "notes/deprecated"],
            "statuses": ["active", "deprecated"],
        },
    }


def _clean_differences(
    workspace: Workspace,
    repository: ObjectRepository,
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    for relative_dir in sorted(INIT_DIRECTORIES):
        if not workspace.resolve(relative_dir).is_dir():
            differences.append(
                {
                    "kind": "missing_directory",
                    "path": relative_dir,
                    "expected": "directory exists",
                }
            )

    for record in _all_records(repository):
        _append_field_schema_differences(record, workspace, differences)
        if record.object_type != "note":
            continue
        relative_path = str(workspace.relative(record.path))
        if record.status not in {"active", "deprecated"}:
            differences.append(
                {
                    "kind": "status_drift",
                    "object_id": record.object_id,
                    "object_type": "note",
                    "path": relative_path,
                    "current": record.status,
                    "expected": _note_status(record.status),
                    "migration": "update note status",
                }
            )

        expected_dir = "notes/deprecated" if record.status == "deprecated" else "notes/active"
        expected_path = f"{expected_dir}/{record.path.name}"
        if relative_path != expected_path and relative_path.startswith("notes/"):
            diff: dict[str, Any] = {
                "kind": "path_migration",
                "object_id": record.object_id,
                "object_type": "note",
                "from": relative_path,
                "to": expected_path,
                "migration": "move note file",
            }
            target = workspace.resolve(expected_path)
            if target.exists() and target != record.path:
                diff["risk"] = "target_exists"
            differences.append(diff)
    return differences


def _append_field_schema_differences(
    record: ObjectRecord,
    workspace: Workspace,
    differences: list[dict[str, Any]],
) -> None:
    schemas = _clean_object_schemas()
    schema = schemas.get(record.object_type)
    relative_path = str(workspace.relative(record.path))
    if schema is None:
        differences.append(
            {
                "kind": "unknown_object_type",
                "object_id": record.object_id,
                "object_type": record.object_type,
                "path": relative_path,
                "expected": sorted(schemas),
                "migration": "review object type before migration",
            }
        )
        return

    fields = set(record.metadata)
    missing = sorted(schema["required"] - fields)
    if missing:
        differences.append(
            {
                "kind": "missing_fields",
                "object_id": record.object_id,
                "object_type": record.object_type,
                "path": relative_path,
                "fields": missing,
                "migration": "add required frontmatter fields with reviewed values",
            }
        )

    unexpected = sorted(fields - schema["allowed"])
    if unexpected:
        differences.append(
            {
                "kind": "unexpected_fields",
                "object_id": record.object_id,
                "object_type": record.object_type,
                "path": relative_path,
                "fields": unexpected,
                "migration": "remove or migrate unsupported frontmatter fields",
            }
        )


def _clean_object_schemas() -> dict[str, dict[str, set[str]]]:
    object_fields = {"id", "type", "title", "status", "created", "updated"}
    review_fields = {"reviewed_at", "review_decision"}
    return {
        "source": {
            "required": object_fields
            | {
                "source_type",
                "path",
                "summary",
                "cleaned",
                "authors",
                "published_at",
                "imported_at",
                "deprecated_at",
                "deprecated_reason",
                "tags",
            },
            "allowed": object_fields
            | review_fields
            | {
                "source_type",
                "path",
                "summary",
                "cleaned",
                "authors",
                "published_at",
                "imported_at",
                "deprecated_at",
                "deprecated_reason",
                "tags",
            },
        },
        "candidate": {
            "required": object_fields
            | {
                "bindto",
                "outline_change_suggestions",
                "summary",
                "evidence",
                "review",
            },
            "allowed": object_fields
            | {
                "bindto",
                "outline_change_suggestions",
                "summary",
                "evidence",
                "review",
            },
        },
        "knowledge": {
            "required": object_fields
            | {
                "summary",
                "evidence",
                "bindto",
                "deprecated_at",
                "deprecated_reason",
            },
            "allowed": object_fields
            | review_fields
            | {
                "summary",
                "evidence",
                "bindto",
                "review_reason",
                "deprecated_at",
                "deprecated_reason",
            },
        },
        "knowledge-base": {
            "required": object_fields
            | {
                "description",
                "tags",
                "scope",
                "default_outline_id",
                "outlines_file",
                "outlines",
            },
            "allowed": object_fields
            | review_fields
            | {
                "description",
                "tags",
                "scope",
                "default_outline_id",
                "outlines_file",
                "outlines",
            },
        },
        "note": {
            "required": object_fields | {"deprecated_at", "deprecated_reason"},
            "allowed": object_fields | review_fields | {"deprecated_at", "deprecated_reason"},
        },
    }


def _clean_warnings(differences: list[dict[str, Any]]) -> list[str]:
    if any(diff.get("risk") == "target_exists" for diff in differences):
        return ["clean migration has target path conflicts; do not overwrite files."]
    return []


def _move_or_update_note_document(
    repository: ObjectRepository,
    source_path: Path,
    source_relative: str,
    deprecated_relative: str,
    document: MarkdownDocument,
) -> None:
    if source_relative == deprecated_relative:
        repository.write_markdown(deprecated_relative, document, overwrite=True)
        return

    created: list[Path] = []
    try:
        target = repository.write_markdown(deprecated_relative, document)
        created.append(target)
        source_path.unlink()
    except Exception:
        _rollback_created(created)
        raise


def _merged_strings(first: list[Any], second: list[Any]) -> list[str]:
    merged: list[str] = []
    for item in first + second:
        if isinstance(item, str) and item not in merged:
            merged.append(item)
    return merged


def _plan_init(workspace: Workspace) -> InitPlan:
    _ensure_writable_root(workspace.root)

    create_directories: list[str] = []
    create_files: list[str] = []
    existing: list[str] = []
    conflicts: list[str] = []

    for relative_dir in INIT_DIRECTORIES:
        path = workspace.resolve(relative_dir)
        parent_conflict = _parent_directory_conflict(workspace, path, relative_dir)
        if parent_conflict is not None:
            conflicts.append(parent_conflict)
            continue
        if path.exists():
            if path.is_dir():
                existing.append(relative_dir)
            else:
                conflicts.append(f"{relative_dir}: expected directory, found file")
        else:
            create_directories.append(relative_dir)

    for relative_file, expected_content in INIT_FILES.items():
        path = workspace.resolve(relative_file)
        parent_conflict = _parent_directory_conflict(workspace, path, relative_file)
        if parent_conflict is not None:
            conflicts.append(parent_conflict)
            continue
        if path.exists():
            if not path.is_file():
                conflicts.append(f"{relative_file}: expected file, found directory")
                continue
            try:
                actual_content = path.read_text(encoding="utf-8")
            except OSError as exc:
                conflicts.append(f"{relative_file}: could not read existing file: {exc}")
                continue
            if actual_content == expected_content:
                existing.append(relative_file)
            else:
                conflicts.append(f"{relative_file}: existing file is not a KBManager placeholder")
        else:
            create_files.append(relative_file)

    return InitPlan(
        create_directories=create_directories,
        create_files=create_files,
        existing=existing,
        conflicts=conflicts,
    )


def _failed(operation: str, code: str, message: str, suggestion: str) -> ApiResult:
    return ApiResult.failed(operation, code, message, suggestion)


def _success_with_index_rebuild(
    root: str | Path,
    operation: str,
    *,
    objects: ObjectChanges,
    diffs: list[dict[str, Any]],
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> ApiResult:
    rebuild = index_rebuild(root)
    rebuild_data = rebuild.to_dict()
    rebuild_diffs = [diff for diff in rebuild.diffs if diff.get("action") in {"create", "update"}]
    merged_objects = ObjectChanges(
        created=objects.created,
        updated=objects.updated + rebuild.objects.updated,
        deprecated=objects.deprecated,
    )
    merged_warnings = (warnings or []) + rebuild.warnings
    merged_extra = dict(extra or {})
    merged_extra["index_rebuild"] = {
        "status": rebuild_data["status"],
        "updated": rebuild.objects.updated,
        "index_paths": rebuild_data.get("index_paths", []),
        "issues": rebuild_data.get("issues", []),
    }

    if rebuild.status == ApiStatus.SUCCESS:
        return ApiResult.success(
            operation,
            objects=merged_objects,
            diffs=diffs + rebuild_diffs,
            warnings=merged_warnings,
            next_actions=next_actions or [],
            extra=merged_extra,
        )

    return ApiResult(
        status=ApiStatus.PARTIAL,
        operation=operation,
        objects=objects,
        diffs=diffs,
        warnings=merged_warnings,
        errors=rebuild.errors,
        next_actions=[
            "Object changes were written, but index rebuild failed. "
            "Fix the reported issue and run kb.index.rebuild."
        ],
        extra=merged_extra,
    )


def _needs_llm(
    operation: str,
    *,
    purpose: str,
    system_prompt: str,
    required_context: list[str],
    output_schema: str,
    constraints: list[str],
    token_payload: dict[str, Any],
    warnings: list[str] | None = None,
) -> ApiResult:
    token = _resume_token(operation, token_payload)
    request_id = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    prompt = prompt_descriptor(
        purpose=purpose,
        output_schema=output_schema,
        user_input=token_payload,
        object_context={
            "required_context": required_context,
            "include_object_body": purpose == "source_ingest",
        },
        constraints=constraints,
    )
    return ApiResult(
        status=ApiStatus.NEEDS_LLM,
        operation=operation,
        warnings=warnings or [],
        next_actions=[f"Run LLM request {request_id}, then resume {operation}."],
        extra={
            "llm_request": {
                "id": f"llm-{request_id}",
                "purpose": purpose,
                "system_prompt": prompt["system_prompt"],
                "prompt_version": prompt["prompt_version"],
                "required_context": required_context,
                "output_schema": output_schema,
                "output_schema_definition": prompt["output_schema_definition"],
                "constraints": constraints,
                "prompt": prompt["prompt"],
            },
            "resume": {"operation": operation, "token": token},
            "run_record": {
                "operation": operation,
                "llm_request_id": f"llm-{request_id}",
                "prompt": prompt["system_prompt"],
                "prompt_version": prompt["prompt_version"],
            },
        },
    )


def _resume_token(operation: str, payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(f"{operation}:{normalized}".encode()).hexdigest()[:24]
    return f"resume-{operation}-{digest}"


def _source_inputs(workspace: Workspace, input_path: str | Path) -> list[SourceInput]:
    resolved = _resolve_local_source_input(workspace, input_path)
    if resolved.is_file():
        return [
            SourceInput(
                path=resolved,
                relative_path=_source_input_reference(workspace, resolved),
                source_kind=_validate_source_input(resolved),
                title_hint=resolved.stem,
            )
        ]
    if resolved.is_dir():
        inputs = [
            SourceInput(
                path=path,
                relative_path=_source_input_reference(workspace, path),
                source_kind=_validate_source_input(path),
                title_hint=path.stem,
            )
            for path in sorted(resolved.rglob("*"))
            if path.is_file() and path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
        ]
        if not inputs:
            raise RepositoryError(f"source directory contains no supported files: {resolved}")
        return inputs
    raise RepositoryError(f"source input does not exist: {resolved}")


def _resolve_local_source_input(workspace: Workspace, input_path: str | Path) -> Path:
    candidate = Path(input_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    workspace_candidate = (workspace.root / candidate).resolve()
    if workspace_candidate.exists():
        return workspace_candidate
    return candidate.resolve()


def _source_input_reference(workspace: Workspace, path: Path) -> str:
    try:
        return str(workspace.relative(path))
    except WorkspacePathError:
        return str(path)


def _source_context_documents(source_inputs: list[SourceInput]) -> list[dict[str, str]]:
    return []


def _validate_source_input(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise RepositoryError(f"source input does not exist or is not a file: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SOURCE_SUFFIXES:
        raise RepositoryError(f"unsupported source type: {suffix}")
    return "markdown" if suffix == ".md" else "pdf"


def _source_add_input_failure_recovery() -> tuple[str, list[str]]:
    return (
        "Provide a readable .md or .pdf file from the local filesystem. KBManager writes "
        "managed objects only inside the workspace.",
        [],
    )


def _validate_source_add_input(
    *,
    title: str | None,
    tags: list[str] | None,
    authors: list[str] | None,
) -> None:
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise RepositoryError("source title must be a non-empty string when provided")
    if tags is not None and not _is_string_list(tags):
        raise RepositoryError("source tags must be a list of strings; use [] when empty")
    if authors is not None and not _is_string_list(authors):
        raise RepositoryError("source authors must be a list of strings; use [] when empty")


def _validate_source_llm_results(
    result: dict[str, Any] | None,
    source_inputs: list[SourceInput],
) -> list[dict[str, Any]]:
    if len(source_inputs) == 1:
        parsed = _validate_source_llm_result(result, source_inputs[0].relative_path)
        return [parsed]
    if not isinstance(result, dict):
        raise RepositoryError(
            "llm_result must be a mapping with sources: [{'input_path': '<requested path>', "
            "'summary': '<summary>', 'cleaned_content': '<content mentioning input_path>'}]"
        )
    sources = result.get("sources")
    if not isinstance(sources, list) or len(sources) != len(source_inputs):
        raise RepositoryError(
            "llm_result.sources must match the requested source files; provide exactly one "
            "result per requested input_path"
        )

    expected_paths = [source.relative_path for source in source_inputs]
    by_path: dict[str, dict[str, Any]] = {}
    for item in sources:
        if not isinstance(item, dict):
            raise RepositoryError(
                "each source ingest result must be a mapping with input_path, summary, and "
                "cleaned_content"
            )
        input_ref = item.get("input_path")
        if not isinstance(input_ref, str):
            raise RepositoryError("source ingest result must include input_path as a string")
        if input_ref in by_path:
            raise RepositoryError(f"duplicate source ingest result for input_path: {input_ref}")
        by_path[input_ref] = _validate_source_llm_result(item, input_ref)

    missing = sorted(set(expected_paths) - set(by_path))
    extra = sorted(set(by_path) - set(expected_paths))
    if missing or extra:
        raise RepositoryError(
            "source ingest results must exactly match requested input paths; missing="
            f"{missing}, extra={extra}"
        )
    return [by_path[path] for path in expected_paths]


def _validate_source_llm_result(
    result: dict[str, Any] | None,
    expected_input_path: str,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RepositoryError(
            "llm_result must be a mapping like {'input_path': '<requested path>', "
            "'summary': '<summary>', 'cleaned_content': '<content mentioning input_path>'}"
        )
    if result.get("input_path") != expected_input_path:
        raise RepositoryError(
            "llm_result.input_path must match the requested source input path; expected "
            f"{expected_input_path!r}"
        )
    summary = result.get("summary")
    cleaned_content = result.get("cleaned_content")
    if not isinstance(summary, str) or not summary.strip():
        raise RepositoryError("llm_result.summary must be a non-empty string")
    if not isinstance(cleaned_content, str) or not cleaned_content.strip():
        raise RepositoryError("llm_result.cleaned_content must be a non-empty string")
    if expected_input_path not in cleaned_content:
        raise RepositoryError(
            "llm_result.cleaned_content must include the requested source input path"
        )
    for key in ("authors", "tags"):
        if key in result and not _is_string_list(result[key]):
            raise RepositoryError(f"llm_result.{key} must be a list of strings; use [] when empty")
    return result


def _plan_source_records(
    repository: ObjectRepository,
    source_inputs: list[SourceInput],
    parsed_sources: list[dict[str, Any]],
    title: str | None,
    tags: list[str] | None,
    authors: list[str] | None,
) -> list[dict[str, Any]]:
    today = _today()
    reserved: set[str] = set()
    records: list[dict[str, Any]] = []
    for source_input, parsed in zip(source_inputs, parsed_sources, strict=True):
        source_id = _next_id(repository, "source", reserved)
        reserved.add(source_id)
        cleaned_relative = f"data/cleaned/{source_id}.md"
        source_relative = (
            f"data/raw/pdf/{source_id}.pdf"
            if source_input.source_kind == "pdf"
            else f"data/raw/md/{source_id}.md"
        )
        metadata = {
            "id": source_id,
            "type": "source",
            "title": title or parsed.get("title") or source_input.title_hint,
            "source_type": source_input.source_kind,
            "status": "raw",
            "path": source_relative,
            "summary": parsed["summary"],
            "cleaned": {
                "path": cleaned_relative,
                "generated_at": today,
                "method": "llm",
                "input_path": source_input.relative_path,
            },
            "authors": authors or parsed.get("authors", []),
            "published_at": parsed.get("published_at"),
            "imported_at": today,
            "deprecated_at": None,
            "deprecated_reason": None,
            "tags": tags or parsed.get("tags", []),
            "created": today,
            "updated": today,
        }
        records.append(
            {
                "source_id": source_id,
                "source_input": source_input,
                "source_relative": source_relative,
                "cleaned_relative": cleaned_relative,
                "metadata": metadata,
                "parsed": parsed,
            }
        )
    return records


def _write_source_records_atomic(
    workspace: Workspace,
    repository: ObjectRepository,
    records: list[dict[str, Any]],
) -> None:
    created: list[Path] = []
    try:
        for record in records:
            source_input = record["source_input"]
            metadata = record["metadata"]
            cleaned_path = workspace.ensure_parent(record["cleaned_relative"])
            _write_new_text_atomic(cleaned_path, record["parsed"]["cleaned_content"])
            created.append(cleaned_path)

            if source_input.source_kind == "markdown":
                original = source_input.path.read_text(encoding="utf-8")
                path = repository.write_markdown(
                    record["source_relative"],
                    MarkdownDocument(frontmatter=metadata, body=f"\n## Source\n\n{original}"),
                )
                created.append(path)
            else:
                target = workspace.ensure_parent(record["source_relative"])
                _copy_new_file_atomic(source_input.path, target)
                created.append(target)
                repository.write_meta(record["source_relative"], metadata)
                created.append(target.with_suffix(".meta.yml"))
    except Exception:
        _rollback_created(created)
        raise


def _validate_source_refs(
    repository: ObjectRepository,
    source_ids: list[str],
) -> list[ObjectRecord]:
    if not source_ids:
        raise RepositoryError(
            "candidate must reference at least one source; pass source_ids with existing "
            "source object IDs"
        )

    records: list[ObjectRecord] = []
    for source_id in source_ids:
        record = _find_single_object(repository, source_id, expected_type="source")
        if record.status not in {"raw", "deprecated"}:
            raise RepositoryError(
                f"source has unsupported status: {source_id}; candidate sources must be "
                "raw or deprecated"
            )
        records.append(record)
    return records


def _deprecated_source_warnings(records: list[ObjectRecord]) -> list[str]:
    return [
        f"source {record.object_id} is deprecated; user review should confirm reuse."
        for record in records
        if record.object_type == "source" and record.status == "deprecated"
    ]


def _source_deprecation_impacts(
    repository: ObjectRepository,
    source_id: str,
) -> list[dict[str, str]]:
    impacts: list[dict[str, str]] = []
    for record in _all_records(repository):
        if record.object_id == source_id:
            continue
        fields: list[str] = []
        for evidence in record.metadata.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            evidence_id = (
                evidence.get("source_id") or evidence.get("object_id") or evidence.get("id")
            )
            if evidence_id == source_id:
                fields.append("evidence")
                break
        if fields:
            impacts.append(
                {
                    "object_id": record.object_id,
                    "object_type": record.object_type,
                    "status": record.status,
                    "fields": ", ".join(fields),
                }
            )
    return impacts


def _write_source_metadata(
    repository: ObjectRepository,
    workspace: Workspace,
    record: ObjectRecord,
    metadata: dict[str, Any],
) -> None:
    relative_path = str(workspace.relative(record.path))
    if record.path.name.endswith(".meta.yml"):
        resource_path = _resource_for_meta_path(record.path)
        repository.write_meta(workspace.relative(resource_path), metadata, overwrite=True)
        return
    document = repository.read_markdown(relative_path)
    repository.write_markdown(
        relative_path,
        MarkdownDocument(frontmatter=metadata, body=document.body),
        overwrite=True,
    )


def _resource_for_meta_path(meta_path: Path) -> Path:
    if meta_path.parent.name == "pdf":
        return meta_path.with_name(meta_path.name.removesuffix(".meta.yml") + ".pdf")
    return meta_path.with_name(meta_path.name.removesuffix(".meta.yml"))


def _validate_candidate_llm_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        raise RepositoryError(
            "llm_result must be a mapping like {'candidates': [candidate_draft, ...]}"
        )
    drafts = result.get("candidates")
    if not isinstance(drafts, list) or not drafts:
        raise RepositoryError("llm_result.candidates must be a non-empty list of candidate drafts")
    for draft in drafts:
        if not isinstance(draft, dict):
            raise RepositoryError(
                "each candidate draft must be a mapping with title, summary, content, evidence, "
                "bindto, and outline_change_suggestions"
            )
        if not isinstance(draft.get("title"), str) or not draft["title"].strip():
            raise RepositoryError("candidate title must be a non-empty string")
        if not isinstance(draft.get("summary"), str) or not draft["summary"].strip():
            raise RepositoryError("candidate summary must be a non-empty string")
        if not isinstance(draft.get("content"), str) or not draft["content"].strip():
            raise RepositoryError("candidate content must be a non-empty string")
        if draft.get("status") in {"accepted", "knowledge"} or draft.get("type") == "knowledge":
            raise RepositoryError(
                "LLM result must not create accepted knowledge; create type candidate with "
                "status omitted or pending"
            )
        evidence = draft.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise RepositoryError(f"candidate evidence must be a non-empty list; {EVIDENCE_SHAPE}")
        for key in ("source_refs",):
            if key in draft and not _is_string_list(draft[key]):
                raise RepositoryError(
                    f"candidate {key} must be a list of strings; use [] when empty"
                )
        for key in ("bindto", "outline_change_suggestions"):
            if key in draft and not _is_mapping_list(draft[key]):
                raise RepositoryError(f"candidate {key} must be a list of mappings")
        for key in ("llm_notes",):
            if key in draft and not isinstance(draft[key], str):
                raise RepositoryError(f"candidate {key} must be a string; omit if absent")
    return drafts


def _plan_candidate_records(
    repository: ObjectRepository,
    drafts: list[dict[str, Any]],
    source_ids: list[str],
) -> list[dict[str, Any]]:
    today = _today()
    used_ids = set(_id_paths(repository))
    planned_ids: set[str] = set()
    records: list[dict[str, Any]] = []

    for draft in drafts:
        candidate_id = draft.get("id") or _next_id(repository, "knowledge", planned_ids)
        if (
            not isinstance(candidate_id, str)
            or not ID_RE.match(candidate_id)
            or not candidate_id.startswith("knowledge-")
        ):
            raise RepositoryError(
                f"invalid candidate ID: {candidate_id}; expected knowledge-YYYYMMDD-001 "
                "or omit id so the API can assign one"
            )
        if candidate_id in used_ids or candidate_id in planned_ids:
            raise RepositoryError(f"candidate ID already exists: {candidate_id}")
        planned_ids.add(candidate_id)

        draft_source_ids = draft.get("source_refs", source_ids)
        if not draft_source_ids:
            raise RepositoryError(
                "candidate must reference at least one source; source_refs must include "
                "the requested upstream IDs"
            )
        if not _is_string_list(draft_source_ids):
            raise RepositoryError("candidate source_refs must be a string list")
        _validate_preserved_refs(source_ids, draft_source_ids, "source_refs")
        _validate_source_refs(repository, draft_source_ids)
        _validate_evidence(repository, draft["evidence"], draft_source_ids)
        bindto = draft.get("bindto", [])
        _validate_bindto(repository, bindto)
        outline_change_suggestions = draft.get("outline_change_suggestions", [])
        _validate_outline_change_suggestions(repository, outline_change_suggestions)

        frontmatter = {
            "id": candidate_id,
            "type": "candidate",
            "title": draft["title"],
            "status": "pending",
            "bindto": bindto,
            "outline_change_suggestions": outline_change_suggestions,
            "summary": draft["summary"],
            "evidence": draft["evidence"],
            "review": {
                "reviewed_at": None,
                "decision": None,
                "reason": None,
            },
            "created": today,
            "updated": today,
        }
        records.append(
            {
                "id": candidate_id,
                "frontmatter": frontmatter,
                "body": (
                    "\n## Content\n\n"
                    f"{draft['content'].strip()}\n\n"
                    "## Supporting Material\n\n"
                    "## LLM Notes\n\n"
                    f"{draft.get('llm_notes', '').strip()}\n"
                ),
            }
        )
    return records


def _write_candidate_records_atomic(
    repository: ObjectRepository,
    records: list[dict[str, Any]],
) -> None:
    created: list[Path] = []
    try:
        for record in records:
            path = repository.write_markdown(
                f"candidates/pending/{record['id']}.md",
                MarkdownDocument(frontmatter=record["frontmatter"], body=record["body"]),
            )
            created.append(path)
    except Exception:
        _rollback_created(created)
        raise


def _candidate_create_response_extra(records: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        {
            "id": record["id"],
            "bindto": list(record["frontmatter"].get("bindto", [])),
            "outline_change_suggestions": list(
                record["frontmatter"].get("outline_change_suggestions", [])
            ),
        }
        for record in records
    ]
    return {
        "candidate_ids": [candidate["id"] for candidate in candidates],
        "bindto": [binding for candidate in candidates for binding in candidate["bindto"]],
        "outline_change_suggestions": [
            suggestion
            for candidate in candidates
            for suggestion in candidate["outline_change_suggestions"]
        ],
        "candidates": candidates,
    }


def _validate_preserved_refs(
    required_refs: list[str],
    draft_refs: list[str],
    field_name: str,
) -> None:
    missing = sorted(set(required_refs) - set(draft_refs))
    if missing:
        raise RepositoryError(
            f"candidate {field_name} must preserve requested refs: {', '.join(missing)}; "
            "include every requested upstream ID in the draft"
        )


def _validate_evidence(
    repository: ObjectRepository,
    evidence: list[Any],
    source_ids: list[str],
) -> None:
    upstream = set(source_ids)
    for item in evidence:
        if not isinstance(item, dict):
            raise RepositoryError(EVIDENCE_SHAPE)
        source_id = item.get("source_id") or item.get("object_id") or item.get("id")
        locator = item.get("locator")
        if not isinstance(source_id, str) or source_id not in upstream:
            raise RepositoryError(
                f"evidence references missing upstream object: {source_id}; evidence must "
                f"reference one of requested upstream IDs: {sorted(upstream)}"
            )
        if not isinstance(locator, str) or not locator.strip():
            raise RepositoryError(
                "evidence locator must be a non-empty string such as a page, section, "
                "heading, or line range"
            )
        if not _has_evidence_snippet(item):
            raise RepositoryError(
                "evidence must include a non-empty quote, excerpt, or snippet field"
            )
        _find_single_object(repository, source_id)


def _validate_evidence_references_sources(
    repository: ObjectRepository,
    evidence: list[dict[str, Any]],
) -> list[str]:
    source_ids = _source_ids_from_evidence(evidence)
    if not source_ids:
        raise RepositoryError("evidence must reference at least one source")
    for source_id in source_ids:
        record = _find_single_object(repository, source_id)
        if record.object_type != "source":
            raise RepositoryError(
                f"evidence must reference source objects only; {source_id} is {record.object_type}"
            )
    return source_ids


def _validate_bindto(
    repository: ObjectRepository,
    bindto: list[dict[str, Any]],
) -> None:
    for item in bindto:
        if not isinstance(item, dict):
            raise RepositoryError(BINDTO_SHAPE)
        kb_id = item.get("kb_id")
        outline_id = item.get("outline_id")
        node_id = item.get("node_id")
        reason = item.get("reason")
        if "outline_node" in item:
            raise RepositoryError(f"{BINDTO_SHAPE}; outline_node is deprecated, use node_id")
        if not isinstance(kb_id, str) or not kb_id.strip():
            raise RepositoryError(f"{BINDTO_SHAPE}; kb_id is required")
        if not isinstance(outline_id, str) or not outline_id.strip():
            raise RepositoryError(f"{BINDTO_SHAPE}; outline_id is required")
        if not isinstance(node_id, str) or not node_id.strip():
            raise RepositoryError(f"{BINDTO_SHAPE}; node_id is required")
        if not isinstance(reason, str) or not reason.strip():
            raise RepositoryError(f"{BINDTO_SHAPE}; reason is required")
        record = _find_single_object(repository, kb_id)
        if record.object_type != "knowledge-base" or record.status != "active":
            raise RepositoryError(f"bindto.kb_id must reference an active knowledge-base: {kb_id}")
        outlines_document = _read_outlines_file(repository.workspace, record)
        outline = _outline_by_id(outlines_document, outline_id)
        if outline.get("status") != "active":
            raise RepositoryError(
                f"bindto.outline_id must reference an active outline: {outline_id}"
            )
        if node_id not in _outline_node_ids(outline.get("nodes", [])):
            raise RepositoryError(
                f"bindto.node_id does not exist in {kb_id}/{outline_id}: {node_id}"
            )


def _candidate_reference_summaries(
    repository: ObjectRepository,
    frontmatter: dict[str, Any],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    evidence_source_ids = _source_ids_from_evidence(frontmatter.get("evidence", []))
    for object_id in evidence_source_ids:
        references.append(_summary_for_record(_find_single_object(repository, object_id)))
    return references


def _summary_for_record(record: ObjectRecord) -> dict[str, Any]:
    return {
        "id": record.object_id,
        "type": record.object_type,
        "status": record.status,
        "title": record.metadata.get("title"),
        "summary": record.metadata.get("summary"),
    }


def _find_single_object(
    repository: ObjectRepository,
    object_id: str,
    *,
    expected_type: str | None = None,
) -> ObjectRecord:
    matches = [record for record in _all_records(repository) if record.object_id == object_id]
    if not matches:
        raise RepositoryError(f"object not found: {object_id}")
    if len(matches) > 1:
        raise RepositoryError(f"duplicate object ID: {object_id}")
    record = matches[0]
    if expected_type is not None and record.object_type != expected_type:
        raise RepositoryError(
            f"object {object_id} is {record.object_type}, expected {expected_type}"
        )
    return record


def _all_records(repository: ObjectRepository) -> list[ObjectRecord]:
    return [
        ObjectRecord(
            object_id=record.object_id,
            object_type=record.object_type,
            status=str(record.metadata.get("status", "")),
            path=record.path,
            metadata=record.metadata,
        )
        for record in repository.iter_object_metadata()
    ]


def _next_id(repository: ObjectRepository, prefix: str, reserved: set[str] | None = None) -> str:
    reserved = reserved or set()
    existing = set(_id_paths(repository)) | reserved
    existing_stems = _id_numeric_stems(existing)
    day = date.today().strftime("%Y%m%d")
    for index in range(1, 1000):
        candidate = f"{prefix}-{day}-{index:03d}"
        if candidate not in existing and candidate not in existing_stems:
            return candidate
    raise RepositoryError(f"no available {prefix} IDs for {day}")


def _next_titled_id(
    repository: ObjectRepository,
    prefix: str,
    title: str,
    reserved: set[str] | None = None,
) -> str:
    slug = _title_slug(title)
    if not slug:
        return _next_id(repository, prefix, reserved)
    reserved = reserved or set()
    existing = set(_id_paths(repository)) | reserved
    existing_stems = _id_numeric_stems(existing)
    day = date.today().strftime("%Y%m%d")
    for index in range(1, 1000):
        stem = f"{prefix}-{day}-{index:03d}"
        candidate = f"{stem}-{slug}"
        if candidate not in existing and stem not in existing_stems:
            return candidate
    raise RepositoryError(f"no available {prefix} IDs for {day}")


def _id_numeric_stems(ids: set[str]) -> set[str]:
    return {"-".join(object_id.split("-")[:3]) for object_id in ids if ID_RE.match(object_id)}


def _title_slug(title: str, max_length: int = 48) -> str:
    parts: list[str] = []
    previous_was_separator = True
    for char in title.strip().casefold():
        if char.isalnum():
            parts.append(char)
            previous_was_separator = False
        elif not previous_was_separator:
            parts.append("-")
            previous_was_separator = True
        if len(parts) >= max_length:
            break
    return "".join(parts).strip("-")


def _id_paths(repository: ObjectRepository) -> dict[str, list[Path]]:
    return repository.scan_object_ids()


def _today() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_mapping_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _summarize_text(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _parent_directory_conflict(
    workspace: Workspace,
    path: Path,
    relative_path: str,
) -> str | None:
    current = path.parent
    while current != workspace.root:
        if current.exists() and not current.is_dir():
            return f"{relative_path}: parent path is not a directory: {workspace.relative(current)}"
        current = current.parent
    return None


def _has_evidence_snippet(item: dict[str, Any]) -> bool:
    for key in ("quote", "excerpt", "snippet"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _ensure_writable_root(root: Path) -> None:
    if root.exists():
        if not root.is_dir():
            raise WorkspacePathError(f"workspace root is not a directory: {root}")
        if not os_access(root):
            raise WorkspacePathError(f"workspace root is not writable: {root}")
        return

    parent = root.parent
    if not parent.exists() or not parent.is_dir() or not os_access(parent):
        raise WorkspacePathError(f"workspace parent is not writable: {parent}")


def os_access(path: Path) -> bool:
    return os.access(path, os.W_OK)


def _create_directory(path: Path, root: Path, created_paths: list[Path]) -> None:
    missing: list[Path] = []
    current = path
    while current != root and not current.exists():
        missing.append(current)
        current = current.parent

    path.mkdir(parents=True, exist_ok=False)
    created_paths.extend(reversed(missing))


def _write_new_text_atomic(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"target already exists: {path}")

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _copy_new_file_atomic(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"target already exists: {target}")

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            while True:
                chunk = input_file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.link(tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)


def _plan_diffs(plan: InitPlan) -> list[dict[str, str]]:
    diffs: list[dict[str, str]] = []
    for path in plan.create_directories:
        diffs.append({"action": "create", "kind": "directory", "path": path})
    for path in plan.create_files:
        diffs.append({"action": "create", "kind": "file", "path": path})
    for path in plan.existing:
        diffs.append({"action": "keep", "kind": "path", "path": path})
    for conflict in plan.conflicts:
        diffs.append({"action": "conflict", "kind": "path", "path": conflict})
    return diffs


def _rollback_created(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        except OSError:
            pass
