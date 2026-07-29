"""model-routing-v2 P3 — planning gate + escalation ladder.

Tests the runner planning-gate helper + first-attempt guard (live wiring), and
the next_escalation ladder the repair-pivot binding consults. The panel is
injected (no live frontier calls); the gate's autonomous short-circuit is
covered by governed_review's own tests.
"""
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime import runner
from phase_loop_runtime.governed_review import GateResult
from phase_loop_runtime.governed_premerge import next_escalation
from phase_loop_runtime.panel_invoker import PanelLegResult, PanelResult


def _sel():
    # No `executor` field: ModelSelection has none, and the gate must NOT read one
    # (the masked bug). The author vendor is derived from `model` (or a recorded
    # execute event) — `claude-opus-4-8` → vendor `claude`.
    return types.SimpleNamespace(
        model="claude-opus-4-8", effort="high", source="s", override_reason=None,
        model_class="implementer",
    )


class PlanningGateHelperTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo = Path(self._td.name)
        self.roadmap = self.repo / "specs" / "rm.md"
        self.roadmap.parent.mkdir(parents=True, exist_ok=True)
        self.roadmap.write_text("# roadmap\n", encoding="utf-8")
        self.plan = self.repo / "plan.md"
        self.plan.write_text("# plan\n## Acceptance Criteria\n- [ ] x\n", encoding="utf-8")
        self.snap = types.SimpleNamespace(closeout_terminal_status=None, terminal_summary={})

    def tearDown(self):
        self._td.cleanup()

    def _run(self, gate_result):
        with patch.object(runner, "governed_planning_gate", return_value=gate_result), \
             patch.object(runner, "available_panel_legs", return_value=("codex", "gemini")):
            return runner._governed_planning_gate(
                self.repo, self.roadmap, "P1", self.plan, self.snap, _sel(), "run"
            )

    def test_promote_proceeds(self):
        self.assertIsNone(self._run(GateResult(ran=True, promoted=True)))

    def test_block_holds_with_non_human_review_gate_block(self):
        r = self._run(GateResult(ran=True, promoted=False, reason="real bug in the plan"))
        self.assertIsNotNone(r)
        status, event = r
        self.assertEqual(status, "blocked")
        self.assertFalse(event.blocker["human_required"])
        self.assertEqual(event.blocker["blocker_class"], "review_gate_block")

    def test_degraded_advisory_promotes(self):
        # degraded => not a real review => promote (autonomy-first, never a
        # same-vendor self-review that blocks).
        self.assertIsNone(self._run(GateResult(ran=True, promoted=True, degraded=True)))


