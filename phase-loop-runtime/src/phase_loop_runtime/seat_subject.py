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
import platform
import re
import shutil
import stat
import sys
import threading
from typing import Literal, Mapping

import rfc8785

from .executable_dependency import ExecutableDependencyError, ExecutableRequirementIdentity
from .executable_dependency_startup import DependencyRequirement


MANAGED_RELEASES_ROOT = Path("/opt/consiliency/tooling/releases")
MANAGED_AUTHORITY_PIN = Path("/etc/consiliency/tooling/seat-authority.json")
GROK_SUBJECT_PIN = Path("/etc/consiliency/tooling/grok-subject-pin.json")

SubjectSource = Literal["session_lease", "managed_release", "managed_image", "standalone"]

_PIN_SCHEMA = "seat_authority_pin.v2"
_GROK_PIN_SCHEMA = "grok_subject_pin.v1"
#: Exactly the Dotfiles producer's release-ID grammar (one safe path component).
_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")
_PIN_MAX_BYTES = 131_072
_MANAGED_ADAPTER_ID = "phase-loop-seat"
_MANAGED_ADAPTER_VERSION = "1"
_MANAGED_POLICY_ID = "phase-loop-seat"
_MANAGED_POLICY_VERSION = "1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LEG = re.compile(r"^[a-z][a-z0-9-]*$")
_CLAUDE_CODE_VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,4}")
_CLAUDE_PACKAGE_NAME = re.compile(
    r"@anthropic-ai/claude-code(?:-(?:linux|darwin|win32)-(?:x64|arm64)(?:-musl)?)?"
)
_PACKAGE_JSON_MAX_BYTES = 65_536
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
    binary_sha256: str | None = None
    provider_version: str | None = None
    lookup_chain: tuple[tuple[str, tuple[int, ...]], ...] = ()


def normalize_claude_code_version(value: object) -> str:
    """Validate a content-free Claude Code version string, falling back to ``unknown``."""
    if type(value) is str and _CLAUDE_CODE_VERSION.fullmatch(value):
        return value
    return "unknown"


def _package_owns_executable(data: dict, pkg_dir: Path, selected: Path) -> bool:
    name = data.get("name")
    if type(name) is not str or not _CLAUDE_PACKAGE_NAME.fullmatch(name):
        return False
    try:
        rel = selected.relative_to(pkg_dir).as_posix()
    except ValueError:
        return False
    files = data.get("files")
    if isinstance(files, list) and any(
        type(entry) is str and entry.removeprefix("./") == rel for entry in files
    ):
        return True
    bin_field = data.get("bin")
    if type(bin_field) is str and bin_field.removeprefix("./") == rel:
        return True
    if isinstance(bin_field, dict) and any(
        type(target) is str and target.removeprefix("./") == rel for target in bin_field.values()
    ):
        return True
    return False


