"""Consiliency/agent-harness#358 — governed pre-merge usable-reviewer floor.

The governed gate blocked ONLY when ZERO legs were usable (governed_review.py), so
a board that delivered a SINGLE usable reviewer silently promoted a merge that one
lone opinion had "reviewed". This guard closes that hole with the decision-
INDEPENDENT lower bound: >= 2 USABLE reviewer legs. A single reviewer is not a board.

It counts LEGS, not distinct vendor families, on purpose. Requiring >= 2 DISTINCT
vendors would forbid a deliberately-configured same-family breadth board, and
telling a degraded same-family board apart from a chosen one needs the declared-vs-
achieved distinction — the three-state model, held for #375. The floor is likewise
below the pre-merge-CR quorum of 3 (ratification_policy.py:104), whose 2-vs-3
semantics are that same held model; dispatching that policy as-is would flip the
gate fail-open -> fail-CLOSED on every in-Harness run (author-excluded + the claude
TUI seat structurally unfillable => at most 2 usable).

Falsifier (named + RUN, not merely asserted): drop the `< _MIN_USABLE_REVIEWERS`
check in `governed_planning_gate` and `test_single_usable_vendor_blocks` reverts to
a PROMOTE. Positive control: a 2-usable-reviewer board still promotes, proving the
guard targets the 1-reviewer case, not all boards. Seam control: the pre-merge LOOP
labels the hold `below_reviewer_floor` (structural, remedy = add a reviewer), not
`non_convergence` (which implies code defects to repair) — proving the fix reaches
BOTH the gate and the loop's `_STRUCTURAL_HOLD` set.
"""
import unittest

from phase_loop_runtime.governed_premerge import run_governed_premerge_loop
from phase_loop_runtime.governed_review import governed_planning_gate
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult


def _panel(*legs):
    return PanelResult(legs=tuple(legs))


class UsableReviewerFloorGateTest(unittest.TestCase):
    def _gate(self, panel, available_legs, author="claude"):
        return governed_planning_gate(
            artifact="ART",
            author_executor=author,
            run_mode="governed",
            available_legs=available_legs,
            invoke=lambda art, pool, spawn=None: panel,
        )

    def test_single_usable_vendor_blocks(self):
        # codex reviews (AGREE); gemini dispatched but UNAVAILABLE -> 1 usable reviewer.
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="unavailable", text="", detail="offline"),
        )
        result = self._gate(panel, ("codex", "gemini"))
        self.assertFalse(result.promoted)  # RED against pre-fix base (was True)
        self.assertTrue(
            any(f.code == "governed_below_reviewer_floor" for f in result.findings)
        )

    def test_two_usable_vendors_promote(self):  # positive control
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
        )
        result = self._gate(panel, ("codex", "gemini"))
        self.assertTrue(result.promoted)

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
        result = self._gate(panel, ("codex", "opencode"), author="gemini")
        self.assertTrue(result.promoted)

    def test_single_reviewer_disagree_blocks_and_preserves_body(self):
        # A lone DISAGREE is below the floor AND blocks; the structural floor must not
        # swallow the concrete review text (#80) — the panel_block body survives.
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="DISAGREE — drops users table"),
            PanelLegResult(leg="gemini", status="unavailable", text=""),
        )
        result = self._gate(panel, ("codex", "gemini"))
        self.assertFalse(result.promoted)
        codes = {f.code for f in result.findings}
        self.assertIn("panel_block", codes)                    # body preserved
        self.assertIn("governed_below_reviewer_floor", codes)  # structural block added
        block = next(f for f in result.findings if f.code == "panel_block")
        self.assertEqual(block.body, "DISAGREE — drops users table")

    def test_two_vendors_one_disagrees_blocks_via_veto(self):
        # 2 usable reviewers clear the floor; the DISAGREE blocks via the existing
        # veto, proving the floor did not bypass or swallow the veto path.
        panel = _panel(
            PanelLegResult(leg="codex", status="ok", text="DISAGREE — real bug"),
            PanelLegResult(leg="gemini", status="ok", text="AGREE"),
        )
        result = self._gate(panel, ("codex", "gemini"))
        self.assertFalse(result.promoted)
        self.assertTrue(any(f.code == "panel_block" for f in result.findings))


class UsableReviewerFloorLoopSeamTest(unittest.TestCase):
    """The pre-merge LOOP must surface below_reviewer_floor as a STRUCTURAL hold
    (accurate remedy = add a reviewer), never mislabel it 'non_convergence' (which
    implies code defects to repair). Proves the fix reaches BOTH seams."""

    def test_loop_labels_below_floor_as_structural_hold(self):
        one_reviewer = _panel(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="unavailable", text=""),
        )

        def loop_invoke(**kw):
            return governed_planning_gate(
                **kw, invoke=lambda art, pool, spawn=None: one_reviewer
            )

        result = run_governed_premerge_loop(
            artifact="ART",
            author_executor="claude",
            run_mode="governed",
            available_legs=("codex", "gemini"),
            invoke=loop_invoke,
            apply_fix=None,
        )
        self.assertFalse(result.mergeable)
        self.assertEqual(result.reason, "below_reviewer_floor")  # NOT non_convergence


if __name__ == "__main__":
    unittest.main()
