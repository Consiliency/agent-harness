"""Focused regression tests for Consiliency/agent-harness#1950.

Covers:
- Broker connection-locked nonblocking response send, zero-byte send failure,
  untyped shutdown exit, pre-shutdown EPIPE race, and clean typed dispositions.
- Jailed Codex timeout (`TIMEOUT` / `codex leg deadline exceeded`), monitor/board
  cancellation (`UNAVAILABLE` / empty review text), containment precedence,
  guarded `model_turn`/`verdict` exec signals, `RecursionError` guard, and
  `_run_seat_policy` record preservation vs replacement refusal.
- Typed normalization of Codex setup/probe failures without deleting pre-existing
  directories, plus `fix` population via `seat_admission._refuses`.
- `run_provider(..., count_spawn=False)` excluding Codex admission probes from
  `_SpawnCounter` while leaving Claude SDK proof regions untouched.
- `seat_admission._base_verdict` predicate ordering (vendor gates last) and
  caller `env` threading into profile credential/precondition checks.
- `seat_jail_qualification.qualify("codex", provider=...)` rejection and
  `_run_probe_in_jail` owned vs borrowed dependency cleanup.
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from phase_loop_runtime import (
    claude_seat_transport,
    panel_invoker as pi,
    sandbox_egress,
    seat_admission,
    seat_codex_credential as cred,
    seat_codex_evidence as evidence,
    seat_codex_runtime as codex_runtime,
    seat_egress_proxy,
    seat_jail,
    seat_jail_qualification,
    seat_profile_codex,
    seat_subject,
)
from phase_loop_runtime.advisor_board import backing as advisor_backing
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from test_seat_codex_cli_shape import EXEC_HELP_0_167_0, FEATURES_0_167_0
from test_seat_codex_credential import NOW, _claims, _login
from test_seat_codex_evidence import stream
from test_seat_codex_leg import local_reads, prepare


# ---------------------------------------------------------------------------
# 1. Broker response-send locking, shutdown races, and typed dispositions
# ---------------------------------------------------------------------------


def _make_stub_broker() -> advisor_backing.ParentUnixBroker:
    broker = object.__new__(advisor_backing.ParentUnixBroker)
    broker._connection = None
    broker._conn_lock = threading.Lock()
    broker._shutdown_connection = None
    broker._shutdown_disposition = None
    broker._cancel_event = threading.Event()
    broker._stopping = False
    broker._sock = None
    broker.evidence = {}
    return broker


def test_broker_send_response_frame_treats_zero_byte_send_as_transport_failure():
    broker = _make_stub_broker()

    class ZeroSendSocket:
        def setblocking(self, flag: bool) -> None:
            assert flag is False

        def send(self, data) -> int:
            return 0

    with pytest.raises(ConnectionResetError, match="0 bytes"):
        broker._send_response_frame(ZeroSendSocket(), b'{"ok":true}')


def test_broker_send_response_frame_exits_on_untyped_shutdown(monkeypatch):
    broker = _make_stub_broker()
    blocked = threading.Event()

    class BlockingSocket:
        def setblocking(self, flag: bool) -> None:
            assert flag is False

        def send(self, data) -> int:
            blocked.set()
            raise BlockingIOError(errno.EAGAIN, "would block")

        def shutdown(self, how: int) -> None:
            pass

    conn = BlockingSocket()
    broker._connection = conn
    monkeypatch.setattr(advisor_backing, "_poll_socket", lambda *a, **k: None)

    def wake() -> None:
        assert blocked.wait(timeout=2)
        broker._wake_server()  # shutdown without a typed disposition

    waker = threading.Thread(target=wake, daemon=True)
    waker.start()
    try:
        with pytest.raises(OSError, match="broker stopping"):
            broker._send_response_frame(conn, b"payload")
    finally:
        waker.join(timeout=2)
    assert not waker.is_alive()
    assert broker._shutdown_connection is None
    assert broker._shutdown_disposition is None


def test_broker_send_response_frame_preserves_pre_shutdown_epipe_race():
    """Force a pre-shutdown EPIPE while _wake_server(deadline_exceeded) contends on _conn_lock."""
    broker = _make_stub_broker()
    in_send = threading.Event()
    waker_started = threading.Event()

    class RacingEpipeSocket:
        def setblocking(self, flag: bool) -> None:
            assert flag is False

        def send(self, data) -> int:
            in_send.set()
            # Give the concurrent shutdown thread time to block on _conn_lock.
            assert waker_started.wait(timeout=2)
            time.sleep(0.05)
            raise BrokenPipeError(errno.EPIPE, "broken pipe before shutdown")

        def shutdown(self, how: int) -> None:
            pass

    conn = RacingEpipeSocket()
    broker._connection = conn

    def wake() -> None:
        assert in_send.wait(timeout=2)
        waker_started.set()
        broker._wake_server(disposition="deadline_exceeded")

    waker = threading.Thread(target=wake, daemon=True)
    waker.start()
    try:
        with pytest.raises(BrokenPipeError):
            broker._send_response_frame(conn, b"payload")
    finally:
        waker.join(timeout=2)
    assert broker._shutdown_connection is conn
    assert broker._shutdown_disposition == "deadline_exceeded"


def test_broker_send_response_frame_suppresses_deliberate_shutdown_on_same_connection():
    broker = _make_stub_broker()
    sent_calls = []

    class ShutdownSocket:
        def setblocking(self, flag: bool) -> None:
            pass

        def send(self, data) -> int:
            sent_calls.append(bytes(data))
            raise AssertionError("send should not run after deliberate shutdown")

        def shutdown(self, how: int) -> None:
            pass

    conn = ShutdownSocket()
    broker._connection = conn
    broker._wake_server(disposition="operation_cancelled")
    broker._send_response_frame(conn, b"payload")
    assert sent_calls == []


def _run_mocked_broker_client(
    tmp_path: Path,
    monkeypatch,
    *,
    wait_result: advisor_backing._ClientWait,
    serve_fn=None,
    returncode: int = -15,
    cancel_event: threading.Event | None = None,
    deadline_s: float | None = 5.0,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    stage = tmp_path / "stage"
    stage.mkdir()
    bundle = stage / "review-bundle.md"
    instructions = stage / "review-instructions.md"
    bundle.write_text("bundle\n", encoding="utf-8")
    instructions.write_text("instructions\n", encoding="utf-8")
    bundle.chmod(0o444)
    instructions.chmod(0o444)
    import hashlib

    repo_digest = advisor_backing._canonical_repo_digest(repo)
    now_ns = time.monotonic_ns()
    auth = advisor_backing.ReviewLegAuthorization(
        operation="op-1",
        purpose="review",
        input_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        instructions_sha256=hashlib.sha256(instructions.read_bytes()).hexdigest(),
        canonical_repo_sha256=repo_digest,
        broker_contract=advisor_backing.PARENT_UNIX_BROKER_V1,
        harness="codex",
        model="gpt-5.4",
        issued_monotonic_ns=now_ns,
        expires_monotonic_ns=now_ns + 60_000_000_000,
        _seal=advisor_backing._AUTHORIZATION_SEAL,
        monitoring_policy="heartbeat_only" if deadline_s is None else "bounded",
    )
    lease = (
        SimpleNamespace(
            lock=threading.Lock(),
            active=True,
            closed=False,
            cancel_event=cancel_event or threading.Event(),
        )
        if deadline_s is None
        else None
    )
    advisor_backing._remember_leg_claim(auth, lease)
    broker = advisor_backing.ParentUnixBroker(
        authorization=auth,
        harness="codex",
        model="gpt-5.4",
        staged_dir=stage,
        canonical_repo=repo,
    )

    class FakeProc:
        def __init__(self) -> None:
            self.pid = os.getpid()
            self.returncode = returncode
            self.stdin = None
            self.stdout = None
            self.stderr = None

        def poll(self):
            return self.returncode

        def communicate(self, *args, **kwargs):
            return (b"", b"")

    class FakeWitness:
        info_fd = 10
        block_fd = 11

        def abandon(self):
            pass

        def complete(self, *args, **kwargs):
            pass

    from phase_loop_runtime import provider_tree_proof

    monkeypatch.setattr(provider_tree_proof, "BwrapLaunch", FakeWitness)
    monkeypatch.setattr(advisor_backing.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(pi, "_terminate_process_group", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_tree_quiescent", lambda *a, **k: True)
    monkeypatch.setattr(advisor_backing, "_await_client", lambda *a, **k: wait_result)
    if serve_fn is not None:
        monkeypatch.setattr(broker, "serve_once", serve_fn)
    else:
        monkeypatch.setattr(broker, "serve_once", lambda *a, **k: None)
    return broker


def test_broker_deadline_with_adapter_cancel_sets_deadline_exceeded_disposition(tmp_path, monkeypatch):
    cancel_called = []
    broker = _run_mocked_broker_client(
        tmp_path,
        monkeypatch,
        wait_result=advisor_backing._ClientWait(completed=False, timed_out=True, cancelled=False),
        returncode=-15,
        deadline_s=5.0,
    )
    adapter = advisor_backing._make_broker_inference_adapter(
        lambda: ("OK", "done"),
        lambda: cancel_called.append(broker._shutdown_disposition),
        lambda: True,
    )
    try:
        with pytest.raises(ValueError, match="deadline"):
            broker.run_credentialless_client(adapter, deadline_s=5.0)
        assert cancel_called == ["deadline_exceeded"]
        assert broker.evidence["provider_cancel_requested"] is True
        assert broker.evidence["broker_failure_disposition"] == "deadline_exceeded"
    finally:
        broker.close()


def test_broker_independent_failure_with_adapter_cancel_does_not_set_disposition(tmp_path, monkeypatch):
    cancel_called = []
    # Client exited abnormally (status 1) before cleanup AND timed_out is False.
    broker = _run_mocked_broker_client(
        tmp_path,
        monkeypatch,
        wait_result=advisor_backing._ClientWait(
            completed=False, timed_out=False, cancelled=False, exit_status=1, exit_ns=time.monotonic_ns(),
        ),
        returncode=1,
        deadline_s=5.0,
    )
    adapter = advisor_backing._make_broker_inference_adapter(
        lambda: ("OK", "done"),
        lambda: cancel_called.append(broker._shutdown_disposition),
        lambda: True,
    )
    try:
        with pytest.raises(ValueError, match="credentialless broker client failed"):
            broker.run_credentialless_client(adapter, deadline_s=5.0)
        assert cancel_called == [None]
        assert broker.evidence["provider_cancel_requested"] is True
        assert "broker_failure_disposition" not in broker.evidence
    finally:
        broker.close()


def test_broker_abnormal_client_exit_plus_cancel_does_not_set_clean_disposition(tmp_path, monkeypatch):
    live_cancel = threading.Event()
    broker = _run_mocked_broker_client(
        tmp_path,
        monkeypatch,
        wait_result=advisor_backing._ClientWait(
            completed=False, timed_out=False, cancelled=False, exit_status=2, exit_ns=time.monotonic_ns(),
        ),
        returncode=2,
        cancel_event=live_cancel,
        deadline_s=None,
    )

    def serve_and_cancel(*args, **kwargs):
        live_cancel.set()

    monkeypatch.setattr(broker, "serve_once", serve_and_cancel)
    adapter = advisor_backing._make_broker_inference_adapter(
        lambda: ("OK", "done"),
        lambda: None,
        lambda: True,
    )
    try:
        with pytest.raises(ValueError, match="credentialless broker client failed"):
            broker.run_credentialless_client(adapter, deadline_s=None, cancel_event=live_cancel)
        assert "broker_failure_disposition" not in broker.evidence
    finally:
        broker.close()


# ---------------------------------------------------------------------------
# 2. Codex timeout, cancellation, containment, signals, RecursionError, policy
# ---------------------------------------------------------------------------


def test_read_tool_record_handles_recursion_error():
    deep = (b"[" * 2000) + (b"]" * 2000) + b"\n"
    record = evidence.read_tool_record(deep)
    assert record.stream_valid is False
    assert record.turn_completed is False
    assert record.commands_completed == 0


def test_exec_jailed_codex_timeout_returns_typed_timeout_and_scans_secrets(tmp_path, monkeypatch):
    seat = prepare(tmp_path, monkeypatch)
    local_reads(monkeypatch)
    obs = {
        "returncode": None, "argv": None, "env": None, "exit_observed": False,
        "auth_state": "unavailable", "auth_probed": False, "model_turn": None,
        "verdict": None, "refusal": None, "stage": None, "secret_match": None,
        "output_refused": False, "stream_rejection": None,
    }
    monkeypatch.setattr(
        pi,
        "_run_leg_with_liveness",
        lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(["codex"], 10, output=b"partial", stderr=b"slow")
        ),
    )
    sink: list[pi._LegFailure] = []
    token = pi._EXEC_OBSERVATION.set(obs)
    try:
        status, review = pi._exec_jailed_codex_leg(
            seat, deadline_s=10, model="gpt-5.4", prompt="review",
            broker_evidence={}, failure_detail_sink=sink,
        )
    finally:
        pi._EXEC_OBSERVATION.reset(token)
    assert (status, review) == ("TIMEOUT", "")
    assert [f.template for f in sink] == ["codex leg deadline exceeded"]
    assert obs["refusal"] == "codex leg deadline exceeded"
    assert obs["model_turn"] is None and obs["verdict"] is None

    # Timeout whose output carries a secret must still trip containment first.
    seat2 = prepare(tmp_path / "s2", monkeypatch)
    local_reads(monkeypatch)
    secret = seat2.codex_copy.secrets[0]
    monkeypatch.setattr(
        pi,
        "_run_leg_with_liveness",
        lambda *a, **k: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(["codex"], 10, output=secret, stderr=b"")
        ),
    )
    sink2: list[pi._LegFailure] = []
    status2, review2 = pi._exec_jailed_codex_leg(
        seat2, deadline_s=10, model="gpt-5.4", prompt="review",
        broker_evidence={}, failure_detail_sink=sink2,
    )
    assert (status2, review2) == ("DEGRADED", "")
    assert sink2[-1].template == "codex_seat_token_in_output"


def test_exec_jailed_codex_cancel_uses_event_not_stderr_and_preserves_containment(tmp_path, monkeypatch):
    # Pre-launch cancel returns UNAVAILABLE with empty review text and sink detail.
    seat = prepare(tmp_path / "pre", monkeypatch)
    local_reads(monkeypatch)
    cancel = threading.Event()
    cancel.set()
    monitor = SimpleNamespace(cancel=cancel)
    sink: list[pi._LegFailure] = []
    obs = {"refusal": None, "model_turn": None, "verdict": None}
    token = pi._EXEC_OBSERVATION.set(obs)
    try:
        status, review = pi._exec_jailed_codex_leg(
            seat, deadline_s=10, model="gpt-5.4", prompt="review",
            broker_evidence={}, failure_detail_sink=sink, review_monitor=monitor,
        )
    finally:
        pi._EXEC_OBSERVATION.reset(token)
    assert (status, review) == ("UNAVAILABLE", "")
    assert sink[-1].template == "review_operation_cancelled"
    assert obs["refusal"] == "review_operation_cancelled"

    # Stderr text alone without cancel event does NOT classify as cancelled.
    seat2 = prepare(tmp_path / "stderr_only", monkeypatch)
    local_reads(monkeypatch)
    (seat2.seat_dir / "seat-out/panel-codex.txt").write_text("Done.\n\nAGREE", encoding="utf-8")
    ok_stream = stream(command=True).decode()
    monkeypatch.setattr(
        pi,
        "_run_leg_with_liveness",
        lambda *a, **k: subprocess.CompletedProcess(["codex"], 0, ok_stream, "review_operation_cancelled"),
    )
    sink2: list[pi._LegFailure] = []
    status2, review2 = pi._exec_jailed_codex_leg(
        seat2, deadline_s=10, model="gpt-5.4", prompt="review",
        broker_evidence={}, failure_detail_sink=sink2,
        review_monitor=SimpleNamespace(cancel=threading.Event()),
    )
    assert status2 == "OK" and "AGREE" in review2 and sink2 == []

    # Post-spawn cancel with leaked secret still reports containment refusal.
    seat3 = prepare(tmp_path / "cancel_leak", monkeypatch)
    local_reads(monkeypatch)
    (seat3.seat_dir / "seat-out/panel-codex.txt").write_bytes(seat3.codex_copy.secrets[0])
    cancel3 = threading.Event()

    def run_and_cancel(*args, **kwargs):
        cancel3.set()
        return subprocess.CompletedProcess(["codex"], 1, "", "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", run_and_cancel)
    sink3: list[pi._LegFailure] = []
    status3, review3 = pi._exec_jailed_codex_leg(
        seat3, deadline_s=10, model="gpt-5.4", prompt="review",
        broker_evidence={}, failure_detail_sink=sink3,
        review_monitor=SimpleNamespace(cancel=cancel3),
    )
    assert (status3, review3) == ("DEGRADED", "")
    assert sink3[-1].template == "codex_seat_token_in_output"


def test_exec_jailed_codex_records_model_turn_and_verdict_before_post_exit_refusals(tmp_path, monkeypatch):
    # Completed turn + verdict followed by token_expiring records both signals.
    seat = prepare(tmp_path / "exp", monkeypatch)
    local_reads(monkeypatch)
    seat.codex_copy = replace(seat.codex_copy, expires_at=0)
    (seat.seat_dir / "seat-out/panel-codex.txt").write_text("Looks good.\n\nAGREE", encoding="utf-8")
    ok_stream = stream(command=True).decode()
    monkeypatch.setattr(
        pi,
        "_run_leg_with_liveness",
        lambda *a, **k: subprocess.CompletedProcess(["codex"], 0, ok_stream, ""),
    )
    obs = {
        "returncode": None, "argv": None, "env": None, "exit_observed": False,
        "auth_state": "unavailable", "auth_probed": False, "model_turn": None,
        "verdict": None, "refusal": None, "stage": None, "secret_match": None,
        "output_refused": False, "stream_rejection": None,
    }
    sink: list[pi._LegFailure] = []
    token = pi._EXEC_OBSERVATION.set(obs)
    try:
        status, review = pi._exec_jailed_codex_leg(
            seat, deadline_s=10, model="gpt-5.4", prompt="review",
            broker_evidence={}, failure_detail_sink=sink,
        )
    finally:
        pi._EXEC_OBSERVATION.reset(token)
    assert (status, review) == ("DEGRADED", "")
    assert sink[-1].template == "codex_seat_token_expiring"
    assert obs["model_turn"] is True
    assert obs["verdict"] is True

    # Empty stdout + non-zero exit must NOT record model_turn=False / verdict=False.
    seat2 = prepare(tmp_path / "empty", monkeypatch)
    local_reads(monkeypatch)
    monkeypatch.setattr(
        pi,
        "_run_leg_with_liveness",
        lambda *a, **k: subprocess.CompletedProcess(["codex"], 1, "", "err"),
    )
    obs2 = dict(obs, model_turn=None, verdict=None, refusal=None, exit_observed=False)
    sink2: list[pi._LegFailure] = []
    token2 = pi._EXEC_OBSERVATION.set(obs2)
    try:
        status2, _ = pi._exec_jailed_codex_leg(
            seat2, deadline_s=10, model="gpt-5.4", prompt="review",
            broker_evidence={}, failure_detail_sink=sink2,
        )
    finally:
        pi._EXEC_OBSERVATION.reset(token2)
    assert status2 == "DEGRADED"
    assert sink2[-1].template == "codex_seat_tools_unavailable"
    assert obs2["model_turn"] is None and obs2["verdict"] is None


@pytest.mark.parametrize(
    "case",
    ["deadline", "prespawn_deadline_latch", "cancel", "cancel_containment", "unrelated", "quiescence_unproven"],
)
def test_default_spawn_codex_broker_dispositions_and_prespawn_latch_race(tmp_path, monkeypatch, case):
    monkeypatch.setattr(pi, "_gc_stale_panel_scratch", lambda: None)
    released = []
    lease = SimpleNamespace(seat_id=7, release=lambda: released.append(True))
    route = SimpleNamespace(jailed=True, lease=lease)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (route, [], None))
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda _: 42)
    monkeypatch.setattr(
        pi._seat_egress_proxy, "start_proxy",
        lambda **k: contextlib.nullcontext(SimpleNamespace(socket="fixture", proxy_url="fixture")),
    )
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda _: {})
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", lambda **k: contextlib.nullcontext(("fixture",)))
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda **k: {})
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(pi._sandbox_policy, "ensure_staging_space", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_retention, "mark_as_sandbox", lambda *a, **k: None)

    def staged(repo, review):
        tree = Path(review) / "pl-panel-stage-fixture"
        (tree / ".git").mkdir(parents=True)
        (tree / ".git/phase-loop-source-commit").write_text("c" * 40)
        return tree

    monkeypatch.setattr(pi._review_stage, "stage_review_tree", staged)
    monkeypatch.setattr(
        pi._sandbox_policy, "select_sandbox_root",
        lambda **k: pi._sandbox_policy.SandboxRootChoice(host=None, path=k["fallback"], fell_back=False, reason=""),
    )
    monkeypatch.setattr(pi, "_bind_route_qualification", lambda seat, route: seat)
    fake_seat = SimpleNamespace(notices=[])
    monkeypatch.setattr(pi, "_prepare_jailed_codex", lambda *a, **k: fake_seat)

    def fake_exec(seat, *, failure_detail_sink=None, quiescence_latch=None, **kwargs):
        if case == "prespawn_deadline_latch":
            raise pi._ReviewOperationCancelled("review_operation_cancelled")
        if case == "cancel_containment":
            return pi._jailed_failure("codex_seat_token_in_output", failure_detail_sink)
        if case == "quiescence_unproven":
            quiescence_latch.trip(pi.ProviderProcessGroupQuiescenceError("still alive"))
            return "TIMEOUT", ""
        if case == "deadline":
            if failure_detail_sink is not None:
                failure_detail_sink.append(pi._LegFailure(template="codex leg deadline exceeded"))
            return "TIMEOUT", ""
        return "UNAVAILABLE", ""

    monkeypatch.setattr(pi, "_exec_jailed_codex_leg", fake_exec)

    class FakeBroker:
        def __init__(self, *args, **kwargs):
            self.evidence: dict[str, object] = {}
            self._cancel_event = threading.Event()
            self._shutdown_disposition: str | None = None

        def run_credentialless_client(self, adapter, *, deadline_s=None, cancel_event=None):
            if case == "prespawn_deadline_latch":
                self._shutdown_disposition = "deadline_exceeded"
                adapter.cancel()
                status, text = adapter.invoke()
                assert (status, text) == ("TIMEOUT", "")
                self.evidence["broker_failure_disposition"] = "deadline_exceeded"
                raise ValueError("credentialless broker client failed: deadline")
            if case in {"deadline", "quiescence_unproven"}:
                self._shutdown_disposition = "deadline_exceeded"
                adapter.invoke()
                adapter.cancel()
                self.evidence["broker_failure_disposition"] = "deadline_exceeded"
                raise ValueError("credentialless broker client failed: deadline")
            if case in {"cancel", "cancel_containment"}:
                self._cancel_event.set()
                self._shutdown_disposition = "operation_cancelled"
                adapter.invoke()
                adapter.cancel()
                self.evidence["broker_failure_disposition"] = "operation_cancelled"
                raise ValueError("credentialless broker client failed: broker operation cancelled or closed")
            # unrelated broker error without a typed disposition
            raise ValueError("credentialless broker client failed: broken pipe")

        def close(self):
            pass

    monkeypatch.setattr(pi, "ParentUnixBroker", FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(
        pi, "derive_review_leg_authorization",
        lambda *a, **k: SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12),
    )
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a: (False, "missing_claude_cli"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))

    def invoke():
        return pi._default_spawn(
            "codex", "ARTIFACT", mode="review", model="m",
            review_authorization=SimpleNamespace(staged_tree_sha256="a" * 64),
            canonical_repo_authority=tmp_path,
        )

    if case == "unrelated":
        spawned = invoke()
        assert spawned[0] == "DEGRADED"
        assert spawned[1] == ""
        assert not (
            isinstance(spawned[2], pi._LegFailure)
            and spawned[2].template in {"codex leg deadline exceeded", "review_operation_cancelled"}
        )
    elif case == "quiescence_unproven":
        with pytest.raises(pi.ProviderProcessGroupQuiescenceError, match="still alive"):
            invoke()
    else:
        spawned = invoke()
        if case in {"deadline", "prespawn_deadline_latch"}:
            assert spawned[0] == "TIMEOUT"
            assert spawned[1] == ""
            assert isinstance(spawned[2], pi._LegFailure)
            assert spawned[2].template == "codex leg deadline exceeded"
            assert "codex leg deadline exceeded" not in spawned.seat_notices
        elif case == "cancel":
            assert spawned[0] == "UNAVAILABLE"
            assert spawned[1] == ""
            assert isinstance(spawned[2], pi._LegFailure)
            assert spawned[2].template == "review_operation_cancelled"
            assert "review_operation_cancelled" not in spawned.seat_notices
        elif case == "cancel_containment":
            assert spawned[0] == "DEGRADED"
            assert spawned[1] == ""
            assert isinstance(spawned[2], pi._LegFailure)
            assert spawned[2].template == "codex_seat_token_in_output"
            assert "codex_seat_token_in_output" in spawned.seat_notices
    assert released == [True]


@pytest.mark.parametrize("mode", ["containment", "inflight_cancel", "late_cancel"])
def test_run_seat_policy_codex_cancel_record_handling(tmp_path, monkeypatch, mode):
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from harden_tdd_guard import invoke_sanctioned_board_control

    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(pi, "_publish_seat_modes", lambda *a, **kw: None)
    cancel = threading.Event()
    recorded_attempts: list[str] = []

    @pi._retained_leg_exec
    def spawn(leg, prompt):
        if mode == "containment":
            pi._note_exec_refusal_code("codex_seat_token_in_output")
            cancel.set()
            return "DEGRADED", "", pi._LegFailure(template="codex_seat_token_in_output")
        if mode == "inflight_cancel":
            pi._note_exec_refusal_code("review_operation_cancelled")
            cancel.set()
            return "UNAVAILABLE", "", pi._LegFailure(template="review_operation_cancelled")
        # late_cancel: completed leg cancelled afterwards
        cancel.set()
        return "OK", "Looks fine.\n\nAGREE"

    from phase_loop_runtime import president_adapter as pa
    real_write = pa.write_private_record

    def track_write(name, record):
        if name.startswith("leg-"):
            recorded_attempts.append(record["attempt_id"])
        return real_write(name, record)

    monkeypatch.setattr(pa, "write_private_record", track_write)
    board = replace(DEFAULT_BOARD, seats=tuple(s for s in DEFAULT_BOARD.seats if s.harness == "codex"))
    stream_dir = tmp_path / "stream"
    result = invoke_sanctioned_board_control(
        board, "fixture prompt", spawn=spawn, stream_dir=stream_dir,
        cancel_event=cancel, max_concurrency=1, monitoring_policy="heartbeat_only",
    )
    leg, = result.legs
    meta = leg._leg_exec_metadata
    record_file = state / "agent-harness/seat-records" / f"leg-{meta['attempt_id']}.json"
    record = json.loads(record_file.read_text(encoding="utf-8"))
    assert leg._review_monitoring["terminal_reason"] == "user_cancel"

    if mode == "containment":
        assert (leg.status, leg.text, leg.detail) == ("DEGRADED", "", "codex_seat_token_in_output")
        assert len(recorded_attempts) == 1
        assert record["refusal"] == "codex_seat_token_in_output"
    elif mode == "inflight_cancel":
        assert (leg.status, leg.text, leg.detail) == ("UNAVAILABLE", "", "review_operation_cancelled")
        assert len(recorded_attempts) == 1
        assert meta["attempt_id"] == recorded_attempts[0]
        assert record["refusal"] == "review_operation_cancelled"
    else:
        assert (leg.status, leg.text, leg.detail) == ("UNAVAILABLE", "", "review_operation_cancelled")
        assert len(recorded_attempts) == 2
        assert meta["attempt_id"] == recorded_attempts[1]
        assert record["outcome"] == "leg_execution_unobserved"
        assert record["refusal"] == "review_operation_cancelled"


# ---------------------------------------------------------------------------
# 3. Setup failure normalization, seat_dir_created safety, and fix population
# ---------------------------------------------------------------------------


def test_prepare_jailed_codex_normalizes_setup_failures_and_preserves_preexisting_seat_dir(
    tmp_path, monkeypatch,
):
    review = tmp_path / "review"
    tree = review / "reviewed-tree"
    tree.mkdir(parents=True)
    tree_fd = seat_jail.open_dir_nofollow(tree)
    try:
        digest = seat_jail.tree_manifest_sha256_at(tree_fd)
    finally:
        os.close(tree_fd)
    auth_obj = SimpleNamespace(staged_tree_sha256=digest)
    proxy = SimpleNamespace(ca_cert=tmp_path / "ca.pem", proxy_url="http://srt:tok@127.0.0.1:3128")
    existing_seat_dir = tmp_path / "preexisting-seat"
    existing_seat_dir.mkdir(mode=0o700)
    marker = existing_seat_dir / "keep.txt"
    marker.write_text("do not delete", encoding="utf-8")

    # 1. FileNotFoundError during subject resolution -> seat_provider_unavailable
    monkeypatch.setattr(pi, "_resolved_jail_subject", lambda *a: (_ for _ in ()).throw(FileNotFoundError("no codex")))
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        pi._prepare_jailed_codex(review, existing_seat_dir, auth_obj, 1, 1, ("b", "i"), proxy, env={})
    assert caught.value.code == "seat_provider_unavailable"
    assert marker.exists()

    # 2. ExecutableDependencyError -> identity, closes owned dependency, leaves pre-existing seat_dir
    closed = []
    dep = SimpleNamespace(_jailcore_owned=True, close=lambda: closed.append(True), subject_source="/bin/codex")
    monkeypatch.setattr(
        pi, "_resolved_jail_subject",
        lambda *a: (seat_subject.SeatSubject("codex", "managed_release", Path("/bin/codex"), None, None), dep),
    )
    monkeypatch.setattr(
        pi, "_validate_jail_dependency",
        lambda *a: (_ for _ in ()).throw(ExecutableDependencyError("authority_invalid", "bad")),
    )
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught2:
        pi._prepare_jailed_codex(review, existing_seat_dir, auth_obj, 1, 1, ("b", "i"), proxy, env={})
    assert caught2.value.code == seat_jail.refused("identity")
    assert closed == [True]
    assert marker.exists()

    # 3. Pre-existing seat_dir triggers FileExistsError at mkdir -> jail_build, does NOT rmtree!
    auth_file = tmp_path / "op/.codex/auth.json"
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text(json.dumps(_login(claims=_claims(exp=int(time.time()) + 7200))), encoding="utf-8")
    auth_file.chmod(0o600)
    monkeypatch.setattr(pi, "_validate_jail_dependency", lambda *a: None)
    monkeypatch.setattr(seat_profile_codex, "validate_codex_projection", lambda *a: None)
    monkeypatch.setattr(seat_profile_codex, "codex_admission_gate", lambda *a, **k: None)
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught3:
        pi._prepare_jailed_codex(
            review, existing_seat_dir, auth_obj, 1, 1, ("b", "i"), proxy,
            env={"HOME": str(auth_file.parents[1])},
        )
    assert caught3.value.code == seat_jail.refused("jail_build")
    assert marker.exists()

    # 4. Contract bug still raises ValueError("contract_bug").
    with pytest.raises(ValueError, match="contract_bug"):
        pi._prepare_jailed_codex(
            review, tmp_path / "bad-mode", auth_obj, 1, 1, ("b", "i"), proxy,
            credential_mode="invalid",
        )


def test_codex_admission_gate_normalizes_probe_errors_and_populates_fix(tmp_path, monkeypatch):
    home = tmp_path / "op"
    auth = home / ".codex/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps(_login(claims=_claims(exp=int(time.time()) + 7200))), encoding="utf-8")
    auth.chmod(0o600)
    monkeypatch.setattr(cred, "auth_path", lambda env=None: auth)
    dep = SimpleNamespace(
        _jailcore_owned=False,
        subject_source="/prepared/bin/codex",
        revalidate=lambda: None,
        entries=[SimpleNamespace(kind="file", destination=p) for p in codex_runtime.CODEX_RUNTIME_DESTINATIONS],
        subject_destination=codex_runtime.CODEX_RUNTIME_DESTINATIONS[0],
    )

    # Probe TimeoutExpired -> jail_build with non-empty fix
    monkeypatch.setattr(
        pi, "run_provider",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(["codex"], 30)),
    )
    verdict = seat_profile_codex.codex_admission_gate(
        "codex", {"HOME": str(home)}, True, executable=Path("/prepared/bin/codex"), dependency=dep,
    )
    assert verdict is not None
    assert verdict.status == "refuses"
    assert verdict.code == seat_jail.refused("jail_build")
    assert verdict.fix

    # Unregistered SeatSandboxRefused falls back to identity with non-empty fix
    unregistered = seat_jail.SeatSandboxRefused.__new__(seat_jail.SeatSandboxRefused)
    unregistered.code = "unregistered_codex_code"
    unregistered.also = ()
    monkeypatch.setattr(
        pi, "run_provider",
        lambda *a, **k: (_ for _ in ()).throw(unregistered),
    )
    verdict2 = seat_profile_codex.codex_admission_gate(
        "codex", {"HOME": str(home)}, True, executable=Path("/prepared/bin/codex"), dependency=dep,
    )
    assert verdict2 is not None
    assert verdict2.status == "refuses"
    assert verdict2.code == seat_jail.refused("identity")
    assert verdict2.fix


# ---------------------------------------------------------------------------
# 4. Probe accounting (count_spawn=False) & Claude SDK proof integrity
# ---------------------------------------------------------------------------


def test_codex_admission_probes_do_not_increment_spawn_counter_and_sdk_proof_holds(tmp_path, monkeypatch):
    home = tmp_path / "op"
    auth = home / ".codex/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps(_login(claims=_claims(exp=int(time.time()) + 7200))), encoding="utf-8")
    auth.chmod(0o600)
    monkeypatch.setattr(cred, "auth_path", lambda env=None: auth)
    dep = SimpleNamespace(
        _jailcore_owned=False,
        subject_source="/prepared/bin/codex",
        revalidate=lambda: None,
        entries=[SimpleNamespace(kind="file", destination=p) for p in codex_runtime.CODEX_RUNTIME_DESTINATIONS],
        subject_destination=codex_runtime.CODEX_RUNTIME_DESTINATIONS[0],
    )

    class FakeProcess:
        def __init__(self, out: str) -> None:
            self._out = out
            self.returncode = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, *args, **kwargs):
            return (self._out, "")

        def kill(self):
            pass

        def wait(self):
            return 0

    def fake_launch_owned(cmd, **kwargs):
        pi._count_provider_spawn()
        out = EXEC_HELP_0_167_0 if "--help" in cmd else FEATURES_0_167_0
        return FakeProcess(out)

    monkeypatch.setattr(
        pi, "_seat_command_profile",
        lambda argv, **k: contextlib.nullcontext((list(argv), pi.SeatProfile(env=dict(k["env"])))),
    )
    monkeypatch.setattr(pi, "launch_owned", fake_launch_owned)

    counter = pi._SpawnCounter()
    with pi._bind_spawn_counter(counter):
        verdict = seat_profile_codex.codex_admission_gate(
            "codex", {"HOME": str(home)}, True, executable=Path("/prepared/bin/codex"), dependency=dep,
        )
        assert verdict is None
        assert counter.count == 0
        # Ordinary run_provider (default count_spawn=True) still increments the counter.
        done = pi.run_provider(["/prepared/bin/codex", "exec", "--help"], env={}, capture_output=True, text=True)
        assert done.returncode == 0
        assert counter.count == 1

    # Claude SDK proof bindings must remain intact (no edits to hashed proof regions).
    repo_root = Path(__file__).resolve().parents[2]
    bindings = claude_seat_transport.sdk_proof_bindings(
        lambda rel: (repo_root / rel).read_bytes() if (repo_root / rel).is_file() else None
    )
    assert bindings


# ---------------------------------------------------------------------------
# 5. Doctor ordering in seat_admission._base_verdict & caller env threading
# ---------------------------------------------------------------------------


def test_seat_admission_runs_shared_checks_before_vendor_gates_and_threads_env(tmp_path, monkeypatch):
    gate_calls = []

    def spy_gate(leg, env, execute):
        gate_calls.append((leg, dict(env), execute))
        return seat_admission._refuses(leg, "codex_seat_cli_shape")

    monkeypatch.setitem(seat_admission._GATES, "codex", [spy_gate])
    monkeypatch.setattr(seat_profile_codex.time, "time", lambda: NOW)

    # 1. Host incapable refuses BEFORE calling vendor gate.
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: "seat_sandbox_unavailable_host")
    v1 = seat_admission.verdict("codex", {}, execute=True)
    assert v1.status == "refuses" and v1.code == "seat_sandbox_unavailable_host"
    assert gate_calls == []

    # 2. Missing credential in caller env refuses BEFORE vendor gate even when os.environ HOME has auth.
    host_home = tmp_path / "host-home"
    host_auth = host_home / ".codex/auth.json"
    host_auth.parent.mkdir(parents=True)
    host_auth.write_text(json.dumps(_login()), encoding="utf-8")
    host_auth.chmod(0o600)
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)

    v2 = seat_admission.verdict("codex", {"HOME": str(empty_home)}, execute=True)
    assert v2.status == "refuses" and v2.code == "codex_seat_credential_missing"
    assert gate_calls == []

    # 3. Missing pass record stops at unknown/launch_measurement BEFORE vendor gate.
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: True)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: None)
    subject = seat_subject.SeatSubject("codex", "standalone", tmp_path / "codex", None, None)
    monkeypatch.setattr(seat_subject, "resolve_seat_subject", lambda *a: subject)
    monkeypatch.setattr(seat_jail, "pass_record_verdict", lambda *a, **k: (False, "no_record"))

    v3 = seat_admission.verdict("codex", {"HOME": str(host_home)}, execute=True)
    assert v3.status == "unknown" and v3.reason == "launch_measurement"
    assert gate_calls == []

    # 4. Once shared checks and pass record succeed, vendor gate runs last.
    monkeypatch.setattr(seat_jail, "pass_record_verdict", lambda *a, **k: (True, "ok"))
    v4 = seat_admission.verdict("codex", {"HOME": str(host_home)}, execute=True)
    assert v4.status == "refuses" and v4.code == "codex_seat_cli_shape"
    assert len(gate_calls) == 1


# ---------------------------------------------------------------------------
# 6. Qualification explicit provider= rejection & _run_probe_in_jail cleanup
# ---------------------------------------------------------------------------


def test_qualify_codex_rejects_explicit_provider_before_host_checks(monkeypatch):
    monkeypatch.setattr(
        seat_jail_qualification.seat_uid,
        "seat_uid_available",
        lambda: pytest.fail("should reject explicit provider before host checks"),
    )
    with pytest.raises(seat_jail_qualification.QualificationError, match="explicit provider"):
        seat_jail_qualification.qualify("codex", provider=Path("/tmp/fake-codex"))


def test_run_probe_in_jail_closes_owned_dependency_on_setup_failure_and_keeps_borrowed_open(
    tmp_path, monkeypatch,
):
    from phase_loop_runtime import panel_invoker as panel

    closed_owned: list[bool] = []
    closed_borrowed: list[bool] = []
    entries = [SimpleNamespace(kind="file", destination=p) for p in codex_runtime.CODEX_RUNTIME_DESTINATIONS]

    def fail_revalidate():
        raise RuntimeError("boom during jail build")

    owned_dep = SimpleNamespace(
        _jailcore_owned=True,
        subject_source=str(tmp_path / "codex"),
        entries=entries,
        subject_destination=codex_runtime.CODEX_RUNTIME_DESTINATIONS[0],
        revalidate=fail_revalidate,
        close=lambda: closed_owned.append(True),
    )
    borrowed_dep = SimpleNamespace(
        _jailcore_owned=False,
        subject_source=str(tmp_path / "codex"),
        entries=entries,
        subject_destination=codex_runtime.CODEX_RUNTIME_DESTINATIONS[0],
        revalidate=fail_revalidate,
        close=lambda: closed_borrowed.append(True),
    )
    subject = seat_subject.SeatSubject("codex", "managed_release", tmp_path / "codex", None, None)

    monkeypatch.setattr(panel, "_resolved_jail_subject", lambda *a: (subject, owned_dep))
    with pytest.raises(RuntimeError, match="boom during jail build"):
        seat_jail_qualification._run_probe_in_jail("codex", tmp_path / "p1", None, 1, "print(1)")
    assert closed_owned == [True]

    monkeypatch.setattr(panel, "_resolved_jail_subject", lambda *a: (subject, borrowed_dep))
    with pytest.raises(RuntimeError, match="boom during jail build"):
        seat_jail_qualification._run_probe_in_jail("codex", tmp_path / "p2", None, 1, "print(1)")
    assert closed_borrowed == []


# ---------------------------------------------------------------------------
# 7. Round 1 review regression pins (Findings 1-4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["output_file", "auth_refresh", "live_stdout", "clean_deadline"])
def test_exec_jailed_codex_real_liveness_latch_cancel_preserves_containment_readbacks(
    tmp_path, monkeypatch, case,
):
    """Real _run_leg_with_liveness + _ProviderQuiescenceLatch cancel must still read back
    seat output/auth and report containment refusals before cancelling or raising."""
    seat = prepare(tmp_path / case, monkeypatch)
    local_reads(monkeypatch)
    ready = tmp_path / f"ready-{case}"
    secret = seat.codex_copy.secrets[0]
    out_file = seat.seat_dir / "seat-out/panel-codex.txt"
    auth_file = seat.seat_dir / "seat-home/.codex/auth.json"

    if case == "output_file":
        body = (
            f"open({str(out_file)!r}, 'wb').write({secret!r}); "
            f"open({str(ready)!r}, 'w').write('ok'); "
            "import time; time.sleep(30)"
        )
    elif case == "auth_refresh":
        body = (
            f"open({str(auth_file)!r}, 'w').write('{{}}'); "
            f"open({str(ready)!r}, 'w').write('ok'); "
            "import time; time.sleep(30)"
        )
    elif case == "live_stdout":
        body = (
            f"import sys, time; sys.stdout.buffer.write({secret!r} + b'\\n'); sys.stdout.buffer.flush(); "
            f"open({str(ready)!r}, 'w').write('ok'); "
            "time.sleep(30)"
        )
    else:
        body = (
            f"open({str(ready)!r}, 'w').write('ok'); "
            "import time; time.sleep(30)"
        )

    def launch(argv, **kwargs):
        return subprocess.Popen(
            [sys.executable, "-c", body],
            stdin=kwargs["stdin"],
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
            start_new_session=True,
        )

    monkeypatch.setattr(pi, "launch_provider", launch)
    latch = pi._ProviderQuiescenceLatch()

    def trigger_cancel():
        deadline = time.monotonic() + 5.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        if case == "live_stdout":
            time.sleep(0.05)
        latch.cancel()

    canceller = threading.Thread(target=trigger_cancel, daemon=True)
    canceller.start()
    sink: list[pi._LegFailure] = []
    try:
        if case == "clean_deadline":
            with pytest.raises(pi._ReviewOperationCancelled):
                pi._exec_jailed_codex_leg(
                    seat, deadline_s=20, model="gpt-5.4", prompt="review",
                    broker_evidence={}, failure_detail_sink=sink, quiescence_latch=latch,
                )
        else:
            status, review = pi._exec_jailed_codex_leg(
                seat, deadline_s=20, model="gpt-5.4", prompt="review",
                broker_evidence={}, failure_detail_sink=sink, quiescence_latch=latch,
            )
            expected = (
                "codex_seat_token_refreshed_in_jail"
                if case == "auth_refresh"
                else "codex_seat_token_in_output"
            )
            assert (status, review) == ("DEGRADED", "")
            assert sink and sink[-1].template == expected
    finally:
        canceller.join(timeout=5)


def test_default_spawn_bounded_codex_passes_board_cancel_event_to_broker(tmp_path, monkeypatch):
    """Bounded jailed Codex legs (review_monitor=None) must forward _BOARD_CANCEL to the broker."""
    monkeypatch.setattr(pi, "_gc_stale_panel_scratch", lambda: None)
    released = []
    lease = SimpleNamespace(seat_id=7, release=lambda: released.append(True))
    route = SimpleNamespace(jailed=True, lease=lease)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (route, [], None))
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda _: 42)
    monkeypatch.setattr(
        pi._seat_egress_proxy, "start_proxy",
        lambda **k: contextlib.nullcontext(SimpleNamespace(socket="fixture", proxy_url="fixture")),
    )
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda _: {})
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", lambda **k: contextlib.nullcontext(("fixture",)))
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda **k: {})
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(pi._sandbox_policy, "ensure_staging_space", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_retention, "mark_as_sandbox", lambda *a, **k: None)

    def staged(repo, review):
        tree = Path(review) / "pl-panel-stage-fixture"
        (tree / ".git").mkdir(parents=True)
        (tree / ".git/phase-loop-source-commit").write_text("c" * 40)
        return tree

    monkeypatch.setattr(pi._review_stage, "stage_review_tree", staged)
    monkeypatch.setattr(
        pi._sandbox_policy, "select_sandbox_root",
        lambda **k: pi._sandbox_policy.SandboxRootChoice(host=None, path=k["fallback"], fell_back=False, reason=""),
    )
    monkeypatch.setattr(pi, "_bind_route_qualification", lambda seat, route: seat)
    monkeypatch.setattr(pi, "_prepare_jailed_codex", lambda *a, **k: SimpleNamespace(notices=[]))
    monkeypatch.setattr(pi, "_exec_jailed_codex_leg", lambda *a, **k: ("UNAVAILABLE", ""))

    board_cancel = threading.Event()
    observed_cancel_events = []

    class FakeBroker:
        def __init__(self, *args, **kwargs):
            self.evidence: dict[str, object] = {}
            self._cancel_event = threading.Event()
            self._shutdown_disposition: str | None = None

        def run_credentialless_client(self, adapter, *, deadline_s=None, cancel_event=None):
            observed_cancel_events.append((deadline_s, cancel_event))
            assert cancel_event is board_cancel
            board_cancel.set()
            self._cancel_event = cancel_event
            self._shutdown_disposition = "operation_cancelled"
            adapter.cancel()
            adapter.invoke()
            self.evidence["broker_failure_disposition"] = "operation_cancelled"
            raise ValueError("credentialless broker client failed: broker operation cancelled or closed")

        def close(self):
            pass

    monkeypatch.setattr(pi, "ParentUnixBroker", FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(
        pi, "derive_review_leg_authorization",
        lambda *a, **k: SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12),
    )
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a: (False, "missing_claude_cli"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    token = pi._BOARD_CANCEL.set(board_cancel)
    try:
        spawned = pi._default_spawn(
            "codex", "ARTIFACT", mode="review", model="m",
            review_authorization=SimpleNamespace(staged_tree_sha256="a" * 64),
            canonical_repo_authority=tmp_path,
        )
    finally:
        pi._BOARD_CANCEL.reset(token)

    assert len(observed_cancel_events) == 1
    assert observed_cancel_events[0][0] is not None
    assert observed_cancel_events[0][1] is board_cancel
    assert spawned[0] == "UNAVAILABLE"
    assert spawned[1] == ""
    assert isinstance(spawned[2], pi._LegFailure)
    assert spawned[2].template == "review_operation_cancelled"
    assert released == [True]


@pytest.mark.parametrize("trigger", ["cancelled", "deadline"])
def test_await_client_captures_already_exited_abnormal_status_end_to_end(tmp_path, monkeypatch, trigger):
    """If the client already exited non-zero before cleanup signals it, _await_client must
    capture exit_status so the broker never assigns a clean typed disposition."""
    real_await = advisor_backing._await_client
    assert real_await.__name__ == "_await_client"

    class AlreadyDeadProc:
        def __init__(self) -> None:
            self.pid = os.getpid()
            self.returncode = 2
            self.stdin = None
            self.stdout = None
            self.stderr = None

        def poll(self):
            return 2

        def communicate(self, *args, **kwargs):
            return (b"", b"")

    proc = AlreadyDeadProc()
    wait = real_await(
        proc,
        b"req",
        failed=lambda: False,
        cancelled=lambda: trigger == "cancelled",
        started=0.0,
        deadline_s=None if trigger == "cancelled" else 1.0,
        clock=lambda: 100.0,
        clock_ns=lambda: 123456,
    )
    assert wait.exit_status == 2
    assert wait.exit_ns == 123456
    assert (wait.cancelled if trigger == "cancelled" else wait.timed_out) is True

    # Also verify end-to-end through run_credentialless_client with the real _await_client.
    live_cancel = threading.Event()
    repo = tmp_path / "e2e-repo"
    repo.mkdir()
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    stage = tmp_path / "e2e-stage"
    stage.mkdir()
    bundle = stage / "review-bundle.md"
    instructions = stage / "review-instructions.md"
    bundle.write_text("bundle\n", encoding="utf-8")
    instructions.write_text("instructions\n", encoding="utf-8")
    bundle.chmod(0o444)
    instructions.chmod(0o444)
    import hashlib

    now_ns = time.monotonic_ns()
    auth = advisor_backing.ReviewLegAuthorization(
        operation="op-e2e",
        purpose="review",
        input_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        instructions_sha256=hashlib.sha256(instructions.read_bytes()).hexdigest(),
        canonical_repo_sha256=advisor_backing._canonical_repo_digest(repo),
        broker_contract=advisor_backing.PARENT_UNIX_BROKER_V1,
        harness="codex",
        model="gpt-5.4",
        issued_monotonic_ns=now_ns,
        expires_monotonic_ns=now_ns + 60_000_000_000,
        _seal=advisor_backing._AUTHORIZATION_SEAL,
        monitoring_policy="heartbeat_only" if trigger == "cancelled" else "bounded",
    )
    lease = (
        SimpleNamespace(
            lock=threading.Lock(), active=True, closed=False, cancel_event=live_cancel,
        )
        if trigger == "cancelled"
        else None
    )
    advisor_backing._remember_leg_claim(auth, lease)
    broker2 = advisor_backing.ParentUnixBroker(
        authorization=auth,
        harness="codex",
        model="gpt-5.4",
        staged_dir=stage,
        canonical_repo=repo,
    )

    class FakeWitness:
        info_fd = 10
        block_fd = 11

        def abandon(self):
            pass

        def complete(self, *args, **kwargs):
            pass

    from phase_loop_runtime import provider_tree_proof

    monkeypatch.setattr(provider_tree_proof, "BwrapLaunch", FakeWitness)
    monkeypatch.setattr(advisor_backing.subprocess, "Popen", lambda *a, **k: AlreadyDeadProc())
    monkeypatch.setattr(pi, "_terminate_process_group", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_tree_quiescent", lambda *a, **k: True)
    monkeypatch.setattr(broker2, "serve_once", lambda *a, **k: None)
    base_time = time.monotonic()
    calls = [0]

    def fake_monotonic():
        calls[0] += 1
        return base_time if calls[0] == 1 else base_time + 100.0

    if trigger == "cancelled":
        def trigger_cancel_await(*args, **kwargs):
            live_cancel.set()
            return real_await(*args, **kwargs)

        monkeypatch.setattr(advisor_backing, "_await_client", trigger_cancel_await)
    else:
        monkeypatch.setattr(advisor_backing.time, "monotonic", fake_monotonic)

    adapter = advisor_backing._make_broker_inference_adapter(
        lambda: ("OK", "done"), lambda: None, lambda: True,
    )
    try:
        with pytest.raises(ValueError, match="credentialless broker client failed"):
            broker2.run_credentialless_client(
                adapter,
                deadline_s=None if trigger == "cancelled" else 1.0,
                cancel_event=live_cancel if trigger == "cancelled" else None,
            )
        assert "broker_failure_disposition" not in broker2.evidence
    finally:
        broker2.close()


@pytest.mark.parametrize("disposition", ["operation_cancelled", "deadline_exceeded"])
def test_broker_recv_request_frame_distinguishes_local_shutdown_from_peer_truncation(disposition):
    """Local typed shutdown during recv() raises _BrokerShutdownStop cleanly; peer EOF before
    local shutdown (including racing with _conn_lock) stays ValueError('truncated broker frame');
    untyped shutdown exits with OSError."""
    # 1. Local typed shutdown while server is waiting for request bytes -> _BrokerShutdownStop
    broker = _make_stub_broker()
    now_ns = time.monotonic_ns()
    auth = advisor_backing.ReviewLegAuthorization(
        operation="op-recv",
        purpose="review",
        input_sha256="0" * 64,
        instructions_sha256="0" * 64,
        canonical_repo_sha256="0" * 64,
        broker_contract=advisor_backing.PARENT_UNIX_BROKER_V1,
        harness="codex",
        model="gpt-5.4",
        issued_monotonic_ns=now_ns,
        expires_monotonic_ns=now_ns + 60_000_000_000,
        _seal=advisor_backing._AUTHORIZATION_SEAL,
        monitoring_policy="bounded",
    )
    advisor_backing._remember_leg_claim(auth, None)
    broker.authorization = auth

    server_sock, peer_sock = socket.socketpair()
    try:
        broker._connection = server_sock

        def wake():
            time.sleep(0.05)
            broker._wake_server(disposition=disposition)

        t = threading.Thread(target=wake, daemon=True)
        t.start()
        try:
            with pytest.raises(advisor_backing._BrokerShutdownStop):
                broker._recv_request_frame(server_sock, 4096)
        finally:
            t.join(timeout=2)
    finally:
        server_sock.close()
        peer_sock.close()

    # 2. Peer closes socket (truncating request) BEFORE local shutdown -> ValueError('truncated broker frame')
    broker2 = _make_stub_broker()
    broker2.authorization = auth
    server_sock2, peer_sock2 = socket.socketpair()
    try:
        broker2._connection = server_sock2
        peer_sock2.close()
        with pytest.raises(ValueError, match="truncated broker frame"):
            broker2._recv_request_frame(server_sock2, 4096)
    finally:
        server_sock2.close()

    # 3. Peer EOF inside recv() racing with _wake_server(disposition=...) waiting on _conn_lock
    broker3 = _make_stub_broker()
    broker3.authorization = auth
    in_recv = threading.Event()
    waker_started = threading.Event()

    class RacingTruncatedSocket:
        def setblocking(self, flag: bool) -> None:
            pass

        def recv(self, size: int) -> bytes:
            in_recv.set()
            assert waker_started.wait(timeout=2)
            time.sleep(0.05)
            return b""

        def shutdown(self, how: int) -> None:
            pass

    conn3 = RacingTruncatedSocket()
    broker3._connection = conn3

    def wake3():
        assert in_recv.wait(timeout=2)
        waker_started.set()
        broker3._wake_server(disposition=disposition)

    t3 = threading.Thread(target=wake3, daemon=True)
    t3.start()
    try:
        with pytest.raises(ValueError, match="truncated broker frame"):
            broker3._recv_request_frame(conn3, 4096)
    finally:
        t3.join(timeout=2)

    # 4. Untyped shutdown exits with OSError
    broker4 = _make_stub_broker()
    broker4.authorization = auth
    server_sock4, peer_sock4 = socket.socketpair()
    try:
        broker4._connection = server_sock4

        def wake4():
            time.sleep(0.05)
            broker4._wake_server()

        t4 = threading.Thread(target=wake4, daemon=True)
        t4.start()
        try:
            with pytest.raises(OSError, match="broker stopping"):
                broker4._recv_request_frame(server_sock4, 4096)
        finally:
            t4.join(timeout=2)
    finally:
        server_sock4.close()
        peer_sock4.close()


# ---------------------------------------------------------------------------
# 8. Round 2 review regression pins (accept cancel, pre-set board cancel, fd>=1024)
# ---------------------------------------------------------------------------


def test_broker_cancel_before_client_connect_exits_accept_without_quiescence_error(tmp_path, monkeypatch):
    """Cancelling while serve_once is waiting in accept() must interrupt quickly without
    timing out the 2s server join or raising ProviderProcessGroupQuiescenceError."""
    live_cancel = threading.Event()
    broker = _run_mocked_broker_client(
        tmp_path,
        monkeypatch,
        wait_result=advisor_backing._ClientWait(completed=False, timed_out=False, cancelled=True),
        serve_fn=None,
        returncode=-15,
        cancel_event=live_cancel,
        deadline_s=5.0,
    )
    # Restore the real serve_once (real listening AF_UNIX socket, no client ever connects!).
    real_serve = advisor_backing.ParentUnixBroker.serve_once
    monkeypatch.setattr(broker, "serve_once", lambda *a, **k: real_serve(broker, *a, **k))

    def slow_cancel_await(*args, **kwargs):
        time.sleep(0.08)
        live_cancel.set()
        return advisor_backing._ClientWait(completed=False, timed_out=False, cancelled=True)

    monkeypatch.setattr(advisor_backing, "_await_client", slow_cancel_await)
    adapter = advisor_backing._make_broker_inference_adapter(
        lambda: ("OK", "done"), lambda: None, lambda: True,
    )
    started = time.monotonic()
    try:
        with pytest.raises(ValueError, match="credentialless broker client failed"):
            broker.run_credentialless_client(adapter, deadline_s=5.0, cancel_event=live_cancel)
        elapsed = time.monotonic() - started
        assert elapsed < 1.5, f"accept() waited too long: {elapsed:.2f}s"
        assert broker.evidence["broker_thread_quiescent"] is True
        assert broker.evidence["broker_failure_disposition"] == "operation_cancelled"
    finally:
        broker.close()


def test_preset_bounded_board_cancel_at_broker_entry_yields_unavailable_not_degraded(tmp_path, monkeypatch):
    """A bounded _BOARD_CANCEL already set before broker.run_credentialless_client starts
    must yield UNAVAILABLE / review_operation_cancelled, never DEGRADED."""
    pre_cancel = threading.Event()
    pre_cancel.set()
    broker = _run_mocked_broker_client(
        tmp_path,
        monkeypatch,
        wait_result=advisor_backing._ClientWait(completed=False, timed_out=False, cancelled=True),
        returncode=-15,
        cancel_event=pre_cancel,
        deadline_s=5.0,
    )
    adapter = advisor_backing._make_broker_inference_adapter(
        lambda: ("OK", "done"), lambda: None, lambda: True,
    )
    try:
        with pytest.raises(ValueError) as caught:
            broker.run_credentialless_client(adapter, deadline_s=5.0, cancel_event=pre_cancel)
        assert type(caught.value) is ValueError
        assert broker.evidence["broker_failure_disposition"] == "operation_cancelled"
    finally:
        broker.close()

    # Now verify through _default_spawn using a broker that raises exactly as above.
    monkeypatch.setattr(pi, "_gc_stale_panel_scratch", lambda: None)
    released = []
    lease = SimpleNamespace(seat_id=7, release=lambda: released.append(True))
    route = SimpleNamespace(jailed=True, lease=lease)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (route, [], None))
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda _: 42)
    monkeypatch.setattr(
        pi._seat_egress_proxy, "start_proxy",
        lambda **k: contextlib.nullcontext(SimpleNamespace(socket="fixture", proxy_url="fixture")),
    )
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda _: {})
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", lambda **k: contextlib.nullcontext(("fixture",)))
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda **k: {})
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(pi._sandbox_policy, "ensure_staging_space", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_retention, "mark_as_sandbox", lambda *a, **k: None)

    def staged(repo, review):
        tree = Path(review) / "pl-panel-stage-fixture"
        (tree / ".git").mkdir(parents=True)
        (tree / ".git/phase-loop-source-commit").write_text("c" * 40)
        return tree

    monkeypatch.setattr(pi._review_stage, "stage_review_tree", staged)
    monkeypatch.setattr(
        pi._sandbox_policy, "select_sandbox_root",
        lambda **k: pi._sandbox_policy.SandboxRootChoice(host=None, path=k["fallback"], fell_back=False, reason=""),
    )

    class PreCancelledBroker:
        def __init__(self, *args, **kwargs):
            self.evidence: dict[str, object] = {}
            self._cancel_event = threading.Event()
            self._shutdown_disposition: str | None = None

        def run_credentialless_client(self, adapter, *, deadline_s=None, cancel_event=None):
            assert cancel_event is pre_cancel
            self.evidence["broker_failure_disposition"] = "operation_cancelled"
            raise ValueError("broker operation cancelled or closed")

        def close(self):
            pass

    monkeypatch.setattr(pi, "ParentUnixBroker", PreCancelledBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(
        pi, "derive_review_leg_authorization",
        lambda *a, **k: SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12),
    )
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a: (False, "missing_claude_cli"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    token = pi._BOARD_CANCEL.set(pre_cancel)
    try:
        spawned = pi._default_spawn(
            "codex", "ARTIFACT", mode="review", model="m",
            review_authorization=SimpleNamespace(staged_tree_sha256="a" * 64),
            canonical_repo_authority=tmp_path,
        )
    finally:
        pi._BOARD_CANCEL.reset(token)
    assert spawned[0] == "UNAVAILABLE"
    assert spawned[1] == ""
    assert isinstance(spawned[2], pi._LegFailure)
    assert spawned[2].template == "review_operation_cancelled"
    assert released == [True]


def test_broker_frame_io_supports_high_numbered_socket_descriptors():
    """poll()-based waits in _recv_request_frame and _send_response_frame work when fd >= 1024."""
    import fcntl
    import resource
    import struct

    soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft <= 1030:
        pytest.skip("RLIMIT_NOFILE too low for fd >= 1024 test")

    broker = _make_stub_broker()
    now_ns = time.monotonic_ns()
    auth = advisor_backing.ReviewLegAuthorization(
        operation="op-highfd",
        purpose="review",
        input_sha256="0" * 64,
        instructions_sha256="0" * 64,
        canonical_repo_sha256="0" * 64,
        broker_contract=advisor_backing.PARENT_UNIX_BROKER_V1,
        harness="codex",
        model="gpt-5.4",
        issued_monotonic_ns=now_ns,
        expires_monotonic_ns=now_ns + 60_000_000_000,
        _seal=advisor_backing._AUTHORIZATION_SEAL,
        monitoring_policy="bounded",
    )
    advisor_backing._remember_leg_claim(auth, None)
    broker.authorization = auth

    s1, s2 = socket.socketpair()
    high_fd = fcntl.fcntl(s1.fileno(), fcntl.F_DUPFD_CLOEXEC, 1024)
    s1.close()
    high_sock = socket.socket(fileno=high_fd)
    try:
        assert high_sock.fileno() >= 1024
        broker._connection = high_sock
        payload = b'{"hello":"highfd"}'

        def delayed_send():
            time.sleep(0.05)
            s2.sendall(struct.pack("!I", len(payload)) + payload)

        sender = threading.Thread(target=delayed_send, daemon=True)
        sender.start()
        try:
            received = broker._recv_request_frame(high_sock, 4096)
        finally:
            sender.join(timeout=2)
        assert received == payload

        # Also exercise _send_response_frame on the same fd >= 1024 socket.
        broker._send_response_frame(high_sock, b'{"status":"OK"}')
        header = s2.recv(4)
        size = struct.unpack("!I", header)[0]
        assert s2.recv(size) == b'{"status":"OK"}'
    finally:
        high_sock.close()
        s2.close()


# ---------------------------------------------------------------------------
# 9. Round 3 review regression pins (second prelaunch check, 10s accept timeout)
# ---------------------------------------------------------------------------


def test_cancel_between_prelaunch_admission_checks_sets_operation_cancelled_disposition(
    tmp_path, monkeypatch,
):
    """Cancellation firing between the first and second pre-launch admission checks
    must still record broker_failure_disposition='operation_cancelled' and raise plain ValueError."""
    live_cancel = threading.Event()
    broker = _run_mocked_broker_client(
        tmp_path,
        monkeypatch,
        wait_result=advisor_backing._ClientWait(completed=False, timed_out=False, cancelled=True),
        returncode=-15,
        cancel_event=live_cancel,
        deadline_s=5.0,
    )
    orig = broker._admission_remaining
    calls = [0]

    def cancel_after_first():
        calls[0] += 1
        if calls[0] == 1:
            result = orig()
            live_cancel.set()
            return result
        return orig()

    monkeypatch.setattr(broker, "_admission_remaining", cancel_after_first)
    adapter = advisor_backing._make_broker_inference_adapter(
        lambda: ("OK", "done"), lambda: None, lambda: True,
    )
    try:
        with pytest.raises(ValueError) as caught:
            broker.run_credentialless_client(adapter, deadline_s=5.0, cancel_event=live_cancel)
        assert type(caught.value) is ValueError
        assert calls[0] == 2
        assert broker.evidence["broker_failure_disposition"] == "operation_cancelled"
    finally:
        broker.close()


def test_accept_connection_enforces_independent_10s_timeout_under_longer_authorization(monkeypatch):
    """_accept_connection() must time out after 10s even when authorization expires minutes later."""
    broker = _make_stub_broker()
    clock = [1_000_000_000_000]
    auth = advisor_backing.ReviewLegAuthorization(
        operation="op-accept-timeout",
        purpose="review",
        input_sha256="0" * 64,
        instructions_sha256="0" * 64,
        canonical_repo_sha256="0" * 64,
        broker_contract=advisor_backing.PARENT_UNIX_BROKER_V1,
        harness="codex",
        model="gpt-5.4",
        issued_monotonic_ns=clock[0],
        expires_monotonic_ns=clock[0] + 300_000_000_000,  # 5 minutes remaining
        _seal=advisor_backing._AUTHORIZATION_SEAL,
        monitoring_policy="bounded",
    )
    advisor_backing._remember_leg_claim(auth, None)
    broker.authorization = auth

    class SilentListener:
        def setblocking(self, flag: bool) -> None:
            assert flag is False

        def accept(self):
            raise BlockingIOError(errno.EAGAIN, "no client yet")

    broker._sock = SilentListener()
    polls = [0]

    def advance_clock(sock, mask, timeout_s):
        polls[0] += 1
        clock[0] += 6_000_000_000  # advance 6s per poll -> exceeds 10s after 2 polls

    monkeypatch.setattr(advisor_backing.time, "monotonic_ns", lambda: clock[0])
    monkeypatch.setattr(advisor_backing, "_poll_socket", advance_clock)

    with pytest.raises(TimeoutError, match="timed out"):
        broker._accept_connection()
    assert polls[0] == 2
