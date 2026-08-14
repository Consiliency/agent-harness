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
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "agy_canary_evidence.v1"
_CLEANUP_STATE_NAME = "cleanup-state.json"
_SETTINGS_SNAPSHOT_NAME = "agy-settings.pre.json"
_RULE = "command(pwd)"
_RENAME_EXCHANGE = 2
_LEDGER_NAME = "agy-launch-ledger.json"
_PROBE_NAME = "agy_capability_probe.json"
_PREPARE_NAME = "agy_canary_prepare.json"
_INPUTS_NAME = "agy_canary_inputs.json"
_SAFE_PRESETS = frozenset({"request-review", "strict"})


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


@dataclass(frozen=True)
class AgyCanaryCapture:
    """Parent-owned opt-in capture state.

    The evidence root is deliberately represented by a directory descriptor.  It
    must never be supplied to a model child in an argv, prompt, or environment.
    """

    root: Path
    root_fd: int

    def close(self) -> None:
        os.close(self.root_fd)


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


def _read_regular_at(directory_fd: int, name: str) -> bytes:
    """Read one direct child without following a symlink."""
    if Path(name).name != name:
        raise AgyCanaryEvidenceError("private evidence names must be basenames")
    return _reopen_at(directory_fd, name)[0]


def _write_replace_at(directory_fd: int, name: str, value: dict[str, Any]) -> None:
    """Atomically replace a parent-owned JSON record under a held descriptor."""
    if Path(name).name != name:
        raise AgyCanaryEvidenceError("private evidence names must be basenames")
    temporary = f".{name}.{secrets.token_hex(12)}"
    _exclusive_write_at(directory_fd, temporary, _canonical_json(value), 0o600)
    os.rename(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    os.fsync(directory_fd)


def _read_json_at(directory_fd: int, name: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular_at(directory_fd, name))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgyCanaryEvidenceError(f"invalid private evidence record: {name}") from exc
    if not isinstance(value, dict):
        raise AgyCanaryEvidenceError(f"private evidence record is not an object: {name}")
    return value


def consume_capture_environment(env: dict[str, str] | None = None) -> AgyCanaryCapture | None:
    """Consume the opt-in root before a board creates child work.

    This intentionally deletes the environment variable even when validation
    fails.  A later child must never inherit a path to the private evidence
    tree merely because setup was rejected.
    """
    source = os.environ if env is None else env
    raw = source.pop("PHASE_LOOP_AGY_CANARY_EVIDENCE_DIR", None)
    if raw is None:
        return None
    root, root_fd = _validate_private_root(Path(raw))
    return AgyCanaryCapture(root=root, root_fd=root_fd)


def _policy_facts(settings: dict[str, Any]) -> dict[str, bool]:
    permissions = settings.get("permissions", {})
    allow = permissions.get("allow", []) if isinstance(permissions, dict) else None
    preset = settings.get("toolPermission", "request-review")
    return {
        "effective_allow_empty": allow == [],
        "safe_preset": isinstance(preset, str) and preset in _SAFE_PRESETS,
        "non_workspace_access_disabled": settings.get("allowNonWorkspaceAccess", False) is False,
    }


def inventory_policy_sources(*, settings_path: Path) -> dict[str, Any]:
    """Inventory the one supported settings source and derive policy facts.

    A non-existent or symlinked source is not silently treated as safe.  The
    attended producer supplies its explicit minimal settings file; ordinary
    boards never enter this code path.
    """
    opened = _open_settings(settings_path)
    try:
        parsed = _parse_policy(opened.data)
    finally:
        os.close(opened.parent_fd)
    facts = _policy_facts(parsed)
    if not all(facts.values()):
        raise AgyCanaryEvidenceError("capture policy is not strict and empty")
    return {
        "schema": "agy_policy_inventory.v1",
        "settings": {
            "path_sha256": _sha256(str(settings_path.resolve()).encode()),
            "bytes": len(opened.data),
            "sha256": _sha256(opened.data),
        },
        "sources_complete": True,
        "customization_inventory": {
            "hooks": [], "plugins": [], "mcp": [], "environment_overrides": [],
        },
        **facts,
    }


def create_capture(*, capture: AgyCanaryCapture, settings_path: Path, seat_key: str) -> dict[str, Any]:
    """Start a single-seat capture ledger after strict policy inventory."""
    if not seat_key or "/" in seat_key or "\\" in seat_key:
        raise AgyCanaryEvidenceError("Gemini seat key must be a nonempty canonical key")
    policy = inventory_policy_sources(settings_path=settings_path)
    existing = None
    try:
        existing = _read_json_at(capture.root_fd, _LEDGER_NAME)
    except AgyCanaryEvidenceError:
        pass
    if existing is not None:
        raise AgyCanaryEvidenceError("capture ledger already exists")
    ledger = {
        "schema": "agy_canary_launch_ledger.v1",
        "seat_key": seat_key,
        "policy": policy,
        "attempts": [],
    }
    _exclusive_write_at(capture.root_fd, _LEDGER_NAME, _canonical_json(ledger), 0o600)
    return ledger


def retain_staged_files(*, capture: AgyCanaryCapture, review_dir: Path) -> dict[str, dict[str, Any]]:
    """Descriptor-read and retain the two only permitted staged inputs."""
    records: dict[str, dict[str, Any]] = {}
    review_fd = os.open(review_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for name in ("review-instructions.md", "review-bundle.md"):
            data, info = _reopen_at(review_fd, name)
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise AgyCanaryEvidenceError(f"staged file is not private: {name}")
            retained = f"staged-{name}"
            _exclusive_write_at(capture.root_fd, retained, data, 0o600)
            records[name] = {"retained": retained, "bytes": len(data), "sha256": _sha256(data)}
    finally:
        os.close(review_fd)
    return records


def record_launch(
    *,
    capture: AgyCanaryCapture,
    seat_key: str,
    attempt_id: str,
    argv: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
    staged: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Append one complete Gemini process record without recording prompt bytes."""
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    if ledger.get("seat_key") != seat_key:
        raise AgyCanaryEvidenceError("capture launch seat does not match sealed singleton")
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list) or any(item.get("attempt_id") == attempt_id for item in attempts if isinstance(item, dict)):
        raise AgyCanaryEvidenceError("attempt identifier is missing or duplicated")
    stream_name = f"agy-stream-{attempt_id}.jsonl"
    diagnostic_name = f"agy-diagnostic-{attempt_id}.log"
    _exclusive_write_at(capture.root_fd, stream_name, stdout.encode(), 0o600)
    _exclusive_write_at(capture.root_fd, diagnostic_name, stderr.encode(), 0o600)
    normalized = ["<prompt>" if value and index == len(argv) - 1 else value for index, value in enumerate(argv)]
    record = {
        "attempt_id": attempt_id,
        "seat_key": seat_key,
        "returncode": int(returncode),
        "argv_sha256": _sha256("\0".join(normalized).encode()),
        "stream": {"name": stream_name, "bytes": len(stdout.encode()), "sha256": _sha256(stdout.encode())},
        "diagnostic": {"name": diagnostic_name, "bytes": len(stderr.encode()), "sha256": _sha256(stderr.encode())},
        "staged": staged,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    attempts.append(record)
    _write_replace_at(capture.root_fd, _LEDGER_NAME, ledger)
    return record


def _parse_stream(data: bytes) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Parse the intentionally narrow, versioned stream-json authority."""
    calls: dict[str, dict[str, Any]] = {}
    sequence = -1
    terminal: dict[str, Any] | None = None
    session: str | None = None
    for raw in data.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AgyCanaryEvidenceError("stream contains invalid JSON") from exc
        if not isinstance(event, dict):
            raise AgyCanaryEvidenceError("stream event is not an object")
        value = event.get("sequence")
        if not isinstance(value, int) or value != sequence + 1:
            raise AgyCanaryEvidenceError("stream sequence is incomplete")
        sequence = value
        current_session = event.get("session_id")
        if not isinstance(current_session, str) or not current_session:
            raise AgyCanaryEvidenceError("stream lacks a session identity")
        if session is None:
            session = current_session
        elif session != current_session:
            raise AgyCanaryEvidenceError("stream mixes sessions")
        kind = event.get("type")
        if kind == "tool_call":
            call_id = event.get("call_id")
            if not isinstance(call_id, str) or call_id in calls:
                raise AgyCanaryEvidenceError("stream tool call identity is invalid")
            calls[call_id] = event
        elif kind == "tool_result":
            call_id = event.get("call_id")
            if not isinstance(call_id, str) or call_id not in calls or "result" in calls[call_id]:
                raise AgyCanaryEvidenceError("stream tool result is unmatched")
            calls[call_id]["result"] = event
        elif kind == "terminal":
            if terminal is not None or not isinstance(event.get("text"), str):
                raise AgyCanaryEvidenceError("stream terminal event is invalid")
            terminal = event
        else:
            raise AgyCanaryEvidenceError("stream event kind is unsupported")
    if session is None or terminal is None or any("result" not in call for call in calls.values()):
        raise AgyCanaryEvidenceError("stream does not contain complete calls and terminal result")
    return session, list(calls.values()), terminal


def verify_capture(*, evidence_root: Path, expected_seat_key: str) -> dict[str, Any]:
    """Strictly reduce all sealed attempts and reject incomplete/forged evidence."""
    root, root_fd = _validate_private_root(evidence_root)
    try:
        ledger = _read_json_at(root_fd, _LEDGER_NAME)
        if ledger.get("seat_key") != expected_seat_key:
            raise AgyCanaryEvidenceError("sealed Gemini seat key does not match board")
        policy = ledger.get("policy")
        if not isinstance(policy, dict) or not all(policy.get(name) is True for name in ("effective_allow_empty", "safe_preset", "non_workspace_access_disabled", "sources_complete")):
            raise AgyCanaryEvidenceError("capture policy facts are incomplete")
        attempts = ledger.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise AgyCanaryEvidenceError("capture has no Gemini attempts")
        output_attempts: list[dict[str, Any]] = []
        final_text = ""
        for item in attempts:
            if not isinstance(item, dict) or item.get("seat_key") != expected_seat_key:
                raise AgyCanaryEvidenceError("capture contains an unbound attempt")
            stream = item.get("stream")
            staged = item.get("staged")
            if not isinstance(stream, dict) or not isinstance(staged, dict):
                raise AgyCanaryEvidenceError("capture launch record is incomplete")
            raw = _read_regular_at(root_fd, str(stream.get("name", "")))
            if len(raw) != stream.get("bytes") or _sha256(raw) != stream.get("sha256"):
                raise AgyCanaryEvidenceError("sealed stream bytes drifted")
            _session, calls, terminal = _parse_stream(raw)
            counts = {"command": 0, "unsandboxed": 0, "non_read_tool": 0, "out_of_stage_read": 0}
            reads = {"review-instructions.md": [], "review-bundle.md": []}
            for call in calls:
                tool = call.get("tool")
                target = call.get("target")
                result = call["result"]
                if not isinstance(tool, str) or not isinstance(target, str) or not isinstance(result, dict):
                    raise AgyCanaryEvidenceError("tool call is unclassifiable")
                succeeded = result.get("outcome") == "success"
                if tool == "read_file":
                    basename = Path(target).name
                    if basename in reads and target.endswith(basename):
                        reads[basename].append(result)
                    else:
                        counts["out_of_stage_read"] += 1
                elif tool in {"command", "unsandboxed"}:
                    counts[tool] += 1
                else:
                    counts["non_read_tool"] += 1
                if succeeded and tool != "read_file":
                    raise AgyCanaryEvidenceError("accepted attempt executed a non-read tool")
            for name, expected in staged.items():
                if not isinstance(expected, dict) or not reads.get(name):
                    raise AgyCanaryEvidenceError(f"accepted attempt did not read {name}")
                if not any(result.get("sha256") == expected.get("sha256") and result.get("bytes") == expected.get("bytes") for result in reads[name]):
                    raise AgyCanaryEvidenceError(f"read result does not cover sealed {name}")
            output_attempts.append({"attempt_id": item.get("attempt_id"), "counts": counts, "terminal_sha256": _sha256(str(terminal["text"]).encode())})
            final_text = str(terminal["text"])
        if not final_text.strip():
            raise AgyCanaryEvidenceError("final Gemini review is empty")
        proof = {
            "schema": SCHEMA_VERSION,
            "seat_key": expected_seat_key,
            "attempt_ids": [item["attempt_id"] for item in output_attempts],
            "attempts": output_attempts,
            "accepted_review_sha256": _sha256(final_text.encode()),
        }
        _write_replace_at(root_fd, "agy_canary_proof.json", proof)
        return proof
    finally:
        os.close(root_fd)


def write_private_board(*, capture: AgyCanaryCapture, basename: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create the full board payload only in the validated private root."""
    if not basename or Path(basename).name != basename:
        raise AgyCanaryEvidenceError("private board name must be a basename")
    data = _canonical_json(payload)
    _exclusive_write_at(capture.root_fd, basename, data, 0o600)
    return {"name": basename, "bytes": len(data), "sha256": _sha256(data)}


def capture_summary(capture: AgyCanaryCapture) -> dict[str, Any]:
    """Return redacted ledger binding information for the public board envelope."""
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    data = _canonical_json(ledger)
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise AgyCanaryEvidenceError("capture ledger has invalid attempts")
    ids = [item.get("attempt_id") for item in attempts if isinstance(item, dict)]
    if len(ids) != len(attempts) or any(not isinstance(item, str) for item in ids):
        raise AgyCanaryEvidenceError("capture ledger has invalid attempt identifiers")
    return {"gemini_seat_key": ledger.get("seat_key"), "gemini_seat_count": 1, "attempt_ids": ids, "ledger_bytes": len(data), "ledger_sha256": _sha256(data)}


def probe_capability(*, evidence_root: Path, agy_executable: str = "agy") -> dict[str, Any]:
    """Record a conservative capability result without executing a provider turn.

    A live trajectory probe is an attended operation.  This producer therefore
    refuses to claim a stream mode from a version string alone.
    """
    root, root_fd = _validate_private_root(evidence_root)
    try:
        proc = subprocess.run([agy_executable, "--version"], capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode != 0:
            raise AgyCanaryEvidenceError("agy version probe failed")
        value = {"schema": "agy_capability_probe.v1", "agy_version": (proc.stdout or proc.stderr).strip(), "mode": None, "complete": False, "reason": "attended_stream_schema_probe_required"}
        _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def bootstrap_attest(*, evidence_root: Path, dotfiles_repo: Path) -> dict[str, Any]:
    """Seal only repository-derived bootstrap identities for the later attended gate."""
    repo = dotfiles_repo.resolve(strict=True)
    if not (repo / ".git").exists() or not (repo / "bootstrap.sh").is_file():
        raise AgyCanaryEvidenceError("bootstrap attestation requires a dotfiles checkout")
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    if head.returncode != 0:
        raise AgyCanaryEvidenceError("cannot resolve dotfiles HEAD")
    identities: dict[str, str] = {}
    for relative in ("bootstrap.sh", "shared/agent-harness.pin", "plans/manifest.json"):
        proc = subprocess.run(["git", "-C", str(repo), "rev-parse", f"HEAD:{relative}"], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise AgyCanaryEvidenceError(f"required bootstrap input is not committed: {relative}")
        identities[relative] = proc.stdout.strip()
    root, root_fd = _validate_private_root(evidence_root)
    try:
        value = {"schema": "agy_canary_bootstrap_attestation.v1", "repo_head": head.stdout.strip(), "blobs": identities}
        _exclusive_write_at(root_fd, "agy_canary_bootstrap_attestation.json", _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def prepare_canary(*, evidence_root: Path, settings_path: Path, seat_key: str) -> dict[str, Any]:
    """Bind cleanup lineage and a positively complete capability probe before launch."""
    root, root_fd = _validate_private_root(evidence_root)
    try:
        cleanup = _read_json_at(root_fd, _CLEANUP_STATE_NAME)
        if cleanup.get("state") != "committed":
            raise AgyCanaryEvidenceError("settings cleanup has not committed")
        probe = _read_json_at(root_fd, _PROBE_NAME)
        if probe.get("complete") is not True or probe.get("mode") not in {"stream_json", "trajectory_store"}:
            raise AgyCanaryEvidenceError("capability probe has not selected a complete authority")
        capture = AgyCanaryCapture(root, root_fd)
        ledger = create_capture(capture=capture, settings_path=settings_path, seat_key=seat_key)
        value = {"schema": "agy_canary_prepare.v1", "cleanup_sha256": _sha256(_canonical_json(cleanup)), "probe_sha256": _sha256(_canonical_json(probe)), "ledger_sha256": _sha256(_canonical_json(ledger)), "seat_key": seat_key}
        _exclusive_write_at(root_fd, _PREPARE_NAME, _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def finalize_canary(*, evidence_root: Path, expected_seat_key: str, check_only: bool = False) -> dict[str, Any]:
    """Seal the final reducer payload; this does not modify any tracked file."""
    proof = verify_capture(evidence_root=evidence_root, expected_seat_key=expected_seat_key)
    if check_only:
        return proof
    root, root_fd = _validate_private_root(evidence_root)
    try:
        inputs = {"schema": "agy_canary_inputs.v1", "proof_sha256": _sha256(_canonical_json(proof)), "completed_at": datetime.now(timezone.utc).isoformat()}
        _write_replace_at(root_fd, _INPUTS_NAME, inputs)
        return {**proof, "inputs_sha256": _sha256(_canonical_json(inputs))}
    finally:
        os.close(root_fd)