def claude_code_version_for_subject(path: Path | None, *, managed: bool = True) -> str:
    """Read the Claude Code version from verified managed ``package.json`` metadata without
    executing the binary (agent-harness#2170). Returns ``unknown`` whenever managed provenance
    or valid package metadata is unavailable."""
    if path is None or not managed:
        return "unknown"
    try:
        selected = Path(path).resolve(strict=True)
    except OSError:
        return "unknown"
    candidates = [selected.parent / "package.json"]
    if selected.parent.name == "bin":
        candidates.append(selected.parent.parent / "package.json")
    for candidate in candidates:
        try:
            descriptor = _open_managed_file(candidate)
            try:
                raw = _read_stable(descriptor, _PACKAGE_JSON_MAX_BYTES, code="package_metadata")
            finally:
                os.close(descriptor)
            data = json.loads(raw.decode("utf-8"))
        except (OSError, ExecutableDependencyError, UnicodeDecodeError, ValueError, TypeError, RecursionError):
            continue
        if isinstance(data, dict) and _package_owns_executable(data, candidate.parent, selected):
            version = normalize_claude_code_version(data.get("version"))
            if version != "unknown":
                return version
    return "unknown"


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
        if leg == "grok":
            raise ExecutableDependencyError("authority_invalid", "Grok dependency lease")
        return SeatSubject(leg, "session_lease", None, None, None)

    with _PROVIDER_LOCK:
        executable = _PROVIDER_EXECUTABLES.get(leg)
    if executable is None:
        raise FileNotFoundError("seat_provider_unavailable")
    search_path = env.get("PATH", os.defpath)
    if not isinstance(search_path, str):
        raise TypeError("PATH must be text")
    absolute_entries = tuple(
        item for item in search_path.split(os.pathsep) if item and Path(item).is_absolute()
    )
    found = (
        shutil.which(executable, path=os.pathsep.join(absolute_entries))
        if absolute_entries
        else None
    )
    if found is None:
        raise FileNotFoundError("seat_provider_unavailable")

    try:
        source = Path(found).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExecutableDependencyError("subject_mismatch", "provider") from exc

    named_target = Path(found)
    candidate = source
    for _hop in range(4):
        lines, trusted = _wrapper_lines(candidate)
        last = lines[-1] if lines else ""
        shaped = trusted and all(_SHELL_WRAPPER_EXPORT.fullmatch(line) for line in lines[1:-1])
        if last.startswith(_FRONTDOOR_PREFIX):
            # Imported here by contract so panel_invoker may import seat_subject later.
            from . import panel_invoker

            target = panel_invoker._frontdoor_target(last, leg, exact_shared=leg == "grok")
            if target is None or not shaped:
                raise ExecutableDependencyError("subject_mismatch", "guarded frontdoor")
            if leg == "grok":
                digest = managed_grok_image_digest(target)
                return SeatSubject(leg, "managed_image", target, target.parents[1].name, None, digest)
            return _managed_subject(leg, target)
        if _names_managed_root(candidate) or (leg == "grok" and _names_managed_root(named_target)):
            raise ExecutableDependencyError("subject_mismatch", "guarded frontdoor")
        match = _SHELL_WRAPPER_EXEC.fullmatch(last)
        if match is None:
            break
        named_target = Path(match.group(1))
        if not shaped:
            if _names_managed_root(named_target):
                raise ExecutableDependencyError("subject_mismatch", "wrapper target")
            break
        try:
            candidate = named_target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            if _names_managed_root(named_target):
                raise ExecutableDependencyError("subject_mismatch", "wrapper target") from exc
            break
    else:
        # Four followed hops and still a wrapper: where it ends is unproven.
        raise ExecutableDependencyError("subject_mismatch", "wrapper depth")

    # Preserve the existing standalone trust checks.  The looked-up path keeps the provider
    # name that resolution classifies; a resolved versioned target has lost it.
    if leg == "codex":
        from . import seat_codex_runtime, seat_jail

        try:
            path, lookup_chain = seat_codex_runtime.resolve_trusted_codex_lookup(Path(found))
        except seat_jail.SeatSandboxRefused as exc:
            if exc.code == "seat_provider_unavailable":
                raise FileNotFoundError("seat_provider_unavailable") from exc
            raise ExecutableDependencyError("subject_mismatch", str(exc)) from exc
        if _names_managed_root(path):
            raise ExecutableDependencyError("subject_mismatch", "provider")
        return SeatSubject(
            leg, "standalone", path, None, None, provider_version=None, lookup_chain=lookup_chain,
        )

    from . import panel_invoker

    try:
        harness, standalone = panel_invoker._seat_provider_source(str(found), env)
        path = Path(standalone).resolve(strict=True)
    except FileNotFoundError:
        raise
    except ExecutableDependencyError:
        raise
    except Exception as exc:
        raise ExecutableDependencyError("subject_mismatch", "standalone provider") from exc
    if harness != leg or _names_managed_root(path):
        raise ExecutableDependencyError("subject_mismatch", "provider")
    version = "unknown" if leg == "claude" else None
    return SeatSubject(leg, "standalone", path, None, None, provider_version=version)


def managed_grok_image_digest(path: Path) -> str:
    """Verify the exact managed release pin and hash its native executable."""
    from .seat_profile_grok import JAIL_PROTECTION

    try:
        release_id, native, executable = path.relative_to(MANAGED_RELEASES_ROOT).parts
    except ValueError as exc:
        raise ExecutableDependencyError("subject_mismatch", "Grok release path") from exc
    if not _safe_release_id(release_id) or (native, executable) != ("native", "grok"):
        raise ExecutableDependencyError("subject_mismatch", "Grok release path")

    releases = _read_pin(GROK_SUBJECT_PIN, _GROK_PIN_SCHEMA)
    for name, entry in releases.items():
        if (
            not _safe_release_id(name)
            or type(entry) is not dict
            or set(entry) != {"binary_sha256", "platform", "version"}
            or type(entry["binary_sha256"]) is not str
            or not _SHA256.fullmatch(entry["binary_sha256"])
            or entry["platform"] != "linux-x64"
            or entry["version"] != "1.0.92"
            # No legitimate producer writes an unapproved fingerprint, even unselected.
            or entry["binary_sha256"] not in JAIL_PROTECTION
        ):
            raise ExecutableDependencyError("authority_invalid", "Grok pin entry")
    if release_id not in releases:
        raise ExecutableDependencyError("authority_missing")
    expected = releases[release_id]["binary_sha256"]
    if sys.platform != "linux" or platform.machine() != "x86_64" or expected not in JAIL_PROTECTION:
        raise ExecutableDependencyError("authority_invalid", "Grok platform or fingerprint")

    try:
        descriptor = _open_root_owned_file(path)
        try:
            identity = _selected_identity_fd(descriptor, path, executable=True)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ExecutableDependencyError("subject_mismatch", "Grok executable path") from exc
    if identity.sha256 != expected:
        raise ExecutableDependencyError("subject_mismatch", "Grok executable digest")
    return identity.sha256


