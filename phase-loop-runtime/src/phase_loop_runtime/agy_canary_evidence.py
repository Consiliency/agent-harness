"""Fail-closed evidence helpers for the opt-in Antigravity canary."""

from __future__ import annotations

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
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
_CUSTOMIZATION_ENV_PREFIXES = ("AGY_", "ANTIGRAVITY_", "GEMINI_")


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

    def command(self, argv: list[str]) -> list[str]:
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
            "--setenv", "XDG_CONFIG_HOME", "/home/phase-loop/.config",
            "--setenv", "XDG_DATA_HOME", "/home/phase-loop/.local/share",
            "--chdir", "/run/phase-loop-review",
        ]
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


def inventory_customizations(
    *, home: Path, env: dict[str, str] | None = None, project_dir: Path | None = None
) -> dict[str, list[str]]:
    """Reject every known executable customization source before a child launch."""
    home = home.resolve(strict=True)
    sources = {
        "hooks": [home / ".gemini" / "antigravity-cli" / "hooks"],
        "plugins": [home / ".gemini" / "antigravity-cli" / "plugins"],
        "mcp": [home / ".gemini" / "antigravity-cli" / "mcp.json"],
        "project": [home / ".gemini" / "antigravity-cli" / "project-settings.json"],
        "system": [
            Path("/etc/antigravity"), Path("/etc/gemini"),
            Path("/usr/share/antigravity"), Path("/usr/local/share/antigravity"),
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
        destination = auth_dir / source.name
        destination.write_bytes(b"")  # required bind target, never a copied credential
        destination.chmod(0o600)
        binds.append((source.resolve(strict=True), str(destination)))
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
    child_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(_CUSTOMIZATION_ENV_PREFIXES)
    }
    child_env["PL_EVIDENCE_BASENAME"] = namespace.evidence_root.name
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
    *, settings_path: Path, customization_home: Path | None = None, env: dict[str, str] | None = None
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
    customizations = (
        inventory_customizations(home=customization_home, env=env)
        if customization_home is not None
        else {"hooks": [], "plugins": [], "mcp": [], "project": [], "environment_overrides": []}
    )
    return {
        "schema": "agy_policy_inventory.v1",
        "settings": {
            "path_sha256": _sha256(str(settings_path.resolve()).encode()),
            "bytes": len(opened.data),
            "sha256": _sha256(opened.data),
        },
        "sources_complete": True,
        "customization_inventory": customizations,
        **facts,
    }


def create_capture(
    *, capture: AgyCanaryCapture, settings_path: Path, seat_key: str, capture_mode: str = "stream_json"
) -> dict[str, Any]:
    """Start a single-seat capture ledger after strict policy inventory."""
    if not seat_key or "/" in seat_key or "\\" in seat_key:
        raise AgyCanaryEvidenceError("Gemini seat key must be a nonempty canonical key")
    if capture_mode not in _CAPTURE_MODES:
        raise AgyCanaryEvidenceError("capture mode is not supported")
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
        "capture_mode": capture_mode,
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


def _parse_stream(
    data: bytes, *, require_staged_reads: bool = False
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
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


def verify_capture(*, evidence_root: Path, expected_seat_key: str) -> dict[str, Any]:
    """Strictly reduce all sealed attempts and reject incomplete/forged evidence."""
    root, root_fd = _validate_private_root(evidence_root)
    try:
        ledger = _read_json_at(root_fd, _LEDGER_NAME)
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
            if not isinstance(item, dict) or item.get("seat_key") != expected_seat_key:
                raise AgyCanaryEvidenceError("capture contains an unbound attempt")
            stream = item.get("stream")
            staged = item.get("staged")
            if not isinstance(stream, dict) or not isinstance(staged, dict):
                raise AgyCanaryEvidenceError("capture launch record is incomplete")
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
        proof = {
            "schema": SCHEMA_VERSION,
            "seat_key": expected_seat_key,
            "attempt_ids": [item["attempt_id"] for item in output_attempts],
            "capture_mode": mode,
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
    root, root_fd = _validate_private_root(evidence_root)
    try:
        version_proc = subprocess.run([agy_executable, "--version"], capture_output=True, text=True, timeout=15, check=False)
        help_proc = subprocess.run([agy_executable, "--help"], capture_output=True, text=True, timeout=15, check=False)
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
            agy_executable, "--output-format", "stream-json", "--sandbox", "--add-dir",
            "/run/phase-loop-review", "--print-timeout", "30s", "-p",
            "Read review-instructions.md and review-bundle.md only. Do not use any other tool. Reply with READY.",
        ]
        proc = subprocess.run(namespace.command(command), capture_output=True, text=True, timeout=90, check=False)
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


def bootstrap_attest(
    *, evidence_root: Path, dotfiles_repo: Path, bootstrap_command: tuple[str, ...] = ("bash", "bootstrap.sh")
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
    pin = (repo / "shared" / "agent-harness.pin").read_text(encoding="utf-8").strip()
    if pin != "v0.7.14":
        raise AgyCanaryEvidenceError("bootstrap attestation requires the v0.7.14 fleet pin")
    child_env = dict(os.environ)
    nonce = secrets.token_hex(24)
    child_env["PHASE_LOOP_AGY_CANARY_BOOTSTRAP_NONCE"] = nonce
    script_bytes = (repo / "bootstrap.sh").read_bytes()
    committed_script = subprocess.run(["git", "-C", str(repo), "show", "HEAD:bootstrap.sh"], capture_output=True, check=False)
    if committed_script.returncode != 0 or committed_script.stdout != script_bytes:
        raise AgyCanaryEvidenceError("bootstrap script bytes differ from committed HEAD")
    before = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True, timeout=30, check=False)
    child_process = subprocess.Popen(
        list(bootstrap_command), cwd=repo, env=child_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        _stdout, _stderr = child_process.communicate(timeout=1800)
    except subprocess.TimeoutExpired as exc:
        child_process.kill()
        child_process.communicate()
        raise AgyCanaryEvidenceError("direct bootstrap child timed out") from exc
    child_rc = child_process.returncode
    after = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True, timeout=30, check=False)
    if child_rc != 0:
        raise AgyCanaryEvidenceError("direct bootstrap child failed")
    installed = subprocess.run(["phase-loop", "version"], capture_output=True, text=True, timeout=30, check=False)
    installed_version = (installed.stdout or installed.stderr).strip()
    if installed.returncode != 0 or "0.7.14" not in installed_version:
        raise AgyCanaryEvidenceError("bootstrap did not install the expected phase-loop version")
    root, root_fd = _validate_private_root(evidence_root)
    try:
        value = {
            "schema": "agy_canary_bootstrap_attestation.v1",
            "repo_head": head.stdout.strip(),
            "blobs": identities,
            "nonce_sha256": _sha256(nonce.encode()),
            "bootstrap": {
                "argv": list(bootstrap_command),
                "pid": child_process.pid,
                "returncode": child_rc,
                "script_sha256": _sha256(script_bytes),
                "script_blob": identities["bootstrap.sh"],
                "before_uv_tools_sha256": _sha256((before.stdout or "").encode()),
                "after_uv_tools_sha256": _sha256((after.stdout or "").encode()),
                "environment_names": sorted(child_env),
                "installed_phase_loop_version_sha256": _sha256(installed_version.encode()),
            },
        }
        _exclusive_write_at(root_fd, "agy_canary_bootstrap_attestation.json", _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def prepare_canary(
    *, evidence_root: Path, settings_path: Path, seat_key: str, auth_paths: tuple[Path, ...] = ()
) -> dict[str, Any]:
    """Bind cleanup lineage and a positively complete capability probe before launch."""
    root, root_fd = _validate_private_root(evidence_root)
    try:
        cleanup = _read_json_at(root_fd, _CLEANUP_STATE_NAME)
        if cleanup.get("state") != "committed":
            raise AgyCanaryEvidenceError("settings cleanup has not committed")
        probe = _read_json_at(root_fd, _PROBE_NAME)
        if probe.get("complete") is not True or probe.get("mode") not in {"stream_json", "trajectory_store"}:
            raise AgyCanaryEvidenceError("capability probe has not selected a complete authority")
        bootstrap = _read_json_at(root_fd, "agy_canary_bootstrap_attestation.json")
        bootstrap_result = bootstrap.get("bootstrap")
        if not isinstance(bootstrap_result, dict) or bootstrap_result.get("returncode") != 0:
            raise AgyCanaryEvidenceError("direct bootstrap attestation is incomplete")
        capture = AgyCanaryCapture(root, root_fd)
        ledger = create_capture(
            capture=capture,
            settings_path=settings_path,
            seat_key=seat_key,
            capture_mode=str(probe["mode"]),
        )
        minimal_home, auth_binds = build_minimal_home(
            evidence_root=capture.root, settings_path=settings_path, auth_paths=auth_paths
        )
        ledger["minimal_home"] = str(minimal_home)
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
        value = {"schema": "agy_canary_prepare.v1", "cleanup_sha256": _sha256(_canonical_json(cleanup)), "probe_sha256": _sha256(_canonical_json(probe)), "bootstrap_sha256": _sha256(_canonical_json(bootstrap)), "ledger_sha256": _sha256(_canonical_json(ledger)), "seat_key": seat_key}
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
    resolver = Path("/etc/resolv.conf").resolve(strict=True)
    resolver_info = resolver.lstat()
    if stat.S_ISLNK(resolver_info.st_mode) or not stat.S_ISREG(resolver_info.st_mode):
        raise AgyCanaryEvidenceError("resolved resolver source is not regular")
    resolver_fd = os.open(resolver, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        resolver_bytes = b""
        while True:
            chunk = os.read(resolver_fd, 65536)
            if not chunk:
                break
            resolver_bytes += chunk
    finally:
        os.close(resolver_fd)
    return AgyCanaryNamespace(stage=stage, minimal_home=home, evidence_root=capture.root, provider_hostname=provider_hostname, auth_binds=tuple(auth_binds), resolver_source=resolver, resolver_sha256=_sha256(resolver_bytes))


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
    proof = verify_capture(evidence_root=evidence_root, expected_seat_key=expected_seat_key)
    if check_only and dotfiles_repo is None:
        return proof
    root, root_fd = _validate_private_root(evidence_root)
    try:
        completed_at = datetime.now(timezone.utc).isoformat()
        inputs = {"schema": "agy_canary_inputs.v1", "proof_sha256": _sha256(_canonical_json(proof)), "completed_at": completed_at}
        if dotfiles_repo is not None:
            repo = dotfiles_repo.resolve(strict=True)
            if plan_path is None or manifest_path is None or not plan_slug:
                raise AgyCanaryEvidenceError("tracked finalization requires repo, plan, manifest, and plan slug")
            plan = (repo / plan_path).resolve(strict=True)
            manifest = (repo / manifest_path).resolve(strict=True)
            if repo not in plan.parents or repo not in manifest.parents:
                raise AgyCanaryEvidenceError("finalizer targets must remain under the validated repository")
            plan_before = plan.read_bytes()
            if b"## Execution evidence" in plan_before:
                raise AgyCanaryEvidenceError("plan already has execution evidence")
            try:
                manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise AgyCanaryEvidenceError("manifest is not JSON") from exc
            entries = manifest_value.get("plans") if isinstance(manifest_value, dict) else None
            matches = [entry for entry in entries or [] if isinstance(entry, dict) and entry.get("slug") == plan_slug]
            if len(matches) != 1:
                raise AgyCanaryEvidenceError("finalizer could not identify one manifest plan")
            canonical_proof = _canonical_json(proof).decode()
            suffix = "\n## Execution evidence\n\n```json\n" + canonical_proof + "```\n"
            plan_after = plan_before + suffix.encode()
            matches[0]["updated_at"] = completed_at
            manifest_after = _canonical_json(manifest_value)
            inputs.update({
                "plan_before_sha256": _sha256(plan_before),
                "plan_after_sha256": _sha256(plan_after),
                "manifest_before_sha256": _sha256(manifest.read_bytes()),
                "manifest_after_sha256": _sha256(manifest_after),
            })
            if not check_only:
                _replace_regular_file(plan, plan_after)
                _replace_regular_file(manifest, manifest_after)
        _write_replace_at(root_fd, _INPUTS_NAME, inputs)
        return {**proof, "inputs_sha256": _sha256(_canonical_json(inputs))}
    finally:
        os.close(root_fd)
