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

import os
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from phase_loop_runtime.phase_worktree_executor import (
    PhaseWorktreeHandle,
    create_phase_worktree,
    integrate_phase_worktree,
    phase_temp_branch,
    resolve_base_sha,
    teardown_phase_worktree,
    transfer_phase_worktree_dirty,
)
from phase_loop_test_utils import make_repo


SCHED_SKIP_REASON = "SCHED RED suite inactive; set PHASE_LOOP_TDD_EXPECT_SCHED=1"
SCHED_RECOVERY_DECISION = "docs/research/sched-worktree-recovery-ratification.md"


def sched_red_active() -> bool:
    return os.environ.get("PHASE_LOOP_TDD_EXPECT_SCHED") == "1"


def require_sched_red(test):
    return pytest.mark.skipif(not sched_red_active(), reason=SCHED_SKIP_REASON)(test)


SCHED_SL2_NODEIDS = (
    "phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py::test_declared_work_unit_kind_is_authoritative_at_lane_selection",
    "phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py::test_no_diff_result_requires_an_explicit_artifact_verification_skip",
    "phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py::test_nested_dispatch_lock_retains_one_explicit_run_identity",
    "phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py::test_declared_phase_reducer_kind_bypasses_executor_heuristic",
    "phase-loop-runtime/tests/test_phase_loop_runner.py::test_nested_runner_dispatch_threads_one_run_identity",
    "phase-loop-runtime/tests/test_phase_loop_launcher.py::test_launcher_accepts_explicit_nonserialized_lease_authority",
    "phase-loop-runtime/tests/test_workerpool_failure_isolation.py::test_blocked_worker_preserves_recoverable_generation_metadata",
    "phase-loop-runtime/tests/test_workerpool_parallel.py::test_worker_pool_propagates_run_identity_and_lease_authority",
    "phase-loop-runtime/tests/test_workerpool_worktree_alloc.py::test_phase_wave_assignments_keep_creator_generation_identity",
    "phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py::test_real_diff_never_skips_artifact_dependent_verification",
    "phase-loop-runtime/tests/test_phase_loop_v45_sched.py::test_staged_planner_artifact_survives_parent_reduction",
    "phase-loop-runtime/tests/test_workerpool_failure_isolation.py::test_manual_or_blocked_closeout_preserves_staged_and_untracked_bytes",
)
SCHED_SL4_NODEIDS = (
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_create_preserves_committed_generation_and_mints_replacement",
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_create_preserves_dirty_and_untracked_generation_bytes_and_ref",
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_ignored_handoff_only_generation_is_preserved",
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_held_live_lease_prevents_reclamation",
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_post_scan_mutation_prevents_reclamation",
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_lease_identity_drift_preserves_generation",
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_generation_path_and_branch_collisions_never_reuse_preserved_generation",
    "phase-loop-runtime/tests/test_phase_worktree_executor.py::test_sched_released_empty_generation_is_reclaimed_and_fresh_generation_launches",
)
SCHED_JOINED_NODEIDS = (
    "phase-loop-runtime/tests/test_phase_loop_v45_sched.py::test_scheduler_consumes_creator_returned_worktree_handle",
    "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::test_supervisor_retains_lease_after_executor_parent_exits[pass_fds]",
    "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::test_supervisor_retains_lease_after_executor_parent_exits[subreaper_session]",
    "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::test_supervisor_retains_lease_after_executor_parent_exits[process_tree_reaping]",
)
SCHED_RED_NODEIDS = SCHED_SL2_NODEIDS + SCHED_SL4_NODEIDS + SCHED_JOINED_NODEIDS

assert len(SCHED_SL2_NODEIDS) == 12
assert len(SCHED_SL4_NODEIDS) == 8
assert len(SCHED_JOINED_NODEIDS) == 4
assert len(SCHED_RED_NODEIDS) == 24
assert len(SCHED_RED_NODEIDS) == len(set(SCHED_RED_NODEIDS))
assert not (set(SCHED_SL2_NODEIDS) & set(SCHED_SL4_NODEIDS))
assert not (set(SCHED_SL2_NODEIDS) & set(SCHED_JOINED_NODEIDS))
assert not (set(SCHED_SL4_NODEIDS) & set(SCHED_JOINED_NODEIDS))


