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
    monkeypatch.setenv("PATH", "/missing-gemini-capability")
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
    completed = tmp_path / "native-completed"
    result = panel._run_claude_tui_session(
        command=[sys.executable, "-c", f"import time; from pathlib import Path; time.sleep(1.3); Path({str(completed)!r}).touch()"], cwd=tmp_path, prompt="input",
        output_file=tmp_path / "absent", timeout_s=1, backstop_s=1,
        stall_threshold_s=.05, env=os.environ, review_monitor=monitor,
    )
    assert result[2] in ("claude_tui_missing_canonical_output", "claude_tui_pty_eof_no_output")
    assert completed.exists(), "native child did not survive the old deadline and silence limits"


def test_cli_default_board_refuses_before_composition(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", "/missing-gemini-capability")
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
def real_broker(tmp_path, *, monitoring_policy="heartbeat_only"):
    board = supported_board()
    token = backing.set_review_instruction_digest("instructions")
    auth = backing.prepare_review_isolation_authorization(
        board, "input", mode="review", monitoring_policy=monitoring_policy,
    )
    backing.activate_review_isolation_authorization(auth, board, "input", mode="review")
    seat = board.seats[0]
    model = backing.harden_subscription_model(seat.harness, seat.model, seat.effort)
    leg = backing.derive_review_leg_authorization(
        auth, "input", harness=seat.harness, model=model,
        deadline_s=None if monitoring_policy == "heartbeat_only" else 1800,
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


@pytest.mark.parametrize("policy", ["heartbeat_only", "bounded"])
def test_real_broker_wait_crosses_old_deadline_after_admission(tmp_path, monkeypatch, policy):
    elapsed = 0
    active = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    response_polls = []
    clock = SimpleNamespace(**{name: getattr(time, name) for name in dir(time)})
    clock.monotonic = lambda: time.monotonic() + elapsed
    monkeypatch.setattr(backing, "time", clock)
    operation_active = backing._leg_operation_active

    def observe_response_poll(authorization):
        owned = operation_active(authorization)
        if active.is_set():
            response_polls.append(elapsed)
            if len(response_polls) >= 2:
                release.set()
        return owned

    monkeypatch.setattr(backing, "_leg_operation_active", observe_response_poll)
    with real_broker(tmp_path, monitoring_policy=policy) as (broker, auth):
        def infer():
            nonlocal elapsed
            # The real server has authenticated and consumed the request before invoke.
            assert broker._used
            elapsed = 4 * 1800
            active.set()
            try:
                assert release.wait(5), "real broker never resumed its response wait"
                return "OK", "admitted response completed"
            finally:
                active.clear()

        def cancel():
            cancelled.set()
            release.set()

        adapter = backing._make_broker_inference_adapter(infer, cancel, lambda: not active.is_set())
        if policy == "heartbeat_only":
            result, evidence = broker.run_credentialless_client(adapter, deadline_s=None)
            assert result == {"schema": backing.PARENT_UNIX_BROKER_V1,
                              "status": "OK", "text": "admitted response completed"}
            assert len(response_polls) >= 2 and min(response_polls) > 1800
            assert evidence["operation_deadline_s"] is None
            assert not evidence["child_timeout"] and not cancelled.is_set()
        else:
            with pytest.raises(ValueError, match="credentialless broker client failed"):
                broker.run_credentialless_client(adapter, deadline_s=1800)
            assert response_polls and response_polls[0] > 1800
            assert broker.evidence["child_timeout"] and cancelled.is_set()
        assert all(broker.evidence[key] for key in (
            "child_quiescent", "broker_thread_quiescent", "provider_adapter_quiescent",
        ))


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
    # /proc inside the owner is the namespace's own procfs (agent-harness#1003): each process
    # records its namespace link and local PID, and the host PID is resolved from outside.
    child_code = (
        "import os,time,pathlib; os.setsid(); "
        f"pathlib.Path({str(marker)!r}).write_text(os.readlink('/proc/self/ns/pid')+' '+str(os.getpid())); "
        "time.sleep(60)"
    )
    provider_code = (f"import os,subprocess,sys,time,pathlib; "
                     f"pathlib.Path({str(leader_marker)!r}).write_text(os.readlink('/proc/self/ns/pid')+' '+str(os.getpid())); "
                     f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)")
    owner_code = (
        "import os,sys,threading; from pathlib import Path; "
        "from phase_loop_runtime.panel_invoker import _ReviewMonitor,_run_leg_with_liveness; "
        f"m=_ReviewMonitor(Path({str(tmp_path / 'monitor.json')!r}),'test',0,threading.Event()); "
        f"_run_leg_with_liveness([sys.executable,'-c',{provider_code!r}],cwd='.',env=os.environ,deadline_s=1,review_monitor=m)"
    )
    owner = subprocess.Popen([sys.executable, "-c", owner_code], start_new_session=True)
    descendant = None
    leader = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            assert owner.poll() is None
            time.sleep(.02)
        assert marker.exists()
        descendant = _host_pid(marker.read_text())
        # Resolve the leader NOW, while its namespace is alive: after owner loss a
        # (namespace inode, local PID) pair can be reused by another test's process.
        if leader_marker.exists():
            leader = _host_pid(leader_marker.read_text())
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
        if leader is not None:
            try: os.kill(leader, signal.SIGKILL)
            except ProcessLookupError: pass


@pytest.mark.parametrize("empty,cancelled", [(False, False), (True, False), (False, True)])
def test_public_board_real_broker_and_fixture_cli(tmp_path, monkeypatch, empty, cancelled):
    """No factory/spawn replacement: the fixture is an executable CLI on PATH."""
    from phase_loop_runtime import sandbox_egress
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
    isolated_network = sandbox_egress.isolated_network
    @contextmanager
    def owned_network(*args, **kwargs):
        assert kwargs["timeout_s"] is None, "heartbeat network still has a wall-clock expiry"
        with isolated_network(*args, **kwargs) as prefix:
            yield prefix
    monkeypatch.setattr(sandbox_egress, "isolated_network", owned_network)
    script = tmp_path / "codex"
    count = tmp_path / "attempts"
    script.write_text(
        "#!/usr/bin/python3\nimport sys,time\nfrom pathlib import Path\n"
        "if 'exec' not in sys.argv: raise SystemExit(0)\n"
        "caps = next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapBnd:'))\n"
        # agent-harness#1003: a SANDBOXED codex seat keeps exactly CAP_SETFCAP (bit 31) so
        # codex's own bubblewrap can start; nothing else, and never NET_ADMIN (bit 12). The
        # fixture board stages a tree, so this seat is sandboxed. An EMPTY set also passes.
        "assert int(caps, 16) & ~(1 << 31) == 0, 'provider can regain firewall capabilities'\n"
        f"with Path({str(count)!r}).open('a') as f: f.write('attempt\\n')\n"
        f"sys.stdin.read()\ntime.sleep({60 if cancelled else .2})\n"
        + ("" if empty else "Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('No blocking findings.\\nAGREE')\n")
    )
    script.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    seat = next(s for s in DEFAULT_BOARD.seats if s.harness == "codex")
    board = replace(DEFAULT_BOARD, seats=(seat, seat))
    cancel = threading.Event()
    def cancel_after_launch():
        deadline = time.monotonic() + 75  # finite fixture startup, no model request
        while not cancel.is_set():
            if count.exists() and len(count.read_text().splitlines()) == 2:
                cancel.set()
                return
            assert time.monotonic() < deadline, "fixture providers did not start"
            time.sleep(.02)
    controller = threading.Thread(target=cancel_after_launch) if cancelled else None
    if controller is not None:
        controller.start()
    try:
        result = panel.invoke_board(board, "synthetic review material", monitoring_policy="heartbeat_only",
                                    stream_dir=tmp_path / "records", cancel_event=cancel, gateway_available=False)
    finally:
        if controller is not None:
            cancel.set()
            controller.join(5)
    expected = "UNAVAILABLE" if cancelled else "EMPTY" if empty else "OK"
    assert [leg.status for leg in result.legs] == [expected] * 2, result
    assert count.read_text().splitlines() == ["attempt", "attempt"]
    records = sorted((tmp_path / "records").glob("*/seat-*.json"))
    assert len(records) == 2
    assert {json.loads(p.read_text())["seat_position"] for p in records} == {0, 1}
    for leg in result.legs:
        assert leg.review_monitoring["effective_policy"] == "heartbeat_only"
        assert leg.harden_isolation_evidence["operation_deadline_s"] is None
        assert leg.harden_isolation_evidence["cleanup_root_removed"]
        assert leg.harden_isolation_evidence["sandbox_network_filtered"] is True
        if cancelled:
            assert leg.review_monitoring["terminal_reason"] == "user_cancel"
            assert all(leg.harden_isolation_evidence[key] for key in (
                "child_quiescent", "broker_thread_quiescent", "provider_adapter_quiescent",
                "host_secret_probe_removed",
            ))


def test_virtual_clock_crosses_multiple_old_backstops(tmp_path, monkeypatch):
    elapsed = 0
    clock = SimpleNamespace(monotonic=lambda: time.monotonic() + elapsed,
                            sleep=time.sleep, time=time.time)
    monkeypatch.setattr(panel, "time", clock)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    release = tmp_path / "release"
    observe = monitor.observe

    def advance_past_backstops(*args, **kwargs):
        nonlocal elapsed
        if not elapsed:
            # Advance the active leg, then let cleanup grace use real elapsed time.
            elapsed = 4 * 1800
            release.touch()
        observe(*args, **kwargs)

    monkeypatch.setattr(monitor, "observe", advance_past_backstops)
    result = panel._run_leg_with_liveness(
        [sys.executable, "-c",
         "import sys,time; from pathlib import Path; "
         "release=Path(sys.argv[1]);\n"
         "while not release.exists(): time.sleep(.01)\n"
         "print('done')", str(release)],
        cwd=tmp_path, env=os.environ, deadline_s=1800, stall_threshold_s=180,
        review_monitor=monitor,
    )
    assert result.returncode == 0 and result.stdout == "done\n"
    assert elapsed > 3 * 1800


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


def test_owner_wrapper_provides_native_runtime_random_device(tmp_path):
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    result = panel._run_leg_with_liveness(
        [sys.executable, "-c", "assert len(open('/dev/urandom', 'rb').read(1)) == 1; print('ready')"],
        cwd=tmp_path, env=os.environ, deadline_s=1, review_monitor=monitor,
    )
    assert result.returncode == 0
    assert result.stdout == "ready\n"


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


@pytest.mark.parametrize("explicit", [False, True])
def test_valid_heartbeat_authority_cannot_enter_bounded_invocation(monkeypatch, explicit):
    board = supported_board()
    auth = backing.prepare_review_isolation_authorization(
        board, "input", mode="review", monitoring_policy="heartbeat_only",
    )
    monkeypatch.setattr(panel, "_resolve_artifact", lambda *a: pytest.fail("artifact effect"))
    try:
        result = panel.invoke_board(board, "input", review_authorization=auth,
                                    **({"monitoring_policy": "bounded"} if explicit else {}))
        assert all(leg.status == "UNAVAILABLE" for leg in result.legs)
        assert all("policy_mismatch" in leg.detail for leg in result.legs)
    finally:
        backing.close_review_isolation_authorization(auth)


def test_nonstreaming_fatal_worker_cancels_silent_first_seat():
    cancel = threading.Event()
    entered = threading.Event()
    emergency = threading.Event()
    timer = threading.Timer(2, lambda: (emergency.set(), cancel.set()))
    timer.start()
    def run_one(position):
        if position == 0:
            entered.set()
            cancel.wait()
            return panel.PanelLegResult('codex', 'DEGRADED')
        assert entered.wait(1)
        raise panel.ProviderProcessGroupQuiescenceError("fatal second seat")
    try:
        with pytest.raises(panel.ProviderProcessGroupQuiescenceError, match="fatal second seat"):
            panel._run_legs_ordered([0, 1], run_one, cancel_event=cancel)
        assert cancel.is_set()
        assert not emergency.is_set(), "fatal error was hidden behind silent first future"
    finally:
        timer.cancel()
        timer.join()


@pytest.mark.parametrize("tui", [False, True])
def test_real_output_is_observed_then_silence_is_unknown(tmp_path, monkeypatch, tui):
    monkeypatch.setattr(panel, "_LEG_LIVENESS_READ_INTERVAL_S", .05)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READ_INTERVAL_S", .02)
    monkeypatch.setattr(panel, "_latest_claude_transcript_text", lambda *a, **k: "")
    monkeypatch.setattr(panel, "_latest_claude_transcript_activity", lambda *a, **k: 0)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    snapshots = []
    observe = monitor.observe
    release = tmp_path / "silence-observed"
    progress_seen = False

    def capture(*args, **kwargs):
        nonlocal progress_seen
        observe(*args, **kwargs)
        row = json.loads(monitor.path.read_text())
        snapshots.append(row)
        if row["observation_state"] == "progress_observed":
            progress_seen = True
        elif (progress_seen and row["last_genuine_progress_age_s"] is not None
              and row["last_genuine_progress_age_s"] > .05):
            release.touch()

    monkeypatch.setattr(monitor, "observe", capture)
    command = [sys.executable, "-c",
               "import time\nfrom pathlib import Path\n"
               "print('Reviewing substantive section alpha', flush=True)\n"
               f"while not Path({str(release)!r}).exists():\n"
               " time.sleep(.01)\n"]
    # Keep the real child alive until both observations exist. A fixed sleep can
    # end before a loaded runner observes silence after draining the final output.
    emergency = threading.Timer(5, monitor.cancel.set)
    emergency.start()
    result = None
    try:
        if tui:
            panel._run_claude_tui_session(command=command, cwd=tmp_path, prompt="input",
                output_file=tmp_path / "absent", timeout_s=1, backstop_s=1,
                env=os.environ, review_monitor=monitor)
        else:
            result = panel._run_leg_with_liveness(command, cwd=tmp_path, env=os.environ,
                                                 deadline_s=1, review_monitor=monitor)
    finally:
        emergency.cancel()
        emergency.join()
    observed = [i for i, row in enumerate(snapshots) if row["observation_state"] == "progress_observed"]
    assert observed, "real genuine output was never reported as observed"
    assert any(snapshots[i]["last_genuine_progress_age_s"] > 0 for i in observed)
    assert any(row["observation_state"] == "progress_unobserved"
               and row["last_genuine_progress_age_s"] is not None
               and row["last_genuine_progress_age_s"] > .05
               for row in snapshots[observed[-1] + 1:]), "silence stayed labelled as progress"
    assert not monitor.cancel.is_set(), "test fixture's emergency cancellation fired"
    if result is not None:
        assert result.returncode == 0


def test_tui_repaints_are_not_novel_content():
    """Deterministic core of agent-harness#1034: only the FIRST status frame is novel;
    timer repaints (one by one or in one burst) never are, while real text still is."""
    frames = [("\r\x1b[2K* Herding... (%ss . esc to interrupt)\r" % i).encode() for i in range(9)]
    seen: set[str] = set()
    assert panel._tui_chunk_has_novel_content(frames[0], seen)
    assert not any(panel._tui_chunk_has_novel_content(frame, seen) for frame in frames[1:5])
    assert not panel._tui_chunk_has_novel_content(b"".join(frames[5:]), seen)
    assert panel._tui_chunk_has_novel_content(b"a genuinely new review sentence\n", seen)


def test_tui_animation_does_not_keep_progress_observed(tmp_path, monkeypatch):
    """End to end, synchronized rather than timed (agent-harness#1034, #1045 r1).

    The child prints one CR-terminated status frame and WAITS for `go`, which the
    observe hook creates only once the monitor has held that frame as progress for
    0.1 s. The child then repaints and waits for `done`, created 0.3 s after `go`.
    Correct: the age keeps growing from the first frame and never drops. Broken (repaints
    refresh progress): the age drops from >= 0.1 s back to ~0."""
    monkeypatch.setattr(panel, "_LEG_LIVENESS_READ_INTERVAL_S", .05)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READ_INTERVAL_S", .02)
    monkeypatch.setattr(panel, "_latest_claude_transcript_text", lambda *a, **k: "")
    monkeypatch.setattr(panel, "_latest_claude_transcript_activity", lambda *a, **k: 0)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    go, done = tmp_path / "go", tmp_path / "done"
    snapshots = []
    released = []
    judged_last_repaint = []
    judged = bytearray()
    last = 8  # the child repaints frames 1..last
    observe = monitor.observe
    novel = panel._tui_chunk_has_novel_content

    def judging(chunk, seen, *rest):
        # `done` waits until the LAST repaint has been judged -- recorded AFTER the
        # detector returns, and matched across all judged text so a frame split over
        # chunks still counts -- not on elapsed time (#1047, #1048 r1).
        verdict = novel(chunk, seen, *rest)
        judged.extend(chunk)
        # The WHOLE last frame, not just its timer prefix (agent-harness#1053).
        if f"* Herding... ({last}s . esc to interrupt)\r".encode() in judged:
            judged_last_repaint.append(True)
        return verdict

    monkeypatch.setattr(panel, "_tui_chunk_has_novel_content", judging)

    def capture(*args, **kwargs):
        observe(*args, **kwargs)
        snapshots.append(dict(monitor.record))
        age = monitor.record["last_genuine_progress_age_s"]
        if not go.exists() and age is not None and age >= .1:
            released.append(time.monotonic())
            go.touch()
        elif (released and judged_last_repaint and not done.exists()
              and time.monotonic() - released[0] >= .3):
            done.touch()

    monkeypatch.setattr(monitor, "observe", capture)
    result = panel._run_claude_tui_session(
        command=[sys.executable, "-c",
                 "import os, sys, time\n"
                 "line = '\\r\\x1b[2K* Herding... (%ss . esc to interrupt)\\r'\n"
                 "go, done = sys.argv[1], sys.argv[2]\n"
                 # The session loop does not enforce timeout_s while a review monitor is
                 # attached (#1045 president), so the child bounds its own waits: a broken
                 # handshake exits in 10 s and fails `released`/`done` below, never hangs CI.
                 "deadline = time.monotonic() + 10\n"
                 # Distinct exit codes name the stage that broke (#1047): 3 = go, 4 = done.
                 "def wait(path, code):\n"
                 " while not os.path.exists(path):\n"
                 "  if time.monotonic() > deadline: sys.exit(code)\n"
                 "  time.sleep(.01)\n"
                 "print(line % 0, end='', flush=True)\n"
                 "wait(go, 3)\n"
                 f"for i in range(1, {last + 1}): print(line % i, end='', flush=True)\n"
                 "wait(done, 4)\n",
                 str(go), str(done)],
        cwd=tmp_path, prompt="input", output_file=tmp_path / "absent",
        timeout_s=15, env=os.environ, review_monitor=monitor,  # not enforced; see the child
    )
    assert released, f"go never released (child exit {result[0]}; 3 = waited for go)"
    assert judged_last_repaint and done.exists(), f"repaints never judged (child exit {result[0]}; 4 = waited for done)"
    ages = [s["last_genuine_progress_age_s"] for s in snapshots
            if s["last_genuine_progress_age_s"] is not None]
    assert all(later >= earlier for earlier, later in zip(ages, ages[1:])), ages
    assert snapshots[-1]["observation_state"] == "progress_unobserved"
    # Not an absolute threshold: a terminal observe() carries the PREVIOUS age forward, so
    # under CI load the final age can lag wall time (agent-harness#1060 CI: 0.16 s). What
    # the handshake guarantees is that it never fell below the 0.1 s that released `go`;
    # with the monotonic check above, a refreshing repaint (age back to ~0) still fails.
    assert snapshots[-1]["last_genuine_progress_age_s"] >= .1, ages


def test_cpu_activity_is_not_reported_as_genuine_output(tmp_path, monkeypatch):
    import itertools
    ticks = itertools.count()
    monkeypatch.setattr(panel, "group_cpu_ticks", lambda pid: next(ticks))
    monkeypatch.setattr(panel, "_LEG_LIVENESS_CPU_SAMPLE_S", .01)
    monkeypatch.setattr(panel, "_LEG_LIVENESS_READ_INTERVAL_S", .01)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    result = panel._run_leg_with_liveness(
        [sys.executable, "-c", "import time; time.sleep(.2)"],
        cwd=tmp_path, env=os.environ, deadline_s=1, review_monitor=monitor,
    )
    assert result.returncode == 0
    assert monitor.record["last_genuine_progress_age_s"] is None
    assert monitor.record["observation_state"] == "progress_unobserved"


@pytest.mark.parametrize("tui", [False, True])
def test_heartbeat_launch_executes_prefix_and_provider(tmp_path, tui):
    marker = tmp_path / "prefix-ran"
    completed = tmp_path / "provider-ran"
    prefix = ("/bin/sh", "-c", f'echo ran > {marker}; exec "$@"', "--")
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(completed)!r}).touch()"]
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "test", 0, threading.Event())
    token = panel._EGRESS_LAUNCH_PREFIX.set(prefix)
    try:
        if tui:
            panel._run_claude_tui_session(command=command, cwd=tmp_path, prompt="input",
                output_file=tmp_path / "absent", timeout_s=1, backstop_s=1,
                env=os.environ, review_monitor=monitor)
        else:
            result = panel._run_leg_with_liveness(command, cwd=tmp_path, env=os.environ,
                                                  deadline_s=1, review_monitor=monitor)
            assert result.returncode == 0
        assert marker.exists() and completed.exists()
    finally:
        panel._EGRESS_LAUNCH_PREFIX.reset(token)


