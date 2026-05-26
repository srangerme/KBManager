"""Application API entry points."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import os
import re
import time
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

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
KNOWLEDGEBASE_MAP_OPERATION = "kb.knowledgebase.map"
NOTE_ADD_OPERATION = "kb.note.add"
NOTE_GET_OPERATION = "kb.note.get"
NOTE_DEPRECATE_OPERATION = "kb.note.deprecate"
INDEX_REBUILD_OPERATION = "kb.index.rebuild"
CLEAN_INSPECT_OPERATION = "kb.clean.inspect"
RELATION_TYPES = frozenset({"agrees", "conflicts", "related_to", "child_of"})
HIERARCHY_RELATION_TYPE = "child_of"
RELATION_TYPE_LIST = ", ".join(sorted(RELATION_TYPES))

INIT_DIRECTORIES = (
    ".lark/logs",
    "data/raw/md",
    "data/raw/pdf",
    "data/raw/html",
    "data/cleaned",
    "data/attachments",
    "data/attachments/url-captures",
    "data/failed",
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
  - relation-index.yml
  - kb-index.md
  - note-index.md
  - review-queue.md
""",
    "indexes/source-index.md": "# Source Index\n\n",
    "indexes/knowledge-index.md": "# Knowledge Index\n\n",
    "indexes/tag-index.md": "# Tag Index\n\n",
    "indexes/relation-index.yml": "relations: []\n",
    "indexes/kb-index.md": "# Knowledge Base Index\n\n",
    "indexes/note-index.md": "# Note Index\n\n",
    "indexes/review-queue.md": "# Review Queue\n\n",
}
INIT_DIRECTORY_PLACEHOLDER_FILES = {
    f"{directory}/{INIT_DIRECTORY_PLACEHOLDER}": ""
    for directory in _all_init_directories()
    if not directory.startswith(".lark")
}
LARK_SETTINGS_EXAMPLE = """{
  "app_id": "cli_xxxxxxxxxxxxxxxx",
  "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "remote": "origin",
  "branch": "main",
  "ack_only": true
}
"""
INIT_LARK_FILES = {
    ".lark/settings.json.example": LARK_SETTINGS_EXAMPLE,
}
INIT_FILES = {**INIT_INDEX_FILES, **INIT_DIRECTORY_PLACEHOLDER_FILES, **INIT_LARK_FILES}


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
    path: Path | None
    relative_path: str
    source_kind: str
    title_hint: str
    content: str | None = None
    original_url: str | None = None


@dataclass(frozen=True)
class KnowledgebaseMembershipUpdate:
    relative_path: str
    original: MarkdownDocument
    updated: MarkdownDocument


SUPPORTED_SOURCE_SUFFIXES = {".md", ".pdf"}
SUPPORTED_SOURCE_URL_SCHEMES = {"http", "https"}
MAX_URL_DOWNLOAD_BYTES = 5 * 1024 * 1024
ID_RE = re.compile(r"^[a-z]+-\d{8}-\d{3}(?:-[^\W_]+(?:-[^\W_]+)*)?$")
INDEX_SCOPES = {
    "all",
    "source",
    "candidate",
    "knowledge",
    "knowledgebase",
    "note",
    "relation",
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
INDEX_YAML_PATHS = ("indexes/relation-index.yml",)
CANDIDATE_RELATION_SHAPE = (
    "candidate relations must be [] when there are no relations, or mappings like "
    "{'type': 'related_to', 'target': 'knowledge-YYYYMMDD-001'} where type is one of "
    f"{RELATION_TYPE_LIST} and target is an existing accepted knowledge ID"
)
REVIEW_RELATION_SHAPE = (
    "reviewed relations must be [] when there are no relations, or mappings like "
    "{'type': 'related_to', 'target': 'knowledge-YYYYMMDD-001'} where type is one of "
    f"{RELATION_TYPE_LIST} and target is an existing knowledge ID"
)
EVIDENCE_SHAPE = (
    "evidence items must be mappings like {'source_id': '<requested-source-or-note-id>', "
    "'locator': '<section/page/line>', 'quote': '<verbatim support>'}; object_id or id may "
    "be used instead of source_id"
)


def init_workspace(root: str | Path = ".", *, dry_run: bool = False) -> ApiResult:
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

    if dry_run:
        return ApiResult.success(
            INIT_OPERATION,
            objects=ObjectChanges(created=plan.create_directories + plan.create_files),
            diffs=_plan_diffs(plan),
            warnings=[],
            next_actions=["Run kb.init without dry_run to create the workspace files."],
        )

    created_paths: list[Path] = []
    try:
        for directory in plan.create_directories:
            path = workspace.resolve(directory)
            _create_directory(path, workspace.root, created_paths)

        for relative_path in plan.create_files:
            path = workspace.resolve(relative_path)
            _write_new_text_atomic(path, INIT_FILES[relative_path])
            if relative_path == "run_lark_server.py":
                path.chmod(0o755)
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
    dry_run: bool = False,
) -> ApiResult:
    """Add a local Markdown/PDF source through the source-ingest LLM boundary."""

    input_text = str(input_path)
    try:
        workspace = Workspace(root)
        _validate_source_add_input(title=title, tags=tags, authors=authors)
        source_inputs = _source_inputs(workspace, input_path)
        input_ref = (
            str(input_path)
            if _is_supported_source_url(input_text)
            else str(Path(input_path))
        )
        token_payload = {
            "input_path": input_ref,
            "inputs": [source.relative_path for source in source_inputs],
            "title": title,
            "tags": tags or [],
            "authors": authors or [],
        }
    except (KBManagerError, OSError) as exc:
        suggestion, next_actions = _source_add_input_failure_recovery(input_text)
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
        if dry_run:
            return ApiResult.success(
                SOURCE_ADD_OPERATION,
                objects=ObjectChanges(created=created),
                diffs=diffs,
            )
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
    reviewed_by: str | None = None,
    reason: str | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Mark a source as deprecated after user review."""

    if not _has_review_decision(decision, reviewed_by, "deprecate"):
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
                "reviewed_by": reviewed_by,
                "reviewed_at": today,
                "review_decision": "deprecate",
                "updated": today,
            }
        )
        relative_path = str(workspace.relative(record.path))
        impacts = _source_deprecation_impacts(repository, source_id)
        diffs = [{"action": "update", "kind": "source", "path": relative_path}]
        if dry_run:
            return ApiResult.success(
                SOURCE_DEPRECATE_OPERATION,
                objects=ObjectChanges(deprecated=[relative_path]),
                diffs=diffs,
                extra={
                    "source_id": source_id,
                    "impacts": impacts,
                },
            )
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
    note_ids: list[str] | None = None,
    resume_token: str | None = None,
    llm_result: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Create pending candidates through the candidate-create LLM boundary."""

    source_ids = source_ids or []
    note_ids = note_ids or []
    token_payload = {"source_ids": source_ids, "note_ids": note_ids}

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        upstream = _validate_upstream_refs(repository, source_ids, note_ids)
        warnings = _deprecated_source_warnings(upstream)
    except (KBManagerError, OSError) as exc:
        return _failed(
            CANDIDATE_CREATE_OPERATION,
            "invalid_reference",
            str(exc),
            "Provide at least one existing source or note reference.",
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
            ],
            token_payload=token_payload,
            warnings=warnings,
        )

    if resume_token != _resume_token(CANDIDATE_CREATE_OPERATION, token_payload):
        return _failed(
            CANDIDATE_CREATE_OPERATION,
            "invalid_resume_token",
            "Resume token does not match this candidate.create request.",
            "Restart kb.candidate.create and use the returned resume token.",
        )

    try:
        drafts = _validate_candidate_llm_result(llm_result)
        records = _plan_candidate_records(repository, drafts, source_ids, note_ids)
        created = [f"candidates/pending/{record['id']}.md" for record in records]
        diffs = [{"action": "create", "kind": "candidate", "path": path} for path in created]
        if dry_run:
            return ApiResult.success(
                CANDIDATE_CREATE_OPERATION,
                objects=ObjectChanges(created=created),
                diffs=diffs,
                warnings=warnings,
                extra=_candidate_create_response_extra(records),
            )
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


