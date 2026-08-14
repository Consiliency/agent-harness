"""Fail-closed evidence helpers for the opt-in Antigravity canary."""

from __future__ import annotations

import base64
import copy
import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # Windows imports this module but does not support POSIX account lookups.
    import pwd
except ImportError:  # pragma: no cover - Windows import coverage exercises this path.
    pwd = None  # type: ignore[assignment]

try:  # Windows imports the panel module but cannot perform this POSIX operation.
    import fcntl
except ImportError:  # pragma: no cover - exercised in a fresh blocked-import subprocess.
    fcntl = None  # type: ignore[assignment]


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
_CAPTURE_MODES = frozenset({"stream_json", "trajectory_store"})
_CUSTOMIZATION_ENV_PREFIXES = (
    "AGY_", "ANTIGRAVITY_", "GEMINI_", "XDG_CONFIG_", "XDG_DATA_", "XDG_STATE_", "XDG_CACHE_", "XDG_RUNTIME_",
)


class AgyCanaryEvidenceError(RuntimeError):
    """Raised when evidence cannot be produced without weakening a gate."""


def _account_home() -> Path:
    """Return the kernel account home, never the caller-controlled HOME value."""
    if pwd is None:
        return Path.home().resolve(strict=True)
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)


@dataclass(frozen=True)
class _TrustedAgyRuntime:
    source: Path
    device: int
    inode: int
    mode: int
    sha256: str
    destination: str = "/run/phase-loop-bin/agy"

    def revalidate(self) -> None:
        info = self.source.lstat()
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
                (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)) != (self.device, self.inode, self.mode) or
                _sha256(self.source.read_bytes()) != self.sha256):
            raise AgyCanaryEvidenceError("trusted agy executable drifted before namespace launch")


def _trusted_agy_runtime() -> _TrustedAgyRuntime:
    """Resolve agy from immutable account/system locations, never HOME or PATH."""
    home = _account_home()
    candidates = (home / ".local/bin/agy", Path("/usr/local/bin/agy"), Path("/usr/bin/agy"))
    for source in candidates:
        try:
            info = source.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
                not os.access(source, os.X_OK) or stat.S_IMODE(info.st_mode) & 0o022 or
                info.st_uid not in {0, os.getuid()}):
            raise AgyCanaryEvidenceError("trusted agy executable is unsafe")
        return _TrustedAgyRuntime(source=source, device=info.st_dev, inode=info.st_ino,
                                  mode=stat.S_IMODE(info.st_mode), sha256=_sha256(source.read_bytes()))
    raise AgyCanaryEvidenceError("trusted agy executable is unavailable")


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


