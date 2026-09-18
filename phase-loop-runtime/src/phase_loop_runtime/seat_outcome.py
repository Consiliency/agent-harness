"""Dependency-neutral durable advisor seat outcomes."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SeatOutcomeRecord:
    """Metadata-only durable terminal outcome for one requested advisor seat.

    FAB (Consiliency/agent-harness#191) activation, piece 2 — ADDITIVE fields
    (`verdict`, `finding_ids`, `seat_instance_id`), all keyword-defaulted so
    every existing positional caller (e.g. `test_convergence_seat_lifecycle`)
    and every non-FAB serialization stays byte-for-byte identical when they are
    left unset:

      * `verdict` — the seat's structured `terminal_verdict(...)` output
        (`AGREE`/`PARTIALLY AGREE`/`DISAGREE`), captured by the FAB panel
        wrapper AT INVOCATION and persisted to the durable run-store ledger.
        FAB's gate binds a provenance seat's self-reported verdict AGAINST this
        durable value (design v4 #2) — the provenance verdict is never trusted
        on its own.
      * `finding_ids` — the finding ids this seat logged, so the gate can bind
        a provenance seat's `finding_ids` to what the seat durably recorded
        (design v5 #2), not merely to a matching verdict.
      * `seat_instance_id` — a UNIQUE per-invocation seat-INSTANCE id (design
        v6 #1). `seat_key` is explicitly NON-unique (two same-vendor seats share
        it), so FAB keys completeness/verdict/finding cross-checks on this
        instance id, never on `seat_key`. `None` for non-FAB callers that never
        allocate one.
    """

    seat_key: str
    vendor_leg: str
    required: bool
    status: str
    attempt_id: str
    epoch: int
    artifact_digest: str
    completed_at: str
    evidence_digest: str
    reason: str | None = None
    verdict: str | None = None
    finding_ids: tuple[str, ...] = ()
    seat_instance_id: str | None = None


def serialize_seat_outcome(record: SeatOutcomeRecord) -> str:
    """Return stable metadata-only JSON; raw review text is intentionally absent.

    The FAB-additive keys (`verdict`, `finding_ids`, `seat_instance_id`) are
    emitted ONLY when set to a non-default value, so a record constructed the
    legacy way (all three unset) serializes byte-for-byte as before — the sole
    production writer of this format is FAB's own `append_seat_outcome`, and a
    non-FAB record must never gain new bytes it never carried (byte-neutrality).
    """
    payload = {
        "artifact_digest": record.artifact_digest,
        "attempt_id": record.attempt_id,
        "completed_at": record.completed_at,
        "epoch": record.epoch,
        "evidence_digest": record.evidence_digest,
        "reason": record.reason,
        "required": record.required,
        "seat_key": record.seat_key,
        "status": record.status,
        "vendor_leg": record.vendor_leg,
    }
    if record.verdict is not None:
        payload["verdict"] = record.verdict
    if record.finding_ids:
        payload["finding_ids"] = list(record.finding_ids)
    if record.seat_instance_id is not None:
        payload["seat_instance_id"] = record.seat_instance_id
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
