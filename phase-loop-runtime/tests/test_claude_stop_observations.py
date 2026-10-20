"""Closed print lifecycle observations using synthetic processes and clocks only."""
from __future__ import annotations

import copy
import io
import json
import threading
import types
import uuid

import pytest

from phase_loop_runtime import claude_print_observations as co
from phase_loop_runtime import panel_invoker as pi
from . import test_claude_print_observations as native

fake_seat = native.fake_seat
SESSION, MODEL = native.SESSION, native.MODEL


class Pipe(io.BytesIO):
    def __init__(self, fd):
        super().__init__()
        self.fd = fd

    def fileno(self):
        return self.fd


class Process:
    pid = 900001

    def __init__(self):
        self.returncode = None
        self.stdout, self.stderr, self.stdin = Pipe(71), Pipe(72), Pipe(73)

    def poll(self):
        return self.returncode


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def driver(monkeypatch):
    """Production reader/reducer/finalizer; fake launch, pipes, CPU and reaper.

    Mirrors the offline native-schema controls, without installed-source authority,
    a qualification checker, or a provider/auth operation.
    """
    def drive(payload, *, mode="guard", chunks=None, stderr_chunks=(), failed_reap=False,
              stop_sink=None, observed=None, session=True, broken_clock=False, latch=None, board_seat=None, clock_step=1.0):
        proc, clock, requests = Process(), Clock(), []
        stdout = [c for c in (chunks if chunks is not None else [native.wire(payload)]) if c]
        if not stdout and mode in ("grace", "output_guard"):
            stdout = [b"synthetic"]
        stderr = list(stderr_chunks)
        monitor = types.SimpleNamespace(cancel=threading.Event(), observe=lambda *a, **k: None)
        calls = 0

        def select(fds, *args):
            nonlocal calls
            clock.now += clock_step
            calls += 1
            if mode == "exception":
                raise RuntimeError("synthetic-private-exception")
            if mode == "cancel":
                monitor.cancel.set()
            if mode == "grace":
                return ([71] if calls == 1 else []), [], []
            return list(fds), [], []

        def read(fd, size):
            data = stdout if fd == 71 else stderr
            if mode in ("zero", "nonzero", "external", "grace", "race"):
                proc.returncode = {"zero": 0, "nonzero": 17, "external": -15,
                                   "grace": 0, "race": -15}[mode]
            return data.pop(0) if data else b""

        def terminate(p, *, force_group=False, termination_observed=None):
            # Same existing leader poll as the production reaper, no extra sampler.
            running = p.poll() is None
            pi._observe_termination_state(termination_observed, running)
            requests.append((running, force_group))
            if failed_reap:
                raise pi.ProviderProcessGroupQuiescenceError("synthetic-quiescence")
            if running:
                p.returncode = -15
            if broken_clock:
                clock.monotonic = lambda: (_ for _ in ()).throw(RuntimeError("clock"))

        monkeypatch.setattr(pi, "launch_provider", lambda *a, **k: proc)
        monkeypatch.setattr(pi, "_anchor_process_group", lambda p: None)
        monkeypatch.setattr(pi, "_terminate_process_group", terminate)
        monkeypatch.setattr(pi, "group_cpu_ticks", lambda p: 0)
        monkeypatch.setattr(pi, "time", clock)
        monkeypatch.setattr(pi, "select", types.SimpleNamespace(select=select))
        monkeypatch.setattr(pi, "os", types.SimpleNamespace(read=read))
        # Feed stdin synchronously: the fake pipe never blocks.
        monkeypatch.setattr(pi, "threading", types.SimpleNamespace(
            Thread=lambda target, **kw: types.SimpleNamespace(start=target)))
        monkeypatch.setattr(pi, "uuid", types.SimpleNamespace(uuid4=lambda: uuid.UUID(SESSION), UUID=uuid.UUID))
        monkeypatch.setattr(pi, "_broker_claude_stall_threshold", lambda *a: 3)
        monkeypatch.setattr(pi, "_LEG_POST_EXIT_GRACE_S", 3)
        kwargs = dict(cwd="/synthetic", env={}, seat_jail=object(), probe_jail=object(),
                      quiescence_latch=latch,
                      review_monitor=monitor if mode == "cancel" else None)
        command = ["/synthetic/claude", "--session-id", SESSION]
        if board_seat is not None:
            monkeypatch.setattr(pi, "_broker_claude_tui_command", lambda **kw: [
                "/synthetic/claude", "--ax-screen-reader", "--session-id", SESSION])
            monkeypatch.setattr(pi, "_record_broker_provider_evidence", lambda *a, **kw: None)
            evidence = {}
            result = pi._exec_jailed_claude_print_leg(board_seat, timeout_s=5, backstop_s=20,
                model=MODEL, effort="high", prompt="synthetic", broker_evidence=evidence, env={},
                failure_detail_sink=[], quiescence_latch=latch, review_monitor=None, session_name=None)
        elif session:
            evidence = {} if observed is None else observed
            result = pi._run_claude_print_session(command, "synthetic", timeout_s=5,
                backstop_s=2 if mode == "deadline" else 20, stall_s=3,
                requested_model=MODEL, seat_token=native.TOKEN, observed=evidence, **kwargs)
        else:
            evidence = {} if stop_sink is None else stop_sink
            result = pi._run_leg_with_liveness(command, deadline_s=2 if mode == "deadline" else 20,
                stall_threshold_s=3, stop_observed=evidence,
                output_guard=(lambda *a: True) if mode == "output_guard" else None, **kwargs)
        return result, evidence, requests, proc
    return drive