def verify_managed_image(subject: SeatSubject, profile) -> None:
    """Admit a verified Grok image only with the no-projection Grok profile."""
    if (
        not isinstance(subject, SeatSubject)
        or subject.source != "managed_image" or subject.leg != "grok"
        or profile is None or profile.leg != "grok" or profile.projection != "none"
        or subject.requirement is not None
    ):
        raise ExecutableDependencyError("authority_invalid", "managed image profile")
    path = subject.subject_path
    if path is None or subject.binary_sha256 is None:
        raise ExecutableDependencyError("subject_mismatch", "managed image identity")
    digest = managed_grok_image_digest(path)
    if subject.release_id != path.parents[1].name or subject.binary_sha256 != digest:
        raise ExecutableDependencyError("subject_mismatch", "managed image identity")


def _safe_release_id(name: str) -> bool:
    return name not in {".", ".."} and _RELEASE_ID.fullmatch(name) is not None


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
    try:
        identity = _selected_identity(selected)
    except OSError as exc:
        raise ExecutableDependencyError("subject_mismatch", "selected executable") from exc
    requirement = DependencyRequirement(
        provider=leg,
        selected_executable=identity,
        authority_id=pin["authority_id"],
        expected_authority_sha256=pin["authority_sha256"],
        adapter_id=_MANAGED_ADAPTER_ID,
        adapter_version=_MANAGED_ADAPTER_VERSION,
        policy_id=_MANAGED_POLICY_ID,
        policy_version=_MANAGED_POLICY_VERSION,
        base_profile_sha256=pin["base_profile_sha256"],
    )
    version = claude_code_version_for_subject(selected, managed=True) if leg == "claude" else None
    return SeatSubject(leg, "managed_release", selected, release_id, requirement, provider_version=version)


def _names_managed_root(path: Path) -> bool:
    """Whether ``path`` lies below the managed root, by name or once resolved."""

    roots = [MANAGED_RELEASES_ROOT.absolute()]
    candidates = [Path(os.path.abspath(path))]
    try:
        roots.append(MANAGED_RELEASES_ROOT.resolve(strict=True))
        candidates.append(path.parent.resolve(strict=True) / path.name)
        candidates.append(path.resolve(strict=True))
    except OSError:
        pass
    return any(item.is_relative_to(root) for item in candidates for root in roots)


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
    releases = _read_pin(MANAGED_AUTHORITY_PIN, _PIN_SCHEMA)
    if release_id not in releases:
        raise ExecutableDependencyError("authority_missing")
    release = releases[release_id]
    if type(release) is not dict:
        raise ExecutableDependencyError("authority_invalid", "pin entry")
    if leg not in release:
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



def _read_pin(path: Path, schema: str) -> dict:
    try:
        descriptor = _open_root_owned_file(path)
    except FileNotFoundError as exc:
        raise ExecutableDependencyError("authority_missing") from exc
    except OSError as exc:
        raise ExecutableDependencyError("authority_invalid", "pin path") from exc
    try:
        raw = _read_stable(descriptor, _PIN_MAX_BYTES, code="authority_invalid")
    except OSError as exc:
        raise ExecutableDependencyError("authority_invalid", "pin read") from exc
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if rfc8785.dumps(value) != raw:
            raise ValueError("noncanonical pin")
        if type(value) is not dict or set(value) != {"schema", "releases"}:
            raise ValueError("pin object")
        if value["schema"] != schema or type(value["releases"]) is not dict:
            raise ValueError("pin schema")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ExecutableDependencyError("authority_invalid", "pin") from exc
    return value["releases"]


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _open_root_owned_file(path: Path) -> int:
    root = _PIN_WALK_ROOT
    if not path.is_absolute() or not root.is_absolute():
        raise OSError("path is not absolute")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OSError("path is outside trust root") from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise OSError("invalid path")
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
                raise OSError("unsafe file")
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
        return _selected_identity_fd(descriptor, path)
    finally:
        os.close(descriptor)


def _selected_identity_fd(
    descriptor: int, path: Path, *, executable: bool = False,
) -> ExecutableRequirementIdentity:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode) or before.st_size <= 0
        or (executable and not before.st_mode & 0o111)
    ):
        raise ExecutableDependencyError("subject_mismatch", "selected executable")
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    after = os.fstat(descriptor)
    if size != before.st_size or _stat_identity(before) != _stat_identity(after):
        raise ExecutableDependencyError("subject_mismatch", "selected executable changed")
    return ExecutableRequirementIdentity(
        path=str(path),
        kind="file",
        mode=f"0{stat.S_IMODE(before.st_mode):03o}",
        size=before.st_size,
        sha256=digest.hexdigest(),
    )


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


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
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
    "claude_code_version_for_subject",
    "deployment_kind",
    "normalize_claude_code_version",
    "open_managed_authority",
    "register_provider_executable",
    "resolve_seat_subject",
]
