"""KBManager Python package."""

from kbmanager.application import (
    candidate_create,
    candidate_defer,
    candidate_get,
    candidate_next_pending,
    clean_inspect,
    index_rebuild,
    init_workspace,
    knowledge_accept,
    knowledge_deprecate,
    knowledge_merge,
    knowledge_reject,
    knowledgebase_create,
    knowledgebase_map,
    knowledgebase_outline_archive,
    knowledgebase_outline_create,
    knowledgebase_outline_set_default,
    note_add,
    note_deprecate,
    note_get,
    source_add,
    source_deprecate,
)
from kbmanager.contracts import ApiError, ApiResult, ApiStatus
from kbmanager.interface import ApplicationApiClient, InteractionInterface, InterfaceResult
from kbmanager.object_paths import ObjectPaths
from kbmanager.prompts import assemble_prompt, load_system_prompt
from kbmanager.repository import MarkdownDocument, ObjectMetadata, ObjectRepository
from kbmanager.workspace import Workspace

__all__ = [
    "ApiError",
    "ApiResult",
    "ApiStatus",
    "ApplicationApiClient",
    "assemble_prompt",
    "candidate_create",
    "candidate_defer",
    "candidate_get",
    "candidate_next_pending",
    "clean_inspect",
    "init_workspace",
    "index_rebuild",
    "knowledge_accept",
    "knowledgebase_create",
    "knowledgebase_outline_archive",
    "knowledgebase_outline_create",
    "knowledgebase_outline_set_default",
    "knowledgebase_map",
    "knowledge_deprecate",
    "knowledge_merge",
    "knowledge_reject",
    "InterfaceResult",
    "load_system_prompt",
    "note_add",
    "note_deprecate",
    "note_get",
    "MarkdownDocument",
    "ObjectMetadata",
    "ObjectPaths",
    "ObjectRepository",
    "source_add",
    "source_deprecate",
    "InteractionInterface",
    "Workspace",
]
