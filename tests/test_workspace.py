from __future__ import annotations

from pathlib import Path

import pytest

from kbmanager.errors import WorkspacePathError
from kbmanager.workspace import Workspace


def test_resolves_relative_path_inside_workspace(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    assert workspace.resolve("data/raw/md/example.md") == tmp_path / "data/raw/md/example.md"


def test_rejects_parent_path_escape(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspacePathError):
        workspace.resolve("../outside.md")


def test_rejects_absolute_path_escape(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspacePathError):
        workspace.resolve("/tmp/outside.md")


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspacePathError):
        workspace.resolve("link/object.md")
