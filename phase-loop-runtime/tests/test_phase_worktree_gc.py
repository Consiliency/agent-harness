"""ah#353 — crash-residual per-phase worktree GC.

``teardown_phase_worktree`` runs only from a ``finally``: it survives an
exception but not a SIGKILL/OOM/timeout, so a hard-killed run leaks its worktree
DIRECTORY forever. ``_gc_stale_phase_worktrees`` sweeps those on the next
``create_phase_worktree``, age-gated so a concurrent run is never touched and
guarded so it NEVER deletes real work.

Every test below names — in its docstring — the mutation to the production code
that must make it fail, and that mutation was run to confirm the test dies (see
the PR body). A test that cannot fail proves nothing; this repo has shipped that
class before.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from phase_loop_runtime.phase_worktree_executor import (
    _gc_stale_phase_worktrees,
    create_phase_worktree,
    phase_temp_branch,
    resolve_base_sha,
    teardown_phase_worktree,
)
from phase_loop_test_utils import make_repo

# lane_worktree_root honours /mnt/workspace when it exists (true on CI/fleet
# hosts). Point every test's worktrees at a NON-EXISTENT mount so the root falls
# back to repo.parent (the pytest tmp_path) and tests never touch the shared
# volume.
_NO_MOUNT_KW = {"workspace_mount": Path("/does/not/exist/for/tests")}


def _current_branch(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_stale(path: Path, *, age_s: int = 48 * 3600) -> None:
    """Backdate the worktree directory mtime so the age gate treats it as
    crash-residual rather than a concurrent run's fresh worktree."""
    old = os.stat(path).st_mtime - age_s
    os.utime(path, (old, old))


def _commit_in_worktree(worktree: Path, rel: str, content: str, message: str) -> None:
    (worktree / rel).write_text(content)
    subprocess.run(["git", "-C", str(worktree), "add", rel], check=True)
    subprocess.run(
        ["git", "-C", str(worktree), "commit", "-q", "-m", message],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def _worktree_registered(repo: Path, path: Path) -> bool:
    out = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return str(path) in out


def test_gc_removes_stale_clean_merged_worktree(tmp_path):
    """Positive path: a stale, clean, fully-merged phase worktree is reclaimed.

    Mutation that must kill this: make ``_gc_stale_phase_worktrees`` a no-op
    (``return records`` immediately) — the worktree survives and the assert on
    absence fails.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    handle = create_phase_worktree(
        repo, phase="extract", target_branch=branch, base_sha=base, **_NO_MOUNT_KW
    )
    assert handle.worktree_path.exists()
    _make_stale(handle.worktree_path)

    records = _gc_stale_phase_worktrees(repo)

    assert not handle.worktree_path.exists()
    assert not _worktree_registered(repo, handle.worktree_path)
    assert any(
        r["action"] == "removed" and r["branch"] == handle.temp_branch for r in records
    )


def test_gc_preserves_dirty_worktree(tmp_path):
    """Never delete work — uncommitted changes: a stale worktree with an
    untracked/modified file is SKIPPED, not deleted.

    Mutation that must kill this: make ``_worktree_has_uncommitted_changes``
    always return ``False`` — the dirty worktree is wrongly reclaimed and the
    assert that it still exists fails.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    handle = create_phase_worktree(
        repo, phase="extract", target_branch=branch, base_sha=base, **_NO_MOUNT_KW
    )
    # Killed child left verified-but-uncommitted work in the tree.
    (handle.worktree_path / "unsaved_work.py").write_text("value = 42\n")
    _make_stale(handle.worktree_path)

    records = _gc_stale_phase_worktrees(repo)

    assert handle.worktree_path.exists(), "dirty worktree must never be deleted"
    assert (handle.worktree_path / "unsaved_work.py").read_text() == "value = 42\n"
    assert any(
        r["reason"] == "uncommitted changes" and r["branch"] == handle.temp_branch
        for r in records
    )
    teardown_phase_worktree(repo, handle)


def test_gc_preserves_worktree_with_unmerged_commits(tmp_path):
    """Never delete work — unmerged commits: a stale worktree whose tree is CLEAN
    but whose temp branch carries a self-commit not in the integration target is
    SKIPPED.

    Mutation that must kill this: make the ancestor check pass unconditionally
    (``if not head:`` instead of ``if not head or not _is_ancestor(...)``) — the
    unmerged worktree is wrongly reclaimed and its self-commit lost; the assert
    that it still exists fails.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    handle = create_phase_worktree(
        repo, phase="extract", target_branch=branch, base_sha=base, **_NO_MOUNT_KW
    )
    # Child committed work onto its temp branch; teardown/integration never ran.
    _commit_in_worktree(
        handle.worktree_path, "committed_work.py", "done = True\n", "phase work"
    )
    # Tree is CLEAN (committed) — only the unmerged-commit guard can save it.
    assert (
        subprocess.run(
            ["git", "-C", str(handle.worktree_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    _make_stale(handle.worktree_path)

    records = _gc_stale_phase_worktrees(repo)

    assert handle.worktree_path.exists(), "unmerged commits must never be deleted"
    assert any(
        r["reason"] == "unmerged commits" and r["branch"] == handle.temp_branch
        for r in records
    )
    teardown_phase_worktree(repo, handle)


def test_gc_preserves_fresh_concurrent_worktree(tmp_path):
    """Age gate: a clean, merged phase worktree that is NOT stale (a concurrent
    run's fresh worktree) is left untouched.

    Mutation that must kill this: delete the ``if mtime >= cutoff: continue``
    guard — the fresh worktree is swept and the assert that it survives fails.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    handle = create_phase_worktree(
        repo, phase="extract", target_branch=branch, base_sha=base, **_NO_MOUNT_KW
    )
    # Do NOT backdate — clean and merged, but freshly created.

    records = _gc_stale_phase_worktrees(repo)

    assert handle.worktree_path.exists(), "a concurrent run's fresh worktree must survive"
    assert not any(r["action"] == "removed" for r in records)
    teardown_phase_worktree(repo, handle)


def test_gc_ignores_non_phase_worktree(tmp_path):
    """Identity gate: a stale, clean worktree on a NON-sched branch (a human's
    worktree / a foreign sibling) is never a candidate.

    Mutation that must kill this: drop the
    ``not branch.startswith(_TEMP_BRANCH_PREFIX)`` filter — the human worktree is
    swept and the ``human_wt.exists()`` assert fails.

    The identity filter is isolated as the SOLE guard on the deletion path: the
    human worktree is deliberately CLEAN and its HEAD is an ancestor of the merge
    target (``origin/main`` is set to HEAD, and the worktree is created at HEAD),
    so with the prefix filter dropped every OTHER guard passes and the worktree is
    deleted. Without this setup the ancestor guard would incidentally save it
    (``origin/main`` is unresolvable in a fresh ``make_repo``), and the mutation
    would kill only the ``records`` bookkeeping — not the deletion claim.
    """
    repo = make_repo(tmp_path)
    # Make the default merge target resolvable and equal to HEAD, so the ancestor
    # guard cannot be what preserves the worktree.
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
        capture_output=True,
    )
    human_wt = tmp_path / "human-worktree"
    # Created at HEAD: clean tree, head == origin/main tip (fully "merged").
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-b", "feature/human", str(human_wt), "HEAD"],
        check=True,
        capture_output=True,
    )
    _make_stale(human_wt)

    records = _gc_stale_phase_worktrees(repo)

    assert human_wt.exists(), "a non-sched worktree must never be touched"
    assert records == []


