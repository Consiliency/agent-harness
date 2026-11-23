"""HOLD, the availability floor: the held-image candidate search (AGYFRESH §2.4, §2.5).

When a seat's selected agy (the *subject*) cannot be used for a subject-side reason,
``agy_qualification.admit_seat`` asks this module for a different image already on the host
that passes an existing qualification predicate (AGYFRESH §2.3). This module finds and
reads candidates; the predicate is the caller's, passed in as a callable, so this module
reads no qualification store entry by itself.

Discovery is bounded and ordered (§2.4): the candidate list is built without reading any
image, then walked in one total order with separate read budgets for candidates whose
version is authenticated and for candidates whose version is only hinted. Every access is
descriptor-relative from an anchor opened one checked component at a time (§2.5): no
candidate path is ever passed to a path-following call. A candidate is read only by
``gemini_heartbeat.VerifiedImage.from_fd`` on a descriptor from that traversal, so at most one
image is open at a time and the read stays within the streaming reader's memory bound.

There is no process memo: every hold rebuilds the list and walks it, so a newer eligible
candidate that appears between two holds wins the second (AGYFRESH §6.2, option "no memo").

Standard library plus ``gemini_heartbeat``; outside ``ROUTE_CORE``. The cache writers
(``retain``, pruning, corrupt-file removal, ``clear_held``, AGYFRESH §2.8) take the store
lock and work descriptor-relative from the same anchor the reader uses.
"""
from __future__ import annotations

import errno
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import threading
from types import MappingProxyType
from typing import Callable, Iterable, Literal, NamedTuple

from . import agy_provenance
from . import gemini_heartbeat as gh

#: The vendor stores searched for held images: ``<store>/<x.y.z>-<16 hex>/agy``.
VENDOR_STORES: tuple[Path, ...] = (Path("/opt/consiliency/operational-clis/agy"),)
#: The harness cache directory under ``Store.host_dir``: ``held/<image sha256>``.
HELD_DIRNAME = "held"
#: Images the cache keeps (written by SL-4).
HELD_KEEP = 2
#: Names listed per directory; a directory with more is skipped as a source.
MAX_DIR_ENTRIES = 1024
#: Vendor directories taken per version, lexicographically first.
MAX_DIRS_PER_VERSION = 2
#: ``qualified-*.json`` store entries read for version hints, lexicographically first.
MAX_HINT_FILES = 64
#: Size bound of one hint file.
MAX_HINT_BYTES = 256 * 1024
#: Image reads reserved for candidates whose version is authenticated.
AUTH_READS = 3
#: Image reads for candidates whose version is only hinted.
HINT_READS = 2

#: Which seat routes a held admission can run on (AGYFRESH §2.6; plan B6). The one place
#: that says so: SL-3 sets ``jailed`` in the PR that makes it true. Status reads it.
ROUTE_COVERAGE = MappingProxyType({"seat_profile": True, "heartbeat": True, "jailed": False})

# Anchors are walked from here. Production walks from "/"; tests substitute an isolated root
# (as ``seat_subject._PIN_WALK_ROOT`` does), because a world-writable /tmp is never an anchor.
_WALK_ROOT = Path("/")
# Native Windows has none of these flags (nor ``dir_fd``): ``None`` makes every open fail closed.
if os.name != "nt":
    _DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    _FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
else:
    _DIR_FLAGS = _FILE_FLAGS = None
_RELEASE = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
_VENDOR_NAME = re.compile(_RELEASE + r"-[0-9a-f]{16}")
_DIGEST_NAME = re.compile(r"[0-9a-f]{64}")
_HINT_NAME = re.compile(r"qualified-[0-9a-f]{64}\.json")
_VERSION = re.compile(_RELEASE)
_TEMP_NAME = re.compile(r"\.[0-9a-f]{64}\.[0-9a-f]{16}\.tmp")
_CHUNK_BYTES = 1024 * 1024
_CANCELLED = "review_operation_cancelled"  # agy_qualification.CANCELLED
_LOG = logging.getLogger(__name__)

# Candidate loading in one process is serialized (AGYFRESH §1.2). Re-entrant, so a nested
# admission on the same thread waits for nothing rather than for itself.
_LOCK = threading.RLock()


class HeldCandidate(NamedTuple):
    """One candidate, before any image is read (AGYFRESH §2.4)."""

    version: tuple[int, int, int]
    authenticated: bool          # True: a catalog member's or a MAC-valid provenance version
    origin: Literal["cache", "vendor"]
    name: str                    # cache: the digest; vendor: "<x.y.z>-<16 hex>"


