"""Per-host CLI qualification for every seat harness: the contract (agent-harness#1333 PR2).

A **qualified CLI version** is a key that passed every operation on this host, under this
runtime, through the seat's production launch path. This module holds the parts of that
contract that do not depend on any one harness: the key and its payload/tree digests, the
pinned help-probe environment, the admission classes, the operations runner and its
candidate token, ``lookup`` and ``ensure_admitted``, the per-user store and lock, and the
closed export schema.

It is inert in PR2: ``ADAPTERS`` is empty and no seat call site imports it. PR3 adds the
first adapters and wires the preflight and spawn gates; the contract itself is in
``advisor_board/CONTRACTS.md`` ("CLI qualification (all harnesses)").
"""
from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
import fcntl
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time
from typing import Callable, Mapping, Sequence

from . import __version__

HARNESSES = ("claude", "codex", "grok", "gemini", "opencode", "pi", "cursor-agent")
# harness -> adapter (PR3 onward). Empty in PR2: nothing is qualified through this module yet.
ADAPTERS: dict = {}
# Harnesses that keep their existing admission until their own PR (the claude jail until PR4,
# agy_qualification until PR5).
PENDING_ADAPTERS = frozenset({"claude", "gemini"})
CLASSES = ("release_qualified", "locally_qualified", "qualification_candidate", "none")
OPERATIONS = ("identity", "completion", "cancel", "owner_loss")
PLATFORMS = ("linux-x64", "linux-arm64", "linux-x64-musl", "linux-arm64-musl")
PAYLOAD_KINDS = ("binary", "tree")
# The files whose digests make up the runtime identity, beside each adapter's own module.
ROUTE_CORE = ("cli_qualification.py",)

UNQUALIFIED = "seat_cli_unqualified"
FAILED = "seat_cli_qualification_failed"
UNAVAILABLE = "seat_cli_qualification_unavailable"
STORE_UNSAFE = "seat_cli_qualification_store_unsafe"
ADAPTER_MISSING = "seat_cli_adapter_missing"
PLATFORM_UNSUPPORTED = "seat_cli_platform_unsupported"
CODES = (UNQUALIFIED, FAILED, UNAVAILABLE, STORE_UNSAFE, ADAPTER_MISSING, PLATFORM_UNSUPPORTED)
CANCELLED = "review_operation_cancelled"

MAX_TRANSIENT_ATTEMPTS = 3
TRANSIENT_FAILURE_EXPIRY_S = 24 * 3600
LOCK_WAIT_S = 900.0
_MAX_ENTRY_BYTES = 64 * 1024
_MAX_FILE_BYTES = 1_000_000_000
_ENTRY_SCHEMA = "cli_qualification_entry.v1"
_ENTRY_TYPES = ("qualified", "failed", "transient")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class QualificationError(ValueError):
    """A typed refusal; ``str(exc)`` is one of ``CODES`` (or ``CANCELLED``)."""


class QualificationReentered(RuntimeError):
    """``ensure_admitted`` was entered from inside a qualification operation."""


class OperationFailed(Exception):
    """An operation observed an identity or isolation violation: terminal for the key."""

    def __init__(self, reason, *, kind="identity"):
        if kind not in {"identity", "isolation"}:
            raise ValueError(kind)
        super().__init__(reason)
        self.reason, self.kind = str(reason), kind


class OperationTransient(Exception):
    """The operation said nothing about the CLI (the provider did not answer, a local fault)."""


# ------------------------------------------------------------------------------ the key

