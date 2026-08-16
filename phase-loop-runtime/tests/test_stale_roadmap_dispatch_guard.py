"""GOVLEAN amendment (2026-08-13): stale-roadmap dispatch guard.

A plan whose pinned ``roadmap_sha256`` no longer matches the live roadmap bytes was
authored against DIFFERENT roadmap content and is un-auditable. Both r2 panel seats
(gemini r1, grok r2) named the same hole for the PROOFGATE re-gate: with the ordering
carried as a governance ruling rather than a structured edge, a pre-amendment plan
dispatched under post-amendment rules would silently defeat the re-gate. The guard in
``runner._execute_goal_coverage_preflight`` fails that ONE anchor mismatch closed by
DEFAULT — independent of ``PHASE_LOOP_ACCEPTANCE_ENFORCE`` — with an explicit recovery
bypass (``PHASE_LOOP_ALLOW_STALE_ROADMAP_PLAN=1``).

Arms are mutation-coupled: the guard must FIRE on the stale sha, must NOT fire on a
matching sha (positive control — an always-fire guard cannot pass), must respect the
explicit bypass, and must stay NARROW (a different anchor mismatch — wrong phase —
keeps the pre-existing warn-by-default semantics; this guard must not widen it).
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phase_loop_runtime import discovery
from phase_loop_runtime.runner import _execute_goal_coverage_preflight


def _roadmap_text(alias="P1"):
    return (
        f"# Roadmap\n\n## Context\nx\n\n## Assumptions\nx\n\n## Non-Goals\nx\n\n"
        f"## Top Interface-Freeze Gates\n\n## Phase Dependency DAG\n{alias}\n\n"
        f"## Phases\n\n### Phase 1 — Thing ({alias})\n**Objective**\nx\n"
        f"**Exit criteria**\n- [ ] EC-{alias}-1 — a\n"
        f"**Scope notes**\nSingle lane (bounded)\n**Non-goals**\nx\n**Key files**\n- x\n"
        f"**Depends on**\n- (none)\n**Produces**\n\n"
        f"## Execution Notes\nx\n\n## Verification\nx\n"
    )


def _build(td: Path, *, break_sha=False, wrong_phase=False):
    rm = td / "specs" / "phase-plans-v1.md"
    rm.parent.mkdir(parents=True, exist_ok=True)
    rm.write_text(_roadmap_text(), encoding="utf-8")
    sha = "0" * 64 if break_sha else discovery.roadmap_sha256(rm)
    rel = discovery.roadmap_repo_relative_path(td, rm)
    plan = td / "plan.md"
    plan.write_text(
        f'---\nphase_loop_plan_version: "1"\nphase: {"P2" if wrong_phase else "P1"}\n'
        f"roadmap: {rel}\nroadmap_sha256: {sha}\n---\n# Plan\n\n"
        f"## Acceptance Criteria\n- [ ] EC-P1-1 — proven by test, falsified by fails if test fails\n",
        encoding="utf-8",
    )
    return rm, plan


class StaleRoadmapDispatchGuardTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.addCleanup(self._td.cleanup)
        # The guard's default-mode claim is only meaningful with the enforce env unset.
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("PHASE_LOOP_ACCEPTANCE_ENFORCE", None)
        os.environ.pop("PHASE_LOOP_ALLOW_STALE_ROADMAP_PLAN", None)

    def test_stale_sha_blocks_by_default(self):
        rm, plan = _build(self.td, break_sha=True)
        blocker = _execute_goal_coverage_preflight(self.td, rm, plan)
        self.assertIsNotNone(blocker, "stale roadmap_sha256 must fail closed WITHOUT enforce env")
        self.assertEqual(blocker["blocker_class"], "contract_bug")
        self.assertFalse(blocker["human_required"])
        self.assertIn("Stale-roadmap dispatch guard", str(blocker["blocker_summary"]))

    def test_matching_sha_passes(self):
        # Positive control: an always-fire guard cannot survive this arm.
        rm, plan = _build(self.td, break_sha=False)
        self.assertIsNone(_execute_goal_coverage_preflight(self.td, rm, plan))

    def test_explicit_bypass_restores_advisory(self):
        rm, plan = _build(self.td, break_sha=True)
        os.environ["PHASE_LOOP_ALLOW_STALE_ROADMAP_PLAN"] = "1"
        self.assertIsNone(
            _execute_goal_coverage_preflight(self.td, rm, plan),
            "explicit recovery bypass must restore the pre-guard advisory default",
        )

    def test_guard_is_narrow_wrong_phase_stays_advisory(self):
        # A DIFFERENT anchor mismatch (plan names another phase) keeps the
        # pre-existing warn-by-default semantics — the guard must not widen.
        rm, plan = _build(self.td, wrong_phase=True)
        self.assertIsNone(
            _execute_goal_coverage_preflight(self.td, rm, plan),
            "non-sha anchor mismatches must keep warn-by-default semantics",
        )

    def test_stale_sha_still_blocks_under_enforce_block(self):
        # Composition sanity: the guard and the enforce path agree on the outcome.
        rm, plan = _build(self.td, break_sha=True)
        os.environ["PHASE_LOOP_ACCEPTANCE_ENFORCE"] = "block"
        blocker = _execute_goal_coverage_preflight(self.td, rm, plan)
        self.assertIsNotNone(blocker)


if __name__ == "__main__":
    unittest.main()
