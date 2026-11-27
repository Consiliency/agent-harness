"""Provider cleanup waits for kernel-confirmed completion of its contained tree
(agent-harness#1994).

Fake-host tests run everywhere. The real-kernel (``K*``) and real-bwrap (``B1``/``B3``)
tests probe their prerequisites read-only first and skip with an explicit
``kernel_prereq:`` reason; ``AH_REQUIRE_KERNEL_TESTS=1`` turns those skips into failures.
"""

from __future__ import annotations

import contextlib
import errno
import gc
import importlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import sys
import textwrap
import threading
import time
import uuid

import pytest

from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime import seat_jail
from phase_loop_runtime import seat_resource_caps as caps

# Shared fake caps host (cgroupfs tree, systemd-run and systemctl).
import test_seat_resource_caps as _caps_tests

_install_fake_cap_host = _caps_tests._install_fake_cap_host
isolated = _caps_tests.isolated  # the shared fixture, collected from this module

try:  # The red-first baseline runs this file against a tree without the module.
    tp = importlib.import_module("phase_loop_runtime.provider_tree_proof")
except ImportError:  # pragma: no cover - only on the pre-change baseline
    tp = None


TERM_S, KILL_S = 0.2, 1.0


class _Proxy:
    """A module stand-in that overrides a few attributes for one module under test."""

    def __init__(self, module, **overrides):
        self._module = module
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(self._module, name)


def _patch(monkeypatch, owner, module_name, **overrides):
    """Override ``owner.<module_name>.<attr>`` for ``owner`` only."""
    current = getattr(owner, module_name)
    base = current._module if isinstance(current, _Proxy) else current
    merged = dict(current.__dict__) if isinstance(current, _Proxy) else {}
    merged.pop("_module", None)
    merged.update(overrides)
    monkeypatch.setattr(owner, module_name, _Proxy(base, **merged))


@pytest.fixture
def short_graces(monkeypatch):
    monkeypatch.setattr(panel, "_PROCESS_GROUP_TERM_GRACE_S", TERM_S)
    monkeypatch.setattr(panel, "_PROCESS_GROUP_KILL_GRACE_S", KILL_S)


def _proof(process):
    return None if tp is None else tp.proof_of(process)


def _fd_count() -> int:
    gc.collect()
    return len(os.listdir("/proc/self/fd"))


def _wait_for(predicate, timeout=10.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _group_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _flip(path: Path) -> None:
    """``populated 1`` -> ``populated 0`` in place, one byte, so a concurrent reader of
    the fake file never sees a truncated body (cgroupfs reads are atomic)."""
    fd = os.open(path, os.O_WRONLY)
    try:
        os.pwrite(fd, b"0", len("populated "))
    finally:
        os.close(fd)


def _scope_events(proc_cgroup: Path, root: Path, pid: int) -> Path:
    line = Path(f"{proc_cgroup}.{pid}").read_text().strip()
    return root / line.split("::", 1)[1].lstrip("/") / "cgroup.events"


def _capped(tmp_path, monkeypatch, isolated, *, script="pass", seat="tree:test",
            runner_body=None):
    root, proc_cgroup, _configured, stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated, runner_body=runner_body)
    return root, proc_cgroup, stopped


