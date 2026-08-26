"""v45 SCHEDHARDEN — real-executor worktree integration (#130).

The v45 SCHED concurrent scheduler launches each ready phase's child in its OWN
git worktree (``--phase-scheduler concurrent``). The original integration step,
``integrate_phase_worktree``, only moves *committed* work back to the pipeline
branch (``rev-list base..temp``). But a real phase executor leaves its verified
work *DIRTY* (uncommitted) in the worktree and emits ``awaiting_phase_closeout``
— the parent runner's closeout is what stages+commits the dirty phase-owned
files (``_perform_phase_closeout`` in runner.py). So against a real (dirty)
child, ``integrate_phase_worktree`` is a no-op: the work never reaches main, the
finalize closeout runs on a clean main tree and finds nothing to commit, and the
worktree is torn down — silently losing the child's work.

These tests use a *side-effect* fake that writes real dirty owned files into the
child's worktree (the status-only SCHED fakes never exercised this). They prove:

  * with the real-exec integration ON, each concurrent child's dirty work is
    transported onto main and committed by the existing closeout → ``complete``;
  * two concurrent siblings BOTH land (the second's patch applies cleanly after
    the first's closeout commit advanced main — the disjointness-gate claim);
  * with the flag OFF (default cutover state), the dirty work is lost — the
    regression the fix repairs, proving the assertion is not green-on-both-sides.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.launcher import LaunchResult
from phase_loop_runtime.runner import run_loop
from phase_loop_test_utils import build_fake_automation_output, commit_fixture_paths, make_repo, write_phase_plan
from test_phase_worktree_executor import require_sched_red

MIDDLE_DIRTY = ("EXTRACT", "IMPORT")

import pytest

# TESTDECOUPLE SL-1 (overlay-dependent): builds a skill/adoption bundle or runs the
# runtime execute path, which resolves the dotfiles skill-source / profile overlay
# (claude-config/*, codex-config/* …) absent standalone. Run-time integration: the
# conftest hook skips it when no dotfiles tree is reachable.
def _phase_from_spec(spec) -> str:
    match = re.search(r"phase-plan-v1-([A-Z_]+)\.md", spec.prompt_bundle.render_prompt())
    assert match is not None, "spec prompt missing plan artifact reference"
    return match.group(1)


def _committed_on_main(repo: Path, rel_path: str) -> bool:
    """True iff ``rel_path`` exists in main's HEAD tree (i.e. was committed)."""

    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{rel_path}"],
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.mark.dotfiles_integration
class V45SchedHardenRealExecTest(unittest.TestCase):
    def setUp(self):
        # Pin cpu_count so the 2-wide middle wave actually runs 2 workers.
        patcher = patch("phase_loop_runtime.worker_pool.os.cpu_count", return_value=8)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.owned = {
            "FOUND": "src/found.py",
            "EXTRACT": "src/extract.py",
            "IMPORT": "src/import_.py",
            "VERIFY": "src/verify.py",
        }

    def _write_roadmap(self, repo: Path) -> Path:
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text(
            textwrap.dedent(
                """
                # Roadmap

                ### Phase 0 - Foundation (FOUND)
                **Depends on**
                - (none)

                ---

                ### Phase 1 - Extract (EXTRACT)
                **Depends on**
                - FOUND

                ---

                ### Phase 2 - Import (IMPORT)
                **Depends on**
                - FOUND

                ---

                ### Phase 3 - Verify (VERIFY)
                **Depends on**
                - EXTRACT
                - IMPORT
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return roadmap

    def _write_plans(self, repo: Path, roadmap: Path) -> None:
        plans = [
            write_phase_plan(repo, phase, roadmap, owned_files=(owned_file,))
            for phase, owned_file in self.owned.items()
        ]
        commit_fixture_paths(repo, "add schedharden plans", roadmap, *plans)

    def _fake_launch(self):
        """A side-effect fake.

        Middle phases behave like a real executor: write the phase-owned file
        into the child's worktree and leave it DIRTY (bare LaunchResult → the
        runner's executed-fallback dirty path → awaiting_phase_closeout). FOUND
        and VERIFY self-report complete with a clean tree to isolate the variable
        under test (concurrent dirty-worktree integration).
        """

        def fake_launch(spec, dry_run=False, log_path=None, stream_output=False, **kwargs):
            phase = _phase_from_spec(spec)
            if phase in MIDDLE_DIRTY:
                target = Path(spec.wrapped_cwd) / self.owned[phase]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"{phase} real-exec output\n", encoding="utf-8")
                # Bare result: no automation closeout → executed fallback → the
                # runner detects the dirty owned file and reduces to
                # awaiting_phase_closeout, then closes out (commits) on main.
                return LaunchResult(command=spec.command, returncode=0, executor=spec.executor)
            return LaunchResult(
                command=spec.command,
                returncode=0,
                output=build_fake_automation_output(
                    status="complete",
                    verification_status="passed",
                    artifact=str(Path(spec.wrapped_cwd) / "plans" / f"phase-plan-v1-{phase}.md"),
                    artifact_state="tracked",
                ),
                executor=spec.executor,
            )

        return fake_launch

    def _run(self, repo: Path, roadmap: Path):
        def fake_worktree_path(repo_arg, *, branch, lane_id, project=None, workspace_mount=None):
            return repo.parent / "worktrees" / f"{branch}-{lane_id}"

        with patch("phase_loop_runtime.runner.launch_with_spec", side_effect=self._fake_launch()), patch(
            "phase_loop_runtime.worker_pool.launch_with_spec", side_effect=self._fake_launch()
        ), patch(
            "phase_loop_runtime.phase_worktree_executor.lane_worktree_path",
            side_effect=fake_worktree_path,
        ):
            # closeout_mode="commit": a real concurrent run must commit each phase's
            # closeout (the default "manual" mode stops at awaiting_phase_closeout
            # and would strand dirty work on main across waves).
            return run_loop(
                repo,
                roadmap,
                phase_scheduler_mode="concurrent",
                closeout_mode="commit",
                max_phases=1,
            )

    def test_concurrent_real_exec_dirty_work_commits_on_main(self):
        with patch.dict(os.environ, {"PHASE_LOOP_CONCURRENT_REAL_EXEC": "true"}):
            with tempfile.TemporaryDirectory() as td:
                repo = make_repo(Path(td))
                roadmap = self._write_roadmap(repo)
                self._write_plans(repo, roadmap)

                snapshot, _results = self._run(repo, roadmap)

                # Both concurrent children's verified work landed and closed out.
                for phase in MIDDLE_DIRTY:
                    self.assertEqual(snapshot.phases[phase], "complete", phase)
                    self.assertTrue(
                        _committed_on_main(repo, self.owned[phase]),
                        f"{phase} dirty work was not committed on main",
                    )
                # No work stranded in the main tree.
                dirty = subprocess.check_output(
                    ["git", "-C", str(repo), "status", "--porcelain"], text=True
                ).strip()
                self.assertEqual(dirty, "", f"main tree left dirty: {dirty!r}")

    def test_concurrent_real_exec_never_commits_preexisting_unowned_dirt(self):
        # Baseline-composition safety: pre_launch_dirty_paths is captured against
        # MAIN and completion is measured on main after transport, so unrelated
        # dirt already present on main is classified as pre-existing — never folded
        # into a phase's ownership-gated closeout commit. (Unexpected main dirt may
        # legitimately BLOCK a phase via the runner's completion-dirty safety check;
        # the invariant under test is no *silent corruption*: the operator's file is
        # neither committed as phase output nor mutated.)
        with patch.dict(os.environ, {"PHASE_LOOP_CONCURRENT_REAL_EXEC": "true"}):
            with tempfile.TemporaryDirectory() as td:
                repo = make_repo(Path(td))
                roadmap = self._write_roadmap(repo)
                self._write_plans(repo, roadmap)
                # Unrelated, unowned dirt present on main before the run.
                (repo / "scratch.txt").write_text("operator scratch\n", encoding="utf-8")

                self._run(repo, roadmap)

                # The pre-existing unowned file was neither committed nor mutated.
                self.assertFalse(_committed_on_main(repo, "scratch.txt"))
                self.assertEqual((repo / "scratch.txt").read_text(), "operator scratch\n")

    def test_without_flag_concurrent_dirty_work_is_lost(self):
        # Cutover safety / regression proof: with the flag OFF (default), the
        # legacy committed-only integration is a no-op on dirty children, so the
        # work never reaches main — the phase BLOCKS (the closeout finds no
        # phase-owned dirty paths) and the worktree is torn down, discarding the
        # child's work. This is the behavior the fix repairs; it must FAIL the
        # land-on-main assertions to prove the green above is real.
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = self._write_roadmap(repo)
            self._write_plans(repo, roadmap)

            snapshot, _results = self._run(repo, roadmap)

            for phase in MIDDLE_DIRTY:
                self.assertFalse(
                    _committed_on_main(repo, self.owned[phase]),
                    f"{phase}: legacy integration unexpectedly landed dirty work without the flag",
                )
                # Pin the specific failure mode: a loud block, not a silent
                # complete-with-work-gone.
                self.assertEqual(
                    snapshot.phases[phase], "blocked",
                    f"{phase}: expected a block when dirty work never reached main",
                )

    def test_concurrent_transfer_conflict_preserves_branch_and_blocks(self):
        # Gate-bypass safety net at the runner level: if transport cannot apply,
        # the runner records a typed conflict event, KEEPS the temp branch
        # (work recoverable), and lets finalize block — never a silent success.
        from phase_loop_runtime.phase_worktree_executor import WorktreeTransferResult

        def fake_transfer(repo, handle, *, commit_message=None):
            return WorktreeTransferResult(
                phase=handle.phase,
                temp_branch=handle.temp_branch,
                had_changes=True,
                applied=False,
                conflict=True,
                reason="forced conflict for test",
            )

        with patch.dict(os.environ, {"PHASE_LOOP_CONCURRENT_REAL_EXEC": "true"}):
            with tempfile.TemporaryDirectory() as td:
                repo = make_repo(Path(td))
                roadmap = self._write_roadmap(repo)
                self._write_plans(repo, roadmap)

                with patch(
                    "phase_loop_runtime.runner.transfer_phase_worktree_dirty",
                    side_effect=fake_transfer,
                ):
                    snapshot, _results = self._run(repo, roadmap)

                for phase in MIDDLE_DIRTY:
                    self.assertNotEqual(snapshot.phases[phase], "complete", phase)
                    self.assertFalse(_committed_on_main(repo, self.owned[phase]), phase)
                from phase_loop_runtime.events import read_events

                conflicts = [
                    e
                    for e in read_events(repo)
                    if e["action"] == "coordinator.concurrent_transfer_conflict"
                ]
                self.assertEqual({c["phase"] for c in conflicts}, set(MIDDLE_DIRTY))
                self.assertTrue(
                    all(c["metadata"]["coordinator"]["transfer"]["conflict"] for c in conflicts)
                )
                self.assertTrue(
                    all(c["metadata"]["coordinator"]["preserved_branch"] for c in conflicts)
                )

    def test_concurrent_real_exec_with_manual_closeout_is_refused(self):
        # Footgun guard: manual closeout would strand transported dirty work on
        # main across waves, so the runner must refuse at startup rather than fail
        # opaquely at the next wave's start gate.
        with patch.dict(os.environ, {"PHASE_LOOP_CONCURRENT_REAL_EXEC": "true"}):
            with tempfile.TemporaryDirectory() as td:
                repo = make_repo(Path(td))
                roadmap = self._write_roadmap(repo)
                self._write_plans(repo, roadmap)
                with self.assertRaises(ValueError) as ctx:
                    run_loop(
                        repo,
                        roadmap,
                        phase_scheduler_mode="concurrent",
                        closeout_mode="manual",
                        max_phases=1,
                    )
                self.assertIn("closeout-mode", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


@pytest.mark.parametrize("mutation", ("pass_fds", "subreaper_session", "process_tree_reaping"))
@require_sched_red
def test_supervisor_retains_lease_after_executor_parent_exits(tmp_path, mutation):
    """Bind the joined RED probes to the runner-to-Popen custody seam."""

    import hashlib
    import inspect
    import json
    import shutil

    from phase_loop_runtime import launcher, runner, worker_pool

    root = Path(__file__).resolve().parents[2]
    nodeid = (
        "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::"
        f"test_supervisor_retains_lease_after_executor_parent_exits[{mutation}]"
    )
    base = "a4db421435058601dca34574cdf115cf9c94ab72"
    source_paths = (
        "phase-loop-runtime/src/phase_loop_runtime/runner.py",
        "phase-loop-runtime/src/phase_loop_runtime/worker_pool.py",
        "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
    )
    sched_test_paths = (
        "phase-loop-runtime/tests/test_phase_worktree_executor.py",
        "phase-loop-runtime/tests/test_phase_loop_lane_scheduler.py",
        "phase-loop-runtime/tests/test_phase_loop_concurrent_phase_dispatch.py",
        "phase-loop-runtime/tests/test_dispatch_lock_reentrancy.py",
        "phase-loop-runtime/tests/test_phase_loop_work_unit_runner.py",
        "phase-loop-runtime/tests/test_phase_loop_runner.py",
        "phase-loop-runtime/tests/test_phase_loop_launcher.py",
        "phase-loop-runtime/tests/test_workerpool_failure_isolation.py",
        "phase-loop-runtime/tests/test_workerpool_parallel.py",
        "phase-loop-runtime/tests/test_workerpool_worktree_alloc.py",
        "phase-loop-runtime/tests/test_v34_parallel_dispatch_soak.py",
        "phase-loop-runtime/tests/test_phase_loop_v45_sched.py",
        "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py",
    )
    source_digests = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in source_paths
    }
    propagation_surfaces = (
        runner.run_loop,
        launcher.launch_with_spec,
        launcher.launch,
    )
    propagation_ready = all(
        "lease_authority" in inspect.signature(surface).parameters for surface in propagation_surfaces
    )
    job_custody_ready = "lease_authority" in inspect.signature(worker_pool.PhaseWorkerJob).parameters
    supervisor_type = getattr(launcher, "LeaseSupervisor", None)

    helper_source = textwrap.dedent(
        """
        import ctypes, json, os, subprocess, sys, time
        from pathlib import Path

        phase, marker_path = sys.argv[1:]
        if phase != "A":
            raise SystemExit(0)
        lease_fd = int(os.environ["SCHED_TEST_LEASE_FD"])
        lease_identity = tuple(map(int, os.environ["SCHED_TEST_LEASE_IDENTITY"].split(":")))
        coordinator_sid = int(os.environ["SCHED_TEST_COORDINATOR_SID"])
        libc = ctypes.CDLL(None, use_errno=True)
        subreaper = ctypes.c_int()
        if libc.prctl(37, ctypes.byref(subreaper), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_GET_CHILD_SUBREAPER")
        try:
            lease = os.fstat(lease_fd)
            lease_inherited = (lease.st_dev, lease.st_ino) == lease_identity
        except OSError:
            lease_inherited = False
        child_marker = Path(marker_path).with_suffix(".child.json")
        release_path = Path(marker_path).with_suffix(".release")
        done_path = Path(marker_path).with_suffix(".done")
        executor = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import json, subprocess, sys\\n"
                "marker, done = sys.argv[1:]\\n"
                "grandchild = subprocess.Popen([sys.executable, '-c', "
                "'from pathlib import Path\\\\nimport sys, time\\\\ndone = Path(sys.argv[1])\\\\n"
                "deadline = time.monotonic() + 10\\\\nwhile not done.exists() and time.monotonic() < deadline:\\\\n    time.sleep(.01)', str(done)], close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\\n"
                "json.dump({'grandchild_pid': grandchild.pid}, open(marker, 'w'))\\n",
                str(child_marker),
                str(done_path),
            ],
            close_fds=True,
        )
        deadline = time.monotonic() + 5
        while not child_marker.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("executor did not report grandchild")
            time.sleep(.01)
        grandchild_pid = json.loads(child_marker.read_text())["grandchild_pid"]
        grandchild_lease_fds = []
        for fd_name in os.listdir(f"/proc/{grandchild_pid}/fd"):
            try:
                candidate = os.stat(f"/proc/{grandchild_pid}/fd/{fd_name}")
            except OSError:
                continue
            if (candidate.st_dev, candidate.st_ino) == lease_identity:
                grandchild_lease_fds.append(fd_name)
        executor.wait()
        Path(marker_path).write_text(json.dumps({
            "helper_pid": os.getpid(), "executor_pid": executor.pid,
            "grandchild_pid": grandchild_pid, "lease_inherited": lease_inherited,
            "grandchild_lease_fds": grandchild_lease_fds,
            "session_isolated": os.getsid(0) != coordinator_sid,
            "subreaper_enabled": bool(subreaper.value),
            "executor_exited": True,
        }), encoding="utf-8")
        while not release_path.exists():
            time.sleep(.01)
        # Descendant reaping belongs to the production supervisor.  In particular,
        # this helper never sweeps the grandchild before the coordinator observes it.
        """
    ).strip()

    def write_roadmap(repo: Path) -> Path:
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text(
            "# Roadmap\n\n### Phase 1 - Alpha (A)\n**Depends on**\n- (none)\n\n### Phase 2 - Beta (B)\n**Depends on**\n- (none)\n",
            encoding="utf-8",
        )
        plans = tuple(write_phase_plan(repo, phase, roadmap, owned_files=(f"src/{phase.lower()}.py",)) for phase in ("A", "B"))
        commit_fixture_paths(repo, "add seam fixture", roadmap, *plans)
        return roadmap

    def probe(case: str) -> dict:
        case_root = tmp_path / case
        repo = make_repo(case_root)
        roadmap = write_roadmap(repo)
        helper_path = case_root / "helper.py"
        marker_path = case_root / "marker.json"
        result_path = case_root / "result.json"
        helper_path.write_text(helper_source, encoding="utf-8")
        coordinator = case_root / "coordinator.py"
        coordinator.write_text(
            textwrap.dedent(
                """
                import ctypes, fcntl, inspect, json, os, re, sys, threading, time
                from contextlib import ExitStack
                from pathlib import Path
                from unittest.mock import patch
                from phase_loop_runtime import launcher, runner, worker_pool
                from phase_loop_runtime.launcher import AuthPreflightResult

                repo, roadmap, helper, marker, result = map(Path, sys.argv[1:6])
                mutation = sys.argv[6]
                lock_path = result.parent / "lease.lock"
                lease_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
                fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lease_stat = os.fstat(lease_fd)
                lease_identity = (lease_stat.st_dev, lease_stat.st_ino)
                class LeaseAuthority:
                    generation = "sched-lease"
                    def __init__(self, fd): self.fd = fd
                    def fileno(self): return self.fd
                authority = LeaseAuthority(lease_fd)
                real_pool, real_create, real_lws, real_launch, real_popen = worker_pool.run_phase_worker_pool, runner.create_phase_worktree, launcher.launch_with_spec, launcher.launch, launcher.subprocess.Popen
                supervisor_type = getattr(launcher, "LeaseSupervisor", None)
                original_reaper = getattr(supervisor_type, "reap_descendants", None)
                chain, errors = [], []
                production_spawn = None
                mutation_applied = False
                reaping_mutation_applied = False
                job_lease_identity = None

                def direct_child_only(supervisor, *args, **kwargs):
                    return supervisor.reap_direct_child(*args, **kwargs)
                def observe_pool(*args, **kwargs):
                    global job_lease_identity
                    chain.append("PhaseWorkerJob")
                    for job in args[2]:
                        if job.phase == "A":
                            lease_authority = getattr(job, "lease_authority", None)
                            if lease_authority is not None:
                                stat = os.fstat(lease_authority.fileno())
                                job_lease_identity = (stat.st_dev, stat.st_ino)
                    return real_pool(*args, **kwargs)
                def isolated_create(*args, **kwargs):
                    return real_create(*args, workspace_mount=result.parent / "worktrees", **kwargs)
                def observe_lws(*args, **kwargs):
                    chain.append("launch_with_spec")
                    return real_lws(*args, **kwargs)
                def observe_launch(*args, **kwargs):
                    chain.append("launch")
                    return real_launch(*args, **kwargs)
                def observe_popen(*args, **kwargs):
                    global production_spawn, mutation_applied
                    command = args[0] if args else kwargs.get("args", ())
                    if isinstance(command, (list, tuple)) and str(helper) in command:
                        chain.append("Popen")
                        production_spawn = {
                            "pass_fds": tuple(kwargs.get("pass_fds", ())),
                            "session": kwargs.get("start_new_session") is True,
                            "subreaper": kwargs.get("preexec_fn") is not None,
                        }
                        if lease_fd in production_spawn["pass_fds"]:
                            if mutation == "pass_fds":
                                kwargs["pass_fds"] = ()
                                mutation_applied = True
                            elif mutation == "subreaper_session":
                                kwargs["start_new_session"] = False
                                kwargs["preexec_fn"] = None
                                mutation_applied = True
                        env = dict(kwargs.get("env") or os.environ)
                        env.update({"SCHED_TEST_LEASE_FD": str(lease_fd), "SCHED_TEST_LEASE_IDENTITY": f"{lease_identity[0]}:{lease_identity[1]}", "SCHED_TEST_COORDINATOR_SID": str(os.getsid(0))})
                        kwargs["env"] = env
                    return real_popen(*args, **kwargs)
                def command(spec, _log_path, *, dry_run):
                    phase = re.search(r"phase-plan-v1-([A-Z]+)\\.md", spec.prompt_bundle.render_prompt()).group(1)
                    return [sys.executable, str(helper), phase, str(marker)], ()
                def run_chain():
                    try:
                        kwargs = {"phase_scheduler_mode": "concurrent", "max_phases": 2}
                        if "lease_authority" in inspect.signature(runner.run_loop).parameters:
                            kwargs["lease_authority"] = authority
                        runner.run_loop(repo, roadmap, **kwargs)
                    except BaseException as exc:
                        errors.append(repr(exc))

                patches = (patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})), patch("phase_loop_runtime.runner.create_phase_worktree", side_effect=isolated_create), patch("phase_loop_runtime.runner.run_phase_worker_pool", side_effect=observe_pool), patch("phase_loop_runtime.runner.launch_with_spec", side_effect=observe_lws), patch("phase_loop_runtime.worker_pool.launch_with_spec", side_effect=observe_lws), patch("phase_loop_runtime.launcher.launch", side_effect=observe_launch), patch("phase_loop_runtime.launcher.subprocess.Popen", side_effect=observe_popen), patch("phase_loop_runtime.launcher._resolve_command_context", side_effect=command), patch("phase_loop_runtime.injection._resolve_pack_skill_dirs", return_value={}))
                with ExitStack() as stack:
                    for item in patches: stack.enter_context(item)
                    if mutation == "process_tree_reaping" and original_reaper is not None:
                        stack.enter_context(patch.object(supervisor_type, "reap_descendants", direct_child_only))
                        reaping_mutation_applied = True
                    thread = threading.Thread(target=run_chain); thread.start()
                    deadline = time.monotonic() + 20
                    while not marker.exists() and not errors:
                        if time.monotonic() >= deadline: raise RuntimeError("real Popen path did not reach helper")
                        time.sleep(.02)
                    observed = json.loads(marker.read_text()) if marker.exists() else None
                    def process_running(pid):
                        stat_path = Path(f"/proc/{pid}/stat")
                        try: return stat_path.read_text().split()[2] != "Z"
                        except OSError: return False
                    def process_ppid(pid):
                        stat_path = Path(f"/proc/{pid}/stat")
                        try: return int(stat_path.read_text().split()[3])
                        except (OSError, ValueError, IndexError): return None
                    # The coordinator's lock must be gone before contention: only a
                    # descriptor actually retained by production may deny this lock.
                    os.close(lease_fd)
                    contender = os.open(lock_path, os.O_RDWR)
                    try:
                        try: fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB); lease_acquired = True
                        except BlockingIOError: lease_acquired = False
                        if lease_acquired: fcntl.flock(contender, fcntl.LOCK_UN)
                    finally: os.close(contender)
                    direct_executor_dead = not process_running(observed["executor_pid"])
                    supervisor_alive = process_running(observed["helper_pid"])
                    grandchild_live = process_running(observed["grandchild_pid"])
                    marker.with_suffix(".release").write_text("release\\n")
                    thread.join(10)
                    launch_returned = not thread.is_alive()
                    post_launch_grandchild_live = process_running(observed["grandchild_pid"])
                    post_launch_grandchild_ppid = process_ppid(observed["grandchild_pid"])
                    marker.with_suffix(".done").write_text("done\\n")
                    deadline = time.monotonic() + 5
                    while process_running(observed["grandchild_pid"]) and time.monotonic() < deadline:
                        time.sleep(.02)
                    grandchild_released_after_done = not process_running(observed["grandchild_pid"])
                result.write_text(json.dumps({"chain": chain, "observed": observed, "lease_identity": lease_identity, "job_lease_identity": job_lease_identity, "lease_acquired": lease_acquired, "direct_executor_dead": direct_executor_dead, "supervisor_alive": supervisor_alive, "grandchild_live": grandchild_live, "launch_returned": launch_returned, "post_launch_grandchild_live": post_launch_grandchild_live, "post_launch_grandchild_ppid": post_launch_grandchild_ppid, "grandchild_released_after_done": grandchild_released_after_done, "errors": errors, "production_spawn": production_spawn, "mutation_applied": mutation_applied, "reaping_mutation_applied": reaping_mutation_applied, "restored_popen": launcher.subprocess.Popen is real_popen, "restored_reaper": getattr(supervisor_type, "reap_descendants", None) is original_reaper}), encoding="utf-8")
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(item for item in sys.path if item)
        completed = subprocess.run(
            [sys.executable, str(coordinator), str(repo), str(roadmap), str(helper_path), str(marker_path), str(result_path), case],
            env=env, capture_output=True, text=True, timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(result_path.read_text(encoding="utf-8"))

    safe = probe("safe")
    mutated = probe(mutation)
    expected_chain = ("PhaseWorkerJob", "launch_with_spec", "launch", "Popen")
    for probe_result in (safe, mutated):
        assert probe_result["errors"] == []
        assert all(item in probe_result["chain"] for item in expected_chain)
        assert [probe_result["chain"].index(item) for item in expected_chain] == sorted(
            probe_result["chain"].index(item) for item in expected_chain
        )
        assert probe_result["restored_popen"] is True
        assert probe_result["launch_returned"] is True

    assert safe["direct_executor_dead"] is True
    assert mutated["direct_executor_dead"] is True
    assert all("post_launch_grandchild_live" in probe_result for probe_result in (safe, mutated))

    unsafe = {
        "pass_fds": mutated["mutation_applied"] and mutated["lease_acquired"] and not mutated["observed"]["lease_inherited"],
        "subreaper_session": mutated["mutation_applied"] and not mutated["observed"]["session_isolated"] and not mutated["observed"]["subreaper_enabled"],
        "process_tree_reaping": (
            mutated["reaping_mutation_applied"]
            and mutated["direct_executor_dead"]
            and mutated["launch_returned"]
            and mutated["post_launch_grandchild_live"]
            and not safe["post_launch_grandchild_live"]
        ),
    }[mutation]

    from phase_loop_runtime.verification_evidence import (
        _bind_sidecar_extension,
        run_verification,
        validate_verification_artifact,
    )

    candidate = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    candidate_tree = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True).strip()
    target_path = "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py"
    target_blob = subprocess.check_output(["git", "-C", str(root), "rev-parse", f"HEAD:{target_path}"], text=True).strip()
    exact_diff_sha256 = hashlib.sha256(
        subprocess.check_output(["git", "-C", str(root), "diff", "--no-ext-diff", f"{base}..{candidate}", "--", *sched_test_paths])
    ).hexdigest()
    source_sha256 = hashlib.sha256(b"".join((root / path).read_bytes() for path in source_paths)).hexdigest()
    mutation_sources = {
        "pass_fds": ("phase_loop_runtime.launcher.subprocess.Popen", "observe_popen", b'kwargs["pass_fds"] = ()'),
        "subreaper_session": ("phase_loop_runtime.launcher.subprocess.Popen", "observe_popen", b'kwargs["start_new_session"] = False; kwargs["preexec_fn"] = None'),
        "process_tree_reaping": ("phase_loop_runtime.launcher.LeaseSupervisor.reap_descendants", "direct_child_only", b"return supervisor.reap_direct_child(*args, **kwargs)"),
    }
    named_dependency, callable_identity, injected_source = mutation_sources[mutation]
    observation_keys = ("lease_inherited", "grandchild_lease_fds", "session_isolated", "subreaper_enabled", "executor_exited")
    mutation_record = {
        "parameter_id": f"sched.supervisor.{mutation}",
        "named_dependency": named_dependency,
        "callable_identity": callable_identity,
        "injected_source_bytes": injected_source.decode("utf-8"),
        "injected_source_sha256": hashlib.sha256(injected_source).hexdigest(),
        "safe_observation": {key: safe["observed"][key] for key in observation_keys} | {"lease_acquired": safe["lease_acquired"], "supervisor_alive": safe["supervisor_alive"], "grandchild_live": safe["grandchild_live"], "post_launch_grandchild_live": safe["post_launch_grandchild_live"]},
        "mutated_observation": {key: mutated["observed"][key] for key in observation_keys} | {"lease_acquired": mutated["lease_acquired"], "supervisor_alive": mutated["supervisor_alive"], "grandchild_live": mutated["grandchild_live"], "post_launch_grandchild_live": mutated["post_launch_grandchild_live"], "post_launch_grandchild_ppid": mutated["post_launch_grandchild_ppid"]},
        "mutation_applied": mutated["reaping_mutation_applied"] if mutation == "process_tree_reaping" else mutated["mutation_applied"],
        "unsafe_discrimination": unsafe,
        "restoration_proof": {"popen_restored": mutated["restored_popen"], "reaper_restored": mutated["restored_reaper"]},
        "restored_source_digests": source_digests,
    }
    artifact_dir = root / f".sched-joined-evidence-{hashlib.sha256(nodeid.encode()).hexdigest()[:16]}"
    try:
        assert artifact_dir.is_relative_to(root)
        run_verification(root, artifact_dir, [[sys.executable, "-c", "pass"]], None, None, 30, phase_alias="SCHED")
        artifact = artifact_dir / "verification.json"
        assert artifact.parent == artifact_dir
        _bind_sidecar_extension(
            artifact,
            namespace="phase_loop_runtime.proofgate_evidence",
            record={
                "schema": "proofgate_evidence_sidecar.v1",
                "candidate_snapshot": {
                    "candidate": candidate, "candidate_tree": candidate_tree, "frozen_base": base,
                    "phase": "SCHED", "nodeid": nodeid, "target_path": target_path,
                    "target_blob": target_blob, "exact_diff_sha256": exact_diff_sha256,
                    "source_digests": source_digests, "source_sha256": source_sha256,
                    "reference_fixture_used": False,
                },
                "mutations": {"parameters": [mutation_record]},
                "chronology": {"expected_failure_anchor": mutation, "safe_before_mutation": True},
            },
        )
        assert validate_verification_artifact(artifact).ok
        assert mutation_record["parameter_id"] == f"sched.supervisor.{mutation}"
        assert mutation_record["restored_source_digests"] == source_digests
    finally:
        shutil.rmtree(artifact_dir, ignore_errors=True)

    assert propagation_ready and job_custody_ready and supervisor_type is not None, "missing production lease-supervisor propagation guarantee"
    assert safe["job_lease_identity"] == safe["lease_identity"]
    assert safe["production_spawn"]["session"] is True
    assert safe["production_spawn"]["subreaper"] is True
    assert safe["production_spawn"]["pass_fds"]
    assert safe["observed"]["lease_inherited"] is True
    assert safe["observed"]["grandchild_lease_fds"] == []
    assert safe["lease_acquired"] is False
    assert safe["observed"]["session_isolated"] is True
    assert safe["observed"]["subreaper_enabled"] is True
    assert safe["observed"]["executor_exited"] is True
    assert safe["supervisor_alive"] is True
    assert safe["grandchild_live"] is True
    assert mutated["restored_reaper"] is True
    assert safe["grandchild_released_after_done"] is True
    assert mutated["grandchild_released_after_done"] is True
    assert "waitpid(-1" not in inspect.getsource(supervisor_type.reap_descendants).replace(" ", ""), (
        "two concurrent worker supervisors must wait only for their own descendants"
    )
    assert unsafe
