import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.events import read_events
from phase_loop_runtime.launcher import LaunchResult
from phase_loop_runtime.runner import run_loop
from phase_loop_runtime.worker_pool import PhaseWorkerJob, run_phase_worker_pool
from phase_loop_test_utils import build_fake_automation_output, commit_fixture_paths, make_repo, write_phase_plan
from test_phase_worktree_executor import require_sched_red

import pytest

# TESTDECOUPLE SL-1 (overlay-dependent): builds a skill/adoption bundle or runs the
# runtime execute path, which resolves the dotfiles skill-source / profile overlay
# (claude-config/*, codex-config/* …) absent standalone. Run-time integration: the
# conftest hook skips it when no dotfiles tree is reachable.
@pytest.mark.dotfiles_integration
class WorkerPoolFailureIsolationTest(unittest.TestCase):
    def test_worker_failure_records_blocked_phase_and_sibling_completion(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                textwrap.dedent(
                    """
                    # Roadmap

                    ### Phase 1 - Alpha (A)
                    **Depends on**
                    - (none)

                    ---

                    ### Phase 2 - Beta (B)
                    **Depends on**
                    - (none)

                    ---

                    ### Phase 3 - Gamma (C)
                    **Depends on**
                    - A
                    - B
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            plans = tuple(write_phase_plan(repo, phase, roadmap) for phase in ("A", "B", "C"))
            commit_fixture_paths(repo, "add workerpool plans", roadmap, *plans)

            def fake_launch(spec, dry_run=False, log_path=None, stream_output=False, **kwargs):
                phase = "A" if "phase-plan-v1-A.md" in spec.prompt_bundle.render_prompt() else "B"
                status = "blocked" if phase == "A" else "complete"
                return LaunchResult(
                    command=spec.command,
                    returncode=0,
                    output=build_fake_automation_output(
                        status=status,
                        verification_status="blocked" if status == "blocked" else "passed",
                        blocker_class="repeated_verification_failure" if status == "blocked" else "none",
                        blocker_summary="fixture blocker" if status == "blocked" else "none",
                        artifact=str(repo / "plans" / f"phase-plan-v1-{phase}.md"),
                        artifact_state="tracked",
                    ),
                    executor=spec.executor,
                    log_path=str(log_path) if log_path else None,
                )

            with patch("phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch):
                snapshot, results = run_loop(repo, roadmap, parallel_dispatch=True)

            self.assertEqual(len(results), 2)
            self.assertEqual(snapshot.phases["A"], "blocked")
            self.assertEqual(snapshot.phases["B"], "complete")
            self.assertNotEqual(snapshot.phases.get("C"), "complete")
            actions = [event["action"] for event in read_events(repo)]
            self.assertIn("coordinator.worker_dispatched", actions)
            self.assertIn("coordinator.worker_completed", actions)


if __name__ == "__main__":
    unittest.main()


@require_sched_red
def test_blocked_worker_preserves_recoverable_generation_metadata():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(Path(td))
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.parent.mkdir(parents=True, exist_ok=True)
        roadmap.write_text("# Roadmap\n", encoding="utf-8")
        preserved = repo / "preserved-generation"
        preserved.mkdir()
        (preserved / "staged.txt").write_bytes(b"staged bytes\n")
        (preserved / "untracked.bin").write_bytes(b"untracked\x00bytes")
        handle = {"generation": "g-1", "worktree_path": str(preserved), "temp_branch": "phase-loop/sched/main/A-g-1"}
        job = PhaseWorkerJob(phase="A", spec=type("Spec", (), {"executor": "codex"})(), worktree_handle=handle)
        with patch(
            "phase_loop_runtime.worker_pool.launch_with_spec",
            return_value=LaunchResult(command=["fake"], returncode=1, executor="codex"),
        ):
            result = run_phase_worker_pool(repo, roadmap, (job,), max_workers=1)[0]

        recovery = result.terminal_summary["recoverable_generation"]
        assert recovery["generation"] == "g-1"
        assert recovery["temp_branch"] == "phase-loop/sched/main/A-g-1"
        assert (preserved / "staged.txt").read_bytes() == b"staged bytes\n"
        assert (preserved / "untracked.bin").read_bytes() == b"untracked\x00bytes"


@require_sched_red
def test_manual_or_blocked_closeout_preserves_staged_and_untracked_bytes():
    """Exercise the worker dispatch seam that must preserve a blocked generation."""

    import inspect

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        repo = make_repo(root / "repo")
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.parent.mkdir(parents=True, exist_ok=True)
        roadmap.write_text("# Roadmap\n", encoding="utf-8")
        worktree = root / "generation"
        worktree.mkdir()
        staged = worktree / "planner.md"
        untracked = worktree / ".dev-skills" / "handoffs" / "resume.md"
        staged.write_bytes(b"staged planner artifact\n")
        untracked.parent.mkdir(parents=True)
        untracked.write_bytes(b"ignored handoff bytes\n")
        handle = {
            "generation": "g-manual",
            "worktree_path": str(worktree),
            "temp_branch": "phase-loop/sched/main/PLAN-g-manual",
        }
        job_kwargs = {"phase": "PLAN", "spec": type("Spec", (), {"executor": "codex"})()}
        job_parameters = inspect.signature(PhaseWorkerJob).parameters
        if "worktree_handle" in job_parameters:
            job_kwargs["worktree_handle"] = handle
        if "closeout_mode" in job_parameters:
            job_kwargs["closeout_mode"] = "manual"
        job = PhaseWorkerJob(**job_kwargs)
        with patch(
            "phase_loop_runtime.worker_pool.launch_with_spec",
            return_value=LaunchResult(command=["fake"], returncode=1, executor="codex"),
        ):
            result = run_phase_worker_pool(repo, roadmap, (job,), max_workers=1)[0]

        assert {"worktree_handle", "closeout_mode"} <= set(job_parameters), (
            "missing production manual-closeout preservation seam"
        )
        recovery = result.terminal_summary["recoverable_generation"]
        assert recovery["generation"] == handle["generation"]
        assert recovery["temp_branch"] == handle["temp_branch"]
        assert staged.read_bytes() == b"staged planner artifact\n"
        assert untracked.read_bytes() == b"ignored handoff bytes\n"
