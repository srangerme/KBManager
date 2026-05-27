"""Built-in LLM prompt selection, versioning, and assembly."""

from __future__ import annotations

import copy
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kbmanager.errors import RepositoryError
from kbmanager.repository import ObjectRepository

SOURCE_SYSTEM_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "system-prompts"
INSTALLED_SYSTEM_PROMPTS_DIR = (
    Path(sysconfig.get_path("data")) / "share" / "kbmanager" / "system-prompts"
)

PROMPT_BY_PURPOSE = {
    "source_ingest": "source-ingest",
    "source_ingest_prompt_rewrite": "source-ingest-prompt-rewrite",
    "create_candidate": "candidate-create",
    "note_title": "note-title",
    "clean_migration_plan": "clean-migration-plan",
    "candidate_review_assist": "candidate-review-assist",
    "knowledge_merge_assist": "knowledge-merge-assist",
    "knowledgebase_create": "knowledgebase-create",
}

OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "source_ingest_result": {
        "type": "object",
        "required": ["input_path", "summary", "cleaned_content"],
        "properties": {
            "input_path": "string",
            "title": "string",
            "summary": "non-empty string",
            "cleaned_content": "non-empty string",
            "tags": "list[string]",
            "authors": "list[string]",
            "published_at": "string|null",
        },
    },
    "source_ingest_result_list": {
        "type": "object",
        "required": ["sources"],
        "properties": {"sources": "list[source_ingest_result]"},
    },
    "source_ingest_prompt_rewrite": {
        "type": "object",
        "required": ["rewritten_prompt", "intent_summary", "constraints", "warnings"],
        "properties": {
            "rewritten_prompt": "non-empty string",
            "intent_summary": "non-empty string",
            "constraints": "list[string]",
            "warnings": "list[string]",
        },
    },
    "candidate_draft_list": {
        "type": "object",
        "required": ["candidates"],
        "properties": {
            "candidates": [
                {
                    "title": "non-empty string",
                    "summary": "non-empty string",
                    "content": "non-empty string",
                    "source_refs": "list[string]",
                    "evidence": "list[{source_id|object_id|id, locator, quote|excerpt|snippet}]",
                    "bindto": "list[{kb_id, outline_id, node_id, reason}] or []",
                    "outline_change_suggestions": (
                        "list[{kb_id, outline_id|null, reason, suggested_change}] or []"
                    ),
                }
            ]
        },
    },
    "note_title": {
        "type": "object",
        "required": ["title"],
        "properties": {"title": "non-empty string"},
    },
    "clean_migration_plan": {
        "type": "object",
        "required": ["summary", "moves", "field_deletions", "field_updates", "risks"],
        "properties": {
            "summary": "non-empty string",
            "moves": "list[{from, to, reason}]",
            "field_deletions": "list[{path, fields, reason}]",
            "field_updates": "list[{path, field, from, to, reason}]",
            "risks": "list[string]",
            "execution_order": "list[string]",
        },
    },
    "candidate_review_assist": {
        "type": "object",
        "required": ["summary", "evidence_review", "bindto", "recommendations"],
        "properties": {
            "summary": "non-empty string",
            "evidence_review": "list[object]",
            "bindto": "list[{kb_id, outline_id, node_id, reason}]",
            "recommendations": "list[object|string]",
        },
    },
    "knowledge_merge_assist": {
        "type": "object",
        "required": ["merged_summary", "merged_content", "evidence", "bindto", "evidence_review"],
    },
    "knowledgebase_create_draft": {
        "type": "object",
        "required": ["frontmatter"],
        "properties": {
            "frontmatter": {
                "description": "non-empty string",
                "tags": "list[string]",
                "scope": "{includes: list[string], excludes: list[string]}",
                "default_outline_id": "non-empty string",
                "outlines": "list[{id, title, description, status, nodes}]",
            },
        },
    },
}


@dataclass(frozen=True)
class SystemPrompt:
    name: str
    version: str
    text: str
    metadata: dict[str, Any]


