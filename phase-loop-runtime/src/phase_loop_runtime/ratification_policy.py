"""Typed per-gate ratification policies and a pure evaluator.

The public contract includes ``RatificationPolicy``, ``RatificationDecision``,
``BoardFacts``, ``DEFAULT_RATIFICATION_POLICIES``, ``GATES``, ``board_facts_from``,
and ``evaluate_ratification``. Policies set vendor and lens floors, consensus
mode (unanimous or majority), and shortfall handling (escalate or proceed_degraded).

``board_facts_from`` projects distinct vendors and lenses from the composed board;
the caller supplies agreeing and usable-reviewer counts. ``evaluate_ratification``
caps the vendor count at the usable-reviewer count, checks the floors and consensus,
and returns a decision without launching seats or doing I/O. These aggregate facts
do not identify which vendor supplied each usable verdict.

Escalation produces a non-human review-gate hold. Proceeding degraded requests a
durable audit record from the caller; the evaluator itself does not write it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The gates a ratification policy can be resolved for.
GATES: tuple[str, ...] = ("plan-ratify", "design-ratify", "pre-merge-CR", "release-dispatch")

# Agreement modes among the usable reviewers. Quorum COUNT is `required_vendors`;
# this enum is only how strict the agreement among the seated reviewers must be.
CONSENSUS_MODES: tuple[str, ...] = ("unanimous", "majority")

# Shortfall dials. Neither ever sets human_required (autonomy-first invariant).
ON_SHORTFALL: tuple[str, ...] = ("escalate", "proceed_degraded")

# Decision statuses the evaluator returns.
RATIFIED = "ratified"
ESCALATE = "escalate"
PROCEED_DEGRADED = "proceed_degraded"


@dataclass(frozen=True)
class RatificationPolicy:
    """The strict typed per-gate policy (IF-0-POLICY-1)."""

    required_vendors: int
    required_lens_coverage: int
    required_consensus: str
    on_shortfall: str

    def __post_init__(self) -> None:
        if not isinstance(self.required_vendors, int) or self.required_vendors < 1:
            raise ValueError(f"required_vendors must be an int >= 1: {self.required_vendors!r}")
        if not isinstance(self.required_lens_coverage, int) or self.required_lens_coverage < 1:
            raise ValueError(
                f"required_lens_coverage must be an int >= 1: {self.required_lens_coverage!r}"
            )
        if self.required_consensus not in CONSENSUS_MODES:
            raise ValueError(
                f"required_consensus {self.required_consensus!r} not in {CONSENSUS_MODES}"
            )
        if self.on_shortfall not in ON_SHORTFALL:
            raise ValueError(f"on_shortfall {self.on_shortfall!r} not in {ON_SHORTFALL}")

    def to_json(self) -> dict[str, Any]:
        return {
            "required_vendors": self.required_vendors,
            "required_lens_coverage": self.required_lens_coverage,
            "required_consensus": self.required_consensus,
            "on_shortfall": self.on_shortfall,
        }


# Per-gate defaults. Plan/design ratification leans autonomy-first
# (``proceed_degraded`` — a plan is not held hostage to reviewer availability); the
# merge/release gates demand a full cross-vendor board and ``escalate`` (a NON-human
# hold) on shortfall. A per-repo ``.consiliency/manifest.json`` may dial any of
# these via :func:`phase_loop_runtime.gate_posture.resolve_ratification_policy`.
DEFAULT_RATIFICATION_POLICIES: dict[str, RatificationPolicy] = {
    "plan-ratify": RatificationPolicy(2, 2, "majority", "proceed_degraded"),
    "design-ratify": RatificationPolicy(2, 2, "majority", "proceed_degraded"),
    "pre-merge-CR": RatificationPolicy(3, 3, "majority", "escalate"),
    "release-dispatch": RatificationPolicy(3, 3, "unanimous", "escalate"),
}


@dataclass(frozen=True)
class BoardFacts:
    """The ACHIEVED board facts the pure evaluator reads.

    ``distinct_vendors`` / ``lens_coverage`` describe independence; ``agreeing`` /
    ``reviewing`` are the usable-reviewer agreement counts (``agreeing`` legs
    returned a terminal AGREE out of ``reviewing`` usable legs). ``reviewed_sha``
    binds these facts to the exact reviewed commit (#88 SHA-binding) so a consumer
    can reject a verdict computed against a different head.
    """

    distinct_vendors: int
    lens_coverage: int
    agreeing: int
    reviewing: int
    reviewed_sha: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "distinct_vendors": self.distinct_vendors,
            "lens_coverage": self.lens_coverage,
            "agreeing": self.agreeing,
            "reviewing": self.reviewing,
        }
        if self.reviewed_sha is not None:
            payload["reviewed_sha"] = self.reviewed_sha
        return payload


def consensus_met(mode: str, *, agreeing: int, reviewing: int) -> bool:
    """True iff the usable reviewers' agreement satisfies ``mode``.

    ``unanimous`` — every usable reviewer AGREE'd (and at least one reviewed);
    ``majority`` — strictly more than half of the usable reviewers AGREE'd. With
    zero usable reviewers there is no consensus (no review happened).
    """
    if reviewing <= 0:
        return False
    if mode == "unanimous":
        return agreeing >= reviewing
    if mode == "majority":
        return agreeing * 2 > reviewing
    return False


def board_facts_from(
    board: Any,
    *,
    agreeing: int,
    reviewing: int,
    reviewed_sha: str | None = None,
) -> BoardFacts:
    """Project a composed ``Board`` into :class:`BoardFacts`.

    Reads the frozen ``advisor_board`` surfaces (imported, never edited):
    ``board_independence(board).distinct_vendors`` for cross-vendor independence and
    the distinct-lens count over the board's seats for lens coverage (composition
    exposes ``distinct_vendors`` but not a lens count — computed here, in POLICY's
    own file, never by adding a helper to SANDBOX's ``composition.py``). The
    ``agreeing`` / ``reviewing`` counts are supplied by the caller (they come from
    the panel verdicts, not the static board shape).
    """
    from .advisor_board.composition import board_independence

    distinct_vendors = board_independence(board).distinct_vendors
    lens_coverage = len({seat.lens for seat in board.seats if seat.lens})
    return BoardFacts(
        distinct_vendors=distinct_vendors,
        lens_coverage=lens_coverage,
        agreeing=agreeing,
        reviewing=reviewing,
        reviewed_sha=reviewed_sha,
    )


@dataclass(frozen=True)
class RatificationDecision:
    """The pure evaluator's verdict + its durable audit shape."""

    gate: str
    status: str  # RATIFIED | ESCALATE | PROCEED_DEGRADED
    satisfied: bool
    shortfalls: tuple[str, ...]
    policy: RatificationPolicy
    facts: BoardFacts

    @property
    def blocks(self) -> bool:
        """True iff this decision holds promotion (an ``escalate`` shortfall).

        A NON-human hold: the consumer turns this into a ``review_gate_block``,
        NEVER a ``human_required`` grant (autonomy-first invariant)."""
        return self.status == ESCALATE

    def to_audit(self) -> dict[str, Any]:
        """The durable audit record a consumer persists.

        For ``proceed_degraded`` this is the paper trail that a degraded board was
        knowingly accepted; for ``escalate`` it is the actionable detail of what
        fell short; for ``ratified`` it records the clean pass.
        """
        return {
            "kind": "ratification_decision",
            "gate": self.gate,
            "status": self.status,
            "satisfied": self.satisfied,
            "shortfalls": list(self.shortfalls),
            "policy": self.policy.to_json(),
            "facts": self.facts.to_json(),
        }


def _effective_vendors(facts: BoardFacts) -> int:
    """Vendors that count toward the independence quorum: distinct SEATED vendors
    capped at the number of USABLE reviewing legs. A vendor that produced no usable
    review cannot vouch for independence, so it must not satisfy ``required_vendors``
    (otherwise the gate fails OPEN on a seated-but-silent board)."""
    return min(facts.distinct_vendors, max(facts.reviewing, 0))


def evaluate_ratification(
    policy: RatificationPolicy,
    facts: BoardFacts,
    *,
    gate: str = "",
) -> RatificationDecision:
    """PURE: decide whether ``facts`` ratify a promotion under ``policy``.

    Computes the shortfalls (vendors / lens_coverage / consensus) and, when any is
    present, applies ``policy.on_shortfall`` (``escalate`` -> a NON-human hold;
    ``proceed_degraded`` -> proceed with an audit record). No IO, no board
    composition, no CLI — safe to unit-test with plain objects.

    The vendor quorum is enforced against the number of vendors that actually
    produced a USABLE review, not merely the number seated: a seat that returned
    no usable review (empty/timeout/degraded — the normal contention condition)
    cannot vouch for independence. The effective vendor count is therefore capped
    at ``reviewing`` (``min(distinct_vendors, reviewing)``); without this cap a
    fully seated board whose legs mostly dropped would fail OPEN — ratifying an
    N-vendor gate on a single usable review.
    """
    shortfalls: list[str] = []
    if _effective_vendors(facts) < policy.required_vendors:
        shortfalls.append("vendors")
    if facts.lens_coverage < policy.required_lens_coverage:
        shortfalls.append("lens_coverage")
    if not consensus_met(policy.required_consensus, agreeing=facts.agreeing, reviewing=facts.reviewing):
        shortfalls.append("consensus")

    if not shortfalls:
        status = RATIFIED
        satisfied = True
    else:
        # on_shortfall is validated to be exactly escalate | proceed_degraded.
        status = ESCALATE if policy.on_shortfall == "escalate" else PROCEED_DEGRADED
        satisfied = False
    return RatificationDecision(
        gate=gate,
        status=status,
        satisfied=satisfied,
        shortfalls=tuple(shortfalls),
        policy=policy,
        facts=facts,
    )


def shortfall_detail(decision: RatificationDecision) -> str:
    """Human/agent-readable, actionable description of a shortfall — the text an
    ``escalate`` block or a ``proceed_degraded`` audit note carries so a non-human
    repair knows exactly what to authenticate/add."""
    p, f = decision.policy, decision.facts
    parts: list[str] = []
    if "vendors" in decision.shortfalls:
        parts.append(
            f"usable reviewer vendors {_effective_vendors(f)} "
            f"(distinct seated {f.distinct_vendors}, usable legs {f.reviewing}) "
            f"< required {p.required_vendors}"
        )
    if "lens_coverage" in decision.shortfalls:
        parts.append(
            f"review lens coverage {f.lens_coverage} < required {p.required_lens_coverage}"
        )
    if "consensus" in decision.shortfalls:
        parts.append(
            f"{p.required_consensus} consensus not met ({f.agreeing}/{f.reviewing} reviewers agreed)"
        )
    return "; ".join(parts) if parts else "policy satisfied"


__all__ = [
    "GATES",
    "CONSENSUS_MODES",
    "ON_SHORTFALL",
    "RATIFIED",
    "ESCALATE",
    "PROCEED_DEGRADED",
    "RatificationPolicy",
    "DEFAULT_RATIFICATION_POLICIES",
    "BoardFacts",
    "RatificationDecision",
    "consensus_met",
    "board_facts_from",
    "evaluate_ratification",
    "shortfall_detail",
]
