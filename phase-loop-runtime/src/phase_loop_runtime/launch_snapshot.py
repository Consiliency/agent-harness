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

from dataclasses import dataclass, field
import errno
import hashlib
import json
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


# -- small helpers --------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jcs(value: Any) -> bytes:
    return rfc8785.dumps(value)


class _Clock:
    def __init__(self, budget_s: float, cancelled: Callable[[], bool], deadline: float | None = None):
        self.end = time.monotonic() + budget_s if deadline is None else deadline
        self.cancelled = cancelled

    def left(self) -> float:
        if self.cancelled():
            raise ConstructionCancelled()
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise _Timeout()
        return remaining


def _segment_ok(name: str) -> bool:
    return bool(name) and name not in (".", "..") and "/" not in name and "\x00" not in name


def _unsafe_path(path: str) -> bool:
    """The writer path rules: NFC, no control character or backslash, no ``.git`` component."""
    if not isinstance(path, str) or not path or path.startswith("/") or len(path) > 4096:
        return True
    if any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in path):
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


def _open_root(path: Path) -> int:
    """Open an absolute directory one component at a time from ``/``, following no symlink."""
    parts = Path(path).parts
    if not parts or parts[0] != "/":
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


@dataclass
class _Read:
    kind: str  # missing | file | symlink | dir | special
    mode: str | None = None
    size: int = 0
    oid: str | None = None
    sha256: str | None = None
    target: bytes | None = None
    data: bytes | None = field(default=None, repr=False)
    stamp: tuple[int, ...] | None = None


def _read_entry(root_fd: int, rel: str, object_format: str, *, max_bytes: int | None = None,
                keep: bool = False) -> _Read:
    """What ``rel`` below ``root_fd`` holds now, read through no-follow descriptors."""
    segments = rel.split("/")
    name = segments.pop()
    fd = os.dup(root_fd)
    try:
        for part in segments:
            try:
                child = _open_dir_at(fd, part)
            except OSError as error:
                if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
                    return _Read("missing")
                raise
            os.close(fd)
            fd = child
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return _Read("missing")
        stamp = _stamp(info)
        if stat.S_ISDIR(info.st_mode):
            return _Read("dir", stamp=stamp)
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(name, dir_fd=fd)
            target_bytes = os.fsencode(target)
            h = _blob_hasher(object_format, len(target_bytes))
            h.update(target_bytes)
            return _Read("symlink", "120000", len(target_bytes), h.hexdigest(), _sha256(target_bytes),
                         target_bytes, None, stamp)
        if not stat.S_ISREG(info.st_mode):
            return _Read("special", stamp=stamp)
        size = info.st_size
        if max_bytes is not None and size > max_bytes:
            raise SnapshotRefused("too_large")
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        try:
            current = os.fstat(file_fd)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISREG(current.st_mode):
                raise SnapshotRefused("source_changed")
            h = _blob_hasher(object_format, size)
            s = hashlib.sha256()
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(file_fd, min(_READ_CHUNK, size + 1 - total) or 1)
                if not chunk:
                    break
                total += len(chunk)
                if total > size:
                    raise SnapshotRefused("source_changed")
                h.update(chunk)
                s.update(chunk)
                if keep:
                    chunks.append(chunk)
            if total != size:
                raise SnapshotRefused("source_changed")
        finally:
            os.close(file_fd)
        return _Read("file", _git_mode(info), size, h.hexdigest(), s.hexdigest(), None,
                     b"".join(chunks) if keep else None, stamp)
    finally:
        os.close(fd)


def _list_dir_at(root_fd: int, rel: str) -> list[str]:
    fd = os.dup(root_fd)
    try:
        for part in rel.split("/") if rel else ():
            child = _open_dir_at(fd, part)
            os.close(fd)
            fd = child
        return sorted(os.listdir(fd))
    finally:
        os.close(fd)


