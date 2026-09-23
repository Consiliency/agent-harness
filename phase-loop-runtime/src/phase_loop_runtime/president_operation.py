"""The HARDEN-authorized president operation (PRESROUTE, v10 Phase 14; IF-0-PRESROUTE-1).

``public_board_president.v1`` is the president's OWN operation: its own brief, its own
completion grammar (per-finding ``FINDING <id>: BLOCKING|DEFERRED — <reason>`` lines and
a terminal ``FORCING DECISION: <decision>``, the grammar ``_valid_president_grammar``
already parses), and its own authorization identity, minted in
``advisor_board.backing.prepare_president_isolation_authorization`` beside -- never
through -- the review operation ``public_board_review.v1``. Running a ruling through the
review operation would hand the seat two contradictory terminal grammars (EC-HARDEN-5's
laundering refusal), which is why this operation exists.

``run_president_operation`` walks ``PRESIDENT_LADDER`` through ``invoke`` exactly as
``panel_invoker.invoke_president`` does and binds the result to the authorization
identity and to two digests:

* ``brief_digest = sha256(brief)`` over the exact brief bytes, and
* ``findings_digest = sha256("\\n".join(findings))`` over the findings in the order the
  president prompt carries them (``_president_prompt`` joins them the same way),

both lowercase hex. The brief is DIGESTED, not sent: the rung receives the president
prompt built from the findings, so a ruling can only name the findings it was shown.

The authorization is checked at this boundary BEFORE any rung is invoked, by exact
equality of its operation identity -- a foreign authorization (the review operation, a
different version, or any other identity) is refused with
``PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH`` and nothing is invoked, as ``spawn``
revalidates the review authorization before it launches.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .advisor_board.backing import PRESIDENT_OPERATION_V1
from .panel_invoker import (
    PRESIDENT_LADDER,
    PresidentPolicyError,
    PresidentRuling,
    invoke_president,
    president_finding_rulings,
    president_forcing_decision,
)

PRESIDENT_OPERATION = PRESIDENT_OPERATION_V1
PRESIDENT_RULING_SCHEMA = "president.ruling.v1"
PRESIDENT_RULING_FILENAME = "president.ruling.json"

# Refusal codes (frozen with IF-0-PRESROUTE-1).
PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH = "president_operation_authorization_mismatch"
PRESIDENT_FILL_HEARTBEAT_REFUSED = "president_fill_heartbeat_refused"
PRESIDENT_FILL_DIGEST_MISMATCH = "president_fill_digest_mismatch"


def brief_digest(brief: str) -> str:
    return hashlib.sha256(brief.encode("utf-8")).hexdigest()


def findings_digest(findings: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(findings).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PresidentOperationResult:
    ruling: PresidentRuling
    authorization_identity: str
    rung_index: int
    brief_digest: str
    findings_digest: str


def require_president_authorization(authorization: object) -> str:
    """Return the president identity, or refuse a foreign one before any use."""
    identity = getattr(authorization, "operation", None)
    # Exact equality only: a denylist, a substring, a stem prefix or a full-identity
    # prefix would each admit a foreign operation.
    if not isinstance(identity, str) or identity != PRESIDENT_OPERATION:
        raise PresidentPolicyError(
            PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH,
            f"the president operation requires a {PRESIDENT_OPERATION!r} authorization, "
            f"not {identity!r}",
        )
    return identity


def run_president_operation(
    *,
    brief: str,
    findings: Sequence[str],
    authorization: object,
    invoke: Callable[[str, str], Mapping[str, str]],
    max_substantive_rounds: int,
) -> PresidentOperationResult:
    identity = require_president_authorization(authorization)
    findings = tuple(findings)
    ruling = invoke_president(
        findings=findings, invoke=invoke, max_substantive_rounds=max_substantive_rounds
    )
    return PresidentOperationResult(
        ruling=ruling,
        authorization_identity=identity,
        rung_index=list(PRESIDENT_LADDER).index(ruling.model),
        brief_digest=brief_digest(brief),
        findings_digest=findings_digest(findings),
    )


def president_ruling_record(
    result: PresidentOperationResult, *, model_id: str | None = None
) -> dict[str, Any]:
    """The ``president.ruling.v1`` record (IF-0-PRESROUTE-1).

    ``model_id`` is the registry PIN the ruling rung resolved to on the landing board;
    without a board it defaults to the rung itself.
    """
    ruling = result.ruling
    return {
        "schema": PRESIDENT_RULING_SCHEMA,
        "authorization_identity": result.authorization_identity,
        "rung_index": result.rung_index,
        "model_id": model_id if model_id is not None else ruling.model,
        "format_reask_count": ruling.format_reasks,
        "brief_digest": result.brief_digest,
        "findings_digest": result.findings_digest,
        "forcing_decision": president_forcing_decision(ruling),
        "finding_rulings": [
            {"id": item.finding_id, "disposition": item.disposition, "reason": item.reason}
            for item in president_finding_rulings(ruling)
        ],
    }


def board_president_ruling_record(
    ruling: PresidentRuling, findings: Sequence[str], board: object, *, brief: str
) -> dict[str, Any]:
    """The record for a ruling a landing board obtained, with the rung's registry PIN."""
    from .president_adapter import seat_for_rung

    seat = seat_for_rung(board, ruling.model)  # type: ignore[arg-type]
    result = PresidentOperationResult(
        ruling=ruling,
        authorization_identity=PRESIDENT_OPERATION,
        rung_index=list(PRESIDENT_LADDER).index(ruling.model),
        brief_digest=brief_digest(brief),
        findings_digest=findings_digest(tuple(findings)),
    )
    return president_ruling_record(result, model_id=seat.model if seat is not None else None)


__all__ = [
    "PRESIDENT_OPERATION",
    "PRESIDENT_RULING_SCHEMA",
    "PRESIDENT_RULING_FILENAME",
    "PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH",
    "PRESIDENT_FILL_HEARTBEAT_REFUSED",
    "PRESIDENT_FILL_DIGEST_MISMATCH",
    "PresidentOperationResult",
    "brief_digest",
    "findings_digest",
    "require_president_authorization",
    "run_president_operation",
    "president_ruling_record",
    "board_president_ruling_record",
]
