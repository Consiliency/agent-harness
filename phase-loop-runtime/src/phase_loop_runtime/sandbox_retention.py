"""Reap review sandboxes before they eat the disk; keep what cannot be rebuilt.

Sizing changed when the sandbox became writable and executable. A read-only copy was 28 MB;
once a seat has built a venv and run tests it is ~150-250 MB, four seats to a round, and
``agent-harness#832`` ran fifteen rounds -- 10-15 GB for one pull request, on a host that was
at 97% on both disks.

**Two triggers, because one is not enough.** The day-long TTL is deliberate: a sandbox has to
survive an idle overnight so a panelist can be resumed against it with its context intact.
But fifteen rounds in six hours outruns any clock, so a total-footprint ceiling reaps
oldest-first as well.

**The split that makes reaping safe** is the same one the stale-resume logic uses:

* ``reviewed-tree/`` is RECONSTRUCTIBLE -- a clone, recoverable from git. Pure waste once cold.
* ``work/`` is IRREPRODUCIBLE -- the panelist's notes, probes and partial findings.

So the rules are: never archive the bulk, never reap the record, and archive BEFORE reaping.
If the archive fails, the sandbox stays. Losing the irreproducible half to a cleanup bug is
the one failure here that cannot be undone, and disk space is always recoverable later.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tarfile
import time
from typing import Callable

from .review_stage import REVIEW_STAGE_DIR_PREFIX, remove_review_stage

__all__ = [
    "SandboxEntry", "discover", "reap", "reap_until_free", "mark_as_sandbox", "SANDBOX_MARKER",
]

WORK_DIRNAME = "work"


@dataclass(frozen=True)
class SandboxEntry:
    path: Path
    mtime: float
    size_bytes: int


SANDBOX_MARKER = ".phase-loop-sandbox"


def _looks_like_a_sandbox(path: Path) -> bool:
    """Only reap what this runtime staged, proven by a marker IT wrote.

    A shape test is not identity. An earlier version accepted any directory containing a
    ``work/`` subdirectory, so an unrelated ``someone-elses-project/work/`` made the WHOLE
    project directory eligible for deletion -- verified destroying a bystander's files. The
    test that was supposed to catch it used a bystander with no ``work/`` subdirectory, so
    it passed without ever exercising the predicate.

    Identity is now a marker file this runtime writes into a sandbox it created, plus the
    staging prefix for the tempdirs `stage_review_tree` names itself. Nothing an operator
    happens to keep under the configured root can match either.
    """
    if not path.is_dir() or path.is_symlink():
        return False
    if (path / SANDBOX_MARKER).is_file():
        return True
    return path.name.startswith(REVIEW_STAGE_DIR_PREFIX)


def mark_as_sandbox(path: Path, *, owner_pid: int | None = None) -> None:
    """Claim a directory as reapable. Only the creator of a sandbox may call this.

    ``owner_pid`` names the process using it. The TTL, footprint and free-space reaps skip a
    sandbox whose owner is still running: every directory under the staging root is
    either a leak or a round in flight, and reaping oldest-first would otherwise delete a
    CONCURRENT board's tree mid-review (agent-harness#1147).
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    owner = ""
    if owner_pid is not None:
        owner = f"pid={owner_pid} start={_process_start(owner_pid) or ''}\n"
    body = ("created by phase-loop review staging; safe to reap\n" + owner).encode("utf-8")
    # Published ATOMICALLY: written under another name, synced, then renamed into place.
    # The marker is what makes a directory reapable, so a marker that exists before its
    # owner line is written is a window in which a live round looks ownerless -- and a
    # concurrent free-space reap deleted one in exactly that window.
    staging = path / f"{SANDBOX_MARKER}.{os.getpid()}.tmp"
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(staging, path / SANDBOX_MARKER)