CacheVersion = Callable[[str, "tuple[int, int, int] | None"], "tuple[int, int, int] | None"]
Predicate = Callable[[gh.VerifiedImage, HeldCandidate], "tuple[str | None, str] | None"]


class HeldImage(NamedTuple):
    """The admitted candidate: its sealed image and what the predicate decided."""

    image: gh.VerifiedImage
    help_sha256: str | None
    admission_class: str
    candidate: HeldCandidate


# --------------------------------------------------------------------- config (§2.7)

def hold_enabled() -> bool:
    """``[agy] hold`` in the USER board config; on by default. Any error disables the hold."""
    from .advisor_board.config import load_agy_hold
    try:
        return load_agy_hold() is True
    except Exception:  # noqa: BLE001 - any config failure disables the hold
        return False


def hold_deny() -> frozenset[str] | None:
    """``[agy] hold_deny``: digests never admitted as a hold. ``None`` when the config cannot
    be read, which the caller treats as a disabled hold."""
    from .advisor_board.config import load_agy_hold_deny
    try:
        return frozenset(load_agy_hold_deny())
    except Exception:  # noqa: BLE001 - any config failure disables the hold
        return None


def retain(image, store, *, cache_version: "CacheVersion | None" = None) -> None:
    """Keep an admitted image in the harness cache, ``held/<sha256>`` (AGYFRESH §2.8).

    Best effort: it never waits for the store lock (busy means retention is skipped this
    time) and never raises. If the file exists it returns. Otherwise the sealed image is
    streamed to a 0600 temp file in the 0700 ``held/``, ``fsync``ed, re-hashed and renamed,
    and the cache is pruned to ``HELD_KEEP`` images by authenticated version, always keeping
    the one just retained. ``cache_version`` is the authenticated version of a cached digest
    (``candidates`` takes the same callable); without it only catalog members have one. The
    image stays the caller's.
    """
    try:
        _retain(image, store, cache_version)
    except Exception:  # noqa: BLE001 - retention is best effort and never fails an admission
        pass
    return None


# ------------------------------------------------------- anchored opens (§2.5)

def _owners() -> frozenset[int]:
    return frozenset({0, os.geteuid()})


def _require_safe(info, kind) -> None:
    if not kind(info.st_mode) or info.st_uid not in _owners() or info.st_mode & 0o022:
        raise OSError(errno.EPERM, "agy hold: unsafe filesystem entry")


def _open_dir_at(name: str, parent: int) -> int:
    """A child directory of ``parent``: no symlink, owned by root or the euid, not group- or
    other-writable."""
    if name in {"", ".", ".."} or "/" in name:
        raise OSError(errno.EINVAL, "agy hold: invalid path component")
    fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
    try:
        _require_safe(os.fstat(fd), stat.S_ISDIR)
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_anchor(path: Path) -> int:
    """Open ``path`` from the walk root one component at a time (AGYFRESH §2.5 "Anchor").
    The readers' anchor: a vendor store, or ``Store.host_dir`` for the cache."""
    return _walk(path)


def _walk(path: Path) -> int:
    """The component walk both anchors use: no symlink at any step, each directory owned by
    root or the euid and not group- or other-writable."""
    target = Path(os.path.abspath(path))
    parts = target.relative_to(_WALK_ROOT).parts
    fd = os.open(_WALK_ROOT, _DIR_FLAGS)
    try:
        _require_safe(os.fstat(fd), stat.S_ISDIR)
        for name in parts:
            child = _open_dir_at(name, fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _list_names(dir_fd: int) -> list[str] | None:
    """The names in a directory, or ``None`` above ``MAX_DIR_ENTRIES`` (source skipped)."""
    names = []
    with os.scandir(dir_fd) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > MAX_DIR_ENTRIES:
                return None
    return names


def _open_candidate(anchor: int, candidate: HeldCandidate) -> tuple[int, int, os.stat_result, str]:
    """``(directory fd, file fd, pre-read fstat, file name)`` of one candidate; the caller
    closes both descriptors. Any unsafe or symlinked step raises ``OSError``."""
    if candidate.origin == "vendor":
        directory, name = _open_dir_at(candidate.name, anchor), "agy"
    else:
        directory, name = os.dup(anchor), candidate.name
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=directory)
        try:
            info = os.fstat(fd)
            _require_safe(info, stat.S_ISREG)
            return directory, fd, info, name
        except BaseException:
            os.close(fd)
            raise
    except BaseException:
        os.close(directory)
        raise


