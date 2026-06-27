"""Visual-evidence closeout validator (rigor-v1 P6).

When a phase changes UI/visual surfaces but attaches no visual evidence
(screenshot path + observed outcome), raise a finding. Autonomy-first:
``block``-severity, so under the default ``PHASE_LOOP_REVIEW=warn`` it is
recorded and the loop continues; it blocks only on opt-in. The agent
self-satisfies by capturing a screenshot (claude-in-chrome / Playwright-via-PMCP)
and recording its path — no human eyeball is required to pass.

The executor records ``visual_evidence_path`` (and optionally
``visual_evidence_observed``) in the terminal summary.
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
