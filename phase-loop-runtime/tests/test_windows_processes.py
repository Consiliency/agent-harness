"""Native Windows process witnesses. Run explicitly on Windows, never as WSL proof."""
from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from phase_loop_runtime import windows_process as windows


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows Job Object proof")


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def command(code, *args):
    return [sys.executable, "-I", "-S", "-c", code, *map(str, args)]


def test_normal_execution_unicode_stdin_and_output(tmp_path):
    directory = tmp_path / "space and é"
    directory.mkdir()
    result = windows.run_owned(command("import sys; print(sys.stdin.read())"),
                               stdin_text="hello", cwd=directory)
    assert result.returncode == 0
    assert result.output.strip() == "hello"
    assert result.quiescent and not result.timed_out


def test_normal_exit_kills_detached_descendant_and_retained_pipe(tmp_path):
    witness = tmp_path / "child.json"
    code = """
import json, subprocess, sys
from pathlib import Path
child = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'import time; time.sleep(60)'], creationflags=0x8)
Path(sys.argv[1]).write_text(json.dumps(child.pid))
print('parent done', flush=True)
"""
    unrelated = subprocess.Popen(command("import time; time.sleep(60)"))
    try:
        result = windows.run_owned(command(code, witness), timeout_seconds=8)
        assert result.returncode == 0 and result.quiescent
        assert result.output.strip() == "parent done"
        assert not windows.process_is_live(json.loads(witness.read_text()))
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=10)


@pytest.mark.parametrize("cancelled", [False, True])
def test_timeout_and_cancel_kill_descendants(tmp_path, cancelled):
    witness = tmp_path / "child.json"
    code = """
import json, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'import time; time.sleep(60)'])
Path(sys.argv[1]).write_text(json.dumps(child.pid))
time.sleep(60)
"""
    cancel = threading.Event()
    timer = threading.Timer(1, cancel.set)
    if cancelled:
        timer.start()
    result = windows.run_owned(command(code, witness), timeout_seconds=3, cancel=cancel)
    timer.cancel()
    assert result.quiescent
    assert result.timed_out is (not cancelled)
    assert not windows.process_is_live(json.loads(witness.read_text()))


def test_assignment_failure_never_admits_executor(tmp_path, monkeypatch):
    witness = tmp_path / "must-not-exist"
    def denied(self, process):
        raise PermissionError("controlled assignment denial")
    monkeypatch.setattr(windows.Job, "assign", denied)
    with pytest.raises(PermissionError):
        windows.run_owned(command("from pathlib import Path; import sys; Path(sys.argv[1]).touch()", witness))
    assert not witness.exists()


def test_owner_death_closes_job_and_kills_tree(tmp_path):
    witness = tmp_path / "child.json"
    executor = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    owner_code = """
import sys
from phase_loop_runtime.windows_process import run_owned
run_owned([sys.executable, '-I', '-S', '-c', sys.argv[1], sys.argv[2]], timeout_seconds=90)
"""
    owner = subprocess.Popen([sys.executable, "-c", owner_code, executor, str(witness)])
    try:
        wait_for(witness.exists)
        child_pid = int(witness.read_text())
        assert windows.process_is_live(child_pid)
        owner.kill()
        owner.wait(timeout=10)
        wait_for(lambda: not windows.process_is_live(child_pid))
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=10)


def test_bounded_output_and_blocked_stdin():
    result = windows.run_owned(command("import sys,time; sys.stdout.write('x'*200000); sys.stdout.flush(); time.sleep(60)"), max_bytes=4096)
    assert result.output_limited and result.quiescent
    assert len(result.output.encode()) == 4096
    result = windows.run_owned(command("import time; time.sleep(60)"), stdin_text="x" * 200000, timeout_seconds=3)
    assert result.timed_out and result.quiescent


def test_invalid_entry_point_and_large_input_do_not_run(tmp_path):
    script = tmp_path / "bad.cmd"
    script.write_text("exit 0")
    with pytest.raises(ValueError, match=".exe"):
        windows.run_owned([str(script)])
    with pytest.raises(ValueError, match="byte limit"):
        windows.run_owned(command("print('no')"), stdin_text="x" * 2000, max_bytes=1000)