def rejected_frames():
    events = native.frames()
    retries = [{"type": "system", "subtype": "api_retry", "session_id": SESSION,
                "error": "server_error"} for _ in range(11)]
    events[1:1] = retries
    events[-1]["is_error"] = True
    return events


def test_three_completion_traces_keep_old_projection_and_distinguish_new_fields(driver):
    events = rejected_frames()
    data = native.wire(events)
    rows = [driver(events), driver(events, chunks=[data.rstrip(b"\n")], mode="stall"),
            driver(events, chunks=[data.rstrip(b"\n")], mode="external")]
    protocols = [row[1]["native_protocol"] for row in rows]
    # Strip only the additive fields. Existing observations/admission remain identical.
    added = {"stop", "first_refusal_code", "first_refusal_phase", "refusal_ms",
             "init_session_state", "result_session_state", "result_is_error_state", "result_shape",
             "first_invalid_reason"}
    old = [{k: v for k, v in p.items() if k not in added} for p in protocols]
    assert old[0] == old[1] == old[2]
    assert [r[0][:3] for r in rows] == [(1, "", "claude_print_result_unproven")] * 3
    assert rows[1][0][3] == "[leg-liveness] stalled: no output/CPU for 3s"
    assert [p["stop"]["first_decision"] for p in protocols] == ["stdout_guard", "stall", "process_exit"]
    assert [p["first_refusal_phase"] for p in protocols] == ["feed", "finish", "finish"]
    assert [p["stop"]["termination_leader_state"] for p in protocols] == ["running", "running", "finished"]
    for _, evidence, requests, proc in rows:
        p = evidence["native_protocol"]
        assert p["process_returncode"] == p["stop"]["process_returncode"] == -15
        assert p["first_invalid_reason"] == "retry_replay"
        assert p["result_session_state"] == p["init_session_state"] == "match"
        assert p["result_is_error_state"] == "true" and p["result_shape"] == "string"
        assert p["first_refusal_code"] == "claude_print_result_unproven"
        assert not evidence["session_id_matches"] and evidence["result_event_sha256"] is None
        assert not any(t["read_completed"] for t in p["tools"])
        assert p["refusal_ms"] is not None
        assert p["stop"]["runtime_requested_group_termination"]
        assert requests and proc.stdout.closed and proc.stderr.closed


@pytest.mark.parametrize("split", [0, 1, 20, -1])
@pytest.mark.parametrize("newline", [False, True])
def test_first_refusal_phase_survives_chunking_and_eof(driver, split, newline):
    events = rejected_frames()
    data = native.wire(events)
    if not newline:
        data = data.rstrip(b"\n")
    _, evidence, _, _ = driver(events, chunks=[data[:split], data[split:]], mode="external")
    p = evidence["native_protocol"]
    assert p["first_refusal_phase"] == ("feed" if newline else "finish")
    assert p["first_refusal_code"] == "claude_print_result_unproven"
    assert p["stop"]["first_decision"] == ("stdout_guard" if newline else "process_exit")
    # A request after an already observed exit does not identify a signal sender.
    assert p["stop"]["termination_leader_state"] == "finished"


