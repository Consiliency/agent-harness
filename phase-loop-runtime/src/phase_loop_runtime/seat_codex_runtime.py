"""The Codex runtime file set a jailed seat binds (SEATS CODEX IF-0-CODEX-2).

A native codex image lives in a vendored target that also holds its code-mode host, the
``rg`` it puts on ``PATH``, its package descriptor and ``codex-resources/``. A jailed seat
binds exactly :data:`CODEX_RUNTIME_FILES`, each read-only from one regular, unlinked host
file, at the same relative path under :data:`CODEX_RUNTIME_ROOT`. ``codex-resources/`` and
the target directory itself are never bound.

Only a ``standalone`` subject reaches :func:`resolve_runtime`. A ``session_lease`` or
``managed_release`` subject is admitted through the profile's projection, on its own
closure, at the same destinations (:data:`CODEX_RUNTIME_DESTINATIONS`), and never falls
back to the standalone path.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re
import stat

from . import seat_jail
from .seat_subject import SeatSubject


CODEX_RUNTIME_ROOT = "/run/phase-loop-seat/codex-runtime"
CODEX_RUNTIME_FILES: tuple[str, ...] = (
    "bin/codex", "bin/codex-code-mode-host", "codex-path/rg", "codex-package.json",
)
CODEX_RUNTIME_DESTINATIONS: tuple[str, ...] = tuple(
    f"{CODEX_RUNTIME_ROOT}/{relpath}" for relpath in CODEX_RUNTIME_FILES
)

# The install layouts a native image is found in: ``.../vendor/<triple>/bin/codex`` (the
# npm platform package) and ``.../releases/<version>-<triple>/bin/codex``.
_TARGET_PARENTS = frozenset({"vendor", "releases"})
_TARGET_NAME = re.compile(r"(?:[^/]+-)?(?:x86_64|aarch64)-unknown-linux-musl")
_WALK = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class CodexRuntime:
    """A resolved vendored target and one host source per runtime file.

    ``sources`` rows are ``(relpath, host path)`` in :data:`CODEX_RUNTIME_FILES` order."""

    target: Path
    sources: tuple[tuple[str, str], ...]


def _trusted_owners() -> frozenset[int]:
    return frozenset({0, os.geteuid()})


def _unavailable(reason: str) -> seat_jail.SeatSandboxRefused:
    return seat_jail.SeatSandboxRefused("seat_provider_unavailable", reason)


def _identity(reason: str) -> seat_jail.SeatSandboxRefused:
    return seat_jail.SeatSandboxRefused(seat_jail.refused("identity"), reason)


def _refusal(exc: OSError, reason: str) -> seat_jail.SeatSandboxRefused:
    # Absent is a missing CLI; anything else (a link, a file where a directory belongs,
    # no permission to look) is a source that cannot be proved to be the CLI's own.
    return _unavailable(reason) if exc.errno == errno.ENOENT else _identity(reason)


def _require_trusted(info: os.stat_result, owners: frozenset[int], what: str) -> None:
    if info.st_uid not in owners or info.st_mode & 0o022:
        raise _identity(f"{what} is writable by another account or wrongly owned")


def _open_target(target: Path) -> int:
    """The target directory, reached from ``/`` one component at a time, never through a
    link."""
    directory = os.open("/", _WALK)
    try:
        for part in target.parts[1:]:
            try:
                child = os.open(part, _WALK, dir_fd=directory)
            except OSError as exc:
                raise _refusal(exc, "runtime target unavailable") from exc
            os.close(directory)
            directory = child
        return directory
    except BaseException:
        os.close(directory)
        raise


def _check_file(target_fd: int, relpath: str, owners: frozenset[int]) -> None:
    """One runtime file: trusted directories down to it, then a regular, unlinked file."""
    parts = relpath.split("/")
    fds: list[int] = []
    try:
        current = target_fd
        for part in parts[:-1]:
            try:
                current = os.open(part, _WALK, dir_fd=current)
            except OSError as exc:
                raise _refusal(exc, f"runtime directory {part!r} unavailable") from exc
            fds.append(current)
            _require_trusted(os.fstat(current), owners, f"runtime directory {part!r}")
        try:
            info = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        except OSError as exc:
            raise _refusal(exc, f"runtime file {relpath!r} unavailable") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _identity(f"runtime file {relpath!r} is not one regular, unlinked file")
        _require_trusted(info, owners, f"runtime file {relpath!r}")
    finally:
        for fd in reversed(fds):
            os.close(fd)


def resolve_runtime(native: Path) -> CodexRuntime:
    """The runtime file set of the vendored target holding ``native``.

    ``native`` must be ``<target>/bin/codex`` in a supported layout. A missing target,
    directory or file refuses ``seat_provider_unavailable``. A runtime file that is a link
    (symbolic or hard), not a regular file, wrongly owned, or below a directory that is,
    or writable by group or other, refuses ``seat_sandbox_refused:identity``.
    """
    native = Path(native)
    if not native.is_absolute() or native.name != "codex" or native.parent.name != "bin":
        raise _unavailable("not a vendored codex image")
    try:
        target = Path(os.path.realpath(native.parent.parent, strict=True))
    except OSError as exc:
        raise _unavailable("runtime target unavailable") from exc
    if target.parent.name not in _TARGET_PARENTS or not _TARGET_NAME.fullmatch(target.name):
        raise _unavailable("not a supported codex install layout")
    owners = _trusted_owners()
    target_fd = _open_target(target)
    try:
        _require_trusted(os.fstat(target_fd), owners, "runtime target")
        for relpath in CODEX_RUNTIME_FILES:
            _check_file(target_fd, relpath, owners)
    finally:
        os.close(target_fd)
    return CodexRuntime(
        target, tuple((relpath, str(target / relpath)) for relpath in CODEX_RUNTIME_FILES))


def runtime_binds(runtime: CodexRuntime) -> tuple[str, ...]:
    """One read-only bind per runtime file, at :data:`CODEX_RUNTIME_DESTINATIONS`."""
    if not isinstance(runtime, CodexRuntime):
        raise TypeError("runtime must be a CodexRuntime")
    if tuple(relpath for relpath, _source in runtime.sources) != CODEX_RUNTIME_FILES:
        raise _identity("runtime file set is not the resolved set")
    binds: list[str] = []
    for (_relpath, source), destination in zip(runtime.sources, CODEX_RUNTIME_DESTINATIONS):
        binds.extend(("--ro-bind", source, destination))
    return tuple(binds)


def subject_runtime(subject: SeatSubject) -> CodexRuntime | None:
    """The standalone runtime for ``subject``, or ``None`` for a projected subject.

    ``session_lease`` and ``managed_release`` return ``None`` without resolving anything:
    the profile's projection admits that subject's own closure and there is no fallback
    to the standalone path."""
    if not isinstance(subject, SeatSubject) or subject.leg != "codex":
        raise ValueError("not a codex seat subject")
    if subject.source in ("session_lease", "managed_release"):
        return None
    if subject.source != "standalone":
        raise ValueError("unknown seat subject source")
    if subject.subject_path is None:
        raise _unavailable("standalone subject has no path")
    return resolve_runtime(subject.subject_path)


__all__ = [
    "CODEX_RUNTIME_DESTINATIONS", "CODEX_RUNTIME_FILES", "CODEX_RUNTIME_ROOT", "CodexRuntime",
    "resolve_runtime", "runtime_binds", "subject_runtime",
]
