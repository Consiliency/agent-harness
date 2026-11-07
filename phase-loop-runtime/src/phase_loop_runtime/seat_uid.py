"""The subordinate seat uid (maintainer decision D8, agent-harness#1132).

A jailed seat never runs as the operator's uid. The egress holder's user namespace H is
created WITHOUT a map; the parent then maps it with the setuid ``newuidmap`` /
``newgidmap`` helpers so that, in H, uid 0 is the operator and uids 1..count are the
operator's subordinate range. Each launch leases one seat id n in 1..count and runs its
provider as n, with no capabilities.

Host prerequisite, run once per host by the maintainer as root and NEVER by this runtime:
``apt install uidmap`` and ``usermod --add-subuids <range> --add-subgids <range>
<operator>``. Without it :func:`seat_uid_available` is False and the seat takes the sealed
route with ``seat_sandbox_unavailable_seat_uid``.

The in-H helpers (``handoff``, ``read``, ``scan``, ``teardown``) run as H-root through
``python -m phase_loop_runtime.seat_uid <verb> ...``.
"""

from __future__ import annotations

import base64
import contextlib
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from . import seat_jail

SUBUID_FILE = Path("/etc/subuid")
SUBGID_FILE = Path("/etc/subgid")
NEWUIDMAP = "/usr/bin/newuidmap"
NEWGIDMAP = "/usr/bin/newgidmap"
# The most seat ids a runtime will lease, whatever the range size.
MAX_SEAT_IDS = 256

PREREQUISITE = (
    "maintainer prerequisite (root, once per host): apt install uidmap, then "
    "usermod --add-subuids <start>-<end> --add-subgids <start>-<end> <operator>"
)


@dataclass(frozen=True)
class SubordinateRange:
    start: int
    count: int


def _operator_name(uid: int) -> str | None:
    import pwd  # POSIX-only; imported lazily so panel_invoker imports on Windows

    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return None


def subordinate_range(path: Path, uid: int | None = None) -> SubordinateRange | None:
    """The operator's first usable range in ``/etc/subuid`` or ``/etc/subgid``.

    Lines are ``<name-or-uid>:<start>:<count>``. A malformed line is skipped. The range
    must hold at least 1 + one seat id (count >= 2)."""
    uid = os.getuid() if uid is None else uid
    owners = {str(uid)}
    name = _operator_name(uid)
    if name:
        owners.add(name)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.strip().split(":")
        if len(parts) != 3 or parts[0] not in owners:
            continue
        try:
            start, count = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if start > 0 and count >= 2:
            return SubordinateRange(start, count)
    return None


def _privileged_helper(path: str) -> bool:
    """``newuidmap``/``newgidmap`` present and able to act: setuid root, or carrying
    file capabilities (some distributions ship them that way)."""
    try:
        info = os.stat(path)
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        return False
    if info.st_uid == 0 and info.st_mode & stat.S_ISUID:
        return True
    try:
        return bool(os.getxattr(path, "security.capability"))
    except OSError:
        return False


def seat_runtime_dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isabs(runtime):
        return Path(runtime) / "phase-loop" / "seat-uid"
    from .seat_host_namespace import operator_private_dir

    return operator_private_dir(
        "seat_uid_leases", base=Path(tempfile.gettempdir()) / f"phase-loop-{os.getuid()}"
    )


def seat_uid_available(
    *,
    uid: int | None = None,
    subuid: Path = SUBUID_FILE,
    subgid: Path = SUBGID_FILE,
    newuidmap: str = NEWUIDMAP,
    newgidmap: str = NEWGIDMAP,
) -> bool:
    """Whether the host has the seat-uid prerequisites (capacity is checked at L9).

    This deliberately does not acquire and release a seat-id lease.  Availability probes
    raced the real acquisition and conflated a configured host with exhausted capacity.
    """
    uid = os.getuid() if uid is None else uid
    if uid == 0:
        return False
    if not (_privileged_helper(newuidmap) and _privileged_helper(newgidmap)):
        return False
    uids = subordinate_range(subuid, uid)
    gids = subordinate_range(subgid, uid)
    if uids is None or gids is None:
        return False
    from .seat_host_namespace import subordinate_ranges_disjoint

    if not subordinate_ranges_disjoint(uid, subuid=subuid, subgid=subgid):
        return False
    return seat_id_count(uids, gids) > 0


seat_uid_prerequisites_available = seat_uid_available