@pytest.mark.parametrize("mode,decision,rc", [
    ("zero", "process_exit", 0), ("nonzero", "process_exit", 17),
    ("external", "process_exit", -15), ("race", "stdout_guard", -15),
    ("stall", "stall", -15), ("grace", "post_exit_grace", 0),
    ("cancel", "cancel", -15), ("output_guard", "output_guard", -15),
])
def test_first_stop_and_final_receipt_are_separate(driver, mode, decision, rc):
    if mode == "race":
        _, evidence, requests, _ = driver(rejected_frames(), mode=mode)
        p = evidence["native_protocol"]["stop"]
    else:
        _, p, requests, _ = driver([], mode=mode, session=False)
    assert p["first_decision"] == decision
    assert p["process_returncode"] == rc
    assert p["runtime_requested_group_termination"] and requests
    assert p["termination_leader_state"] in ("running", "finished")
    assert type(p["timing_saturated"]) is bool
    for name in ("duration_ms", "deadline_ms", "stall_ms", "decision_ms", "heartbeat_age_ms"):
        assert p[name] is None or type(p[name]) is int and 0 <= p[name] <= co.MAX_OBSERVATION_MS
    if mode == "cancel":
        assert p["deadline_ms"] is p["stall_ms"] is None


def test_hard_deadline_keeps_timeout_even_with_late_refusal(driver):
    result, observed, _, _ = driver(rejected_frames(), mode="deadline",
        chunks=[native.wire(rejected_frames()).rstrip(b"\n")])
    assert result == (124, "", "timeout after 2s", "")
    p = observed["native_protocol"]
    assert p["stop"]["first_decision"] == "deadline"
    assert p["first_refusal_phase"] == "finish"
    assert p["first_refusal_code"] == "claude_print_result_unproven"


def test_primary_exception_keeps_first_decision_and_reaps(driver):
    observed = {}
    with pytest.raises(RuntimeError, match="synthetic-private-exception"):
        driver([], mode="exception", session=False, stop_sink=observed)
    assert observed["first_decision"] == "exception"
    assert observed["process_returncode"] == -15
    assert "synthetic-private-exception" not in json.dumps(observed)


@pytest.mark.parametrize("session", [True, False])
def test_failed_quiescence_suppresses_all_observations(driver, session):
    observed = {}
    with pytest.raises(pi.ProviderProcessGroupQuiescenceError):
        driver(rejected_frames(), failed_reap=True, session=session,
               observed=observed, stop_sink=observed)
    assert observed == {}


class BrokenSink(dict):
    def update(self, *args, **kwargs):
        raise RuntimeError("synthetic sink failure")

    def setdefault(self, *args, **kwargs):
        raise RuntimeError("synthetic sink failure")


def test_optional_sink_and_final_clock_failures_do_not_change_outcome(driver):
    result, _, requests, _ = driver([], mode="zero", session=False, stop_sink=BrokenSink())
    assert result.returncode == 0 and requests
    result, evidence, _, _ = driver(rejected_frames(), observed=BrokenSink())
    assert result == (1, "", "claude_print_result_unproven", "") and evidence == {}
    result, p, _, _ = driver([], mode="zero", session=False, broken_clock=True)
    assert result.returncode == 0 and p["first_decision"] == "process_exit"
    assert p["duration_ms"] is None
    pi._observe_termination_state(BrokenSink(), True)  # cleanup observer is best effort too


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
@pytest.mark.parametrize("encoding", ["raw", "base64", "hex"])
def test_raw_channel_guards_suppress_every_new_field(driver, channel, encoding):
    import base64
    token = {"raw": native.TOKEN, "base64": base64.b64encode(native.TOKEN),
             "hex": native.TOKEN.hex().encode()}[encoding]
    pieces = [token[:7], token[7:]]
    kwargs = {"chunks": pieces} if channel == "stdout" else {"stderr_chunks": pieces}
    result, observed, requests, _ = driver([], **kwargs)
    assert result == (1, "", "claude_seat_token_in_output", "")
    assert observed == {} and requests


@pytest.mark.parametrize("index", [0, 3])
@pytest.mark.parametrize("state,value", [("match", SESSION), ("mismatch", native.OTHER),
    ("missing", "ABSENT"), ("wrong_type", None), ("wrong_type", {}), ("wrong_type", 1)])
