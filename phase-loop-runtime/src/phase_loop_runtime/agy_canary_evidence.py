"""Fail-closed evidence helpers for the opt-in Antigravity canary."""

from __future__ import annotations

import base64
import configparser
import csv
import copy
import ctypes
import errno
import hashlib
import io
import json
import os
import posixpath
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.request
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

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
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2
_LEDGER_NAME = "agy-launch-ledger.json"
_PROBE_NAME = "agy_capability_probe.json"
_PREPARE_NAME = "agy_canary_prepare.json"
_LAUNCH_AUTHORITY_NAME = "agy_canary_launch_authority.json"
_STAGE_AUTHORITY_NAME = "agy_canary_stage_authority.json"
_STAGE_BINDING_NAME = "agy_canary_stage_binding.json"
_PROVIDER_REGISTRY_NAME = "agy_provider_launches.json"
_INPUTS_NAME = "agy_canary_inputs.json"
_REVIEW_INSTRUCTION_GENERATOR = "phase_loop_runtime.panel_invoker._resolve_brief.v1"
_SAFE_PRESETS = frozenset({"request-review", "strict"})
_CAPTURE_MODES = frozenset({"stream_json", "trajectory_store"})
_CAPABILITY_PROBE_SCHEMA = "agy_capability_probe.v2"
_MAX_FULL_STAGED_READ_BYTES = 256 * 1024
_CAPABILITY_CLASSES = (
    ("allowed_read", "read_file", "/run/phase-loop-review", "success"),
    ("allowed_write", "write_file", "/run/phase-loop-review/.agy-capability-write", "success"),
    ("command", "command", "true", "success"),
    ("unsandboxed", "unsandboxed", "true", "success"),
    ("inert_mcp", "mcp_call", "inert://constant-response", "success"),
    ("out_of_stage_read", "read_file", "/run/phase-loop-probe/out-of-stage-sentinel", "success"),
    ("read_url", "read_url", "http://127.0.0.1:8765/constant", "success"),
    ("execute_url", "execute_url", "http://127.0.0.1:8765/constant", "success"),
)
_FINAL_GOVERNANCE_POSTURE = {
    "external_attestation": "absent",
    "human_required": True,
    "blocker_class": "admin_approval",
}
_FINAL_ATTESTATION_KEYS = frozenset({
    "bootstrap", "release", "release_sha256", "wheel_binding_sha256",
    "installation", "installation_sha256", "proof", "reducer_proof_sha256",
    "completed_at", "manifest_after_sha256",
})
_FINAL_INPUT_KEYS = frozenset({
    "schema", "proof", "proof_sha256", "completed_at", "attestation",
    "plan_before_sha256", "plan_after_sha256", "manifest_before_sha256",
    "manifest_after_sha256", "plan", "manifest", "plan_slug",
    "plan_before_b64", "manifest_before_b64",
})
_PRIVATE_BOARD_RESERVED_NAMES = frozenset({
    _CLEANUP_STATE_NAME,
    _SETTINGS_SNAPSHOT_NAME,
    _LEDGER_NAME,
    _PROBE_NAME,
    _PREPARE_NAME,
    _LAUNCH_AUTHORITY_NAME,
    _STAGE_AUTHORITY_NAME,
    _STAGE_BINDING_NAME,
    _PROVIDER_REGISTRY_NAME,
    _INPUTS_NAME,
    "agy_canary_bootstrap_attestation.json",
    "agy_canary_proof.json",
})
_PRIVATE_BOARD_RESERVED_PREFIXES = (
    ".",
    "agy-provider-",
    "agy-stream-",
    "agy-diagnostic-",
    "agy-capability-",
    "staged-",
)
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


def _validate_provider_output(path: Path, *, evidence_root: Path) -> Path:
    """Open only a private host directory that may become the fixed child output mount."""
    if not path.is_absolute() or path.parent != Path("/tmp") or path == evidence_root:
        raise AgyCanaryEvidenceError("provider output must be a distinct direct absolute child of /tmp")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise AgyCanaryEvidenceError("provider output directory does not exist") from exc
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
            stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid()):
        raise AgyCanaryEvidenceError("provider output directory is not private")
    return path.resolve(strict=True)


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


def _agy_runtime_record(runtime: _TrustedAgyRuntime, version: str) -> dict[str, Any]:
    return {
        "path": str(runtime.source), "device": runtime.device, "inode": runtime.inode,
        "mode": runtime.mode, "sha256": runtime.sha256, "version": version,
    }


def _sealed_agy_runtime(value: Any) -> _TrustedAgyRuntime:
    if (not isinstance(value, dict) or set(value) != {"path", "device", "inode", "mode", "sha256", "version"} or
            not isinstance(value.get("path"), str) or not Path(value["path"]).is_absolute() or
            not all(_is_plain_int(value.get(name)) and value[name] >= 0 for name in ("device", "inode", "mode")) or
            not _is_digest(value.get("sha256")) or value.get("version") != "1.1.13"):
        raise AgyCanaryEvidenceError("capability probe agy runtime identity is malformed")
    return _TrustedAgyRuntime(
        Path(value["path"]), value["device"], value["inode"], value["mode"], value["sha256"],
    )


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


_PROVIDER_EXECUTABLES = {
    "gemini": "agy",
    "codex": "codex",
    "claude": "claude",
    "grok": "grok",
}
_CAPTURE_PROVIDERS = frozenset(_PROVIDER_EXECUTABLES)
_MAX_PROVIDER_REVIEW_ATTEMPTS = 2

# Account-local npm shims are intentionally *not* executable authorities: the
# capture namespace masks /home, and a shim can be repointed between discovery
# and launch.  These are the only accepted package roots for the locally
# installed subscription CLIs.  Each package is rebound at a fixed child path;
# neither ~/.npm-global/bin nor any other part of HOME is exposed to a child.
_NPM_PROVIDER_RUNTIMES = {
    "codex": (
        ".npm-global/bin/codex",
        ".npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex",
        ".npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl",
        "bin/codex",
    ),
    "claude": (
        ".npm-global/bin/claude",
        ".npm-global/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
        None,
        "",
    ),
    "grok": (".grok/bin/grok", ".grok/bin/grok-1.0.3", None, ""),  # model-id-source: provider CLI version path, not a model
}
_PROVIDER_AUTH_PATHS = {
    "codex": (".codex/auth.json", "/home/phase-loop/.codex/auth.json"),
    "claude": (".claude/.credentials.json", "/home/phase-loop/.claude/.credentials.json"),
    "grok": (".grok/auth.json", "/home/phase-loop/.grok/auth.json"),
}
_PROVIDER_STATUS_COMMANDS = {
    "codex": ("login", "status"),
    "claude": ("auth", "status"),
}
_PROVIDER_TLS_HOSTS = {
    "gemini": "antigravity.google",
    "codex": "chatgpt.com",
    "claude": "api.anthropic.com",
    "grok": "api.x.ai",
}
_PROVIDER_LAUNCHER_TARGETS = {
    "codex": "../lib/node_modules/@openai/codex/bin/codex.js",
    "grok": "grok-1.0.3",  # model-id-source: provider CLI version, not a model
}
_NATIVE_PROVIDER_ASSETS = {
    "codex": (
        "bin/codex",
        "bin/codex-code-mode-host",
        "codex-path/rg",
        "codex-resources/bwrap",
        "codex-package.json",
    ),
}


def _read_regular_path(path: Path) -> tuple[bytes, os.stat_result]:
    """Descriptor-read one absolute regular file without following a link."""
    if not path.is_absolute() or path.is_symlink():
        raise AgyCanaryEvidenceError("trusted runtime path is not a direct regular file")
    parent_fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        return _reopen_at(parent_fd, path.name)
    finally:
        os.close(parent_fd)


def _stable_file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
        info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _reopen_bounded_at(
    directory_fd: int, name: str, *, limit: int,
) -> tuple[bytes, os.stat_result]:
    fd = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=directory_fd,
    )
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise AgyCanaryEvidenceError(
                "provider launch file exceeds the full-read limit"
            )
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            chunk = os.read(fd, min(64 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(fd)
        if (total > limit or
                _stable_file_identity(after) != _stable_file_identity(before)):
            raise AgyCanaryEvidenceError(
                "provider launch file changed or exceeded the full-read limit"
            )
        return b"".join(chunks), after
    finally:
        os.close(fd)


def _tree_entry_identity(info: os.stat_result, *, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "dev": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": info.st_nlink,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _descriptor_tree_inventory(
    root: Path, *, content: bool = True,
) -> dict[str, Any]:
    """Inventory one exact nofollow tree through held directory descriptors."""
    if not root.is_absolute() or root.is_symlink():
        raise AgyCanaryEvidenceError("provider launch tree root is unsafe")
    try:
        root_before = root.lstat()
        root_fd = os.open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise AgyCanaryEvidenceError("provider launch tree is unavailable") from exc
    entries: list[dict[str, Any]] = []

    def walk(directory_fd: int, relative_parent: Path) -> None:
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as exc:
            raise AgyCanaryEvidenceError(
                "provider launch tree membership is unreadable"
            ) from exc
        for name in names:
            if not name or Path(name).name != name or name in {".", ".."}:
                raise AgyCanaryEvidenceError("provider launch tree entry is malformed")
            relative = (relative_parent / name).as_posix()
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise AgyCanaryEvidenceError(
                    "provider launch tree entry is unavailable"
                ) from exc
            if stat.S_ISLNK(before.st_mode):
                raise AgyCanaryEvidenceError("provider launch tree contains a symlink")
            if stat.S_ISDIR(before.st_mode):
                try:
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=directory_fd,
                    )
                except OSError as exc:
                    raise AgyCanaryEvidenceError(
                        "provider launch tree directory is unavailable"
                    ) from exc
                try:
                    opened = os.fstat(child_fd)
                    if _stable_file_identity(opened) != _stable_file_identity(before):
                        raise AgyCanaryEvidenceError(
                            "provider launch tree changed while inventorying"
                        )
                    entries.append({
                        "path": relative,
                        **_tree_entry_identity(opened, kind="directory"),
                    })
                    walk(child_fd, Path(relative))
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(before.st_mode):
                if content:
                    data, opened = _reopen_bounded_at(
                        directory_fd, name, limit=_MAX_FULL_STAGED_READ_BYTES,
                    )
                    if _stable_file_identity(opened) != _stable_file_identity(before):
                        raise AgyCanaryEvidenceError(
                            "provider launch tree changed while inventorying"
                        )
                    record = {
                        "path": relative,
                        **_tree_entry_identity(opened, kind="file"),
                        "bytes": len(data),
                        "sha256": _sha256(data),
                    }
                else:
                    record = {
                        "path": relative,
                        **_tree_entry_identity(before, kind="file"),
                    }
                entries.append(record)
            else:
                raise AgyCanaryEvidenceError(
                    "provider launch tree contains a special file"
                )
            try:
                after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise AgyCanaryEvidenceError(
                    "provider launch tree changed while inventorying"
                ) from exc
            if _stable_file_identity(after) != _stable_file_identity(before):
                raise AgyCanaryEvidenceError(
                    "provider launch tree changed while inventorying"
                )

    try:
        root_opened = os.fstat(root_fd)
        if (not stat.S_ISDIR(root_opened.st_mode) or
                _stable_file_identity(root_opened) !=
                _stable_file_identity(root_before)):
            raise AgyCanaryEvidenceError("provider launch tree root changed")
        walk(root_fd, Path())
        root_after = root.lstat()
        if (_stable_file_identity(root_after) !=
                _stable_file_identity(root_opened)):
            raise AgyCanaryEvidenceError("provider launch tree root changed")
    finally:
        os.close(root_fd)
    return {
        "schema": "agy_provider_launch_tree.v1",
        "root": str(root),
        "root_identity": _tree_entry_identity(root_opened, kind="directory"),
        "entries": entries,
    }


def _tree_inventory_metadata(value: dict[str, Any]) -> dict[str, Any]:
    projected = json.loads(json.dumps(value))
    for entry in projected["entries"]:
        entry.pop("bytes", None)
        entry.pop("sha256", None)
    return projected


def _exact_launch_tree_inventory(root: Path) -> dict[str, Any]:
    inventory = _descriptor_tree_inventory(root)
    if _tree_inventory_metadata(inventory) != _descriptor_tree_inventory(
        root, content=False,
    ):
        raise AgyCanaryEvidenceError(
            "provider launch tree changed during metadata revalidation"
        )
    return inventory


def _read_bounded_regular_path(
    path: Path, *, limit: int,
) -> tuple[bytes, os.stat_result]:
    """Descriptor-read at most limit + 1 bytes after a pre-read size gate."""
    if not path.is_absolute() or path.is_symlink():
        raise AgyCanaryEvidenceError("trusted runtime path is not a direct regular file")
    path_before = path.lstat()
    parent_fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise AgyCanaryEvidenceError("trusted regular file exceeds read limit")
            chunks: list[bytes] = []
            total = 0
            while total <= limit:
                chunk = os.read(fd, min(64 * 1024, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            after = os.fstat(fd)
            if (
                total > limit
                or after.st_size > limit
                or total != before.st_size
                or _stable_file_identity(path_before) != _stable_file_identity(before)
                or _stable_file_identity(after) != _stable_file_identity(before)
            ):
                raise AgyCanaryEvidenceError("trusted regular file exceeds read limit")
            data = b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)
    try:
        path_after = path.lstat()
    except OSError as exc:
        raise AgyCanaryEvidenceError("trusted regular file identity drifted") from exc
    if _stable_file_identity(path_after) != _stable_file_identity(after):
        raise AgyCanaryEvidenceError("trusted regular file identity drifted")
    return data, after


def _stat_regular_path(path: Path) -> os.stat_result:
    """Nofollow metadata check for a regular file without re-reading its bytes."""
    if not path.is_absolute() or path.is_symlink():
        raise AgyCanaryEvidenceError("trusted runtime path is not a direct regular file")
    parent_fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise AgyCanaryEvidenceError("trusted runtime path is not regular")
            return info
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _runtime_tree_metadata(root: Path) -> dict[str, tuple[str, tuple[int, ...]]]:
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise AgyCanaryEvidenceError("trusted provider package is unavailable") from exc
    if (
        stat.S_ISLNK(root_info.st_mode)
        or not stat.S_ISDIR(root_info.st_mode)
        or root_info.st_uid != os.getuid()
        or stat.S_IMODE(root_info.st_mode) & 0o002
    ):
        raise AgyCanaryEvidenceError("trusted provider package root is unsafe")
    identities = {".": ("directory", _stable_file_identity(root_info))}

    def walk_error(error: OSError) -> None:
        raise AgyCanaryEvidenceError(
            "trusted provider package metadata is unreadable"
        ) from error

    for current, directories, files in os.walk(
        root, topdown=True, onerror=walk_error, followlinks=False,
    ):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in [*directories, *files]:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            try:
                info = path.lstat()
            except OSError as exc:
                raise AgyCanaryEvidenceError(
                    "trusted provider package metadata is unreadable"
                ) from exc
            if stat.S_ISLNK(info.st_mode):
                raise AgyCanaryEvidenceError("trusted provider package contains a symlink")
            if stat.S_ISDIR(info.st_mode):
                if stat.S_IMODE(info.st_mode) & 0o002:
                    raise AgyCanaryEvidenceError(
                        "trusted provider package directory is unsafe"
                    )
                kind = "directory"
            elif stat.S_ISREG(info.st_mode) and not stat.S_IMODE(info.st_mode) & 0o002:
                kind = "file"
            else:
                raise AgyCanaryEvidenceError(
                    "trusted provider package contains an unsafe file"
                )
            identities[relative] = (kind, _stable_file_identity(info))
    return identities


def _runtime_tree_snapshot(
    root: Path, *, capture_relatives: frozenset[str] = frozenset(),
) -> tuple[str, dict[str, tuple[bytes, os.stat_result]]]:
    """Hash one package traversal and retain only explicitly requested files."""
    try:
        root_info = root.lstat()
    except FileNotFoundError as exc:
        raise AgyCanaryEvidenceError("trusted provider package is unavailable") from exc
    if (stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode) or
            root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) & 0o002):
        raise AgyCanaryEvidenceError("trusted provider package root is unsafe")
    digest = hashlib.sha256()
    captured: dict[str, tuple[bytes, os.stat_result]] = {}
    identities = {".": ("directory", _stable_file_identity(root_info))}

    def walk_error(error: OSError) -> None:
        raise AgyCanaryEvidenceError(
            "trusted provider package content is unreadable"
        ) from error

    for current, directories, files in os.walk(
        root, topdown=True, onerror=walk_error, followlinks=False,
    ):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in [*directories, *files]:
            path = current_path / name
            relative_text = path.relative_to(root).as_posix()
            relative = relative_text.encode()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise AgyCanaryEvidenceError("trusted provider package contains a symlink")
            digest.update(relative + b"\0" + format(stat.S_IMODE(info.st_mode), "04o").encode() + b"\0")
            if stat.S_ISDIR(info.st_mode):
                if stat.S_IMODE(info.st_mode) & 0o002:
                    raise AgyCanaryEvidenceError("trusted provider package directory is unsafe")
                identities[relative_text] = (
                    "directory", _stable_file_identity(info),
                )
                continue
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o002:
                raise AgyCanaryEvidenceError("trusted provider package contains an unsafe file")
            data, reopened = _read_regular_path(path)
            if _stable_file_identity(reopened) != _stable_file_identity(info):
                raise AgyCanaryEvidenceError("trusted provider package changed while hashing")
            identities[relative_text] = ("file", _stable_file_identity(reopened))
            digest.update(data)
            if relative_text in capture_relatives:
                captured[relative_text] = (data, reopened)
    if set(captured) != set(capture_relatives):
        raise AgyCanaryEvidenceError("trusted provider package entry is unavailable")
    if _runtime_tree_metadata(root) != identities:
        raise AgyCanaryEvidenceError(
            "trusted provider package changed during metadata revalidation"
        )
    return digest.hexdigest(), captured


def _runtime_tree_sha256(root: Path) -> str:
    """Hash the exact runnable package tree and reject links/special files."""
    return _runtime_tree_snapshot(root)[0]


def _trusted_node_runtime() -> tuple[Path, int, int, int, str]:
    node = Path("/usr/bin/node")
    try:
        data, info = _read_regular_path(node)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("trusted node runtime is unavailable") from exc
    if (not os.access(node, os.X_OK) or stat.S_IMODE(info.st_mode) & 0o022 or
            info.st_uid != 0):
        raise AgyCanaryEvidenceError("trusted node runtime is unsafe")
    return node, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), _sha256(data)


@dataclass(frozen=True)
class _TrustedProviderRuntime:
    """An executable identity resolved independently from HOME and PATH."""

    provider: str
    source: Path
    device: int
    inode: int
    mode: int
    sha256: str
    support_source: Path | None = None
    support_device: int | None = None
    support_inode: int | None = None
    support_mode: int | None = None
    support_sha256: str | None = None
    entry_relative: str = ""
    node_source: Path | None = None
    node_device: int | None = None
    node_inode: int | None = None
    node_mode: int | None = None
    node_sha256: str | None = None
    launcher: Path | None = None
    launcher_target: str | None = None

    @property
    def destination(self) -> str:
        return f"/run/phase-loop-bin/{_PROVIDER_EXECUTABLES[self.provider]}"

    def revalidate(self, *, full_assets: bool = False) -> None:
        try:
            info = _stat_regular_path(self.source)
        except (FileNotFoundError, OSError) as exc:
            raise AgyCanaryEvidenceError(
                f"trusted {self.provider} executable drifted before namespace launch"
            ) from exc
        if ((info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)) !=
                (self.device, self.inode, self.mode)):
            raise AgyCanaryEvidenceError(f"trusted {self.provider} executable drifted before namespace launch")
        if (full_assets and self.support_source is None and
                _sha256(_read_regular_path(self.source)[0]) != self.sha256):
            raise AgyCanaryEvidenceError(
                f"trusted {self.provider} executable drifted before namespace launch"
            )
        if self.launcher is not None:
            try:
                launcher_info = self.launcher.lstat()
            except FileNotFoundError as exc:
                raise AgyCanaryEvidenceError(
                    f"trusted {self.provider} launcher drifted before namespace launch"
                ) from exc
            if (not stat.S_ISLNK(launcher_info.st_mode) or
                    os.readlink(self.launcher) != self.launcher_target or
                    (self.support_source is None and
                     self.launcher.resolve(strict=True) != self.source)):
                raise AgyCanaryEvidenceError(
                    f"trusted {self.provider} launcher drifted before namespace launch"
                )
        if self.support_source is not None:
            info = self.support_source.lstat()
            if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
                    (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)) !=
                    (self.support_device, self.support_inode, self.support_mode)):
                raise AgyCanaryEvidenceError(
                    f"trusted {self.provider} package drifted before namespace launch"
                )
            if full_assets:
                expected_source = self.support_source / self.entry_relative
                if self.source != expected_source:
                    raise AgyCanaryEvidenceError(
                        f"trusted {self.provider} executable drifted before namespace launch"
                    )
                tree_sha256, captured = _runtime_tree_snapshot(
                    self.support_source,
                    capture_relatives=frozenset({self.entry_relative}),
                )
                entry_data, entry_info = captured[self.entry_relative]
                if ((entry_info.st_dev, entry_info.st_ino,
                     stat.S_IMODE(entry_info.st_mode)) !=
                        (self.device, self.inode, self.mode) or
                        _sha256(entry_data) != self.sha256):
                    raise AgyCanaryEvidenceError(
                        f"trusted {self.provider} executable drifted before namespace launch"
                    )
                if tree_sha256 != self.support_sha256:
                    raise AgyCanaryEvidenceError(
                        f"trusted {self.provider} package drifted before namespace launch"
                    )
        if self.node_source is not None:
            info = _stat_regular_path(self.node_source)
            if ((info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)) !=
                    (self.node_device, self.node_inode, self.node_mode) or
                    (full_assets and
                     _sha256(_read_regular_path(self.node_source)[0]) != self.node_sha256)):
                raise AgyCanaryEvidenceError("trusted node runtime drifted before namespace launch")

    def runtime_binds(self) -> tuple[tuple[Path, str], ...]:
        return ((self.support_source, self.destination),) if self.support_source else ((self.source, self.destination),)

    def child_argv(self, arguments: list[str]) -> list[str]:
        target = str(Path(self.destination) / self.entry_relative) if self.entry_relative else self.destination
        if self.node_source is not None:
            return [str(self.node_source), target, *arguments]
        return [target, *arguments]


def _trusted_provider_runtime(provider: str) -> _TrustedProviderRuntime:
    """Resolve a supported provider only from account/system-owned locations."""
    executable = _PROVIDER_EXECUTABLES.get(provider)
    if executable is None:
        raise AgyCanaryEvidenceError("provider launch authority is unsupported")
    npm_spec = _NPM_PROVIDER_RUNTIMES.get(provider)
    if npm_spec is not None:
        launcher_relative, source_relative, support_relative, entry_relative = npm_spec
        home = _account_home()
        launcher = home / launcher_relative
        source = home / source_relative
        support = home / support_relative if support_relative is not None else None
        try:
            launcher_info = launcher.lstat()
            support_info = support.lstat() if support is not None else None
            if support is None:
                data, info = _read_regular_path(source)
                support_sha256 = None
            else:
                capture_relatives = frozenset({
                    entry_relative, "codex-package.json",
                    *_NATIVE_PROVIDER_ASSETS.get(provider, ()),
                })
                support_sha256, captured = _runtime_tree_snapshot(
                    support, capture_relatives=capture_relatives,
                )
                data, info = captured[entry_relative]
        except (FileNotFoundError, OSError) as exc:
            raise AgyCanaryEvidenceError(f"trusted {provider} native runtime is unavailable") from exc
        launcher_target = os.readlink(launcher) if stat.S_ISLNK(launcher_info.st_mode) else None
        if (not stat.S_ISLNK(launcher_info.st_mode) or not launcher_target or
                (provider in _PROVIDER_LAUNCHER_TARGETS and
                 launcher_target != _PROVIDER_LAUNCHER_TARGETS[provider]) or
                not os.access(source, os.X_OK) or
                stat.S_IMODE(info.st_mode) & 0o002 or info.st_uid != os.getuid() or
                (support_info is not None and
                 (stat.S_ISLNK(support_info.st_mode) or not stat.S_ISDIR(support_info.st_mode)))):
            raise AgyCanaryEvidenceError(f"trusted {provider} native runtime is unsafe")
        if support is not None:
            for relative in _NATIVE_PROVIDER_ASSETS.get(provider, ()):
                _asset_data, asset_info = captured[relative]
                if stat.S_IMODE(asset_info.st_mode) & 0o002 or asset_info.st_uid != os.getuid():
                    raise AgyCanaryEvidenceError(f"trusted {provider} native asset is unsafe")
            try:
                package = json.loads(_read_regular_path(support.parent.parent / "package.json")[0])
                native_package = json.loads(captured["codex-package.json"][0])
            except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                raise AgyCanaryEvidenceError("trusted Codex package provenance is unavailable") from exc
            if (package.get("name") != "@openai/codex" or
                    not isinstance(package.get("version"), str) or
                    package["version"] != f"{native_package.get('version')}-linux-x64"):
                raise AgyCanaryEvidenceError("trusted Codex package provenance drifted")
        if provider == "grok":
            try:
                version = json.loads(_read_regular_path(home / ".grok" / "version.json")[0])
            except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                raise AgyCanaryEvidenceError("trusted Grok version provenance is unavailable") from exc
            if version.get("version") != source.name.removeprefix("grok-"):
                raise AgyCanaryEvidenceError("trusted Grok version provenance drifted")
        return _TrustedProviderRuntime(
            provider, source, info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
            _sha256(data), support,
            support_info.st_dev if support_info is not None else None,
            support_info.st_ino if support_info is not None else None,
            stat.S_IMODE(support_info.st_mode) if support_info is not None else None,
            support_sha256,
            entry_relative, None, None, None, None, None, launcher, launcher_target,
        )
    candidates = (
        _account_home() / ".local" / "bin" / executable,
        Path("/usr/local/bin") / executable,
        Path("/usr/bin") / executable,
    )
    for source in candidates:
        try:
            info = source.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
                not os.access(source, os.X_OK) or stat.S_IMODE(info.st_mode) & 0o022 or
                info.st_uid not in {0, os.getuid()}):
            raise AgyCanaryEvidenceError(f"trusted {provider} executable is unsafe")
        return _TrustedProviderRuntime(
            provider=provider, source=source, device=info.st_dev, inode=info.st_ino,
            mode=stat.S_IMODE(info.st_mode), sha256=_sha256(source.read_bytes()),
        )
    raise AgyCanaryEvidenceError(f"trusted {provider} executable is unavailable")


@dataclass(frozen=True)
class _OpenedSettings:
    fd: int
    parent_fd: int
    name: str
    data: bytes
    mode: int
    device: int
    inode: int
    uid: int
    gid: int


@dataclass
class _FinalTarget:
    parent_fd: int
    name: str
    data: bytes
    replacement: bytes
    mode: int
    device: int
    inode: int
    temporary: str | None = None
    exchanged: bool = False


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
class _OwnedCleanupRoot:
    path: Path
    kind: str
    prefix: str
    device: int
    inode: int
    uid: int
    gid: int
    quarantine_token: str


_OWNED_CLEANUP_PREFIXES = {
    "provider_output": "phase-loop-provider-output-",
    "scratch": "pl-panel-capture-",
}
_OWNED_CLEANUP_QUARANTINE_PREFIX = ".phase-loop-cleaned-"


def _seal_owned_cleanup_root(
    path: Path, *, kind: str, quarantine_token: str | None = None,
) -> _OwnedCleanupRoot:
    """Seal one internally created private /tmp root before it is populated."""
    return _owned_cleanup_root_authority(
        path, kind=kind, quarantine_token=quarantine_token,
    )


def _owned_cleanup_root_authority(
    path: Path, *, kind: str, quarantine_token: str | None = None,
) -> _OwnedCleanupRoot:
    """Authenticate one newly-created cleanup root without mutating it."""
    prefix = _OWNED_CLEANUP_PREFIXES.get(kind)
    if (prefix is None or not path.is_absolute() or path.parent != Path("/tmp") or
            not path.name.startswith(prefix) or path.name == prefix):
        raise AgyCanaryEvidenceError("cleanup root must be a direct child of /tmp")
    try:
        info = path.lstat()
    except OSError as exc:
        raise AgyCanaryEvidenceError("cleanup root is unavailable") from exc
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
            info.st_uid != os.getuid() or info.st_gid != os.getgid() or
            stat.S_IMODE(info.st_mode) != 0o700):
        raise AgyCanaryEvidenceError("cleanup root is not one private owned directory")
    token = quarantine_token or secrets.token_hex(16)
    if re.fullmatch(r"[0-9a-f]{32}", token) is None:
        raise AgyCanaryEvidenceError("cleanup quarantine token is malformed")
    return _OwnedCleanupRoot(
        path=path, kind=kind, prefix=prefix,
        device=info.st_dev, inode=info.st_ino,
        uid=info.st_uid, gid=info.st_gid,
        quarantine_token=token,
    )


def _create_owned_cleanup_root(*, kind: str) -> tuple[Path, _OwnedCleanupRoot]:
    """Create and seal one root, reclaiming it on any authorization failure."""
    prefix = _OWNED_CLEANUP_PREFIXES.get(kind)
    if prefix is None:
        raise AgyCanaryEvidenceError("cleanup root kind is unsupported")
    path = Path(tempfile.mkdtemp(prefix=prefix, dir="/tmp"))
    authority: _OwnedCleanupRoot | None = None
    try:
        authority = _owned_cleanup_root_authority(path, kind=kind)
        path.chmod(0o700)
        sealed = _seal_owned_cleanup_root(
            path, kind=kind,
            quarantine_token=authority.quarantine_token,
        )
        if sealed != authority:
            raise AgyCanaryEvidenceError(
                "cleanup root identity drifted during creation"
            )
        return path, sealed
    except Exception as primary:
        if authority is not None:
            try:
                _cleanup_owned_roots((authority,))
            except Exception as cleanup_error:
                raise cleanup_error from primary
        raise


def _cleanup_owned_roots(roots: Sequence[_OwnedCleanupRoot]) -> None:
    """Remove public roots and retain only validated empty /tmp tombstones."""
    errors: list[str] = []
    seen: set[tuple[str, str, int, int, str]] = set()
    for authority in roots:
        key = (
            authority.kind, str(authority.path),
            authority.device, authority.inode, authority.quarantine_token,
        )
        if key in seen:
            continue
        seen.add(key)
        path = authority.path
        try:
            if (authority.prefix != _OWNED_CLEANUP_PREFIXES.get(authority.kind) or
                    path.parent != Path("/tmp") or
                    not path.name.startswith(authority.prefix) or
                    path.name == authority.prefix or
                    re.fullmatch(
                        r"[0-9a-f]{32}", authority.quarantine_token,
                    ) is None):
                raise AgyCanaryEvidenceError("cleanup root authority is malformed")
            tmp_before = Path("/tmp").lstat()
            tmp_fd = os.open(
                "/tmp",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                tmp_opened = os.fstat(tmp_fd)
                if (not stat.S_ISDIR(tmp_opened.st_mode) or tmp_opened.st_uid != 0 or
                        stat.S_IMODE(tmp_opened.st_mode) != 0o1777 or
                        (tmp_opened.st_dev, tmp_opened.st_ino,
                         tmp_opened.st_mode, tmp_opened.st_uid,
                         tmp_opened.st_gid) !=
                        (tmp_before.st_dev, tmp_before.st_ino,
                         tmp_before.st_mode, tmp_before.st_uid,
                         tmp_before.st_gid)):
                    raise AgyCanaryEvidenceError(
                        "trusted /tmp cleanup parent is unsafe"
                    )
                try:
                    entry = os.stat(
                        path.name, dir_fd=tmp_fd, follow_symlinks=False,
                    )
                except FileNotFoundError:
                    quarantine_name = _find_owned_cleanup_tombstone(
                        tmp_fd=tmp_fd, authority=authority,
                    )
                    _validate_owned_cleanup_descendant_tombstones(
                        tmp_fd=tmp_fd, authority=authority,
                    )
                    _validate_owned_cleanup_tombstone(
                        tmp_fd=tmp_fd,
                        name=quarantine_name,
                        authority=authority,
                    )
                    try:
                        os.stat(
                            path.name, dir_fd=tmp_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        pass
                    else:
                        raise AgyCanaryEvidenceError(
                            "cleanup public root name was recreated"
                        )
                    continue
                if (stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode) or
                        (entry.st_dev, entry.st_ino, entry.st_uid, entry.st_gid) !=
                        (authority.device, authority.inode,
                         authority.uid, authority.gid)):
                    raise AgyCanaryEvidenceError("cleanup root identity drifted")
                anchor_fd = os.open(
                    path.name,
                    os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=tmp_fd,
                )
                try:
                    anchored = os.fstat(anchor_fd)
                    if ((anchored.st_dev, anchored.st_ino, anchored.st_uid,
                         anchored.st_gid) !=
                            (authority.device, authority.inode,
                             authority.uid, authority.gid)):
                        raise AgyCanaryEvidenceError(
                            "cleanup root anchor identity drifted"
                        )
                    _chmod_owned_cleanup_directory(
                        anchor_fd, uid=authority.uid, gid=authority.gid,
                    )
                    root_fd = os.open(
                        path.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                        os.O_CLOEXEC,
                        dir_fd=tmp_fd,
                    )
                    try:
                        opened = os.fstat(root_fd)
                        if ((opened.st_dev, opened.st_ino, opened.st_uid,
                             opened.st_gid) !=
                                (anchored.st_dev, anchored.st_ino,
                                 anchored.st_uid, anchored.st_gid)):
                            raise AgyCanaryEvidenceError(
                                "cleanup root descriptor identity drifted"
                            )
                        quarantine_name = _quarantine_owned_cleanup_root(
                            tmp_fd=tmp_fd,
                            public_name=path.name,
                            authority=authority,
                            anchored=opened,
                        )
                        _quarantine_owned_cleanup_entries(
                            root_fd, tmp_fd=tmp_fd, authority=authority,
                        )
                        _validate_owned_cleanup_tombstone(
                            tmp_fd=tmp_fd,
                            name=quarantine_name,
                            authority=authority,
                        )
                        _validate_owned_cleanup_descendant_tombstones(
                            tmp_fd=tmp_fd, authority=authority,
                        )
                        _validate_owned_cleanup_tombstone(
                            tmp_fd=tmp_fd,
                            name=quarantine_name,
                            authority=authority,
                        )
                        try:
                            os.stat(
                                path.name, dir_fd=tmp_fd,
                                follow_symlinks=False,
                            )
                        except FileNotFoundError:
                            pass
                        else:
                            raise AgyCanaryEvidenceError(
                                "cleanup public root name was recreated"
                            )
                    finally:
                        os.close(root_fd)
                finally:
                    os.close(anchor_fd)
            finally:
                os.close(tmp_fd)
        except Exception as exc:
            errors.append(f"{path.name}:{type(exc).__name__}")
    if errors:
        raise AgyCanaryEvidenceError(
            "capture resource cleanup was incomplete: " + ",".join(errors)
        )


def _find_owned_cleanup_tombstone(
    *, tmp_fd: int, authority: _OwnedCleanupRoot,
) -> str:
    """Find exactly one canonical empty tombstone for an absent public root."""
    expected = (
        f"{_OWNED_CLEANUP_QUARANTINE_PREFIX}{authority.kind}-"
        f"{authority.quarantine_token}"
    )
    matches: list[str] = []
    for name in os.listdir(tmp_fd):
        if not name.startswith(_OWNED_CLEANUP_QUARANTINE_PREFIX):
            continue
        try:
            entry = os.stat(name, dir_fd=tmp_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if ((entry.st_dev, entry.st_ino, entry.st_uid, entry.st_gid) !=
                (authority.device, authority.inode,
                 authority.uid, authority.gid)):
            continue
        if name != expected:
            raise AgyCanaryEvidenceError(
                "cleanup tombstone name is malformed"
            )
        matches.append(name)
    if len(matches) != 1:
        raise AgyCanaryEvidenceError(
            "cleanup tombstone cardinality is invalid"
        )
    _validate_owned_cleanup_tombstone(
        tmp_fd=tmp_fd, name=matches[0], authority=authority,
    )
    return matches[0]


def _validate_owned_cleanup_tombstone(
    *, tmp_fd: int, name: str, authority: _OwnedCleanupRoot,
) -> None:
    """Validate one empty tombstone through a held no-follow descriptor."""
    try:
        entry = os.stat(name, dir_fd=tmp_fd, follow_symlinks=False)
        tombstone_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=tmp_fd,
        )
    except OSError as exc:
        raise AgyCanaryEvidenceError(
            "cleanup tombstone is unavailable"
        ) from exc
    try:
        opened = os.fstat(tombstone_fd)
        expected_authority = (
            authority.device, authority.inode, authority.uid, authority.gid,
        )
        stable = _cleanup_tombstone_stat_identity(opened)
        first_entries = os.listdir(tombstone_fd)
        first_after = os.fstat(tombstone_fd)
        after_entry = os.stat(
            name, dir_fd=tmp_fd, follow_symlinks=False,
        )
        second_entries = os.listdir(tombstone_fd)
        second_after = os.fstat(tombstone_fd)
        final_entry = os.stat(
            name, dir_fd=tmp_fd, follow_symlinks=False,
        )
        if (not stat.S_ISDIR(entry.st_mode) or
                not stat.S_ISDIR(opened.st_mode) or
                (entry.st_dev, entry.st_ino, entry.st_uid, entry.st_gid) !=
                expected_authority or
                (opened.st_dev, opened.st_ino,
                 opened.st_uid, opened.st_gid) != expected_authority or
                stat.S_IMODE(entry.st_mode) != 0o700 or
                stat.S_IMODE(opened.st_mode) != 0o700 or
                entry.st_nlink != 2 or opened.st_nlink != 2 or
                first_entries or second_entries or
                any(
                    _cleanup_tombstone_stat_identity(info) != stable
                    for info in (
                        entry, first_after, after_entry,
                        second_after, final_entry,
                    )
                )):
            raise AgyCanaryEvidenceError(
                "cleanup tombstone authority is invalid"
            )
    finally:
        os.close(tombstone_fd)


def _cleanup_tombstone_stat_identity(info: os.stat_result) -> tuple[int, ...]:
    """Return full stable metadata used across tombstone validation passes."""
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
        info.st_uid, info.st_gid, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def _quarantine_owned_cleanup_root(
    *, tmp_fd: int, public_name: str, authority: _OwnedCleanupRoot,
    anchored: os.stat_result,
) -> str:
    """Atomically move one held root out of service without deleting its name."""
    quarantine_name = (
        f"{_OWNED_CLEANUP_QUARANTINE_PREFIX}{authority.kind}-"
        f"{authority.quarantine_token}"
    )
    _rename_noreplace(
        tmp_fd, public_name, tmp_fd, quarantine_name,
    )
    moved = os.stat(
        quarantine_name, dir_fd=tmp_fd, follow_symlinks=False,
    )
    if (not stat.S_ISDIR(moved.st_mode) or
            (moved.st_dev, moved.st_ino, moved.st_uid, moved.st_gid) !=
            (anchored.st_dev, anchored.st_ino, anchored.st_uid,
             anchored.st_gid)):
        raise AgyCanaryEvidenceError(
            "cleanup quarantine does not contain the held root"
        )
    try:
        os.stat(public_name, dir_fd=tmp_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise AgyCanaryEvidenceError(
            "cleanup public root remained after quarantine"
        )
    return quarantine_name


def _quarantine_owned_cleanup_entries(
    directory_fd: int, *, tmp_fd: int, authority: _OwnedCleanupRoot,
) -> None:
    """Quarantine and sanitize entries without deleting substitutable names."""
    for name in sorted(os.listdir(directory_fd)):
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (entry.st_uid, entry.st_gid) != (authority.uid, authority.gid):
            raise AgyCanaryEvidenceError("cleanup entry ownership drifted")
        if stat.S_ISLNK(entry.st_mode):
            raise AgyCanaryEvidenceError(
                "cleanup symlink cannot be sanitized safely"
            )
        elif stat.S_ISREG(entry.st_mode):
            if entry.st_nlink != 1:
                raise AgyCanaryEvidenceError("cleanup regular file is hard-linked")
            anchor_fd = os.open(
                name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            try:
                anchored = os.fstat(anchor_fd)
                if (not stat.S_ISREG(anchored.st_mode) or
                        anchored.st_nlink != 1 or
                        (anchored.st_dev, anchored.st_ino,
                         anchored.st_uid, anchored.st_gid) !=
                        (entry.st_dev, entry.st_ino,
                         entry.st_uid, entry.st_gid)):
                    raise AgyCanaryEvidenceError(
                        "cleanup regular file anchor drifted"
                    )
                os.chmod(f"/proc/self/fd/{anchor_fd}", 0o600)
                file_fd = os.open(
                    name, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
                try:
                    opened = os.fstat(file_fd)
                    if (not stat.S_ISREG(opened.st_mode) or
                            opened.st_nlink != 1 or
                            (opened.st_dev, opened.st_ino,
                             opened.st_uid, opened.st_gid) !=
                            (anchored.st_dev, anchored.st_ino,
                             anchored.st_uid, anchored.st_gid)):
                        raise AgyCanaryEvidenceError(
                            "cleanup regular file identity drifted"
                        )
                    os.ftruncate(file_fd, 0)
                    os.fsync(file_fd)
                    sanitized = os.fstat(file_fd)
                    quarantine_name = _quarantine_owned_cleanup_entry(
                        source_fd=directory_fd, source_name=name,
                        tmp_fd=tmp_fd, authority=authority,
                        kind="file", expected=sanitized,
                    )
                    moved = os.stat(
                        quarantine_name, dir_fd=tmp_fd,
                        follow_symlinks=False,
                    )
                    if (not stat.S_ISREG(moved.st_mode) or
                            moved.st_nlink != 1 or moved.st_size != 0 or
                            stat.S_IMODE(moved.st_mode) != 0o600 or
                            _cleanup_entry_stat_identity(moved) !=
                            _cleanup_entry_stat_identity(os.fstat(file_fd))):
                        raise AgyCanaryEvidenceError(
                            "cleanup file tombstone is invalid"
                        )
                finally:
                    os.close(file_fd)
            finally:
                os.close(anchor_fd)
        elif stat.S_ISDIR(entry.st_mode):
            anchor_fd = os.open(
                name,
                os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            try:
                anchored = os.fstat(anchor_fd)
                if ((anchored.st_dev, anchored.st_ino, anchored.st_uid,
                     anchored.st_gid) !=
                        (entry.st_dev, entry.st_ino, entry.st_uid,
                         entry.st_gid)):
                    raise AgyCanaryEvidenceError(
                        "cleanup directory anchor drifted"
                    )
                _chmod_owned_cleanup_directory(
                    anchor_fd, uid=authority.uid, gid=authority.gid,
                )
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                    os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
                try:
                    opened = os.fstat(child_fd)
                    if ((opened.st_dev, opened.st_ino, opened.st_uid,
                         opened.st_gid) !=
                            (anchored.st_dev, anchored.st_ino,
                             anchored.st_uid, anchored.st_gid)):
                        raise AgyCanaryEvidenceError(
                            "cleanup directory identity drifted"
                        )
                    quarantine_name = _quarantine_owned_cleanup_entry(
                        source_fd=directory_fd, source_name=name,
                        tmp_fd=tmp_fd, authority=authority,
                        kind="directory", expected=opened,
                    )
                    _quarantine_owned_cleanup_entries(
                        child_fd, tmp_fd=tmp_fd, authority=authority,
                    )
                    final_entry = os.stat(
                        quarantine_name, dir_fd=tmp_fd,
                        follow_symlinks=False,
                    )
                    if (not stat.S_ISDIR(final_entry.st_mode) or
                            (final_entry.st_dev, final_entry.st_ino,
                             final_entry.st_uid, final_entry.st_gid) !=
                            (opened.st_dev, opened.st_ino,
                             opened.st_uid, opened.st_gid) or
                            stat.S_IMODE(final_entry.st_mode) != 0o700 or
                            final_entry.st_nlink != 2 or os.listdir(child_fd)):
                        raise AgyCanaryEvidenceError(
                            "cleanup directory tombstone is invalid"
                        )
                finally:
                    os.close(child_fd)
            finally:
                os.close(anchor_fd)
        else:
            raise AgyCanaryEvidenceError("cleanup root contains a special file")


def _quarantine_owned_cleanup_entry(
    *, source_fd: int, source_name: str, tmp_fd: int,
    authority: _OwnedCleanupRoot, kind: str, expected: os.stat_result,
) -> str:
    """Move one descendant atomically and verify the moved inode before use."""
    quarantine_name = (
        f"{_OWNED_CLEANUP_QUARANTINE_PREFIX}entry-"
        f"{authority.quarantine_token}-{kind}-{secrets.token_hex(8)}"
    )
    _rename_noreplace(
        source_fd, source_name, tmp_fd, quarantine_name,
    )
    moved = os.stat(
        quarantine_name, dir_fd=tmp_fd, follow_symlinks=False,
    )
    if _cleanup_entry_stat_identity(moved) != _cleanup_entry_stat_identity(expected):
        raise AgyCanaryEvidenceError(
            "cleanup descendant quarantine identity drifted"
        )
    try:
        os.stat(source_name, dir_fd=source_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise AgyCanaryEvidenceError(
            "cleanup descendant public name was recreated"
        )
    return quarantine_name


def _cleanup_entry_stat_identity(info: os.stat_result) -> tuple[int, ...]:
    """Return stable descendant metadata unaffected by an in-parent rename."""
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
        info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns,
    )


def _validate_owned_cleanup_descendant_tombstones(
    *, tmp_fd: int, authority: _OwnedCleanupRoot,
) -> None:
    """Require two identical full traversals of all descendant tombstones."""
    first = _owned_cleanup_descendant_tombstone_inventory(
        tmp_fd=tmp_fd, authority=authority,
    )
    second = _owned_cleanup_descendant_tombstone_inventory(
        tmp_fd=tmp_fd, authority=authority,
    )
    if first != second:
        raise AgyCanaryEvidenceError(
            "cleanup descendant tombstone inventory drifted"
        )


def _owned_cleanup_descendant_tombstone_inventory(
    *, tmp_fd: int, authority: _OwnedCleanupRoot,
) -> tuple[tuple[str, str, tuple[int, ...]], ...]:
    """Traverse token-bound tombstones and return their canonical inventory."""
    prefix = (
        f"{_OWNED_CLEANUP_QUARANTINE_PREFIX}entry-"
        f"{authority.quarantine_token}-"
    )
    inventory: list[tuple[str, str, tuple[int, ...]]] = []
    for name in sorted(os.listdir(tmp_fd)):
        if not name.startswith(prefix):
            continue
        match = re.fullmatch(
            re.escape(prefix) + r"(file|directory)-[0-9a-f]{16}", name,
        )
        if match is None:
            raise AgyCanaryEvidenceError(
                "cleanup descendant tombstone name is malformed"
            )
        entry = os.stat(name, dir_fd=tmp_fd, follow_symlinks=False)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        if match.group(1) == "directory":
            flags |= os.O_DIRECTORY
        opened_fd = os.open(name, flags, dir_fd=tmp_fd)
        try:
            opened = os.fstat(opened_fd)
            stable = _cleanup_tombstone_stat_identity(opened)
            if match.group(1) == "directory":
                first_content = os.listdir(opened_fd)
                first_after = os.fstat(opened_fd)
                after_entry = os.stat(
                    name, dir_fd=tmp_fd, follow_symlinks=False,
                )
                second_content = os.listdir(opened_fd)
            else:
                first_content = os.read(opened_fd, 1)
                first_after = os.fstat(opened_fd)
                after_entry = os.stat(
                    name, dir_fd=tmp_fd, follow_symlinks=False,
                )
                second_content = os.read(opened_fd, 1)
            second_after = os.fstat(opened_fd)
            final_entry = os.stat(
                name, dir_fd=tmp_fd, follow_symlinks=False,
            )
            expected_kind = (
                stat.S_ISDIR if match.group(1) == "directory"
                else stat.S_ISREG
            )
            expected_mode = 0o700 if match.group(1) == "directory" else 0o600
            expected_nlink = 2 if match.group(1) == "directory" else 1
            if (not expected_kind(entry.st_mode) or
                    not expected_kind(opened.st_mode) or
                    (entry.st_uid, entry.st_gid) !=
                    (authority.uid, authority.gid) or
                    (opened.st_uid, opened.st_gid) !=
                    (authority.uid, authority.gid) or
                    stat.S_IMODE(entry.st_mode) != expected_mode or
                    stat.S_IMODE(opened.st_mode) != expected_mode or
                    entry.st_nlink != expected_nlink or
                    opened.st_nlink != expected_nlink or
                    (match.group(1) == "file" and
                     (entry.st_size != 0 or opened.st_size != 0)) or
                    first_content or second_content or
                    any(
                        _cleanup_tombstone_stat_identity(info) != stable
                        for info in (
                            entry, first_after, after_entry,
                            second_after, final_entry,
                        )
                    )):
                raise AgyCanaryEvidenceError(
                    "cleanup descendant tombstone is invalid"
                )
            inventory.append((name, match.group(1), stable))
        finally:
            os.close(opened_fd)
    return tuple(inventory)


def _chmod_owned_cleanup_directory(anchor_fd: int, *, uid: int, gid: int) -> None:
    """Repair one directory through its held O_PATH descriptor, never its name."""
    before = os.fstat(anchor_fd)
    if (not stat.S_ISDIR(before.st_mode) or
            (before.st_uid, before.st_gid) != (uid, gid)):
        raise AgyCanaryEvidenceError("cleanup directory ownership drifted")
    os.chmod(f"/proc/self/fd/{anchor_fd}", 0o700)
    after = os.fstat(anchor_fd)
    if ((after.st_dev, after.st_ino, after.st_uid, after.st_gid) !=
            (before.st_dev, before.st_ino, before.st_uid, before.st_gid) or
            not stat.S_ISDIR(after.st_mode) or
            stat.S_IMODE(after.st_mode) != 0o700):
        raise AgyCanaryEvidenceError("cleanup directory chmod authority drifted")


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
    provider_output: Path | None = None
    provider_output_cleanup: _OwnedCleanupRoot | None = None
    writable_stage: bool = False
    fixture_binds: tuple[tuple[Path, str], ...] = ()
    provider_env: tuple[tuple[str, str], ...] = ()
    agy_runtime: _TrustedAgyRuntime | None = None

    def outer_environment(self) -> dict[str, str]:
        """Minimal host environment for bwrap itself; never carry loader/runtime overrides."""
        return {name: os.environ[name] for name in ("LANG", "LC_ALL", "LC_CTYPE") if name in os.environ} | {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        }

    def agy_command(self, argv: list[str]) -> list[str]:
        if not argv or argv[0] != "agy":
            raise AgyCanaryEvidenceError("namespace agy command must start with agy")
        runtime = self.agy_runtime or _trusted_agy_runtime()
        return self.command([runtime.destination, *argv[1:]], agy_runtime=runtime)

    def rewrite_provider_output_path(self, host_path: Path) -> str:
        """Translate a validated private host-output descendant to its fixed child path."""
        if self.provider_output is None:
            raise AgyCanaryEvidenceError("provider output mapping is not configured")
        output = _validate_provider_output(self.provider_output, evidence_root=self.evidence_root)
        if not host_path.is_absolute() or host_path.is_symlink():
            raise AgyCanaryEvidenceError("provider output path must be an absolute non-symlink")
        try:
            relative = host_path.relative_to(output)
        except ValueError as exc:
            raise AgyCanaryEvidenceError("provider output path escapes its private root") from exc
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise AgyCanaryEvidenceError("provider output path is not a file descendant")
        return str(Path("/run/phase-loop-output") / relative)

    def command(
        self,
        argv: list[str],
        *,
        agy_runtime: _TrustedAgyRuntime | None = None,
        runtime_binds: tuple[tuple[Path, str], ...] = (),
    ) -> list[str]:
        bwrap = _canonical_bwrap()
        if not self.stage.is_absolute() or not self.minimal_home.is_absolute():
            raise AgyCanaryEvidenceError("namespace inputs must be absolute")
        # `/tmp` and `/run` are fresh tmpfs mounts.  Thus the direct `/tmp` child
        # holding evidence is absent even though the immutable host filesystem is
        # mounted read-only for the provider executable and CA roots.
        command = [
            str(bwrap),
            "--die-with-parent",
            "--new-session",
            "--unshare-pid",
            "--clearenv",
            "--ro-bind", "/", "/",
            "--tmpfs", "/tmp",
            "--tmpfs", "/run",
            "--proc", "/proc",
            "--dev", "/dev",
            "--dir", "/run/phase-loop-review",
            "--bind" if self.writable_stage else "--ro-bind", str(self.stage), "/run/phase-loop-review",
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
        for name, value in self.provider_env:
            if name not in {"CODEX_HOME", "GROK_HOME"} or not value.startswith("/home/phase-loop/"):
                raise AgyCanaryEvidenceError("provider namespace environment is invalid")
            command.extend(["--setenv", name, value])
        if self.provider_output is not None:
            output = _validate_provider_output(self.provider_output, evidence_root=self.evidence_root)
            command.extend(["--dir", "/run/phase-loop-output", "--bind", str(output), "/run/phase-loop-output"])
        for source, destination in self.fixture_binds:
            if (not source.is_absolute() or source.is_symlink() or not destination.startswith("/run/phase-loop-")):
                raise AgyCanaryEvidenceError("capability fixture bind is invalid")
            parent = Path(destination).parent
            command.extend(["--dir", str(parent), "--ro-bind", str(source), destination])
        if agy_runtime is not None:
            agy_runtime.revalidate()
            command.extend(["--dir", "/run/phase-loop-bin", "--ro-bind", str(agy_runtime.source), agy_runtime.destination])
        for source, destination in runtime_binds:
            if (not source.is_absolute() or source.is_symlink() or
                    not destination.startswith("/run/phase-loop-bin/") or
                    Path(destination).parent != Path("/run/phase-loop-bin")):
                raise AgyCanaryEvidenceError("provider runtime bind is invalid")
            command.extend(["--dir", "/run/phase-loop-bin", "--ro-bind", str(source), destination])
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


def _provider_launch_identity(
    command: list[str], *, provider: str,
) -> dict[str, Any]:
    raw = "\0".join(command).encode()
    normalized = list(command)
    if provider == "gemini" and normalized:
        normalized[-1] = "<prompt>"
    return {
        "argv_bytes": len(raw),
        "argv_sha256": _sha256(raw),
        "normalized_argv_sha256": _sha256("\0".join(normalized).encode()),
    }


def _provider_runtime_record(runtime: _TrustedProviderRuntime) -> dict[str, Any]:
    return {
        "schema": "agy_provider_runtime.v1",
        "provider": runtime.provider,
        "source": str(runtime.source),
        "device": runtime.device,
        "inode": runtime.inode,
        "mode": runtime.mode,
        "sha256": runtime.sha256,
        "support_source": str(runtime.support_source) if runtime.support_source else None,
        "support_device": runtime.support_device,
        "support_inode": runtime.support_inode,
        "support_mode": runtime.support_mode,
        "support_sha256": runtime.support_sha256,
        "entry_relative": runtime.entry_relative,
        "node_source": str(runtime.node_source) if runtime.node_source else None,
        "node_device": runtime.node_device,
        "node_inode": runtime.node_inode,
        "node_mode": runtime.node_mode,
        "node_sha256": runtime.node_sha256,
        "launcher": str(runtime.launcher) if runtime.launcher else None,
        "launcher_target": runtime.launcher_target,
        "destination": runtime.destination,
    }


def _validate_provider_runtime_record(
    value: Any, *, provider: str,
) -> dict[str, Any]:
    required = {
        "schema", "provider", "source", "device", "inode", "mode", "sha256",
        "support_source", "support_device", "support_inode", "support_mode",
        "support_sha256", "entry_relative", "node_source", "node_device",
        "node_inode", "node_mode", "node_sha256", "launcher",
        "launcher_target", "destination",
    }
    if (not isinstance(value, dict) or set(value) != required or
            value.get("schema") != "agy_provider_runtime.v1" or
            value.get("provider") != provider or
            not isinstance(value.get("source"), str) or
            not Path(value["source"]).is_absolute() or
            any(not _is_plain_int(value.get(name)) or value[name] < 0
                for name in ("device", "inode", "mode")) or
            not _is_digest(value.get("sha256")) or
            not isinstance(value.get("entry_relative"), str) or
            Path(value["entry_relative"]).is_absolute() or
            ".." in Path(value["entry_relative"]).parts or
            value.get("destination") !=
            f"/run/phase-loop-bin/{_PROVIDER_EXECUTABLES[provider]}"):
        raise AgyCanaryEvidenceError("provider runtime authority is malformed")
    for prefix in ("support", "node"):
        path = value[f"{prefix}_source"]
        facts = [
            value[f"{prefix}_device"], value[f"{prefix}_inode"],
            value[f"{prefix}_mode"], value[f"{prefix}_sha256"],
        ]
        if path is None:
            if any(item is not None for item in facts):
                raise AgyCanaryEvidenceError(
                    "provider runtime authority is malformed"
                )
        elif (not isinstance(path, str) or not Path(path).is_absolute() or
                any(not _is_plain_int(item) or item < 0 for item in facts[:3]) or
                not _is_digest(facts[3])):
            raise AgyCanaryEvidenceError("provider runtime authority is malformed")
    launcher = value["launcher"]
    launcher_target = value["launcher_target"]
    if ((launcher is None) != (launcher_target is None) or
            (launcher is not None and (
                not isinstance(launcher, str) or not Path(launcher).is_absolute() or
                not isinstance(launcher_target, str) or not launcher_target
            ))):
        raise AgyCanaryEvidenceError("provider runtime authority is malformed")
    return value


@dataclass(frozen=True)
class ProviderLaunchAuthority:
    """A provider-neutral, immutable launch surface for one captured leg.

    The object deliberately exposes neither credential bytes nor host HOME.  A
    caller receives only a fixed child executable path, a descriptor-backed
    output reader, and the namespace's already-minimal outer environment.
    """

    provider: str
    runtime: _TrustedProviderRuntime
    namespace: AgyCanaryNamespace
    auth_records: tuple[dict[str, str], ...]
    auth_records_sha256: str
    customization_sources: dict[str, Any]
    customization_sources_sha256: str
    minimal_customizations: dict[str, Any]
    minimal_customizations_sha256: str
    auth_placeholders: tuple[dict[str, Any], ...]
    auth_placeholders_sha256: str
    projected_auth: dict[str, Any] | None = None
    stage_inventory: dict[str, Any] | None = None
    minimal_home_inventory: dict[str, Any] | None = None
    review_launch: dict[str, Any] | None = dataclass_field(default=None, compare=False)
    review_attempts: list[dict[str, Any]] = dataclass_field(default_factory=list, compare=False)
    _runtime_record_bytes: bytes = dataclass_field(init=False, repr=False, compare=False)
    _stage_inventory_bytes: bytes = dataclass_field(init=False, repr=False, compare=False)
    _minimal_home_inventory_bytes: bytes = dataclass_field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        record = _validate_provider_runtime_record(
            _provider_runtime_record(self.runtime), provider=self.provider,
        )
        object.__setattr__(self, "_runtime_record_bytes", _canonical_json(record))
        stage_inventory = self.stage_inventory or _exact_launch_tree_inventory(
            self.namespace.stage
        )
        minimal_home_inventory = (
            self.minimal_home_inventory or
            _exact_launch_tree_inventory(self.namespace.minimal_home)
        )
        if (stage_inventory.get("root") != str(self.namespace.stage) or
                minimal_home_inventory.get("root") !=
                str(self.namespace.minimal_home)):
            raise AgyCanaryEvidenceError(
                f"{self.provider} provider filesystem authority is malformed"
            )
        object.__setattr__(self, "stage_inventory", stage_inventory)
        object.__setattr__(self, "minimal_home_inventory", minimal_home_inventory)
        object.__setattr__(
            self, "_stage_inventory_bytes", _canonical_json(stage_inventory),
        )
        object.__setattr__(
            self, "_minimal_home_inventory_bytes",
            _canonical_json(minimal_home_inventory),
        )

    def _revalidate_filesystems(self) -> None:
        if (self.stage_inventory is None or self.minimal_home_inventory is None or
                _canonical_json(self.stage_inventory) !=
                self._stage_inventory_bytes or
                _canonical_json(self.minimal_home_inventory) !=
                self._minimal_home_inventory_bytes):
            raise AgyCanaryEvidenceError(
                f"{self.provider} in-memory launch authority drifted"
            )
        if (_canonical_json(_exact_launch_tree_inventory(self.namespace.stage)) !=
                self._stage_inventory_bytes or
                _canonical_json(_exact_launch_tree_inventory(
                    self.namespace.minimal_home
                )) != self._minimal_home_inventory_bytes):
            raise AgyCanaryEvidenceError(
                f"{self.provider} provider filesystem authority drifted"
            )

    def _revalidate(self, *, full_assets: bool = False) -> None:
        sealed_values = (
            (self.auth_records, self.auth_records_sha256),
            (self.customization_sources, self.customization_sources_sha256),
            (self.minimal_customizations, self.minimal_customizations_sha256),
            (self.auth_placeholders, self.auth_placeholders_sha256),
        )
        if any(
            not _is_digest(expected) or
            _sha256(_canonical_json(value)) != expected
            for value, expected in sealed_values
        ):
            raise AgyCanaryEvidenceError(
                f"{self.provider} in-memory launch authority drifted"
            )
        if self._runtime_record_bytes != _canonical_json(
            _provider_runtime_record(self.runtime)
        ):
            raise AgyCanaryEvidenceError(
                f"{self.provider} in-memory launch authority drifted"
            )
        self._revalidate_filesystems()
        self.runtime.revalidate(full_assets=full_assets)
        _revalidate_customization_source_authority(self.customization_sources)
        revalidate_customization_inventory(
            self.minimal_customizations,
            home=self.namespace.minimal_home,
            project_dir=self.namespace.stage,
            env={},
        )
        if _auth_placeholder_authority(
            minimal_home=self.namespace.minimal_home,
            records=self.auth_records,
        ) != self.auth_placeholders:
            raise AgyCanaryEvidenceError(
                f"{self.provider} authentication bind target drifted"
            )
        for record in self.auth_records:
            source = Path(record["source"])
            parent_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                data, info = _reopen_at(parent_fd, source.name)
            finally:
                os.close(parent_fd)
            if (not stat.S_ISREG(info.st_mode) or _sha256(data) != record["source_sha256"] or
                    ("uid" in record and str(info.st_uid) != record["uid"]) or
                    ("mode" in record and format(stat.S_IMODE(info.st_mode), "04o") != record["mode"])):
                raise AgyCanaryEvidenceError(f"{self.provider} authentication bind drifted")

    def _command(self, argv: list[str], *, full_assets: bool) -> list[str]:
        if not argv or argv[0] != _PROVIDER_EXECUTABLES[self.provider]:
            raise AgyCanaryEvidenceError("provider authority command has the wrong executable")
        self._revalidate(full_assets=full_assets)
        return self.namespace.command(
            self.runtime.child_argv(argv[1:]), runtime_binds=self.runtime.runtime_binds()
        )

    def command(self, argv: list[str]) -> list[str]:
        """Build a standalone launch command from freshly hashed provider assets."""
        return self._command(argv, full_assets=True)

    def outer_environment(self) -> dict[str, str]:
        return self.namespace.outer_environment()

    def rewrite_provider_output_path(self, host_path: Path) -> str:
        return self.namespace.rewrite_provider_output_path(host_path)

    def self_test(self) -> dict[str, Any]:
        self._revalidate()
        return namespace_self_test(namespace=self.namespace)

    def preflight(self, argv: list[str]) -> list[str]:
        """Run the namespace visibility check immediately before returning argv."""
        # The namespace self-test does not execute the provider runtime.  Each
        # provider probe below uses ``command`` and therefore hashes all mounted
        # assets exactly once immediately before its subprocess boundary.
        self._revalidate()
        namespace_self_test(namespace=self.namespace)
        checks = [("version", ["--version"])]
        if self.provider in _PROVIDER_STATUS_COMMANDS:
            checks.append(("authentication", list(_PROVIDER_STATUS_COMMANDS[self.provider])))
        for label, arguments in checks:
            proc = subprocess.run(
                self.command([_PROVIDER_EXECUTABLES[self.provider], *arguments]),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=self.outer_environment(),
            )
            if proc.returncode != 0:
                raise AgyCanaryEvidenceError(
                    f"{self.provider} {label} preflight failed inside capture namespace"
                )
        # The review subprocess has not started yet.  Build its immutable argv
        # after a cheap identity check; ``record_review_attempt`` performs the
        # full byte revalidation immediately before every actual attempt/retry.
        command = self._command(argv, full_assets=False)
        launch = _provider_launch_identity(command, provider=self.provider)
        if self.review_launch is None:
            object.__setattr__(self, "review_launch", launch)
        elif self.review_launch != launch:
            raise AgyCanaryEvidenceError("provider authority review command drifted")
        return command

    def record_review_attempt(
        self, command: list[str], *, attempt_id: str | None = None,
    ) -> None:
        """Bind one actual preflight-wrapped review attempt in execution order."""
        # This is the per-subprocess boundary: retries reuse the preflight argv,
        # but must never reuse a runtime or projected credential that changed
        # after an earlier attempt.  Full bytes are read every time; the remaining
        # same-UID race is only the narrow interval after this read and before the
        # kernel consumes the already-built read-only mount argv.
        self._revalidate(full_assets=True)
        launch = _provider_launch_identity(command, provider=self.provider)
        if self.review_launch != launch:
            raise AgyCanaryEvidenceError("provider review attempt was not preflight-authorized")
        if len(self.review_attempts) >= _MAX_PROVIDER_REVIEW_ATTEMPTS:
            raise AgyCanaryEvidenceError("provider review attempt limit exceeded")
        expected_id = f"{self.provider}-{len(self.review_attempts) + 1}"
        if attempt_id is None:
            attempt_id = expected_id
        if attempt_id != expected_id:
            raise AgyCanaryEvidenceError("provider review attempt identity is not exact")
        self.review_attempts.append({
            "index": len(self.review_attempts), "attempt_id": attempt_id, **launch,
        })

    def review_attempt_proof(self) -> dict[str, Any]:
        """Return the exact preflight command and each actual invocation."""
        if self.review_launch is None:
            return {"launch": None, "attempts": [], "terminal_attempt": None}
        attempts = [dict(item) for item in self.review_attempts]
        if any(
            item != {
                "index": index,
                "attempt_id": f"{self.provider}-{index + 1}",
                **self.review_launch,
            }
            for index, item in enumerate(attempts)
        ):
            raise AgyCanaryEvidenceError("provider review attempt proof drifted")
        return {
            "launch": dict(self.review_launch),
            "attempts": attempts,
            "terminal_attempt": len(attempts) - 1 if attempts else None,
        }

    def runtime_authority(self) -> dict[str, Any]:
        # Registry/result bookkeeping consumes the immutable record frozen when
        # the authority was prepared.  Only cheap path identity is revalidated
        # here; full bytes are reserved for actual provider subprocess boundaries.
        self.runtime.revalidate()
        expected = _canonical_json(_provider_runtime_record(self.runtime))
        if self._runtime_record_bytes != expected:
            raise AgyCanaryEvidenceError(
                f"{self.provider} in-memory launch authority drifted"
            )
        try:
            record = json.loads(self._runtime_record_bytes)
        except json.JSONDecodeError as exc:
            raise AgyCanaryEvidenceError(
                f"{self.provider} frozen runtime authority is malformed"
            ) from exc
        return _validate_provider_runtime_record(record, provider=self.provider)

    def auth_placeholder_proof(self) -> list[dict[str, Any]]:
        self._revalidate()
        return [dict(item) for item in self.auth_placeholders]

    def read_expected_output(self, name: str) -> bytes:
        """Read one exact nofollow regular output; reject sibling output artifacts."""
        if not name or Path(name).name != name or self.namespace.provider_output is None:
            raise AgyCanaryEvidenceError("provider output name is invalid")
        output = _validate_provider_output(self.namespace.provider_output, evidence_root=self.namespace.evidence_root)
        directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            entries = sorted(os.listdir(directory_fd))
            if entries != [name]:
                raise AgyCanaryEvidenceError("provider output set is not exact")
            data, info = _reopen_at(directory_fd, name)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise AgyCanaryEvidenceError("provider output is not one private regular file")
            return data
        finally:
            os.close(directory_fd)

    def projected_auth_proof(self) -> dict[str, Any]:
        """Return the launch-time projected credential identity, not a login claim."""
        if self.projected_auth is None:
            return _projected_auth_proof(
                provider=self.provider, runtime=self.runtime, records=self.auth_records
            )
        _validate_projected_auth_proof(
            proof=self.projected_auth, provider=self.provider, runtime=self.runtime,
            records=self.auth_records,
        )
        return self.projected_auth

    def write_expected_output(self, name: str, data: bytes) -> bytes:
        """Materialize exactly one parent-owned provider output without a path race.

        This is for provider CLIs which can only emit their final response on
        stdout.  The caller must supply bytes captured by the parent; the child
        never receives a writable evidence path.  A pre-existing name, a link,
        or any sibling makes the capture ambiguous and is rejected.
        """
        if (not name or Path(name).name != name or not isinstance(data, bytes) or
                self.namespace.provider_output is None):
            raise AgyCanaryEvidenceError("provider output write is invalid")
        output = _validate_provider_output(
            self.namespace.provider_output, evidence_root=self.namespace.evidence_root
        )
        directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if os.listdir(directory_fd):
                raise AgyCanaryEvidenceError("provider output set is not empty")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            try:
                file_fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
            except FileExistsError as exc:
                raise AgyCanaryEvidenceError("provider output already exists") from exc
            try:
                view = memoryview(data)
                while view:
                    written = os.write(file_fd, view)
                    if written <= 0:
                        raise AgyCanaryEvidenceError("provider output short write")
                    view = view[written:]
                os.fsync(file_fd)
                info = os.fstat(file_fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        stat.S_IMODE(info.st_mode) != 0o600):
                    raise AgyCanaryEvidenceError("provider output is not one private regular file")
            finally:
                os.close(file_fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return self.read_expected_output(name)


def _provider_auth_records(provider: str, minimal_home: Path) -> tuple[dict[str, str], ...]:
    """Freeze only the provider's declared credential file and empty bind target."""
    if provider == "gemini":
        return ()
    source_relative, destination = _PROVIDER_AUTH_PATHS[provider]
    source = _account_home() / source_relative
    try:
        data, info = _read_regular_path(source)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError(
            f"{provider} authentication source is unavailable"
        ) from exc
    if stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid():
        raise AgyCanaryEvidenceError(f"{provider} authentication source is unsafe")
    child_relative = Path(destination).relative_to("/home/phase-loop")
    target = minimal_home / child_relative
    try:
        target_data, target_info = _read_regular_path(target)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError(
            f"{provider} authentication bind target is unavailable"
        ) from exc
    if (target_data or target_info.st_nlink != 1 or
            stat.S_IMODE(target_info.st_mode) != 0o600 or
            target_info.st_uid != os.getuid()):
        raise AgyCanaryEvidenceError(
            f"{provider} authentication bind target is unsafe"
        )
    return ({
        "source": str(source), "destination": destination, "source_sha256": _sha256(data),
        "uid": str(info.st_uid), "mode": format(stat.S_IMODE(info.st_mode), "04o"),
    },)


def _projected_auth_proof(
    *, provider: str, runtime: _TrustedProviderRuntime, records: tuple[dict[str, str], ...]
) -> dict[str, Any]:
    """Freeze projected credential file facts without asserting semantic login."""
    rows: list[dict[str, str]] = []
    for record in records:
        source = Path(record["source"])
        parent_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            data, info = _reopen_at(parent_fd, source.name)
        finally:
            os.close(parent_fd)
        if (_sha256(data) != record["source_sha256"] or
                ("uid" in record and str(info.st_uid) != record["uid"]) or
                ("mode" in record and format(stat.S_IMODE(info.st_mode), "04o") != record["mode"])):
            raise AgyCanaryEvidenceError("provider projected authentication source drifted")
        rows.append({
            "destination": record["destination"], "uid": str(info.st_uid),
            "mode": format(stat.S_IMODE(info.st_mode), "04o"), "sha256": _sha256(data),
        })
    proof = {
        "schema": "agy_provider_projected_auth.v1", "provider": provider,
        "runtime_destination": runtime.destination, "runtime_sha256": runtime.sha256,
        "records": rows,
    }
    _validate_projected_auth_proof(
        proof=proof, provider=provider, runtime=runtime, records=records
    )
    return proof


def _validate_projected_auth_proof(
    *, proof: Any, provider: str, runtime: _TrustedProviderRuntime,
    records: tuple[dict[str, str], ...],
) -> None:
    if (not isinstance(proof, dict) or
            set(proof) != {"schema", "provider", "runtime_destination", "runtime_sha256", "records"} or
            proof.get("schema") != "agy_provider_projected_auth.v1" or
            proof.get("provider") != provider or proof.get("runtime_destination") != runtime.destination or
            proof.get("runtime_sha256") != runtime.sha256 or not isinstance(proof.get("records"), list) or
            len(proof["records"]) != len(records)):
        raise AgyCanaryEvidenceError("provider projected authentication proof is malformed")
    for row, record in zip(proof["records"], records, strict=True):
        if (not isinstance(row, dict) or set(row) != {"destination", "uid", "mode", "sha256"} or
                row.get("destination") != record.get("destination") or
                row.get("uid") != record.get("uid") or row.get("mode") != record.get("mode") or
                row.get("sha256") != record.get("source_sha256")):
            raise AgyCanaryEvidenceError("provider projected authentication record is malformed")


def prepare_provider_launch_authorities(
    *, capture: AgyCanaryCapture, stage: Path, providers: tuple[str, ...]
) -> dict[str, ProviderLaunchAuthority]:
    """Prepare fixed namespace authorities for every requested provider.

    This is intentionally the sole cross-provider handoff used by the panel
    runtime.  It never falls back to PATH, ambient HOME, or copied credentials.
    """
    if not providers or len(set(providers)) != len(providers):
        raise AgyCanaryEvidenceError("provider authority set is missing or duplicated")
    _ledger, _prepare, authority = _require_prepare_authority(capture=capture)
    stage_binding = _validate_stage_binding(
        capture=capture, review_dir=stage, authority=authority,
    )
    stage_inventory = _exact_launch_tree_inventory(stage)
    _validate_provider_stage_inventory(stage_inventory, binding=stage_binding)
    minimal_home = Path(str(authority["minimal_home"]["path"]))
    minimal_home_identity = _minimal_home_identity(minimal_home)
    if minimal_home_identity != authority["minimal_home"]["identity"]:
        raise AgyCanaryEvidenceError("prepared minimal HOME settings drifted")
    minimal_home_inventory = minimal_home_identity["tree"]
    customization_sources = authority["customization_sources"]
    _revalidate_customization_source_authority(customization_sources)
    minimal_customizations = freeze_customization_inventory(
        home=minimal_home, project_dir=stage, env={},
    )
    gemini_auth_records = tuple(authority["auth_binds"])
    resolver, resolver_sha256 = _resolver_snapshot()
    agy_runtime = _sealed_agy_runtime(authority["agy_runtime"])
    result: dict[str, ProviderLaunchAuthority] = {}
    provider_outputs: list[_OwnedCleanupRoot] = []
    for provider in providers:
        try:
            runtime = (_TrustedProviderRuntime(
                "gemini", agy_runtime.source, agy_runtime.device, agy_runtime.inode,
                agy_runtime.mode, agy_runtime.sha256,
            ) if provider == "gemini" else _trusted_provider_runtime(provider))
            auth_records = gemini_auth_records if provider == "gemini" else _provider_auth_records(provider, minimal_home)
            provider_output, provider_output_cleanup = _create_owned_cleanup_root(
                kind="provider_output",
            )
            provider_outputs.append(provider_output_cleanup)
            namespace = AgyCanaryNamespace(
                stage=stage, minimal_home=minimal_home, evidence_root=capture.root,
                provider_hostname=_PROVIDER_TLS_HOSTS[provider], auth_binds=tuple(
                    (Path(item["source"]), item["destination"]) for item in auth_records
                ), resolver_source=resolver, resolver_sha256=resolver_sha256,
                provider_output=provider_output,
                provider_output_cleanup=provider_output_cleanup,
                provider_env=(("CODEX_HOME", "/home/phase-loop/.codex"),) if provider == "codex" else (("GROK_HOME", "/home/phase-loop/.grok"),) if provider == "grok" else (),
            )
            frozen_records = tuple(auth_records)
            placeholders = _auth_placeholder_authority(
                minimal_home=minimal_home, records=frozen_records,
            )
            result[provider] = ProviderLaunchAuthority(
                provider=provider,
                runtime=runtime,
                namespace=namespace,
                auth_records=frozen_records,
                auth_records_sha256=_sha256(_canonical_json(frozen_records)),
                customization_sources=customization_sources,
                customization_sources_sha256=_sha256(
                    _canonical_json(customization_sources)
                ),
                minimal_customizations=minimal_customizations,
                minimal_customizations_sha256=_sha256(
                    _canonical_json(minimal_customizations)
                ),
                auth_placeholders=placeholders,
                auth_placeholders_sha256=_sha256(
                    _canonical_json(placeholders)
                ),
                projected_auth=_projected_auth_proof(
                    provider=provider, runtime=runtime, records=frozen_records,
                ),
                stage_inventory=stage_inventory,
                minimal_home_inventory=minimal_home_inventory,
            )
        except Exception as primary:
            try:
                _cleanup_owned_roots(provider_outputs)
            except Exception as cleanup_error:
                raise cleanup_error from primary
            raise
    return result


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _require_prepare_authority(
    *, capture: AgyCanaryCapture
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Reopen the one immutable prepare receipt required by every launch path."""
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    authority = _read_json_at(capture.root_fd, _LAUNCH_AUTHORITY_NAME)
    prepare = _read_json_at(capture.root_fd, _PREPARE_NAME)
    required = {
        "schema", "authority_name", "authority_sha256", "cleanup_sha256",
        "probe_sha256", "bootstrap_sha256", "ledger_sha256", "settings_sha256",
        "settings_bytes", "settings_mode", "seat_key", "release", "release_sha256",
        "wheel_binding_sha256", "installation_sha256", "source_inventory_sha256",
    }
    if (not isinstance(prepare, dict) or set(prepare) != required or
            prepare.get("schema") != "agy_canary_prepare.v1" or
            prepare.get("authority_name") != _LAUNCH_AUTHORITY_NAME or
            prepare.get("authority_sha256") != _sha256(_canonical_json(authority))):
        raise AgyCanaryEvidenceError("capture requires the exact prepare receipt")
    _validate_launch_authority(authority=authority, ledger=ledger, root_fd=capture.root_fd)
    expected = {
        "cleanup_sha256": authority["cleanup_sha256"],
        "probe_sha256": authority["probe_sha256"],
        "bootstrap_sha256": authority["bootstrap_sha256"],
        "settings_sha256": authority["settings"]["sha256"],
        "settings_bytes": authority["settings"]["bytes"],
        "settings_mode": authority["settings"]["mode"],
        "seat_key": authority["seat_key"],
        "release": authority["release"],
        "release_sha256": authority["release_sha256"],
        "wheel_binding_sha256": authority["wheel_binding_sha256"],
        "installation_sha256": authority["installation_sha256"],
        "source_inventory_sha256": authority["source_inventory_sha256"],
    }
    if any(prepare.get(name) != value for name, value in expected.items()):
        raise AgyCanaryEvidenceError("prepare receipt does not match immutable launch authority")
    # The ledger subsequently receives attempts.  Its prepare-time hash is bound
    # by the authority's immutable fields and can never be accepted as a mutable
    # current-ledger claim.
    if not _is_digest(prepare.get("ledger_sha256")):
        raise AgyCanaryEvidenceError("prepare receipt ledger identity is malformed")
    return ledger, prepare, authority


def bind_staged_review_inputs(
    *, capture: AgyCanaryCapture, review_dir: Path, bundle_bytes: bytes,
    instruction_bytes: bytes, generator_identity: str,
) -> dict[str, Any]:
    """Seal the parent-rendered review files to the bootstrap-attested plan.

    The board runner supplies the bytes it rendered, then this function
    descriptor-reopens the staged files and rejects a substituted bundle, plan,
    instruction text, or generator identity before any provider authority exists.
    """
    _ledger, prepare, authority = _require_prepare_authority(capture=capture)
    if (not isinstance(bundle_bytes, bytes) or not bundle_bytes or
            not isinstance(instruction_bytes, bytes) or not instruction_bytes or
            generator_identity != _REVIEW_INSTRUCTION_GENERATOR):
        raise AgyCanaryEvidenceError("staged review binding inputs are not canonical")
    bootstrap = _validate_bootstrap_attestation(
        receipt=_read_json_at(capture.root_fd, "agy_canary_bootstrap_attestation.json")
    )
    if _sha256(_canonical_json(bootstrap)) != authority["bootstrap_sha256"]:
        raise AgyCanaryEvidenceError("staged review binding bootstrap receipt drifted")
    targets = bootstrap.get("targets")
    inputs = bootstrap.get("input_sha256")
    if (not isinstance(targets, dict) or not isinstance(inputs, dict) or
            not isinstance(targets.get("plan"), str) or
            not _is_digest(inputs.get(targets["plan"])) or
            _sha256(bundle_bytes) != inputs[targets["plan"]]):
        raise AgyCanaryEvidenceError("staged review bundle is not the bootstrap-attested plan")
    review_fd = os.open(review_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if sorted(os.listdir(review_fd)) != [
            "review-bundle.md", "review-instructions.md",
        ]:
            raise AgyCanaryEvidenceError("staged review file set is not exact")
        staged: dict[str, dict[str, Any]] = {}
        for name, expected in (
            ("review-bundle.md", bundle_bytes),
            ("review-instructions.md", instruction_bytes),
        ):
            data, info = _reopen_at(review_fd, name)
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or
                    data != expected):
                raise AgyCanaryEvidenceError("staged review bytes differ from parent render")
            if len(data) > _MAX_FULL_STAGED_READ_BYTES:
                raise AgyCanaryEvidenceError("staged review file exceeds full-read evidence limit")
            staged[name] = {"bytes": len(data), "sha256": _sha256(data)}
    finally:
        os.close(review_fd)
    binding = {
        "schema": "agy_canary_stage_binding.v1",
        "prepare_sha256": _sha256(_canonical_json(prepare)),
        "launch_authority_sha256": _sha256(_canonical_json(authority)),
        "plan_sha256": _sha256(bundle_bytes),
        "instruction_generator": generator_identity,
        "staged": staged,
    }
    _exclusive_write_at(capture.root_fd, _STAGE_BINDING_NAME, _canonical_json(binding), 0o600)
    return binding


def _validate_stage_binding(
    *, capture: AgyCanaryCapture, review_dir: Path, authority: dict[str, Any]
) -> dict[str, Any]:
    """Revalidate the parent-sealed stage immediately before authority issuance."""
    _ledger, prepare, _same_authority = _require_prepare_authority(capture=capture)
    binding = _read_json_at(capture.root_fd, _STAGE_BINDING_NAME)
    required = {
        "schema", "prepare_sha256", "launch_authority_sha256", "plan_sha256",
        "instruction_generator", "staged",
    }
    if (not isinstance(binding, dict) or set(binding) != required or
            binding.get("schema") != "agy_canary_stage_binding.v1" or
            binding.get("prepare_sha256") != _sha256(_canonical_json(prepare)) or
            binding.get("launch_authority_sha256") != _sha256(_canonical_json(authority)) or
            binding.get("instruction_generator") != _REVIEW_INSTRUCTION_GENERATOR or
            not _is_digest(binding.get("plan_sha256")) or not isinstance(binding.get("staged"), dict) or
            set(binding["staged"]) != {"review-bundle.md", "review-instructions.md"}):
        raise AgyCanaryEvidenceError("staged review binding is not exact")
    review_fd = os.open(review_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if sorted(os.listdir(review_fd)) != [
            "review-bundle.md", "review-instructions.md",
        ]:
            raise AgyCanaryEvidenceError("staged review file set drifted")
        for name, record in binding["staged"].items():
            if (not isinstance(record, dict) or set(record) != {"bytes", "sha256"} or
                    not _is_plain_int(record.get("bytes")) or record["bytes"] < 1 or
                    not _is_digest(record.get("sha256"))):
                raise AgyCanaryEvidenceError("staged review binding schema is malformed")
            data, info = _reopen_at(review_fd, name)
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or
                    len(data) != record["bytes"] or _sha256(data) != record["sha256"]):
                raise AgyCanaryEvidenceError("staged review binding bytes drifted")
            if name == "review-bundle.md" and _sha256(data) != binding["plan_sha256"]:
                raise AgyCanaryEvidenceError("staged review plan binding drifted")
    finally:
        os.close(review_fd)
    return binding


def _validate_provider_stage_inventory(
    inventory: dict[str, Any], *, binding: dict[str, Any],
) -> None:
    """Require the stage to contain only the two sealed parent-rendered files."""
    if (inventory.get("schema") != "agy_provider_launch_tree.v1" or
            not isinstance(inventory.get("root_identity"), dict) or
            not isinstance(inventory.get("entries"), list)):
        raise AgyCanaryEvidenceError("provider stage inventory is malformed")
    root = inventory["root_identity"]
    if (root.get("kind") != "directory" or root.get("uid") != os.getuid() or
            root.get("mode") != 0o700):
        raise AgyCanaryEvidenceError("provider stage root is unsafe")
    expected_names = ["review-bundle.md", "review-instructions.md"]
    entries = inventory["entries"]
    if [entry.get("path") for entry in entries] != expected_names:
        raise AgyCanaryEvidenceError("provider stage inventory is not exact")
    for entry in entries:
        record = binding["staged"][entry["path"]]
        if (entry.get("kind") != "file" or entry.get("uid") != os.getuid() or
                entry.get("mode") != 0o600 or entry.get("nlink") != 1 or
                entry.get("bytes") != record["bytes"] or
                entry.get("sha256") != record["sha256"]):
            raise AgyCanaryEvidenceError("provider stage file authority drifted")


def _is_digest(value: Any) -> bool:
    """Accept only an actual lower-case SHA-256 text primitive."""
    return (type(value) is str and len(value) == 64 and
            all(character in "0123456789abcdef" for character in value))


def _is_owner_only_mode(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 4 and
            all(character in "01234567" for character in value) and
            not (int(value, 8) & 0o077))


def _is_plain_int(value: Any) -> bool:
    """``bool`` is an ``int`` subclass, but never an evidence primitive."""
    return type(value) is int


def _minimal_home_identity(home: Path) -> dict[str, Any]:
    """Descriptor-seal the complete generated HOME and its strict settings."""
    settings = home / ".gemini" / "antigravity-cli" / "settings.json"
    opened = _open_settings(settings)
    try:
        if stat.S_IMODE(opened.mode) != 0o600:
            raise AgyCanaryEvidenceError("minimal HOME settings are not private")
        policy = _parse_policy(opened.data)
    finally:
        os.close(opened.fd)
        os.close(opened.parent_fd)
    facts = _policy_facts(policy)
    if not all(facts.values()):
        raise AgyCanaryEvidenceError("minimal HOME settings policy is not strict and empty")
    return {
        "settings_bytes": len(opened.data),
        "settings_sha256": _sha256(opened.data),
        "settings_mode": format(opened.mode, "04o"),
        "policy_sha256": _sha256(_canonical_json(policy)),
        "tree": _exact_launch_tree_inventory(home),
    }


def _validate_private_root(path: Path) -> tuple[Path, int]:
    if not path.is_absolute() or path.parent != Path("/tmp"):
        raise AgyCanaryEvidenceError("evidence root must be a direct absolute child of /tmp")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise AgyCanaryEvidenceError("evidence root does not exist") from exc
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
            info.st_uid != os.getuid()):
        raise AgyCanaryEvidenceError("evidence root must be a real directory")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise AgyCanaryEvidenceError("evidence root must have mode 0700")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    opened = os.fstat(fd)
    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
        os.close(fd)
        raise AgyCanaryEvidenceError("evidence root identity changed during open")
    try:
        resolved = path.resolve(strict=True)
        reopened = path.lstat()
    except (FileNotFoundError, OSError) as exc:
        os.close(fd)
        raise AgyCanaryEvidenceError("evidence root identity changed during open") from exc
    if (resolved != path or
            (reopened.st_dev, reopened.st_ino) != (opened.st_dev, opened.st_ino)):
        os.close(fd)
        raise AgyCanaryEvidenceError("evidence root identity changed during open")
    return resolved, fd


def _evidence_root_masking_authority(root: Path, root_fd: int) -> dict[str, Any]:
    info = os.fstat(root_fd)
    try:
        current = root.lstat()
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("bootstrap evidence root identity drifted") from exc
    if (root != Path("/tmp") / root.name or root.resolve(strict=True) != root or
            (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or
            current.st_uid != os.getuid() or stat.S_IMODE(current.st_mode) != 0o700):
        raise AgyCanaryEvidenceError("bootstrap evidence root is not canonical")
    return {
        "schema": "agy_canary_evidence_root_mask.v1", "path": str(root),
        "dev": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
        "mode": stat.S_IMODE(info.st_mode), "strategy": "private_tmpfs",
        "child_visible": False,
    }


def _validate_evidence_root_masking_authority(
    value: Any, *, revalidate: bool = True,
) -> dict[str, Any]:
    required = {
        "schema", "path", "dev", "inode", "uid", "mode", "strategy",
        "child_visible",
    }
    if (not isinstance(value, dict) or set(value) != required or
            value.get("schema") != "agy_canary_evidence_root_mask.v1" or
            not isinstance(value.get("path"), str) or
            not Path(value["path"]).is_absolute() or
            Path(value["path"]).parent != Path("/tmp") or
            any(not _is_plain_int(value.get(name)) or value[name] < 0 for name in (
                "dev", "inode", "uid", "mode"
            )) or (revalidate and value["uid"] != os.getuid()) or
            value["mode"] != 0o700 or
            value.get("strategy") != "private_tmpfs" or
            value.get("child_visible") is not False):
        raise AgyCanaryEvidenceError("bootstrap evidence root masking authority is malformed")
    if revalidate:
        root, root_fd = _validate_private_root(Path(value["path"]))
        try:
            if _evidence_root_masking_authority(root, root_fd) != value:
                raise AgyCanaryEvidenceError("bootstrap evidence root masking authority drifted")
        finally:
            os.close(root_fd)
    return value


def _validate_bootstrap_evidence_root_isolation(
    *, root: Path, repo: Path, account_home: Path,
    uv_store_authority: dict[str, Any],
) -> None:
    protected_paths = {
        repo.resolve(strict=True), account_home.resolve(strict=True),
        *(Path(row["resolved"]) for row in uv_store_authority["directories"].values()),
    }
    if uv_store_authority["workspace"] is not None:
        protected_paths.add(Path(uv_store_authority["workspace"]["resolved"]))
    if any(
            root == path or root in path.parents or path in root.parents
            for path in protected_paths):
        raise AgyCanaryEvidenceError(
            "bootstrap evidence root overlaps a child-visible writable or source path"
        )


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


def _exclusive_write_owned_at(
    directory_fd: int, name: str, data: bytes, mode: int, *, uid: int, gid: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(name, flags, mode, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid) != (uid, gid):
            os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
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
        fd = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
    except Exception:
        os.close(parent_fd)
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AgyCanaryEvidenceError("settings path must be a regular file")
        if os.geteuid() == 0 or info.st_uid != os.geteuid():
            raise AgyCanaryEvidenceError(
                "settings cleanup requires the non-root settings owner"
            )
        data = _read_open_fd(fd)
    except Exception:
        os.close(fd)
        os.close(parent_fd)
        raise
    return _OpenedSettings(
        fd=fd,
        parent_fd=parent_fd,
        name=path.name,
        data=data,
        mode=stat.S_IMODE(info.st_mode),
        device=info.st_dev,
        inode=info.st_ino,
        uid=info.st_uid,
        gid=info.st_gid,
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


def _read_open_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_opened_settings(
    opened: _OpenedSettings, *, name: str, expected_data: bytes,
) -> None:
    descriptor = os.fstat(opened.fd)
    try:
        path_info = os.stat(
            name, dir_fd=opened.parent_fd, follow_symlinks=False,
        )
    except OSError as exc:
        raise AgyCanaryEvidenceError(
            "settings leased path identity drifted"
        ) from exc
    _require_opened_path_identity(opened, name=name, path_info=path_info)
    expected_identity = (
        opened.device, opened.inode, opened.mode, opened.uid, opened.gid,
    )
    for info in (descriptor, path_info):
        identity = (
            info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode),
            info.st_uid, info.st_gid,
        )
        if not stat.S_ISREG(info.st_mode) or identity != expected_identity:
            raise AgyCanaryEvidenceError("settings leased identity or ownership drifted")
    if _read_open_fd(opened.fd) != expected_data:
        raise AgyCanaryEvidenceError("settings leased bytes drifted")


def _require_opened_path_identity(
    opened: _OpenedSettings, *, name: str,
    path_info: os.stat_result | None = None,
) -> None:
    if path_info is None:
        try:
            path_info = os.stat(
                name, dir_fd=opened.parent_fd, follow_symlinks=False,
            )
        except OSError as exc:
            raise AgyCanaryEvidenceError(
                "settings leased path identity drifted"
            ) from exc
    if (not stat.S_ISREG(path_info.st_mode) or
            (path_info.st_dev, path_info.st_ino) != (opened.device, opened.inode)):
        raise AgyCanaryEvidenceError("settings leased path identity drifted")


def _begin_lease_signal_guard() -> set[Any]:
    if (not sys.platform.startswith("linux") or
            threading.current_thread() is not threading.main_thread() or
            threading.active_count() != 1 or
            not hasattr(signal, "pthread_sigmask") or
            not hasattr(signal, "sigtimedwait") or signal.SIGIO in signal.sigpending()):
        raise AgyCanaryEvidenceError(
            "settings write lease requires one signal-clean main thread"
        )
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGIO})
    if signal.SIGIO in signal.sigpending():
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        raise AgyCanaryEvidenceError("settings write lease SIGIO state is ambiguous")
    return previous


def _end_lease_signal_guard(previous: set[Any]) -> None:
    while signal.sigtimedwait({signal.SIGIO}, 0) is not None:
        pass
    signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _acquire_write_lease(fd: int, *, label: str) -> None:
    required = ("F_SETLEASE", "F_GETLEASE", "F_WRLCK", "F_UNLCK")
    if fcntl is None or any(getattr(fcntl, name, None) is None for name in required):
        raise AgyCanaryEvidenceError("settings write leases are unavailable")
    try:
        fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_WRLCK)
    except OSError as exc:
        raise AgyCanaryEvidenceError(
            f"settings write lease is unavailable: {label}"
        ) from exc
    _require_write_lease(fd, label=label)


def _require_write_lease(fd: int, *, label: str) -> None:
    assert fcntl is not None
    if fcntl.fcntl(fd, fcntl.F_GETLEASE) != fcntl.F_WRLCK:
        raise AgyCanaryEvidenceError(f"settings write lease broke: {label}")


def _release_write_lease(fd: int) -> None:
    assert fcntl is not None
    fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_UNLCK)


def _reacquire_write_lease(fd: int, *, label: str) -> None:
    try:
        _require_write_lease(fd, label=label)
        return
    except AgyCanaryEvidenceError:
        pass
    assert fcntl is not None
    try:
        fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_UNLCK)
        fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_WRLCK)
    except OSError as exc:
        raise AgyCanaryEvidenceError(
            f"settings recovery lease is unavailable: {label}"
        ) from exc
    _require_write_lease(fd, label=label)


def _create_replacement(
    *, settings: _OpenedSettings, name: str, data: bytes,
) -> _OpenedSettings:
    fd = os.open(
        name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        settings.mode, dir_fd=settings.parent_fd,
    )
    try:
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid) != (settings.uid, settings.gid):
            os.fchown(fd, settings.uid, settings.gid)
        os.fchmod(fd, settings.mode)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise AgyCanaryEvidenceError("settings replacement short write")
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd)
        opened = _OpenedSettings(
            fd=fd, parent_fd=settings.parent_fd, name=name, data=data,
            mode=stat.S_IMODE(info.st_mode), device=info.st_dev,
            inode=info.st_ino, uid=info.st_uid, gid=info.st_gid,
        )
        if (opened.mode, opened.uid, opened.gid) != (
            settings.mode, settings.uid, settings.gid,
        ):
            raise AgyCanaryEvidenceError(
                "settings replacement ownership or mode was not preserved"
            )
        _validate_opened_settings(opened, name=name, expected_data=data)
        return opened
    except Exception:
        os.close(fd)
        try:
            os.unlink(name, dir_fd=settings.parent_fd)
        except FileNotFoundError:
            pass
        raise


def _process_uids(pid_dir: Path) -> tuple[int, int, int, int] | None:
    try:
        text = (pid_dir / "status").read_text()
    except (FileNotFoundError, ProcessLookupError) as exc:
        try:
            pid_dir.stat()
        except (FileNotFoundError, ProcessLookupError):
            return None
        except OSError as status_exc:
            raise AgyCanaryEvidenceError(
                "settings process inventory is unreadable: "
                f"pid={pid_dir.name},surface=uid-status"
            ) from status_exc
        raise AgyCanaryEvidenceError(
            "settings process inventory is unreadable: "
            f"pid={pid_dir.name},surface=uid-status"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise AgyCanaryEvidenceError(
            "settings process inventory is unreadable: "
            f"pid={pid_dir.name},surface=uid-status"
        ) from exc
    uid_rows = [line.split() for line in text.splitlines() if line.startswith("Uid:")]
    if (len(uid_rows) != 1 or len(uid_rows[0]) != 5 or
            any(not value.isdecimal() for value in uid_rows[0][1:])):
        raise AgyCanaryEvidenceError(
            "settings process inventory is unreadable: "
            f"pid={pid_dir.name},surface=uid-classification"
        )
    values = [int(value) for value in uid_rows[0][1:]]
    return values[0], values[1], values[2], values[3]


def _assert_quiescent(
    settings: _OpenedSettings,
    *,
    block_all_agy_processes: bool,
    proc_root: Path = Path("/proc"),
) -> None:
    blockers: list[str] = []
    own_pid = os.getpid()
    try:
        pid_dirs = list(proc_root.iterdir())
    except OSError as exc:
        raise AgyCanaryEvidenceError(
            "settings process inventory is unreadable: surface=proc-root"
        ) from exc
    for pid_dir in pid_dirs:
        if not pid_dir.name.isdigit() or int(pid_dir.name) == own_pid:
            continue
        process_uids = _process_uids(pid_dir)
        if process_uids is None:
            continue
        if settings.uid not in process_uids:
            continue
        try:
            argv = (pid_dir / "cmdline").read_bytes().split(b"\0")
            executable_name = Path(os.fsdecode(argv[0])).name.lower() if argv and argv[0] else ""
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            raise AgyCanaryEvidenceError(
                "settings process inventory is unreadable: "
                f"pid={pid_dir.name},surface=cmdline"
            ) from exc
        if block_all_agy_processes and (
            executable_name == "agy" or "antigravity" in executable_name
        ):
            blockers.append(f"pid={pid_dir.name},process={executable_name}")
    if blockers:
        raise AgyCanaryEvidenceError(
            "settings tree is not quiescent: " + ", ".join(sorted(set(blockers))[:8])
        )


def _rename_noreplace(
    source_fd: int, source: str, destination_fd: int, destination: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise AgyCanaryEvidenceError("renameat2(RENAME_NOREPLACE) is unavailable")
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(
        source_fd, os.fsencode(source), destination_fd,
        os.fsencode(destination), _RENAME_NOREPLACE,
    ) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


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
    """Remove exactly the failed-canary ``command(pwd)`` rule under quiescence.

    Linux write leases cover conflicting opens and truncation. The maintenance
    lock and path checks cover cooperating rename workflows; a hostile same-UID
    transient rename-and-restore is outside this owner-only cleanup contract.
    """

    if fcntl is None:
        raise AgyCanaryEvidenceError("settings cleanup requires POSIX fcntl locking")
    root_path, root_fd = _validate_private_root(evidence_root)
    settings: _OpenedSettings | None = None
    replacement: _OpenedSettings | None = None
    lock_fd: int | None = None
    temporary: str | None = None
    exchanged = False
    committed = False
    settings_leased = False
    replacement_leased = False
    lease_signal_mask: set[Any] | None = None
    replacement_bytes = b""
    transitions: list[str] = []
    primary_error: BaseException | None = None
    recovery_authority: dict[str, Any] = {}

    def record_state(state: str, **fields: Any) -> None:
        transitions.append(state)
        _replace_state(
            root_fd,
            _state_record(state, transitions=list(transitions), **fields),
        )

    def recovery_fields() -> dict[str, Any]:
        fields = dict(recovery_authority)
        if settings is not None and temporary is not None:
            try:
                _validate_opened_settings(
                    settings, name=temporary, expected_data=settings.data,
                )
            except Exception:
                pass
            else:
                fields["temp_name"] = temporary
        return fields

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

        lease_signal_mask = _begin_lease_signal_guard()
        settings = _open_settings(settings_path)
        _acquire_write_lease(settings.fd, label="original")
        settings_leased = True
        _validate_opened_settings(
            settings, name=settings.name, expected_data=settings.data,
        )
        before = _parse_policy(settings.data)
        after, result = _derive_replacement(before)
        canonical_settings = (
            _account_home() / ".gemini" / "antigravity-cli" / "settings.json"
        ).resolve(strict=False)
        block_all_agy_processes = (
            settings_path.resolve(strict=True) == canonical_settings
        )
        _assert_quiescent(
            settings,
            block_all_agy_processes=block_all_agy_processes,
        )

        _exclusive_write_owned_at(
            root_fd, _SETTINGS_SNAPSHOT_NAME, settings.data, settings.mode,
            uid=settings.uid, gid=settings.gid,
        )
        snapshot_bytes, snapshot_info = _reopen_at(root_fd, _SETTINGS_SNAPSHOT_NAME)
        if (snapshot_bytes != settings.data or
                (snapshot_info.st_uid, snapshot_info.st_gid,
                 stat.S_IMODE(snapshot_info.st_mode)) !=
                (settings.uid, settings.gid, settings.mode)):
            raise AgyCanaryEvidenceError("private settings snapshot did not seal exactly")
        recovery_authority = {
            "recovery_path": str(root_path / _SETTINGS_SNAPSHOT_NAME),
            "recovery_sha256": _sha256(snapshot_bytes),
            "recovery_device": snapshot_info.st_dev,
            "recovery_inode": snapshot_info.st_ino,
            "recovery_uid": snapshot_info.st_uid,
            "recovery_gid": snapshot_info.st_gid,
            "recovery_mode": format(stat.S_IMODE(snapshot_info.st_mode), "04o"),
        }
        common = {
            "result": result,
            "settings_path_sha256": _sha256(str(settings_path).encode()),
            "before_sha256": _sha256(settings.data),
            "before_mode": format(settings.mode, "04o"),
            "recovery_snapshot_sha256": _sha256(snapshot_bytes),
            **recovery_authority,
        }
        record_state("prepared", **common)

        if result == "already_absent":
            _require_write_lease(settings.fd, label="original")
            _validate_opened_settings(
                settings, name=settings.name, expected_data=settings.data,
            )
            record_state("verified", **common)
            _require_write_lease(settings.fd, label="original")
            _assert_quiescent(
                settings, block_all_agy_processes=block_all_agy_processes,
            )
            _require_write_lease(settings.fd, label="original")
            _validate_opened_settings(
                settings, name=settings.name, expected_data=settings.data,
            )
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

        _require_write_lease(settings.fd, label="original")
        _validate_opened_settings(
            settings, name=settings.name, expected_data=settings.data,
        )
        temporary = f".phase-loop-agy-settings.{secrets.token_hex(16)}.tmp"
        replacement = _create_replacement(
            settings=settings, name=temporary, data=replacement_bytes,
        )
        _acquire_write_lease(replacement.fd, label="replacement")
        replacement_leased = True
        _require_write_lease(settings.fd, label="original")
        _require_write_lease(replacement.fd, label="replacement")
        _validate_opened_settings(
            settings, name=settings.name, expected_data=settings.data,
        )
        _validate_opened_settings(
            replacement, name=temporary, expected_data=replacement_bytes,
        )
        _assert_quiescent(
            settings, block_all_agy_processes=block_all_agy_processes,
        )
        _rename_exchange(settings.parent_fd, settings.name, temporary)
        exchanged = True
        record_state("exchanged_unverified", temp_name=temporary, **common)

        _require_write_lease(settings.fd, label="original")
        _require_write_lease(replacement.fd, label="replacement")
        _validate_opened_settings(
            replacement, name=settings.name, expected_data=replacement_bytes,
        )
        _validate_opened_settings(
            settings, name=temporary, expected_data=settings.data,
        )
        destination = _read_open_fd(replacement.fd)
        destination_parsed = _parse_policy(destination)
        if destination_parsed != after:
            raise AgyCanaryEvidenceError("exchanged destination failed structural or mode validation")
        os.fsync(settings.parent_fd)
        _require_write_lease(settings.fd, label="original")
        _require_write_lease(replacement.fd, label="replacement")
        record_state("verified", temp_name=temporary, **common)
        _require_write_lease(settings.fd, label="original")
        _require_write_lease(replacement.fd, label="replacement")
        _assert_quiescent(
            replacement, block_all_agy_processes=block_all_agy_processes,
        )
        _require_write_lease(settings.fd, label="original")
        _require_write_lease(replacement.fd, label="replacement")
        _validate_opened_settings(
            replacement, name=settings.name, expected_data=replacement_bytes,
        )
        _validate_opened_settings(
            settings, name=temporary, expected_data=settings.data,
        )
        record_state("committed", **common)
        committed = True
        os.unlink(temporary, dir_fd=settings.parent_fd)
        temporary = None
        os.fsync(settings.parent_fd)
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
        primary_error = exc
        if committed and temporary is None:
            try:
                record_state(
                    "recovery_retained",
                    error=type(exc).__name__,
                    recovery_reason="post_commit_directory_fsync",
                    **recovery_fields(),
                )
            except Exception:
                pass
        if (not exchanged and settings is not None and replacement is not None and
                temporary is not None):
            try:
                _require_opened_path_identity(replacement, name=temporary)
                os.unlink(temporary, dir_fd=settings.parent_fd)
                temporary = None
                os.fsync(settings.parent_fd)
            except Exception as cleanup_exc:
                try:
                    record_state(
                        "recovery_retained",
                        error=type(exc).__name__,
                        cleanup_error=type(cleanup_exc).__name__,
                        **recovery_fields(),
                    )
                except Exception:
                    pass
        if (exchanged and settings is not None and replacement is not None and
                temporary is not None):
            try:
                record_state("rollback_required", error=type(exc).__name__)
                _reacquire_write_lease(settings.fd, label="original")
                _reacquire_write_lease(replacement.fd, label="replacement")
                _require_opened_path_identity(settings, name=temporary)
                _require_opened_path_identity(replacement, name=settings.name)
                _validate_opened_settings(
                    settings, name=temporary, expected_data=settings.data,
                )
                _validate_opened_settings(
                    replacement, name=settings.name,
                    expected_data=replacement_bytes,
                )
                _rename_exchange(settings.parent_fd, settings.name, temporary)
                exchanged = False
                _validate_opened_settings(
                    settings, name=settings.name, expected_data=settings.data,
                )
                _require_opened_path_identity(replacement, name=temporary)
                if _read_open_fd(replacement.fd) == replacement_bytes:
                    os.unlink(temporary, dir_fd=settings.parent_fd)
                    temporary = None
                    os.fsync(settings.parent_fd)
                    record_state(
                        "rolled_back", error=type(exc).__name__,
                        **recovery_fields(),
                    )
                else:
                    record_state(
                        "recovery_retained", error=type(exc).__name__,
                        **recovery_fields(),
                    )
            except Exception as rollback_exc:
                try:
                    record_state(
                        "recovery_retained",
                        error=type(exc).__name__,
                        rollback_error=type(rollback_exc).__name__,
                        **recovery_fields(),
                    )
                except Exception:
                    pass
        if isinstance(exc, AgyCanaryEvidenceError):
            raise
        if isinstance(exc, OSError) and exc.errno in {errno.ELOOP, errno.EXDEV}:
            raise AgyCanaryEvidenceError(str(exc)) from exc
        raise AgyCanaryEvidenceError(f"settings cleanup failed: {exc}") from exc
    finally:
        cleanup_errors: list[str] = []
        if replacement is not None:
            try:
                if replacement_leased:
                    _release_write_lease(replacement.fd)
            except Exception as exc:
                cleanup_errors.append(f"replacement-lease:{type(exc).__name__}")
            try:
                os.close(replacement.fd)
            except OSError as exc:
                cleanup_errors.append(f"replacement-fd:{type(exc).__name__}")
        if settings is not None:
            try:
                if settings_leased:
                    _release_write_lease(settings.fd)
            except Exception as exc:
                cleanup_errors.append(f"original-lease:{type(exc).__name__}")
            try:
                os.close(settings.fd)
            except OSError as exc:
                cleanup_errors.append(f"original-fd:{type(exc).__name__}")
            try:
                os.close(settings.parent_fd)
            except OSError as exc:
                cleanup_errors.append(f"settings-parent:{type(exc).__name__}")
        if lease_signal_mask is not None:
            try:
                _end_lease_signal_guard(lease_signal_mask)
            except Exception as exc:
                cleanup_errors.append(f"signal-guard:{type(exc).__name__}")
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception as exc:
                cleanup_errors.append(f"maintenance-unlock:{type(exc).__name__}")
            try:
                os.close(lock_fd)
            except OSError as exc:
                cleanup_errors.append(f"maintenance-fd:{type(exc).__name__}")
        try:
            os.close(root_fd)
        except OSError as exc:
            cleanup_errors.append(f"evidence-root:{type(exc).__name__}")
        if cleanup_errors and primary_error is None:
            raise AgyCanaryEvidenceError(
                "settings cleanup finalization failed: " + ", ".join(cleanup_errors)
            )


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


def _revalidate_customization_source_authority(value: Any) -> None:
    if (not isinstance(value, dict) or
            set(value) != {"inventory", "home", "project"} or
            not isinstance(value.get("inventory"), dict) or
            not isinstance(value.get("home"), str) or
            not isinstance(value.get("project"), str)):
        raise AgyCanaryEvidenceError(
            "prepare has malformed customization-source authority"
        )
    home = Path(value["home"])
    project = Path(value["project"])
    if not home.is_absolute() or not project.is_absolute():
        raise AgyCanaryEvidenceError(
            "prepare customization-source roots are not absolute"
        )
    revalidate_customization_inventory(
        value["inventory"], home=home, project_dir=project,
        env=dict(os.environ),
    )


def _auth_placeholder_authority(
    *, minimal_home: Path, records: tuple[dict[str, str], ...],
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for record in records:
        destination = record.get("destination")
        if not isinstance(destination, str):
            raise AgyCanaryEvidenceError(
                "provider authentication bind destination is malformed"
            )
        try:
            relative = Path(destination).relative_to("/home/phase-loop")
        except ValueError as exc:
            raise AgyCanaryEvidenceError(
                "provider authentication bind destination escapes minimal HOME"
            ) from exc
        target = minimal_home / relative
        try:
            data, info = _read_regular_path(target)
        except (FileNotFoundError, OSError) as exc:
            raise AgyCanaryEvidenceError(
                "provider authentication bind target is unavailable"
            ) from exc
        if (data or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise AgyCanaryEvidenceError(
                "provider authentication bind target is not an empty private placeholder"
            )
        rows.append({
            "destination": destination,
            "path": str(target),
            "device": info.st_dev,
            "inode": info.st_ino,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": format(stat.S_IMODE(info.st_mode), "04o"),
            "sha256": _sha256(data),
        })
    return tuple(rows)


def _validate_auth_placeholder_proof(
    value: Any, *, minimal_home: Path, records: list[dict[str, Any]],
) -> None:
    if not isinstance(value, list) or len(value) != len(records):
        raise AgyCanaryEvidenceError(
            "provider authentication placeholder proof is malformed"
        )
    empty_sha256 = _sha256(b"")
    for row, record in zip(value, records, strict=True):
        destination = record.get("destination")
        try:
            expected_path = minimal_home / Path(str(destination)).relative_to(
                "/home/phase-loop"
            )
        except ValueError as exc:
            raise AgyCanaryEvidenceError(
                "provider authentication placeholder proof is malformed"
            ) from exc
        if (not isinstance(row, dict) or set(row) != {
                "destination", "path", "device", "inode", "uid", "gid",
                "mode", "sha256",
            } or row.get("destination") != destination or
                row.get("path") != str(expected_path) or
                any(not _is_plain_int(row.get(name)) or row[name] < 0
                    for name in ("device", "inode", "uid", "gid")) or
                row.get("mode") != "0600" or
                row.get("sha256") != empty_sha256):
            raise AgyCanaryEvidenceError(
                "provider authentication placeholder proof is malformed"
            )


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
        os.close(opened.fd)
        os.close(opened.parent_fd)
    target.write_bytes(data)
    target.chmod(0o600)
    binds = _validated_auth_binds(auth_paths, root)
    for _source_relative, destination in _PROVIDER_AUTH_PATHS.values():
        placeholder = root / Path(destination).relative_to("/home/phase-loop")
        placeholder.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        placeholder.write_bytes(b"")
        placeholder.chmod(0o600)
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
    namespace_python = Path("/usr/bin/python3").resolve(strict=True)
    try:
        python_info = _stat_regular_path(namespace_python)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("namespace self-test Python is unavailable") from exc
    if python_info.st_uid != 0 or not os.access(namespace_python, os.X_OK):
        raise AgyCanaryEvidenceError("namespace self-test Python is unsafe")
    test_program = (
        "import socket, ssl, pathlib, os; "
        "assert pathlib.Path('/run/phase-loop-review/review-instructions.md').is_file(); "
        "assert pathlib.Path('/run/phase-loop-review/review-bundle.md').is_file(); "
        f"assert not pathlib.Path('/tmp/' + {namespace.evidence_root.name!r}).exists(); "
        f"socket.getaddrinfo({namespace.provider_hostname!r}, 443, type=socket.SOCK_STREAM); "
        f"s=socket.create_connection(({namespace.provider_hostname!r}, 443), timeout=10); "
        f"ssl.create_default_context().wrap_socket(s, server_hostname={namespace.provider_hostname!r}).close()"
    )
    proc = subprocess.run(
        namespace.command([str(namespace_python), "-I", "-c", test_program]),
        capture_output=True, text=True, timeout=30, check=False,
        env=namespace.outer_environment(),
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
        os.close(opened.fd)
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
    ledger, _prepare, authority = _require_prepare_authority(capture=capture)
    binding = _validate_stage_binding(capture=capture, review_dir=review_dir, authority=authority)
    records: dict[str, dict[str, Any]] = {}
    review_fd = os.open(review_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for name in ("review-instructions.md", "review-bundle.md"):
            data, info = _reopen_at(review_fd, name)
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise AgyCanaryEvidenceError(f"staged file is not private: {name}")
            binding_record = binding["staged"][name]
            if (len(data) != binding_record["bytes"] or
                    _sha256(data) != binding_record["sha256"]):
                raise AgyCanaryEvidenceError("retained staged file differs from sealed parent render")
            retained = f"staged-{name}"
            _exclusive_write_at(capture.root_fd, retained, data, 0o600)
            records[name] = {"retained": retained, "bytes": len(data), "sha256": _sha256(data)}
    finally:
        os.close(review_fd)
    stage_authority = {
        "schema": "agy_canary_stage_authority.v1",
        "launch_authority_sha256": _sha256(_canonical_json(authority)),
        "stage_binding_sha256": _sha256(_canonical_json(binding)),
        "staged": records,
    }
    _exclusive_write_at(capture.root_fd, _STAGE_AUTHORITY_NAME, _canonical_json(stage_authority), 0o600)
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
    _prepared_ledger, _prepare, authority = _require_prepare_authority(capture=capture)
    if attempt_id not in authority["authorized_attempt_ids"]:
        raise AgyCanaryEvidenceError("capture launch attempt is not prepare-authorized")
    stage_binding = _read_json_at(capture.root_fd, _STAGE_BINDING_NAME)
    stage_authority = _read_json_at(capture.root_fd, _STAGE_AUTHORITY_NAME)
    if (set(stage_authority) != {"schema", "launch_authority_sha256", "stage_binding_sha256", "staged"} or
            stage_authority.get("schema") != "agy_canary_stage_authority.v1" or
            stage_authority.get("launch_authority_sha256") != _sha256(_canonical_json(authority)) or
            stage_authority.get("stage_binding_sha256") != _sha256(_canonical_json(stage_binding)) or
            stage_authority.get("staged") != staged):
        raise AgyCanaryEvidenceError("capture staged input authority is not exact")
    attempts = ledger.get("attempts")
    if (not isinstance(attempt_id, str) or not attempt_id or Path(attempt_id).name != attempt_id or
            not isinstance(attempts, list) or any(item.get("attempt_id") == attempt_id for item in attempts if isinstance(item, dict))):
        raise AgyCanaryEvidenceError("attempt identifier is missing or duplicated")
    stream_name = f"agy-stream-{attempt_id}.jsonl"
    diagnostic_name = f"agy-diagnostic-{attempt_id}.log"
    _exclusive_write_at(capture.root_fd, stream_name, stdout.encode(), 0o600)
    _exclusive_write_at(capture.root_fd, diagnostic_name, stderr.encode(), 0o600)
    normalized = ["<prompt>" if value and index == len(argv) - 1 else value for index, value in enumerate(argv)]
    record = {
        "attempt_id": attempt_id,
        "seat_key": seat_key,
        "returncode": returncode,
        "argv_sha256": _sha256("\0".join(normalized).encode()),
        "stream": {"name": stream_name, "bytes": len(stdout.encode()), "sha256": _sha256(stdout.encode())},
        "diagnostic": {"name": diagnostic_name, "bytes": len(stderr.encode()), "sha256": _sha256(stderr.encode())},
        "staged": staged,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    attempts.append(record)
    _write_replace_at(capture.root_fd, _LEDGER_NAME, ledger)
    return record


def _provider_token(provider: str, seat_key: str) -> str:
    if provider not in _PROVIDER_EXECUTABLES or not seat_key or Path(seat_key).name != seat_key:
        raise AgyCanaryEvidenceError("provider record identity is invalid")
    return _sha256(f"{provider}\0{seat_key}".encode())[:24]


def _provider_names(provider: str, seat_key: str) -> dict[str, str]:
    token = _provider_token(provider, seat_key)
    return {
        "authority": f"agy-provider-launch-{provider}-{token}.json",
        "result": f"agy-provider-result-{provider}-{token}.json",
        "terminal": f"agy-provider-terminal-{provider}-{token}.txt",
        "detail": f"agy-provider-detail-{provider}-{token}.txt",
    }


def seal_provider_launches(
    *, capture: AgyCanaryCapture,
    launches: tuple[tuple[str, str, ProviderLaunchAuthority], ...],
) -> dict[str, Any]:
    """Freeze every captured provider/seat authority before concurrent execution."""
    if len(launches) != len(_CAPTURE_PROVIDERS):
        raise AgyCanaryEvidenceError("provider launch registry is empty")
    _ledger, _prepare, launch_authority = _require_prepare_authority(capture=capture)
    stage_binding = _read_json_at(capture.root_fd, _STAGE_BINDING_NAME)
    stage_binding_sha256 = _sha256(_canonical_json(stage_binding))
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    seat_keys: set[str] = set()
    providers: set[str] = set()
    for provider, seat_key, authority in launches:
        key = (provider, seat_key)
        if key in seen or provider in providers or authority.provider != provider:
            raise AgyCanaryEvidenceError("provider launch registry has duplicate or mismatched authority")
        seen.add(key)
        if seat_key in seat_keys:
            raise AgyCanaryEvidenceError("provider launch registry seat key is duplicated")
        seat_keys.add(seat_key)
        providers.add(provider)
        names = _provider_names(provider, seat_key)
        projection = authority.projected_auth_proof()
        launch = {
            "schema": "agy_provider_launch.v1",
            "provider": provider,
            "seat_key": seat_key,
            "launch_authority_sha256": _sha256(_canonical_json(launch_authority)),
            "stage_binding_sha256": stage_binding_sha256,
            "runtime": authority.runtime_authority(),
            "auth_placeholders": authority.auth_placeholder_proof(),
            "projected_auth": projection,
        }
        data = _canonical_json(launch)
        _exclusive_write_at(capture.root_fd, names["authority"], data, 0o600)
        entries.append({
            "provider": provider,
            "seat_key": seat_key,
            "authority": {"name": names["authority"], "bytes": len(data), "sha256": _sha256(data)},
            "result_name": names["result"],
        })
    registry = {
        "schema": "agy_provider_launch_registry.v1",
        "launch_authority_sha256": _sha256(_canonical_json(launch_authority)),
        "stage_binding_sha256": stage_binding_sha256,
        "entries": entries,
    }
    _exclusive_write_at(capture.root_fd, _PROVIDER_REGISTRY_NAME, _canonical_json(registry), 0o600)
    return registry


def _provider_registry(*, root_fd: int) -> dict[str, Any]:
    registry = _read_json_at(root_fd, _PROVIDER_REGISTRY_NAME)
    required = {"schema", "launch_authority_sha256", "stage_binding_sha256", "entries"}
    if (not isinstance(registry, dict) or set(registry) != required or
            registry.get("schema") != "agy_provider_launch_registry.v1" or
            not _is_digest(registry.get("launch_authority_sha256")) or
            not _is_digest(registry.get("stage_binding_sha256")) or
            not isinstance(registry.get("entries"), list) or len(registry["entries"]) != len(_CAPTURE_PROVIDERS)):
        raise AgyCanaryEvidenceError("provider launch registry is malformed")
    seen: set[tuple[str, str]] = set()
    seat_keys: set[str] = set()
    providers: set[str] = set()
    for entry in registry["entries"]:
        if (not isinstance(entry, dict) or set(entry) != {"provider", "seat_key", "authority", "result_name"} or
                not isinstance(entry.get("provider"), str) or entry["provider"] not in _PROVIDER_EXECUTABLES or
                not isinstance(entry.get("seat_key"), str) or not entry["seat_key"] or
                not isinstance(entry.get("result_name"), str) or entry["result_name"] != _provider_names(entry["provider"], entry["seat_key"])["result"] or
                not isinstance(entry.get("authority"), dict) or set(entry["authority"]) != {"name", "bytes", "sha256"}):
            raise AgyCanaryEvidenceError("provider launch registry entry is malformed")
        key = (entry["provider"], entry["seat_key"])
        if key in seen:
            raise AgyCanaryEvidenceError("provider launch registry entry is duplicated")
        seen.add(key)
        if entry["seat_key"] in seat_keys:
            raise AgyCanaryEvidenceError("provider launch registry seat key is duplicated")
        seat_keys.add(entry["seat_key"])
        if entry["provider"] in providers:
            raise AgyCanaryEvidenceError("provider launch registry provider is duplicated")
        providers.add(entry["provider"])
    if providers != _CAPTURE_PROVIDERS:
        raise AgyCanaryEvidenceError("provider launch registry does not cover every provider")
    return registry


def record_provider_result(
    *, capture: AgyCanaryCapture, provider: str, seat_key: str,
    authority: ProviderLaunchAuthority, status: str, text: str, detail: str | None,
) -> dict[str, Any]:
    """Seal one terminal provider result after the panel workers have completed."""
    if (authority.provider != provider or status not in {"OK", "EMPTY", "ERROR", "TIMEOUT", "DEGRADED", "UNAVAILABLE"} or
            not isinstance(text, str) or (detail is not None and not isinstance(detail, str))):
        raise AgyCanaryEvidenceError("provider terminal result is invalid")
    registry = _provider_registry(root_fd=capture.root_fd)
    entry = next((item for item in registry["entries"] if item["provider"] == provider and item["seat_key"] == seat_key), None)
    if entry is None:
        raise AgyCanaryEvidenceError("provider terminal result is not registered")
    names = _provider_names(provider, seat_key)
    launch_bytes = _read_regular_at(capture.root_fd, entry["authority"]["name"])
    if len(launch_bytes) != entry["authority"]["bytes"] or _sha256(launch_bytes) != entry["authority"]["sha256"]:
        raise AgyCanaryEvidenceError("provider launch authority bytes drifted")
    try:
        launch = json.loads(launch_bytes)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("provider launch authority is not JSON") from exc
    if (not isinstance(launch, dict) or launch.get("provider") != provider or launch.get("seat_key") != seat_key or
            launch.get("runtime") != authority.runtime_authority() or
            launch.get("auth_placeholders") != authority.auth_placeholder_proof() or
            launch.get("projected_auth") != authority.projected_auth_proof()):
        raise AgyCanaryEvidenceError("provider launch authority does not match terminal result")
    terminal = text.encode()
    _exclusive_write_at(capture.root_fd, names["terminal"], terminal, 0o600)
    detail_record: dict[str, Any] | None = None
    if detail is not None:
        detail_bytes = detail.encode()
        _exclusive_write_at(capture.root_fd, names["detail"], detail_bytes, 0o600)
        detail_record = {"name": names["detail"], "bytes": len(detail_bytes), "sha256": _sha256(detail_bytes)}
    attempts = authority.review_attempt_proof()
    terminal_record = {"name": names["terminal"], "bytes": len(terminal), "sha256": _sha256(terminal)}
    result = {
        "schema": "agy_provider_result.v1", "provider": provider, "seat_key": seat_key,
        "registry_sha256": _sha256(_canonical_json(registry)), "authority_sha256": entry["authority"]["sha256"],
        "attempts": attempts, "status": status,
        "terminal": terminal_record, "detail": detail_record,
    }
    _exclusive_write_at(capture.root_fd, entry["result_name"], _canonical_json(result), 0o600)
    return result


def _verified_provider_results(*, root_fd: int) -> dict[tuple[str, str], dict[str, Any]]:
    """Read the exact sealed provider result set without accepting board claims."""
    registry = _provider_registry(root_fd=root_fd)
    authority = _read_json_at(root_fd, _LAUNCH_AUTHORITY_NAME)
    ledger = _read_json_at(root_fd, _LEDGER_NAME)
    stage_binding = _read_json_at(root_fd, _STAGE_BINDING_NAME)
    if (registry["launch_authority_sha256"] != _sha256(_canonical_json(authority)) or
            registry["stage_binding_sha256"] != _sha256(_canonical_json(stage_binding))):
        raise AgyCanaryEvidenceError("provider launch registry authority binding drifted")
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in registry["entries"]:
        provider = entry["provider"]
        seat_key = entry["seat_key"]
        names = _provider_names(provider, seat_key)
        launch_bytes = _read_regular_at(root_fd, entry["authority"]["name"])
        if (len(launch_bytes) != entry["authority"]["bytes"] or
                _sha256(launch_bytes) != entry["authority"]["sha256"]):
            raise AgyCanaryEvidenceError("provider authority record bytes drifted")
        try:
            launch = json.loads(launch_bytes)
        except json.JSONDecodeError as exc:
            raise AgyCanaryEvidenceError("provider authority record is not JSON") from exc
        launch_required = {
            "schema", "provider", "seat_key", "launch_authority_sha256",
            "stage_binding_sha256", "runtime", "auth_placeholders",
            "projected_auth",
        }
        projection = launch.get("projected_auth") if isinstance(launch, dict) else None
        if (not isinstance(launch, dict) or set(launch) != launch_required or
                launch.get("schema") != "agy_provider_launch.v1" or launch.get("provider") != provider or
                launch.get("seat_key") != seat_key or launch.get("launch_authority_sha256") != registry["launch_authority_sha256"] or
                launch.get("stage_binding_sha256") != registry["stage_binding_sha256"] or
                not isinstance(projection, dict) or projection.get("provider") != provider or
                projection.get("schema") != "agy_provider_projected_auth.v1"):
            raise AgyCanaryEvidenceError("provider authority record is malformed")
        runtime = _validate_provider_runtime_record(
            launch.get("runtime"), provider=provider,
        )
        expected_records = authority.get("auth_binds") if provider == "gemini" else None
        rows = projection.get("records") if isinstance(projection, dict) else None
        malformed_rows = not isinstance(rows, list) or any(
            not isinstance(row, dict) or set(row) != {"destination", "uid", "mode", "sha256"} or
            not isinstance(row.get("uid"), str) or not row["uid"].isdigit() or
            not _is_owner_only_mode(row.get("mode")) or not _is_digest(row.get("sha256"))
            for row in rows or []
        )
        gemini_drift = provider == "gemini" and (
            not isinstance(expected_records, list) or not isinstance(rows, list) or
            len(rows) != len(expected_records) or any(
                row.get("destination") != record.get("destination") or row.get("uid") != record.get("uid") or
                row.get("mode") != record.get("mode") or row.get("sha256") != record.get("source_sha256")
                for row, record in zip(rows, expected_records, strict=True)
            )
        )
        if (set(projection) != {"schema", "provider", "runtime_destination", "runtime_sha256", "records"} or
                projection.get("runtime_destination") != f"/run/phase-loop-bin/{_PROVIDER_EXECUTABLES[provider]}" or
                projection.get("runtime_sha256") != runtime["sha256"] or malformed_rows or gemini_drift or
                (provider != "gemini" and (not isinstance(rows, list) or len(rows) != 1 or rows[0].get("destination") != _PROVIDER_AUTH_PATHS[provider][1]))):
            raise AgyCanaryEvidenceError("provider projected authentication proof is malformed")
        if provider == "gemini":
            sealed_agy = _sealed_agy_runtime(authority.get("agy_runtime"))
            expected_runtime = _provider_runtime_record(_TrustedProviderRuntime(
                "gemini", sealed_agy.source, sealed_agy.device, sealed_agy.inode,
                sealed_agy.mode, sealed_agy.sha256,
            ))
            if runtime != expected_runtime:
                raise AgyCanaryEvidenceError(
                    "Gemini provider runtime differs from prepare authority"
                )
        assert isinstance(rows, list)
        _validate_auth_placeholder_proof(
            launch.get("auth_placeholders"),
            minimal_home=Path(authority["minimal_home"]["path"]),
            records=rows,
        )
        result = _read_json_at(root_fd, entry["result_name"])
        required = {"schema", "provider", "seat_key", "registry_sha256", "authority_sha256", "attempts", "status", "terminal", "detail"}
        if (not isinstance(result, dict) or set(result) != required or result.get("schema") != "agy_provider_result.v1" or
                result.get("provider") != provider or result.get("seat_key") != seat_key or
                result.get("registry_sha256") != _sha256(_canonical_json(registry)) or
                result.get("authority_sha256") != entry["authority"]["sha256"] or
                result.get("status") not in {"OK", "EMPTY", "ERROR", "TIMEOUT", "DEGRADED", "UNAVAILABLE"}):
            raise AgyCanaryEvidenceError("provider terminal result is malformed")
        attempts = result.get("attempts")
        if (not isinstance(attempts, dict) or set(attempts) != {"launch", "attempts", "terminal_attempt"} or
                (attempts["launch"] is not None and (
                    not isinstance(attempts["launch"], dict) or set(attempts["launch"]) != {"argv_bytes", "argv_sha256", "normalized_argv_sha256"} or
                    not _is_plain_int(attempts["launch"].get("argv_bytes")) or attempts["launch"]["argv_bytes"] < 1 or
                    not _is_digest(attempts["launch"].get("argv_sha256")) or
                    not _is_digest(attempts["launch"].get("normalized_argv_sha256"))
                )) or not isinstance(attempts["attempts"], list)):
            raise AgyCanaryEvidenceError("provider review attempt proof is malformed")
        if len(attempts["attempts"]) > _MAX_PROVIDER_REVIEW_ATTEMPTS:
            raise AgyCanaryEvidenceError("provider review attempt limit exceeded")
        if attempts["launch"] is None:
            if attempts["attempts"] or attempts["terminal_attempt"] is not None:
                raise AgyCanaryEvidenceError("provider review attempt proof is inconsistent")
        else:
            expected_attempts = [
                {
                    "index": index,
                    "attempt_id": f"{provider}-{index + 1}",
                    **attempts["launch"],
                }
                for index in range(len(attempts["attempts"]))
            ]
            expected_terminal = len(expected_attempts) - 1 if expected_attempts else None
            if (attempts["attempts"] != expected_attempts or
                    attempts["terminal_attempt"] != expected_terminal):
                raise AgyCanaryEvidenceError("provider review attempts are malformed")
        if provider == "gemini":
            runner_attempts = ledger.get("attempts")
            if not isinstance(runner_attempts, list):
                raise AgyCanaryEvidenceError("Gemini runner ledger attempts are malformed")
            runner_ids = [
                item.get("attempt_id") if isinstance(item, dict) else None
                for item in runner_attempts
            ]
            provider_attempts = attempts["attempts"]
            provider_ids = [item["attempt_id"] for item in provider_attempts]
            if (runner_ids != authority["authorized_attempt_ids"][:len(runner_ids)] or
                    provider_ids != runner_ids or
                    any(not isinstance(item, dict) or
                        not _is_digest(item.get("argv_sha256")) or
                        provider_attempts[index]["normalized_argv_sha256"] !=
                        item["argv_sha256"]
                        for index, item in enumerate(runner_attempts))):
                raise AgyCanaryEvidenceError(
                    "Gemini provider attempts do not match the authorized runner ledger"
                )
        terminal = result.get("terminal")
        if (not isinstance(terminal, dict) or set(terminal) != {"name", "bytes", "sha256"} or
                terminal.get("name") != names["terminal"] or not _is_plain_int(terminal.get("bytes")) or
                terminal["bytes"] < 0 or not _is_digest(terminal.get("sha256"))):
            raise AgyCanaryEvidenceError("provider terminal output is malformed")
        terminal_bytes = _read_regular_at(root_fd, terminal["name"])
        if len(terminal_bytes) != terminal["bytes"] or _sha256(terminal_bytes) != terminal["sha256"]:
            raise AgyCanaryEvidenceError("provider terminal output bytes drifted")
        detail = result.get("detail")
        if detail is not None:
            if (not isinstance(detail, dict) or set(detail) != {"name", "bytes", "sha256"} or
                    detail.get("name") != names["detail"] or not _is_plain_int(detail.get("bytes")) or
                    detail["bytes"] < 0 or not _is_digest(detail.get("sha256"))):
                raise AgyCanaryEvidenceError("provider terminal detail is malformed")
            detail_bytes = _read_regular_at(root_fd, detail["name"])
            if len(detail_bytes) != detail["bytes"] or _sha256(detail_bytes) != detail["sha256"]:
                raise AgyCanaryEvidenceError("provider terminal detail bytes drifted")
            detail_text: str | None = detail_bytes.decode("utf-8")
        else:
            detail_text = None
        try:
            text = terminal_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AgyCanaryEvidenceError("provider terminal output is not UTF-8") from exc
        if (result["status"] == "OK" and
                (not attempts["attempts"] or not text.strip())):
            raise AgyCanaryEvidenceError("usable provider result lacks an actual review attempt")
        if result["status"] == "EMPTY" and text.strip():
            raise AgyCanaryEvidenceError("empty provider result has terminal review text")
        results[(provider, seat_key)] = {"status": result["status"], "text": text, "detail": detail_text}
    return results


def _provider_result_summary(*, root_fd: int) -> dict[str, Any]:
    """Return the immutable provider-record identity carried by public evidence."""
    registry = _provider_registry(root_fd=root_fd)
    _verified_provider_results(root_fd=root_fd)
    result_entries: list[dict[str, Any]] = []
    identities: list[dict[str, str]] = []
    for entry in registry["entries"]:
        data = _read_regular_at(root_fd, entry["result_name"])
        result_entries.append({
            "name": entry["result_name"],
            "bytes": len(data),
            "sha256": _sha256(data),
        })
        identities.append({"provider": entry["provider"], "seat_key": entry["seat_key"]})
    return {
        "registry_sha256": _sha256(_canonical_json(registry)),
        "result_set_sha256": _sha256(_canonical_json(result_entries)),
        "providers": identities,
    }


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
        if not _is_plain_int(value) or value != sequence + 1:
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
            required = {"sequence", "session_id", "type", "call_id", "tool", "target"}
            if ((set(event) != required and set(event) != required | {"attempt"}) or
                    not isinstance(event.get("tool"), str) or not event["tool"] or
                    not isinstance(event.get("target"), str) or not event["target"] or
                    ("attempt" in event and type(event.get("attempt")) is not bool)):
                raise AgyCanaryEvidenceError("stream tool call schema is invalid")
            call_id = event.get("call_id")
            if not isinstance(call_id, str) or call_id in calls or pending_call is not None:
                raise AgyCanaryEvidenceError("stream tool call identity is invalid")
            calls[call_id] = event
            pending_call = call_id
        elif kind == "tool_result":
            outcome = event.get("outcome")
            expected_fields = {"sequence", "session_id", "type", "call_id", "outcome", "content"} if outcome == "success" else {"sequence", "session_id", "type", "call_id", "outcome"}
            if ((set(event) != expected_fields and set(event) != expected_fields | {"execution"}) or
                    outcome not in {"success", "denied", "error"} or
                    (outcome == "success" and not isinstance(event.get("content"), str)) or
                    ("execution" in event and type(event.get("execution")) is not bool)):
                raise AgyCanaryEvidenceError("stream tool result schema is invalid")
            call_id = event.get("call_id")
            if not isinstance(call_id, str) or call_id != pending_call or "result" in calls.get(call_id, {}):
                raise AgyCanaryEvidenceError("stream tool result is unmatched")
            calls[call_id]["result"] = event
            pending_call = None
        elif kind == "terminal":
            if set(event) != {"sequence", "session_id", "type", "text"} or pending_call is not None or terminal is not None or not isinstance(event.get("text"), str) or not event["text"].strip():
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


def _reduce_capability_class(
    *, capability: tuple[str, str, str, str], data: bytes, namespace: AgyCanaryNamespace,
    stream_name: str, staged_contents: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Reduce one isolated action from raw stream-json authority, never its prompt or docs."""
    class_name, expected_tool, expected_target, expected_outcome = capability
    _session, calls, _terminal = _parse_stream(data)
    if class_name == "allowed_read":
        if staged_contents is None:
            _require_probe_content_matches_stage(calls, namespace)
        else:
            for call in calls:
                result = call.get("result")
                expected = staged_contents.get(str(call.get("target")))
                if (expected is None or not isinstance(result, dict) or
                        not isinstance(result.get("content"), str) or result["content"].encode() != expected):
                    raise AgyCanaryEvidenceError("probe staged content does not match retained fixed input")
        expected_reads = {
            "/run/phase-loop-review/review-instructions.md",
            "/run/phase-loop-review/review-bundle.md",
        }
        if len(calls) != 2 or {call.get("target") for call in calls} != expected_reads:
            raise AgyCanaryEvidenceError("allowed read capability is incomplete or aliased")
    elif len(calls) != 1:
        raise AgyCanaryEvidenceError("capability class does not have one uniquely paired call")
    for call in calls:
        result = call.get("result")
        if (call.get("tool") != expected_tool or
                (class_name != "allowed_read" and call.get("target") != expected_target) or
                call.get("attempt") is not True or not isinstance(result, dict) or
                result.get("execution") is not True or result.get("outcome") != expected_outcome or
                not isinstance(result.get("content"), str)):
            raise AgyCanaryEvidenceError("capability class lacks typed attempt, execution, target, or outcome")
    return {
        "class": class_name,
        "tool": expected_tool,
        "target": expected_target,
        "attempt": True,
        "execution": True,
        "result": "text",
        "outcome": expected_outcome,
        "stream": {"name": stream_name, "bytes": len(data), "sha256": _sha256(data)},
    }


def _capability_prompt(class_name: str) -> str:
    """Keep each attended action minimally scoped; stream bytes, not this text, are authority."""
    prompts = {
        "allowed_read": "Read review-instructions.md and review-bundle.md only. Reply READY.",
        "allowed_write": "Write the exact word READY to .agy-capability-write only. Reply READY.",
        "command": "Run true only. Reply READY.",
        "unsandboxed": "Run true only using the unsandboxed capability. Reply READY.",
        "inert_mcp": "Call only the inert constant-response MCP fixture. Reply READY.",
        "out_of_stage_read": "Read only /run/phase-loop-probe/out-of-stage-sentinel. Reply READY.",
        "read_url": "Read only http://127.0.0.1:8765/constant. Reply READY.",
        "execute_url": "Execute only the no-op action at http://127.0.0.1:8765/constant. Reply READY.",
    }
    return prompts[class_name]


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
        allowed_ledger_fields = base_ledger_fields | {"private_board", "minimal_home", "auth_binds", "customization_sources"}
        if not isinstance(ledger, dict) or not base_ledger_fields <= set(ledger) or not set(ledger) <= allowed_ledger_fields or ledger.get("schema") != "agy_canary_launch_ledger.v1":
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
        capture = AgyCanaryCapture(root, root_fd)
        _prepared_ledger, _prepare, authority = _require_prepare_authority(capture=capture)
        stage_binding = _read_json_at(root_fd, _STAGE_BINDING_NAME)
        stage_authority = _read_json_at(root_fd, _STAGE_AUTHORITY_NAME)
        if (set(stage_authority) != {"schema", "launch_authority_sha256", "stage_binding_sha256", "staged"} or
                stage_authority.get("schema") != "agy_canary_stage_authority.v1" or
                stage_authority.get("launch_authority_sha256") != _sha256(_canonical_json(authority)) or
                stage_authority.get("stage_binding_sha256") != _sha256(_canonical_json(stage_binding))):
            raise AgyCanaryEvidenceError("capture stage authority is malformed")
        authorized_attempts = authority["authorized_attempt_ids"]
        ledger_attempt_ids = [item.get("attempt_id") if isinstance(item, dict) else None for item in attempts]
        if ledger_attempt_ids != authorized_attempts[:len(ledger_attempt_ids)]:
            raise AgyCanaryEvidenceError("capture attempt IDs are not the authorized prefix")
        output_attempts: list[dict[str, Any]] = []
        final_text = ""
        for index, item in enumerate(attempts):
            if not isinstance(item, dict) or set(item) != {"attempt_id", "seat_key", "returncode", "argv_sha256", "stream", "diagnostic", "staged", "completed_at"}:
                raise AgyCanaryEvidenceError("capture attempt schema is malformed")
            if not isinstance(item, dict) or item.get("seat_key") != expected_seat_key:
                raise AgyCanaryEvidenceError("capture contains an unbound attempt")
            final_attempt = index == len(attempts) - 1
            if not _is_plain_int(item.get("returncode")) or (final_attempt and item.get("returncode") != 0):
                raise AgyCanaryEvidenceError("final capture attempt did not exit zero")
            if (not isinstance(item.get("attempt_id"), str) or not _is_digest(item.get("argv_sha256")) or
                    not isinstance(item.get("completed_at"), str) or not item["completed_at"]):
                raise AgyCanaryEvidenceError("capture attempt primitives are malformed")
            if item["attempt_id"] not in authorized_attempts:
                raise AgyCanaryEvidenceError("capture has an attempt outside prepare authority")
            stream = item.get("stream")
            staged = item.get("staged")
            if not isinstance(stream, dict) or not isinstance(staged, dict):
                raise AgyCanaryEvidenceError("capture launch record is incomplete")
            if set(staged) != {"review-instructions.md", "review-bundle.md"}:
                raise AgyCanaryEvidenceError("capture staged input set is not exact")
            if stage_authority.get("staged") != staged:
                raise AgyCanaryEvidenceError("capture attempt staged inputs differ from launch authority")
            diagnostic = item.get("diagnostic")
            if not isinstance(diagnostic, dict) or set(diagnostic) != {"name", "bytes", "sha256"}:
                raise AgyCanaryEvidenceError("capture diagnostic schema is malformed")
            diagnostic_bytes = _read_regular_at(root_fd, str(diagnostic.get("name", "")))
            if (not _is_plain_int(diagnostic.get("bytes")) or diagnostic["bytes"] < 0 or
                    not _is_digest(diagnostic.get("sha256")) or len(diagnostic_bytes) != diagnostic["bytes"] or
                    _sha256(diagnostic_bytes) != diagnostic["sha256"]):
                raise AgyCanaryEvidenceError("sealed diagnostic bytes drifted")
            for staged_name, staged_record in staged.items():
                if (not isinstance(staged_record, dict) or set(staged_record) != {"retained", "bytes", "sha256"} or
                        not isinstance(staged_record.get("retained"), str) or not _is_plain_int(staged_record.get("bytes")) or
                        staged_record["bytes"] < 0 or not _is_digest(staged_record.get("sha256"))):
                    raise AgyCanaryEvidenceError("capture retained input schema is malformed")
                retained = _read_regular_at(root_fd, str(staged_record.get("retained", "")))
                if len(retained) != staged_record.get("bytes") or _sha256(retained) != staged_record.get("sha256"):
                    raise AgyCanaryEvidenceError("sealed retained input bytes drifted")
            raw = _read_regular_at(root_fd, str(stream.get("name", "")))
            if (set(stream) != {"name", "bytes", "sha256"} or not isinstance(stream.get("name"), str) or
                    not _is_plain_int(stream.get("bytes")) or stream["bytes"] < 1 or not _is_digest(stream.get("sha256")) or
                    len(raw) != stream["bytes"] or _sha256(raw) != stream["sha256"]):
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
                        if final_attempt and result.get("outcome") != "success":
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
            if final_attempt:
                for name, expected in staged.items():
                    if not isinstance(expected, dict) or len(reads.get(name, [])) != 1:
                        raise AgyCanaryEvidenceError(f"accepted attempt did not read {name}")
                    matching_reads = [result for result in reads[name] if (
                        isinstance(result.get("content"), str)
                        and _sha256(result["content"].encode()) == expected.get("sha256")
                        and len(result["content"].encode()) == expected.get("bytes")
                    )]
                    if len(matching_reads) != 1:
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
        expected_summary = {
            "gemini_seat_key": pre_board.get("seat_key"),
            "gemini_seat_count": 1,
            "attempt_ids": [item.get("attempt_id") for item in attempts],
            "ledger_bytes": len(pre_board_data),
            "ledger_sha256": _sha256(pre_board_data),
            "provider_results": _provider_result_summary(root_fd=root_fd),
        }
        if private_board.get("capture") != expected_summary or not isinstance(board_payload, dict) or board_payload.get("agy_canary_capture") != expected_summary:
            raise AgyCanaryEvidenceError("private board does not bind the sealed capture summary")
        provider_results = _verified_provider_results(root_fd=root_fd)
        if provider_results.get(("gemini", expected_seat_key), {}).get("text") != final_text:
            raise AgyCanaryEvidenceError("sealed Gemini provider result does not match accepted terminal")
        _validate_private_board_payload(
            board_payload,
            expected_summary,
            require_usable=True,
            provider_results=provider_results,
        )
        proof = {
            "schema": SCHEMA_VERSION,
            "seat_key": expected_seat_key,
            "attempt_ids": [item["attempt_id"] for item in output_attempts],
            "capture_mode": mode,
            "attempts": output_attempts,
            "accepted_review_sha256": _sha256(final_text.encode()),
            "private_board_sha256": private_board["sha256"],
            "provider_results": expected_summary["provider_results"],
            "release_sha256": authority["release_sha256"],
            "wheel_binding_sha256": authority["wheel_binding_sha256"],
            "installation_sha256": authority["installation_sha256"],
            **_FINAL_GOVERNANCE_POSTURE,
        }
        if seal:
            _write_replace_at(root_fd, "agy_canary_proof.json", proof)
        return proof
    finally:
        os.close(root_fd)


def _is_reserved_private_board_name(basename: str) -> bool:
    return basename in _PRIVATE_BOARD_RESERVED_NAMES or basename.startswith(_PRIVATE_BOARD_RESERVED_PREFIXES)


def write_private_board(*, capture: AgyCanaryCapture, basename: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Create the full board payload only in the validated private root."""
    if not basename or Path(basename).name != basename:
        raise AgyCanaryEvidenceError("private board name must be a basename")
    if _is_reserved_private_board_name(basename):
        raise AgyCanaryEvidenceError("private board name collides with reserved evidence")
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    if "private_board" in ledger:
        raise AgyCanaryEvidenceError("capture private board payload is already sealed")
    summary = capture_summary(capture)
    if payload.get("agy_canary_capture") != summary:
        raise AgyCanaryEvidenceError("private board payload does not bind capture summary")
    _validate_private_board_payload(
        payload,
        summary,
        require_usable=True,
        provider_results=_verified_provider_results(root_fd=capture.root_fd),
    )
    data = _canonical_json(payload)
    _exclusive_write_at(capture.root_fd, basename, data, 0o600)
    private = {"name": basename, "bytes": len(data), "sha256": _sha256(data), "capture": summary}
    ledger["private_board"] = private
    _write_replace_at(capture.root_fd, _LEDGER_NAME, ledger)
    return {"name": basename, "bytes": len(data), "sha256": _sha256(data)}


def _validate_private_board_payload(
    payload: dict[str, Any], summary: dict[str, Any], *, require_usable: bool = False,
    provider_results: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> None:
    """Validate the usable board contract whenever a full board result is sealed.

    Minimal capture-only payloads remain available for isolated reducer fixtures;
    the CLI's production envelope always has ``board`` and therefore must meet
    this exact floor before it can become canary evidence.
    """
    if "board" not in payload:
        if require_usable:
            raise AgyCanaryEvidenceError("private board payload lacks exact usable legs")
        return
    required = {"board", "usable", "requested_seats", "delivered_seats", "shortfall", "independence", "legs", "agy_canary_capture"}
    if set(payload) != required or payload.get("agy_canary_capture") != summary:
        raise AgyCanaryEvidenceError("private board payload schema is malformed")
    if (not isinstance(payload.get("board"), str) or not payload["board"] or type(payload.get("usable")) is not bool or
            not _is_plain_int(payload.get("requested_seats")) or payload["requested_seats"] < 1 or
            not _is_plain_int(payload.get("delivered_seats")) or payload["delivered_seats"] < 0 or
            not isinstance(payload.get("legs"), list) or len(payload["legs"]) != payload["requested_seats"]):
        raise AgyCanaryEvidenceError("private board payload primitives are malformed")
    shortfall = payload["shortfall"]
    independence = payload["independence"]
    if (not isinstance(shortfall, dict) or set(shortfall) != {"requested_seats", "delivered_seats", "unfilled_seats", "natively_fillable_seats"} or
            shortfall.get("requested_seats") != payload["requested_seats"] or shortfall.get("delivered_seats") != payload["delivered_seats"] or
            not isinstance(shortfall.get("unfilled_seats"), list) or not _is_plain_int(shortfall.get("natively_fillable_seats")) or
            not isinstance(independence, dict) or set(independence) != {"level", "distinct_vendors", "seats"} or
            not isinstance(independence.get("level"), str) or not _is_plain_int(independence.get("distinct_vendors")) or not _is_plain_int(independence.get("seats"))):
        raise AgyCanaryEvidenceError("private board payload floor is malformed")
    usable_legs: list[dict[str, Any]] = []
    unfilled: list[dict[str, Any]] = []
    allowed_vendors = set(_PROVIDER_EXECUTABLES)
    for leg in payload["legs"]:
        if (not isinstance(leg, dict) or set(leg) != {"seat_key", "leg", "status", "detail", "text", "needs_native_agent"} or
                not all(isinstance(leg.get(field), str) for field in ("seat_key", "leg", "status", "text")) or
                leg.get("leg") not in allowed_vendors or leg.get("status") not in {"OK", "EMPTY", "ERROR", "TIMEOUT", "DEGRADED", "UNAVAILABLE"} or
                (leg.get("detail") is not None and not isinstance(leg.get("detail"), str)) or
                not _valid_native_agent_request(leg.get("needs_native_agent"))):
            raise AgyCanaryEvidenceError("private board leg schema is malformed")
        if leg["status"] == "OK" and leg["text"].strip():
            usable_legs.append(leg)
        else:
            unfilled.append(leg)
    if provider_results is not None:
        board_keys = [(leg["leg"], leg["seat_key"]) for leg in payload["legs"]]
        if (len(board_keys) != len(set(board_keys)) or
                len({seat_key for _provider, seat_key in board_keys}) != len(board_keys) or
                set(board_keys) != set(provider_results)):
            raise AgyCanaryEvidenceError("private board provider result set is incomplete or substituted")
        for leg in payload["legs"]:
            expected = provider_results[(leg["leg"], leg["seat_key"])]
            if any(leg[name] != expected[name] for name in ("status", "text", "detail")):
                raise AgyCanaryEvidenceError("private board leg does not match sealed provider result")
    usable_vendors = {leg["leg"] for leg in usable_legs}
    gemini_legs = [
        leg for leg in payload["legs"]
        if leg["leg"] == "gemini" and leg["seat_key"] == summary["gemini_seat_key"]
    ]
    expected_shortfall = [
        {
            "seat_key": leg["seat_key"], "leg": leg["leg"], "status": leg["status"],
            "needs_native_agent": leg["needs_native_agent"],
        }
        for leg in unfilled
    ]
    if (len(gemini_legs) != 1 or gemini_legs[0] not in usable_legs or
            payload["delivered_seats"] != len(usable_legs) or
            payload["usable"] != (len(usable_legs) >= 3) or
            independence["seats"] != len(usable_legs) or
            independence["distinct_vendors"] != len(usable_vendors) or
            shortfall["unfilled_seats"] != expected_shortfall or
            shortfall["natively_fillable_seats"] != sum(
                leg["needs_native_agent"] is not None for leg in unfilled
            ) or
            (require_usable and (not payload["usable"] or len(usable_vendors) < 3))):
        raise AgyCanaryEvidenceError("private board is below the usable independence floor")


def _valid_native_agent_request(value: Any) -> bool:
    """Accept exactly the parent serializer's public native-fill request shape."""
    if value is None:
        return True
    required = {
        "leg", "model", "mode", "reason", "detail", "instructions",
        "verdict_required", "verdict_contract",
    }
    optional = {"seat_key", "effort", "lens", "artifact_ref", "brief_ref"}
    return (
        isinstance(value, dict) and required <= set(value) <= required | optional and
        all(isinstance(value.get(name), str) and value[name] for name in required - {"verdict_required"}) and
        type(value.get("verdict_required")) is bool and
        all(isinstance(value.get(name), str) and value[name] for name in optional if name in value)
    )


def capture_summary(capture: AgyCanaryCapture) -> dict[str, Any]:
    """Return redacted ledger binding information for the public board envelope."""
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    pre_board = dict(ledger)
    pre_board.pop("private_board", None)
    data = _canonical_json(pre_board)
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise AgyCanaryEvidenceError("capture ledger has invalid attempts")
    ids = [item.get("attempt_id") for item in attempts if isinstance(item, dict)]
    if len(ids) != len(attempts) or any(not isinstance(item, str) for item in ids):
        raise AgyCanaryEvidenceError("capture ledger has invalid attempt identifiers")
    return {
        "gemini_seat_key": ledger.get("seat_key"),
        "gemini_seat_count": 1,
        "attempt_ids": ids,
        "ledger_bytes": len(data),
        "ledger_sha256": _sha256(data),
        "provider_results": _provider_result_summary(root_fd=capture.root_fd),
    }


@dataclass
class _CapabilityFixture:
    """One disposable, runnable capability environment and its explicit cleanup."""

    namespace: AgyCanaryNamespace
    root: Path
    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)
        shutil.rmtree(self.root, ignore_errors=True)


def _build_capability_fixture(*, namespace: AgyCanaryNamespace, class_name: str) -> _CapabilityFixture:
    """Construct isolated real files/routes for one capability action.

    Prompts describe the action, but this fixture is the authority for what an
    attended provider was actually able to reach.  No mutable host review tree
    or shared probe state is reused between classes.
    """
    root = Path(tempfile.mkdtemp(prefix=f"phase-loop-agy-capability-{class_name}-", dir="/tmp"))
    root.chmod(0o700)
    stage = root / "stage"
    stage.mkdir(mode=0o700)
    source_fd = os.open(namespace.stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for name in ("review-instructions.md", "review-bundle.md"):
            data, info = _reopen_at(source_fd, name)
            if not stat.S_ISREG(info.st_mode):
                raise AgyCanaryEvidenceError("capability fixture source is not regular")
            target = stage / name
            target.write_bytes(data)
            target.chmod(0o600)
    finally:
        os.close(source_fd)
    fixture_binds: list[tuple[Path, str]] = []
    if class_name == "out_of_stage_read":
        probe = root / "probe"
        probe.mkdir(mode=0o700)
        sentinel = probe / "out-of-stage-sentinel"
        sentinel.write_text("OUT_OF_STAGE\n")
        sentinel.chmod(0o600)
        fixture_binds.append((sentinel, "/run/phase-loop-probe/out-of-stage-sentinel"))
    if class_name == "inert_mcp":
        mcp = root / "inert-mcp.json"
        mcp.write_bytes(_canonical_json({"schema": "agy_inert_mcp.v1", "result": "READY"}))
        mcp.chmod(0o600)
        fixture_binds.append((mcp, "/run/phase-loop-mcp/inert.json"))
    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    if class_name in {"read_url", "execute_url"}:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - HTTP handler spelling is fixed.
                if self.path == "/constant":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"READY\n")
                else:
                    self.send_error(404)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        try:
            server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
        except OSError as exc:
            raise AgyCanaryEvidenceError("capability loopback fixture port is unavailable") from exc
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # The provider prompt target is deliberately fixed in the v2 contract;
        # the ephemeral listener proves route/no-route semantics locally and
        # remains a retained diagnostic fixture, not metadata supplied by it.
        route = root / "loopback-route.json"
        route.write_bytes(_canonical_json({"url": "http://127.0.0.1:8765/constant", "no_route": "http://127.0.0.1:8765/missing"}))
        route.chmod(0o600)
    isolated = AgyCanaryNamespace(
        stage=stage, minimal_home=namespace.minimal_home, evidence_root=namespace.evidence_root,
        provider_hostname=namespace.provider_hostname, auth_binds=namespace.auth_binds,
        resolver_source=namespace.resolver_source, resolver_sha256=namespace.resolver_sha256,
        writable_stage=class_name == "allowed_write", fixture_binds=tuple(fixture_binds),
    )
    return _CapabilityFixture(isolated, root, server, thread)


def probe_capability(
    *,
    evidence_root: Path,
    agy_executable: str = "agy",
    namespace: AgyCanaryNamespace | None = None,
) -> dict[str, Any]:
    """Run every isolated 1.1.13 action through the production namespace wrapper.

    Help output and synthetic metadata are not capability evidence.  Each row
    below is an attended, disposable sub-probe whose raw stream remains private;
    only a complete, non-aliased matrix selects stream-json as authority.
    """
    runtime = _trusted_agy_runtime()
    outer_env = namespace.outer_environment() if namespace is not None else {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    }
    if agy_executable not in {"agy", str(runtime.source)}:
        raise AgyCanaryEvidenceError("agy probe executable must be the trusted agy path")
    root, root_fd = _validate_private_root(evidence_root)
    try:
        runtime.revalidate()
        version_proc = subprocess.run([str(runtime.source), "--version"], capture_output=True, text=True, timeout=15, check=False, env=outer_env)
        runtime.revalidate()
        help_proc = subprocess.run([str(runtime.source), "--help"], capture_output=True, text=True, timeout=15, check=False, env=outer_env)
        version = (version_proc.stdout or version_proc.stderr).strip()
        help_text = (help_proc.stdout or help_proc.stderr)
        if version_proc.returncode != 0 or help_proc.returncode != 0:
            raise AgyCanaryEvidenceError("agy version probe failed")
        if version != "1.1.13" or "stream-json" not in help_text:
            value = {"schema": _CAPABILITY_PROBE_SCHEMA, "agy_version": version, "agy_runtime": _agy_runtime_record(runtime, version), "help_sha256": _sha256(help_text.encode()), "mode": None, "complete": False, "reason": "unsupported_agy_1_1_13_capture_surface", "classes": []}
            _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
            return value
        if namespace is None:
            value = {"schema": _CAPABILITY_PROBE_SCHEMA, "agy_version": version, "agy_runtime": _agy_runtime_record(runtime, version), "help_sha256": _sha256(help_text.encode()), "mode": None, "complete": False, "reason": "production_namespace_required", "classes": []}
            _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
            return value
        namespace_self_test(namespace=namespace)
        staged: dict[str, dict[str, Any]] = {}
        stage_fd = os.open(namespace.stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            for name in ("review-instructions.md", "review-bundle.md"):
                data, info = _reopen_at(stage_fd, name)
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                    raise AgyCanaryEvidenceError("capability probe stage is not private")
                retained_name = f"agy-capability-stage-{name}"
                _exclusive_write_at(root_fd, retained_name, data, 0o600)
                staged[name] = {"name": retained_name, "bytes": len(data), "sha256": _sha256(data)}
        finally:
            os.close(stage_fd)
        rows: list[dict[str, Any]] = []
        for capability in _CAPABILITY_CLASSES:
            class_name = capability[0]
            fixture = _build_capability_fixture(namespace=namespace, class_name=class_name)
            try:
                namespace_self_test(namespace=fixture.namespace)
                command = [
                    "agy", "--output-format", "stream-json", "--sandbox", "--add-dir",
                    "/run/phase-loop-review", "--print-timeout", "30s", "-p",
                    _capability_prompt(class_name),
                ]
                proc = subprocess.run(
                    fixture.namespace.command([runtime.destination, *command[1:]], agy_runtime=runtime), capture_output=True, text=True,
                    timeout=90, check=False, env=outer_env,
                )
                stream = (proc.stdout or "").encode()
                stream_name = f"agy-capability-{class_name}.jsonl"
                _exclusive_write_at(root_fd, stream_name, stream, 0o600)
                if proc.returncode != 0:
                    raise AgyCanaryEvidenceError("capability sub-probe process failed")
                rows.append(_reduce_capability_class(
                    capability=capability, data=stream, namespace=fixture.namespace,
                    stream_name=stream_name,
                ))
            except AgyCanaryEvidenceError as exc:
                value = {
                    "schema": _CAPABILITY_PROBE_SCHEMA, "agy_version": version, "agy_runtime": _agy_runtime_record(runtime, version),
                    "help_sha256": _sha256(help_text.encode()), "mode": None,
                    "complete": False,
                    "reason": f"stream_json_capability_unproven:{class_name}:{type(exc).__name__}",
                "classes": rows, "staged": staged,
                }
                _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
                return value
            finally:
                fixture.close()
        if [row["class"] for row in rows] != [item[0] for item in _CAPABILITY_CLASSES]:
            raise AgyCanaryEvidenceError("capability matrix is incomplete or aliased")
        value = {
            "schema": _CAPABILITY_PROBE_SCHEMA, "agy_version": version, "agy_runtime": _agy_runtime_record(runtime, version),
            "help_sha256": _sha256(help_text.encode()), "mode": "stream_json",
            "complete": True, "classes": rows, "staged": staged,
        }
        _exclusive_write_at(root_fd, _PROBE_NAME, _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def _system_interpreter_authority() -> dict[str, Any]:
    """Seal the fixed root-owned system Python without executing it."""
    selector = Path("/usr/bin/python3")
    try:
        executable = selector.resolve(strict=True)
        data, info = _read_regular_path(executable)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("bootstrap requires canonical system Python") from exc
    mode = stat.S_IMODE(info.st_mode)
    if (not sys.platform.startswith("linux") or not stat.S_ISREG(info.st_mode) or
            info.st_uid != 0 or mode & (stat.S_IWGRP | stat.S_IWOTH) or
            not mode & stat.S_IXUSR or not os.access(executable, os.X_OK)):
        raise AgyCanaryEvidenceError("canonical system Python is not root-owned and immutable")
    return {
        "schema": "agy_canary_interpreter_authority.v1",
        "selector": str(selector), "path": str(executable),
        "dev": info.st_dev, "inode": info.st_ino, "mode": mode,
        "uid": info.st_uid, "size": info.st_size, "sha256": _sha256(data),
    }


def _validate_interpreter_authority(
    value: Any, *, revalidate: bool,
) -> dict[str, Any]:
    required = {
        "schema", "selector", "path", "dev", "inode", "mode", "uid", "size", "sha256",
    }
    if (not isinstance(value, dict) or set(value) != required or
            value.get("schema") != "agy_canary_interpreter_authority.v1" or
            value.get("selector") != "/usr/bin/python3" or
            not isinstance(value.get("path"), str) or not Path(value["path"]).is_absolute() or
            any(not _is_plain_int(value.get(name)) or value[name] < 0 for name in (
                "dev", "inode", "mode", "uid", "size"
            )) or value["uid"] != 0 or value["mode"] & (stat.S_IWGRP | stat.S_IWOTH) or
            not value["mode"] & stat.S_IXUSR or not _is_digest(value.get("sha256"))):
        raise AgyCanaryEvidenceError("interpreter authority is malformed")
    if revalidate and _system_interpreter_authority() != value:
        raise AgyCanaryEvidenceError("canonical system Python authority drifted")
    return value


def _canonical_bash() -> Path:
    bash = Path("/usr/bin/bash").resolve(strict=True)
    if not bash.is_file() or not os.access(bash, os.X_OK):
        raise AgyCanaryEvidenceError("bootstrap attestation requires canonical /usr/bin/bash")
    return bash


def _canonical_bwrap() -> Path:
    """Resolve only the fixed Bubblewrap authority used by capture namespaces."""
    bwrap = Path("/usr/bin/bwrap")
    try:
        info = bwrap.lstat()
    except FileNotFoundError as exc:
        raise AgyCanaryEvidenceError("capture requires canonical /usr/bin/bwrap") from exc
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or
            not os.access(bwrap, os.X_OK)):
        raise AgyCanaryEvidenceError("capture requires canonical /usr/bin/bwrap")
    return bwrap


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


_UV_WORKSPACE_ROOT = Path("/mnt/workspace")
_BOOTSTRAP_LOCAL_SOURCE_SEAMS = (
    "bootstrap.local.sh", "hooks/post-bootstrap.local.sh",
)
_TREE_SNAPSHOT_SCHEMA = "agy_canary_tree_snapshot.v1"
_TREE_SANDBOX_SCHEMA = "agy_canary_tree_bwrap.v1"
# Stable Linux UAPI values from asm-generic/fcntl.h and linux/fcntl.h.
_LINUX_MEMFD_SEAL_ABI = {
    "F_ADD_SEALS": 1033,
    "F_GET_SEALS": 1034,
    "F_SEAL_SEAL": 0x1,
    "F_SEAL_SHRINK": 0x2,
    "F_SEAL_GROW": 0x4,
    "F_SEAL_WRITE": 0x8,
}


@dataclass(frozen=True)
class _TreeSnapshotEntry:
    path: str
    mode: str
    oid: str
    fd: int | None = None
    link_target: str | None = None


@dataclass
class _GitTreeSnapshot:
    authority: dict[str, Any]
    entries: tuple[_TreeSnapshotEntry, ...]

    @property
    def fds(self) -> tuple[int, ...]:
        return tuple(entry.fd for entry in self.entries if entry.fd is not None)

    def close(self) -> None:
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass


def _linux_memfd_seal_abi() -> dict[str, int]:
    """Return Linux's stable fcntl seal UAPI, rejecting conflicting bindings."""
    if (
        not sys.platform.startswith("linux")
        or fcntl is None
        or not hasattr(os, "memfd_create")
        or not getattr(os, "MFD_ALLOW_SEALING", 0)
        or not getattr(os, "MFD_CLOEXEC", 0)
    ):
        raise AgyCanaryEvidenceError("tracked snapshot requires Linux sealed memfds")
    for name, expected in _LINUX_MEMFD_SEAL_ABI.items():
        exposed = getattr(fcntl, name, None)
        if exposed is not None and exposed != expected:
            raise AgyCanaryEvidenceError("Python fcntl seal constants conflict with Linux UAPI")
    return dict(_LINUX_MEMFD_SEAL_ABI)


def _uv_directory_identity(path: Path, *, uid: int) -> dict[str, Any]:
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("canonical uv store directory is unavailable") from exc
    mode = stat.S_IMODE(info.st_mode)
    if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
            info.st_uid != uid or mode & stat.S_IWOTH):
        raise AgyCanaryEvidenceError("canonical uv store directory is unsafe")
    return {
        "path": str(path), "resolved": str(resolved), "dev": info.st_dev,
        "inode": info.st_ino, "mode": mode, "uid": info.st_uid,
    }


def _uv_store_authority(
    *, account_home: Path, workspace_root: Path = _UV_WORKSPACE_ROOT,
) -> dict[str, Any]:
    """Seal the exact home/workspace storage policy committed in bootstrap.sh."""
    home = account_home.resolve(strict=True)
    uid = home.stat().st_uid
    workspace: dict[str, Any] | None = None
    if workspace_root.is_dir():
        try:
            selector_info = workspace_root.lstat()
            resolved_root = workspace_root.resolve(strict=True)
            root_info = resolved_root.lstat()
        except (FileNotFoundError, OSError) as exc:
            raise AgyCanaryEvidenceError("canonical uv workspace root is unavailable") from exc
        selector_mode = stat.S_IMODE(selector_info.st_mode)
        root_mode = stat.S_IMODE(root_info.st_mode)
        if (not stat.S_ISDIR(root_info.st_mode) or resolved_root.resolve(strict=True) != resolved_root or
                root_info.st_uid != uid or root_mode & stat.S_IWOTH or
                (stat.S_ISLNK(selector_info.st_mode) and selector_info.st_uid != 0) or
                (not stat.S_ISLNK(selector_info.st_mode) and not stat.S_ISDIR(selector_info.st_mode))):
            raise AgyCanaryEvidenceError("canonical uv workspace root is unsafe")
        data_identity = _uv_directory_identity(workspace_root / "uv-data", uid=uid)
        if Path(data_identity["resolved"]) != resolved_root / "uv-data":
            raise AgyCanaryEvidenceError("canonical uv workspace data root is indirect")
        workspace = {
            "selector": str(workspace_root), "resolved": str(resolved_root),
            "selector_dev": selector_info.st_dev, "selector_inode": selector_info.st_ino,
            "selector_mode": selector_mode, "selector_uid": selector_info.st_uid,
            "link_target": os.readlink(workspace_root) if stat.S_ISLNK(selector_info.st_mode) else None,
            "dev": root_info.st_dev, "inode": root_info.st_ino,
            "mode": root_mode, "uid": root_info.st_uid,
            "data": data_identity,
        }
        paths = {
            "tool": workspace_root / "uv-data" / "tools",
            "bin": home / ".local" / "bin",
            "cache": workspace_root / "uv-cache",
            "python": workspace_root / "uv-data" / "python",
        }
        policy = "workspace"
    else:
        paths = {
            "tool": home / ".local" / "share" / "uv" / "tools",
            "bin": home / ".local" / "bin",
            "cache": home / ".cache" / "uv",
            "python": home / ".local" / "share" / "uv" / "python",
        }
        policy = "home"
    directories = {
        name: _uv_directory_identity(path, uid=uid) for name, path in paths.items()
    }
    if workspace is not None:
        resolved_root = Path(workspace["resolved"])
        expected_resolved = {
            "tool": resolved_root / "uv-data" / "tools",
            "cache": resolved_root / "uv-cache",
            "python": resolved_root / "uv-data" / "python",
        }
        for name, expected in expected_resolved.items():
            if Path(directories[name]["resolved"]) != expected:
                raise AgyCanaryEvidenceError("canonical uv workspace directory escaped its root")
    elif any(Path(row["resolved"]) != Path(row["path"]) for row in directories.values()):
        raise AgyCanaryEvidenceError("canonical home uv store directory is indirect")
    return {
        "schema": "agy_canary_uv_store_authority.v1", "policy": policy,
        "account_home": str(home), "workspace": workspace,
        "directories": directories,
    }


def _validate_uv_store_authority(
    value: Any, *, revalidate: bool, account_home: Path | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    directory_fields = {"path", "resolved", "dev", "inode", "mode", "uid"}
    workspace_fields = {
        "selector", "resolved", "selector_dev", "selector_inode", "selector_mode",
        "selector_uid", "link_target", "dev", "inode", "mode", "uid",
        "data",
    }
    directories = value.get("directories") if isinstance(value, dict) else None
    workspace = value.get("workspace") if isinstance(value, dict) else None
    if (not isinstance(value, dict) or set(value) != {
            "schema", "policy", "account_home", "workspace", "directories"
    } or
            value.get("schema") != "agy_canary_uv_store_authority.v1" or
            value.get("policy") not in {"home", "workspace"} or
            not isinstance(value.get("account_home"), str) or
            not Path(value["account_home"]).is_absolute() or
            not isinstance(directories, dict) or set(directories) != {
                "tool", "bin", "cache", "python"
            } or any(
                not isinstance(row, dict) or set(row) != directory_fields or
                not isinstance(row.get("path"), str) or not Path(row["path"]).is_absolute() or
                not isinstance(row.get("resolved"), str) or not Path(row["resolved"]).is_absolute() or
                any(not _is_plain_int(row.get(name)) or row[name] < 0 for name in (
                    "dev", "inode", "mode", "uid"
                )) or row["mode"] > 0o7777 or row["mode"] & stat.S_IWOTH
                for row in directories.values()
            ) or (value["policy"] == "home" and workspace is not None) or
            (value["policy"] == "workspace" and (
                not isinstance(workspace, dict) or set(workspace) != workspace_fields or
                not isinstance(workspace.get("selector"), str) or
                not Path(workspace["selector"]).is_absolute() or
                not isinstance(workspace.get("resolved"), str) or
                not Path(workspace["resolved"]).is_absolute() or
                not isinstance(workspace.get("data"), dict) or
                set(workspace["data"]) != directory_fields or
                not isinstance(workspace["data"].get("path"), str) or
                not Path(workspace["data"]["path"]).is_absolute() or
                not isinstance(workspace["data"].get("resolved"), str) or
                not Path(workspace["data"]["resolved"]).is_absolute() or
                any(not _is_plain_int(workspace["data"].get(name)) or
                    workspace["data"][name] < 0 for name in ("dev", "inode", "mode", "uid")) or
                workspace["data"]["mode"] > 0o7777 or
                workspace["data"]["mode"] & stat.S_IWOTH or
                workspace.get("link_target") is not None and
                not isinstance(workspace.get("link_target"), str) or
                any(not _is_plain_int(workspace.get(name)) or workspace[name] < 0 for name in (
                    "selector_dev", "selector_inode", "selector_mode", "selector_uid",
                    "dev", "inode", "mode", "uid",
                ))))):
        raise AgyCanaryEvidenceError("uv store authority is malformed")
    if account_home is not None and Path(value["account_home"]) != account_home.resolve(strict=True):
        raise AgyCanaryEvidenceError("uv store authority account home drifted")
    if workspace_root is not None:
        expected_selector = str(workspace_root)
        if value["policy"] != ("workspace" if workspace_root.is_dir() else "home") or (
                value["policy"] == "workspace" and workspace["selector"] != expected_selector):
            raise AgyCanaryEvidenceError("uv store authority workspace policy drifted")
    if revalidate:
        selector = (
            Path(workspace["selector"]) if value["policy"] == "workspace"
            else workspace_root if workspace_root is not None else Path(value["account_home"]) / ".absent-workspace"
        )
        if _uv_store_authority(
            account_home=Path(value["account_home"]), workspace_root=selector,
        ) != value:
            raise AgyCanaryEvidenceError("canonical uv store authority drifted")
    return value


def _uv_environment(
    *, uv_executable: Path, interpreter_authority: dict[str, Any],
    uv_store_authority: dict[str, Any],
) -> dict[str, str]:
    authority = _validate_uv_store_authority(uv_store_authority, revalidate=True)
    interpreter = _validate_interpreter_authority(interpreter_authority, revalidate=True)
    return {
        "HOME": authority["account_home"],
        "PATH": str(uv_executable.parent) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_TOOL_DIR": authority["directories"]["tool"]["path"],
        "UV_TOOL_BIN_DIR": authority["directories"]["bin"]["path"],
        "UV_CACHE_DIR": authority["directories"]["cache"]["path"],
        "UV_PYTHON_INSTALL_DIR": authority["directories"]["python"]["path"],
        "UV_PYTHON": interpreter["path"],
        "UV_PYTHON_DOWNLOADS": "never",
    }


def _validate_uv_environment(
    environment: Any, *, uv_executable: Path,
    interpreter_authority: dict[str, Any], uv_store_authority: dict[str, Any],
) -> dict[str, str]:
    expected = _uv_environment(
        uv_executable=uv_executable, interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority,
    )
    if environment != expected:
        raise AgyCanaryEvidenceError("canonical uv environment is malformed")
    return environment


def _uv_tool_dir(
    uv_executable: Path, *, environment: dict[str, str],
    interpreter_authority: dict[str, Any], uv_store_authority: dict[str, Any],
) -> Path:
    environment = _validate_uv_environment(
        environment, uv_executable=uv_executable,
        interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority,
    )
    proc = subprocess.run(
        [str(uv_executable), "tool", "dir"], capture_output=True, text=True,
        timeout=30, check=False, env=environment,
    )
    tool_dir = Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
    expected = Path(uv_store_authority["directories"]["tool"]["path"])
    if (tool_dir is None or tool_dir != expected or not tool_dir.is_absolute() or
            not tool_dir.is_dir() or tool_dir.is_symlink()):
        raise AgyCanaryEvidenceError("canonical uv tool directory is unavailable")
    _validate_uv_store_authority(uv_store_authority, revalidate=True)
    return tool_dir


def _uv_registry_provenance(*, tool_dir: Path, version: str) -> dict[str, str]:
    """Bind uv's registry-tool receipt; registry installs have no direct_url.json."""
    receipt = tool_dir / "phase-loop-runtime" / "uv-receipt.toml"
    try:
        raw, info = _read_regular_path(receipt)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("canonical uv registry receipt is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise AgyCanaryEvidenceError("canonical uv registry receipt is unsafe")
    match = re.search(
        rb'^requirements = \[\{ name = "phase-loop-runtime", specifier = "==([^"\r\n]+)" \}\]$',
        raw, flags=re.MULTILINE,
    )
    if match is None or match.group(1).decode("ascii", errors="strict") != version:
        raise AgyCanaryEvidenceError("canonical uv registry receipt does not pin phase-loop version")
    return {
        "schema": "uv_registry_receipt.v1", "requirement": f"phase-loop-runtime=={version}",
        "receipt_sha256": _sha256(raw),
    }


def _installed_phase_loop_identity(
    *, interpreter_authority: dict[str, Any], uv_store_authority: dict[str, Any],
    uv_environment: dict[str, str], uv_executable: Path | None = None,
) -> dict[str, Any]:
    """Inspect only uv's canonical managed entrypoint, not an ambient PATH shim."""
    authority = _validate_interpreter_authority(interpreter_authority, revalidate=True)
    uv = _canonical_uv() if uv_executable is None else uv_executable.resolve(strict=True)
    store_authority = _validate_uv_store_authority(uv_store_authority, revalidate=True)
    tool_dir = _uv_tool_dir(
        uv, environment=uv_environment, interpreter_authority=authority,
        uv_store_authority=store_authority,
    )
    try:
        environment_root = (tool_dir / "phase-loop-runtime").resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("phase-loop uv environment is unavailable") from exc
    script = tool_dir / "phase-loop-runtime" / "bin" / "phase-loop"
    if not script.is_file() or script.is_symlink():
        raise AgyCanaryEvidenceError("phase-loop console script is not installed in canonical uv tool dir")
    interpreter = environment_root / "bin" / "python"
    if not interpreter.is_absolute() or not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise AgyCanaryEvidenceError("phase-loop interpreter is not canonical")
    interpreter_source = interpreter.resolve(strict=True)
    if interpreter_source != Path(authority["path"]):
        raise AgyCanaryEvidenceError("phase-loop interpreter differs from sealed system Python")
    _validate_interpreter_authority(authority, revalidate=True)
    roots = sorted(
        (*environment_root.glob("lib/python*/site-packages"),
         *environment_root.glob("lib64/python*/site-packages")),
        key=lambda path: path.as_posix(),
    )
    matches = [
        root for root in roots
        if root.is_dir() and not root.is_symlink() and root.resolve() == root and
        (root / "phase_loop_runtime-0.7.14.dist-info").is_dir()
    ]
    if len(matches) != 1:
        raise AgyCanaryEvidenceError("phase-loop installed distribution root is not unique")
    root = matches[0]
    module = root / "phase_loop_runtime" / "__init__.py"
    if not module.is_relative_to(root):
        raise AgyCanaryEvidenceError("phase-loop module ownership is invalid")
    package_root = module.parent
    dist_info = root / "phase_loop_runtime-0.7.14.dist-info"
    record = dist_info / "RECORD"
    try:
        script_bytes, _script_info = _read_regular_path(script)
        interpreter_bytes, _interpreter_info = _read_regular_path(interpreter_source)
        record_bytes, _record_info = _read_regular_path(record)
        metadata_bytes, _metadata_info = _read_regular_path(dist_info / "METADATA")
        _module_bytes, _module_info = _read_regular_path(module)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("phase-loop installed content is unavailable") from exc
    if (re.findall(rb"^Name: ([^\r\n]+)$", metadata_bytes, flags=re.MULTILINE) !=
            [b"phase-loop-runtime"] or
            re.findall(rb"^Version: ([^\r\n]+)$", metadata_bytes, flags=re.MULTILINE) !=
            [b"0.7.14"]):
        raise AgyCanaryEvidenceError("phase-loop installed metadata identity is invalid")
    _validate_interpreter_authority(authority, revalidate=True)
    return {
        "uv_executable": str(uv), "uv_tool_dir": str(tool_dir),
        "console_script": str(script), "interpreter": str(interpreter_source),
        "version": "0.7.14", "distribution_root": str(root),
        "module_origin": str(module), "environment_root": str(environment_root),
        "console_script_sha256": _sha256(script_bytes),
        "interpreter_sha256": _sha256(interpreter_bytes),
        "interpreter_authority": authority,
        "uv_store_authority": store_authority,
        "package_tree_sha256": _runtime_tree_sha256(package_root),
        "record_sha256": _sha256(record_bytes),
        "provenance": _uv_registry_provenance(tool_dir=tool_dir, version="0.7.14"),
    }


_GIT_EXECUTABLE = Path("/usr/bin/git")
_GIT_EXEC_PATH = Path("/usr/lib/git-core")
_MAX_TRUSTED_GIT_BYTES = 16 * 1024 * 1024
_GITHUB_EXECUTABLE = Path("/usr/bin/gh")
_MAX_TRUSTED_GITHUB_BYTES = 64 * 1024 * 1024
_GITHUB_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class _GitExecutableAuthority:
    identity: tuple[int, ...]
    sha256: str
    exec_path_identity: tuple[int, ...]
    path_identity: tuple[int, ...]


_SEALED_GIT_AUTHORITY: _GitExecutableAuthority | None = None


@dataclass(frozen=True)
class _GitHubExecutableAuthority:
    identity: tuple[int, ...]
    sha256: str
    path_identity: tuple[int, ...]


_SEALED_GITHUB_AUTHORITY: _GitHubExecutableAuthority | None = None


@dataclass(frozen=True)
class _SshAgentAuthority:
    path: str
    socket_identity: tuple[int, ...]
    parent_identities: tuple[tuple[str, tuple[int, ...]], ...]


_SEALED_SSH_AGENT_AUTHORITIES: dict[str, _SshAgentAuthority] = {}
_SEALED_SSH_AGENT_FDS: dict[str, int] = {}


def _trusted_root_directory_identity(path: Path) -> tuple[int, ...]:
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if (
        path.resolve(strict=True) != path
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise AgyCanaryEvidenceError("canonical Git helper directory is unsafe")
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def _canonical_git_executable() -> Path:
    global _SEALED_GIT_AUTHORITY
    try:
        selector = _GIT_EXECUTABLE.lstat()
        if selector.st_size > _MAX_TRUSTED_GIT_BYTES:
            raise AgyCanaryEvidenceError("canonical Git executable exceeds authority cap")
        data, reopened = _read_bounded_regular_path(
            _GIT_EXECUTABLE, limit=_MAX_TRUSTED_GIT_BYTES,
        )
        authority = _GitExecutableAuthority(
            identity=_stable_file_identity(reopened),
            sha256=_sha256(data),
            exec_path_identity=_trusted_root_directory_identity(_GIT_EXEC_PATH),
            path_identity=_trusted_root_directory_identity(Path("/usr/bin")),
        )
    except (FileNotFoundError, OSError, AgyCanaryEvidenceError) as exc:
        raise AgyCanaryEvidenceError("canonical /usr/bin/git authority is unavailable") from exc
    mode = stat.S_IMODE(reopened.st_mode)
    if (
        _stable_file_identity(selector) != authority.identity
        or not stat.S_ISREG(reopened.st_mode)
        or reopened.st_uid != 0
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not mode & stat.S_IXUSR
        or not os.access(_GIT_EXECUTABLE, os.X_OK)
    ):
        raise AgyCanaryEvidenceError("canonical /usr/bin/git authority is unsafe")
    if _SEALED_GIT_AUTHORITY is None:
        _SEALED_GIT_AUTHORITY = authority
    elif authority != _SEALED_GIT_AUTHORITY:
        raise AgyCanaryEvidenceError("canonical /usr/bin/git authority drifted")
    return _GIT_EXECUTABLE


def _canonical_github_executable() -> Path:
    global _SEALED_GITHUB_AUTHORITY
    try:
        selector = _GITHUB_EXECUTABLE.lstat()
        if selector.st_size > _MAX_TRUSTED_GITHUB_BYTES:
            raise AgyCanaryEvidenceError(
                "canonical GitHub executable exceeds authority cap"
            )
        data, reopened = _read_bounded_regular_path(
            _GITHUB_EXECUTABLE, limit=_MAX_TRUSTED_GITHUB_BYTES,
        )
        authority = _GitHubExecutableAuthority(
            identity=_stable_file_identity(reopened),
            sha256=_sha256(data),
            path_identity=_trusted_root_directory_identity(Path("/usr/bin")),
        )
    except (FileNotFoundError, OSError, AgyCanaryEvidenceError) as exc:
        raise AgyCanaryEvidenceError(
            "canonical /usr/bin/gh authority is unavailable"
        ) from exc
    mode = stat.S_IMODE(reopened.st_mode)
    if (
        _stable_file_identity(selector) != authority.identity
        or not stat.S_ISREG(reopened.st_mode)
        or reopened.st_uid != 0
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not mode & stat.S_IXUSR
        or not os.access(_GITHUB_EXECUTABLE, os.X_OK)
    ):
        raise AgyCanaryEvidenceError("canonical /usr/bin/gh authority is unsafe")
    if _SEALED_GITHUB_AUTHORITY is None:
        _SEALED_GITHUB_AUTHORITY = authority
    elif authority != _SEALED_GITHUB_AUTHORITY:
        raise AgyCanaryEvidenceError("canonical /usr/bin/gh authority drifted")
    return _GITHUB_EXECUTABLE


def _ssh_agent_parent_chain(path: Path) -> tuple[tuple[str, tuple[int, ...]], ...]:
    chain: list[tuple[str, tuple[int, ...]]] = []
    current_uid = os.getuid()
    for parent in reversed(path.parent.parents):
        info = parent.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if (
            parent.is_symlink()
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, current_uid}
            or (
                mode & (stat.S_IWGRP | stat.S_IWOTH)
                and not (info.st_uid == 0 and mode & stat.S_ISVTX)
            )
        ):
            raise AgyCanaryEvidenceError("Git SSH agent parent authority is unsafe")
        chain.append((str(parent), (
            info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
        )))
    parent = path.parent
    info = parent.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != current_uid
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise AgyCanaryEvidenceError("Git SSH agent direct parent authority is unsafe")
    chain.append((str(parent), (
        info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
    )))
    return tuple(chain)


def _canonical_ssh_auth_sock(value: str) -> Path:
    socket_path = Path(value)
    if (
        not socket_path.is_absolute()
        or value != os.path.normpath(value)
        or any(part in {"", ".", ".."} for part in socket_path.parts[1:])
    ):
        raise AgyCanaryEvidenceError("Git SSH agent path is noncanonical")
    try:
        if socket_path.resolve(strict=True) != socket_path:
            raise AgyCanaryEvidenceError("Git SSH agent path is noncanonical")
        parents_before = _ssh_agent_parent_chain(socket_path)
        socket_before = socket_path.lstat()
        parents_after = _ssh_agent_parent_chain(socket_path)
        socket_after = socket_path.lstat()
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("Git SSH agent authority is unavailable") from exc
    mode = stat.S_IMODE(socket_after.st_mode)
    if (
        parents_before != parents_after
        or _stable_file_identity(socket_before) != _stable_file_identity(socket_after)
        or socket_path.is_symlink()
        or not stat.S_ISSOCK(socket_after.st_mode)
        or socket_after.st_uid != os.getuid()
        or mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise AgyCanaryEvidenceError("Git SSH agent authority is unsafe")
    o_path = getattr(os, "O_PATH", 0)
    if not o_path:
        raise AgyCanaryEvidenceError("Git SSH agent descriptor authority is unavailable")
    authority_fd: int | None = None
    try:
        authority_fd = os.open(
            socket_path, o_path | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        descriptor_info = os.fstat(authority_fd)
    except OSError as exc:
        if authority_fd is not None:
            os.close(authority_fd)
        raise AgyCanaryEvidenceError("Git SSH agent descriptor authority is unavailable") from exc
    assert authority_fd is not None
    if _stable_file_identity(descriptor_info) != _stable_file_identity(socket_after):
        os.close(authority_fd)
        raise AgyCanaryEvidenceError("Git SSH agent authority is unsafe")
    authority = _SshAgentAuthority(
        path=value, socket_identity=_stable_file_identity(descriptor_info),
        parent_identities=parents_after,
    )
    sealed = _SEALED_SSH_AGENT_AUTHORITIES.get(value)
    if sealed is None:
        _SEALED_SSH_AGENT_AUTHORITIES[value] = authority
        _SEALED_SSH_AGENT_FDS[value] = authority_fd
    else:
        os.close(authority_fd)
        try:
            sealed_descriptor = os.fstat(_SEALED_SSH_AGENT_FDS[value])
        except OSError as exc:
            raise AgyCanaryEvidenceError("Git SSH agent sealed descriptor is unavailable") from exc
        if _stable_file_identity(sealed_descriptor) != sealed.socket_identity:
            raise AgyCanaryEvidenceError("Git SSH agent sealed descriptor drifted")
    if sealed is not None and sealed != authority:
        raise AgyCanaryEvidenceError("Git SSH agent authority drifted")
    return socket_path


def _git_environment() -> dict[str, str]:
    environment = {
        "HOME": str(_account_home()),
        "PATH": "/usr/bin",
        "LC_ALL": "C",
        "GIT_EXEC_PATH": str(_GIT_EXEC_PATH),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": (
            "/usr/bin/ssh -F /dev/null -oBatchMode=yes "
            "-oStrictHostKeyChecking=yes"
        ),
    }
    auth_sock = os.environ.get("SSH_AUTH_SOCK")
    if auth_sock is not None:
        environment["SSH_AUTH_SOCK"] = str(_canonical_ssh_auth_sock(auth_sock))
    return environment


def _git_run(
    repo: Path, *args: str, text: bool = False, input: bytes | str | None = None,
) -> subprocess.CompletedProcess[Any]:
    git = _canonical_git_executable()
    return subprocess.run(
        [
            str(git), "--no-replace-objects", f"--exec-path={_GIT_EXEC_PATH}",
            "-c", "core.hooksPath=/dev/null",
            "-C", str(repo), *args,
        ],
        capture_output=True, text=text, check=False, env=_git_environment(), input=input,
    )


def _github_run(*args: str) -> subprocess.CompletedProcess[str]:
    github = _canonical_github_executable()
    try:
        result = subprocess.run(
            [str(github), *args],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=_GITHUB_TIMEOUT_SECONDS,
            env={
                "HOME": str(_account_home()),
                "PATH": "/usr/bin",
                "LC_ALL": "C",
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise AgyCanaryEvidenceError("GitHub client command timed out") from exc
    if result.returncode != 0:
        raise AgyCanaryEvidenceError("GitHub client command failed")
    return result


def _allowed_git_config_name(name: str) -> bool:
    lowered = name.lower()
    if lowered in {
        "core.repositoryformatversion", "core.filemode", "core.bare",
        "core.logallrefupdates", "core.worktree", "core.hookspath",
        "extensions.worktreeconfig", "user.name", "user.email",
    }:
        return True
    parts = lowered.split(".")
    return len(parts) >= 3 and (
        (parts[0] == "remote" and parts[-1] in {"url", "fetch"})
        or (parts[0] == "branch" and parts[-1] in {"remote", "merge"})
        or (parts[0] == "submodule" and parts[-1] in {"active", "url"})
    )


def _validate_git_repository_authority(
    repo: Path, *, require_inert_exclude: bool = False,
) -> None:
    canonical = repo.resolve(strict=True)
    metadata = _git_run(
        canonical, "rev-parse", "--path-format=absolute", "--show-toplevel",
        "--git-dir", "--git-common-dir", "--is-shallow-repository", text=True,
    )
    lines = metadata.stdout.splitlines() if metadata.returncode == 0 else []
    if len(lines) != 4:
        raise AgyCanaryEvidenceError("Git repository authority is unavailable")
    try:
        top_level = Path(lines[0]).resolve(strict=True)
        git_dir = Path(lines[1]).resolve(strict=True)
        common_dir = Path(lines[2]).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AgyCanaryEvidenceError("Git repository authority is malformed") from exc
    if (
        top_level != canonical
        or not git_dir.is_dir()
        or not common_dir.is_dir()
        or lines[3] != "false"
    ):
        raise AgyCanaryEvidenceError("Git repository authority is unsafe")
    authority_paths = _git_run(
        canonical, "rev-parse", "--path-format=absolute",
        "--git-path", "info/grafts", "--git-path", "objects/info/alternates",
        "--git-path", "shallow", "--git-path", "info/exclude", text=True,
    )
    paths = authority_paths.stdout.splitlines() if authority_paths.returncode == 0 else []
    if len(paths) != 4:
        raise AgyCanaryEvidenceError("Git repository authority paths are unavailable")
    for value in paths[:3]:
        try:
            Path(value).lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise AgyCanaryEvidenceError("Git repository authority path is unreadable") from exc
        raise AgyCanaryEvidenceError("Git repository has active graft, alternate, or shallow authority")
    exclude = Path(paths[3])
    try:
        exclude_stat = exclude.lstat()
    except FileNotFoundError:
        exclude_stat = None
    except OSError as exc:
        raise AgyCanaryEvidenceError("Git repository info/exclude authority is unreadable") from exc
    if exclude_stat is not None:
        if (
            not stat.S_ISREG(exclude_stat.st_mode)
            or exclude.is_symlink()
            or exclude_stat.st_size > _MAX_FULL_STAGED_READ_BYTES
        ):
            raise AgyCanaryEvidenceError("Git repository info/exclude authority is unsafe")
        try:
            exclude_bytes, exclude_reopened = _read_bounded_regular_path(
                exclude, limit=_MAX_FULL_STAGED_READ_BYTES,
            )
            if (
                _stable_file_identity(exclude_reopened)
                != _stable_file_identity(exclude_stat)
                or len(exclude_bytes) > _MAX_FULL_STAGED_READ_BYTES
            ):
                raise AgyCanaryEvidenceError("Git repository info/exclude authority is unsafe")
            exclude_bytes.decode("utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise AgyCanaryEvidenceError(
                "Git repository info/exclude authority is unreadable"
            ) from exc
        except AgyCanaryEvidenceError as exc:
            raise AgyCanaryEvidenceError(
                "Git repository info/exclude authority is unsafe"
            ) from exc
        try:
            exclude_after = exclude.lstat()
        except OSError as exc:
            raise AgyCanaryEvidenceError(
                "Git repository info/exclude authority is unreadable"
            ) from exc
        if _stable_file_identity(exclude_after) != _stable_file_identity(exclude_reopened):
            raise AgyCanaryEvidenceError("Git repository info/exclude authority is unsafe")
        if require_inert_exclude and any(
            line.strip() and not line.startswith(b"#")
            for line in exclude_bytes.splitlines()
        ):
            raise AgyCanaryEvidenceError("Git repository info/exclude authority is unsafe")
    local_config = _git_run(
        canonical, "config", "--local", "--no-includes", "--name-only",
        "--null", "--list",
    )
    if local_config.returncode != 0:
        raise AgyCanaryEvidenceError("Git repository config authority is unavailable")
    try:
        names = [
            item.decode("utf-8", errors="strict")
            for item in local_config.stdout.split(b"\0") if item
        ]
    except UnicodeDecodeError as exc:
        raise AgyCanaryEvidenceError("Git repository config authority is malformed") from exc
    if any(name.lower() == "extensions.worktreeconfig" for name in names):
        worktree_config = _git_run(
            canonical, "config", "--worktree", "--no-includes", "--name-only",
            "--null", "--list",
        )
        if worktree_config.returncode != 0:
            raise AgyCanaryEvidenceError("Git worktree config authority is unavailable")
        try:
            names.extend(
                item.decode("utf-8", errors="strict")
                for item in worktree_config.stdout.split(b"\0") if item
            )
        except UnicodeDecodeError as exc:
            raise AgyCanaryEvidenceError("Git worktree config authority is malformed") from exc
    if any(not _allowed_git_config_name(name) for name in names):
        raise AgyCanaryEvidenceError("Git repository config authority is unsafe")


def _git_text(repo: Path, *args: str) -> str:
    proc = _git_run(repo, *args, text=True)
    if proc.returncode != 0:
        raise AgyCanaryEvidenceError(f"git command failed: {' '.join(args)}")
    return proc.stdout.strip()


def _git_untracked(repo: Path, *args: str) -> list[str]:
    proc = _git_run(repo, "ls-files", "-z", "--others", *args)
    if proc.returncode != 0:
        raise AgyCanaryEvidenceError("git command failed: ls-files")
    try:
        return [
            value.decode("utf-8", errors="strict")
            for value in proc.stdout.split(b"\0") if value
        ]
    except UnicodeDecodeError as exc:
        raise AgyCanaryEvidenceError("git untracked inventory is malformed") from exc


def _git_tracked_gitignores_are_exact(repo: Path) -> bool:
    proc = _git_run(repo, "ls-files", "-z")
    if proc.returncode != 0:
        raise AgyCanaryEvidenceError("git command failed: ls-files")
    try:
        tracked = [
            value.decode("utf-8", errors="strict")
            for value in proc.stdout.split(b"\0") if value
        ]
    except UnicodeDecodeError as exc:
        raise AgyCanaryEvidenceError("git tracked inventory is malformed") from exc
    for relative in tracked:
        path = Path(relative)
        if path.name != ".gitignore":
            continue
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            return False
        try:
            size = _git_text(repo, "cat-file", "-s", f"HEAD:{relative}")
            if not size.isdigit() or int(size) > _MAX_FULL_STAGED_READ_BYTES:
                return False
            local, _info = _read_bounded_regular_path(
                (repo / path).absolute(), limit=_MAX_FULL_STAGED_READ_BYTES,
            )
        except (OSError, AgyCanaryEvidenceError):
            return False
        committed = _git_run(repo, "show", f"HEAD:{relative}")
        if committed.returncode != 0 or committed.stdout != local:
            return False
    return True


def _git_filter_with_committed_gitignores(repo: Path, raw: list[str]) -> list[str]:
    if not raw:
        return []
    head = _git_text(repo, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory(prefix="phase-loop-gitignore-", dir="/tmp") as value:
        snapshot = Path(value).resolve(strict=True)
        snapshot.chmod(0o700)
        initialized = _git_run(snapshot, "init", "--quiet", "--template=")
        if initialized.returncode != 0:
            raise AgyCanaryEvidenceError("committed gitignore sandbox is unavailable")
        for mode, object_type, oid, relative in _git_tree_rows(repo, head):
            path = _snapshot_relative_path(relative)
            if path.name != ".gitignore":
                continue
            if object_type != "blob" or mode not in {"100644", "100755"}:
                raise AgyCanaryEvidenceError("committed gitignore is not a regular blob")
            target = snapshot.joinpath(*path.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(_git_object_bytes(repo, oid))
            target.chmod(0o600)
        payload = b"\0".join(path.encode("utf-8") for path in raw) + b"\0"
        checked = _git_run(
            snapshot, "check-ignore", "-z", "--stdin", "--no-index", input=payload,
        )
        if checked.returncode not in {0, 1}:
            raise AgyCanaryEvidenceError("committed gitignore evaluation failed")
        try:
            ignored = [
                value.decode("utf-8", errors="strict")
                for value in checked.stdout.split(b"\0") if value
            ]
        except UnicodeDecodeError as exc:
            raise AgyCanaryEvidenceError("committed gitignore result is malformed") from exc
        ignored_set = set(ignored)
        if len(ignored_set) != len(ignored) or not ignored_set.issubset(raw):
            raise AgyCanaryEvidenceError("committed gitignore result is malformed")
        return [path for path in raw if path not in ignored_set]


def _git_nonignored_untracked(repo: Path) -> list[str]:
    raw = _git_untracked(repo)
    if any(path == ".gitignore" or path.endswith("/.gitignore") for path in raw):
        return raw
    if not _git_tracked_gitignores_are_exact(repo):
        return [".gitignore authority drift"]
    nonignored = _git_filter_with_committed_gitignores(repo, raw)
    if not _git_tracked_gitignores_are_exact(repo):
        return [".gitignore authority drift"]
    return nonignored


def _git_worktree_is_dirty(repo: Path) -> bool:
    return bool(
        _git_text(repo, "status", "--porcelain", "--untracked-files=all")
        or _git_nonignored_untracked(repo)
    )


def _repo_relative_path(repo: Path, candidate: Path) -> str:
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise AgyCanaryEvidenceError("attested repository input must be a canonical relative path")
    path = (repo / candidate).resolve(strict=True)
    if repo not in path.parents or not path.is_file() or path.is_symlink():
        raise AgyCanaryEvidenceError("attested repository input is not a regular repository file")
    return candidate.as_posix()


def _worktree_blob(repo: Path, relative: str) -> tuple[str, bytes]:
    blob = _git_text(repo, "rev-parse", f"HEAD:{relative}")
    committed = _git_run(repo, "show", f"HEAD:{relative}")
    local = (repo / relative).read_bytes()
    if committed.returncode != 0 or committed.stdout != local:
        raise AgyCanaryEvidenceError(f"worktree input differs from committed HEAD: {relative}")
    return blob, local


def _clean_dotfiles_repo(repo: Path) -> str:
    if not (repo / ".git").exists() or not (repo / "bootstrap.sh").is_file():
        raise AgyCanaryEvidenceError("bootstrap attestation requires a dotfiles checkout")
    _validate_git_repository_authority(repo, require_inert_exclude=True)
    if _git_worktree_is_dirty(repo):
        raise AgyCanaryEvidenceError("bootstrap attestation requires a clean dotfiles worktree")
    return _git_text(repo, "rev-parse", "HEAD")


def _bootstrap_environment(
    *, uv_executable: Path, account_home: Path, interpreter_authority: dict[str, Any],
    uv_store_authority: dict[str, Any],
) -> dict[str, str]:
    """Use an explicit allowlist, never the caller's ambient environment."""
    supplied_home = os.environ.get("HOME")
    if supplied_home is not None and Path(supplied_home).resolve(strict=False) != account_home:
        raise AgyCanaryEvidenceError("bootstrap attestation rejects HOME drift")
    return _uv_environment(
        uv_executable=uv_executable, interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority,
    )


def _validate_bootstrap_uv_policy(
    *, script_bytes: bytes, uv_store_authority: dict[str, Any],
) -> None:
    """Require the attested shell input to enforce the storage policy we sealed."""
    authority = _validate_uv_store_authority(uv_store_authority, revalidate=True)
    required = (
        b'    export UV_CACHE_DIR="/mnt/workspace/uv-cache"\n',
        b'    export UV_TOOL_DIR="/mnt/workspace/uv-data/tools"\n',
        b'    export UV_PYTHON_INSTALL_DIR="/mnt/workspace/uv-data/python"\n',
        b'export UV_CACHE_DIR=/mnt/workspace/uv-cache\n',
        b'export UV_TOOL_DIR=/mnt/workspace/uv-data/tools\n',
        b'export UV_PYTHON_INSTALL_DIR=/mnt/workspace/uv-data/python',
    )
    if (script_bytes.count(b'if [ -d /mnt/workspace ]; then\n') < 1 or
            any(script_bytes.count(line) != 1 for line in required)):
        raise AgyCanaryEvidenceError("bootstrap uv storage policy differs from canonical contract")
    if authority["policy"] == "workspace":
        expected = {
            "tool": "/mnt/workspace/uv-data/tools",
            "cache": "/mnt/workspace/uv-cache",
            "python": "/mnt/workspace/uv-data/python",
        }
        if (authority["workspace"]["selector"] != "/mnt/workspace" or any(
                authority["directories"][name]["path"] != path
                for name, path in expected.items())):
            raise AgyCanaryEvidenceError("bootstrap uv workspace authority is malformed")


def _snapshot_relative_path(value: str) -> PurePosixPath:
    """Accept only a portable, non-escaping Git tree path."""
    if (not value or value.startswith("/") or "\\" in value or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise AgyCanaryEvidenceError("tracked snapshot path is unsafe")
    path = PurePosixPath(value)
    if path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise AgyCanaryEvidenceError("tracked snapshot path is unsafe")
    return path


def _snapshot_symlink_target(path: PurePosixPath, data: bytes) -> str:
    try:
        target = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AgyCanaryEvidenceError("tracked snapshot symlink target is malformed") from exc
    if (not target or target.startswith("/") or "\x00" in target or "\n" in target or
            "\r" in target):
        raise AgyCanaryEvidenceError("tracked snapshot symlink target is unsafe")
    resolved = posixpath.normpath(posixpath.join(str(path.parent), target))
    if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
        raise AgyCanaryEvidenceError("tracked snapshot symlink escapes the repository")
    return target


def _git_object_bytes(repo: Path, oid: str) -> bytes:
    size_text = _git_text(repo, "cat-file", "-s", oid)
    if not size_text.isdigit() or int(size_text) > _MAX_FULL_STAGED_READ_BYTES:
        raise AgyCanaryEvidenceError("tracked snapshot blob exceeds the full-read cap")
    proc = _git_run(repo, "cat-file", "blob", oid)
    if proc.returncode != 0 or len(proc.stdout) != int(size_text):
        raise AgyCanaryEvidenceError("tracked snapshot blob is unavailable")
    if hashlib.sha1(b"blob " + str(len(proc.stdout)).encode() + b"\0" + proc.stdout).hexdigest() != oid:
        raise AgyCanaryEvidenceError("tracked snapshot blob identity drifted")
    return proc.stdout


def _git_tree_rows(repo: Path, commit: str) -> list[tuple[str, str, str, str]]:
    proc = _git_run(repo, "ls-tree", "-rz", "--full-tree", commit)
    if proc.returncode != 0:
        raise AgyCanaryEvidenceError("tracked snapshot tree is unavailable")
    rows: list[tuple[str, str, str, str]] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            header, raw_path = raw.split(b"\t", 1)
            mode, object_type, oid = header.decode("ascii", errors="strict").split(" ")
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise AgyCanaryEvidenceError("tracked snapshot inventory is malformed") from exc
        _snapshot_relative_path(path)
        if (mode, object_type) not in {
                ("100644", "blob"), ("100755", "blob"),
                ("120000", "blob"), ("160000", "commit"),
        } or len(oid) != 40 or any(char not in "0123456789abcdef" for char in oid):
            raise AgyCanaryEvidenceError("tracked snapshot inventory mode is unsupported")
        rows.append((mode, object_type, oid, path))
    if not rows:
        raise AgyCanaryEvidenceError("tracked snapshot inventory is empty")
    return rows


def _sealed_tree_fd(*, data: bytes, executable: bool, label: str) -> int:
    seal_abi = _linux_memfd_seal_abi()
    assert fcntl is not None
    required_seals = (
        seal_abi["F_SEAL_WRITE"] | seal_abi["F_SEAL_GROW"] |
        seal_abi["F_SEAL_SHRINK"] | seal_abi["F_SEAL_SEAL"]
    )
    fd = os.memfd_create(label, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.fchmod(fd, 0o755 if executable else 0o644)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise AgyCanaryEvidenceError("tracked snapshot memfd short write")
            view = view[written:]
        os.fsync(fd)
        fcntl.fcntl(fd, seal_abi["F_ADD_SEALS"], required_seals)
        if fcntl.fcntl(fd, seal_abi["F_GET_SEALS"]) != required_seals:
            raise AgyCanaryEvidenceError("tracked snapshot memfd sealing did not hold")
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except (OSError, AgyCanaryEvidenceError) as exc:
        os.close(fd)
        if isinstance(exc, AgyCanaryEvidenceError):
            raise
        raise AgyCanaryEvidenceError("tracked snapshot memfd sealing failed") from exc


def _collect_git_tree(
    *, repo: Path, commit: str, prefix: str = "", seen: set[str] | None = None,
) -> tuple[list[tuple[str, str, str, str, Path]], list[dict[str, Any]]]:
    _validate_git_repository_authority(repo)
    seen = set() if seen is None else seen
    recursion_key = f"{repo}:{commit}"
    if recursion_key in seen:
        raise AgyCanaryEvidenceError("tracked snapshot submodule recursion is cyclic")
    seen.add(recursion_key)
    collected: list[tuple[str, str, str, str, Path]] = []
    submodules: list[dict[str, Any]] = []
    for mode, object_type, oid, relative in _git_tree_rows(repo, commit):
        joined = f"{prefix}/{relative}" if prefix else relative
        _snapshot_relative_path(joined)
        if mode != "160000":
            collected.append((mode, object_type, oid, joined, repo))
            continue
        subrepo = repo / relative
        try:
            info = subrepo.lstat()
        except FileNotFoundError as exc:
            raise AgyCanaryEvidenceError("tracked snapshot submodule checkout is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise AgyCanaryEvidenceError("tracked snapshot submodule checkout is unsafe")
        if _git_text(subrepo, "rev-parse", f"{oid}^{{commit}}") != oid:
            raise AgyCanaryEvidenceError("tracked snapshot submodule commit is unavailable")
        child_rows, child_submodules = _collect_git_tree(
            repo=subrepo, commit=oid, prefix=joined, seen=seen,
        )
        child_records = [
            f"{child_mode} {child_type} {child_oid}\t{child_path}\n"
            for child_mode, child_type, child_oid, child_path, _source in child_rows
        ]
        submodules.append({
            "path": joined, "commit": oid,
            "tree_oid": _git_text(subrepo, "rev-parse", f"{oid}^{{tree}}"),
            "inventory_sha256": _sha256("".join(child_records).encode()),
            "entry_count": len(child_rows),
        })
        submodules.extend(child_submodules)
        collected.extend(child_rows)
    seen.remove(recursion_key)
    return collected, submodules


def _git_tree_snapshot(repo: Path, commit: str, *, materialize: bool) -> _GitTreeSnapshot:
    rows, submodules = _collect_git_tree(repo=repo, commit=commit)
    paths = [row[3] for row in rows]
    if len(set(paths)) != len(paths):
        raise AgyCanaryEvidenceError("tracked snapshot contains duplicate paths")
    records = [f"{mode} {kind} {oid}\t{path}\n" for mode, kind, oid, path, _repo in rows]
    entries: list[_TreeSnapshotEntry] = []
    try:
        for mode, _kind, oid, path_text, source_repo in rows:
            data = _git_object_bytes(source_repo, oid)
            if mode == "120000":
                target = _snapshot_symlink_target(_snapshot_relative_path(path_text), data)
                entries.append(_TreeSnapshotEntry(path_text, mode, oid, link_target=target))
            elif materialize:
                entries.append(_TreeSnapshotEntry(
                    path_text, mode, oid,
                    fd=_sealed_tree_fd(data=data, executable=mode == "100755", label="phase-loop-tree"),
                ))
            else:
                entries.append(_TreeSnapshotEntry(path_text, mode, oid))
    except Exception:
        for entry in entries:
            if entry.fd is not None:
                os.close(entry.fd)
        raise
    authority = {
        "schema": _TREE_SNAPSHOT_SCHEMA, "commit": commit,
        "tree_oid": _git_text(repo, "rev-parse", f"{commit}^{{tree}}"),
        "mount_path": str(repo),
        "inventory_sha256": _sha256(_canonical_json({
            "entries": records, "submodules": submodules,
        })),
        "entry_count": len(rows),
        "file_count": sum(mode in {"100644", "100755"} for mode, *_rest in rows),
        "executable_count": sum(mode == "100755" for mode, *_rest in rows),
        "symlink_count": sum(mode == "120000" for mode, *_rest in rows),
        "gitlink_count": len(submodules),
        "submodules": submodules,
    }
    return _GitTreeSnapshot(authority=authority, entries=tuple(entries))


def _validate_tree_snapshot_authority(
    value: Any, *, repo: Path | None = None, commit: str | None = None,
    require_execution_path: bool = True,
) -> dict[str, Any]:
    required = {
        "schema", "commit", "tree_oid", "mount_path", "inventory_sha256",
        "entry_count", "file_count", "executable_count", "symlink_count",
        "gitlink_count", "submodules",
    }
    if (not isinstance(value, dict) or set(value) != required or
            value.get("schema") != _TREE_SNAPSHOT_SCHEMA or
            any(not isinstance(value.get(name), str) or len(value[name]) != 40 or
                any(char not in "0123456789abcdef" for char in value[name])
                for name in ("commit", "tree_oid")) or
            not isinstance(value.get("mount_path"), str) or
            not Path(value["mount_path"]).is_absolute() or
            any(part in {"", ".", ".."} for part in Path(value["mount_path"]).parts) or
            not _is_digest(value.get("inventory_sha256")) or
            any(not _is_plain_int(value.get(name)) or value[name] < 0 for name in (
                "entry_count", "file_count", "executable_count", "symlink_count"
            )) or value["entry_count"] < 1 or
            value["file_count"] + value["symlink_count"] != value["entry_count"] or
            value["executable_count"] > value["file_count"] or
            not _is_plain_int(value.get("gitlink_count")) or value["gitlink_count"] < 0 or
            not isinstance(value.get("submodules"), list) or
            value["gitlink_count"] != len(value["submodules"])):
        raise AgyCanaryEvidenceError("tracked snapshot authority is malformed")
    submodule_required = {"path", "commit", "tree_oid", "inventory_sha256", "entry_count"}
    submodule_paths: list[str] = []
    for row in value["submodules"]:
        if (not isinstance(row, dict) or set(row) != submodule_required or
                not isinstance(row.get("path"), str) or
                not _is_digest(row.get("inventory_sha256")) or
                not _is_plain_int(row.get("entry_count")) or row["entry_count"] < 1 or
                any(not isinstance(row.get(name), str) or len(row[name]) != 40 or
                    any(char not in "0123456789abcdef" for char in row[name])
                    for name in ("commit", "tree_oid"))):
            raise AgyCanaryEvidenceError("tracked snapshot submodule authority is malformed")
        _snapshot_relative_path(row["path"])
        submodule_paths.append(row["path"])
    if submodule_paths != sorted(set(submodule_paths)):
        raise AgyCanaryEvidenceError("tracked snapshot submodule authority is malformed")
    if commit is not None and value["commit"] != commit:
        raise AgyCanaryEvidenceError("tracked snapshot commit drifted")
    if repo is not None:
        canonical = repo.resolve(strict=True)
        if require_execution_path and value["mount_path"] != str(canonical):
            raise AgyCanaryEvidenceError("tracked snapshot mount path drifted")
        derived = _git_tree_snapshot(canonical, value["commit"], materialize=False)
        expected = derived.authority
        if not require_execution_path:
            expected = {**expected, "mount_path": value["mount_path"]}
        if expected != value:
            raise AgyCanaryEvidenceError("tracked snapshot authority drifted")
    return value


def _bootstrap_local_source_seams(repo: Path) -> dict[str, str]:
    """Prove gitignored source hooks are absent, including broken symlinks."""
    hooks = repo / "hooks"
    try:
        hooks_info = hooks.lstat()
    except FileNotFoundError:
        hooks_info = None
    if hooks_info is not None:
        hooks_mode = stat.S_IMODE(hooks_info.st_mode)
        if (stat.S_ISLNK(hooks_info.st_mode) or not stat.S_ISDIR(hooks_info.st_mode) or
                hooks_info.st_uid != repo.stat().st_uid or
                hooks_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise AgyCanaryEvidenceError("bootstrap local source seam parent is unsafe")
    for relative in _BOOTSTRAP_LOCAL_SOURCE_SEAMS:
        try:
            (repo / relative).lstat()
        except FileNotFoundError:
            continue
        raise AgyCanaryEvidenceError(f"bootstrap local source seam is present: {relative}")
    return {relative: "absent" for relative in _BOOTSTRAP_LOCAL_SOURCE_SEAMS}


def _tree_snapshot_bwrap_argv(
    *, snapshot: _GitTreeSnapshot, bwrap: Path, bash: Path,
    environment: dict[str, str], account_home: Path,
    uv_store_authority: dict[str, Any], evidence_root_masking: dict[str, Any],
    command: tuple[str, ...] | None = None, identity_only: bool = False,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Mount every attested Git blob read-only over the canonical repository path."""
    repo = Path(snapshot.authority["mount_path"])
    command = (str(bash), str(repo / "bootstrap.sh")) if command is None else command
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise AgyCanaryEvidenceError("tracked snapshot child command is malformed")
    writable_binds = [str(account_home.resolve(strict=True))]
    workspace = uv_store_authority["workspace"]
    if workspace is not None:
        writable_binds.append(workspace["resolved"])
    writable_binds = sorted(set(writable_binds))
    evidence_root_masking = _validate_evidence_root_masking_authority(
        evidence_root_masking, revalidate=not identity_only,
    )
    argv = [
        str(bwrap), "--unshare-all", "--share-net", "--die-with-parent", "--new-session",
        "--clearenv", "--ro-bind", "/", "/",
    ]
    for path in writable_binds:
        argv.extend(("--bind", path, path))
    argv.extend((
        "--tmpfs", "/tmp", "--tmpfs", "/run",
        "--ro-bind-try", "/run/user", "/run/user",
        "--proc", "/proc", "--dev-bind", "/dev", "/dev",
    ))
    for volatile_root in (Path("/tmp"), Path("/run")):
        if repo.is_relative_to(volatile_root):
            relative = repo.relative_to(volatile_root)
            for depth in range(1, len(relative.parts)):
                argv.extend(("--dir", str(volatile_root.joinpath(*relative.parts[:depth]))))
    argv.extend(("--tmpfs", str(repo)))
    parents = sorted({
        str(repo.joinpath(*PurePosixPath(entry.path).parts[:depth]))
        for entry in snapshot.entries
        for depth in range(1, len(PurePosixPath(entry.path).parts))
    }, key=lambda value: (len(Path(value).parts), value))
    for parent in parents:
        argv.extend(("--dir", parent))
    for entry in sorted(snapshot.entries, key=lambda row: row.path):
        destination = str(repo.joinpath(*PurePosixPath(entry.path).parts))
        if entry.mode == "120000":
            if entry.link_target is None:
                raise AgyCanaryEvidenceError("tracked snapshot symlink is incomplete")
            argv.extend(("--symlink", entry.link_target, destination))
        else:
            if entry.fd is None and not identity_only:
                raise AgyCanaryEvidenceError("tracked snapshot file descriptor is missing")
            permissions = "0755" if entry.mode == "100755" else "0644"
            descriptor = (
                f"sealed:{entry.mode}:{entry.oid}" if identity_only else str(entry.fd)
            )
            argv.extend(("--perms", permissions, "--ro-bind-data", descriptor, destination))
    argv.extend(("--remount-ro", str(repo)))
    for name in sorted(environment):
        argv.extend(("--setenv", name, environment[name]))
    argv.extend(("--chdir", str(repo), "--", *command))
    identity_argv = list(argv)
    if not identity_only:
        by_destination = {
            str(repo.joinpath(*PurePosixPath(entry.path).parts)): entry
            for entry in snapshot.entries if entry.mode != "120000"
        }
        for index, item in enumerate(identity_argv[:-2]):
            if item != "--ro-bind-data":
                continue
            destination = identity_argv[index + 2]
            entry = by_destination.get(destination)
            if entry is None:
                raise AgyCanaryEvidenceError("tracked snapshot argv identity is incomplete")
            identity_argv[index + 1] = f"sealed:{entry.mode}:{entry.oid}"
    arg_bytes = sum(len(item.encode()) + 1 for item in identity_argv)
    try:
        arg_max = os.sysconf("SC_ARG_MAX")
        open_max = os.sysconf("SC_OPEN_MAX")
    except (OSError, ValueError) as exc:
        raise AgyCanaryEvidenceError("tracked snapshot process limits are unavailable") from exc
    descriptor_count = (
        snapshot.authority["file_count"] if identity_only else len(snapshot.fds)
    )
    if arg_bytes >= arg_max or descriptor_count + 16 >= open_max:
        raise AgyCanaryEvidenceError("tracked snapshot exceeds process argument or descriptor limits")
    sandbox = {
        "schema": _TREE_SANDBOX_SCHEMA, "executable": str(bwrap),
        "argv_sha256": _sha256(_canonical_json(identity_argv)),
        "argv_count": len(identity_argv),
        "argv_bytes": arg_bytes, "passed_fd_count": descriptor_count,
        "root": "read_only", "network": "shared",
        "mount_path": str(repo), "command": list(command),
        "writable_binds": writable_binds,
        "tmpfs": ["/tmp", "/run", str(repo)],
        "environment_sha256": _sha256(_canonical_json(environment)),
        "evidence_root_masking": evidence_root_masking,
    }
    return tuple(argv), sandbox


def _validate_tree_sandbox(
    value: Any, *, tree: dict[str, Any], environment: dict[str, str],
    uv_store_authority: dict[str, Any], bash: Path,
    revalidate_evidence_root: bool = True,
) -> dict[str, Any]:
    required = {
        "schema", "executable", "argv_sha256", "argv_count", "argv_bytes",
        "passed_fd_count", "root", "network", "mount_path", "command",
        "writable_binds", "tmpfs", "environment_sha256",
        "evidence_root_masking",
    }
    account_home = Path(uv_store_authority["account_home"])
    writable_binds = [str(account_home)]
    if uv_store_authority["workspace"] is not None:
        writable_binds.append(uv_store_authority["workspace"]["resolved"])
    writable_binds = sorted(set(writable_binds))
    mount_path = tree["mount_path"]
    if (not isinstance(value, dict) or set(value) != required or
            value.get("schema") != _TREE_SANDBOX_SCHEMA or
            value.get("executable") != str(_canonical_bwrap()) or
            not _is_digest(value.get("argv_sha256")) or
            any(not _is_plain_int(value.get(name)) or value[name] < 1 for name in (
                "argv_count", "argv_bytes", "passed_fd_count"
            )) or value["passed_fd_count"] != tree["file_count"] or
            value.get("root") != "read_only" or value.get("network") != "shared" or
            value.get("mount_path") != mount_path or
            value.get("command") != [str(bash), str(Path(mount_path) / "bootstrap.sh")] or
            value.get("writable_binds") != writable_binds or
            value.get("tmpfs") != ["/tmp", "/run", mount_path] or
            value.get("environment_sha256") != _sha256(_canonical_json(environment)) or
            _validate_evidence_root_masking_authority(
                value.get("evidence_root_masking"),
                revalidate=revalidate_evidence_root,
            ) != value.get("evidence_root_masking")):
        raise AgyCanaryEvidenceError("tracked snapshot sandbox record is malformed")
    return value


def _launch_tree_snapshot_child(
    *, repo: Path, head: str, bwrap: Path, bash: Path,
    environment: dict[str, str], account_home: Path,
    uv_store_authority: dict[str, Any], evidence_root_masking: dict[str, Any],
    local_source_seams: dict[str, str],
) -> tuple[subprocess.Popen[str], dict[str, Any], dict[str, Any]]:
    """Own every snapshot FD across argv construction, launch, and communication."""
    snapshot = _git_tree_snapshot(repo, head, materialize=True)
    try:
        bootstrap_argv, sandbox = _tree_snapshot_bwrap_argv(
            snapshot=snapshot, bwrap=bwrap, bash=bash, environment=environment,
            account_home=account_home, uv_store_authority=uv_store_authority,
            evidence_root_masking=evidence_root_masking,
        )
        if _bootstrap_local_source_seams(repo) != local_source_seams:
            raise AgyCanaryEvidenceError("bootstrap local source seam state drifted")
        try:
            child_process = subprocess.Popen(
                list(bootstrap_argv), cwd=repo, env={}, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, pass_fds=snapshot.fds,
            )
        except OSError as exc:
            raise AgyCanaryEvidenceError("tracked snapshot child could not start") from exc
        try:
            child_process.communicate(timeout=1800)
        except subprocess.TimeoutExpired as exc:
            child_process.kill()
            child_process.communicate()
            raise AgyCanaryEvidenceError("direct bootstrap child timed out") from exc
        return child_process, sandbox, snapshot.authority
    finally:
        snapshot.close()


def bootstrap_attest(
    *, evidence_root: Path, dotfiles_repo: Path, plan_path: Path
) -> dict[str, Any]:
    """Open the private evidence authority before any subprocess or child."""
    root, root_fd = _validate_private_root(evidence_root)
    try:
        return _bootstrap_attest_opened(
            root=root, root_fd=root_fd, dotfiles_repo=dotfiles_repo,
            plan_path=plan_path,
        )
    finally:
        os.close(root_fd)


def _bootstrap_attest_opened(
    *, root: Path, root_fd: int, dotfiles_repo: Path, plan_path: Path,
) -> dict[str, Any]:
    """Directly run committed bootstrap and attest its direct child result."""
    disallowed_overrides = sorted(
        key for key in os.environ
        if key in {"DEV_EDITABLE", "PYTHONPATH", "PYTHONHOME"}
        or key.startswith("PHASE_LOOP_")
        or key.startswith("AGENT_HARNESS_")
        or key.startswith("UV_")
        or key.startswith("XDG_")
    )
    if disallowed_overrides:
        raise AgyCanaryEvidenceError(
            "bootstrap attestation rejects environment overrides: "
            + ",".join(disallowed_overrides)
        )
    repo = dotfiles_repo.resolve(strict=True)
    head = _clean_dotfiles_repo(repo)
    local_source_seams = _bootstrap_local_source_seams(repo)
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
    bash = _canonical_bash()
    uv = _canonical_uv()
    interpreter_authority = _system_interpreter_authority()
    _validate_interpreter_authority(interpreter_authority, revalidate=True)
    account_home = _account_home()
    uv_store_authority = _uv_store_authority(account_home=account_home)
    _validate_uv_store_authority(
        uv_store_authority, revalidate=True, account_home=account_home,
    )
    evidence_root_masking = _evidence_root_masking_authority(root, root_fd)
    _validate_bootstrap_evidence_root_isolation(
        root=root, repo=repo, account_home=account_home,
        uv_store_authority=uv_store_authority,
    )
    child_env = _bootstrap_environment(
        uv_executable=uv, account_home=account_home,
        interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority,
    )
    script_bytes = inputs["bootstrap.sh"]
    _validate_bootstrap_uv_policy(
        script_bytes=script_bytes, uv_store_authority=uv_store_authority,
    )
    def revalidate_inputs() -> None:
        if _clean_dotfiles_repo(repo) != head:
            raise AgyCanaryEvidenceError("bootstrap inputs drifted from the attested clean HEAD")
        for relative, expected_blob in identities.items():
            blob, data = _worktree_blob(repo, relative)
            if blob != expected_blob or data != inputs[relative]:
                raise AgyCanaryEvidenceError("bootstrap input bytes drifted from attested blobs")
    revalidate_inputs()
    before = subprocess.run(
        [str(uv), "tool", "list"], capture_output=True, text=True,
        timeout=30, check=False, env=child_env,
    )
    bwrap = _canonical_bwrap()
    child_process, sandbox, tree_snapshot_authority = _launch_tree_snapshot_child(
        repo=repo, head=head, bwrap=bwrap, bash=bash, environment=child_env,
        account_home=account_home, uv_store_authority=uv_store_authority,
        evidence_root_masking=evidence_root_masking,
        local_source_seams=local_source_seams,
    )
    if _evidence_root_masking_authority(root, root_fd) != evidence_root_masking:
        raise AgyCanaryEvidenceError("bootstrap evidence root masking authority drifted")
    child_rc = child_process.returncode
    if _bootstrap_local_source_seams(repo) != local_source_seams:
        raise AgyCanaryEvidenceError("bootstrap local source seam state drifted")
    revalidate_inputs()
    _validate_interpreter_authority(interpreter_authority, revalidate=True)
    _validate_uv_store_authority(uv_store_authority, revalidate=True)
    after = subprocess.run(
        [str(uv), "tool", "list"], capture_output=True, text=True,
        timeout=30, check=False, env=child_env,
    )
    if child_rc != 0:
        raise AgyCanaryEvidenceError("direct bootstrap child failed")
    installation = _installed_phase_loop_identity(
        uv_executable=uv, interpreter_authority=interpreter_authority,
        uv_store_authority=uv_store_authority, uv_environment=child_env,
    )
    if installation["version"] != "0.7.14":
        raise AgyCanaryEvidenceError("bootstrap did not install the expected phase-loop version")
    value = {
        "schema": "agy_canary_bootstrap_attestation.v1",
        "repo_head": head,
        "tree_snapshot": tree_snapshot_authority,
        "blobs": identities,
        "input_sha256": {name: _sha256(data) for name, data in inputs.items()},
        "targets": {"plan": plan_relative, "manifest": "plans/manifest.json"},
        "bootstrap": {
            "sandbox": sandbox,
            "pid": child_process.pid,
            "returncode": child_rc,
            "script_sha256": _sha256(script_bytes),
            "script_blob": identities["bootstrap.sh"],
            "before_uv_tools_sha256": _sha256((before.stdout or "").encode()),
            "after_uv_tools_sha256": _sha256((after.stdout or "").encode()),
            "environment_names": sorted(child_env),
            "uv_environment": {
                name: child_env[name] for name in (
                    "HOME", "PATH", "PYTHONDONTWRITEBYTECODE",
                    "UV_TOOL_DIR", "UV_TOOL_BIN_DIR",
                    "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "UV_PYTHON",
                    "UV_PYTHON_DOWNLOADS",
                )
            },
            "interpreter_authority": interpreter_authority,
            "uv_store_authority": uv_store_authority,
            "local_source_seams": local_source_seams,
            "installation": installation,
        },
    }
    if _evidence_root_masking_authority(root, root_fd) != evidence_root_masking:
        raise AgyCanaryEvidenceError("bootstrap evidence root masking authority drifted")
    _exclusive_write_at(
        root_fd, "agy_canary_bootstrap_attestation.json", _canonical_json(value), 0o600
    )
    return value


def _validate_installation_identity(installed: Any) -> dict[str, Any]:
    expected_installation = {
        "uv_executable", "uv_tool_dir", "console_script", "interpreter", "version",
        "distribution_root", "module_origin", "environment_root",
        "console_script_sha256", "interpreter_sha256",
        "interpreter_authority", "uv_store_authority",
        "package_tree_sha256", "record_sha256", "provenance",
    }
    installation_strings = expected_installation - {
        "provenance", "interpreter_authority", "uv_store_authority",
    }
    if (not isinstance(installed, dict) or set(installed) != expected_installation or
            any(not isinstance(installed.get(name), str) or not installed[name] for name in installation_strings) or
            installed["version"] != "0.7.14" or
            any(not Path(installed[name]).is_absolute() for name in (
                "uv_executable", "uv_tool_dir", "console_script", "interpreter",
                "distribution_root", "module_origin", "environment_root",
            )) or
            any(not _is_digest(installed[name]) for name in (
                "console_script_sha256", "interpreter_sha256", "package_tree_sha256", "record_sha256"
            )) or
            not Path(installed["module_origin"]).is_relative_to(Path(installed["distribution_root"])) or
            not Path(installed["distribution_root"]).is_relative_to(Path(installed["environment_root"]))):
        raise AgyCanaryEvidenceError("bootstrap attestation installation identity is malformed")
    authority = _validate_interpreter_authority(
        installed["interpreter_authority"], revalidate=False
    )
    if (installed["interpreter"] != authority["path"] or
            installed["interpreter_sha256"] != authority["sha256"]):
        raise AgyCanaryEvidenceError("bootstrap attestation interpreter binding is malformed")
    store_authority = _validate_uv_store_authority(
        installed["uv_store_authority"], revalidate=False
    )
    if (installed["uv_tool_dir"] != store_authority["directories"]["tool"]["path"] or
            Path(installed["environment_root"]).parent !=
            Path(store_authority["directories"]["tool"]["path"])):
        raise AgyCanaryEvidenceError("bootstrap attestation uv store binding is malformed")
    provenance = installed["provenance"]
    if (not isinstance(provenance, dict) or set(provenance) != {"schema", "requirement", "receipt_sha256"} or
            provenance.get("schema") != "uv_registry_receipt.v1" or
            provenance.get("requirement") != "phase-loop-runtime==0.7.14" or
            not _is_digest(provenance.get("receipt_sha256"))):
        raise AgyCanaryEvidenceError("bootstrap attestation registry provenance is malformed")
    return installed


def _validate_bootstrap_attestation(
    *, receipt: Any, repo: Path | None = None, installation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept only a complete, directly-produced bootstrap receipt."""
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema", "repo_head", "tree_snapshot", "blobs", "input_sha256", "targets", "bootstrap"
    } or receipt.get("schema") != "agy_canary_bootstrap_attestation.v1":
        raise AgyCanaryEvidenceError("bootstrap attestation schema is malformed")
    targets = receipt["targets"]
    if (not isinstance(targets, dict) or set(targets) != {"plan", "manifest"} or
            not isinstance(targets.get("plan"), str) or
            targets["plan"] in {"", "plans/manifest.json"} or
            Path(targets["plan"]).is_absolute() or
            any(part in {"", ".", ".."} for part in Path(targets["plan"]).parts) or
            targets.get("manifest") != "plans/manifest.json"):
        raise AgyCanaryEvidenceError("bootstrap attestation targets are malformed")
    expected_paths = {
        "bootstrap.sh", "shared/agent-harness.pin", "plans/manifest.json", targets["plan"],
    }
    repo_head = receipt["repo_head"]
    blobs = receipt["blobs"]
    input_sha256 = receipt["input_sha256"]
    if (not isinstance(repo_head, str) or len(repo_head) != 40 or
            any(char not in "0123456789abcdef" for char in repo_head.lower()) or
            len(expected_paths) != 4 or
            not isinstance(blobs, dict) or not isinstance(input_sha256, dict) or
            set(blobs) != expected_paths or set(input_sha256) != expected_paths or
            any(not isinstance(value, str) or len(value) != 40 or
                any(char not in "0123456789abcdef" for char in value.lower())
                for value in blobs.values()) or
            any(not _is_digest(value) for value in input_sha256.values())):
        raise AgyCanaryEvidenceError("bootstrap attestation input identities are malformed")
    bootstrap = receipt["bootstrap"]
    expected_bootstrap = {
        "sandbox", "pid", "returncode", "script_sha256", "script_blob",
        "before_uv_tools_sha256", "after_uv_tools_sha256", "environment_names",
        "uv_environment", "interpreter_authority", "uv_store_authority",
        "local_source_seams", "installation",
    }
    if not isinstance(bootstrap, dict) or set(bootstrap) != expected_bootstrap:
        raise AgyCanaryEvidenceError("bootstrap attestation child record is malformed")
    tree = _validate_tree_snapshot_authority(
        receipt["tree_snapshot"], repo=repo, commit=repo_head,
    )
    if (type(bootstrap["pid"]) is not int or bootstrap["pid"] <= 0 or
            bootstrap["returncode"] != 0 or bootstrap["script_sha256"] != input_sha256["bootstrap.sh"] or
            bootstrap["script_blob"] != blobs["bootstrap.sh"] or
            any(not _is_digest(bootstrap[name]) for name in (
                "before_uv_tools_sha256", "after_uv_tools_sha256"
            ))):
        raise AgyCanaryEvidenceError("bootstrap attestation child identity is malformed")
    bootstrap_path = Path(tree["mount_path"]) / "bootstrap.sh"
    local_source_seams = bootstrap["local_source_seams"]
    if (local_source_seams != {
            relative: "absent" for relative in _BOOTSTRAP_LOCAL_SOURCE_SEAMS
    } or _bootstrap_local_source_seams(bootstrap_path.parent) != local_source_seams):
        raise AgyCanaryEvidenceError("bootstrap attestation local source seams drifted")
    environment_names = bootstrap["environment_names"]
    if (not isinstance(environment_names, list) or environment_names != sorted(environment_names) or
            len(set(environment_names)) != len(environment_names) or
            environment_names != sorted({
                "HOME", "PATH", "PYTHONDONTWRITEBYTECODE",
                "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_CACHE_DIR",
                "UV_PYTHON_INSTALL_DIR", "UV_PYTHON", "UV_PYTHON_DOWNLOADS",
            })):
        raise AgyCanaryEvidenceError("bootstrap attestation child environment is malformed")
    authority = _validate_interpreter_authority(
        bootstrap["interpreter_authority"], revalidate=True
    )
    installed = _validate_installation_identity(bootstrap["installation"])
    store_authority = _validate_uv_store_authority(
        bootstrap["uv_store_authority"], revalidate=True, account_home=_account_home(),
        workspace_root=_UV_WORKSPACE_ROOT,
    )
    expected_uv_environment = _uv_environment(
        uv_executable=Path(installed["uv_executable"]), interpreter_authority=authority,
        uv_store_authority=store_authority,
    )
    if bootstrap.get("uv_environment") != expected_uv_environment:
        raise AgyCanaryEvidenceError("bootstrap attestation uv environment is malformed")
    _validate_tree_sandbox(
        bootstrap["sandbox"], tree=tree, environment=expected_uv_environment,
        uv_store_authority=store_authority, bash=_canonical_bash(),
    )
    if installed["interpreter_authority"] != authority:
        raise AgyCanaryEvidenceError("bootstrap attestation interpreter authority drifted")
    if installed["uv_store_authority"] != store_authority:
        raise AgyCanaryEvidenceError("bootstrap attestation uv store authority drifted")
    if installation is not None and installed != installation:
        raise AgyCanaryEvidenceError("bootstrap attestation installation identity drifted")
    if repo is not None:
        _validate_git_repository_authority(repo)
        if _git_text(repo, "rev-parse", f"{repo_head}^{{commit}}") != repo_head:
            raise AgyCanaryEvidenceError("bootstrap attestation HEAD is not immutable")
        for relative in expected_paths:
            actual = _git_run(repo, "show", f"{repo_head}:{relative}")
            if (actual.returncode != 0 or blobs[relative] != _git_text(
                    repo, "rev-parse", f"{repo_head}:{relative}"
            ) or input_sha256[relative] != _sha256(actual.stdout)):
                raise AgyCanaryEvidenceError("bootstrap attestation input identity drifted")
    return receipt


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
        os.close(opened.fd)
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


def _record_digest(value: str) -> str:
    """Decode one canonical PEP 376 SHA-256 field to lower-case hex."""
    if not re.fullmatch(r"sha256=[A-Za-z0-9_-]{43}", value):
        raise AgyCanaryEvidenceError("wheel RECORD hash is not canonical sha256")
    encoded = value.removeprefix("sha256=")
    try:
        raw = base64.b64decode(encoded + "=", altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise AgyCanaryEvidenceError("wheel RECORD hash is malformed") from exc
    if len(raw) != hashlib.sha256().digest_size:
        raise AgyCanaryEvidenceError("wheel RECORD hash has the wrong size")
    return raw.hex()


def _wheel_record_path(value: str) -> str:
    """Accept only a normalized relative archive/RECORD path."""
    if (not value or "\\" in value or "\x00" in value or value.startswith("/") or
            re.match(r"^[A-Za-z]:", value) is not None or
            value.endswith("/") or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise AgyCanaryEvidenceError("wheel RECORD path is unsafe or noncanonical")
    return value


def _record_rows(data: bytes, *, wheel: bool) -> list[tuple[str, str, str]]:
    try:
        text = data.decode("utf-8", errors="strict")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise AgyCanaryEvidenceError("wheel RECORD is malformed") from exc
    output: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if len(row) != 3 or not all(isinstance(value, str) for value in row):
            raise AgyCanaryEvidenceError("wheel RECORD row is malformed")
        path, digest, size = row
        if wheel:
            _wheel_record_path(path)
        elif not path or "\\" in path or "\x00" in path or path.startswith("/"):
            raise AgyCanaryEvidenceError("installed RECORD path is malformed")
        if path in seen:
            raise AgyCanaryEvidenceError("wheel RECORD path is duplicated")
        seen.add(path)
        output.append((path, digest, size))
    if not output:
        raise AgyCanaryEvidenceError("wheel RECORD is empty")
    return output


def _wheel_console_scripts(data: bytes) -> list[dict[str, str]]:
    """Parse the authenticated wheel metadata into canonical launcher authority."""
    try:
        text = data.decode("utf-8", errors="strict")
        parser = configparser.ConfigParser(
            interpolation=None, delimiters=("=",), strict=True,
            empty_lines_in_values=False,
        )
        parser.optionxform = str
        parser.read_string(text)
    except (UnicodeDecodeError, configparser.Error) as exc:
        raise AgyCanaryEvidenceError("release wheel entry points are malformed") from exc
    if not parser.has_section("console_scripts"):
        raise AgyCanaryEvidenceError("release wheel lacks governed console entry points")
    scripts = [
        {"name": name, "target": target}
        for name, target in parser.items("console_scripts", raw=True)
    ]
    scripts.sort(key=lambda row: row["name"])
    expected = [
        {"name": "codex-phase-loop", "target": "phase_loop_runtime.cli:main"},
        {"name": "phase-loop", "target": "phase_loop_runtime.cli:main"},
    ]
    if scripts != expected:
        raise AgyCanaryEvidenceError("release wheel console entry points are not canonical")
    return scripts


def _wheel_binding(
    *, wheel_bytes: bytes, filename: str, digest: str, url_sha256: str, version: str,
) -> dict[str, Any]:
    """Derive a canonical install map from the exact reauthenticated wheel bytes."""
    if _sha256(wheel_bytes) != digest:
        raise AgyCanaryEvidenceError("downloaded release artifact digest mismatch")
    expected_prefix = f"phase_loop_runtime-{version}"
    if (not re.fullmatch(rf"{re.escape(expected_prefix)}-py3-none-any\.whl", filename) or
            not _is_digest(digest) or not _is_digest(url_sha256)):
        raise AgyCanaryEvidenceError("release wheel identity is not canonical")
    try:
        archive = zipfile.ZipFile(io.BytesIO(wheel_bytes))
    except (OSError, zipfile.BadZipFile) as exc:
        raise AgyCanaryEvidenceError("release wheel is not a valid archive") from exc
    with archive:
        members: dict[str, tuple[zipfile.ZipInfo, bytes]] = {}
        for info in archive.infolist():
            name = _wheel_record_path(info.filename)
            file_type = (info.external_attr >> 16) & 0o170000
            if (info.is_dir() or info.flag_bits & 0x1 or
                    file_type not in {0, stat.S_IFREG} or
                    name in members):
                raise AgyCanaryEvidenceError("release wheel member is unsafe or duplicated")
            try:
                content = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise AgyCanaryEvidenceError("release wheel member could not be verified") from exc
            if len(content) != info.file_size:
                raise AgyCanaryEvidenceError("release wheel member size drifted")
            members[name] = (info, content)
    dist_info = f"{expected_prefix}.dist-info"
    record_path = f"{dist_info}/RECORD"
    if record_path not in members:
        raise AgyCanaryEvidenceError("release wheel lacks its canonical RECORD")
    rows = _record_rows(members[record_path][1], wheel=True)
    if {path for path, _digest, _size in rows} != set(members):
        raise AgyCanaryEvidenceError("release wheel RECORD does not exactly inventory the archive")
    wheel_metadata_path = f"{dist_info}/WHEEL"
    entry_points_path = f"{dist_info}/entry_points.txt"
    try:
        wheel_metadata = members[wheel_metadata_path][1].decode("utf-8", errors="strict")
    except (KeyError, UnicodeDecodeError) as exc:
        raise AgyCanaryEvidenceError("release wheel metadata is unavailable") from exc
    purelib_lines = [line for line in wheel_metadata.splitlines() if line.startswith("Root-Is-Purelib:")]
    if purelib_lines != ["Root-Is-Purelib: true"]:
        raise AgyCanaryEvidenceError("release wheel root install scheme is not canonical")
    try:
        console_scripts = _wheel_console_scripts(members[entry_points_path][1])
    except KeyError as exc:
        raise AgyCanaryEvidenceError("release wheel entry points are unavailable") from exc
    data_prefix = f"{expected_prefix}.data/"
    files: list[dict[str, Any]] = []
    for path, record_hash, record_size in rows:
        content = members[path][1]
        if path == record_path:
            if record_hash or record_size:
                raise AgyCanaryEvidenceError("release wheel RECORD self-row is not empty")
            continue
        if not record_hash or not record_size.isdigit() or str(int(record_size)) != record_size:
            raise AgyCanaryEvidenceError("release wheel RECORD size is malformed")
        size = int(record_size)
        content_sha256 = _record_digest(record_hash)
        if len(content) != size or _sha256(content) != content_sha256:
            raise AgyCanaryEvidenceError("release wheel content does not match RECORD")
        if path.startswith(data_prefix):
            remainder = path.removeprefix(data_prefix)
            scheme, separator, installed_path = remainder.partition("/")
            if separator != "/" or scheme not in {"purelib", "platlib", "data"}:
                raise AgyCanaryEvidenceError("release wheel install scheme is unsupported")
            _wheel_record_path(installed_path)
        else:
            scheme = "purelib"
            installed_path = path
        files.append({
            "wheel_path": path, "scheme": scheme, "installed_path": installed_path,
            "sha256": content_sha256, "size": size,
        })
    files.sort(key=lambda row: row["wheel_path"])
    return {
        "schema": "agy_canary_wheel_binding.v1", "filename": filename,
        "sha256": digest, "url_sha256": url_sha256,
        "record_path": record_path, "record_sha256": _sha256(members[record_path][1]),
        "root_scheme": "purelib", "console_scripts": console_scripts, "files": files,
    }


def _validate_wheel_binding(value: Any, *, version: str) -> dict[str, Any]:
    required = {
        "schema", "filename", "sha256", "url_sha256", "record_path",
        "record_sha256", "root_scheme", "console_scripts", "files",
    }
    if (not isinstance(value, dict) or set(value) != required or
            value.get("schema") != "agy_canary_wheel_binding.v1" or
            value.get("filename") != f"phase_loop_runtime-{version}-py3-none-any.whl" or
            value.get("record_path") != f"phase_loop_runtime-{version}.dist-info/RECORD" or
            value.get("root_scheme") != "purelib" or
            any(not _is_digest(value.get(name)) for name in ("sha256", "url_sha256", "record_sha256")) or
            value.get("console_scripts") != [
                {"name": "codex-phase-loop", "target": "phase_loop_runtime.cli:main"},
                {"name": "phase-loop", "target": "phase_loop_runtime.cli:main"},
            ] or
            not isinstance(value.get("files"), list) or not value["files"]):
        raise AgyCanaryEvidenceError("release wheel binding is malformed")
    wheel_paths: set[str] = set()
    targets: set[tuple[str, str]] = set()
    previous = ""
    data_prefix = f"phase_loop_runtime-{version}.data/"
    for row in value["files"]:
        if (not isinstance(row, dict) or set(row) != {
                "wheel_path", "scheme", "installed_path", "sha256", "size"
        } or not isinstance(row.get("wheel_path"), str) or
                not isinstance(row.get("installed_path"), str) or
                row.get("scheme") not in {"purelib", "platlib", "data"} or
                not _is_digest(row.get("sha256")) or not _is_plain_int(row.get("size")) or
                row["size"] < 0):
            raise AgyCanaryEvidenceError("release wheel binding file row is malformed")
        wheel_path = _wheel_record_path(row["wheel_path"])
        installed_path = _wheel_record_path(row["installed_path"])
        if wheel_path == value["record_path"]:
            raise AgyCanaryEvidenceError("release wheel binding includes its mutable RECORD")
        if wheel_path.startswith(data_prefix):
            remainder = wheel_path.removeprefix(data_prefix)
            scheme, separator, expected_installed_path = remainder.partition("/")
            if (separator != "/" or scheme not in {"purelib", "platlib", "data"} or
                    row["scheme"] != scheme or installed_path != expected_installed_path):
                raise AgyCanaryEvidenceError("release wheel binding install map is malformed")
        elif row["scheme"] != "purelib" or installed_path != wheel_path:
            raise AgyCanaryEvidenceError("release wheel binding root install map is malformed")
        target = (row["scheme"], installed_path)
        if wheel_path <= previous or wheel_path in wheel_paths or target in targets:
            raise AgyCanaryEvidenceError("release wheel binding files are duplicated or unsorted")
        previous = wheel_path
        wheel_paths.add(wheel_path)
        targets.add(target)
    if "phase_loop_runtime/__init__.py" not in wheel_paths:
        raise AgyCanaryEvidenceError("release wheel binding lacks the governed runtime package")
    if f"phase_loop_runtime-{version}.dist-info/entry_points.txt" not in wheel_paths:
        raise AgyCanaryEvidenceError("release wheel binding lacks governed entry points")
    return value


def _validate_release_identity(release: Any) -> dict[str, Any]:
    required = {
        "version", "handoff_commit", "release_commit", "tag_object", "tag_peel",
        "artifacts", "wheel_binding",
    }
    if (not isinstance(release, dict) or set(release) != required or
            release.get("version") != "0.7.14" or
            release.get("tag_peel") != release.get("release_commit")):
        raise AgyCanaryEvidenceError("release identity is malformed")
    for name in ("handoff_commit", "release_commit", "tag_object", "tag_peel"):
        value = release.get(name)
        if not isinstance(value, str) or len(value) != 40 or any(
                character not in "0123456789abcdef" for character in value.lower()):
            raise AgyCanaryEvidenceError("release identity is malformed")
    artifacts = release.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise AgyCanaryEvidenceError("release artifacts are malformed")
    if artifacts != sorted(artifacts, key=lambda row: (row.get("filename", ""), row.get("packagetype", "")) if isinstance(row, dict) else ("", "")):
        raise AgyCanaryEvidenceError("release artifacts are not canonical")
    identities: set[tuple[str, str]] = set()
    wheel_rows: list[dict[str, str]] = []
    sdist_count = 0
    for artifact in artifacts:
        if (not isinstance(artifact, dict) or set(artifact) != {
                "filename", "packagetype", "sha256", "url_sha256"
        } or not all(isinstance(artifact.get(name), str) for name in artifact) or
                any(not _is_digest(artifact.get(name)) for name in ("sha256", "url_sha256"))):
            raise AgyCanaryEvidenceError("release artifact is malformed")
        identity = (artifact["filename"], artifact["packagetype"])
        if identity in identities:
            raise AgyCanaryEvidenceError("release artifacts are duplicated")
        identities.add(identity)
        if artifact["filename"].endswith(".whl"):
            if artifact["packagetype"] != "bdist_wheel":
                raise AgyCanaryEvidenceError("release wheel artifact type is malformed")
            wheel_rows.append(artifact)
        if artifact["filename"].endswith(".tar.gz"):
            if artifact["packagetype"] != "sdist":
                raise AgyCanaryEvidenceError("release sdist artifact type is malformed")
            sdist_count += 1
    expected_artifacts = {
        (f"phase_loop_runtime-{release['version']}-py3-none-any.whl", "bdist_wheel"),
        (f"phase_loop_runtime-{release['version']}.tar.gz", "sdist"),
    }
    if (len(wheel_rows) != 1 or sdist_count != 1 or
            identities != expected_artifacts):
        raise AgyCanaryEvidenceError("release requires one wheel and one sdist")
    binding = _validate_wheel_binding(release.get("wheel_binding"), version=release["version"])
    wheel = wheel_rows[0]
    if any(binding[name] != wheel[name] for name in ("filename", "sha256", "url_sha256")):
        raise AgyCanaryEvidenceError("release wheel binding does not match its artifact")
    return release


def _installed_target(*, root: Path, environment_root: Path, row: dict[str, Any]) -> Path:
    base = environment_root if row["scheme"] == "data" else root
    target = base.joinpath(*row["installed_path"].split("/"))
    try:
        resolved = target.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("installed wheel file is missing") from exc
    if resolved != target or (resolved != base and base not in resolved.parents):
        raise AgyCanaryEvidenceError("installed wheel path escapes its canonical scheme")
    return target


def _record_relative(*, root: Path, target: Path) -> str:
    relative = os.path.relpath(target, root).replace(os.sep, "/")
    if not relative or "\\" in relative or relative.startswith("/"):
        raise AgyCanaryEvidenceError("installed RECORD mapping is malformed")
    return relative


def _uv_console_script_bytes(*, interpreter: Path, target: str) -> bytes:
    """Derive uv's deterministic POSIX console launcher from trusted inputs."""
    match = re.fullmatch(
        r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):([A-Za-z_]\w*)", target
    )
    if not interpreter.is_absolute() or match is None:
        raise AgyCanaryEvidenceError("console launcher authority is malformed")
    module, function = match.groups()
    if "'" in str(interpreter) or "\n" in str(interpreter):
        raise AgyCanaryEvidenceError("console launcher interpreter path is unsafe")
    body = (
        "# -*- coding: utf-8 -*-\n"
        "import sys\n"
        f"from {module} import {function}\n"
        'if __name__ == "__main__":\n'
        '    if sys.argv[0].endswith("-script.pyw"):\n'
        "        sys.argv[0] = sys.argv[0][:-11]\n"
        '    elif sys.argv[0].endswith(".exe"):\n'
        "        sys.argv[0] = sys.argv[0][:-4]\n"
        f"    sys.exit({function}())\n"
    ).encode("utf-8")
    shebang = f"#!{interpreter}\n".encode("utf-8")
    if len(shebang) <= 127 and " " not in str(interpreter):
        return shebang + body
    return (
        "#!/bin/sh\n"
        f"'''exec' '{interpreter}' \"$0\" \"$@\"\n"
        "' '''\n"
    ).encode("utf-8") + body


def _validate_uv_console_script(
    *, data: bytes, environment_root: Path, interpreter: Path, target: str,
) -> None:
    """Compare uv's exact launcher template against wheel and interpreter authority."""
    launcher_interpreter = environment_root / "bin" / "python"
    try:
        launcher_environment = launcher_interpreter.parent.parent.resolve(strict=True)
        launcher_source = launcher_interpreter.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("installed console launcher interpreter is malformed") from exc
    if (not launcher_interpreter.is_absolute() or launcher_interpreter.name != "python" or
            launcher_interpreter.parent.name != "bin" or
            launcher_environment != environment_root or launcher_source != interpreter):
        raise AgyCanaryEvidenceError("installed console launcher interpreter is not trusted")
    if data != _uv_console_script_bytes(interpreter=launcher_interpreter, target=target):
        raise AgyCanaryEvidenceError("installed console launcher differs from wheel authority")


def _validate_uv_cache(data: bytes) -> None:
    """Admit only uv's inert, RECORD-sealed wheel cache metadata."""
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgyCanaryEvidenceError("installed uv cache metadata is malformed") from exc
    timestamp = value.get("timestamp") if isinstance(value, dict) else None
    if (not isinstance(value, dict) or set(value) != {
            "timestamp", "commit", "tags", "env", "directories"
    } or not isinstance(timestamp, dict) or set(timestamp) != {
            "secs_since_epoch", "nanos_since_epoch"
    } or not _is_plain_int(timestamp.get("secs_since_epoch")) or
            timestamp["secs_since_epoch"] < 0 or
            not _is_plain_int(timestamp.get("nanos_since_epoch")) or
            not 0 <= timestamp["nanos_since_epoch"] < 1_000_000_000 or
            value["commit"] is not None or value["tags"] is not None or
            value["env"] != {} or value["directories"] != {}):
        raise AgyCanaryEvidenceError("installed uv cache metadata is malformed")


def _validate_installed_wheel_binding(
    *, installation: dict[str, Any], release: dict[str, Any],
) -> None:
    """Prove uv's installed distribution is the exact reauthenticated wheel."""
    _validate_release_identity(release)
    _validate_installation_identity(installation)
    _validate_interpreter_authority(
        installation["interpreter_authority"], revalidate=True
    )
    _validate_uv_store_authority(
        installation["uv_store_authority"], revalidate=True
    )
    root = Path(installation["distribution_root"])
    environment_root = Path(installation["environment_root"])
    package_root = Path(installation["module_origin"]).parent
    interpreter = Path(installation["interpreter"])
    if (installation.get("version") != release["version"] or
            installation.get("provenance", {}).get("requirement") !=
            f"phase-loop-runtime=={release['version']}" or
            not root.is_absolute() or not environment_root.is_absolute() or
            not root.is_relative_to(environment_root) or
            not package_root.is_relative_to(root)):
        raise AgyCanaryEvidenceError("installed phase-loop registry receipt does not match verified release")
    binding = release["wheel_binding"]
    expected_rows: dict[str, tuple[str, int, Path]] = {}
    expected_physical: set[Path] = set()
    for row in binding["files"]:
        target = _installed_target(root=root, environment_root=environment_root, row=row)
        relative = _record_relative(root=root, target=target)
        if relative in expected_rows:
            raise AgyCanaryEvidenceError("wheel files alias one installed target")
        data, _info = _read_regular_path(target)
        if len(data) != row["size"] or _sha256(data) != row["sha256"]:
            raise AgyCanaryEvidenceError("installed wheel file differs from verified wheel")
        expected_rows[relative] = (row["sha256"], row["size"], target)
        expected_physical.add(target)
    dist_info = root / f"phase_loop_runtime-{release['version']}.dist-info"
    record = dist_info / "RECORD"
    launcher_interpreter = environment_root / "bin" / "python"
    try:
        launcher_interpreter_source = launcher_interpreter.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise AgyCanaryEvidenceError("installed launcher interpreter is unavailable") from exc
    if launcher_interpreter_source != interpreter:
        raise AgyCanaryEvidenceError("installed launcher interpreter differs from trusted runtime")
    console_targets = {
        _record_relative(root=root, target=environment_root / "bin" / row["name"]):
            environment_root / "bin" / row["name"]
        for row in binding["console_scripts"]
    }
    installer_targets = {
        _record_relative(root=root, target=dist_info / "INSTALLER"): dist_info / "INSTALLER",
        _record_relative(root=root, target=dist_info / "REQUESTED"): dist_info / "REQUESTED",
        _record_relative(root=root, target=dist_info / "uv_cache.json"): dist_info / "uv_cache.json",
        **console_targets,
    }
    record_relative = _record_relative(root=root, target=record)
    record_bytes, _record_info = _read_regular_path(record)
    rows = _record_rows(record_bytes, wheel=False)
    actual: dict[str, tuple[str, int, Path]] = {}
    allowed = set(expected_rows) | set(installer_targets) | {record_relative}
    for path, digest_text, size_text in rows:
        if path not in allowed:
            raise AgyCanaryEvidenceError("installed RECORD contains an extra governed file")
        if path == record_relative:
            if digest_text or size_text:
                raise AgyCanaryEvidenceError("installed RECORD self-row is not empty")
            actual[path] = ("", 0, record)
            continue
        if not size_text.isdigit() or str(int(size_text)) != size_text:
            raise AgyCanaryEvidenceError("installed RECORD size is malformed")
        digest = _record_digest(digest_text)
        target = expected_rows[path][2] if path in expected_rows else installer_targets[path]
        data, _info = _read_regular_path(target)
        size = int(size_text)
        if len(data) != size or _sha256(data) != digest:
            raise AgyCanaryEvidenceError("installed RECORD does not authenticate installed bytes")
        actual[path] = (digest, size, target)
    if set(actual) != allowed:
        raise AgyCanaryEvidenceError("installed RECORD is missing governed files")
    for path, (digest, size, _target) in expected_rows.items():
        if actual[path][:2] != (digest, size):
            raise AgyCanaryEvidenceError("installed RECORD differs from verified wheel RECORD")
    for row in binding["console_scripts"]:
        script = environment_root / "bin" / row["name"]
        script_bytes, script_info = _read_regular_path(script)
        _validate_uv_console_script(
            data=script_bytes, environment_root=environment_root,
            interpreter=interpreter, target=row["target"],
        )
        if not script_info.st_mode & stat.S_IXUSR:
            raise AgyCanaryEvidenceError("installed console launcher is not executable")
    _validate_uv_cache(_read_regular_path(dist_info / "uv_cache.json")[0])
    phase_script = environment_root / "bin" / "phase-loop"
    script_bytes, _script_info = _read_regular_path(phase_script)
    interpreter_bytes, _interpreter_info = _read_regular_path(interpreter)
    if (Path(installation["console_script"]) != phase_script or
            _sha256(script_bytes) != installation["console_script_sha256"] or
            _sha256(interpreter_bytes) != installation["interpreter_sha256"] or
            _sha256(record_bytes) != installation["record_sha256"] or
            _runtime_tree_sha256(package_root) != installation["package_tree_sha256"]):
        raise AgyCanaryEvidenceError("installed launcher or runtime identity drifted")
    expected_physical.update({
        record, dist_info / "INSTALLER", dist_info / "REQUESTED",
        dist_info / "uv_cache.json",
    })
    expected_directories: set[Path] = set()
    for expected_path in expected_physical:
        for governed_root in (package_root, dist_info):
            if expected_path.is_relative_to(governed_root):
                parent = expected_path.parent
                while parent != governed_root.parent:
                    expected_directories.add(parent)
                    if parent == governed_root:
                        break
                    parent = parent.parent
    for governed_root in (package_root, dist_info):
        for current, directories, files in os.walk(governed_root, topdown=True, followlinks=False):
            current_path = Path(current)
            for directory in tuple(directories):
                child = current_path / directory
                if child.is_symlink():
                    raise AgyCanaryEvidenceError("installed distribution contains a symlink")
                if (directory == "__pycache__" and
                        child not in expected_directories):
                    raise AgyCanaryEvidenceError(
                        "installed distribution contains unrecorded bytecode"
                    )
            for name in files:
                path = current_path / name
                if path not in expected_physical:
                    raise AgyCanaryEvidenceError("installed distribution contains an extra governed file")


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
    if not isinstance(artifacts, list) or len(artifacts) != 2:
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
    expected_pairs = {
        (f"phase_loop_runtime-{value['version']}-py3-none-any.whl", "bdist_wheel"),
        (f"phase_loop_runtime-{value['version']}.tar.gz", "sdist"),
    }
    if {(name, kind) for name, kind, _url in identities} != expected_pairs:
        raise AgyCanaryEvidenceError("merged handoff artifacts are not the canonical pair")
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
    _validate_git_repository_authority(repo, require_inert_exclude=True)
    if _git_worktree_is_dirty(repo):
        raise AgyCanaryEvidenceError("release lineage requires a clean agent-harness worktree")
    remote = _git_text(repo, "remote", "get-url", "origin")
    if remote not in {"https://github.com/Consiliency/agent-harness.git", "git@github.com:Consiliency/agent-harness.git"}:
        raise AgyCanaryEvidenceError("release lineage requires canonical Consiliency/agent-harness origin")
    canonical_main = "refs/remotes/phase-loop/canonical-main"
    fetched = _git_run(
        repo, "fetch", "--quiet", "origin", "+refs/heads/main:" + canonical_main,
        "+refs/tags/v*:refs/tags/v*",
    )
    if fetched.returncode != 0:
        raise AgyCanaryEvidenceError("release lineage could not refresh canonical origin")
    resolved = _git_text(repo, "rev-parse", f"{handoff_commit}^{{commit}}")
    if resolved != handoff_commit:
        raise AgyCanaryEvidenceError("handoff selector must not be a movable ref")
    if _git_text(repo, "diff", "--name-only", f"{resolved}^", resolved).splitlines() != ["docs/releases/outside-agent-release-handoff.md"]:
        raise AgyCanaryEvidenceError("handoff commit changes paths outside the release handoff")
    # A handoff is authoritative only after its commit is reachable from the
    # fetched main branch, never merely present in an arbitrary local branch.
    if _git_run(repo, "merge-base", "--is-ancestor", resolved, canonical_main).returncode != 0:
        raise AgyCanaryEvidenceError("handoff commit is not merged into origin/main")
    handoff = _release_handoff_record(_git_run(
        repo, "show", f"{resolved}:docs/releases/outside-agent-release-handoff.md",
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
    if _git_run(repo, "verify-tag", "--raw", f"refs/tags/{tag}").returncode != 0:
        raise AgyCanaryEvidenceError("release tag signature verification failed")
    release = _github_run(
        "release", "view", tag, "--repo",
        "github.com/Consiliency/agent-harness", "--json", "url,tagName",
    )
    try:
        release_value = json.loads(release.stdout)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("GitHub Release lookup failed") from exc
    if release.returncode != 0 or not isinstance(release_value, dict) or release_value.get("tagName") != tag or release_value.get("url") != handoff.get("release_url"):
        raise AgyCanaryEvidenceError("GitHub Release does not match merged handoff")
    workflow_definition = _github_run(
        "api", "--hostname", "github.com", "-H",
        "Accept: application/vnd.github+json",
        "repos/Consiliency/agent-harness/actions/workflows/publish-pypi.yml",
    )
    try:
        workflow_value = json.loads(workflow_definition.stdout)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("publish workflow definition lookup failed") from exc
    if (workflow_definition.returncode != 0 or not isinstance(workflow_value, dict) or
            not _is_plain_int(workflow_value.get("id")) or workflow_value["id"] <= 0 or
            workflow_value.get("path") != ".github/workflows/publish-pypi.yml" or
            workflow_value.get("state") != "active"):
        raise AgyCanaryEvidenceError("publish workflow definition is not active and canonical")
    workflow_id = workflow_value["id"]
    workflow = _github_run(
        "api", "--hostname", "github.com", "--paginate", "-H",
        "Accept: application/vnd.github+json",
        f"repos/Consiliency/agent-harness/actions/workflows/{workflow_id}/runs?event=push&head_sha={release_commit}&per_page=100",
    )
    try:
        pages = [json.loads(line) for line in workflow.stdout.splitlines() if line]
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("publish workflow lookup failed") from exc
    if (workflow.returncode != 0 or not pages or
            any(not isinstance(page, dict) or set(page) != {
                "total_count", "workflow_runs"
            } or not _is_plain_int(page.get("total_count")) or
                page["total_count"] < 0 or not isinstance(page.get("workflow_runs"), list)
                for page in pages)):
        raise AgyCanaryEvidenceError("publish workflow pagination is malformed")
    totals = {page["total_count"] for page in pages}
    runs = [row for page in pages for row in page["workflow_runs"]]
    if (len(pages) != 1 or totals != {len(runs)} or len(runs) != 1 or not all(
            isinstance(row, dict) and row.get("workflow_id") == workflow_id and
            row.get("event") == "push" and row.get("head_sha") == release_commit and
            row.get("head_branch") == tag and row.get("status") == "completed" and
            row.get("conclusion") == "success" and
            row.get("html_url") == handoff.get("workflow_url")
            for row in runs
    )):
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
        identity = (row["filename"], row["packagetype"], row["url"])
        if identity in expected:
            raise AgyCanaryEvidenceError("PyPI artifact rows are duplicated")
        expected[identity] = digest
    recorded: dict[tuple[str, str, str], str] = {}
    for row in artifacts:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in ("filename", "packagetype", "url", "sha256")):
            raise AgyCanaryEvidenceError("handoff artifact row is malformed")
        recorded[(row["filename"], row["packagetype"], row["url"])] = row["sha256"]
    if expected != recorded or not any(name.endswith(".whl") for name, _kind, _url in expected) or not any(name.endswith(".tar.gz") for name, _kind, _url in expected):
        raise AgyCanaryEvidenceError("handoff artifacts do not exactly match PyPI")
    downloads: dict[tuple[str, str, str], bytes] = {}
    for identity, digest in expected.items():
        _filename, _kind, url = identity
        downloads[identity] = download(url)
        if _sha256(downloads[identity]) != digest:
            raise AgyCanaryEvidenceError("downloaded release artifact digest mismatch")
    wheel_identities = [identity for identity in expected if identity[0].endswith(".whl")]
    if len(wheel_identities) != 1:
        raise AgyCanaryEvidenceError("release lineage has no unique wheel")
    wheel_identity = wheel_identities[0]
    wheel_filename, _wheel_kind, wheel_url = wheel_identity
    wheel_binding = _wheel_binding(
        wheel_bytes=downloads[wheel_identity], filename=wheel_filename,
        digest=expected[wheel_identity], url_sha256=_sha256(wheel_url.encode()),
        version=version,
    )
    value = {
        "version": version, "handoff_commit": resolved, "release_commit": release_commit,
        "tag_object": tag_object, "tag_peel": tag_peel,
        "artifacts": [
            {"filename": name, "packagetype": kind, "sha256": digest, "url_sha256": _sha256(url.encode())}
            for (name, kind, url), digest in sorted(expected.items())
        ],
        "wheel_binding": wheel_binding,
    }
    return _validate_release_identity(value)


def _require_complete_capability_probe(*, probe: dict[str, Any], root_fd: int) -> None:
    """Reject legacy or caller-shaped probe receipts before a canary can use them."""
    if (set(probe) != {"schema", "agy_version", "agy_runtime", "help_sha256", "mode", "complete", "classes", "staged"} or
            probe.get("schema") != _CAPABILITY_PROBE_SCHEMA or probe.get("agy_version") != "1.1.13" or
            probe.get("mode") != "stream_json" or probe.get("complete") is not True or
            not isinstance(probe.get("help_sha256"), str) or len(probe["help_sha256"]) != 64 or
            any(char not in "0123456789abcdef" for char in probe["help_sha256"].lower())):
        raise AgyCanaryEvidenceError("capability probe has not selected a complete matrix authority")
    runtime = _sealed_agy_runtime(probe["agy_runtime"])
    if probe["agy_runtime"]["version"] != probe["agy_version"]:
        raise AgyCanaryEvidenceError("capability probe agy runtime version is malformed")
    runtime.revalidate()
    staged = probe.get("staged")
    if not isinstance(staged, dict) or set(staged) != {"review-instructions.md", "review-bundle.md"}:
        raise AgyCanaryEvidenceError("capability probe staged authority is malformed")
    staged_contents: dict[str, bytes] = {}
    for name, record in staged.items():
        if (not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"} or
                record.get("name") != f"agy-capability-stage-{name}" or not _is_plain_int(record.get("bytes")) or
                record["bytes"] < 1 or not _is_digest(record.get("sha256"))):
            raise AgyCanaryEvidenceError("capability probe staged authority is malformed")
        content = _read_regular_at(root_fd, record["name"])
        if len(content) != record["bytes"] or _sha256(content) != record["sha256"]:
            raise AgyCanaryEvidenceError("capability probe staged authority drifted")
        staged_contents[f"/run/phase-loop-review/{name}"] = content
    classes = probe["classes"]
    if not isinstance(classes, list) or len(classes) != len(_CAPABILITY_CLASSES):
        raise AgyCanaryEvidenceError("capability probe matrix is incomplete")
    expected = {item[0]: item[1:] for item in _CAPABILITY_CLASSES}
    for row in classes:
        if not isinstance(row, dict) or set(row) != {"class", "tool", "target", "attempt", "execution", "result", "outcome", "stream"}:
            raise AgyCanaryEvidenceError("capability probe matrix row is malformed")
        class_name = row.get("class")
        if class_name not in expected:
            raise AgyCanaryEvidenceError("capability probe matrix has an unknown class")
        tool, target, outcome = expected.pop(class_name)
        stream = row.get("stream")
        if (row.get("tool"), row.get("target"), row.get("attempt"), row.get("execution"),
                row.get("result"), row.get("outcome")) != (tool, target, True, True, "text", outcome) or (
                not isinstance(stream, dict) or set(stream) != {"name", "bytes", "sha256"} or
                stream.get("name") != f"agy-capability-{class_name}.jsonl" or
                not _is_plain_int(stream.get("bytes")) or stream["bytes"] < 1 or
                not _is_digest(stream.get("sha256"))):
            raise AgyCanaryEvidenceError("capability probe matrix row is not exact")
        raw = _read_regular_at(root_fd, stream["name"])
        if len(raw) != stream["bytes"] or _sha256(raw) != stream["sha256"]:
            raise AgyCanaryEvidenceError("capability probe raw matrix artifact drifted")
        reduced = _reduce_capability_class(
            capability=(class_name, tool, target, outcome), data=raw,
            namespace=AgyCanaryNamespace(Path("/"), Path("/"), Path("/"), "invalid"),
            stream_name=stream["name"], staged_contents=staged_contents,
        )
        if reduced != row:
            raise AgyCanaryEvidenceError("capability probe row is not independently reducible")
    if expected:
        raise AgyCanaryEvidenceError("capability probe matrix has missing classes")


def _validate_launch_authority(*, authority: Any, ledger: dict[str, Any], root_fd: int) -> None:
    """Validate immutable prepare authority without consulting mutable attempts."""
    required = {
        "schema", "seat_key", "capture_mode", "authorized_attempt_ids", "cleanup_sha256",
        "probe_sha256", "bootstrap_sha256", "release", "release_sha256",
        "wheel_binding_sha256", "installation_sha256", "settings",
        "policy_sha256", "source_inventory_sha256", "customization_sources",
        "minimal_home", "auth_binds", "agy_runtime",
    }
    if not isinstance(authority, dict) or set(authority) != required or authority.get("schema") != "agy_canary_launch_authority.v1":
        raise AgyCanaryEvidenceError("prepare launch authority schema is malformed")
    if (authority.get("seat_key") != ledger.get("seat_key") or
            authority.get("capture_mode") != ledger.get("capture_mode") or
            authority.get("capture_mode") != "stream_json"):
        raise AgyCanaryEvidenceError("prepare launch authority seat or mode drifted")
    attempt_ids = authority.get("authorized_attempt_ids")
    if (not isinstance(attempt_ids, list) or attempt_ids != ["gemini-1", "gemini-2"] or  # model-id-source: canary attempt IDs, not models
            len(set(attempt_ids)) != len(attempt_ids)):
        raise AgyCanaryEvidenceError("prepare launch authority attempts are not exact")
    for field in ("cleanup_sha256", "probe_sha256", "bootstrap_sha256", "release_sha256", "wheel_binding_sha256", "installation_sha256", "policy_sha256", "source_inventory_sha256"):
        if not _is_digest(authority.get(field)):
            raise AgyCanaryEvidenceError("prepare launch authority digest is malformed")
    customization_sources = authority.get("customization_sources")
    _revalidate_customization_source_authority(customization_sources)
    if (customization_sources != ledger.get("customization_sources") or
            authority["source_inventory_sha256"] !=
            _sha256(_canonical_json(customization_sources["inventory"]))):
        raise AgyCanaryEvidenceError(
            "prepare launch authority customization sources drifted"
        )
    release = _validate_release_identity(authority.get("release"))
    if (authority["release_sha256"] != _sha256(_canonical_json(release)) or
            authority["wheel_binding_sha256"] !=
            _sha256(_canonical_json(release["wheel_binding"]))):
        raise AgyCanaryEvidenceError("prepare launch authority release binding drifted")
    settings = authority.get("settings")
    if (not isinstance(settings, dict) or set(settings) != {"path", "bytes", "sha256", "mode"} or
            not isinstance(settings.get("path"), str) or not Path(settings["path"]).is_absolute() or
            not _is_plain_int(settings.get("bytes")) or settings["bytes"] < 1 or
            not _is_digest(settings.get("sha256")) or settings.get("mode") != "0600"):
        raise AgyCanaryEvidenceError("prepare launch authority settings are malformed")
    opened = _open_settings(Path(settings["path"]))
    try:
        if (len(opened.data) != settings["bytes"] or _sha256(opened.data) != settings["sha256"] or
                format(opened.mode, "04o") != settings["mode"] or
                _sha256(_canonical_json(_parse_policy(opened.data))) != authority.get("policy_sha256")):
            raise AgyCanaryEvidenceError("prepare launch authority settings drifted")
    finally:
        os.close(opened.fd)
        os.close(opened.parent_fd)
    minimal = authority.get("minimal_home")
    if (not isinstance(minimal, dict) or set(minimal) != {"path", "identity"} or
            not isinstance(minimal.get("path"), str) or not Path(minimal["path"]).is_absolute() or
            not isinstance(minimal.get("identity"), dict)):
        raise AgyCanaryEvidenceError("prepare launch authority minimal HOME is malformed")
    identity = minimal["identity"]
    if (set(identity) != {
            "settings_bytes", "settings_sha256", "settings_mode",
            "policy_sha256", "tree",
        } or
            not _is_plain_int(identity.get("settings_bytes")) or identity["settings_bytes"] < 1 or
            not _is_digest(identity.get("settings_sha256")) or identity.get("settings_mode") != "0600" or
            not _is_digest(identity.get("policy_sha256")) or
            not isinstance(identity.get("tree"), dict) or
            identity["settings_sha256"] != settings["sha256"] or identity["settings_bytes"] != settings["bytes"]):
        raise AgyCanaryEvidenceError("prepare launch authority minimal HOME identity is malformed")
    if _minimal_home_identity(Path(minimal["path"])) != identity:
        raise AgyCanaryEvidenceError("prepare launch authority minimal HOME drifted")
    binds = authority.get("auth_binds")
    if not isinstance(binds, list) or len({item.get("destination") for item in binds if isinstance(item, dict)}) != len(binds):
        raise AgyCanaryEvidenceError("prepare launch authority auth bindings are malformed")
    for bind in binds:
        if (not isinstance(bind, dict) or set(bind) != {"source", "destination", "source_sha256", "uid", "mode"} or
                not isinstance(bind.get("source"), str) or not Path(bind["source"]).is_absolute() or
                not isinstance(bind.get("destination"), str) or not bind["destination"].startswith("/home/phase-loop/") or
                not _is_digest(bind.get("source_sha256")) or not isinstance(bind.get("uid"), str) or
                not bind["uid"].isdigit() or bind.get("mode") != "0600"):
            raise AgyCanaryEvidenceError("prepare launch authority auth binding is malformed")
    bootstrap = _validate_bootstrap_attestation(
        receipt=_read_json_at(root_fd, "agy_canary_bootstrap_attestation.json")
    )
    if (authority["bootstrap_sha256"] != _sha256(_canonical_json(bootstrap)) or
            authority["installation_sha256"] !=
            _sha256(_canonical_json(bootstrap["bootstrap"]["installation"]))):
        raise AgyCanaryEvidenceError("prepare launch authority installation binding drifted")
    probe = _read_json_at(root_fd, _PROBE_NAME)
    if authority["probe_sha256"] != _sha256(_canonical_json(probe)):
        raise AgyCanaryEvidenceError("prepare launch authority probe drifted")
    _require_complete_capability_probe(probe=probe, root_fd=root_fd)
    if authority.get("agy_runtime") != probe.get("agy_runtime"):
        raise AgyCanaryEvidenceError("prepare launch authority agy runtime drifted")


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
        _require_complete_capability_probe(probe=probe, root_fd=root_fd)
        bootstrap_receipt = _read_json_at(root_fd, "agy_canary_bootstrap_attestation.json")
        bootstrap = _validate_bootstrap_attestation(receipt=bootstrap_receipt)
        interpreter_authority = bootstrap["bootstrap"]["interpreter_authority"]
        uv_store_authority = bootstrap["bootstrap"]["uv_store_authority"]
        current_installation = _installed_phase_loop_identity(
            interpreter_authority=interpreter_authority,
            uv_store_authority=uv_store_authority,
            uv_environment=bootstrap["bootstrap"]["uv_environment"],
        )
        bootstrap = _validate_bootstrap_attestation(
            receipt=bootstrap_receipt, installation=current_installation,
        )
        installation = bootstrap["bootstrap"]["installation"]
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
        _validate_release_identity(release)
        _validate_installed_wheel_binding(installation=installation, release=release)
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
            bind_records.append({
                "source": str(source), "destination": destination, "source_sha256": _sha256(data),
                "uid": str(_info.st_uid), "mode": format(stat.S_IMODE(_info.st_mode), "04o"),
            })
        ledger["auth_binds"] = bind_records
        _write_replace_at(root_fd, _LEDGER_NAME, ledger)
        minimal_identity = _minimal_home_identity(minimal_home)
        if (minimal_identity["settings_sha256"] != cleanup_lineage["settings_sha256"] or
                minimal_identity["settings_bytes"] != cleanup_lineage["settings_bytes"] or
                minimal_identity["settings_mode"] != cleanup_lineage["settings_mode"]):
            raise AgyCanaryEvidenceError("minimal HOME settings do not match cleaned source")
        authority = {
            "schema": "agy_canary_launch_authority.v1",
            "seat_key": seat_key,
            "capture_mode": str(probe["mode"]),
            "authorized_attempt_ids": ["gemini-1", "gemini-2"],  # model-id-source: canary attempt IDs, not models
            "cleanup_sha256": _sha256(_canonical_json(cleanup)),
            "probe_sha256": _sha256(_canonical_json(probe)),
            "bootstrap_sha256": _sha256(_canonical_json(bootstrap)),
            "release": release,
            "release_sha256": _sha256(_canonical_json(release)),
            "wheel_binding_sha256": _sha256(_canonical_json(release["wheel_binding"])),
            "installation_sha256": _sha256(_canonical_json(installation)),
            "settings": {"path": str(settings_path.resolve(strict=True)), "bytes": cleanup_lineage["settings_bytes"], "sha256": cleanup_lineage["settings_sha256"], "mode": cleanup_lineage["settings_mode"]},
            "policy_sha256": minimal_identity["policy_sha256"],
            "source_inventory_sha256": _sha256(_canonical_json(source_inventory)),
            "customization_sources": ledger["customization_sources"],
            "minimal_home": {"path": str(minimal_home), "identity": minimal_identity},
            "auth_binds": bind_records,
            "agy_runtime": probe["agy_runtime"],
        }
        _validate_launch_authority(authority=authority, ledger=ledger, root_fd=root_fd)
        _exclusive_write_at(root_fd, _LAUNCH_AUTHORITY_NAME, _canonical_json(authority), 0o600)
        value = {
            "schema": "agy_canary_prepare.v1", "authority_name": _LAUNCH_AUTHORITY_NAME,
            "authority_sha256": _sha256(_canonical_json(authority)),
            "cleanup_sha256": authority["cleanup_sha256"], "probe_sha256": authority["probe_sha256"],
            "bootstrap_sha256": authority["bootstrap_sha256"], "ledger_sha256": _sha256(_canonical_json(ledger)),
            "settings_sha256": cleanup_lineage["settings_sha256"], "settings_bytes": cleanup_lineage["settings_bytes"],
            "settings_mode": cleanup_lineage["settings_mode"], "seat_key": seat_key, "release": release,
            "release_sha256": authority["release_sha256"],
            "wheel_binding_sha256": authority["wheel_binding_sha256"],
            "installation_sha256": authority["installation_sha256"],
            "source_inventory_sha256": authority["source_inventory_sha256"],
        }
        _exclusive_write_at(root_fd, _PREPARE_NAME, _canonical_json(value), 0o600)
        return value
    finally:
        os.close(root_fd)


def capture_namespace(*, capture: AgyCanaryCapture, stage: Path, provider_hostname: str = "antigravity.google") -> AgyCanaryNamespace:
    """Recover the prepare-sealed minimal HOME for one production child launch."""
    ledger = _read_json_at(capture.root_fd, _LEDGER_NAME)
    prepare = _read_json_at(capture.root_fd, _PREPARE_NAME)
    authority = _read_json_at(capture.root_fd, _LAUNCH_AUTHORITY_NAME)
    if (not isinstance(prepare, dict) or prepare.get("schema") != "agy_canary_prepare.v1" or
            prepare.get("authority_name") != _LAUNCH_AUTHORITY_NAME or
            prepare.get("authority_sha256") != _sha256(_canonical_json(authority)) or
            prepare.get("seat_key") != authority.get("seat_key")):
        raise AgyCanaryEvidenceError("capture namespace requires the exact prepare receipt")
    _validate_launch_authority(authority=authority, ledger=ledger, root_fd=capture.root_fd)
    if authority.get("capture_mode") != "stream_json":
        raise AgyCanaryEvidenceError("production launch has no supported stream-json authority")
    minimal = authority.get("minimal_home")
    if not isinstance(minimal, dict) or not isinstance(minimal.get("path"), str):
        raise AgyCanaryEvidenceError("prepare did not seal a minimal HOME")
    home = Path(minimal["path"])
    info = home.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise AgyCanaryEvidenceError("sealed minimal HOME is invalid")
    if _minimal_home_identity(home) != minimal.get("identity"):
        raise AgyCanaryEvidenceError("prepared minimal HOME settings drifted")
    freeze_customization_inventory(home=home, project_dir=stage, env={})
    _revalidate_customization_source_authority(authority["customization_sources"])
    auth_records = authority.get("auth_binds", [])
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
    return AgyCanaryNamespace(stage=stage, minimal_home=home, evidence_root=capture.root, provider_hostname=provider_hostname, auth_binds=tuple(auth_binds), resolver_source=resolver, resolver_sha256=resolver_sha256, agy_runtime=_sealed_agy_runtime(authority["agy_runtime"]))


def _open_final_target(path: Path, replacement: bytes) -> _FinalTarget:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise AgyCanaryEvidenceError("finalizer target must be an absolute file path")
    parent = path.parent.resolve(strict=True)
    parent_info = parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise AgyCanaryEvidenceError("finalizer target parent must be a real directory")
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        current, info = _reopen_at(parent_fd, path.name)
        if not stat.S_ISREG(info.st_mode):
            raise AgyCanaryEvidenceError("finalizer target is not a regular file")
        return _FinalTarget(
            parent_fd=parent_fd,
            name=path.name,
            data=current,
            replacement=replacement,
            mode=stat.S_IMODE(info.st_mode),
            device=info.st_dev,
            inode=info.st_ino,
        )
    except Exception:
        os.close(parent_fd)
        raise


def _final_target_matches_preimage(target: _FinalTarget) -> bool:
    current, info = _reopen_at(target.parent_fd, target.name)
    return (
        current == target.data
        and (info.st_dev, info.st_ino) == (target.device, target.inode)
        and stat.S_IMODE(info.st_mode) == target.mode
    )


def _verify_final_target_exchange(target: _FinalTarget) -> None:
    if target.temporary is None:
        raise AgyCanaryEvidenceError("finalizer exchange lacks a staged replacement")
    destination, destination_info = _reopen_at(target.parent_fd, target.name)
    swapped_original, swapped_info = _reopen_at(target.parent_fd, target.temporary)
    if (
        destination != target.replacement
        or stat.S_IMODE(destination_info.st_mode) != target.mode
        or swapped_original != target.data
        or (swapped_info.st_dev, swapped_info.st_ino) != (target.device, target.inode)
        or stat.S_IMODE(swapped_info.st_mode) != target.mode
    ):
        raise AgyCanaryEvidenceError("finalizer exchanged target failed identity, byte, or mode validation")


def _restore_final_target(target: _FinalTarget) -> bool:
    if target.temporary is None:
        return False
    _rename_exchange(target.parent_fd, target.name, target.temporary)
    os.fsync(target.parent_fd)
    restored, restored_info = _reopen_at(target.parent_fd, target.name)
    replacement, replacement_info = _reopen_at(target.parent_fd, target.temporary)
    if (
        restored != target.data
        or (restored_info.st_dev, restored_info.st_ino) != (target.device, target.inode)
        or stat.S_IMODE(restored_info.st_mode) != target.mode
        or replacement != target.replacement
        or stat.S_IMODE(replacement_info.st_mode) != target.mode
    ):
        return False
    target.exchanged = False
    return True


def _discard_final_target_temporary(target: _FinalTarget) -> None:
    if target.temporary is None:
        return
    os.unlink(target.temporary, dir_fd=target.parent_fd)
    os.fsync(target.parent_fd)
    target.temporary = None


def _finalize_targets_transactionally(plan_target: _FinalTarget, manifest_target: _FinalTarget) -> None:
    targets = (plan_target, manifest_target)
    recovery_required = False
    committed = False
    try:
        plan_parent = os.fstat(plan_target.parent_fd)
        manifest_parent = os.fstat(manifest_target.parent_fd)
        if (
            (plan_parent.st_dev, plan_parent.st_ino, plan_target.name)
            == (manifest_parent.st_dev, manifest_parent.st_ino, manifest_target.name)
        ):
            raise AgyCanaryEvidenceError("finalizer targets must be distinct")
        if not all(_final_target_matches_preimage(target) for target in targets):
            raise AgyCanaryEvidenceError("finalizer target identity or bytes drifted before staging")
        for target in targets:
            target.temporary = f".phase-loop-agy-finalize-{target.name}.{secrets.token_hex(16)}.tmp"
            _exclusive_write_at(target.parent_fd, target.temporary, target.replacement, target.mode)
        for target in targets:
            if not _final_target_matches_preimage(target):
                raise AgyCanaryEvidenceError("finalizer target identity or bytes drifted before exchange")
            if target.temporary is None:
                raise AgyCanaryEvidenceError("finalizer replacement staging is incomplete")
            _rename_exchange(target.parent_fd, target.name, target.temporary)
            target.exchanged = True
            os.fsync(target.parent_fd)
            _verify_final_target_exchange(target)
        for target in targets:
            _verify_final_target_exchange(target)
        committed = True
        cleanup_errors: list[str] = []
        for target in targets:
            try:
                _discard_final_target_temporary(target)
            except OSError as exc:
                cleanup_errors.append(f"{target.name}:{type(exc).__name__}")
        if cleanup_errors:
            raise AgyCanaryEvidenceError(
                "finalizer committed with recovery residue: " + ", ".join(cleanup_errors)
            )
    except Exception:
        if committed:
            recovery_required = True
        else:
            rollback_proven = True
            for target in reversed(targets):
                if not target.exchanged:
                    continue
                try:
                    rollback_proven = _restore_final_target(target) and rollback_proven
                except Exception:
                    rollback_proven = False
            recovery_required = not rollback_proven
        if not recovery_required:
            for target in targets:
                _discard_final_target_temporary(target)
        raise


def _validate_final_attestation_envelope(attestation: Any) -> dict[str, Any]:
    if not isinstance(attestation, dict) or set(attestation) != _FINAL_ATTESTATION_KEYS:
        raise AgyCanaryEvidenceError("final attestation schema is malformed")
    completed_at = attestation.get("completed_at")
    try:
        completed = datetime.fromisoformat(completed_at) if isinstance(completed_at, str) else None
    except ValueError as exc:
        raise AgyCanaryEvidenceError("final attestation completion time is malformed") from exc
    if (
        completed is None
        or completed.tzinfo is None
        or completed.utcoffset() != timezone.utc.utcoffset(completed)
        or completed.isoformat() != completed_at
    ):
        raise AgyCanaryEvidenceError("final attestation completion time is malformed")
    manifest_sha256 = attestation.get("manifest_after_sha256")
    if (
        not isinstance(manifest_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None
    ):
        raise AgyCanaryEvidenceError("final attestation manifest digest is malformed")
    return attestation


def _final_suffix(proof: dict[str, Any], attestation: dict[str, Any]) -> bytes:
    _validate_final_proof(proof)
    _validate_final_attestation_envelope(attestation)
    payload = {"attestation": attestation, "proof": proof, "proof_sha256": _sha256(_canonical_json(proof)), "schema": "agy_canary_final.v1"}
    return b"\n## Execution evidence\n\n```json\n" + _canonical_json(payload) + b"```\n"


def _parse_final_payload(plan: bytes) -> tuple[bytes, dict[str, Any]]:
    marker = b"\n## Execution evidence\n\n```json\n"
    if plan.count(marker) != 1 or not plan.endswith(b"```\n"):
        raise AgyCanaryEvidenceError("final plan does not contain one canonical execution suffix")
    before, encoded = plan.split(marker, 1)
    return before, _parse_final_payload_encoding(encoded)


def _parse_final_payload_encoding(encoded: bytes) -> dict[str, Any]:
    if not encoded.endswith(b"```\n"):
        raise AgyCanaryEvidenceError("final execution payload is not terminal")
    try:
        payload = json.loads(encoded[:-4])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgyCanaryEvidenceError("final execution payload is not JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"attestation", "proof", "proof_sha256", "schema"} or payload.get("schema") != "agy_canary_final.v1" or not isinstance(payload.get("proof"), dict) or not isinstance(payload.get("attestation"), dict):
        raise AgyCanaryEvidenceError("final execution payload is invalid")
    if payload.get("proof_sha256") != _sha256(_canonical_json(payload["proof"])) or _canonical_json(payload) != encoded[:-4]:
        raise AgyCanaryEvidenceError("final execution payload is not canonical")
    _validate_final_proof(payload["proof"])
    return payload


def _has_canonical_final_suffix(plan: bytes) -> bool:
    marker = b"\n## Execution evidence\n\n```json\n"
    _before, separator, encoded = plan.rpartition(marker)
    if not separator:
        return False
    if not plan.endswith(b"```\n"):
        raise AgyCanaryEvidenceError("existing execution payload is not terminal")
    try:
        _parse_final_payload_encoding(encoded)
    except AgyCanaryEvidenceError as exc:
        raise AgyCanaryEvidenceError(
            "existing terminal execution payload is malformed"
        ) from exc
    return True


def _validate_final_proof(proof: dict[str, Any]) -> None:
    required = {"schema", "seat_key", "attempt_ids", "capture_mode", "attempts", "accepted_review_sha256", "private_board_sha256", "provider_results", "release_sha256", "wheel_binding_sha256", "installation_sha256", *_FINAL_GOVERNANCE_POSTURE}
    if any(name not in proof for name in _FINAL_GOVERNANCE_POSTURE):
        raise AgyCanaryEvidenceError("final proof governance posture is malformed")
    if set(proof) != required or proof.get("schema") != SCHEMA_VERSION or proof.get("capture_mode") not in _CAPTURE_MODES:
        raise AgyCanaryEvidenceError("final proof schema is malformed")
    if any(proof.get(name) != value for name, value in _FINAL_GOVERNANCE_POSTURE.items()):
        raise AgyCanaryEvidenceError("final proof governance posture is malformed")
    if not isinstance(proof.get("seat_key"), str) or not proof["seat_key"] or not isinstance(proof.get("attempt_ids"), list) or not isinstance(proof.get("attempts"), list):
        raise AgyCanaryEvidenceError("final proof seat binding is malformed")
    attempt_ids = proof["attempt_ids"]
    if (not attempt_ids or len(set(attempt_ids)) != len(attempt_ids) or any(not isinstance(item, str) or not item for item in attempt_ids) or
            len(proof["attempts"]) != len(attempt_ids)):
        raise AgyCanaryEvidenceError("final proof attempt binding is malformed")
    if any(not isinstance(item, dict) or set(item) != {"attempt_id", "counts", "terminal_sha256"} or item.get("attempt_id") != attempt_ids[index] or not isinstance(item.get("counts"), dict) or set(item["counts"]) != {"command", "unsandboxed", "non_read_tool", "out_of_stage_read"} or any(item["counts"].get(name) != 0 for name in item["counts"]) or not isinstance(item.get("terminal_sha256"), str) or len(item["terminal_sha256"]) != 64 or any(char not in "0123456789abcdef" for char in item["terminal_sha256"].lower()) for index, item in enumerate(proof["attempts"])):
        raise AgyCanaryEvidenceError("final proof attempts are malformed")
    for name in ("accepted_review_sha256", "private_board_sha256", "release_sha256", "wheel_binding_sha256", "installation_sha256"):
        value = proof.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise AgyCanaryEvidenceError("final proof digest is malformed")
    _validate_provider_result_summary(proof["provider_results"])


def _validate_provider_result_summary(value: Any) -> None:
    """Validate the redacted, provider-neutral result-set identity."""
    required = {"registry_sha256", "result_set_sha256", "providers"}
    if (not isinstance(value, dict) or set(value) != required or
            not _is_digest(value.get("registry_sha256")) or
            not _is_digest(value.get("result_set_sha256")) or
            not isinstance(value.get("providers"), list) or len(value["providers"]) != len(_CAPTURE_PROVIDERS)):
        raise AgyCanaryEvidenceError("final proof provider results are malformed")
    identities: set[tuple[str, str]] = set()
    providers: set[str] = set()
    seat_keys: set[str] = set()
    for item in value["providers"]:
        if (not isinstance(item, dict) or set(item) != {"provider", "seat_key"} or
                item.get("provider") not in _PROVIDER_EXECUTABLES or
                not isinstance(item.get("seat_key"), str) or not item["seat_key"] or
                Path(item["seat_key"]).name != item["seat_key"]):
            raise AgyCanaryEvidenceError("final proof provider result identity is malformed")
        identity = (item["provider"], item["seat_key"])
        if identity in identities or item["provider"] in providers or item["seat_key"] in seat_keys:
            raise AgyCanaryEvidenceError("final proof provider results are duplicated")
        identities.add(identity)
        providers.add(item["provider"])
        seat_keys.add(item["seat_key"])
    if providers != _CAPTURE_PROVIDERS:
        raise AgyCanaryEvidenceError("final proof provider results do not cover every provider")


def _proof_identity(proof: dict[str, Any]) -> dict[str, Any]:
    _validate_final_proof(proof)
    return {
        "seat_key": proof["seat_key"],
        "attempt_ids": proof["attempt_ids"],
        "private_board_sha256": proof["private_board_sha256"],
        "provider_results": proof["provider_results"],
        "release_sha256": proof["release_sha256"],
        "wheel_binding_sha256": proof["wheel_binding_sha256"],
        "installation_sha256": proof["installation_sha256"],
        **_FINAL_GOVERNANCE_POSTURE,
        "proof_sha256": _sha256(_canonical_json(proof)),
    }


def _bootstrap_final_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    """Project every immutable execution authority required after private cleanup."""
    return {
        "repo_head": receipt["repo_head"],
        "tree_snapshot": copy.deepcopy(receipt["tree_snapshot"]),
        "blobs": copy.deepcopy(receipt["blobs"]),
        "input_sha256": copy.deepcopy(receipt["input_sha256"]),
        "sandbox": copy.deepcopy(receipt["bootstrap"]["sandbox"]),
    }


def _attested_final_targets(
    *, root_fd: int, repo: Path, plan_path: Path, manifest_path: Path, plan_slug: str,
    require_preimages: bool = True,
) -> tuple[dict[str, Any], str, str]:
    bootstrap = _validate_bootstrap_attestation(
        receipt=_read_json_at(root_fd, "agy_canary_bootstrap_attestation.json"), repo=repo
    )
    current_head = _clean_dotfiles_repo(repo) if require_preimages else None
    if require_preimages and bootstrap.get("repo_head") != current_head:
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
    _validate_final_proof(proof)
    root, root_fd = _validate_private_root(evidence_root)
    try:
        repo = dotfiles_repo.resolve(strict=True)
        _validate_git_repository_authority(repo, require_inert_exclude=True)
        bootstrap_receipt, plan_relative, manifest_relative = _attested_final_targets(
            root_fd=root_fd, repo=repo, plan_path=plan_path, manifest_path=manifest_path, plan_slug=plan_slug,
            require_preimages=False,
        )
        inputs = _read_json_at(root_fd, _INPUTS_NAME)
        if (
            set(inputs) != _FINAL_INPUT_KEYS
            or inputs.get("schema") != "agy_canary_inputs.v1"
        ):
            raise AgyCanaryEvidenceError("private finalizer receipt schema is malformed")
        digest_names = (
            "proof_sha256", "plan_before_sha256", "plan_after_sha256",
            "manifest_before_sha256", "manifest_after_sha256",
        )
        if any(
            not isinstance(inputs.get(name), str)
            or re.fullmatch(r"[0-9a-f]{64}", inputs[name]) is None
            for name in digest_names
        ):
            raise AgyCanaryEvidenceError("private finalizer receipt digest is malformed")
        if (
            inputs.get("proof") != proof
            or inputs["proof_sha256"] != _sha256(_canonical_json(proof))
            or inputs.get("plan") != plan_relative
            or inputs.get("manifest") != manifest_relative
            or inputs.get("plan_slug") != plan_slug
        ):
            raise AgyCanaryEvidenceError("private finalizer receipt is not bound to current proof and targets")
        if not isinstance(inputs.get("plan_before_b64"), str) or not isinstance(inputs.get("manifest_before_b64"), str):
            raise AgyCanaryEvidenceError("private finalizer receipt preimages are malformed")
        plan_before = base64.b64decode(inputs["plan_before_b64"], validate=True)
        manifest_before = base64.b64decode(inputs["manifest_before_b64"], validate=True)
        if (
            inputs["plan_before_sha256"] != _sha256(plan_before)
            or inputs["manifest_before_sha256"] != _sha256(manifest_before)
        ):
            raise AgyCanaryEvidenceError("private finalizer receipt preimage digest is malformed")
        attestation = _validate_final_attestation_envelope(inputs.get("attestation"))
        completed_at = attestation["completed_at"]
        if inputs.get("completed_at") != completed_at:
            raise AgyCanaryEvidenceError("private finalizer receipt completion time is malformed")
        release = attestation.get("release")
        installation = attestation.get("installation")
        if (not isinstance(release, dict) or
                attestation.get("bootstrap") !=
                _bootstrap_final_identity(bootstrap_receipt) or
                attestation.get("release_sha256") != _sha256(_canonical_json(release)) or
                attestation.get("wheel_binding_sha256") !=
                _sha256(_canonical_json(release.get("wheel_binding"))) or
                attestation.get("installation_sha256") !=
                _sha256(_canonical_json(installation)) or
                attestation.get("proof") != _proof_identity(proof) or
                attestation.get("reducer_proof_sha256") != _sha256(_canonical_json(proof))):
            raise AgyCanaryEvidenceError("private finalizer release/proof binding is malformed")
        _validate_release_identity(release)
        _validate_installation_identity(installation)
        plan_after = plan_before + _final_suffix(proof, attestation)
        manifest_value = json.loads(manifest_before)
        entries = manifest_value.get("plans") if isinstance(manifest_value, dict) else None
        matches = [item for item in entries or [] if isinstance(item, dict) and item.get("slug") == plan_slug]
        if len(matches) != 1:
            raise AgyCanaryEvidenceError("private finalizer receipt has an invalid manifest preimage")
        matches[0]["updated_at"] = completed_at
        manifest_after = _canonical_json(manifest_value)
        manifest_after_sha256 = _sha256(manifest_after)
        if (
            inputs["plan_after_sha256"] != _sha256(plan_after)
            or inputs["manifest_after_sha256"] != manifest_after_sha256
            or attestation["manifest_after_sha256"] != manifest_after_sha256
        ):
            raise AgyCanaryEvidenceError("private finalizer manifest digest is malformed")
        candidate = bootstrap_receipt["repo_head"]
        candidate_plan = _git_run(repo, "show", f"{candidate}:{plan_relative}")
        candidate_manifest = _git_run(repo, "show", f"{candidate}:{manifest_relative}")
        if (candidate_plan.returncode != 0 or candidate_manifest.returncode != 0 or
                candidate_plan.stdout != plan_before or
                candidate_manifest.stdout != manifest_before):
            raise AgyCanaryEvidenceError(
                "private finalizer preimages differ from bootstrap candidate"
            )
        current_head = _git_text(repo, "rev-parse", "HEAD")
        if current_head == candidate:
            changed = _git_text(repo, "diff", "--name-only", candidate).splitlines()
            staged = _git_text(
                repo, "diff", "--cached", "--name-only", candidate,
            ).splitlines()
            untracked = _git_nonignored_untracked(repo)
            if (sorted(changed) != sorted([plan_relative, manifest_relative]) or
                    any(path not in {plan_relative, manifest_relative} for path in staged) or
                    untracked):
                raise AgyCanaryEvidenceError(
                    "private finalizer worktree changed unexpected paths"
                )
            actual_plan = (repo / plan_relative).read_bytes()
            actual_manifest = (repo / manifest_relative).read_bytes()
        else:
            finalized = _clean_dotfiles_repo(repo)
            changed = _git_text(
                repo, "diff", "--name-only", candidate, finalized,
            ).splitlines()
            if sorted(changed) != sorted([plan_relative, manifest_relative]):
                raise AgyCanaryEvidenceError(
                    "private finalizer committed transition changed unexpected paths"
                )
            actual_plan_proc = _git_run(repo, "show", f"{finalized}:{plan_relative}")
            actual_manifest_proc = _git_run(repo, "show", f"{finalized}:{manifest_relative}")
            if actual_plan_proc.returncode != 0 or actual_manifest_proc.returncode != 0:
                raise AgyCanaryEvidenceError(
                    "private finalizer committed outputs are unavailable"
                )
            actual_plan = actual_plan_proc.stdout
            actual_manifest = actual_manifest_proc.stdout
        if actual_plan != plan_after or actual_manifest != manifest_after:
            raise AgyCanaryEvidenceError("tracked finalizer output drifted from its sealed preimages")
        return {
            **proof,
            "canonical_proof_sha256": _sha256(_canonical_json(proof)),
            "inputs_sha256": _sha256(_canonical_json(inputs)),
        }
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
    _validate_git_repository_authority(repo)
    plan_relative = _repo_relative_path(repo, plan_path)
    manifest_relative = _repo_relative_path(repo, manifest_path)
    resolved = _git_text(repo, "rev-parse", f"{commit}^{{commit}}")
    after_plan = _git_run(repo, "show", f"{resolved}:{plan_relative}").stdout
    prefix, payload = _parse_final_payload(after_plan)
    attestation = _validate_final_attestation_envelope(payload["attestation"])
    bootstrap = attestation.get("bootstrap")
    candidate = bootstrap.get("repo_head") if isinstance(bootstrap, dict) else None
    if not isinstance(candidate, str):
        raise AgyCanaryEvidenceError("committed finalizer payload lacks bootstrap candidate")
    candidate = _git_text(repo, "rev-parse", f"{candidate}^{{commit}}")
    before_plan = _git_run(repo, "show", f"{candidate}:{plan_relative}").stdout
    before_manifest = _git_run(repo, "show", f"{candidate}:{manifest_relative}").stdout
    _validate_committed_attestation(
        repo=repo, attestation=attestation, plan_relative=plan_relative,
        manifest_relative=manifest_relative, plan_before=before_plan, manifest_before=before_manifest,
    )
    if attestation.get("proof") != _proof_identity(payload["proof"]) or attestation.get("reducer_proof_sha256") != _sha256(_canonical_json(payload["proof"])):
        raise AgyCanaryEvidenceError("committed proof does not match attested reducer identity")
    changed = _git_text(repo, "diff", "--name-only", candidate, resolved).splitlines()
    if sorted(changed) != sorted([plan_relative, manifest_relative]):
        raise AgyCanaryEvidenceError("committed finalizer transform changed unexpected paths")
    if prefix != before_plan:
        raise AgyCanaryEvidenceError("committed plan prefix differs from bootstrap candidate preimage")
    release = attestation["release"]
    if release != _reconcile_release_lineage(
        repo=agent_harness_repo.resolve(strict=True), handoff_commit=handoff_commit
    ):
        raise AgyCanaryEvidenceError("committed release identity does not reauthenticate immutable handoff lineage")
    after_manifest = _git_run(repo, "show", f"{resolved}:{manifest_relative}").stdout
    try:
        before_value = json.loads(before_manifest)
    except json.JSONDecodeError as exc:
        raise AgyCanaryEvidenceError("committed manifest is not JSON") from exc
    entries_before = before_value.get("plans") if isinstance(before_value, dict) else None
    matches_before = [item for item in entries_before or [] if isinstance(item, dict) and item.get("slug") == plan_slug]
    if len(matches_before) != 1:
        raise AgyCanaryEvidenceError("committed finalizer transform lacks one target manifest entry")
    matches_before[0]["updated_at"] = attestation["completed_at"]
    expected_manifest = _canonical_json(before_value)
    if (
        expected_manifest != after_manifest
        or attestation["manifest_after_sha256"] != _sha256(expected_manifest)
    ):
        raise AgyCanaryEvidenceError("committed manifest differs from sealed finalizer transform")
    return {
        "commit": resolved,
        "proof_sha256": payload["proof_sha256"],
        "canonical_proof_sha256": _sha256(_canonical_json(payload["proof"])),
        **_FINAL_GOVERNANCE_POSTURE,
        "plan_sha256": _sha256(after_plan),
        "manifest_sha256": _sha256(after_manifest),
    }


def _validate_committed_attestation(
    *, repo: Path, attestation: Any, plan_relative: str, manifest_relative: str,
    plan_before: bytes, manifest_before: bytes,
) -> None:
    """Validate every bootstrap/release identity embedded in a committed suffix."""
    _validate_git_repository_authority(repo)
    attestation = _validate_final_attestation_envelope(attestation)
    bootstrap = attestation.get("bootstrap")
    release = attestation.get("release")
    if (not isinstance(bootstrap, dict) or not isinstance(release, dict) or
            attestation["release_sha256"] != _sha256(_canonical_json(release))):
        raise AgyCanaryEvidenceError("committed finalizer payload lacks attested bootstrap/release identities")
    _validate_release_identity(release)
    if attestation.get("wheel_binding_sha256") != _sha256(_canonical_json(release["wheel_binding"])):
        raise AgyCanaryEvidenceError("committed finalizer wheel binding is malformed")
    installation = _validate_installation_identity(attestation.get("installation"))
    _validate_interpreter_authority(
        installation["interpreter_authority"], revalidate=True
    )
    _validate_uv_store_authority(
        installation["uv_store_authority"], revalidate=True, account_home=_account_home(),
        workspace_root=_UV_WORKSPACE_ROOT,
    )
    if attestation.get("installation_sha256") != _sha256(_canonical_json(installation)):
        raise AgyCanaryEvidenceError("committed finalizer installation binding is malformed")
    proof_identity = attestation["proof"]
    if not isinstance(proof_identity, dict) or set(proof_identity) != {"seat_key", "attempt_ids", "private_board_sha256", "provider_results", "release_sha256", "wheel_binding_sha256", "installation_sha256", "proof_sha256", *_FINAL_GOVERNANCE_POSTURE}:
        raise AgyCanaryEvidenceError("committed finalizer proof identity is malformed")
    if any(proof_identity.get(name) != value for name, value in _FINAL_GOVERNANCE_POSTURE.items()):
        raise AgyCanaryEvidenceError("committed finalizer proof governance is malformed")
    _validate_provider_result_summary(proof_identity["provider_results"])
    if (proof_identity.get("release_sha256") != attestation["release_sha256"] or
            proof_identity.get("wheel_binding_sha256") != attestation["wheel_binding_sha256"] or
            proof_identity.get("installation_sha256") != attestation["installation_sha256"]):
        raise AgyCanaryEvidenceError("committed finalizer proof release binding is malformed")
    if set(bootstrap) != {
            "repo_head", "tree_snapshot", "blobs", "input_sha256", "sandbox"
    }:
        raise AgyCanaryEvidenceError("committed finalizer bootstrap identity is malformed")
    repo_head = bootstrap["repo_head"]
    blobs = bootstrap["blobs"]
    input_sha256 = bootstrap["input_sha256"]
    tree_snapshot = _validate_tree_snapshot_authority(
        bootstrap["tree_snapshot"], repo=repo, commit=repo_head,
        require_execution_path=False,
    )
    expected_paths = {"bootstrap.sh", "shared/agent-harness.pin", "plans/manifest.json", plan_relative}
    if not isinstance(repo_head, str) or len(repo_head) != 40 or not isinstance(blobs, dict) or not isinstance(input_sha256, dict) or set(blobs) != expected_paths or set(input_sha256) != expected_paths:
        raise AgyCanaryEvidenceError("committed finalizer bootstrap identity is malformed")
    if _git_text(repo, "rev-parse", f"{repo_head}^{{commit}}") != repo_head:
        raise AgyCanaryEvidenceError("committed finalizer bootstrap HEAD is not immutable")
    base_bytes: dict[str, bytes] = {}
    for relative in expected_paths:
        actual = _git_run(repo, "show", f"{repo_head}:{relative}")
        if actual.returncode != 0 or blobs[relative] != _git_text(repo, "rev-parse", f"{repo_head}:{relative}") or input_sha256[relative] != _sha256(actual.stdout):
            raise AgyCanaryEvidenceError("committed finalizer bootstrap blob identity drifted")
        base_bytes[relative] = actual.stdout
    if base_bytes[plan_relative] != plan_before or base_bytes[manifest_relative] != manifest_before:
        raise AgyCanaryEvidenceError("committed finalizer preimages differ from bootstrap identity")
    environment = _uv_environment(
        uv_executable=Path(installation["uv_executable"]),
        interpreter_authority=installation["interpreter_authority"],
        uv_store_authority=installation["uv_store_authority"],
    )
    _validate_tree_sandbox(
        bootstrap["sandbox"], tree=tree_snapshot, environment=environment,
        uv_store_authority=installation["uv_store_authority"],
        bash=_canonical_bash(), revalidate_evidence_root=False,
    )
    candidate_snapshot = _git_tree_snapshot(repo, repo_head, materialize=False)
    snapshot = _GitTreeSnapshot(
        authority={
            **candidate_snapshot.authority,
            "mount_path": tree_snapshot["mount_path"],
        },
        entries=candidate_snapshot.entries,
    )
    _argv, expected_sandbox = _tree_snapshot_bwrap_argv(
        snapshot=snapshot, bwrap=_canonical_bwrap(), bash=_canonical_bash(),
        environment=environment, account_home=_account_home(),
        uv_store_authority=installation["uv_store_authority"],
        evidence_root_masking=bootstrap["sandbox"]["evidence_root_masking"],
        identity_only=True,
    )
    if expected_sandbox != bootstrap["sandbox"]:
        raise AgyCanaryEvidenceError("committed finalizer sandbox identity drifted")


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
    _validate_final_proof(proof)
    root, root_fd = _validate_private_root(evidence_root)
    plan_target: _FinalTarget | None = None
    manifest_target: _FinalTarget | None = None
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
        if prepare.get("seat_key") != expected_seat_key:
            raise AgyCanaryEvidenceError("finalizer seat does not match prepare authority")
        if _read_json_at(root_fd, "agy_canary_proof.json") != proof:
            raise AgyCanaryEvidenceError("finalizer proof does not match sealed reducer receipt")
        release = prepare.get("release")
        if (not isinstance(release, dict) or
                prepare.get("release_sha256") != _sha256(_canonical_json(release)) or
                prepare.get("wheel_binding_sha256") !=
                _sha256(_canonical_json(release.get("wheel_binding")))):
            raise AgyCanaryEvidenceError("finalizer requires release identities sealed by prepare")
        _validate_release_identity(release)
        installation = _validate_installation_identity(_bootstrap["bootstrap"]["installation"])
        if (proof["release_sha256"] != prepare["release_sha256"] or
                proof["wheel_binding_sha256"] != prepare["wheel_binding_sha256"] or
                proof["installation_sha256"] != prepare["installation_sha256"] or
                prepare["installation_sha256"] != _sha256(_canonical_json(installation))):
            raise AgyCanaryEvidenceError("finalizer proof differs from prepare release binding")
        inputs["attestation"] = {
            "bootstrap": _bootstrap_final_identity(_bootstrap),
            "release": release,
            "release_sha256": prepare["release_sha256"],
            "wheel_binding_sha256": prepare["wheel_binding_sha256"],
            "installation": installation,
            "installation_sha256": prepare["installation_sha256"],
            "proof": _proof_identity(proof),
            "reducer_proof_sha256": _sha256(_canonical_json(proof)),
        }
        plan = repo / plan_relative
        manifest = repo / manifest_relative
        plan_target = _open_final_target(plan, b"")
        manifest_target = _open_final_target(manifest, b"")
        plan_before = plan_target.data
        input_sha256 = _bootstrap.get("input_sha256")
        if (
            not isinstance(input_sha256, dict)
            or _sha256(plan_before) != input_sha256.get(plan_relative)
            or _sha256(manifest_target.data) != input_sha256.get(manifest_relative)
        ):
            raise AgyCanaryEvidenceError("finalizer target preimages differ from bootstrap attestation")
        if _has_canonical_final_suffix(plan_before):
            raise AgyCanaryEvidenceError("plan already has execution evidence")
        manifest_before = manifest_target.data
        try:
            manifest_value = json.loads(manifest_before)
        except json.JSONDecodeError as exc:
            raise AgyCanaryEvidenceError("manifest is not JSON") from exc
        entries = manifest_value.get("plans") if isinstance(manifest_value, dict) else None
        matches = [entry for entry in entries or [] if isinstance(entry, dict) and entry.get("slug") == plan_slug]
        if len(matches) != 1:
            raise AgyCanaryEvidenceError("finalizer could not identify one manifest plan")
        matches[0]["updated_at"] = completed_at
        manifest_after = _canonical_json(manifest_value)
        inputs["attestation"].update({
            "completed_at": completed_at,
            "manifest_after_sha256": _sha256(manifest_after),
        })
        plan_after = plan_before + _final_suffix(proof, inputs["attestation"])
        plan_target.replacement = plan_after
        manifest_target.replacement = manifest_after
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
        _finalize_targets_transactionally(plan_target, manifest_target)
        return {
            **proof,
            "canonical_proof_sha256": _sha256(_canonical_json(proof)),
            "inputs_sha256": _sha256(_canonical_json(inputs)),
        }
    finally:
        if manifest_target is not None:
            os.close(manifest_target.parent_fd)
        if plan_target is not None:
            os.close(plan_target.parent_fd)
        os.close(root_fd)
