"""Resolve the executable subject selected for a review seat.

The resolver keeps deployment authority separate from release contents.  A managed
release is selected by the guarded frontdoor, while its authority identity and digest
come only from the root-owned host pin.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
from typing import Literal, Mapping

import rfc8785

from .executable_dependency import ExecutableDependencyError, ExecutableRequirementIdentity
from .executable_dependency_startup import DependencyRequirement


MANAGED_RELEASES_ROOT = Path("/opt/consiliency/tooling/releases")
MANAGED_AUTHORITY_PIN = Path("/etc/consiliency/tooling/seat-authority.json")

SubjectSource = Literal["session_lease", "managed_release", "standalone"]

_PIN_SCHEMA = "seat_authority_pin.v2"
_PIN_MAX_BYTES = 131_072
_MANAGED_ADAPTER_ID = "phase-loop-seat"
_MANAGED_ADAPTER_VERSION = "1"
_MANAGED_POLICY_ID = "phase-loop-seat"
_MANAGED_POLICY_VERSION = "1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LEG = re.compile(r"^[a-z][a-z0-9-]*$")
_FRONTDOOR_PREFIX = "exec /usr/bin/python3 -I "
_SHELL_WRAPPER_EXPORT = re.compile(
    r'export [A-Z_][A-Z0-9_]*=(?:[A-Za-z0-9._/:@+-]|"\$PATH")*'
)
_SHELL_WRAPPER_EXEC = re.compile(
    r'exec (/[A-Za-z0-9._@+/-]+)(?: -c [A-Za-z0-9._-]+=[A-Za-z0-9._/:@+-]+)* "\$@"'
)

# Tests substitute an isolated filesystem root and the invoking uid.  Production keeps
# both sets root-only.
_PIN_WALK_ROOT = Path("/")
_PIN_OWNERS = frozenset({0})
_MANAGED_OWNERS = frozenset({0})

_PROVIDER_EXECUTABLES: dict[str, str] = {
    "claude": "claude",
    "gemini": "agy",
}
_PROVIDER_LOCK = threading.RLock()


@dataclass(frozen=True)
class SeatSubject:
    leg: str
    source: SubjectSource
    subject_path: Path | None
    release_id: str | None
    requirement: DependencyRequirement | None


def register_provider_executable(leg: str, executable: str) -> None:
    """Register the PATH executable for a provider leg.

    Repeating the same registration is harmless.  A conflicting registration is a
    programming error because resolution must not depend on import order.
    """

    if not isinstance(leg, str) or not _LEG.fullmatch(leg):
        raise ValueError("invalid provider leg")
    if (
        not isinstance(executable, str)
        or not executable
        or Path(executable).name != executable
        or "/" in executable
    ):
        raise ValueError("invalid provider executable")
    with _PROVIDER_LOCK:
        previous = _PROVIDER_EXECUTABLES.get(leg)
        if previous is not None and previous != executable:
            raise ValueError(f"provider executable already registered for {leg}")
        _PROVIDER_EXECUTABLES[leg] = executable


def resolve_seat_subject(leg: str, env: Mapping[str, str]) -> SeatSubject:
    """Resolve one seat subject in lease, managed-release, standalone order."""

    if not isinstance(leg, str) or not _LEG.fullmatch(leg):
        raise ValueError("invalid provider leg")
    if not isinstance(env, Mapping):
        raise TypeError("env must be a mapping")

    dependency = _current_dependency(leg)
    if dependency is not None:
        return SeatSubject(leg, "session_lease", None, None, None)

    with _PROVIDER_LOCK:
        executable = _PROVIDER_EXECUTABLES.get(leg)
    if executable is None:
        raise FileNotFoundError("seat_provider_unavailable")
    search_path = env.get("PATH", os.defpath)
    if not isinstance(search_path, str):
        raise TypeError("PATH must be text")
    found = shutil.which(executable, path=search_path)
    if found is None:
        raise FileNotFoundError("seat_provider_unavailable")

    try:
        source = Path(found).resolve(strict=True)
    except OSError as exc:
        raise ExecutableDependencyError("subject_mismatch", "provider") from exc

    candidate = source
    for _hop in range(4):
        lines, trusted = _wrapper_lines(candidate)
        last = lines[-1] if lines else ""
        if last.startswith(_FRONTDOOR_PREFIX):
            # Imported here by contract so panel_invoker may import seat_subject later.
            from . import panel_invoker

            target = panel_invoker._frontdoor_target(last, leg)
            if target is None or not trusted:
                raise ExecutableDependencyError("subject_mismatch", "guarded frontdoor")
            return _managed_subject(leg, target)
        if _inside_managed_root(candidate):
            raise ExecutableDependencyError("subject_mismatch", "guarded frontdoor")
        match = _SHELL_WRAPPER_EXEC.fullmatch(last)
        if not trusted or match is None or not all(
            _SHELL_WRAPPER_EXPORT.fullmatch(line) for line in lines[1:-1]
        ):
            break
        try:
            candidate = Path(match.group(1)).resolve(strict=True)
        except OSError as exc:
            raise ExecutableDependencyError("subject_mismatch", "wrapper target") from exc

    # Preserve the existing standalone trust checks.  Passing an absolute source makes
    # its lookup independent of panel_invoker's legacy import-time PATH snapshot.
    from . import panel_invoker

    try:
        harness, standalone = panel_invoker._seat_provider_source(str(source), env)
        path = Path(standalone).resolve(strict=True)
    except FileNotFoundError:
        raise
    except ExecutableDependencyError:
        raise
    except Exception as exc:
        raise ExecutableDependencyError("subject_mismatch", "standalone provider") from exc
    if harness != leg or _inside_managed_root(path):
        raise ExecutableDependencyError("subject_mismatch", "provider")
    return SeatSubject(leg, "standalone", path, None, None)


def open_managed_authority(subject: SeatSubject) -> tuple[int, str]:
    """Open a managed subject's authority and verify its independently pinned digest."""

    if (
        not isinstance(subject, SeatSubject)
        or subject.source != "managed_release"
        or subject.release_id is None
        or subject.requirement is None
    ):
        raise ExecutableDependencyError("authority_missing")
    authority = (
        MANAGED_RELEASES_ROOT
        / subject.release_id
        / "share/phase-loop/seat-dependencies"
        / subject.leg
        / "authority.json"
    )
    try:
        descriptor = _open_managed_file(authority)
    except FileNotFoundError as exc:
        raise ExecutableDependencyError("authority_missing") from exc
    except OSError as exc:
        raise ExecutableDependencyError("authority_invalid", "authority path") from exc
    try:
        observed = _sha256_fd(descriptor, _PIN_MAX_BYTES, code="authority_invalid")
        expected = subject.requirement.expected_authority_sha256
        if observed != expected:
            raise ExecutableDependencyError("authority_invalid", "digest")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor, expected
    except BaseException:
        os.close(descriptor)
        raise