@dataclass(frozen=True)
class AgyCanaryNamespace:
    """The production-equivalent child boundary for a capture-enabled seat."""

    stage: Path
    minimal_home: Path
    evidence_root: Path
    provider_hostname: str
    auth_binds: tuple[tuple[Path, str], ...] = ()
    resolver_source: Path | None = None
    resolver_sha256: str | None = None

    def outer_environment(self) -> dict[str, str]:
        """Minimal host environment for bwrap itself; never carry loader/runtime overrides."""
        return {name: os.environ[name] for name in ("LANG", "LC_ALL", "LC_CTYPE") if name in os.environ} | {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        }

    def agy_command(self, argv: list[str]) -> list[str]:
        if not argv or argv[0] != "agy":
            raise AgyCanaryEvidenceError("namespace agy command must start with agy")
        runtime = _trusted_agy_runtime()
        return self.command([runtime.destination, *argv[1:]], agy_runtime=runtime)

    def command(self, argv: list[str], *, agy_runtime: _TrustedAgyRuntime | None = None) -> list[str]:
        bwrap = Path("/usr/bin/bwrap")
        if not bwrap.is_file() or not os.access(bwrap, os.X_OK):
            raise AgyCanaryEvidenceError("capture requires /usr/bin/bwrap")
        if not self.stage.is_absolute() or not self.minimal_home.is_absolute():
            raise AgyCanaryEvidenceError("namespace inputs must be absolute")
        # `/tmp` and `/run` are fresh tmpfs mounts.  Thus the direct `/tmp` child
        # holding evidence is absent even though the immutable host filesystem is
        # mounted read-only for the provider executable and CA roots.
        command = [
            str(bwrap),
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--ro-bind", "/", "/",
            "--tmpfs", "/tmp",
            "--tmpfs", "/run",
            "--proc", "/proc",
            "--dev", "/dev",
            "--dir", "/run/phase-loop-review",
            "--ro-bind", str(self.stage), "/run/phase-loop-review",
            "--tmpfs", "/home",
            "--dir", "/home/phase-loop",
            "--ro-bind", str(self.minimal_home), "/home/phase-loop",
            "--setenv", "HOME", "/home/phase-loop",
            "--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "--setenv", "XDG_CONFIG_HOME", "/home/phase-loop/.config",
            "--setenv", "XDG_DATA_HOME", "/home/phase-loop/.local/share",
            "--setenv", "XDG_STATE_HOME", "/home/phase-loop/.local/state",
            "--setenv", "XDG_CACHE_HOME", "/home/phase-loop/.cache",
            "--setenv", "XDG_CONFIG_DIRS", "/home/phase-loop/.config",
            "--dir", "/run/user",
            "--dir", "/run/user/phase-loop",
            "--setenv", "XDG_RUNTIME_DIR", "/run/user/phase-loop",
            "--chdir", "/run/phase-loop-review",
        ]
        if agy_runtime is not None:
            agy_runtime.revalidate()
            command.extend(["--dir", "/run/phase-loop-bin", "--ro-bind", str(agy_runtime.source), agy_runtime.destination])
        # `/etc/resolv.conf` is often a symlink into `/run`; the fresh `/run`
        # otherwise leaves the child unable to resolve the provider.  Bind only
        # the resolved regular source back at its expected target.
        if self.resolver_source is not None:
            resolver_fd = os.open(self.resolver_source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                resolver_info = os.fstat(resolver_fd)
                resolver_bytes = b""
                while True:
                    chunk = os.read(resolver_fd, 65536)
                    if not chunk:
                        break
                    resolver_bytes += chunk
            finally:
                os.close(resolver_fd)
            if not stat.S_ISREG(resolver_info.st_mode) or self.resolver_sha256 != _sha256(resolver_bytes):
                raise AgyCanaryEvidenceError("resolver source bytes drifted")
            target = Path("/etc/resolv.conf").resolve(strict=True)
            if not target.is_relative_to(Path("/run")):
                raise AgyCanaryEvidenceError("resolver source is not an expected /run target")
            parents: list[Path] = []
            current = target.parent
            while current != Path("/run"):
                parents.append(current)
                current = current.parent
            for parent in reversed(parents):
                command.extend(["--dir", str(parent)])
            command.extend(["--ro-bind", str(self.resolver_source), str(target)])
        for source, destination in self.auth_binds:
            if not source.is_absolute() or Path(destination).is_absolute() is False:
                raise AgyCanaryEvidenceError("auth bind paths must be absolute")
            command.extend(["--ro-bind", str(source), destination])
        command.extend(["--", *argv])
        return command


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

    if fcntl is None:
        raise AgyCanaryEvidenceError("settings cleanup requires POSIX fcntl locking")
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
            _account_home() / ".gemini" / "antigravity-cli" / "settings.json"
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


def inventory_customizations(
    *, home: Path, env: dict[str, str] | None = None, project_dir: Path | None = None
) -> dict[str, list[str]]:
    """Inventory all supported executable customization sources.

    This is deliberately an inventory of the *real* user/project environment,
    not the generated minimal HOME used after masking.  Callers that need an
    authorizing result must freeze the returned record and revalidate it before
    launch with :func:`freeze_customization_inventory`.
    """
    home = home.resolve(strict=True)
    sources = {
        "hooks": [home / ".gemini" / "antigravity-cli" / "hooks"],
        "plugins": [home / ".gemini" / "antigravity-cli" / "plugins"],
        "mcp": [home / ".gemini" / "antigravity-cli" / "mcp.json"],
        "project": [home / ".gemini" / "antigravity-cli" / "project-settings.json"],
        "system": [
            Path("/etc/antigravity"), Path("/etc/gemini"), Path("/etc/xdg/antigravity"),
            Path("/usr/share/antigravity"), Path("/usr/share/gemini"),
            Path("/usr/local/share/antigravity"), Path("/usr/local/share/gemini"),
        ],
    }
    if project_dir is not None:
        sources["project"].extend([
            project_dir / ".gemini", project_dir / ".antigravity", project_dir / ".mcp.json",
        ])
    found: dict[str, list[str]] = {key: [] for key in sources}
    for kind, paths in sources.items():
        for path in paths:
            if path.exists() or path.is_symlink():
                found[kind].append(str(path))
    source_env = os.environ if env is None else env
    found["environment_overrides"] = sorted(
        name for name in source_env if name.startswith(_CUSTOMIZATION_ENV_PREFIXES)
        and name not in {"AGY_CANARY_SETTINGS_PATH"}
    )
    if any(found.values()):
        raise AgyCanaryEvidenceError("active agy customization source detected")
    return found


def freeze_customization_inventory(
    *, home: Path, project_dir: Path, env: dict[str, str]
) -> dict[str, Any]:
    """Derive a complete, empty source inventory from real launch inputs."""
    if not home.is_absolute() or not project_dir.is_absolute():
        raise AgyCanaryEvidenceError("customization inventory requires absolute user and project roots")
    inventory = inventory_customizations(home=home, project_dir=project_dir, env=env)
    # Preserve candidates as path hashes only: their identities can be compared
    # later without placing a home/project path into public canary output.
    candidates = {
        "home_sha256": _sha256(str(home.resolve(strict=True)).encode()),
        "project_sha256": _sha256(str(project_dir.resolve(strict=True)).encode()),
        "environment_names": sorted(
            name for name in env
            if name.startswith(_CUSTOMIZATION_ENV_PREFIXES)
            and name not in {"AGY_CANARY_SETTINGS_PATH"}
        ),
        "inventory": inventory,
    }
    if candidates["environment_names"] or any(inventory.values()):
        raise AgyCanaryEvidenceError("active agy customization source detected")
    return {"schema": "agy_customization_inventory.v1", "sources_complete": True, **candidates}


def revalidate_customization_inventory(
    frozen: dict[str, Any], *, home: Path, project_dir: Path, env: dict[str, str]
) -> None:
    """Fail closed if any real source changed after the inventory was frozen."""
    if frozen != freeze_customization_inventory(home=home, project_dir=project_dir, env=env):
        raise AgyCanaryEvidenceError("customization-source inventory drifted")


def _validated_auth_binds(auth_paths: tuple[Path, ...], minimal_home: Path) -> tuple[tuple[Path, str], ...]:
    binds: list[tuple[Path, str]] = []
    auth_dir = minimal_home / ".gemini" / "antigravity-cli" / "auth"
    auth_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    for source in auth_paths:
        if not source.is_absolute() or source.is_symlink():
            raise AgyCanaryEvidenceError("authentication bind must be an absolute regular file")
        parent_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            data, info = _reopen_at(parent_fd, source.name)
            if not stat.S_ISREG(info.st_mode):
                raise AgyCanaryEvidenceError("authentication bind must be a regular file")
        finally:
            os.close(parent_fd)
        host_destination = auth_dir / source.name
        host_destination.write_bytes(b"")  # required bind target, never a copied credential
        host_destination.chmod(0o600)
        # bwrap mounts ``minimal_home`` at /home/phase-loop; later auth binds
        # must therefore target this in-namespace path, not the hidden host temp HOME.
        destination = f"/home/phase-loop/.gemini/antigravity-cli/auth/{source.name}"
        binds.append((source.resolve(strict=True), destination))
        # Never retain authentication bytes; the digest proves the exact file the
        # operator bound without disclosing it in a record or prompt.
        _ = _sha256(data)
    return tuple(binds)


def build_minimal_home(
    *, evidence_root: Path, settings_path: Path, auth_paths: tuple[Path, ...] = ()
) -> tuple[Path, tuple[tuple[Path, str], ...]]:
    """Create a private minimal HOME that exposes only reducer-validated settings.

    Authentication material is intentionally not copied here.  An attended
    operator may add an explicit read-only bind after proving its required path;
    this helper otherwise fails closed rather than falling back to normal HOME.
    """
    root = Path(tempfile.mkdtemp(prefix="phase-loop-agy-home-", dir="/tmp"))
    root.chmod(0o700)
    if evidence_root.resolve(strict=True) in root.parents:
        raise AgyCanaryEvidenceError("minimal HOME must not be beneath evidence root")
    config = root / ".gemini" / "antigravity-cli"
    config.mkdir(parents=True, mode=0o700)
    for directory in (root / ".config", root / ".local" / "share", root / ".local" / "state", root / ".cache"):
        directory.mkdir(parents=True, mode=0o700)
    target = config / "settings.json"
    opened = _open_settings(settings_path)
    try:
        data = opened.data
    finally:
        os.close(opened.parent_fd)
    target.write_bytes(data)
    target.chmod(0o600)
    binds = _validated_auth_binds(auth_paths, root)
    inventory_customizations(home=root, env={})
    return root, binds


def _resolver_snapshot() -> tuple[Path, str]:
    """Descriptor-read the only resolver file a fresh /run namespace may rebind."""
    resolver = Path("/etc/resolv.conf").resolve(strict=True)
    info = resolver.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AgyCanaryEvidenceError("resolved resolver source is not regular")
    resolver_fd = os.open(resolver, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(resolver_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(resolver_fd)
    return resolver, _sha256(b"".join(chunks))


def build_probe_namespace(
    *, evidence_root: Path, stage: Path, settings_path: Path,
    auth_paths: tuple[Path, ...] = (), provider_hostname: str = "antigravity.google",
) -> AgyCanaryNamespace:
    """Derive the probe namespace from the owned settings/auth sources, never argv HOME."""
    home, auth_binds = build_minimal_home(
        evidence_root=evidence_root, settings_path=settings_path, auth_paths=auth_paths
    )
    resolver, resolver_sha256 = _resolver_snapshot()
    return AgyCanaryNamespace(
        stage=stage, minimal_home=home, evidence_root=evidence_root,
        provider_hostname=provider_hostname, auth_binds=auth_binds,
        resolver_source=resolver, resolver_sha256=resolver_sha256,
    )


def namespace_self_test(*, namespace: AgyCanaryNamespace) -> dict[str, Any]:
    """Prove the fixed stage path and evidence-root masking before provider launch."""
    test_program = (
        "import socket, ssl, pathlib, os; "
        "assert pathlib.Path('/run/phase-loop-review/review-instructions.md').is_file(); "
        "assert pathlib.Path('/run/phase-loop-review/review-bundle.md').is_file(); "
        "assert not pathlib.Path('/tmp/' + os.environ['PL_EVIDENCE_BASENAME']).exists(); "
        f"socket.getaddrinfo({namespace.provider_hostname!r}, 443, type=socket.SOCK_STREAM); "
        f"s=socket.create_connection(({namespace.provider_hostname!r}, 443), timeout=10); "
        f"ssl.create_default_context().wrap_socket(s, server_hostname={namespace.provider_hostname!r}).close()"
    )
    child_env = namespace.outer_environment() | {"PL_EVIDENCE_BASENAME": namespace.evidence_root.name}
    proc = subprocess.run(
        namespace.command([sys.executable, "-I", "-c", test_program]),
        capture_output=True, text=True, timeout=30, check=False, env=child_env,
    )
    if proc.returncode != 0:
        raise AgyCanaryEvidenceError("bwrap namespace masking self-test failed")
    return {"schema": "agy_namespace_self_test.v1", "stage": "/run/phase-loop-review", "evidence_root_hidden": True, "provider_hostname": namespace.provider_hostname}


def _policy_facts(settings: dict[str, Any]) -> dict[str, bool]:
    permissions = settings.get("permissions", {})
    allow = permissions.get("allow", []) if isinstance(permissions, dict) else None
    preset = settings.get("toolPermission", "request-review")
    return {
        "effective_allow_empty": allow == [],
        "safe_preset": isinstance(preset, str) and preset in _SAFE_PRESETS,
        "non_workspace_access_disabled": settings.get("allowNonWorkspaceAccess", False) is False,
    }


def inventory_policy_sources(
    *, settings_path: Path, source_inventory: dict[str, Any]
) -> dict[str, Any]:
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
    if source_inventory.get("schema") != "agy_customization_inventory.v1" or source_inventory.get("sources_complete") is not True:
        raise AgyCanaryEvidenceError("capture policy lacks a complete real customization inventory")
    return {
        "schema": "agy_policy_inventory.v1",
        "settings": {
            "path_sha256": _sha256(str(settings_path.resolve()).encode()),
            "bytes": len(opened.data),
            "sha256": _sha256(opened.data),
        },
        "sources_complete": True,
        "customization_inventory": source_inventory,
        **facts,
    }


def create_capture(
    *, capture: AgyCanaryCapture, settings_path: Path, seat_key: str,
    source_inventory: dict[str, Any] | None = None, capture_mode: str = "stream_json"
) -> dict[str, Any]:
    """Start a single-seat capture ledger after strict policy inventory."""
    if not seat_key or "/" in seat_key or "\\" in seat_key:
        raise AgyCanaryEvidenceError("Gemini seat key must be a nonempty canonical key")
    if capture_mode not in _CAPTURE_MODES:
        raise AgyCanaryEvidenceError("capture mode is not supported")
    if source_inventory is None:
        # Compatibility for internal assembly tests only.  The reducer refuses
        # to authorize this record because it makes no complete-source claim.
        policy = {**inventory_policy_sources(settings_path=settings_path, source_inventory={"schema": "agy_customization_inventory.v1", "sources_complete": True, "inventory": {}, "environment_names": [], "home_sha256": "", "project_sha256": ""}), "sources_complete": False}
    else:
        policy = inventory_policy_sources(settings_path=settings_path, source_inventory=source_inventory)
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
        "capture_mode": capture_mode,
        "policy": policy,
        "attempts": [],
    }
    _exclusive_write_at(capture.root_fd, _LEDGER_NAME, _canonical_json(ledger), 0o600)
    return ledger


def retain_staged_files(*, capture: AgyCanaryCapture, review_dir: Path) -> dict[str, dict[str, Any]]:
    """Descriptor-read and retain the two only permitted staged inputs."""
    if "private_board" in _read_json_at(capture.root_fd, _LEDGER_NAME):
        raise AgyCanaryEvidenceError("cannot retain staged inputs after private board sealing")
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
    if "private_board" in ledger:
        raise AgyCanaryEvidenceError("cannot record launch after private board sealing")
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


def _parse_stream(
    data: bytes, *, require_staged_reads: bool = False
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Parse the intentionally narrow, versioned stream-json authority."""
    calls: dict[str, dict[str, Any]] = {}
    sequence = -1
    terminal: dict[str, Any] | None = None
    session: str | None = None
    pending_call: str | None = None
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
        if terminal is not None:
            raise AgyCanaryEvidenceError("stream contains an event after terminal")
        if kind == "tool_call":
            call_id = event.get("call_id")
            if not isinstance(call_id, str) or call_id in calls or pending_call is not None:
                raise AgyCanaryEvidenceError("stream tool call identity is invalid")
            calls[call_id] = event
            pending_call = call_id
        elif kind == "tool_result":
            call_id = event.get("call_id")
            if not isinstance(call_id, str) or call_id != pending_call or "result" in calls.get(call_id, {}):
                raise AgyCanaryEvidenceError("stream tool result is unmatched")
            calls[call_id]["result"] = event
            pending_call = None
        elif kind == "terminal":
            if pending_call is not None or terminal is not None or not isinstance(event.get("text"), str):
                raise AgyCanaryEvidenceError("stream terminal event is invalid")
            terminal = event
        else:
            raise AgyCanaryEvidenceError("stream event kind is unsupported")
    if session is None or terminal is None or pending_call is not None or any("result" not in call for call in calls.values()):
        raise AgyCanaryEvidenceError("stream does not contain complete calls and terminal result")
    if require_staged_reads:
        expected = {
            "/run/phase-loop-review/review-instructions.md",
            "/run/phase-loop-review/review-bundle.md",
        }
        staged_calls = list(calls.values())
        if len(staged_calls) != 2:
            raise AgyCanaryEvidenceError("stream does not contain exactly two staged reads")
        actual = {str(call.get("target")) for call in staged_calls}
        if actual != expected or any(call.get("tool") != "read_file" for call in staged_calls):
            raise AgyCanaryEvidenceError("stream does not contain exactly two staged reads")
        for call in staged_calls:
            result = call.get("result")
            if not isinstance(result, dict) or result.get("outcome") != "success":
                raise AgyCanaryEvidenceError("stream staged read did not succeed")
            # The reducer derives the staged-file proof from raw content.  A
            # provider-reported digest or byte count alone is not authority.
            if not isinstance(result.get("content"), str):
                raise AgyCanaryEvidenceError("stream staged read lacks reconstructable content")
    return session, list(calls.values()), terminal


def _require_probe_content_matches_stage(
    calls: list[dict[str, Any]], namespace: AgyCanaryNamespace
) -> None:
    """Bind the probe's raw read content to the two descriptor-opened stage files."""
    expected: dict[str, bytes] = {}
    stage_fd = os.open(
        namespace.stage,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        for name in ("review-instructions.md", "review-bundle.md"):
            data, info = _reopen_at(stage_fd, name)
            if not stat.S_ISREG(info.st_mode):
                raise AgyCanaryEvidenceError("probe staged input is not a regular file")
            expected[f"/run/phase-loop-review/{name}"] = data
    finally:
        os.close(stage_fd)
    for call in calls:
        target = call.get("target")
        result = call.get("result")
        if target not in expected or not isinstance(result, dict):
            raise AgyCanaryEvidenceError("probe staged read is unclassifiable")
        content = result.get("content")
        if not isinstance(content, str) or content.encode() != expected[target]:
            raise AgyCanaryEvidenceError("probe staged content does not match fixed input")


def _parse_trajectory(data: bytes) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Parse a sealed trajectory-store snapshot into the same strict event shape."""
    try:
        value = json.loads(data)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("trajectory snapshot is not JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("conversation_id"), str):
        raise AgyCanaryEvidenceError("trajectory snapshot lacks a conversation identity")
    events = value.get("events")
    if not isinstance(events, list):
        raise AgyCanaryEvidenceError("trajectory snapshot lacks events")
    # Reuse stream validation after requiring that every stored event belongs to
    # the sealed conversation.  This is intentionally not a heuristic DB scan.
    normalized: list[str] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict) or event.get("conversation_id") != value["conversation_id"]:
            raise AgyCanaryEvidenceError("trajectory contains an unbound event")
        copied = dict(event)
        copied["sequence"] = index
        copied["session_id"] = value["conversation_id"]
        normalized.append(json.dumps(copied, sort_keys=True))
    return _parse_stream("\n".join(normalized).encode())


def verify_capture(*, evidence_root: Path, expected_seat_key: str, seal: bool = True) -> dict[str, Any]:
    """Strictly reduce all sealed attempts and reject incomplete/forged evidence."""
    root, root_fd = _validate_private_root(evidence_root)
    try:
        ledger = _read_json_at(root_fd, _LEDGER_NAME)
        base_ledger_fields = {"schema", "seat_key", "capture_mode", "policy", "attempts"}
        if not isinstance(ledger, dict) or (set(ledger) != base_ledger_fields and set(ledger) != base_ledger_fields | {"private_board"}) or ledger.get("schema") != "agy_canary_launch_ledger.v1":
            raise AgyCanaryEvidenceError("capture ledger schema is malformed")
        if ledger.get("seat_key") != expected_seat_key:
            raise AgyCanaryEvidenceError("sealed Gemini seat key does not match board")
        mode = ledger.get("capture_mode")
        if mode not in _CAPTURE_MODES:
            raise AgyCanaryEvidenceError("capture mode is not sealed")
        policy = ledger.get("policy")
        if not isinstance(policy, dict) or not all(policy.get(name) is True for name in ("effective_allow_empty", "safe_preset", "non_workspace_access_disabled", "sources_complete")):
            raise AgyCanaryEvidenceError("capture policy facts are incomplete")
        attempts = ledger.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise AgyCanaryEvidenceError("capture has no Gemini attempts")
        output_attempts: list[dict[str, Any]] = []
        final_text = ""
        for item in attempts:
            if not isinstance(item, dict) or set(item) != {"attempt_id", "seat_key", "returncode", "argv_sha256", "stream", "diagnostic", "staged", "completed_at"}:
                raise AgyCanaryEvidenceError("capture attempt schema is malformed")
            if not isinstance(item, dict) or item.get("seat_key") != expected_seat_key:
                raise AgyCanaryEvidenceError("capture contains an unbound attempt")
            if item.get("returncode") != 0:
                raise AgyCanaryEvidenceError("capture attempt did not exit zero")
            stream = item.get("stream")
            staged = item.get("staged")
            if not isinstance(stream, dict) or not isinstance(staged, dict):
                raise AgyCanaryEvidenceError("capture launch record is incomplete")
            if set(staged) != {"review-instructions.md", "review-bundle.md"}:
                raise AgyCanaryEvidenceError("capture staged input set is not exact")
            diagnostic = item.get("diagnostic")
            if not isinstance(diagnostic, dict) or set(diagnostic) != {"name", "bytes", "sha256"}:
                raise AgyCanaryEvidenceError("capture diagnostic schema is malformed")
            diagnostic_bytes = _read_regular_at(root_fd, str(diagnostic.get("name", "")))
            if len(diagnostic_bytes) != diagnostic.get("bytes") or _sha256(diagnostic_bytes) != diagnostic.get("sha256"):
                raise AgyCanaryEvidenceError("sealed diagnostic bytes drifted")
            for staged_name, staged_record in staged.items():
                if not isinstance(staged_record, dict) or set(staged_record) != {"retained", "bytes", "sha256"}:
                    raise AgyCanaryEvidenceError("capture retained input schema is malformed")
                retained = _read_regular_at(root_fd, str(staged_record.get("retained", "")))
                if len(retained) != staged_record.get("bytes") or _sha256(retained) != staged_record.get("sha256"):
                    raise AgyCanaryEvidenceError("sealed retained input bytes drifted")
            raw = _read_regular_at(root_fd, str(stream.get("name", "")))
            if len(raw) != stream.get("bytes") or _sha256(raw) != stream.get("sha256"):
                raise AgyCanaryEvidenceError("sealed stream bytes drifted")
            _session, calls, terminal = (
                _parse_stream(raw) if mode == "stream_json" else _parse_trajectory(raw)
            )
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
                    if basename in reads and target == f"/run/phase-loop-review/{basename}":
                        if result.get("outcome") != "success":
                            raise AgyCanaryEvidenceError("accepted staged read did not succeed")
                        reads[basename].append(result)
                    else:
                        counts["out_of_stage_read"] += 1
                elif tool in {"command", "unsandboxed"}:
                    counts[tool] += 1
                else:
                    counts["non_read_tool"] += 1
                if succeeded and tool != "read_file":
                    raise AgyCanaryEvidenceError("accepted attempt executed a non-read tool")
            if any(counts.values()):
                raise AgyCanaryEvidenceError("accepted attempt contains a prohibited tool attempt")
            for name, expected in staged.items():
                if not isinstance(expected, dict) or not reads.get(name):
                    raise AgyCanaryEvidenceError(f"accepted attempt did not read {name}")
                if not any(
                    isinstance(result.get("content"), str)
                    and _sha256(result["content"].encode()) == expected.get("sha256")
                    and len(result["content"].encode()) == expected.get("bytes")
                    for result in reads[name]
                ):
                    raise AgyCanaryEvidenceError(f"read result does not cover sealed {name}")
            output_attempts.append({"attempt_id": item.get("attempt_id"), "counts": counts, "terminal_sha256": _sha256(str(terminal["text"]).encode())})
            final_text = str(terminal["text"])
        if not final_text.strip():
            raise AgyCanaryEvidenceError("final Gemini review is empty")
        private_board = ledger.get("private_board")
        if not isinstance(private_board, dict):
            raise AgyCanaryEvidenceError("capture has no sealed private board payload")
        name = private_board.get("name")
        if not isinstance(name, str):
            raise AgyCanaryEvidenceError("private board binding has no name")
        board_bytes = _read_regular_at(root_fd, name)
        if len(board_bytes) != private_board.get("bytes") or _sha256(board_bytes) != private_board.get("sha256"):
            raise AgyCanaryEvidenceError("private board payload bytes drifted")
        try:
            board_payload = json.loads(board_bytes)
        except json.JSONDecodeError as exc:
            raise AgyCanaryEvidenceError("private board payload is not JSON") from exc
        pre_board = dict(ledger)
        pre_board.pop("private_board")
        pre_board_data = _canonical_json(pre_board)
        expected_summary = {"gemini_seat_key": pre_board.get("seat_key"), "gemini_seat_count": 1, "attempt_ids": [item.get("attempt_id") for item in attempts], "ledger_bytes": len(pre_board_data), "ledger_sha256": _sha256(pre_board_data)}
        if private_board.get("capture") != expected_summary or not isinstance(board_payload, dict) or board_payload.get("agy_canary_capture") != expected_summary:
            raise AgyCanaryEvidenceError("private board does not bind the sealed capture summary")
        proof = {
            "schema": SCHEMA_VERSION,
            "seat_key": expected_seat_key,
            "attempt_ids": [item["attempt_id"] for item in output_attempts],
            "capture_mode": mode,
            "attempts": output_attempts,
            "accepted_review_sha256": _sha256(final_text.encode()),
            "private_board_sha256": private_board["sha256"],
        }
        if seal:
            _write_replace_at(root_fd, "agy_canary_proof.json", proof)
        return proof
    finally:
        os.close(root_fd)


def write_private_board(*, capture: AgyCanaryCapture, basename: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create the full board payload only in the validated private root."""
    if not basename or Path(basename).name != basename:
        raise AgyCanaryEvidenceError("private board name must be a basename")
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    if "private_board" in ledger:
        raise AgyCanaryEvidenceError("capture private board payload is already sealed")
    summary = capture_summary(capture)
    if payload.get("agy_canary_capture") != summary:
        raise AgyCanaryEvidenceError("private board payload does not bind capture summary")
    data = _canonical_json(payload)
    _exclusive_write_at(capture.root_fd, basename, data, 0o600)
    private = {"name": basename, "bytes": len(data), "sha256": _sha256(data), "capture": summary}
    ledger["private_board"] = private
    _write_replace_at(capture.root_fd, _LEDGER_NAME, ledger)
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


def probe_capability(
    *,
    evidence_root: Path,
    agy_executable: str = "agy",
    namespace: AgyCanaryNamespace | None = None,
) -> dict[str, Any]:
    """Run the bounded 1.1.13 stream-json schema probe inside the live profile.

    The 1.1.13 CLI advertises ``--output-format stream-json``.  Advertising a
    flag alone is not evidence: this producer executes a no-command, staged-only
    request through the same namespace wrapper, then accepts the mode only when
    the returned bytes satisfy the strict parser.  It is intentionally attended
    because it consumes the operator's authenticated subscription.
    """
    runtime = _trusted_agy_runtime()
    if agy_executable not in {"agy", str(runtime.source)}:
        raise AgyCanaryEvidenceError("agy probe executable must be the trusted agy path")
    root, root_fd = _validate_private_root(evidence_root)
    try:
        runtime.revalidate()
        version_proc = subprocess.run([str(runtime.source), "--version"], capture_output=True, text=True, timeout=15, check=False)
        runtime.revalidate()
        help_proc = subprocess.run([str(runtime.source), "--help"], capture_output=True, text=True, timeout=15, check=False)
        version = (version_proc.stdout or version_proc.stderr).strip()
        help_text = (help_proc.stdout or help_proc.stderr)
        if version_proc.returncode != 0 or help_proc.returncode != 0:
            raise AgyCanaryEvidenceError("agy version probe failed")
        if version != "1.1.13" or "stream-json" not in help_text:
            value = {"schema": "agy_capability_probe.v1", "agy_version": version, "help_sha256": _sha256(help_text.encode()), "mode": None, "complete": False, "reason": "unsupported_agy_1_1_13_capture_surface"}
            _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
            return value
        if namespace is None:
            value = {"schema": "agy_capability_probe.v1", "agy_version": version, "help_sha256": _sha256(help_text.encode()), "mode": None, "complete": False, "reason": "production_namespace_required"}
            _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
            return value
        namespace_self_test(namespace=namespace)
        command = [
            "agy", "--output-format", "stream-json", "--sandbox", "--add-dir",
            "/run/phase-loop-review", "--print-timeout", "30s", "-p",
            "Read review-instructions.md and review-bundle.md only. Do not use any other tool. Reply with READY.",
        ]
        proc = subprocess.run(namespace.agy_command(command), capture_output=True, text=True, timeout=90, check=False)
        stream = (proc.stdout or "").encode()
        try:
            _session, calls, _terminal = _parse_stream(stream, require_staged_reads=True)
            _require_probe_content_matches_stage(calls, namespace)
        except AgyCanaryEvidenceError as exc:
            value = {"schema": "agy_capability_probe.v1", "agy_version": version, "help_sha256": _sha256(help_text.encode()), "mode": None, "complete": False, "reason": f"stream_json_schema_unproven:{type(exc).__name__}", "stream_sha256": _sha256(stream)}
        else:
            if proc.returncode != 0:
                raise AgyCanaryEvidenceError("agy stream-json probe process failed")
            value = {"schema": "agy_capability_probe.v1", "agy_version": version, "help_sha256": _sha256(help_text.encode()), "mode": "stream_json", "complete": True, "stream_sha256": _sha256(stream), "stream_bytes": len(stream)}
        _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def _canonical_bash() -> Path:
    bash = Path("/usr/bin/bash").resolve(strict=True)
    if not bash.is_file() or not os.access(bash, os.X_OK):
        raise AgyCanaryEvidenceError("bootstrap attestation requires canonical /usr/bin/bash")
    return bash


def _canonical_uv() -> Path:
    """Resolve uv from a fixed trusted location, never an ambient PATH search."""
    candidates = (_account_home() / ".local" / "bin" / "uv", Path("/usr/local/bin/uv"), Path("/usr/bin/uv"))
    for candidate in candidates:
        try:
            executable = candidate.resolve(strict=True)
        except FileNotFoundError:
            continue
        if executable.is_file() and os.access(executable, os.X_OK):
            return executable
    raise AgyCanaryEvidenceError("bootstrap attestation requires a canonical uv executable")


def _uv_tool_dir(uv_executable: Path) -> Path:
    proc = subprocess.run([str(uv_executable), "tool", "dir"], capture_output=True, text=True, timeout=30, check=False)
    tool_dir = Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
    if tool_dir is None or not tool_dir.is_absolute() or not tool_dir.is_dir() or tool_dir.is_symlink():
        raise AgyCanaryEvidenceError("canonical uv tool directory is unavailable")
    return tool_dir.resolve(strict=True)


def _installed_phase_loop_identity(*, uv_executable: Path | None = None) -> dict[str, str]:
    """Inspect only uv's canonical managed entrypoint, not an ambient PATH shim."""
    uv = _canonical_uv() if uv_executable is None else uv_executable.resolve(strict=True)
    tool_dir = _uv_tool_dir(uv)
    script = tool_dir / "phase-loop-runtime" / "bin" / "phase-loop"
    if not script.is_file() or script.is_symlink():
        raise AgyCanaryEvidenceError("phase-loop console script is not installed in canonical uv tool dir")
    first_line = script.read_text(encoding="utf-8", errors="strict").splitlines()[0:1]
    if len(first_line) != 1 or not first_line[0].startswith("#!"):
        raise AgyCanaryEvidenceError("phase-loop console script has no canonical interpreter")
    interpreter = Path(first_line[0][2:])
    if not interpreter.is_absolute() or not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise AgyCanaryEvidenceError("phase-loop interpreter is not canonical")
    program = (
        "import importlib.metadata as m,json,pathlib,phase_loop_runtime; "
        "d=m.distribution('phase-loop-runtime'); root=pathlib.Path(d.locate_file('')).resolve(); "
        "module=pathlib.Path(phase_loop_runtime.__file__).resolve(); "
        "direct=next((pathlib.Path(d.locate_file(f)) for f in d.files or [] if f.name=='direct_url.json'),None); "
        "value={'version':d.version,'distribution_root':str(root),'module_origin':str(module),"
        "'direct_url_sha256':__import__('hashlib').sha256(direct.read_bytes()).hexdigest() if direct else '',"
        "'direct_url':json.loads(direct.read_text()) if direct else {}}; print(json.dumps(value,sort_keys=True))"
    )
    proc = subprocess.run(
        [str(interpreter), "-I", "-c", program], capture_output=True, text=True, timeout=30,
        check=False,
    )
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("phase-loop interpreter did not identify its distribution") from exc
    if proc.returncode != 0 or not isinstance(value, dict) or not all(isinstance(value.get(key), str) for key in ("version", "distribution_root", "module_origin", "direct_url_sha256")):
        raise AgyCanaryEvidenceError("phase-loop installed distribution identity is invalid")
    root = Path(value["distribution_root"])
    module = Path(value["module_origin"])
    direct = value.get("direct_url")
    if not module.is_relative_to(root) or not isinstance(direct, dict):
        raise AgyCanaryEvidenceError("phase-loop module ownership is invalid")
    archive = direct.get("archive_info")
    if not isinstance(direct.get("url"), str) or not isinstance(archive, dict) or not isinstance(archive.get("hash"), str):
        raise AgyCanaryEvidenceError("phase-loop direct-wheel provenance is unavailable")
    return {
        "uv_executable": str(uv), "uv_tool_dir": str(tool_dir),
        "console_script": str(script), "interpreter": str(interpreter),
        "version": value["version"], "distribution_root": str(root),
        "module_origin": str(module), "direct_url_sha256": value["direct_url_sha256"],
        "archive_hash": archive["hash"], "archive_url_sha256": _sha256(direct["url"].encode()),
    }


def _git_text(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AgyCanaryEvidenceError(f"git command failed: {' '.join(args)}")
    return proc.stdout.strip()


def _repo_relative_path(repo: Path, candidate: Path) -> str:
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise AgyCanaryEvidenceError("attested repository input must be a canonical relative path")
    path = (repo / candidate).resolve(strict=True)
    if repo not in path.parents or not path.is_file() or path.is_symlink():
        raise AgyCanaryEvidenceError("attested repository input is not a regular repository file")
    return candidate.as_posix()


def _worktree_blob(repo: Path, relative: str) -> tuple[str, bytes]:
    blob = _git_text(repo, "rev-parse", f"HEAD:{relative}")
    committed = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{relative}"], capture_output=True, check=False)
    local = (repo / relative).read_bytes()
    if committed.returncode != 0 or committed.stdout != local:
        raise AgyCanaryEvidenceError(f"worktree input differs from committed HEAD: {relative}")
    return blob, local


def _clean_dotfiles_repo(repo: Path) -> str:
    if not (repo / ".git").exists() or not (repo / "bootstrap.sh").is_file():
        raise AgyCanaryEvidenceError("bootstrap attestation requires a dotfiles checkout")
    if _git_text(repo, "status", "--porcelain"):
        raise AgyCanaryEvidenceError("bootstrap attestation requires a clean dotfiles worktree")
    return _git_text(repo, "rev-parse", "HEAD")


def _bootstrap_environment(*, nonce: str, uv_executable: Path, account_home: Path) -> dict[str, str]:
    """Use an explicit allowlist, never the caller's ambient environment."""
    supplied_home = os.environ.get("HOME")
    if supplied_home is not None and Path(supplied_home).resolve(strict=False) != account_home:
        raise AgyCanaryEvidenceError("bootstrap attestation rejects HOME drift")
    allowed = ("LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL", "TMPDIR")
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env["HOME"] = str(account_home)
    env["PATH"] = str(uv_executable.parent) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    env["PHASE_LOOP_AGY_CANARY_BOOTSTRAP_NONCE"] = nonce
    return env


def bootstrap_attest(
    *, evidence_root: Path, dotfiles_repo: Path, plan_path: Path
) -> dict[str, Any]:
    """Directly run committed bootstrap and attest its nonce-bound child result."""
    disallowed_overrides = sorted(
        key for key in os.environ
        if key in {"DEV_EDITABLE", "PYTHONPATH", "PYTHONHOME"}
        or key.startswith("PHASE_LOOP_")
        or key.startswith("AGENT_HARNESS_")
    )
    if disallowed_overrides:
        raise AgyCanaryEvidenceError(
            "bootstrap attestation rejects environment overrides: "
            + ",".join(disallowed_overrides)
        )
    repo = dotfiles_repo.resolve(strict=True)
    head = _clean_dotfiles_repo(repo)
    plan_relative = _repo_relative_path(repo, plan_path)
    identities: dict[str, str] = {}
    inputs: dict[str, bytes] = {}
    for relative in ("bootstrap.sh", "shared/agent-harness.pin", "plans/manifest.json", plan_relative):
        blob, data = _worktree_blob(repo, relative)
        identities[relative] = blob
        inputs[relative] = data
    pin = (repo / "shared" / "agent-harness.pin").read_text(encoding="utf-8").strip()
    if pin != "v0.7.14":
        raise AgyCanaryEvidenceError("bootstrap attestation requires the v0.7.14 fleet pin")
    nonce = secrets.token_hex(24)
    bash = _canonical_bash()
    uv = _canonical_uv()
    child_env = _bootstrap_environment(nonce=nonce, uv_executable=uv, account_home=_account_home())
    script_bytes = inputs["bootstrap.sh"]
    def revalidate_inputs() -> None:
        if _clean_dotfiles_repo(repo) != head:
            raise AgyCanaryEvidenceError("bootstrap inputs drifted from the attested clean HEAD")
        for relative, expected_blob in identities.items():
            blob, data = _worktree_blob(repo, relative)
            if blob != expected_blob or data != inputs[relative]:
                raise AgyCanaryEvidenceError("bootstrap input bytes drifted from attested blobs")
    revalidate_inputs()
    before = subprocess.run([str(uv), "tool", "list"], capture_output=True, text=True, timeout=30, check=False)
    with tempfile.NamedTemporaryFile(prefix="phase-loop-bootstrap-", dir="/tmp", delete=False) as snapshot:
        snapshot.write(script_bytes)
        snapshot.flush()
        os.fchmod(snapshot.fileno(), 0o700)
        bootstrap_argv = (str(bash), snapshot.name)
    try:
        child_process = subprocess.Popen(
            list(bootstrap_argv), cwd=repo, env=child_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            _stdout, _stderr = child_process.communicate(timeout=1800)
        except subprocess.TimeoutExpired as exc:
            child_process.kill()
            child_process.communicate()
            raise AgyCanaryEvidenceError("direct bootstrap child timed out") from exc
    finally:
        os.unlink(bootstrap_argv[1])
    child_rc = child_process.returncode
    revalidate_inputs()
    after = subprocess.run([str(uv), "tool", "list"], capture_output=True, text=True, timeout=30, check=False)
    if child_rc != 0:
        raise AgyCanaryEvidenceError("direct bootstrap child failed")
    installation = _installed_phase_loop_identity(uv_executable=uv)
    if installation["version"] != "0.7.14":
        raise AgyCanaryEvidenceError("bootstrap did not install the expected phase-loop version")
    root, root_fd = _validate_private_root(evidence_root)
    try:
        value = {
            "schema": "agy_canary_bootstrap_attestation.v1",
            "repo_head": head,
            "blobs": identities,
            "input_sha256": {name: _sha256(data) for name, data in inputs.items()},
            "targets": {"plan": plan_relative, "manifest": "plans/manifest.json"},
            "nonce_sha256": _sha256(nonce.encode()),
            "bootstrap": {
                "argv": list(bootstrap_argv),
                "pid": child_process.pid,
                "returncode": child_rc,
                "script_sha256": _sha256(script_bytes),
                "script_blob": identities["bootstrap.sh"],
                "before_uv_tools_sha256": _sha256((before.stdout or "").encode()),
                "after_uv_tools_sha256": _sha256((after.stdout or "").encode()),
                "environment_names": sorted(child_env),
                "installation": installation,
            },
        }
        _exclusive_write_at(root_fd, "agy_canary_bootstrap_attestation.json", _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def _rederive_cleanup_lineage(*, root_fd: int, settings_path: Path) -> dict[str, Any]:
    """Reopen the sealed preimage and current settings; never trust a cleanup flag."""
    cleanup = _read_json_at(root_fd, _CLEANUP_STATE_NAME)
    if cleanup.get("state") != "committed":
        raise AgyCanaryEvidenceError("settings cleanup has not committed")
    before_bytes = _read_regular_at(root_fd, _SETTINGS_SNAPSHOT_NAME)
    before = _parse_policy(before_bytes)
    expected, result = _derive_replacement(before)
    opened = _open_settings(settings_path)
    try:
        current_bytes = opened.data
        current = _parse_policy(current_bytes)
        current_mode = opened.mode
    finally:
        os.close(opened.parent_fd)
    if cleanup.get("settings_path_sha256") != _sha256(str(settings_path).encode()):
        raise AgyCanaryEvidenceError("cleanup settings source does not match prepare source")
    if cleanup.get("before_sha256") != _sha256(before_bytes):
        raise AgyCanaryEvidenceError("cleanup sealed preimage bytes drifted")
    if cleanup.get("recovery_snapshot_sha256") != _sha256(before_bytes):
        raise AgyCanaryEvidenceError("cleanup snapshot lineage is incomplete")
    if cleanup.get("before_mode") != format(current_mode, "04o"):
        raise AgyCanaryEvidenceError("cleanup settings mode lineage drifted")
    if current != expected or result != cleanup.get("result"):
        raise AgyCanaryEvidenceError("cleanup structural delta does not match current settings")
    facts = _policy_facts(current)
    if not all(facts.values()):
        raise AgyCanaryEvidenceError("cleanup current policy is not strict and empty")
    return {
        "cleanup": cleanup,
        "settings_sha256": _sha256(current_bytes),
        "settings_bytes": len(current_bytes),
        "settings_mode": format(current_mode, "04o"),
    }


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed PyPI URL below
        value = json.load(response)
    if not isinstance(value, dict):
        raise AgyCanaryEvidenceError("release metadata is not an object")
    return value


def _download_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - verified handoff URL
        return response.read()


def _release_handoff_record(text: bytes) -> dict[str, Any]:
    start = b"<!-- release_evidence.v1:start -->"
    end = b"<!-- release_evidence.v1:end -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise AgyCanaryEvidenceError("merged handoff lacks one release evidence record")
    raw = text.split(start, 1)[1].split(end, 1)[0]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("merged handoff release evidence is not JSON") from exc
    required = {"schema", "version", "release_commit", "tag_object", "tag_peel", "release_url", "workflow_url", "pypi_metadata_url", "artifacts"}
    if not isinstance(value, dict) or set(value) != required or value.get("schema") != "release_evidence.v1" or _canonical_json(value) != raw:
        raise AgyCanaryEvidenceError("merged handoff release evidence has the wrong schema")
    if not isinstance(value["version"], str) or not value["version"].count(".") == 2:
        raise AgyCanaryEvidenceError("merged handoff release version is malformed")
    for name in ("release_commit", "tag_object", "tag_peel"):
        if not isinstance(value[name], str) or len(value[name]) != 40 or any(char not in "0123456789abcdef" for char in value[name].lower()):
            raise AgyCanaryEvidenceError("merged handoff immutable identity is malformed")
    for name in ("release_url", "workflow_url", "pypi_metadata_url"):
        parsed = urllib.parse.urlparse(value[name]) if isinstance(value[name], str) else None
        if parsed is None or parsed.scheme != "https" or not parsed.netloc:
            raise AgyCanaryEvidenceError("merged handoff URL is malformed")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise AgyCanaryEvidenceError("merged handoff artifacts are malformed")
    identities: set[tuple[str, str, str]] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"filename", "packagetype", "url", "sha256"} or not all(isinstance(artifact.get(name), str) for name in ("filename", "packagetype", "url", "sha256")):
            raise AgyCanaryEvidenceError("merged handoff artifact row is malformed")
        if len(artifact["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in artifact["sha256"].lower()):
            raise AgyCanaryEvidenceError("merged handoff artifact digest is malformed")
        parsed = urllib.parse.urlparse(artifact["url"])
        if parsed.scheme != "https" or not parsed.netloc:
            raise AgyCanaryEvidenceError("merged handoff artifact URL is malformed")
        identity = (artifact["filename"], artifact["packagetype"], artifact["url"])
        if identity in identities:
            raise AgyCanaryEvidenceError("merged handoff artifact rows are duplicated")
        identities.add(identity)
    return value


def _reconcile_release_lineage(
    *, repo: Path, handoff_commit: str,
    fetch_json: Any = _fetch_json, download: Any = _download_bytes,
) -> dict[str, Any]:
    """Derive the release provenance exclusively from merged repository state.

    The downloader and metadata fetcher are seams for synthetic fixtures.  The
    production implementation always derives URLs and digests from the merged
    handoff/PyPI record; callers cannot supply them.
    """
    if len(handoff_commit) != 40 or any(ch not in "0123456789abcdef" for ch in handoff_commit.lower()):
        raise AgyCanaryEvidenceError("handoff selector must be an immutable commit OID")
    if _git_text(repo, "status", "--porcelain"):
        raise AgyCanaryEvidenceError("release lineage requires a clean agent-harness worktree")
    resolved = _git_text(repo, "rev-parse", f"{handoff_commit}^{{commit}}")
    if resolved != handoff_commit:
        raise AgyCanaryEvidenceError("handoff selector must not be a movable ref")
    if _git_text(repo, "diff", "--name-only", f"{resolved}^", resolved).splitlines() != ["docs/releases/outside-agent-release-handoff.md"]:
        raise AgyCanaryEvidenceError("handoff commit changes paths outside the release handoff")
    # A handoff is authoritative only after its commit is reachable from the
    # fetched main branch, never merely present in an arbitrary local branch.
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", resolved, "origin/main"], capture_output=True, check=False).returncode != 0:
        raise AgyCanaryEvidenceError("handoff commit is not merged into origin/main")
    handoff = _release_handoff_record(subprocess.run(
        ["git", "-C", str(repo), "show", f"{resolved}:docs/releases/outside-agent-release-handoff.md"],
        capture_output=True, check=False,
    ).stdout)
    version = handoff.get("version")
    release_commit = handoff.get("release_commit")
    if not isinstance(version, str) or not isinstance(release_commit, str) or len(release_commit) != 40:
        raise AgyCanaryEvidenceError("merged handoff lacks immutable release identity")
    tag = f"v{version}"
    tag_object = _git_text(repo, "rev-parse", f"refs/tags/{tag}")
    tag_peel = _git_text(repo, "rev-parse", f"refs/tags/{tag}^{{}}")
    if tag_peel != release_commit or handoff.get("tag_object") != tag_object or handoff.get("tag_peel") != tag_peel:
        raise AgyCanaryEvidenceError("handoff tag identity does not match local signed tag")
    if subprocess.run(["git", "-C", str(repo), "verify-tag", "--raw", f"refs/tags/{tag}"], capture_output=True, check=False).returncode != 0:
        raise AgyCanaryEvidenceError("release tag signature verification failed")
    release = subprocess.run(
        ["gh", "release", "view", tag, "--repo", "Consiliency/agent-harness", "--json", "url,tagName"],
        capture_output=True, text=True, check=False,
    )
    try:
        release_value = json.loads(release.stdout)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("GitHub Release lookup failed") from exc
    if release.returncode != 0 or not isinstance(release_value, dict) or release_value.get("tagName") != tag or release_value.get("url") != handoff.get("release_url"):
        raise AgyCanaryEvidenceError("GitHub Release does not match merged handoff")
    workflow = subprocess.run(
        ["gh", "run", "list", "--repo", "Consiliency/agent-harness", "--workflow", "publish-pypi.yml", "--commit", release_commit, "--limit", "20", "--json", "headSha,conclusion,event,url"],
        capture_output=True, text=True, check=False,
    )
    try:
        runs = json.loads(workflow.stdout)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("publish workflow lookup failed") from exc
    matching = [row for row in runs if isinstance(row, dict) and row.get("headSha") == release_commit and row.get("conclusion") == "success" and row.get("event") == "push"] if isinstance(runs, list) else []
    if workflow.returncode != 0 or len(matching) != 1 or matching[0].get("url") != handoff.get("workflow_url"):
        raise AgyCanaryEvidenceError("publish workflow does not match merged handoff")
    metadata_url = f"https://pypi.org/pypi/phase-loop-runtime/{version}/json"
    if handoff.get("pypi_metadata_url") != metadata_url:
        raise AgyCanaryEvidenceError("handoff PyPI metadata endpoint is not canonical")
    metadata = fetch_json(metadata_url)
    rows = metadata.get("urls")
    artifacts = handoff.get("artifacts")
    if not isinstance(rows, list) or not isinstance(artifacts, list):
        raise AgyCanaryEvidenceError("release artifact metadata is incomplete")
    expected: dict[tuple[str, str, str], str] = {}
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("filename", "packagetype", "url")):
            raise AgyCanaryEvidenceError("PyPI artifact row is malformed")
        digest = row.get("digests", {}).get("sha256") if isinstance(row.get("digests"), dict) else None
        if not isinstance(digest, str) or len(digest) != 64:
            raise AgyCanaryEvidenceError("PyPI artifact digest is malformed")
        expected[(row["filename"], row["packagetype"], row["url"])] = digest
    recorded: dict[tuple[str, str, str], str] = {}
    for row in artifacts:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("filename", "packagetype", "url", "sha256")):
            raise AgyCanaryEvidenceError("handoff artifact row is malformed")
        recorded[(row["filename"], row["packagetype"], row["url"])] = row["sha256"]
    if expected != recorded or not any(name.endswith(".whl") for name, _kind, _url in expected) or not any(name.endswith(".tar.gz") for name, _kind, _url in expected):
        raise AgyCanaryEvidenceError("handoff artifacts do not exactly match PyPI")
    for (_filename, _kind, url), digest in expected.items():
        if _sha256(download(url)) != digest:
            raise AgyCanaryEvidenceError("downloaded release artifact digest mismatch")
    return {
        "version": version, "handoff_commit": resolved, "release_commit": release_commit,
        "tag_object": tag_object, "tag_peel": tag_peel,
        "artifacts": [
            {"filename": name, "packagetype": kind, "sha256": digest, "url_sha256": _sha256(url.encode())}
            for (name, kind, url), digest in sorted(expected.items())
        ],
    }


def prepare_canary(
    *, evidence_root: Path, settings_path: Path, seat_key: str, auth_paths: tuple[Path, ...] = (),
    agent_harness_repo: Path, handoff_commit: str, customization_home: Path,
    project_dir: Path, source_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Bind cleanup lineage and a positively complete capability probe before launch."""
    root, root_fd = _validate_private_root(evidence_root)
    try:
        cleanup_lineage = _rederive_cleanup_lineage(
            root_fd=root_fd, settings_path=settings_path
        )
        cleanup = cleanup_lineage["cleanup"]
        probe = _read_json_at(root_fd, _PROBE_NAME)
        if probe.get("complete") is not True or probe.get("mode") not in {"stream_json", "trajectory_store"}:
            raise AgyCanaryEvidenceError("capability probe has not selected a complete authority")
        bootstrap = _read_json_at(root_fd, "agy_canary_bootstrap_attestation.json")
        bootstrap_result = bootstrap.get("bootstrap")
        if not isinstance(bootstrap_result, dict) or bootstrap_result.get("returncode") != 0:
            raise AgyCanaryEvidenceError("direct bootstrap attestation is incomplete")
        installation = bootstrap_result.get("installation")
        if not isinstance(installation, dict) or installation != _installed_phase_loop_identity():
            raise AgyCanaryEvidenceError("direct bootstrap installed identity no longer matches")
        bootstrap_targets = bootstrap.get("targets")
        bootstrap_blobs = bootstrap.get("blobs")
        if not isinstance(bootstrap_targets, dict) or not isinstance(bootstrap_blobs, dict):
            raise AgyCanaryEvidenceError("bootstrap attestation lacks target identities")
        source_environment = dict(os.environ) if source_env is None else dict(source_env)
        source_inventory = freeze_customization_inventory(
            home=customization_home, project_dir=project_dir, env=source_environment
        )
        # Reopen immediately before the first capture ledger write; this makes a
        # generated minimal HOME incapable of standing in for source discovery.
        revalidate_customization_inventory(
            source_inventory, home=customization_home, project_dir=project_dir, env=source_environment
        )
        release = _reconcile_release_lineage(
            repo=agent_harness_repo.resolve(strict=True), handoff_commit=handoff_commit
        )
        revalidate_customization_inventory(
            source_inventory, home=customization_home, project_dir=project_dir, env=source_environment
        )
        wheel_rows = [row for row in release["artifacts"] if str(row["filename"]).endswith(".whl")]
        if len(wheel_rows) != 1:
            raise AgyCanaryEvidenceError("release lineage has no unique wheel")
        wheel = wheel_rows[0]
        if installation.get("version") != release["version"] or installation.get("archive_hash") not in {f"sha256={wheel['sha256']}", wheel["sha256"]} or installation.get("archive_url_sha256") != wheel["url_sha256"]:
            raise AgyCanaryEvidenceError("installed phase-loop provenance does not match verified wheel")
        capture = AgyCanaryCapture(root, root_fd)
        ledger = create_capture(
            capture=capture,
            settings_path=settings_path,
            seat_key=seat_key,
            source_inventory=source_inventory,
            capture_mode=str(probe["mode"]),
        )
        minimal_home, auth_binds = build_minimal_home(
            evidence_root=capture.root, settings_path=settings_path, auth_paths=auth_paths
        )
        ledger["minimal_home"] = str(minimal_home)
        ledger["customization_sources"] = {
            "inventory": source_inventory,
            "home": str(customization_home.resolve(strict=True)),
            "project": str(project_dir.resolve(strict=True)),
        }
        bind_records: list[dict[str, str]] = []
        for source, destination in auth_binds:
            parent_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                data, _info = _reopen_at(parent_fd, source.name)
            finally:
                os.close(parent_fd)
            bind_records.append({"source": str(source), "destination": destination, "source_sha256": _sha256(data)})
        ledger["auth_binds"] = bind_records
        _write_replace_at(root_fd, _LEDGER_NAME, ledger)
        value = {"schema": "agy_canary_prepare.v1", "cleanup_sha256": _sha256(_canonical_json(cleanup)), "probe_sha256": _sha256(_canonical_json(probe)), "bootstrap_sha256": _sha256(_canonical_json(bootstrap)), "ledger_sha256": _sha256(_canonical_json(ledger)), "settings_sha256": cleanup_lineage["settings_sha256"], "settings_bytes": cleanup_lineage["settings_bytes"], "settings_mode": cleanup_lineage["settings_mode"], "seat_key": seat_key, "release": release, "release_sha256": _sha256(_canonical_json(release)), "source_inventory_sha256": _sha256(_canonical_json(source_inventory))}
        _exclusive_write_at(root_fd, _PREPARE_NAME, _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def capture_namespace(*, capture: AgyCanaryCapture, stage: Path, provider_hostname: str = "antigravity.google") -> AgyCanaryNamespace:
    """Recover the prepare-sealed minimal HOME for one production child launch."""
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    if ledger.get("capture_mode") != "stream_json":
        raise AgyCanaryEvidenceError("production launch has no supported stream-json authority")
    name = ledger.get("minimal_home")
    if not isinstance(name, str) or not Path(name).is_absolute():
        raise AgyCanaryEvidenceError("prepare did not seal a minimal HOME")
    home = Path(name)
    info = home.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise AgyCanaryEvidenceError("sealed minimal HOME is invalid")
    inventory_customizations(home=home, env={}, project_dir=stage)
    source_record = ledger.get("customization_sources")
    if source_record is not None:
        if not isinstance(source_record, dict) or not isinstance(source_record.get("inventory"), dict) or not isinstance(source_record.get("home"), str) or not isinstance(source_record.get("project"), str):
            raise AgyCanaryEvidenceError("prepare has malformed customization-source inventory")
        revalidate_customization_inventory(
            source_record["inventory"], home=Path(source_record["home"]),
            project_dir=Path(source_record["project"]), env=dict(os.environ),
        )
    auth_records = ledger.get("auth_binds", [])
    if not isinstance(auth_records, list):
        raise AgyCanaryEvidenceError("prepare has malformed authentication binds")
    auth_binds: list[tuple[Path, str]] = []
    for record in auth_records:
        if not isinstance(record, dict) or not isinstance(record.get("source"), str) or not isinstance(record.get("destination"), str):
            raise AgyCanaryEvidenceError("prepare has malformed authentication bind")
        source = Path(record["source"])
        parent_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            data, _info = _reopen_at(parent_fd, source.name)
        finally:
            os.close(parent_fd)
        if _sha256(data) != record.get("source_sha256"):
            raise AgyCanaryEvidenceError("authentication bind bytes drifted")
        auth_binds.append((source, str(record["destination"])))
    resolver, resolver_sha256 = _resolver_snapshot()
    return AgyCanaryNamespace(stage=stage, minimal_home=home, evidence_root=capture.root, provider_hostname=provider_hostname, auth_binds=tuple(auth_binds), resolver_source=resolver, resolver_sha256=resolver_sha256)


def _replace_regular_file(path: Path, data: bytes) -> None:
    parent = path.parent.resolve(strict=True)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        current, info = _reopen_at(parent_fd, path.name)
        if not stat.S_ISREG(info.st_mode):
            raise AgyCanaryEvidenceError("finalizer target is not a regular file")
        temporary = f".{path.name}.{secrets.token_hex(12)}"
        _exclusive_write_at(parent_fd, temporary, data, stat.S_IMODE(info.st_mode))
        os.rename(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _final_suffix(proof: dict[str, Any], attestation: dict[str, Any]) -> bytes:
    payload = {"attestation": attestation, "proof": proof, "proof_sha256": _sha256(_canonical_json(proof)), "schema": "agy_canary_final.v1"}
    return b"\n## Execution evidence\n\n```json\n" + _canonical_json(payload) + b"```\n"


def _parse_final_payload(plan: bytes) -> tuple[bytes, dict[str, Any]]:
    marker = b"\n## Execution evidence\n\n```json\n"
    if plan.count(marker) != 1 or not plan.endswith(b"```\n"):
        raise AgyCanaryEvidenceError("final plan does not contain one canonical execution suffix")
    before, encoded = plan.split(marker, 1)
    try:
        payload = json.loads(encoded[:-4])
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("final execution payload is not JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"attestation", "proof", "proof_sha256", "schema"} or payload.get("schema") != "agy_canary_final.v1" or not isinstance(payload.get("proof"), dict) or not isinstance(payload.get("attestation"), dict):
        raise AgyCanaryEvidenceError("final execution payload is invalid")
    if payload.get("proof_sha256") != _sha256(_canonical_json(payload["proof"])) or _canonical_json(payload) != encoded[:-4]:
        raise AgyCanaryEvidenceError("final execution payload is not canonical")
    return before, payload


def _attested_final_targets(
    *, root_fd: int, repo: Path, plan_path: Path, manifest_path: Path, plan_slug: str,
    require_preimages: bool = True,
) -> tuple[dict[str, Any], str, str]:
    bootstrap = _read_json_at(root_fd, "agy_canary_bootstrap_attestation.json")
    current_head = _clean_dotfiles_repo(repo) if require_preimages else _git_text(repo, "rev-parse", "HEAD")
    if bootstrap.get("repo_head") != current_head:
        raise AgyCanaryEvidenceError("dotfiles worktree no longer matches bootstrap-attested HEAD")
    targets = bootstrap.get("targets")
    blobs = bootstrap.get("blobs")
    input_sha256 = bootstrap.get("input_sha256")
    if not isinstance(targets, dict) or not isinstance(blobs, dict) or not isinstance(input_sha256, dict):
        raise AgyCanaryEvidenceError("bootstrap attestation lacks tracked finalizer targets")
    plan_relative = _repo_relative_path(repo, plan_path)
    manifest_relative = _repo_relative_path(repo, manifest_path)
    if targets.get("plan") != plan_relative or targets.get("manifest") != manifest_relative:
        raise AgyCanaryEvidenceError("finalizer targets differ from bootstrap attestation")
    if require_preimages:
        plan_blob, plan_bytes = _worktree_blob(repo, plan_relative)
        manifest_blob, manifest_bytes = _worktree_blob(repo, manifest_relative)
        if blobs.get(plan_relative) != plan_blob or blobs.get(manifest_relative) != manifest_blob or input_sha256.get(plan_relative) != _sha256(plan_bytes) or input_sha256.get(manifest_relative) != _sha256(manifest_bytes):
            raise AgyCanaryEvidenceError("finalizer input blob differs from bootstrap attestation")
    if not plan_slug:
        raise AgyCanaryEvidenceError("finalizer requires a canonical plan slug")
    return bootstrap, plan_relative, manifest_relative


def check_private_final(
    *, evidence_root: Path, expected_seat_key: str, dotfiles_repo: Path,
    plan_path: Path, manifest_path: Path, plan_slug: str,
) -> dict[str, Any]:
    """Read-only reverse validator for the private reducer-sealed final state."""
    proof = verify_capture(evidence_root=evidence_root, expected_seat_key=expected_seat_key, seal=False)
    root, root_fd = _validate_private_root(evidence_root)
    try:
        repo = dotfiles_repo.resolve(strict=True)
        _bootstrap, plan_relative, manifest_relative = _attested_final_targets(
            root_fd=root_fd, repo=repo, plan_path=plan_path, manifest_path=manifest_path, plan_slug=plan_slug,
            require_preimages=False,
        )
        inputs = _read_json_at(root_fd, _INPUTS_NAME)
        if inputs.get("proof") != proof or inputs.get("plan") != plan_relative or inputs.get("manifest") != manifest_relative or inputs.get("plan_slug") != plan_slug:
            raise AgyCanaryEvidenceError("private finalizer receipt is not bound to current proof and targets")
        plan_before = base64.b64decode(str(inputs.get("plan_before_b64", "")), validate=True)
        manifest_before = base64.b64decode(str(inputs.get("manifest_before_b64", "")), validate=True)
        completed_at = inputs.get("completed_at")
        if not isinstance(completed_at, str):
            raise AgyCanaryEvidenceError("private finalizer receipt lacks completion time")
        attestation = inputs.get("attestation")
        if not isinstance(attestation, dict):
            raise AgyCanaryEvidenceError("private finalizer receipt lacks attested identities")
        plan_after = plan_before + _final_suffix(proof, attestation)
        manifest_value = json.loads(manifest_before)
        entries = manifest_value.get("plans") if isinstance(manifest_value, dict) else None
        matches = [item for item in entries or [] if isinstance(item, dict) and item.get("slug") == plan_slug]
        if len(matches) != 1:
            raise AgyCanaryEvidenceError("private finalizer receipt has an invalid manifest preimage")
        matches[0]["updated_at"] = completed_at
        manifest_after = _canonical_json(manifest_value)
        if (repo / plan_relative).read_bytes() != plan_after or (repo / manifest_relative).read_bytes() != manifest_after:
            raise AgyCanaryEvidenceError("tracked finalizer output drifted from its sealed preimages")
        return {**proof, "inputs_sha256": _sha256(_canonical_json(inputs))}
    except (ValueError, json.JSONDecodeError) as exc:
        raise AgyCanaryEvidenceError("private finalizer receipt is malformed") from exc
    finally:
        os.close(root_fd)


def check_committed_final(
    *, dotfiles_repo: Path, commit: str, plan_path: Path, manifest_path: Path, plan_slug: str,
    agent_harness_repo: Path, handoff_commit: str,
) -> dict[str, Any]:
    """Reverse the fixed transform from immutable git objects without private files."""
    repo = dotfiles_repo.resolve(strict=True)
    plan_relative = _repo_relative_path(repo, plan_path)
    manifest_relative = _repo_relative_path(repo, manifest_path)
    resolved = _git_text(repo, "rev-parse", f"{commit}^{{commit}}")
    parent = _git_text(repo, "rev-parse", f"{resolved}^")
    changed = _git_text(repo, "diff", "--name-only", parent, resolved).splitlines()
    if sorted(changed) != sorted([plan_relative, manifest_relative]):
        raise AgyCanaryEvidenceError("committed finalizer transform changed unexpected paths")
    after_plan = subprocess.run(["git", "-C", str(repo), "show", f"{resolved}:{plan_relative}"], capture_output=True, check=False).stdout
    before_plan = subprocess.run(["git", "-C", str(repo), "show", f"{parent}:{plan_relative}"], capture_output=True, check=False).stdout
    after_manifest = subprocess.run(["git", "-C", str(repo), "show", f"{resolved}:{manifest_relative}"], capture_output=True, check=False).stdout
    before_manifest = subprocess.run(["git", "-C", str(repo), "show", f"{parent}:{manifest_relative}"], capture_output=True, check=False).stdout
    prefix, payload = _parse_final_payload(after_plan)
    if prefix != before_plan:
        raise AgyCanaryEvidenceError("committed plan prefix differs from parent preimage")
    _validate_committed_attestation(
        repo=repo, attestation=payload["attestation"], plan_relative=plan_relative,
        manifest_relative=manifest_relative, plan_before=before_plan, manifest_before=before_manifest,
    )
    release = payload["attestation"]["release"]
    if release != _reconcile_release_lineage(
        repo=agent_harness_repo.resolve(strict=True), handoff_commit=handoff_commit
    ):
        raise AgyCanaryEvidenceError("committed release identity does not reauthenticate immutable handoff lineage")
    try:
        before_value = json.loads(before_manifest)
        after_value = json.loads(after_manifest)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("committed manifest is not JSON") from exc
    entries_before = before_value.get("plans") if isinstance(before_value, dict) else None
    entries_after = after_value.get("plans") if isinstance(after_value, dict) else None
    matches_before = [item for item in entries_before or [] if isinstance(item, dict) and item.get("slug") == plan_slug]
    matches_after = [item for item in entries_after or [] if isinstance(item, dict) and item.get("slug") == plan_slug]
    if len(matches_before) != 1 or len(matches_after) != 1:
        raise AgyCanaryEvidenceError("committed finalizer transform lacks one target manifest entry")
    completed_at = matches_after[0].get("updated_at")
    matches_before[0]["updated_at"] = completed_at
    if _canonical_json(before_value) != after_manifest:
        raise AgyCanaryEvidenceError("committed manifest changed outside canonical updated_at transform")
    return {"commit": resolved, "proof_sha256": payload["proof_sha256"], "plan_sha256": _sha256(after_plan), "manifest_sha256": _sha256(after_manifest)}


def _validate_committed_attestation(
    *, repo: Path, attestation: Any, plan_relative: str, manifest_relative: str,
    plan_before: bytes, manifest_before: bytes,
) -> None:
    """Validate every bootstrap/release identity embedded in a committed suffix."""
    bootstrap = attestation.get("bootstrap") if isinstance(attestation, dict) else None
    release = attestation.get("release") if isinstance(attestation, dict) else None
    if not isinstance(attestation, dict) or set(attestation) != {"bootstrap", "release", "release_sha256"} or not isinstance(bootstrap, dict) or not isinstance(release, dict) or attestation["release_sha256"] != _sha256(_canonical_json(release)):
        raise AgyCanaryEvidenceError("committed finalizer payload lacks attested bootstrap/release identities")
    if set(bootstrap) != {"repo_head", "blobs", "input_sha256"}:
        raise AgyCanaryEvidenceError("committed finalizer bootstrap identity is malformed")
    repo_head = bootstrap["repo_head"]
    blobs = bootstrap["blobs"]
    input_sha256 = bootstrap["input_sha256"]
    expected_paths = {"bootstrap.sh", "shared/agent-harness.pin", "plans/manifest.json", plan_relative}
    if not isinstance(repo_head, str) or len(repo_head) != 40 or not isinstance(blobs, dict) or not isinstance(input_sha256, dict) or set(blobs) != expected_paths or set(input_sha256) != expected_paths:
        raise AgyCanaryEvidenceError("committed finalizer bootstrap identity is malformed")
    if _git_text(repo, "rev-parse", f"{repo_head}^{{commit}}") != repo_head:
        raise AgyCanaryEvidenceError("committed finalizer bootstrap HEAD is not immutable")
    base_bytes: dict[str, bytes] = {}
    for relative in expected_paths:
        actual = subprocess.run(["git", "-C", str(repo), "show", f"{repo_head}:{relative}"], capture_output=True, check=False)
        if actual.returncode != 0 or blobs[relative] != _git_text(repo, "rev-parse", f"{repo_head}:{relative}") or input_sha256[relative] != _sha256(actual.stdout):
            raise AgyCanaryEvidenceError("committed finalizer bootstrap blob identity drifted")
        base_bytes[relative] = actual.stdout
    if base_bytes[plan_relative] != plan_before or base_bytes[manifest_relative] != manifest_before:
        raise AgyCanaryEvidenceError("committed finalizer preimages differ from bootstrap identity")
    if set(release) != {"version", "handoff_commit", "release_commit", "tag_object", "tag_peel", "artifacts"} or release.get("version") != "0.7.14" or release.get("tag_peel") != release.get("release_commit"):
        raise AgyCanaryEvidenceError("committed finalizer release identity is malformed")
    for name in ("handoff_commit", "release_commit", "tag_object", "tag_peel"):
        value = release.get(name)
        if not isinstance(value, str) or len(value) != 40 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise AgyCanaryEvidenceError("committed finalizer release identity is malformed")
    artifacts = release.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AgyCanaryEvidenceError("committed finalizer release artifacts are malformed")
    identities: set[tuple[str, str]] = set()
    wheel_count = sdist_count = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"filename", "packagetype", "sha256", "url_sha256"} or not all(isinstance(artifact.get(name), str) for name in ("filename", "packagetype", "sha256", "url_sha256")):
            raise AgyCanaryEvidenceError("committed finalizer release artifact is malformed")
        if any(len(artifact[name]) != 64 or any(char not in "0123456789abcdef" for char in artifact[name].lower()) for name in ("sha256", "url_sha256")):
            raise AgyCanaryEvidenceError("committed finalizer release artifact digest is malformed")
        identity = (artifact["filename"], artifact["packagetype"])
        if identity in identities:
            raise AgyCanaryEvidenceError("committed finalizer release artifacts are duplicated")
        identities.add(identity)
        wheel_count += artifact["filename"].endswith(".whl")
        sdist_count += artifact["filename"].endswith(".tar.gz")
    if wheel_count != 1 or sdist_count != 1:
        raise AgyCanaryEvidenceError("committed finalizer release requires one wheel and one sdist")


def finalize_canary(
    *,
    evidence_root: Path,
    expected_seat_key: str,
    check_only: bool = False,
    dotfiles_repo: Path | None = None,
    plan_path: Path | None = None,
    manifest_path: Path | None = None,
    plan_slug: str | None = None,
) -> dict[str, Any]:
    """Seal the proof and, when explicitly configured, apply its only tracked suffix."""
    if dotfiles_repo is None:
        raise AgyCanaryEvidenceError("tracked finalization requires a bootstrap-attested dotfiles repository")
    if check_only:
        if dotfiles_repo is None or plan_path is None or manifest_path is None or not plan_slug:
            raise AgyCanaryEvidenceError("private finalizer check requires repo, plan, manifest, and plan slug")
        return check_private_final(evidence_root=evidence_root, expected_seat_key=expected_seat_key, dotfiles_repo=dotfiles_repo, plan_path=plan_path, manifest_path=manifest_path, plan_slug=plan_slug)
    proof = verify_capture(evidence_root=evidence_root, expected_seat_key=expected_seat_key)
    root, root_fd = _validate_private_root(evidence_root)
    try:
        completed_at = datetime.now(timezone.utc).isoformat()
        inputs = {"schema": "agy_canary_inputs.v1", "proof": proof, "proof_sha256": _sha256(_canonical_json(proof)), "completed_at": completed_at}
        if plan_path is None or manifest_path is None or not plan_slug:
            raise AgyCanaryEvidenceError("tracked finalization requires repo, plan, manifest, and plan slug")
        repo = dotfiles_repo.resolve(strict=True)
        _bootstrap, plan_relative, manifest_relative = _attested_final_targets(
            root_fd=root_fd, repo=repo, plan_path=plan_path, manifest_path=manifest_path, plan_slug=plan_slug
        )
        prepare = _read_json_at(root_fd, _PREPARE_NAME)
        release = prepare.get("release")
        if not isinstance(release, dict) or prepare.get("release_sha256") != _sha256(_canonical_json(release)):
            raise AgyCanaryEvidenceError("finalizer requires release identities sealed by prepare")
        inputs["attestation"] = {
            "bootstrap": {name: _bootstrap.get(name) for name in ("repo_head", "blobs", "input_sha256")},
            "release": release,
            "release_sha256": prepare["release_sha256"],
        }
        plan = repo / plan_relative
        manifest = repo / manifest_relative
        plan_before = plan.read_bytes()
        if b"## Execution evidence" in plan_before:
            raise AgyCanaryEvidenceError("plan already has execution evidence")
        manifest_before = manifest.read_bytes()
        try:
            manifest_value = json.loads(manifest_before)
        except json.JSONDecodeError as exc:
            raise AgyCanaryEvidenceError("manifest is not JSON") from exc
        entries = manifest_value.get("plans") if isinstance(manifest_value, dict) else None
        matches = [entry for entry in entries or [] if isinstance(entry, dict) and entry.get("slug") == plan_slug]
        if len(matches) != 1:
            raise AgyCanaryEvidenceError("finalizer could not identify one manifest plan")
        plan_after = plan_before + _final_suffix(proof, inputs["attestation"])
        matches[0]["updated_at"] = completed_at
        manifest_after = _canonical_json(manifest_value)
        inputs.update({
                "plan_before_sha256": _sha256(plan_before),
                "plan_after_sha256": _sha256(plan_after),
                "manifest_before_sha256": _sha256(manifest_before),
                "manifest_after_sha256": _sha256(manifest_after),
                "plan": plan_relative,
                "manifest": manifest_relative,
                "plan_slug": plan_slug,
                "plan_before_b64": base64.b64encode(plan_before).decode(),
                "manifest_before_b64": base64.b64encode(manifest_before).decode(),
        })
        _write_replace_at(root_fd, _INPUTS_NAME, inputs)
        _replace_regular_file(plan, plan_after)
        _replace_regular_file(manifest, manifest_after)
        return {**proof, "inputs_sha256": _sha256(_canonical_json(inputs))}
    finally:
        os.close(root_fd)
