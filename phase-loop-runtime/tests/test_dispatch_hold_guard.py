"""GOVLEAN amendment (2026-08-13): machine-readable dispatch-hold guard.

Codex r2 and grok r2 converged on the same gap: a prose-only execution re-gate is
invisible to automated dispatch, and a REFRESHED plan (current roadmap_sha256)
defeats the stale-roadmap guard. The ratified encoding is a ``**Dispatch holds**``
field declared on the NEW phase's side (the grammar forbids editing existing phases
and forward dependencies), enforced by ``runner._dispatch_hold_blocker``: dispatch of
a held phase fails closed BY DEFAULT until the holding phase is recorded completed in
``plans/manifest.json``. Explicit recovery bypass: ``PHASE_LOOP_ALLOW_HELD_DISPATCH=1``.

Arms are mutation-coupled: fire (held + holder incomplete), release (holder
completed), narrowness (unheld phase unaffected), bypass, no-holds regression, and
fail-closed-on-unreadable-manifest.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phase_loop_runtime import discovery
from phase_loop_runtime.runner import _execute_goal_coverage_preflight


def _roadmap_text(with_hold=True):
    hold = (
        "**Dispatch holds**\n- P1 — held until G1 completes (machine-parsed)\n\n"
        if with_hold
        else ""
    )
    return (
        "# Roadmap\n\n## Context\nx\n\n## Assumptions\nx\n\n## Non-Goals\nx\n\n"
        "## Top Interface-Freeze Gates\n\n## Phase Dependency DAG\nP1\n\n"
        "## Phases\n\n### Phase 1 — Thing (P1)\n**Objective**\nx\n"
        "**Exit criteria**\n- [ ] EC-P1-1 — a\n"
        "**Scope notes**\nSingle lane (bounded)\n**Non-goals**\nx\n**Key files**\n- x\n"
        "**Depends on**\n- (none)\n**Produces**\n\n"
        "### Phase 2 — Gov (G1)\n**Objective**\nx\n"
        "**Exit criteria**\n- [ ] EC-G1-1 — a\n"
        "**Scope notes**\nSingle lane (bounded)\n**Non-goals**\nx\n**Key files**\n- x\n"
        f"{hold}"
        "**Depends on**\n- P1\n**Produces**\n\n"
        "## Execution Notes\nx\n\n## Verification\nx\n"
    )


def _build(td: Path, *, with_hold=True, holder_completed=False, plan_phase="P1",
           manifest="auto"):
    rm = td / "specs" / "phase-plans-v1.md"
    rm.parent.mkdir(parents=True, exist_ok=True)
    rm.write_text(_roadmap_text(with_hold), encoding="utf-8")
    sha = discovery.roadmap_sha256(rm)
    rel = discovery.roadmap_repo_relative_path(td, rm)
    plan = td / "plan.md"
    plan.write_text(
        f'---\nphase_loop_plan_version: "1"\nphase: {plan_phase}\n'
        f"roadmap: {rel}\nroadmap_sha256: {sha}\n---\n# Plan\n\n"
        f"## Acceptance Criteria\n- [ ] EC-{plan_phase}-1 — proven by test\n",
        encoding="utf-8",
    )
    mdir = td / "plans"
    mdir.mkdir(exist_ok=True)
    if manifest == "auto":
        entries = []
        if holder_completed:
            entries.append({"slug": "v1-G1", "file": "plans/x.md", "type": "phase",
                            "status": "completed"})
        (mdir / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
    elif manifest == "unreadable":
        (mdir / "manifest.json").write_text("{not json", encoding="utf-8")
    return rm, plan


class DispatchHoldGuardTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.addCleanup(self._td.cleanup)
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        for var in ("PHASE_LOOP_ACCEPTANCE_ENFORCE", "PHASE_LOOP_ALLOW_HELD_DISPATCH",
                    "PHASE_LOOP_ALLOW_STALE_ROADMAP_PLAN"):
            os.environ.pop(var, None)

    def test_held_phase_blocks_by_default(self):
        rm, plan = _build(self.td, with_hold=True, holder_completed=False)
        blocker = _execute_goal_coverage_preflight(self.td, rm, plan)
        self.assertIsNotNone(blocker, "held phase must fail closed WITHOUT enforce env")
        self.assertEqual(blocker["blocker_class"], "contract_bug")
        self.assertFalse(blocker["human_required"])
        self.assertIn("Dispatch-hold guard", str(blocker["blocker_summary"]))
        self.assertIn("G1", str(blocker["blocker_summary"]))

    def test_completed_holder_releases_the_hold(self):
        # Positive control: an always-fire guard cannot survive this arm.
        rm, plan = _build(self.td, with_hold=True, holder_completed=True)
        self.assertIsNone(_execute_goal_coverage_preflight(self.td, rm, plan))

    def test_unheld_phase_is_unaffected(self):
        rm, plan = _build(self.td, with_hold=True, holder_completed=False,
                          plan_phase="G1")
        blocker = _execute_goal_coverage_preflight(self.td, rm, plan)
        self.assertIsNone(blocker, "the hold names P1; a G1 plan must not be blocked")

    def test_explicit_bypass(self):
        rm, plan = _build(self.td, with_hold=True, holder_completed=False)
        os.environ["PHASE_LOOP_ALLOW_HELD_DISPATCH"] = "1"
        self.assertIsNone(_execute_goal_coverage_preflight(self.td, rm, plan))

    def test_no_holds_field_is_a_no_op(self):
        rm, plan = _build(self.td, with_hold=False)
        self.assertIsNone(_execute_goal_coverage_preflight(self.td, rm, plan))

    def test_unreadable_manifest_fails_closed(self):
        # The hold parsed successfully; the completion ledger being unreadable must
        # keep the hold ACTIVE (fail-closed direction for a dispatch gate).
        rm, plan = _build(self.td, with_hold=True, manifest="unreadable")
        blocker = _execute_goal_coverage_preflight(self.td, rm, plan)
        self.assertIsNotNone(blocker)
        self.assertIn("Dispatch-hold guard", str(blocker["blocker_summary"]))


if __name__ == "__main__":
    unittest.main()
