"""Verification-evidence closeout validator (rigor-v1 P5).

For generic phases reporting ``verification_status=passed``, require an artifact
reference or a typed ``verification_evidence_opt_out`` reason. RG and plans
mentioning ``IF-0-RG-1`` or ``--verification-log`` are left to the existing gate.
This validator checks for a reference; it does not validate artifact contents.

Findings have ``block`` severity. The default ``PHASE_LOOP_REVIEW=warn`` records
them without stopping the loop; opting into block mode enforces them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .closeout_validators import CloseoutContext, ReviewFinding, register_closeout_validator
from .models import VERIFICATION_EVIDENCE_OPT_OUT_REASONS


def _has_verification_artifact(terminal: Mapping) -> bool:
    """Detect a verification artifact in the same places the upstream gate reads
    (`closeout._verification_artifact_path`): the nested `artifact_paths` map, or
    the top-level convenience key the skills tell executors to write."""
    if terminal.get("verification_artifact_path"):
        return True
    artifact_paths = terminal.get("artifact_paths")
    if isinstance(artifact_paths, Mapping):
        return bool(
            artifact_paths.get("verification")
            or artifact_paths.get("verification_artifact")
            or artifact_paths.get("verification_log")
            or artifact_paths.get("root")
        )
    return False


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
    if _has_verification_artifact(ctx.terminal):
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
