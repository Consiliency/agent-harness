import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime.lane_scheduler import worktree_assignments_for_phase_wave
from phase_loop_test_utils import make_repo
from test_phase_worktree_executor import require_sched_red


class WorkerPoolWorktreeAllocTest(unittest.TestCase):
    def test_concurrent_phase_wave_gets_distinct_git_worktrees(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))

            assignments = worktree_assignments_for_phase_wave(
                repo,
                ("A", "B", "C"),
                branch="feature/wp",
                mode="concurrent",
                base_sha="base",
            )

            self.assertEqual({item.lane_id for item in assignments}, {"A", "B", "C"})
            self.assertEqual({item.isolation_mode for item in assignments}, {"git_worktree"})
            self.assertEqual({item.base_sha for item in assignments}, {"base"})
            self.assertEqual(len({item.worktree_path for item in assignments}), 3)

    def test_serialized_phase_wave_uses_main_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))

            assignments = worktree_assignments_for_phase_wave(repo, ("A", "B"), branch="main", mode="serialized")

            self.assertEqual(tuple(item.worktree_path for item in assignments), (str(repo), str(repo)))
            self.assertEqual({item.isolation_mode for item in assignments}, {"main_worktree"})


if __name__ == "__main__":
    unittest.main()


@require_sched_red
def test_phase_wave_assignments_keep_creator_generation_identity():
    """Observe creator custody on the actual runner-dispatched worker job."""
    from unittest.mock import patch

    from phase_loop_runtime import runner, worker_pool
    from phase_loop_runtime.launcher import AuthPreflightResult, LaunchResult
    from phase_loop_test_utils import build_fake_automation_output, commit_fixture_paths, write_phase_plan

    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(Path(td))
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text(
            "# Roadmap\n\n### Phase 1 - Alpha (A)\n**Depends on**\n- (none)\n\n"
            "### Phase 2 - Beta (B)\n**Depends on**\n- (none)\n",
            encoding="utf-8",
        )
        plans = {
            phase: write_phase_plan(repo, phase, roadmap, owned_files=(f"src/{phase.lower()}.py",))
            for phase in ("A", "B")
        }
        commit_fixture_paths(repo, "add dispatch fixture", roadmap, *plans.values())
        observed_jobs = []
        observed_specs = []
        created_handles = {}
        real_pool = worker_pool.run_phase_worker_pool
        real_create = runner.create_phase_worktree

        def observe_create(*args, **kwargs):
            handle = real_create(*args, workspace_mount=Path(td) / "worktrees", **kwargs)
            created_handles[kwargs["phase"]] = handle
            return handle

        def observe_pool(*args, **kwargs):
            observed_jobs.extend(args[2])
            return real_pool(*args, **kwargs)

        def complete_launch(spec, **_kwargs):
            observed_specs.append(spec)
            phase = "A" if "phase-plan-v1-A.md" in spec.prompt_bundle.render_prompt() else "B"
            return LaunchResult(
                command=spec.command,
                returncode=0,
                output=build_fake_automation_output(
                    status="complete",
                    verification_status="passed",
                    artifact=str(plans[phase]),
                    artifact_state="tracked",
                ),
                executor=spec.executor,
            )

        with (
            patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})),
            patch("phase_loop_runtime.runner.create_phase_worktree", side_effect=observe_create),
            patch("phase_loop_runtime.runner.run_phase_worker_pool", side_effect=observe_pool),
            patch("phase_loop_runtime.runner.launch_with_spec", side_effect=complete_launch),
            patch("phase_loop_runtime.worker_pool.launch_with_spec", side_effect=complete_launch),
            patch("phase_loop_runtime.injection._resolve_pack_skill_dirs", return_value={}),
        ):
            runner.run_loop(repo, roadmap, phase_scheduler_mode="concurrent", max_phases=2)

    assert {spec.prompt_bundle.render_prompt().split("phase-plan-v1-")[1][0] for spec in observed_specs} == {"A", "B"}
    assert {job.phase for job in observed_jobs} == {"A", "B"}
    assert all(hasattr(job, "worktree_handle") for job in observed_jobs), (
        "missing production creator-handle dispatch seam"
    )
    for job in observed_jobs:
        assert job.worktree_handle is created_handles[job.phase]
        assert job.spec.wrapped_cwd == str(created_handles[job.phase].worktree_path)
        assert job.worktree_handle.generation == created_handles[job.phase].generation
        assert job.worktree_handle.temp_branch == created_handles[job.phase].temp_branch
        assert job.worktree_handle.lease_authority.identity == created_handles[job.phase].lease_authority.identity
