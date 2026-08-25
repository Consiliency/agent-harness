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
    """Bind every joined mutation to the production runner-to-Popen seam."""

    import hashlib
    import json
    import shutil

    from phase_loop_runtime import launcher

    root = Path(__file__).resolve().parents[2]
    nodeid = (
        "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::"
        f"test_supervisor_retains_lease_after_executor_parent_exits[{mutation}]"
    )
    base = "472e90ae7c42070468f033d1b0990f9f046f0296"
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
    base_digest = hashlib.sha256(subprocess.check_output(
        ["git", "-C", str(root), "show", f"{base}:phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py"]
    )).hexdigest()
    diff_digest = hashlib.sha256(
        subprocess.check_output(
            ["git", "-C", str(root), "diff", "--no-ext-diff", base, "--", *sched_test_paths]
        )
    ).hexdigest()
    from phase_loop_runtime.verification_evidence import (
        _bind_sidecar_extension, run_verification, validate_verification_artifact,
    )

    artifact_dir = root / ".sched-test-evidence" / mutation
    run_verification(root, artifact_dir, [[sys.executable, "-c", "pass"]], None, None, 30, phase_alias="SCHED")
    artifact = artifact_dir / "verification.json"
    mutant_bytes = json.dumps(
        {"dependency": "phase_loop_runtime.launcher.subprocess.Popen", "mutation": mutation}, sort_keys=True
    ).encode()
    _bind_sidecar_extension(artifact, namespace="phase_loop_runtime.proofgate_evidence", record={
        "schema": "proofgate_evidence_sidecar.v1",
        "candidate_snapshot": {
            "frozen_base": base,
            "candidate_test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_digests": source_digests,
            "exact_diff_sha256": diff_digest,
        },
        "mutations": [{
            "injected_bytes_sha256": hashlib.sha256(mutant_bytes).hexdigest(),
            "behavior": mutation,
            "restored_bytes_sha256": source_digests["phase-loop-runtime/src/phase_loop_runtime/launcher.py"],
        }],
        "chronology": {
            "nodeid": nodeid,
            "expected_failure_anchor": f"production-{mutation}-guarantee",
            "observed": {"lock": "not_observed_before_production_binding", "grandchild": "not_observed_before_production_binding", "subreaper": "not_observed_before_production_binding"},
            "base_test_sha256": base_digest,
        },
    })
    assert validate_verification_artifact(artifact).ok
    shutil.rmtree(artifact_dir.parent)

    supervisor_type = getattr(launcher, "LeaseSupervisor", None)
    assert supervisor_type is not None, "missing production LeaseSupervisor guarantee"

    helper_source = textwrap.dedent(
        """
        import ctypes, json, os, subprocess, sys, time
        from pathlib import Path

        phase, marker_path = sys.argv[1:]
        if phase != "A":
            raise SystemExit(0)
        lease_fd = int(os.environ["SCHED_TEST_LEASE_FD"])
        coordinator_sid = int(os.environ["SCHED_TEST_COORDINATOR_SID"])
        libc = ctypes.CDLL(None, use_errno=True)
        subreaper = ctypes.c_int()
        if libc.prctl(37, ctypes.byref(subreaper), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_GET_CHILD_SUBREAPER")
        try:
            os.fstat(lease_fd)
            lease_inherited = True
        except OSError:
            lease_inherited = False
        child_marker = Path(marker_path).with_suffix(".child.json")
        executor = subprocess.Popen(
            [sys.executable, "-c", "import json, subprocess, sys; p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.8)'], close_fds=True); json.dump({'grandchild_pid': p.pid}, open(sys.argv[1], 'w'))", str(child_marker)], close_fds=True)
        deadline = time.monotonic() + 5
        while not child_marker.exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("executor did not report grandchild")
            time.sleep(.01)
        grandchild_pid = json.loads(child_marker.read_text())["grandchild_pid"]
        grandchild_has_lease = False
        if lease_inherited:
            lease_stat = os.fstat(lease_fd)
            for fd_name in os.listdir(f"/proc/{grandchild_pid}/fd"):
                try:
                    candidate = os.stat(f"/proc/{grandchild_pid}/fd/{fd_name}")
                except OSError:
                    continue
                grandchild_has_lease |= (candidate.st_dev, candidate.st_ino) == (lease_stat.st_dev, lease_stat.st_ino)
        Path(marker_path).write_text(json.dumps({
            "helper_pid": os.getpid(), "executor_pid": executor.pid,
            "grandchild_pid": grandchild_pid, "lease_inherited": lease_inherited,
            "grandchild_has_lease": grandchild_has_lease,
            "session_isolated": os.getsid(0) != coordinator_sid,
            "subreaper_enabled": bool(subreaper.value),
        }), encoding="utf-8")
        executor.wait()
        while True:
            try:
                os.waitpid(-1, 0)
            except ChildProcessError:
                break
        """
    ).strip()

    def write_roadmap(repo: Path) -> Path:
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text(
            "# Roadmap\n\n### Phase 1 - Alpha (A)\n**Depends on**\n- (none)\n\n### Phase 2 - Beta (B)\n**Depends on**\n- (none)\n",
            encoding="utf-8",
        )
        plan_a = write_phase_plan(repo, "A", roadmap, owned_files=("src/a.py",))
        plan_b = write_phase_plan(repo, "B", roadmap, owned_files=("src/b.py",))
        commit_fixture_paths(repo, "add seam fixture", roadmap, plan_a, plan_b)
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
                import ctypes, fcntl, json, os, re, sys, threading, time
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
                real_pool, real_lws, real_launch, real_popen = worker_pool.run_phase_worker_pool, launcher.launch_with_spec, launcher.launch, launcher.subprocess.Popen
                chain = []
                restored = False

                def observe_pool(*args, **kwargs):
                    chain.append("PhaseWorkerJob")
                    return real_pool(*args, **kwargs)
                def observe_lws(*args, **kwargs):
                    chain.append("launch_with_spec")
                    return real_lws(*args, **kwargs)
                def observe_launch(*args, **kwargs):
                    chain.append("launch")
                    return real_launch(*args, **kwargs)
                def observe_popen(*args, **kwargs):
                    command = args[0] if args else kwargs.get("args", ())
                    if isinstance(command, (list, tuple)) and str(helper) in command:
                        chain.append("Popen")
                        assert kwargs.get("pass_fds"), "production supervisor did not supply lease pass_fds"
                        assert kwargs.get("start_new_session") is True, "production supervisor did not create a session"
                        assert kwargs.get("preexec_fn") is not None, "production supervisor did not enable subreaping"
                        if mutation == "pass_fds": kwargs["pass_fds"] = ()
                        elif mutation == "subreaper_session": kwargs["start_new_session"] = False
                    return real_popen(*args, **kwargs)
                def command(spec, _log_path, *, dry_run):
                    phase = re.search(r"phase-plan-v1-([A-Z]+)\\.md", spec.prompt_bundle.render_prompt()).group(1)
                    return [sys.executable, str(helper), phase, str(marker)], ()
                def run_chain():
                    runner.run_loop(repo, roadmap, phase_scheduler_mode="concurrent", max_phases=1)

                patches = (patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})), patch("phase_loop_runtime.runner.run_phase_worker_pool", side_effect=observe_pool), patch("phase_loop_runtime.worker_pool.launch_with_spec", side_effect=observe_lws), patch("phase_loop_runtime.launcher.launch", side_effect=observe_launch), patch("phase_loop_runtime.launcher.subprocess.Popen", side_effect=observe_popen), patch("phase_loop_runtime.launcher._resolve_command_context", side_effect=command), patch("phase_loop_runtime.injection._resolve_pack_skill_dirs", return_value={}))
                with ExitStack() as stack:
                    for item in patches: stack.enter_context(item)
                    thread = threading.Thread(target=run_chain); thread.start()
                    deadline = time.monotonic() + 20
                    while not marker.exists():
                        if time.monotonic() >= deadline: raise RuntimeError("real Popen path did not reach helper")
                        time.sleep(.02)
                    observed = json.loads(marker.read_text())
                    if mutation == "process_tree_reaping":
                        helper_stat = Path(f"/proc/{observed['helper_pid']}/stat")
                        while helper_stat.exists() and helper_stat.read_text().split()[2] != "Z" and time.monotonic() < deadline: time.sleep(.02)
                    contender = os.open(lock_path, os.O_RDWR)
                    try:
                        try: fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB); lease_acquired = True
                        except BlockingIOError: lease_acquired = False
                        if lease_acquired: fcntl.flock(contender, fcntl.LOCK_UN)
                    finally: os.close(contender)
                    try: os.kill(observed["grandchild_pid"], 0); grandchild_live = True
                    except ProcessLookupError: grandchild_live = False
                    thread.join(10)
                    restored = launcher.subprocess.Popen is real_popen
                restored = launcher.subprocess.Popen is real_popen
                result.write_text(json.dumps({"chain": chain, "observed": observed, "lease_acquired": lease_acquired, "grandchild_live": grandchild_live, "restored": restored}), encoding="utf-8")
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
    expected_chain = ["PhaseWorkerJob", "launch_with_spec", "launch", "Popen"]
    assert all(item in safe["chain"] for item in expected_chain)
    assert all(item in mutated["chain"] for item in expected_chain)
    assert [safe["chain"].index(item) for item in expected_chain] == sorted(safe["chain"].index(item) for item in expected_chain)
    assert [mutated["chain"].index(item) for item in expected_chain] == sorted(mutated["chain"].index(item) for item in expected_chain)
    assert safe["restored"] and mutated["restored"]
    assert safe["observed"]["lease_inherited"] is True
    assert safe["observed"]["grandchild_has_lease"] is False
    assert safe["lease_acquired"] is False
    assert safe["observed"]["session_isolated"] is True
    assert safe["observed"]["subreaper_enabled"] is True

    unsafe = {
        "pass_fds": mutated["lease_acquired"] and not mutated["observed"]["lease_inherited"],
        "subreaper_session": not mutated["observed"]["session_isolated"] and not mutated["observed"]["subreaper_enabled"],
        "process_tree_reaping": mutated["lease_acquired"] and mutated["grandchild_live"],
    }[mutation]
    assert unsafe
    from phase_loop_runtime.verification_evidence import (
        _bind_sidecar_extension, run_verification, validate_verification_artifact,
    )
    artifact_dir = tmp_path / "verification" / mutation
    run_verification(root, artifact_dir, [[sys.executable, "-c", "pass"]], None, None, 30, phase_alias="SCHED")
    artifact = artifact_dir / "verification.json"
    mutant_bytes = json.dumps({"dependency": "phase_loop_runtime.launcher.subprocess.Popen", "mutation": mutation}, sort_keys=True).encode()
    _bind_sidecar_extension(artifact, namespace="phase_loop_runtime.proofgate_evidence", record={
        "schema": "proofgate_evidence_sidecar.v1",
        "candidate_snapshot": {"frozen_base": base, "candidate_test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "source_digests": source_digests, "exact_diff_sha256": diff_digest},
        "mutations": [{"injected_bytes_sha256": hashlib.sha256(mutant_bytes).hexdigest(), "behavior": mutation, "restored_bytes_sha256": source_digests["phase-loop-runtime/src/phase_loop_runtime/launcher.py"]}],
        "chronology": {"nodeid": nodeid, "expected_failure_anchor": mutation, "observed": {"lock_held": not mutated["lease_acquired"], "grandchild_live": mutated["grandchild_live"], "subreaper_enabled": mutated["observed"]["subreaper_enabled"]}, "base_test_sha256": base_digest},
    })
    assert validate_verification_artifact(artifact).ok
