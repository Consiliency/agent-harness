"""Operator policy must refuse before effects and survive unknown silence."""
from dataclasses import replace
from contextlib import contextmanager
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime import panel_invoker as panel


def supported_board():
    return replace(DEFAULT_BOARD, seats=tuple(
        seat for seat in DEFAULT_BOARD.seats if seat.harness != "gemini"
    ))


def test_heartbeat_default_board_refuses_before_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("policy refusal reached an effect")
    monkeypatch.setattr(panel, "default_matrix", forbidden)
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", forbidden)
    result = panel.invoke_board(DEFAULT_BOARD, "private input", monitoring_policy="heartbeat_only")
    assert len(result.legs) == len(DEFAULT_BOARD.seats)
    assert all(leg.status == "UNAVAILABLE" for leg in result.legs)
    assert all("gemini" in leg.detail for leg in result.legs)


@pytest.mark.parametrize("timeout", [0, -1, 1800, float("inf"), float("nan")])
def test_heartbeat_timeout_conflict_is_pure(timeout, monkeypatch):
    monkeypatch.setattr(panel, "default_matrix", lambda **kw: pytest.fail("availability probe"))
    result = panel.invoke_board(supported_board(), "input", monitoring_policy="heartbeat_only",
                                timeouts_by_leg={"codex": timeout})
    assert all(leg.status == "UNAVAILABLE" and "timeout" in leg.detail for leg in result.legs)


def test_resolved_policy_is_explicit():
    policy = backing.resolve_review_monitoring_policy("heartbeat_only", supported_board())
    assert policy.model_deadline_s is None
    assert policy.admission_window_s == 10
    assert policy.requested == policy.effective == "heartbeat_only"
    with pytest.raises(ValueError):
        backing.resolve_review_monitoring_policy("infinity", supported_board())


def test_silent_real_child_survives_old_deadline_and_stall(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "_LEG_LIVENESS_READ_INTERVAL_S", .02)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    result = panel._run_leg_with_liveness(
        [sys.executable, "-c", "import time; time.sleep(.35); print('complete')"],
        cwd=tmp_path, env=os.environ, deadline_s=.05, stall_threshold_s=.05,
        review_monitor=monitor,
    )
    assert result.returncode == 0
    assert result.stdout == "complete\n"
    record = json.loads(monitor.path.read_text())
    assert record["model_deadline_s"] is None
    assert record["effective_policy"] == "heartbeat_only"
    assert "complete" not in monitor.path.read_text()


def test_silent_real_child_cancellation_reaps_namespace(tmp_path):
    event = threading.Event()
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, event)
    timer = threading.Timer(.3, event.set)
    timer.start()
    try:
        result = panel._run_leg_with_liveness(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=tmp_path, env=os.environ, deadline_s=.05, stall_threshold_s=.05,
            review_monitor=monitor,
        )
    finally:
        timer.join()
    assert result.returncode != 0
    assert result.stderr == "review_operation_cancelled"
    assert json.loads(monitor.path.read_text())["terminal_reason"] == "user_cancel"


def test_heartbeat_tui_survives_silence(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "_latest_claude_transcript_text", lambda *a, **k: "")
    monkeypatch.setattr(panel, "_latest_claude_transcript_activity", lambda *a, **k: 0)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    result = panel._run_claude_tui_session(
        command=["sh", "-c", "sleep 1.3"], cwd=tmp_path, prompt="input",
        output_file=tmp_path / "absent", timeout_s=1, backstop_s=1,
        stall_threshold_s=.05, env=os.environ, review_monitor=monitor,
    )
    assert result[2] in ("claude_tui_missing_canonical_output", "claude_tui_pty_eof_no_output")


