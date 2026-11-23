"""Private run directories that keep a standalone board's failing-leg logs (agent-harness#2131).

A standalone ``advisor-board`` has no stream directory, so an unknown leg failure's reason
was discarded. Each run gets a fresh 0700 directory under the operator's state dir, handed
to the board as its leg-log directory only: no verdict, seat-mode or monitoring file is
written there. When the run ends, only the leg logs the board's results name are kept; a
run with none is removed. Kept runs are bounded by count and age, and a run another process
still holds is never touched.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
import time
from collections.abc import Iterable
from pathlib import Path

KEEP_RUNS = 20
MAX_AGE_S = 14 * 24 * 3600
_PREFIX = "advisor-board-"
_ACTIVE = ".active"
_LOG_REF = re.compile(r"; CLI output: (leg-logs/[A-Za-z0-9_-]+\.log)\Z")

try:
    import fcntl
except ImportError:  # pragma: no cover - not POSIX: no retention
    fcntl = None  # type: ignore[assignment]


def runs_parent() -> Path:
    from .seat_jail import state_home

    return state_home() / "agent-harness" / "board-runs"


class LegLogRun:
    """One run's private leg-log directory, held (``.active`` locked) until :meth:`finish`."""

    def __init__(self, path: Path, lock_fd: int) -> None:
        self.path = path
        self._lock_fd: int | None = lock_fd

    @classmethod
    def start(cls) -> "LegLogRun | None":
        """A fresh run under a validated private parent, or ``None`` when one cannot be
        made safely (the board then runs without retention, as before)."""
        from .advisor_board.backing import trusted_directory

        if fcntl is None:
            return None
        parent = os.path.normpath(str(runs_parent()))
        try:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        except OSError:
            return None
        if trusted_directory(parent, private=True) is None:
            return None
        run = os.path.join(parent, _PREFIX + secrets.token_hex(8))
        try:
            os.mkdir(run, 0o700)
        except OSError:
            return None
        try:
            fd = os.open(os.path.join(run, _ACTIVE),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except OSError:
            shutil.rmtree(run, ignore_errors=True)
            return None
        fcntl.flock(fd, fcntl.LOCK_EX)
        return cls(Path(run), fd)

    def finish(self, details: Iterable[object]) -> Path | None:
        """Keep only the leg logs ``details`` name; remove the run when none remains.
        Then bound the kept runs. Returns the run's path when it was kept."""
        refs = set()
        for detail in details:
            match = _LOG_REF.search(str(detail or ""))
            if match is not None:
                refs.add(match.group(1).split("/", 1)[1])
        kept = False
        logs = self.path / "leg-logs"
        try:
            entries = list(os.scandir(logs)) if logs.is_dir() and not logs.is_symlink() else []
        except OSError:
            entries = []
        for entry in entries:
            if entry.name in refs and entry.is_file(follow_symlinks=False):
                kept = True
                continue
            try:
                os.unlink(entry.path)
            except OSError:
                pass
        try:
            if kept:
                os.unlink(self.path / _ACTIVE)
            else:
                shutil.rmtree(self.path, ignore_errors=True)
        finally:
            self._release()
        prune(self.path.parent, keep=KEEP_RUNS, max_age_s=MAX_AGE_S)
        return self.path if kept and self.path.is_dir() else None

    def _release(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None


def _held(run: Path) -> bool:
    """Whether another live process still holds ``run`` (its ``.active`` lock)."""
    try:
        fd = os.open(run / _ACTIVE, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def prune(parent: Path, *, keep: int, max_age_s: float) -> None:
    """Remove runs beyond the newest ``keep`` or older than ``max_age_s``; never a run
    that is held, and never anything but this module's own run directories."""
    if fcntl is None:
        return
    runs = []
    try:
        for entry in os.scandir(parent):
            if entry.name.startswith(_PREFIX) and entry.is_dir(follow_symlinks=False):
                info = entry.stat(follow_symlinks=False)
                if info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077:
                    runs.append((info.st_mtime, Path(entry.path)))
    except OSError:
        return
    now = time.time()
    for index, (mtime, run) in enumerate(sorted(runs, reverse=True)):
        if (index >= keep or now - mtime > max_age_s) and not _held(run):
            shutil.rmtree(run, ignore_errors=True)
