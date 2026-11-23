"""LaneExec snapshot and seed construction (launch protocol v1 ``x-snapshot`` and ``x-seed``).

:func:`build_snapshot` copies a hostile source tree into a new private execution tree in one of
the three frozen modes (``git``, ``git_overlay``, ``full``). :func:`build_seed` captures the
requester's declared seed set into a private staging directory. Neither touches the network.

Source handling follows ``x-contract-pins.writer_snapshot_reference``:

* git never runs with the source as its repository. A private reader repository borrows the
  source's objects through an alternate, reads a *copy* of the source index and runs with a
  sanitized environment and forced configuration (no system or global configuration, hooks,
  fsmonitor, filters, protocols, replace objects, lazy fetch, pager or editor). The source's own
  configuration is only parsed from a private copy with ``git config --file --no-includes``.
* Files are read through descriptors opened one path component at a time without following a
  symlink, and blob ids are computed here from the bytes read.
* After the copy, HEAD, the index bytes, the untracked listing and every copied entry's stamp are
  checked again (``x-snapshot.recheck``).

Every refusal is a :class:`SnapshotRefused` or :class:`SeedRefused` carrying one closed reason of
the schema's ``SnapshotReason`` or ``SeedReason``; no path, input value or git output reaches it.
A cancel observed while constructing raises :class:`ConstructionCancelled`.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence
import unicodedata

import rfc8785

from . import openshell_artifacts as _artifacts
from .launch_process_contract import (
    InventoryCounts,
    SeedDeclaration,
    SeedEntry,
    SeedLimits,
    Snapshot,
    SnapshotEvidence,
    validate_launch_message,
)

__all__ = [
    "DEFAULT_SECRET_MATCHER",
    "DEFAULT_SNAPSHOT_BUDGET_S",
    "DEFAULT_SEED_LIMITS",
    "DEFAULT_SNAPSHOT_LIMITS",
    "SEED_CODE",
    "SNAPSHOT_CODE",
    "ConstructionCancelled",
    "SecretMatcher",
    "SeedHandle",
    "SeedRefused",
    "SnapshotHandle",
    "SnapshotLimits",
    "SnapshotPolicy",
    "SnapshotRefused",
    "build_seed",
    "build_snapshot",
    "overlay_bytes",
    "snapshot_budget",
    "tree_manifest_rows",
    "tree_manifest_sha256",
]

SNAPSHOT_CODE = "sandbox_launch_snapshot_refused"
SEED_CODE = "sandbox_launch_seed_refused"

SNAPSHOT_REASONS = frozenset({
    "not_a_work_tree", "dirty_source", "untracked_input", "too_large", "unsupported_repository",
    "nested_repository", "unsafe_path", "source_changed", "mode_unpermitted", "mask_outside_root",
    "timeout",
})
SEED_REASONS = frozenset({
    "unsafe_path", "symlink", "seed_root_untrusted", "not_regular_file", "manifest_invalid",
    "image_link_conflict", "digest_mismatch", "too_large", "source_changed", "timeout",
    "scratch_unprovisioned",
})

#: The private branch the execution repository starts on.
EXECUTION_BRANCH = "laneexec"
#: Fixed identity and stamp of the synthetic input commit S.
_SYNTHETIC_ENV = MappingProxyType({
    "GIT_AUTHOR_NAME": "agent-harness-laneexec", "GIT_AUTHOR_EMAIL": "laneexec@invalid",
    "GIT_AUTHOR_DATE": "@0 +0000", "GIT_COMMITTER_NAME": "agent-harness-laneexec",
    "GIT_COMMITTER_EMAIL": "laneexec@invalid", "GIT_COMMITTER_DATE": "@0 +0000",
})
_GIT = "/usr/bin/git"
_OBJECT_FORMATS = MappingProxyType({"sha1": 40, "sha256": 64})
_SMALL_FILE = 1024 * 1024
_MAX_INDEX_BYTES = 512 * 1024 * 1024
_GIT_OUTPUT_CAP = 512 * 1024 * 1024
_READ_CHUNK = 1024 * 1024
_FULL_DEPTH = 64

#: Forced on every git command, ahead of its own arguments (writer_snapshot_reference).
_GIT_CONFIG = (
    "core.hooksPath=/dev/null", "core.fsmonitor=false", "core.untrackedCache=false",
    "core.splitIndex=false", "core.sparseCheckout=false", "core.autocrlf=false",
    "core.safecrlf=false", "core.symlinks=true", "core.fileMode=true",
    "core.attributesFile=/dev/null", "core.excludesFile=/dev/null", "core.askPass=",
    "core.sshCommand=false", "core.pager=cat", "credential.helper=", "protocol.allow=never",
    "submodule.recurse=false", "gc.auto=0", "maintenance.auto=false", "commit.gpgSign=false",
    "tag.gpgSign=false", "advice.detachedHead=false", "init.defaultBranch=main",
    "safe.bareRepository=all",
)
_GIT_ENV = MappingProxyType({
    "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false",
    "SSH_ASKPASS": "/bin/false", "GIT_EDITOR": "/bin/false", "GIT_SEQUENCE_EDITOR": "/bin/false",
    "GIT_PAGER": "cat", "PAGER": "cat", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
    "GIT_OPTIONAL_LOCKS": "0", "GIT_PROTOCOL_FROM_USER": "0", "GIT_ALLOW_PROTOCOL": "",
    "GIT_LITERAL_PATHSPECS": "1", "GIT_ADVICE": "0",
})


# -- refusals -------------------------------------------------------------------------------

class SnapshotRefused(Exception):
    """``state refused``, code ``sandbox_launch_snapshot_refused`` with ``snapshot_reason``."""

    code = SNAPSHOT_CODE

    def __init__(self, reason: str):
        if reason not in SNAPSHOT_REASONS:
            raise ValueError("snapshot_reason_unknown")
        super().__init__(reason)
        self.reason = reason


class SeedRefused(Exception):
    """``state refused``, code ``sandbox_launch_seed_refused`` with ``seed_reason``."""

    code = SEED_CODE

    def __init__(self, reason: str):
        if reason not in SEED_REASONS:
            raise ValueError("seed_reason_unknown")
        super().__init__(reason)
        self.reason = reason


class ConstructionCancelled(Exception):
    """The caller's ``cancelled`` predicate became true while a snapshot or seed was built."""


class _Timeout(Exception):
    pass


# -- limits and policy ----------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotLimits:
    """``x-snapshot.limits``; operator configuration may only lower the defaults."""

    max_bytes: int = 536870912
    max_entries: int = 200000
    untracked_blob_max_bytes: int = 67108864

    def __post_init__(self):
        for name, ceiling in (("max_bytes", 536870912), ("max_entries", 200000),
                              ("untracked_blob_max_bytes", 67108864)):
            value = getattr(self, name)
            if type(value) is not int or value < 0 or value > ceiling:
                raise ValueError("snapshot_limits_invalid")

    def to_json(self) -> dict[str, int]:
        return {"max_bytes": self.max_bytes, "max_entries": self.max_entries,
                "untracked_blob_max_bytes": self.untracked_blob_max_bytes}


DEFAULT_SNAPSHOT_LIMITS = SnapshotLimits()
DEFAULT_SEED_LIMITS = SeedLimits(4096, 16777216, 67108864, 1048576)
_SEED_CEILINGS = DEFAULT_SEED_LIMITS


@dataclass(frozen=True)
class SecretMatcher:
    """The operator secret-name matcher (``x-snapshot.masks``), matched case-insensitively.

    ``dirs`` are segment sequences matched anywhere in a path, ``names`` exact file names and
    ``patterns`` regular expressions on a file name. Its :attr:`identity` enters masks_sha256.
    """

    dirs: tuple[tuple[str, ...], ...]
    names: tuple[str, ...]
    patterns: tuple[str, ...]
    _compiled: tuple[re.Pattern[str], ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "dirs", tuple(tuple(s.lower() for s in d) for d in self.dirs))
        object.__setattr__(self, "names", tuple(n.lower() for n in self.names))
        object.__setattr__(self, "_compiled", tuple(re.compile(p) for p in self.patterns))

    def to_json(self) -> dict[str, Any]:
        return {"dirs": [list(d) for d in self.dirs], "names": list(self.names),
                "patterns": list(self.patterns)}

    @property
    def identity(self) -> str:
        return hashlib.sha256(rfc8785.dumps(self.to_json())).hexdigest()

    def matches(self, path: str) -> bool:
        segments = [s.lower() for s in path.split("/") if s]
        for rule in self.dirs:
            for index in range(len(segments) - len(rule) + 1):
                if list(rule) == segments[index:index + len(rule)]:
                    return True
        name = segments[-1] if segments else ""
        return name in self.names or any(p.search(name) for p in self._compiled)


#: The toolkit's shared secret list (``snapshot_limits_reference`` policy ``secrets``).
DEFAULT_SECRET_MATCHER = SecretMatcher(
    dirs=((".ssh",), (".aws",), (".gnupg",), (".config", "op"), (".docker",), (".kube",)),
    names=(".npmrc", ".netrc", "_netrc", ".pypirc", ".git-credentials", "credentials.json"),
    patterns=(r"^\.env$", r"^\.env\.(?!(example|sample|template)$).+$",
              r"\.(pem|key|p12|pfx|kdbx)$", r"^id_[a-z0-9_-]+$"),
)

#: Default workload policy: the modes each workload may take without an operator entry.
_DEFAULT_MODES = MappingProxyType({
    "pi-runner": frozenset({"git", "git_overlay"}),
    "implementation": frozenset({"git"}),
    "leg": frozenset({"git", "full"}),
    "qualification": frozenset({"git", "full"}),
})


@dataclass(frozen=True)
class SnapshotPolicy:
    """The effective snapshot policy for one launch.

    ``operator_modes`` are the modes an operator workload-policy entry adds for this workload.
    ``result_kind`` ``patch`` never takes ``git_overlay``. The secret matcher always applies.
    """

    workload: str
    result_kind: str
    limits: SnapshotLimits = DEFAULT_SNAPSHOT_LIMITS
    secrets: SecretMatcher = DEFAULT_SECRET_MATCHER
    operator_modes: frozenset[str] = frozenset()
    budget_s: float = 300.0

    def permits(self, mode: str) -> bool:
        if mode == "git_overlay" and self.result_kind == "patch":
            return False
        return mode in (_DEFAULT_MODES.get(self.workload, frozenset({"git"})) | self.operator_modes)