def test_cli_default_board_refuses_before_composition(tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli
    from phase_loop_runtime.advisor_board import composition
    monkeypatch.setattr(composition, "compose_review_board", lambda: pytest.fail("auth composition"))
    rc = cli._advisor_board_command(args=SimpleNamespace(
        artifact=str(tmp_path / "need-not-exist"), monitoring_policy="heartbeat_only", json=True,
    ))
    assert rc == 2
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "UNAVAILABLE"
    assert "gemini" in record["monitoring"]["diagnostic"]


def test_policy_bound_to_registered_lease(tmp_path):
    auth = backing.prepare_review_isolation_authorization(
        supported_board(), "input", mode="review", monitoring_policy="heartbeat_only",
    )
    object.__setattr__(auth, "monitoring_policy", "bounded")
    with pytest.raises(ValueError, match="policy_mismatch"):
        backing.revalidate_review_isolation_authorization(auth, None, "input", mode="review")


@contextmanager
def real_broker(tmp_path):
    board = supported_board()
    token = backing.set_review_instruction_digest("instructions")
    auth = backing.prepare_review_isolation_authorization(
        board, "input", mode="review", monitoring_policy="heartbeat_only",
    )
    backing.activate_review_isolation_authorization(auth, board, "input", mode="review")
    seat = board.seats[0]
    model = backing.harden_subscription_model(seat.harness, seat.model, seat.effort)
    leg = backing.derive_review_leg_authorization(
        auth, "input", harness=seat.harness, model=model, deadline_s=None,
        mode="review", canonical_repo_authority=Path.cwd(),
    )
    stage = tmp_path / "stage"
    stage.mkdir()
    for name, content in [("review-bundle.md", "input"), ("review-instructions.md", "instructions")]:
        path = stage / name
        path.write_text(content)
        path.chmod(0o400)
    broker = backing.ParentUnixBroker(leg, harness=seat.harness, model=model,
                                      staged_dir=stage, canonical_repo=Path.cwd())
    try:
        yield broker, auth
    finally:
        broker.close()
        backing.close_review_isolation_authorization(auth)
        backing.reset_review_instruction_digest(token)


def test_real_broker_admitted_response_outlives_expiry(tmp_path):
    with real_broker(tmp_path) as (broker, auth):
        active = threading.Event()
        def infer():
            active.set()
            # Only admission expires; an admitted response must remain owned.
            object.__setattr__(broker.authorization, "expires_monotonic_ns", time.monotonic_ns() - 1)
            time.sleep(.25)
            active.clear()
            return "OK", "review complete"
        adapter = backing._make_broker_inference_adapter(infer, active.clear, lambda: not active.is_set())
        result, evidence = broker.run_credentialless_client(adapter, deadline_s=None)
        assert result["status"] == "OK"
        assert evidence["operation_deadline_s"] is None
        assert evidence["child_quiescent"] and evidence["broker_thread_quiescent"]
        assert evidence["provider_adapter_quiescent"]
        assert not evidence["provider_cancel_requested"]


def test_real_broker_cancel_joins_provider_and_child(tmp_path):
    with real_broker(tmp_path) as (broker, auth):
        active = threading.Event()
        entered = threading.Event()
        cancelled = threading.Event()
        operation_cancel = threading.Event()
        def infer():
            active.set()
            entered.set()
            try:
                assert cancelled.wait(5), "test's emergency fixture bound"
                return "OK", "must not be usable"
            finally:
                active.clear()
        def cancel_when_entered():
            assert entered.wait(5)
            operation_cancel.set()
        canceller = threading.Thread(target=cancel_when_entered)
        canceller.start()
        adapter = backing._make_broker_inference_adapter(infer, cancelled.set, lambda: not active.is_set())
        try:
            with pytest.raises(ValueError, match="cancelled|closed|Broken pipe"):
                broker.run_credentialless_client(adapter, deadline_s=None, cancel_event=operation_cancel)
        finally:
            cancelled.set()
            canceller.join(5)
        assert not active.is_set()
        assert broker.evidence["child_quiescent"]
        assert broker.evidence["broker_thread_quiescent"]
        assert broker.evidence["provider_cancel_requested"]


def test_real_broker_expired_admission_never_invokes(tmp_path):
    with real_broker(tmp_path) as (broker, auth):
        object.__setattr__(broker.authorization, "expires_monotonic_ns", time.monotonic_ns() - 1)
        calls = []
        adapter = backing._make_broker_inference_adapter(
            lambda: (calls.append(True) or ("OK", "unexpected inference")), lambda: None, lambda: True,
        )
        with pytest.raises(ValueError, match="expired"):
            broker.run_credentialless_client(adapter, deadline_s=None)
        assert not calls


def test_owner_death_reaps_detached_descendant(tmp_path):
    marker = tmp_path / "descendant-host-pid"
    leader_marker = tmp_path / "provider-host-pid"
    # /proc remains the host mount, so stat exposes a host PID despite PID isolation.
    child_code = (
        "import os,time,pathlib; os.setsid(); "
        f"pathlib.Path({str(marker)!r}).write_text(pathlib.Path('/proc/self/stat').read_text().split()[0]); "
        "time.sleep(60)"
    )
    provider_code = (f"import subprocess,sys,time,pathlib; "
                     f"pathlib.Path({str(leader_marker)!r}).write_text(pathlib.Path('/proc/self/stat').read_text().split()[0]); "
                     f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)")
    owner_code = (
        "import os,sys,threading; from pathlib import Path; "
        "from phase_loop_runtime.panel_invoker import _ReviewMonitor,_run_leg_with_liveness; "
        f"m=_ReviewMonitor(Path({str(tmp_path / 'monitor.json')!r}),'test',0,threading.Event()); "
        f"_run_leg_with_liveness([sys.executable,'-c',{provider_code!r}],cwd='.',env=os.environ,deadline_s=1,review_monitor=m)"
    )
    owner = subprocess.Popen([sys.executable, "-c", owner_code], start_new_session=True)
    descendant = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            assert owner.poll() is None
            time.sleep(.02)
        assert marker.exists()
        descendant = int(marker.read_text())
        owner.kill()
        owner.wait(5)
        deadline = time.monotonic() + 5
        while Path(f"/proc/{descendant}").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert not Path(f"/proc/{descendant}").exists(), "descendant escaped owner loss"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(5)
        if descendant is not None and Path(f"/proc/{descendant}").exists():
            os.kill(descendant, signal.SIGKILL)
        if leader_marker.exists():
            leader = int(leader_marker.read_text())
            try: os.kill(leader, signal.SIGKILL)
            except ProcessLookupError: pass


@pytest.mark.parametrize("empty", [False, True])
def test_public_board_real_broker_and_fixture_cli(tmp_path, monkeypatch, empty):
    """No factory/spawn replacement: the fixture is an executable CLI on PATH."""
    script = tmp_path / "codex"
    count = tmp_path / "attempts"
    script.write_text(
        "#!/usr/bin/python3\nimport sys,time\nfrom pathlib import Path\n"
        "if 'exec' not in sys.argv: raise SystemExit(0)\n"
        f"with Path({str(count)!r}).open('a') as f: f.write('attempt\\n')\n"
        "sys.stdin.read()\ntime.sleep(.2)\n"
        + ("" if empty else "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('No blocking findings.\\nAGREE')\n")
    )
    script.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    seat = next(s for s in DEFAULT_BOARD.seats if s.harness == "codex")
    board = replace(DEFAULT_BOARD, seats=(seat, seat))
    result = panel.invoke_board(board, "synthetic review material", monitoring_policy="heartbeat_only",
                                stream_dir=tmp_path / "records")
    assert [leg.status for leg in result.legs] == (["EMPTY"] * 2 if empty else ["OK"] * 2), result
    assert count.read_text().splitlines() == ["attempt", "attempt"]
    records = sorted((tmp_path / "records").glob("*/seat-*.json"))
    assert len(records) == 2
    assert {json.loads(p.read_text())["seat_position"] for p in records} == {0, 1}
    for leg in result.legs:
        assert leg.review_monitoring["effective_policy"] == "heartbeat_only"
        assert leg.harden_isolation_evidence["operation_deadline_s"] is None
        assert leg.harden_isolation_evidence["cleanup_root_removed"]


def test_virtual_clock_crosses_multiple_old_backstops(tmp_path, monkeypatch):
    ticks = iter(range(0, 1000000, 2000))
    clock = SimpleNamespace(monotonic=lambda: next(ticks), sleep=time.sleep, time=time.time)
    monkeypatch.setattr(panel, "time", clock)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    result = panel._run_leg_with_liveness(
        [sys.executable, "-c", "import time; time.sleep(.1); print('done')"],
        cwd=tmp_path, env=os.environ, deadline_s=1800, stall_threshold_s=180,
        review_monitor=monitor,
    )
    assert result.returncode == 0 and result.stdout == "done\n"
    assert next(ticks) > 3 * 1800


@pytest.mark.parametrize("mutation", ["late_frame", "wrong_input", "wrong_route", "wrong_nonce", "closed_operation"])
def test_real_server_rejects_invalid_admission(tmp_path, mutation):
    with real_broker(tmp_path) as (broker, auth):
        errors = []
        calls = []
        adapter = backing._make_broker_inference_adapter(
            lambda: (calls.append(True) or ("OK", "result")), lambda: None, lambda: True,
        )
        request = {"schema": backing.PARENT_UNIX_BROKER_V1, "operation": auth.operation,
                   "nonce": broker.nonce, "harness": broker.harness, "model": broker.model,
                   "purpose": auth.purpose, "input_sha256": auth.input_sha256}
        if mutation == "wrong_input": request["input_sha256"] = "0" * 64
        if mutation == "wrong_route": request["model"] = "wrong"
        if mutation == "wrong_nonce": request["nonce"] = "wrong"
        if mutation == "late_frame":
            object.__setattr__(broker.authorization, "expires_monotonic_ns", time.monotonic_ns() + 150_000_000)
        def serve():
            try:
                broker.serve_once(adapter, expected_pid=os.getpid(), expected_start=broker._proc_stat(os.getpid())[1])
            except BaseException as exc:
                errors.append(exc)
        server = threading.Thread(target=serve)
        server.start()
        conn = socket.socket(socket.AF_UNIX)
        try:
            conn.connect(str(broker.path))
            payload = json.dumps(request).encode()
            conn.sendall(len(payload).to_bytes(4, "big") + payload[:1])
            if mutation == "late_frame":
                time.sleep(.2)
            if mutation == "closed_operation":
                backing.close_review_isolation_authorization(auth)
            try: conn.sendall(payload[1:])
            except BrokenPipeError: pass
            server.join(1)
            assert not server.is_alive()
            assert errors and not calls
        finally:
            conn.close()
            broker._wake_server()
            server.join(2)


def test_broker_leg_cannot_be_replayed_or_change_policy(tmp_path):
    with real_broker(tmp_path) as (broker, auth):
        with pytest.raises(ValueError, match="already consumed"):
            backing.ParentUnixBroker(broker.authorization, harness=broker.harness, model=broker.model,
                                     staged_dir=broker.staged_dir, canonical_repo=Path.cwd())
        object.__setattr__(broker.authorization, "monitoring_policy", "bounded")
        with pytest.raises(ValueError, match="policy_mismatch"):
            backing.ParentUnixBroker(broker.authorization, harness=broker.harness, model=broker.model,
                                     staged_dir=broker.staged_dir, canonical_repo=Path.cwd())


def test_early_namespace_child_exit_cancels_inference(tmp_path):
    with real_broker(tmp_path) as (broker, auth):
        active = threading.Event()
        cancelled = threading.Event()
        def infer():
            active.set()
            try:
                os.kill(broker.evidence["peer_pid"], signal.SIGKILL)
                assert cancelled.wait(5)
                return "OK", "late result must not become success"
            finally:
                active.clear()
        adapter = backing._make_broker_inference_adapter(infer, cancelled.set, lambda: not active.is_set())
        with pytest.raises(ValueError):
            broker.run_credentialless_client(adapter, deadline_s=None)
        assert cancelled.is_set() and not active.is_set()
        assert broker.evidence["broker_thread_quiescent"]
        assert broker.evidence["child_quiescent"]


def test_broker_launch_exception_leaves_no_server_thread(tmp_path, monkeypatch):
    with real_broker(tmp_path) as (broker, auth):
        before = set(threading.enumerate())
        adapter = backing._make_broker_inference_adapter(lambda: pytest.fail("inference"), lambda: None, lambda: True)
        def fail(*args, **kwargs): raise OSError("fixture launch failure")
        monkeypatch.setattr(backing.subprocess, "Popen", fail)
        with pytest.raises(OSError, match="fixture launch failure"):
            broker.run_credentialless_client(adapter, deadline_s=None)
        assert set(threading.enumerate()) == before
        assert broker.evidence["provider_adapter_quiescent"]


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_cancellation_joins_worker_and_child(tmp_path, signum):
    marker = tmp_path / "started"
    code = f'''
import os,sys,threading
from pathlib import Path
from phase_loop_runtime import panel_invoker as p
event=threading.Event()
monitor=p._ReviewMonitor(Path({str(tmp_path / 'monitor.json')!r}), 'test', 0, event)
def run(item):
    result=p._run_leg_with_liveness(
        [sys.executable, '-c', "from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(60)"],
        cwd='.', env=os.environ, deadline_s=1, review_monitor=monitor)
    return p.PanelLegResult('codex', 'DEGRADED', detail=result.stderr)
result=p._run_legs_ordered([0], run, cancel_event=event)
assert event.is_set() and result[0].detail == 'review_operation_cancelled'
'''
    owner = subprocess.Popen([sys.executable, "-c", code])
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            assert owner.poll() is None
            time.sleep(.02)
        assert marker.exists()
        owner.send_signal(signum)
        assert owner.wait(5) == 0
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(5)


def test_unproven_quiescence_is_fatal_not_usable(tmp_path):
    with real_broker(tmp_path) as (broker, auth):
        active = threading.Event()
        def infer():
            active.set()
            return "OK", "not a usable result"
        adapter = backing._make_broker_inference_adapter(infer, lambda: None, lambda: not active.is_set())
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError, match="quiescence unproven"):
            broker.run_credentialless_client(adapter, deadline_s=None)
        assert not broker.evidence["provider_adapter_quiescent"]