def seat_id_count(uids: SubordinateRange, gids: SubordinateRange) -> int:
    """How many seat ids H can hold: 1..count map onto the subordinate range."""
    return min(uids.count, gids.count, MAX_SEAT_IDS)


class SeatIdsExhausted(RuntimeError):
    pass


class SeatIdLease:
    """A nonblocking lease whose lifetime is explicit and whose release is idempotent."""

    def __init__(self, manager, seat_id: int):
        self._manager = manager
        self.seat_id = seat_id
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._manager.__exit__(None, None, None)


class SeatIdCapacity:
    """Production adapter for the resolver's ``SeatCapacity`` protocol."""

    def __init__(self, count: int | None = None, *, directory: Path | None = None):
        self._count = count
        self._directory = directory

    def _seat_count(self) -> int | None:
        if self._count is not None:
            return self._count
        uids = subordinate_range(SUBUID_FILE)
        gids = subordinate_range(SUBGID_FILE)
        if uids is None or gids is None:
            return None
        return seat_id_count(uids, gids)

    def try_lease(self) -> SeatIdLease | None:
        count = self._seat_count()
        if count is None:
            return None
        manager = lease_seat_id(count, directory=self._directory)
        try:
            seat_id = manager.__enter__()
        except (SeatIdsExhausted, OSError):
            return None
        return SeatIdLease(manager, seat_id)


