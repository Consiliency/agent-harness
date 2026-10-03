"""Where a review sandbox lives, and what it may reach.

A panelist runs wherever its sandbox is, so the sandbox root is a LOCATION rather than a
directory: a bare path is local, ``host:path`` names a host the seat executes on. That
choice removes the remote-filesystem problem instead of managing it -- no network
filesystem, no small-file I/O over the wire, and nothing for macOS or Windows to support
beyond the local default.

Every knob here is env-overridable and defaults to a working local setup. With nothing
configured there is no probe and no fallback decision, only a free-space check.

**Where the stage lands, and how much of it is kept, is sized to the filesystem it is on**
(agent-harness#1147). The invariant: sandbox staging and spawned-CLI scratch are never
RAM-backed while a disk-backed candidate is usable; otherwise they run in a typed DEGRADED
mode (:class:`ScratchLocation`, one warning, hard-clamped retention), or are refused under
``PHASE_LOOP_SANDBOX_REFUSE_RAM=1``. Caps and floors scale to the filesystem, which protects
a small disk as well as a tmpfs. "RAM-backed" is a Linux tmpfs/ramfs, identified by the
device serving the path in the mount table; macOS and Windows temp dirs count as disk.

Two named exceptions, each a typed :func:`child_scratch_env` decision: the agy
QUALIFICATION and capture jails keep their tmpfs ``/tmp`` and frozen env, because they are
qualification evidence (follow-up agent-harness#1179); and the Gemini HEARTBEAT seat's jail
mounts its own private ``/tmp`` (agent-harness#1181). Neither covers a bounded Gemini leg.

Environment overrides (all optional):

* ``PHASE_LOOP_SANDBOX_STAGING_DIR`` -- the local directory each round's ``pl-panel-*``
  scratch is created in. Honoured as given, even on a tmpfs (degraded, with a warning).
  ``TMPDIR`` is deliberately NOT this override: systems commonly point it at a tmpfs.
* ``PHASE_LOOP_SANDBOX_REFUSE_RAM=1`` -- fail closed: refuse instead of the degraded fallback.
* ``PHASE_LOOP_SANDBOX_ROOT`` -- the *selected* root (``host:path`` allowed), recorded in the
  evidence as ``sandbox_root_*``; placement does not consume it yet (agent-harness#896).
* ``PHASE_LOOP_SANDBOX_FLOOR_BYTES`` -- free-space floor. When set it is used verbatim; the
  default (2 GiB) is lowered to a quarter of a filesystem smaller than 8 GiB, and is a quarter
  of a RAM-backed one.
* ``PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES`` -- retention ceiling (default 40 GiB), always
  further limited to a quarter of the staging filesystem (a tenth if it is RAM-backed).
* ``PHASE_LOOP_SANDBOX_TTL_S`` (default 24 h), ``PHASE_LOOP_SANDBOX_PROBE_TIMEOUT_S``,
  ``PHASE_LOOP_SANDBOX_ARCHIVE_DEST``, ``PHASE_LOOP_SANDBOX_DISABLE``.

Without an override the stage goes to the platform's per-user cache dir (``$XDG_CACHE_HOME``
or ``~/.cache`` on Linux, ``~/Library/Caches`` on macOS, ``%LOCALAPPDATA%`` on Windows) under
``phase-loop/sandboxes``, then to the system temp dir if that is not RAM-backed.

Spawned agent CLIs (board legs, advisory seats, the president, executors, convergence
adapters; not the two exceptions above) get ``TMPDIR`` and
``CLAUDE_CODE_TMPDIR`` pointed at a private (0700) disk-backed per-user dir with room --
``phase-loop/tmp`` in the cache dir -- for each variable that is unset and whose own default
destination is RAM-backed (:func:`fill_child_tmp_env`). Setting a variable yourself opts
out, except on the brokered route, whose allowlist drops ambient values: there only the
runtime's own dir can appear.

Two failure modes drive the shape of :func:`select_sandbox_root`:

* A dead remote root typically **hangs** rather than erroring, so the probe is bounded by a
  timeout and runs off-thread. Catching exceptions is not sufficient.
* Running the filesystem to zero does not degrade a review, it takes the host down with it.
  So below the floor we **refuse**; unreachability falls back, exhaustion does not.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from dataclasses import dataclass
from ipaddress import ip_address
import os
from pathlib import Path
import re
from typing import Mapping
import shutil
import stat
import subprocess
import sys
import tempfile
import warnings

__all__ = [
    "SandboxLocation",
    "SandboxRootChoice",
    "SandboxSpaceError",
    "EgressPolicy",
    "parse_location",
    "select_sandbox_root",
    "egress_allowlist",
    "configured_root",
    "floor_bytes",
    "ttl_seconds",
    "max_total_bytes",
    "probe_timeout_s",
    "archive_destination",
    "sandbox_enabled",
    "staging_root",
    "legacy_staging_root",
    "is_ram_backed",
    "fill_child_tmp_env",
    "resolve_staging",
    "ScratchLocation",
    "SandboxRamBackedError",
    "refuse_ram",
    "effective_max_total_bytes",
    "effective_floor_bytes",
]

# Dev-friendly defaults. Production raises the floor by configuration, not by code.
_DEFAULT_FLOOR_BYTES = 2 * 1024**3
_DEFAULT_TTL_S = 24 * 3600
_DEFAULT_PROBE_TIMEOUT_S = 5.0
_DEFAULT_MAX_TOTAL_BYTES = 40 * 1024**3
# Retained sandboxes may occupy at most this share of the filesystem they are on, whatever
# the configured cap says. A quarter leaves the other three for everything else that shares
# the filesystem; with the floor below it never exceeds half, so the cap can always be
# satisfied without breaching the floor.
_MAX_TOTAL_FRACTION = 0.25
# On a RAM-backed root (only ever the least-bad fallback, or an explicit choice) retention is
# clamped hard: a tenth of it, with the floor raised to a quarter -- 35% at most, in RAM.
_RAM_MAX_TOTAL_FRACTION = 0.10
# The default floor never claims more than this share of the filesystem. A fixed 2 GiB on a
# filesystem of 8 GiB or less would be a quarter or more of it -- on a 2 GiB filesystem it
# refuses every round forever -- so below that size the floor scales with the filesystem.
_FLOOR_FRACTION = 0.25
_STAGING_DIR_ENV = "PHASE_LOOP_SANDBOX_STAGING_DIR"
_MOUNTINFO = Path("/proc/self/mountinfo")
_RAM_FSTYPES = frozenset({"tmpfs", "ramfs"})
_CHILD_TMP_ENV_VARS = ("TMPDIR", "CLAUDE_CODE_TMPDIR")

# The inference endpoints a seat may reach inside the private network, allowlisted by
# HOST AND PORT. Never by host alone: the same machine serves qdrant (user data) and a
# file_browser, and NFS, rpcbind and ssh besides.
_INFERENCE_ALLOW: tuple[tuple[str, int], ...] = (
    ("100.84.171.76", 8020),   # ai_router, fronts the models
    ("100.84.171.76", 3131),   # service discovery
)


class SandboxSpaceError(RuntimeError):
    """Refusing to create a sandbox that would exhaust the filesystem."""


@dataclass(frozen=True)
class SandboxLocation:
    host: str | None
    path: Path

    def __str__(self) -> str:
        return f"{self.host}:{self.path}" if self.host else str(self.path)


@dataclass(frozen=True)
class SandboxRootChoice:
    host: str | None
    path: Path
    fell_back: bool
    reason: str = ""


def parse_location(value: str | os.PathLike[str]) -> SandboxLocation:
    """Parse a root spec. Bare path -> local; ``host:path`` -> that host.

    A Windows drive letter is a path, not a host: splitting on the first colon would read
    ``C:\\work`` as the host ``C``. A single-character prefix is therefore treated as a
    drive, and a value with no colon at all is always local.
    """
    text = str(value)
    if ":" not in text:
        return SandboxLocation(None, Path(text))
    head, _, tail = text.partition(":")
    if len(head) <= 1 or not tail:
        return SandboxLocation(None, Path(text))
    return SandboxLocation(head, Path(tail))


def _free_bytes(path: str | os.PathLike[str]) -> int:
    """Free bytes at ``path``, walking up to the nearest existing ancestor."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _free_bytes_at(location: SandboxLocation, timeout_s: float) -> int | None:
    """Free bytes at a location, local or remote. ``None`` when it cannot be determined.

    One seam for both cases so the floor is enforced identically wherever the sandbox
    lands. Checking only the local side would let a remote root that is itself full pass
    the floor and then fail mid-stage.
    """
    if location.host is None:
        return _free_bytes(location.path)
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={max(1, int(timeout_s))}",
             location.host, f"df -PB1 {location.path} 2>/dev/null | awk 'NR==2{{print $4}}'"],
            check=True, capture_output=True, text=True, timeout=timeout_s,
        ).stdout.strip()
        return int(out) if out.isdigit() else None
    except Exception:
        return None


