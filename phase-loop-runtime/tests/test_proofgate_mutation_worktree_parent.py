"""Regression guard: proofgate mutation worktrees must land in a writable parent.

On a team host ``/mnt/workspace/worktrees`` exists but is root-owned and not
user-writable; selecting it raised ``PermissionError`` from ``tempfile.mkdtemp``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from phase_loop_runtime.verification_evidence import _mutation_worktree_parent

pytestmark = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root bypasses directory permissions"
)


@pytest.fixture
def layout(tmp_path: Path):
    repo_root = tmp_path / "code" / "repo"
    repo_root.mkdir(parents=True)
    unwritable = tmp_path / "shared-worktrees"
    unwritable.mkdir()
    unwritable.chmod(0o111)
    home = tmp_path / "home"
    marker = tmp_path / "team-host"
    yield repo_root, unwritable, home, marker
    unwritable.chmod(0o755)


def test_skips_unwritable_shared_parent(layout):
    repo_root, unwritable, home, marker = layout
    parent = _mutation_worktree_parent(
        repo_root, environ={}, team_host_marker=marker, home=home, shared_parent=unwritable
    )
    assert parent == repo_root.parent


def test_honours_worktree_root_over_unwritable_shared_parent(layout, tmp_path):
    repo_root, unwritable, home, marker = layout
    root = tmp_path / "my-worktrees"
    root.mkdir()
    parent = _mutation_worktree_parent(
        repo_root,
        environ={"WORKTREE_ROOT": str(root)},
        team_host_marker=marker,
        home=home,
        shared_parent=unwritable,
    )
    assert parent == root


def test_team_host_uses_home_workspace_worktrees(layout):
    repo_root, unwritable, home, marker = layout
    marker.touch()
    team_parent = home / "workspace" / "worktrees"
    team_parent.mkdir(parents=True)
    parent = _mutation_worktree_parent(
        repo_root, environ={}, team_host_marker=marker, home=home, shared_parent=unwritable
    )
    assert parent == team_parent


def test_unwritable_worktree_root_falls_through(layout, tmp_path):
    repo_root, unwritable, home, marker = layout
    writable_shared = tmp_path / "writable-shared"
    writable_shared.mkdir()
    parent = _mutation_worktree_parent(
        repo_root,
        environ={"WORKTREE_ROOT": str(unwritable)},
        team_host_marker=marker,
        home=home,
        shared_parent=writable_shared,
    )
    assert parent == writable_shared
