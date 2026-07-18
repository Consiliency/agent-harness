"""ah#186 — the run-loop preflight rejects `--lane-scheduler serialized/concurrent`
without `--work-unit-mode` for REAL execution (the recorded wave would never be
dispatched and the monolithic executor would run with an empty owned-file contract →
dirty_worktree_conflict). Dry-run (a valid wave preview) and work-unit-mode are NOT
guarded.

Deliberately an UNMARKED module (NOT `dotfiles_integration`) so CI actually runs it —
test_phase_loop_wave_runner.py, which holds the dry-run wave tests, is marked and skipped
under CI's `-m "not dotfiles_integration"`.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import phase_loop_runtime.runner as runner_module
from phase_loop_runtime.runner import run_loop
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan


class _PastGuard(RuntimeError):
    """Sentinel raised from the first call AFTER the ah#186 preflight, so a test can
    prove control reached past the guard (i.e. the guard did NOT fire)."""


def _setup(td: str):
    repo = make_repo(Path(td))
    roadmap = repo / "specs" / "phase-plans-v1.md"
    roadmap.write_text("# Roadmap\n\n### Phase 0 - Runner (RUNNER)\n", encoding="utf-8")
    plan = write_phase_plan(repo, "RUNNER", roadmap, body="- do the thing\n")
    commit_fixture_paths(repo, "preflight fixture", roadmap, plan)
    return repo, roadmap


class LaneSchedulerWorkUnitPreflightTest(unittest.TestCase):
    def test_real_exec_concurrent_without_work_unit_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = _setup(td)
            with self.assertRaises(ValueError) as cm:
                run_loop(repo, roadmap, phase="RUNNER", dry_run=False, lane_scheduler_mode="concurrent")
            self.assertIn("--work-unit-mode", str(cm.exception))

    def test_real_exec_serialized_without_work_unit_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = _setup(td)
            with self.assertRaises(ValueError) as cm:
                run_loop(repo, roadmap, phase="RUNNER", dry_run=False, lane_scheduler_mode="serialized")
            self.assertIn("--work-unit-mode", str(cm.exception))

    def test_work_unit_mode_passes_the_preflight(self):
        # With --work-unit-mode the guard must NOT fire; control reaches past it (proven
        # by the sentinel patched onto the first post-guard call).
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = _setup(td)
            with patch.object(runner_module.RotationState, "from_csv", side_effect=_PastGuard):
                with self.assertRaises(_PastGuard):
                    run_loop(
                        repo, roadmap, phase="RUNNER", dry_run=False,
                        lane_scheduler_mode="serialized", work_unit_mode=True,
                    )

    def test_dry_run_wave_preview_passes_the_preflight(self):
        # Dry-run is a valid wave PREVIEW without --work-unit-mode; the guard must NOT fire.
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = _setup(td)
            with patch.object(runner_module.RotationState, "from_csv", side_effect=_PastGuard):
                with self.assertRaises(_PastGuard):
                    run_loop(repo, roadmap, phase="RUNNER", dry_run=True, lane_scheduler_mode="concurrent")

    def test_lane_scheduler_off_is_never_guarded(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = _setup(td)
            with patch.object(runner_module.RotationState, "from_csv", side_effect=_PastGuard):
                with self.assertRaises(_PastGuard):
                    run_loop(repo, roadmap, phase="RUNNER", dry_run=False, lane_scheduler_mode="off")


if __name__ == "__main__":
    unittest.main()
