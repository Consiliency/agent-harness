"""v45 SCHED — per-phase worktree lifecycle (phase_worktree_executor).

Scenario tests on throwaway git repos proving the isolation contract that makes
concurrent cross-phase dispatch safe:
  * two phases run in separate worktrees on separate temp branches;
  * disjoint-file results merge back conflict-free regardless of order;
  * a child that commits nothing integrates as a no-op;
  * an overlapping (same-file) change surfaces a conflict instead of corrupting
    the pipeline branch (the gate-bypass safety net);
  * teardown removes both the worktree and the temp branch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from phase_loop_runtime.phase_worktree_executor import (
    PhaseWorktreeHandle,
    create_phase_worktree,
    integrate_phase_worktree,
    phase_temp_branch,
    resolve_base_sha,
    teardown_phase_worktree,
)
from phase_loop_test_utils import make_repo


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def _commit_in_worktree(worktree: Path, rel: str, content: str, message: str) -> None:
    target = worktree / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    subprocess.run(["git", "-C", str(worktree), "add", rel], check=True)
    subprocess.run(
        ["git", "-C", str(worktree), "commit", "-q", "-m", message],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def test_create_isolates_phase_on_its_own_branch(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    handle = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)

    assert handle.worktree_path.exists()
    assert handle.temp_branch == phase_temp_branch(branch, "EXTRACT")
    # The worktree is checked out on the temp branch, not the pipeline branch.
    assert _current_branch(handle.worktree_path) == handle.temp_branch
    # The main worktree stays on the pipeline branch.
    assert _current_branch(repo) == branch
    teardown_phase_worktree(repo, handle)


def test_two_phases_get_distinct_worktrees(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    a = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    b = create_phase_worktree(repo, phase="import", target_branch=branch, base_sha=base)

    assert a.worktree_path != b.worktree_path
    assert a.temp_branch != b.temp_branch
    assert a.worktree_path.exists() and b.worktree_path.exists()
    teardown_phase_worktree(repo, a)
    teardown_phase_worktree(repo, b)


def test_disjoint_results_merge_back_conflict_free(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    a = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    b = create_phase_worktree(repo, phase="import", target_branch=branch, base_sha=base)
    _commit_in_worktree(a.worktree_path, "src/extract.py", "extract = True\n", "extract work")
    _commit_in_worktree(b.worktree_path, "src/import_.py", "imported = True\n", "import work")

    res_a = integrate_phase_worktree(repo, a)
    res_b = integrate_phase_worktree(repo, b)

    assert res_a.integrated and not res_a.conflict
    assert res_b.integrated and not res_b.conflict
    # Both phases' files are now on the pipeline branch in the main worktree.
    assert (repo / "src" / "extract.py").read_text() == "extract = True\n"
    assert (repo / "src" / "import_.py").read_text() == "imported = True\n"
    teardown_phase_worktree(repo, a)
    teardown_phase_worktree(repo, b)


def test_integration_is_noop_without_commits(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    handle = create_phase_worktree(repo, phase="memory", target_branch=branch, base_sha=base)
    res = integrate_phase_worktree(repo, handle)

    assert res.integrated
    assert res.had_commits is False
    assert resolve_base_sha(repo) == base  # pipeline tip unmoved
    teardown_phase_worktree(repo, handle)


def test_overlapping_change_surfaces_conflict_and_aborts(tmp_path):
    # Safety net: if the ownership-disjointness gate were bypassed and two phases
    # edited the same file divergently, integration must refuse, not corrupt.
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    # Seed a shared file on the pipeline branch so both edits diverge from it.
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "shared.py").write_text("value = 0\n")
    _git(repo, "add", "src/shared.py")
    _git(repo, "commit", "-q", "-m", "seed shared")
    base = resolve_base_sha(repo)

    a = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    b = create_phase_worktree(repo, phase="import", target_branch=branch, base_sha=base)
    _commit_in_worktree(a.worktree_path, "src/shared.py", "value = 1\n", "extract edits shared")
    _commit_in_worktree(b.worktree_path, "src/shared.py", "value = 2\n", "import edits shared")

    res_a = integrate_phase_worktree(repo, a)
    res_b = integrate_phase_worktree(repo, b)

    assert res_a.integrated  # first merge fast-forwards cleanly
    assert res_b.conflict and not res_b.integrated
    assert "src/shared.py" in res_b.conflicted_paths
    # The aborted merge left the pipeline branch on phase A's value, not corrupted.
    assert (repo / "src" / "shared.py").read_text() == "value = 1\n"
    assert _current_branch(repo) == branch
    teardown_phase_worktree(repo, a)
    teardown_phase_worktree(repo, b)


def test_teardown_removes_worktree_and_branch(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    handle = create_phase_worktree(repo, phase="verify", target_branch=branch, base_sha=base)
    path = handle.worktree_path
    teardown_phase_worktree(repo, handle)

    assert not path.exists()
    listed = _git(repo, "branch", "--list", handle.temp_branch).stdout.strip()
    assert listed == ""


def test_create_is_idempotent_after_stale_worktree(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    _commit_in_worktree(first.worktree_path, "src/extract.py", "x = 1\n", "stale work")
    # Simulate a crashed prior run: do NOT tear down; recreate the same phase.
    second = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)

    assert second.worktree_path == first.worktree_path
    assert second.worktree_path.exists()
    # Recreated fresh at base: the stale commit's file is gone.
    assert not (second.worktree_path / "src" / "extract.py").exists()
    teardown_phase_worktree(repo, second)


def test_handle_roundtrips_fields(tmp_path):
    handle = PhaseWorktreeHandle(
        phase="EXTRACT",
        worktree_path=Path("/tmp/wt"),
        temp_branch="phase-loop/sched/main/EXTRACT",
        target_branch="main",
        base_sha="deadbeef",
    )
    assert handle.phase == "EXTRACT"
    assert handle.target_branch == "main"
