import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.launcher import LaunchResult
from phase_loop_runtime.worker_pool import PhaseWorkerJob, run_phase_worker_pool
from phase_loop_test_utils import make_repo
from test_phase_worktree_executor import require_sched_red


class WorkerPoolParallelTest(unittest.TestCase):
    def test_runs_workers_concurrently_and_writes_summaries(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.parent.mkdir(parents=True, exist_ok=True)
            roadmap.write_text("# Roadmap\n", encoding="utf-8")
            jobs = tuple(PhaseWorkerJob(phase=phase, spec=_Spec(phase)) for phase in ("A", "B", "C"))
            started: list[str] = []

            def fake_launch(spec, **kwargs):
                started.append(spec.phase)
                time.sleep(0.05)
                return LaunchResult(command=["fake", spec.phase], returncode=0, executor="codex")

            before = time.monotonic()
            with patch("phase_loop_runtime.worker_pool.launch_with_spec", side_effect=fake_launch):
                results = run_phase_worker_pool(repo, roadmap, jobs, max_workers=3)
            elapsed = time.monotonic() - before

            self.assertLess(elapsed, 0.14)
            self.assertEqual(tuple(item.phase for item in results), ("A", "B", "C"))
            self.assertEqual(set(started), {"A", "B", "C"})
            for item in results:
                self.assertTrue(item.summary_path.exists())
                self.assertEqual(item.terminal_summary["terminal_status"], "complete")


class _Spec:
    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.executor = "codex"


if __name__ == "__main__":
    unittest.main()


@require_sched_red
def test_worker_pool_propagates_run_identity_and_lease_authority():
    captured = {}

    def fake_launch(spec, **kwargs):
        captured.update(kwargs)
        return LaunchResult(command=["fake"], returncode=0, executor="codex")

    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(Path(td))
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.parent.mkdir(parents=True, exist_ok=True)
        roadmap.write_text("# Roadmap\n", encoding="utf-8")
        lease = object()
        job = PhaseWorkerJob(
            phase="A",
            spec=_Spec("A"),
            caller_run_id="sched-run-1",
            lease_authority=lease,
        )
        with patch("phase_loop_runtime.worker_pool.launch_with_spec", side_effect=fake_launch):
            run_phase_worker_pool(repo, roadmap, (job,), max_workers=1)

    assert captured["caller_run_id"] == "sched-run-1"
    assert captured["lease_authority"] is lease