def _read_small(path: Path, cap: int = _SMALL_FILE) -> bytes | None:
    """A small git metadata file of the source, refusing a symlink at its last component."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError:
        raise SnapshotRefused("unsupported_repository") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SnapshotRefused("unsupported_repository")
        data = b""
        while len(data) <= cap:
            chunk = os.read(fd, cap + 1 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > cap:
            raise SnapshotRefused("too_large")
        return data
    finally:
        os.close(fd)


# -- sanitized git --------------------------------------------------------------------------

def _git(clock: _Clock, args: Sequence[str], *, git_dir: Path | None = None,
         work_tree: Path | None = None, index_file: Path | None = None, cwd: Path = Path("/"),
         data: bytes = b"", extra_env: Mapping[str, str] | None = None, allow_fail: bool = False,
         code: str = "unsupported_repository") -> bytes:
    env = dict(_GIT_ENV)
    if git_dir is not None:
        env["GIT_DIR"] = str(git_dir)
    if work_tree is not None:
        env["GIT_WORK_TREE"] = str(work_tree)
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
        rc, out, _ = _artifacts.run_process(tuple(argv), cwd=cwd, env=env, data=data, cap=_GIT_OUTPUT_CAP,
                                            bound=_artifacts.Bound(clock.end, clock.cancelled))
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

@dataclass(frozen=True)
class _Source:
    top: Path
    git_dir: Path
    common_dir: Path
    linked: bool
    object_format: str
    head_ref: str | None
    head_oid: str
    exclude: bytes


def _real_dir(path: Path) -> Path:
    try:
        real = Path(os.path.realpath(path))
        if not stat.S_ISDIR(os.stat(real).st_mode):
            raise SnapshotRefused("not_a_work_tree")
        return real
    except OSError:
        raise SnapshotRefused("not_a_work_tree") from None


def _locate(top: Path) -> tuple[Path, Path, bool] | None:
    """``(git_dir, common_dir, linked)`` of work tree ``top``, or None when ``top`` has no ``.git``."""
    dot_git = top / ".git"
    try:
        info = os.lstat(dot_git)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(info.st_mode):
        git_dir, linked = _real_dir(dot_git), False
    elif stat.S_ISREG(info.st_mode):
        text = (_read_small(dot_git, 4096) or b"").decode("utf-8", "replace")
        match = re.fullmatch(r"gitdir: (.+?)\r?\n?", text)
        if not match:
            raise SnapshotRefused("not_a_work_tree")
        git_dir, linked = _real_dir(top / match.group(1)), True
        back = (_read_small(git_dir / "gitdir", 4096) or b"").decode("utf-8", "replace").strip()
        if not back or os.path.realpath(git_dir / back) != os.path.realpath(dot_git):
            raise SnapshotRefused("not_a_work_tree")
    else:
        raise SnapshotRefused("not_a_work_tree")
    common_text = (_read_small(git_dir / "commondir", 4096) or b"").decode("utf-8", "replace").strip()
    common_dir = _real_dir(git_dir / common_text) if common_text else git_dir
    if linked and common_dir == git_dir:
        raise SnapshotRefused("not_a_work_tree")
    return git_dir, common_dir, linked


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


def _read_ref(git_dir: Path, common_dir: Path, name: str, object_format: str) -> str | None:
    base = git_dir if re.match(r"refs/(bisect|rewritten|worktree)/", name) else common_dir
    try:
        fd = _open_root(base)
    except OSError:
        raise SnapshotRefused("unsupported_repository") from None
    try:
        entry = _read_entry(fd, name, object_format, max_bytes=4096, keep=True)
    finally:
        os.close(fd)
    if entry.kind == "file":
        text = (entry.data or b"").decode("ascii", "replace").strip()
        if not _is_oid(object_format, text):
            raise SnapshotRefused("unsupported_repository")
        return text
    if entry.kind != "missing":
        raise SnapshotRefused("unsupported_repository")
    packed = _read_small(common_dir / "packed-refs", 256 * 1024 * 1024)
    for line in (packed or b"").decode("utf-8", "replace").split("\n"):
        if not line or line.startswith(("#", "^")):
            continue
        oid, _, ref = line.partition(" ")
        if ref == name:
            if not _is_oid(object_format, oid):
                raise SnapshotRefused("unsupported_repository")
            return oid
    return None


def _inspect(clock: _Clock, top: Path, box: Path) -> _Source | None:
    located = _locate(top)
    if located is None:
        return None
    git_dir, common_dir, linked = located
    for path in (common_dir / "objects/info/alternates", common_dir / "objects/info/http-alternates",
                 common_dir / "shallow", git_dir / "shallow", common_dir / "reftable"):
        if os.path.lexists(path):
            raise SnapshotRefused("unsupported_repository")
    pack_dir = common_dir / "objects" / "pack"
    if pack_dir.is_dir() and any(n.endswith(".promisor") for n in os.listdir(pack_dir)):
        raise SnapshotRefused("unsupported_repository")
    if any(n.startswith("sharedindex.") for n in os.listdir(git_dir)):
        raise SnapshotRefused("unsupported_repository")
    config = _parse_config(clock, _read_small(common_dir / "config") or b"", box)
    version = config.get("core.repositoryformatversion", "0")
    if version not in ("0", "1"):
        raise SnapshotRefused("unsupported_repository")
    if config.get("core.bare", "false").lower() == "true" or "core.worktree" in config:
        raise SnapshotRefused("unsupported_repository")
    object_format = config.get("extensions.objectformat", "sha1").lower()
    if object_format not in _OBJECT_FORMATS:
        raise SnapshotRefused("unsupported_repository")
    for key, value in config.items():
        if key == "extensions.partialclone" or (re.fullmatch(r"remote\..*\.promisor", key) and value.lower() == "true"):
            raise SnapshotRefused("unsupported_repository")
        if key == "extensions.refstorage" and value.lower() != "files":
            raise SnapshotRefused("unsupported_repository")
        if key.startswith("extensions.") and version == "1" and key not in (
                "extensions.objectformat", "extensions.worktreeconfig", "extensions.refstorage"):
            raise SnapshotRefused("unsupported_repository")
    head = (_read_small(git_dir / "HEAD", 4096) or b"").decode("utf-8", "replace").strip()
    if _is_oid(object_format, head):
        head_ref, head_oid = None, head
    else:
        match = re.fullmatch(r"ref: (refs/heads/[^\x00-\x20\x7f~^:?*\[\\]+)", head)
        if not match or ".." in match.group(1) or "@{" in match.group(1):
            raise SnapshotRefused("not_a_work_tree")
        oid = _read_ref(git_dir, common_dir, match.group(1), object_format)
        if oid is None:
            raise SnapshotRefused("not_a_work_tree")
        head_ref, head_oid = match.group(1), oid
    exclude = _read_small(common_dir / "info" / "exclude") or b""
    return _Source(top, git_dir, common_dir, linked, object_format, head_ref, head_oid, exclude)


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


def _walk_tree_rows(root: Path) -> list[list[str]]:
    """Recompute the tree manifest of a private execution tree (``.git`` excluded)."""
    rows: list[tuple[str, str, str]] = []

    def walk(fd: int, prefix: str) -> None:
        for name in sorted(os.listdir(fd)):
            if not prefix and name == ".git":
                continue
            rel = prefix + name
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = _open_dir_at(fd, name)
                try:
                    walk(child, rel + "/")
                finally:
                    os.close(child)
            elif stat.S_ISLNK(info.st_mode):
                rows.append((rel, "symlink", _sha256(os.fsencode(os.readlink(name, dir_fd=fd)))))
            elif stat.S_ISREG(info.st_mode):
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                h = hashlib.sha256()
                try:
                    while chunk := os.read(file_fd, _READ_CHUNK):
                        h.update(chunk)
                finally:
                    os.close(file_fd)
                rows.append((rel, "executable_file" if info.st_mode & 0o111 else "file", h.hexdigest()))
            else:
                raise SnapshotRefused("source_changed")

    fd = _open_root(root)
    try:
        walk(fd, "")
    finally:
        os.close(fd)
    return tree_manifest_rows(rows)


# -- the snapshot handle --------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotHandle:
    """One constructed execution tree and its frozen identity.

    ``envelope_base_commit`` is the envelope ``workspace_state.base_commit`` (S, B in
    ``git_overlay``, null without a work tree). ``descriptor_bytes`` are the RFC 8785 snapshot
    descriptor, the envelope's single baseline reference. ``inventory`` lists every source path
    with its class; nothing in it is file content.
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


