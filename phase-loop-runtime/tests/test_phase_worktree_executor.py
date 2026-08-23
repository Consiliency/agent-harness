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

import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from phase_loop_runtime.phase_worktree_executor import (
    PhaseWorktreeError,
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
    with _isolated_worktree_root(tmp_path):
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
    with _isolated_worktree_root(tmp_path):
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
    with _isolated_worktree_root(tmp_path):
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
    with _isolated_worktree_root(tmp_path):
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
    with _isolated_worktree_root(tmp_path):
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
    with _isolated_worktree_root(tmp_path):
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
    with _isolated_worktree_root(tmp_path):
        repo = make_repo(tmp_path)
        branch = _current_branch(repo)
        base = resolve_base_sha(repo)

        first = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)
        _commit_in_worktree(first.worktree_path, "src/extract.py", "x = 1\n", "stale work")
        # Simulate a crashed prior run: do NOT tear down; recreate the same phase.
        second = create_phase_worktree(repo, phase="extract", target_branch=branch, base_sha=base)

        assert second.worktree_path == first.worktree_path
        assert second.worktree_path.exists()
        # Recreated fresh at base: the stale commit's file is not in the NEW worktree.
        assert not (second.worktree_path / "src" / "extract.py").exists()
        # ah#624: but the work must remain RECOVERABLE. The prior run's commits were never
        # merged, so its branch must survive -- deleting it would orphan those commits with
        # no handle. This assertion is the one that previously pinned the data loss: the old
        # code ran `branch -D` unconditionally here.
        all_branches = subprocess.run(
            ["git", "-C", str(repo), "branch", "--list", f"{first.temp_branch}*"],
            capture_output=True, text=True,
        ).stdout
        salvaged = [b.strip("* ").strip() for b in all_branches.splitlines() if ".salvage-" in b]
        assert salvaged, f"unmerged crash-residual commits were orphaned: {all_branches!r}"
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{salvaged[0]}:src/extract.py"],
            capture_output=True, text=True,
        )
        assert blob.returncode == 0 and "x = 1" in blob.stdout, "stale work unrecoverable"
        # The orphan pin must stay SILENT here. This IS the clean-removal path (the work
        # was committed, so the worktree is clean), but the renamed salvage BRANCH already
        # reaches those commits -- nothing is orphaned. Pinning anyway would add a
        # refs/salvage/ ref on every ordinary recreate and make the accumulation of ah#627
        # worse than linear, so the ABSENCE of the ref is the property under test.
        # Mutation that must kill this: pin unconditionally (drop the reachability test).
        assert not _git(
            repo, "for-each-ref", "--format=%(refname)", "refs/salvage/"
        ).stdout.strip(), "spurious salvage ref pinned on an already-reachable commit"
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


