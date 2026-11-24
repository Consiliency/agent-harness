"""Clock boundaries exercised without waiting for a real reservation to expire."""

from types import SimpleNamespace

import pytest

from test_launch_service import launch_tmp_path as _launch_tmp_path

launch_tmp_path = _launch_tmp_path


@pytest.mark.parametrize("confirm", [False, True])
def test_unconfirmed_renewals_retry_until_absolute_fence(confirm):
    from phase_loop_runtime.launch_lifetime import LaunchLifetime

    now = [100.0]
    transactions = []
    fences = []

    class Stop:
        def is_set(self):
            return len(transactions) >= 2 and confirm

        def wait(self, seconds):
            assert len(transactions) < 20, "renewal retried beyond its original cutoff"
            now[0] += seconds
            return self.is_set()

    def renew(*key, deadline):
        transactions.append((now[0], deadline))
        if confirm:
            return len(transactions) == 2
        now[0] = min(now[0] + 4, deadline)
        return False

    def fence(*key, cause, deadline):
        fences.append((now[0], cause, deadline))
        return True

    lifetime = LaunchLifetime("f" * 32, 60, now[0], 7, 12, lambda: now[0])
    lifetime.started()
    life = SimpleNamespace(renew_launch=renew, fence_launch=fence)
    loss = []
    lifetime.renew(life, "rid", "request", Stop(), lambda: loss.append(True))
    assert transactions[0] == (120.0, 140.0)
    assert len(transactions) >= 2
    assert lifetime.execution_deadline == 107.0
    assert lifetime.confirmed_count == int(confirm)
    if confirm:
        assert lifetime.last_confirmed == transactions[-1][0]
        assert not fences and not loss
    else:
        assert fences == [(140.0, "renewal_lost", 160.0)]
        assert loss == [True] and lifetime.fenced.is_set()


@pytest.mark.parametrize("failure", ["fence", "lock"])
def test_unstarted_cleanup_logs_only_the_allowlisted_code(monkeypatch, failure):
    import syslog
    import threading
    from contextlib import nullcontext
    from phase_loop_runtime.launch_supervisor import _settle_unstarted

    warnings = []
    monkeypatch.setattr(syslog, "syslog", lambda priority, message: warnings.append((priority, message)))
    h = SimpleNamespace(
        ids=("reservation", "request", "generation"), reservation_id="reservation", generation="generation"
    )
    life = SimpleNamespace(
        fence_launch=lambda *args, **kwargs: failure != "fence",
        launch_operation_lock=lambda *args, **kwargs: nullcontext(False),
    )
    lifetime = SimpleNamespace(clock=lambda: 0, renewal_cutoff=1, fenced=threading.Event())
    _settle_unstarted(h, life, lifetime, threading.Event())
    assert warnings == [(syslog.LOG_WARNING, "sandbox_placement_release_unconfirmed")]


@pytest.mark.parametrize("operation", ["renew", "cancel"])
def test_generation_before_start_intent_requires_lifecycle_fix(tmp_path, monkeypatch, operation):
    """Requires agent-harness#2156. Both calls use the real SL-3a lifecycle."""
    import threading
    import time
    from phase_loop_runtime import launch_exec, launch_supervisor as sup
    from test_launch_admission import admitted_fixture
    from test_launch_service import local_case

    admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **k: None)
    observations = []
    holder = []

    def runner(h):
        holder.append(h)
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                svc.capped_popen,
                svc.load_caps,
                svc.readiness_code,
                time.monotonic,
                containment_ready=lambda: True,
            ),
        )

    env, svc, req = local_case(tmp_path, supervisor_runner=runner)

    def publication(controller, digest, envelope):
        life = svc.lifecycle
        h = holder[0]
        deadline = time.monotonic() + 2
        if operation == "cancel":
            outcome = life.cancel_launch_owner(*h.ids, deadline=deadline)
            observations.append((outcome, list(env.cancels)))
        else:
            with monkeypatch.context() as patch:
                patch.setattr(life, "_confirm_slot", lambda *args: False)
                first = life.renew_launch(*h.ids, deadline=deadline)
            fenced = life._launch_read("dispositions", h.generation)["fenced"]
            second = life.renew_launch(*h.ids, deadline=time.monotonic() + 2)
            observations.append((first, fenced, second))
        return False

    monkeypatch.setattr(sup, "publish_controller", publication)
    out = svc.launch(req, cancelled=threading.Event())
    assert out.termination.reason == "failed_to_start" and out.worker_invocations == 0
    assert observations == ([("cancel_pending", [])] if operation == "cancel" else [(False, False, True)])


