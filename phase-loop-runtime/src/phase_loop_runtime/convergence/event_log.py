"""Coordinator-owned, metadata-only convergence event log.

The log is an append-only JSONL ledger of :class:`CoordinatorEvent` records. It
is the sole durable reconstruction input for the convergence runtime: a restart
replays these bytes and nothing else, so every append must survive a crash and
every read must refuse to launder corruption into apparent success.

Durability contract for one append:

* the payload is written with a fully drained ``os.write`` loop, so a short
  write can never commit a truncated record;
* the file is ``fsync``-ed before the call returns, and the parent directory is
  ``fsync``-ed as well whenever the append is what created the directory entry
  (a POSIX directory entry is not durable until its directory is synced);
* an exclusive ``flock`` serializes writers *across processes*, so the
  read-check-append sequence is linearizable rather than merely thread-safe;
* a torn final record left by a crashed writer is truncated under that same
  lock before the new record is appended, so the next append is readable
  instead of being concatenated onto a half-written line.

Every newline-terminated record is committed and must parse. Only an
unterminated final fragment can be repaired as an interrupted append.
"""
from __future__ import annotations

import fcntl
import errno
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from phase_loop_runtime.train_ledger import CoordinatorEvent, CoordinatorEventKind

_MAX_RECORD_BYTES = 64 * 1024
_LOCK = threading.Lock()

#: Ambiguity reasons folded by :func:`recover_train_state`. They are distinct
#: strings on purpose: a caller must be able to tell a schema/model version
#: mismatch from two trains sharing one log, because the remedies differ.
_MIXED_VERSIONS = "mixed event schema or model versions"
_MIXED_TRAINS = "mixed train identities in one log"
_EPOCH_REGRESSION = "epoch regression"
_CONFLICTING_DUPLICATE = "conflicting duplicate event"
_OUTCOME_WITHOUT_INTENT = "outcome without intent"
_AMBIGUOUS_PROVIDER = "ambiguous provider outcome"


@dataclass(frozen=True)
class RecoveredTrainState:
    train_id: str
    node_states: dict[str, CoordinatorEvent] = field(default_factory=dict)
    pending_attempts: tuple[CoordinatorEvent, ...] = ()
    latest_epoch: int | None = None
    verification_valid: bool = False
    approval_valid: bool = False
    ambiguities: tuple[str, ...] = ()
    last_event_offset: int = -1


def default_convergence_event_log_path(coordinator_root: Path, train_id: str) -> Path:
    if not train_id or train_id in {".", ".."} or any(c in train_id for c in ("/", "\\", "\0")):
        raise ValueError("train identity must be one nonempty path component")
    path = coordinator_root / "convergence" / f"train-{train_id}.events.jsonl"
    _reject_phase_loop(path)
    root = coordinator_root.resolve()
    parent = root / "convergence"
    candidate = parent / path.name
    if parent.is_symlink() or candidate.is_symlink() or not candidate.resolve().is_relative_to(parent):
        raise ValueError("convergence storage descendants cannot be symlinks")
    return path


def _reject_phase_loop(path: Path) -> None:
    if ".phase-loop" in path.parts or ".phase-loop" in path.resolve().parts:
        raise ValueError("convergence event logs cannot be stored under .phase-loop")


