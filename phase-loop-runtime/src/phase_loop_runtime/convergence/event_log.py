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

Corruption before the final record is never repaired and never tolerated: only
the last line may be torn, because only the last line can be an interrupted
in-progress append.
"""
from __future__ import annotations

import fcntl
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
    path = coordinator_root / "convergence" / f"train-{train_id}.events.jsonl"
    _reject_phase_loop(path)
    return path


def _reject_phase_loop(path: Path) -> None:
    if ".phase-loop" in path.parts:
        raise ValueError("convergence event logs cannot be stored under .phase-loop")


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


def _durable_prefix(raw: bytes) -> int:
    """Bytes of ``raw`` that form whole, parseable records.

    Only the final record may be torn -- it is the sole record an interrupted
    append can have been writing. Any earlier malformed line is real corruption
    and is reported rather than silently truncated away.
    """

    end = raw.rfind(b"\n") + 1
    complete = raw[:end]
    lines = [line for line in complete.split(b"\n") if line.strip()]
    for index, line in enumerate(lines):
        try:
            _event(json.loads(line.decode("utf-8")))
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            if index == len(lines) - 1:
                # A complete-but-unparseable *final* record is still a torn
                # append: drop exactly that record and keep everything before it.
                return end - (len(line) + 1)
            raise ValueError(
                f"malformed convergence event at line {index + 1}"
            ) from exc
    return end


def _repair_torn_tail(fd: int) -> None:
    """Truncate a torn final record so the next append lands on a clean boundary."""

    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        return
    keep = _durable_prefix(raw)
    if keep != len(raw):
        os.ftruncate(fd, keep)
        os.fsync(fd)


def _existing_events(fd: int) -> tuple[CoordinatorEvent, ...]:
    """Replay the already-durable records held open by ``fd``."""

    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    return _parse(b"".join(chunks).decode("utf-8"))


def _append(path: Path, event: CoordinatorEvent, *, require_intent: bool) -> None:
    """Durably commit ``event`` under a cross-process exclusive lock.

    Reading the existing records, deciding idempotence versus conflict, repairing
    a torn tail, and writing the new record all happen while the same ``flock``
    is held, so two coordinators appending concurrently cannot interleave a
    check with the other's write.
    """

    _reject_phase_loop(path)
    raw = _payload(event)
    parent = path.parent
    created_parent = not parent.exists()
    if created_parent:
        parent.mkdir(parents=True, exist_ok=True)
    created_entry = created_parent or not path.exists()
    with _LOCK:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            _repair_torn_tail(fd)
            existing = _existing_events(fd)
            if _is_already_recorded(existing, event, require_intent=require_intent):
                return
            _write_fully(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
    if created_entry:
        _fsync_directory(parent)


def _fsync_directory(directory: Path) -> None:
    """Make a newly created directory entry durable, tolerating platforms without it."""

    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:  # pragma: no cover - directory fds are unavailable on some hosts
        return
    try:
        os.fsync(dir_fd)
    except OSError:  # pragma: no cover - defensive
        pass
    finally:
        os.close(dir_fd)


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
    value = dict(value)
    value["kind"] = CoordinatorEventKind(value["kind"])
    for name in ("owned_paths", "upstream_dep_shas", "seat_outcomes"):
        value[name] = tuple(value.get(name, ()))
    return CoordinatorEvent(**value)


def _parse(text: str) -> tuple[CoordinatorEvent, ...]:
    lines = [line for line in text.splitlines() if line.strip()]
    events: list[CoordinatorEvent] = []
    for index, line in enumerate(lines):
        try:
            events.append(_event(json.loads(line)))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            if index == len(lines) - 1:
                break
            raise ValueError(f"malformed convergence event at line {index + 1}") from exc
    return tuple(events)


def read_convergence_events(path: Path) -> tuple[CoordinatorEvent, ...]:
    """Replay ``path`` without mutating a byte of it.

    A malformed *final* record is tolerated -- a concurrent writer's in-progress
    append looks exactly like that -- and is repaired only by the next append,
    so every reader stays byte-neutral.
    """

    if not path.exists():
        return ()
    return _parse(path.read_text(encoding="utf-8"))


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
