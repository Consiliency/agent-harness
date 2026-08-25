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
    """Exercise the future real supervisor contract after a live seam probe.

    The initial probe deliberately uses today's launcher seam and records its
    restoration before asserting the missing typed supervisor.  Once SL-2 and
    SL-4 publish their interfaces, the same test drives a real handle through
    runner -> PhaseWorkerJob -> launch_with_spec -> launch -> LeaseSupervisor
    -> Popen, then asks real reclamation to preserve or acquire as appropriate.
    """

    import fcntl
    import json
    import signal

    from phase_loop_runtime import launcher

    helper_source = (
        "import os, subprocess, sys\n"
        "for raw in list(os.listdir('/proc/self/fd')):\n"
        "    try: fd = int(raw)\n"
        "    except ValueError: continue\n"
        "    if fd > 2:\n"
        "        try: os.close(fd)\n"
        "        except OSError: pass\n"
        "phase, marker_path = sys.argv[1], sys.argv[2]\n"
        "if phase != 'A':\n"
        "    raise SystemExit(0)\n"
        "from pathlib import Path\n"
        "Path('committed.txt').write_bytes(b'committed generation bytes\\n')\n"
        "subprocess.run(['git', 'add', 'committed.txt'], check=True)\n"
        "subprocess.run(['git', 'commit', '-qm', 'joined preserved generation'], check=True)\n"
        "Path('dirty.txt').write_bytes(b'dirty generation bytes\\x00')\n"
        "Path('scratch').mkdir(exist_ok=True)\n"
        "Path('scratch/untracked.bin').write_bytes(b'untracked generation bytes\\x00')\n"
        "Path('.dev-skills/handoffs').mkdir(parents=True, exist_ok=True)\n"
        "Path('.dev-skills/handoffs/resume.bin').write_bytes(b'ignored handoff bytes\\x00')\n"
        "with os.scandir('/proc/self/fd') as entries:\n"
        "    inherited = [int(entry.name) for entry in entries if entry.name.isdigit()]\n"
        "for fd in inherited:\n"
        "    if fd > 2:\n"
        "        try: os.close(fd)\n"
        "        except OSError: pass\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(45)'], "
        "close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "with open(marker_path, 'a', encoding='utf-8') as marker:\n"
        "    marker.write(__import__('json').dumps({'phase': phase, 'helper_pid': os.getpid(), "
        "'grandchild_pid': child.pid}) + '\\n'); marker.flush(); os.fsync(marker.fileno())\n"
        "import time; time.sleep(1)\n"
    )

    def write_roadmap(repo: Path) -> Path:
        roadmap = repo / "specs" / "phase-plans-v1.md"
        roadmap.write_text(
            "# Roadmap\n\n"
            "### Phase 1 - Alpha (A)\n**Depends on**\n- (none)\n\n"
            "### Phase 2 - Beta (B)\n**Depends on**\n- (none)\n",
            encoding="utf-8",
        )
        (repo / ".gitignore").write_text(".dev-skills/\n", encoding="utf-8")
        plan_a = write_phase_plan(repo, "A", roadmap, owned_files=("src/a.py",))
        plan_b = write_phase_plan(repo, "B", roadmap, owned_files=("src/b.py",))
        commit_fixture_paths(repo, "add joined fixture", roadmap, plan_a, plan_b, repo / ".gitignore")
        return roadmap

    def run_probe(case_root: Path, case_mutation: str, *, require_supervisor: bool) -> dict:
        repo = make_repo(case_root)
        roadmap = write_roadmap(repo)
        observation_path = case_root / "observations.jsonl"
        pid_path = case_root / "children.jsonl"
        helper_path = case_root / "helper.py"
        helper_path.write_text(helper_source, encoding="utf-8")
        coordinator_path = case_root / "coordinator.py"
        coordinator_path.write_text(
            textwrap.dedent(
                """
                import ctypes
                import fcntl
                import hashlib
                import json
                import os
                import re
                import signal
                import sys
                import threading
                import time
                from contextlib import ExitStack
                from pathlib import Path
                from unittest.mock import patch

                from phase_loop_runtime import launcher, runner, worker_pool
                from phase_loop_runtime.launcher import AuthPreflightResult

                repo = Path(sys.argv[1])
                roadmap = Path(sys.argv[2])
                observations = Path(sys.argv[3])
                pid_path = Path(sys.argv[4])
                helper_path = Path(sys.argv[5])
                mutation = sys.argv[6]
                require_supervisor = sys.argv[7] == "1"

                def emit(kind, **data):
                    with observations.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"kind": kind, **data}, sort_keys=True) + "\\n")
                        stream.flush(); os.fsync(stream.fileno())

                def fake_path(_repo, *, branch, lane_id, **_kwargs):
                    return observations.parent / "worktrees" / f"{branch}-{lane_id}"

                real_pool = worker_pool.run_phase_worker_pool
                real_lws = launcher.launch_with_spec
                real_launch = launcher.launch
                real_popen = launcher.subprocess.Popen
                supervisor_type = getattr(launcher, "LeaseSupervisor", None)
                active_handle = None
                active_lease_fd = None
                supervisor_constructor = None
                supervisor_patch = None

                def callable_digest(value):
                    try:
                        source = __import__("inspect").getsource(value).encode("utf-8")
                    except (OSError, TypeError):
                        source = repr(value).encode("utf-8")
                    return hashlib.sha256(source).hexdigest()

                popen_source_digest = callable_digest(real_popen)
                supervisor_source_digest = (
                    callable_digest(supervisor_type) if supervisor_type is not None else None
                )

                def observe_pool(pool_repo, pool_roadmap, jobs, **kwargs):
                    global active_handle, active_lease_fd
                    emit("PhaseWorkerJob", phases=[job.phase for job in jobs])
                    if require_supervisor:
                        target = next(job for job in jobs if job.phase == "A")
                        assert target.lease_authority is target.worktree_handle.lease_authority
                        active_handle = target.worktree_handle
                        active_lease_fd = active_handle.lease_authority.fileno()
                        emit(
                            "typed_lease_authority",
                            generation=active_handle.generation,
                            temp_branch=active_handle.temp_branch,
                            worktree_path=str(active_handle.worktree_path),
                            lease_path=os.readlink(f"/proc/self/fd/{active_lease_fd}"),
                        )
                    return real_pool(pool_repo, pool_roadmap, jobs, **kwargs)

                def observe_lws(spec, **kwargs):
                    emit("launch_with_spec", cwd=spec.wrapped_cwd)
                    return real_lws(spec, **kwargs)

                def observe_launch(*args, **kwargs):
                    emit("launch", cwd=str(kwargs.get("cwd") or ""))
                    return real_launch(*args, **kwargs)

                def observe_popen(*args, **kwargs):
                    command = args[0] if args else kwargs.get("args", ())
                    before_fds = tuple(kwargs.get("pass_fds", ()))
                    is_supervisor_spawn = require_supervisor and active_lease_fd in before_fds
                    before_session = kwargs.get("start_new_session")
                    if is_supervisor_spawn and mutation == "pass_fds":
                        kwargs["pass_fds"] = ()
                    if is_supervisor_spawn and mutation == "subreaper_session":
                        kwargs["start_new_session"] = False
                        previous_preexec = kwargs.get("preexec_fn")

                        def disable_child_subreaper():
                            if previous_preexec is not None:
                                previous_preexec()
                            libc = ctypes.CDLL(None, use_errno=True)
                            if libc.prctl(36, 0, 0, 0, 0) != 0:
                                raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER")

                        kwargs["preexec_fn"] = disable_child_subreaper
                    process = real_popen(*args, **kwargs)
                    if is_supervisor_spawn:
                        emit(
                            "supervisor_spawn_mutation",
                            source_anchor="phase_loop_runtime.launcher.subprocess.Popen",
                            mutation=mutation,
                            mutation_digest=hashlib.sha256(
                                (
                                    "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::"
                                    f"test_supervisor_retains_lease_after_executor_parent_exits[{mutation}]::"
                                    f"{popen_source_digest}"
                                ).encode()
                            ).hexdigest(),
                            source_digest=popen_source_digest,
                            before_pass_fds=list(before_fds),
                            after_pass_fds=list(kwargs.get("pass_fds", ())),
                            before_start_new_session=before_session,
                            after_start_new_session=kwargs.get("start_new_session"),
                            after_pr_set_child_subreaper=(
                                False if mutation == "subreaper_session" else None
                            ),
                            supervisor_pid=process.pid,
                        )
                    if isinstance(command, (tuple, list)) and str(helper_path) in command:
                        emit("helper_popen", source_anchor="LeaseSupervisor->subprocess.Popen", pid=process.pid)
                    return process

                def command(spec, _log_path, *, dry_run):
                    assert dry_run is False
                    match = re.search(r"phase-plan-v1-([A-Z]+)\\.md", spec.prompt_bundle.render_prompt())
                    assert match is not None
                    return [sys.executable, str(helper_path), match.group(1), str(pid_path)], ()

                def helper_parent(pid):
                    fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
                    return int(fields[3])

                def helper_exited(pid):
                    path = Path(f"/proc/{pid}/stat")
                    return not path.exists() or path.read_text(encoding="utf-8").split()[2] == "Z"

                def launch_reclaimer(handle, release_read_fd, release_write_fd):
                    child = os.fork()
                    if child:
                        return child
                    try:
                        os.close(release_write_fd)
                        os.read(release_read_fd, 1)
                        handle.lease_authority.close()
                        from phase_loop_runtime.phase_worktree_executor import reclaim_phase_worktree
                        result = reclaim_phase_worktree(repo, handle)
                        payload = {
                            "reclaimed": result.reclaimed,
                            "reason": result.reason,
                            "lease_acquired": result.lease_acquired,
                        }
                    except BaseException as exc:
                        payload = {"error": repr(exc)}
                    (observations.parent / "reclaim.json").write_text(json.dumps(payload), encoding="utf-8")
                    os._exit(0)

                def run_chain():
                    try:
                        runner.run_loop(repo, roadmap, phase_scheduler_mode="concurrent", max_phases=1)
                    except BaseException as exc:
                        emit("runner_error", error=repr(exc))

                patches = (
                    patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})),
                    patch("phase_loop_runtime.runner.run_phase_worker_pool", side_effect=observe_pool),
                    patch("phase_loop_runtime.worker_pool.launch_with_spec", side_effect=observe_lws),
                    patch("phase_loop_runtime.launcher.launch", side_effect=observe_launch),
                    patch("phase_loop_runtime.launcher.subprocess.Popen", side_effect=observe_popen),
                    patch("phase_loop_runtime.launcher._resolve_command_context", side_effect=command),
                    patch("phase_loop_runtime.phase_worktree_executor.lane_worktree_path", side_effect=fake_path),
                    patch("phase_loop_runtime.injection._resolve_pack_skill_dirs", return_value={}),
                )
                with ExitStack() as patch_stack:
                    for active_patch in patches:
                        patch_stack.enter_context(active_patch)
                    if require_supervisor:
                        assert supervisor_type is not None
                        supervisor_patch = patch.object(
                            launcher, "LeaseSupervisor", wraps=supervisor_type
                        )
                        supervisor_constructor = supervisor_patch.start()
                    thread = threading.Thread(target=run_chain, daemon=True)
                    thread.start()
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip():
                            break
                        time.sleep(0.05)
                    assert pid_path.exists(), "real launcher never reached helper grandchild"
                    marker = json.loads(pid_path.read_text(encoding="utf-8").splitlines()[0])
                    helper_pid = marker["helper_pid"]
                    grandchild_pid = marker["grandchild_pid"]
                    assert os.kill(grandchild_pid, 0) is None
                    if require_supervisor:
                        assert active_handle is not None and active_lease_fd is not None
                        assert supervisor_constructor.call_count > 0
                        supervisor_pid = helper_parent(helper_pid)
                        emit(
                            "actual_supervisor",
                            constructor_calls=supervisor_constructor.call_count,
                            pid=supervisor_pid,
                            helper_pid=helper_pid,
                            grandchild_pid=grandchild_pid,
                        )
                        if mutation == "process_tree_reaping":
                            while time.monotonic() < deadline and not helper_exited(helper_pid):
                                time.sleep(0.02)
                            assert helper_exited(helper_pid)
                            os.kill(supervisor_pid, signal.SIGKILL)
                            emit(
                                "supervisor_direct_child_only_mutation",
                                source_anchor="LeaseSupervisor process lifetime",
                                mutation_digest=hashlib.sha256(
                                    f"{supervisor_pid}:{helper_pid}:{grandchild_pid}".encode()
                                ).hexdigest(),
                                source_digest=supervisor_source_digest,
                                supervisor_pid=supervisor_pid,
                            )
                        read_fd, write_fd = os.pipe()
                        reclaimer_pid = launch_reclaimer(active_handle, read_fd, write_fd)
                        os.close(read_fd)
                    else:
                        reclaimer_pid = None
                    if supervisor_patch is not None:
                        supervisor_patch.stop()
                    patch_stack.close()
                    emit(
                        "source_restored",
                        source_anchor="phase_loop_runtime.launcher.subprocess.Popen",
                        source_digest=popen_source_digest,
                        restored_digest=callable_digest(launcher.subprocess.Popen),
                        restored_identity=launcher.subprocess.Popen is real_popen,
                    )
                    if supervisor_patch is not None:
                        emit(
                            "source_restored",
                            source_anchor="phase_loop_runtime.launcher.LeaseSupervisor",
                            source_digest=supervisor_source_digest,
                            restored_digest=callable_digest(launcher.LeaseSupervisor),
                            restored_identity=launcher.LeaseSupervisor is supervisor_type,
                        )
                    if require_supervisor:
                        emit("reclaimer_armed", pid=reclaimer_pid)
                    emit("coordinator_parent_exit")
                    os._exit(0)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(item for item in sys.path if item)
        coordinator = subprocess.Popen(
            [
                sys.executable,
                str(coordinator_path),
                str(repo),
                str(roadmap),
                str(observation_path),
                str(pid_path),
                str(helper_path),
                case_mutation,
                "1" if require_supervisor else "0",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert coordinator.wait(timeout=30) == 0, coordinator.stderr.read().decode("utf-8")
        events = [json.loads(line) for line in observation_path.read_text(encoding="utf-8").splitlines()]
        markers = [json.loads(line) for line in pid_path.read_text(encoding="utf-8").splitlines() if line]
        children = [marker["grandchild_pid"] for marker in markers]
        typed = next((event for event in events if event["kind"] == "typed_lease_authority"), None)
        post_parent_acquired = None
        if typed is not None:
            probe_fd = os.open(typed["lease_path"], os.O_RDWR)
            try:
                fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                post_parent_acquired = True
            except BlockingIOError:
                post_parent_acquired = False
            finally:
                if post_parent_acquired:
                    fcntl.flock(probe_fd, fcntl.LOCK_UN)
                os.close(probe_fd)
        reclaim_path = case_root / "reclaim.json"
        deadline = __import__("time").monotonic() + 20
        while typed is not None and not reclaim_path.exists() and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
        reclaim = json.loads(reclaim_path.read_text(encoding="utf-8")) if reclaim_path.exists() else None
        return {
            "repo": repo,
            "events": events,
            "children": children,
            "typed": typed,
            "post_parent_acquired": post_parent_acquired,
            "reclaim": reclaim,
        }

    def assert_preserved(probe: dict) -> None:
        typed = probe["typed"]
        assert typed is not None
        worktree = Path(typed["worktree_path"])
        assert subprocess.run(
            ["git", "-C", str(probe["repo"]), "show-ref", "--verify", f"refs/heads/{typed['temp_branch']}"],
            capture_output=True,
        ).returncode == 0
        assert (worktree / "committed.txt").read_bytes() == b"committed generation bytes\n"
        assert (worktree / "dirty.txt").read_bytes() == b"dirty generation bytes\x00"
        assert (worktree / "scratch/untracked.bin").read_bytes() == b"untracked generation bytes\x00"
        assert (worktree / ".dev-skills/handoffs/resume.bin").read_bytes() == b"ignored handoff bytes\x00"

    preproduction = run_probe(tmp_path / "preproduction", "preproduction", require_supervisor=False)
    try:
        preproduction_kinds = [event["kind"] for event in preproduction["events"]]
        assert preproduction_kinds.index("PhaseWorkerJob") < preproduction_kinds.index("launch_with_spec") < preproduction_kinds.index("launch") < preproduction_kinds.index("helper_popen") < preproduction_kinds.index("coordinator_parent_exit")
        restored = next(event for event in preproduction["events"] if event["kind"] == "source_restored")
        assert restored["restored_identity"] is True
        assert restored["source_digest"] == restored["restored_digest"]
        assert preproduction["children"] and all(os.kill(pid, 0) is None for pid in preproduction["children"])
    finally:
        for pid in preproduction["children"]:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    supervisor_type = getattr(launcher, "LeaseSupervisor", None)
    if supervisor_type is None:
        # The frozen pre-production base has no supervisor integration yet.  A
        # test-local reference supervisor lets every parameter exercise its own
        # mutation and emit evidence before the named missing-production seam
        # fails the activated contract.  It must never hide a real supervisor.
        import fcntl
        import hashlib
        import inspect
        import json
        import time

        frozen_nodeid = (
            "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::"
            "test_supervisor_retains_lease_after_executor_parent_exits"
        )
        reference_source = (
            "SCHED reference supervisor v4: runner-to-launch seam, pass_fds, "
            "session, PR_SET_CHILD_SUBREAPER, and complete descendant reaping"
        )
        reference_digest = hashlib.sha256(reference_source.encode("utf-8")).hexdigest()
        source_repo = Path(__file__).resolve().parents[2]
        preproduction_base = subprocess.check_output(
            ["git", "-C", str(source_repo), "rev-parse", "HEAD^"], text=True
        ).strip()

        def source_digest_at_base(path: str) -> str:
            return hashlib.sha256(
                subprocess.check_output(
                    ["git", "-C", str(source_repo), "show", f"{preproduction_base}:{path}"]
                )
            ).hexdigest()

        preproduction_source_digests = {
            "launcher.py": source_digest_at_base("phase-loop-runtime/src/phase_loop_runtime/launcher.py"),
            "phase_worktree_executor.py": source_digest_at_base(
                "phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py"
            ),
        }
        launch_digest = hashlib.sha256(inspect.getsource(launcher.launch).encode("utf-8")).hexdigest()
        popen_digest = hashlib.sha256(inspect.getsource(launcher.subprocess.Popen).encode("utf-8")).hexdigest()

        def reference_mutation(case: str) -> dict:
            case_root = tmp_path / f"reference-{case}"
            case_root.mkdir(exist_ok=True)
            lock_path = case_root / "lease.lock"
            marker_path = case_root / "marker.json"
            child_marker_path = case_root / "child.json"
            lease_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            helper = (
                "import ctypes, json, os, subprocess, sys, time\n"
                "lease_fd, marker, child_marker, session, enable_subreaper, reap_tree = (int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]))\n"
                "import ctypes\n"
                "libc = ctypes.CDLL(None, use_errno=True)\n"
                "if libc.prctl(36, enable_subreaper, 0, 0, 0) != 0: raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER')\n"
                "subreaper = ctypes.c_int()\n"
                "if libc.prctl(37, ctypes.byref(subreaper), 0, 0, 0) != 0: raise OSError(ctypes.get_errno(), 'PR_GET_CHILD_SUBREAPER')\n"
                "inherited = True\n"
                "try: os.fstat(lease_fd)\n"
                "except OSError: inherited = False\n"
                "executor = subprocess.Popen([sys.executable, '-c', \"import json, os, subprocess, sys; lease_fd = int(sys.argv[2]); inherited = os.path.exists('/proc/self/fd/%s' % lease_fd); child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=((lease_fd,) if inherited else ())); json.dump({'grandchild_pid': child.pid}, open(sys.argv[1], 'w'))\", child_marker, str(lease_fd)], "
                "close_fds=True, pass_fds=((lease_fd,) if inherited else ()), "
                "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                "deadline = time.monotonic() + 5\n"
                "while not os.path.exists(child_marker):\n"
                "    if time.monotonic() >= deadline: raise RuntimeError('reference executor did not report grandchild')\n"
                "    time.sleep(0.01)\n"
                "grandchild_pid = json.load(open(child_marker))['grandchild_pid']\n"
                "json.dump({'executor_pid': executor.pid, 'grandchild_pid': grandchild_pid, 'inherited': inherited, 'session_isolated': os.getsid(0) != session, 'subreaper_enabled': bool(subreaper.value)}, open(marker, 'w'))\n"
                "if inherited: os.close(lease_fd)\n"
                "executor.wait()\n"
                "if reap_tree:\n"
                "    while True:\n"
                "        try: pid, _status = os.waitpid(-1, 0)\n"
                "        except ChildProcessError: break\n"
            )
            pass_fds = () if case == "pass_fds" else (lease_fd,)
            supervisor = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    helper,
                    str(lease_fd),
                    str(marker_path),
                    str(child_marker_path),
                    str(os.getsid(0)),
                    str(int(case != "subreaper_session")),
                    str(int(case != "process_tree_reaping")),
                ],
                close_fds=True,
                pass_fds=pass_fds,
                start_new_session=case != "subreaper_session",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # The coordinator relinquishes its copy: any remaining exclusion
            # must belong solely to the reference supervisor's descendant tree.
            os.close(lease_fd)
            lease_fd = -1
            deadline = time.monotonic() + 5
            while not marker_path.exists():
                assert time.monotonic() < deadline, "reference supervisor did not report custody"
                time.sleep(0.01)
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            grandchild_pid = marker["grandchild_pid"]
            contender = os.open(lock_path, os.O_RDWR)
            try:
                try:
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    contender_acquired = True
                except BlockingIOError:
                    contender_acquired = False
                finally:
                    if contender_acquired:
                        fcntl.flock(contender, fcntl.LOCK_UN)
            finally:
                os.close(contender)
                grandchild_live = os.kill(grandchild_pid, 0) is None
                supervisor.wait(timeout=10)
                grandchild_reaped = False
                try:
                    os.kill(grandchild_pid, 0)
                except ProcessLookupError:
                    grandchild_reaped = True
                if case == "safe":
                    deadline = time.monotonic() + 5
                    while not grandchild_reaped and time.monotonic() < deadline:
                        try:
                            os.kill(grandchild_pid, 0)
                        except ProcessLookupError:
                            grandchild_reaped = True
                            break
                        time.sleep(0.02)
                    assert grandchild_reaped, "reference supervisor did not reap grandchild"
                elif not grandchild_reaped:
                    try:
                        os.kill(grandchild_pid, 0)
                    except ProcessLookupError:
                        grandchild_reaped = True
            expected_anchor = {
                "pass_fds": "live grandchild loses inherited lease",
                "subreaper_session": "supervisor disables both session isolation and PR_SET_CHILD_SUBREAPER",
                "process_tree_reaping": "direct-child-only reaping leaves a live grandchild",
                "safe": "unmodified reference supervisor retains lease and isolates its session",
            }[case]
            unsafe = (
                contender_acquired if case == "pass_fds"
                else (not marker["session_isolated"] and not marker["subreaper_enabled"])
                if case == "subreaper_session"
                else supervisor.returncode == 0 and grandchild_live
                if case == "process_tree_reaping"
                else False
            )
            evidence = {
                "schema_version": "verification_evidence.v3",
                "nodeid": f"{frozen_nodeid}[{case}]",
                "preproduction_base": preproduction_base,
                "preproduction_source_digests": preproduction_source_digests,
                "reference_supervisor_digest": reference_digest,
                "reference_fixture_used": True,
                "injection_anchor": "test_local.ReferenceLeaseSupervisor",
                "injection_digest": hashlib.sha256(
                    f"{frozen_nodeid}[{case}]::{reference_digest}".encode("utf-8")
                ).hexdigest(),
                "expected_failure_anchor": expected_anchor,
                "observed": {
                    "unsafe": unsafe,
                    "contender_acquired": contender_acquired,
                    "direct_child_exited": supervisor.returncode == 0,
                    "grandchild_live": grandchild_live,
                    "grandchild_reaped": grandchild_reaped,
                    "session_isolated": marker["session_isolated"],
                    "subreaper_enabled": marker["subreaper_enabled"],
                },
                "positive_control": (
                    not contender_acquired
                    and grandchild_live
                    and marker["session_isolated"]
                    and marker["subreaper_enabled"]
                    and grandchild_reaped
                ),
                "restored_source_digests": {"launcher.launch": launch_digest, "launcher.Popen": popen_digest},
            }
            if not grandchild_reaped:
                try:
                    os.kill(grandchild_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if lease_fd >= 0:
                fcntl.flock(lease_fd, fcntl.LOCK_UN)
                os.close(lease_fd)
            return evidence

        positive = reference_mutation("safe")
        assert positive["positive_control"] is True
        assert positive["observed"]["grandchild_reaped"] is True
        record = reference_mutation(mutation)
        record["positive_control"] = positive["positive_control"]
        assert record["schema_version"] == "verification_evidence.v3"
        assert record["nodeid"].endswith(f"[{mutation}]")
        assert record["preproduction_base"] == preproduction_base
        assert record["preproduction_source_digests"] == preproduction_source_digests
        assert record["observed"]["unsafe"] is True
        assert record["positive_control"] is True
        if mutation == "subreaper_session":
            assert record["observed"]["session_isolated"] is False
            assert record["observed"]["subreaper_enabled"] is False
        if mutation == "process_tree_reaping":
            assert record["observed"]["direct_child_exited"] is True
            assert record["observed"]["grandchild_live"] is True
            assert record["observed"]["grandchild_reaped"] is False
        print(json.dumps(record, sort_keys=True))
        pytest.fail(f"{mutation}: pre-production seam executed; LeaseSupervisor is missing")

    safe = run_probe(tmp_path / "safe", "safe", require_supervisor=True)
    mutated = run_probe(tmp_path / mutation, mutation, require_supervisor=True)
    try:
        for probe in (safe, mutated):
            kinds = [event["kind"] for event in probe["events"]]
            assert kinds.index("PhaseWorkerJob") < kinds.index("launch_with_spec") < kinds.index("launch") < kinds.index("actual_supervisor") < kinds.index("coordinator_parent_exit")
            assert probe["children"] and all(os.kill(pid, 0) is None for pid in probe["children"])
            assert_preserved(probe)
            assert probe["reclaim"] is not None and "error" not in probe["reclaim"]
            restorations = [event for event in probe["events"] if event["kind"] == "source_restored"]
            assert restorations and all(event["restored_identity"] is True for event in restorations)
            assert all(event["source_digest"] == event["restored_digest"] for event in restorations)

        safe_spawn = next(event for event in safe["events"] if event["kind"] == "supervisor_spawn_mutation")
        assert safe_spawn["before_pass_fds"]
        assert safe_spawn["after_start_new_session"] is True
        assert safe["post_parent_acquired"] is False
        assert safe["reclaim"]["lease_acquired"] is False
        assert safe["reclaim"]["reclaimed"] is False

        restored = {
            event["source_anchor"]: event
            for event in mutated["events"]
            if event["kind"] == "source_restored"
        }
        if mutation == "pass_fds":
            evidence = next(event for event in mutated["events"] if event["kind"] == "supervisor_spawn_mutation")
            assert evidence["before_pass_fds"] and not evidence["after_pass_fds"]
            assert evidence["source_digest"] == restored["phase_loop_runtime.launcher.subprocess.Popen"]["source_digest"]
        elif mutation == "subreaper_session":
            evidence = next(event for event in mutated["events"] if event["kind"] == "supervisor_spawn_mutation")
            assert evidence["before_start_new_session"] is True
            assert evidence["after_start_new_session"] is False
            assert evidence["after_pr_set_child_subreaper"] is False
            assert evidence["source_digest"] == restored["phase_loop_runtime.launcher.subprocess.Popen"]["source_digest"]
        else:
            evidence = next(
                event for event in mutated["events"] if event["kind"] == "supervisor_direct_child_only_mutation"
            )
            assert evidence["source_anchor"] == "LeaseSupervisor process lifetime"
            assert evidence["source_digest"] == restored["phase_loop_runtime.launcher.LeaseSupervisor"]["source_digest"]

        if mutation == "subreaper_session":
            # A conformant supervisor still owns the lease and reaps the tree
            # after this mutation; unsafe session/subreaper state does not
            # require a fabricated lease-loss observation.
            assert mutated["post_parent_acquired"] is False
            assert mutated["reclaim"]["lease_acquired"] is False
        else:
            assert mutated["post_parent_acquired"] is True
            assert mutated["reclaim"]["lease_acquired"] is True
        assert mutated["reclaim"]["reclaimed"] is False

        verification_evidence = {
            "schema_version": "verification_evidence.v3",
            "nodeid": (
                "phase-loop-runtime/tests/test_phase_loop_v45_schedharden.py::"
                f"test_supervisor_retains_lease_after_executor_parent_exits[{mutation}]"
            ),
            "reference_fixture_used": False,
            "injection_anchor": "phase_loop_runtime.launcher.LeaseSupervisor",
            "injection_digest": evidence["mutation_digest"],
            "expected_failure_anchor": {
                "pass_fds": "live grandchild loses inherited lease",
                "subreaper_session": "supervisor disables both session isolation and PR_SET_CHILD_SUBREAPER",
                "process_tree_reaping": "direct-child-only reaping leaves a live grandchild",
            }[mutation],
            "positive_control": safe["post_parent_acquired"] is False,
            "observed": {
                "grandchild_live": bool(mutated["children"]),
                "lease_held": mutated["post_parent_acquired"] is False,
            },
        }
        assert verification_evidence["reference_fixture_used"] is False
        assert verification_evidence["nodeid"].endswith(f"[{mutation}]")
        print(json.dumps(verification_evidence, sort_keys=True))
    finally:
        for probe in (safe, mutated):
            for pid in probe["children"]:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