def test_liveness_probe_preserves_process_and_cpu_unknown(monkeypatch):
    from phase_loop_runtime import observability
    child = subprocess.Popen(command("import time; time.sleep(60)"))
    try:
        monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("os.kill is unsafe for native Windows liveness"))
        assert observability._pid_is_live(child.pid)
        assert child.poll() is None
        assert observability._process_cpu_percent(child.pid) is None
        assert observability._process_group_cpu_percent(child.pid) is None
        child.terminate()
        child.wait(timeout=10)
        assert not observability._pid_is_live(child.pid)
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)


def test_unqualified_production_launch_fails_closed(tmp_path):
    from phase_loop_runtime.launcher import launch
    result = launch(command("raise SystemExit('must not execute')"), lease_authority=object())
    assert result.available is False and result.returncode == 1
    assert result.live_proof_gate == "disposable_proof_required"
    assert result.timeout_posture == "runner_managed"
    assert result.unavailable_reason == "native_windows_supervision_unavailable"


@pytest.mark.parametrize("leased", [False, True])
def test_production_launcher_streams_stdin_and_reuses_completed_lease(tmp_path, leased):
    from phase_loop_runtime.launcher import launch
    from phase_loop_runtime.file_lock import open_generation_lease
    from phase_loop_runtime.phase_worktree_executor import LeaseAuthority
    lease = None
    if leased:
        path = tmp_path / "generation.lock"
        fd = open_generation_lease(path)
        value = os.fstat(fd)
        lease = LeaseAuthority(path, fd, f'generation:{value.st_dev}:{value.st_ino}', 'generation')
    try:
        for index in range(2):
            log = tmp_path / f"output{index}.log"
            result = launch(command("import sys,time; print(sys.stdin.read(),flush=True); time.sleep(.1)"),
                            stdin_text="received", log_path=log, lease_authority=lease,
                            heartbeat_interval_seconds=0)
            assert result.available and result.returncode == 0, result
            assert result.output.strip() == "received"
            assert log.read_text(encoding="utf-8").strip() == "received"
            assert result.cleanup_evidence["job_active_processes"] == 0
            assert Path(result.heartbeat_path).exists()
            if leased:
                assert result.supervisor_receipt["receipt_binding"] == lease.identity
    finally:
        if lease:
            lease.close()


def test_output_callback_failure_cannot_report_success():
    def fail(chunk):
        raise OSError("controlled sink failure")
    result = windows.run_owned(command("print('result',flush=True)"), on_output=fail)
    assert result.returncode != 0
    assert result.quiescent


@pytest.mark.parametrize("stalled", [False, True])
def test_leased_launcher_timeout_and_stall_confirm_cleanup(tmp_path, monkeypatch, stalled):
    from phase_loop_runtime.launcher import launch
    from phase_loop_runtime import observability
    from phase_loop_runtime.file_lock import open_generation_lease
    from phase_loop_runtime.phase_worktree_executor import LeaseAuthority
    path = tmp_path / "generation.lock"
    fd = open_generation_lease(path)
    value = os.fstat(fd)
    lease = LeaseAuthority(path, fd, f'generation:{value.st_dev}:{value.st_ino}', 'generation')
    if stalled:
        monkeypatch.setattr(observability, "_process_cpu_percent", lambda _: 0.0)
    try:
        result = launch(command("import time; time.sleep(60)"), lease_authority=lease,
                        log_path=tmp_path / "output.log", heartbeat_interval_seconds=0,
                        quiet_warning_seconds=0 if stalled else 600,
                        quiet_blocker_seconds=0 if stalled else 1800,
                        timeout_seconds=5)
        assert result.available, result
        assert result.stalled is stalled
        assert result.timed_out is (not stalled)
        assert result.cleanup_evidence["job_active_processes"] == 0
        assert result.cleanup_evidence["salvage_snapshot"]["reason"] == ("stalled" if stalled else "timeout")
    finally:
        lease.close()


