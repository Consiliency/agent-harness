"""v45 SCHED — per-phase git worktree lifecycle (IF-0-SCHED-1 support).

Concurrent cross-phase dispatch is only safe when each phase's child executor
runs in its *own* git worktree: the children run ``git add``/``commit``/``status``
and would otherwise race on ``index.lock``/HEAD in a shared tree even when their
owned files are disjoint. ``validate_concurrent_phase_ownership`` guarantees the
file-disjointness; this module provides the isolation that makes concurrent git
operations safe and the merge-back conflict-free.

Lifecycle per phase in a ready wave:

1. ``create_phase_worktree`` — ``git worktree add -b <temp-branch> <path> <base>``.
   Each phase gets its OWN temporary branch off the pipeline-branch tip, because
   git refuses to check out one branch in two worktrees simultaneously.
2. The caller launches the child with ``repo=<worktree_path>`` so the executor's
   ``wrapped_cwd`` points the child into the isolated tree.
3. ``integrate_phase_worktree`` — fast-forward/merge the phase's temp branch back
   onto the pipeline branch in the *main* worktree. Because waved siblings own
   disjoint files (enforced upstream), sequential merges never conflict.
4. ``teardown_phase_worktree`` — remove the worktree and delete the temp branch.

Only repo-tracked content crosses the worktree boundary via the temp branch.
Runner-owned ledger/state (``events.jsonl``/``state.json`` under ``.phase-loop``)
is written by the parent against the main repo and is not committed, so it never
participates in merge-back.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .runtime_paths import lane_worktree_path
from .worktree_index import _is_ancestor, default_base_ref, list_worktrees

# Namespace prefix for the throwaway per-phase temp branches. Kept as a single
# source of truth so the crash-residual GC can recognise exactly the branches
# ``phase_temp_branch`` mints — never a human's branch or a foreign worktree.
_TEMP_BRANCH_PREFIX = "phase-loop/sched/"


@dataclass(frozen=True)
class PhaseWorktreeHandle:
    """Identifies one phase's isolated worktree and its temporary branch."""

    phase: str
    worktree_path: Path
    temp_branch: str
    target_branch: str
    base_sha: str


@dataclass(frozen=True)
class WorktreeIntegrationResult:
    """Outcome of merging a phase's temp branch back onto the pipeline branch."""

    phase: str
    temp_branch: str
    integrated: bool
    conflict: bool = False
    merged_sha: str | None = None
    had_commits: bool = True
    reason: str | None = None
    conflicted_paths: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "temp_branch": self.temp_branch,
            "integrated": self.integrated,
            "conflict": self.conflict,
            "merged_sha": self.merged_sha,
            "had_commits": self.had_commits,
            "reason": self.reason,
            "conflicted_paths": list(self.conflicted_paths),
        }


@dataclass(frozen=True)
class WorktreeTransferResult:
    """Outcome of transporting a phase child's worktree changes onto main.

    ``had_changes`` is True when the child produced any delta since base (dirty
    and/or committed). ``applied`` is True when main's working tree now carries
    that delta (or there was nothing to transfer). A failed apply leaves
    ``applied=False`` with ``conflict=True``; ``git apply`` is atomic, so main is
    left untouched and the work is preserved on ``temp_branch`` for diagnosis.
    """

    phase: str
    temp_branch: str
    had_changes: bool
    applied: bool
    conflict: bool = False
    reason: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "temp_branch": self.temp_branch,
            "had_changes": self.had_changes,
            "applied": self.applied,
            "conflict": self.conflict,
            "reason": self.reason,
        }