@pytest.mark.parametrize("overrides", [
    {"backing": "omnigent"}, {"auth": "api_key"}, {"host_leg": True},
    {"harness": "gemini"}, {"harness": "opencode"},
])
def test_unsupported_routes_refuse_before_factory(overrides, monkeypatch):
    seat = replace(supported_board().seats[0], **overrides)
    board = replace(DEFAULT_BOARD, seats=(seat,), allow_api_key_fallback=seat.auth == "api_key")
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", lambda *a, **k: pytest.fail("factory effect"))
    result = panel.invoke_board(board, "input", monitoring_policy="heartbeat_only")
    assert result.legs[0].status == "UNAVAILABLE"
    assert result.legs[0].review_monitoring["terminal_reason"] == "policy_refusal"


def test_monitor_write_failure_is_reported_and_child_reaped(tmp_path, monkeypatch):
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    # Exercise the real write failure after native launch, not a fake healthy record.
    monitor.path.parent.joinpath("monitor.tmp").mkdir()
    latch = panel._ProviderQuiescenceLatch()
    with pytest.raises(OSError):
        panel._run_leg_with_liveness(
            [sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path,
            env=os.environ, deadline_s=1, review_monitor=monitor, quiescence_latch=latch,
        )
    assert monitor.write_failed
    assert monitor.record["terminal_reason"] == "monitoring_write_failed"
    assert latch.is_quiescent()


def test_pre_cancelled_monitor_never_launches(tmp_path, monkeypatch):
    event = threading.Event()
    event.set()
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, event)
    monkeypatch.setattr(panel.subprocess, "Popen", lambda *a, **k: pytest.fail("cancelled launch"))
    with pytest.raises(panel._ReviewOperationCancelled):
        panel._run_leg_with_liveness(["no-provider"], cwd=tmp_path, env={}, deadline_s=1, review_monitor=monitor)


