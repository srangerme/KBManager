"""Repository and workspace exceptions."""

from __future__ import annotations


class KBManagerError(Exception):
    """Base exception for expected KBManager failures."""


class WorkspacePathError(KBManagerError):
    """Raised when a path escapes the configured workspace."""


class RepositoryError(KBManagerError):
    """Raised when object files cannot be parsed or written safely."""