@pytest.mark.parametrize("abrupt", [False, True])
def test_heartbeat_network_helpers_end_with_owner(tmp_path, abrupt):
    ready = tmp_path / "helpers.json"
    code = (
        "import json,os,sys; from pathlib import Path; "
        "from phase_loop_runtime.sandbox_egress import isolated_network\n"
        "with isolated_network(timeout_s=None) as prefix:\n"
        " children=Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()\n"
        f" Path({str(ready)!r}).write_text(json.dumps(children))\n"
        " sys.stdin.read(1)\n"
    )
    owner = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE)
    children = []
    try:
        deadline = time.monotonic() + 75  # bounded local namespace/DNS setup, no model
        while not ready.exists() and time.monotonic() < deadline:
            assert owner.poll() is None, "network setup failed"
            time.sleep(.02)
        assert ready.exists()
        children = json.loads(ready.read_text())
        assert len(children) == 2
        commands = [Path(f"/proc/{pid}/cmdline").read_bytes() for pid in children]
        assert any(b"read -r _owner_lifetime" in cmd for cmd in commands)
        assert any(b"--exit-fd=" in cmd for cmd in commands)
        assert all(b"sleep " not in cmd for cmd in commands)
        if abrupt:
            owner.kill()
            owner.wait(5)
        else:
            owner.communicate(b"x", timeout=10)
            assert owner.returncode == 0
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            alive = []
            for pid in children:
                try:
                    state = Path(f"/proc/{pid}/stat").read_text().split()[2]
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if state != "Z":
                    alive.append(pid)
            if not alive:
                break
            time.sleep(.02)
        assert not alive, "network helper outlived its owner"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=5)
        for pid in children:
            try: os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError: pass


