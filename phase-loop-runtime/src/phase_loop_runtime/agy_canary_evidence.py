"""Fail-closed evidence helpers for the opt-in Antigravity canary."""

from __future__ import annotations

import copy
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "agy_canary_evidence.v1"
_CLEANUP_STATE_NAME = "cleanup-state.json"
_SETTINGS_SNAPSHOT_NAME = "agy-settings.pre.json"
_RULE = "command(pwd)"
_RENAME_EXCHANGE = 2


class AgyCanaryEvidenceError(RuntimeError):
    """Raised when evidence cannot be produced without weakening a gate."""


@dataclass(frozen=True)
class _OpenedSettings:
    parent_fd: int
    name: str
    data: bytes
    mode: int
    device: int
    inode: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _validate_private_root(path: Path) -> tuple[Path, int]:
    if not path.is_absolute() or path.parent != Path("/tmp"):
        raise AgyCanaryEvidenceError("evidence root must be a direct absolute child of /tmp")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise AgyCanaryEvidenceError("evidence root does not exist") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise AgyCanaryEvidenceError("evidence root must be a real directory")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise AgyCanaryEvidenceError("evidence root must have mode 0700")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
        os.close(fd)
        raise AgyCanaryEvidenceError("evidence root identity changed during open")
    return path.resolve(strict=True), fd