def _unchanged(fd: int, directory: int, name: str, before: os.stat_result) -> bool:
    """AGYFRESH §2.5 "Read", option (b): the descriptor is as it was, and the name still
    names that inode. It detects a replacement observable now, nothing more; the sealed
    digest is the integrity control."""
    after = os.fstat(fd)
    if ((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)):
        return False
    try:
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(named.st_mode) and (named.st_dev, named.st_ino) == (before.st_dev, before.st_ino)


# ----------------------------------------------------------- the candidate list (§2.4)

def parse_version(text) -> tuple[int, int, int] | None:
    """``"x.y.z"`` as a tuple, or ``None`` for anything else."""
    if not isinstance(text, str) or not _VERSION.fullmatch(text):
        return None
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def _hint_versions(store_anchor: int | None) -> set[tuple[int, int, int]]:
    """``payload.release_version`` of at most ``MAX_HINT_FILES`` ``qualified-*.json`` entries,
    read WITHOUT MAC verification: hints, never authority."""
    found: set[tuple[int, int, int]] = set()
    if store_anchor is None:
        return found
    try:
        names = _list_names(store_anchor)
    except OSError:
        return found
    if names is None:
        return found
    for name in sorted(item for item in names if _HINT_NAME.fullmatch(item))[:MAX_HINT_FILES]:
        try:
            fd = os.open(name, _FILE_FLAGS, dir_fd=store_anchor)
        except OSError:
            continue
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_HINT_BYTES:
                continue
            data = os.read(fd, MAX_HINT_BYTES + 1)
            if len(data) > MAX_HINT_BYTES:  # it grew after the stat: skip it unparsed
                continue
            document = json.loads(data)
            version = parse_version(document.get("payload", {}).get("release_version"))
        except (OSError, ValueError, AttributeError, RecursionError):
            continue
        finally:
            os.close(fd)
        if version is not None:
            found.add(version)
    return found


def _sort_key(candidate: HeldCandidate):
    # version descending; authenticated before hinted; cache before vendor; name ascending.
    return (tuple(-part for part in candidate.version), not candidate.authenticated,
            candidate.origin != "cache", candidate.name)


def candidates(*, members: Iterable[dict], cache: int | None, store_anchor: int | None,
               cache_version: CacheVersion,
               vendor: Iterable[tuple[int, int]]) -> list[tuple[HeldCandidate, int]]:
    """The ordered candidate list, ``(candidate, anchor fd)``; no image is read.

    ``cache`` is the opened ``held/`` directory (or ``None``), ``store_anchor`` the opened
    ``Store.host_dir`` the hints are read from (or ``None``), ``vendor`` the opened vendor
    stores as ``(index, fd)``. ``cache_version(digest, member_version)`` is the authenticated
    version of a cached digest given its catalog member's version (``None`` when it is not a
    member), or ``None`` when the name is not a candidate (no authenticated version, a
    ``failed`` entry, or a denied digest).
    """
    member_versions = {}
    for member in members:
        version = parse_version(member.get("release_version"))
        if version is not None:
            member_versions[member.get("image_sha256")] = version
    catalog_versions = set(member_versions.values())
    listed: list[tuple[HeldCandidate, int, int]] = []
    if cache is not None:
        try:
            names = _list_names(cache)
        except OSError:
            names = None
        for name in sorted(names or ()):
            if not _DIGEST_NAME.fullmatch(name):
                continue
            version = cache_version(name, member_versions.get(name))
            if version is not None:
                listed.append((HeldCandidate(version, True, "cache", name), cache, -1))
    pending: list[tuple[str, tuple[int, int, int], int, int]] = []
    for index, anchor in vendor:
        try:
            names = _list_names(anchor)
        except OSError:
            continue
        per_version: dict[tuple[int, int, int], list[str]] = {}
        for name in sorted(names or ()):
            if _VENDOR_NAME.fullmatch(name):
                version = parse_version(name.rsplit("-", 1)[0])
                per_version.setdefault(version, []).append(name)
        for version, items in per_version.items():
            for name in items[:MAX_DIRS_PER_VERSION]:
                pending.append((name, version, anchor, index))
    hinted = set()
    if any(version not in catalog_versions for _name, version, _anchor, _index in pending):
        hinted = _hint_versions(store_anchor) - catalog_versions
    for name, version, anchor, index in pending:
        if version in catalog_versions:
            listed.append((HeldCandidate(version, True, "vendor", name), anchor, index))
        elif version in hinted:
            listed.append((HeldCandidate(version, False, "vendor", name), anchor, index))
    listed.sort(key=lambda item: (_sort_key(item[0]), item[2]))
    return [(candidate, anchor) for candidate, anchor, _index in listed]