def test_heartbeat_egress_unavailable_stays_degraded(tmp_path, monkeypatch):
    from phase_loop_runtime import sandbox_egress
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)
    result = panel.invoke_board(supported_board(), "synthetic review material",
        monitoring_policy="heartbeat_only", stream_dir=tmp_path / "records")
    assert all(leg.status == "DEGRADED" for leg in result.legs)
    assert all("egress isolation unavailable" in leg.detail for leg in result.legs)
    assert all(not leg.text for leg in result.legs)
    assert all(not (leg.harden_isolation_evidence or {}).get("sandbox_network_filtered") for leg in result.legs)


def test_bounded_broker_expiry_returns_leg_after_successful_cleanup(tmp_path, monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
    receipts = []
    close = backing.ParentUnixBroker.close
    def record_close(broker):
        close(broker)
        receipts.append(dict(broker.evidence))
    monkeypatch.setattr(backing.ParentUnixBroker, "close", record_close)
    script = tmp_path / "codex"
    marker = tmp_path / "provider-pid"
    # Expire only the aggregate clock, after the real fixture has launched.
    clock_origin = time.monotonic()
    monkeypatch.setattr(backing, "time", SimpleNamespace(
        monotonic=lambda: clock_origin + (4.0 if marker.exists() else 0.0),
        monotonic_ns=time.monotonic_ns,
    ))
    script.write_text(
        "#!/usr/bin/python3\nimport sys,time\nfrom pathlib import Path\n"
        "if 'exec' not in sys.argv: raise SystemExit(0)\n"
        f"Path({str(marker)!r}).write_text(Path('/proc/self/stat').read_text().split()[0])\n"
        "sys.stdin.read()\ntime.sleep(60)\n"
    )
    script.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    seat = next(s for s in DEFAULT_BOARD.seats if s.harness == "codex")
    board = replace(DEFAULT_BOARD, seats=(seat,))
    result = panel.invoke_board(board, "fixture bounded expiry", timeouts_by_leg={"codex": 1},
        stream_dir=tmp_path / "records", review_policy=panel.ReviewLandingPolicy(("sol",), False))
    assert marker.exists(), "fixture never reached provider launch"
    assert len(result.legs) == 1
    assert result.legs[0].status == "DEGRADED"
    assert not Path("/proc/" + marker.read_text()).exists()
    assert len(receipts) == 1
    evidence = receipts[0]
    assert evidence["child_quiescent"] and evidence["broker_thread_quiescent"]
    assert evidence["provider_adapter_quiescent"] and evidence["cleanup_root_removed"]
    assert evidence["child_timeout"] and evidence["provider_cancel_requested"]


def test_heartbeat_explicit_gateway_refuses_before_effects(monkeypatch):
    monkeypatch.setattr(panel, "default_matrix", lambda **kw: pytest.fail("availability probe"))
    result = panel.invoke_board(supported_board(), "input", monitoring_policy="heartbeat_only",
                                gateway_available=True)
    assert all(leg.status == "UNAVAILABLE" and
               leg.detail == "review_monitoring_unsupported_transport" for leg in result.legs)


@pytest.mark.parametrize("route", ["popen", "owned", "run"])
def test_real_namespace_launch_preserves_requested_cwd(tmp_path, route):
    from phase_loop_runtime.sandbox_egress import isolated_network

    cwd = tmp_path / "seat with spaces"
    cwd.mkdir()
    command = [sys.executable, "-c",
        "import json,os; from pathlib import Path; "
        "print(json.dumps({'cwd':os.getcwd(),'caps':next(x.split()[1] "
        "for x in Path('/proc/self/status').read_text().splitlines() "
        "if x.startswith('CapBnd:'))}))"]
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "cwd-binding", 0, threading.Event())
    with isolated_network(timeout_s=None) as prefix:
        token = panel._EGRESS_LAUNCH_PREFIX.set(prefix)
        try:
            if route == "run":
                result = panel.run_provider(command, cwd=cwd, env=os.environ,
                                            capture_output=True, text=True, timeout=10)
                assert result.returncode == 0, result.stderr
                output = result.stdout
            else:
                proc = panel.launch_provider(command, cwd=cwd, env=os.environ,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    process_owner=monitor.owned_command(()) if route == "owned" else ())
                output, error = proc.communicate(timeout=10)
                assert proc.returncode == 0, error
            record = json.loads(output)
            assert record["cwd"] == str(cwd)
            assert int(record["caps"], 16) == 0
        finally:
            panel._EGRESS_LAUNCH_PREFIX.reset(token)


