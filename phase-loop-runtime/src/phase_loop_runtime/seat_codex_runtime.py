"""The Codex runtime file set a jailed seat binds (SEATS CODEX IF-0-CODEX-2).

A native codex image lives in a vendored target that also holds its code-mode host, the
``rg`` it puts on ``PATH``, its package descriptor and ``codex-resources/``. A jailed seat
binds exactly :data:`CODEX_RUNTIME_FILES`, each read-only from one regular, unlinked host
file, at the same relative path under :data:`CODEX_RUNTIME_ROOT`. ``codex-resources/`` and
the target directory itself are never bound.

Only a ``standalone`` subject reaches :func:`resolve_runtime` / :func:`open_runtime`. A
``session_lease`` or ``managed_release`` subject is admitted through the profile's
projection, on its own closure, at the same destinations
(:data:`CODEX_RUNTIME_DESTINATIONS`), and never falls back to the standalone path.

Standalone trust model (agent-harness#1952)
-------------------------------------------
1. Every ancestor from ``/`` down to the runtime target must be a real directory owned by
   root or the operator (``{0, os.geteuid()}``) and not group- or other-writable, with the
   standard exception for root-owned sticky directories (such as ``/tmp`` or ``/var/tmp``,
   where another account cannot rename or unlink an entry owned by root or the operator).
   Permitted ancestor symlinks (for example ``/var -> /private/var`` or operator-owned
   launcher links) are inspected through an ``O_PATH | O_NOFOLLOW`` descriptor, required to
   be owned by root or the operator inside an already-verified parent directory, and
   traversed via ``os.readlink("", dir_fd=link_fd)`` with ``..`` resolved against the
   verified directory stack. The target directory itself, its subdirectories (``bin``,
   ``codex-path``), and all four runtime files allow no symlinks and no sticky exception.
2. Standalone admission pins the validated regular-file **inodes** via open
   ``O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`` file descriptors and full stat
   identities ``(st_dev, st_ino, st_uid, st_gid, st_mode, st_nlink, st_size, st_mtime_ns,
   st_ctime_ns)`` alongside open ``O_PATH`` directory descriptors for the verified
   ancestry. Binding and admission execution project those exact descriptors via
   ``--ro-bind-data <fd> <dest>`` (reopening independent offset-0 open-file descriptions
   via ``/proc/self/fd/<held_fd>``) and verify live descriptor identities and zero offsets
   immediately before spawn, eliminating pathname re-resolution by ``bwrap``. Unlike signed
   ``managed_release`` projections (which hold sealed memfd snapshots verified against a
   signed SHA-256 manifest), in-place writes by root or the operator's own UID during
   ``bwrap --ro-bind-data`` copying are outside the standalone multi-user tampering threat
   model; concurrent mutation before spawn is still detected by full stat-identity
   revalidation.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
try:
    import fcntl
except ImportError:  # Standalone imports remain supported on non-POSIX hosts.
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Sequence

from . import seat_jail
from .seat_subject import SeatSubject


CODEX_RUNTIME_ROOT = "/run/phase-loop-seat/codex-runtime"
CODEX_RUNTIME_FILES: tuple[str, ...] = (
    "bin/codex", "bin/codex-code-mode-host", "codex-path/rg", "codex-package.json",
)
CODEX_RUNTIME_DESTINATIONS: tuple[str, ...] = tuple(
    f"{CODEX_RUNTIME_ROOT}/{relpath}" for relpath in CODEX_RUNTIME_FILES
)
CODEX_RUNTIME_MODES: tuple[str, ...] = ("0555", "0555", "0555", "0444")

# The install layouts a native image is found in: ``.../vendor/<triple>/bin/codex`` (the
# npm platform package) and ``.../releases/<version>-<triple>/bin/codex``.
_TARGET_PARENTS = frozenset({"vendor", "releases"})
_TARGET_NAME = re.compile(r"(?:[^/]+-)?(?:x86_64|aarch64)-unknown-linux-musl")
_MAX_SYMLINK_HOPS = 40
_WRAPPER_MAX_BYTES = 4096
_SHELL_WRAPPER_EXPORT = re.compile(
    r'export [A-Z_][A-Z0-9_]*=(?:[A-Za-z0-9._/:@+-]|"\$PATH")*'
)
_SHELL_WRAPPER_EXEC = re.compile(
    r'exec (/[A-Za-z0-9._@+/-]+)(?: -c [A-Za-z0-9._-]+=[A-Za-z0-9._/:@+-]+)* "\$@"'
)

# Native Windows has none of these flags (nor ``dir_fd``): ``None`` makes every open fail closed.
if os.name != "nt":
    _WALK = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    _LINK_OPEN = getattr(os, "O_PATH", os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC
    _FILE_OPEN = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | os.O_CLOEXEC
        | getattr(os, "O_NOCTTY", 0)
    )
    _REOPEN_FLAGS = os.O_RDONLY | os.O_CLOEXEC
else:
    _WALK = None
    _LINK_OPEN = None
    _FILE_OPEN = None
    _REOPEN_FLAGS = None


RuntimeDirIdentity = tuple[int, int, int, int, int]
RuntimeStatIdentity = tuple[int, int, int, int, int, int, int, int, int]


@dataclass(frozen=True)
class RuntimeFileIdentity:
    """Validated file identity for one standalone Codex runtime file."""

    relpath: str
    source: str
    destination: str
    mode: str
    stat_identity: RuntimeStatIdentity


@dataclass(frozen=True)
class CodexRuntime:
    """A resolved vendored target and one host source per runtime file.

    ``sources`` rows are ``(relpath, host path)`` in :data:`CODEX_RUNTIME_FILES` order.
    ``files`` and ``ancestry`` carry the validated stat/directory identities recorded
    during resolution (defaulting to empty tuples for backwards-compatible synthetic
    construction)."""

    target: Path
    sources: tuple[tuple[str, str], ...]
    files: tuple[RuntimeFileIdentity, ...] = ()
    ancestry: tuple[tuple[str, RuntimeDirIdentity], ...] = ()


@dataclass(frozen=True)
class StandaloneRuntimeEntry:
    """One projected file entry in a standalone Codex runtime."""

    kind: str
    destination: str
    mode: str


@dataclass(frozen=True)
class StandaloneRuntimeFile:
    """One reopened read-only descriptor for a standalone Codex runtime file."""

    relpath: str
    source: str
    destination: str
    mode: str
    fd: int
    stat_identity: RuntimeStatIdentity


@dataclass(frozen=True)
class _HeldDirectory:
    path: str
    fd: int
    identity: RuntimeDirIdentity
    strict_ancestor: bool


@dataclass(frozen=True)
class _HeldRuntimeFile:
    info: RuntimeFileIdentity
    fd: int


class StandaloneRuntimeProjection:
    """One consumer-owned set of reopened standalone Codex runtime descriptors."""

    def __init__(
        self,
        *,
        files: tuple[StandaloneRuntimeFile, ...],
        entries: tuple[StandaloneRuntimeEntry, ...],
        digest: str,
    ) -> None:
        self.files = files
        self.entries = entries
        self.digest = digest
        self._closed = False

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(item.fd for item in self.files)

    @property
    def destinations(self) -> tuple[str, ...]:
        return tuple(item.destination for item in self.entries)

    def mount_args(self) -> tuple[str, ...]:
        args: list[str] = []
        for item in self.files:
            args.extend(("--perms", item.mode, "--ro-bind-data", str(item.fd), item.destination))
        return tuple(args)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for item in self.files:
            _close_quietly(item.fd)

    def __enter__(self) -> StandaloneRuntimeProjection:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AdmittedStandaloneRuntime:
    """Descriptor-held standalone Codex runtime with launch-time revalidation.

    Holds open ``O_PATH`` directory descriptors for the verified ancestor chain and runtime
    subdirectories plus open ``O_RDONLY`` descriptors for all four runtime files.
    """

    def __init__(
        self,
        *,
        runtime: CodexRuntime,
        ancestry: tuple[_HeldDirectory, ...],
        files: tuple[_HeldRuntimeFile, ...],
        lookup_chain: tuple[tuple[str, RuntimeStatIdentity], ...] = (),
    ) -> None:
        self.leg = "codex"
        self.runtime = runtime
        self._ancestry = ancestry
        self._files = files
        self._lookup_chain = tuple(lookup_chain)
        self.subject_source = runtime.sources[0][1]
        self.subject_destination = CODEX_RUNTIME_DESTINATIONS[0]
        self.entries = tuple(
            StandaloneRuntimeEntry(kind="file", destination=item.info.destination, mode=item.info.mode)
            for item in files
        )
        self.projection_digest = _standalone_projection_digest(runtime)
        self._jailcore_owned = True
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def revalidate(self) -> None:
        if self._closed:
            raise _identity("standalone codex runtime closed")
        owners = _trusted_owners()
        for directory in self._ancestry:
            try:
                observed = os.fstat(directory.fd)
            except OSError as exc:
                raise _identity(f"runtime directory {directory.path!r} unavailable") from exc
            if _dir_identity(observed) != directory.identity:
                raise _identity(f"runtime directory {directory.path!r} changed")
            if directory.strict_ancestor:
                _require_trusted_ancestor(observed, owners, f"runtime ancestor {directory.path!r}")
            else:
                _require_trusted(observed, owners, f"runtime directory {directory.path!r}")
        for held in self._files:
            try:
                observed = os.fstat(held.fd)
            except OSError as exc:
                raise _identity(f"runtime file {held.info.relpath!r} unavailable") from exc
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_nlink != 1
                or _stat_identity(observed) != held.info.stat_identity
            ):
                raise _identity(f"runtime file {held.info.relpath!r} changed")
            _require_trusted(observed, owners, f"runtime file {held.info.relpath!r}")
        # Re-walk the canonical path from `/` without following symlinks to detect
        # directory or file swaps on disk even while the original inodes remain open.
        _verify_disk_matches_held(self.runtime, self._ancestry, self._files, owners)
        if self._lookup_chain:
            _verify_lookup_chain(self._lookup_chain, self._files[0].info, owners)

    def reopen_projection(self) -> StandaloneRuntimeProjection:
        self.revalidate()
        reopened: list[StandaloneRuntimeFile] = []
        try:
            for held in self._files:
                fd = _reopen_validated_file(held)
                reopened.append(
                    StandaloneRuntimeFile(
                        relpath=held.info.relpath,
                        source=held.info.source,
                        destination=held.info.destination,
                        mode=held.info.mode,
                        fd=fd,
                        stat_identity=held.info.stat_identity,
                    )
                )
        except BaseException:
            for item in reopened:
                _close_quietly(item.fd)
            raise
        return StandaloneRuntimeProjection(
            files=tuple(reopened),
            entries=self.entries,
            digest=self.projection_digest,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for held in reversed(self._files):
            _close_quietly(held.fd)
        for directory in reversed(self._ancestry):
            _close_quietly(directory.fd)

    def __enter__(self) -> AdmittedStandaloneRuntime:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


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


def _dir_identity(info: os.stat_result) -> RuntimeDirIdentity:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)


def _stat_identity(info: os.stat_result) -> RuntimeStatIdentity:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _standalone_projection_digest(runtime: CodexRuntime) -> str:
    document = {
        "schema": "org.agent-harness.codex-standalone-runtime.v1",
        "target": str(runtime.target),
        "ancestry": [[path, list(identity)] for path, identity in runtime.ancestry],
        "files": [
            {
                "relpath": item.relpath,
                "source": item.source,
                "destination": item.destination,
                "mode": item.mode,
                "stat_identity": list(item.stat_identity),
            }
            for item in runtime.files
        ],
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_trusted(info: os.stat_result, owners: frozenset[int], what: str) -> None:
    if info.st_uid not in owners or info.st_mode & 0o022:
        raise _identity(f"{what} is writable by another account or wrongly owned")


def _require_trusted_ancestor(info: os.stat_result, owners: frozenset[int], what: str) -> None:
    """Verify a directory strictly above the runtime target.

    Must be a real directory owned by root or the operator and not group- or
    other-writable, except for a root-owned sticky directory (such as ``/tmp`` or
    ``/var/tmp``) where another account cannot rename or unlink entries owned by root or
    the operator.
    """
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in owners:
        raise _identity(f"{what} is writable by another account or wrongly owned")
    if info.st_mode & 0o022 and not (info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)):
        raise _identity(f"{what} is writable by another account or wrongly owned")


def _join_canonical(parent: str, part: str) -> str:
    return f"/{part}" if parent == "/" else f"{parent}/{part}"


def _open_root_dir(owners: frozenset[int]) -> tuple[str, int, RuntimeDirIdentity]:
    if _WALK is None:
        raise _identity("POSIX nofollow open is unavailable on this platform")
    try:
        root_fd = os.open("/", _WALK)
    except OSError as exc:
        raise _refusal(exc, "runtime ancestor '/' unavailable") from exc
    try:
        root_info = os.fstat(root_fd)
        _require_trusted_ancestor(root_info, owners, "runtime ancestor '/'")
        return "/", root_fd, _dir_identity(root_info)
    except BaseException:
        _close_quietly(root_fd)
        raise


def _read_owned_symlink(parent_fd: int, part: str, owners: frozenset[int], what: str) -> str:
    if _LINK_OPEN is None:
        raise _identity("POSIX nofollow open is unavailable on this platform")
    try:
        link_fd = os.open(part, _LINK_OPEN, dir_fd=parent_fd)
    except OSError as exc:
        raise _refusal(exc, f"{what} unavailable") from exc
    try:
        info = os.fstat(link_fd)
        if not stat.S_ISLNK(info.st_mode):
            raise _identity(f"{what} is not a directory")
        if info.st_uid not in owners:
            raise _identity(f"{what} symlink is wrongly owned")
        try:
            return os.readlink("", dir_fd=link_fd)
        except OSError as exc:
            raise _refusal(exc, f"{what} symlink unreadable") from exc
    finally:
        _close_quietly(link_fd)


def _walk_trusted_dir(
    path: Path,
    owners: frozenset[int],
    *,
    follow_symlinks: bool = True,
    strict_leaf: bool = True,
) -> tuple[Path, list[_HeldDirectory]]:
    """Walk ``path`` from ``/`` verifying every ancestor directory and permitted symlink.

    Returns ``(canonical_path, held_directories)`` with every directory from ``/`` through
    the leaf held open via ``_WALK``. On error, closes all opened descriptors.
    """
    if not path.is_absolute():
        raise _unavailable("runtime path is not absolute")
    raw_text = os.fspath(path)
    if "\x00" in raw_text:
        raise _identity("runtime path contains NUL byte")
    pending = [part for part in raw_text.split("/") if part]
    root_path, root_fd, root_id = _open_root_dir(owners)
    # Stack items: (canonical_path, fd, dir_identity)
    stack: list[tuple[str, int, RuntimeDirIdentity]] = [(root_path, root_fd, root_id)]
    hops = 0
    try:
        while pending:
            part = pending.pop(0)
            if part == ".":
                continue
            if part == "..":
                if len(stack) > 1:
                    _old_path, old_fd, _old_id = stack.pop()
                    _close_quietly(old_fd)
                continue
            cur_path, cur_fd, _cur_id = stack[-1]
            next_path = _join_canonical(cur_path, part)
            is_last = not pending
            try:
                child_fd = os.open(part, _WALK, dir_fd=cur_fd)
            except OSError as exc:
                if (
                    follow_symlinks
                    and not (is_last and strict_leaf)
                    and exc.errno in (errno.ELOOP, errno.ENOTDIR)
                ):
                    link_target = _read_owned_symlink(
                        cur_fd, part, owners, f"runtime ancestor {next_path!r}"
                    )
                    hops += 1
                    if hops > _MAX_SYMLINK_HOPS:
                        raise _identity("too many symbolic links in runtime path") from exc
                    if "\x00" in link_target:
                        raise _identity("runtime symlink target contains NUL byte") from exc
                    target_parts = [item for item in link_target.split("/") if item]
                    if link_target.startswith("/"):
                        while len(stack) > 1:
                            _p, fd_to_close, _i = stack.pop()
                            _close_quietly(fd_to_close)
                    pending = [*target_parts, *pending]
                    continue
                raise _refusal(exc, f"runtime ancestor {next_path!r} unavailable") from exc
            try:
                info = os.fstat(child_fd)
                if is_last and strict_leaf:
                    if not stat.S_ISDIR(info.st_mode):
                        raise _identity(f"runtime target {next_path!r} is not a directory")
                    _require_trusted(info, owners, "runtime target")
                else:
                    _require_trusted_ancestor(info, owners, f"runtime ancestor {next_path!r}")
            except BaseException:
                _close_quietly(child_fd)
                raise
            stack.append((next_path, child_fd, _dir_identity(info)))
        if strict_leaf:
            leaf_path, leaf_fd, _leaf_id = stack[-1]
            leaf_info = os.fstat(leaf_fd)
            if not stat.S_ISDIR(leaf_info.st_mode):
                raise _identity(f"runtime target {leaf_path!r} is not a directory")
            _require_trusted(leaf_info, owners, "runtime target")
        canonical = Path(stack[-1][0])
        last_index = len(stack) - 1
        held = [
            _HeldDirectory(
                path=item_path,
                fd=item_fd,
                identity=item_id,
                strict_ancestor=(idx < last_index or not strict_leaf),
            )
            for idx, (item_path, item_fd, item_id) in enumerate(stack)
        ]
        return canonical, held
    except BaseException:
        for _p, fd_to_close, _i in reversed(stack):
            _close_quietly(fd_to_close)
        raise


def _open_trusted_leaf(
    path: Path,
    owners: frozenset[int],
    *,
    follow_symlinks: bool = True,
    follow_leaf_symlink: bool = True,
    what: str = "runtime file",
) -> tuple[Path, int, os.stat_result]:
    """Walk ``path`` from ``/`` checking every ancestor and open its regular, unlinked leaf."""
    if _FILE_OPEN is None:
        raise _identity("POSIX nofollow open is unavailable on this platform")
    if not path.is_absolute():
        raise _unavailable(f"{what} is not absolute")
    raw_text = os.fspath(path)
    if "\x00" in raw_text:
        raise _identity(f"{what} contains NUL byte")
    pending = [part for part in raw_text.split("/") if part]
    if not pending:
        raise _identity(f"{what} cannot be root directory")
    root_path, root_fd, root_id = _open_root_dir(owners)
    stack: list[tuple[str, int, RuntimeDirIdentity]] = [(root_path, root_fd, root_id)]
    hops = 0
    try:
        while True:
            part = pending.pop(0)
            if part == ".":
                if not pending:
                    raise _identity(f"{what} is a directory")
                continue
            if part == "..":
                if len(stack) > 1:
                    _p, old_fd, _i = stack.pop()
                    _close_quietly(old_fd)
                if not pending:
                    raise _identity(f"{what} is a directory")
                continue
            cur_path, cur_fd, _cur_id = stack[-1]
            next_path = _join_canonical(cur_path, part)
            if pending:
                try:
                    child_fd = os.open(part, _WALK, dir_fd=cur_fd)
                except OSError as exc:
                    if follow_symlinks and exc.errno in (errno.ELOOP, errno.ENOTDIR):
                        link_target = _read_owned_symlink(
                            cur_fd, part, owners, f"runtime ancestor {next_path!r}"
                        )
                        hops += 1
                        if hops > _MAX_SYMLINK_HOPS:
                            raise _identity("too many symbolic links in runtime path") from exc
                        if "\x00" in link_target:
                            raise _identity("runtime symlink target contains NUL byte") from exc
                        target_parts = [item for item in link_target.split("/") if item]
                        if link_target.startswith("/"):
                            while len(stack) > 1:
                                _p, fd_to_close, _i = stack.pop()
                                _close_quietly(fd_to_close)
                        pending = [*target_parts, *pending]
                        if not pending:
                            raise _identity(f"{what} resolved to directory") from exc
                        continue
                    raise _refusal(exc, f"runtime ancestor {next_path!r} unavailable") from exc
                try:
                    info = os.fstat(child_fd)
                    _require_trusted_ancestor(info, owners, f"runtime ancestor {next_path!r}")
                except BaseException:
                    _close_quietly(child_fd)
                    raise
                stack.append((next_path, child_fd, _dir_identity(info)))
                continue

            # Leaf component: never follow unless follow_leaf_symlink explicitly allows an owned hop.
            try:
                leaf_fd = os.open(part, _FILE_OPEN, dir_fd=cur_fd)
            except OSError as exc:
                if follow_leaf_symlink and exc.errno == errno.ELOOP:
                    link_target = _read_owned_symlink(
                        cur_fd, part, owners, f"{what} {next_path!r}"
                    )
                    hops += 1
                    if hops > _MAX_SYMLINK_HOPS:
                        raise _identity("too many symbolic links in runtime path") from exc
                    if "\x00" in link_target:
                        raise _identity("runtime symlink target contains NUL byte") from exc
                    target_parts = [item for item in link_target.split("/") if item]
                    if link_target.startswith("/"):
                        while len(stack) > 1:
                            _p, fd_to_close, _i = stack.pop()
                            _close_quietly(fd_to_close)
                    if not target_parts:
                        raise _identity(f"{what} resolved to directory") from exc
                    pending = target_parts
                    continue
                raise _refusal(exc, f"{what} {next_path!r} unavailable") from exc
            try:
                info = os.fstat(leaf_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise _identity(f"{what} {next_path!r} is not one regular, unlinked file")
                _require_trusted(info, owners, f"{what} {next_path!r}")
                return Path(next_path), leaf_fd, info
            except BaseException:
                _close_quietly(leaf_fd)
                raise
    finally:
        for _p, fd_to_close, _i in reversed(stack):
            _close_quietly(fd_to_close)


def _wrapper_lines_fd(fd: int, info: os.stat_result) -> list[str]:
    if not stat.S_ISREG(info.st_mode) or info.st_size > _WRAPPER_MAX_BYTES:
        return []
    try:
        raw = os.pread(fd, _WRAPPER_MAX_BYTES + 1, 0)
    except OSError:
        return []
    if len(raw) > _WRAPPER_MAX_BYTES:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or lines[0] != "#!/bin/sh":
        return []
    return lines


def _is_elf_fd(fd: int) -> bool:
    try:
        return os.pread(fd, 4, 0) == b"\x7fELF"
    except OSError:
        return False


def _codex_js_native_candidates(launcher: Path) -> tuple[Path, ...]:
    machine = os.uname().machine
    suffix = {"x86_64": "x64", "aarch64": "arm64"}.get(machine)
    if suffix is None:
        return ()
    triple = f"{machine}-unknown-linux-musl"
    package = launcher.parent.parent
    return (
        package / "node_modules/@openai" / f"codex-linux-{suffix}" / "vendor" / triple / "bin/codex",
        package / "vendor" / triple / "bin/codex",
        package.parent / f"codex-linux-{suffix}" / "vendor" / triple / "bin/codex",
    )


def resolve_trusted_codex_lookup(
    found: Path,
) -> tuple[Path, tuple[tuple[str, RuntimeStatIdentity], ...]]:
    """Resolve a ``PATH``-discovered standalone Codex entry via verified descriptors.

    Every ancestor directory, permitted symlink, shell wrapper hop, and npm ``codex.js``
    launcher-to-native transition is opened through the trusted descriptor walker so that
    discovery and trust validation inspect the exact same objects.
    """
    owners = _trusted_owners()
    current = Path(found)
    chain: list[tuple[str, RuntimeStatIdentity]] = []
    for _hop in range(5):
        canonical, fd, info = _open_trusted_leaf(
            current,
            owners,
            follow_symlinks=True,
            follow_leaf_symlink=True,
            what="codex lookup entry",
        )
        try:
            chain.append((str(canonical), _stat_identity(info)))
            lines = _wrapper_lines_fd(fd, info)
            if lines:
                last = lines[-1]
                shaped = all(_SHELL_WRAPPER_EXPORT.fullmatch(line) for line in lines[1:-1])
                match = _SHELL_WRAPPER_EXEC.fullmatch(last) if shaped else None
                if match is not None:
                    current = Path(match.group(1))
                    continue
            if canonical.name.lower() == "codex.js":
                candidates = _codex_js_native_candidates(canonical)
                if not candidates:
                    raise _unavailable("unsupported host architecture for codex")
                selected: tuple[Path, RuntimeStatIdentity] | None = None
                for candidate in candidates:
                    try:
                        native_path, native_fd, native_info = _open_trusted_leaf(
                            candidate,
                            owners,
                            follow_symlinks=True,
                            follow_leaf_symlink=False,
                            what="codex native image",
                        )
                    except seat_jail.SeatSandboxRefused as exc:
                        if exc.code == "seat_provider_unavailable":
                            continue
                        raise
                    try:
                        if native_path.name.lower() != "codex" or not _is_elf_fd(native_fd):
                            continue
                        selected = (native_path, _stat_identity(native_info))
                        break
                    finally:
                        _close_quietly(native_fd)
                if selected is None:
                    raise _unavailable("codex native image unavailable")
                native_path, native_id = selected
                chain.append((str(native_path), native_id))
                return native_path, tuple(chain)
            if canonical.name.lower() != "codex" or not _is_elf_fd(fd):
                raise _unavailable("codex executable is not a native ELF image")
            return canonical, tuple(chain)
        finally:
            _close_quietly(fd)
    raise _identity("codex wrapper depth exceeded")


def _open_runtime_file(
    target_fd: int,
    target_path: Path,
    relpath: str,
    destination: str,
    mode: str,
    owners: frozenset[int],
    held_subdirs: dict[str, _HeldDirectory],
) -> _HeldRuntimeFile:
    """Open one runtime file below ``target_fd``, holding trusted intermediate dirs."""
    if _WALK is None or _FILE_OPEN is None:
        raise _identity("POSIX nofollow open is unavailable on this platform")
    parts = relpath.split("/")
    current_fd = target_fd
    current_rel = ""
    for part in parts[:-1]:
        current_rel = part if not current_rel else f"{current_rel}/{part}"
        existing = held_subdirs.get(current_rel)
        if existing is not None:
            current_fd = existing.fd
            continue
        try:
            child_fd = os.open(part, _WALK, dir_fd=current_fd)
        except OSError as exc:
            raise _refusal(exc, f"runtime directory {part!r} unavailable") from exc
        try:
            info = os.fstat(child_fd)
            if not stat.S_ISDIR(info.st_mode):
                raise _identity(f"runtime directory {part!r} is not a directory")
            _require_trusted(info, owners, f"runtime directory {part!r}")
        except BaseException:
            _close_quietly(child_fd)
            raise
        held_subdirs[current_rel] = _HeldDirectory(
            path=str(target_path / current_rel),
            fd=child_fd,
            identity=_dir_identity(info),
            strict_ancestor=False,
        )
        current_fd = child_fd
    try:
        file_fd = os.open(parts[-1], _FILE_OPEN, dir_fd=current_fd)
    except OSError as exc:
        raise _refusal(exc, f"runtime file {relpath!r} unavailable") from exc
    try:
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise _identity(f"runtime file {relpath!r} is not one regular, unlinked file")
        _require_trusted(info, owners, f"runtime file {relpath!r}")
        return _HeldRuntimeFile(
            info=RuntimeFileIdentity(
                relpath=relpath,
                source=str(target_path / relpath),
                destination=destination,
                mode=mode,
                stat_identity=_stat_identity(info),
            ),
            fd=file_fd,
        )
    except BaseException:
        _close_quietly(file_fd)
        raise


def _verify_disk_matches_held(
    runtime: CodexRuntime,
    ancestry: tuple[_HeldDirectory, ...],
    files: tuple[_HeldRuntimeFile, ...],
    owners: frozenset[int],
) -> None:
    """Fresh no-follow walk from ``/`` confirming disk paths still name the held inodes."""
    canonical, walked_ancestors = _walk_trusted_dir(
        runtime.target, owners, follow_symlinks=False, strict_leaf=True
    )
    walked_subdirs: dict[str, _HeldDirectory] = {}
    walked_files: list[_HeldRuntimeFile] = []
    try:
        if canonical != runtime.target:
            raise _identity("runtime target path changed")
        target_fd = walked_ancestors[-1].fd
        for relpath, destination, mode in zip(
            CODEX_RUNTIME_FILES, CODEX_RUNTIME_DESTINATIONS, CODEX_RUNTIME_MODES
        ):
            walked_files.append(
                _open_runtime_file(
                    target_fd, canonical, relpath, destination, mode, owners, walked_subdirs
                )
            )
        all_walked_dirs = [*walked_ancestors, *walked_subdirs.values()]
        if [(d.path, d.identity) for d in all_walked_dirs] != [
            (d.path, d.identity) for d in ancestry
        ]:
            raise _identity("runtime ancestry identity changed")
        if [f.info for f in walked_files] != [f.info for f in files]:
            raise _identity("runtime file identity changed")
    finally:
        for item in reversed(walked_files):
            _close_quietly(item.fd)
        for item in reversed(list(walked_subdirs.values())):
            _close_quietly(item.fd)
        for item in reversed(walked_ancestors):
            _close_quietly(item.fd)


def _verify_lookup_chain(
    lookup_chain: Sequence[tuple[str, RuntimeStatIdentity]],
    codex_file: RuntimeFileIdentity,
    owners: frozenset[int],
) -> None:
    if not lookup_chain:
        return
    last_path, last_identity = lookup_chain[-1]
    if last_path != codex_file.source or last_identity != codex_file.stat_identity:
        raise _identity("standalone lookup chain does not match admitted codex binary")
    for hop_path, hop_identity in lookup_chain:
        canonical, fd, info = _open_trusted_leaf(
            Path(hop_path),
            owners,
            follow_symlinks=False,
            follow_leaf_symlink=False,
            what="codex lookup hop",
        )
        try:
            if str(canonical) != hop_path or _stat_identity(info) != hop_identity:
                raise _identity(f"codex lookup hop {hop_path!r} changed")
        finally:
            _close_quietly(fd)


def _reopen_validated_file(held: _HeldRuntimeFile) -> int:
    if _REOPEN_FLAGS is None:
        raise _identity("POSIX fd reopen is unavailable on this platform")
    try:
        reopened = os.open(f"/proc/self/fd/{held.fd}", _REOPEN_FLAGS)
    except OSError as exc:
        raise _identity(f"runtime file {held.info.relpath!r} reopen failed") from exc
    try:
        observed = os.fstat(reopened)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or _stat_identity(observed) != held.info.stat_identity
        ):
            raise _identity(f"runtime file {held.info.relpath!r} identity drifted on reopen")
        if os.lseek(reopened, 0, os.SEEK_CUR) != 0:
            raise _identity(f"runtime file {held.info.relpath!r} reopened at nonzero offset")
        return reopened
    except BaseException:
        _close_quietly(reopened)
        raise


def open_runtime(
    native: Path,
    *,
    lookup_chain: Sequence[tuple[str, RuntimeStatIdentity]] = (),
    follow_symlinks: bool = True,
) -> AdmittedStandaloneRuntime:
    """Validate and hold open descriptors for the standalone Codex runtime holding ``native``."""
    native = Path(native)
    if not native.is_absolute() or native.name != "codex" or native.parent.name != "bin":
        raise _unavailable("not a vendored codex image")
    owners = _trusted_owners()
    target, ancestors = _walk_trusted_dir(
        native.parent.parent, owners, follow_symlinks=follow_symlinks, strict_leaf=True
    )
    held_subdirs: dict[str, _HeldDirectory] = {}
    held_files: list[_HeldRuntimeFile] = []
    try:
        if target.parent.name not in _TARGET_PARENTS or not _TARGET_NAME.fullmatch(target.name):
            raise _unavailable("not a supported codex install layout")
        target_fd = ancestors[-1].fd
        for relpath, destination, mode in zip(
            CODEX_RUNTIME_FILES, CODEX_RUNTIME_DESTINATIONS, CODEX_RUNTIME_MODES
        ):
            held_files.append(
                _open_runtime_file(
                    target_fd, target, relpath, destination, mode, owners, held_subdirs
                )
            )
        if lookup_chain:
            _verify_lookup_chain(lookup_chain, held_files[0].info, owners)
        all_dirs = (*ancestors, *held_subdirs.values())
        runtime = CodexRuntime(
            target=target,
            sources=tuple((item.info.relpath, item.info.source) for item in held_files),
            files=tuple(item.info for item in held_files),
            ancestry=tuple((item.path, item.identity) for item in all_dirs),
        )
        return AdmittedStandaloneRuntime(
            runtime=runtime,
            ancestry=all_dirs,
            files=tuple(held_files),
            lookup_chain=tuple(lookup_chain),
        )
    except BaseException:
        for item in reversed(held_files):
            _close_quietly(item.fd)
        for item in reversed(list(held_subdirs.values())):
            _close_quietly(item.fd)
        for item in reversed(ancestors):
            _close_quietly(item.fd)
        raise


def resolve_runtime(native: Path) -> CodexRuntime:
    """The runtime file set of the vendored target holding ``native``.

    ``native`` must be ``<target>/bin/codex`` in a supported layout. A missing target,
    directory or file refuses ``seat_provider_unavailable``. An untrusted ancestor, a
    runtime file that is a link (symbolic or hard), not a regular file, wrongly owned, or
    below a directory that is, or writable by group or other, refuses
    ``seat_sandbox_refused:identity``.
    """
    with open_runtime(native) as admitted:
        return admitted.runtime


def admit_runtime(
    runtime: CodexRuntime,
    *,
    lookup_chain: Sequence[tuple[str, RuntimeStatIdentity]] = (),
) -> AdmittedStandaloneRuntime:
    """Re-open and pin descriptors for a previously resolved :class:`CodexRuntime`.

    Fails closed with ``seat_sandbox_refused:identity`` if ``runtime`` lacks validated
    file/ancestry identities or if any ancestor or runtime file changed on disk.
    """
    if not isinstance(runtime, CodexRuntime):
        raise _identity("standalone codex runtime must be a resolved CodexRuntime")
    if (
        not runtime.files
        or not runtime.ancestry
        or tuple(item.relpath for item in runtime.files) != CODEX_RUNTIME_FILES
        or runtime.sources != tuple((item.relpath, item.source) for item in runtime.files)
    ):
        raise _identity("standalone codex runtime lacks validated identities")
    admitted = open_runtime(
        runtime.target / "bin/codex",
        lookup_chain=lookup_chain,
        follow_symlinks=False,
    )
    try:
        if (
            admitted.runtime.target != runtime.target
            or admitted.runtime.ancestry != runtime.ancestry
            or admitted.runtime.files != runtime.files
        ):
            raise _identity("standalone codex runtime changed since resolution")
        return admitted
    except BaseException:
        admitted.close()
        raise


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


def verify_standalone_projection(
    runtime: object,
    mount_args: Sequence[str],
    pass_fds: Sequence[int],
    expected_digest: str,
    *,
    container_argv: Sequence[str] | None = None,
) -> tuple[int, ...]:
    """Verify live projection mounts, descriptors, identities, and zero offsets before spawn."""
    if not isinstance(runtime, AdmittedStandaloneRuntime):
        raise _identity("standalone codex runtime missing")
    runtime.revalidate()
    if not expected_digest or runtime.projection_digest != expected_digest:
        raise _identity("standalone codex runtime projection digest mismatch")
    args = tuple(mount_args)
    expected_count = len(CODEX_RUNTIME_FILES)
    if len(args) != expected_count * 5:
        raise _identity("standalone codex runtime mount grammar changed")
    if container_argv is not None:
        container = tuple(container_argv)
        width = len(args)
        matches = [
            idx
            for idx in range(len(container) - width + 1)
            if container[idx : idx + width] == args
        ]
        if len(matches) != 1:
            raise _identity("standalone codex runtime mounts missing or duplicated in argv")
    pass_set = set(pass_fds)
    fds: list[int] = []
    for idx, (expected_file, expected_dest, expected_mode) in enumerate(
        zip(runtime.runtime.files, CODEX_RUNTIME_DESTINATIONS, CODEX_RUNTIME_MODES)
    ):
        chunk = args[idx * 5 : (idx + 1) * 5]
        if (
            chunk[0] != "--perms"
            or chunk[1] != expected_mode
            or chunk[2] != "--ro-bind-data"
            or chunk[4] != expected_dest
        ):
            raise _identity("standalone codex runtime mount entry tampered")
        try:
            fd = int(chunk[3])
        except ValueError as exc:
            raise _identity("standalone codex runtime mount descriptor invalid") from exc
        if str(fd) != chunk[3] or fd < 3 or fd not in pass_set:
            raise _identity("standalone codex runtime mount descriptor not in pass_fds")
        fds.append(fd)
        try:
            if fcntl is None or not hasattr(os, "O_ACCMODE"):
                raise _identity("POSIX fcntl is unavailable on this platform")
            fd_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            observed = os.fstat(fd)
            offset = os.lseek(fd, 0, os.SEEK_CUR)
        except OSError as exc:
            raise _identity("standalone codex runtime projection descriptor unavailable") from exc
        if (fd_flags & os.O_ACCMODE) != os.O_RDONLY:
            raise _identity(
                f"standalone codex runtime projection fd for {expected_file.relpath!r} is not read-only"
            )
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or _stat_identity(observed) != expected_file.stat_identity
        ):
            raise _identity(f"standalone codex runtime projection fd for {expected_file.relpath!r} drifted")
        if offset != 0:
            raise _identity(f"standalone codex runtime projection fd for {expected_file.relpath!r} has nonzero offset")
    if len(set(fds)) != expected_count:
        raise _identity("standalone codex runtime projection descriptors are not distinct")
    return tuple(fds)


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
    resolved = resolve_runtime(subject.subject_path)
    lookup_chain = getattr(subject, "lookup_chain", ())
    if lookup_chain:
        if not resolved.files:
            raise _identity("standalone codex runtime lacks validated identities")
        _verify_lookup_chain(lookup_chain, resolved.files[0], _trusted_owners())
    return resolved


__all__ = [
    "AdmittedStandaloneRuntime",
    "CODEX_RUNTIME_DESTINATIONS",
    "CODEX_RUNTIME_FILES",
    "CODEX_RUNTIME_MODES",
    "CODEX_RUNTIME_ROOT",
    "CodexRuntime",
    "RuntimeDirIdentity",
    "RuntimeFileIdentity",
    "RuntimeStatIdentity",
    "StandaloneRuntimeEntry",
    "StandaloneRuntimeFile",
    "StandaloneRuntimeProjection",
    "admit_runtime",
    "open_runtime",
    "resolve_runtime",
    "resolve_trusted_codex_lookup",
    "runtime_binds",
    "subject_runtime",
    "verify_standalone_projection",
]