def candidate_get(root: str | Path = ".", *, candidate_id: str) -> ApiResult:
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


def candidate_next_pending(root: str | Path = ".") -> ApiResult:
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

    result = candidate_get(workspace.root, candidate_id=pending[0].object_id).to_dict()
    return ApiResult.success(
        CANDIDATE_NEXT_PENDING_OPERATION,
        extra={"candidate": result["candidate"]},
    )


def knowledge_accept(
    root: str | Path = ".",
    *,
    candidate_id: str,
    decision: str | None = None,
    reviewed_by: str | None = None,
    reason: str | None = None,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
    kb_ids: list[str] | None = None,
    relations: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Promote a pending candidate to accepted knowledge after user review."""

    if not _has_review_decision(decision, reviewed_by, "accept"):
        return _needs_review(KNOWLEDGE_ACCEPT_OPERATION, ["accept", "reject", "defer", "merge"])

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        record = _pending_candidate_record(repository, workspace, candidate_id)
        document = repository.read_markdown(workspace.relative(record.path))
        _validate_required_accept_content(
            title=title,
            body=body,
            tags=tags,
            kb_ids=kb_ids,
            relations=relations,
        )
        _validate_knowledge_review_refs(
            repository,
            kb_ids or [],
            relations or [],
            self_knowledge_id=candidate_id,
        )
        today = _today()
        accepted_frontmatter = {
            "id": candidate_id,
            "type": "knowledge",
            "title": title or document.frontmatter["title"],
            "status": "accepted",
            "tags": tags if tags is not None else document.frontmatter.get("suggested_tags", []),
            "source_refs": document.frontmatter.get("source_refs", []),
            "note_refs": document.frontmatter.get("note_refs", []),
            "evidence": document.frontmatter.get("evidence", []),
            "kb_ids": (
                kb_ids if kb_ids is not None else document.frontmatter.get("suggested_kb_ids", [])
            ),
            "relations": (
                relations if relations is not None else document.frontmatter.get("relations", [])
            ),
            "reviewed_by": reviewed_by,
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
        accepted_body = _knowledge_body(body, document.body)
        membership_updates = _plan_knowledgebase_membership_updates(
            repository,
            workspace,
            knowledge_id=candidate_id,
            old_kb_ids=[],
            new_kb_ids=accepted_frontmatter["kb_ids"],
        )
        diffs = [
            {"action": "create", "kind": "knowledge", "path": knowledge_path},
            {
                "action": "remove",
                "kind": "candidate",
                "path": str(workspace.relative(record.path)),
            },
            *[
                {"action": "update", "kind": "knowledge-base", "path": update.relative_path}
                for update in membership_updates
            ],
        ]
        if dry_run:
            return ApiResult.success(
                KNOWLEDGE_ACCEPT_OPERATION,
                objects=ObjectChanges(
                    created=[knowledge_path],
                    updated=[update.relative_path for update in membership_updates],
                ),
                diffs=diffs,
                extra={"knowledge_id": candidate_id, "kb_ids": accepted_frontmatter["kb_ids"]},
            )
        _promote_candidate_to_knowledge(
            repository,
            record.path,
            knowledge_path,
            MarkdownDocument(frontmatter=accepted_frontmatter, body=accepted_body),
            membership_updates,
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
            updated=[update.relative_path for update in membership_updates],
        ),
        diffs=diffs,
        extra={"knowledge_id": candidate_id, "kb_ids": accepted_frontmatter["kb_ids"]},
    )


def knowledge_reject(
    root: str | Path = ".",
    *,
    candidate_id: str,
    decision: str | None = None,
    reviewed_by: str | None = None,
    reason: str | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Reject a candidate after user review."""

    if not _has_review_decision(decision, reviewed_by, "reject"):
        return _needs_review(KNOWLEDGE_REJECT_OPERATION, ["reject", "revise"])
    return _move_reviewed_candidate(
        root,
        operation=KNOWLEDGE_REJECT_OPERATION,
        candidate_id=candidate_id,
        target_status="rejected",
        decision="reject",
        reviewed_by=reviewed_by,
        reason=reason,
        dry_run=dry_run,
    )


def candidate_defer(
    root: str | Path = ".",
    *,
    candidate_id: str,
    decision: str | None = None,
    reviewed_by: str | None = None,
    reason: str | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Defer a pending candidate after user review."""

    if not _has_review_decision(decision, reviewed_by, "defer"):
        return _needs_review(CANDIDATE_DEFER_OPERATION, ["defer", "accept", "reject"])
    return _move_reviewed_candidate(
        root,
        operation=CANDIDATE_DEFER_OPERATION,
        candidate_id=candidate_id,
        target_status="deferred",
        decision="defer",
        reviewed_by=reviewed_by,
        reason=reason,
        dry_run=dry_run,
    )


def knowledge_merge(
    root: str | Path = ".",
    *,
    candidate_id: str,
    target_knowledge_id: str,
    decision: str | None = None,
    reviewed_by: str | None = None,
    reason: str | None = None,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
    kb_ids: list[str] | None = None,
    relations: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Merge a reviewed candidate into an existing knowledge object."""

    if not _has_review_decision(decision, reviewed_by, "merge"):
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
            body=body,
            tags=tags,
            kb_ids=kb_ids,
            relations=relations,
        )
        _validate_knowledge_review_refs(
            repository,
            kb_ids or [],
            relations or [],
            self_knowledge_id=target_knowledge_id,
        )
        candidate_document = repository.read_markdown(workspace.relative(candidate_record.path))
        knowledge_document = repository.read_markdown(workspace.relative(knowledge_record.path))
        today = _today()
        merged_frontmatter = dict(knowledge_document.frontmatter)
        merged_frontmatter.update(
            {
                "title": title or knowledge_document.frontmatter["title"],
                "tags": tags
                if tags is not None
                else _merged_strings(
                    knowledge_document.frontmatter.get("tags", []),
                    candidate_document.frontmatter.get("suggested_tags", []),
                ),
                "source_refs": _merged_strings(
                    knowledge_document.frontmatter.get("source_refs", []),
                    candidate_document.frontmatter.get("source_refs", []),
                ),
                "note_refs": _merged_strings(
                    knowledge_document.frontmatter.get("note_refs", []),
                    candidate_document.frontmatter.get("note_refs", []),
                ),
                "evidence": knowledge_document.frontmatter.get("evidence", [])
                + candidate_document.frontmatter.get("evidence", []),
                "kb_ids": kb_ids
                if kb_ids is not None
                else _merged_strings(
                    knowledge_document.frontmatter.get("kb_ids", []),
                    candidate_document.frontmatter.get("suggested_kb_ids", []),
                ),
                "relations": relations
                if relations is not None
                else knowledge_document.frontmatter.get("relations", [])
                + candidate_document.frontmatter.get("relations", []),
                "reviewed_by": reviewed_by,
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
            reviewed_by=reviewed_by,
            reason=reason,
        )
        knowledge_relative = str(workspace.relative(knowledge_record.path))
        rejected_relative = f"candidates/rejected/{candidate_id}.md"
        membership_updates = _plan_knowledgebase_membership_updates(
            repository,
            workspace,
            knowledge_id=target_knowledge_id,
            old_kb_ids=knowledge_document.frontmatter.get("kb_ids", []),
            new_kb_ids=merged_frontmatter["kb_ids"],
        )
        diffs = [
            {"action": "update", "kind": "knowledge", "path": knowledge_relative},
            {"action": "move", "kind": "candidate", "path": rejected_relative},
            *[
                {"action": "update", "kind": "knowledge-base", "path": update.relative_path}
                for update in membership_updates
            ],
        ]
        if dry_run:
            return ApiResult.success(
                KNOWLEDGE_MERGE_OPERATION,
                objects=ObjectChanges(
                    updated=[
                        knowledge_relative,
                        rejected_relative,
                        *[update.relative_path for update in membership_updates],
                    ]
                ),
                diffs=diffs,
                extra={
                    "knowledge_id": target_knowledge_id,
                    "rejected_candidate_id": candidate_id,
                    "kb_ids": merged_frontmatter["kb_ids"],
                },
            )
        _merge_candidate_into_knowledge(
            repository,
            workspace,
            candidate_record.path,
            rejected_relative,
            rejected_candidate,
            knowledge_relative,
            MarkdownDocument(
                frontmatter=merged_frontmatter,
                body=_knowledge_body(body, knowledge_document.body),
            ),
            knowledge_document,
            membership_updates,
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
                *[update.relative_path for update in membership_updates],
            ]
        ),
        diffs=diffs,
        extra={
            "knowledge_id": target_knowledge_id,
            "rejected_candidate_id": candidate_id,
            "kb_ids": merged_frontmatter["kb_ids"],
        },
    )