#: Test seam: called after the copy and before the recheck (barrier for mid-copy mutations).
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
        self.stamps: dict[str, tuple[int, ...]] = {}
        self.bytes = 0

    def add(self, path: str, cls: str, *, kind: str, mode: str | None = None, oid: str | None = None,
            size: int = 0, stamp: tuple[int, ...] | None = None) -> None:
        if len(self.entries) >= self.limits.max_entries:
            raise SnapshotRefused("too_large")
        if cls in ("tracked", "untracked", "ignored"):
            self.bytes += size
            if self.bytes > self.limits.max_bytes:
                raise SnapshotRefused("too_large")
        self.entries[path] = {"path": path, "class": cls, "type": kind, "mode": mode, "oid": oid}
        if stamp is not None:
            self.stamps[path] = stamp

    def sorted(self) -> list[dict[str, Any]]:
        return [self.entries[p] for p in sorted(self.entries, key=str.encode)]

    def counts(self) -> InventoryCounts:
        tally = dict.fromkeys(("tracked", "untracked", "ignored", "omitted", "masked", "special"), 0)
        for entry in self.entries.values():
            tally[entry["class"]] += 1
        return InventoryCounts(**tally)


@dataclass
class _Copy:
    path: str
    kind: str  # file | symlink | dir
    oid: str | None
    executable: bool
    sha256: str | None