def _probe_root(location: str, timeout_s: float) -> bool:
    """Is this root reachable AND writable? Bounded; never raises."""
    parsed = parse_location(location)
    try:
        if parsed.host is None:
            parsed.path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=parsed.path):
                return True
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={max(1, int(timeout_s))}",
             parsed.host, f"mkdir -p {parsed.path} && touch {parsed.path}/.probe && rm -f {parsed.path}/.probe"],
            check=True, capture_output=True, timeout=timeout_s,
        )
        return True
    except Exception:
        return False


def _probe_with_deadline(location: str, timeout_s: float) -> bool:
    """Run the probe off-thread so a HANGING root loses to the clock.

    A wedged network filesystem or an unresponsive host does not raise; it blocks. A bare
    ``subprocess`` timeout does not cover every such path, so the whole probe is bounded
    here. The worker thread is abandoned rather than joined -- it is a probe with no
    side effects worth waiting for.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_probe_root, location, timeout_s)
        try:
            return bool(future.result(timeout=timeout_s))
        except _FutureTimeout:
            return False
    finally:
        executor.shutdown(wait=False)


def sandbox_enabled() -> bool:
    """Should a review round stage a sandbox for its seats?

    Default ON: a board whose seats cannot open the code they review is the defect this
    exists to fix, and leaving it off by default would ship the machinery dormant -- which
    is exactly what happened before this knob existed.

    ``PHASE_LOOP_SANDBOX_DISABLE=1`` turns it off for an operator who wants the historical
    bundle-only posture, and the brokered surface is then byte-identical to before.
    """
    return os.environ.get("PHASE_LOOP_SANDBOX_DISABLE", "").strip() not in ("1", "true", "yes")


def configured_root() -> str | None:
    return os.environ.get("PHASE_LOOP_SANDBOX_ROOT") or None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def floor_bytes() -> int:
    return _env_int("PHASE_LOOP_SANDBOX_FLOOR_BYTES", _DEFAULT_FLOOR_BYTES)


def ttl_seconds() -> int:
    return _env_int("PHASE_LOOP_SANDBOX_TTL_S", _DEFAULT_TTL_S)


def max_total_bytes() -> int:
    return _env_int("PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES", _DEFAULT_MAX_TOTAL_BYTES)


def probe_timeout_s() -> float:
    try:
        return float(os.environ["PHASE_LOOP_SANDBOX_PROBE_TIMEOUT_S"])
    except (KeyError, ValueError):
        return _DEFAULT_PROBE_TIMEOUT_S


def archive_destination() -> str | None:
    return os.environ.get("PHASE_LOOP_SANDBOX_ARCHIVE_DEST") or None


def _existing_ancestor(path: str | os.PathLike[str]) -> Path:
    probe = Path(os.path.abspath(path))
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def _unescape_mountinfo(field: str) -> str:
    # The kernel octal-escapes space, tab, newline and backslash in mountinfo paths.
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def _mount_fstype(path: str | os.PathLike[str]) -> str | None:
    """The fstype of the mount that actually holds ``path``; ``None`` when it cannot be read.

    Read from ``/proc/self/mountinfo``, never guessed from the path: ``/tmp`` is a disk
    directory on most hosts and a tmpfs on some, and a per-user cache can be either.

    The mount is identified by DEVICE, not by path: the resolved path's ``st_dev`` is
    matched against each entry's ``major:minor``. Path order alone gets overmounts wrong
    -- a tmpfs mounted over a directory that has a disk submount under it, or an older
    tmpfs moved on top of a newer bind mount, both leave a hidden disk entry that a
    longest-prefix or last-line rule picks instead of the tmpfs actually serving the path.
    Among entries on that device the visible one is the longest mountpoint containing the
    path (last line on a tie). Only if no entry carries the device (a filesystem whose
    ``st_dev`` is synthetic, e.g. a btrfs subvolume) does the path rule decide alone.
    No ``/proc`` (macOS, Windows) is unknown, and unknown is not tmpfs.
    """
    try:
        text = _MOUNTINFO.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    anchor = _existing_ancestor(path)
    target = os.path.realpath(anchor)
    try:
        st_dev = os.stat(target).st_dev
        device = f"{os.major(st_dev)}:{os.minor(st_dev)}"
    except (AttributeError, OSError):
        device = None
    entries: list[tuple[str, str, str]] = []  # (device, mountpoint, fstype), file order
    for line in text.splitlines():
        left, sep, right = line.partition(" - ")
        fields = left.split()
        if not sep or len(fields) < 5 or not right.split():
            continue
        entries.append((fields[2], _unescape_mountinfo(fields[4]), right.split()[0]))

    def _inside(mountpoint: str) -> bool:
        return target == mountpoint or target.startswith(mountpoint.rstrip("/") + "/")

    def _visible(candidates: list[tuple[str, str, str]]) -> str | None:
        best: str | None = None
        best_len = -1
        for _dev, mountpoint, fstype in candidates:
            if _inside(mountpoint) and len(mountpoint) >= best_len:
                best, best_len = fstype, len(mountpoint)
        return best

    on_device = [e for e in entries if device is not None and e[0] == device]
    if on_device:
        return _visible(on_device) or on_device[-1][2]
    return _visible(entries)


def _fs_total_bytes(path: str | os.PathLike[str]) -> int | None:
    """Total size of the filesystem holding ``path``; ``None`` when it cannot be measured.

    ``shutil.disk_usage`` is portable (``os.statvfs`` does not exist on Windows, where the
    relative caps would then silently never apply).
    """
    try:
        return shutil.disk_usage(_existing_ancestor(path)).total
    except OSError:
        return None


def is_ram_backed(path: str | os.PathLike[str]) -> bool:
    """Is ``path`` on a tmpfs or ramfs -- storage that is spent out of RAM?

    Linux only, from the mount table. macOS and Windows temp dirs are disk-backed, and a
    host without a readable mount table is treated the same way: unknown is not RAM.
    """
    if not sys.platform.startswith("linux"):
        return False
    return _mount_fstype(path) in _RAM_FSTYPES


def _user_cache_dir() -> Path | None:
    """The platform's per-user cache directory, from the standard locations (stdlib only).

    Linux and other POSIX: ``$XDG_CACHE_HOME`` or ``~/.cache``. macOS: ``~/Library/Caches``.
    Windows: ``%LOCALAPPDATA%``.
    """
    try:
        home = Path.home()
    except (KeyError, RuntimeError):
        home = None
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            return Path(local)
        return home / "AppData" / "Local" if home is not None else None
    if sys.platform == "darwin":
        return home / "Library" / "Caches" if home is not None else None
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    if os.path.isabs(xdg):
        return Path(xdg)
    return home / ".cache" if home is not None else None


def _usable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return False
    return os.access(path, os.W_OK | os.X_OK)


def _private(path: Path, base: Path) -> bool:
    """Create ``path`` below ``base`` as a directory only this account can use, or refuse it.

    ``base`` is a directory the runtime does not own (the user's cache dir, or the shared
    system temp dir); every component from below it down to ``path`` is the runtime's. Each
    such component is created on its own at 0700 and must then be a real directory (not a
    link) owned by this account, tightened to 0700 if it is looser. Used wherever a
    directory is handed to spawned CLIs or holds a staged tree.
    """
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        return False
    if not parts:
        return False
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    if not base.is_dir():
        return False
    current = base
    try:
        for part in parts:
            current = current / part
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            st = current.lstat()
            if not stat.S_ISDIR(st.st_mode):
                return False  # a link (to anything) or a non-directory
            if hasattr(os, "getuid") and st.st_uid != os.getuid():
                return False
            if hasattr(os, "getuid") and st.st_mode & 0o077:
                current.chmod(0o700)
    except OSError:
        return False
    return os.access(path, os.W_OK | os.X_OK)


class SandboxRamBackedError(SandboxSpaceError):
    """``PHASE_LOOP_SANDBOX_REFUSE_RAM`` is set and no disk-backed location is usable."""


@dataclass(frozen=True)
class ScratchLocation:
    """Where per-user scratch goes, and whether that is the DEGRADED (RAM or unwritable)
    fallback. ``degraded`` is the typed form of the invariant's one exception: a
    RAM-backed location is used only when no disk-backed candidate is usable."""

    path: Path
    degraded: bool
    reason: str = ""


_RAM_FALLBACK_WARNED: set[str] = set()
_REFUSE_RAM_ENV = "PHASE_LOOP_SANDBOX_REFUSE_RAM"


def refuse_ram() -> bool:
    """Opt-in fail-closed: refuse rather than fall back to a RAM-backed location."""
    return os.environ.get(_REFUSE_RAM_ENV, "").strip().lower() in ("1", "true", "yes")


def _degraded(leaf: str, fallback: Path, reason: str) -> ScratchLocation:
    if refuse_ram():
        raise SandboxRamBackedError(
            f"no disk-backed location for phase-loop {leaf} ({reason}) and "
            f"{_REFUSE_RAM_ENV} is set; refusing rather than using RAM"
        )
    if leaf not in _RAM_FALLBACK_WARNED:
        _RAM_FALLBACK_WARNED.add(leaf)
        warnings.warn(
            f"no writable disk-backed directory for phase-loop {leaf}; using {fallback} "
            f"({reason}) in DEGRADED mode with hard-clamped retention. Set "
            f"{_STAGING_DIR_ENV} to a disk-backed directory, or {_REFUSE_RAM_ENV}=1 to refuse.",
            RuntimeWarning, stacklevel=4,
        )
    return ScratchLocation(fallback, True, reason)


def _staging_candidates() -> list[tuple[Path, Path | None]]:
    """``(directory, base)``: the cache candidate is the runtime's own below ``base`` and
    must be private (:func:`_private`); the temp dir is used as found (``base`` None), as
    before -- each round's scratch in it is a fresh ``mkdtemp``."""
    cache = _user_cache_dir()
    candidates = [(cache / "phase-loop" / "sandboxes", cache)] if cache is not None else []
    candidates.append((legacy_staging_root(), None))
    return candidates


