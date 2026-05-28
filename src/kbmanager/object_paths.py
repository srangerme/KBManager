"""Known object path conventions for the file repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kbmanager.errors import RepositoryError
from kbmanager.workspace import Workspace


@dataclass(frozen=True)
class ObjectPaths:
    workspace: Workspace

    def source_markdown(self, filename: str) -> Path:
        return self._resolve_file("data/raw/md", filename, ".md")

    def source_pdf(self, filename: str) -> Path:
        return self._resolve_file("data/raw/pdf", filename, ".pdf")

    def candidate(self, filename: str, status: str = "pending") -> Path:
        if status not in {"pending", "rejected", "deferred"}:
            raise RepositoryError(f"unsupported candidate status: {status}")
        return self._resolve_file(f"candidates/{status}", filename, ".md")

    def knowledge(self, filename: str) -> Path:
        return self._resolve_file("knowledge/atomic", filename, ".md")

    def knowledgebase(self, filename: str) -> Path:
        return self._resolve_file("knowledge/bases", filename, ".md")

    def note(self, filename: str, status: str = "active") -> Path:
        if status not in {"active", "deprecated"}:
            raise RepositoryError(f"unsupported note status: {status}")
        return self._resolve_file(f"notes/{status}", filename, ".md")

    def index(self, filename: str) -> Path:
        suffix = Path(filename).suffix.lower()
        if suffix == ".md":
            return self._resolve_file("indexes", filename, ".md")
        if suffix in {".yml", ".yaml"}:
            return self._resolve_file("indexes", filename, suffix)
        raise RepositoryError(f"index filename must end with .md, .yml, or .yaml: {filename}")

    def knowledgebase_index(self, filename: str) -> Path:
        return self._resolve_file("indexes/knowledgebase", filename, ".md")

    def _resolve_file(self, directory: Path | str, filename: str, suffix: str) -> Path:
        candidate = Path(filename)
        if candidate.name != filename:
            raise RepositoryError(f"filename must not include directories: {filename}")
        if candidate.suffix.lower() != suffix:
            raise RepositoryError(f"filename must end with {suffix}: {filename}")
        return self.workspace.resolve(Path(directory) / candidate)
