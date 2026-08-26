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

import fcntl
import hashlib
import os
import stat
import subprocess
import uuid
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
    generation: str = "legacy"
    lease_authority: "LeaseAuthority | None" = None
    lease_identity: str | None = None


class LeaseAuthority:
    """A process-local, non-serializable lease for one worktree generation."""

    def __init__(self, path: Path, fd: int, identity: str, generation: str | None = None) -> None:
        self.path = path
        self._fd = fd
        self.identity = identity
        self.generation = generation or identity.partition(":")[0]

    def fileno(self) -> int:
        return self._fd

    def is_open(self) -> bool:
        if self._fd < 0:
            return False
        try:
            os.fstat(self._fd)
        except OSError:
            return False
        return True

    def close(self) -> None:
        if self.is_open():
            os.close(self._fd)
        self._fd = -1

    def with_identity(self, identity: str) -> "LeaseAuthority":
        return LeaseAuthority(self.path, self._fd, identity, self.generation)


@dataclass(frozen=True)
class WorktreeReclamationResult:
    reclaimed: bool
    reason: str | None = None


@dataclass(frozen=True)
class WorktreeTeardownResult:
    removed: bool
    reason: str | None = None


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


def phase_temp_branch(target_branch: str, phase: str, generation: str | None = None) -> str:
    """Deterministic temp-branch name for a phase's isolated worktree.

    Slashes in the pipeline branch are preserved (git refs allow them); the
    ``phase-loop/sched/`` prefix namespaces these throwaway branches so cleanup
    sweeps can recognize them.
    """

    suffix = f"-{generation}" if generation else ""
    return f"phase-loop/sched/{target_branch}/{phase.upper()}{suffix}"


def _branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _remove_worktree(repo: Path, path: Path) -> None:
    removed = _git(repo, "worktree", "remove", "--force", str(path), check=False)
    if removed.returncode != 0:
        raise OSError(removed.stderr.strip() or removed.stdout.strip() or "could not remove worktree")


def _git_dir(repo: Path) -> Path:
    root = repo / ".git"
    if not root.is_file():
        return root
    pointer = root.read_text(encoding="utf-8").strip()
    if not pointer.startswith("gitdir: "):
        raise OSError("could not resolve git directory")
    gitdir = Path(pointer.removeprefix("gitdir: "))
    return gitdir if gitdir.is_absolute() else root.parent / gitdir


def _lease_path(repo: Path, generation: str) -> Path:
    root = _git_dir(repo)
    path = root / "phase-loop-leases" / f"{generation}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _generation_marker(repo: Path, target_branch: str, phase: str) -> Path:
    token = hashlib.sha256(f"{target_branch}\0{phase}".encode("utf-8")).hexdigest()
    root = _git_dir(repo)
    path = root / "phase-loop-generations" / token
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _new_lease(repo: Path, generation: str) -> LeaseAuthority:
    path = _lease_path(repo, generation)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    lease_stat = os.fstat(fd)
    identity = f"{generation}:{lease_stat.st_dev}:{lease_stat.st_ino}"
    return LeaseAuthority(path, fd, identity, generation)


def _mount_filesystem_type(path: Path) -> str | None:
    """Return the known filesystem type for ``path`` without guessing."""

    try:
        target = str(path.resolve())
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        return None

    best: tuple[int, str] | None = None
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        post_fields = after.split()
        if not separator or len(fields) < 5 or not post_fields:
            continue
        mount_path = (
            fields[4]
            .replace(r"\040", " ")
            .replace(r"\011", "\t")
            .replace(r"\012", "\n")
            .replace(r"\134", "\\")
        )
        prefix = mount_path.rstrip("/") or "/"
        if target == prefix or target.startswith(prefix.rstrip("/") + "/"):
            candidate = (len(prefix), post_fields[0])
            if best is None or candidate[0] > best[0]:
                best = candidate
    return best[1] if best is not None else None


def _supports_safe_reclamation(path: Path) -> bool:
    """Require a known-local POSIX filesystem before crash reclamation.

    The nonblocking ``flock`` below is then a same-kernel proof for the held
    lease.  Unknown or network filesystems fail closed rather than relying on
    lock semantics we cannot establish here.
    """

    if os.name != "posix" or not all(
        hasattr(os, attribute) for attribute in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    ):
        return False
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            return False
    except OSError:
        return False
    return _mount_filesystem_type(path) in {"apfs", "btrfs", "ext2", "ext3", "ext4", "overlay", "tmpfs", "xfs", "zfs"}


