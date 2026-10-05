"""First-use jail qualification (agent-harness#1132, plan amendment A2).

When a Claude seat would take the jailed route and no EC-EXECFIND-2 pass is recorded for
this host, this jail's profile digest and the falsifier-run layout, the harness runs the
host's jail qualification itself, once, before launching. It is the same procedure as
``phase-loop seat-sandbox qualify``, and on a pass it records the pass in the per-host
store. This folds in agent-harness#1186's first-use self-check (option C).

- **One run per host:** the run is serialized by an exclusive lock in the per-user state
  directory. Concurrent seats or boards wait for it, then re-read the store.
- **On a failure** (the falsifiers failed, or the run could not happen): the seat is
  degraded and not run with ``seat_jail_qualification_failed`` and a typed reason (plan
  amendment A3b: never a sealed substitute). The rest of the board runs.
- **The failure cache:** a failure is cached for this host, digest and layout only, and is
  retried after ``RETRY_ENV`` seconds or as soon as the digest or layout changes.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping

from . import seat_jail

QUALIFIED = "qualified"            # a pass was already recorded
QUALIFIED_NOW = "qualified_now"    # this process (or one it waited for) recorded it now
FAILED = "failed"

#: Typed reasons; each has a literal fix.
REASON_FIXES: Mapping[str, str] = {
    "prerequisite_missing": (
        "install the seat prerequisites (bwrap, slirp4netns, uidmap and subordinate ids), "
        "then run `phase-loop seat-sandbox qualify`"),
    "store_unsafe": (
        "make $XDG_STATE_HOME, its phase-loop directory and seat-jail-passes private "
        "(chmod go-w; group-writable is accepted only for your user-private group), then "
        "run `phase-loop seat-sandbox qualify`"),
    "falsifiers_failed": (
        "run `phase-loop seat-sandbox qualify` to see which check failed, and report a defect"),
    "timeout": "another qualification is still running or hung; retry, or run "
               "`phase-loop seat-sandbox qualify`",
    "error": "run `phase-loop seat-sandbox qualify` to see the error",
}

RETRY_ENV = "PHASE_LOOP_SEAT_JAIL_QUALIFY_RETRY_S"
DEFAULT_RETRY_S = 3600.0
LOCK_WAIT_S = 1800.0
_FAILURE_CAP = 4096
_SCHEMA = "seat_jail_qualify_failure.v1"


@dataclass(frozen=True)
class Outcome:
    state: str
    reason: str | None = None

    @property
    def qualified(self) -> bool:
        return self.state in (QUALIFIED, QUALIFIED_NOW)


_RECENT: dict[str, Outcome] = {}
_RECENT_LOCK = threading.Lock()


def recent_outcome(digest: str) -> Outcome | None:
    """This process's latest outcome for ``digest`` (the mode line reads it)."""
    with _RECENT_LOCK:
        return _RECENT.get(digest)


def _remember(digest: str, outcome: Outcome) -> Outcome:
    with _RECENT_LOCK:
        _RECENT[digest] = outcome
    return outcome


def _state_dir() -> Path:
    return seat_jail.state_home() / "phase-loop"


def failure_dir() -> Path:
    return _state_dir() / "seat-jail-qualify-failures"


def lock_path() -> Path:
    return _state_dir() / "seat-jail-qualify.lock"


def retry_s(env: Mapping[str, str] | None = None) -> float:
    env = os.environ if env is None else env
    try:
        value = float(env.get(RETRY_ENV, ""))
    except ValueError:
        return DEFAULT_RETRY_S
    return value if value >= 0 else DEFAULT_RETRY_S


def _private_dirs(*paths: Path) -> None:
    for path in paths:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass


def cached_failure(digest: str, *, now: float, retry_after_s: float) -> str | None:
    """The cached failure reason for this host, digest and layout, while it is fresh."""
    path = failure_dir() / f"{digest}.json"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _FAILURE_CAP:
            return None
        record = json.loads(os.read(fd, _FAILURE_CAP + 1))
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None
    finally:
        os.close(fd)
    if not isinstance(record, dict):
        return None
    reason = record.get("reason")
    failed_at = record.get("failed_at")
    if (record.get("schema") != _SCHEMA or reason not in REASON_FIXES
            or record.get("host_identity") != seat_jail.host_identity()
            or record.get("falsifier_layout") != seat_jail.falsifier_layout_identity()
            or isinstance(failed_at, bool) or not isinstance(failed_at, (int, float))
            or now - failed_at >= retry_after_s):
        return None
    return reason