def deployment_kind() -> Literal["managed", "uv_tool", "pip", "source", "unknown"]:
    """Classify this runtime's installation using paths and metadata only."""

    package = _runtime_package_path()
    try:
        managed_root = MANAGED_RELEASES_ROOT.resolve(strict=True)
        if package.is_relative_to(managed_root):
            return "managed"
    except OSError:
        pass

    parts = package.parts
    for index in range(max(0, len(parts) - 3)):
        if parts[index : index + 3] == ("uv", "tools", "phase-loop-runtime"):
            return "uv_tool"
    for ancestor in package.parents:
        if (
            ancestor.name == "phase-loop-runtime"
            and (ancestor / "pyproject.toml").is_file()
            and (ancestor / "src/phase_loop_runtime").is_dir()
        ):
            return "source"
    if _distribution_installer() == "pip":
        return "pip"
    return "unknown"


def _current_dependency(leg: str):
    from .executable_dependency_startup import current_dependency_for_provider

    return current_dependency_for_provider(leg)


def _managed_subject(leg: str, target: Path) -> SeatSubject:
    try:
        root = MANAGED_RELEASES_ROOT.resolve(strict=True)
        selected = Path(target).resolve(strict=True)
        relative = selected.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ExecutableDependencyError("subject_mismatch", "release") from exc
    if len(relative.parts) < 2:
        raise ExecutableDependencyError("subject_mismatch", "release")
    release_id = relative.parts[0]
    pin = _pin_entry(release_id, leg)
    requirement = DependencyRequirement(
        provider=leg,
        selected_executable=_selected_identity(selected),
        authority_id=pin["authority_id"],
        expected_authority_sha256=pin["authority_sha256"],
        adapter_id=_MANAGED_ADAPTER_ID,
        adapter_version=_MANAGED_ADAPTER_VERSION,
        policy_id=_MANAGED_POLICY_ID,
        policy_version=_MANAGED_POLICY_VERSION,
        base_profile_sha256=pin["base_profile_sha256"],
    )
    return SeatSubject(leg, "managed_release", selected, release_id, requirement)


def _inside_managed_root(path: Path) -> bool:
    try:
        root = MANAGED_RELEASES_ROOT.resolve(strict=True)
        return Path(path).resolve(strict=True).is_relative_to(root)
    except OSError:
        return False


