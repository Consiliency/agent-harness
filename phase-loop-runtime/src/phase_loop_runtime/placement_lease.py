"""The lease journal and the reaper for non-local placement (agent-harness#896, C6).

Every rung of a placement walk that is asked gets a lease: an id allocated here, written to
one file under ``<state home>/phase-loop/placement-leases/`` and fsynced with its directory
BEFORE the first call with a remote effect, then held under ``flock`` by the owning process
until the rung is left or the leg ends. A backend tags whatever it creates or reserves for a
request with the owner id and the lease id, so a sandbox whose owner died is found by its
lease, never by a pid, an age or whether a reference was recorded.

* A lease whose lock is HELD is live. No reaper touches it, this process's own included.
* A lease whose lock is FREE is the reaper's: its owner died, or gave it up at once
  (:meth:`Lease.abandon`) because a release could not be confirmed.
* An entry is cleared only when a kill by that lease id was acknowledged and the backend
  lists nothing for it.

An entry records the lease id, the backend name, the sanitized root, the ``sandbox_ref``
once known, ``created_at``, ``confirmed_killed_at`` and whether it was abandoned. It never
records request or result bytes.
"""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Callable

from . import sandbox_placement, sandbox_policy, seat_jail

__all__ = ["Lease", "open_lease", "owner_id", "reap"]

_LEASE_DIRNAME = "placement-leases"
_OWNER_FILENAME = "placement-owner-id"
_ID = re.compile(r"[0-9a-f]{32}")
_ENTRY = re.compile(r"([0-9a-f]{32})\.json")
# An entry is written and locked under this name and only then renamed into place, so a
# name matching `_ENTRY` is always a complete entry whose lock its owner already held.
_PENDING = re.compile(r"\.([0-9a-f]{32})\.pending")
_ENTRY_MAX = 65536
#: The owner id is created once and never changes, so it is read once per state home.
_OWNER: dict[Path, str] = {}


def _fsync(fd: int) -> None:
    """A seam: the tests order the journal's syncs against the backend's calls."""
    os.fsync(fd)


def _state_dir() -> Path:
    return seat_jail.state_home() / "phase-loop"


def _lease_dir() -> Path:
    return _state_dir() / _LEASE_DIRNAME


