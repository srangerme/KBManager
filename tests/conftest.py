from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kbmanager.repository import ObjectRepository  # noqa: E402
from kbmanager.workspace import Workspace  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


@pytest.fixture
def repository(workspace: Workspace) -> ObjectRepository:
    return ObjectRepository(workspace)