@contextlib.contextmanager
def lease_seat_id(count: int, *, directory: Path | None = None) -> Iterator[int]:
    """Lease one seat id n in 1..count for the life of the ``with`` block.

    An ``flock`` on ``<runtime>/phase-loop/seat-uid/<n>.lock``: concurrent seats never
    share a uid, and a crashed holder's lease is released by the kernel."""
    import fcntl  # POSIX-only; imported lazily so panel_invoker imports on Windows

    directory = directory or seat_runtime_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for n in range(1, count + 1):
        fd = os.open(directory / f"{n}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        try:
            yield n
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return
    raise SeatIdsExhausted("every seat id is leased")


def uid_map_argv(helper: str, pid: int, operator_id: int, sub: SubordinateRange,
                 count: int) -> list[str]:
    """``newuidmap <pid> 0 <operator> 1 1 <start> <count>`` (and the gid twin):
    in H, 0 is the operator and 1..count the subordinate range."""
    return [helper, str(pid), "0", str(operator_id), "1", "1", str(sub.start), str(count)]


def map_holder(pid: int, *, uid: int | None = None, gid: int | None = None,
               subuid: Path = SUBUID_FILE, subgid: Path = SUBGID_FILE,
               timeout_s: float = 15.0) -> int:
    """Write H's uid and gid maps. Returns the seat-id count. Raises ``OSError``."""
    uid = os.getuid() if uid is None else uid
    gid = os.getgid() if gid is None else gid
    uids = subordinate_range(subuid, uid)
    gids = subordinate_range(subgid, uid)
    if uids is None or gids is None:
        raise OSError(errno.EPERM, "no subordinate range for the operator")
    count = seat_id_count(uids, gids)
    for argv in (uid_map_argv(NEWUIDMAP, pid, uid, uids, count),
                 uid_map_argv(NEWGIDMAP, pid, gid, gids, count)):
        done = subprocess.run(argv, capture_output=True, timeout=timeout_s,
                              stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"})
        if done.returncode != 0:
            raise OSError(errno.EPERM, f"{os.path.basename(argv[0])} failed")
    return count


def subordinate_host_uid(n: int, *, uid: int | None = None, subuid: Path = SUBUID_FILE) -> int:
    """The host uid that H uid n maps to."""
    uids = subordinate_range(subuid, os.getuid() if uid is None else uid)
    if uids is None or not 1 <= n <= uids.count:
        raise ValueError("seat id outside the subordinate range")
    return uids.start + n - 1


def owned_by_subordinate(host_uid: int, *, uid: int | None = None,
                         subuid: Path = SUBUID_FILE) -> bool:
    uids = subordinate_range(subuid, os.getuid() if uid is None else uid)
    return uids is not None and uids.start <= host_uid < uids.start + uids.count


# --------------------------------------------------------------------------------------
# The in-H hand-off (plan "Launch order inside H", step 3).
# --------------------------------------------------------------------------------------

def chown_tree_at(dir_fd: int, uid: int, gid: int) -> None:
    """``fchownat(..., AT_SYMLINK_NOFOLLOW)`` over everything under ``dir_fd`` and the
    directory itself. Never follows a link."""
    os.chown(dir_fd, uid, gid)
    for name in os.listdir(dir_fd):
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=dir_fd)
            try:
                chown_tree_at(child, uid, gid)
            finally:
                os.close(child)
        else:
            os.chown(name, uid, gid, dir_fd=dir_fd, follow_symlinks=False)


def handoff(review_dir: str, seat_id: int, *, gemini: bool = False,
            tree: str | None = None) -> None:
    """As H-root: prove the stage is private inodes, then hand the three seat
    directories to n:n. Raises :class:`seat_jail.SeatSandboxRefused`.

    The nlink proof comes FIRST: H-root holds CAP_FOWNER in H, so a chown over a stage
    that shared an inode with an operator file outside it would re-own that file."""
    root = seat_jail.open_dir_nofollow(review_dir)
    try:
        tree_fd = (seat_jail.open_dir_nofollow(tree) if tree is not None
                   else seat_jail.open_dir_nofollow(seat_jail.HOST_TREE_DIRNAME, dir_fd=root))
        try:
            if not seat_jail.tree_is_private(tree_fd):
                raise seat_jail.SeatSandboxRefused(seat_jail.refused("stage_not_private"))
            chown_tree_at(tree_fd, seat_id, seat_id)
        finally:
            os.close(tree_fd)
        for name in (seat_jail.HOST_HOME_DIRNAME, seat_jail.HOST_OUT_DIRNAME):
            fd = seat_jail.open_dir_nofollow(name, dir_fd=root)
            try:
                chown_tree_at(fd, seat_id, seat_id)
            finally:
                os.close(fd)
        if gemini:
            # Owned by H-root (the operator), group n: the seat reads through the group
            # grant and can neither write nor chmod it. The `.gemini` tree (ancestor + its
            # `antigravity-cli` and the writable mount points) is now more than one level
            # deep (agent-harness#1170 F006), so hand it off recursively: directories 0550
            # so the seat can traverse to the config, regular files 0440.
            fd = seat_jail.open_dir_nofollow(seat_jail.HOST_GEMINI_CONFIG_DIRNAME, dir_fd=root)
            try:
                _handoff_gemini_tree_at(fd, seat_id)
            finally:
                os.close(fd)
    finally:
        os.close(root)


def _handoff_gemini_tree_at(dir_fd: int, seat_id: int) -> None:
    """``fchownat(..., AT_SYMLINK_NOFOLLOW)`` the agy config tree to H-root:seat_id, with
    directories 0550 (traversable, not writable) and regular files 0440. Recurses without
    following any link; a non-regular, non-directory entry is refused."""
    os.chown(dir_fd, 0, seat_id)
    os.chmod(dir_fd, 0o550)
    for name in os.listdir(dir_fd):
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = seat_jail.open_dir_nofollow(name, dir_fd=dir_fd)
            try:
                _handoff_gemini_tree_at(child, seat_id)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            os.chown(name, 0, seat_id, dir_fd=dir_fd, follow_symlinks=False)
            os.chmod(name, 0o440, dir_fd=dir_fd, follow_symlinks=False)
        else:
            raise seat_jail.SeatSandboxRefused(
                seat_jail.refused("gemini_credential_unsafe"), f"unexpected config entry {name!r}")


SEAT_DIR_NAMES: tuple[str, ...] = (
    seat_jail.HOST_TREE_DIRNAME, seat_jail.HOST_HOME_DIRNAME, seat_jail.HOST_OUT_DIRNAME,
    seat_jail.HOST_GEMINI_CONFIG_DIRNAME,
)


def teardown(review_dir: str) -> list[str]:
    """As H-root: the J2 fd-relative removal of every seat directory. Returns the names
    that could NOT be removed (empty on success); never follows a link."""
    retained: list[str] = []
    root = seat_jail.open_dir_nofollow(review_dir)
    try:
        for name in SEAT_DIR_NAMES:
            try:
                os.stat(name, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                continue
            try:
                seat_jail.remove_tree_at(root, name)
            except OSError:
                retained.append(name)
    finally:
        os.close(root)
    return retained


# --------------------------------------------------------------------------------------
# Retention records and reap (F020, F022).
# --------------------------------------------------------------------------------------

def retention_dir() -> Path:
    return seat_jail.state_home() / "phase-loop" / "seat-retained"


def stage_root() -> Path:
    """Where panel scratch directories are created: the parent of every retained path.

    Follows `sandbox_policy.staging_root()` where the runtime has it (agent-harness#1147),
    else the temp dir `_default_spawn` stages under."""
    from . import sandbox_policy

    staging_root = getattr(sandbox_policy, "staging_root", None)
    return Path(staging_root() if staging_root is not None else tempfile.gettempdir()).resolve()


def record_retention(retained_path: Path, *, directory: Path | None = None) -> Path:
    """Record a retained directory so ``reap`` may later remove it.

    The retained directory's parent chain includes the leg's ``mkdtemp`` scratch dir,
    which is operator-owned and 0700 (F020); the record states it."""
    directory = directory or retention_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {"path": str(retained_path), "recorded_at": int(time.time()),
              "operator_uid": os.getuid()}
    fd, name = tempfile.mkstemp(prefix="retained-", suffix=".json", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
    return Path(name)


class ReapRefused(RuntimeError):
    pass


def validate_reap_target(path: str, *, records: Path | None = None,
                         root: Path | None = None, subuid: Path = SUBUID_FILE) -> int:
    """F022: ``reap`` accepts only a path recorded by a retention notice, under the stage
    root, opened ``O_NOFOLLOW|O_DIRECTORY`` component by component, and owned by a
    subordinate uid. Returns an open directory fd for the target's PARENT; raises
    :class:`ReapRefused` otherwise."""
    records = records or retention_dir()
    root = (root or stage_root())
    recorded: set[str] = set()
    try:
        entries = sorted(records.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            document = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and isinstance(document.get("path"), str):
            recorded.add(document["path"])
    if path not in recorded:
        raise ReapRefused("not recorded by a retention notice")
    candidate = Path(path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ReapRefused("not an absolute contained path")
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ReapRefused("not under the stage root") from exc
    parts = relative.parts
    if not parts:
        raise ReapRefused("is the stage root itself")
    fds: list[int] = []
    try:
        current = seat_jail.open_dir_nofollow(root)
        fds.append(current)
        for part in parts[:-1]:
            current = seat_jail.open_dir_nofollow(part, dir_fd=current)
            fds.append(current)
        # O_PATH: the operator cannot READ a seat-owned 0700 directory, but may name it
        # and fstat it -- which is all the owner check needs.
        leaf = os.open(parts[-1], os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                       dir_fd=current)
    except OSError as exc:
        for fd in fds:
            os.close(fd)
        raise ReapRefused("not a directory reachable without following a link") from exc
    try:
        owner = os.fstat(leaf).st_uid
    finally:
        os.close(leaf)
    if not owned_by_subordinate(owner, subuid=subuid):
        for fd in fds:
            os.close(fd)
        raise ReapRefused("not owned by a subordinate seat uid")
    parent = fds.pop()
    for fd in fds:
        os.close(fd)
    return parent


# --------------------------------------------------------------------------------------
# Running a helper inside H.
# --------------------------------------------------------------------------------------

# A helper module runs from THIS installation, whatever the launch's working directory:
# ``-I`` keeps the working directory, PYTHON* variables and the user site off the import
# path, and the boot puts this package's own root first.
_PACKAGE_ROOT = str(Path(__file__).resolve().parent.parent)
_TRUSTED_BOOT = ("import sys, runpy; sys.path.insert(0, sys.argv.pop(1)); "
                 "runpy.run_module(sys.argv.pop(1), run_name='__main__', alter_sys=True)")


def trusted_module_argv(module: str, *args: str) -> list[str]:
    """The argv that runs ``module`` (a ``phase_loop_runtime`` module) as ``__main__`` from
    the installation this process imported, never from the working directory."""
    if not module.startswith("phase_loop_runtime."):
        raise ValueError("only this package's helpers are launched this way")
    return [sys.executable, "-I", "-c", _TRUSTED_BOOT, _PACKAGE_ROOT, module, *args]


def in_h_argv(holder_pid: int, verb: str, *args: str) -> list[str]:
    """``nsenter`` into H as H-root, then this module's helper ``verb``."""
    return ["/usr/bin/nsenter", "-t", str(holder_pid), "-U", "-m", "--preserve-credentials",
            *trusted_module_argv("phase_loop_runtime.seat_uid", verb, *args)]


class SeatObjectMissing(FileNotFoundError):
    """The seat has not (yet) created the object: not a refusal."""


_READ_MISSING = 4


def read_in_h(holder_pid: int, root: str, relpath: str, cap_bytes: int,
              *, timeout_s: float = 30.0) -> bytes:
    """The J10 reader, run in H as H-root, streaming the bytes to the parent. Raises
    :class:`SeatObjectMissing` when nothing is there yet, and
    :class:`seat_jail.UnsafeSeatObject` on any refusal."""
    done = subprocess.run(in_h_argv(holder_pid, "read", root, relpath, str(cap_bytes)),
                          capture_output=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                          env=_pythonpath_env())
    if done.returncode == _READ_MISSING:
        raise SeatObjectMissing(relpath)
    if done.returncode != 0 or len(done.stdout) > cap_bytes:
        raise seat_jail.UnsafeSeatObject(errno.EINVAL, "seat object refused")
    return done.stdout


def _pythonpath_env() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": _PACKAGE_ROOT, "LC_ALL": "C"}


def holder_pid_from_prefix(prefix: Sequence[str]) -> int:
    """H's holder pid, from an egress launch prefix (``nsenter ... -t <pid> ...``)."""
    items = list(prefix)
    return int(items[items.index("-t") + 1])


def teardown_in_h(holder_pid: int, review_dir: str) -> list[str]:
    """Run :func:`teardown` in H. Returns what was retained; a helper that could not run
    at all retains everything it was asked to remove."""
    try:
        done = subprocess.run(in_h_argv(holder_pid, "teardown", review_dir),
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
                              env=_pythonpath_env())
    except (OSError, subprocess.SubprocessError):
        return list(SEAT_DIR_NAMES)
    if done.returncode == 0:
        return []
    try:
        retained = json.loads(done.stdout)
    except ValueError:
        return list(SEAT_DIR_NAMES)
    if not isinstance(retained, list) or not retained:
        return list(SEAT_DIR_NAMES)
    return [str(item) for item in retained if item in SEAT_DIR_NAMES] or list(SEAT_DIR_NAMES)


def run_in_h(holder_pid: int, verb: str, *args: str, timeout_s: float = 60.0) -> int:
    return subprocess.run(in_h_argv(holder_pid, verb, *args), stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=timeout_s,
                          env=_pythonpath_env()).returncode


@contextlib.contextmanager
def mapped_namespace() -> Iterator[int]:
    """A fresh user namespace mapped like H, for ``reap``: yields its holder pid."""
    from .sandbox_egress import _wait_for_new_user_namespace

    holder = subprocess.Popen(["/usr/bin/unshare", "--user", "--mount", "/bin/sh", "-c",
                               "read -r _gate; exec sleep 600"],
                              stdin=subprocess.PIPE, env={"PATH": "/usr/bin:/bin"})
    try:
        # Board round 1 (codex): the map can only be written once the holder IS in its new
        # user namespace; `Popen` returns before `unshare` has made the call.
        _wait_for_new_user_namespace(holder)
        map_holder(holder.pid)
        yield holder.pid
    finally:
        holder.kill()
        holder.wait(timeout=5)


def reap(path: str) -> None:
    """Remove a retained seat directory (``phase-loop seat-sandbox reap``)."""
    parent = validate_reap_target(path)
    os.close(parent)
    with mapped_namespace() as pid:
        if run_in_h(pid, "remove", path) != 0:
            raise ReapRefused("teardown failed; directory kept")


# --------------------------------------------------------------------------------------
# The read-only ``scan`` verb (plans/seats-firstseat-containment-contract.md section 16).
# --------------------------------------------------------------------------------------

SCAN_SCHEMA = "seat_scan.v1"
SCAN_CAP_BYTES = 16 * 1024 * 1024
SCAN_TIME_LIMIT_S = 60.0
#: Section 10's field names, looked for in entry names and contents.
SCAN_FIELD_NAMES: tuple[bytes, ...] = (b"access_token", b"refresh_token", b"id_token",
                                       b"client_secret")
_SCAN_BASES = ("tree", "seat")
_SCAN_SEAT_DIRS = (seat_jail.HOST_HOME_DIRNAME, seat_jail.HOST_OUT_DIRNAME)
_SCAN_MAX_ROWS = 512
_SCAN_FLAGS_AVAILABLE = all(hasattr(os, name) for name in (
    "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC", "O_DIRECTORY"))
_SCAN_O_FILE = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
_SCAN_O_DIR = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
               | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))


class _Walk:
    """One bounded walk: counts and completeness only ever move one way."""

    def __init__(self, cap_bytes: int, time_limit_s: float, encodings: tuple[bytes, ...]):
        self.cap = cap_bytes
        self.deadline = time.monotonic() + time_limit_s
        self.encodings = encodings
        self.complete = True
        self.entries = 0
        self.field_names = 0
        self.delivered_token = 0

    def expired(self) -> bool:
        if time.monotonic() >= self.deadline:
            self.complete = False
            return True
        return False

    def count(self, data: bytes) -> None:
        if any(name in data for name in SCAN_FIELD_NAMES):
            self.field_names += 1
        if self.encodings and any(form in data for form in self.encodings):
            self.delivered_token += 1

    def read(self, dir_fd: int, name: str, info: os.stat_result) -> bytes | None:
        """A regular entry's bytes, or ``None`` (incomplete) when over the cap or unreadable."""
        if info.st_size > self.cap:
            self.complete = False
            return None
        try:
            fd = os.open(name, _SCAN_O_FILE, dir_fd=dir_fd)
        except OSError:
            self.complete = False
            return None
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino)
                    != (info.st_dev, info.st_ino) or opened.st_size > self.cap):
                self.complete = False
                return None
            chunks, total = [], 0
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.cap:
                    self.complete = False
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        except OSError:
            self.complete = False
            return None
        finally:
            os.close(fd)

    def tree(self, dir_fd: int, prefix: str, manifest: list | None) -> None:
        """Walk ``dir_fd`` without following links. A link or non-regular entry is counted
        and recorded without being opened; a directory is descended."""
        try:
            names = sorted(os.listdir(dir_fd))
        except OSError:
            self.complete = False
            return
        for name in names:
            if self.expired():
                return
            self.entries += 1
            raw = os.fsencode(name)
            self.count(raw)
            relative = f"{prefix}{name}"
            try:
                info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except OSError:
                self.complete = False
                continue
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                if manifest is not None:
                    manifest.append([relative, mode, "dir"])
                try:
                    child = os.open(name, _SCAN_O_DIR, dir_fd=dir_fd)
                except OSError:
                    self.complete = False
                    continue
                try:
                    self.tree(child, relative + "/", manifest)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                data = self.read(dir_fd, name, info)
                if data is not None:
                    self.count(data)
                if manifest is not None:
                    manifest.append([relative, mode, hashlib.sha256(data).hexdigest()
                                     if data is not None else "unread"])
            elif manifest is not None:
                manifest.append([relative, mode, "link" if stat.S_ISLNK(info.st_mode) else "other"])


def _manifest_digest(entries: list) -> str:
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode("utf-8")).hexdigest()


