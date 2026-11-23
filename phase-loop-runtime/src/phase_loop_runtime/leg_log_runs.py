"""Private run directories that keep a standalone board's failing-leg logs (agent-harness#2131).

A standalone ``advisor-board`` has no stream directory, so an unknown leg failure's reason
was discarded. Each run gets a fresh 0700 directory under the operator's state dir, handed
to the board as its leg-log directory only: no verdict, seat-mode or monitoring file is
written there. When the run ends, only the leg logs the board's results name are kept; a
run with none is removed. Kept runs are bounded by count and age.

Every step that registers, completes or prunes a run holds one lock on the parent
(``board-runs/.lock``), so a pruner never sees a half-registered run or ranks a run by a
stale snapshot. Completed runs are ranked by their completion marker, a run still in
progress (its ``.active`` lock held) is never removed, and the finishing run is excluded
from its own prune. Any setup or lock failure leaves the board running without retention.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import shutil
import stat
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from .advisor_board.backing import spelled_without_parent_steps, trusted_component

KEEP_RUNS = 20
MAX_AGE_S = 14 * 24 * 3600
_PREFIX = "advisor-board-"
_ACTIVE = ".active"
_DONE = ".done"
_PARENT_LOCK = ".lock"
# Resolved without failing on platforms that lack these flags (Windows imports this module
# but never retains: ``fcntl`` is absent there, so no run is ever started).
_DIR_FLAGS = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
              | getattr(os, "O_CLOEXEC", 0))
_LOG_REF = re.compile(r"; CLI output: (leg-logs/[A-Za-z0-9_-]+\.log)\Z")

try:
    import fcntl
except ImportError:  # pragma: no cover - not POSIX: no retention
    fcntl = None  # type: ignore[assignment]


def runs_parent() -> Path:
    from .seat_jail import state_home

    return state_home() / "agent-harness" / "board-runs"


def _open_private_parent() -> tuple[str, int] | None:
    """The validated ``board-runs`` path and an open descriptor on it, or ``None``. Each
    existing component is opened without following a link and checked before anything is
    created inside it; a missing one is created relative to its checked parent."""
    path = spelled_without_parent_steps(str(runs_parent()))
    if path is None:
        return None
    fd = os.open("/", _DIR_FLAGS)
    try:
        for part in path.split("/")[1:]:
            if not trusted_component(os.fstat(fd)):
                raise OSError("untrusted state path component")
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if (not trusted_component(info) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise OSError("board-runs is not private")
        return path, fd
    except OSError:
        os.close(fd)
        return None


@contextlib.contextmanager
def _parent_locked(parent_fd: int) -> Iterator[None]:
    fd = os.open(_PARENT_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                 dir_fd=parent_fd)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


class LegLogRun:
    """One run's private leg-log directory, held (``.active`` locked) until :meth:`finish`."""

    def __init__(self, path: Path, parent_fd: int, active_fd: int) -> None:
        self.path = path
        self._parent_fd: int | None = parent_fd
        self._active_fd: int | None = active_fd

    @classmethod
    def start(cls) -> "LegLogRun | None":
        """A fresh run under the validated private parent, or ``None`` when one cannot be
        made safely (the board then runs without retention, as before)."""
        if fcntl is None:
            return None
        opened = _open_private_parent()
        if opened is None:
            return None
        parent, parent_fd = opened
        name = _PREFIX + secrets.token_hex(8)
        run_fd = active_fd = None
        try:
            with _parent_locked(parent_fd):
                os.mkdir(name, 0o700, dir_fd=parent_fd)
                run_fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
                active_fd = os.open(_ACTIVE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                    | os.O_CLOEXEC, 0o600, dir_fd=run_fd)
                fcntl.flock(active_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if active_fd is not None:
                os.close(active_fd)
            shutil.rmtree(os.path.join(parent, name), ignore_errors=True)
            os.close(parent_fd)
            return None
        finally:
            if run_fd is not None:
                os.close(run_fd)
        return cls(Path(parent) / name, parent_fd, active_fd)

    def finish(self, details: Iterable[object]) -> Path | None:
        """Keep only the leg logs ``details`` name and mark the run complete, or remove it
        when none remains; then bound the other runs. Returns the path when it was kept."""
        refs = set()
        for detail in details:
            match = _LOG_REF.search(str(detail or ""))
            if match is not None:
                refs.add(match.group(1).split("/", 1)[1])
        kept = False
        try:
            with _parent_locked(self._parent_fd):
                kept = self._settle(refs)
                _prune_locked(self.path.parent, keep=KEEP_RUNS, max_age_s=MAX_AGE_S,
                              exclude=self.path)
        except OSError:
            kept = False
            shutil.rmtree(self.path, ignore_errors=True)
        finally:
            self._release()
        return self.path if kept and self.path.is_dir() else None

    def _settle(self, refs: set[str]) -> bool:
        logs = self.path / "leg-logs"
        try:
            entries = list(os.scandir(logs)) if logs.is_dir() and not logs.is_symlink() else []
        except OSError:
            entries = []
        kept = False
        for entry in entries:
            if entry.name in refs and entry.is_file(follow_symlinks=False):
                kept = True
                continue
            try:
                os.unlink(entry.path)
            except OSError:
                pass
        if not kept:
            shutil.rmtree(self.path, ignore_errors=True)
            return False
        os.close(os.open(self.path / _DONE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o600))
        os.unlink(self.path / _ACTIVE)
        return True

    def _release(self) -> None:
        for name in ("_active_fd", "_parent_fd"):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)


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


def prune(parent: Path, *, keep: int, max_age_s: float, exclude: Path | None = None) -> None:
    """:func:`_prune_locked` under the parent lock."""
    if fcntl is None:
        return
    try:
        parent_fd = os.open(parent, _DIR_FLAGS)
    except OSError:
        return
    try:
        with _parent_locked(parent_fd):
            _prune_locked(parent, keep=keep, max_age_s=max_age_s, exclude=exclude)
    except OSError:
        pass
    finally:
        os.close(parent_fd)


def _prune_locked(parent: Path, *, keep: int, max_age_s: float, exclude: Path | None) -> None:
    """Remove runs beyond the newest ``keep`` or older than ``max_age_s``, newest first
    by completion (a run left unfinished by a dead process by its directory time). Never
    ``exclude``, a held run, or anything but this module's own run directories."""
    runs = []
    try:
        for entry in os.scandir(parent):
            if not entry.name.startswith(_PREFIX) or not entry.is_dir(follow_symlinks=False):
                continue
            run = Path(entry.path)
            info = entry.stat(follow_symlinks=False)
            if (run == exclude or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077 or _held(run)):
                continue
            try:
                when = os.lstat(run / _DONE).st_mtime
            except OSError:
                when = info.st_mtime
            runs.append((when, run))
    except OSError:
        return
    now = time.time()
    for index, (when, run) in enumerate(sorted(runs, reverse=True)):
        if index >= keep or now - when > max_age_s:
            shutil.rmtree(run, ignore_errors=True)
