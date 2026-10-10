"""Why the agy on PATH is, or is not, admitted for a Gemini review seat (agent-harness#1431).

Read-only and non-executing: it never runs agy, never qualifies anything and never admits
anything. Admission stays with ``agy_integrity`` and the route core; this module only
explains its verdict to the operator, for ``phase-loop doctor`` and for the board's
composition notice, so the two cannot disagree about what to run.

An image is admitted when it is a shipped release member
(``gemini_heartbeat.QUALIFIED_IMAGES``) or has a local qualification record. The local
record is keyed on the image AND on the runtime's route-core files
(``agy_qualification.runtime_identity``), so a runtime upgrade leaves a host that
qualified its agy with no record for the new runtime (agent-harness#1420). The store binds
that key into each entry's name and MAC and keeps no readable copy of it, so "this build
was qualified under another runtime" is inferred from two entries' UNVERIFIED payloads:
the member cache names the release this image is, and a ``qualified`` entry names that
same release. That inference is a hint for the operator and nothing else reads it.

Nothing returned here is an absolute path: ``doctor`` output is metadata-only.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

# Statuses, in the order `diagnose` decides them.
ABSENT = "absent"
UNKNOWN = "unknown"
RELEASE_QUALIFIED = "release_qualified"
SELF_QUALIFICATION_DISABLED = "self_qualification_disabled"
STORE_UNSAFE = "store_unsafe"
LOCAL_QUALIFICATION_FAILED = "local_qualification_failed"
LOCALLY_QUALIFIED = "locally_qualified"
LOCAL_RECORD_OTHER_RUNTIME = "local_record_other_runtime"
NOT_QUALIFIED = "not_qualified"

STATUSES: tuple[str, ...] = (
    ABSENT, UNKNOWN, RELEASE_QUALIFIED, SELF_QUALIFICATION_DISABLED, STORE_UNSAFE,
    LOCAL_QUALIFICATION_FAILED, LOCALLY_QUALIFIED, LOCAL_RECORD_OTHER_RUNTIME, NOT_QUALIFIED,
)
#: The statuses under which the Gemini seat's probe admits the image.
ADMITTED: frozenset[str] = frozenset({RELEASE_QUALIFIED, LOCALLY_QUALIFIED})

RUN_FIX = "run `phase-loop agy-qualification run`"
_SHIPPED_LATER_NOTE = (
    "a shipped agy build is also on PATH, after the one found first; putting its directory "
    "first on PATH for board runs admits the Gemini seat without a local qualification"
)
_SHIPPED_ELSEWHERE_NOTE = (
    "if another agy build is installed on this host, check it by putting its directory first "
    "on PATH and re-running `phase-loop doctor`: a shipped build reports `release_qualified`"
)

_MAX_IMAGE_BYTES = 300_000_000
_MAX_ENTRY_BYTES = 256 * 1024
# How many other agy executables on PATH are hashed looking for a shipped build.
_MAX_PATH_CANDIDATES = 8


@dataclass(frozen=True)
class AgyDiagnosis:
    """One verdict about the agy on PATH, with what to tell the operator."""

    status: str
    detail: str
    #: The one thing to run, when the image is not admitted.
    fix: str | None = None
    #: A side note for the operator (another build on PATH, or how to check for one).
    note: str | None = None
    #: The agy release this image is, when the store's member cache names it (unverified).
    release: str | None = None
    #: Another agy on PATH is a shipped build but is not the first one found.
    shipped_build_later_on_path: bool = False

    @property
    def admitted(self) -> bool:
        return self.status in ADMITTED

    def as_json(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "harness": "gemini", "cli": "agy", "status": self.status, "detail": self.detail,
            "shipped_build_later_on_path": self.shipped_build_later_on_path,
        }
        for key in ("release", "fix", "note"):
            if getattr(self, key) is not None:
                entry[key] = getattr(self, key)
        return entry


def _image_digest(path: str) -> str | None:
    """SHA-256 of the regular file ``path`` resolves to, or ``None`` when it cannot be read."""
    try:
        fd = os.open(os.path.realpath(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_IMAGE_BYTES:
            return None
        value = sha256()
        while chunk := os.read(fd, 1024 * 1024):
            value.update(chunk)
        return value.hexdigest()
    except OSError:
        return None
    finally:
        os.close(fd)


def _path_candidates(search_path: str) -> list[str]:
    """Every distinct ``agy`` executable on ``search_path``, in PATH order."""
    seen: set[str] = set()
    found: list[str] = []
    for directory in search_path.split(os.pathsep):
        candidate = os.path.join(directory or os.curdir, "agy")
        if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
            continue
        real = os.path.realpath(candidate)
        if real not in seen:
            seen.add(real)
            found.append(candidate)
    return found


def _shipped_build_later_on_path(search_path: str, shipped: Mapping[str, str]) -> bool:
    for candidate in _path_candidates(search_path)[1:1 + _MAX_PATH_CANDIDATES]:
        if _image_digest(candidate) in shipped:
            return True
    return False


def _unverified_payloads(store, entry_type: str) -> list[dict[str, Any]]:
    """The payloads of this host's ``entry_type`` entries, read WITHOUT their MAC.

    An entry's MAC covers a key (image, runtime) that the entry does not carry, so an
    entry written under another runtime cannot be verified here. These payloads are
    therefore hints only; nothing is admitted on them."""
    payloads: list[dict[str, Any]] = []
    try:
        names = sorted(path.name for path in store.host_dir.iterdir()
                       if path.name.startswith(entry_type + "-") and path.suffix == ".json")
    except OSError:
        return payloads
    for name in names:
        try:
            fd = os.open(store.host_dir / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_ENTRY_BYTES:
                continue
            raw = json.loads(os.read(fd, _MAX_ENTRY_BYTES + 1))
        except (OSError, ValueError):
            continue
        finally:
            os.close(fd)
        payload = raw.get("payload") if isinstance(raw, dict) and raw.get("type") == entry_type else None
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _release_of(store, image_sha256: str) -> str | None:
    for payload in _unverified_payloads(store, "member_cache"):
        release = payload.get("release_version")
        if payload.get("member_sha256") == image_sha256 and isinstance(release, str) and release:
            return release
    return None


def _has_record_for_this_runtime(store, image_sha256: str, host, runtime) -> bool:
    """A ``qualified`` entry exists under the name the LIVE key gives this image.

    The entry's name is derived from (image, platform, runtime, profile); its MAC also
    covers the measured ``--help``, which only running agy can produce. So this is
    presence under the live key, and the seat's own lookup still verifies it at launch."""
    name_context, _context = store._qualified_contexts(image_sha256, "", host, runtime)
    return os.path.lexists(store._path("qualified", name_context))


