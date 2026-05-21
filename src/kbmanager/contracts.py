"""Structured API result contracts shared by all layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApiStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_LLM = "needs_llm"
    NEEDS_REVIEW = "needs_review"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ApiError:
    operation: str
    code: str
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True)
class ObjectChanges:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "created": list(self.created),
            "updated": list(self.updated),
            "deprecated": list(self.deprecated),
        }


@dataclass(frozen=True)
class ReviewRequest:
    required: bool = False
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "options": list(self.options),
        }


@dataclass(frozen=True)
class ApiResult:
    status: ApiStatus
    operation: str
    objects: ObjectChanges = field(default_factory=ObjectChanges)
    diffs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[ApiError] = field(default_factory=list)
    review: ReviewRequest = field(default_factory=ReviewRequest)
    next_actions: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, operation: str, **kwargs: Any) -> ApiResult:
        return cls(status=ApiStatus.SUCCESS, operation=operation, **kwargs)

    @classmethod
    def failed(
        cls,
        operation: str,
        code: str,
        message: str,
        suggestion: str | None = None,
        **kwargs: Any,
    ) -> ApiResult:
        return cls(
            status=ApiStatus.FAILED,
            operation=operation,
            errors=[ApiError(operation, code, message, suggestion)],
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status.value,
            "operation": self.operation,
            "objects": self.objects.to_dict(),
            "diffs": list(self.diffs),
            "warnings": list(self.warnings),
            "errors": [error.to_dict() for error in self.errors],
            "review": self.review.to_dict(),
            "next_actions": list(self.next_actions),
        }
        result.update(self.extra)
        return result
