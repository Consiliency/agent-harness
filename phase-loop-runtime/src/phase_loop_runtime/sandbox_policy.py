"""Where a review sandbox lives, and what it may reach.

A panelist runs wherever its sandbox is, so the sandbox root is a LOCATION rather than a
directory: a bare path is local, ``host:path`` names a host the seat executes on. That
choice removes the remote-filesystem problem instead of managing it -- no network
filesystem, no small-file I/O over the wire, and nothing for macOS or Windows to support
beyond the local default.

Every knob here is env-overridable and defaults to a working local setup. With nothing
configured there is no probe and no fallback decision, only a free-space check.

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
import shutil
import subprocess
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
]

# Dev-friendly defaults. Production raises the floor by configuration, not by code.
_DEFAULT_FLOOR_BYTES = 2 * 1024**3
_DEFAULT_TTL_S = 24 * 3600
_DEFAULT_PROBE_TIMEOUT_S = 5.0
_DEFAULT_MAX_TOTAL_BYTES = 40 * 1024**3

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
    free = _free_bytes_at(SandboxLocation(None, Path(destination)), 5.0)
    if free is not None and free < floor:
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