def _scan_row(base_fd: int, relpath: str, walk: _Walk) -> dict[str, object]:
    """One row's post-leg state, resolved one component at a time without following a
    link. A link at the row or at any ancestor is reported as ``link``, never opened."""
    parts = [part for part in relpath.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return {"kind": "other", "digest": None, "mode": None}
    fds: list[int] = []
    try:
        current = base_fd
        for part in parts[:-1]:
            try:
                info = os.stat(part, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                return {"kind": "missing", "digest": None, "mode": None}
            except OSError:
                walk.complete = False
                return {"kind": "other", "digest": None, "mode": None}
            if stat.S_ISLNK(info.st_mode):
                return {"kind": "link", "digest": None, "mode": None}
            if not stat.S_ISDIR(info.st_mode):
                return {"kind": "other", "digest": None, "mode": None}
            current = os.open(part, _SCAN_O_DIR, dir_fd=current)
            fds.append(current)
        try:
            info = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return {"kind": "missing", "digest": None, "mode": None}
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            return {"kind": "link", "digest": None, "mode": mode}
        if stat.S_ISREG(info.st_mode):
            data = walk.read(current, parts[-1], info)
            return {"kind": "file", "mode": mode,
                    "digest": hashlib.sha256(data).hexdigest() if data is not None else None}
        if stat.S_ISDIR(info.st_mode):
            child = os.open(parts[-1], _SCAN_O_DIR, dir_fd=current)
            try:
                entries: list = []
                inner = _Walk(walk.cap, max(0.0, walk.deadline - time.monotonic()), ())
                inner.tree(child, "", entries)
                if not inner.complete:
                    walk.complete = False
            finally:
                os.close(child)
            return {"kind": "dir", "mode": mode,
                    "digest": _manifest_digest(entries) if inner.complete else None}
        return {"kind": "other", "digest": None, "mode": mode}
    except OSError:
        walk.complete = False
        return {"kind": "other", "digest": None, "mode": None}
    finally:
        for fd in reversed(fds):
            os.close(fd)


def scan(seat_root: str, tree: str, rows: Mapping[str, tuple[str, str]], *,
         token: bytes | None, cap_bytes: int = SCAN_CAP_BYTES,
         time_limit_s: float = SCAN_TIME_LIMIT_S) -> dict[str, object]:
    """The ``scan`` verb's body: post-leg row digests, the post-leg tree manifest and the
    section 10 counts over the tree, ``seat-home`` (its ``.agy-rw`` overlays included) and
    ``seat-out``. Read-only, never follows a link, bounded by ``cap_bytes`` per entry and
    ``time_limit_s`` overall. Nothing is skipped silently: an over-cap, unreadable or
    unwalked entry clears ``scan_complete``; a nonzero count stands regardless. ``rows``
    maps a parent-chosen key to ``(base, relpath)``, base ``tree`` or ``seat``; no
    seat-chosen path is returned."""
    if not _SCAN_FLAGS_AVAILABLE:
        return {
            "schema": SCAN_SCHEMA,
            "rows": {key: {"kind": "other", "digest": None, "mode": None}
                     for key in rows},
            "tree_manifest": None,
            "scan_complete": False,
            "entries": 0,
            "counts": {"field_names": 0, "delivered_token": 0},
        }
    walk = _Walk(int(cap_bytes), float(time_limit_s),
                 seat_jail.secret_encodings(token) if token else ())
    result: dict[str, object] = {"schema": SCAN_SCHEMA, "rows": {}, "tree_manifest": None}
    bases: dict[str, int] = {}
    try:
        try:
            bases["tree"] = seat_jail.open_dir_nofollow(tree)
            bases["seat"] = seat_jail.open_dir_nofollow(seat_root)
        except OSError:
            walk.complete = False
        if "tree" in bases:
            manifest: list = []
            walk.tree(bases["tree"], "", manifest)
            result["tree_manifest"] = _manifest_digest(manifest)
        if "seat" in bases:
            for name in _SCAN_SEAT_DIRS:
                if walk.expired():
                    break
                try:
                    fd = os.open(name, _SCAN_O_DIR, dir_fd=bases["seat"])
                except OSError:
                    walk.complete = False
                    continue
                try:
                    walk.tree(fd, f"{name}/", None)
                finally:
                    os.close(fd)
        row_results: dict[str, object] = {}
        for key, spec in rows.items():
            base, relpath = spec
            if base not in bases or walk.expired():
                walk.complete = False
                row_results[key] = {"kind": "other", "digest": None, "mode": None}
                continue
            row_results[key] = _scan_row(bases[base], relpath, walk)
        result["rows"] = row_results
    finally:
        for fd in bases.values():
            os.close(fd)
    if not walk.complete:
        result["tree_manifest"] = None  # a manifest over a partial walk describes nothing
    result.update(scan_complete=walk.complete, entries=walk.entries,
                  counts={"field_names": walk.field_names,
                          "delivered_token": walk.delivered_token})
    return result


def tree_manifest_digest(tree, *, cap_bytes: int = SCAN_CAP_BYTES,
                         time_limit_s: float = SCAN_TIME_LIMIT_S) -> str | None:
    """The manifest :func:`scan` computes, for the parent's own pre-leg reading of a tree
    it can still read. ``None`` when the walk was not complete."""
    if not _SCAN_FLAGS_AVAILABLE:
        return None
    walk = _Walk(int(cap_bytes), float(time_limit_s), ())
    try:
        fd = seat_jail.open_dir_nofollow(str(tree))
    except OSError:
        return None
    try:
        manifest: list = []
        walk.tree(fd, "", manifest)
    finally:
        os.close(fd)
    return _manifest_digest(manifest) if walk.complete else None


def _unavailable_scan() -> dict[str, object]:
    return {"schema": SCAN_SCHEMA, "rows": {}, "tree_manifest": None, "scan_complete": False,
            "entries": 0, "counts": {"field_names": 0, "delivered_token": 0}}


def _valid_scan(value, keys) -> bool:
    if not isinstance(value, dict) or set(value) != {"schema", "rows", "tree_manifest",
                                                     "scan_complete", "entries", "counts"}:
        return False
    counts = value["counts"]
    rows = value["rows"]
    return (value["schema"] == SCAN_SCHEMA and type(value["scan_complete"]) is bool
            and type(value["entries"]) is int and isinstance(counts, dict)
            and set(counts) == {"field_names", "delivered_token"}
            and all(type(v) is int and v >= 0 for v in counts.values())
            and (value["tree_manifest"] is None or isinstance(value["tree_manifest"], str))
            and isinstance(rows, dict) and set(rows) == set(keys)
            and all(isinstance(r, dict) and set(r) == {"kind", "digest", "mode"}
                    and r["kind"] in ("file", "dir", "link", "other", "missing")
                    for r in rows.values()))


def scan_in_h(holder_pid: int, seat_root: str, tree: str, rows: Mapping[str, tuple[str, str]],
              *, token: bytes | None, cap_bytes: int = SCAN_CAP_BYTES,
              time_limit_s: float = SCAN_TIME_LIMIT_S) -> dict[str, object]:
    """Run :func:`scan` in H as H-root, where the seat-owned tree and seat directories are
    readable. The rows and the delivered token travel on stdin, never on argv. A helper
    that could not run, or answered outside the closed shape, returns an incomplete scan
    with zero counts."""
    keys = list(rows)
    if len(keys) > _SCAN_MAX_ROWS or any(spec[0] not in _SCAN_BASES for spec in rows.values()):
        return _unavailable_scan()
    request = json.dumps({"rows": {key: list(spec) for key, spec in rows.items()},
                          "token_b64": base64.b64encode(token).decode("ascii") if token else None})
    try:
        done = subprocess.run(
            in_h_argv(holder_pid, "scan", seat_root, tree, str(int(cap_bytes)),
                      str(int(time_limit_s * 1000))),
            input=request.encode("utf-8"), capture_output=True,
            timeout=time_limit_s + 30.0, env=_pythonpath_env())
    except (OSError, subprocess.SubprocessError, ValueError):
        return _unavailable_scan()
    if done.returncode != 0 or len(done.stdout) > (1 << 20):
        return _unavailable_scan()
    try:
        value = json.loads(done.stdout)
    except ValueError:
        return _unavailable_scan()
    return value if _valid_scan(value, keys) else _unavailable_scan()


def _scan_main(rest: Sequence[str]) -> int:
    try:
        cap_bytes, limit_ms = int(rest[2]), int(rest[3])
        request = json.loads(sys.stdin.buffer.read(1 << 20) or b"{}")
        rows = {str(key): (str(spec[0]), str(spec[1]))
                for key, spec in dict(request.get("rows") or {}).items()}
        encoded = request.get("token_b64")
        token = base64.b64decode(encoded, validate=True) if encoded else None
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return 2
    if len(rows) > _SCAN_MAX_ROWS or any(spec[0] not in _SCAN_BASES for spec in rows.values()):
        return 2
    result = scan(rest[0], rest[1], rows, token=token, cap_bytes=cap_bytes,
                  time_limit_s=limit_ms / 1000.0)
    sys.stdout.write(json.dumps(result, sort_keys=True))
    return 0


def _main(argv: Sequence[str]) -> int:
    if not argv:
        return 2
    verb, rest = argv[0], list(argv[1:])
    if verb == "handoff" and len(rest) >= 3:
        # handoff <seat_dir> <tree> <n> [--gemini] -- <argv...>
        if "--" not in rest:
            return 2
        split = rest.index("--")
        gemini = "--gemini" in rest[:split]
        try:
            handoff(rest[0], int(rest[2]), gemini=gemini, tree=rest[1])
        except seat_jail.SeatSandboxRefused as exc:
            print(exc.code, file=sys.stderr)
            return 125
        except (OSError, ValueError):
            return 124
        command = rest[split + 1:]
        if not command:
            return 2
        os.execv(command[0], command)
    if verb == "read" and len(rest) == 3:
        try:
            root = seat_jail.open_dir_nofollow(rest[0])
            try:
                data = seat_jail.read_regular_file_at(root, rest[1], int(rest[2]))
            finally:
                os.close(root)
        except seat_jail.UnsafeSeatObject as exc:
            return _READ_MISSING if exc.errno == errno.ENOENT else 1
        except (OSError, ValueError):
            return 1
        sys.stdout.buffer.write(data)
        return 0
    if verb == "scan" and len(rest) == 4:
        # scan <seat_root> <tree> <cap_bytes> <time_limit_ms>; rows and token on stdin
        return _scan_main(rest)
    if verb == "teardown" and len(rest) == 1:
        retained = teardown(rest[0])
        print(json.dumps(retained))
        return 0 if not retained else 3
    if verb == "remove" and len(rest) == 1:
        target = Path(rest[0])
        try:
            parent = seat_jail.open_dir_nofollow(str(target.parent))
            try:
                seat_jail.remove_tree_at(parent, target.name)
            finally:
                os.close(parent)
        except OSError:
            return 1
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