def knowledge_deprecate(
    root: str | Path = ".",
    *,
    knowledge_id: str,
    decision: str | None = None,
    reviewed_by: str | None = None,
    reason: str | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Mark accepted knowledge as deprecated after user review."""

    if not _has_review_decision(decision, reviewed_by, "deprecate"):
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
                "reviewed_by": reviewed_by,
                "reviewed_at": today,
                "review_decision": "deprecate",
                "updated": today,
            }
        )
        relative_path = str(workspace.relative(record.path))
        diffs = [{"action": "update", "kind": "knowledge", "path": relative_path}]
        if dry_run:
            return ApiResult.success(
                KNOWLEDGE_DEPRECATE_OPERATION,
                objects=ObjectChanges(deprecated=[relative_path]),
                diffs=diffs,
                extra={"knowledge_id": knowledge_id},
            )
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
    description: str,
    acceptance_criteria: str,
    tags: list[str] | None = None,
    body: str | None = None,
    knowledgebase_id: str | None = None,
    decision: str | None = None,
    reviewed_by: str | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Create a user-approved knowledge base object."""

    if not _has_review_decision(decision, reviewed_by, "approve"):
        return _needs_review(KNOWLEDGEBASE_CREATE_OPERATION, ["approve", "revise"])

    try:
        workspace = Workspace(root)
        repository = ObjectRepository(workspace)
        _validate_knowledgebase_input(
            repository,
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria,
            tags=tags,
            knowledgebase_id=knowledgebase_id,
        )
        today = _today()
        kb_id = knowledgebase_id or _next_titled_id(repository, "kb", title)
        relative_path = f"knowledge/bases/{kb_id}.md"
        if workspace.resolve(relative_path).exists():
            raise RepositoryError(f"knowledge base path already exists: {relative_path}")
        frontmatter = {
            "id": kb_id,
            "type": "knowledge-base",
            "title": title.strip(),
            "status": "active",
            "description": description.strip(),
            "acceptance_criteria": acceptance_criteria.strip(),
            "knowledge_ids": [],
            "tags": tags or [],
            "reviewed_by": reviewed_by,
            "reviewed_at": today,
            "review_decision": "approve",
            "created": today,
            "updated": today,
        }
        document = MarkdownDocument(
            frontmatter=frontmatter,
            body=_knowledgebase_body(description, acceptance_criteria, body),
        )
        diffs = [{"action": "create", "kind": "knowledge-base", "path": relative_path}]
        if dry_run:
            return ApiResult.success(
                KNOWLEDGEBASE_CREATE_OPERATION,
                objects=ObjectChanges(created=[relative_path]),
                diffs=diffs,
                extra={"knowledgebase_id": kb_id, "path": relative_path},
            )
        repository.write_markdown(relative_path, document)
    except (KBManagerError, OSError) as exc:
        return _failed(
            KNOWLEDGEBASE_CREATE_OPERATION,
            "knowledgebase_create_failed",
            str(exc),
            "Provide a unique reviewed knowledge base title and optional ID.",
        )

    return _success_with_index_rebuild(
        workspace.root,
        KNOWLEDGEBASE_CREATE_OPERATION,
        objects=ObjectChanges(created=[relative_path]),
        diffs=diffs,
        extra={"knowledgebase_id": kb_id, "path": relative_path},
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
    dry_run: bool = False,
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
        if dry_run:
            return ApiResult.success(
                NOTE_ADD_OPERATION,
                objects=ObjectChanges(created=[relative_path]),
                diffs=diffs,
                extra=_note_response_extra(new_note_id, relative_path, document),
            )
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


def note_get(root: str | Path = ".", *, note_id: str) -> ApiResult:
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
    reviewed_by: str | None = None,
    dry_run: bool = False,
) -> ApiResult:
    """Mark a note deprecated and move it to notes/deprecated."""

    if not _has_review_decision(decision, reviewed_by, "deprecate"):
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
                "reviewed_by": reviewed_by,
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
        if dry_run:
            return ApiResult.success(
                NOTE_DEPRECATE_OPERATION,
                objects=ObjectChanges(deprecated=[deprecated_relative]),
                diffs=diffs,
                extra={"note_id": note_id, "path": deprecated_relative},
            )
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


def clean_inspect(root: str | Path = ".") -> ApiResult:
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
    dry_run: bool = False,
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
        if dry_run:
            return ApiResult.success(
                INDEX_REBUILD_OPERATION,
                objects=ObjectChanges(updated=updated),
                diffs=diffs,
                warnings=_issue_warnings(issues),
                extra={"issues": issues, "index_paths": sorted(planned_indexes)},
            )
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
        "indexes/relation-index.yml": _relation_index_yaml(knowledge, candidates),
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
    knowledge = [
        record
        for record in _records_by_type(visible_records, "knowledge")
        if record.status == "accepted"
    ]
    if knowledgebase_id is not None:
        knowledgebases = _records_by_type(visible_records, "knowledge-base")
        kb_record = next(
            (record for record in knowledgebases if record.object_id == knowledgebase_id),
            None,
        )
        if kb_record is None:
            raise RepositoryError(f"knowledgebase not found: {knowledgebase_id}")
        knowledge_ids = set(_knowledge_ids_for_base(kb_record, knowledge))
        knowledge = [record for record in knowledge if record.object_id in knowledge_ids]

    issues = _knowledge_hierarchy_issues(knowledge, workspace)
    by_id = {record.object_id: record for record in knowledge}
    children: dict[str, list[ObjectRecord]] = {record.object_id: [] for record in knowledge}
    roots: list[ObjectRecord] = []
    for record in knowledge:
        parent_id = _child_of_target(record)
        if parent_id and parent_id in by_id:
            children[parent_id].append(record)
        else:
            roots.append(record)

    for siblings in children.values():
        siblings.sort(key=_record_sort_key)
    roots.sort(key=_record_sort_key)

    title = "Knowledgebase Map"
    if knowledgebase_id is not None:
        title = f"Knowledgebase Map: {knowledgebase_id}"
    lines = [
        f"# {title}",
        "",
        "```mermaid",
        "flowchart TD",
    ]
    if not knowledge:
        lines.append('  empty["No accepted knowledge"]')
    else:
        for record in sorted(knowledge, key=_record_sort_key):
            lines.append(f"  {_mermaid_node_id(record.object_id)}[\"{_mermaid_label(record)}\"]")
        edges = _mermaid_tree_edges(roots, children)
        if edges:
            lines.append("")
            lines.extend(edges)
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
            "indexes/relation-index.yml",
        },
        "knowledge": {
            "indexes/knowledge-index.md",
            "indexes/tag-index.md",
            "indexes/relation-index.yml",
        },
        "knowledgebase": {"indexes/kb-index.md"},
        "note": {"indexes/note-index.md"},
        "relation": {"indexes/relation-index.yml"},
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
        "| ID | Title | Status | Tags | Knowledge Bases | Path |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    record.status,
                    _join_strings(record.metadata.get("tags", [])),
                    _join_strings(record.metadata.get("kb_ids", [])),
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