@pytest.mark.parametrize(
    ("timing", "cleanup"),
    [("before", None)] + [
        (timing, cleanup)
        for timing in (
            "at", "after", "expires_during_intent", "cancel_before_intent", "intent_unconfirmed", "lock_timeout"
        )
        for cleanup in ("release", "reap")
    ],
)
def test_local_chain_requires_current_renewal_through_start_intent(tmp_path, monkeypatch, timing, cleanup):
    import threading
    import time
    from phase_loop_runtime import launch_exec, launch_supervisor as sup
    from test_launch_admission import admitted_fixture
    from test_launch_service import local_case

    admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *args, **kwargs: None)
    calls = []
    intent_deadlines = []
    now = None
    cutoff = None

    def spawn(*args, **kwargs):
        calls.append("spawn")
        raise OSError("fixture ends the bounded spawn")

    def runner(h):
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                spawn,
                svc.load_caps,
                svc.readiness_code,
                lambda: time.monotonic() if now is None else now,
                containment_ready=lambda: True,
            ),
        )

    env, svc, req = local_case(tmp_path, ttl=60, supervisor_runner=runner)
    publish = sup._publish_admitted_controller
    mark = svc.lifecycle.mark_start_intent
    renew = sup.LaunchLifetime.renew

    def after_claim(h, blobs):
        nonlocal cutoff, now
        published = publish(h, blobs)
        key = dict(
            version=1, reservation_id=h.reservation_id, request_id=h.request_id, generation=h.generation
        )
        heartbeat = svc.lifecycle._confirmed_renewal(key, svc.lifecycle._disposition(key))
        cutoff = heartbeat["heartbeat_at"] + 2 * (heartbeat["ttl_s"] / 3)
        now = cutoff + {"at": 0, "after": 0.5}.get(timing, -0.5)
        if timing == "lock_timeout":
            from contextlib import nullcontext

            original_lock = svc.lifecycle.launch_operation_lock

            def first_lock_times_out(*args, **kwargs):
                monkeypatch.setattr(svc.lifecycle, "launch_operation_lock", original_lock)
                return nullcontext(False)

            monkeypatch.setattr(svc.lifecycle, "launch_operation_lock", first_lock_times_out)
        if timing == "cancel_before_intent":
            outcome = svc.lifecycle.cancel_launch_owner(*h.ids, deadline=time.monotonic() + 2)
            assert outcome == "cancel_pending"
        return published

    def mark_intent(*ids, deadline):
        nonlocal now
        calls.append("intent")
        intent_deadlines.append(deadline - time.monotonic())
        marked = mark(*ids, deadline=deadline)
        if timing == "expires_during_intent":
            now = cutoff
        return marked and timing != "intent_unconfirmed"

    def delayed_heartbeat(lifetime, lifecycle, reservation_id, request_id, stop, on_loss):
        # Make the start decision before the heartbeat thread observes the cutoff.
        stop.wait(10)
        renew(lifetime, lifecycle, reservation_id, request_id, stop, on_loss)

    def forbidden_rollback(*args, **kwargs):
        calls.append("rollback")
        return False

    monkeypatch.setattr(sup, "_rollback", forbidden_rollback)
    monkeypatch.setattr(sup, "_publish_admitted_controller", after_claim)
    monkeypatch.setattr(svc.lifecycle, "mark_start_intent", mark_intent)
    monkeypatch.setattr(sup.LaunchLifetime, "renew", delayed_heartbeat)
    result = svc.launch(req, cancelled=threading.Event())
    claim = svc.lifecycle.launch_claim_record(req.reservation.reservation_id)
    assert claim["claimed"] is True
    disposition = svc.lifecycle._launch_read("dispositions", claim["generation"])
    expected_calls = {"before": ["intent", "spawn"], "expires_during_intent": ["intent"], "intent_unconfirmed": ["intent"]}.get(timing, [])
    assert calls == expected_calls
    assert all(remaining <= 0.5 for remaining in intent_deadlines)
    assert disposition["start_intent"] is ("intent" in expected_calls)
    assert disposition["fenced"] is ("spawn" not in expected_calls)
    assert result.state == ("finished" if "spawn" in expected_calls else "uncertain")

    if cleanup is None:
        assert disposition["debt"]["cause"] == "start_unknown"
        assert disposition["debt"]["descendants_ended"] is False
        assert disposition["debt"]["parent_collected"] is False
        assert claim["rollback_cause"] is None
        return
    stage = svc.lifecycle.launch_root / "stages" / claim["generation"]
    scratch = svc.lifecycle.launch_run_dir(claim["run_id"]) / "scratch"
    collected_before_teardown = not stage.exists() and not scratch.exists()
    if cleanup == "release":
        response, code = env.release(req.reservation.to_json(), "agent-harness")
        assert (code, response.state) == (0, "released")
    else:
        response, code = env.reap("agent-harness")
        assert (code, response.state, response.inventory.destroyed) == (0, "complete", 1)
    assert collected_before_teardown
    expected_cause = {
        "cancel_before_intent": "cancel",
        "intent_unconfirmed": "collection_unknown",
        "lock_timeout": "collection_unknown",
    }.get(timing, "renewal_lost")
    assert disposition["debt"]["cause"] == expected_cause
    assert disposition["debt"]["descendants_ended"] is True
    assert disposition["debt"]["parent_collected"] is True
    assert not (svc.lifecycle.launch_root / "stages" / claim["generation"]).exists()
    assert not svc.lifecycle.launch_run_dir(claim["run_id"]).exists()