@dataclass(frozen=True)
class QualificationKey:
    """``(harness, platform, payload_identity, interpreter_identity?, help_digest, runtime_identity)``."""

    harness: str
    platform: str
    payload_sha256: str
    payload_kind: str
    help_sha256: str
    runtime: Mapping
    interpreter_sha256: str | None = None

    def __post_init__(self):
        if self.harness not in HARNESSES or self.platform not in PLATFORMS \
                or self.payload_kind not in PAYLOAD_KINDS:
            raise ValueError("cli qualification key has an unknown harness, platform or kind")
        for value in (self.payload_sha256, self.help_sha256):
            if not isinstance(value, str) or not _HEX64.fullmatch(value):
                raise ValueError("cli qualification key digest is not a sha256")
        if self.interpreter_sha256 is not None and not (
                isinstance(self.interpreter_sha256, str) and _HEX64.fullmatch(self.interpreter_sha256)):
            raise ValueError("cli qualification key interpreter digest is not a sha256")
        if not isinstance(self.runtime, Mapping):
            raise ValueError("cli qualification key runtime identity is not a mapping")

    def context(self, *, with_help=True):
        value = {"harness": self.harness, "platform": self.platform,
                 "payload_sha256": self.payload_sha256, "payload_kind": self.payload_kind,
                 "interpreter_sha256": self.interpreter_sha256, "runtime": dict(self.runtime)}
        if with_help:
            value["help_sha256"] = self.help_sha256
        return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _read_regular(path, *, follow_root=False):
    """The bytes of one regular file, opened ``O_NOFOLLOW`` (the path's last component is
    never a symlink), capped."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | (0 if follow_root else os.O_NOFOLLOW)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise QualificationError(UNAVAILABLE) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE_BYTES:
            raise QualificationError(UNAVAILABLE)
        digest = sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest(), stat.S_IMODE(info.st_mode)
    finally:
        os.close(fd)


def file_digest(path):
    """A native single binary's payload identity: the sha256 of that file, never a link."""
    return _read_regular(path)[0]


def tree_digest(closure: Mapping[str, os.PathLike | str]):
    """A script package's payload identity over its adapter-declared closure.

    ``closure`` maps a stable label (``package``, or a platform-dependency name) to a root
    directory. The digest is over the sorted ``(label/relative path, type, mode, sha256 or
    link text)`` of every entry. Symlinks are recorded by their link text and never
    followed; a symlinked root or any special file refuses.
    """
    entries = []
    for label in sorted(closure):
        root = Path(closure[label])
        try:
            info = os.lstat(root)
        except OSError as exc:
            raise QualificationError(UNAVAILABLE) from exc
        if not stat.S_ISDIR(info.st_mode):
            raise QualificationError(UNAVAILABLE)
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            for name in sorted(dirnames + filenames):
                path = Path(directory) / name
                relative = f"{label}/{path.relative_to(root).as_posix()}"
                info = os.lstat(path)
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISLNK(info.st_mode):
                    entries.append([relative, "link", 0, os.readlink(path)])
                elif stat.S_ISDIR(info.st_mode):
                    entries.append([relative, "dir", mode, ""])
                elif stat.S_ISREG(info.st_mode):
                    entries.append([relative, "file", mode, _read_regular(path)[0]])
                else:
                    raise QualificationError(UNAVAILABLE)
    return sha256(_canonical(sorted(entries))).hexdigest()


def detect_platform():
    """``linux-x64`` | ``linux-arm64`` (``-musl``); anything else is unsupported."""
    from . import agy_provenance

    try:
        name = agy_provenance.detect_platform().name
    except agy_provenance.ProvenanceError as exc:
        raise QualificationError(PLATFORM_UNSUPPORTED) from exc
    if name not in PLATFORMS:
        raise QualificationError(PLATFORM_UNSUPPORTED)
    return name


def runtime_identity(adapter_module=None):
    """``__version__`` plus the digests of this module and the adapter's own module."""
    package = Path(__file__).resolve().parent
    files = {name: _read_regular(package / name, follow_root=True)[0] for name in ROUTE_CORE}
    if adapter_module is not None:
        adapter = Path(adapter_module)
        files[adapter.name] = _read_regular(adapter, follow_root=True)[0]
    return {"version": __version__, "route_core": files}


# ----------------------------------------------------------------------- pinned probe

PROBE_ENV = {"LC_ALL": "C.UTF-8", "COLUMNS": "200", "TERM": "dumb", "NO_COLOR": "1",
             "PATH": "/usr/bin:/bin"}


def probe_env(home, suppressors=None):
    """The help probe's whole environment. The user's environment never reaches it; an
    adapter adds only its update/banner suppressors, which cannot override a pinned name."""
    env = {**PROBE_ENV, "HOME": str(home)}
    for name, value in (suppressors or {}).items():
        if name in env:
            raise ValueError(f"suppressor {name} would override the pinned probe environment")
        env[str(name)] = str(value)
    return env


