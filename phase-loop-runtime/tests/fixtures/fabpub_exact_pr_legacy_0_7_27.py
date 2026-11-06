"""Frozen source-level compatibility fixture for phase-loop-runtime 0.7.27.

These functions preserve the pre-overlay consumers relevant to the exact-PR
transition.  They intentionally know only raw evidence and the #1591
post-ambiguity observation fence.  Tests pin the complete file digest before
executing them.
"""
from __future__ import annotations

import hashlib
import json


def replay(evidence_bytes: bytes) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for line in evidence_bytes.decode("utf-8").splitlines():
        if line:
            record = json.loads(line)
            records[record["idempotency_key"]] = record
    return records


def epoch_blocked(evidence_bytes: bytes) -> bool:
    return any(
        record.get("state") == "outcome_ambiguous_blocked"
        for record in replay(evidence_bytes).values()
    )


def block_unsealed_owner(evidence_bytes: bytes, effect_key: str) -> tuple[bytes, bool]:
    current = replay(evidence_bytes).get(effect_key)
    if current is not None and current.get("state") in {
        "effect_terminal_observed",
        "outcome_ambiguous_blocked",
        "rejected_before_start",
        "no_effect_terminal_proven",
    }:
        return evidence_bytes, False
    row = {
        "evidence_reference": "unsealed-adapter-start-owner",
        "idempotency_key": effect_key,
        "schema": "BrokerEvidence.v1",
        "state": "outcome_ambiguous_blocked",
    }
    return evidence_bytes + (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"), True


def false_not_landed_rotation(observation_bytes: bytes, effect_key: str) -> None:
    for line in observation_bytes.decode("utf-8").splitlines():
        row = json.loads(line)
        if (
            row.get("idempotency_key") == effect_key
            and row.get("observed_state") == "effect_terminal_observed"
        ):
            raise PermissionError(
                "attested_not_landed refused by post-ambiguity observed effect "
                + hashlib.sha256(line.encode("utf-8")).hexdigest()
            )


def writer(evidence_bytes: bytes, provider) -> None:
    if epoch_blocked(evidence_bytes):
        raise PermissionError("epoch permanently blocked")
    provider()