def _wrapper_lines(path: Path) -> tuple[list[str], bool]:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    flags |= getattr(os, "O_NOCTTY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return [], False
    try:
        info = os.fstat(descriptor)
        trusted = (
            stat.S_ISREG(info.st_mode)
            and info.st_uid in {0, os.geteuid()}
            and info.st_mode & 0o022 == 0
            and info.st_size <= 4096
        )
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            return [], trusted
        raw = os.read(descriptor, 4097)
        if len(raw) > 4096:
            return [], False
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return [], False
    finally:
        os.close(descriptor)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or lines[0] != "#!/bin/sh":
        return [], trusted
    return lines, trusted


def _pin_entry(release_id: str, leg: str) -> dict[str, str]:
    try:
        descriptor = _open_pin()
    except FileNotFoundError as exc:
        raise ExecutableDependencyError("authority_missing") from exc
    except OSError as exc:
        raise ExecutableDependencyError("authority_invalid", "pin path") from exc
    try:
        raw = _read_stable(descriptor, _PIN_MAX_BYTES, code="authority_invalid")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if rfc8785.dumps(value) != raw:
            raise ValueError("noncanonical pin")
        if type(value) is not dict or set(value) != {"schema", "releases"}:
            raise ValueError("pin object")
        if value["schema"] != _PIN_SCHEMA or type(value["releases"]) is not dict:
            raise ValueError("pin schema")
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExecutableDependencyError("authority_invalid", "pin") from exc
    release = value["releases"].get(release_id)
    if type(release) is not dict or leg not in release:
        raise ExecutableDependencyError("authority_missing")
    entry = release[leg]
    if type(entry) is not dict or set(entry) != {
        "authority_sha256",
        "authority_id",
        "base_profile_sha256",
    }:
        raise ExecutableDependencyError("authority_invalid", "pin entry")
    if not all(type(item) is str and _SHA256.fullmatch(item) for item in entry.values()):
        raise ExecutableDependencyError("authority_invalid", "pin entry")
    return entry


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _open_pin() -> int:
    pin = MANAGED_AUTHORITY_PIN
    root = _PIN_WALK_ROOT
    if not pin.is_absolute() or not root.is_absolute():
        raise OSError("pin path is not absolute")
    try:
        relative = pin.relative_to(root)
    except ValueError as exc:
        raise OSError("pin path is outside trust root") from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise OSError("invalid pin path")
    walk = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open(root, walk)
    try:
        _require_owned_directory(directory, _PIN_OWNERS)
        for part in parts[:-1]:
            child = os.open(part, walk, dir_fd=directory)
            os.close(directory)
            directory = child
            _require_owned_directory(directory, _PIN_OWNERS)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid not in _PIN_OWNERS
                or info.st_mode & 0o022
            ):
                raise OSError("unsafe pin file")
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise
    finally:
        os.close(directory)


def _open_managed_file(path: Path) -> int:
    root = MANAGED_RELEASES_ROOT
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OSError("managed path escaped") from exc
    walk = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open(root, walk)
    try:
        _require_owned_directory(directory, _MANAGED_OWNERS)
        for part in relative.parts[:-1]:
            child = os.open(part, walk, dir_fd=directory)
            os.close(directory)
            directory = child
            _require_owned_directory(directory, _MANAGED_OWNERS)
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in _MANAGED_OWNERS
            or info.st_mode & 0o022
        ):
            os.close(descriptor)
            raise OSError("unsafe managed file")
        return descriptor
    finally:
        os.close(directory)


def _require_owned_directory(descriptor: int, owners: frozenset[int]) -> None:
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in owners or info.st_mode & 0o022:
        raise OSError("unsafe directory")


def _selected_identity(path: Path) -> ExecutableRequirementIdentity:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | getattr(os, "O_NOCTTY", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise ExecutableDependencyError("subject_mismatch", "selected executable")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            raise ExecutableDependencyError("subject_mismatch", "selected executable changed")
        return ExecutableRequirementIdentity(
            path=str(path),
            kind="file",
            mode=f"0{stat.S_IMODE(before.st_mode):03o}",
            size=before.st_size,
            sha256=digest.hexdigest(),
        )
    finally:
        os.close(descriptor)


def _read_stable(descriptor: int, limit: int, *, code: str) -> bytes:
    before = os.fstat(descriptor)
    raw = os.read(descriptor, limit + 1)
    after = os.fstat(descriptor)
    if len(raw) > limit or len(raw) != before.st_size or _stat_identity(before) != _stat_identity(after):
        raise ExecutableDependencyError(code, "changed while reading")
    return raw


def _sha256_fd(descriptor: int, limit: int, *, code: str) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = _read_stable(descriptor, limit, code=code)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return hashlib.sha256(raw).hexdigest()


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
    )


def _runtime_package_path() -> Path:
    return Path(__file__).resolve()


def _distribution_installer() -> str | None:
    try:
        value = metadata.distribution("phase-loop-runtime").read_text("INSTALLER")
    except metadata.PackageNotFoundError:
        return None
    return value.strip() if value is not None else None


__all__ = [
    "MANAGED_AUTHORITY_PIN",
    "MANAGED_RELEASES_ROOT",
    "SeatSubject",
    "SubjectSource",
    "deployment_kind",
    "open_managed_authority",
    "register_provider_executable",
    "resolve_seat_subject",
]