def test_leased_storage_contention_obeys_launch_deadline_before_executor(tmp_path):
    from phase_loop_runtime.launcher import launch
    from phase_loop_runtime.windows_storage import BoundDirectory
    from phase_loop_runtime.file_lock import open_generation_lease
    from phase_loop_runtime.phase_worktree_executor import LeaseAuthority
    path = tmp_path / "generation.lock"
    fd = open_generation_lease(path)
    value = os.fstat(fd)
    lease = LeaseAuthority(path, fd, f'generation:{value.st_dev}:{value.st_ino}', 'generation')
    witness = tmp_path / "must-not-run"
    try:
        with BoundDirectory(path.with_name(path.name + ".supervision"), create_private=True):
            started = time.monotonic()
            result = launch(command("from pathlib import Path; import sys; Path(sys.argv[1]).touch()", witness),
                            lease_authority=lease, timeout_seconds=.2)
            elapsed = time.monotonic() - started
        assert not result.available
        assert .15 <= elapsed < 1.5
        assert not witness.exists()
    finally:
        lease.close()


def test_nested_job_ownership():
    # The stage is assigned to an outer job before it launches this inner owner.
    # Windows 8+ supports nested jobs; no breakaway option is enabled.
    code = """
import sys
from phase_loop_runtime.windows_process import run_owned
result = run_owned([sys.executable, '-I', '-S', '-c', 'print(42)'])
assert result.quiescent and result.returncode == 0, result
print(result.output.strip())
"""
    result = windows.run_owned([sys.executable, "-c", code])
    assert result.returncode == 0 and result.quiescent
    assert result.output.strip() == "42"


@pytest.mark.parametrize("kill_guardian", [False, True])
def test_guardian_holds_lease_and_preserves_uncertain_generation(tmp_path, kill_guardian):
    from test_windows_locking import contender
    lease = tmp_path / "generation.lock"
    witness = tmp_path / "executor.pid"
    guardian_witness = tmp_path / "guardian.pid"
    owner_code = """
import os, sys, time
from pathlib import Path
from phase_loop_runtime.file_lock import open_generation_lease
from phase_loop_runtime.phase_worktree_executor import LeaseAuthority
from phase_loop_runtime.windows_process import start_leased_guardian
path = Path(sys.argv[1])
fd = open_generation_lease(path)
value = os.fstat(fd)
authority = LeaseAuthority(path, fd, f'generation:{value.st_dev}:{value.st_ino}', 'generation')
executor = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
guardian = start_leased_guardian([sys.executable, '-I', '-S', '-c', executor, sys.argv[2]], authority, timeout_seconds=15)
Path(sys.argv[3]).write_text(str(guardian.pid))
authority.close()
time.sleep(60)
"""
    owner = subprocess.Popen([sys.executable, "-c", owner_code, str(lease), str(witness), str(guardian_witness)])
    guardian_pid = None
    try:
        wait_for(witness.exists)
        guardian_pid = int(guardian_witness.read_text())
        child_pid = int(witness.read_text())
        assert contender(lease, "lease").returncode == 23
        if kill_guardian:
            kernel = windows._kernel()
            kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            kernel.TerminateProcess.restype = ctypes.c_int
            handle = kernel.OpenProcess(1, False, guardian_pid)
            assert handle
            try:
                assert kernel.TerminateProcess(handle, 1)
            finally:
                kernel.CloseHandle(handle)
        else:
            owner.kill()
            owner.wait(timeout=10)
        wait_for(lambda: not windows.process_is_live(child_pid))
        wait_for(lambda: not windows.process_is_live(guardian_pid))
        assert contender(lease, "lease").returncode == 0
        marker = lease.with_name(lease.name + ".supervision")
        assert (marker / "pending.json").exists()
        assert (marker / "complete.json").exists() is (not kill_guardian)
        if not kill_guardian:
            pending = json.loads((marker / "pending.json").read_text())
            complete = json.loads((marker / "complete.json").read_text())
            assert complete == {**pending, "quiescent": True}
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=10)
