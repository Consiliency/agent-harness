"""Consiliency/agent-harness#358 — governed PRE-MERGE usable-reviewer floor.

The governed pre-merge loop promoted a merge whenever the gate returned no block
finding — including when a board delivered a SINGLE usable reviewer, so one lone
opinion "reviewed" a merge. This guard closes that hole with the decision-
INDEPENDENT lower bound: >= 2 USABLE reviewer legs. A single reviewer is not a board.

SCOPE — the floor is PRE-MERGE ONLY. It lives in ``run_governed_premerge_loop``,
NOT in ``governed_planning_gate``. Plan/design ratification is deliberately
autonomy-first (``proceed_degraded`` — a plan is not held hostage to reviewer
availability, ratification_policy.py:96-100); the merge gate demands a real board.
``test_planning_gate_does_not_enforce_floor`` pins that split: the same 1-usable
board that the pre-merge loop HOLDS, the plan-stage gate PROMOTES. A planning-gate
floor, if wanted, is a REVIEWTRUTH criterion with its own falsifier (#375), not a
side effect of this merge-gate fix.

It counts LEGS, not distinct vendor families, on purpose. Requiring >= 2 DISTINCT
vendors would forbid a deliberately-configured same-family breadth board, and
telling a degraded same-family board apart from a chosen one needs the declared-vs-
achieved distinction — the three-state model, held for #375. The floor is likewise
below the pre-merge-CR quorum of 3 (ratification_policy.py:104), whose 2-vs-3
semantics are that same held model; dispatching that policy as-is would flip the
gate fail-open -> fail-CLOSED on every in-Harness run (author-excluded + the claude
TUI seat structurally unfillable => at most 2 usable).

Falsifier (named + RUN, not merely asserted): set ``_MIN_USABLE_REVIEWERS = 0`` in
``governed_premerge.py`` and exactly three tests revert —
``test_single_usable_vendor_blocks`` (the loop promotes), ``test_single_reviewer_
disagree_blocks_and_preserves_body`` (the structural floor finding disappears), and
``test_loop_labels_below_floor_as_structural_hold`` (reason is no longer
below_reviewer_floor). Positive controls: 2-usable boards still promote / block-via-
veto, proving the guard targets the 1-reviewer case, not all boards. Structural-hold
control: the loop labels the hold ``below_reviewer_floor`` (remedy = add a reviewer),
never ``non_convergence`` (which implies code defects to repair).
"""
import unittest

from phase_loop_runtime.governed_premerge import run_governed_premerge_loop
from phase_loop_runtime.governed_review import governed_planning_gate
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult


def _panel(*legs):
    return PanelResult(legs=tuple(legs))


def _loop(panel, available_legs, author="claude", apply_fix=None):
    """Drive the PRE-MERGE loop with a fixed board (the floor's real home)."""
    def loop_invoke(**kw):
        return governed_planning_gate(**kw, invoke=lambda art, pool, spawn=None: panel)

    return run_governed_premerge_loop(
        artifact="ART",
        author_executor=author,
        run_mode="governed",
        available_legs=available_legs,
        invoke=loop_invoke,
        apply_fix=apply_fix,
    )


