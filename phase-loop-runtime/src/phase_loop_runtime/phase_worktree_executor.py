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
from dataclasses import dataclass, field
from pathlib import Path

from .runtime_paths import lane_worktree_path


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

    return f"phase-loop/sched/{target_branch}/{phase.upper()}"


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _remove_worktree(repo: Path, path: Path) -> None:
    _git(repo, "worktree", "remove", "--force", str(path), check=False)


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

    phase = phase.upper()
    worktree_path = lane_worktree_path(
        repo,
        branch=target_branch,
        lane_id=phase,
        workspace_mount=workspace_mount,
    )
    temp_branch = phase_temp_branch(target_branch, phase)

    # Clear stale state from an interrupted prior run before recreating.
    if worktree_path.exists():
        _remove_worktree(repo, worktree_path)
    _git(repo, "worktree", "prune", check=False)
    if _branch_exists(repo, temp_branch):
        _git(repo, "branch", "-D", temp_branch, check=False)

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