def _open_log(path: Path, *, create: bool) -> tuple[int, int]:
    """Bind canonical storage once; its owner must not relocate bound objects."""

    parent = path.parent.resolve()
    if ".phase-loop" in path.parts:
        raise ValueError("convergence event logs cannot be stored under .phase-loop")
    _reject_phase_loop(parent / path.name)
    root = parent
    missing = []
    while not root.exists():
        if not create:
            raise FileNotFoundError(path)
        missing.append(root.name)
        root = root.parent
    reference = root.stat()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    traversal_flags = (
        getattr(os, "O_SEARCH", getattr(os, "O_PATH", os.O_RDONLY))
        | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    parent_fd = None
    try:
        parent_fd = os.open(root.anchor, traversal_flags)
        for name in root.parts[1:]:
            next_fd = os.open(name, traversal_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        opened = os.fstat(parent_fd)
        if (opened.st_dev, opened.st_ino) != (reference.st_dev, reference.st_ino):
            raise ValueError("convergence storage changed during binding")
        next_fd = os.open(".", directory_flags, dir_fd=parent_fd)
        os.close(parent_fd)
        parent_fd = next_fd
        for name in reversed(missing):
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except FileExistsError:
                pass
            next_fd = os.open(name, directory_flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND if create else os.O_RDONLY
        fd = os.open(path.name, flags | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        return fd, parent_fd
    except BaseException as exc:
        if parent_fd is not None:
            os.close(parent_fd)
        if isinstance(exc, OSError) and exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ValueError("convergence storage cannot follow a replaced path") from exc
        raise


def _key(event: CoordinatorEvent) -> tuple[str, str, str | None, int | None]:
    return (event.train_id, event.node_id, event.attempt_id, event.epoch)


def _payload(event: CoordinatorEvent) -> bytes:
    value = asdict(event)
    value["kind"] = event.kind.value
    for name in ("owned_paths", "upstream_dep_shas", "seat_outcomes"):
        value[name] = list(value[name])
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > _MAX_RECORD_BYTES:
        raise ValueError("convergence event exceeds metadata-only size limit")
    return raw


def _write_fully(fd: int, raw: bytes) -> None:
    """Drain ``raw`` into ``fd``; a short ``os.write`` must never commit a stub."""

    written = 0
    while written < len(raw):
        chunk = os.write(fd, raw[written:])
        if chunk <= 0:  # pragma: no cover - defensive against a stalled device
            raise OSError("convergence event append made no progress")
        written += chunk


def _durable_records(raw: bytes) -> tuple[int, tuple[CoordinatorEvent, ...]]:
    """The durable prefix length of ``raw`` and the records it holds.

    Only the unterminated fragment after the last LF may be torn. Every complete
    line is decoded independently and malformed committed bytes are refused.
    """

    end = raw.rfind(b"\n") + 1
    events: list[CoordinatorEvent] = []
    for index, line in enumerate(raw[:end].split(b"\n")[:-1]):
        if not line.strip():
            continue
        try:
            events.append(_event(json.loads(line.decode("utf-8"))))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"malformed convergence event at line {index + 1}") from exc
    return end, tuple(events)


def _read_all(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _append(path: Path, event: CoordinatorEvent, *, require_intent: bool) -> None:
    """Durably commit ``event`` under a cross-process exclusive lock.

    Reading the existing records, deciding idempotence versus conflict, repairing
    a torn tail, and writing the new record all happen while the same ``flock``
    is held, so two coordinators appending concurrently cannot interleave a
    check with the other's write.
    """

    raw = _payload(event)
    with _LOCK:
        fd, parent_fd = _open_log(path, create=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            raw_existing = _read_all(fd)
            keep, existing = _durable_records(raw_existing)
            already_recorded = _is_already_recorded(existing, event, require_intent=require_intent)
            if keep != len(raw_existing):
                # Truncate the torn final record so this append lands on a clean
                # boundary instead of being concatenated onto a half-written line.
                os.ftruncate(fd, keep)
                os.fsync(fd)
            if already_recorded:
                return
            _write_fully(fd, raw)
            os.fsync(fd)
            os.fsync(parent_fd)
        finally:
            os.close(fd)
            os.close(parent_fd)


def _is_already_recorded(
    existing: tuple[CoordinatorEvent, ...],
    event: CoordinatorEvent,
    *,
    require_intent: bool,
) -> bool:
    """True when ``event`` is an idempotent replay; raise when it conflicts.

    Exact ``(train_id, node_id, attempt_id, epoch)`` keys govern the fold, so an
    identical replay is a no-op while a same-key record whose payload differs is
    a divergence the log refuses to hold two answers for.
    """

    key = _key(event)
    if require_intent and not any(
        item.kind is CoordinatorEventKind.INTENT and _key(item) == key for item in existing
    ):
        raise ValueError("outcome has no matching intent")
    for item in existing:
        if item.kind is not event.kind or _key(item) != key:
            continue
        if item == event:
            return True
        raise ValueError(
            f"conflicting duplicate {event.kind.value} for an already-recorded exact key"
        )
    return False


def record_intent(path: Path, event: CoordinatorEvent) -> None:
    if event.kind is not CoordinatorEventKind.INTENT:
        raise ValueError("record_intent requires an intent event")
    _append(path, event, require_intent=False)


def record_outcome(path: Path, event: CoordinatorEvent) -> None:
    if event.kind is not CoordinatorEventKind.OUTCOME:
        raise ValueError("record_outcome requires an outcome event")
    _append(path, event, require_intent=True)


def _event(value: dict) -> CoordinatorEvent:
    if not isinstance(value, dict):
        raise ValueError("convergence event must be an object")
    value = dict(value)
    collections = ("owned_paths", "upstream_dep_shas", "seat_outcomes")
    try:
        value["kind"] = CoordinatorEventKind(value["kind"])
        for name in collections:
            items = value.get(name, [])
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValueError("convergence event collection must contain strings")
            value[name] = tuple(items)
        for name, item in value.items():
            if name in collections:
                continue
            if name == "epoch":
                if item is not None and type(item) is not int:
                    raise ValueError("convergence epoch must be an integer")
            elif item is not None and not isinstance(item, str):
                raise ValueError("convergence event metadata must be text")
        return CoordinatorEvent(**value)
    except (KeyError, TypeError) as exc:
        raise ValueError("malformed convergence event fields") from exc


def _parse(text: str) -> tuple[CoordinatorEvent, ...]:
    return _durable_records(text.encode("utf-8"))[1]


def read_convergence_events(path: Path) -> tuple[CoordinatorEvent, ...]:
    """Replay ``path`` without mutating a byte of it.

    An unterminated fragment is ignored and repaired only by the next append.
    Complete malformed records are refused, and every reader stays byte-neutral.
    """

    try:
        fd, parent_fd = _open_log(path, create=False)
    except FileNotFoundError:
        return ()
    try:
        return _durable_records(_read_all(fd))[1]
    finally:
        os.close(fd)
        os.close(parent_fd)


def recover_train_state(events: Iterable[CoordinatorEvent]) -> RecoveredTrainState:
    values = tuple(events)
    if not values:
        return RecoveredTrainState(train_id="")
    train_id = values[0].train_id
    ambiguities: list[str] = []
    intents: dict[tuple[str, str, str | None, int | None], CoordinatorEvent] = {}
    outcomes: dict[tuple[str, str, str | None, int | None], CoordinatorEvent] = {}
    node_states: dict[str, CoordinatorEvent] = {}
    versions = {
        (event.event_schema_version, event.transition_model_version, event.invalidation_model_version)
        for event in values
    }
    if len(versions) != 1:
        ambiguities.append(_MIXED_VERSIONS)
    if any(event.train_id != train_id for event in values):
        ambiguities.append(_MIXED_TRAINS)
    latest_epoch: int | None = None
    for event in values:
        if event.epoch is not None:
            if latest_epoch is not None and event.epoch < latest_epoch:
                ambiguities.append(_EPOCH_REGRESSION)
            latest_epoch = max(latest_epoch or event.epoch, event.epoch)
        target = intents if event.kind is CoordinatorEventKind.INTENT else outcomes
        key = _key(event)
        if key in target and target[key] != event:
            ambiguities.append(_CONFLICTING_DUPLICATE)
        target[key] = event
        # Replay order decides the fold: the last durable event of either kind
        # per node is that node's recovered state.
        node_states[event.node_id] = event
    for key, outcome in outcomes.items():
        if key not in intents:
            ambiguities.append(_OUTCOME_WITHOUT_INTENT)
        if outcome.blocker_reason and "ambiguous" in outcome.blocker_reason.lower():
            ambiguities.append(_AMBIGUOUS_PROVIDER)
    pending = tuple(event for key, event in intents.items() if key not in outcomes)
    verification_valid = (
        bool(outcomes)
        and not ambiguities
        and all(event.verification_digest for event in outcomes.values())
    )
    approval_valid = (
        bool(outcomes)
        and not ambiguities
        and all(event.seat_outcomes for event in outcomes.values())
    )
    return RecoveredTrainState(
        train_id,
        node_states,
        pending,
        latest_epoch,
        verification_valid,
        approval_valid,
        tuple(dict.fromkeys(ambiguities)),
        len(values) - 1,
    )