def _in_head(repo: Path, rel: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{rel}"],
            capture_output=True,
        ).returncode
        == 0
    )


def _status(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
    ).stdout


@contextmanager
def _isolated_worktree_root(tmp_path: Path):
    """Pin per-phase worktrees under ``tmp_path`` instead of the shared
    ``<WORKTREE-PATH-REDACTED>`` volume, so transfer tests don't collide on or
    pollute that directory across runs."""

    def fake_path(repo_arg, *, branch, lane_id, project=None, workspace_mount=None):
        return tmp_path / "wt" / f"{branch}-{lane_id}"

    with patch(
        "phase_loop_runtime.phase_worktree_executor.lane_worktree_path", side_effect=fake_path
    ):
        yield


@pytest.fixture(autouse=True)
def _per_test_worktree_root(tmp_path: Path):
    """Keep every lifecycle case off the shared deterministic workspace path."""

    with _isolated_worktree_root(tmp_path):
        yield


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


def _assert_preserved(repo: Path, handle, expected: dict[str, bytes]) -> None:
    """A preserved generation must retain its path, ref, and every byte.

    This deliberately checks all three independent recovery handles.  A branch
    alone is not enough for untracked/ignored bytes, while a path alone is not
    enough once the worker has crashed and only the temporary ref survives.
    """

    assert handle.worktree_path.exists()
    assert _git(repo, "show-ref", "--verify", f"refs/heads/{handle.temp_branch}").returncode == 0
    for rel, content in expected.items():
        assert (handle.worktree_path / rel).read_bytes() == content


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
    # Keep this legacy control byte-empty.  It proves only that the historical
    # implementation can recreate an occupied fixture at its requested base;
    # preservation and collision behavior belong to the activated SCHED case.
    second = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)

    assert second.worktree_path.exists()
    assert second.base_sha == base
    teardown_phase_worktree(repo, second)


def test_transfer_brings_dirty_uncommitted_work_to_main_unstaged(tmp_path):
    # The real-executor case integrate_phase_worktree cannot handle: the child
    # left work DIRTY (uncommitted) in its worktree. Transfer must land it on
    # main's working tree, UNSTAGED and UNCOMMITTED, so the parent closeout's
    # selective `git add -- <owned>` still governs what gets committed.
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    # Dirty, untracked file in the worktree — never committed.
    (handle.worktree_path / "src").mkdir(parents=True, exist_ok=True)
    (handle.worktree_path / "src" / "extract.py").write_text("extract = True\n")

    res = transfer_phase_worktree_dirty(repo, handle)

    assert res.had_changes and res.applied and not res.conflict
    # Work is present on main's working tree...
    assert (repo / "src" / "extract.py").read_text() == "extract = True\n"
    # ...but NOT committed (closeout will commit it)...
    assert not _in_head(repo, "src/extract.py")
    assert resolve_base_sha(repo) == base  # pipeline tip unmoved
    # ...and NOT staged (so the ownership-gated selective `git add` still applies).
    assert "A  src/extract.py" not in _status(repo)
    assert "?? src/extract.py" in _status(repo)
    teardown_phase_worktree(repo, handle)


def test_transfer_is_noop_when_child_left_nothing(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="memory", target_branch=branch, base_sha=base)
    res = transfer_phase_worktree_dirty(repo, handle)

    assert res.had_changes is False and res.applied is True
    assert _status(repo) == ""  # main untouched
    teardown_phase_worktree(repo, handle)