# ----------------------------------------------------------------------- the walk (§2.4)

def select(ordered: list[tuple[HeldCandidate, int]], *, predicate: Predicate, excluded: Iterable[str] = (), cancelled: Callable[[], bool] = lambda: False) -> HeldImage | None:
    """Walk ``ordered`` and return the first candidate ``predicate`` admits, or ``None``.

    Reading an authenticated candidate spends one of ``AUTH_READS``, a hinted one one of
    ``HINT_READS``; a candidate whose class is exhausted is skipped. A file already examined
    (same ``st_dev``, ``st_ino``) or a cached digest already rejected is skipped without
    spending. ``predicate(image, candidate)`` returns ``(help_sha256, admission_class)`` or
    ``None``; what it raises propagates, with the candidate closed. A candidate-local error
    (an unsafe, symlinked, replaced, oversized or unreadable file) skips that candidate.

    ``cancelled()`` is checked before each candidate is opened, after it is streamed, before
    a winner is handed off and before a miss is returned: once it is true the walk raises
    ``review_operation_cancelled`` with every image it opened closed.
    """
    budget = {True: AUTH_READS, False: HINT_READS}
    rejected = set(excluded)
    examined = set()
    for candidate, anchor in ordered:
        if budget[candidate.authenticated] <= 0:
            continue
        if candidate.origin == "cache" and candidate.name in rejected:
            continue
        if cancelled():
            raise ValueError(_CANCELLED)
        try:
            directory, fd, before, name = _open_candidate(anchor, candidate)
        except OSError:
            continue
        image = None
        try:
            identity = (before.st_dev, before.st_ino)
            if identity in examined:
                continue
            examined.add(identity)
            # The bound is read at call time (H4); an oversized candidate is a local skip.
            if before.st_size > agy_provenance.MAX_MEMBER_BYTES:
                continue
            budget[candidate.authenticated] -= 1
            try:
                image = gh.VerifiedImage.from_fd(fd)
            except (OSError, ValueError, gh.AgyCanaryEvidenceError):
                continue
            if not _unchanged(fd, directory, name, before):
                image.close()
                image = None
                continue
            if cancelled():  # after streaming: a cancelled walk never judges what it read
                image.close()
                image = None
                raise ValueError(_CANCELLED)
        except OSError:
            if image is not None:
                image.close()
                image = None
            continue
        finally:
            os.close(fd)
            os.close(directory)
        if image.sha256 in rejected or (candidate.origin == "cache" and image.sha256 != candidate.name):
            # Already rejected, or a cache file whose content is not the digest it is named by.
            image.close()
            continue
        try:
            decision = predicate(image, candidate)
        except BaseException:
            image.close()
            raise
        if decision is None:
            rejected.add(image.sha256)
            image.close()
            continue
        if cancelled():  # never hand a winner off after cancellation
            image.close()
            raise ValueError(_CANCELLED)
        help_sha256, admission_class = decision
        return HeldImage(image, help_sha256, admission_class, candidate)
    if cancelled():  # nor report a miss: a cancelled hold is a cancellation, not a refusal
        raise ValueError(_CANCELLED)
    return None


def search(*, members: Iterable[dict], store_dir: Path | None, cache_version: CacheVersion,
           predicate: Predicate, excluded: Iterable[str] = (), cancelled: Callable[[], bool] = lambda: False) -> HeldImage | None:
    """One hold: open the anchors, build the ordered list, walk it, close every descriptor.

    ``store_dir`` is ``Store.host_dir`` when ``Store.status() == "ok"``, else ``None`` (no
    cache and no hints). Serialized per process by the module lock.
    """
    with _LOCK:
        opened: list[int] = []
        try:
            store_anchor = cache = None
            if store_dir is not None:
                try:
                    store_anchor = open_anchor(store_dir)
                    opened.append(store_anchor)
                except (OSError, ValueError):
                    store_anchor = None
                if store_anchor is not None:
                    try:
                        cache = _open_dir_at(HELD_DIRNAME, store_anchor)
                        opened.append(cache)
                    except OSError:
                        cache = None
            vendor = []
            for index, root in enumerate(VENDOR_STORES):
                try:
                    anchor = open_anchor(root)
                except (OSError, ValueError):
                    continue
                opened.append(anchor)
                vendor.append((index, anchor))
            ordered = candidates(members=members, cache=cache, store_anchor=store_anchor,
                                 cache_version=cache_version, vendor=vendor)
            return select(ordered, predicate=predicate, excluded=excluded, cancelled=cancelled)
        finally:
            for fd in opened:
                os.close(fd)