def test_recreate_preserves_dirty_crash_residual(tmp_path):
    """ah#624: a same-path recreate must NOT force-delete UNCOMMITTED work.

    This is the shape a real killed run leaves: `transfer_phase_worktree_dirty` means
    a killed child's verified work is uncommitted by design. The old code ran
    `_remove_worktree(..., --force)` unconditionally here, destroying it silently.

    Mutation that must kill this: restore the unconditional `_remove_worktree` call --
    the salvage directory never appears and the content is gone.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    # ISOLATE the worktree root. Without this the worktree lands in the SHARED
    # /mnt/workspace/worktrees and the salvage glob below matches leftovers from other
    # runs -- the assertion then passes even with the fix removed (verified: it did).
    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        # Dirty, never committed -- exactly what a SIGKILL leaves behind.
        (first.worktree_path / "src").mkdir(parents=True, exist_ok=True)
        (first.worktree_path / "src" / "unsaved.py").write_text("unsaved = True\n")

        second = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )

        # Creation still succeeded at the canonical path.
        assert second.worktree_path == first.worktree_path
        assert second.worktree_path.exists()
        # The uncommitted work was MOVED ASIDE, not deleted.
        salvaged = sorted(
            first.worktree_path.parent.glob(f"{first.worktree_path.name}.salvage-*")
        )
        assert salvaged, "dirty crash residual was destroyed instead of preserved"
        recovered = salvaged[0] / "src" / "unsaved.py"
        assert recovered.exists(), f"salvage dir exists but work is missing: {salvaged[0]}"
        assert "unsaved = True" in recovered.read_text()

        teardown_phase_worktree(repo, second)


def test_recreate_with_real_origin_does_not_wedge(tmp_path):
    """ah#624 regression: the MERGED-branch shape must not wedge creation.

    Production-shaped, and the reason the other tests missed this: `make_repo` has no
    `origin/main`, so `_is_ancestor` fail-closes to False and every other test takes
    the RENAME path by luck. With a real `origin/main` the branch tip IS reachable, so
    `merged` is True -- which is what makes the round-1 mechanism reachable at all.

    What this test pins is the GUARD on the delete, not the delete itself. The
    worktree here is dirty, so it gets salvaged with `temp_branch` still CHECKED OUT;
    `_branch_is_checked_out` is therefore True and the `merged and not checked_out`
    conjunction is False, so control takes the rename path. Drop the guard and the
    merged case calls `branch -D` on a checked-out branch: git refuses, the error is
    swallowed by check=False, the name is never freed, and `worktree add -b` fails
    with "a branch named ... already exists". That is the round-1 wedge.

    So this test does NOT execute `branch -D` -- see
    `test_recreate_deletes_a_merged_unreferenced_branch` for the fires-at-all
    direction. (An earlier version of this docstring claimed it "reaches the delete
    path", which was false and is exactly the kind of prose that misleads the next
    person into putting an assertion where it cannot bite.)

    Mutation that must kill this: drop the `_branch_is_checked_out` guard so the
    merged case calls `branch -D` unconditionally -- creation raises.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    # Give the repo a real merge target, as the GC tests do.
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )

    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        # Dirty but NOT committed: the tip stays at base, so it IS an ancestor of
        # origin/main -- the merged shape that triggers the delete path.
        (first.worktree_path / "src").mkdir(parents=True, exist_ok=True)
        (first.worktree_path / "src" / "unsaved.py").write_text("unsaved = True\n")

        # Must not raise.
        second = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )

        assert second.worktree_path.exists()
        assert _current_branch(second.worktree_path) == second.temp_branch
        # And the uncommitted work is still recoverable.
        salvaged = sorted(
            first.worktree_path.parent.glob(f"{first.worktree_path.name}.salvage-*")
        )
        assert salvaged, "dirty work destroyed on the merged path"
        assert (salvaged[0] / "src" / "unsaved.py").exists()

        teardown_phase_worktree(repo, second)


def test_failed_pin_leaves_the_worktree_intact_so_a_retry_converges(tmp_path):
    """Round-2 third seat: pinning AFTER removal is non-convergent, not merely late.

    If the pin is ordered after `_remove_worktree` and `update-ref` fails, we raise --
    but the worktree is already gone. The retry then finds no worktree, captures no
    sha, skips the pin entirely and SUCCEEDS, silently dropping the very commit the
    raise was protecting. Pinning first means a failed pin leaves the worktree intact,
    so the retry sees the same state and can try again.

    Mutation that must kill this: move the pin after `_remove_worktree` -- the first
    call still raises, but the worktree is gone and the retry succeeds while the
    commit becomes unreachable.
    """
    from phase_loop_runtime import phase_worktree_executor as pwe

    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        _commit_in_worktree(first.worktree_path, "src/work.py", "w = 1\n", "real work")
        orphan_sha = _git(first.worktree_path, "rev-parse", "HEAD").stdout.strip()
        _git(first.worktree_path, "checkout", "-q", "--detach", orphan_sha)
        _git(repo, "branch", "-D", first.temp_branch)

        real_git = pwe._git

        def failing_pin(target, *args, **kwargs):
            if args[:1] == ("update-ref",):
                return subprocess.CompletedProcess(
                    args=list(args), returncode=1, stdout="", stderr="fatal: simulated"
                )
            return real_git(target, *args, **kwargs)

        with patch.object(pwe, "_git", side_effect=failing_pin):
            with pytest.raises(PhaseWorktreeError, match="could not be written"):
                create_phase_worktree(
                    repo, phase="extract", target_branch=branch, base_sha=base
                )

        # The worktree survives the failed pin -- that is what makes the retry able to
        # preserve the commit rather than silently skip it.
        assert first.worktree_path.exists(), (
            "worktree was removed despite the pin failing: a retry can no longer "
            "recover the commit"
        )

        # And the retry (pin now working) does preserve it.
        second = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        containing = _git(
            repo, "for-each-ref", "--contains", orphan_sha, "--format=%(refname)"
        ).stdout.split()
        assert any(r.startswith("refs/salvage/") for r in containing), containing
        teardown_phase_worktree(repo, second)


