"""Per-operator host state used by review seats."""

from __future__ import annotations

import grp
import os
from pathlib import Path
import pwd
import secrets
import stat
import tempfile
from typing import Literal

from . import seat_jail


OperatorStateKind = Literal["seat_uid_leases", "native_fill", "scratch"]

SUBUID_FILE = Path("/etc/subuid")
SUBGID_FILE = Path("/etc/subgid")

_LEAFS: dict[OperatorStateKind, str] = {
    "seat_uid_leases": "seat-uid",
    "native_fill": "native-fill",
    "scratch": "scratch",
}

ISSUE_1108_DISPOSITIONS = {
    "Claude channel sidecar port": "recorded",
    "Task-message broker port": "recorded",
    "President native-fill files": "write_private_atomic",
    "Staging free-space floor": "recorded",
    "CI offload lock": "recorded",
    "TMPDIR under /dev": "scratch_root_allowed",
    "Seat-uid lease fallback directory": "operator_private_dir",
    "Overlapping subordinate ranges": "subordinate_ranges_disjoint",
}


def operator_private_dir(kind: OperatorStateKind, *, base: Path | None = None) -> Path:
    """Create or validate one owner-only directory without following a path link.

    ``base`` names the exact requested directory.  Without it, the directory is selected
    from the operator's standard runtime/state locations.
    """

    if kind not in _LEAFS:
        raise ValueError("unknown operator state kind")
    target = Path(base) if base is not None else _default_private_dir(kind)
    if not target.is_absolute():
        _refuse("private directory must be absolute")
    _ensure_private_path(target)
    return target


def write_private_atomic(directory: Path, name: str, data: bytes) -> None:
    """Atomically replace ``name`` relative to one verified private directory fd."""

    if (
        not isinstance(name, str)
        or name in {"", ".", ".."}
        or Path(name).name != name
        or "/" in name
        or "\x00" in name
    ):
        raise ValueError("invalid private file name")
    if not isinstance(data, bytes):
        raise TypeError("private file data must be bytes")
    try:
        descriptor = _open_directory(Path(directory))
    except OSError as exc:
        _refuse("private directory walk", exc)
    temporary = f".{name}.tmp-{secrets.token_hex(16)}"
    file_descriptor: int | None = None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != _euid()
            or info.st_mode & 0o022
        ):
            _refuse("private directory owner or mode")
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=descriptor,
        )
        view = memoryview(data)
        while view:
            written = os.write(file_descriptor, view)
            if written <= 0:
                raise OSError("short private write")
            view = view[written:]
        os.fsync(file_descriptor)
        os.close(file_descriptor)
        file_descriptor = None
        os.rename(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        os.fsync(descriptor)
    except BaseException:
        if file_descriptor is not None:
            os.close(file_descriptor)
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)


def subordinate_ranges_disjoint(
    uid: int | None = None,
    *,
    subuid: Path = SUBUID_FILE,
    subgid: Path = SUBGID_FILE,
) -> bool:
    """Whether all of this operator's subordinate uid/gid ranges are exclusive."""

    operator = _uid() if uid is None else uid
    try:
        name = pwd.getpwuid(operator).pw_name
    except (KeyError, OSError):
        name = None
    owners = {str(operator)}
    if name:
        owners.add(name)
    uid_ranges = _range_inventory(Path(subuid), owners)
    gid_ranges = _range_inventory(Path(subgid), owners)
    if uid_ranges is None or gid_ranges is None:
        return False
    own_uids, other_uids = uid_ranges
    own_gids, other_gids = gid_ranges
    if not own_uids or not own_gids:
        return False
    try:
        host_uids = {entry.pw_uid for entry in pwd.getpwall()}
        host_gids = {entry.gr_gid for entry in grp.getgrall()}
    except (OSError, KeyError, ValueError):
        return False
    return (
        _ranges_exclusive(own_uids, other_uids, host_uids)
        and _ranges_exclusive(own_gids, other_gids, host_gids)
    )