def _relative_inventory_path(raw_path: bytes) -> tuple[str, tuple[str, ...]]:
    rendered = os.fsdecode(raw_path)
    parts = Path(rendered).parts
    if not parts or Path(rendered).is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise OSError("invalid git status path in worktree inventory")
    return rendered, tuple(parts)


def _open_inventory_parent(path: Path, parts: tuple[str, ...]) -> tuple[int, str]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        for component in parts[:-1]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _stat_snapshot(file_stat: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
    )


def _inventory_entry(path: Path, raw_path: bytes, status_code: str) -> tuple[object, ...]:
    rendered, parts = _relative_inventory_path(raw_path)
    parent_fd, name = _open_inventory_parent(path, parts)
    try:
        try:
            initial = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if "?" in status_code or "!" in status_code:
                raise OSError("worktree inventory changed during scan")
            return ("worktree", status_code, rendered, "missing")
        initial_snapshot = _stat_snapshot(initial)
        if stat.S_ISLNK(initial.st_mode):
            target = os.readlink(name, dir_fd=parent_fd)
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if _stat_snapshot(current) != initial_snapshot:
                raise OSError("worktree link changed during scan")
            digest = hashlib.sha256(os.fsencode(target)).hexdigest()
            return ("worktree", status_code, rendered, "symlink", *initial_snapshot, digest)
        if stat.S_ISREG(initial.st_mode):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            descriptor = os.open(name, flags, dir_fd=parent_fd)
            try:
                if _stat_snapshot(os.fstat(descriptor)) != initial_snapshot:
                    raise OSError("worktree file changed during scan")
                digest = hashlib.sha256()
                while chunk := os.read(descriptor, 131072):
                    digest.update(chunk)
            finally:
                os.close(descriptor)
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if _stat_snapshot(current) != initial_snapshot:
                raise OSError("worktree file changed during scan")
            return ("worktree", status_code, rendered, "regular", *initial_snapshot, digest.hexdigest())
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if _stat_snapshot(current) != initial_snapshot:
            raise OSError("worktree special file changed during scan")
        return ("worktree", status_code, rendered, "special", *initial_snapshot)
    finally:
        os.close(parent_fd)