def test_recreate_moves_aside_an_unrecognized_leftover_directory(tmp_path):
    """A NON-EMPTY, non-git leftover at the path must not wedge creation forever.

    The empty-dir heal does not cover this: a partial `worktree add`, or foreign
    content dropped at the path, leaves a non-empty directory git cannot stat. The
    dirty check fail-closes to "unknown", `git worktree move` will NEVER move something
    that is not a registered worktree, and every retry raises identically.

    The fallback is gated on "not a registered worktree" -- renaming a REAL worktree
    behind git's back would corrupt its registry, so a locked one must still refuse.

    Mutation that must kill this: drop the `Path.rename` fallback -- creation raises.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        planned = tmp_path / "wt" / f"{branch}-EXTRACT"
        planned.mkdir(parents=True, exist_ok=True)
        (planned / "half-written.py").write_text("partial = True\n")

        # Must not raise.
        handle = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        assert handle.worktree_path == planned
        assert (handle.worktree_path / ".git").exists()

        # The foreign content was PRESERVED, not deleted.
        moved = sorted(planned.parent.glob(f"{planned.name}.salvage-*"))
        assert moved, "unrecognized leftover was destroyed instead of moved aside"
        assert (moved[0] / "half-written.py").read_text() == "partial = True\n"
        teardown_phase_worktree(repo, handle)


def test_recreate_reports_a_locked_clean_worktree_honestly(tmp_path):
    """A locked CLEAN worktree must fail with its real cause, not "already exists".

    git refuses to remove a locked worktree even with --force, and `_remove_worktree`
    swallows that. Without an explicit check the path survives and `worktree add`
    fails with an opaque "already exists" that names neither the lock nor the fix.
    The dirty path already reports this honestly; the clean path must match.

    Mutation that must kill this: drop the post-removal existence check -- creation
    still fails, but with the opaque worktree-add error instead.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        _git(repo, "worktree", "lock", str(first.worktree_path))
        try:
            with pytest.raises(PhaseWorktreeError, match="locked or in use"):
                create_phase_worktree(
                    repo, phase="extract", target_branch=branch, base_sha=base
                )
        finally:
            _git(repo, "worktree", "unlock", str(first.worktree_path))
        teardown_phase_worktree(repo, first)


def test_recreate_refuses_locked_dirty_worktree_and_preserves_work(tmp_path):
    """ah#624: a dirty worktree whose move is REFUSED (locked) must fail loudly.

    Covers the source-still-exists raise in create's dirty branch, which no test
    reached (it sat in the coverage missing-lines report). git refuses `worktree move`
    on a locked worktree, so the salvage cannot free the path -- the only correct
    outcome is a raise with the work untouched.

    A locked worktree is still a VALID worktree, so `git status` succeeds and reports
    real dirt: this exercises the determinate-dirty wording, not the indeterminate
    branch added for the empty-leftover case.

    Mutation that must kill this: replace the raise with the old `_remove_worktree`
    force-delete -- no exception is raised and the uncommitted file is destroyed.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        (first.worktree_path / "src").mkdir(parents=True, exist_ok=True)
        (first.worktree_path / "src" / "unsaved.py").write_text("unsaved = True\n")
        _git(repo, "worktree", "lock", str(first.worktree_path))
        try:
            with pytest.raises(PhaseWorktreeError, match="refusing to clobber"):
                create_phase_worktree(
                    repo, phase="extract", target_branch=branch, base_sha=base
                )
            # The dirty work is untouched at the ORIGINAL path -- refused, not relocated.
            assert (
                first.worktree_path / "src" / "unsaved.py"
            ).read_text() == "unsaved = True\n"
            # And no salvage directory was fabricated for a move that never happened.
            assert not list(
                first.worktree_path.parent.glob(f"{first.worktree_path.name}.salvage-*")
            )
        finally:
            _git(repo, "worktree", "unlock", str(first.worktree_path))
        teardown_phase_worktree(repo, first)


def test_recreate_deletes_a_merged_unreferenced_branch(tmp_path):
    """The merged fast path must actually FIRE, and must stay quiet when it does.

    Found by a line-coverage sweep: `branch -D` was executed by ZERO tests across all
    three worktree files. Every existing test reaches the rename path -- either
    because `make_repo` has no `origin/main` (so `_is_ancestor` fail-closes) or
    because the worktree is dirty (so the branch is checked out in the salvage). The
    delete side was pinned only in the safety direction: nothing would have caught a
    mutation replacing the fast path with "always rename", which is pure ah#627
    accumulation and completely silent.

    The shape that reaches it: real `origin/main`, and a worktree with NO commits and
    NO dirt -- so the branch tip is `base` (merged), the clean path removes the
    worktree, and the branch is checked out nowhere.

    Also pins the no-noise claim on the TRUE delete path: today the absence of
    salvage material is only asserted on the rename path.

    Mutation that must kill this: replace the fast path with an unconditional rename.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )

    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        # No commits, no dirt: tip == base, so the branch IS merged.
        assert not _git(
            first.worktree_path, "status", "--porcelain", "--untracked-files=all"
        ).stdout.strip()

        second = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        assert second.worktree_path.exists()

        # The stale branch was DELETED, not renamed -- nothing needed preserving.
        branches = _git(
            repo, "branch", "--list", f"{first.temp_branch}*", "--format=%(refname:short)"
        ).stdout.split()
        assert not [b for b in branches if ".salvage-" in b], (
            f"merged branch was salvaged instead of deleted: {branches}"
        )
        assert not _git(
            repo, "for-each-ref", "--format=%(refname)", "refs/salvage/"
        ).stdout.strip(), "merged fast path left salvage refs behind"
        assert not sorted(
            first.worktree_path.parent.glob(f"{first.worktree_path.name}.salvage-*")
        ), "merged fast path left a salvage directory behind"

        teardown_phase_worktree(repo, second)


