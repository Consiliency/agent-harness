"""Where a review sandbox lives, and what it may reach.

A panelist runs wherever its sandbox is, so the sandbox root is a LOCATION rather than a
directory: a bare path is local, ``host:path`` names a host the seat executes on. That
choice removes the remote-filesystem problem instead of managing it -- no network
filesystem, no small-file I/O over the wire, and nothing for macOS or Windows to support
beyond the local default.

Every knob here is env-overridable and defaults to a working local setup. With nothing
configured there is no probe and no fallback decision, only a free-space check.

**Where the stage lands, and how much of it is kept, is sized to the filesystem it is on**
(agent-harness#1147). On a host whose ``/tmp`` is a tmpfs, staging there spends RAM, and a
fixed 40 GiB retention cap on a 15 GiB tmpfs can never trigger. So :func:`staging_root`
never picks a RAM-backed filesystem by default, and :func:`effective_max_total_bytes` /
:func:`effective_floor_bytes` scale to the size of the filesystem the stage is actually on.

Environment overrides (all optional):

* ``PHASE_LOOP_SANDBOX_STAGING_DIR`` -- the local directory each round's ``pl-panel-*``
  scratch is created in. Honoured as given, even on a tmpfs (with a warning); the relative
  cap still bounds it. ``TMPDIR`` is deliberately NOT this override: systems commonly point
  it at a tmpfs.
* ``PHASE_LOOP_SANDBOX_ROOT`` -- the *selected* root (``host:path`` allowed), recorded in the
  evidence as ``sandbox_root_*``; placement does not consume it yet (agent-harness#896).
* ``PHASE_LOOP_SANDBOX_FLOOR_BYTES`` -- free-space floor. When set it is used verbatim; the
  default (2 GiB) is lowered to a quarter of a filesystem smaller than 8 GiB, and raised to a
  quarter of a RAM-backed one.
* ``PHASE_LOOP_SANDBOX_MAX_TOTAL_BYTES`` -- retention ceiling (default 40 GiB), always
  further limited to a quarter of the staging filesystem (a tenth if it is RAM-backed).

Without an override the stage goes to the platform's per-user cache dir (``$XDG_CACHE_HOME``
or ``~/.cache`` on Linux, ``~/Library/Caches`` on macOS, ``%LOCALAPPDATA%`` on Windows) under
``phase-loop/sandboxes``, then to the system temp dir if that is not RAM-backed. "RAM-backed"
is a Linux tmpfs/ramfs by mount-table fstype; macOS and Windows temp dirs count as disk.

Spawned agent CLIs (board legs, the president, executors) get ``TMPDIR`` and
``CLAUDE_CODE_TMPDIR`` pointed at ``phase-loop/tmp`` in the same cache dir when -- and only
when -- their own temp dir is RAM-backed and the variable is not already set
(:func:`fill_child_tmp_env`).
* ``PHASE_LOOP_SANDBOX_TTL_S`` (default 24 h), ``PHASE_LOOP_SANDBOX_PROBE_TIMEOUT_S``,
  ``PHASE_LOOP_SANDBOX_ARCHIVE_DEST``, ``PHASE_LOOP_SANDBOX_DISABLE``.

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
import shutil
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
    """The fstype of the mount that holds ``path``; ``None`` when it cannot be read.

    Read from ``/proc/self/mountinfo``, never guessed from the path: ``/tmp`` is a disk
    directory on most hosts and a tmpfs on some, and a per-user cache can be either. The
    mount is the one whose mountpoint is the longest prefix of the resolved path; among
    equal mountpoints the LAST line wins, because a later mount hides an earlier one.
    No ``/proc`` (macOS, Windows) is unknown, and unknown is not tmpfs.
    """
    try:
        text = _MOUNTINFO.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    target = os.path.realpath(_existing_ancestor(path))
    best: str | None = None
    best_len = -1
    for line in text.splitlines():
        left, sep, right = line.partition(" - ")
        fields = left.split()
        if not sep or len(fields) < 5 or not right.split():
            continue
        mountpoint = _unescape_mountinfo(fields[4])
        inside = target == mountpoint or target.startswith(mountpoint.rstrip("/") + "/")
        if inside and len(mountpoint) >= best_len:
            best, best_len = right.split()[0], len(mountpoint)
    return best


def _fs_total_bytes(path: str | os.PathLike[str]) -> int | None:
    """Total size of the filesystem holding ``path``; ``None`` when it cannot be measured."""
    try:
        st = os.statvfs(_existing_ancestor(path))
    except (AttributeError, OSError):
        return None
    return st.f_blocks * st.f_frsize


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


_RAM_FALLBACK_WARNED: set[str] = set()


def _resolve_disk_dir(leaf: str) -> tuple[Path, bool]:
    """``(directory, disk_backed)`` for per-user scratch named ``leaf``.

    The per-user cache dir first, then the system temp dir, each only when it is writable
    and not RAM-backed. If neither qualifies, the least-bad one is returned -- the first
    writable candidate, else the temp dir -- with ``disk_backed=False`` so callers clamp
    their caps, and one warning per process. It never raises.
    """
    cache = _user_cache_dir()
    candidates = [cache / "phase-loop" / leaf] if cache is not None else []
    candidates.append(legacy_staging_root())
    for candidate in candidates:
        if not is_ram_backed(candidate) and _usable(candidate):
            return candidate, True
    fallback = next((c for c in candidates if _usable(c)), legacy_staging_root())
    if leaf not in _RAM_FALLBACK_WARNED:
        _RAM_FALLBACK_WARNED.add(leaf)
        warnings.warn(
            f"no writable disk-backed directory for phase-loop {leaf}; using {fallback}, "
            "which is RAM-backed or unwritable, with hard-clamped retention. Set "
            f"{_STAGING_DIR_ENV} to a disk-backed directory.",
            RuntimeWarning, stacklevel=3,
        )
    return fallback, False


def legacy_staging_root() -> Path:
    """Where releases before agent-harness#1147 staged: the system temp dir."""
    return Path(tempfile.gettempdir())