def _process_start(pid: int) -> str | None:
    """The kernel start time of ``pid`` (field 22 of ``/proc/<pid>/stat``), to tell a
    live owner from a recycled pid. ``None`` where there is no ``/proc``."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return stat.rpartition(")")[2].split()[19]


def _owner_alive(path: Path) -> bool:
    """Is the process that marked this sandbox still running? Unknown owner: no."""
    try:
        text = (path / SANDBOX_MARKER).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _recorded_owner_alive(text)


#: A per-run scratch directory that is not a sandbox (the launcher's review copy, the
#: falsifier's dependency snapshot, an owned agy HOME) records its owner in a SIBLING file
#: ``<name>.owner``, so the directory's own content is untouched.
OWNER_SUFFIX = ".owner"


def _publish_atomically(target: Path, body: bytes) -> None:
    staging = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(staging, target)


def claim_scratch_dir(path: Path, *, owner_pid: int | None = None) -> None:
    """Record the process that owns per-run scratch ``path`` (agent-harness#1147). The
    crash-residue sweep removes the directory only once this owner is provably gone."""
    path = Path(path)
    pid = os.getpid() if owner_pid is None else owner_pid
    body = f"pid={pid} start={_process_start(pid) or ''}\n".encode("utf-8")
    _publish_atomically(path.with_name(path.name + OWNER_SUFFIX), body)


def release_scratch_dir(path: Path) -> None:
    """Drop ``path``'s owner record once the directory itself is gone. Never raises."""
    try:
        Path(path).with_name(Path(path).name + OWNER_SUFFIX).unlink()
    except OSError:
        pass


def scratch_owner_gone(path: Path) -> bool:
    """Is the recorded owner of per-run scratch ``path`` PROVABLY gone? Only a readable
    record naming a process that no longer runs (or whose pid was reused) says yes. No
    record, or an unreadable one, is an unknown owner -- and an unknown owner is never
    gone: deciding by age alone deleted a running child's files (agent-harness#1161)."""
    try:
        text = Path(path).with_name(Path(path).name + OWNER_SUFFIX).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return False
    fields = dict(part.split("=", 1) for part in text.split() if "=" in part)
    if not fields.get("pid", "").isdigit():
        return False
    return not _recorded_owner_alive(text)


def _recorded_owner_alive(text: str) -> bool:
    fields = dict(
        part.split("=", 1) for line in text.splitlines() for part in line.split() if "=" in part
    )
    try:
        pid = int(fields.get("pid", ""))
    except ValueError:
        return False
    recorded = fields.get("start", "")
    current = _process_start(pid)
    if current is not None:
        return not recorded or current == recorded
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _size_of(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def discover(root: Path | str) -> list[SandboxEntry]:
    """Sandboxes under ``root``, newest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    entries = []
    for child in root.iterdir():
        # Only this account's sandboxes. On a shared `/tmp` another user's 0700 directory
        # (or root's `systemd-private-*`) raised EACCES out of the marker probe, which
        # aborted the whole reap for everyone; and one it could list would count toward
        # THIS user's ceiling while being impossible to remove (agent-harness#1098).
        try:
            if child.lstat().st_uid != os.getuid() or not _looks_like_a_sandbox(child):
                continue
            entries.append(SandboxEntry(child, child.stat().st_mtime, _size_of(child)))
        except OSError:
            continue
    return sorted(entries, key=lambda e: e.mtime, reverse=True)


def _archive_work(entry: SandboxEntry, destination: Path) -> Path | None:
    """Archive only the irreproducible half.

    The code copy is a clone and comes back from git; archiving it would spend the space
    the reap just recovered. Returns ``None`` when there is nothing to keep.
    """
    work = entry.path / WORK_DIRNAME
    if not work.is_dir() or not any(work.rglob("*")):
        return None
    destination.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(entry.mtime))
    target = destination / f"{entry.path.name}-{stamp}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(work, arcname=f"{entry.path.name}/{WORK_DIRNAME}")
    return target


def _remove(entry: SandboxEntry) -> None:
    """Remove a sandbox, tolerating read-only directories a panelist created."""
    remove_review_stage(entry.path)
    if entry.path.exists():
        shutil.rmtree(entry.path, ignore_errors=True)


def reap(
    root: Path | str,
    *,
    ttl_s: float,
    max_total_bytes: int | None = None,
    archive_dest: Path | str | None = None,
) -> list[Path]:
    """Reap cold sandboxes, then reap oldest-first until under the footprint ceiling.

    Returns the paths removed. Never raises: this runs on cleanup paths where losing the
    original error to a cleanup error would be worse than leaving a directory behind.
    """
    destination = Path(archive_dest) if archive_dest is not None else None
    removed: list[Path] = []
    cutoff = time.time() - ttl_s

    def _retire(entry: SandboxEntry) -> bool:
        gone = _reap_one(entry, archive_dest=destination)
        removed.extend(gone)
        return bool(gone)

    entries = discover(root)
    survivors = []
    for entry in entries:
        # A cold sandbox whose owner still runs is a long round, not a leftover.
        if entry.mtime < cutoff and not _owner_alive(entry.path):
            if not _retire(entry):
                survivors.append(entry)
        else:
            survivors.append(entry)

    if max_total_bytes is not None:
        total = sum(e.size_bytes for e in survivors)
        # Oldest first: the newest sandbox is the one most likely to be resumed. A sandbox
        # whose owner is still running is a round in flight, never over-budget waste.
        for entry in sorted(survivors, key=lambda e: e.mtime):
            if total <= max_total_bytes:
                break
            if _owner_alive(entry.path):
                continue
            if _retire(entry):
                total -= entry.size_bytes

    return removed


def reap_until_free(
    root: Path | str,
    *,
    floor_bytes: int,
    free_bytes: Callable[[Path], int],
    archive_dest: Path | str | None = None,
) -> list[Path]:
    """Reap retained sandboxes oldest-first until ``root`` has ``floor_bytes`` free.

    Called before a new round is refused for space: retained sandboxes are reclaimable, and
    refusing a board while they sit there trades a working review for cold leftovers. Live
    rounds are skipped and the archive-before-reap rule still holds. Never raises.
    """
    root = Path(root)
    removed: list[Path] = []
    try:
        if free_bytes(root) >= floor_bytes:
            return removed
        for entry in sorted(discover(root), key=lambda e: e.mtime):
            if _owner_alive(entry.path):
                continue
            removed.extend(_reap_one(entry, archive_dest=archive_dest))
            if free_bytes(root) >= floor_bytes:
                break
    except Exception:
        pass
    return removed


def _reap_one(entry: SandboxEntry, *, archive_dest: Path | str | None = None) -> list[Path]:
    """Archive then remove one sandbox; ``[]`` when it was kept."""
    if archive_dest is not None:
        try:
            _archive_work(entry, Path(archive_dest))
        except Exception:
            # Never trade the irreproducible half for disk space. Space can be
            # recovered on the next pass; the panelist's work cannot.
            return []
    try:
        _remove(entry)
    except Exception:
        return []
    return [entry.path]