def load_system_prompt(name: str) -> SystemPrompt:
    if "/" in name or "\\" in name or name.startswith("."):
        raise RepositoryError(f"invalid system prompt name: {name}")
    path = _system_prompt_path(name)
    if path is None:
        raise RepositoryError(f"system prompt not found: {name}")

    text = path.read_text(encoding="utf-8")
    document = ObjectRepository.parse_markdown(text, source=str(path))
    version = document.frontmatter.get("version")
    if not isinstance(version, (int, str)) or str(version) == "":
        raise RepositoryError(f"system prompt has no version: {name}")
    return SystemPrompt(
        name=name,
        version=str(version),
        text=document.body.lstrip(),
        metadata=dict(document.frontmatter),
    )


def _system_prompt_path(name: str) -> Path | None:
    for directory in (SOURCE_SYSTEM_PROMPTS_DIR, INSTALLED_SYSTEM_PROMPTS_DIR):
        path = directory / f"{name}.md"
        if path.is_file():
            return path
    return None


def prompt_name_for_purpose(purpose: str) -> str:
    try:
        return PROMPT_BY_PURPOSE[purpose]
    except KeyError as exc:
        raise RepositoryError(f"unsupported LLM purpose: {purpose}") from exc


def schema_for_output(output_schema: str) -> dict[str, Any]:
    try:
        return OUTPUT_SCHEMAS[output_schema]
    except KeyError as exc:
        raise RepositoryError(f"unsupported LLM output schema: {output_schema}") from exc


def assemble_prompt(
    *,
    system_prompt: str,
    user_input: str | dict[str, Any] | None = None,
    object_context: dict[str, Any] | None = None,
    output_schema: str | dict[str, Any],
    constraints: list[str] | None = None,
) -> dict[str, Any]:
    prompt = load_system_prompt(system_prompt)
    schema = schema_for_output(output_schema) if isinstance(output_schema, str) else output_schema
    sections = [
        {"role": "system", "name": "kbmanager_system_prompt", "content": prompt.text},
        {
            "role": "user",
            "name": "current_user_input",
            "content": user_input if user_input is not None else {},
        },
        {
            "role": "context",
            "name": "object_context",
            "content": _redacted_context(object_context or {}),
        },
        {
            "role": "schema",
            "name": "output_schema",
            "content": {"schema": schema, "constraints": constraints or []},
        },
    ]
    return {
        "system_prompt": prompt.name,
        "prompt_version": prompt.version,
        "sections": sections,
    }


def prompt_descriptor(
    *,
    purpose: str,
    output_schema: str,
    user_input: str | dict[str, Any] | None,
    object_context: dict[str, Any] | None,
    constraints: list[str] | None,
) -> dict[str, Any]:
    prompt_name = prompt_name_for_purpose(purpose)
    assembled = assemble_prompt(
        system_prompt=prompt_name,
        user_input=user_input,
        object_context=object_context,
        output_schema=output_schema,
        constraints=constraints,
    )
    return {
        "system_prompt": prompt_name,
        "prompt_version": assembled["prompt_version"],
        "output_schema": output_schema,
        "output_schema_definition": schema_for_output(output_schema),
        "prompt": assembled,
    }


def _redacted_context(context: dict[str, Any]) -> dict[str, Any]:
    safe = copy.deepcopy(context)
    if not safe.get("include_object_body", False):
        _remove_body_fields(safe)
    safe.pop("include_object_body", None)
    return safe


def _remove_body_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value):
            if key in {"body", "object_body", "full_body", "content"}:
                replacement = _body_summary(value[key])
                value[f"{key}_summary"] = replacement
                del value[key]
            else:
                _remove_body_fields(value[key])
    elif isinstance(value, list):
        for item in value:
            _remove_body_fields(item)


def _body_summary(value: Any) -> str:
    if not isinstance(value, str):
        return "<non-text body omitted>"
    compact = " ".join(value.split())
    if not compact:
        return ""
    return compact if len(compact) <= 240 else compact[:237] + "..."


def schema_as_yaml(schema_name: str) -> str:
    return yaml.safe_dump(schema_for_output(schema_name), sort_keys=False, allow_unicode=True)