# --- agent-harness#908 board round 4, finding (f): the provider's cwd is re-established INSIDE the
# namespace by PATH. `nsenter --wd` fchdir()ed to a dentry opened in the caller's mount namespace,
# which a provider that canonicalises its cwd (codex's own sandbox) cannot resolve -- the real
# codex CLI exited 1 with "No such file or directory (os error 2)" before any inference, and
# completed a review once the chdir became a path lookup after nsenter/setpriv. A plain nested
# user+mount namespace inside the holder does NOT reproduce the failure (the fchdir()ed cwd is
# still reachable there; board r5, native seat), so the class needs the provider's own sandbox
# and the real-CLI receipt lives with the PR evidence. This control pins the launch shape the
# receipt was taken with, so the fchdir form cannot silently return.
def test_launch_prefix_chdirs_by_path_inside_the_namespace(tmp_path):
    cwd = tmp_path / "seat with spaces"
    cwd.mkdir()
    prefix = ("nsenter", "--net", "--mount", "-t", "1", "-U", "--preserve-credentials",
              "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--")
    token = panel._EGRESS_LAUNCH_PREFIX.set(prefix)
    try:
        composed = panel._provider_launch_prefix(cwd)
    finally:
        panel._EGRESS_LAUNCH_PREFIX.reset(token)
    assert composed[:len(prefix)] == list(prefix), "the egress prefix is preserved verbatim"
    assert composed[len(prefix):] == ["/usr/bin/env", "--chdir=" + str(cwd.resolve()), "--"], (
        "the chdir runs AFTER nsenter and setpriv, by path, in the namespace the provider lives in"
    )
    assert not any(str(item).startswith("--wd") for item in composed), (
        "nsenter --wd fchdir()s to an outer-namespace dentry; a canonicalising provider sees "
        "'(unreachable)' and exits with ENOENT"
    )
    # no prefix -> no chdir wrapper either (the plain Popen cwd applies)
    token = panel._EGRESS_LAUNCH_PREFIX.set(())
    try:
        assert panel._provider_launch_prefix(cwd) == []
    finally:
        panel._EGRESS_LAUNCH_PREFIX.reset(token)