class PhaseWorktreeError(RuntimeError):
    """Raised when a worktree lifecycle git operation fails unexpectedly."""


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _git_bytes(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run git capturing stdout/stderr as raw BYTES (never text-decoded).

    A git patch is a byte stream that must survive verbatim: routing it through
    ``text=True`` strips ``\\r`` (corrupting CRLF files into spurious apply
    conflicts or silent LF rewrites) and raises ``UnicodeDecodeError`` on any
    non-UTF-8 "text" blob git inlines raw (high bytes without a NUL, so git does
    not base85-encode it). The diff capture and ``git apply`` stdin in
    :func:`transfer_phase_worktree_dirty` therefore use bytes I/O.
    """

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        input=input_bytes,
    )


def resolve_base_sha(repo: Path, ref: str = "HEAD") -> str:
    """Resolve ``ref`` (default the current tip) to a concrete commit SHA."""

    result = _git(repo, "rev-parse", ref)
    return result.stdout.strip()


def current_branch(repo: Path) -> str:
    """Name of the branch currently checked out in ``repo``'s main worktree.

    This is the pipeline branch concurrent phases branch from and integrate back
    onto. Detached HEAD returns ``"HEAD"``.
    """

    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def phase_temp_branch(target_branch: str, phase: str) -> str:
    """Deterministic temp-branch name for a phase's isolated worktree.

    Slashes in the pipeline branch are preserved (git refs allow them); the
    ``phase-loop/sched/`` prefix namespaces these throwaway branches so cleanup
    sweeps can recognize them.
    """

    return f"{_TEMP_BRANCH_PREFIX}{target_branch}/{phase.upper()}"


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _remove_worktree(repo: Path, path: Path) -> None:
    _git(repo, "worktree", "remove", "--force", str(path), check=False)


def _worktree_target_branch(temp_branch: str) -> str | None:
    """Recover the pipeline branch a sched temp branch integrates back onto.

    ``phase-loop/sched/<target_branch>/<PHASE>`` — ``<target_branch>`` may itself
    contain slashes (e.g. ``feat/foo``), ``<PHASE>`` never does, so strip the
    prefix then drop the final segment. Returns ``None`` when ``temp_branch`` is
    not one of our sched temp branches.
    """

    if not temp_branch.startswith(_TEMP_BRANCH_PREFIX):
        return None
    remainder = temp_branch[len(_TEMP_BRANCH_PREFIX):]
    target, sep, _phase = remainder.rpartition("/")
    if not sep or not target:
        return None
    return target



def _branch_is_checked_out(repo: Path, branch: str) -> bool:
    """True if any worktree has ``branch`` checked out.

    git refuses to delete such a branch, so this decides between delete and rename.
    Fails CLOSED: on any parse/exec error it reports True, which routes to the
    rename path -- renaming is always safe, deleting is not.
    """
    try:
        for ref in list_worktrees(repo):
            if ref.branch == branch:
                return True
        return False
    except Exception:
        return True


def _unique_salvage_name(is_free, stem: str) -> str:
    """A salvage name that does not collide.

    ``int(time.time())`` alone collides when two recreates land in the same second --
    plausible in a concurrent wave -- which made ``worktree move``/``branch -m`` fail
    and wedged creation. Probe until free, then fall back to a monotonic suffix.
    """
    base = f"{stem}-{int(time.time())}"
    if is_free(base):
        return base
    for n in range(1, 1000):
        cand = f"{base}.{n}"
        if is_free(cand):
            return cand
    return f"{base}.{time.monotonic_ns()}"

def _commit_is_reachable(repo: Path, sha: str) -> bool:
    """True if ``sha`` is reachable from at least one ref in ``repo``.

    Used to decide whether a removed worktree's HEAD still has a handle on it. Fails
    CLOSED in the direction that PRESERVES: on any git error it reports False, which
    makes the caller pin a salvage ref. A redundant ref costs a few bytes; a missing
    one costs the commits.
    """

    result = _git(
        repo, "for-each-ref", "--count=1", "--contains", sha, "--format=%(refname)",
        check=False,
    )
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def _dirty_state(worktree_path: Path) -> str:
    """``"dirty"`` / ``"clean"`` / ``"unknown"`` for ``worktree_path``.

    Splits out the case ``_worktree_has_uncommitted_changes`` deliberately folds into
    "dirty": git could not read status at all (the path is not a repo, or is an
    orphaned leftover from a partially-failed ``worktree add``). Both must PRESERVE,
    but only one of them may be described to an operator as "it holds uncommitted
    work" -- saying that about a path git cannot even read is a false diagnosis.
    """

    result = _git(
        worktree_path, "status", "--porcelain", "--untracked-files=all", check=False
    )
    if result.returncode != 0:
        return "unknown"
    return "dirty" if result.stdout.strip() else "clean"


def _worktree_has_uncommitted_changes(worktree_path: Path) -> bool:
    """True if the worktree holds any dirty state we must not destroy.

    ``git status --porcelain --untracked-files=all`` reports tracked
    modifications, staged changes, AND untracked new files — the three ways a
    crashed child leaves real work behind (the transport model leaves verified
    work UNCOMMITTED in the worktree; the parent's closeout, which never ran on a
    kill, is what would have staged+committed it). Any failure to read status is
    treated as "dirty" so GC preserves the worktree (fail toward not deleting).

    Deliberately NOT ``--ignored``: gitignored content in a phase worktree is
    regenerable build artifacts (``__pycache__``, ``build/``), never work.
    Preserving on ignored files would skip essentially every worktree and neuter
    the reclaim. (Contrast ah#215, which concerned TRACKED-then-ignored files —
    those still surface as tracked modifications here.)
    """

    return _dirty_state(worktree_path) != "clean"


def _gc_stale_phase_worktrees(
    repo: Path,
    *,
    max_age_s: int = 24 * 3600,
    now: float | None = None,
) -> list[dict[str, str]]:
    """Best-effort reclaim of crash-residual per-phase worktrees.

    ``teardown_phase_worktree`` only runs from a ``finally`` — it survives an
    exception but NOT a SIGKILL/OOM/timeout/lost-SSH kill, so a hard-killed run
    leaks its worktree DIRECTORY forever. This sweeps those, mirroring
    ``_gc_stale_panel_scratch`` (age-gated, advisory) — but a scratch dir holds
    nothing while a worktree can hold real work, so it adds two never-delete-work
    guards with no precedent to copy.

    A worktree is removed only when ALL hold:
      * its branch is one of our ``phase-loop/sched/`` temp branches (identity —
        a human's worktree or a foreign sibling clone is never a candidate);
      * its directory mtime is older than ``max_age_s`` (a CONCURRENT run's fresh
        worktree must never be touched);
      * its working tree is clean (no uncommitted/untracked work); AND
      * its HEAD is already contained in the branch it integrates back onto (no
        unmerged commits to lose).

    Enumeration is via ``list_worktrees(repo)`` (git-registered, so scoped to
    THIS repo's object store) rather than globbing the worktree root — the root
    can be ``repo.parent`` shared with unrelated clones, which globbing would
    wrongly sweep. Wrapped so any failure (permissions, a racing removal, an
    unreadable mtime) can NEVER affect the run. Returns per-candidate
    skip/removal records for logging/tests; never raises.
    """

    records: list[dict[str, str]] = []
    try:
        base_ref = default_base_ref(repo)
        cutoff = (time.time() if now is None else now) - max_age_s
        for ref in list_worktrees(repo):
            try:
                branch = ref.branch
                if not branch or not branch.startswith(_TEMP_BRANCH_PREFIX):
                    continue  # not a phase worktree — never touch
                wt_path = Path(ref.path)
                try:
                    mtime = wt_path.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff:
                    continue  # fresh — could belong to a concurrent run
                if _worktree_has_uncommitted_changes(wt_path):
                    records.append(
                        {
                            "path": str(wt_path),
                            "branch": branch,
                            "action": "skipped",
                            "reason": "uncommitted changes",
                        }
                    )
                    continue
                target = _worktree_target_branch(branch)
                merge_ref = (
                    target if (target and _branch_exists(repo, target)) else base_ref
                )
                head = ref.head_sha
                if not head or not _is_ancestor(repo, head, merge_ref):
                    # HEAD carries commits not yet in the integration target —
                    # unmerged work. (_is_ancestor also returns False on any git
                    # error, so an indeterminate check preserves the worktree.)
                    records.append(
                        {
                            "path": str(wt_path),
                            "branch": branch,
                            "action": "skipped",
                            "reason": "unmerged commits",
                        }
                    )
                    continue
                _remove_worktree(repo, wt_path)
                # VERIFY the removal before recording it or deleting the branch.
                # `_remove_worktree` is best-effort (check=False) and git legitimately
                # REFUSES on a locked worktree, so an unverified "removed" record is a
                # lie, and a branch -D after a failed removal would delete the only
                # handle on a worktree that still exists.
                if wt_path.exists():
                    records.append(
                        {
                            "path": str(wt_path),
                            "branch": branch,
                            "action": "skipped",
                            "reason": "removal refused (locked or in use)",
                        }
                    )
                    continue
                if _branch_exists(repo, branch):
                    _git(repo, "branch", "-D", branch, check=False)
                records.append(
                    {
                        "path": str(wt_path),
                        "branch": branch,
                        "action": "removed",
                        "reason": "crash-residual: clean, merged, stale",
                    }
                )
            except Exception:
                continue
        # Reclaims admin records for any directory removed above (and for any
        # already-vanished directory). Prune alone frees no bytes — it is the
        # follow-up to the removals, not the mechanism.
        _git(repo, "worktree", "prune", check=False)
    except Exception:
        return records
    return records


def create_phase_worktree(
    repo: Path,
    *,
    phase: str,
    target_branch: str,
    base_sha: str,
    workspace_mount: Path | None = None,
) -> PhaseWorktreeHandle:
    """Create an isolated worktree for ``phase`` on its own temp branch.

    Idempotent: a stale worktree at the computed path or a stale temp branch
    (from a crashed prior run) is pruned/deleted before recreation. The new
    worktree is checked out at ``base_sha`` so every concurrent sibling starts
    from the same pipeline-branch tip.
    """

    # Best-effort reclaim of crash-residual worktrees leaked by killed runs
    # (teardown's finally never ran). Advisory only — never affects this run.
    # Surface what the sweep destroyed. A destructive op that leaves no trace is
    # indistinguishable from one that never ran, and the caller previously discarded
    # these records entirely. Guarded + stderr: this must never break creation, and
    # the module has no logger of its own.
    try:
        for _rec in _gc_stale_phase_worktrees(repo) or ():
            if _rec.get("action") == "removed":
                print(
                    f"phase-worktree gc: removed {_rec.get('path')} "
                    f"(branch {_rec.get('branch')}; {_rec.get('reason')})",
                    file=sys.stderr,
                )
    except Exception:
        pass

    phase = phase.upper()
    worktree_path = lane_worktree_path(
        repo,
        branch=target_branch,
        lane_id=phase,
        workspace_mount=workspace_mount,
    )
    temp_branch = phase_temp_branch(target_branch, phase)

    # Clear stale state from an interrupted prior run before recreating.
    #
    # ah#624: this used to force-remove UNCONDITIONALLY and then `branch -D`, with no
    # dirty check and no ancestor proof. A run killed mid-work leaves its verified work
    # UNCOMMITTED (see `transfer_phase_worktree_dirty`), so recreating the same phase
    # silently deleted that work AND the branch that could have recovered it. Same guards
    # the reclamation sweep already applies -- preserve, do not destroy.
    clean_head_sha = ""
    if worktree_path.exists() and not any(worktree_path.iterdir()):
        # An EMPTY leftover directory -- an orphan of `worktree prune`, or a partially
        # failed prior `worktree add`. It is not a registered worktree (those always
        # contain a `.git` file), so `git status` fails there and the dirty check
        # fail-closes to "dirty", the move is refused, and every retry raises forever.
        # `main` self-heals here because `worktree add` accepts an existing empty dir.
        # Do not convert a self-healing shape into a permanent operator stop over a
        # directory that provably holds nothing.
        try:
            worktree_path.rmdir()
        except OSError:
            pass  # Raced or not actually empty: fall through to the guards below.
    if worktree_path.exists():
        state = _dirty_state(worktree_path)
        if state != "clean":
            # Move it aside instead of deleting it. Loud, recoverable, and it frees the
            # path so creation still succeeds.
            salvage = worktree_path.with_name(
                _unique_salvage_name(
                    lambda n: not worktree_path.with_name(n).exists(),
                    f"{worktree_path.name}.salvage",
                )
            )
            _git(repo, "worktree", "move", str(worktree_path), str(salvage), check=False)
            if worktree_path.exists():
                # git refused the move (locked / in use). Do NOT force-delete: fail
                # loudly rather than destroy uncommitted work. Word it for the state we
                # ACTUALLY observed -- telling an operator a path "holds uncommitted
                # work" when git could not even read it is a false diagnosis, and they
                # will act on this message while triaging.
                held = (
                    "it holds uncommitted work from an interrupted run"
                    if state == "dirty"
                    else "git could not read its status, so whether it holds work is "
                    "UNKNOWN (it may not be a git worktree at all)"
                )
                raise PhaseWorktreeError(
                    f"refusing to clobber a phase worktree at {worktree_path}: "
                    f"{held} and it could not be moved aside. Inspect and remove it "
                    f"manually."
                )
            if not salvage.exists():
                # The source is gone but the destination was never written, so the move
                # did NOT do what the message below would claim. Verify the DESTINATION:
                # inferring success from a vanished source is the same false-clean shape
                # as trusting an empty git probe (ah#628 -- a concurrent same-phase
                # recreate can move the source out from under this one).
                raise PhaseWorktreeError(
                    f"refusing to report a preservation that did not happen: the dirty "
                    f"worktree at {worktree_path} is gone but {salvage} was not created. "
                    f"Its uncommitted work may have been taken by a concurrent recreate; "
                    f"look for sibling {worktree_path.name}.salvage-* directories."
                )
            print(
                f"phase-worktree: preserved dirty crash residual -> {salvage}",
                file=sys.stderr,
            )
        else:
            # Clean tree, but "clean" only means nothing UNCOMMITTED -- the worktree can
            # still be the sole handle on committed work. If its HEAD is detached (an
            # executor is arbitrary code; it may `checkout --detach`, and the runtime
            # already models detached phase worktrees in `worktree_index`), removing the
            # worktree drops the last thing pointing at those commits. Capture the sha
            # BEFORE removal and pin it below if nothing else ends up reaching it.
            #
            # `--verify ... ^{commit}` rather than a bare `rev-parse HEAD`: on an unborn
            # HEAD the bare form prints the literal string "HEAD" to STDOUT, which would
            # make `clean_head_sha` truthy garbage.
            clean_head_sha = _git(
                worktree_path, "rev-parse", "--verify", "--quiet", "HEAD^{commit}",
                check=False,
            ).stdout.strip()
            _remove_worktree(repo, worktree_path)
    _git(repo, "worktree", "prune", check=False)

    # Pin the removed worktree's HEAD BEFORE branch handling, not after.
    #
    # Both raises in the branch block below fire AFTER `_remove_worktree` has already
    # run, so pinning afterwards is unreachable in exactly the case that needs it: a
    # detached HEAD on a chain disjoint from temp_branch, with the branch rename
    # failing. Removal happened, the raise fires, and the sha is pinned nowhere --
    # violating this code's own invariant that the pin happens AT REMOVAL TIME.
    # Ordering it here keeps the silent cases silent: temp_branch has not been renamed
    # or deleted yet, so a commit it reaches is still seen as reachable.
    if clean_head_sha and not _commit_is_reachable(repo, clean_head_sha):
        salvage_ref = _unique_salvage_name(
            lambda n: _git(repo, "rev-parse", "--verify", n, check=False).returncode != 0,
            f"refs/salvage/{phase}",
        )
        # The trailing "" is an oldvalue of "must not exist". Unlike `worktree move`
        # and `branch -m`, which refuse an existing target, a plain `update-ref`
        # OVERWRITES -- which would silently orphan whatever the previous pin held.
        # This is the one salvage seam where the racing loser could lose data quietly
        # instead of loudly (ah#628), and one argument closes it without a lock.
        pinned = _git(repo, "update-ref", salvage_ref, clean_head_sha, "", check=False)
        if pinned.returncode != 0:
            raise PhaseWorktreeError(
                f"refusing to orphan crash-residual commit {clean_head_sha[:12]} from "
                f"phase {phase}: the worktree was removed and {salvage_ref} could not be "
                f"written. Recover it with `git update-ref` before re-running."
            )
        print(
            f"phase-worktree: pinned orphaned crash-residual commit "
            f"{clean_head_sha[:12]} as {salvage_ref}",
            file=sys.stderr,
        )

    if _branch_exists(repo, temp_branch):
        # Only delete the branch once its commits are provably reachable elsewhere.
        # `_is_ancestor` returns False on ANY git error, so an unresolvable merge target
        # preserves the branch -- fail closed. A log does not protect orphaned SHAs.
        head = _git(repo, "rev-parse", temp_branch, check=False).stdout.strip()
        # The branch's ACTUAL integration target is target_branch -- `integrate_phase_
        # worktree` merges onto it, and the GC already prefers it. Using only
        # `default_base_ref` (origin/main, always truthy) misses the common shape of a
        # run killed after integration but before the push: the commits are reachable
        # from local target_branch, yet the branch gets needlessly salvage-renamed,
        # feeding ah#627. Conservative either way -- this just stops the false alarm.
        merge_ref = (
            target_branch if _branch_exists(repo, target_branch)
            else default_base_ref(repo)
        )
        merged = bool(head and merge_ref and _is_ancestor(repo, head, merge_ref))
        # A salvaged worktree still has temp_branch CHECKED OUT, so `branch -D` is
        # refused ("used by worktree at ...") and, with check=False, silently ignored --
        # then `worktree add -b` below fails because the name was never freed, wedging
        # every retry. Rename ALWAYS frees the name; it works on a checked-out branch.
        # Deleting is only an optimisation for the merged case, so do it only when the
        # branch is not checked out anywhere.
        if merged and not _branch_is_checked_out(repo, temp_branch):
            _git(repo, "branch", "-D", temp_branch, check=False)
        else:
            # Unmerged commits: preserving them is mandatory, but the name must be freed
            # or `worktree add -b` below fails outright. RENAME rather than delete -- the
            # commits stay reachable under a salvage ref, and creation still succeeds.
            salvage_branch = _unique_salvage_name(
                lambda n: not _branch_exists(repo, n), f"{temp_branch}.salvage"
            )
            _git(repo, "branch", "-m", temp_branch, salvage_branch, check=False)
            if _branch_exists(repo, temp_branch):
                # The rename did not take. Do NOT print a preservation message that is
                # false, and do not let `worktree add -b` fail with a confusing error.
                raise PhaseWorktreeError(
                    f"refusing to proceed: could not free branch {temp_branch} "
                    f"(rename to {salvage_branch} failed). It holds crash-residual "
                    f"commits; resolve manually."
                )
            print(
                f"phase-worktree: preserved crash-residual commits as "
                f"{salvage_branch} (was {temp_branch})",
                file=sys.stderr,
            )

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    created = _git(
        repo,
        "worktree",
        "add",
        "-b",
        temp_branch,
        str(worktree_path),
        base_sha,
        check=False,
    )
    if created.returncode != 0:
        raise PhaseWorktreeError(
            f"failed to create worktree for phase {phase} at {worktree_path}: "
            f"{created.stderr.strip() or created.stdout.strip()}"
        )
    return PhaseWorktreeHandle(
        phase=phase,
        worktree_path=worktree_path,
        temp_branch=temp_branch,
        target_branch=target_branch,
        base_sha=base_sha,
    )


def integrate_phase_worktree(
    repo: Path,
    handle: PhaseWorktreeHandle,
    *,
    message: str | None = None,
) -> WorktreeIntegrationResult:
    """Merge a phase's temp branch back onto the pipeline branch.

    Precondition: the main worktree (``repo``) is checked out on
    ``handle.target_branch`` with a clean index for the merged files (the caller
    integrates sequentially after all children finish). Disjoint owned files make
    the merge conflict-free by construction; a conflict is surfaced (and aborted)
    rather than resolved silently, because it signals the ownership gate was
    bypassed.
    """

    commits = _git(repo, "rev-list", f"{handle.base_sha}..{handle.temp_branch}", check=False)
    if commits.returncode != 0:
        return WorktreeIntegrationResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            integrated=False,
            had_commits=False,
            reason=f"could not inspect commits: {commits.stderr.strip()}",
        )
    if not commits.stdout.strip():
        # Child produced no commits (e.g. plan-only, blocked, or dry run).
        return WorktreeIntegrationResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            integrated=True,
            had_commits=False,
            merged_sha=resolve_base_sha(repo),
            reason="no commits to integrate",
        )

    merge_message = message or f"phase-loop sched: integrate {handle.phase}"
    merged = _git(
        repo,
        "merge",
        "--no-ff",
        "-m",
        merge_message,
        handle.temp_branch,
        check=False,
    )
    if merged.returncode != 0:
        conflicted = _git(repo, "diff", "--name-only", "--diff-filter=U", check=False)
        conflicted_paths = tuple(
            line.strip() for line in conflicted.stdout.splitlines() if line.strip()
        )
        _git(repo, "merge", "--abort", check=False)
        return WorktreeIntegrationResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            integrated=False,
            conflict=True,
            conflicted_paths=conflicted_paths,
            reason=(
                "merge conflict integrating phase worktree — the concurrent "
                "ownership-disjointness gate should have prevented this"
            ),
        )
    return WorktreeIntegrationResult(
        phase=handle.phase,
        temp_branch=handle.temp_branch,
        integrated=True,
        merged_sha=resolve_base_sha(repo),
    )


def transfer_phase_worktree_dirty(
    repo: Path,
    handle: PhaseWorktreeHandle,
    *,
    commit_message: str | None = None,
) -> WorktreeTransferResult:
    """Transport a phase child's worktree work onto main as UNSTAGED changes.

    Unlike :func:`integrate_phase_worktree` (which merges only *committed* work),
    a real phase executor leaves its verified work DIRTY in the worktree and
    emits ``awaiting_phase_closeout`` — the parent runner's closeout is what
    stages+commits the dirty phase-owned files. So the committed-only merge is a
    no-op against a real child and the work is lost. This brings the child's full
    delta (uncommitted + any self-commits) onto the *main* working tree without
    committing it, so the parent's existing closeout — whose selective
    ``git add -- <owned>`` is what enforces the ownership gate — commits it on the
    pipeline branch exactly as in serial mode.

    The work is first committed onto ``temp_branch`` (preserving it on a ref), then
    transported via ``git diff base..temp | git apply`` rather than a
    cherry-pick: cherry-pick would pre-stage every changed path into main's index
    and defeat the closeout's selective, ownership-gated staging. ``git apply`` is
    atomic, so a failed apply (which the disjointness gate should make impossible)
    leaves main untouched and the work recoverable on ``temp_branch``.
    """

    worktree = handle.worktree_path
    # Stage everything dirty (captures untracked new files too) and commit it onto
    # the temp branch so the work survives on a ref even if the apply to main fails.
    _git(worktree, "add", "-A", check=False)
    has_staged = _git(worktree, "diff", "--cached", "--quiet", check=False).returncode != 0
    if has_staged:
        message = commit_message or f"phase-loop sched transport: {handle.phase}"
        committed = _git(worktree, "commit", "-q", "-m", message, check=False)
        if committed.returncode != 0:
            return WorktreeTransferResult(
                phase=handle.phase,
                temp_branch=handle.temp_branch,
                had_changes=True,
                applied=False,
                reason=(
                    "failed to commit worktree changes for transport: "
                    f"{committed.stderr.strip() or committed.stdout.strip()}"
                ),
            )

    revs = _git(worktree, "rev-list", f"{handle.base_sha}..{handle.temp_branch}", check=False)
    if revs.returncode != 0:
        # The transport commit above already succeeded (when there was dirt), so
        # the work is on temp_branch — mark had_changes=True so the caller PRESERVES
        # the branch (its preserve guard keys on had_changes) instead of deleting it.
        return WorktreeTransferResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            had_changes=has_staged,
            applied=False,
            conflict=has_staged,
            reason=f"could not inspect commits: {revs.stderr.strip()}",
        )
    if not revs.stdout.strip():
        # Child produced no work (blocked, plan-only, dry run, or a clean
        # self-reported terminal). Nothing to transport; main is untouched.
        return WorktreeTransferResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            had_changes=False,
            applied=True,
            reason="no changes to transfer",
        )

    # Bytes I/O: the patch must survive verbatim (CRLF, binary, non-UTF-8 blobs).
    diff = _git_bytes(worktree, "diff", "--binary", handle.base_sha, handle.temp_branch)
    if diff.returncode != 0:
        return WorktreeTransferResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            had_changes=True,
            applied=False,
            conflict=True,
            reason=f"could not compute transfer diff: {diff.stderr.decode('utf-8', 'replace').strip()}",
        )
    if not diff.stdout.strip():
        return WorktreeTransferResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            had_changes=False,
            applied=True,
            reason="empty net diff",
        )

    applied = _git_bytes(repo, "apply", "--whitespace=nowarn", "-", input_bytes=diff.stdout)
    if applied.returncode != 0:
        return WorktreeTransferResult(
            phase=handle.phase,
            temp_branch=handle.temp_branch,
            had_changes=True,
            applied=False,
            conflict=True,
            reason=(
                "git apply failed transporting worktree changes onto main — the "
                "concurrent ownership-disjointness gate should have prevented this: "
                f"{applied.stderr.decode('utf-8', 'replace').strip() or applied.stdout.decode('utf-8', 'replace').strip()}"
            ),
        )
    return WorktreeTransferResult(
        phase=handle.phase,
        temp_branch=handle.temp_branch,
        had_changes=True,
        applied=True,
    )


def teardown_phase_worktree(
    repo: Path,
    handle: PhaseWorktreeHandle,
    *,
    delete_branch: bool = True,
) -> None:
    """Remove the phase's worktree and (by default) delete its temp branch.

    Best-effort: missing worktree/branch is not an error so this is safe to call
    in a ``finally`` even if creation partially failed.
    """

    _remove_worktree(repo, handle.worktree_path)
    _git(repo, "worktree", "prune", check=False)
    if delete_branch and _branch_exists(repo, handle.temp_branch):
        _git(repo, "branch", "-D", handle.temp_branch, check=False)