def test_transfer_also_carries_child_self_committed_work(tmp_path):
    # A child that self-commits (the complete-without-dirty path) still has its
    # work carried to main — as unstaged changes — via the base..temp delta.
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="import", target_branch=branch, base_sha=base)
    _commit_in_worktree(handle.worktree_path, "src/import_.py", "imported = True\n", "import work")

    res = transfer_phase_worktree_dirty(repo, handle)

    assert res.had_changes and res.applied
    assert (repo / "src" / "import_.py").read_text() == "imported = True\n"
    assert not _in_head(repo, "src/import_.py")  # unstaged on main, not yet committed
    teardown_phase_worktree(repo, handle)


def test_transfer_preserves_crlf_and_non_utf8_bytes(tmp_path):
    # The patch must survive verbatim: a text-mode (str) diff→apply pipe strips
    # \r from CRLF files (spurious conflict or silent LF rewrite) and crashes on
    # non-UTF-8 "text" blobs (high bytes, no NUL → git inlines raw, not base85).
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="bytesfidelity", target_branch=branch, base_sha=base)
    crlf = b"line1\r\nline2\r\nline3\r\n"
    raw = bytes(range(0x80, 0x100)) * 4  # high bytes, no 0x00 → git treats as text
    (handle.worktree_path / "src").mkdir(parents=True, exist_ok=True)
    (handle.worktree_path / "src" / "crlf.txt").write_bytes(crlf)
    (handle.worktree_path / "src" / "raw.dat").write_bytes(raw)

    res = transfer_phase_worktree_dirty(repo, handle)

    assert res.had_changes and res.applied and not res.conflict
    assert (repo / "src" / "crlf.txt").read_bytes() == crlf  # \r preserved
    assert (repo / "src" / "raw.dat").read_bytes() == raw  # raw bytes intact
    teardown_phase_worktree(repo, handle)


def test_transfer_carries_deletions(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    # Seed a file at base that the child deletes.
    (repo / "todelete.txt").write_text("bye\n")
    _git(repo, "add", "todelete.txt")
    _git(repo, "commit", "-q", "-m", "seed deletion target")
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="deletion", target_branch=branch, base_sha=base)
    (handle.worktree_path / "todelete.txt").unlink()  # dirty deletion in the worktree

    res = transfer_phase_worktree_dirty(repo, handle)

    assert res.had_changes and res.applied
    assert not (repo / "todelete.txt").exists()  # deletion carried to main (unstaged)
    assert " D todelete.txt" in _status(repo)
    teardown_phase_worktree(repo, handle)


def test_transfer_conflict_preserves_work_on_temp_branch_and_leaves_main_intact(tmp_path):
    # Gate-bypass safety net: if a transferred patch cannot apply (a sibling
    # touched the same file), git apply is atomic — main is left untouched and the
    # work survives on the temp branch for diagnosis.
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "shared.py").write_text("value = 0\n")
    _git(repo, "add", "src/shared.py")
    _git(repo, "commit", "-q", "-m", "seed shared")
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    (handle.worktree_path / "src" / "shared.py").write_text("value = 1\n")  # dirty edit
    # Main diverges from base on the same file AFTER the worktree branched.
    (repo / "src" / "shared.py").write_text("value = 99\n")
    _git(repo, "add", "src/shared.py")
    _git(repo, "commit", "-q", "-m", "main diverges shared")

    res = transfer_phase_worktree_dirty(repo, handle)

    assert res.conflict and not res.applied and res.had_changes
    # Main's content is untouched by the failed apply.
    assert (repo / "src" / "shared.py").read_text() == "value = 99\n"
    # Work preserved on the temp branch (the transport commit).
    revs = _git(repo, "rev-list", f"{base}..{handle.temp_branch}").stdout.strip()
    assert revs != ""
    teardown_phase_worktree(repo, handle, delete_branch=False)


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