def _stable_inventory(path: Path, *, base_sha: str | None = None) -> tuple[tuple[object, ...], ...]:
    """Fingerprint all recoverable delta state without following links.

    A clean status is not an empty generation: commits after ``base_sha`` are
    separately bound to both their commit identity and binary diff bytes.
    """

    status = _git_bytes(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching", "-z")
    if status.returncode != 0:
        raise OSError(status.stderr.decode("utf-8", "replace").strip() or "could not inspect worktree inventory")

    entries: list[tuple[object, ...]] = []
    records = status.stdout.split(b"\0")
    index = 0
    while index < len(records) - 1:
        record = records[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise OSError("malformed git status inventory")
        status_code = record[:2].decode("ascii")
        entries.append(_inventory_entry(path, record[3:], status_code))
        if b"R" in record[:2] or b"C" in record[:2]:
            if index >= len(records) - 1:
                raise OSError("malformed git rename inventory")
            entries.append(("rename-source", status_code, os.fsdecode(records[index])))
            index += 1

    base = base_sha or resolve_base_sha(path)
    head = _git(path, "rev-parse", "HEAD", check=False)
    if head.returncode != 0:
        raise OSError(head.stderr.strip() or "could not resolve worktree HEAD")
    head_sha = head.stdout.strip()
    if head_sha != base:
        committed = _git_bytes(path, "diff", "--binary", "--full-index", base, head_sha)
        if committed.returncode != 0:
            raise OSError(committed.stderr.decode("utf-8", "replace").strip() or "could not inspect committed worktree state")
        entries.append(("committed", base, head_sha, hashlib.sha256(committed.stdout).hexdigest()))
    return tuple(sorted(entries, key=repr))


def _empty_stable_inventory(path: Path, base_sha: str) -> str | None:
    before = _stable_inventory(path, base_sha=base_sha)
    after = _stable_inventory(path, base_sha=base_sha)
    if before != after:
        return "inventory_changed"
    return "inventory_nonempty" if before else None


def _delete_reclaimed_generation(repo: Path, handle: PhaseWorktreeHandle) -> None:
    _remove_worktree(repo, handle.worktree_path)
    pruned = _git(repo, "worktree", "prune", check=False)
    if pruned.returncode != 0:
        raise OSError(pruned.stderr.strip() or pruned.stdout.strip() or "could not prune worktree metadata")
    if _branch_exists(repo, handle.temp_branch):
        deleted = _git(repo, "branch", "-D", handle.temp_branch, check=False)
        if deleted.returncode != 0:
            raise OSError(deleted.stderr.strip() or deleted.stdout.strip() or "could not delete worktree branch")


def reclaim_phase_worktree(repo: Path, handle: PhaseWorktreeHandle) -> WorktreeReclamationResult:
    """Reclaim only a released, stably empty generation; preserve on doubt."""
    authority = handle.lease_authority
    if (
        authority is None
        or handle.lease_identity != authority.identity
        or authority.generation != handle.generation
    ):
        return WorktreeReclamationResult(False, "lease_identity_drift")
    if authority.is_open():
        return WorktreeReclamationResult(False, "live_lease")
    if not _supports_safe_reclamation(handle.worktree_path):
        return WorktreeReclamationResult(False, "unsupported_filesystem")
    try:
        fd = os.open(authority.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return WorktreeReclamationResult(False, "live_lease")
        try:
            lease_stat = os.fstat(fd)
            if f"{handle.generation}:{lease_stat.st_dev}:{lease_stat.st_ino}" != handle.lease_identity:
                return WorktreeReclamationResult(False, "lease_identity_drift")
            inventory_reason = _empty_stable_inventory(handle.worktree_path, handle.base_sha)
            if inventory_reason is not None:
                return WorktreeReclamationResult(False, inventory_reason)
            _delete_reclaimed_generation(repo, handle)
            return WorktreeReclamationResult(True)
        finally:
            os.close(fd)
    except OSError:
        return WorktreeReclamationResult(False, "inventory_error")


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
    base_path = lane_worktree_path(
        repo,
        branch=target_branch,
        lane_id=phase,
        workspace_mount=workspace_mount,
    )
    generation = uuid.uuid4().hex
    base_branch = phase_temp_branch(target_branch, phase)
    marker = _generation_marker(repo, target_branch, phase)
    occupied = marker.exists() or base_path.exists() or _branch_exists(repo, base_branch)
    worktree_path = base_path.parent / f"{base_path.name}-{generation}" if occupied else base_path
    temp_branch = phase_temp_branch(target_branch, phase, generation) if occupied else base_branch
    lease = _new_lease(repo, generation)

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
        lease.close()
        raise PhaseWorktreeError(
            f"failed to create worktree for phase {phase} at {worktree_path}: "
            f"{created.stderr.strip() or created.stdout.strip()}"
        )
    marker.write_text(generation, encoding="utf-8")
    return PhaseWorktreeHandle(
        phase=phase,
        worktree_path=worktree_path,
        temp_branch=temp_branch,
        target_branch=target_branch,
        base_sha=base_sha,
        generation=generation,
        lease_authority=lease,
        lease_identity=lease.identity,
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
    supervisor_receipt: dict[str, object] | None = None,
) -> WorktreeTeardownResult:
    """Remove only an owner-authorized, stably empty worktree generation."""

    authority = handle.lease_authority
    if (
        supervisor_receipt is None
        or authority is None
        or not authority.is_open()
        or authority.generation != handle.generation
        or handle.lease_identity != authority.identity
        or supervisor_receipt.get("generation") != handle.generation
        or supervisor_receipt.get("receipt_binding") != handle.lease_identity
        or supervisor_receipt.get("process_tree_empty") is not True
        or supervisor_receipt.get("terminal_status") != "complete"
    ):
        return WorktreeTeardownResult(False, "invalid_supervisor_receipt")
    try:
        inventory_reason = _empty_stable_inventory(handle.worktree_path, handle.base_sha)
    except OSError:
        return WorktreeTeardownResult(False, "inventory_error")
    if inventory_reason is not None:
        return WorktreeTeardownResult(False, inventory_reason)
    try:
        _remove_worktree(repo, handle.worktree_path)
        pruned = _git(repo, "worktree", "prune", check=False)
        if pruned.returncode != 0:
            raise OSError(pruned.stderr.strip() or pruned.stdout.strip() or "could not prune worktree metadata")
        if delete_branch and _branch_exists(repo, handle.temp_branch):
            deleted = _git(repo, "branch", "-D", handle.temp_branch, check=False)
            if deleted.returncode != 0:
                raise OSError(deleted.stderr.strip() or deleted.stdout.strip() or "could not delete worktree branch")
    except OSError:
        return WorktreeTeardownResult(False, "removal_error")
    authority.close()
    return WorktreeTeardownResult(True)