# --- agent-harness#908 board round 4, finding (d): a native leg fill (EC-REVIEWTRUTH-14) is a route
# heartbeat-only excludes ("no native host seat", CONTRACTS.md review monitoring policy v1). It is
# refused by the whole-board preflight, before minting, composition effects or any launch, so a
# valid fill can never be bound as a usable OK under the policy. Bounded keeps the fill.
def test_policy_preflight_refuses_a_native_fill_under_heartbeat_only():
    with pytest.raises(ValueError, match="review_monitoring_unsupported_route:native_fill"):
        backing.resolve_review_monitoring_policy("heartbeat_only", supported_board(), native_fill_requested=True)
    policy = backing.resolve_review_monitoring_policy("bounded", supported_board(), native_fill_requested=True)
    assert policy.requested == policy.effective == "bounded"


def test_production_invoker_refuses_a_valid_native_fill_under_heartbeat_only(tmp_path, monkeypatch):
    """The seat's reproduction: production invoke_board, a fill BOUND to the real digests. Under
    heartbeat_only the whole-board preflight refuses before ANY effect (no availability probe, no
    authorization minting, no launch): every leg UNAVAILABLE with the typed route refusal."""
    from test_native_claude_seat_fill import CC, _bound_fill, _typed_deferral_spawn
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    board = supported_board()
    seat = next(s for s in board.seats if s.harness == "claude")
    fill = _bound_fill(panel.NativeLegFill, board, seat, artifact.read_text())
    def forbidden(*args, **kwargs):
        pytest.fail("policy refusal reached an effect")
    monkeypatch.setattr(panel, "default_matrix", forbidden)
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization", forbidden)
    monkeypatch.setattr(panel, "launch_provider", forbidden)
    monkeypatch.setattr(panel, "run_provider", forbidden)
    result = panel.invoke_board(
        board, "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path),
        base_env=dict(CC), native_leg_fills=[fill], monitoring_policy="heartbeat_only",
    )
    assert len(result.legs) == len(board.seats) and not result.usable_legs
    assert all(leg.status == "UNAVAILABLE" for leg in result.legs)
    assert all("review_monitoring_unsupported_route:native_fill" in (leg.detail or "") for leg in result.legs)
    assert all(getattr(leg, "_review_monitoring", {}).get("terminal_reason") == "policy_refusal" for leg in result.legs)