def test_session_diagnostic_is_independent_of_admission_latch(index, state, value):
    events = native.frames()
    if value == "ABSENT":
        events[index].pop("session_id")
    else:
        events[index]["session_id"] = value
    stream, _ = native.observe(events)
    assert getattr(stream, "init_session_state" if index == 0 else "result_session_state") == state
    assert stream.session_id_matches is (state == "match")
    if index == 0 and state != "match":
        assert stream.result_session_state == "unseen"
    if state != "match":
        assert stream.refusal_phase == "feed" and stream.violation == "claude_print_session_unproven"


@pytest.mark.parametrize("flag,state", [(False, "false"), (True, "true"), ("ABSENT", "absent"),
    (None, "null"), (0, "wrong_type"), ({}, "wrong_type"), ([], "wrong_type")])
@pytest.mark.parametrize("text,shape", [("Reviewed.\nAGREE", "string"), ("ABSENT", "absent"),
    (None, "null"), ({"private": "unknown prose"}, "other")])
def test_result_flag_and_value_shapes_preserve_legacy_admission(flag, state, text, shape):
    events = native.frames()
    if flag == "ABSENT":
        events[-1].pop("is_error")
    else:
        events[-1]["is_error"] = flag
    if text == "ABSENT":
        events[-1].pop("result")
    else:
        events[-1]["result"] = text
    stream, observed = native.observe(events)
    assert stream.result_is_error_state == state and stream.result_shape == shape
    admitted = (flag is False or state == "absent") and shape == "string"
    assert stream.session_id_matches is admitted
    assert stream.refusal_phase == ("none" if admitted else "feed")
    if flag is not False:
        assert not observed["valid"] or flag is True
    assert "unknown prose" not in json.dumps(observed)


@pytest.mark.parametrize("raw,reason", [(b'not-json\n', "json"), (b'[]\n', "frame_shape"),
    (b'{"type":"x","type":"x"}\n', "duplicate_key"),
    (b'{"type":"x","text":"\xff"}\n', "decode")])
def test_first_malformed_reason_is_closed_and_sticky(raw, reason):
    s = pi._ClaudePrintStream(SESSION, MODEL)
    s.feed(raw + b"not-json\n" + native.wire(native.frames()))
    p = s.observations.snapshot()
    assert p["first_invalid_reason"] == reason
    assert p["model_status"] == "unproven"
    assert not any(t["read_completed"] for t in p["tools"])


@pytest.mark.parametrize("role,index,reason", [("assistant", 1, "assistant_replay"),
    ("user", 2, "user_replay"), ("system", 1, "retry_replay")])
def test_replay_reasons_distinguish_roles(role, index, reason):
    events = native.frames()
    event = copy.deepcopy(events[index]) if role != "system" else {
        "type": "system", "subtype": "api_retry", "session_id": SESSION, "error": "server_error"}
    event.pop("uuid", None)
    events[index:index + (role != "system")] = [event, copy.deepcopy(event)]
    _, p = native.observe(events)
    assert p["first_invalid_reason"] == reason and not p["valid"]


@pytest.mark.parametrize("seconds,expected,capped", [
    (None, None, False), (True, None, False), (-1, None, False),
    (float("nan"), None, False), (float("inf"), None, False),
    ("private", None, False), ({}, None, False), (0, 0, False), (0.0019, 1, False),
    (86400, 86_400_000, False), (86401, 86_400_000, True), (10**1000, 86_400_000, True),
])
def test_relative_milliseconds_are_bounded(seconds, expected, capped):
    assert co.bounded_milliseconds(seconds) == (expected, capped)


def test_three_board_leg_outcomes_keep_the_same_admission(driver, fake_seat):
    seat, removed = fake_seat
    rows = [driver(rejected_frames(), board_seat=seat),
            driver(rejected_frames(), chunks=[native.wire(rejected_frames()).rstrip(b"\n")],
                   mode="stall", board_seat=seat),
            driver(rejected_frames(), chunks=[native.wire(rejected_frames()).rstrip(b"\n")],
                   mode="external", board_seat=seat)]
    assert [r[0] for r in rows] == [("DEGRADED", "")] * 3
    assert [r[1]["claude_native_protocol"]["stop"]["first_decision"] for r in rows] == [
        "stdout_guard", "stall", "process_exit"]
    assert len(removed) == 9