def _relation_index_yaml(
    knowledge: list[ObjectRecord],
    candidates: list[ObjectRecord],
) -> str:
    relations: list[dict[str, Any]] = []
    for record in knowledge + candidates:
        for relation in record.metadata.get("relations", []):
            if isinstance(relation, dict):
                item = dict(relation)
                item["source"] = record.object_id
                relations.append(item)
    return yaml.safe_dump(
        {"relations": relations},
        sort_keys=False,
        allow_unicode=True,
    )


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
        knowledge_ids = _knowledge_ids_for_base(record, knowledge)
        lines.append(
            _table_row(
                [
                    record.object_id,
                    _metadata_text(record, "title"),
                    record.status,
                    str(len(knowledge_ids)),
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
                    _join_strings(record.metadata.get("source_refs", [])),
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
    knowledge_ids = set(_knowledge_ids_for_base(kb_record, knowledge))
    lines = [
        f"# Knowledge Index: {kb_record.object_id}",
        "",
        "| ID | Title | Status | Tags | Path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in knowledge:
        if record.object_id not in knowledge_ids:
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


def _knowledge_ids_for_base(kb_record: ObjectRecord, knowledge: list[ObjectRecord]) -> list[str]:
    knowledge_ids = set(_string_items(kb_record.metadata.get("knowledge_ids", [])))
    for record in knowledge:
        if kb_record.object_id in _string_items(record.metadata.get("kb_ids", [])):
            knowledge_ids.add(record.object_id)
    return sorted(knowledge_ids)


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
    _append_knowledgebase_membership_issues(records, issues)
    _append_relation_consistency_issues(records, by_id, workspace, issues)
    return issues


def _append_reference_issues(
    record: ObjectRecord,
    by_id: dict[str, list[ObjectRecord]],
    issues: list[dict[str, str]],
) -> None:
    field_types = {
        "source_refs": "source",
        "note_refs": "note",
        "kb_ids": "knowledge-base",
        "suggested_kb_ids": "knowledge-base",
        "knowledge_ids": "knowledge",
    }
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

    for relation in record.metadata.get("relations", []):
        if isinstance(relation, dict) and isinstance(relation.get("target"), str):
            _append_missing_or_type_issue(
                record,
                "relations",
                relation["target"],
                "knowledge",
                by_id,
                issues,
            )

    for evidence in record.metadata.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        target_id = evidence.get("source_id") or evidence.get("object_id") or evidence.get("id")
        if isinstance(target_id, str):
            _append_missing_reference_issue(record, "evidence", target_id, by_id, issues)


def _append_relation_consistency_issues(
    records: list[ObjectRecord],
    by_id: dict[str, list[ObjectRecord]],
    workspace: Workspace,
    issues: list[dict[str, str]],
) -> None:
    for record in records:
        child_of_count = 0
        for relation in record.metadata.get("relations", []):
            if not isinstance(relation, dict):
                issues.append(
                    {
                        "code": "invalid_relation_shape",
                        "object_id": record.object_id,
                        "message": "relation entries must be mappings with type and target",
                        "path": str(workspace.relative(record.path)),
                    }
                )
                continue
            relation_type = relation.get("type")
            target_id = relation.get("target")
            if relation_type not in RELATION_TYPES:
                issues.append(
                    {
                        "code": "unknown_relation_type",
                        "object_id": record.object_id,
                        "message": (
                            f"unknown relation type: {relation_type}; expected one of "
                            f"{RELATION_TYPE_LIST}"
                        ),
                        "path": str(workspace.relative(record.path)),
                    }
                )
            if relation_type == HIERARCHY_RELATION_TYPE:
                child_of_count += 1
                if target_id == record.object_id:
                    issues.append(
                        {
                            "code": "child_of_self",
                            "object_id": record.object_id,
                            "field": "relations",
                            "target_id": str(target_id),
                            "message": f"{record.object_id} child_of points to itself",
                        }
                    )
                elif isinstance(target_id, str):
                    matches = by_id.get(target_id, [])
                    if not matches:
                        issues.append(
                            {
                                "code": "child_of_missing_target",
                                "object_id": record.object_id,
                                "field": "relations",
                                "target_id": target_id,
                                "message": (
                                    f"{record.object_id} child_of target is missing: "
                                    f"{target_id}"
                                ),
                            }
                        )
                    elif not any(match.object_type == "knowledge" for match in matches):
                        issues.append(
                            {
                                "code": "child_of_non_knowledge_target",
                                "object_id": record.object_id,
                                "field": "relations",
                                "target_id": target_id,
                                "message": (
                                    f"{record.object_id} child_of target must be knowledge: "
                                    f"{target_id}"
                                ),
                            }
                        )
        if child_of_count > 1:
            issues.append(
                {
                    "code": "multiple_child_of",
                    "object_id": record.object_id,
                    "field": "relations",
                    "message": f"{record.object_id} has multiple child_of relations",
                }
            )
    issues.extend(_knowledge_hierarchy_cycle_issues(records))


def _knowledge_hierarchy_issues(
    records: list[ObjectRecord],
    workspace: Workspace,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    by_id = {record.object_id: [record] for record in records}
    _append_relation_consistency_issues(records, by_id, workspace, issues)
    return issues


def _knowledge_hierarchy_cycle_issues(records: list[ObjectRecord]) -> list[dict[str, str]]:
    parent_by_child = {
        record.object_id: parent_id
        for record in records
        if record.object_type == "knowledge"
        for parent_id in [_child_of_target(record)]
        if parent_id
    }
    issues: list[dict[str, str]] = []
    reported: set[frozenset[str]] = set()
    for start in sorted(parent_by_child):
        path: list[str] = []
        seen_at: dict[str, int] = {}
        current: str | None = start
        while current in parent_by_child:
            if current in seen_at:
                cycle = path[seen_at[current] :]
                cycle_ids = frozenset(cycle)
                cycle_key = " -> ".join(cycle + [current])
                if cycle_ids not in reported:
                    reported.add(cycle_ids)
                    issues.append(
                        {
                            "code": "child_of_cycle",
                            "object_id": start,
                            "field": "relations",
                            "message": f"child_of cycle detected: {cycle_key}",
                        }
                    )
                break
            seen_at[current] = len(path)
            path.append(current)
            current = parent_by_child.get(current)
    return issues


def _child_of_target(record: ObjectRecord) -> str | None:
    for relation in record.metadata.get("relations", []):
        if not isinstance(relation, dict):
            continue
        if relation.get("type") != HIERARCHY_RELATION_TYPE:
            continue
        target_id = relation.get("target")
        if isinstance(target_id, str) and target_id.strip():
            return target_id
    return None


def _append_knowledgebase_membership_issues(
    records: list[ObjectRecord],
    issues: list[dict[str, str]],
) -> None:
    knowledge_by_id = {
        record.object_id: record for record in records if record.object_type == "knowledge"
    }
    kb_by_id = {
        record.object_id: record for record in records if record.object_type == "knowledge-base"
    }

    for kb_record in kb_by_id.values():
        kb_id = kb_record.object_id
        for knowledge_id in _string_items(kb_record.metadata.get("knowledge_ids", [])):
            knowledge_record = knowledge_by_id.get(knowledge_id)
            if knowledge_record is None:
                continue
            if kb_id not in _string_items(knowledge_record.metadata.get("kb_ids", [])):
                issues.append(
                    {
                        "code": "knowledgebase_membership_mismatch",
                        "object_id": kb_id,
                        "field": "knowledge_ids",
                        "target_id": knowledge_id,
                        "message": (
                            f"{kb_id}.knowledge_ids includes {knowledge_id}, "
                            f"but {knowledge_id}.kb_ids does not include {kb_id}"
                        ),
                    }
                )

    for knowledge_record in knowledge_by_id.values():
        knowledge_id = knowledge_record.object_id
        for kb_id in _string_items(knowledge_record.metadata.get("kb_ids", [])):
            kb_record = kb_by_id.get(kb_id)
            if kb_record is None:
                continue
            if knowledge_id not in _string_items(kb_record.metadata.get("knowledge_ids", [])):
                issues.append(
                    {
                        "code": "knowledgebase_membership_mismatch",
                        "object_id": knowledge_id,
                        "field": "kb_ids",
                        "target_id": kb_id,
                        "message": (
                            f"{knowledge_id}.kb_ids includes {kb_id}, "
                            f"but {kb_id}.knowledge_ids does not include {knowledge_id}"
                        ),
                    }
                )


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


def _table_row(values: list[str]) -> str:
    return "| " + " | ".join(_escape_table_cell(value) for value in values) + " |"


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _needs_review(operation: str, options: list[str]) -> ApiResult:
    return ApiResult(
        status=ApiStatus.NEEDS_REVIEW,
        operation=operation,
        review=ReviewRequest(required=True, options=options),
        next_actions=["Provide a user review decision before retrying this operation."],
    )


def _has_review_decision(
    decision: str | None,
    reviewed_by: str | None,
    expected: str,
) -> bool:
    return decision == expected and isinstance(reviewed_by, str) and bool(reviewed_by.strip())


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
    body: str | None,
    tags: list[str] | None,
    kb_ids: list[str] | None,
    relations: list[dict[str, Any]] | None,
) -> None:
    if title is not None and not title.strip():
        raise RepositoryError("reviewed title must be non-empty when provided; expected string")
    if body is not None and not body.strip():
        raise RepositoryError("reviewed body must be non-empty when provided; expected string")
    if tags is not None and not _is_string_list(tags):
        raise RepositoryError("reviewed tags must be a list of strings; use [] when no tags")
    if kb_ids is not None and not _is_string_list(kb_ids):
        raise RepositoryError(
            "reviewed kb_ids must be a list of strings; use [] when no knowledge bases"
        )
    if relations is not None and not _is_mapping_list(relations):
        raise RepositoryError(REVIEW_RELATION_SHAPE)


def _validate_knowledge_review_refs(
    repository: ObjectRepository,
    kb_ids: list[str],
    relations: list[dict[str, Any]],
    *,
    self_knowledge_id: str,
) -> None:
    for kb_id in kb_ids:
        record = _find_single_object(repository, kb_id)
        if record.object_type != "knowledge-base":
            raise RepositoryError(
                f"reviewed kb_id must reference knowledge-base: {kb_id}; "
                "remove it or create/pass an existing kb-YYYYMMDD-001 ID"
            )
    _validate_child_of_count(relations, REVIEW_RELATION_SHAPE)
    for relation in relations:
        relation_type = relation.get("type")
        target_id = relation.get("target")
        _validate_relation_type(relation_type, REVIEW_RELATION_SHAPE)
        if not isinstance(target_id, str) or not target_id.strip():
            raise RepositoryError(
                f"{REVIEW_RELATION_SHAPE}; relation.target must be an existing knowledge ID"
            )
        if relation_type == HIERARCHY_RELATION_TYPE and target_id == self_knowledge_id:
            raise RepositoryError("child_of relation must not target the same knowledge object")
        if target_id == self_knowledge_id:
            continue
        record = _find_single_object(repository, target_id)
        if record.object_type != "knowledge":
            raise RepositoryError(
                f"reviewed relation target must be knowledge: {target_id}; "
                "remove non-knowledge targets or replace target with an existing knowledge ID"
            )


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
    body: str | None,
    tags: list[str] | None,
    kb_ids: list[str] | None,
    relations: list[dict[str, Any]] | None,
) -> None:
    _validate_review_content(
        title=title,
        body=body,
        tags=tags,
        kb_ids=kb_ids,
        relations=relations,
    )
    if title is None or body is None or tags is None or kb_ids is None or relations is None:
        raise RepositoryError(
            "accept requires reviewed title, body, tags, kb_ids, and relations; "
            "pass title/body as non-empty strings, tags/kb_ids as string lists, and "
            "relations as [] or relation mappings"
        )


def _validate_required_merge_content(
    *,
    body: str | None,
    tags: list[str] | None,
    kb_ids: list[str] | None,
    relations: list[dict[str, Any]] | None,
) -> None:
    _validate_review_content(
        title=None,
        body=body,
        tags=tags,
        kb_ids=kb_ids,
        relations=relations,
    )
    if body is None or tags is None or kb_ids is None or relations is None:
        raise RepositoryError(
            "merge requires reviewed body, tags, kb_ids, and relations; "
            "pass body as a non-empty string, tags/kb_ids as string lists, and "
            "relations as [] or relation mappings"
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
    reviewed_by: str | None,
    reason: str | None,
) -> MarkdownDocument:
    frontmatter = dict(document.frontmatter)
    today = _today()
    frontmatter.update(
        {
            "type": "candidate",
            "status": status,
            "review": {
                "reviewed_by": reviewed_by,
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
    reviewed_by: str | None,
    reason: str | None,
    dry_run: bool,
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
            reviewed_by=reviewed_by,
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
        if dry_run:
            return ApiResult.success(
                operation,
                objects=ObjectChanges(updated=[target_relative]),
                diffs=diffs,
                extra={"candidate_id": candidate_id, "candidate_status": target_status},
            )
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
    membership_updates: list[KnowledgebaseMembershipUpdate] | None = None,
) -> None:
    created: list[Path] = []
    written_memberships: list[KnowledgebaseMembershipUpdate] = []
    try:
        target = repository.write_markdown(knowledge_path, knowledge_document)
        created.append(target)
        for update in membership_updates or []:
            repository.write_markdown(update.relative_path, update.updated, overwrite=True)
            written_memberships.append(update)
        candidate_path.unlink()
    except Exception:
        _rollback_membership_updates(repository, written_memberships)
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
    membership_updates: list[KnowledgebaseMembershipUpdate] | None = None,
) -> None:
    knowledge_updated = False
    written_memberships: list[KnowledgebaseMembershipUpdate] = []
    try:
        repository.write_markdown(knowledge_relative, merged_knowledge, overwrite=True)
        knowledge_updated = True
        for update in membership_updates or []:
            repository.write_markdown(update.relative_path, update.updated, overwrite=True)
            written_memberships.append(update)
        _move_candidate_document(
            repository,
            workspace,
            candidate_path,
            rejected_relative,
            rejected_candidate,
        )
    except Exception:
        _rollback_membership_updates(repository, written_memberships)
        if knowledge_updated:
            repository.write_markdown(
                knowledge_relative,
                original_knowledge,
                overwrite=True,
            )
        raise


def _plan_knowledgebase_membership_updates(
    repository: ObjectRepository,
    workspace: Workspace,
    *,
    knowledge_id: str,
    old_kb_ids: list[Any],
    new_kb_ids: list[Any],
) -> list[KnowledgebaseMembershipUpdate]:
    old_ids = set(_string_items(old_kb_ids))
    new_ids = set(_string_items(new_kb_ids))
    updates: list[KnowledgebaseMembershipUpdate] = []
    for kb_id in sorted(old_ids | new_ids):
        record = _find_single_object(repository, kb_id, expected_type="knowledge-base")
        relative_path = str(workspace.relative(record.path))
        original = repository.read_markdown(relative_path)
        updated = _knowledgebase_membership_document(
            original,
            knowledge_id=knowledge_id,
            include=kb_id in new_ids,
        )
        if updated.frontmatter != original.frontmatter:
            updates.append(
                KnowledgebaseMembershipUpdate(
                    relative_path=relative_path,
                    original=original,
                    updated=updated,
                )
            )
    return updates


def _knowledgebase_membership_document(
    document: MarkdownDocument,
    *,
    knowledge_id: str,
    include: bool,
) -> MarkdownDocument:
    frontmatter = dict(document.frontmatter)
    knowledge_ids = _string_items(frontmatter.get("knowledge_ids", []))
    if include and knowledge_id not in knowledge_ids:
        knowledge_ids.append(knowledge_id)
    if not include:
        knowledge_ids = [item for item in knowledge_ids if item != knowledge_id]
    frontmatter["knowledge_ids"] = knowledge_ids
    frontmatter["updated"] = _today()
    return MarkdownDocument(frontmatter=frontmatter, body=document.body)


def _rollback_membership_updates(
    repository: ObjectRepository,
    updates: list[KnowledgebaseMembershipUpdate],
) -> None:
    for update in reversed(updates):
        try:
            repository.write_markdown(update.relative_path, update.original, overwrite=True)
        except (KBManagerError, OSError):
            pass


def _validate_knowledgebase_input(
    repository: ObjectRepository,
    *,
    title: str,
    description: str,
    acceptance_criteria: str,
    tags: list[str] | None,
    knowledgebase_id: str | None,
) -> None:
    if not isinstance(title, str) or not title.strip():
        raise RepositoryError("knowledge base title must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise RepositoryError("knowledge base description must be a non-empty string")
    if not isinstance(acceptance_criteria, str) or not acceptance_criteria.strip():
        raise RepositoryError("knowledge base acceptance criteria must be a non-empty string")
    if tags is not None and not _is_string_list(tags):
        raise RepositoryError("knowledge base tags must be a list of strings; use [] when empty")
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


def _knowledgebase_body(description: str, acceptance_criteria: str, body: str | None) -> str:
    content = body.strip() if isinstance(body, str) and body.strip() else ""
    sections = (
        f"\n## Description\n\n{description.strip()}\n\n"
        f"## Acceptance Criteria\n\n{acceptance_criteria.strip()}\n\n"
        "## Knowledge List\n"
    )
    return f"{sections}\n{content}\n"


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
            "removed_fields": ["bindings", "tags", "summary"],
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

    for legacy_dir in ("notes/inbox", "notes/bound", "notes/archive"):
        path = workspace.resolve(legacy_dir)
        if path.exists():
            differences.append(
                {
                    "kind": "legacy_directory",
                    "path": legacy_dir,
                    "expected": "notes/active or notes/deprecated",
                    "migration": "move contained note Markdown files to notes/active unless deprecated",
                }
            )

    for record in _all_records(repository):
        _append_field_schema_differences(record, workspace, differences)
        if record.object_type != "note":
            continue
        relative_path = str(workspace.relative(record.path))
        legacy_fields = [
            field for field in ("bindings", "tags", "summary") if field in record.metadata
        ]
        if legacy_fields:
            differences.append(
                {
                    "kind": "legacy_fields",
                    "object_id": record.object_id,
                    "object_type": "note",
                    "path": relative_path,
                    "fields": legacy_fields,
                    "migration": "delete these frontmatter fields",
                }
            )
        if record.status not in {"active", "deprecated"}:
            differences.append(
                {
                    "kind": "legacy_status",
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
    review_fields = {"reviewed_by", "reviewed_at", "review_decision"}
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
                "source_url",
            },
        },
        "candidate": {
            "required": object_fields
            | {
                "source_refs",
                "note_refs",
                "suggested_tags",
                "suggested_kb_ids",
                "evidence",
                "relations",
                "review",
            },
            "allowed": object_fields
            | {
                "source_refs",
                "note_refs",
                "suggested_tags",
                "suggested_kb_ids",
                "evidence",
                "relations",
                "review",
            },
        },
        "knowledge": {
            "required": object_fields
            | {
                "tags",
                "source_refs",
                "evidence",
                "kb_ids",
                "relations",
                "deprecated_at",
                "deprecated_reason",
            },
            "allowed": object_fields
            | review_fields
            | {
                "tags",
                "source_refs",
                "note_refs",
                "evidence",
                "kb_ids",
                "relations",
                "review_reason",
                "deprecated_at",
                "deprecated_reason",
            },
        },
        "knowledge-base": {
            "required": object_fields
            | {
                "description",
                "acceptance_criteria",
                "knowledge_ids",
                "tags",
            },
            "allowed": object_fields
            | review_fields
            | {
                "description",
                "acceptance_criteria",
                "knowledge_ids",
                "tags",
            },
        },
        "note": {
            "required": object_fields | {"deprecated_at", "deprecated_reason"},
            "allowed": object_fields
            | review_fields
            | {"deprecated_at", "deprecated_reason"},
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
    rebuild_diffs = [
        diff for diff in rebuild.diffs if diff.get("action") in {"create", "update"}
    ]
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
    input_text = str(input_path)
    if _is_supported_source_url(input_text):
        try:
            html = _download_url_as_html(input_text)
        except RepositoryError as direct_error:
            try:
                pdf_path = _download_url_as_pdf_with_playwright(workspace, input_text)
            except RepositoryError as playwright_error:
                report_path = _write_url_download_failure_report(
                    workspace,
                    input_text,
                    direct_error=direct_error,
                    playwright_error=playwright_error,
                )
                raise RepositoryError(
                    "URL acquisition failed; direct URL download and Playwright PDF "
                    f"export both failed. Failure report: {report_path}. "
                    f"Direct download error: {direct_error}. "
                    f"Playwright PDF export error: {playwright_error}"
                ) from playwright_error
            return [
                SourceInput(
                    path=pdf_path,
                    relative_path=str(workspace.relative(pdf_path)),
                    source_kind="url_pdf",
                    title_hint=_title_hint_for_url(input_text),
                    original_url=input_text,
                )
            ]
        return [
            SourceInput(
                path=None,
                relative_path=input_text,
                source_kind="url",
                title_hint=_title_hint_for_url(input_text),
                content=html,
            )
        ]

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
    return [
        {"input_path": source.relative_path, "content": source.content}
        for source in source_inputs
        if source.content is not None
    ]


def _validate_source_input(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise RepositoryError(f"source input does not exist or is not a file: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SOURCE_SUFFIXES:
        raise RepositoryError(f"unsupported source type: {suffix}")
    return "markdown" if suffix == ".md" else "pdf"


def _is_supported_source_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in SUPPORTED_SOURCE_URL_SCHEMES and bool(parsed.netloc)


def _title_hint_for_url(value: str) -> str:
    parsed = urlparse(value)
    path_name = Path(parsed.path).stem
    return path_name or parsed.netloc


def _source_add_input_failure_recovery(input_text: str) -> tuple[str, list[str]]:
    if not _is_supported_source_url(input_text):
        return (
            "Provide a readable .md or .pdf file inside the workspace, "
            "or an accessible HTTP(S) URL.",
            [],
        )
    return (
        "Direct URL download and Playwright PDF export failed. The URL was not added as "
        "a source; check data/failed for the captured error report, then manually "
        "download the page as a local PDF or Markdown file if needed.",
        [
            "Review the matching report under data/failed.",
            "If you still need this page, manually export/print/save it as PDF.",
            "Store the captured file inside the workspace and retry kb.source.add with its path.",
        ],
    )


def _download_url_as_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "KBManager/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            content_type = response.headers.get_content_type()
            if not (
                content_type == "text/html"
                or content_type == "application/xhtml+xml"
                or content_type.startswith("text/")
            ):
                raise RepositoryError(f"unsupported URL content type: {content_type}")
            raw = response.read(MAX_URL_DOWNLOAD_BYTES + 1)
            if len(raw) > MAX_URL_DOWNLOAD_BYTES:
                raise RepositoryError(
                    f"URL content exceeds maximum size of {MAX_URL_DOWNLOAD_BYTES} bytes"
                )
            charset = response.headers.get_content_charset() or "utf-8"
    except RepositoryError:
        raise
    except OSError as exc:
        raise RepositoryError(f"could not download URL source: {url}: {exc}") from exc

    text = raw.decode(charset, errors="replace")
    if not text.strip():
        raise RepositoryError(f"downloaded URL source is empty: {url}")
    if content_type in {"text/html", "application/xhtml+xml"}:
        return text
    escaped = escape(text)
    return (
        "<!doctype html>\n"
        "<html>\n"
        "<head>\n"
        f'  <meta charset="{escape(charset, quote=True)}">\n'
        f"  <title>{escape(url)}</title>\n"
        "</head>\n"
        "<body>\n"
        f"  <pre>{escaped}</pre>\n"
        "</body>\n"
        "</html>\n"
    )


def _download_url_as_pdf_with_playwright(workspace: Workspace, url: str) -> Path:
    target = workspace.ensure_parent(_url_capture_pdf_relative(url))
    if target.exists():
        return target

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RepositoryError(
            "Playwright is not installed; install the Python playwright package and browser "
            "runtime to enable URL PDF export fallback"
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=30_000)
                page.pdf(path=str(target), print_background=True, prefer_css_page_size=True)
            finally:
                browser.close()
    except (PlaywrightError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise RepositoryError(
            f"could not export URL as PDF with Playwright: {url}: {exc}"
        ) from exc

    if not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise RepositoryError(f"Playwright PDF export produced an empty file: {url}")
    return target


def _url_capture_pdf_relative(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"data/attachments/url-captures/{digest}.pdf"


def _write_url_download_failure_report(
    workspace: Workspace,
    url: str,
    *,
    direct_error: Exception,
    playwright_error: Exception,
) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    relative_path = f"data/failed/url-{digest}-{stamp}.json"
    report_path = workspace.ensure_parent(relative_path)
    report = {
        "url": url,
        "failed_at": _today(),
        "direct_download_error": str(direct_error),
        "playwright_pdf_error": str(playwright_error),
        "source_added": False,
        "next_actions": [
            "Manually download or print the page as PDF if it is still needed.",
            "Run kb.source.add again with the local PDF or Markdown file path.",
        ],
    }
    _write_new_text_atomic(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return relative_path


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
            if source_input.source_kind in {"pdf", "url_pdf"}
            else f"data/raw/html/{source_id}.html"
            if source_input.source_kind == "url"
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
        if source_input.original_url is not None:
            metadata["source_url"] = source_input.original_url
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
                if source_input.path is None:
                    raise RepositoryError("markdown source input is missing a local path")
                original = source_input.path.read_text(encoding="utf-8")
                path = repository.write_markdown(
                    record["source_relative"],
                    MarkdownDocument(frontmatter=metadata, body=f"\n## Source\n\n{original}"),
                )
                created.append(path)
            elif source_input.source_kind in {"pdf", "url_pdf"}:
                if source_input.path is None:
                    raise RepositoryError("PDF source input is missing a local path")
                target = workspace.ensure_parent(record["source_relative"])
                _copy_new_file_atomic(source_input.path, target)
                created.append(target)
                repository.write_meta(record["source_relative"], metadata)
                created.append(target.with_suffix(".meta.yml"))
            else:
                if source_input.content is None:
                    raise RepositoryError("URL source input is missing downloaded content")
                target = workspace.ensure_parent(record["source_relative"])
                _write_new_text_atomic(target, source_input.content)
                created.append(target)
                repository.write_meta(record["source_relative"], metadata)
                created.append(target.with_suffix(".meta.yml"))
    except Exception:
        _rollback_created(created)
        raise


def _validate_upstream_refs(
    repository: ObjectRepository,
    source_ids: list[str],
    note_ids: list[str],
) -> list[ObjectRecord]:
    if not source_ids and not note_ids:
        raise RepositoryError(
            "candidate must reference at least one source or note; pass source_ids and/or "
            "note_ids with existing object IDs"
        )

    records: list[ObjectRecord] = []
    for source_id in source_ids:
        record = _find_single_object(repository, source_id, expected_type="source")
        if record.status not in {"raw", "archived", "deprecated"}:
            raise RepositoryError(
                f"source has unsupported status: {source_id}; candidate sources must be "
                "raw, archived, or deprecated"
            )
        records.append(record)
    for note_id in note_ids:
        records.append(_find_single_object(repository, note_id, expected_type="note"))
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
        if source_id in _string_items(record.metadata.get("source_refs", [])):
            fields.append("source_refs")
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
        raise RepositoryError(
            "llm_result.candidates must be a non-empty list of candidate drafts"
        )
    for draft in drafts:
        if not isinstance(draft, dict):
            raise RepositoryError(
                "each candidate draft must be a mapping with title, body, evidence, refs, "
                "and optional relations"
            )
        if not isinstance(draft.get("title"), str) or not draft["title"].strip():
            raise RepositoryError("candidate title must be a non-empty string")
        if not isinstance(draft.get("body"), str) or not draft["body"].strip():
            raise RepositoryError("candidate body must be a non-empty string")
        if draft.get("status") in {"accepted", "knowledge"} or draft.get("type") == "knowledge":
            raise RepositoryError(
                "LLM result must not create accepted knowledge; create type candidate with "
                "status omitted or pending"
            )
        evidence = draft.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise RepositoryError(f"candidate evidence must be a non-empty list; {EVIDENCE_SHAPE}")
        for key in ("source_refs", "note_refs", "suggested_tags", "suggested_kb_ids"):
            if key in draft and not _is_string_list(draft[key]):
                raise RepositoryError(
                    f"candidate {key} must be a list of strings; use [] when empty"
                )
        if "relations" in draft and not _is_mapping_list(draft["relations"]):
            raise RepositoryError(CANDIDATE_RELATION_SHAPE)
        for key in ("evidence_summary", "llm_notes"):
            if key in draft and not isinstance(draft[key], str):
                raise RepositoryError(f"candidate {key} must be a string; omit if absent")
    return drafts


def _plan_candidate_records(
    repository: ObjectRepository,
    drafts: list[dict[str, Any]],
    source_ids: list[str],
    note_ids: list[str],
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
        draft_note_ids = draft.get("note_refs", note_ids)
        if not draft_source_ids and not draft_note_ids:
            raise RepositoryError(
                "candidate must reference at least one source or note; source_refs/note_refs "
                "must include the requested upstream IDs"
            )
        if not _is_string_list(draft_source_ids) or not _is_string_list(draft_note_ids):
            raise RepositoryError(
                "candidate source_refs and note_refs must be string lists; use [] when empty"
            )
        _validate_preserved_refs(source_ids, draft_source_ids, "source_refs")
        _validate_preserved_refs(note_ids, draft_note_ids, "note_refs")
        _validate_upstream_refs(repository, draft_source_ids, draft_note_ids)
        _validate_evidence(
            repository,
            draft["evidence"],
            draft_source_ids,
            draft_note_ids,
        )
        relations = draft.get("relations", [])
        _validate_candidate_relations(repository, relations, self_knowledge_id=candidate_id)
        suggested_kb_ids = draft.get("suggested_kb_ids", [])
        _validate_candidate_suggested_kb_ids(repository, suggested_kb_ids)

        frontmatter = {
            "id": candidate_id,
            "type": "candidate",
            "title": draft["title"],
            "status": "pending",
            "source_refs": draft_source_ids,
            "note_refs": draft_note_ids,
            "suggested_tags": draft.get("suggested_tags", []),
            "suggested_kb_ids": suggested_kb_ids,
            "evidence": draft["evidence"],
            "relations": relations,
            "review": {
                "reviewed_by": None,
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
                    "\n## Candidate Knowledge\n\n"
                    f"{draft['body'].strip()}\n\n"
                    "## Evidence\n\n"
                    f"{draft.get('evidence_summary', '').strip()}\n\n"
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
            "suggested_tags": list(record["frontmatter"].get("suggested_tags", [])),
            "suggested_kb_ids": list(record["frontmatter"].get("suggested_kb_ids", [])),
        }
        for record in records
    ]
    return {
        "candidate_ids": [candidate["id"] for candidate in candidates],
        "suggested_tags": _merged_strings(
            [],
            [tag for candidate in candidates for tag in candidate["suggested_tags"]],
        ),
        "suggested_kb_ids": _merged_strings(
            [],
            [kb_id for candidate in candidates for kb_id in candidate["suggested_kb_ids"]],
        ),
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
    note_ids: list[str],
) -> None:
    upstream = set(source_ids) | set(note_ids)
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


def _validate_candidate_relations(
    repository: ObjectRepository,
    relations: list[dict[str, Any]],
    *,
    self_knowledge_id: str | None = None,
) -> None:
    _validate_child_of_count(relations, CANDIDATE_RELATION_SHAPE)
    for relation in relations:
        relation_type = relation.get("type")
        target_id = relation.get("target")
        _validate_relation_type(relation_type, CANDIDATE_RELATION_SHAPE)
        if not isinstance(target_id, str) or not target_id.strip():
            raise RepositoryError(
                f"{CANDIDATE_RELATION_SHAPE}; "
                "relation.target must be an existing knowledge ID"
            )
        if relation_type == HIERARCHY_RELATION_TYPE and target_id == self_knowledge_id:
            raise RepositoryError("child_of relation must not target the same candidate ID")
        target = _find_single_object(repository, target_id)
        if target.object_type != "knowledge":
            raise RepositoryError(
                f"candidate relation target must be knowledge: {target_id}; "
                "remove non-knowledge targets or replace target with an existing knowledge ID"
            )


def _validate_relation_type(value: Any, shape_message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RepositoryError(f"{shape_message}; relation.type must be non-empty")
    if value not in RELATION_TYPES:
        raise RepositoryError(
            f"{shape_message}; relation.type must be one of: {RELATION_TYPE_LIST}"
        )


def _validate_child_of_count(relations: list[dict[str, Any]], shape_message: str) -> None:
    count = sum(1 for relation in relations if relation.get("type") == HIERARCHY_RELATION_TYPE)
    if count > 1:
        raise RepositoryError(
            f"{shape_message}; each knowledge object may have at most one child_of"
        )


def _validate_candidate_suggested_kb_ids(
    repository: ObjectRepository,
    suggested_kb_ids: list[str],
) -> None:
    for kb_id in suggested_kb_ids:
        record = _find_single_object(repository, kb_id)
        if record.object_type != "knowledge-base":
            raise RepositoryError(
                f"candidate suggested_kb_id must be knowledge-base: {kb_id}; "
                "remove it or use an existing kb-YYYYMMDD-001 ID"
            )


def _candidate_reference_summaries(
    repository: ObjectRepository,
    frontmatter: dict[str, Any],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for object_id in frontmatter.get("source_refs", []):
        references.append(_summary_for_record(_find_single_object(repository, object_id)))
    for object_id in frontmatter.get("note_refs", []):
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