@require_sched_red
def test_sched_create_preserves_committed_generation_and_mints_replacement(tmp_path):
    # SCHED_RECOVERY_DECISION: docs/research/sched-worktree-recovery-ratification.md
    assert SCHED_RECOVERY_DECISION == "docs/research/sched-worktree-recovery-ratification.md"
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
        _commit_in_worktree(first.worktree_path, "src/recoverable.py", "kept = True\n", "recoverable")
        preserved_commit = resolve_base_sha(first.worktree_path)
        assert preserved_commit != base
        assert _git(repo, "rev-parse", first.temp_branch).stdout.strip() == preserved_commit
        replacement = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    assert replacement.generation != first.generation
    assert replacement.worktree_path != first.worktree_path
    assert replacement.temp_branch != first.temp_branch
    assert _git(repo, "rev-parse", first.temp_branch).stdout.strip() == preserved_commit
    assert _git(first.worktree_path, "rev-parse", "HEAD").stdout.strip() == preserved_commit
    _assert_preserved(repo, first, {"src/recoverable.py": b"kept = True\n"})


@require_sched_red
def test_sched_create_preserves_dirty_and_untracked_generation_bytes_and_ref(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    dirty = b"dirty-but-recoverable\n"
    untracked = b"untracked-but-recoverable\x00bytes"
    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
        (first.worktree_path / "tracked.txt").write_bytes(dirty)
        target = first.worktree_path / "scratch" / "untracked.bin"
        target.parent.mkdir()
        target.write_bytes(untracked)
        link_target = first.worktree_path / "link-target.bin"
        link_target.write_bytes(b"symlink target bytes\n")
        symlink = first.worktree_path / "recoverable-link"
        symlink.symlink_to(link_target.name)
        fifo = first.worktree_path / "recoverable.fifo"
        os.mkfifo(fifo)
        replacement = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    assert replacement.generation != first.generation
    _assert_preserved(
        repo,
        first,
        {
            "tracked.txt": dirty,
            "scratch/untracked.bin": untracked,
            "link-target.bin": b"symlink target bytes\n",
        },
    )
    assert (first.worktree_path / "recoverable-link").is_symlink()
    assert os.readlink(first.worktree_path / "recoverable-link") == "link-target.bin"
    assert stat.S_ISFIFO((first.worktree_path / "recoverable.fifo").lstat().st_mode)


@require_sched_red
def test_sched_ignored_handoff_only_generation_is_preserved(tmp_path):
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text(".dev-skills/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore handoffs")
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
        handoff = first.worktree_path / ".dev-skills" / "handoffs" / "resume.md"
        handoff.parent.mkdir(parents=True)
        handoff.write_text("recover this generation\n", encoding="utf-8")
        replacement = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
    assert replacement.generation != first.generation
    _assert_preserved(repo, first, {".dev-skills/handoffs/resume.md": b"recover this generation\n"})


@require_sched_red
def test_sched_held_live_lease_prevents_reclamation(tmp_path):
    import phase_loop_runtime.phase_worktree_executor as executor

    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
        (handle.worktree_path / "keep.txt").write_bytes(b"held lease keeps this generation\n")
        result = executor.reclaim_phase_worktree(repo, handle)
    assert result.reclaimed is False
    assert result.reason == "live_lease"
    _assert_preserved(repo, handle, {"keep.txt": b"held lease keeps this generation\n"})


@require_sched_red
def test_sched_post_scan_mutation_prevents_reclamation(tmp_path):
    import phase_loop_runtime.phase_worktree_executor as executor

    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
        handle.lease_authority.close()
        original_inventory = executor._stable_inventory
        mutation_ran = False

        def mutate_between_stable_inventories(*args, **kwargs):
            nonlocal mutation_ran
            observed = original_inventory(*args, **kwargs)
            if not mutation_ran:
                mutation_ran = True
                (handle.worktree_path / "late.txt").write_bytes(b"appeared between stable inventories\n")
            return observed

        with patch.object(executor, "_stable_inventory", side_effect=mutate_between_stable_inventories):
            result = executor.reclaim_phase_worktree(repo, handle)
    assert mutation_ran, "the between-inventory mutation anchor must execute"
    assert result.reclaimed is False
    assert result.reason == "inventory_changed"
    _assert_preserved(repo, handle, {"late.txt": b"appeared between stable inventories\n"})


@require_sched_red
def test_sched_lease_identity_drift_preserves_generation(tmp_path):
    import phase_loop_runtime.phase_worktree_executor as executor

    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    with _isolated_worktree_root(tmp_path):
        handle = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
        (handle.worktree_path / "identity.txt").write_bytes(b"identity-bound recovery\n")
        drifted = replace(handle, lease_authority=handle.lease_authority.with_identity("foreign-lease"))
        result = executor.reclaim_phase_worktree(repo, drifted)
    assert result.reclaimed is False
    assert result.reason == "lease_identity_drift"
    _assert_preserved(repo, handle, {"identity.txt": b"identity-bound recovery\n"})

    # Preserve-on-doubt is part of this frozen node: a failed inventory and an
    # unsupported filesystem capability are both uncertainty, never permission
    # to remove a released generation.
    uncertain = create_phase_worktree(repo, phase="import", target_branch=branch, base_sha=resolve_base_sha(repo))
    uncertain.lease_authority.close()
    (uncertain.worktree_path / "uncertain.txt").write_bytes(b"inventory uncertainty\n")
    with patch.object(executor, "_stable_inventory", side_effect=OSError("simulated inventory failure")):
        inventory_error = executor.reclaim_phase_worktree(repo, uncertain)
    assert inventory_error.reclaimed is False
    assert inventory_error.reason == "inventory_error"
    _assert_preserved(repo, uncertain, {"uncertain.txt": b"inventory uncertainty\n"})

    unsupported = create_phase_worktree(repo, phase="verify", target_branch=branch, base_sha=resolve_base_sha(repo))
    unsupported.lease_authority.close()
    (unsupported.worktree_path / "unsupported.txt").write_bytes(b"filesystem capability unknown\n")
    with patch.object(executor, "_supports_safe_reclamation", return_value=False):
        unsupported_result = executor.reclaim_phase_worktree(repo, unsupported)
    assert unsupported_result.reclaimed is False
    assert unsupported_result.reason == "unsupported_filesystem"
    _assert_preserved(repo, unsupported, {"unsupported.txt": b"filesystem capability unknown\n"})


@require_sched_red
def test_sched_generation_path_and_branch_collisions_never_reuse_preserved_generation(tmp_path):
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
        _commit_in_worktree(first.worktree_path, "committed.txt", "preserved commit\n", "preserve generation")
        second = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
    assert (second.generation, second.worktree_path, second.temp_branch) != (first.generation, first.worktree_path, first.temp_branch)
    _assert_preserved(repo, first, {"committed.txt": b"preserved commit\n"})


@require_sched_red
def test_sched_released_empty_generation_is_reclaimed_and_fresh_generation_launches(tmp_path):
    import inspect

    import phase_loop_runtime.phase_worktree_executor as executor

    repo = make_repo(tmp_path)
    branch = _current_branch(repo)

    def branch_is_addressable(handle):
        return _git(
            repo,
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{handle.temp_branch}",
            check=False,
        ).returncode == 0

    with _isolated_worktree_root(tmp_path):
        assert "supervisor_receipt" in inspect.signature(teardown_phase_worktree).parameters
        invalid_receipt_generations = []
        for status in ("missing", "malformed", "stale", "failed", "blocked", "manual", "ambiguous"):
            preserved = create_phase_worktree(
                repo,
                phase=f"preserve-{status}",
                target_branch=branch,
                base_sha=resolve_base_sha(repo),
            )
            receipt = None
            if status == "malformed":
                receipt = {"generation": preserved.generation}
            elif status == "stale":
                receipt = {
                    "generation": f"{preserved.generation}-stale",
                    "process_tree_empty": True,
                    "receipt_binding": f"{preserved.lease_authority.identity}-stale",
                    "terminal_status": "complete",
                }
            elif status != "missing":
                receipt = {
                    "generation": preserved.generation,
                    "process_tree_empty": True,
                    "receipt_binding": preserved.lease_authority.identity,
                    "terminal_status": status,
                }
            invalid_receipt_generations.append((status, preserved, receipt))

        invalid_removal_attempts = []

        def invalid_receipt_must_not_remove(repo_arg, path):
            invalid_removal_attempts.append((repo_arg, path))
            raise AssertionError("invalid receipt reached worktree removal")

        with patch.object(executor, "_remove_worktree", side_effect=invalid_receipt_must_not_remove):
            rejected_generations = [
                (status, preserved, teardown_phase_worktree(repo, preserved, supervisor_receipt=receipt))
                for status, preserved, receipt in invalid_receipt_generations
            ]
        assert invalid_removal_attempts == []
        for status, preserved, rejected in rejected_generations:
            assert rejected.removed is False, f"{status} empty generation was removed without valid receipt"
            assert preserved.worktree_path.exists(), f"{status} receipt lost the recoverable worktree"
            assert branch_is_addressable(preserved), f"{status} receipt lost the recoverable branch"
            assert _git(repo, "rev-parse", preserved.temp_branch).stdout.strip() == preserved.base_sha

        removal_failure = create_phase_worktree(
            repo,
            phase="preserve-removal-failure",
            target_branch=branch,
            base_sha=resolve_base_sha(repo),
        )
        removal_attempts = []

        def fail_real_removal(repo_arg, path):
            removal_attempts.append((repo_arg, path))
            raise OSError("simulated removal failure")

        with patch.object(executor, "_remove_worktree", side_effect=fail_real_removal):
            failed_removal = teardown_phase_worktree(
                repo,
                removal_failure,
                supervisor_receipt={
                    "generation": removal_failure.generation,
                    "process_tree_empty": True,
                    "receipt_binding": removal_failure.lease_authority.identity,
                    "terminal_status": "complete",
                },
            )
        assert removal_attempts == [(repo, removal_failure.worktree_path)]
        assert failed_removal.removed is False
        assert removal_failure.worktree_path.exists()
        assert branch_is_addressable(removal_failure)
        assert _git(repo, "rev-parse", removal_failure.temp_branch).stdout.strip() == removal_failure.base_sha

        nonempty = create_phase_worktree(
            repo,
            phase="preserve-nonempty",
            target_branch=branch,
            base_sha=resolve_base_sha(repo),
        )
        (nonempty.worktree_path / "must-survive.txt").write_bytes(b"nonempty inventory\n")
        retained_nonempty = teardown_phase_worktree(
            repo,
            nonempty,
            supervisor_receipt={
                "generation": nonempty.generation,
                "process_tree_empty": True,
                "receipt_binding": nonempty.lease_authority.identity,
                "terminal_status": "complete",
            },
        )
        assert retained_nonempty.removed is False
        _assert_preserved(repo, nonempty, {"must-survive.txt": b"nonempty inventory\n"})

        first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
        removal_observations = []
        original_remove = executor._remove_worktree

        def remove_while_owner_is_live(repo_arg, path):
            removal_observations.append(first.lease_authority.is_open())
            return original_remove(repo_arg, path)

        # Owner-authorized teardown is distinct from crash reclamation: the
        # original authority stays open through final inventory/removal and only
        # the bound complete-tree receipt authorizes its closure afterwards.
        with patch.object(executor, "_remove_worktree", side_effect=remove_while_owner_is_live):
            teardown = teardown_phase_worktree(
                repo,
                first,
                supervisor_receipt={
                    "generation": first.generation,
                    "process_tree_empty": True,
                    "receipt_binding": first.lease_authority.identity,
                    "terminal_status": "complete",
                },
            )
        assert removal_observations == [True]
        assert teardown.removed is True
        assert first.lease_authority.is_open() is False

        # Crash-residual reclamation separately acquires a released lease and
        # mints a fresh generation only after the empty inventory is proven.
        first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
        first.lease_authority.close()
        reclaimed = executor.reclaim_phase_worktree(repo, first)
        replacement = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=resolve_base_sha(repo))
    assert reclaimed.reclaimed is True
    assert not first.worktree_path.exists()
    assert replacement.generation != first.generation
    assert replacement.worktree_path.exists()