def test_pi_relay_delivers_exact_bytes_and_reports_loss(tmp_path):
    import socket
    import threading
    import time
    from phase_loop_runtime.launch_supervisor import LocalPiLink
    import tempfile
    from pathlib import Path
    import shutil

    root = Path(tempfile.mkdtemp()).resolve()
    link = LocalPiLink(root, "rsv-example")
    stopped, cancelled = threading.Event(), threading.Event()
    with link.listening() as listener:
        child, endpoint = socket.socketpair()
        with child, socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            child.settimeout(2)
            relay = threading.Thread(
                target=link.relay,
                args=(listener, endpoint),
                kwargs=dict(
                    stop=stopped,
                    cancelled=cancelled,
                    clock=time.monotonic,
                    accept_deadline=time.monotonic() + 120,
                ),
            )
            relay.start()
            try:
                client.connect(str(root / "rsv-example" / "link.sock"))
                client.sendall(b"\x00\xffhello\r\n")
                assert child.recv(256) == b"\x00\xffhello\r\n"
                child.sendall(b"\xfeanswer\x00")
                assert client.recv(256) == b"\xfeanswer\x00"
                client.close()
                assert cancelled.wait(2) and link.lost.is_set()
            finally:
                stopped.set()
                relay.join(2)
    assert not (root / "rsv-example").exists()
    shutil.rmtree(root)


def test_detached_supervisor_settles_after_caller_exits(tmp_path):
    """Real isolated, session-separated supervisor. Only test inventory location is selected."""
    import json
    from pathlib import Path
    import subprocess
    import sys
    import time
    from phase_loop_runtime import launch_supervisor

    root = tmp_path.resolve()
    runtime = Path(launch_supervisor.__file__).resolve().parent.parent
    testroot = Path(__file__).resolve().parent
    child_bootstrap = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(runtime)!r})
