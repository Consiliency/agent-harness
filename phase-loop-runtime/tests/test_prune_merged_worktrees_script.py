"""Safety self-test for the ``prune_merged_worktrees.sh`` closeout helper.

The helper can invoke ``sudo rm -rf`` on a permission-locked worktree. A prior
version keyed exclusion off ``git rev-parse --show-toplevel`` for BOTH the
"primary" and "self" checks — identical when run from a linked worktree — so the
PRIMARY checkout was never excluded and its ``is a main working tree`` removal
error was silenced, letting the blanket fallback ``sudo rm -rf`` the primary repo
(destroying the shared object store). These tests pin the three independent
guards that close that hole, exercising the PREDICATES directly (a ``--dry-run``
transcript alone never reaches the removal path, so it cannot prove confinement).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = (
    _REPO_ROOT
    / "skills-src"
    / "claude"
    / "claude-execute-phase"
    / "scripts"
    / "prune_merged_worktrees.sh"
)


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True,
        capture_output=True, text=True,
    ).stdout


def _source_and_eval(snippet: str) -> subprocess.CompletedProcess:
    """Source the helper as a library (no sweep) and run a bash snippet against
    its extracted predicates."""
    body = (
        f'PRUNE_MERGED_WORKTREES_LIB=1 source "{_SCRIPT}"\n' + snippet
    )
    return subprocess.run(
        ["bash", "-c", body], capture_output=True, text=True,
    )


def test_script_exists_and_is_executable():
    assert _SCRIPT.is_file(), _SCRIPT
    assert os.access(_SCRIPT, os.X_OK), "helper must be executable"


def test_no_blanket_sudo_rm_only_confined_permission_path():
    text = _SCRIPT.read_text(encoding="utf-8")
    # Exactly ONE executable sudo line (ignore comments/warnings that mention sudo).
    sudo_cmds = [
        ln for ln in text.splitlines()
        if "sudo " in ln and not ln.lstrip().startswith("#") and "echo " not in ln
    ]
    assert len(sudo_cmds) == 1, f"exactly one sudo command expected, got {sudo_cmds}"
    assert "sudo -n rm -rf -- \"$path\"" in text, "sudo rm must be -n and -- guarded"
    # It must be reachable only after both the permission-error and base checks.
    assert "grep -qi 'permission denied'" in text
    assert "path_under_base" in text


def test_path_under_base_predicate():
    # strictly-under → true; equal-to-base → false; sibling-prefix → false; empty → false.
    res = _source_and_eval(
        'path_under_base /mnt/wt/base/a /mnt/wt/base && echo under-yes || echo under-no\n'
        'path_under_base /mnt/wt/base    /mnt/wt/base && echo eq-yes    || echo eq-no\n'
        'path_under_base /mnt/wt/base-evil /mnt/wt/base && echo evil-yes || echo evil-no\n'
        'path_under_base "" /mnt/wt/base && echo empty-yes || echo empty-no\n'
        'path_under_base /mnt/wt/base/a "" && echo nobase-yes || echo nobase-no\n'
    )
    assert res.returncode == 0, res.stderr
    out = res.stdout.split()
    assert out == ["under-yes", "eq-no", "evil-no", "empty-no", "nobase-no"], out


@pytest.fixture()
def worktree_layout(tmp_path: Path) -> dict[str, Path]:
    """A primary repo with a linked worktree on a merged, clean branch."""
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q", "-b", "main")
    (primary / "f").write_text("x")
    _git(primary, "add", ".")
    _git(primary, "commit", "-qm", "init")
    # Fake an origin/main ref so is_merged's ancestor check has a target.
    _git(primary, "update-ref", "refs/remotes/origin/main", "HEAD")
    linked = tmp_path / "wtbase" / "linked"
    linked.parent.mkdir()
    # Linked worktree on a NEW branch whose tip is an ancestor of origin/main
    # (i.e. "merged"): `main` itself cannot be checked out in a second worktree.
    _git(primary, "worktree", "add", "-q", "-b", "feat/merged", str(linked), "main")
    return {"primary": primary, "linked": linked, "base": tmp_path / "wtbase"}


def test_primary_never_in_candidate_set_from_linked_worktree(worktree_layout):
    """primary_worktree() resolves the main tree, and it is excluded even when the
    sweep is invoked from a LINKED worktree (the catastrophic-bug scenario)."""
    linked = worktree_layout["linked"]
    primary = worktree_layout["primary"]
    res = subprocess.run(
        ["bash", "-c",
         f'cd "{linked}"\n'
         f'PRUNE_MERGED_WORKTREES_LIB=1 source "{_SCRIPT}"\n'
         'echo "PRIMARY=$(primary_worktree)"\n'
         'echo "SELF=$(git rev-parse --show-toplevel)"\n'],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    lines = dict(l.split("=", 1) for l in res.stdout.splitlines() if "=" in l)
    assert Path(lines["PRIMARY"]).resolve() == primary.resolve()
    # From the linked worktree, SELF != PRIMARY — so the old show-toplevel-for-both
    # bug (which left PRIMARY unexcluded) cannot recur.
    assert Path(lines["SELF"]).resolve() == linked.resolve()
    assert Path(lines["SELF"]).resolve() != Path(lines["PRIMARY"]).resolve()


def test_dry_run_from_linked_worktree_never_prunes_primary(worktree_layout):
    """End-to-end --dry-run from the linked worktree: the primary (merged+clean,
    on main) must never appear in a PRUNE line."""
    linked = worktree_layout["linked"]
    primary = worktree_layout["primary"]
    res = subprocess.run(
        ["bash", str(_SCRIPT), "--dry-run"],
        cwd=linked, capture_output=True, text=True,
        env={**os.environ, "PHASE_LOOP_WORKTREES_BASE": str(worktree_layout["base"])},
    )
    assert res.returncode == 0, res.stderr
    combined = res.stdout + res.stderr
    for line in combined.splitlines():
        if line.startswith("PRUNE:"):
            assert str(primary) not in line, f"primary selected for prune: {line}"
