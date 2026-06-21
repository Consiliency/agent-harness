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
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

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
