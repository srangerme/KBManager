"""Workspace path handling with escape protection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kbmanager.errors import WorkspacePathError


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __init__(self, root: str | Path) -> None:
        resolved = Path(root).expanduser().resolve()
        object.__setattr__(self, "root", resolved)

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()

        if not self._is_within_root(resolved):
            raise WorkspacePathError(f"path escapes workspace root: {path}")
        return resolved

    def relative(self, path: str | Path) -> Path:
        return self.resolve(path).relative_to(self.root)

    def ensure_parent(self, path: str | Path) -> Path:
        resolved = self.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def _is_within_root(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents
