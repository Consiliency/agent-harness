"""Visual-evidence closeout validator (rigor-v1 P6).

When ``ui_change_detected`` matches changed paths, raise a finding unless the
terminal summary has a truthy ``visual_evidence_path`` or ``visual_evidence``.
The validator does not open the referenced evidence or require an observed-outcome
field. Executors may also record ``visual_evidence_observed`` for reviewers.

Findings have ``block`` severity. The default ``PHASE_LOOP_REVIEW=warn`` records
them without stopping the loop; opting into block mode enforces them.
"""
from __future__ import annotations

from .closeout_validators import CloseoutContext, ReviewFinding, register_closeout_validator
from .models import ui_change_detected


@register_closeout_validator
def visual_evidence_validator(ctx: CloseoutContext) -> list[ReviewFinding]:
    if not ui_change_detected(ctx.changed_paths):
        return []
    if ctx.terminal.get("visual_evidence_path") or ctx.terminal.get("visual_evidence"):
        return []  # evidence attached
    return [
        ReviewFinding(
            code="visual_evidence_missing",
            reason=(
                "changed a UI/visual surface (*.tsx/jsx/vue/svelte/css or components/**) "
                "but attached no visual_evidence_path; capture a screenshot "
                "(claude-in-chrome or Playwright-via-PMCP) and record its path"
            ),
            severity="block",
            blocker_class="review_gate_block",
        )
    ]