# ------------------------------------------------------------- the harness cache (§2.8)

def _open_held(anchor: int) -> int:
    """``held/`` under the verified store anchor, for writing: created 0700 if absent; an
    existing one must be a directory (no symlink) owned by the euid with mode exactly 0700,
    as the cache requires. Anything else refuses the write, which ``retain`` swallows."""
    try:
        os.mkdir(HELD_DIRNAME, 0o700, dir_fd=anchor)
    except FileExistsError:
        pass
    fd = os.open(HELD_DIRNAME, _DIR_FLAGS, dir_fd=anchor)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise OSError(errno.EPERM, "agy hold: the cache directory is not the euid's 0700")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _fd_sha256(fd: int, buffer: bytearray) -> str:
    """The digest of a descriptor's content, read by offset through ``buffer`` (no allocation
    per chunk)."""
    digest, offset, view = sha256(), 0, memoryview(buffer)
    while count := os.preadv(fd, [buffer], offset):
        digest.update(view[:count])
        offset += count
    return digest.hexdigest()


def _unlink_if_same(directory: int, name: str, identity: tuple[int, int]) -> bool:
    """Unlink ``name`` only if it still names the inode judged (``(st_dev, st_ino)``), never
    following a symlink. A name replaced since the judgement is left alone."""
    try:
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if (named.st_dev, named.st_ino) != identity:
        return False
    os.unlink(name, dir_fd=directory)
    return True


def _write_image(image, held: int, name: str, buffer: bytearray) -> None:
    """Stream the sealed image to a temp file, ``fsync``, re-hash what was written, rename."""
    temporary = f".{name}.{secrets.token_hex(8)}.tmp"
    out = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                  0o600, dir_fd=held)
    done = False
    try:
        info = os.fstat(out)
        identity = (info.st_dev, info.st_ino)
        os.fchmod(out, 0o600)
        digest, offset, view = sha256(), 0, memoryview(buffer)
        while count := os.preadv(image.fd, [buffer], offset):
            offset += count
            if offset > agy_provenance.MAX_MEMBER_BYTES:
                raise OSError(errno.EFBIG, "agy hold: image over the member bound")
            digest.update(view[:count])
            written = 0
            while written < count:
                step = os.write(out, view[written:count])
                if step <= 0:
                    raise OSError(errno.EIO, "agy hold: short cache write")
                written += step
        if digest.hexdigest() != name:
            raise OSError(errno.EIO, "agy hold: the image is not the digest it is named by")
        os.fsync(out)
        if _fd_sha256(out, buffer) != name:
            raise OSError(errno.EIO, "agy hold: the cache file is not what was written")
        os.rename(temporary, name, src_dir_fd=held, dst_dir_fd=held)
        done = True
        os.fsync(held)
    finally:
        os.close(out)
        if not done:
            _unlink_if_same(held, temporary, identity)


def _readable_by_the_hold(info: os.stat_result) -> bool:
    """The reader's file rules for a cache candidate (``_open_candidate``): a regular file
    owned by root or the euid, not group- or other-writable, within the member bound."""
    return (stat.S_ISREG(info.st_mode) and info.st_uid in _owners() and not info.st_mode & 0o022
            and info.st_size <= agy_provenance.MAX_MEMBER_BYTES)