def build_snapshot(spec: Snapshot, *, policy: SnapshotPolicy, scratch: Path | str,
                   cancelled: Callable[[], bool], deadline: float | None = None) -> SnapshotHandle:
    """Build the execution tree of ``spec`` under the new private directory ``scratch``.

    ``scratch`` must not exist and its parent must; it is created 0700 and receives the execution
    tree at ``scratch/tree`` (private intermediate repositories are removed before return). A
    refusal deletes ``scratch``. ``deadline`` (monotonic) overrides ``policy.budget_s``.
    """
    if spec.mode not in ("git", "git_overlay", "full") or not policy.permits(spec.mode):
        raise SnapshotRefused("mode_unpermitted")
    clock = _Clock(policy.budget_s, cancelled, deadline)
    base_dir = Path(scratch)
    try:
        base_dir.mkdir(mode=0o700)
    except OSError:
        raise ValueError("snapshot_scratch_invalid") from None
    box = base_dir / "work"
    box.mkdir(mode=0o700)
    tree = base_dir / "tree"
    try:
        return _build(spec, policy, clock, box, tree)
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


def _build(spec: Snapshot, policy: SnapshotPolicy, clock: _Clock, box: Path, tree: Path) -> SnapshotHandle:
    top = Path(spec.root)
    if not top.is_absolute() or os.path.realpath(top) != str(top):
        raise SnapshotRefused("not_a_work_tree")
    try:
        root_fd = _open_root(top)
    except OSError:
        raise SnapshotRefused("not_a_work_tree") from None
    try:
        if spec.cwd not in (".", "") and _read_entry(root_fd, spec.cwd, "sha1").kind != "dir":
            raise SnapshotRefused("unsafe_path")
        masks = _Masks(root_fd, spec, policy.secrets)
        source = _inspect(clock, top, box)
        if source is None:
            if spec.mode != "full":
                raise SnapshotRefused("not_a_work_tree")
            return _build_plain(spec, policy, clock, root_fd, masks, tree)
        return _build_git(spec, policy, clock, root_fd, masks, source, box, tree)
    finally:
        os.close(root_fd)


def _inventory_ignored(spec_mode: str, root_fd: int, item: str, inventory: _Inventory, masks: _Masks,
                       object_format: str | None, clock: _Clock, copies: list[_Copy],
                       class_name: str = "ignored") -> None:
    """Classify an ignored listing item: ``omitted`` in git modes, walked in full mode."""
    path = item.rstrip("/")
    is_dir = item.endswith("/")
    if masks(path):
        inventory.add(path, "masked", kind="dir" if is_dir else "file")
        return
    if spec_mode != "full":
        inventory.add(path, "omitted", kind="dir" if is_dir else "file")
        return

    def walk(rel: str, depth: int) -> None:
        clock.left()
        if _unsafe_path(rel) or _gitmodules(rel):
            raise SnapshotRefused("unsafe_path")
        if masks(rel):
            inventory.add(rel, "masked", kind="file")
            return
        entry = _read_entry(root_fd, rel, object_format or "sha1")
        if entry.kind == "dir":
            if depth > _FULL_DEPTH:
                raise SnapshotRefused("too_large")
            names = _list_dir_at(root_fd, rel)
            if any(n.lower() == ".git" for n in names):
                raise SnapshotRefused("nested_repository")
            if not names:
                inventory.add(rel, class_name, kind="dir", stamp=entry.stamp)
                copies.append(_Copy(rel, "dir", None, False, None))
                return
            for name in names:
                walk(f"{rel}/{name}", depth + 1)
            return
        _classify_read(rel, entry, class_name, inventory, copies)

    walk(path, 0)


