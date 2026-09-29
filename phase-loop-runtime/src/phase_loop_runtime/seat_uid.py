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

The in-H helpers (``handoff``, ``read``, ``teardown``) run as H-root through
``python -m phase_loop_runtime.seat_uid <verb> ...``.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

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
    base = Path(runtime) if runtime and os.path.isabs(runtime) else Path(
        tempfile.gettempdir()) / f"phase-loop-{os.getuid()}"
    return base / "phase-loop" / "seat-uid"


def seat_uid_available(
    *,
    uid: int | None = None,
    subuid: Path = SUBUID_FILE,
    subgid: Path = SUBGID_FILE,
    newuidmap: str = NEWUIDMAP,
    newgidmap: str = NEWGIDMAP,
) -> bool:
    """J7 step 2, the seat-uid half: setuid helpers, a range for uid AND gid, a free seat
    id, and an operator that is not uid 0."""
    uid = os.getuid() if uid is None else uid
    if uid == 0:
        return False
    if not (_privileged_helper(newuidmap) and _privileged_helper(newgidmap)):
        return False
    uids = subordinate_range(subuid, uid)
    gids = subordinate_range(subgid, uid)
    if uids is None or gids is None:
        return False
    count = seat_id_count(uids, gids)
    try:
        with lease_seat_id(count):
            return True
    except SeatIdsExhausted:
        return False
    except OSError:
        return False


def seat_id_count(uids: SubordinateRange, gids: SubordinateRange) -> int:
    """How many seat ids H can hold: 1..count map onto the subordinate range."""
    return min(uids.count, gids.count, MAX_SEAT_IDS)


class SeatIdsExhausted(RuntimeError):
    pass


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
            # Owned by H-root (the operator), group n, 0750/0440: the seat reads through
            # the group grant and can neither write nor chmod it.
            fd = seat_jail.open_dir_nofollow(seat_jail.HOST_GEMINI_CONFIG_DIRNAME, dir_fd=root)
            try:
                os.chown(fd, 0, seat_id)
                os.chmod(fd, 0o750)
                for name in os.listdir(fd):
                    os.chown(name, 0, seat_id, dir_fd=fd, follow_symlinks=False)
                    os.chmod(name, 0o440, dir_fd=fd, follow_symlinks=False)
            finally:
                os.close(fd)
    finally:
        os.close(root)


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
        leaf = seat_jail.open_dir_nofollow(parts[-1], dir_fd=current)
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

def in_h_argv(holder_pid: int, verb: str, *args: str) -> list[str]:
    """``nsenter`` into H as H-root, then this module's helper ``verb``."""
    return ["/usr/bin/nsenter", "-t", str(holder_pid), "-U", "-m", "--preserve-credentials",
            sys.executable, "-m", "phase_loop_runtime.seat_uid", verb, *args]


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
    package_root = str(Path(__file__).resolve().parent.parent)
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": package_root, "LC_ALL": "C"}


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
    holder = subprocess.Popen(["/usr/bin/unshare", "--user", "--mount", "/bin/sh", "-c",
                               "read -r _gate; exec sleep 600"],
                              stdin=subprocess.PIPE, env={"PATH": "/usr/bin:/bin"})
    try:
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
