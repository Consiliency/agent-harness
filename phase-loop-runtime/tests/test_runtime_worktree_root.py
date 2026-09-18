from pathlib import Path

import pytest

from phase_loop_runtime.runtime_paths import lane_worktree_root


def test_private_worktree_override(monkeypatch, tmp_path):
    private = tmp_path / "private/worktrees"
    monkeypatch.setenv("WORKTREE_ROOT", str(private))
    assert lane_worktree_root(tmp_path / "repo") == private


def test_explicit_mount_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKTREE_ROOT", str(tmp_path / "private"))
    mount = tmp_path / "explicit"
    mount.mkdir()
    assert lane_worktree_root(tmp_path / "repo", workspace_mount=mount) == mount / "worktrees"


def test_relative_override_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKTREE_ROOT", "relative")
    with pytest.raises(ValueError, match="absolute"):
        lane_worktree_root(tmp_path / "repo")


def test_legacy_without_mount(monkeypatch, tmp_path):
    monkeypatch.delenv("WORKTREE_ROOT", raising=False)
    assert lane_worktree_root(tmp_path / "repo", workspace_mount=tmp_path / "absent") == tmp_path