def _classify_read(rel: str, entry: _Read, cls: str, inventory: _Inventory, copies: list[_Copy]) -> None:
    if entry.kind in ("file", "symlink"):
        inventory.add(rel, cls, kind=entry.kind, mode=entry.mode, oid=entry.oid, size=entry.size,
                      stamp=entry.stamp)
        copies.append(_Copy(rel, entry.kind, entry.oid, entry.mode == "100755", entry.sha256))
    elif entry.kind == "missing":
        raise SnapshotRefused("source_changed")
    else:
        inventory.add(rel, "special", kind=entry.kind, stamp=entry.stamp)


def _build_plain(spec: Snapshot, policy: SnapshotPolicy, clock: _Clock, root_fd: int, masks: _Masks,
                 tree: Path) -> SnapshotHandle:
    """Full mode on a root that is not a git work tree: the whole tree, no ``.git``."""
    inventory = _Inventory(policy.limits)
    copies: list[_Copy] = []
    names = _list_dir_at(root_fd, "")
    if any(n.lower() == ".git" for n in names):
        raise SnapshotRefused("nested_repository")
    for name in names:
        _inventory_ignored("full", root_fd, name + ("/" if _read_entry(root_fd, name, "sha1").kind == "dir" else ""),
                           inventory, masks, None, clock, copies, class_name="untracked")
    _make_tree(tree)
    rows = _copy_entries(root_fd, tree, copies, clock, "sha1")
    _after_copy(tree)
    _recheck_stamps(root_fd, inventory)
    content = tree_manifest_sha256(rows)
    if tree_manifest_sha256(_walk_tree_rows(tree)) != content:
        raise SnapshotRefused("source_changed")
    return _handle(spec, tree, None, None, None, None, rows, inventory, masks)


def _make_tree(tree: Path) -> None:
    tree.mkdir(mode=0o700)


def _copy_entries(root_fd: int, tree: Path, copies: Sequence[_Copy], clock: _Clock,
                  object_format: str) -> list[list[str]]:
    """Copy each entry into the new tree, re-verifying the bytes against the inventoried id."""
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
                entry = _read_entry(root_fd, item.path, object_format, keep=True)
                if entry.kind != item.kind or (item.oid is not None and entry.oid != item.oid) or (
                        item.sha256 is not None and entry.sha256 != item.sha256):
                    raise SnapshotRefused("source_changed")
                if item.kind == "symlink":
                    os.symlink(os.fsdecode(entry.target or b""), name, dir_fd=fd)
                    rows.append((item.path, "symlink", entry.sha256 or ""))
                    continue
                mode = 0o700 if entry.mode == "100755" else 0o600
                out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                              mode, dir_fd=fd)
                try:
                    view = memoryview(entry.data or b"")
                    while view:
                        view = view[os.write(out, view):]
                    os.fchmod(out, mode)
                finally:
                    os.close(out)
                rows.append((item.path, "executable_file" if mode == 0o700 else "file", entry.sha256 or ""))
            finally:
                os.close(fd)
    finally:
        os.close(tree_fd)
    return tree_manifest_rows(rows)


def _recheck_stamps(root_fd: int, inventory: _Inventory) -> None:
    for path, stamp in inventory.stamps.items():
        if _stat_entry(root_fd, path).stamp != stamp:
            raise SnapshotRefused("source_changed")


def _stat_entry(root_fd: int, rel: str) -> _Read:
    segments = rel.split("/")
    name = segments.pop()
    fd = os.dup(root_fd)
    try:
        for part in segments:
            try:
                child = _open_dir_at(fd, part)
            except OSError:
                return _Read("missing")
            os.close(fd)
            fd = child
        try:
            return _Read("stat", stamp=_stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)))
        except FileNotFoundError:
            return _Read("missing")
    finally:
        os.close(fd)


def _handle(spec: Snapshot, tree: Path, object_format: str | None, base: str | None, input_commit: str | None,
            overlay: bytes | None, rows: list[list[str]], inventory: _Inventory, masks: _Masks) -> SnapshotHandle:
    entries = inventory.sorted()
    return SnapshotHandle(
        tree=tree, mode=spec.mode, cwd=spec.cwd, object_format=object_format, base_commit=base,
        input_commit=input_commit, overlay=overlay, content_sha256=tree_manifest_sha256(rows),
        inventory=tuple(MappingProxyType(e) for e in entries), inventory_sha256=_sha256(_jcs(entries)),
        masks_sha256=masks.sha256, counts=inventory.counts(), byte_total=inventory.bytes,
        tree_rows=tuple(tuple(r) for r in rows))


