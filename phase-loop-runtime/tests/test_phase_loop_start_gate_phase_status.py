"""Standalone unit tests for the cross-phase dirty start gate's status filter.

These exercise ``_cross_phase_dirty_start_gate`` directly (no ``run_loop``), so
they do NOT depend on a dotfiles fleet tree and run in the extracted
``agent-harness`` standalone layout — unlike the integration-marked
``test_phase_loop_start_gate_refuses_cross_phase_dirty`` suite.

Regression coverage for issue #1: a phase that is no longer in-flight
(``unplanned``/``complete``/``unknown``, or removed from the roadmap) must not
perpetually own a blocking dirty path, and the refusal message must only
recommend recovery commands that are actually reachable from the refused state.
"""
import tempfile
import unittest
from pathlib import Path

from phase_loop_test_utils import make_repo, write_named_roadmap
from phase_loop_runtime.events import append_event
from phase_loop_runtime.models import LoopEvent, utc_now
from phase_loop_runtime.observability import build_terminal_summary
from phase_loop_runtime.provenance import event_provenance
from phase_loop_runtime.runner import _cross_phase_dirty_start_gate


def _seed_owner_dirty(repo: Path, roadmap: Path, owner: str, path: str) -> None:
    """Record an owner phase as having produced a dirty owned path, and make that
    path live-dirty (untracked) in the working tree."""
    append_event(
        repo,
        LoopEvent(
            timestamp=utc_now(),
            repo=str(repo),
            roadmap=str(roadmap),
            phase=owner,
            action="execute",
            status="executed",
            model="fixture",
            reasoning_effort="medium",
            source="fixture",
            metadata={
                "terminal_summary": build_terminal_summary(
                    terminal_status="executed",
                    terminal_blocker=None,
                    verification_status="passed",
                    next_action="Preserve phase-owned output.",
                    dirty_paths=(path,),
                    phase_owned_dirty=True,
                    phase_owned_dirty_paths=(path,),
                )
            },
            **event_provenance(roadmap, owner),
        ),
    )
    (repo / path).write_text("dirty owner output\n", encoding="utf-8")


class StartGatePhaseStatusTest(unittest.TestCase):
    def _fixture(self) -> tuple[Path, Path]:
        td = tempfile.mkdtemp()
        repo = make_repo(Path(td))
        roadmap = write_named_roadmap(repo, (("ALPHA", "Alpha"), ("BETA", "Beta")))
        _seed_owner_dirty(repo, roadmap, "ALPHA", "alpha-output.txt")
        return repo, roadmap

    def test_refuses_when_owner_active(self):
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", {"ALPHA": "executed", "BETA": "planned"})
        self.assertIsNotNone(gate)
        self.assertEqual(gate["offending_phase"], "ALPHA")
        self.assertEqual(gate["offending_status"], "executed")
        self.assertEqual(gate["overlapping_dirty_paths"], ["alpha-output.txt"])

    def test_skips_unplanned_owner(self):
        # Issue #1's reported scenario: roadmap edited, owner ended up unplanned.
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", {"ALPHA": "unplanned", "BETA": "planned"})
        self.assertIsNone(gate)

    def test_fires_for_complete_owner(self):
        # A `complete` phase can legitimately hold preserved-but-uncommitted
        # owned output; the gate must still refuse (recovery is the bypass flag).
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", {"ALPHA": "complete", "BETA": "planned"})
        self.assertIsNotNone(gate)
        self.assertEqual(gate["offending_status"], "complete")

    def test_fires_for_unknown_owner(self):
        # CRITICAL regression guard: `reconcile` reclassifies a still-dirty
        # `executing` phase to `unknown` (reconcile.py:78), and the start gate
        # only runs on a dirty tree — so `unknown` is the disguise the canonical
        # in-flight hazard wears at the exact moment the gate fires. `unknown`
        # MUST stay out of the inactive-skip set or the gate is neutralized.
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", {"ALPHA": "unknown", "BETA": "planned"})
        self.assertIsNotNone(gate)
        self.assertEqual(gate["offending_status"], "unknown")

    def test_skips_owner_absent_from_roadmap(self):
        # Owner removed from the roadmap entirely -> no status entry -> no lien.
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", {"BETA": "planned"})
        self.assertIsNone(gate)

    def test_no_phase_status_map_grants_no_lien(self):
        # Defensive: without a status map every owner is treated as non-active.
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", None)
        self.assertIsNone(gate)

    def test_recovery_actions_lead_with_bypass_and_cover_untracked(self):
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", {"ALPHA": "executed"})
        actions = gate["next_actions"]
        # The proven escape hatch leads.
        self.assertIn("--allow-cross-phase-dirty", actions[0])
        # Untracked output guidance is present (issue #1 secondary observation).
        self.assertTrue(any("git stash -u" in action for action in actions))
        # A non-blocked owner gets no reconcile suggestion (it would be rejected).
        self.assertFalse(any("phase-loop reconcile" in action for action in actions))

    def test_blocked_owner_recovery_includes_allow_dirty_reconcile(self):
        repo, _ = self._fixture()
        gate = _cross_phase_dirty_start_gate(repo, "BETA", {"ALPHA": "blocked"})
        actions = gate["next_actions"]
        self.assertIn("--allow-cross-phase-dirty", actions[0])
        reconcile = [a for a in actions if "phase-loop reconcile" in a]
        self.assertEqual(len(reconcile), 1)
        # Must carry --allow-dirty: the overlapping path is dirty by definition
        # when the gate fires, so reconcile's dirty-tree guard would otherwise
        # reject it (issue #1: don't recommend a rejectable command).
        self.assertIn("--allow-dirty", reconcile[0])
        self.assertIn("--to-status planned", reconcile[0])


if __name__ == "__main__":
    unittest.main()