def _start_capped(script, seat):
    return caps.capped_popen(
        [sys.executable, "-c", script], seat_key=seat, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# --------------------------------------------------------------------------------------
# T1/T2: the cleanup and latch predicates consult the launch's witness (red on main).
# --------------------------------------------------------------------------------------

@pytest.mark.real_seat_caps
def test_terminate_waits_for_the_launch_scope_to_be_unpopulated(
        monkeypatch, tmp_path, isolated, short_graces):
    root, proc_cgroup, _stopped = _capped(tmp_path, monkeypatch, isolated)
    process = _start_capped("pass", "tree:t1")
    proof_api = getattr(caps, "_witness_scope", None) is not None
    proof = _proof(process)
    if proof_api:
        assert proof is not None and proof.kind == "cgroup"
    else:
        assert proof is None
    assert process.wait(timeout=10) == 0
    assert _wait_for(lambda: _group_gone(process.pid))
    events = _scope_events(proc_cgroup, root, process.pid)
    assert events.read_text().startswith("populated 1")
    with pytest.raises(panel.ProviderProcessGroupQuiescenceError):
        panel._terminate_process_group(process)
    _flip(events)
    panel._terminate_process_group(process)


@pytest.mark.real_seat_caps
def test_latch_release_waits_for_the_launch_scope_to_be_unpopulated(
        monkeypatch, tmp_path, isolated):
    root, proc_cgroup, _stopped = _capped(tmp_path, monkeypatch, isolated)
    latch = panel._ProviderQuiescenceLatch()
    process = latch.launch(lambda: _start_capped("pass", "tree:t2"))
    assert process.wait(timeout=10) == 0
    assert _wait_for(lambda: _group_gone(process.pid))
    events = _scope_events(proc_cgroup, root, process.pid)
    with pytest.raises(panel.ProviderProcessGroupQuiescenceError,
                       match="deregistration preceded quiescence"):
        latch.release(process)
    assert not latch.is_quiescent()
    _flip(events)
    latch.release(process)
    assert latch.is_quiescent()


# --------------------------------------------------------------------------------------
# T3/T4: witness, gate and reaper order in capped_popen.
# --------------------------------------------------------------------------------------

@pytest.mark.real_seat_caps
def test_the_target_never_runs_before_the_gate_opens(monkeypatch, tmp_path, isolated):
    _capped(tmp_path, monkeypatch, isolated)
    marker = tmp_path / "target-ran"
    launcher = {}
    attached = []
    held, release = threading.Event(), threading.Event()
    real_write, real_attach = os.write, tp.attach

    def write(fd, data):
        if threading.current_thread() is launcher.get("thread") and data == b"1":
            held.set()
            assert release.wait(30)
        return real_write(fd, data)

    def attach(proc, proof):
        attached.append(proc)
        return real_attach(proc, proof)

    _patch(monkeypatch, caps, "os", write=write)
    monkeypatch.setattr(tp, "attach", attach)
    result = {}

    def run():
        try:
            result["process"] = _start_capped(
                f"from pathlib import Path; Path({str(marker)!r}).touch()", "tree:t3a")
        except BaseException as exc:  # surfaced below
            result["error"] = exc

    thread = threading.Thread(target=run)
    launcher["thread"] = thread
    thread.start()
    try:
        assert held.wait(15), result.get("error")
        assert len(attached) == 1
        (process,) = attached
        assert _proof(process) is not None
        time.sleep(0.5)
        assert process.poll() is None
        assert not marker.exists()
    finally:
        release.set()
        thread.join(15)
    assert "error" not in result, result.get("error")
    assert _wait_for(marker.exists)
    assert result["process"].wait(timeout=10) == 0


@pytest.mark.real_seat_caps
def test_witness_precedes_the_gate_and_the_reaper_and_survives_fast_exit(
        monkeypatch, tmp_path, isolated):
    root, proc_cgroup, _stopped = _capped(tmp_path, monkeypatch, isolated)
    order = []
    launcher = threading.current_thread()
    real_write, real_witness = os.write, caps._witness_scope

    def write(fd, data):
        if threading.current_thread() is launcher and data == b"1":
            order.append("gate")
        return real_write(fd, data)

    def witness(*args):
        order.append("witness")
        return real_witness(*args)

    class Thread(threading.Thread):
        def start(self):
            if self.name.startswith("seat-caps-"):
                order.append("reaper")
            return super().start()

    _patch(monkeypatch, caps, "os", write=write)
    monkeypatch.setattr(caps, "_witness_scope", witness)
    _patch(monkeypatch, caps, "threading", Thread=Thread)
    process = _start_capped("pass", "tree:t3b")
    assert order == ["witness", "gate", "reaper"]
    assert process.wait(timeout=10) == 0
    assert _wait_for(lambda: not caps._PARENTS)
    proof = _proof(process)
    assert proof is not None and proof.status == tp.INCOMPLETE
    assert proof.observe() is False and proof.status == tp.INCOMPLETE
    _flip(_scope_events(proc_cgroup, root, process.pid))
    assert proof.observe() is True


def _runner(root: Path, proc_cgroup: Path, *, scope=True, events="populated 1\\n",
            stub_helper=False) -> str:
    """A fake systemd-run that can omit the scope, write other events, or replace the
    helper with one that attests and then ignores its gate."""
    if stub_helper:
        tail = """\
            attest = int(sys.argv[sys.argv.index('--attest-fd') + 1])
            os.write(attest, b'1')
            os.close(attest)
            import time
            time.sleep(60)
        """
    else:
        tail = """\
            marker = sys.argv.index('--')
            os.execv(sys.argv[marker + 1], sys.argv[marker + 1:])
        """
    make_scope = f"""\
            scope.mkdir(parents=True, exist_ok=True)
            (scope / 'cgroup.events').write_text({events!r})
            (scope / 'cgroup.kill').touch()
    """ if scope else ""
    return textwrap.dedent(f"""\
        #!/usr/bin/python3
        import os, pathlib, sys
        unit = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--unit='))
        parent = next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--slice='))
        parts = parent.removesuffix('.slice').split('-')
        parent_path = pathlib.Path('user.slice', 'user-{os.getuid()}.slice',
                                   'user@{os.getuid()}.service')
        for index in range(1, len(parts) + 1):
            parent_path /= '-'.join(parts[:index]) + '.slice'
        line = '0::/' + str(parent_path / unit) + '\\n'
        pathlib.Path({str(proc_cgroup)!r}).write_text(line)
        pathlib.Path({str(proc_cgroup)!r} + '.' + str(os.getpid())).write_text(line)
        scope = pathlib.Path({str(root)!r}, parent_path, unit)
    """) + textwrap.dedent(make_scope) + textwrap.dedent(tail)


@pytest.mark.real_seat_caps
@pytest.mark.parametrize("case", ["no_scope", "mismatch", "changed", "unpopulated"])
def test_witness_failure_refuses_before_the_target_runs(
        monkeypatch, tmp_path, isolated, case):
    root = tmp_path / "cgroup"
    proc_cgroup = tmp_path / "proc-cgroup"
    body = _runner(root, proc_cgroup, scope=case != "no_scope",
                   events="populated 0\\n" if case == "unpopulated" else "populated 1\\n")
    _r, _p, _configured, stopped = _install_fake_cap_host(
        monkeypatch, tmp_path, isolated, runner_body=body)
    real_proc_cgroup_of = caps._proc_cgroup_of
    calls = []

    def proc_cgroup_of(pid):
        calls.append(pid)
        value = real_proc_cgroup_of(pid)
        if case == "mismatch" or (case == "changed" and len(calls) > 1):
            return value + "-elsewhere"
        return value

    monkeypatch.setattr(caps, "_proc_cgroup_of", proc_cgroup_of)
    processes = []
    real_popen = subprocess.Popen

    def record(*args, **kwargs):
        processes.append(real_popen(*args, **kwargs))
        return processes[-1]

    _patch(monkeypatch, caps, "subprocess", Popen=record)
    marker = tmp_path / "target-ran"
    baseline = _fd_count()
    with pytest.raises(seat_jail.SeatSandboxRefused) as refused:
        _start_capped(f"from pathlib import Path; Path({str(marker)!r}).touch()",
                      f"tree:t4-{case}")
    assert refused.value.code == caps.CODE
    (process,) = processes
    assert process.returncode == 125
    assert not caps._PARENTS and stopped
    time.sleep(0.3)
    assert not marker.exists()
    processes.clear()
    del process
    assert _fd_count() == baseline


@pytest.mark.real_seat_caps
def test_witness_failure_escalates_a_helper_that_ignores_its_gate(
        monkeypatch, tmp_path, isolated):
    root = tmp_path / "cgroup"
    proc_cgroup = tmp_path / "proc-cgroup"
    _install_fake_cap_host(monkeypatch, tmp_path, isolated,
                           runner_body=_runner(root, proc_cgroup, stub_helper=True))
    monkeypatch.setattr(caps, "_proc_cgroup_of", lambda pid: "/elsewhere")
    monkeypatch.setattr(caps, "_ATTEST_TIMEOUT_S", 0.5)
    processes = []
    real_popen = subprocess.Popen

    def record(*args, **kwargs):
        processes.append(real_popen(*args, **kwargs))
        return processes[-1]

    _patch(monkeypatch, caps, "subprocess", Popen=record)
    marker = tmp_path / "target-ran"
    with pytest.raises(seat_jail.SeatSandboxRefused):
        _start_capped(f"from pathlib import Path; Path({str(marker)!r}).touch()", "tree:t4s")
    (process,) = processes
    assert process.returncode == -signal.SIGTERM
    assert not marker.exists()


# --------------------------------------------------------------------------------------
# Unit-level proofs on fake witness files.
# --------------------------------------------------------------------------------------

def _events_file(tmp_path: Path, body="populated 1\nfrozen 0\n") -> tuple[Path, int]:
    path = tmp_path / f"events-{uuid.uuid4().hex}"
    path.write_text(body)
    return path, os.open(path, os.O_RDONLY | os.O_CLOEXEC)


def _group(script="import time; time.sleep(30)"):
    return subprocess.Popen([sys.executable, "-c", script], start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def _exited_group():
    process = _group("pass")
    process.wait(timeout=10)
    return process


def _reap(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


@pytest.mark.parametrize("body, expected", [
    (b"populated 0\nfrozen 0\n", True),
    (b"frozen 1\npopulated 1\n", False),
    (b"populated 0\n", True),
])
def test_events_parsing_accepts_the_kernel_body(body, expected):
    assert tp.parse_events(body) is expected


@pytest.mark.parametrize("body", [
    b"populated 0\npopulated 0\n", b"populated 2\n", b"frozen 0\n", b"populated 0 x\n",
    b"populated  0\n", b"populated\n", b"", b"\xffpopulated 0\n",
])
def test_events_parsing_rejects_malformed_bodies(tmp_path, body):
    with pytest.raises(tp.ProofFault):
        tp.parse_events(body)
    path = tmp_path / "events"
    path.write_bytes(body)
    proof = tp.TreeProof.cgroup(os.open(path, os.O_RDONLY), None, unit="u")
    assert proof.observe() is False
    assert proof.status == tp.UNKNOWN


def test_an_unreadable_or_malformed_witness_stays_unknown(tmp_path, monkeypatch):
    path, events = _events_file(tmp_path)
    proof = tp.TreeProof.cgroup(events, None, unit="u")
    real_pread = os.pread

    def eio(fd, size, offset):
        raise OSError(errno.EIO, "injected")

    _patch(monkeypatch, tp, "os", pread=eio)
    assert proof.observe() is False and proof.status == tp.UNKNOWN
    _patch(monkeypatch, tp, "os", pread=real_pread)
    _flip(path)
    assert proof.observe() is False and proof.status == tp.UNKNOWN

    path2, events2 = _events_file(tmp_path, "populated x\n")
    malformed = tp.TreeProof.cgroup(events2, None, unit="u")
    assert malformed.observe() is False and malformed.status == tp.UNKNOWN
    _flip(path2)
    assert malformed.observe() is False

    process = _exited_group()
    tp.attach(process, malformed)
    latch = panel._ProviderQuiescenceLatch()
    latch._processes[process.pid] = process
    with pytest.raises(panel.ProviderProcessGroupQuiescenceError):
        latch.release(process)
    assert not latch.is_quiescent()


def test_concurrent_terminations_signal_once_and_close_each_descriptor_once(
        tmp_path, monkeypatch, short_graces):
    path, events = _events_file(tmp_path)
    kill_read, kill_write = os.pipe()
    process = _group()
    originals = (events, kill_write)
    tp.attach(process, tp.TreeProof.cgroup(events, kill_write, unit="u"))
    terms, closes, ebadf = [], [], []
    in_signal, release = threading.Event(), threading.Event()
    real_killpg, real_close = os.killpg, os.close

    def killpg(pgid, signum):
        if signum == signal.SIGTERM:
            terms.append(pgid)
            if len(terms) == 1:
                in_signal.set()
                assert release.wait(10)
        return real_killpg(pgid, signum)

    def close(fd):
        closes.append(fd)
        try:
            return real_close(fd)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                ebadf.append(fd)
            raise

    _patch(monkeypatch, panel, "os", killpg=killpg)
    _patch(monkeypatch, tp, "os", close=close)
    errors = []

    def terminate():
        try:
            panel._terminate_process_group(process)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=terminate)
    first.start()
    assert in_signal.wait(10)
    second = threading.Thread(target=terminate)
    second.start()
    stop = threading.Event()

    def observer():
        while not stop.is_set():
            panel._tree_quiescent(process)

    third = threading.Thread(target=observer)
    third.start()
    time.sleep(0.2)
    release.set()
    assert _wait_for(lambda: _group_gone(process.pid))
    _flip(path)
    first.join(10)
    second.join(10)
    stop.set()
    third.join(10)
    assert not errors, [getattr(error, "__notes__", None) for error in errors]
    assert len(terms) == 1
    os.set_blocking(kill_read, False)
    try:
        writes = os.read(kill_read, 16)
    except BlockingIOError:
        writes = b""
    assert writes in (b"", b"1")
    assert not ebadf
    for fd in originals:
        assert closes.count(fd) == 1
    panel._terminate_process_group(process)
    assert len(terms) == 1
    os.close(kill_read)


def test_a_held_cleanup_lock_cannot_carry_termination_past_its_deadline(
        tmp_path, monkeypatch, short_graces):
    _path, events = _events_file(tmp_path)
    process = _group()
    proof = tp.attach(process, tp.TreeProof.cgroup(events, None, unit="u"))
    signals = []
    real_killpg = os.killpg

    def killpg(pgid, signum):
        if signum:
            signals.append(signum)
        return real_killpg(pgid, signum)

    _patch(monkeypatch, panel, "os", killpg=killpg)
    assert proof.cleanup_lock.acquire()
    result = {}

    def terminate():
        started = time.monotonic()
        try:
            panel._terminate_process_group(process)
        except panel.ProviderProcessGroupQuiescenceError as exc:
            result["error"] = exc
        result["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=terminate, daemon=True)
    thread.start()
    thread.join(TERM_S + KILL_S + 2)
    try:
        assert not thread.is_alive()
        assert "error" in result
        assert result["elapsed"] <= TERM_S + KILL_S + 0.5
        assert not signals
    finally:
        proof.cleanup_lock.release()
        _reap(process)


def test_kill_writes_cgroup_kill_and_the_fallback_gets_the_remaining_time(
        tmp_path, short_graces):
    path, events = _events_file(tmp_path)
    kill_read, kill_write = os.pipe()
    process = _group("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                     "time.sleep(30)")
    time.sleep(0.3)
    tp.attach(process, tp.TreeProof.cgroup(events, kill_write, unit="u"))
    received = []

    def kernel():
        received.append(os.read(kill_read, 1))
        _flip(path)

    watcher = threading.Thread(target=kernel, daemon=True)
    watcher.start()
    panel._terminate_process_group(process)
    watcher.join(5)
    assert received == [b"1"]
    os.close(kill_read)

    path2, events2 = _events_file(tmp_path)
    calls = []
    started = time.monotonic()
    deadline = started + TERM_S + KILL_S

    def fallback(timeout):
        calls.append((timeout, time.monotonic()))
        _flip(path2)

    process2 = _group("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                      "time.sleep(30)")
    time.sleep(0.3)
    tp.attach(process2, tp.TreeProof.cgroup(events2, None, unit="u", kill_fallback=fallback))
    started = time.monotonic()
    panel._terminate_process_group(process2)
    deadline = started + TERM_S + KILL_S
    ((timeout, called),) = calls
    assert 0 < timeout <= deadline - called + 0.01


# --------------------------------------------------------------------------------------
# L1-L4: the state-lock and descriptor contract.
# --------------------------------------------------------------------------------------

def test_a_held_state_lock_cannot_carry_termination_past_its_deadline(
        tmp_path, short_graces):
    _path, events = _events_file(tmp_path)
    process = _group()
    proof = tp.attach(process, tp.TreeProof.cgroup(events, None, unit="u"))
    holder_ready, holder_release = threading.Event(), threading.Event()

    def hold():
        with proof._lock:
            holder_ready.set()
            holder_release.wait(30)

    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert holder_ready.wait(5)
    result = {}

    def terminate():
        started = time.monotonic()
        try:
            panel._terminate_process_group(process)
        except panel.ProviderProcessGroupQuiescenceError as exc:
            result["error"] = exc
        result["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=terminate, daemon=True)
    thread.start()
    thread.join(TERM_S + KILL_S + 2)
    try:
        assert not thread.is_alive()
        assert result["elapsed"] <= TERM_S + KILL_S + 0.1
        notes = getattr(result["error"], "__notes__", [])
        assert any(note.startswith("state_lock_busy=") for note in notes), notes
        started = time.monotonic()
        assert proof.observe() is False
        assert time.monotonic() - started <= tp.SLICE_S + 0.03
        assert proof.status == tp.INCOMPLETE
    finally:
        holder_release.set()
        holder.join(5)
        _reap(process)


@pytest.mark.parametrize("seize", ["result_application", "after_wait"])
def test_nested_lock_contention_never_resets_the_termination_budget(
        tmp_path, monkeypatch, short_graces, seize):
    path, events = _events_file(tmp_path, "populated 0\n")
    process = _group()
    proof = tp.attach(process, tp.TreeProof.cgroup(events, None, unit="u"))
    seized, release = threading.Event(), threading.Event()

    def holder():
        with proof._lock:
            seized.set()
            release.wait(30)

    real_read, real_wait = proof._read, proof.wait

    def read(fd):
        value = real_read(fd)
        if seize == "result_application" and not seized.is_set():
            threading.Thread(target=holder, daemon=True).start()
            assert seized.wait(5)
        return value

    def wait(deadline):
        value = real_wait(deadline)
        if seize == "after_wait" and not seized.is_set():
            threading.Thread(target=holder, daemon=True).start()
            assert seized.wait(5)
            # The tree completes only once the lock is already seized.
            _flip(path)
        return value

    monkeypatch.setattr(proof, "_read", read)
    monkeypatch.setattr(proof, "wait", wait)
    if seize == "after_wait":
        path.write_text("populated 1\n")
    started = time.monotonic()
    try:
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError):
            panel._terminate_process_group(process)
        assert time.monotonic() - started <= TERM_S + KILL_S + 0.1
        assert proof.status == tp.INCOMPLETE
    finally:
        release.set()
        _reap(process)


def test_the_kill_fallback_is_bounded_reaped_and_outside_the_state_lock(
        tmp_path, monkeypatch, short_graces):
    _path, events = _events_file(tmp_path)
    started_children = []
    real_popen = tp.subprocess.Popen

    def record(*args, **kwargs):
        started_children.append(real_popen(*args, **kwargs))
        return started_children[-1]

    _patch(monkeypatch, tp, "subprocess", Popen=record)
    proof_box = {}

    def slow_fallback(timeout):
        assert not proof_box["proof"]._lock.locked()
        tp.run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout)

    process = _group("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                     "time.sleep(30)")
    time.sleep(0.3)
    proof_box["proof"] = tp.attach(
        process, tp.TreeProof.cgroup(events, None, unit="u", kill_fallback=slow_fallback))
    started = time.monotonic()
    with pytest.raises(panel.ProviderProcessGroupQuiescenceError):
        panel._terminate_process_group(process)
    assert time.monotonic() - started <= TERM_S + KILL_S + 0.3
    (child,) = started_children
    assert _wait_for(lambda: child.poll() is not None, timeout=2)
    assert proof_box["proof"].kill_errors and proof_box["proof"].kill_errors[0].startswith(
        "fallback:")

    path2, events2 = _events_file(tmp_path)

    def raising_fallback(timeout):
        assert not proof2._lock.locked()
        _flip(path2)
        raise RuntimeError("injected fallback fault")

    process2 = _group("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                      "time.sleep(30)")
    time.sleep(0.3)
    proof2 = tp.attach(process2, tp.TreeProof.cgroup(events2, None, unit="u",
                                                      kill_fallback=raising_fallback))
    panel._terminate_process_group(process2)
    assert proof2.kill_errors == ["fallback:RuntimeError"]

    _path3, events3 = _events_file(tmp_path)
    kill_read, kill_write = os.pipe()
    proof3 = tp.TreeProof.cgroup(events3, kill_write, unit="u")
    real_write = os.write

    def write(fd, data):
        if data == b"1":
            assert not proof3._lock.locked()
        return real_write(fd, data)

    _patch(monkeypatch, tp, "os", write=write)
    proof3.kill(time.monotonic() + 1)
    assert os.read(kill_read, 1) == b"1"
    os.close(kill_read)
    proof3.close()


def test_close_races_waits_and_kills_without_bad_descriptors(tmp_path, monkeypatch):
    ebadf = []
    real_pread, real_write = os.pread, os.write

    def pread(fd, size, offset):
        try:
            return real_pread(fd, size, offset)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                ebadf.append(fd)
            raise

    def write(fd, data):
        try:
            return real_write(fd, data)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                ebadf.append(fd)
            raise

    _patch(monkeypatch, tp, "os", pread=pread, write=write)
    path = tmp_path / "events"
    path.write_text("populated 1\n")
    baseline = _fd_count()
    for _ in range(200):
        path.write_text("populated 1\n")
        kill_read, kill_write = os.pipe()
        proof = tp.TreeProof.cgroup(os.open(path, os.O_RDONLY), kill_write, unit="u")
        go = threading.Barrier(3)

        def waiter():
            go.wait()
            for _ in range(3):
                proof.wait(time.monotonic() + 0.002)

        def killer():
            go.wait()
            proof.kill(time.monotonic() + 0.01)

        threads = [threading.Thread(target=waiter), threading.Thread(target=killer)]
        for thread in threads:
            thread.start()
        go.wait()
        assert proof.close(time.monotonic() + 1)
        for thread in threads:
            thread.join(5)
        _flip(path)
        assert proof.observe() is False
        assert proof.status == tp.UNKNOWN and proof.closed
        assert proof.events_fd == proof.kill_fd == -1
        os.close(kill_read)
    assert not ebadf
    assert _fd_count() == baseline


def test_pending_is_never_spoiled_and_adoption_only_accepts_pending(monkeypatch):
    calls = []

    def spy(name, real):
        def call(*args):
            calls.append(name)
            return real(*args)
        return call

    _patch(monkeypatch, tp, "os", dup=spy("dup", os.dup), pread=spy("pread", os.pread))
    _patch(monkeypatch, tp, "select", poll=spy("poll", select.poll))
    _patch(monkeypatch, tp, "signal",
           pidfd_send_signal=spy("signal", signal.pidfd_send_signal))
    proof = tp.TreeProof.pending()
    assert proof.observe() is False
    assert proof.wait(time.monotonic() + 0.01) is False
    proof.kill(time.monotonic() + 0.01)
    assert calls == [] and proof.status == tp.PENDING
    monkeypatch.undo()

    child = _group()
    try:
        stop = threading.Event()

        def observer():
            while not stop.is_set():
                proof.observe()

        thread = threading.Thread(target=observer)
        thread.start()
        time.sleep(0.05)
        assert proof.adopt_init(os.pidfd_open(child.pid)) is True
        stop.set()
        thread.join(5)
        assert proof.status == tp.INCOMPLETE

        def rejected(target):
            fd = os.pidfd_open(child.pid)
            assert target.adopt_init(fd) is False
            with pytest.raises(OSError):
                os.fstat(fd)

        rejected(proof)  # INCOMPLETE
        unknown = tp.TreeProof.pending()
        unknown.mark_witness_missing(time.monotonic() + 1)
        assert unknown.status == tp.UNKNOWN
        rejected(unknown)
        closed = tp.TreeProof.pending()
        closed.close()
        rejected(closed)
        proven = tp.TreeProof.bwrap_init(_closed_pipe())
        assert proven.observe() is True and proven.status == tp.PROVEN
        rejected(proven)
    finally:
        _reap(child)


def _closed_pipe() -> int:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    return read_fd


# --------------------------------------------------------------------------------------
# Real kernel and real bwrap (D10 probe-then-skip contract).
# --------------------------------------------------------------------------------------

_MANAGER = Path("/sys/fs/cgroup/user.slice") / f"user-{os.getuid()}.slice" / \
    f"user@{os.getuid()}.service"


def _prereq_problem() -> str | None:
    if not sys.platform.startswith("linux"):
        return "linux"
    for tool in ("/usr/bin/systemd-run", "/usr/bin/systemctl"):
        if not os.access(tool, os.X_OK):
            return Path(tool).name
    try:
        enabled = set((_MANAGER / "cgroup.subtree_control").read_text().split())
    except OSError:
        return "user_manager_cgroup"
    if not {"pids", "memory"} <= enabled:
        return "user_manager_delegation"
    if not os.access(_MANAGER / "app.slice" / "cgroup.kill", os.W_OK):
        return "cgroup_kill"
    try:
        fd = os.pidfd_open(os.getpid())
    except (AttributeError, OSError):
        return "pidfd_open"
    os.close(fd)
    try:
        done = subprocess.run(["/usr/bin/systemctl", "--user", "show", "--property=Version"],
                              capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return "user_manager_bus"
    if done.returncode:
        return "user_manager_bus"
    from _seat_prereq import nested_namespace_refusal
    refusal = nested_namespace_refusal(("/bin/true",))
    if refusal is not None:
        return f"bwrap:{refusal}"
    return None


@pytest.fixture(scope="session")
def _kernel_prereq_problem():
    return _prereq_problem()


@pytest.fixture
def kernel_prereqs(_kernel_prereq_problem):
    if _kernel_prereq_problem is not None:
        reason = f"kernel_prereq: {_kernel_prereq_problem}"
        if os.environ.get("AH_REQUIRE_KERNEL_TESTS") == "1":
            pytest.fail(reason)
        pytest.skip(reason)


def _cgroup_dir(pid: int) -> Path:
    line = next(line for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines()
                if line.startswith("0::"))
    return Path("/sys/fs/cgroup") / line[3:].lstrip("/")


class _Scope:
    """One test-owned ``ah-tp-<uuid>`` scope, always cleaned up within a bound."""

    def __init__(self, command, *, delegate=False, pass_fds=()):
        self.unit = f"ah-tp-{uuid.uuid4().hex}.scope"
        argv = ["/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--collect",
                f"--unit={self.unit}", "--slice=app.slice"]
        if delegate:
            argv.append("-p")
            argv.append("Delegate=yes")
        self.process = subprocess.Popen(
            [*argv, "--", *command], pass_fds=pass_fds, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.path: Path | None = None
        self.pidfds: list[int] = []
        self.barriers: list[int] = []
        self.created: list[Path] = []

    def locate(self):
        self.path = _cgroup_dir(self.process.pid)
        assert self.path.name == self.unit, self.path
        return self.path

    def cleanup(self):
        if self.path is not None:
            try:
                (self.path / "cgroup.kill").write_text("1")
            except OSError:
                pass
        for fd in self.pidfds:
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except OSError:
                pass
        for fd in self.barriers:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for directory in reversed(self.created):
            _wait_for(lambda: _unpopulated(directory), timeout=5)
            try:
                directory.rmdir()
            except OSError:
                pass
        for fd in self.pidfds:
            try:
                os.close(fd)
            except OSError:
                pass


def _unpopulated(directory: Path) -> bool:
    try:
        return "populated 0" in (directory / "cgroup.events").read_text()
    except OSError:
        return True


def _read_line(fd: int, timeout=15.0) -> str:
    data = b""
    deadline = time.monotonic() + timeout
    while not data.endswith(b"\n"):
        remaining = deadline - time.monotonic()
        assert remaining > 0, "fixture readiness timed out"
        if select.select([fd], [], [], remaining)[0]:
            chunk = os.read(fd, 64)
            assert chunk, "fixture exited before readiness"
            data += chunk
    return data.decode().strip()


def test_a_zombie_member_does_not_keep_the_scope_populated(kernel_prereqs):
    barrier_r, barrier_w = os.pipe()
    ready_r, ready_w = os.pipe()
    scope = _Scope([sys.executable, "-c",
                    "import os,sys; os.write(int(sys.argv[2]), b'r\\n'); "
                    "os.read(int(sys.argv[1]), 1)", str(barrier_r), str(ready_w)],
                   pass_fds=(barrier_r, ready_w))
    os.close(barrier_r)
    os.close(ready_w)
    scope.barriers.append(barrier_w)
    try:
        _read_line(ready_r)
        events = os.open(scope.locate() / "cgroup.events", os.O_RDONLY)
        try:
            os.close(barrier_w)
            scope.barriers.clear()

            def state():
                return Path(f"/proc/{scope.process.pid}/stat").read_text().rsplit(") ", 1)[1][0]

            assert _wait_for(lambda: state() == "Z", timeout=5)

            def unpopulated():
                try:
                    return tp.parse_events(os.pread(events, 4096, 0))
                except OSError as exc:
                    return exc.errno == errno.ENODEV

            assert _wait_for(unpopulated, timeout=5)
            assert state() == "Z"
        finally:
            os.close(events)
    finally:
        os.close(ready_r)
        scope.cleanup()


_SYS_EXIT = {"x86_64": 60, "aarch64": 93}.get(os.uname().machine, 60)


def test_a_live_sibling_thread_keeps_the_scope_populated(kernel_prereqs):
    barrier_r, barrier_w = os.pipe()
    ready_r, ready_w = os.pipe()
    script = (
        "import ctypes,os,sys,threading\n"
        "r=int(sys.argv[1]); w=int(sys.argv[2])\n"
        "def sibling():\n"
        "    os.write(w, b'r\\n'); os.read(r, 1); os._exit(0)\n"
        "threading.Thread(target=sibling).start()\n"
        f"ctypes.CDLL(None).syscall({_SYS_EXIT}, 0)\n"
    )
    scope = _Scope([sys.executable, "-c", script, str(barrier_r), str(ready_w)],
                   pass_fds=(barrier_r, ready_w))
    os.close(barrier_r)
    os.close(ready_w)
    scope.barriers.append(barrier_w)
    try:
        _read_line(ready_r)
        events = os.open(scope.locate() / "cgroup.events", os.O_RDONLY)
        try:
            for _ in range(5):
                assert tp.parse_events(os.pread(events, 4096, 0)) is False
                time.sleep(0.05)
            os.close(barrier_w)
            scope.barriers.clear()

            def unpopulated():
                try:
                    return tp.parse_events(os.pread(events, 4096, 0))
                except OSError as exc:
                    return exc.errno == errno.ENODEV

            assert _wait_for(unpopulated, timeout=5)
        finally:
            os.close(events)
    finally:
        os.close(ready_r)
        scope.cleanup()


_BWRAP = ("/usr/bin/bwrap", "--unshare-pid", "--unshare-user", "--new-session",
          "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev")


def test_terminate_waits_for_every_member_of_the_launch_scope(
        kernel_prereqs, monkeypatch, short_graces):
    """A bwrap tree in its own session (no parent-death signal) runs beside the launch's
    process group; cleanup returns once the whole scope is empty."""
    barrier_r, barrier_w = os.pipe()
    ready_r, ready_w = os.pipe()
    provider = (
        "import os,signal,sys\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "r=int(sys.argv[1]); w=int(sys.argv[2])\n"
        "if os.fork()==0:\n"
        "    os.setsid(); os.write(w, b'r\\n'); os.read(r, 1); os._exit(0)\n"
        "os.read(r, 1)\n"
    )
    scope = _Scope([*_BWRAP, "--", sys.executable, "-c", provider, str(barrier_r),
                    str(ready_w)], pass_fds=(barrier_r, ready_w))
    os.close(barrier_r)
    os.close(ready_w)
    scope.barriers.append(barrier_w)
    oracles: list[int] = []
    try:
        _read_line(ready_r)
        path = scope.locate()
        for pid in (path / "cgroup.procs").read_text().split():
            oracles.append(os.pidfd_open(int(pid)))
        assert len(oracles) >= 3  # outer bwrap, init and provider, grandchild
        witness = getattr(caps, "_witness_scope", None)
        if witness is not None:
            monkeypatch.setattr(caps, "_seat_slice_chain", lambda _unit: (path.parent,))
            tp.attach(scope.process, witness(scope.process.pid, "unused", scope.unit))
        panel._anchor_process_group(scope.process)
        panel._terminate_process_group(scope.process)
        assert all(select.select([fd], [], [], 0)[0] for fd in oracles), \
            "cleanup returned before every member of the launch scope exited"
    finally:
        for fd in oracles:
            os.close(fd)
        os.close(ready_r)
        scope.cleanup()


def _nested_scope(kernel_prereqs_fixture=None):
    barrier_r, barrier_w = os.pipe()
    ready_r, ready_w = os.pipe()
    go_r, go_w = os.pipe()
    script = (
        "import os,sys\n"
        "r=int(sys.argv[1]); w=int(sys.argv[2]); go=int(sys.argv[3])\n"
        "pid=os.fork()\n"
        "if pid==0:\n"
        "    os.close(go); os.read(r, 1); os._exit(0)\n"
        "os.write(w, (str(pid)+'\\n').encode()); os.read(go, 1)\n"
    )
    scope = _Scope([sys.executable, "-c", script, str(barrier_r), str(ready_w), str(go_r)],
                   delegate=True, pass_fds=(barrier_r, ready_w, go_r))
    for fd in (barrier_r, ready_w, go_r):
        os.close(fd)
    scope.barriers.extend((barrier_w, go_w))
    grandchild = int(_read_line(ready_r))
    os.close(ready_r)
    scope.pidfds.append(os.pidfd_open(grandchild))
    path = scope.locate()
    child = path / "child"
    child.mkdir()
    scope.created.append(child)
    (child / "cgroup.procs").write_text(str(grandchild))
    os.close(go_w)
    scope.barriers.remove(go_w)
    assert scope.process.wait(timeout=10) == 0
    return scope, path, child


def test_a_nested_member_keeps_the_scope_populated_and_scope_kill_reaches_it(
        kernel_prereqs):
    scope, path, child = _nested_scope()
    try:
        events = os.open(path / "cgroup.events", os.O_RDONLY)
        kill = os.open(path / "cgroup.kill", os.O_WRONLY)
        proof = tp.TreeProof.cgroup(events, kill, unit=scope.unit)
        assert (path / "cgroup.procs").read_text().split() == []
        assert proof.observe() is False and proof.status == tp.INCOMPLETE
        proof.kill(time.monotonic() + 5)
        deadline = time.monotonic() + 5
        while not proof.observe(deadline) and time.monotonic() < deadline:
            proof.wait(deadline)
        assert proof.status == tp.PROVEN and proof.reason in {"unpopulated", "enodev"}
    finally:
        scope.cleanup()


def test_a_removed_witnessed_cgroup_reports_enodev_and_proves(kernel_prereqs):
    scope, path, child = _nested_scope()
    try:
        events = os.open(child / "cgroup.events", os.O_RDONLY)
        proof = tp.TreeProof.cgroup(events, None, unit=scope.unit)
        (child / "cgroup.kill").write_text("1")
        assert _wait_for(lambda: _unpopulated(child), timeout=5)
        try:
            child.rmdir()
        except FileNotFoundError:
            pass  # the manager trimmed it first; the held descriptor is what matters
        scope.created.remove(child)
        probe = os.dup(events)
        try:
            with pytest.raises(OSError) as raised:
                os.pread(probe, 4096, 0)
            assert raised.value.errno == errno.ENODEV
        finally:
            os.close(probe)
        assert proof.observe() is True
        assert proof.status == tp.PROVEN and proof.reason == "enodev"
    finally:
        scope.cleanup()


# --------------------------------------------------------------------------------------
# B1/B3: the bwrap init witness and its gate on real bwrap.
# --------------------------------------------------------------------------------------

_MARKER_SCRIPT = (
    "import os,sys; from pathlib import Path\n"
    "Path(sys.argv[1]).touch()\n"
    "os.read(int(sys.argv[2]), 1) if len(sys.argv) > 2 else None\n"
)


def _start_bwrap(witness, command, *, writable, pass_fds=(), die_with_parent=False):
    argv = ["/usr/bin/bwrap", "--info-fd", str(witness.info_fd), "--block-fd",
            str(witness.block_fd), *_BWRAP[1:], "--bind", str(writable), str(writable),
            *(("--die-with-parent",) if die_with_parent else ()), "--", *command]
    return subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            **witness.popen_kwargs({"pass_fds": pass_fds}))


def test_the_pinned_init_gates_the_command_and_proves_completion(kernel_prereqs, tmp_path):
    marker = tmp_path / "marker"
    barrier_r, barrier_w = os.pipe()
    witness = tp.BwrapLaunch()
    process = _start_bwrap(witness, [sys.executable, "-c", _MARKER_SCRIPT, str(marker),
                                     str(barrier_r)], writable=tmp_path,
                           pass_fds=(barrier_r,))
    os.close(barrier_r)
    seen_before_gate = []

    def before_gate(proc):
        time.sleep(0.3)
        seen_before_gate.append(marker.exists())

    try:
        witness.complete(process, before_gate=before_gate)
        assert seen_before_gate == [False]
        assert _wait_for(marker.exists)
        proof = tp.proof_of(process)
        os.kill(process.pid, signal.SIGKILL)  # the outer exits; the init still runs
        process.wait(timeout=5)
        assert proof.observe() is False and proof.status == tp.INCOMPLETE
        os.close(barrier_w)
        barrier_w = -1
        deadline = time.monotonic() + 5
        while not proof.wait(deadline) and time.monotonic() < deadline:
            pass
        assert proof.status == tp.PROVEN
    finally:
        if barrier_w >= 0:
            os.close(barrier_w)
        _reap(process)


def _held(block_w) -> bool:
    return block_w in tp._HELD_GATES


@pytest.mark.parametrize("case", ["bad_json", "ppid_mismatch", "nspid_failure"])
def test_a_failed_pin_releases_the_gate_only_after_no_reader_remains(
        kernel_prereqs, tmp_path, monkeypatch, case):
    marker = tmp_path / "marker"
    witness = tp.BwrapLaunch()
    block_w = witness.block_w
    if case == "bad_json":
        real = tp._read_info

        def read_info(fd, deadline):
            real(fd, deadline)
            raise tp.PinFailure("S2", "bwrap_info_malformed")

        monkeypatch.setattr(tp, "_read_info", read_info)
    elif case == "ppid_mismatch":
        monkeypatch.setattr(tp, "_proc_stat", lambda pid: ("S", 1))
    else:
        monkeypatch.setattr(tp, "_nspid", lambda pid: "7")
    released = []
    real_release = tp._release_if_no_reader

    def release(fd, deadline):
        value = real_release(fd, deadline)
        released.append(value)
        return value

    monkeypatch.setattr(tp, "_release_if_no_reader", release)
    process = _start_bwrap(witness, [sys.executable, "-c", _MARKER_SCRIPT, str(marker)],
                           writable=tmp_path)
    with pytest.raises(tp.WitnessUnavailable) as failed:
        witness.complete(process)
    time.sleep(1)
    try:
        assert not marker.exists(), "the gated command ran after a failed pin"
        assert failed.value.stage == {"bad_json": "S2", "ppid_mismatch": "S3",
                                      "nspid_failure": "S4"}[case]
        assert released == [True] and not _held(block_w)
    finally:
        _reap(process)


def test_an_unestablished_teardown_keeps_the_gate_held_through_collection(
        kernel_prereqs, tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    witness = tp.BwrapLaunch()
    block_w = witness.block_w
    info = {}
    real = tp._read_info

    def read_info(fd, deadline):
        info.update(real(fd, deadline))
        raise tp.PinFailure("S2", "bwrap_info_malformed")

    def no_group(pgid, signum):
        raise PermissionError(errno.EPERM, "injected")

    monkeypatch.setattr(tp, "_read_info", read_info)
    monkeypatch.setattr(tp, "TEARDOWN_BUDGET_S", 0.5)
    process = _start_bwrap(witness, [sys.executable, "-c", _MARKER_SCRIPT, str(marker)],
                           writable=tmp_path)

    launch_args = process.args

    def wait(timeout=None):
        raise subprocess.TimeoutExpired(launch_args, timeout)

    _patch(monkeypatch, tp, "os", killpg=no_group)
    monkeypatch.setattr(process, "wait", wait)
    with pytest.raises(tp.WitnessUnavailable) as failed:
        witness.complete(process)
    monkeypatch.undo()
    assert failed.value.retained and "gate_retained:S2" in failed.value.__notes__
    assert _held(block_w)
    child = info["child-pid"]
    pidfd = os.pidfd_open(child)
    outer_pid = process.pid
    del process, witness, failed
    gc.collect()
    assert _held(block_w)
    time.sleep(1)
    assert not marker.exists()
    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
    assert tp._release_if_no_reader(block_w, time.monotonic() + 5)
    assert not _held(block_w)
    time.sleep(0.5)
    assert not marker.exists()
    os.close(pidfd)
    try:
        os.waitpid(outer_pid, 0)
    except ChildProcessError:
        pass


# --------------------------------------------------------------------------------------
# B5: the teardown stage table on fake pipes.
# --------------------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, pid):
        self.pid = pid
        self.killed = 0

    def kill(self):
        self.killed += 1

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


@pytest.mark.parametrize("stage", ["S0", "S1", "S2", "S3", "S4", "S5", "S6"])
def test_the_teardown_stage_table(monkeypatch, stage):
    group, init = [], []
    reader: dict[str, int] = {}

    def drop_reader():
        fd = reader.pop("fd", None)
        if fd is not None:
            os.close(fd)

    def killpg(pgid, signum):
        group.append(pgid)
        drop_reader()

    def pidfd_send_signal(fd, signum):
        init.append(fd)
        drop_reader()

    _patch(monkeypatch, tp, "os", killpg=killpg)
    _patch(monkeypatch, tp, "signal", pidfd_send_signal=pidfd_send_signal)
    witness = tp.BwrapLaunch()
    block_w = witness.block_w
    if stage in {"S0", "S1"}:
        assert witness.abandon() is True
        assert not group and not init and not _held(block_w)
        return
    reader["fd"] = os.dup(witness.block_fd)
    sleeper = _group()
    try:
        proc = _FakeProc(os.getpid())
        if stage == "S2":
            os.write(witness.info_fd, b"not json")
        elif stage == "S3":
            os.write(witness.info_fd, json.dumps({"child-pid": sleeper.pid}).encode())
            monkeypatch.setattr(tp, "_proc_stat", lambda pid: ("S", os.getpid() + 1))
        elif stage == "S4":
            os.write(witness.info_fd, json.dumps({"child-pid": sleeper.pid}).encode())
        else:
            monkeypatch.setattr(tp, "pin_bwrap_init",
                                lambda pid, fd, deadline: os.pidfd_open(sleeper.pid))

        def before_gate(_proc):
            if stage == "S5":
                raise RuntimeError("injected before the gate")
            drop_reader()  # S6: the last reader is gone before the gate write

        with pytest.raises(tp.WitnessUnavailable) as failed:
            witness.complete(proc, before_gate=before_gate)
        assert failed.value.stage == stage
        assert not _held(block_w) and not failed.value.retained
        assert group == [proc.pid]
        expected_init = 1 if stage in {"S4", "S5", "S6"} else 0
        assert len(init) == expected_init
    finally:
        drop_reader()
        _reap(sleeper)


def test_an_exception_inside_teardown_leaves_the_gate_held(monkeypatch):
    def interrupted(pgid, signum):
        raise KeyboardInterrupt

    _patch(monkeypatch, tp, "os", killpg=interrupted)
    witness = tp.BwrapLaunch()
    block_w = witness.block_w
    reader = os.dup(witness.block_fd)
    os.write(witness.info_fd, b"not json")
    try:
        with pytest.raises(KeyboardInterrupt):
            witness.complete(_FakeProc(os.getpid()))
        assert _held(block_w)
    finally:
        os.close(reader)
        assert tp._release_if_no_reader(block_w, time.monotonic() + 1)


# --------------------------------------------------------------------------------------
# B4: the raw owned branch pins its init; the Gemini profile's launch adopts it later.
# --------------------------------------------------------------------------------------

def test_an_owned_raw_launch_carries_its_lifecycle_fds_after_the_owners_bwrap(
        kernel_prereqs, tmp_path, monkeypatch):
    launched, probed = [], []
    real_popen, real_run = subprocess.Popen, subprocess.run

    def popen(argv, *args, **kwargs):
        launched.append(list(argv))
        return real_popen(argv, *args, **kwargs)

    def run(argv, *args, **kwargs):
        probed.append(list(argv))
        return real_run(argv, *args, **kwargs)

    _patch(monkeypatch, panel, "subprocess", Popen=popen, run=run)
    provider = tmp_path / "provider"
    provider.write_text("#!/usr/bin/python3\nimport os\n"
                        "print(os.stat('/proc/self/ns/pid').st_ino)\n")
    provider.chmod(0o700)
    process = panel.launch_owned(
        [str(provider)], role=panel.SeatLaunchRole.PROVIDER_ADMIN,
        profile=panel.SeatProfile(env={"PATH": "/usr/bin:/bin"}, readonly_paths=(provider,)),
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = process.communicate(timeout=15)
    finally:
        panel._terminate_process_group(process)
    assert process.returncode == 0, err
    assert int(out) != os.stat("/proc/self/ns/pid").st_ino
    (argv,) = [item for item in launched if "/usr/bin/bwrap" in item]
    index = argv.index("/usr/bin/bwrap")
    assert argv[index + 1] == "--info-fd" and argv[index + 3] == "--block-fd"
    assert all("--info-fd" not in item for item in probed if "/usr/bin/bwrap" in item)
    proof = tp.proof_of(process)
    assert proof is not None and proof.kind == tp.BWRAP_INIT
    assert proof.status == tp.PROVEN


def _pending_launch(monkeypatch):
    monkeypatch.setattr(panel, "_probes_seat", lambda *args, **kwargs: False)
    monkeypatch.setattr(panel, "_compose_launch_prefix",
                        lambda cwd, owner=(), retain_caps=(): [
                            "/bin/sh", "-c", "read line", "sh", "--info-fd"])
    owner = ["/usr/bin/bwrap", "--unshare-pid", "--info-fd", "9", "--block-fd", "10", "--"]
    return panel.launch_provider(["profile-command"], process_owner=owner,
                                 stdin=subprocess.PIPE, start_new_session=True)


def test_a_profile_owned_launch_is_pending_until_its_init_is_adopted(
        monkeypatch, short_graces):
    process = _pending_launch(monkeypatch)
    proof = tp.proof_of(process)
    assert proof is not None and proof.status == tp.PENDING
    assert proof.adopt_init(os.pidfd_open(process.pid)) is True
    assert proof.status == tp.INCOMPLETE
    panel._terminate_process_group(process)
    assert proof.status == tp.PROVEN


def test_cleanup_before_the_profile_admits_leaves_the_proof_unknown(
        monkeypatch, short_graces):
    process = _pending_launch(monkeypatch)
    proof = tp.proof_of(process)
    try:
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError):
            panel._terminate_process_group(process)
        assert proof.status == tp.UNKNOWN and proof.reason == "witness_missing"
        assert proof.adopt_init(os.pidfd_open(os.getpid())) is False
    finally:
        _reap(process)


def test_an_owned_launch_without_its_bwrap_in_the_prefix_is_refused_and_releases_its_gate(
        monkeypatch):
    monkeypatch.setattr(panel, "_probes_seat", lambda *args, **kwargs: False)
    monkeypatch.setattr(panel, "_compose_launch_prefix",
                        lambda cwd, owner=(), retain_caps=(): ["/bin/true"])
    started = []
    _patch(monkeypatch, panel, "subprocess",
           Popen=lambda *args, **kwargs: started.append(args))
    held = set(tp._HELD_GATES)
    baseline = _fd_count()
    with pytest.raises(panel._sandbox_egress.SeatIdentityUnverified, match="seat_owner_unavailable"):
        panel.launch_provider(["profile-command"],
                              process_owner=["/usr/bin/bwrap", "--unshare-pid", "--"])
    assert not started
    assert set(tp._HELD_GATES) == held
    assert _fd_count() == baseline


# --------------------------------------------------------------------------------------
# agent-harness#2005: integration coverage for the Gemini-profile adoption call inside
# _run_leg_with_liveness (uncapped profile-owned launch).
# --------------------------------------------------------------------------------------

class _FakeGeminiHeartbeatProfile:
    """Minimal stand-in for ``gemini_heartbeat.GeminiHeartbeatProfile`` in liveness tests."""

    def __init__(self, *, admit_fn):
        self.executable = "/heartbeat/agy"
        self.env = {"PATH": "/usr/bin:/bin"}
        self.mount_args = ["--info-fd", "9", "--block-fd", "10"]
        self.process = None
        self.init_fd: int | None = None
        self.identity: dict[str, int] | None = None
        self.quiescent = False
        self.evidence: dict[str, object] = {}
        self.admit_calls = 0
        self.quiescence_checks = 0
        self.init_fd_open_at_quiescence: bool | None = None
        self._admit_fn = admit_fn

    def admit(self, proc, cancel):
        self.admit_calls += 1
        self._admit_fn(self, proc, cancel)

    def verify_quiescence(self):
        self.quiescence_checks += 1
        if self.init_fd is not None:
            os.fstat(self.init_fd)
            self.init_fd_open_at_quiescence = True
        self.quiescent = True

    def close(self):
        if self.init_fd is not None:
            fd, self.init_fd = self.init_fd, None
            os.close(fd)


def _pid_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _kill_if_alive(pid: int | None) -> None:
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _setup_uncapped_gemini_liveness(monkeypatch, tmp_path, *, descendant_pid_file: Path | None = None):
    """Wire ``_run_leg_with_liveness`` for a fake-host uncapped Gemini profile launch."""
    profile_lifecycle: list[str] = []
    monkeypatch.setattr(panel, "_probes_seat", lambda *args, **kwargs: False)
    monkeypatch.setattr(panel, "_filtered_holder_namespace", lambda: 1)
    monkeypatch.setattr(
        panel, "_seat_owner",
        lambda view, *, filtered_network=False: [
            "/usr/bin/bwrap", "--unshare-pid", *view, "--",
        ],
    )
    if descendant_pid_file is None:
        script = "IFS= read -r line && cat >/dev/null && printf '%s\\n' \"$line\""
    else:
        pid_path = shlex.quote(str(descendant_pid_file))
        tmp_pid_path = shlex.quote(str(descendant_pid_file) + ".tmp")
        script = (
            "sleep 60 </dev/null >/dev/null 2>&1 & "
            f"printf '%s\\n' \"$!\" > {tmp_pid_path} && mv {tmp_pid_path} {pid_path} && "
            "IFS= read -r line && cat >/dev/null && printf '%s\\n' \"$line\""
        )

    def _fake_compose_launch_prefix(cwd, owner=(), retain_caps=()):
        # Preserve lifecycle flags only when the supplied owner actually carries them,
        # so breaking gemini_profile forwarding through launch_owned fails the tests.
        lifecycle = [arg for arg in owner if arg in ("--info-fd", "--block-fd")]
        return ["/bin/sh", "-c", script, "sh", *lifecycle]

    monkeypatch.setattr(panel, "_compose_launch_prefix", _fake_compose_launch_prefix)

    @contextlib.contextmanager
    def _fake_seat_command_profile(command, *, env, cwd, gemini_profile=None, **kwargs):
        profile_lifecycle.append("enter")
        try:
            yield list(command), panel.SeatProfile(
                env={"PATH": "/usr/bin:/bin"},
                mount_args=tuple(gemini_profile.mount_args) if gemini_profile is not None else (),
            )
        finally:
            profile_lifecycle.append("exit")

    monkeypatch.setattr(panel, "_seat_command_profile", _fake_seat_command_profile)
    monitor = panel._ReviewMonitor(
        tmp_path / "monitor.json", "gemini-adoption", 0, threading.Event(),
    )
    return monitor, profile_lifecycle


def _await_same_group_descendant(pid_file: Path, leader_pid: int) -> int:
    assert _wait_for(pid_file.exists, timeout=5.0), "same-group descendant did not publish its pid"
    descendant_pid = int(pid_file.read_text(encoding="utf-8").strip())
    assert descendant_pid != leader_pid
    assert os.getpgid(descendant_pid) == leader_pid
    return descendant_pid


def _run_uncapped_gemini_leg(tmp_path, monitor, profile, *, input_text="adopted\n"):
    egress_token = panel._EGRESS_LAUNCH_PREFIX.set(("fake-egress",))
    try:
        with panel._uncapped_nonseat_probe():
            return panel._run_leg_with_liveness(
                [profile.executable],
                cwd=tmp_path,
                env=profile.env,
                deadline_s=10.0,
                stall_threshold_s=10.0,
                input_text=input_text,
                review_monitor=monitor,
                gemini_profile=profile,
            )
    finally:
        panel._EGRESS_LAUNCH_PREFIX.reset(egress_token)


def test_run_leg_with_liveness_adopts_duplicate_gemini_init_fd_on_uncapped_launch(
        monkeypatch, tmp_path, short_graces):
    monitor, profile_lifecycle = _setup_uncapped_gemini_liveness(monkeypatch, tmp_path)
    observed: dict[str, object] = {}
    real_dup = os.dup

    def _recording_dup(fd):
        duplicated = real_dup(fd)
        observed["dup_src"] = fd
        observed["dup_dst"] = duplicated
        return duplicated

    _patch(monkeypatch, panel, "os", dup=_recording_dup)

    def _admit(self, proc, cancel):
        assert cancel is monitor.cancel
        assert proc.poll() is None
        proof = tp.proof_of(proc)
        assert proof is not None and proof.status == tp.PENDING
        observed["proof"] = proof
        self.init_fd = os.pidfd_open(proc.pid)
        self.identity = {"init_pid": proc.pid}
        real_adopt = proof.adopt_init

        def _spy_adopt(fd, deadline=None):
            observed["adopted_fd"] = fd
            observed["adopted_stat"] = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
            ok = real_adopt(fd, deadline=deadline)
            observed["status_after_adopt"] = proof.status
            return ok

        monkeypatch.setattr(proof, "adopt_init", _spy_adopt)

    profile = _FakeGeminiHeartbeatProfile(admit_fn=_admit)
    baseline = _fd_count()
    try:
        result = _run_uncapped_gemini_leg(tmp_path, monitor, profile)
        assert result.returncode == 0
        assert result.stdout == "adopted\n"
        assert result.stderr == ""
        assert profile.admit_calls == 1
        assert profile.quiescence_checks == 1
        assert profile.init_fd_open_at_quiescence is True
        assert profile_lifecycle == ["enter", "exit"]
        proof = observed["proof"]
        assert observed["dup_src"] == profile.init_fd
        assert observed["adopted_fd"] == observed["dup_dst"]
        assert observed["adopted_fd"] != profile.init_fd
        assert observed["status_after_adopt"] == tp.INCOMPLETE
        assert proof.status == tp.PROVEN and proof.reason == "init_exited"
        # Adoption transferred a duplicate: the profile's own descriptor stayed open.
        assert profile.init_fd is not None
        profile_stat = os.fstat(profile.init_fd)
        assert observed["adopted_stat"] == (profile_stat.st_dev, profile_stat.st_ino)
        assert _group_gone(profile.process.pid)
    finally:
        profile.close()
    assert _fd_count() == baseline


@pytest.mark.parametrize("failure_mode", ["admit_raises", "missing_init_fd"])
def test_run_leg_with_liveness_refuses_gemini_admission_failure_and_reaps(
        monkeypatch, tmp_path, short_graces, failure_mode):
    descendant_pid_file = tmp_path / "descendant.pid"
    monitor, profile_lifecycle = _setup_uncapped_gemini_liveness(
        monkeypatch, tmp_path, descendant_pid_file=descendant_pid_file,
    )
    observed: dict[str, object] = {"dup_calls": 0, "adopt_calls": 0, "descendant_pid": None}
    real_dup = os.dup

    def _recording_dup(fd):
        observed["dup_calls"] += 1
        return real_dup(fd)

    _patch(monkeypatch, panel, "os", dup=_recording_dup)

    def _admit(self, proc, cancel):
        assert proc.poll() is None
        observed["descendant_pid"] = _await_same_group_descendant(descendant_pid_file, proc.pid)
        proof = tp.proof_of(proc)
        assert proof is not None and proof.status == tp.PENDING
        observed["proof"] = proof
        real_adopt = proof.adopt_init

        def _spy_adopt(fd, deadline=None):
            observed["adopt_calls"] += 1
            return real_adopt(fd, deadline=deadline)

        monkeypatch.setattr(proof, "adopt_init", _spy_adopt)
        if failure_mode == "admit_raises":
            raise ValueError("gemini_heartbeat_admission_handshake_failed")
        # missing_init_fd: admit returns without pinning an init pidfd.

    profile = _FakeGeminiHeartbeatProfile(admit_fn=_admit)
    baseline = _fd_count()
    try:
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError) as exc_info:
            _run_uncapped_gemini_leg(tmp_path, monitor, profile)
        assert isinstance(exc_info.value.__context__, ValueError)
        assert "gemini_heartbeat_admission_handshake_failed" in str(exc_info.value.__context__)
        assert profile.admit_calls == 1
        assert observed["dup_calls"] == 0
        assert observed["adopt_calls"] == 0
        assert profile_lifecycle == ["enter", "exit"]
        proof = observed["proof"]
        assert proof.status == tp.UNKNOWN and proof.reason == "witness_missing"
        assert profile.process is not None and profile.process.poll() is not None
        assert _group_gone(profile.process.pid)
        assert _wait_for(lambda: _pid_gone(observed["descendant_pid"]), timeout=2.0)
    finally:
        _kill_if_alive(observed["descendant_pid"])
        profile.close()
    assert _fd_count() == baseline


def test_run_leg_with_liveness_handles_gemini_init_fd_duplication_failure(
        monkeypatch, tmp_path, short_graces):
    descendant_pid_file = tmp_path / "descendant.pid"
    monitor, profile_lifecycle = _setup_uncapped_gemini_liveness(
        monkeypatch, tmp_path, descendant_pid_file=descendant_pid_file,
    )
    observed: dict[str, object] = {"adopt_calls": 0, "descendant_pid": None}

    def _failing_dup(fd):
        observed["dup_src"] = fd
        raise OSError(errno.EMFILE, "too many open files")

    _patch(monkeypatch, panel, "os", dup=_failing_dup)

    def _admit(self, proc, cancel):
        assert proc.poll() is None
        observed["descendant_pid"] = _await_same_group_descendant(descendant_pid_file, proc.pid)
        proof = tp.proof_of(proc)
        assert proof is not None and proof.status == tp.PENDING
        observed["proof"] = proof
        self.init_fd = os.pidfd_open(proc.pid)
        self.identity = {"init_pid": proc.pid}
        real_adopt = proof.adopt_init

        def _spy_adopt(fd, deadline=None):
            observed["adopt_calls"] += 1
            return real_adopt(fd, deadline=deadline)

        monkeypatch.setattr(proof, "adopt_init", _spy_adopt)

    profile = _FakeGeminiHeartbeatProfile(admit_fn=_admit)
    baseline = _fd_count()
    try:
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError) as exc_info:
            _run_uncapped_gemini_leg(tmp_path, monitor, profile)
        assert isinstance(exc_info.value.__context__, OSError)
        assert exc_info.value.__context__.errno == errno.EMFILE
        assert observed["dup_src"] == profile.init_fd
        assert observed["adopt_calls"] == 0
        assert profile.quiescence_checks == 1
        assert profile.init_fd_open_at_quiescence is True
        assert profile_lifecycle == ["enter", "exit"]
        proof = observed["proof"]
        assert proof.status == tp.UNKNOWN and proof.reason == "witness_missing"
        assert profile.process is not None and profile.process.poll() is not None
        assert _group_gone(profile.process.pid)
        assert _wait_for(lambda: _pid_gone(observed["descendant_pid"]), timeout=2.0)
        assert profile.init_fd is not None
        os.fstat(profile.init_fd)
    finally:
        _kill_if_alive(observed["descendant_pid"])
        profile.close()
    assert _fd_count() == baseline


def test_run_leg_with_liveness_closes_duplicate_and_reaps_when_adopt_init_refuses(
        monkeypatch, tmp_path, short_graces):
    descendant_pid_file = tmp_path / "descendant.pid"
    monitor, profile_lifecycle = _setup_uncapped_gemini_liveness(
        monkeypatch, tmp_path, descendant_pid_file=descendant_pid_file,
    )
    observed: dict[str, object] = {"descendant_pid": None}
    real_dup = os.dup

    def _recording_dup(fd):
        duplicated = real_dup(fd)
        observed["dup_dst"] = duplicated
        return duplicated

    _patch(monkeypatch, panel, "os", dup=_recording_dup)

    def _admit(self, proc, cancel):
        assert proc.poll() is None
        observed["descendant_pid"] = _await_same_group_descendant(descendant_pid_file, proc.pid)
        proof = tp.proof_of(proc)
        assert proof is not None and proof.status == tp.PENDING
        observed["proof"] = proof
        self.init_fd = os.pidfd_open(proc.pid)
        self.identity = {"init_pid": proc.pid}
        # Reject the single adoption attempt via the real adopt_init lock-busy path
        # so adopt_init itself closes the transferred duplicate before returning False.
        real_acquire = proof._acquire
        real_adopt = proof.adopt_init
        reject_next = {"flag": True}

        def _busy_once(deadline):
            if reject_next["flag"]:
                reject_next["flag"] = False
                return False
            return real_acquire(deadline)

        def _spy_adopt(fd, deadline=None):
            observed["adopted_fd"] = fd
            ok = real_adopt(fd, deadline=deadline)
            observed["adopt_returned"] = ok
            try:
                os.fstat(fd)
                observed["dup_closed_immediately"] = False
            except OSError as exc:
                observed["dup_closed_immediately"] = exc.errno == errno.EBADF
            return ok

        monkeypatch.setattr(proof, "_acquire", _busy_once)
        monkeypatch.setattr(proof, "adopt_init", _spy_adopt)

    profile = _FakeGeminiHeartbeatProfile(admit_fn=_admit)
    baseline = _fd_count()
    try:
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError) as exc_info:
            _run_uncapped_gemini_leg(tmp_path, monitor, profile)
        assert isinstance(exc_info.value.__context__, ValueError)
        assert "gemini_heartbeat_admission_handshake_failed" in str(exc_info.value.__context__)
        assert observed["adopted_fd"] == observed["dup_dst"]
        assert observed["adopted_fd"] != profile.init_fd
        assert observed["adopt_returned"] is False
        assert observed["dup_closed_immediately"] is True
        assert profile.quiescence_checks == 1
        assert profile.init_fd_open_at_quiescence is True
        assert profile_lifecycle == ["enter", "exit"]
        proof = observed["proof"]
        assert proof.status == tp.UNKNOWN and proof.reason == "witness_missing"
        assert profile.process is not None and profile.process.poll() is not None
        assert _group_gone(profile.process.pid)
        assert _wait_for(lambda: _pid_gone(observed["descendant_pid"]), timeout=2.0)
        assert profile.init_fd is not None
        os.fstat(profile.init_fd)
    finally:
        _kill_if_alive(observed["descendant_pid"])
        profile.close()
    assert _fd_count() == baseline