# -- the shared snapshot budget -------------------------------------------------------------

#: ``x-lifetime.budget``: the default snapshot budget (the pinned driver-default transfer allowance).
DEFAULT_SNAPSHOT_BUDGET_S = 300.0
_BUDGET_END: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "laneexec_snapshot_budget_end", default=None)


@contextlib.contextmanager
def snapshot_budget(seconds: float):
    """Bind one attempt's finite snapshot budget for the builders called inside the block.

    ``x-lifetime.budget``: snapshot construction and seed capture share the attempt's snapshot
    budget. The end is fixed when the block is entered; a nested block may only shorten it, and
    neither builder ever extends it. Outside a block each builder applies the default budget.
    """
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("snapshot_budget_invalid")
    end = time.monotonic() + seconds
    outer = _BUDGET_END.get()
    if outer is not None:
        end = min(end, outer)
    token = _BUDGET_END.set(end)
    try:
        yield end
    finally:
        _BUDGET_END.reset(token)


def _budget_end(budget_s: float) -> float:
    if type(budget_s) not in (int, float) or not math.isfinite(budget_s) or budget_s < 0:
        raise ValueError("snapshot_budget_invalid")
    end = time.monotonic() + budget_s
    outer = _BUDGET_END.get()
    return end if outer is None else min(end, outer)


# -- small helpers --------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jcs(value: Any) -> bytes:
    return rfc8785.dumps(value)


class _Clock:
    """One finite monotonic end and the caller's cancel predicate, checked during every read."""

    def __init__(self, end: float, cancelled: Callable[[], bool]):
        self.end = end
        self.cancelled = cancelled

    def left(self) -> float:
        if self.cancelled():
            raise ConstructionCancelled()
        remaining = self.end - time.monotonic()
        if not math.isfinite(remaining) or remaining <= 0:
            raise _Timeout()
        return remaining


def _unsafe_path(path: str) -> bool:
    """``x-snapshot.path_rules`` for a repository-relative path.

    NFC UTF-8, '/'-separated, no empty, '.' or '..' segment, no control character, backslash or
    ':' and no ``.git`` component in any case or 8.3 alias. This is the snapshot grammar of the
    wire (RepoPath plus the writer-path rules); it is deliberately wider than
    ``openshell_artifacts.safe_path``, the openshell owned-path grammar, which refuses ordinary
    names such as ``.gitattributes`` or a space.
    """
    if not isinstance(path, str) or not path or path.startswith("/") or len(path) > 4096:
        return True
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return True
    if any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in path):
        return True
    if unicodedata.normalize("NFC", path) != path:
        return True
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return True
        if re.fullmatch(r"\.git[. ]*", part, re.IGNORECASE) or re.fullmatch(r"git~\d+", part, re.IGNORECASE):
            return True
    return False


def _gitmodules(path: str) -> bool:
    return any(re.fullmatch(r"\.gitmodules[. ]*", part, re.IGNORECASE) for part in path.split("/"))


def _open_dir_at(parent: int, name: str) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)


def _open_root(path: Path | str) -> int:
    """Open an absolute directory one component at a time from ``/``, following no symlink."""
    parts = Path(path).parts
    if not parts or parts[0] != "/" or any(p in (".", "..") for p in parts[1:]):
        raise OSError(errno.EINVAL, "not absolute")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[1:]:
            child = _open_dir_at(fd, part)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_rel_dir(base_fd: int, rel: str) -> int:
    fd = os.dup(base_fd)
    try:
        for part in rel.split("/") if rel else ():
            child = _open_dir_at(fd, part)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _identity(fd: int) -> tuple[int, int]:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def _blob_hasher(object_format: str, size: int):
    h = hashlib.sha256() if object_format == "sha256" else hashlib.sha1()  # noqa: S324 - git id
    h.update(b"blob %d\x00" % size)
    return h


def _git_mode(info: os.stat_result) -> str | None:
    if stat.S_ISLNK(info.st_mode):
        return "120000"
    if stat.S_ISREG(info.st_mode):
        return "100755" if info.st_mode & 0o100 else "100644"
    return None


def _kind(info: os.stat_result) -> str:
    if stat.S_ISDIR(info.st_mode):
        return "dir"
    if stat.S_ISLNK(info.st_mode):
        return "symlink"
    if stat.S_ISREG(info.st_mode):
        return "file"
    return "special"


@dataclass
class _Content:
    mode: str
    size: int
    oid: str
    sha256: str
    target: bytes | None = None