def _record_failure(digest: str, reason: str, now: float) -> None:
    try:
        _private_dirs(seat_jail.state_home(), _state_dir(), failure_dir())
        record = {"schema": _SCHEMA, "profile_digest": digest, "reason": reason,
                  "failed_at": now, "host_identity": seat_jail.host_identity(),
                  "falsifier_layout": seat_jail.falsifier_layout_identity()}
        target = failure_dir() / f"{digest}.json"
        staged = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                     0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
        os.replace(staged, target)
    except OSError:
        return   # an uncached failure is retried next time; never fatal


@contextlib.contextmanager
def qualification_lock(wait_s: float = LOCK_WAIT_S) -> Iterator[None]:
    """The host-level lock every qualification run holds (first use and the CLI alike).
    Raises ``TimeoutError`` after ``wait_s``."""
    fd = _acquire_lock(wait_s)
    try:
        yield
    finally:
        os.close(fd)


def _acquire_lock(wait_s: float) -> int:
    import fcntl

    _private_dirs(seat_jail.state_home(), _state_dir())
    fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_CLOEXEC", 0), 0o600)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise TimeoutError("jail qualification lock") from None
            time.sleep(0.2)


def classify_failure(exc: BaseException) -> str:
    """A qualification exception's typed reason (the message itself is never shown)."""
    from . import seat_jail_qualification, seat_uid

    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, seat_jail_qualification.QualificationError):
        text = str(exc)
        if (text == seat_uid.PREREQUISITE or text == "egress isolation unavailable"
                or text.startswith("no /etc/machine-id")):
            return "prerequisite_missing"
        if "no pass recorded" in text:
            return "store_unsafe"
        return "falsifiers_failed"
    return "error"


def _default_qualify(leg: str) -> Mapping[str, object]:
    from . import seat_jail_qualification

    return seat_jail_qualification.qualify(leg)


def ensure_qualified(
    leg: str, *,
    verdict: Callable[[str], tuple[bool, str]] | None = None,
    qualify: Callable[[str], Mapping[str, object]] | None = None,
    now: Callable[[], float] | None = None,
    retry_after_s: float | None = None,
    lock_wait_s: float = LOCK_WAIT_S,
) -> Outcome:
    """Qualify this host's jail for ``leg`` on first use. Never raises."""
    verdict = verdict or seat_jail.pass_record_verdict
    qualify = qualify or _default_qualify
    now = now or time.time
    retry_after = retry_s() if retry_after_s is None else retry_after_s
    digest = seat_jail.jail_profile_digest(leg)
    passed, why = verdict(digest)
    if passed:
        return _remember(digest, Outcome(QUALIFIED))
    if why.startswith(("store_unsafe:", "error:")):
        # A run cannot fix these: an unsafe store refuses the pass it would write. They are
        # cheap to re-detect, so they are not cached (the chmod takes effect at once).
        return _remember(digest, Outcome(
            FAILED, "store_unsafe" if why.startswith("store_unsafe:") else "error"))
    cached = cached_failure(digest, now=now(), retry_after_s=retry_after)
    if cached is not None:
        return _remember(digest, Outcome(FAILED, cached))
    try:
        fd = _acquire_lock(lock_wait_s)
    except TimeoutError:
        return _remember(digest, Outcome(FAILED, "timeout"))   # not cached: someone is running
    except (OSError, ImportError):
        return _remember(digest, Outcome(FAILED, "error"))
    try:
        # Another process may have finished while this one waited.
        if verdict(digest)[0]:
            return _remember(digest, Outcome(QUALIFIED_NOW))
        cached = cached_failure(digest, now=now(), retry_after_s=retry_after)
        if cached is not None:
            return _remember(digest, Outcome(FAILED, cached))
        try:
            evidence = qualify(leg)
            reason = None if evidence.get("result") == "pass" else "falsifiers_failed"
        except Exception as exc:  # every failure is typed; the seat is degraded, not run
            reason = classify_failure(exc)
        if reason is None and verdict(digest)[0]:
            return _remember(digest, Outcome(QUALIFIED_NOW))
        reason = reason or "error"
        _record_failure(digest, reason, now())
        return _remember(digest, Outcome(FAILED, reason))
    finally:
        os.close(fd)