from phase_loop_runtime import launch_supervisor as supervisor
life = supervisor.PlacementLifecycle
def in_fixture(client):
    return life(client,state_root=Path({str(root / "state")!r}),config_root=Path({str(root / "config")!r}))
supervisor.PlacementLifecycle = in_fixture
raise SystemExit(supervisor.main())
"""
    caller_script = f"""
import os,sys
from pathlib import Path
sys.path[:0] = [{str(runtime)!r},{str(testroot)!r}]
import pytest, threading
from phase_loop_runtime import launch_exec,launch_supervisor,seat_uid
from test_launch_service import local_case
from test_launch_admission import admitted_fixture
root = Path({str(root)!r})
patch = pytest.MonkeyPatch()
admitted_fixture(patch,root)
patch.setattr(launch_exec,"isolated_admission",lambda *a,**kw:None)
real = seat_uid.trusted_module_argv
patch.setattr(seat_uid,"trusted_module_argv",lambda name,*args:
    [sys.executable,"-I","-c",{child_bootstrap!r},*args] if name.endswith(".launch_supervisor") else real(name,*args))
transfer = launch_supervisor._transfer
def exit_after_transfer(*args):
    if not transfer(*args):
        raise ValueError("transfer failed")
    os._exit(0)
patch.setattr(launch_supervisor,"_transfer",exit_after_transfer)
env,svc,req=local_case(root)
svc.launch(req,cancelled=threading.Event())
raise RuntimeError("caller returned without handoff")
"""
    caller = subprocess.Popen(
        [sys.executable, "-I", "-c", caller_script],
        cwd="/",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    _, err = caller.communicate(timeout=20)
    assert caller.returncode == 0, err[-1000:]
    record = root / "state/agent-harness/laneexec/launches/launch-1.json"
    end = time.monotonic() + 10
    while time.monotonic() < end:
        row = json.loads(record.read_bytes())
        if row.get("terminal"):
            break
        time.sleep(0.025)
    assert row["phase"] == "terminal" and row["owner"]["pid"] != caller.pid
    assert json.loads(row["terminal"])["code"] == "sandbox_placement_capability_unmet"


@pytest.mark.parametrize("fault", ["timeout", "peer_uid"])
def test_local_pi_refuses_unverified_link_without_child_bytes(tmp_path, fault):
    import os
    import socket
    import struct
    import threading
    from phase_loop_runtime.launch_supervisor import LocalPiLink

    now = [10.0]
    accept_times = []

    class OtherUid:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def getsockopt(self, level, name, count):
            assert (level, name) == (socket.SOL_SOCKET, socket.SO_PEERCRED)
            return struct.pack("3i", os.getpid(), os.geteuid() + 1, os.getegid())

    class Listener:
        def settimeout(self, seconds):
            pass

        def accept(self):
            accept_times.append(now[0])
            if fault == "peer_uid":
                return OtherUid(), None
            now[0] += 30
            raise TimeoutError

        def close(self):
            pass

    link = LocalPiLink(tmp_path.parent.parent, "r")
    stopped, cancelled = threading.Event(), threading.Event()
    endpoint, child = socket.socketpair()
    with child:
        link.relay(
            Listener(),
            endpoint,
            stop=stopped,
            cancelled=cancelled,
            clock=lambda: now[0],
            accept_deadline=130,
        )
        assert child.recv(1) == b""
    assert link.lost.is_set() and cancelled.is_set()
    assert accept_times == ([10] if fault == "peer_uid" else [10, 40, 70, 100])


def test_generation_owner_disposition_separates_known_death_from_handoff(tmp_path):
    from dataclasses import replace
    import hashlib
    import threading
    from phase_loop_runtime.placement_process_contract import canonical_bytes
    from test_launch_service import local_case

    env, svc, req = local_case(tmp_path)
    env.owner = "gone"
    for crossed in (False, True):
        key = "elected-" + str(int(crossed))
        request = replace(req, request_id=key)
        row = dict(
            version=1,
            request_id=key,
            reservation_id=req.reservation.reservation_id,
            phase="caller",
            generation="f" * 32,
            owner={"pid": 123, "start": "old"},
            terminal=None,
            run_id=None,
            body_sha256=hashlib.sha256(canonical_bytes(request.to_json())).hexdigest(),
            handoff=crossed,
            caller_context={},
        )
        svc.lifecycle.write_launch_record(key, row)
        stop = threading.Event()
        stop.set()
        observed = svc.launch(request, cancelled=stop)
        if crossed:
            assert observed.state == "uncertain" and svc.lifecycle.launch_record(key) == row
        else:
            assert (
                observed.code == "sandbox_launch_refused" and svc.lifecycle.launch_terminal(key) == observed
            )


@pytest.mark.parametrize("fault", ["worker_refused", "uncollected", "timed_out", "cancelled"])
def test_local_terminal_and_collection_debt_after_start(tmp_path, monkeypatch, fault):
    import signal
    import threading
    import time
    from dataclasses import replace
    from phase_loop_runtime import launch_supervisor as sup, launch_exec, launch_process_contract as wire
    from test_launch_service import local_case
    from test_launch_admission import admitted_fixture

    admitted_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launch_exec, "isolated_admission", lambda *a, **kw: None)
    signals = []
    stopped = threading.Event()
    clock_offset = [0]
    handed = []

    class Process:
        returncode = 0

        def poll(self):
            return None if fault in ("timed_out", "cancelled") and not stopped.is_set() else self.returncode

        def wait(self, timeout=None):
            assert stopped.is_set()
            return self.returncode

    def send(h, proc, sig):
        signals.append(sig)
        stopped.set()
        return True

    def spawn(*args, **kw):
        if fault == "timed_out":
            clock_offset[0] = 31
        if fault == "cancelled":

            def cancel():
                svc.lifecycle.cancel_launch_owner(*handed[0].ids, deadline=time.monotonic() + 3)

            threading.Thread(target=cancel, daemon=True).start()
        return Process()

    def runner(h):
        handed.append(h)
        sup.run_supervisor(
            h,
            effects=sup.SupervisorEffects(
                svc.lifecycle,
                svc.capped_popen,
                svc.load_caps,
                svc.readiness_code,
                svc.clock,
                containment_ready=lambda: True,
                signal_group=send,
                observe_result=lambda *_: sup.TerminatedAttempt(
                    0, None, None, True, fault != "uncollected"
                ),
            ),
        )

    env, svc, req = local_case(
        tmp_path,
        supervisor_runner=runner,
        capped_popen=spawn,
        clock=lambda: time.monotonic() + clock_offset[0],
    )
    result = svc.launch(req, cancelled=threading.Event())
    assert result.state == "finished" and result.termination.reason == (
        fault if fault in ("timed_out", "cancelled") else "failed_to_start"
    )
    assert signals == ([signal.SIGTERM] if fault in ("timed_out", "cancelled") else [])
    status = env.service("agent-harness").status(
        wire.StatusRequest("observe", req.reservation.reservation_id, req.request_id, {})
    )
    assert status.launch == result and status.run_id == result.attempt_id
    if fault == "uncollected":
        claim = svc.lifecycle.launch_claim_record(req.reservation.reservation_id)
        debt = svc.lifecycle.read_cleanup_debt(
            req.reservation.reservation_id, req.request_id, claim["generation"]
        )
        assert debt.descendants_ended is True and debt.parent_collected is False
        assert env.release(req.reservation.to_json(), "agent-harness")[0].state == "cleanup_pending"
        assert (
            svc.launch(replace(req, request_id="another"), cancelled=threading.Event()).state == "refused"
        )