def test_completion_racing_cancel_cannot_be_success(tmp_path):
    with real_broker(tmp_path) as (broker, auth):
        event = threading.Event()
        def infer():
            event.set()
            return "OK", "result raced cancellation"
        adapter = backing._make_broker_inference_adapter(infer, lambda: None, lambda: True)
        with pytest.raises(ValueError, match="cancelled|closed"):
            broker.run_credentialless_client(adapter, deadline_s=None, cancel_event=event)


def test_child_reap_error_still_joins_and_records_cleanup(tmp_path, monkeypatch):
    with real_broker(tmp_path) as (broker, auth):
        event = threading.Event()
        original = subprocess.Popen.communicate
        failed = []
        def communicate(proc, *args, **kwargs):
            if kwargs.get("timeout") == 2 and not failed:
                failed.append(True)
                raise OSError("injected child reap error")
            return original(proc, *args, **kwargs)
        monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
        def infer():
            event.set()
            return "OK", "cancel raced completion"
        adapter = backing._make_broker_inference_adapter(infer, lambda: None, lambda: True)
        with pytest.raises(ValueError):
            broker.run_credentialless_client(adapter, deadline_s=None, cancel_event=event)
        assert failed
        assert broker.evidence["child_quiescent"]
        assert broker.evidence["broker_thread_quiescent"]
        assert broker.evidence["provider_adapter_quiescent"]