class UsableReviewerFloorLoopTest(unittest.TestCase):
    def test_single_usable_vendor_blocks(self):
        # codex reviews (AGREE); gemini dispatched but UNAVAILABLE -> 1 usable reviewer.
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="unavailable", text="", detail="offline"),
        )
        result = _loop(panel, ("codex", "gemini"))
        self.assertFalse(result.mergeable)  # RED against pre-fix base (was True)
        self.assertTrue(
            any(f.code == "governed_below_reviewer_floor" for f in result.findings)
        )
        self.assertEqual(result.reason, "below_reviewer_floor")
        self.assertEqual(result.rounds, 1)  # structural hold terminates at round 1

    def test_two_usable_vendors_promote(self):  # positive control
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
        )
        result = _loop(panel, ("codex", "gemini"))
        self.assertTrue(result.mergeable)

    def test_two_same_family_legs_promote_distinct_vendor_strengthening_held(self):
        # codex + opencode are BOTH the codex vendor family. The decision-INDEPENDENT
        # floor counts LEGS (2 usable) so this board PROMOTES today — telling a
        # deliberate same-family breadth board apart from a degraded one is the
        # declared-vs-achieved three-state model, held for #375. This test pins that
        # scope boundary: the floor does NOT (yet) require distinct vendor families.
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="opencode", status="ok", text="AGREE"),
        )
        result = _loop(panel, ("codex", "opencode"), author="gemini")
        self.assertTrue(result.mergeable)

    def test_single_reviewer_disagree_blocks_and_preserves_body(self):
        # A lone DISAGREE is below the floor AND blocks; the structural floor must not
        # swallow the concrete review text (#80) — the panel_block body survives.
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="DISAGREE — drops users table"),
            PanelLegResult(leg="gemini", status="unavailable", text=""),
        )
        result = _loop(panel, ("codex", "gemini"))
        self.assertFalse(result.mergeable)
        codes = {f.code for f in result.findings}
        self.assertIn("panel_block", codes)                    # body preserved
        self.assertIn("governed_below_reviewer_floor", codes)  # structural block added
        block = next(f for f in result.findings if f.code == "panel_block")
        self.assertEqual(block.body, "DISAGREE — drops users table")

    def test_two_vendors_one_disagrees_blocks_via_veto(self):
        # 2 usable reviewers clear the floor; the DISAGREE blocks via the existing
        # veto, proving the floor did not bypass or swallow the veto path (this hold
        # is floor-INDEPENDENT — it survives the falsifier).
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="DISAGREE — real bug"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
        )
        result = _loop(panel, ("codex", "gemini"))
        self.assertFalse(result.mergeable)
        self.assertTrue(any(f.code == "panel_block" for f in result.findings))

    def test_loop_labels_below_floor_as_structural_hold(self):
        # The pre-merge loop must surface below_reviewer_floor as a STRUCTURAL hold
        # (accurate remedy = add a reviewer), never mislabel it 'non_convergence'
        # (which implies code defects to repair).
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="unavailable", text=""),
        )
        result = _loop(panel, ("codex", "gemini"))
        self.assertFalse(result.mergeable)
        self.assertEqual(result.reason, "below_reviewer_floor")  # NOT non_convergence


class PlanningGateScopeSplitTest(unittest.TestCase):
    """The floor is PRE-MERGE only. The plan-stage gate stays autonomy-first: the
    same 1-usable board the loop HOLDS, the gate PROMOTES. This pins the scope
    boundary the team-lead drew at ratification_policy.py:96-100 and would catch a
    regression that re-added the floor to `governed_planning_gate`."""

    def test_one_board_held_by_loop_promoted_by_plan_gate(self):
        # Board #384 r2: pin the split with ONE board object handed to BOTH callers
        # — the property is "the same board treated differently by the two callers",
        # NOT "two differently-built boards behave differently". 1 usable reviewer
        # (codex AGREE) + 1 unavailable (gemini).
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="unavailable", text=""),
        )

        # (a) the PRE-MERGE loop HOLDS this exact board below the floor ...
        loop_result = _loop(panel, ("codex", "gemini"))
        self.assertFalse(loop_result.mergeable)
        self.assertEqual(loop_result.reason, "below_reviewer_floor")

        # (b) ... while the plan-stage gate PROMOTES the SAME board (autonomy-first).
        gate_result = governed_planning_gate(
            artifact="ART",
            author_executor="claude",
            run_mode="governed",
            available_legs=("codex", "gemini"),
            invoke=lambda art, pool, spawn=None: panel,
        )
        self.assertTrue(gate_result.promoted)
        self.assertFalse(
            any(f.code == "governed_below_reviewer_floor" for f in gate_result.findings)
        )


if __name__ == "__main__":
    unittest.main()