def _prune(held: int, names: list[str], keep: str, cache_version: "CacheVersion | None",
           buffer: bytearray) -> None:
    """Keep ``HELD_KEEP`` images the hold can use: ``keep`` (the one just retained) and the
    highest authenticated versions among the rest, ranked only among files the reader would
    admit. A file the reader would refuse (unsafe owner or mode, over the bound, content not
    the digest it is named by) and a file with no authenticated version (or a ``failed``
    entry, or a denied digest) are unlinked, never kept over a usable one. A temp file is left
    only by an interrupted retain (the store lock is held) and is unlinked. Symlinks and
    other entries are neither followed nor unlinked and take no slot."""
    members = {}
    for member in gh.catalog_members():
        version = parse_version(member.get("release_version"))
        if version is not None:
            members[member.get("image_sha256")] = version
    usable = []
    for name in sorted(names):
        is_temp = bool(_TEMP_NAME.fullmatch(name))
        if not (is_temp or _DIGEST_NAME.fullmatch(name)) or name == keep:
            continue
        try:
            fd = os.open(name, _FILE_FLAGS, dir_fd=held)
        except FileNotFoundError:
            continue  # vanished
        except OSError:
            # Not openable. A symlink (the no-follow open refuses it) is left alone; a regular
            # file the reader cannot open either (mode 000, say) is removed, inode-checked.
            try:
                info = os.stat(name, dir_fd=held, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                _discard(held, name, (info.st_dev, info.st_ino))
            continue
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                continue  # a directory named like a digest is not a cache file: left alone
            identity = (info.st_dev, info.st_ino)
            valid = (not is_temp and _readable_by_the_hold(info)
                     and _fd_sha256(fd, buffer) == name)
        finally:
            os.close(fd)
        version = None
        if valid:
            version = (cache_version(name, members.get(name)) if cache_version is not None
                       else members.get(name))
        if version is None:
            _discard(held, name, identity)
            continue
        usable.append((version, name, identity))
    ranked = sorted(usable, key=lambda item: (tuple(-part for part in item[0]), item[1]))
    for _version, name, identity in ranked[HELD_KEEP - 1:]:
        _discard(held, name, identity)


def _discard(held: int, name: str, identity: tuple[int, int]) -> None:
    """Prune one file, inode-checked. A removal that fails is reported (a warning naming the
    file), never left silently; retention itself still never fails the admission."""
    try:
        _unlink_if_same(held, name, identity)
    except OSError as exc:
        _LOG.warning("agy hold: could not remove the cache file held/%s: %s", name, exc)


def _ancestry_safe(path: Path) -> bool:
    """Whether every EXISTING component of ``path`` passes the anchor walk's checks (no
    symlink, owned by root or the euid, not group- or other-writable). A missing component
    ends the walk: the rest would be created by ``Store.create``."""
    target = Path(os.path.abspath(path))
    try:
        parts = target.relative_to(_WALK_ROOT).parts
        fd = os.open(_WALK_ROOT, _DIR_FLAGS)
    except (OSError, ValueError):
        return False
    try:
        _require_safe(os.fstat(fd), stat.S_ISDIR)
        for name in parts:
            try:
                child = _open_dir_at(name, fd)
            except FileNotFoundError:
                return True
            os.close(fd)
            fd = child
    except OSError:
        return False
    finally:
        os.close(fd)
    return True


def _open_cache_store(store) -> int:
    """The writers' anchor: ``Store.host_dir`` by the same walk as the readers' anchor, and
    also owned by the euid with mode 0700, the store's own invariant. Stricter than reading,
    because the cache writers create, rename and unlink in it. The store lock is opened
    relative to this descriptor, so the lock and the cache share one verified directory."""
    fd = _walk(store.host_dir)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise OSError(errno.EPERM, "agy hold: the store directory is not the euid's 0700")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _reachable(path: Path) -> bool:
    """Whether ``path`` lies below the walk root, so an anchor walk can reach it at all."""
    return Path(os.path.abspath(path)).is_relative_to(_WALK_ROOT)


def _retain(image, store, cache_version) -> None:
    name = getattr(image, "sha256", None)
    if not isinstance(name, str) or not _DIGEST_NAME.fullmatch(name) or image.fd is None:
        return
    if not _reachable(store.host_dir):
        return  # no anchor can reach it: nothing is created, written or pruned
    if store.status() == "absent":
        # Validate what exists before creating anything: an unsafe ancestor creates nothing.
        if not _ancestry_safe(store.host_dir):
            return
        store.create()
    if store.status() != "ok":
        return
    anchor = _open_cache_store(store)  # before any lock or mutation; a refusal touches nothing
    try:
        with store.try_lock(dir_fd=anchor) as locked:
            if not locked:
                return  # busy: retention is skipped this time, never waited for
            held = _open_held(anchor)
            try:
                try:
                    os.stat(name, dir_fd=held, follow_symlinks=False)
                    return  # already there (whatever it is: a symlink is not followed)
                except FileNotFoundError:
                    pass
                names = _list_names(held)
                if names is None or len(names) + 1 > MAX_DIR_ENTRIES:
                    # No room: publishing (its temp file included) would take held/ past
                    # MAX_DIR_ENTRIES, which the reader refuses to list. Nothing is added.
                    return
                buffer = bytearray(_CHUNK_BYTES)
                _write_image(image, held, name, buffer)
                _prune(held, names, name, cache_version, buffer)
            finally:
                os.close(held)
    finally:
        os.close(anchor)


class HeldClear(NamedTuple):
    """What ``clear_held`` removed, and every path below the store directory it could not."""

    removed: int
    not_removed: tuple[str, ...]


_MAX_CLEAR_DEPTH = 16


def _remove_tree(parent: int, name: str, depth: int) -> tuple[int, list[str]]:
    """Remove the directory ``name`` under ``parent`` and everything in it, through no-follow
    descriptors; a symlink is removed itself, never followed. Returns ``(removed, left)``,
    ``left`` being the paths (relative to ``parent``) that could not be removed."""
    if depth > _MAX_CLEAR_DEPTH:
        return 0, [name + "/"]
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
    except OSError:
        return 0, [name + "/"]
    removed, left = 0, []
    try:
        try:
            with os.scandir(fd) as entries:
                children = [entry.name for entry in entries]
        except OSError:
            return 0, [name + "/"]  # it cannot be listed: it stays, and is reported
        for child in children:
            try:
                info = os.stat(child, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                left.append(f"{name}/{child}")
                continue
            if stat.S_ISDIR(info.st_mode):
                count, rest = _remove_tree(fd, child, depth + 1)
                removed += count
                left.extend(f"{name}/{item}" for item in rest)
                continue
            try:
                os.unlink(child, dir_fd=fd)
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                left.append(f"{name}/{child}")
    finally:
        os.close(fd)
    try:
        os.rmdir(name, dir_fd=parent)
        if depth:
            removed += 1
    except OSError:
        if not left:
            left.append(name + "/")
    return removed, left


def clear_held(store) -> HeldClear:
    """``agy-qualification clear --all``: remove ``held/`` completely, under the store lock,
    through the verified store anchor. Nested entries are removed through checked no-follow
    descriptors; a ``held`` that is a symlink or a file is removed itself, never traversed.

    Whatever is left is reported in ``not_removed``, never silently, and this never raises.
    Whether ``held/`` is there does not depend on the store's own status (a store with a
    missing key still has its cache). When cleanup cannot safely proceed (no anchor reaches
    the store, the anchor walk refuses it, or the store lock cannot be taken), ``held/`` is
    reported as not removed."""
    whole = (HELD_DIRNAME + "/",)
    try:
        os.lstat(store.host_dir / HELD_DIRNAME)
    except (FileNotFoundError, NotADirectoryError):
        return HeldClear(0, ())  # confirmed absent
    except OSError:
        return HeldClear(0, whole)  # an inaccessible path: it may be there, so it is reported
    if not _reachable(store.host_dir):
        return HeldClear(0, whole)
    try:
        anchor = _open_cache_store(store)
    except OSError:
        return HeldClear(0, whole)
    try:
        with store.lock(dir_fd=anchor):
            return _clear_at(anchor)
    except (OSError, ValueError):
        return HeldClear(0, whole)  # the lock was refused (a symlink, wrong owner or mode)
    finally:
        os.close(anchor)


def _clear_at(anchor: int) -> HeldClear:
    """``clear_held`` under the lock: never raises, reports what stays."""
    try:
        info = os.stat(HELD_DIRNAME, dir_fd=anchor, follow_symlinks=False)
    except FileNotFoundError:
        return HeldClear(0, ())
    except OSError:
        return HeldClear(0, (HELD_DIRNAME + "/",))
    if not stat.S_ISDIR(info.st_mode):
        try:
            os.unlink(HELD_DIRNAME, dir_fd=anchor)
            return HeldClear(1, ())
        except FileNotFoundError:
            return HeldClear(0, ())
        except OSError:
            return HeldClear(0, (HELD_DIRNAME,))
    removed, left = _remove_tree(anchor, HELD_DIRNAME, 0)
    return HeldClear(removed, tuple(left))