def test_create_phase_worktree_reclaims_stale_and_creates(tmp_path):
    """Callsite wiring (no stub): calling ``create_phase_worktree`` for real
    reclaims a pre-existing stale sibling AND creates the new worktree.

    The stub-free positive control: the assert that the NEW worktree exists and
    is checked out proves the GC callsite did not break creation. Mutation that
    must kill this: remove the ``_gc_stale_phase_worktrees(repo)`` call from
    ``create_phase_worktree`` — the stale sibling survives and its absence assert
    fails.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    stale = create_phase_worktree(
        repo, phase="extract", target_branch=branch, base_sha=base, **_NO_MOUNT_KW
    )
    _make_stale(stale.worktree_path)

    # Real call for a DIFFERENT phase — its top-of-function GC sweeps the sibling.
    fresh = create_phase_worktree(
        repo, phase="import", target_branch=branch, base_sha=base, **_NO_MOUNT_KW
    )

    # Positive control: creation succeeded.
    assert fresh.worktree_path.exists()
    assert _current_branch(fresh.worktree_path) == fresh.temp_branch
    assert fresh.temp_branch == phase_temp_branch(branch, "IMPORT")
    # Reclamation: the stale sibling is gone.
    assert not stale.worktree_path.exists()
    assert not _worktree_registered(repo, stale.worktree_path)

    teardown_phase_worktree(repo, fresh)


def test_locked_worktree_records_skipped_not_removed(tmp_path):
    """A refused removal must NOT be recorded as "removed", and must NOT delete the branch.

    git legitimately refuses to remove a locked worktree. Before the removal was
    verified, the sweep appended ``action: "removed"`` regardless and then ran
    ``branch -D`` -- a false record, and a branch delete that would strand a
    worktree still on disk. The branch is the only handle on that work.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    stale = create_phase_worktree(
        repo, phase="extract", target_branch=branch, base_sha=base, **_NO_MOUNT_KW
    )
    _make_stale(stale.worktree_path)
    # Lock it: git will now refuse --force removal.
    subprocess.run(["git","-C",str(repo),"worktree","lock",str(stale.worktree_path)], check=True)

    records = _gc_stale_phase_worktrees(repo)

    entry = next((r for r in records if r["path"] == str(stale.worktree_path)), None)
    assert entry is not None, "the locked candidate must still be reported"
    assert entry["action"] == "skipped", f"refused removal recorded as {entry['action']!r}"
    # The worktree survived, so its recovery branch must survive too.
    assert stale.worktree_path.exists()
    branches = subprocess.run(["git","-C",str(repo),"branch","--list",stale.temp_branch],
                              capture_output=True, text=True).stdout
    assert stale.temp_branch in branches, "branch deleted despite failed removal"

    subprocess.run(["git","-C",str(repo),"worktree","unlock",str(stale.worktree_path)], check=False)