def _staging_usable(candidate: Path, base: Path | None) -> bool:
    return _usable(candidate) if base is None else _private(candidate, base)


def legacy_staging_root() -> Path:
    """Where releases before agent-harness#1147 staged: the system temp dir."""
    return Path(tempfile.gettempdir())


def resolve_staging() -> ScratchLocation:
    """The directory a round's ``pl-panel-*`` scratch (and its sandbox) is made in.

    Invariant: never RAM-backed while a disk-backed candidate is usable. Order:
    ``PHASE_LOOP_SANDBOX_STAGING_DIR`` if set (honoured as given; flagged degraded if it
    is RAM-backed); else the per-user cache dir's ``phase-loop/sandboxes``; else the
    system temp dir when it is not RAM-backed. With neither usable the result is the
    typed DEGRADED fallback -- the first writable candidate, else the temp dir -- with one
    warning and hard-clamped retention, or a :class:`SandboxRamBackedError` under
    ``PHASE_LOOP_SANDBOX_REFUSE_RAM=1``.
    """
    override = os.environ.get(_STAGING_DIR_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            pass  # surfaces where the scratch dir is made, with the path in the error
        if is_ram_backed(path):
            if refuse_ram():
                raise SandboxRamBackedError(
                    f"{_STAGING_DIR_ENV}={override} is RAM-backed and {_REFUSE_RAM_ENV} is set"
                )
            warnings.warn(
                f"{_STAGING_DIR_ENV}={override} is RAM-backed; honouring the explicit choice, "
                "with hard-clamped retention",
                RuntimeWarning, stacklevel=3,
            )
            return ScratchLocation(path, True, "explicit override is RAM-backed")
        return ScratchLocation(path, False)
    candidates = _staging_candidates()
    for candidate, base in candidates:
        if not is_ram_backed(candidate) and _staging_usable(candidate, base):
            return ScratchLocation(candidate, False)
    fallback = next(
        (c for c, base in candidates if _staging_usable(c, base)), legacy_staging_root())
    return _degraded("sandboxes", fallback, "every candidate is RAM-backed or unwritable")


def staging_root() -> Path:
    """:func:`resolve_staging`'s directory."""
    return resolve_staging().path


def _child_tmp_dir() -> ScratchLocation:
    """A private (0700, ours) disk-backed dir for spawned CLIs' own scratch, with room.

    Candidates: the per-user cache dir's ``phase-loop/tmp``, then a per-user
    ``phase-loop-<uid>`` dir under the system temp dir. Each must be disk-backed, private,
    and above its free-space floor -- relocating multi-gigabyte CLI scratch onto a full
    small disk would trade one exhausted filesystem for another.
    """
    cache = _user_cache_dir()
    uid = os.getuid() if hasattr(os, "getuid") else "user"
    shared = legacy_staging_root()
    candidates = [(cache / "phase-loop" / "tmp", cache)] if cache is not None else []
    candidates.append((shared / f"phase-loop-{uid}" / "tmp", shared))
    for candidate, base in candidates:
        if is_ram_backed(candidate) or not _private(candidate, base):
            continue
        try:
            if _free_bytes(candidate) < effective_floor_bytes(candidate):
                continue
        except OSError:
            continue
        return ScratchLocation(candidate, False)
    return ScratchLocation(legacy_staging_root(), True, "no private disk-backed dir with room")


def _child_default_tmp(name: str, env: Mapping[str, str]) -> list[str]:
    """Where a child CLI would put its scratch for ``name`` if ``name`` stays unset."""
    system = "/tmp" if os.name == "posix" else tempfile.gettempdir()
    if name == "TMPDIR":
        return [system]
    # CLAUDE_CODE_TMPDIR unset: Claude Code falls back to the temp dir, which may be the
    # child's TMPDIR or /tmp itself (`/tmp/claude-<uid>`) -- judge by both.
    return [p for p in (env.get("TMPDIR"), system) if p]


def fill_child_tmp_env(env: dict[str, str]) -> dict[str, str]:
    """Point a spawned agent CLI's own scratch at disk when it would otherwise land in RAM.

    Agent CLIs write large scratch of their own: Claude Code uses ``$CLAUDE_CODE_TMPDIR``,
    falling back to ``/tmp/claude-<uid>`` (agent-harness#1147). Each of ``TMPDIR`` and
    ``CLAUDE_CODE_TMPDIR`` that ``env`` does NOT already set is judged against its own
    default destination; if that is RAM-backed, it is set to a private disk-backed
    per-user dir. A value the caller set is never overridden. When no private disk-backed
    dir with room exists the env is left alone in the typed degraded mode (one warning),
    or ``PHASE_LOOP_SANDBOX_REFUSE_RAM=1`` raises :class:`SandboxRamBackedError`.
    Mutates and returns ``env``.
    """
    try:
        needed = [
            name for name in _CHILD_TMP_ENV_VARS
            if name not in env and any(is_ram_backed(p) for p in _child_default_tmp(name, env))
        ]
        if not needed:
            return env
        location = _child_tmp_dir()
    except Exception as exc:  # never silent: degraded (one warning) or refused, as below
        location = ScratchLocation(legacy_staging_root(), True,
                                   f"scratch probe failed: {type(exc).__name__}")
    if location.degraded:
        _degraded("child scratch", location.path, location.reason)  # warns or refuses
        return env
    for name in needed:
        env[name] = str(location.path)
    return env


#: The scratch decision every agent-CLI launch makes (:func:`child_scratch_env`).
CHILD_SCRATCH_RELOCATE = "relocate"
#: The child is jailed with its own private ``/tmp`` (the Gemini heartbeat seat,
#: agent-harness#1181); a host directory would not exist inside it.
CHILD_SCRATCH_PRIVATE_TMP = "private_tmp"
#: The agy capture/qualification jails' frozen env (named exception, agent-harness#1179).
CHILD_SCRATCH_FROZEN_CAPTURE = "frozen_capture"
CHILD_SCRATCH_DECISIONS = (
    CHILD_SCRATCH_RELOCATE, CHILD_SCRATCH_PRIVATE_TMP, CHILD_SCRATCH_FROZEN_CAPTURE,
)


def child_scratch_env(env: Mapping[str, str], decision: str) -> dict[str, str]:
    """The env an agent CLI is launched with, after its scratch decision.

    ``CHILD_SCRATCH_RELOCATE`` applies :func:`fill_child_tmp_env`; the two named
    exceptions keep the env as built. Any other value is refused, so a launch site cannot
    state a decision this module does not know. Returns a new dict.
    """
    if decision not in CHILD_SCRATCH_DECISIONS:
        raise ValueError(f"unknown child scratch decision {decision!r}")
    out = dict(env)
    return fill_child_tmp_env(out) if decision == CHILD_SCRATCH_RELOCATE else out


def effective_max_total_bytes(path: str | os.PathLike[str]) -> int:
    """The retention ceiling for sandboxes under ``path``: the configured cap, but never
    more than a quarter of the filesystem they are on -- a tenth if it is RAM-backed."""
    cap = max_total_bytes()
    total = _fs_total_bytes(path)
    if total:
        fraction = _RAM_MAX_TOTAL_FRACTION if is_ram_backed(path) else _MAX_TOTAL_FRACTION
        cap = min(cap, int(total * fraction))
    return cap


def _floor_configured() -> bool:
    """Was a floor CONFIGURED? Decided by the setting's presence, never by its value: a
    floor explicitly set to exactly the default must still be used verbatim."""
    value = os.environ.get("PHASE_LOOP_SANDBOX_FLOOR_BYTES", "").strip()
    try:
        int(value)
    except ValueError:
        return False
    return True


def effective_floor_bytes(path: str | os.PathLike[str]) -> int:
    """The free-space floor for staging at ``path``.

    A configured floor is used verbatim -- the operator's protection is never weakened.
    So is a non-default value from the ``floor_bytes()`` seam. The DEFAULT scales with the
    filesystem: on disk it is capped at a quarter, so a small filesystem is not refused
    forever by a floor as large as itself; on a RAM-backed filesystem it is a quarter of
    it, so staging always leaves that much memory free and never demands more than exists.
    """
    floor = floor_bytes()
    if _floor_configured() or floor != _DEFAULT_FLOOR_BYTES:
        return floor
    total = _fs_total_bytes(path)
    if total:
        quarter = int(total * _FLOOR_FRACTION)
        floor = quarter if is_ram_backed(path) else min(floor, quarter)
    return floor


def ensure_staging_space(destination: Path | str, floor_bytes: int | None = None) -> None:
    """Refuse if the filesystem that will ACTUALLY hold the sandbox is below the floor.

    `select_sandbox_root` checks the free space of the root it SELECTS. Nothing consumes
    that selection for placement yet (agent-harness#896): the clone is always staged
    locally under the leg's scratch dir. So a healthy configured root -- remote, or simply
    on another local filesystem -- returned early and the real destination was never
    measured, and recording `sandbox_root_applied=False` documents that without preventing
    it. Board round 7, codex, BLOCKING: "deferring remote placement is acceptable only if
    the actual staging filesystem is still checked."

    Filling the filesystem that holds the broker's scratch takes the host down with it,
    which is why this refuses rather than warns -- the same trade the floor was introduced
    for. Call it with the directory the clone will be written into, not the policy's
    selection.
    """
    floor = _DEFAULT_FLOOR_BYTES if floor_bytes is None else floor_bytes
    target = Path(destination)
    if not target.is_dir():
        # UNKNOWN IS NOT FULL, and this is where that has to be decided -- not by a
        # `free is not None` guard, which board round 8 showed is dead for a local path:
        # `_free_bytes_at` with no host always returns an int or raises. `_free_bytes`
        # walks up to the nearest existing ancestor, so an unmeasurable destination landed
        # on a pseudo-filesystem reporting 0 and REFUSED -- the opposite of the intent, and
        # the test that claimed otherwise monkeypatched a `None` production cannot produce.
        warnings.warn(
            f"cannot measure free space at {destination}; staging is NOT space-checked",
            RuntimeWarning, stacklevel=2,
        )
        return
    # `_free_bytes_at` with no host returns an int or raises -- it can never be None, so
    # the `free is not None` guard that stood here was DEAD, and the test that claimed to
    # cover it monkeypatched a None production cannot produce. That is the same vacuous
    # shape the comment above condemns, committed in the fix for it (board round 9).
    # Unmeasurable is decided above, by `is_dir()`, which is the reachable branch.
    free = _free_bytes_at(SandboxLocation(None, target), 5.0)
    if free < floor:
        raise SandboxSpaceError(
            f"the staging filesystem at {destination} has {free / 1024**3:.1f} GiB free, "
            f"below the {floor / 1024**3:.1f} GiB floor; refusing to stage a sandbox "
            "rather than fill the filesystem the broker and the host depend on"
        )


def select_sandbox_root(
    configured: str | None = None,
    fallback: str | os.PathLike[str] | None = None,
    *,
    floor_bytes: int | None = None,
    probe_timeout_s: float | None = None,
) -> SandboxRootChoice:
    """Choose one root for a whole round, and say why.

    The choice is sticky per round, not per seat: four seats on different roots would have
    different speed and space characteristics while reviewing the same change, and cleanup
    would have to hunt in two places.
    """
    floor = _DEFAULT_FLOOR_BYTES if floor_bytes is None else floor_bytes
    timeout = _DEFAULT_PROBE_TIMEOUT_S if probe_timeout_s is None else probe_timeout_s
    local = Path(fallback) if fallback is not None else Path(tempfile.gettempdir())

    if configured:
        if _probe_with_deadline(configured, timeout):
            parsed = parse_location(configured)
            remote_free = _free_bytes_at(parsed, timeout)
            # Unknown free space is not permission to proceed, but it is also not a
            # reason to abandon a reachable root: treat it as satisfying the floor only
            # when it cannot be measured at all, and record that in the reason.
            if remote_free is None or remote_free >= floor:
                return SandboxRootChoice(parsed.host, parsed.path, False)
            warnings.warn(
                f"sandbox root {configured} is below the free-space floor; falling back to {local}",
                RuntimeWarning, stacklevel=2,
            )
            reason = f"{configured} below floor"
        else:
            warnings.warn(
                f"sandbox root {configured} did not answer within {timeout}s; falling back to {local}",
                RuntimeWarning, stacklevel=2,
            )
            reason = f"{configured} unreachable within {timeout}s"
        free = _free_bytes_at(SandboxLocation(None, local), timeout) or 0
        if free < floor:
            raise SandboxSpaceError(
                f"refusing to create a sandbox: {local} has {free} bytes of free space, "
                f"below the {floor}-byte floor. Filling this filesystem would take the host "
                f"down; a refused round is recoverable."
            )
        return SandboxRootChoice(None, local, True, reason)

    free = _free_bytes_at(SandboxLocation(None, local), timeout) or 0
    if free < floor:
        raise SandboxSpaceError(
            f"refusing to create a sandbox: {local} has {free} bytes of free space, "
                f"below the {floor}-byte floor. Filling this filesystem would take the host "
                f"down; a refused round is recoverable."
        )
    return SandboxRootChoice(None, local, False)


@dataclass(frozen=True)
class EgressPolicy:
    """Deny private space, allow the public internet, allow named endpoints.

    A panelist needs to search, read documentation and install packages, so blanket egress
    denial is the wrong boundary. What must stay unreachable is everything INSIDE: the rest
    of the tailnet, loopback services (the review broker among them), docker bridges, and
    cloud metadata.
    """

    allow: tuple[tuple[str, int], ...] = _INFERENCE_ALLOW

    def allows(self, host: str, port: int) -> bool:
        if (host, port) in self.allow:
            return True
        try:
            address = ip_address(host)
        except ValueError:
            return True  # a name resolves publicly or not at all; the filter enforces on the resolved IP
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved:
            return False
        if address.is_private:
            return False
        # 100.64.0.0/10 (CGNAT) is the tailnet. Python calls it neither private nor global.
        if address.version == 4 and int(address) >> 22 == (100 << 2 | 1):
            return False
        return bool(address.is_global)


def egress_allowlist() -> EgressPolicy:
    return EgressPolicy()