def _private_dir(path: Path) -> int:
    """Open the lease directory (0700, created if absent) and return its descriptor.
    A link, or a directory that is not this user's, is refused."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid():
            raise PermissionError(errno.EPERM, "the placement lease directory is not this user's")
        if info.st_mode & 0o077:
            os.fchmod(fd, 0o700)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _read_owner(path: Path) -> str | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid():
            raise PermissionError(errno.EPERM, "the placement owner id is not this user's")
        if info.st_mode & 0o077:
            os.fchmod(fd, 0o600)
        text = os.read(fd, 64).decode("ascii", "replace").strip()
    finally:
        os.close(fd)
    if not _ID.fullmatch(text):
        raise ValueError("the placement owner id file is malformed")
    return text


def owner_id() -> str:
    """This user's placement owner id: random, created once, kept 0600 under the state home.

    A backend tags what it creates with it and lists by it. It names no user and no host,
    and it lives beside the lease journal, so an id and its leases are always found
    together."""
    path = _state_dir() / _OWNER_FILENAME
    cached = _OWNER.get(path)
    if cached is not None:
        return cached
    found = _read_owner(path)
    if found is not None:
        _OWNER[path] = found
        return found
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{_OWNER_FILENAME}.{secrets.token_hex(8)}")
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, (secrets.token_hex(16) + "\n").encode("ascii"))
        _fsync(fd)
    finally:
        os.close(fd)
    try:
        # Create-if-absent: of two first users, one id wins and both read it.
        os.link(pending, path)
    except FileExistsError:
        pass
    finally:
        os.unlink(pending)
    found = _read_owner(path)
    if found is None:
        raise FileNotFoundError(errno.ENOENT, "the placement owner id could not be created")
    _OWNER[path] = found
    return found


def _sanitized(root: object) -> str:
    """A root as the journal records it: rebuilt from parsed parts, so userinfo, a query
    and a fragment never reach the file."""
    if isinstance(root, (str, os.PathLike)):
        root = sandbox_policy.parse_location(root)
    return sandbox_placement._root_text(root)


def _write_entry(fd: int, entry: dict[str, object]) -> None:
    # One line, written in one call from offset 0: a reader takes the first line only, so a
    # crash between the write and the truncate still leaves a complete entry.
    data = (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8")
    os.pwrite(fd, data, 0)
    os.ftruncate(fd, len(data))
    _fsync(fd)


def _read_entry(fd: int) -> dict[str, object] | None:
    try:
        entry = json.loads(os.pread(fd, _ENTRY_MAX, 0).split(b"\n", 1)[0])
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


class Lease:
    """One rung's lease, held under ``flock`` by this process until it is cleared or
    abandoned."""

    def __init__(
        self, *, lease_id: str, owner: str, path: Path, fd: int, entry: dict[str, object],
    ) -> None:
        self.lease_id = lease_id
        self.owner_id = owner
        self.path = path
        #: The driver's side of the fence: once set, `execute` is never sent for this lease.
        self.fenced = False
        self._fd: int | None = fd
        self._entry = entry
        self._lock = threading.Lock()

    @property
    def held(self) -> bool:
        """Does this process still hold the lease lock?"""
        return self._fd is not None

    def fence(self) -> None:
        self.fenced = True

    def _update(self, **fields: object) -> None:
        with self._lock:
            if self._fd is None:
                return
            self._entry.update(fields)
            _write_entry(self._fd, self._entry)

    def record_sandbox_ref(self, sandbox_ref: str) -> None:
        self._update(sandbox_ref=str(sandbox_ref))

    def note_killed(self) -> None:
        """The backend acknowledged a kill by this lease id."""
        self._update(confirmed_killed_at=time.time())

    def _unlock(self) -> None:
        with self._lock:
            fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)  # closing the descriptor releases the flock

    def abandon(self) -> None:
        """Leave a rung without a confirmed release: mark the entry, KEEP it, and give the
        lock up at once so that any reaper, this process's own included, may act on it. An
        abandoned lease is fenced for good."""
        self.fenced = True
        try:
            self._update(abandoned=True)
        except OSError:
            pass
        self._unlock()

    def clear(self) -> None:
        """Remove the entry: nothing is held for this lease. If the entry cannot be removed
        it stays with a free lock, which only sends a reaper to confirm it again."""
        try:
            os.unlink(self.path)
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                _fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        self._unlock()

    def heartbeat(self, renew: Callable[[], object], interval_s: float) -> Callable[[], None]:
        """Renew on an interval for as long as this process holds the lease lock, and stop
        with the leg: the returned function ends it.

        ``renew`` is one renewal, bounded by its caller. A renewal that times out ends the
        heartbeat, since a far end that does not answer within the bound is not kept alive
        by asking again; any other failure is tried again at the next interval. The leg
        never waits for a renewal."""
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(max(0.0, interval_s)):
                if not self.held:
                    return
                try:
                    renew()
                except sandbox_placement.PlacementUnavailable as exc:
                    if exc.code == sandbox_placement._TIMEOUT:
                        return
                except Exception:
                    continue

        threading.Thread(target=beat, name="placement-renew", daemon=True).start()
        return stop.set


def open_lease(backend_name: str | None, root: object) -> Lease:
    """Allocate a lease for one rung and make its entry durable.

    The entry is written and locked under a pending name, fsynced, renamed into place, and
    its directory fsynced, all before this returns -- so before ``admit``. From the moment
    the entry has its name, its lock is held by this process."""
    import fcntl  # POSIX-only; imported lazily so the package imports elsewhere

    owner = owner_id()
    lease_id = secrets.token_hex(16)
    directory = _lease_dir()
    dir_fd = _private_dir(directory)
    pending, final = f".{lease_id}.pending", f"{lease_id}.json"
    try:
        fd = os.open(
            pending, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
            dir_fd=dir_fd,
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            entry: dict[str, object] = {
                "lease_id": lease_id,
                "backend": str(backend_name or ""),
                "root": _sanitized(root),
                "sandbox_ref": None,
                "created_at": time.time(),
                "confirmed_killed_at": None,
                "abandoned": False,
            }
            _write_entry(fd, entry)
            os.rename(pending, final, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            _fsync(dir_fd)
        except BaseException:
            os.close(fd)
            for name in (pending, final):
                try:
                    os.unlink(name, dir_fd=dir_fd)
                except OSError:
                    pass
            raise
    finally:
        os.close(dir_fd)
    return Lease(lease_id=lease_id, owner=owner, path=directory / final, fd=fd, entry=entry)


def _lock_free(directory: Path, lease_id: str) -> bool:
    """Is no process holding this lease? A lease with no entry at all is free: the owner id
    and the journal live together, so a sandbox of this owner without an entry is nobody's."""
    import fcntl

    for name in (f"{lease_id}.json", f".{lease_id}.pending"):
        try:
            fd = os.open(directory / name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        finally:
            os.close(fd)
    return True


def reap(
    backends: Callable[[str], object],
    bound: "sandbox_placement.OperationBound",
) -> dict[str, tuple[str, ...]]:
    """Kill what dead or abandoned leases left behind, driven by the journal.

    ``backends(scheme)`` returns the backend for a root's scheme, or ``None``. It is called
    only for an entry whose lock is free: with no such entry no backend is contacted and
    no plugin is loaded. For a contacted backend: everything it lists for this owner whose
    lease lock is free is killed by lease id, and so is every free entry naming it, listed
    or not (the kill is also the fence); then the listing is read again, and an entry is
    cleared only when its kill was acknowledged and nothing is listed for it. Anything else
    is kept for the next run. Liveness is never decided by a pid or an age.

    Returns the lease ids ``cleared`` and ``kept``.
    """
    import fcntl

    directory = _lease_dir()
    cleared: list[str] = []
    kept: list[str] = []
    free: list[tuple[str, int, Path, dict[str, object] | None]] = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    try:
        for name in names:
            match = _ENTRY.fullmatch(name) or _PENDING.fullmatch(name)
            if match is None:
                continue
            try:
                fd = os.open(directory / name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            except OSError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)  # held: a live lease
                continue
            if name.startswith("."):
                # Never renamed into place, so nothing was ever sent for it.
                try:
                    os.unlink(directory / name)
                except OSError:
                    pass
                os.close(fd)
                continue
            free.append((match.group(1), fd, directory / name, _read_entry(fd)))
        by_scheme: dict[str, list[tuple[str, int, Path, dict[str, object]]]] = {}
        for lease_id, fd, path, entry in free:
            scheme = sandbox_policy.parse_location(str((entry or {}).get("root", ""))).scheme
            if entry is None or not sandbox_placement._SCHEME.fullmatch(scheme):
                kept.append(lease_id)  # unreadable: never guessed at
                continue
            by_scheme.setdefault(scheme, []).append((lease_id, fd, path, entry))
        for scheme, group in by_scheme.items():
            try:
                backend = backends(scheme)
            except Exception:
                backend = None
            if backend is None or bound.cancelled.is_set():
                kept.extend(lease_id for lease_id, _fd, _path, _entry in group)
                continue
            done = _reap_backend(backend, group, directory, bound)
            cleared.extend(done)
            kept.extend(lease_id for lease_id, _fd, _path, _entry in group if lease_id not in done)
    finally:
        for _lease_id, fd, _path, _entry in free:
            os.close(fd)
    return {"cleared": tuple(cleared), "kept": tuple(kept)}


def _reap_backend(
    backend: object, group: list[tuple[str, int, Path, dict[str, object]]], directory: Path,
    bound: "sandbox_placement.OperationBound",
) -> set[str]:
    """One backend: list, kill by lease, confirm, clear. Returns the lease ids cleared."""
    calls = sandbox_placement._Calls()
    owner = owner_id()

    def listed() -> set[str] | None:
        try:
            pairs = calls.run(
                # Read to the end inside the bound: a listing may arrive in pages.
                lambda: [tuple(pair) for pair in backend.list_owned(owner, bound)],  # type: ignore[attr-defined]
                bound.timeout_s, bound.cancelled,
            )
            return {str(pair[1]) for pair in pairs}  # type: ignore[union-attr]
        except Exception:
            return None

    try:
        mine = [lease_id for lease_id, _fd, _path, _entry in group]
        targets = list(mine)
        for lease_id in sorted((listed() or set()) - set(mine)):
            if _ID.fullmatch(lease_id) and _lock_free(directory, lease_id):
                targets.append(lease_id)
        killed: set[str] = set()
        for lease_id in targets:
            try:
                calls.run(
                    lambda lease_id=lease_id: backend.kill(lease_id, bound),  # type: ignore[attr-defined]
                    bound.timeout_s, bound.cancelled,
                )
                killed.add(lease_id)
            except Exception:
                continue
        still = listed()
        done: set[str] = set()
        for lease_id, fd, path, entry in group:
            if lease_id in killed and still is not None and lease_id not in still:
                try:
                    os.unlink(path)
                    done.add(lease_id)
                except OSError:
                    pass
                continue
            if lease_id in killed:
                entry["confirmed_killed_at"] = time.time()
            entry["abandoned"] = True
            try:
                _write_entry(fd, entry)
            except OSError:
                pass
        return done
    finally:
        calls.close()