def test_recreate_heals_an_empty_leftover_directory(tmp_path):
    """An EMPTY leftover dir must not wedge creation forever.

    Orphaned by `worktree prune`, or left by a partially failed `worktree add`: it is
    not a registered worktree, so `git status` fails there, the dirty check
    fail-closes to "dirty", `worktree move` is refused, and the raise repeats on
    every retry -- about a directory that provably holds nothing.

    `main` self-heals this shape (`worktree add` accepts an existing empty dir), so
    without this the ah#624 guards turn a self-healing state into a permanent
    operator stop. Found by the round-2 review panel, executed in both directions.

    Mutation that must kill this: drop the empty-dir rmdir -- creation raises.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        # Mirrors the path `_isolated_worktree_root` pins creation to.
        planned = tmp_path / "wt" / f"{branch}-EXTRACT"
        planned.mkdir(parents=True, exist_ok=True)
        assert planned.exists() and not any(planned.iterdir())

        # Must not raise.
        handle = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        assert handle.worktree_path == planned
        assert (handle.worktree_path / ".git").exists()
        teardown_phase_worktree(repo, handle)


def test_recreate_pins_orphan_even_when_branch_rename_fails(tmp_path):
    """ah#624 round-2: the pin must not be preempted by the branch-rename raise.

    Both raises in the branch-handling block fire AFTER `_remove_worktree` has already
    run. With the pin ordered after that block it is unreachable in exactly the case
    that needs it -- a detached HEAD on a chain DISJOINT from the temp branch, with
    the rename failing -- so the worktree is removed, the raise fires, and the sha is
    pinned nowhere. That violates the invariant the pin exists to uphold: preserve AT
    REMOVAL TIME.

    Found by the round-2 review panel. The rename failure is forced synthetically
    (the trigger is rare); the ORDERING hole it exposes is structural.

    Mutation that must kill this: move the pin block back after branch handling --
    the raise still fires but the commit is reachable from nothing.
    """
    from phase_loop_runtime import phase_worktree_executor as pwe

    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        # Unmerged commit ON the temp branch.
        _commit_in_worktree(first.worktree_path, "src/on_branch.py", "b = 1\n", "branch work")
        # Detach onto a DISJOINT chain: sibling of the branch tip, not reachable from it.
        _git(first.worktree_path, "checkout", "-q", "--detach", base)
        _commit_in_worktree(first.worktree_path, "src/detached.py", "d = 1\n", "detached work")
        orphan_sha = _git(first.worktree_path, "rev-parse", "HEAD").stdout.strip()

        # Force the branch rename to collide with an existing name so it fails.
        _git(repo, "branch", "collide", base)
        real_unique = pwe._unique_salvage_name

        def colliding(is_free, stem):
            return "collide" if stem.startswith(first.temp_branch) else real_unique(is_free, stem)

        with patch.object(pwe, "_unique_salvage_name", side_effect=colliding):
            with pytest.raises(RuntimeError, match="could not free branch"):
                create_phase_worktree(
                    repo, phase="extract", target_branch=branch, base_sha=base
                )

        # The raise is expected -- but the detached work must NOT have been orphaned.
        containing = _git(
            repo, "for-each-ref", "--contains", orphan_sha, "--format=%(refname)"
        ).stdout.split()
        assert containing, (
            f"commit {orphan_sha[:12]} orphaned: the worktree was removed and the "
            f"rename raise preempted the pin"
        )
        assert any(r.startswith("refs/salvage/") for r in containing), containing


def test_recreate_refuses_to_claim_a_preservation_that_did_not_happen(tmp_path):
    """ah#628: success must be proven at the DESTINATION, not inferred from the source.

    The salvage guard used to accept "the source path is gone" as proof the move
    worked. Under a concurrent same-phase recreate the source can be moved away by
    the OTHER caller, so this one would print
    ``preserved dirty crash residual -> <path>`` for a directory it never wrote --
    a destructive-op log claiming a preservation that did not happen, which is worse
    than no log at all.

    Mutation that must kill this: drop the ``salvage.exists()`` check -- creation
    proceeds and emits the false preservation message instead of raising.
    """
    from phase_loop_runtime import phase_worktree_executor as pwe

    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)

    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        (first.worktree_path / "src").mkdir(parents=True, exist_ok=True)
        (first.worktree_path / "src" / "unsaved.py").write_text("unsaved = True\n")

        real_git = pwe._git

        def fake_git(target, *args, **kwargs):
            # `worktree move` fails, but the source disappears anyway -- exactly what a
            # concurrent recreate that won the race leaves behind.
            if args[:2] == ("worktree", "move"):
                shutil.rmtree(first.worktree_path, ignore_errors=True)
                return subprocess.CompletedProcess(
                    args=list(args), returncode=1, stdout="", stderr="fatal: simulated"
                )
            return real_git(target, *args, **kwargs)

        with patch.object(pwe, "_git", side_effect=fake_git):
            with pytest.raises(RuntimeError, match="preservation that did not happen"):
                create_phase_worktree(
                    repo, phase="extract", target_branch=branch, base_sha=base
                )


def test_recreate_pins_orphaned_detached_head(tmp_path):
    """ah#624 round-2: a CLEAN worktree can still be the last handle on real commits.

    "Clean" only means nothing UNCOMMITTED. An executor is arbitrary agent-run code
    inside the worktree; if it commits, detaches HEAD, and drops the temp branch, the
    branch-handling block below has nothing to rename and the recreate removes the
    worktree -- which was the only thing pointing at those commits. They become
    unreachable and gc eventually collects them.

    Found by the round-2 review panel and reproduced against the pre-fix code: the
    commit was reachable from NO ref after the recreate.

    Mutation that must kill this: drop the `_commit_is_reachable` pin -- `contains`
    comes back empty and the commit is orphaned.
    """
    repo = make_repo(tmp_path)
    branch = _current_branch(repo)
    base = resolve_base_sha(repo)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )

    with _isolated_worktree_root(tmp_path):
        first = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        # Commit real work, then detach and drop the branch that referenced it.
        (first.worktree_path / "src").mkdir(parents=True, exist_ok=True)
        (first.worktree_path / "src" / "committed.py").write_text("value = 1\n")
        _git(first.worktree_path, "add", "-A")
        _git(first.worktree_path, "commit", "-q", "-m", "committed work")
        orphan_sha = _git(
            first.worktree_path, "rev-parse", "HEAD"
        ).stdout.strip()
        _git(first.worktree_path, "checkout", "-q", "--detach", orphan_sha)
        _git(repo, "branch", "-D", first.temp_branch)

        # The worktree is CLEAN now -- the removal path, not the salvage path.
        # Asserted directly rather than via the runtime helper, so the test pins the
        # actual precondition instead of trusting the code under review to report it.
        assert not _git(
            first.worktree_path, "status", "--porcelain", "--untracked-files=all"
        ).stdout.strip()

        second = create_phase_worktree(
            repo, phase="extract", target_branch=branch, base_sha=base
        )
        assert second.worktree_path.exists()

        # The commit must still be reachable from SOME ref.
        containing = _git(
            repo, "for-each-ref", "--contains", orphan_sha, "--format=%(refname)"
        ).stdout.split()
        assert containing, (
            f"commit {orphan_sha[:12]} was orphaned by the recreate: no ref reaches it"
        )
        assert any(r.startswith("refs/salvage/") for r in containing), containing

        teardown_phase_worktree(repo, second)