def scratch_root_allowed(path: Path) -> bool:
    """False when scratch resolves at or below a kernel/device pseudo-filesystem."""

    try:
        resolved = Path(os.path.realpath(os.fspath(path)))
    except (OSError, TypeError, ValueError):
        return False
    for blocked in (Path("/dev"), Path("/proc"), Path("/sys")):
        if resolved == blocked or resolved.is_relative_to(blocked):
            return False
    return True


def _default_private_dir(kind: OperatorStateKind) -> Path:
    uid = _uid()
    if kind == "seat_uid_leases":
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime and os.path.isabs(runtime):
            return Path(runtime) / "phase-loop" / _LEAFS[kind]
        return Path(tempfile.gettempdir()) / f"phase-loop-{uid}" / "phase-loop" / _LEAFS[kind]
    if kind == "native_fill":
        state = os.environ.get("XDG_STATE_HOME")
        root = Path(state) if state and os.path.isabs(state) else Path.home() / ".local/state"
        return root / "phase-loop" / _LEAFS[kind]
    return Path(tempfile.gettempdir()) / f"phase-loop-{uid}" / _LEAFS[kind]


def _ensure_private_path(target: Path) -> None:
    parts = target.parts
    if not parts or parts[0] != "/" or any(part in {"", ".", ".."} for part in parts[1:]):
        _refuse("invalid private directory path")
    walk = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open("/", walk)
    private_started = False
    try:
        for index, part in enumerate(parts[1:], start=1):
            try:
                child = os.open(part, walk, dir_fd=directory)
            except FileNotFoundError:
                private_started = True
                try:
                    os.mkdir(part, 0o700, dir_fd=directory)
                    child = os.open(part, walk, dir_fd=directory)
                except OSError as exc:
                    _refuse("private directory creation", exc)
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode):
                os.close(child)
                _refuse("private directory component")
            if index == len(parts) - 1:
                private_started = True
            if private_started:
                if info.st_uid != _euid() or stat.S_IMODE(info.st_mode) != 0o700:
                    os.close(child)
                    _refuse("private directory owner or mode")
            elif info.st_mode & 0o022 and not (
                info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            ):
                os.close(child)
                _refuse("writable private directory ancestor")
            os.close(directory)
            directory = child
    except OSError as exc:
        _refuse("private directory walk", exc)
    finally:
        os.close(directory)


def _open_directory(path: Path) -> int:
    if not path.is_absolute():
        _refuse("private directory must be absolute")
    parts = path.parts
    walk = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open("/", walk)
    try:
        for index, part in enumerate(parts[1:]):
            flags = (
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
                if index == len(parts[1:]) - 1
                else walk
            )
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory
    except BaseException:
        os.close(directory)
        raise


def _range_inventory(path: Path, owners: set[str]):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    own: list[tuple[int, int]] = []
    other: list[tuple[int, int]] = []
    for line in lines:
        fields = line.split(":")
        if len(fields) != 3 or not fields[0]:
            return None
        try:
            start = int(fields[1])
            count = int(fields[2])
        except ValueError:
            return None
        if start <= 0 or count <= 0:
            return None
        end = start + count
        if end <= start:
            return None
        (own if fields[0] in owners else other).append((start, end))
    return own, other


def _ranges_exclusive(
    own: list[tuple[int, int]],
    other: list[tuple[int, int]],
    host_ids: set[int],
) -> bool:
    for start, end in own:
        if any(start < other_end and other_start < end for other_start, other_end in other):
            return False
        if any(start <= host_id < end for host_id in host_ids):
            return False
    return True


def _uid() -> int:
    return os.getuid()


def _euid() -> int:
    return os.geteuid()


def _refuse(message: str, cause: BaseException | None = None):
    error = seat_jail.SeatSandboxRefused(seat_jail.refused("identity"), message)
    if cause is not None:
        raise error from cause
    raise error


__all__ = [
    "ISSUE_1108_DISPOSITIONS",
    "OperatorStateKind",
    "operator_private_dir",
    "scratch_root_allowed",
    "subordinate_ranges_disjoint",
    "write_private_atomic",
]
