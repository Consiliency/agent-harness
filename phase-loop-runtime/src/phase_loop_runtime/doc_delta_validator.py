"""Doc-delta closeout validator (rigor-v1 P2).

When a phase's diff touches a user-visible public surface but the closeout
records no doc-delta decision, raise a finding. Autonomy-first: the finding is
``block``-severity, so under the default ``PHASE_LOOP_REVIEW=warn`` it is merely
recorded (the loop continues) and only blocks when an operator opts in. The
agent self-satisfies it by updating docs or recording a ``no_doc_delta``
decision in the terminal summary — no human required.

The executor records its decision as ``doc_delta_decision: <literal>`` in the
terminal summary (one of ``models.DOC_DELTA_DECISIONS``).
"""
from __future__ import annotations

from .closeout_validators import CloseoutContext, ReviewFinding, register_closeout_validator
from .models import DOC_DELTA_DECISIONS, public_surface_touched


@register_closeout_validator
def doc_delta_validator(ctx: CloseoutContext) -> list[ReviewFinding]:
    if not public_surface_touched(ctx.changed_paths):
        return []
    decision = str(ctx.terminal.get("doc_delta_decision") or "").strip()
    if decision in DOC_DELTA_DECISIONS:
        return []  # a decision was recorded — satisfied
    return [
        ReviewFinding(
            code="doc_delta_undecided",
            reason=(
                "changed a public surface (CLI/schema/contract docs/README/CHANGELOG) "
                "but recorded no doc_delta decision; update the doc surface or record "
                "doc_delta_decision=no_doc_delta with a justification"
            ),
            severity="block",
            blocker_class="review_gate_block",
        )
    ]