def test_final_latch_failure_suppresses_stop_and_protocol(driver):
    observed = {}
    def fail():
        raise pi.ProviderProcessGroupQuiescenceError("synthetic-latch")
    latch = types.SimpleNamespace(launch=lambda launch: launch(), release=lambda p: None, raise_if_set=fail)
    with pytest.raises(pi.ProviderProcessGroupQuiescenceError, match="synthetic-latch"):
        driver(rejected_frames(), latch=latch, observed=observed)
    assert observed == {}


@pytest.mark.parametrize("reason", sorted(co.INVALID_REASONS))
def test_first_invalid_reason_never_changes_and_never_qualifies_read(reason):
    stream = pi._ClaudePrintStream(SESSION, MODEL)
    stream.feed(native.wire(native.frames()[:3]))
    stream.observations.malformed(reason)
    stream.observations.malformed("json")
    stream.feed(native.wire(native.frames()[3:]))
    p = stream.observations.snapshot()
    assert p["first_invalid_reason"] == reason
    assert not p["valid"] and p["model_status"] == "unproven"
    assert not any(t["read_completed"] for t in p["tools"])
    assert stream.result_text == "Reviewed.\nAGREE"  # diagnostics supply no admission authority


@pytest.mark.parametrize("bound", ["MAX_EVENTS", "MAX_ERRORS", "MAX_MODELS", "MAX_BLOCKS", "MAX_TOOLS",
                                  "MAX_FINGERPRINT_BYTES", "MAX_FINGERPRINT_DEPTH"])
def test_each_existing_observer_bound_has_closed_first_reason(monkeypatch, bound):
    monkeypatch.setattr(co, bound, 0)
    events = native.frames()
    if bound == "MAX_ERRORS":
        events[-1]["is_error"] = True
    _, p = native.observe(events)
    assert p["first_invalid_reason"] == "bounds" and p["truncated"] and not p["valid"]


@pytest.mark.parametrize("field,value,reason", [
    ("session_id", native.OTHER, "session"), ("parent_tool_use_id", "private", "nested_frame"),
    ("uuid", {}, "uuid_shape"), ("message", None, "message_shape"),
])
def test_existing_frame_invalidations_keep_closed_reason(field, value, reason):
    events = native.frames()
    events[1][field] = value
    _, p = native.observe(events)
    assert p["first_invalid_reason"] == reason
    assert "private" not in json.dumps(p)


def test_first_refusal_is_not_replaced_by_later_frames_or_finish():
    stream = pi._ClaudePrintStream(SESSION, MODEL)
    events = native.frames()
    events[0]["apiKeySource"] = "unknown-native-text"
    stream.feed(native.wire(events))
    stream.finish()
    assert stream.violation == "claude_print_subscription_unproven"
    assert stream.refusal_phase == "feed" and stream.result_shape is None
    assert stream.result_session_state == "unseen"
    assert "unknown-native-text" not in json.dumps(stream.observations.snapshot())


def test_clock_sample_saturation_is_explicit_in_the_published_receipt(driver):
    result, p, _, _ = driver([], mode="zero", session=False, clock_step=100000)
    assert result.returncode == 0
    assert p["first_decision"] == "process_exit" and p["timing_saturated"]
    assert p["decision_ms"] == p["duration_ms"] == co.MAX_OBSERVATION_MS


def test_backward_clock_samples_are_unknown(driver):
    result, p, _, _ = driver([], mode="zero", session=False, clock_step=-1)
    assert result.returncode == 0 and p["first_decision"] == "process_exit"
    assert p["decision_ms"] is p["duration_ms"] is p["heartbeat_age_ms"] is None
    assert not p["timing_saturated"]


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("platform", ["posix", "nt"])
def test_termination_state_uses_existing_poll_and_keeps_first_receipt(monkeypatch, running, platform):
    polls = []
    def poll():
        polls.append(True)
        return None if running else -15
    proc = types.SimpleNamespace(pid=900001, poll=poll, terminate=lambda: None,
                                 wait=lambda **kw: None)
    monkeypatch.setattr(pi, "os", types.SimpleNamespace(name=platform, getpgid=lambda p: p))
    monkeypatch.setattr(pi, "_process_group_exists", lambda p: False)
    observed = {}
    pi._terminate_process_group(proc, termination_observed=observed)
    assert len(polls) == (2 if platform == "posix" else 1)
    assert observed == {"termination_leader_state": "running" if running else "finished"}
    proc.poll = lambda: -15 if running else None
    pi._terminate_process_group(proc, termination_observed=observed)
    assert observed == {"termination_leader_state": "running" if running else "finished"}
