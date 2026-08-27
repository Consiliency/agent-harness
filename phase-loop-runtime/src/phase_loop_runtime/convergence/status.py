"""Ledger-only recovery status projection.

A snapshot projects nothing but :class:`RecoveredTrainState` plus the identity
of the log it was replayed from, so a restart with the same durable events
renders the same bytes. No runner cache, working tree, or side artifact is
consulted.

``verification_valid`` and ``approval_valid`` are **replay-derived ledger
facts**: they say what the recorded outcomes claimed, not what is true of the
world right now. Only a live ``ReconciliationVerdict`` carries fresh authority,
observations, and invalidation triggers. The JSON field names are unchanged for
consumers, and carry that same replay-derived meaning; the human render says so
in words, because a human reading "verification: valid" is the reader most
likely to mistake a replayed claim for a fresh one.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .event_log import RecoveredTrainState


@dataclass(frozen=True)
class TrainStatusSnapshot:
    train_id: str
    event_log_path: str
    last_event_offset: int
    pending_attempt_ids: tuple[str, ...]
    node_states: tuple[tuple[str, str], ...]
    verification_valid: bool
    approval_valid: bool
    ambiguities: tuple[str, ...]
    next_action: str


def _pending_id(node_id: str, attempt_id: str | None) -> str:
    """A pending attempt's identity, qualified by node.

    Two nodes may legitimately share an attempt id; projecting the bare id would
    collapse them into one opaque entry and hide a whole in-flight node.
    """

    return f"{node_id}:{attempt_id or '-'}"


def build_train_status(state: RecoveredTrainState, event_log_path: Path | str = "") -> TrainStatusSnapshot:
    pending = tuple(_pending_id(event.node_id, event.attempt_id) for event in state.pending_attempts)
    next_action = "reconcile exact authority" if not state.ambiguities and not pending else "resolve ambiguous or pending convergence state"
    return TrainStatusSnapshot(state.train_id, str(event_log_path), state.last_event_offset, pending, tuple(sorted((key, event.kind.value) for key, event in state.node_states.items())), state.verification_valid, state.approval_valid, state.ambiguities, next_action)


def _validity(value: bool) -> str:
    return "valid" if value else "invalid"


def render_train_status(snapshot: TrainStatusSnapshot, *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(asdict(snapshot), sort_keys=True)
    return "\n".join(
        (
            f"train-status: {snapshot.train_id}",
            f"event-log: {snapshot.event_log_path}",
            f"last-offset: {snapshot.last_event_offset}",
            f"pending-attempts: {', '.join(snapshot.pending_attempt_ids) or 'none'}",
            f"ambiguities: {', '.join(snapshot.ambiguities) or 'none'}",
            f"replay-derived verification: {_validity(snapshot.verification_valid)}",
            f"replay-derived approval: {_validity(snapshot.approval_valid)}",
            "  (replay-derived from the recorded outcomes; live authority comes",
            "   from a fresh reconciliation verdict, not from this projection)",
            f"next-action: {snapshot.next_action}",
        )
    )