def diagnose(*, search_path: str | None = None, store=None) -> AgyDiagnosis:
    """Diagnose the first ``agy`` on ``search_path`` (default: this process's PATH)."""
    from . import agy_provenance, agy_qualification, gemini_heartbeat

    if search_path is None:
        search_path = os.environ.get("PATH", os.defpath)
    source = shutil.which("agy", path=search_path)
    if source is None:
        return AgyDiagnosis(ABSENT, "agy is not on PATH",
                            "install the agy CLI on PATH, then re-run")
    image_sha256 = _image_digest(source)
    if image_sha256 is None:
        return AgyDiagnosis(UNKNOWN, "the agy on PATH could not be read as a regular file",
                            "reinstall the agy CLI, then re-run")
    shipped = gemini_heartbeat.QUALIFIED_IMAGES
    if image_sha256 in shipped:
        return AgyDiagnosis(RELEASE_QUALIFIED, "the agy build on PATH is a shipped release member")
    later = _shipped_build_later_on_path(search_path, shipped)
    note = _SHIPPED_LATER_NOTE if later else _SHIPPED_ELSEWHERE_NOTE
    not_shipped = "the agy build on PATH is not in this runtime's shipped set"

    def verdict(status: str, detail: str, fix: str | None, release: str | None = None) -> AgyDiagnosis:
        return AgyDiagnosis(status, f"{not_shipped}; {detail}", fix,
                            None if status in ADMITTED else note, release, later)

    if not agy_qualification.self_qualification_enabled():
        return verdict(
            SELF_QUALIFICATION_DISABLED,
            "local self-qualification is turned off in the user board config",
            "re-enable `[agy] self_qualification` in your user board config, then " + RUN_FIX)
    try:
        store = store or agy_qualification.Store()
        state = store.status()
        if state == "unsafe":
            return verdict(
                STORE_UNSAFE, "the per-user agy qualification store is not owner-only",
                "make the store directory `phase-loop agy-qualification status` names owner-only "
                "(0700 directories, 0600 files, no symlinks), or remove it, then " + RUN_FIX)
        release = None
        if state == "ok":
            host = agy_provenance.detect_platform()
            runtime = agy_qualification.runtime_identity()
            if store.get_failed(image_sha256, host, runtime) is not None:
                return verdict(
                    LOCAL_QUALIFICATION_FAILED,
                    "this build failed its qualification on this host under this runtime",
                    "see `phase-loop agy-qualification status`; after updating or repairing agy, run "
                    "`phase-loop agy-qualification clear` and `phase-loop agy-qualification run`")
            release = _release_of(store, image_sha256)
            if _has_record_for_this_runtime(store, image_sha256, host, runtime):
                return verdict(
                    LOCALLY_QUALIFIED,
                    "a local qualification record for this build and this runtime is present",
                    None, release)
            if release is not None and any(
                    payload.get("release_version") == release
                    for payload in _unverified_payloads(store, "qualified")):
                return verdict(
                    LOCAL_RECORD_OTHER_RUNTIME,
                    f"this host qualified agy {release} under a different runtime, and a local "
                    "record is bound to the runtime's own files, so this runtime "
                    f"({runtime['version']}) has none (a runtime upgrade drops it)",
                    RUN_FIX, release)
        return verdict(NOT_QUALIFIED,
                       "this host has no local qualification record for this build",
                       RUN_FIX, release)
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        # ``ProvenanceError`` (an unsupported platform) is a ``ValueError``.
        return verdict(UNKNOWN, "the local qualification store could not be read", RUN_FIX)


def report() -> list[dict[str, Any]]:
    """The section ``phase-loop doctor`` embeds: one row per seat CLI that is qualified per
    host. Never raises, and carries no path."""
    try:
        return [diagnose().as_json()]
    except Exception:  # noqa: BLE001 - doctor reports, it never fails on a diagnosis
        return [AgyDiagnosis(UNKNOWN, "the agy diagnosis could not be completed").as_json()]