def _exclusive_write_at(directory_fd: int, name: str, data: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(name, flags, mode, dir_fd=directory_fd)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise AgyCanaryEvidenceError(f"short write for {name}")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(directory_fd)


def _replace_state(directory_fd: int, value: dict[str, Any]) -> None:
    data = _canonical_json(value)
    temporary = f".{_CLEANUP_STATE_NAME}.{secrets.token_hex(12)}"
    _exclusive_write_at(directory_fd, temporary, data, 0o600)
    os.rename(temporary, _CLEANUP_STATE_NAME, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    os.fsync(directory_fd)


def _state_record(state: str, **fields: Any) -> dict[str, Any]:
    return {"schema": SCHEMA_VERSION, "operation": "clean_settings", "state": state, **fields}


def _open_settings(path: Path) -> _OpenedSettings:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise AgyCanaryEvidenceError("settings path must be an absolute file path")
    parent = path.parent.resolve(strict=True)
    parent_info = parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise AgyCanaryEvidenceError("settings parent must be a real directory")
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
    except Exception:
        os.close(parent_fd)
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AgyCanaryEvidenceError("settings path must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    return _OpenedSettings(
        parent_fd=parent_fd,
        name=path.name,
        data=data,
        mode=stat.S_IMODE(info.st_mode),
        device=info.st_dev,
        inode=info.st_ino,
    )


def _parse_policy(data: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgyCanaryEvidenceError("settings JSON is malformed") from exc
    if not isinstance(parsed, dict):
        raise AgyCanaryEvidenceError("settings JSON root must be an object")
    permissions = parsed.get("permissions", {})
    if not isinstance(permissions, dict):
        raise AgyCanaryEvidenceError("settings permissions must be an object")
    allow = permissions.get("allow", [])
    if not isinstance(allow, list) or not all(isinstance(item, str) for item in allow):
        raise AgyCanaryEvidenceError("settings permissions.allow must be a string array")
    return parsed


def _derive_replacement(before: dict[str, Any]) -> tuple[dict[str, Any], str]:
    after = copy.deepcopy(before)
    permissions = after.get("permissions", {})
    allow = permissions.get("allow", [])
    matches = [index for index, value in enumerate(allow) if value == _RULE]
    if len(matches) > 1:
        raise AgyCanaryEvidenceError("cleanup provenance failed: command(pwd) appears more than once")
    if matches:
        del allow[matches[0]]
        result = "removed_exact_rule"
    else:
        result = "already_absent"
    if allow:
        raise AgyCanaryEvidenceError("effective persistent allow list is not empty after cleanup")
    if after.get("toolPermission", "request-review") in {
        "always-proceed",
        "proceed-in-sandbox",
    }:
        raise AgyCanaryEvidenceError("unsafe Antigravity toolPermission preset")
    if after.get("allowNonWorkspaceAccess", False) is True:
        raise AgyCanaryEvidenceError("non-workspace access is enabled")
    return after, result


def _fd_is_writable(pid_dir: Path, fd_name: str) -> bool:
    try:
        text = (pid_dir / "fdinfo" / fd_name).read_text()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False
    for line in text.splitlines():
        if line.startswith("flags:"):
            try:
                flags = int(line.split(":", 1)[1].strip(), 8)
            except ValueError:
                return True
            return flags & os.O_ACCMODE != os.O_RDONLY
    return True


def _assert_quiescent(
    settings: _OpenedSettings,
    settings_parent: Path,
    *,
    block_all_agy_processes: bool,
) -> None:
    blockers: list[str] = []
    own_pid = os.getpid()
    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit() or int(pid_dir.name) == own_pid:
            continue
        try:
            argv = (pid_dir / "cmdline").read_bytes().split(b"\0")
            executable_name = Path(os.fsdecode(argv[0])).name.lower() if argv and argv[0] else ""
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            argv = []
            executable_name = ""
        if block_all_agy_processes and (
            executable_name == "agy" or "antigravity" in executable_name
        ):
            blockers.append(f"pid={pid_dir.name},process={executable_name}")
        fd_dir = pid_dir / "fd"
        try:
            entries = list(fd_dir.iterdir())
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        for entry in entries:
            try:
                info = entry.stat()
                target = os.readlink(entry)
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                continue
            same_inode = (info.st_dev, info.st_ino) == (settings.device, settings.inode)
            beneath = target == str(settings_parent) or target.startswith(f"{settings_parent}/")
            if same_inode or (beneath and _fd_is_writable(pid_dir, entry.name)):
                blockers.append(f"pid={pid_dir.name},fd={entry.name}")
    if blockers:
        raise AgyCanaryEvidenceError(
            "settings tree is not quiescent: " + ", ".join(sorted(set(blockers))[:8])
        )


def _rename_exchange(directory_fd: int, left: str, right: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise AgyCanaryEvidenceError("renameat2(RENAME_EXCHANGE) is unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(directory_fd, os.fsencode(left), directory_fd, os.fsencode(right), _RENAME_EXCHANGE) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _reopen_at(directory_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AgyCanaryEvidenceError(f"{name} is no longer a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), info
    finally:
        os.close(fd)


def clean_settings(*, evidence_root: Path, settings_path: Path, maintenance_lock: Path) -> dict[str, Any]:
    """Remove exactly the failed-canary ``command(pwd)`` rule under quiescence."""

    root_path, root_fd = _validate_private_root(evidence_root)
    settings: _OpenedSettings | None = None
    lock_fd: int | None = None
    temporary: str | None = None
    exchanged = False
    replacement_bytes = b""
    transitions: list[str] = []

    def record_state(state: str, **fields: Any) -> None:
        transitions.append(state)
        _replace_state(
            root_fd,
            _state_record(state, transitions=list(transitions), **fields),
        )

    try:
        if not maintenance_lock.is_absolute() or maintenance_lock.is_symlink():
            raise AgyCanaryEvidenceError("maintenance lock must be an absolute non-symlink path")
        lock_fd = os.open(
            maintenance_lock,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AgyCanaryEvidenceError("settings maintenance lock is unavailable") from exc

        settings = _open_settings(settings_path)
        before = _parse_policy(settings.data)
        after, result = _derive_replacement(before)
        canonical_settings = (
            Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
        ).resolve(strict=False)
        _assert_quiescent(
            settings,
            settings_path.parent.resolve(strict=True),
            block_all_agy_processes=settings_path.resolve(strict=True) == canonical_settings,
        )

        _exclusive_write_at(root_fd, _SETTINGS_SNAPSHOT_NAME, settings.data, settings.mode)
        snapshot_bytes, snapshot_info = _reopen_at(root_fd, _SETTINGS_SNAPSHOT_NAME)
        if snapshot_bytes != settings.data or stat.S_IMODE(snapshot_info.st_mode) != settings.mode:
            raise AgyCanaryEvidenceError("private settings snapshot did not seal exactly")
        common = {
            "result": result,
            "settings_path_sha256": _sha256(str(settings_path).encode()),
            "before_sha256": _sha256(settings.data),
            "before_mode": format(settings.mode, "04o"),
            "recovery_snapshot_sha256": _sha256(snapshot_bytes),
        }
        record_state("prepared", **common)

        if result == "already_absent":
            record_state("verified", **common)
            record_state("committed", **common)
            return {
                "schema": SCHEMA_VERSION,
                "state": "committed",
                "result": result,
                "structural_delta_valid": True,
                "effective_allow_empty": True,
                "safe_tool_permission": True,
                "non_workspace_access_disabled": True,
                "recovery_snapshot_sealed": True,
                "before_sha256": _sha256(settings.data),
                "after_sha256": _sha256(settings.data),
                "mode_preserved": True,
                "removed_rule": None,
            }
        else:
            replacement_bytes = json.dumps(after, indent=2, ensure_ascii=False).encode() + b"\n"

        current, current_info = _reopen_at(settings.parent_fd, settings.name)
        current_identity = (current_info.st_dev, current_info.st_ino)
        if (
            current_identity != (settings.device, settings.inode)
            or stat.S_IMODE(current_info.st_mode) != settings.mode
            or len(current) != len(settings.data)
            or _sha256(current) != _sha256(settings.data)
        ):
            raise AgyCanaryEvidenceError("settings identity or bytes drifted before exchange")

        temporary = f".phase-loop-agy-settings.{secrets.token_hex(16)}.tmp"
        _exclusive_write_at(settings.parent_fd, temporary, replacement_bytes, settings.mode)
        _rename_exchange(settings.parent_fd, settings.name, temporary)
        exchanged = True
        record_state("exchanged_unverified", temp_name=temporary, **common)

        destination, destination_info = _reopen_at(settings.parent_fd, settings.name)
        swapped_original, swapped_info = _reopen_at(settings.parent_fd, temporary)
        destination_parsed = _parse_policy(destination)
        if destination_parsed != after or stat.S_IMODE(destination_info.st_mode) != settings.mode:
            raise AgyCanaryEvidenceError("exchanged destination failed structural or mode validation")
        if (
            swapped_original != settings.data
            or (swapped_info.st_dev, swapped_info.st_ino) != (settings.device, settings.inode)
            or stat.S_IMODE(swapped_info.st_mode) != settings.mode
        ):
            raise AgyCanaryEvidenceError("swapped-out original failed identity validation")
        os.fsync(settings.parent_fd)
        record_state("verified", temp_name=temporary, **common)
        record_state("committed", **common)
        os.unlink(temporary, dir_fd=settings.parent_fd)
        os.fsync(settings.parent_fd)
        temporary = None
        return {
            "schema": SCHEMA_VERSION,
            "state": "committed",
            "result": result,
            "structural_delta_valid": True,
            "effective_allow_empty": True,
            "safe_tool_permission": True,
            "non_workspace_access_disabled": True,
            "recovery_snapshot_sealed": True,
            "before_sha256": _sha256(settings.data),
            "after_sha256": _sha256(destination),
            "mode_preserved": True,
            "removed_rule": _RULE if result == "removed_exact_rule" else None,
        }
    except Exception as exc:
        if exchanged and settings is not None and temporary is not None:
            try:
                record_state("rollback_required", error=type(exc).__name__)
                _rename_exchange(settings.parent_fd, settings.name, temporary)
                restored, restored_info = _reopen_at(settings.parent_fd, settings.name)
                own_replacement, _ = _reopen_at(settings.parent_fd, temporary)
                if (
                    restored == settings.data
                    and (restored_info.st_dev, restored_info.st_ino) == (settings.device, settings.inode)
                    and own_replacement == replacement_bytes
                ):
                    os.unlink(temporary, dir_fd=settings.parent_fd)
                    os.fsync(settings.parent_fd)
                    record_state("rolled_back", error=type(exc).__name__)
                    temporary = None
                else:
                    record_state(
                        "recovery_retained", temp_name=temporary, error=type(exc).__name__
                    )
            except Exception as rollback_exc:
                try:
                    record_state(
                        "recovery_retained",
                        temp_name=temporary,
                        error=type(exc).__name__,
                        rollback_error=type(rollback_exc).__name__,
                    )
                except Exception:
                    pass
        if isinstance(exc, AgyCanaryEvidenceError):
            raise
        if isinstance(exc, OSError) and exc.errno in {errno.ELOOP, errno.EXDEV}:
            raise AgyCanaryEvidenceError(str(exc)) from exc
        raise AgyCanaryEvidenceError(f"settings cleanup failed: {exc}") from exc
    finally:
        if settings is not None:
            os.close(settings.parent_fd)
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(root_fd)
