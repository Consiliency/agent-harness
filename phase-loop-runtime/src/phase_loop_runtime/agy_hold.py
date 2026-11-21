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

Standard library plus ``gemini_heartbeat``; outside ``ROUTE_CORE``. SL-4 (HOLD-CACHE) adds
the cache writers; here ``retain`` is a no-op and ``held/`` is only read.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import re
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
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_RELEASE = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
_VENDOR_NAME = re.compile(_RELEASE + r"-[0-9a-f]{16}")
_DIGEST_NAME = re.compile(r"[0-9a-f]{64}")
_HINT_NAME = re.compile(r"qualified-[0-9a-f]{64}\.json")
_VERSION = re.compile(_RELEASE)
_CANCELLED = "review_operation_cancelled"  # agy_qualification.CANCELLED

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


def retain(image, store) -> None:
    """Keep an admitted image in the harness cache (AGYFRESH §2.8). A no-op until SL-4."""
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
    """Open ``path`` from the walk root one component at a time (AGYFRESH §2.5 "Anchor")."""
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