def _read_content(dir_fd: int, name: str, info: os.stat_result, object_format: str, clock: _Clock, *,
                  cap: int, sink: Callable[[bytes], None] | None = None) -> _Content:
    """Read a regular file or symlink named ``name`` in ``dir_fd`` without following a symlink.

    ``info`` is its lstat. A size above ``cap`` refuses ``too_large`` before any byte is read;
    the read stops at the lstat size + 1 bytes (so at most ``cap`` + 1), and the clock and the
    cancel predicate are checked before every chunk.
    """
    clock.left()
    if stat.S_ISLNK(info.st_mode):
        target = os.fsencode(os.readlink(name, dir_fd=dir_fd))
        if len(target) > cap:
            raise SnapshotRefused("too_large")
        h = _blob_hasher(object_format, len(target))
        h.update(target)
        if sink is not None:
            sink(target)
        return _Content("120000", len(target), h.hexdigest(), _sha256(target), target)
    size = info.st_size
    if size > cap:
        raise SnapshotRefused("too_large")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    try:
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISREG(current.st_mode):
            raise SnapshotRefused("source_changed")
        h = _blob_hasher(object_format, size)
        s = hashlib.sha256()
        total = 0
        while True:
            clock.left()
            chunk = os.read(fd, min(_READ_CHUNK, size + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > size:
                raise SnapshotRefused("source_changed")
            h.update(chunk)
            s.update(chunk)
            if sink is not None:
                sink(chunk)
        if total != size:
            raise SnapshotRefused("source_changed")
    finally:
        os.close(fd)
    return _Content(_git_mode(info) or "100644", size, h.hexdigest(), s.hexdigest())


def _lstat_at(base_fd: int, rel: str) -> tuple[int | None, os.stat_result | None]:
    """``(parent_fd, lstat)`` of ``rel`` below ``base_fd`` through no-follow components.

    The caller closes ``parent_fd``. Both are None when a component is missing or not a plain
    directory; ``lstat`` alone is None when the last component is missing.
    """
    parent, _, name = rel.rpartition("/")
    try:
        fd = _open_rel_dir(base_fd, parent)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
            return None, None
        raise
    try:
        return fd, os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return fd, None


def _meta_read(base_fd: int, rel: str, clock: _Clock, cap: int = _SMALL_FILE) -> bytes | None:
    """A repository metadata file read through pinned, no-follow descriptors.

    The clock is checked before the open and before every read; the read stops at the recorded
    size + 1 bytes, and a stamp that drifts between the lstat and the end of the read refuses
    ``source_changed``.
    """
    return _meta_read_stamped(base_fd, rel, clock, cap)[0]


def _meta_read_stamped(base_fd: int, rel: str, clock: _Clock,
                       cap: int = _SMALL_FILE) -> tuple[bytes | None, tuple[int, ...] | None]:
    clock.left()
    fd, info = _lstat_at(base_fd, rel)
    if fd is None:
        return None, None
    try:
        if info is None:
            return None, None
        if not stat.S_ISREG(info.st_mode):
            raise SnapshotRefused("unsupported_repository")
        size = info.st_size
        if size > cap:
            raise SnapshotRefused("too_large")
        name = rel.rpartition("/")[2]
        clock.left()
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        try:
            if _identity(file_fd) != (info.st_dev, info.st_ino):
                raise SnapshotRefused("source_changed")
            chunks: list[bytes] = []
            total = 0
            while total <= size:
                clock.left()
                chunk = os.read(file_fd, min(_READ_CHUNK, size + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total != size or _stamp(os.fstat(file_fd)) != _stamp(info):
                raise SnapshotRefused("source_changed")
            return b"".join(chunks), _stamp(info)
        finally:
            os.close(file_fd)
    finally:
        os.close(fd)


def _meta_exists(base_fd: int, rel: str) -> bool:
    fd, info = _lstat_at(base_fd, rel)
    if fd is not None:
        os.close(fd)
    return info is not None


# -- sanitized git --------------------------------------------------------------------------

def _git(clock: _Clock, args: Sequence[str], *, git_dir: Path | str | None = None,
         work_tree: str | None = None, index_file: Path | None = None, cwd: Path | str = Path("/"),
         data: bytes = b"", extra_env: Mapping[str, str] | None = None, allow_fail: bool = False,
         code: str = "unsupported_repository", pass_fds: tuple[int, ...] = ()) -> bytes:
    env = dict(_GIT_ENV)
    if git_dir is not None:
        env["GIT_DIR"] = str(git_dir)
    if work_tree is not None:
        env["GIT_WORK_TREE"] = work_tree
    if index_file is not None:
        env["GIT_INDEX_FILE"] = str(index_file)
    if extra_env:
        env.update(extra_env)
    argv = [_GIT, "--no-replace-objects"]
    for item in _GIT_CONFIG:
        argv += ["-c", item]
    argv += list(args)
    try:
        clock.left()
    except _Timeout:
        raise SnapshotRefused("timeout") from None
    try:
        rc, out, _ = _artifacts.run_process(tuple(argv), cwd=Path(cwd), env=env, data=data, cap=_GIT_OUTPUT_CAP,
                                            bound=_artifacts.Bound(clock.end, clock.cancelled),
                                            pass_fds=pass_fds)
    except _artifacts.Refused as refusal:
        if str(refusal) == "cancelled":
            raise ConstructionCancelled() from None
        if str(refusal) == "output_limit":
            raise SnapshotRefused("too_large") from None
        raise SnapshotRefused("timeout" if str(refusal) == "end_reached" else code) from None
    if rc and not allow_fail:
        raise SnapshotRefused(code)
    return out


def _split_z(data: bytes) -> list[str]:
    items = data.split(b"\x00")
    if items and items[-1] == b"":
        items.pop()
    try:
        return [item.decode("utf-8") for item in items]
    except UnicodeDecodeError:
        raise SnapshotRefused("unsafe_path") from None


def _is_oid(object_format: str, text: str) -> bool:
    return (len(text) == _OBJECT_FORMATS[object_format] and re.fullmatch(r"[0-9a-f]+", text) is not None
            and text != "0" * len(text))


# -- the source repository ------------------------------------------------------------------

@dataclass
class _Source:
    """The source repository's metadata, held through pinned directory descriptors."""

    git_fd: int
    common_fd: int
    objects_fd: int
    identities: tuple[tuple[int, int], ...]
    pointers: tuple[tuple[str, tuple[int, ...] | None], ...]
    linked: bool
    object_format: str
    head_ref: str | None
    head_oid: str
    exclude: bytes

    def close(self) -> None:
        for fd in {self.git_fd, self.common_fd, self.objects_fd}:
            try:
                os.close(fd)
            except OSError:
                pass


def _lexical(base: str, text: str) -> str:
    """An absolute, lexically normalized path; ``..`` is resolved without consulting the disk."""
    return os.path.normpath(text if os.path.isabs(text) else os.path.join(base, text))


def _open_meta_dir(path: str) -> int:
    try:
        return _open_root(path)
    except OSError:
        raise SnapshotRefused("not_a_work_tree") from None


def _locate(root_fd: int, top: Path, clock: _Clock) -> tuple[int, int, bool, tuple] | None:
    """``(git_fd, common_fd, linked)`` of work tree ``top`` through no-follow descriptors.

    A linked worktree's ``.git`` pointer, its gitdir backlink and ``commondir`` are resolved
    lexically and opened component by component; a symlink component refuses, and the backlink
    must name this ``.git`` by identity. The stamps of each present pointer file (``.git``,
    ``gitdir``, ``commondir``) are returned for the post-copy recheck. None when ``top`` has no
    ``.git``.
    """
    pointers: list[tuple[str, tuple[int, ...] | None]] = []
    try:
        info = os.stat(".git", dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(info.st_mode):
        git_fd, linked, git_path = _open_dir_at(root_fd, ".git"), False, str(top / ".git")
    elif stat.S_ISREG(info.st_mode):
        raw, stamp = _meta_read_stamped(root_fd, ".git", clock, 4096)
        pointers.append((".git", stamp))
        text = (raw or b"").decode("utf-8", "replace")
        match = re.fullmatch(r"gitdir: (.+?)\r?\n?", text)
        if not match:
            raise SnapshotRefused("not_a_work_tree")
        git_path = _lexical(str(top), match.group(1))
        git_fd, linked = _open_meta_dir(git_path), True
        try:
            raw, stamp = _meta_read_stamped(git_fd, "gitdir", clock, 4096)
            pointers.append(("gitdir", stamp))
            back = (raw or b"").decode("utf-8", "replace").strip()
            if not back:
                raise SnapshotRefused("not_a_work_tree")
            back_path = _lexical(git_path, back)
            parent_fd = _open_meta_dir(os.path.dirname(back_path))
            try:
                pointer = os.stat(os.path.basename(back_path), dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise SnapshotRefused("not_a_work_tree") from None
            finally:
                os.close(parent_fd)
            if (pointer.st_dev, pointer.st_ino) != (info.st_dev, info.st_ino):
                raise SnapshotRefused("not_a_work_tree")
        except BaseException:
            os.close(git_fd)
            raise
    else:
        raise SnapshotRefused("not_a_work_tree")
    try:
        raw, stamp = _meta_read_stamped(git_fd, "commondir", clock, 4096)
        pointers.append(("commondir", stamp))
        common_text = (raw or b"").decode("utf-8", "replace").strip()
        if common_text:
            common_fd = _open_meta_dir(_lexical(git_path, common_text))
        else:
            common_fd = os.dup(git_fd)
    except BaseException:
        os.close(git_fd)
        raise
    if linked and _identity(common_fd) == _identity(git_fd):
        os.close(common_fd)
        os.close(git_fd)
        raise SnapshotRefused("not_a_work_tree")
    return git_fd, common_fd, linked, tuple(pointers)


def _parse_config(clock: _Clock, raw: bytes, box: Path) -> dict[str, str]:
    """Parse a private copy of config bytes with includes off; never the source's file."""
    directory = box / f"config-{len(os.listdir(box))}"
    directory.mkdir(mode=0o700)
    (directory / "config").write_bytes(raw)
    out = _git(clock, ["config", "--file", str(directory / "config"), "--no-includes", "--null", "--list"],
               git_dir=directory / "no-repository", cwd=directory)
    values: dict[str, str] = {}
    for item in _split_z(out):
        key, sep, value = item.partition("\n")
        values[key.lower()] = value if sep else "true"
    return values


def _read_ref(git_fd: int, common_fd: int, name: str, object_format: str, clock: _Clock) -> str | None:
    base = git_fd if re.match(r"refs/(bisect|rewritten|worktree)/", name) else common_fd
    loose = _meta_read(base, name, clock, 4096)
    if loose is not None:
        text = loose.decode("ascii", "replace").strip()
        if not _is_oid(object_format, text):
            raise SnapshotRefused("unsupported_repository")
        return text
    packed = _meta_read(common_fd, "packed-refs", clock, 256 * 1024 * 1024)
    for line in (packed or b"").decode("utf-8", "replace").split("\n"):
        if not line or line.startswith(("#", "^")):
            continue
        oid, _, ref = line.partition(" ")
        if ref == name:
            if not _is_oid(object_format, oid):
                raise SnapshotRefused("unsupported_repository")
            return oid
    return None


def _inspect(clock: _Clock, root_fd: int, top: Path, box: Path) -> _Source | None:
    located = _locate(root_fd, top, clock)
    if located is None:
        return None
    git_fd, common_fd, linked, pointers = located
    objects_fd = -1
    try:
        for base, rel in ((common_fd, "objects/info/alternates"), (common_fd, "objects/info/http-alternates"),
                          (common_fd, "shallow"), (git_fd, "shallow"), (common_fd, "reftable")):
            if _meta_exists(base, rel):
                raise SnapshotRefused("unsupported_repository")
        try:
            objects_fd = _open_dir_at(common_fd, "objects")
        except OSError:
            raise SnapshotRefused("unsupported_repository") from None
        try:
            pack_fd = _open_dir_at(objects_fd, "pack")
        except FileNotFoundError:
            pack_fd = None
        except OSError:
            raise SnapshotRefused("unsupported_repository") from None
        if pack_fd is not None:
            try:
                if any(n.endswith(".promisor") for n in os.listdir(pack_fd)):
                    raise SnapshotRefused("unsupported_repository")
            finally:
                os.close(pack_fd)
        if any(n.startswith("sharedindex.") for n in os.listdir(git_fd)):
            raise SnapshotRefused("unsupported_repository")
        config = _parse_config(clock, _meta_read(common_fd, "config", clock) or b"", box)
        version = config.get("core.repositoryformatversion", "0")
        if version not in ("0", "1"):
            raise SnapshotRefused("unsupported_repository")
        if config.get("core.bare", "false").lower() == "true" or "core.worktree" in config:
            raise SnapshotRefused("unsupported_repository")
        object_format = config.get("extensions.objectformat", "sha1").lower()
        if object_format not in _OBJECT_FORMATS:
            raise SnapshotRefused("unsupported_repository")
        for key, value in config.items():
            if key == "extensions.partialclone" or (
                    re.fullmatch(r"remote\..*\.promisor", key) and value.lower() == "true"):
                raise SnapshotRefused("unsupported_repository")
            if key == "extensions.refstorage" and value.lower() != "files":
                raise SnapshotRefused("unsupported_repository")
            if key.startswith("extensions.") and version == "1" and key not in (
                    "extensions.objectformat", "extensions.worktreeconfig", "extensions.refstorage"):
                raise SnapshotRefused("unsupported_repository")
        head = (_meta_read(git_fd, "HEAD", clock, 4096) or b"").decode("utf-8", "replace").strip()
        if _is_oid(object_format, head):
            head_ref, head_oid = None, head
        else:
            match = re.fullmatch(r"ref: (refs/heads/[^\x00-\x20\x7f~^:?*\[\\]+)", head)
            if not match or ".." in match.group(1) or "@{" in match.group(1):
                raise SnapshotRefused("not_a_work_tree")
            oid = _read_ref(git_fd, common_fd, match.group(1), object_format, clock)
            if oid is None:
                raise SnapshotRefused("not_a_work_tree")
            head_ref, head_oid = match.group(1), oid
        exclude = _meta_read(common_fd, "info/exclude", clock) or b""
        identities = (_identity(git_fd), _identity(common_fd), _identity(objects_fd))
        return _Source(git_fd, common_fd, objects_fd, identities, pointers, linked, object_format, head_ref,
                       head_oid, exclude)
    except BaseException:
        for fd in {git_fd, common_fd, objects_fd}:
            if fd >= 0:
                os.close(fd)
        raise


# -- canonical digests ----------------------------------------------------------------------

def tree_manifest_rows(entries: Iterable[tuple[str, str, str]]) -> list[list[str]]:
    """``rfc8785_tree_manifest`` rows ``[path, kind, sha256]`` sorted by UTF-8 path bytes."""
    rows = [[path, kind, digest] for path, kind, digest in entries]
    rows.sort(key=lambda row: row[0].encode("utf-8"))
    return rows


def tree_manifest_sha256(rows: Sequence[Sequence[str]]) -> str:
    return _sha256(_jcs([list(row) for row in rows]))


def overlay_bytes(entries: Iterable[tuple[str, str, str | None]]) -> bytes:
    """The UTF-8 RFC 8785 overlay array of ``[path, kind, sha256|null]`` sorted by path bytes."""
    rows = sorted(([p, k, d] for p, k, d in entries), key=lambda row: row[0].encode("utf-8"))
    return _jcs(rows)


def _walk_tree_rows(root: Path, clock: _Clock | None = None) -> list[list[str]]:
    """Recompute the tree manifest of a private execution tree (``.git`` excluded)."""
    rows: list[tuple[str, str, str]] = []
    fd = _open_root(root)
    stack = [(fd, "")]
    try:
        while stack:
            dir_fd, prefix = stack.pop()
            try:
                for name in sorted(os.listdir(dir_fd)):
                    if clock is not None:
                        clock.left()
                    if not prefix and name == ".git":
                        continue
                    rel = prefix + name
                    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        stack.append((_open_dir_at(dir_fd, name), rel + "/"))
                    elif stat.S_ISLNK(info.st_mode):
                        rows.append((rel, "symlink", _sha256(os.fsencode(os.readlink(name, dir_fd=dir_fd)))))
                    elif stat.S_ISREG(info.st_mode):
                        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
                        h = hashlib.sha256()
                        try:
                            while chunk := os.read(file_fd, _READ_CHUNK):
                                if clock is not None:
                                    clock.left()
                                h.update(chunk)
                        finally:
                            os.close(file_fd)
                        rows.append((rel, "executable_file" if info.st_mode & 0o111 else "file", h.hexdigest()))
                    else:
                        raise SnapshotRefused("source_changed")
            finally:
                os.close(dir_fd)
    finally:
        for dir_fd, _ in stack:
            os.close(dir_fd)
    return tree_manifest_rows(rows)


# -- the snapshot handle --------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotHandle:
    """One constructed execution tree and its frozen identity.

    ``envelope_base_commit`` is the envelope ``workspace_state.base_commit`` (S, B in
    ``git_overlay``, null without a work tree). ``descriptor_bytes`` are the RFC 8785 snapshot
    descriptor ``laneexec.snapshot.descriptor.v1``, the envelope's single baseline reference
    (an internal canonical artifact; the wire fixes no descriptor schema). ``inventory`` lists
    every source path with its class; nothing in it is file content.
    """

    tree: Path
    mode: str
    cwd: str
    object_format: str | None
    base_commit: str | None
    input_commit: str | None
    overlay: bytes | None = field(repr=False)
    content_sha256: str
    inventory: tuple[Mapping[str, Any], ...] = field(repr=False)
    inventory_sha256: str
    masks_sha256: str
    counts: InventoryCounts
    byte_total: int
    tree_rows: tuple[tuple[str, str, str], ...] = field(repr=False)

    @property
    def overlay_sha256(self) -> str | None:
        return None if self.overlay is None else _sha256(self.overlay)

    @property
    def envelope_base_commit(self) -> str | None:
        return self.input_commit if self.mode != "git_overlay" else self.base_commit

    @property
    def top_level_entries(self) -> tuple[str, ...]:
        return tuple(sorted({row[0].split("/", 1)[0] for row in self.tree_rows}, key=str.encode))

    def descriptor(self) -> dict[str, Any]:
        return {"schema": "laneexec.snapshot.descriptor.v1", "mode": self.mode, "cwd": self.cwd,
                "object_format": self.object_format, "base_commit": self.base_commit,
                "input_commit": self.input_commit, "overlay_sha256": self.overlay_sha256,
                "content_sha256": self.content_sha256, "inventory_sha256": self.inventory_sha256,
                "masks_sha256": self.masks_sha256, "counts": self.counts.to_json(),
                "byte_total": self.byte_total}

    @property
    def descriptor_bytes(self) -> bytes:
        return _jcs(self.descriptor())

    @property
    def descriptor_sha256(self) -> str:
        return _sha256(self.descriptor_bytes)

    def evidence(self) -> SnapshotEvidence:
        return SnapshotEvidence(self.mode, self.content_sha256, self.base_commit, self.input_commit,
                                self.overlay_sha256, self.inventory_sha256, self.masks_sha256,
                                self.counts, self.byte_total)

    def recheck(self) -> None:
        """Recompute the execution tree's manifest; any difference refuses ``source_changed``."""
        try:
            rows = _walk_tree_rows(self.tree)
        except OSError:
            raise SnapshotRefused("source_changed") from None
        if tree_manifest_sha256(rows) != self.content_sha256:
            raise SnapshotRefused("source_changed")

    def discard(self) -> None:
        shutil.rmtree(self.tree.parent, ignore_errors=True)


#: Test seams: barriers after the inventory and after the copy, before the recheck.
_after_enumerate: Callable[[], None] = lambda: None
_after_inventory: Callable[[], None] = lambda: None
_after_copy: Callable[[Path], None] = lambda tree: None


# -- construction ---------------------------------------------------------------------------

class _Masks:
    def __init__(self, root_fd: int, spec: Snapshot, secrets: SecretMatcher):
        self.files = frozenset(spec.masks)
        self.dirs = tuple(sorted(set(spec.mask_dirs)))
        self.secrets = secrets
        for path in (*spec.masks, *spec.mask_dirs):
            if not isinstance(path, str) or path.startswith("/") or any(
                    part in ("", ".", "..") for part in path.split("/")):
                raise SnapshotRefused("mask_outside_root")
            # A mask resolved through a symlinked directory would name content outside the root.
            fd = os.dup(root_fd)
            try:
                for part in path.split("/")[:-1]:
                    try:
                        child = _open_dir_at(fd, part)
                    except FileNotFoundError:
                        break
                    except OSError:
                        raise SnapshotRefused("mask_outside_root") from None
                    os.close(fd)
                    fd = child
            finally:
                os.close(fd)

    def __call__(self, path: str) -> bool:
        if path in self.files or any(path == d or path.startswith(d + "/") for d in self.dirs):
            return True
        return self.secrets.matches(path)

    @property
    def sha256(self) -> str:
        return _sha256(_jcs({"files": sorted(self.files, key=str.encode),
                             "dirs": sorted(self.dirs, key=str.encode),
                             "secrets": self.secrets.identity}))


class _Inventory:
    def __init__(self, limits: SnapshotLimits):
        self.limits = limits
        self.entries: dict[str, dict[str, Any]] = {}
        self.bytes = 0

    def remaining(self) -> int:
        return self.limits.max_bytes - self.bytes

    def add(self, path: str, cls: str, *, kind: str, mode: str | None = None, oid: str | None = None,
            size: int = 0) -> None:
        if len(self.entries) >= self.limits.max_entries:
            raise SnapshotRefused("too_large")
        if cls in ("tracked", "untracked", "ignored"):
            self.bytes += size
            if self.bytes > self.limits.max_bytes:
                raise SnapshotRefused("too_large")
        self.entries[path] = {"path": path, "class": cls, "type": kind, "mode": mode, "oid": oid}

    def sorted(self) -> list[dict[str, Any]]:
        return [self.entries[p] for p in sorted(self.entries, key=str.encode)]

    def counts(self) -> InventoryCounts:
        tally = dict.fromkeys(("tracked", "untracked", "ignored", "omitted", "masked", "special"), 0)
        for entry in self.entries.values():
            tally[entry["class"]] += 1
        return InventoryCounts(**tally)


@dataclass(frozen=True)
class _Node:
    """One enumerated source entry: its relative path, kind, depth and stamp."""

    rel: str
    kind: str
    depth: int
    stamp: tuple[int, ...]


def _enumerate(root_fd: int, clock: _Clock, limits: SnapshotLimits, *, skip_top_git: bool) -> dict[str, _Node]:
    """Every source entry below ``root_fd``, walked through pinned no-follow directory descriptors.

    Nothing is opened for content here. A directory or file named exactly ``.git`` below the top
    level is a nested repository; the top-level one is skipped when the root is a work tree.
    """
    nodes: dict[str, _Node] = {}
    stack = [(os.dup(root_fd), "", 0)]
    try:
        while stack:
            dir_fd, prefix, depth = stack.pop()
            try:
                for raw_name in sorted(os.listdir(dir_fd)):
                    clock.left()
                    name = raw_name
                    if name == ".git" and not prefix and skip_top_git:
                        continue
                    if name == ".git":
                        raise SnapshotRefused("nested_repository")
                    rel = prefix + name
                    try:
                        rel.encode("utf-8")
                    except UnicodeEncodeError:
                        raise SnapshotRefused("unsafe_path") from None
                    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                    kind = _kind(info)
                    nodes[rel] = _Node(rel, kind, depth, _stamp(info))
                    if len(nodes) > limits.max_entries * 2 + 1:
                        raise SnapshotRefused("too_large")
                    if kind == "dir":
                        stack.append((_open_dir_at(dir_fd, name), rel + "/", depth + 1))
            finally:
                os.close(dir_fd)
    finally:
        for dir_fd, _, _ in stack:
            os.close(dir_fd)
    return nodes


@dataclass
class _Copy:
    path: str
    kind: str  # file | symlink | dir
    size: int
    sha256: str | None
    executable: bool


def _read_node(root_fd: int, node: _Node, object_format: str, clock: _Clock, cap: int) -> _Content:
    parent_fd, info = _lstat_at(root_fd, node.rel)
    if parent_fd is None or info is None:
        if parent_fd is not None:
            os.close(parent_fd)
        raise SnapshotRefused("source_changed")
    try:
        if _stamp(info) != node.stamp:
            raise SnapshotRefused("source_changed")
        return _read_content(parent_fd, node.rel.rpartition("/")[2], info, object_format, clock, cap=cap)
    finally:
        os.close(parent_fd)


def build_snapshot(spec: Snapshot, *, policy: SnapshotPolicy, scratch: Path | str,
                   cancelled: Callable[[], bool]) -> SnapshotHandle:
    """Build the execution tree of ``spec`` under the new private directory ``scratch``.

    ``scratch`` must not exist; its parent must be a trusted directory (owned by this uid, not
    group- or other-writable, no symlink or group- or other-writable ancestor), normally the
    per-reservation directory under the client's LaneExec state directory. ``scratch`` is created
    0700 and receives the execution tree at ``scratch/tree``; private intermediate repositories
    are removed before return, and a refusal or cancel deletes ``scratch``. The budget is
    ``policy.budget_s``, shortened by an enclosing :func:`snapshot_budget`.
    """
    if spec.mode not in ("git", "git_overlay", "full") or not policy.permits(spec.mode):
        raise SnapshotRefused("mode_unpermitted")
    clock = _Clock(_budget_end(policy.budget_s), cancelled)
    base_dir = _private_child(Path(scratch), "snapshot_scratch_invalid")
    box = base_dir / "work"
    box.mkdir(mode=0o700)
    tree = base_dir / "tree"
    try:
        handle = _build(spec, policy, clock, box, tree)
        clock.left()
        return handle
    except _Timeout:
        shutil.rmtree(base_dir, ignore_errors=True)
        raise SnapshotRefused("timeout") from None
    except OSError:
        shutil.rmtree(base_dir, ignore_errors=True)
        raise SnapshotRefused("source_changed") from None
    except BaseException:
        shutil.rmtree(base_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(box, ignore_errors=True)


def _trusted_parent(path: Path) -> bool:
    """Owned by this uid, not group- or other-writable, reached with no symlink or writable ancestor."""
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        for part in path.parts[1:]:
            if os.fstat(fd).st_mode & 0o022:
                return False
            try:
                child = _open_dir_at(fd, part)
            except OSError:
                return False
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        return info.st_uid == os.geteuid() and not info.st_mode & 0o022
    finally:
        os.close(fd)


def _private_child(path: Path, code: str) -> Path:
    if not path.is_absolute() or any(p in (".", "..") for p in path.parts) or not _trusted_parent(path.parent):
        raise ValueError(code)
    try:
        path.mkdir(mode=0o700)
        path.chmod(0o700)
    except OSError:
        raise ValueError(code) from None
    return path


def _build(spec: Snapshot, policy: SnapshotPolicy, clock: _Clock, box: Path, tree: Path) -> SnapshotHandle:
    top = Path(spec.root)
    if not top.is_absolute() or os.path.normpath(top) != str(top):
        raise SnapshotRefused("not_a_work_tree")
    try:
        root_fd = _open_root(top)
    except OSError:
        raise SnapshotRefused("not_a_work_tree") from None
    try:
        if spec.cwd not in (".", ""):
            parent_fd, info = _lstat_at(root_fd, spec.cwd)
            if parent_fd is not None:
                os.close(parent_fd)
            if info is None or not stat.S_ISDIR(info.st_mode):
                raise SnapshotRefused("unsafe_path")
        masks = _Masks(root_fd, spec, policy.secrets)
        source = _inspect(clock, root_fd, top, box)
        if source is None:
            if spec.mode != "full":
                raise SnapshotRefused("not_a_work_tree")
            handle = _build_plain(spec, policy, clock, root_fd, masks, tree)
            _check_root(root_fd, top)
            return handle
        try:
            handle = _build_git(spec, policy, clock, root_fd, top, masks, source, box, tree)
        finally:
            source.close()
        _check_root(root_fd, top)
        return handle
    finally:
        os.close(root_fd)


def _check_root(root_fd: int, top: Path) -> None:
    """The snapshot root path still names the pinned root directory, else ``source_changed``."""
    try:
        fd = _open_root(top)
    except OSError:
        raise SnapshotRefused("source_changed") from None
    try:
        if _identity(fd) != _identity(root_fd):
            raise SnapshotRefused("source_changed")
    finally:
        os.close(fd)


def _build_plain(spec: Snapshot, policy: SnapshotPolicy, clock: _Clock, root_fd: int, masks: _Masks,
                 tree: Path) -> SnapshotHandle:
    """Full mode on a root that is not a git work tree: the whole tree, no ``.git``."""
    limits = policy.limits
    inventory = _Inventory(limits)
    nodes = _enumerate(root_fd, clock, limits, skip_top_git=False)
    copies: list[_Copy] = []
    parents = {rel.rpartition("/")[0] for rel in nodes}
    for rel in sorted(nodes, key=str.encode):
        node = nodes[rel]
        if _unsafe_path(rel) or _gitmodules(rel):
            raise SnapshotRefused("unsafe_path")
        if masks(rel):
            if node.kind != "dir":
                inventory.add(rel, "masked", kind=node.kind)
            continue
        if node.kind == "dir":
            if node.depth >= _FULL_DEPTH:
                raise SnapshotRefused("too_large")
            if rel not in parents:
                inventory.add(rel, "untracked", kind="dir")
                copies.append(_Copy(rel, "dir", 0, None, False))
            continue
        if node.kind == "special":
            inventory.add(rel, "special", kind="special")
            continue
        content = _read_node(root_fd, node, "sha1", clock, inventory.remaining())
        inventory.add(rel, "untracked", kind=node.kind, mode=content.mode, oid=content.oid, size=content.size)
        copies.append(_Copy(rel, node.kind, content.size, content.sha256, content.mode == "100755"))
    _after_inventory()
    tree.mkdir(mode=0o700)
    rows = _copy_entries(root_fd, tree, copies, clock)
    _after_copy(tree)
    _recheck_enumeration(root_fd, clock, limits, nodes, skip_top_git=False)
    if tree_manifest_sha256(_walk_tree_rows(tree, clock)) != tree_manifest_sha256(rows):
        raise SnapshotRefused("source_changed")
    return _handle(spec, tree, None, None, None, None, rows, inventory, masks)


def _recheck_enumeration(root_fd: int, clock: _Clock, limits: SnapshotLimits, nodes: Mapping[str, _Node], *,
                         skip_top_git: bool) -> None:
    """``x-snapshot.recheck``: the source enumeration and every entry's stamp are unchanged."""
    try:
        again = _enumerate(root_fd, clock, limits, skip_top_git=skip_top_git)
    except SnapshotRefused:
        raise SnapshotRefused("source_changed") from None
    for rel in set(again) | set(nodes):
        before, after = nodes.get(rel), again.get(rel)
        if before is None or after is None or before.kind != after.kind:
            raise SnapshotRefused("source_changed")
        if before.kind != "dir" and before.stamp != after.stamp:
            raise SnapshotRefused("source_changed")


def _copy_entries(root_fd: int, tree: Path, copies: Sequence[_Copy], clock: _Clock) -> list[list[str]]:
    """Stream each entry into the new tree, bounded by its admitted size and re-verified."""
    tree_fd = _open_root(tree)
    rows: list[tuple[str, str, str]] = []
    try:
        for item in copies:
            clock.left()
            segments = item.path.split("/")
            name = segments.pop()
            fd = os.dup(tree_fd)
            try:
                for part in segments:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    child = _open_dir_at(fd, part)
                    os.close(fd)
                    fd = child
                if item.kind == "dir":
                    os.mkdir(name, 0o700, dir_fd=fd)
                    continue
                parent_fd, info = _lstat_at(root_fd, item.path)
                if parent_fd is None or info is None:
                    if parent_fd is not None:
                        os.close(parent_fd)
                    raise SnapshotRefused("source_changed")
                try:
                    if _kind(info) != item.kind or (item.kind == "file" and info.st_size != item.size):
                        raise SnapshotRefused("source_changed")
                    if item.kind == "symlink":
                        content = _read_content(parent_fd, name, info, "sha1", clock, cap=item.size)
                        if content.sha256 != item.sha256:
                            raise SnapshotRefused("source_changed")
                        os.symlink(os.fsdecode(content.target or b""), name, dir_fd=fd)
                        rows.append((item.path, "symlink", content.sha256))
                        continue
                    mode = 0o700 if (info.st_mode & 0o100) else 0o600
                    out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  mode, dir_fd=fd)
                    try:
                        def sink(chunk: bytes) -> None:
                            view = memoryview(chunk)
                            while view:
                                view = view[os.write(out, view):]
                        content = _read_content(parent_fd, name, info, "sha1", clock, cap=item.size, sink=sink)
                        os.fchmod(out, mode)
                    finally:
                        os.close(out)
                    if content.sha256 != item.sha256 or (mode == 0o700) != item.executable:
                        raise SnapshotRefused("source_changed")
                    rows.append((item.path, "executable_file" if mode == 0o700 else "file", content.sha256))
                finally:
                    os.close(parent_fd)
            finally:
                os.close(fd)
    finally:
        os.close(tree_fd)
    return tree_manifest_rows(rows)


def _handle(spec: Snapshot, tree: Path, object_format: str | None, base: str | None, input_commit: str | None,
            overlay: bytes | None, rows: list[list[str]], inventory: _Inventory, masks: _Masks) -> SnapshotHandle:
    entries = inventory.sorted()
    return SnapshotHandle(
        tree=tree, mode=spec.mode, cwd=spec.cwd, object_format=object_format, base_commit=base,
        input_commit=input_commit, overlay=overlay, content_sha256=tree_manifest_sha256(rows),
        inventory=tuple(MappingProxyType(e) for e in entries), inventory_sha256=_sha256(_jcs(entries)),
        masks_sha256=masks.sha256, counts=inventory.counts(), byte_total=inventory.bytes,
        tree_rows=tuple(tuple(r) for r in rows))


_PLACEHOLDER_TARGET = "laneexec-placeholder"


def _classification_tree(root_fd: int, nodes: Mapping[str, _Node], classify: Path, clock: _Clock,
                         limits: SnapshotLimits) -> None:
    """A private tree with the source's names: empty files, inert symlinks, captured ignores.

    Only regular files named ``.gitignore`` are read, through :func:`_read_node` under the
    shared clock and a cumulative allowance of ``limits.max_bytes``; special entries are left
    out (the inventory classes them directly).
    """
    classify.mkdir(mode=0o700)
    allowance = limits.max_bytes
    for rel in sorted(nodes, key=str.encode):
        clock.left()
        node = nodes[rel]
        target = classify / rel
        if node.kind == "dir":
            target.mkdir(mode=0o700)
        elif node.kind == "symlink":
            os.symlink(_PLACEHOLDER_TARGET, target)
        elif node.kind == "file":
            data = b""
            if rel.rpartition("/")[2] == ".gitignore":
                chunks: list[bytes] = []
                content = _read_node_into(root_fd, node, clock, allowance, chunks.append)
                allowance -= content.size
                data = b"".join(chunks)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
            finally:
                os.close(fd)


def _read_node_into(root_fd: int, node: _Node, clock: _Clock, cap: int, sink: Callable[[bytes], None]) -> _Content:
    parent_fd, info = _lstat_at(root_fd, node.rel)
    if parent_fd is None or info is None:
        if parent_fd is not None:
            os.close(parent_fd)
        raise SnapshotRefused("source_changed")
    try:
        if _stamp(info) != node.stamp:
            raise SnapshotRefused("source_changed")
        return _read_content(parent_fd, node.rel.rpartition("/")[2], info, "sha1", clock, cap=cap, sink=sink)
    finally:
        os.close(parent_fd)


_LOOSE_DIR = re.compile(r"[0-9a-f]{2}")
_LOOSE_NAME = re.compile(r"[0-9a-f]{38}|[0-9a-f]{62}")
_PACK_NAME = re.compile(r"pack-[0-9a-f]{40,64}\.(pack|idx)")


def _project_objects(objects_fd: int, dest: Path, clock: _Clock) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Stream the pinned store's loose objects and pack/index pairs into a private store.

    The store is walked through no-follow descriptors; a symlink or special entry anywhere in
    it, alternates and promisor metadata refuse ``unsupported_repository``. Other metadata
    (commit-graph, multi-pack-index, bitmaps, info) is not projected. Returns each projected
    file's relative path and stamp for the post-copy recheck.
    """
    projected: list[tuple[str, tuple[int, ...]]] = []
    files: list[tuple[str, os.stat_result]] = []
    packs: dict[str, set[str]] = {}
    stack = [(os.dup(objects_fd), "")]
    try:
        while stack:
            dir_fd, prefix = stack.pop()
            try:
                for name in sorted(os.listdir(dir_fd)):
                    clock.left()
                    rel = prefix + name
                    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                    kind = _kind(info)
                    if kind in ("symlink", "special"):
                        raise SnapshotRefused("unsupported_repository")
                    if rel in ("info/alternates", "info/http-alternates") or name.endswith(".promisor"):
                        raise SnapshotRefused("unsupported_repository")
                    if kind == "dir":
                        stack.append((_open_dir_at(dir_fd, name), rel + "/"))
                        continue
                    if (_LOOSE_DIR.fullmatch(prefix[:-1]) and "/" not in prefix[:-1]
                            and _LOOSE_NAME.fullmatch(name)):
                        files.append((rel, info))
                    elif prefix == "pack/" and (match := _PACK_NAME.fullmatch(name)):
                        packs.setdefault(name.rsplit(".", 1)[0], set()).add(match.group(1))
                        files.append((rel, info))
            finally:
                os.close(dir_fd)
    finally:
        for dir_fd, _ in stack:
            os.close(dir_fd)
    paired = {stem for stem, kinds in packs.items() if kinds == {"pack", "idx"}}
    dest.mkdir(mode=0o700, exist_ok=True)
    (dest / "pack").mkdir(mode=0o700, exist_ok=True)
    for rel, info in files:
        if rel.startswith("pack/") and rel[5:].rsplit(".", 1)[0] not in paired:
            continue
        parent, _, name = rel.rpartition("/")
        (dest / parent).mkdir(mode=0o700, exist_ok=True)
        parent_fd = _open_rel_dir(objects_fd, parent)
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if _stamp(current) != _stamp(info) or not stat.S_ISREG(current.st_mode):
                raise SnapshotRefused("source_changed")
            out = os.open(dest / rel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
            try:
                def sink(chunk: bytes) -> None:
                    view = memoryview(chunk)
                    while view:
                        view = view[os.write(out, view):]
                _read_content(parent_fd, name, current, "sha1", clock, cap=current.st_size, sink=sink)
            finally:
                os.close(out)
            after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if _stamp(after) != _stamp(info):
                raise SnapshotRefused("source_changed")
        finally:
            os.close(parent_fd)
        projected.append((rel, _stamp(info)))
    return tuple(projected)


def _recheck_projection(objects_fd: int, projected: Sequence[tuple[str, tuple[int, ...]]], clock: _Clock) -> None:
    for rel, stamp in projected:
        clock.left()
        parent_fd, info = _lstat_at(objects_fd, rel)
        if parent_fd is not None:
            os.close(parent_fd)
        if info is None or _stamp(info) != stamp:
            raise SnapshotRefused("source_changed")


def _build_git(spec: Snapshot, policy: SnapshotPolicy, clock: _Clock, root_fd: int, top: Path, masks: _Masks,
               source: _Source, box: Path, tree: Path) -> SnapshotHandle:
    fmt = source.object_format
    limits = policy.limits
    overlay_mode = spec.mode == "git_overlay"
    reader = box / "reader.git"
    _git(clock, ["init", "-q", "--bare", "--template=", f"--object-format={fmt}", str(reader)])
    # Git sees only a private projection of the pinned object store, never the hostile store.
    projected = _project_objects(source.objects_fd, reader / "objects", clock)
    (reader / "info").mkdir(exist_ok=True)
    (reader / "info" / "exclude").write_bytes(source.exclude)
    index_bytes = _meta_read(source.git_fd, "index", clock, _MAX_INDEX_BYTES)
    if index_bytes is None:
        if not overlay_mode:
            raise SnapshotRefused("dirty_source")
        index_bytes = b""
    source_index = box / "source.index"
    if index_bytes:
        source_index.write_bytes(index_bytes)
    index_digest = _sha256(index_bytes)

    def rg(args: Sequence[str], **kw: Any) -> bytes:
        return _git(clock, args, git_dir=reader, **kw)

    base = rg(["rev-parse", "--verify", "--end-of-options", f"{source.head_oid}^{{commit}}"],
              code="not_a_work_tree").decode().strip()
    rg(["rev-parse", "--verify", "--end-of-options", f"{base}^{{tree}}"], code="not_a_work_tree")

    base_entries: dict[str, tuple[str, str]] = {}
    for item in _split_z(rg(["ls-tree", "-r", "-z", "--full-tree", base])):
        match = re.fullmatch(r"(\d{6}) (\w+) ([0-9a-f]+)\t(.+)", item, re.DOTALL)
        if not match:
            raise SnapshotRefused("unsupported_repository")
        gmode, kind, oid, path = match.groups()
        if gmode == "160000" or kind == "commit" or _gitmodules(path):
            raise SnapshotRefused("unsupported_repository")
        if _unsafe_path(path) or gmode not in ("100644", "100755", "120000"):
            raise SnapshotRefused("unsupported_repository")
        base_entries[path] = (gmode, oid)
    if len(base_entries) > limits.max_entries:
        raise SnapshotRefused("too_large")

    nodes = _enumerate(root_fd, clock, limits, skip_top_git=True)
    _after_enumerate()
    # Git classifies paths in a private tree of placeholders carrying only the captured
    # .gitignore bytes; it never opens a file of the hostile work tree.
    classify = box / "classify"
    _classification_tree(root_fd, nodes, classify, clock, limits)

    def listing(args: Sequence[str]) -> list[str]:
        return _split_z(rg(["ls-files", "-z", *args], work_tree=str(classify), index_file=source_index,
                           cwd=classify))

    staged: dict[str, tuple[str, str]] = {}
    for item in listing(["--stage"]) if index_bytes else ():
        match = re.fullmatch(r"(\d{6}) ([0-9a-f]+) (\d)\t(.+)", item, re.DOTALL)
        if not match:
            raise SnapshotRefused("dirty_source")
        gmode, oid, stage, path = match.groups()
        if gmode == "160000" or _gitmodules(path):
            raise SnapshotRefused("unsupported_repository")
        if stage != "0":
            raise SnapshotRefused("dirty_source")
        if _unsafe_path(path):
            raise SnapshotRefused("unsafe_path")
        staged[path] = (gmode, oid)
    if not overlay_mode and staged != base_entries:
        raise SnapshotRefused("dirty_source")
    untracked = listing(["--others", "--exclude-standard"])
    for path in untracked:
        if path.endswith("/"):
            raise SnapshotRefused("nested_repository")
    untracked_set = frozenset(untracked)
    ignored_set = frozenset(listing(["--others", "--ignored", "--exclude-standard"]))
    tracked_set = frozenset(staged) | frozenset(base_entries)
    for path in untracked_set | ignored_set:
        if path not in nodes:
            raise SnapshotRefused("source_changed")

    inventory = _Inventory(limits)
    copies: list[_Copy] = []
    copied: set[str] = set()
    overlay_rows: list[tuple[str, str, str | None]] = []
    masked_tracked: list[str] = []
    for rel in sorted(nodes, key=str.encode):
        node = nodes[rel]
        if node.kind == "dir":
            continue
        tracked = rel in tracked_set
        if not tracked and (_unsafe_path(rel) or _gitmodules(rel)):
            raise SnapshotRefused("unsafe_path")
        if masks(rel):
            inventory.add(rel, "masked", kind=node.kind)
            if rel in base_entries:
                masked_tracked.append(rel)
            continue
        if node.kind == "special":
            inventory.add(rel, "special", kind="special")
            if tracked and not overlay_mode:
                raise SnapshotRefused("dirty_source")
            continue
        if rel in staged or rel in untracked_set:
            cls = "tracked" if tracked else "untracked"
            cap = inventory.remaining()
            if overlay_mode or cls == "untracked":
                cap = min(cap, limits.untracked_blob_max_bytes)
            if node.stamp[2] > cap and node.kind == "file":
                raise SnapshotRefused("too_large")
            content = _read_node(root_fd, node, fmt, clock, cap)
            if not overlay_mode and tracked and (content.mode, content.oid) != base_entries.get(rel):
                raise SnapshotRefused("dirty_source")
            inventory.add(rel, cls, kind=node.kind, mode=content.mode, oid=content.oid, size=content.size)
            copies.append(_Copy(rel, node.kind, content.size, content.sha256, content.mode == "100755"))
            copied.add(rel)
            if overlay_mode and base_entries.get(rel) != (content.mode, content.oid):
                kind = "symlink" if node.kind == "symlink" else (
                    "executable_file" if content.mode == "100755" else "file")
                overlay_rows.append((rel, kind, content.sha256))
        elif rel in ignored_set:
            if spec.mode == "full":
                if node.depth >= _FULL_DEPTH:
                    raise SnapshotRefused("too_large")
                content = _read_node(root_fd, node, fmt, clock, inventory.remaining())
                inventory.add(rel, "ignored", kind=node.kind, mode=content.mode, oid=content.oid,
                              size=content.size)
                copies.append(_Copy(rel, node.kind, content.size, content.sha256, content.mode == "100755"))
            else:
                inventory.add(rel, "omitted", kind=node.kind)
        elif tracked:
            # A B path git no longer lists (removed from the index): absent from the copy.
            if not overlay_mode:
                raise SnapshotRefused("dirty_source")
            inventory.add(rel, "omitted", kind=node.kind)
        else:
            raise SnapshotRefused("unsupported_repository")
    if not overlay_mode:
        for path in base_entries:
            if path not in copied and not masks(path):
                raise SnapshotRefused("dirty_source")
        if policy.result_kind == "patch" and any(
                inventory.entries[c.path]["class"] == "untracked" for c in copies):
            raise SnapshotRefused("untracked_input")
    else:
        # Every B or index path that the execution tree does not carry is a deletion entry.
        for path in sorted(tracked_set - copied, key=str.encode):
            if not masks(path):
                overlay_rows.append((path, "deleted", None))
    _after_inventory()

    # The execution repository: init, the working tree, B's objects, S, branch and index.
    _git(clock, ["init", "-q", "--template=", f"--object-format={fmt}", f"--initial-branch={EXECUTION_BRANCH}",
                 str(tree)])
    tree.chmod(0o700)
    ex_git = tree / ".git"
    _git(clock, ["config", "core.logAllRefUpdates", "false"], git_dir=ex_git)
    (ex_git / "info").mkdir(mode=0o700, exist_ok=True)
    (ex_git / "info" / "exclude").write_bytes(source.exclude)
    rows = _copy_entries(root_fd, tree, copies, clock)
    rg(["pack-objects", "--revs", "-q", "--delta-base-offset", str(ex_git / "objects" / "pack" / "pack")],
       data=f"{base}\n".encode())

    def eg(args: Sequence[str], **kw: Any) -> bytes:
        kw.setdefault("work_tree", str(tree))
        kw.setdefault("cwd", tree)
        return _git(clock, args, git_dir=ex_git, **kw)

    input_commit = base
    if not overlay_mode:
        inputs = [c for c in copies if inventory.entries[c.path]["class"] == "untracked" and c.kind != "dir"]
        if inputs:
            for item in inputs:
                if item.kind == "symlink":
                    data = os.fsencode(os.readlink(tree / item.path))
                else:
                    data = (tree / item.path).read_bytes()
                oid = eg(["hash-object", "-w", "--no-filters", "--stdin"], data=data).decode().strip()
                if oid != inventory.entries[item.path]["oid"]:
                    raise SnapshotRefused("source_changed")
            s_index = box / "input.index"
            eg(["read-tree", base], index_file=s_index)
            info = b"".join(
                f"{inventory.entries[i.path]['mode']} {inventory.entries[i.path]['oid']}\t".encode()
                + i.path.encode() + b"\x00" for i in inputs)
            eg(["update-index", "-z", "--index-info"], index_file=s_index, data=info)
            input_tree = eg(["write-tree"], index_file=s_index).decode().strip()
            input_commit = eg(["commit-tree", input_tree, "-p", base], extra_env=_SYNTHETIC_ENV,
                              data=b"laneexec: snapshot input baseline\n").decode().strip()
    eg(["update-ref", f"refs/heads/{EXECUTION_BRANCH}", input_commit])
    eg(["read-tree", input_commit])
    if masked_tracked:
        eg(["update-index", "-z", "--skip-worktree", "--stdin"],
           data=b"".join(p.encode() + b"\x00" for p in masked_tracked))
    if not overlay_mode:
        eg(["update-index", "-q", "--refresh"], allow_fail=True)
        if _split_z(eg(["diff-files", "--no-ext-diff", "--no-textconv", "-z", "--name-only"])):
            raise SnapshotRefused("source_changed")

    _after_copy(tree)
    # The source must not have moved while it was copied: metadata identities and pointer
    # stamps, HEAD, the index and info/exclude bytes, the projected object files and the walk.
    try:
        after = _inspect(clock, root_fd, top, box)
    except SnapshotRefused as refusal:
        if refusal.reason == "timeout":
            raise
        raise SnapshotRefused("source_changed") from None
    try:
        if after is None or after.identities != source.identities or after.pointers != source.pointers or (
                after.head_oid, after.head_ref, after.exclude) != (source.head_oid, source.head_ref, source.exclude):
            raise SnapshotRefused("source_changed")
        after_index = _meta_read(after.git_fd, "index", clock, _MAX_INDEX_BYTES) or b""
        _recheck_projection(after.objects_fd, projected, clock)
    except SnapshotRefused as refusal:
        if refusal.reason == "timeout":
            raise
        raise SnapshotRefused("source_changed") from None
    finally:
        if after is not None:
            after.close()
    if _sha256(after_index) != index_digest:
        raise SnapshotRefused("source_changed")
    _recheck_enumeration(root_fd, clock, limits, nodes, skip_top_git=True)

    overlay = None
    tree_rows = _walk_tree_rows(tree, clock)
    if overlay_mode:
        overlay = overlay_bytes(overlay_rows)
        tree_now = {row[0]: row for row in tree_rows}
        recheck_rows = []
        for path, kind, _ in overlay_rows:
            if kind == "deleted":
                if path in tree_now:
                    raise SnapshotRefused("source_changed")
                recheck_rows.append((path, kind, None))
            else:
                row = tree_now.get(path)
                recheck_rows.append((path, row[1], row[2]) if row else (path, "deleted", None))
        if overlay_bytes(recheck_rows) != overlay:
            raise SnapshotRefused("source_changed")
    if tree_manifest_sha256(tree_rows) != tree_manifest_sha256(rows):
        raise SnapshotRefused("source_changed")
    input_value = base if overlay_mode else input_commit
    return _handle(spec, tree, fmt, base, input_value, overlay, rows, inventory, masks)


# -- seed capture ---------------------------------------------------------------------------

def _strict_json(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate")
            out[key] = value
        return out

    def reject(_: str) -> Any:
        raise ValueError("constant")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject)


def _seed_open_dir(parent: int, name: str) -> int:
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        raise SeedRefused("not_regular_file") from None
    if stat.S_ISLNK(info.st_mode):
        raise SeedRefused("symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise SeedRefused("not_regular_file")
    try:
        return _open_dir_at(parent, name)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SeedRefused("symlink") from None
        raise SeedRefused("source_changed") from None


def _seed_root_fd(seed_root: Path) -> tuple[int, tuple[int, ...]]:
    """Open seed_root from ``/`` without following a symlink and check its trust rules."""
    parts = seed_root.parts
    if not seed_root.is_absolute() or any(p in (".", "..") for p in parts):
        raise SeedRefused("seed_root_untrusted")
    uid = os.geteuid()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        chain = []
        for index, part in enumerate(parts[1:]):
            info = os.fstat(fd)
            if info.st_mode & 0o022:
                raise SeedRefused("seed_root_untrusted")
            chain.append((info.st_dev, info.st_ino))
            child = _seed_open_dir(fd, part)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise SeedRefused("seed_root_untrusted")
        return fd, tuple(x for pair in chain for x in pair) + _stamp(info)[:2]
    except BaseException:
        os.close(fd)
        raise


def _seed_read(dir_fd: int, name: str, cap: int,
               check: Callable[[], None] = lambda: None) -> tuple[bytes, os.stat_result]:
    """Read at most ``cap`` + 1 bytes of a regular file opened without following a symlink."""
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise SeedRefused("not_regular_file") from None
    if stat.S_ISLNK(info.st_mode):
        raise SeedRefused("symlink")
    if not stat.S_ISREG(info.st_mode):
        raise SeedRefused("not_regular_file")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise SeedRefused("symlink") from None
        raise SeedRefused("source_changed") from None
    try:
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISREG(current.st_mode):
            raise SeedRefused("source_changed")
        chunks, total = [], 0
        while total <= cap:
            check()
            chunk = os.read(fd, min(_READ_CHUNK, cap + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks), current
    finally:
        os.close(fd)


@dataclass(frozen=True)
class _SeedFile:
    relpath: str
    sha256: str
    size: int
    executable: bool
    stamp: tuple[int, ...]


@dataclass(frozen=True)
class SeedHandle:
    """The verified, captured seed set of one launch (``x-seed.verify``).

    ``staging`` holds the captured bytes (directories 0700, files 0600); every later write uses
    them. An unseeded launch gets the empty handle (``manifest_sha256`` None, no entries).
    """

    request_id: str
    seed_root: Path | None
    staging: Path | None
    manifest: bytes | None = field(repr=False)
    entries: tuple[SeedEntry, ...]
    limits: SeedLimits
    _files: tuple[_SeedFile, ...] = field(repr=False)
    _identity: tuple[Any, ...] = field(repr=False)

    @property
    def manifest_sha256(self) -> str | None:
        return None if self.manifest is None else _sha256(self.manifest)

    def reference(self) -> dict[str, Any] | None:
        """The one ``launch.references`` entry, role ``config`` (``x-seed.binding``)."""
        if self.manifest is None:
            return None
        return {"role": "config", "sha256": self.manifest_sha256, "byte_length": len(self.manifest),
                "source": {"namespace": "declared_root", "root": "laneexec_seed",
                           "path": f"{self.request_id}.seed.json"}}

    def check_image_links(self, image_links: Sequence[str]) -> None:
        """``image_link_conflict`` when a seed entry sits at, under or above (as a file) a link path."""
        for image_path in image_links:
            link = image_path.lstrip("/")
            pieces = link.split("/")
            ancestors = {"/".join(pieces[:i]) for i in range(1, len(pieces))}
            for entry in self.entries:
                if entry.relpath == link or entry.relpath.startswith(link + "/") or entry.relpath in ancestors:
                    raise SeedRefused("image_link_conflict")

    def recheck(self, *, cancelled: Callable[[], bool] = lambda: False) -> None:
        """``recheck_before_start``: trust rules, identities and bytes; a change is ``source_changed``."""
        if self.manifest is None:
            return
        def check() -> None:
            if cancelled():
                raise ConstructionCancelled()

        try:
            identity, files = _capture_identity(self.seed_root, self.request_id, self.manifest, self.limits,
                                                self._files, check)
        except SeedRefused as refusal:
            # The trust rules keep their reason at recheck; any other difference from the
            # captured source (removed, retyped, swapped or rewritten) is a changed source.
            if refusal.reason == "seed_root_untrusted":
                raise
            raise SeedRefused("source_changed") from None
        if identity != self._identity or files != self._files:
            raise SeedRefused("source_changed")

    def provision(self, scratch: Path, image_links: Sequence[str] = ()) -> None:
        """Write ``scratch/`` new from the captured bytes, then the image links (local target).

        Every ancestor must be owned by root or this uid, not group- or other-writable and not a
        symlink, else ``scratch_unprovisioned``. ``scratch`` holds exactly the declared set plus
        the links and their parents afterwards.
        """
        self.check_image_links(image_links)
        scratch = Path(scratch)
        uid = os.geteuid()
        try:
            parent_fd = _open_root(scratch.parent)
        except OSError:
            raise SeedRefused("scratch_unprovisioned") from None
        try:
            probe = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                for part in scratch.parent.parts[1:]:
                    info = os.fstat(probe)
                    if info.st_uid not in (0, uid) or info.st_mode & 0o022:
                        raise SeedRefused("scratch_unprovisioned")
                    try:
                        child = _open_dir_at(probe, part)
                    except OSError:
                        raise SeedRefused("scratch_unprovisioned") from None
                    os.close(probe)
                    probe = child
                info = os.fstat(probe)
                if info.st_uid not in (0, uid) or info.st_mode & 0o022:
                    raise SeedRefused("scratch_unprovisioned")
                if os.fstat(probe)[:2] != os.fstat(parent_fd)[:2]:
                    raise SeedRefused("scratch_unprovisioned")
            finally:
                os.close(probe)
            try:
                os.mkdir(scratch.name, 0o700, dir_fd=parent_fd)
            except OSError:
                raise SeedRefused("scratch_unprovisioned") from None
            scratch_fd = _open_dir_at(parent_fd, scratch.name)
        finally:
            os.close(parent_fd)
        try:
            os.fchmod(scratch_fd, 0o700)
            expected: set[str] = set()
            for item in self._files:
                data = (self.staging / item.relpath).read_bytes() if self.staging else b""
                if len(data) != item.size or _sha256(data) != item.sha256:
                    raise SeedRefused("source_changed")
                mode = 0o700 if item.executable else 0o600
                _write_under(scratch_fd, item.relpath, data, mode, expected)
            for image_path in image_links:
                link = image_path.lstrip("/")
                pieces = link.split("/")
                fd = os.dup(scratch_fd)
                try:
                    for index, part in enumerate(pieces[:-1]):
                        try:
                            os.mkdir(part, 0o700, dir_fd=fd)
                        except FileExistsError:
                            pass
                        expected.add("/".join(pieces[:index + 1]))
                        child = _open_dir_at(fd, part)
                        os.close(fd)
                        fd = child
                    os.symlink(image_path, pieces[-1], dir_fd=fd)
                    expected.add(link)
                finally:
                    os.close(fd)
            present = set(_list_all(scratch_fd, ""))
            if present != expected:
                raise SeedRefused("scratch_unprovisioned")
        finally:
            os.close(scratch_fd)

    def discard(self) -> None:
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)


def _write_under(root_fd: int, relpath: str, data: bytes, mode: int, expected: set[str]) -> None:
    pieces = relpath.split("/")
    fd = os.dup(root_fd)
    try:
        for index, part in enumerate(pieces[:-1]):
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            expected.add("/".join(pieces[:index + 1]))
            child = _open_dir_at(fd, part)
            os.close(fd)
            fd = child
        out = os.open(pieces[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode,
                      dir_fd=fd)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(out, view):]
            os.fchmod(out, mode)
        finally:
            os.close(out)
        expected.add(relpath)
    finally:
        os.close(fd)


def _list_all(fd: int, prefix: str) -> list[str]:
    found = []
    for name in os.listdir(fd):
        rel = prefix + name
        found.append(rel)
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = _open_dir_at(fd, name)
            try:
                found.extend(_list_all(child, rel + "/"))
            finally:
                os.close(child)
    return found


def _check_manifest(raw: bytes, seed: SeedDeclaration, request_id: str, limits: SeedLimits) -> tuple[SeedEntry, ...]:
    if _sha256(raw) != seed.manifest_sha256:
        raise SeedRefused("digest_mismatch")
    try:
        value = _strict_json(raw)
        canonical = _jcs(value)
    except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
        raise SeedRefused("manifest_invalid") from None
    if canonical != raw:
        raise SeedRefused("manifest_invalid")
    # An entry over the effective entry cap is too_large, even where the schema ceiling is the cap.
    if isinstance(value, dict) and isinstance(value.get("entries"), list) and any(
            isinstance(e, dict) and type(e.get("size")) is int and e["size"] > limits.entry_max_bytes
            for e in value["entries"]):
        raise SeedRefused("too_large")
    if not validate_launch_message("SeedManifest", value):
        raise SeedRefused("manifest_invalid")
    if value["request_id"] != request_id:
        raise SeedRefused("manifest_invalid")
    entries = tuple(SeedEntry.from_json(e) for e in value["entries"])
    for entry in entries:
        parts = entry.relpath.split("/")
        if (len(entry.relpath) > 1024 or any(len(p) > 255 or p in ("", ".", "..") for p in parts)
                or entry.relpath.startswith("/")
                or any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in entry.relpath)):
            raise SeedRefused("manifest_invalid")
    keys = [e.relpath.encode("utf-8") for e in entries]
    if keys != sorted(keys):
        raise SeedRefused("manifest_invalid")
    if len(entries) != seed.entries or sum(e.size for e in entries) != seed.total_bytes:
        raise SeedRefused("manifest_invalid")
    paths = [e.relpath for e in entries]
    if any(unicodedata.normalize("NFC", p) != p for p in paths) or len(set(paths)) != len(paths):
        raise SeedRefused("unsafe_path")
    prefixes = {"/".join(p.split("/")[:i]) for p in paths for i in range(1, p.count("/") + 1)}
    if any(p in prefixes for p in paths):
        raise SeedRefused("unsafe_path")
    if any(e.size > limits.entry_max_bytes for e in entries):
        raise SeedRefused("too_large")
    return entries


def _capture_identity(seed_root: Path | None, request_id: str, manifest: bytes | None, limits: SeedLimits,
                      files: Sequence[_SeedFile], check: Callable[[], None],
                      sink: Callable[[str, bytes], None] | None = None) -> tuple[tuple[Any, ...], tuple[_SeedFile, ...]]:
    """Open the seed source once more along the trusted chain; return identities and files."""
    if seed_root is None:
        raise SeedRefused("seed_root_untrusted")
    uid = os.geteuid()
    root_fd, root_identity = _seed_root_fd(Path(seed_root))
    try:
        raw, info = _seed_read(root_fd, f"{request_id}.seed.json", limits.manifest_max_bytes, check)
        if info.st_uid != uid or info.st_mode & 0o022:
            raise SeedRefused("seed_root_untrusted")
        if manifest is not None and raw != manifest:
            raise SeedRefused("source_changed")
        entry_fd = _seed_open_dir(root_fd, request_id)
        try:
            entry_identity = _stamp(os.fstat(entry_fd))[:2]
            captured = []
            for item in files:
                check()
                pieces = item.relpath.split("/")
                fd = os.dup(entry_fd)
                try:
                    for part in pieces[:-1]:
                        child = _seed_open_dir(fd, part)
                        os.close(fd)
                        fd = child
                    data, file_info = _seed_read(fd, pieces[-1], item.size, check)
                finally:
                    os.close(fd)
                if len(data) != item.size or _sha256(data) != item.sha256:
                    raise SeedRefused("digest_mismatch" if sink is not None else "source_changed")
                if sink is not None:
                    sink(item.relpath, data)
                captured.append(_SeedFile(item.relpath, item.sha256, item.size, item.executable,
                                          _stamp(file_info)[:2]))
        finally:
            os.close(entry_fd)
        return (root_identity, _stamp(info)[:2], entry_identity), tuple(captured)
    finally:
        os.close(root_fd)


def build_seed(seed: SeedDeclaration | None, *, request_id: str, seed_root: Path | str | None,
               limits: SeedLimits, staging: Path | str, cancelled: Callable[[], bool]) -> SeedHandle:
    """Verify the declared seed set and capture it into the new private directory ``staging``.

    Only declared relpaths are opened, after the manifest checks pass. A refusal deletes the
    staged capture. ``staging`` must not exist and its parent must be trusted, as for
    :func:`build_snapshot`. Capture shares the attempt's snapshot budget (:func:`snapshot_budget`;
    the default budget outside one), else ``timeout``.
    """
    if seed is None:
        if cancelled():
            raise ConstructionCancelled()
        return SeedHandle(request_id, None, None, None, (), limits, (), ())
    clock = _Clock(_budget_end(DEFAULT_SNAPSHOT_BUDGET_S), cancelled)

    def check() -> None:
        try:
            clock.left()
        except _Timeout:
            raise SeedRefused("timeout") from None

    for name in ("max_entries", "entry_max_bytes", "max_bytes", "manifest_max_bytes"):
        value = getattr(limits, name)
        if type(value) is not int or value < 0 or value > getattr(_SEED_CEILINGS, name):
            raise SeedRefused("too_large")
    if request_id.endswith(".seed.json") or "/" in request_id or request_id in ("", ".", ".."):
        raise SeedRefused("unsafe_path")
    if seed.entries > limits.max_entries or seed.total_bytes > limits.max_bytes:
        raise SeedRefused("too_large")
    if seed_root is None:
        raise SeedRefused("seed_root_untrusted")
    check()
    root_fd, _ = _seed_root_fd(Path(seed_root))
    try:
        raw, info = _seed_read(root_fd, f"{request_id}.seed.json", limits.manifest_max_bytes, check)
    finally:
        os.close(root_fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise SeedRefused("seed_root_untrusted")
    if len(raw) > limits.manifest_max_bytes:
        raise SeedRefused("too_large")
    entries = _check_manifest(raw, seed, request_id, limits)
    staging_dir = _private_child(Path(staging), "seed_staging_invalid")
    try:
        staging_fd = _open_root(staging_dir)
    except OSError:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise ValueError("seed_staging_invalid") from None
    planned = tuple(_SeedFile(e.relpath, e.sha256, e.size, bool(e.executable), ()) for e in entries)

    def sink(relpath: str, data: bytes) -> None:
        check()
        _write_under(staging_fd, relpath, data, 0o600, set())

    try:
        identity, files = _capture_identity(Path(seed_root), request_id, raw, limits, planned,
                                            check, sink)
        check()
    except BaseException:
        os.close(staging_fd)
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    os.close(staging_fd)
    return SeedHandle(request_id, Path(seed_root), staging_dir, raw, entries, limits, files, identity)