def measure_help(probes: Sequence[Sequence[str]], *, home, suppressors=None, timeout_s=60.0,
                 run=subprocess.run):
    """The option-surface bytes: every probe argv, stdout and stderr together, in order.

    PR3's adapters pass a ``run`` that executes the verified bytes inside the owned profile.
    """
    out = []
    for argv in probes:
        try:
            proc = run(list(argv), env=probe_env(home, suppressors), cwd=str(home),
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout_s, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise QualificationError(UNAVAILABLE) from exc
        if proc.returncode != 0 or not proc.stdout:
            raise QualificationError(UNAVAILABLE)
        out.append(proc.stdout)  # never the argv: an install path is not part of the help
    return b"\0".join(out)


# ------------------------------------------------------------------ the candidate token

@dataclass(frozen=True)
class CandidateToken:
    """Set only by ``run_operations``; a launch under it is a qualification launch of ``key``."""

    key: QualificationKey


_CANDIDATE: contextvars.ContextVar = contextvars.ContextVar("cli_qualification_candidate", default=None)


def candidate():
    return _CANDIDATE.get()


def bind_candidate(fn: Callable):
    """``fn`` carrying the caller's candidate token across a thread hop (``ThreadPoolExecutor``
    does not copy the context)."""
    token = _CANDIDATE.get()

    def bound(*args, **kwargs):
        reset = _CANDIDATE.set(token)
        try:
            return fn(*args, **kwargs)
        finally:
            _CANDIDATE.reset(reset)

    return bound


# ------------------------------------------------------------------------ the outcome

# outcome -> (admission class it launches with, or None; the refusal code, or None).
# Recording-only release (Q1): only an identity failure, an unsafe store and a candidate
# launch of another key refuse here. PR3 adds the adapter-side refusals (verified-bytes
# mismatch, an unrecognised wrapper, an unsupported platform, a missing adapter).
OUTCOMES = {
    "candidate": ("qualification_candidate", None),
    "locally_qualified": ("locally_qualified", None),
    "absent": ("none", None),
    "opted_out": ("none", None),
    "transient": ("none", None),
    "failed_transient": ("none", None),
    "failed_identity": (None, FAILED),
    "store_unsafe": (None, STORE_UNSAFE),
    "candidate_mismatch": (None, UNQUALIFIED),
}


@dataclass(frozen=True)
class Lookup:
    outcome: str

    def __post_init__(self):
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown cli qualification outcome {self.outcome!r}")

    @property
    def admission_class(self):
        return OUTCOMES[self.outcome][0]

    @property
    def code(self):
        return OUTCOMES[self.outcome][1]

    @property
    def refuses(self):
        return self.code is not None


# ---------------------------------------------------------------------------- opt-out

def self_qualification_enabled(harness):
    """``[qualification.<harness>] self_qualification`` in the USER board config (default on).
    For ``gemini``, ``[agy] self_qualification`` also opts out. Any config error opts out."""
    from .advisor_board import config

    try:
        enabled = config.load_cli_self_qualification(harness)
        if harness == "gemini":
            enabled = enabled and config.load_agy_self_qualification()
        return enabled
    except Exception:  # noqa: BLE001 - a malformed config never enables first use
        return False


# ------------------------------------------------------------------------------ store

def read_machine_id(path="/etc/machine-id"):
    try:
        value = Path(path).read_text().strip()
    except OSError:
        return None
    return value if re.fullmatch(r"[0-9a-f]{32}", value) else None


def default_store_root(environ=None):
    environ = os.environ if environ is None else environ
    base = environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "phase-loop" / "cli-qualification"


class Store:
    """``<root>/hosts/<machine>/<harness>/``: one harness's entries on one host, its HMAC key
    and its lock. Directories 0700, files 0600, euid-owned, opened ``O_NOFOLLOW``; anything
    else makes the store unsafe. Each MAC covers the entry type, the euid, the machine-id,
    the harness and the LIVE key context, never the entry's own fields or filename.

    New and orthogonal to ``seat-jail-passes/`` and ``agy-qualification/``.
    """

    def __init__(self, harness, root=None, *, euid=None, machine_id=None):
        if harness not in HARNESSES:
            raise ValueError(f"unknown harness {harness!r}")
        self.harness = harness
        self.root = Path(root) if root is not None else default_store_root()
        self.euid = os.geteuid() if euid is None else euid
        self.machine_id = read_machine_id() if machine_id is None else machine_id

    @property
    def host_dir(self):
        machine = sha256(f"cli-qualification-host\0{self.machine_id}".encode()).hexdigest()[:32]
        return self.root / "hosts" / machine / self.harness

    def _chain(self):
        return (self.root, self.root / "hosts", self.host_dir.parent, self.host_dir)

    def _dir_ok(self, path):
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError:
            return False
        return (stat.S_ISDIR(info.st_mode) and info.st_uid == self.euid
                and stat.S_IMODE(info.st_mode) == 0o700)

    def status(self):
        """``absent`` | ``ok`` | ``unsafe``."""
        if self.machine_id is None:
            return "unsafe"
        for path in self._chain():
            state = self._dir_ok(path)
            if state is None:
                return "absent"
            if not state:
                return "unsafe"
        try:
            self._key()
        except FileNotFoundError:
            return "absent"
        except (OSError, ValueError):
            return "unsafe"
        return "ok"

    def create(self):
        if self.machine_id is None:
            raise QualificationError(UNAVAILABLE)
        for path in self._chain():
            if self._dir_ok(path) is None:
                try:
                    path.mkdir(mode=0o700, parents=path == self.root)
                except FileExistsError:
                    continue
                os.chmod(path, 0o700)
        if self.status() == "absent":
            try:
                self._write(self.host_dir / "key", secrets.token_bytes(32), exclusive=True)
            except FileExistsError:
                pass
        if self.status() != "ok":
            raise QualificationError(STORE_UNSAFE)

    def _read(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.euid
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > _MAX_ENTRY_BYTES):
                raise ValueError(STORE_UNSAFE)
            return os.read(fd, _MAX_ENTRY_BYTES + 1)
        finally:
            os.close(fd)

    def _write(self, path, data, *, exclusive=False):
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if exclusive:
            try:
                os.link(temporary, path)
            finally:
                os.unlink(temporary)
        else:
            os.replace(temporary, path)

    def _key(self):
        key = self._read(self.host_dir / "key")
        if len(key) != 32:
            raise ValueError(STORE_UNSAFE)
        return key

    def _context(self, entry_type, context):
        if entry_type not in _ENTRY_TYPES:
            raise ValueError(STORE_UNSAFE)
        return {**context, "type": entry_type, "euid": self.euid, "machine_id": self.machine_id,
                "store_harness": self.harness}

    def _path(self, entry_type, name_context):
        name = sha256(_canonical(self._context(entry_type, name_context))).hexdigest()
        return self.host_dir / f"{entry_type}-{name}.json"

    def _mac(self, key, entry_type, context, payload):
        return hmac.new(key, _canonical({"context": self._context(entry_type, context), "payload": payload}),
                        "sha256").hexdigest()

    @staticmethod
    def _name_context(key, *, with_help):
        return key.context(with_help=with_help)

    def put(self, entry_type, context, payload):
        if self.status() != "ok":
            raise QualificationError(STORE_UNSAFE)
        mac = self._mac(self._key(), entry_type, context, payload)
        self._write(self._path(entry_type, context),
                    _canonical({"schema": _ENTRY_SCHEMA, "type": entry_type, "payload": payload, "mac": mac}))

    def get(self, entry_type, context):
        """The entry's payload iff its MAC verifies against the LIVE context; else None."""
        if self.status() != "ok":
            return None
        try:
            raw = json.loads(self._read(self._path(entry_type, context)))
            if raw.get("schema") != _ENTRY_SCHEMA or raw.get("type") != entry_type:
                return None
            payload, mac = raw["payload"], raw["mac"]
            if not isinstance(payload, dict) or not isinstance(mac, str):
                return None
            if not hmac.compare_digest(mac, self._mac(self._key(), entry_type, context, payload)):
                return None
            return payload
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def remove(self, entry_types):
        removed = 0
        if self.status() != "ok":
            return removed
        for path in self.host_dir.iterdir():
            if path.name.split("-", 1)[0] in entry_types and path.suffix == ".json":
                path.unlink()
                removed += 1
        return removed

    def entries(self):
        if self.status() != "ok":
            return []
        return sorted(path.name.split("-", 1)[0] for path in self.host_dir.iterdir()
                      if path.suffix == ".json" and not path.name.startswith("."))

    @contextlib.contextmanager
    def lock(self, cancel_event=None, heartbeat=None, *, timeout_s=LOCK_WAIT_S, poll_s=0.1):
        """One ``flock`` per user, host and harness. The wait is bounded: a waiter that cannot
        acquire it within ``timeout_s`` refuses with the typed code instead of hanging."""
        fd = os.open(self.host_dir / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.euid or stat.S_IMODE(info.st_mode) != 0o600:
                raise QualificationError(STORE_UNSAFE)
            deadline = time.monotonic() + timeout_s
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise QualificationError(CANCELLED)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise QualificationError(UNAVAILABLE) from None
                    if heartbeat is not None:
                        heartbeat("cli_qualification_lock_wait")
                    time.sleep(poll_s)
            yield
        finally:
            os.close(fd)

    # -- typed entries -----------------------------------------------------------------
    def put_qualified(self, key):
        self.put("qualified", key.context(), {"operations": {op: "passed" for op in OPERATIONS}})

    def get_qualified(self, key):
        payload = self.get("qualified", key.context())
        if payload is None or payload.get("operations") != {op: "passed" for op in OPERATIONS}:
            return None
        return payload

    # A failure is keyed WITHOUT the help digest (it rides as MAC-bound payload), so an
    # identity failure refuses without executing anything, and a transient-derived one can
    # tell a help change apart from the same key.
    def put_failed(self, key, *, kind, operation, reason, now):
        self.put("failed", key.context(with_help=False),
                 {"kind": kind, "help_sha256": key.help_sha256, "operation": operation,
                  "reason": reason, "at": now})

    def get_failed(self, key):
        return self.get("failed", key.context(with_help=False))

    def note_transient(self, key, *, now):
        context = key.context(with_help=False)
        payload = self.get("transient", context) or {}
        count = payload.get("count") if isinstance(payload.get("count"), int) else 0
        self.put("transient", context, {"count": count + 1, "at": now})
        return count + 1

    def reset_transients(self, key):
        self._path("transient", key.context(with_help=False)).unlink(missing_ok=True)


# --------------------------------------------------------------- lookup and first use

def lookup(key, *, store=None, now=None):
    """Read-only admission of ``key``; never executes an operation.

    Under a candidate token it returns the candidate without reading config or the store.
    Otherwise the user opt-out comes first, then the store: an identity failure is sticky;
    a transient-derived failure expires after 24 h or when the help digest changes (every
    other key change is a different entry); a verified qualified entry admits.
    """
    token = _CANDIDATE.get()
    if token is not None:
        return Lookup("candidate" if token.key == key else "candidate_mismatch")
    if not self_qualification_enabled(key.harness):
        return Lookup("opted_out")
    store = store or Store(key.harness)
    state = store.status()
    if state == "unsafe":
        return Lookup("store_unsafe")
    if state == "absent":
        return Lookup("absent")
    now = time.time() if now is None else now
    failed = store.get_failed(key)
    if failed is not None:
        if failed.get("kind") != "transient":
            return Lookup("failed_identity")
        at = failed.get("at")
        if (failed.get("help_sha256") == key.help_sha256 and isinstance(at, (int, float))
                and now - at < TRANSIENT_FAILURE_EXPIRY_S):
            return Lookup("failed_transient")
    if store.get_qualified(key) is not None:
        return Lookup("locally_qualified")
    return Lookup("absent")


def run_operations(key, operations: Mapping[str, Callable[[], None]], *, cancel_event=None, heartbeat=None):
    """Every operation, in order, under a candidate token bound to ``key``."""
    if set(operations) != set(OPERATIONS):
        raise ValueError("an adapter must supply every qualification operation")
    reset = _CANDIDATE.set(CandidateToken(key))
    try:
        for operation in OPERATIONS:
            if cancel_event is not None and cancel_event.is_set():
                return {"status": "cancelled"}
            if heartbeat is not None:
                heartbeat(f"cli_qualification_{operation}")
            try:
                operations[operation]()
            except OperationFailed as exc:
                return {"status": "failed", "operation": operation, "kind": exc.kind, "reason": exc.reason}
            except Exception:  # noqa: BLE001 - an unexplained fault is never a pass
                return {"status": "transient", "operation": operation}
            if cancel_event is not None and cancel_event.is_set():
                return {"status": "cancelled"}
        return {"status": "passed"}
    finally:
        _CANDIDATE.reset(reset)


def ensure_admitted(key, operations, *, store=None, cancel_event=None, heartbeat=None,
                    lock_timeout_s=LOCK_WAIT_S, now=None):
    """``lookup``, and on ``absent`` the first-use path. Called only by the board preflight
    and ``phase-loop cli-qualification run`` (PR3); never from a spawn.

    The lookup runs again once the lock is held, so a waiter whose peer just qualified the
    key runs nothing. Cancellation writes nothing.
    """
    if _CANDIDATE.get() is not None:
        raise QualificationReentered("cli_qualification_reentered")
    if set(operations) != set(OPERATIONS):
        raise ValueError("an adapter must supply every qualification operation")
    store = store or Store(key.harness)
    first = lookup(key, store=store, now=now)
    if first.outcome != "absent":
        return first
    if store.machine_id is None:
        raise QualificationError(UNAVAILABLE)
    if store.status() == "absent":
        store.create()
    with store.lock(cancel_event, heartbeat, timeout_s=lock_timeout_s):
        again = lookup(key, store=store, now=now)
        if again.outcome != "absent":
            return again
        result = run_operations(key, operations, cancel_event=cancel_event, heartbeat=heartbeat)
        now = time.time() if now is None else now
        if result["status"] == "passed":
            store.put_qualified(key)
            store.reset_transients(key)
            return Lookup("locally_qualified")
        if result["status"] == "cancelled":
            raise QualificationError(CANCELLED)
        if result["status"] == "failed":
            store.put_failed(key, kind="identity", operation=result["operation"],
                             reason=result["reason"], now=now)
            return Lookup("failed_identity")
        if store.note_transient(key, now=now) >= MAX_TRANSIENT_ATTEMPTS:
            store.put_failed(key, kind="transient", operation=result.get("operation"),
                             reason="repeated_transient", now=now)
            store.reset_transients(key)
            return Lookup("failed_transient")
        return Lookup("transient")


# ------------------------------------------------------------------- candidate schema

_HEX64_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_PEP440_SCHEMA = {"type": "string",
                  "pattern": r"^[0-9]+(\.[0-9]+)*((a|b|rc)[0-9]+)?(\.post[0-9]+)?(\.dev[0-9]+)?(\+[a-z0-9.]+)?$"}
_ROUTE_CORE_NAMES = sorted({*ROUTE_CORE, "gemini_heartbeat.py", "agy_qualification.py", "agy_provenance.py"})

# ``cli_qualification_candidate.v1``: closed at every level. It never carries the interpreter
# hash, an HMAC, a machine-id, a hostname, a path, a username, environment, credentials or
# receipts. ``harness`` names every known harness here; PR6 narrows it to the adapters.
CANDIDATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "cli_qualification_candidate.v1",
    "type": "object",
    "additionalProperties": False,
    "required": ["harness", "platform", "version_label", "payload_sha256", "payload_kind",
                 "help_sha256", "runtime_identity", "agent_harness_version", "ops", "utc"],
    "properties": {
        "harness": {"enum": list(HARNESSES)},
        "platform": {"enum": list(PLATFORMS)},
        "version_label": {"type": "string", "pattern": r"^[A-Za-z0-9 ._()+-]{1,64}$"},
        "payload_sha256": _HEX64_SCHEMA,
        "payload_kind": {"enum": list(PAYLOAD_KINDS)},
        "help_sha256": _HEX64_SCHEMA,
        "runtime_identity": {
            "type": "object",
            "additionalProperties": False,
            "required": ["version", "route_core"],
            "properties": {
                "version": _PEP440_SCHEMA,
                "route_core": {
                    "type": "object",
                    "additionalProperties": False,
                    "minProperties": 1,
                    "properties": {name: _HEX64_SCHEMA for name in _ROUTE_CORE_NAMES},
                },
            },
        },
        "agent_harness_version": _PEP440_SCHEMA,
        "ops": {
            "type": "object",
            "additionalProperties": False,
            "required": list(OPERATIONS),
            "properties": {op: {"const": "passed"} for op in OPERATIONS},
        },
        "utc": {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$"},
    },
}


def validate_candidate(record):
    """Raise ``jsonschema.ValidationError`` unless ``record`` is a closed v1 candidate."""
    import jsonschema

    jsonschema.Draft202012Validator(CANDIDATE_SCHEMA).validate(record)


# ------------------------------------------------------------------------------- CLI

def cli_main(args):
    """``phase-loop cli-qualification {status,clear} --harness <h>``."""
    harness = args.qual_harness
    store = Store(harness)
    if args.action == "status":
        adapter = "adapter" if harness in ADAPTERS else "pending" if harness in PENDING_ADAPTERS else "none"
        print(json.dumps({"harness": harness, "adapter": adapter, "store": str(store.host_dir),
                          "store_status": store.status(), "entries": store.entries(),
                          "self_qualification": self_qualification_enabled(harness),
                          "runtime": runtime_identity()}, sort_keys=True))
        return 0
    removed = store.remove(_ENTRY_TYPES if args.qual_all else ("failed", "transient"))
    print(json.dumps({"harness": harness, "removed": removed}, sort_keys=True))
    return 0
