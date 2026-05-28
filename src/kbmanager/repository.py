"""File repository primitives for Markdown frontmatter and sidecar metadata."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kbmanager.errors import RepositoryError, WorkspacePathError
from kbmanager.workspace import Workspace


@dataclass(frozen=True)
class MarkdownDocument:
    frontmatter: dict[str, Any]
    body: str


@dataclass(frozen=True)
class ObjectMetadata:
    path: Path
    object_id: str
    object_type: str
    metadata: dict[str, Any]


REQUIRED_OBJECT_FIELDS = ("id", "type", "title", "status", "created", "updated")
OBJECT_METADATA_ROOTS = (
    "data/raw/md",
    "data/raw/pdf",
    "candidates",
    "knowledge",
    "notes",
)


class ObjectRepository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def read_markdown(self, path: str | Path) -> MarkdownDocument:
        resolved = self.workspace.resolve(path)
        self._reject_markdown_sidecar(resolved)
        text = self._read_text(resolved)
        document = self.parse_markdown(text, source=str(path))
        self.validate_required_fields(document.frontmatter, source=str(path))
        return document

    def write_markdown(
        self,
        path: str | Path,
        document: MarkdownDocument,
        *,
        overwrite: bool = False,
    ) -> Path:
        resolved = self.workspace.ensure_parent(path)
        self._reject_markdown_sidecar(resolved)
        self.validate_required_fields(document.frontmatter, source=str(path))
        text = self.render_markdown(document)
        self._atomic_write_text(resolved, text, overwrite=overwrite)
        return resolved

    def read_meta(self, resource_path: str | Path) -> dict[str, Any]:
        resource = self.workspace.resolve(resource_path)
        if resource.suffix.lower() == ".md":
            raise RepositoryError("Markdown objects must use frontmatter, not .meta.yml")
        if not resource.exists():
            raise RepositoryError(f"resource file not found: {resource}")
        meta_path = self._meta_path(resource)
        data = self._read_yaml_file(meta_path)
        if not isinstance(data, dict):
            raise RepositoryError(f"metadata file must contain a mapping: {meta_path}")
        self.validate_required_fields(data, source=str(meta_path))
        return data

    def write_meta(
        self,
        resource_path: str | Path,
        metadata: dict[str, Any],
        *,
        overwrite: bool = False,
    ) -> Path:
        resource = self.workspace.resolve(resource_path)
        if resource.suffix.lower() == ".md":
            raise RepositoryError("Markdown objects must use frontmatter, not .meta.yml")
        if not resource.exists():
            raise RepositoryError(f"resource file not found: {resource}")
        meta_path = self._meta_path(resource)
        self.workspace.ensure_parent(meta_path)
        self.validate_required_fields(metadata, source=str(meta_path))
        self._atomic_write_text(meta_path, self._dump_yaml(metadata), overwrite=overwrite)
        return meta_path

    def move_file(
        self,
        source_path: str | Path,
        target_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        source = self.workspace.resolve(source_path)
        target = self.workspace.ensure_parent(target_path)
        if not source.exists():
            raise RepositoryError(f"source file not found: {source}")
        if target.exists() and not overwrite:
            raise RepositoryError(f"target already exists: {target}")
        os.replace(source, target)
        return target

    def iter_object_metadata(self) -> list[ObjectMetadata]:
        records: list[ObjectMetadata] = []
        for root in OBJECT_METADATA_ROOTS:
            directory = self.workspace.resolve(root)
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*")):
                if path.suffix.lower() == ".md":
                    self._reject_markdown_sidecar(path)
                    document = self.parse_markdown(self._read_text(path), source=str(path))
                    self.validate_required_fields(document.frontmatter, source=str(path))
                    records.append(self._metadata_record(path, document.frontmatter))
                elif path.suffix.lower() == ".pdf":
                    meta_path = self._meta_path(path)
                    if not meta_path.exists():
                        raise RepositoryError(f"raw source has no sidecar metadata: {path}")
                elif path.name.endswith(".meta.yml"):
                    resource = self._resource_for_meta_path(path)
                    if not resource.exists():
                        raise RepositoryError(f"metadata sidecar has no resource file: {path}")
                    data = self._read_yaml_file(path)
                    if not isinstance(data, dict):
                        raise RepositoryError(f"metadata file must contain a mapping: {path}")
                    self.validate_required_fields(data, source=str(path))
                    records.append(self._metadata_record(path, data))
        return records

    def scan_object_ids(self) -> dict[str, list[Path]]:
        ids: dict[str, list[Path]] = {}
        for record in self.iter_object_metadata():
            ids.setdefault(record.object_id, []).append(record.path)
        return ids

    def find_duplicate_ids(self) -> dict[str, list[Path]]:
        return {
            object_id: paths
            for object_id, paths in self.scan_object_ids().items()
            if len(paths) > 1
        }

    @staticmethod
    def parse_markdown(text: str, source: str = "<markdown>") -> MarkdownDocument:
        if not text.startswith("---\n"):
            raise RepositoryError(f"missing YAML frontmatter: {source}")

        end = text.find("\n---\n", 4)
        if end == -1:
            raise RepositoryError(f"unterminated YAML frontmatter: {source}")

        raw_frontmatter = text[4:end]
        body = text[end + len("\n---\n") :]
        try:
            parsed = yaml.safe_load(raw_frontmatter) or {}
        except yaml.YAMLError as exc:
            raise RepositoryError(f"invalid YAML frontmatter in {source}: {exc}") from exc

        if not isinstance(parsed, dict):
            raise RepositoryError(f"frontmatter must contain a mapping: {source}")
        return MarkdownDocument(frontmatter=parsed, body=body)

    @staticmethod
    def validate_required_fields(metadata: dict[str, Any], source: str) -> None:
        missing = [field for field in REQUIRED_OBJECT_FIELDS if field not in metadata]
        if missing:
            raise RepositoryError(
                f"missing required metadata fields in {source}: {', '.join(missing)}"
            )
        for field in ("id", "type"):
            if not isinstance(metadata[field], str) or not metadata[field]:
                raise RepositoryError(
                    f"metadata field must be a non-empty string in {source}: {field}"
                )

    @staticmethod
    def render_markdown(document: MarkdownDocument) -> str:
        if not isinstance(document.frontmatter, dict):
            raise RepositoryError("frontmatter must be a mapping")
        frontmatter = ObjectRepository._dump_yaml(document.frontmatter).rstrip()
        return f"---\n{frontmatter}\n---\n{document.body}"

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RepositoryError(f"file not found: {path}") from exc
        except OSError as exc:
            raise RepositoryError(f"could not read file {path}: {exc}") from exc

    def _read_yaml_file(self, path: Path) -> Any:
        text = self._read_text(path)
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RepositoryError(f"invalid YAML metadata in {path}: {exc}") from exc

    def _reject_markdown_sidecar(self, markdown_path: Path) -> None:
        if markdown_path.suffix.lower() != ".md":
            return
        sidecar = self._meta_path(markdown_path)
        if sidecar.exists():
            raise RepositoryError("Markdown objects must not have sidecar .meta.yml files")

    @staticmethod
    def _metadata_record(path: Path, metadata: dict[str, Any]) -> ObjectMetadata:
        return ObjectMetadata(
            path=path,
            object_id=metadata["id"],
            object_type=metadata["type"],
            metadata=dict(metadata),
        )

    @staticmethod
    def _meta_path(resource_path: Path) -> Path:
        return resource_path.with_suffix(".meta.yml")

    @staticmethod
    def _resource_for_meta_path(meta_path: Path) -> Path:
        if meta_path.parent.name == "pdf":
            suffix = f".{meta_path.parent.name}"
            return meta_path.with_name(meta_path.name.removesuffix(".meta.yml") + suffix)
        return meta_path.with_name(meta_path.name.removesuffix(".meta.yml"))

    @staticmethod
    def _dump_yaml(data: dict[str, Any]) -> str:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    def _atomic_write_text(self, path: Path, text: str, *, overwrite: bool) -> None:
        if not self.workspace._is_within_root(path):
            raise WorkspacePathError(f"path escapes workspace root: {path}")
        if path.exists() and not overwrite:
            raise RepositoryError(f"target already exists: {path}")

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