def staging_root() -> Path:
    """The local directory a round's ``pl-panel-*`` scratch (and its sandbox) is made in.

    ``PHASE_LOOP_SANDBOX_STAGING_DIR`` if set (honoured as given, with a warning if it is
    RAM-backed); else the per-user cache dir's ``phase-loop/sandboxes``; else the system temp
    dir when it is not RAM-backed; else the least-bad of those (see ``_resolve_disk_dir``).
    Retention on a RAM-backed root is clamped hard by :func:`effective_max_total_bytes` and
    :func:`effective_floor_bytes`.
    """
    override = os.environ.get(_STAGING_DIR_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            pass  # surfaces where the scratch dir is made, with the path in the error
        if is_ram_backed(path):
            warnings.warn(
                f"{_STAGING_DIR_ENV}={override} is RAM-backed; honouring the explicit choice, "
                "with hard-clamped retention",
                RuntimeWarning, stacklevel=2,
            )
        return path
    return _resolve_disk_dir("sandboxes")[0]


def fill_child_tmp_env(env: dict[str, str]) -> dict[str, str]:
    """Point a spawned agent CLI's own scratch at disk when its temp dir is RAM-backed.

    Agent CLIs write large scratch of their own: Claude Code uses ``$CLAUDE_CODE_TMPDIR``,
    falling back to ``/tmp/claude-<uid>``, and on a host whose ``/tmp`` is a tmpfs that is
    RAM (agent-harness#1147). When the child's effective temp dir (``TMPDIR`` in ``env``,
    else the system default) is RAM-backed, ``TMPDIR`` and ``CLAUDE_CODE_TMPDIR`` are set to
    a disk-backed per-user dir -- only the ones ``env`` does not already set, so an
    explicit value is never overridden. On disk, or with no disk-backed dir, ``env`` is
    returned unchanged. Mutates and returns ``env``; never raises.
    """
    try:
        effective = env.get("TMPDIR") or ("/tmp" if os.name == "posix" else tempfile.gettempdir())
        if not is_ram_backed(effective):
            return env
        target, disk_backed = _resolve_disk_dir("tmp")
        if not disk_backed:
            return env
        for name in _CHILD_TMP_ENV_VARS:
            env.setdefault(name, str(target))
    except Exception:
        pass
    return env


def effective_max_total_bytes(path: str | os.PathLike[str]) -> int:
    """The retention ceiling for sandboxes under ``path``: the configured cap, but never
    more than a quarter of the filesystem they are on -- a tenth if it is RAM-backed."""
    cap = max_total_bytes()
    total = _fs_total_bytes(path)
    if total:
        fraction = _RAM_MAX_TOTAL_FRACTION if is_ram_backed(path) else _MAX_TOTAL_FRACTION
        cap = min(cap, int(total * fraction))
    return cap


def effective_floor_bytes(path: str | os.PathLike[str]) -> int:
    """The free-space floor for staging at ``path``.

    A configured floor (``PHASE_LOOP_SANDBOX_FLOOR_BYTES`` other than the 2 GiB default) is
    used verbatim -- the operator's protection is never weakened. The DEFAULT is capped at a quarter of the filesystem, so
    a small filesystem is not refused forever by a floor as large as itself; on a
    RAM-backed filesystem it is instead RAISED to a quarter, so staging keeps that much
    memory free.
    """
    floor = floor_bytes()
    if floor != _DEFAULT_FLOOR_BYTES:
        return floor  # configured: never scaled
    total = _fs_total_bytes(path)
    if total:
        quarter = int(total * _FLOOR_FRACTION)
        floor = max(floor, quarter) if is_ram_backed(path) else min(floor, quarter)
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
