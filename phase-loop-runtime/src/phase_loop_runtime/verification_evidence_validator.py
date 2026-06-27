"""Verification-evidence closeout validator (rigor-v1 P5).

Closes the generic-phase hole: today only `RG` phases or plans opting in via
`IF-0-RG-1`/`--verification-log` require an evidence artifact, so any other phase
can self-report `verification_status=passed` with nothing backing it. This
validator raises a finding for those generic phases too.

Autonomy-first: ``block``-severity, so under the default ``PHASE_LOOP_REVIEW=warn``
it is recorded and the loop continues; it blocks only on opt-in. The agent
self-satisfies by attaching a verification artifact or recording a typed opt-out
reason (``verification_evidence_opt_out``) — no human required.
"""
from __future__ import annotations

from pathlib import Path

from .closeout_validators import CloseoutContext, ReviewFinding, register_closeout_validator
from .models import VERIFICATION_EVIDENCE_OPT_OUT_REASONS


def _legacy_evidence_gate_owns(phase_alias: str, plan_path: str) -> bool:
    """True when the existing verification-evidence gate already governs this phase
    (RG, or a plan opting into IF-0-RG-1/--verification-log). Those are handled
    upstream in build_phase_loop_closeout, so this validator stays out of them."""
    if phase_alias.upper() == "RG":
        return True
    try:
        text = Path(plan_path).read_text(encoding="utf-8")
    except OSError:
        return False
    return "IF-0-RG-1" in text or "--verification-log" in text


@register_closeout_validator
def verification_evidence_validator(ctx: CloseoutContext) -> list[ReviewFinding]:
    reported = str(ctx.terminal.get("verification_status") or ctx.automation.get("verification_status") or "")
    if reported != "passed":
        return []
    if _legacy_evidence_gate_owns(ctx.phase_alias, ctx.plan_path):
        return []  # owned by the upstream evidence gate
    if ctx.terminal.get("verification_artifact_path"):
        return []  # evidence attached
    opt_out = str(ctx.terminal.get("verification_evidence_opt_out") or "").strip()
    if opt_out in VERIFICATION_EVIDENCE_OPT_OUT_REASONS:
        return []  # declined with a typed reason
    return [
        ReviewFinding(
            code="verification_evidence_missing_generic",
            reason=(
                "reported verification_status=passed with no verification_artifact_path; "
                "attach the runner verification log or record a verification_evidence_opt_out "
                f"reason ({', '.join(VERIFICATION_EVIDENCE_OPT_OUT_REASONS)})"
            ),
            severity="block",
            blocker_class="review_gate_block",
        )
    ]
