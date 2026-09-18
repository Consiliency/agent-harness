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

from .review_stage import REVIEW_STAGE_DIR_PREFIX, remove_review_stage

__all__ = ["SandboxEntry", "discover", "reap", "mark_as_sandbox", "SANDBOX_MARKER"]

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


def mark_as_sandbox(path: Path) -> None:
    """Claim a directory as reapable. Only the creator of a sandbox may call this."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / SANDBOX_MARKER).write_text(
        "created by phase-loop review staging; safe to reap\n", encoding="utf-8"
    )


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
        if not _looks_like_a_sandbox(child):
            continue
        try:
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
        if destination is not None:
            try:
                _archive_work(entry, destination)
            except Exception:
                # Never trade the irreproducible half for disk space. Space can be
                # recovered on the next pass; the panelist's work cannot.
                return False
        try:
            _remove(entry)
        except Exception:
            return False
        removed.append(entry.path)
        return True

    entries = discover(root)
    survivors = []
    for entry in entries:
        if entry.mtime < cutoff:
            if not _retire(entry):
                survivors.append(entry)
        else:
            survivors.append(entry)

    if max_total_bytes is not None:
        total = sum(e.size_bytes for e in survivors)
        # Oldest first: the newest sandbox is the one most likely to be resumed.
        for entry in sorted(survivors, key=lambda e: e.mtime):
            if total <= max_total_bytes:
                break
            if _retire(entry):
                total -= entry.size_bytes

    return removed