def _build_git(spec: Snapshot, policy: SnapshotPolicy, clock: _Clock, root_fd: int, masks: _Masks,
               source: _Source, box: Path, tree: Path) -> SnapshotHandle:
    fmt = source.object_format
    top = source.top
    limits = policy.limits
    reader = box / "reader.git"
    _git(clock, ["init", "-q", "--bare", "--template=", f"--object-format={fmt}", str(reader)])
    (reader / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (reader / "objects" / "info" / "alternates").write_bytes(os.fsencode(str(source.common_dir / "objects")) + b"\n")
    (reader / "info").mkdir(exist_ok=True)
    (reader / "info" / "exclude").write_bytes(source.exclude)
    index_bytes = _read_small(source.git_dir / "index", _MAX_INDEX_BYTES)
    if index_bytes is None:
        if spec.mode == "git_overlay":
            index_bytes = b""
        else:
            raise SnapshotRefused("dirty_source")
    source_index = box / "source.index"
    if index_bytes:
        source_index.write_bytes(index_bytes)
    index_digest = _sha256(index_bytes)

    def rg(args: Sequence[str], **kw: Any) -> bytes:
        return _git(clock, args, git_dir=reader, **kw)

    def listing(args: Sequence[str]) -> list[str]:
        return _split_z(rg(["ls-files", "-z", *args], work_tree=top, index_file=source_index, cwd=top))

    base = rg(["rev-parse", "--verify", "--end-of-options", f"{source.head_oid}^{{commit}}"],
              code="not_a_work_tree").decode().strip()
    rg(["rev-parse", "--verify", "--end-of-options", f"{base}^{{tree}}"],
                   code="not_a_work_tree").decode().strip()

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

    inventory = _Inventory(limits)
    copies: list[_Copy] = []
    overlay_rows: list[tuple[str, str, str | None]] = []
    masked_tracked: list[str] = []

    if spec.mode == "git_overlay":
        listed = listing(["--cached", "--others", "--exclude-standard"]) if index_bytes else \
            listing(["--others", "--exclude-standard"])
        untracked_listing = listing(["--others", "--exclude-standard"])
        candidates = sorted(set(listed) | set(base_entries) | set(staged), key=str.encode)
        for path in candidates:
            clock.left()
            if path.endswith("/"):
                raise SnapshotRefused("nested_repository")
            if _unsafe_path(path) or _gitmodules(path):
                raise SnapshotRefused("unsafe_path")
            in_base = path in base_entries
            if masks(path):
                inventory.add(path, "masked", kind="file")
                if in_base:
                    masked_tracked.append(path)
                continue
            entry = _read_entry(root_fd, path, fmt)
            cls = "tracked" if (in_base or path in staged) else "untracked"
            if entry.kind == "missing":
                if in_base or path in staged:
                    if in_base:
                        overlay_rows.append((path, "deleted", None))
                    continue
                raise SnapshotRefused("source_changed")
            if entry.kind == "dir":
                if os.path.lexists(top / path / ".git"):
                    raise SnapshotRefused("nested_repository")
                raise SnapshotRefused("unsupported_repository")
            if entry.kind == "special":
                inventory.add(path, "special", kind="special", stamp=entry.stamp)
                if in_base:
                    overlay_rows.append((path, "deleted", None))
                continue
            differs = not in_base or base_entries[path] != (entry.mode, entry.oid)
            if differs and entry.size > limits.untracked_blob_max_bytes:
                raise SnapshotRefused("too_large")
            _classify_read(path, entry, cls, inventory, copies)
            if differs:
                kind = "symlink" if entry.kind == "symlink" else (
                    "executable_file" if entry.mode == "100755" else "file")
                overlay_rows.append((path, kind, entry.sha256))
        for item in listing(["--others", "--ignored", "--exclude-standard", "--directory"]):
            _inventory_ignored("git", root_fd, item, inventory, masks, fmt, clock, copies)
        untracked = untracked_listing
    else:
        if staged != base_entries:
            raise SnapshotRefused("dirty_source")
        dirty = False
        for path in sorted(base_entries, key=str.encode):
            clock.left()
            gmode, oid = base_entries[path]
            if masks(path):
                inventory.add(path, "masked", kind="symlink" if gmode == "120000" else "file", mode=gmode, oid=oid)
                masked_tracked.append(path)
                continue
            entry = _read_entry(root_fd, path, fmt)
            if entry.kind not in ("file", "symlink") or (entry.mode, entry.oid) != (gmode, oid):
                dirty = True
                continue
            _classify_read(path, entry, "tracked", inventory, copies)
        if dirty:
            raise SnapshotRefused("dirty_source")
        untracked = listing(["--others", "--exclude-standard"])
        for path in untracked:
            clock.left()
            if path.endswith("/"):
                raise SnapshotRefused("nested_repository")
            if _unsafe_path(path) or _gitmodules(path):
                raise SnapshotRefused("unsafe_path")
            if masks(path):
                inventory.add(path, "masked", kind="file")
                continue
            entry = _read_entry(root_fd, path, fmt, max_bytes=limits.untracked_blob_max_bytes)
            if entry.kind == "dir" and os.path.lexists(top / path / ".git"):
                raise SnapshotRefused("nested_repository")
            _classify_read(path, entry, "untracked", inventory, copies)
        if policy.result_kind == "patch" and any(
                inventory.entries[c.path]["class"] == "untracked" for c in copies):
            raise SnapshotRefused("untracked_input")
        for item in listing(["--others", "--ignored", "--exclude-standard", "--directory"]):
            _inventory_ignored(spec.mode, root_fd, item, inventory, masks, fmt, clock, copies)

    # The execution repository: init, the working tree, B's objects, S, branch and index.
    _git(clock, ["init", "-q", "--template=", f"--object-format={fmt}", f"--initial-branch={EXECUTION_BRANCH}",
                 str(tree)])
    tree.chmod(0o700)
    ex_git = tree / ".git"
    _git(clock, ["config", "core.logAllRefUpdates", "false"], git_dir=ex_git)
    (ex_git / "info").mkdir(mode=0o700, exist_ok=True)
    (ex_git / "info" / "exclude").write_bytes(source.exclude)
    rows = _copy_entries(root_fd, tree, copies, clock, fmt)
    rg(["pack-objects", "--revs", "-q", "--delta-base-offset", str(ex_git / "objects" / "pack" / "pack")],
       data=f"{base}\n".encode())

    def eg(args: Sequence[str], **kw: Any) -> bytes:
        kw.setdefault("work_tree", tree)
        kw.setdefault("cwd", tree)
        return _git(clock, args, git_dir=ex_git, **kw)

    input_commit = base
    if spec.mode != "git_overlay":
        inputs = [c for c in copies if inventory.entries[c.path]["class"] == "untracked" and c.kind != "dir"]
        if inputs:
            for item in inputs:
                if item.kind == "symlink":
                    data = os.fsencode(os.readlink(tree / item.path))
                else:
                    data = (tree / item.path).read_bytes()
                oid = eg(["hash-object", "-w", "--no-filters", "--stdin"], data=data).decode().strip()
                if oid != item.oid:
                    raise SnapshotRefused("source_changed")
            s_index = box / "input.index"
            eg(["read-tree", base], index_file=s_index)
            info = b"".join(f"{inventory.entries[i.path]['mode']} {i.oid}\t".encode() + i.path.encode() + b"\x00"
                            for i in inputs)
            eg(["update-index", "-z", "--index-info"], index_file=s_index, data=info)
            input_tree = eg(["write-tree"], index_file=s_index).decode().strip()
            input_commit = eg(["commit-tree", input_tree, "-p", base], extra_env=_SYNTHETIC_ENV,
                              data=b"laneexec: snapshot input baseline\n").decode().strip()
    eg(["update-ref", f"refs/heads/{EXECUTION_BRANCH}", input_commit])
    eg(["read-tree", input_commit])
    if masked_tracked:
        eg(["update-index", "-z", "--skip-worktree", "--stdin"],
           data=b"".join(p.encode() + b"\x00" for p in masked_tracked))
    if spec.mode != "git_overlay":
        eg(["update-index", "-q", "--refresh"], allow_fail=True)
        if _split_z(eg(["diff-files", "-z", "--name-only"])):
            raise SnapshotRefused("source_changed")

    _after_copy(tree)
    # The source must not have moved while it was copied.
    after = _inspect(clock, top, box)
    if after is None or (after.head_oid, after.head_ref) != (source.head_oid, source.head_ref):
        raise SnapshotRefused("source_changed")
    after_index = _read_small(source.git_dir / "index", _MAX_INDEX_BYTES) or b""
    if _sha256(after_index) != index_digest:
        raise SnapshotRefused("source_changed")
    if listing(["--others", "--exclude-standard"]) != untracked:
        raise SnapshotRefused("source_changed")
    _recheck_stamps(root_fd, inventory)

    overlay = None
    if spec.mode == "git_overlay":
        overlay = overlay_bytes(overlay_rows)
        tree_now = {row[0]: row for row in _walk_tree_rows(tree)}
        recheck_rows = []
        for path, kind, digest in overlay_rows:
            if kind == "deleted":
                if path in tree_now:
                    raise SnapshotRefused("source_changed")
                recheck_rows.append((path, kind, None))
            else:
                row = tree_now.get(path)
                recheck_rows.append((path, row[1], row[2]) if row else (path, "deleted", None))
        if overlay_bytes(recheck_rows) != overlay:
            raise SnapshotRefused("source_changed")
    if tree_manifest_sha256(_walk_tree_rows(tree)) != tree_manifest_sha256(rows):
        raise SnapshotRefused("source_changed")
    input_value = base if spec.mode == "git_overlay" else input_commit
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


def _seed_read(dir_fd: int, name: str, cap: int) -> tuple[bytes, os.stat_result]:
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
        identity, files = _capture_identity(self.seed_root, self.request_id, self.manifest, self.limits,
                                            self._files, cancelled)
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
                      files: Sequence[_SeedFile], cancelled: Callable[[], bool],
                      sink: Callable[[str, bytes], None] | None = None) -> tuple[tuple[Any, ...], tuple[_SeedFile, ...]]:
    """Open the seed source once more along the trusted chain; return identities and files."""
    if seed_root is None:
        raise SeedRefused("seed_root_untrusted")
    uid = os.geteuid()
    root_fd, root_identity = _seed_root_fd(Path(seed_root))
    try:
        raw, info = _seed_read(root_fd, f"{request_id}.seed.json", limits.manifest_max_bytes)
        if info.st_uid != uid or info.st_mode & 0o022:
            raise SeedRefused("seed_root_untrusted")
        if manifest is not None and raw != manifest:
            raise SeedRefused("source_changed")
        entry_fd = _seed_open_dir(root_fd, request_id)
        try:
            entry_identity = _stamp(os.fstat(entry_fd))[:2]
            captured = []
            for item in files:
                if cancelled():
                    raise ConstructionCancelled()
                pieces = item.relpath.split("/")
                fd = os.dup(entry_fd)
                try:
                    for part in pieces[:-1]:
                        child = _seed_open_dir(fd, part)
                        os.close(fd)
                        fd = child
                    data, file_info = _seed_read(fd, pieces[-1], item.size)
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
               limits: SeedLimits, staging: Path | str, cancelled: Callable[[], bool],
               deadline: float | None = None) -> SeedHandle:
    """Verify the declared seed set and capture it into the new private directory ``staging``.

    Only declared relpaths are opened, after the manifest checks pass. A refusal deletes the
    staged capture. ``deadline`` (monotonic) is the attempt's snapshot budget, else ``timeout``.
    """
    if seed is None:
        return SeedHandle(request_id, None, None, None, (), limits, (), ())
    clock = _Clock(0, cancelled, deadline if deadline is not None else float("inf"))

    def check() -> bool:
        try:
            clock.left()
        except _Timeout:
            raise SeedRefused("timeout") from None
        return False

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
        raw, info = _seed_read(root_fd, f"{request_id}.seed.json", limits.manifest_max_bytes)
    finally:
        os.close(root_fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise SeedRefused("seed_root_untrusted")
    if len(raw) > limits.manifest_max_bytes:
        raise SeedRefused("too_large")
    entries = _check_manifest(raw, seed, request_id, limits)
    staging_dir = Path(staging)
    try:
        staging_dir.mkdir(mode=0o700)
        staging_fd = _open_root(staging_dir)
    except OSError:
        raise SeedRefused("scratch_unprovisioned") from None
    planned = tuple(_SeedFile(e.relpath, e.sha256, e.size, bool(e.executable), ()) for e in entries)

    def sink(relpath: str, data: bytes) -> None:
        check()
        _write_under(staging_fd, relpath, data, 0o600, set())

    try:
        identity, files = _capture_identity(Path(seed_root), request_id, raw, limits, planned,
                                            lambda: check(), sink)
    except BaseException:
        os.close(staging_fd)
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    os.close(staging_fd)
    return SeedHandle(request_id, Path(seed_root), staging_dir, raw, entries, limits, files, identity)
