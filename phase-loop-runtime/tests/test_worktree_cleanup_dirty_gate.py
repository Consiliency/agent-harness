"""Regression tests for the dirty-tree gate in the two worktree cleanup helpers.

``sweep_stale_worktrees.sh`` and ``cleanup_lane_worktrees.sh`` both force-removed a
worktree on a merge/pattern test alone, with no check for uncommitted work. A worktree
whose commits are already on the target while uncommitted edits sit on top is the normal
post-merge follow-up state, so ``MERGED`` (or a matching branch name) never implies the
tree is finished. On a live team host this selected three worktrees holding 60
uncommitted files for ``git worktree remove -f -f`` (Consiliency/agent-harness#1300).

Each gate is pinned together with a positive control: a merged-and-clean worktree must
still be removed. Without the control a blanket "always KEEP" regression would pass.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "skills-src" / "claude" / "claude-execute-phase" / "scripts"
_SWEEP = _SCRIPTS / "sweep_stale_worktrees.sh"
_CLEANUP = _SCRIPTS / "cleanup_lane_worktrees.sh"

# Repo-source helpers under skills-src/ are not packaged into the wheel; skip in the
# standalone-from-wheel gate where they are absent.
pytestmark = pytest.mark.skipif(
    not _SWEEP.exists() or not _CLEANUP.exists(),
    reason="repo-only helpers (skills-src/ not in the wheel)",
)

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=_ENV, check=True, capture_output=True, text=True
    ).stdout


def _run(script: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args], cwd=cwd, env=_ENV, capture_output=True, text=True
    )


def _repo_with_worktree(tmp_path: Path, branch: str, *, dirty: str | None) -> tuple[Path, Path]:
    """A primary checkout plus a linked worktree on ``branch`` already merged into HEAD.

    ``dirty`` selects the uncommitted state: ``None`` clean, ``"tracked"`` a modified
    tracked file, ``"untracked"`` a new unversioned file.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q", "-b", "main")
    (primary / "f.txt").write_text("base\n")
    _git(primary, "add", "f.txt")
    _git(primary, "commit", "-qm", "base")

    # Branch from main with no new commits, so its HEAD is an ancestor of main's HEAD
    # (MERGED) and it matches the lane pattern used by cleanup_lane.
    wt = tmp_path / "wt"
    _git(primary, "worktree", "add", "-q", str(wt), "-b", branch)

    if dirty == "tracked":
        (wt / "f.txt").write_text("uncommitted edit\n")
    elif dirty == "untracked":
        (wt / "only-copy.txt").write_text("sole artifact\n")
    return primary, wt


# --- sweep_stale_worktrees.sh -------------------------------------------------------

@pytest.mark.parametrize("dirty", ["tracked", "untracked"])
def test_sweep_keeps_merged_but_dirty_worktree(tmp_path: Path, dirty: str) -> None:
    primary, wt = _repo_with_worktree(tmp_path, "codex/followup", dirty=dirty)
    res = _run(_SWEEP, primary, "--dry-run")
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert "KEEP:" in out and str(wt) in out, out
    assert "dirty tree" in out, out
    assert "PRUNE:" not in out, out


def test_sweep_prunes_merged_and_clean_worktree(tmp_path: Path) -> None:
    """Positive control: the gate must not degrade into an unconditional KEEP."""
    primary, wt = _repo_with_worktree(tmp_path, "codex/finished", dirty=None)
    res = _run(_SWEEP, primary, "--dry-run")
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert "PRUNE:" in out and str(wt) in out, out
    assert "tree clean" in out, out


def test_sweep_removes_only_the_clean_worktree_for_real(tmp_path: Path) -> None:
    """Non-dry-run: the dirty worktree survives, the clean one is gone."""
    primary, dirty_wt = _repo_with_worktree(tmp_path, "codex/followup", dirty="tracked")
    clean_wt = tmp_path / "clean"
    _git(primary, "worktree", "add", "-q", str(clean_wt), "-b", "codex/finished")

    res = _run(_SWEEP, primary)
    assert res.returncode == 0, res.stderr
    assert dirty_wt.exists(), "merged-but-dirty worktree was destroyed"
    assert (dirty_wt / "f.txt").read_text() == "uncommitted edit\n"
    assert not clean_wt.exists(), "merged-and-clean worktree should have been pruned"


def test_sweep_never_classifies_the_primary_checkout(tmp_path: Path) -> None:
    """Invoked from a linked worktree, the primary checkout must be skipped, not targeted."""
    primary, wt = _repo_with_worktree(tmp_path, "codex/followup", dirty=None)
    res = _run(_SWEEP, wt, "--dry-run")
    assert res.returncode == 0, res.stderr
    out = res.stdout + res.stderr
    assert str(primary) not in out.replace(str(wt), ""), out
    assert "skipped" in out, out


# --- cleanup_lane_worktrees.sh -----------------------------------------------------

@pytest.mark.parametrize("dirty", ["tracked", "untracked"])
def test_cleanup_lane_keeps_dirty_worktree(tmp_path: Path, dirty: str) -> None:
    primary, wt = _repo_with_worktree(tmp_path, "worktree-sl-1", dirty=dirty)
    res = _run(_CLEANUP, primary, "worktree-*")
    assert res.returncode == 0, res.stderr
    assert wt.exists(), "lane worktree with uncommitted work was destroyed"
    assert "dirty tree" in (res.stdout + res.stderr)


def test_cleanup_lane_removes_clean_worktree(tmp_path: Path) -> None:
    """Positive control: a finished lane worktree is still reclaimed."""
    primary, wt = _repo_with_worktree(tmp_path, "worktree-sl-1", dirty=None)
    res = _run(_CLEANUP, primary, "worktree-*")
    assert res.returncode == 0, res.stderr
    assert not wt.exists(), "clean lane worktree should have been removed"