def test_bounded_policy_still_binds_a_valid_native_fill(tmp_path, monkeypatch):
    """Control: the same bound fill under the default bounded policy binds as before (EC-REVIEWTRUTH-14),
    so the refusal keys on the policy alone and bounded native-fill behaviour is preserved."""
    from harden_tdd_guard import invoke_sanctioned_review_transport
    from test_native_claude_seat_fill import CC, _bound_fill, _typed_deferral_spawn
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    board = supported_board()
    seat = next(s for s in board.seats if s.harness == "claude")
    fill = _bound_fill(panel.NativeLegFill, board, seat, artifact.read_text())
    result = invoke_sanctioned_review_transport(
        board, "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path),
        base_env=dict(CC), native_leg_fills=[fill],
    )
    claude = next(leg for leg in result.legs if leg.leg == "claude")
    assert claude.status == "OK" and claude.usable and claude.detail == "native_fill"


def test_cli_refuses_native_leg_with_heartbeat_only_before_loading_the_fill(tmp_path, monkeypatch, capsys):
    from phase_loop_runtime import cli
    from phase_loop_runtime.advisor_board import composition
    monkeypatch.setattr(composition, "compose_review_board", lambda: pytest.fail("auth composition"))
    monkeypatch.setattr(panel, "load_native_leg_fills", lambda spec: pytest.fail("the fill was loaded"))
    rc = cli._advisor_board_command(args=SimpleNamespace(
        artifact=str(tmp_path / "need-not-exist"), monitoring_policy="heartbeat_only", json=True,
        native_legs=["claude=" + str(tmp_path / "absent")],
    ))
    assert rc == 2
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "UNAVAILABLE" and record["monitoring"]["terminal_reason"] == "policy_refusal"
    assert "native_fill" in record["monitoring"]["diagnostic"]


def _host_pid(record: str, timeout_s: float = 5.0) -> int:
    """Host PID for a ``"<pid-namespace link> <namespace-local pid>"`` record.

    Inside the owner wrapper /proc is the namespace's OWN procfs (agent-harness#1003), so a
    process can only report its namespace-local PID; the host PID is resolved from outside
    through the host /proc (the process whose pid namespace matches and whose innermost
    ``NSpid`` is that PID).
    """
    link, local = record.split()
    deadline = time.monotonic() + timeout_s
    while True:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                if os.readlink(f"/proc/{entry}/ns/pid") != link:
                    continue
                nspid = next(line for line in Path(f"/proc/{entry}/status").read_text().splitlines()
                             if line.startswith("NSpid:"))
            except (OSError, StopIteration):
                continue
            if nspid.split()[-1] == local:
                return int(entry)
        if time.monotonic() >= deadline:
            raise AssertionError(f"no host process for {record!r}")
        time.sleep(.02)