class PlanStageFloorScopeProductionPathTest(unittest.TestCase):
    """Consiliency/agent-harness#358 — the usable-reviewer floor is PRE-MERGE ONLY.

    This drives the PRODUCTION plan-stage wrapper ``runner._governed_planning_gate``
    (runner.py:9812) with the REAL gate and a SINGLE usable reviewer, asserting the
    plan still PROMOTES (proceeds — ``None``). It exists because board #384 r1 found
    the exact blind spot it closes: the rejected shared-gate design (parent commit
    ``fd6f6b7``) applied the pre-merge floor inside ``governed_planning_gate`` and so
    HELD a 1-reviewer PLAN, contradicting the autonomy-first plan-ratification
    posture (``proceed_degraded`` — a plan is not held hostage to reviewer
    availability, ratification_policy.py:96-100). Six earlier guard tests all passed
    under that regression because none exercised THIS production surface; a
    direct-gate test (``test_planning_gate_does_not_enforce_floor`` in the 358 file)
    sits one level below the wrapper the next widener actually runs.

    Non-vacuity is proven by the ACTUAL rejected design, not a synthetic floor:
    ``git checkout fd6f6b7a1 -- .../governed_review.py`` turns this test RED (the real
    gate returns a ``below_reviewer_floor`` block, the wrapper returns ``("blocked",
    event)``, and the ``assertIsNone`` fails); it is GREEN at HEAD. The floor's own
    ``_MIN_USABLE_REVIEWERS`` lives in ``governed_premerge`` and the plan gate never
    reads it, so this test is invariant under the ``2 -> 0`` pre-merge falsifier —
    that is the decoupling control.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo = Path(self._td.name)
        self.roadmap = self.repo / "specs" / "rm.md"
        self.roadmap.parent.mkdir(parents=True, exist_ok=True)
        self.roadmap.write_text("# roadmap\n", encoding="utf-8")
        self.plan = self.repo / "plan.md"
        self.plan.write_text("# plan\n## Acceptance Criteria\n- [ ] x\n", encoding="utf-8")
        self.snap = types.SimpleNamespace(closeout_terminal_status=None, terminal_summary={})

    def tearDown(self):
        self._td.cleanup()

    def test_single_usable_reviewer_plan_promotes_via_production_wrapper(self):
        # One usable reviewer (codex AGREE) + one unavailable (gemini) => the
        # PRE-MERGE loop would HOLD (below the floor of 2), but the PLAN-stage gate
        # must PROMOTE. Author vendor `claude` is disjoint from the codex/gemini
        # pool, so the real gate selects a live reviewer and reaches a verdict.
        panel = PanelResult(legs=(
            PanelLegResult(leg="codex", status="ok", text="AGREE"),
            PanelLegResult(leg="gemini", status="unavailable", text=""),
        ))
        real_gate = runner.governed_planning_gate  # unpatched below; mutation flows through it

        def gate_running_real_with_injected_panel(**kw):
            kw.setdefault("invoke", lambda art, pool, **_ignored: panel)
            return real_gate(**kw)

        with patch.object(runner, "governed_planning_gate",
                          side_effect=gate_running_real_with_injected_panel), \
                patch.object(runner, "available_panel_legs", return_value=("codex", "gemini")), \
                patch.object(runner, "_phase_author_vendors", return_value=frozenset({"claude"})):
            result = runner._governed_planning_gate(
                self.repo, self.roadmap, "P1", self.plan, self.snap, _sel(), "run"
            )

        # None => proceed to execute (promoted). A floor re-added to
        # governed_planning_gate makes the real gate block => wrapper returns a
        # ("blocked", event) tuple => this fails. That is the RED under the rejected
        # shared-gate design (the surface the change actually touches).
        self.assertIsNone(result)


class FirstAttemptGuardTest(unittest.TestCase):
    def test_first_attempt_when_no_prior_dispatch(self):
        with patch.object(runner, "read_events", return_value=[]):
            self.assertFalse(runner._phase_already_dispatched(Path("/x"), "P1"))

    def test_not_first_attempt_after_execute(self):
        with patch.object(runner, "read_events", return_value=[{"phase": "P1", "action": "execute"}]):
            self.assertTrue(runner._phase_already_dispatched(Path("/x"), "P1"))

    def test_other_phase_dispatch_does_not_count(self):
        with patch.object(runner, "read_events", return_value=[{"phase": "P2", "action": "repair"}]):
            self.assertFalse(runner._phase_already_dispatched(Path("/x"), "P1"))


class PhaseAuthorVendorsTest(unittest.TestCase):
    """Reviewer≠author derives from the UNION of the dispatch events'
    `selected_executor` across ALL the phase's events. The old single-vendor
    version filtered on `action in (execute/repair/plan)`, but dispatch events log
    `action='run'`, so the filter never matched and it fell back to the configured
    model — defeating reviewer≠author (advisor-panel reconciliation). The filter is
    gone and multiple authors (rotation/repair) are ALL excluded."""

    def test_union_across_events_with_action_run(self):
        events = [
            {"phase": "P1", "action": "run", "selected_executor": "codex"},
            {"phase": "P1", "action": "run", "selected_executor": "claude"},
            {"phase": "P2", "action": "run", "selected_executor": "gemini"},  # other phase
        ]
        with patch.object(runner, "read_events", return_value=events):
            v = runner._phase_author_vendors(Path("/x"), "P1")
        self.assertEqual(v, frozenset({"codex", "claude"}))

    def test_empty_set_when_no_recorded_executor(self):
        # Unknown author → empty set → the gate fails closed upstream (no silent
        # fallback to the configured model's vendor).
        with patch.object(runner, "read_events", return_value=[]):
            self.assertEqual(runner._phase_author_vendors(Path("/x"), "P1"), frozenset())


class EscalationLadderBindingTest(unittest.TestCase):
    # The contract the repair-pivot binding consults (next_escalation is pure).
    def test_below_threshold_retries(self):
        self.assertEqual(next_escalation(model_class="implementer", patch_retries=1, run_mode="governed").action, "retry")

    def test_implementer_escalates_to_planner(self):
        d = next_escalation(model_class="implementer", patch_retries=2, run_mode="governed")
        self.assertEqual(d.action, "escalate_class")
        self.assertEqual(d.model_class, "planner")

    def test_planner_failing_governed_invokes_panel(self):
        self.assertEqual(next_escalation(model_class="planner", patch_retries=2, run_mode="governed").action, "invoke_panel")

    def test_planner_failing_autonomous_is_non_human_terminal(self):
        d = next_escalation(model_class="planner", patch_retries=2, run_mode="autonomous")
        self.assertEqual(d.action, "terminal_blocker")
        self.assertFalse(d.blocker["human_required"])


if __name__ == "__main__":
    unittest.main()
