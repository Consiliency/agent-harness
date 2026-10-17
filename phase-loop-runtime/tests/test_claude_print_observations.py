"""Synthetic native-schema observations; no provider, account or SDK operation."""
from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import claude_print_observations as co
from . import test_jailed_claude_print as jailed

fake_seat = jailed.fake_seat
_exec = jailed._exec
TOKEN = jailed.TOKEN


SESSION = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
MODEL = "claude-opus-5-5"
FILE = "/seat/tree/pyproject.toml"
TOOL = "toolu_read"


def frames():
    # Wire nesting is from the pinned official CLI decoder, not SDK dataclasses.
    return [
        {"type": "system", "subtype": "init", "session_id": SESSION, "uuid": "init-frame",
         "model": MODEL, "apiKeySource": "none"},
        {"type": "assistant", "session_id": SESSION, "uuid": "assistant-frame",
         "parent_tool_use_id": None, "message": {"id": "msg_opaque", "role": "assistant",
            "model": MODEL, "content": [{"type": "tool_use", "id": TOOL, "name": "Read",
                                          "input": {"file_path": FILE}}]}},
        {"type": "user", "session_id": SESSION, "uuid": "user-frame",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": TOOL,
                                                   "content": "private file contents"}]}},
        {"type": "result", "subtype": "success", "session_id": SESSION, "uuid": "result-frame",
         "is_error": False, "result": "Reviewed.\nAGREE"},
    ]


def wire(events):
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


def observe(events, requested=MODEL):
    stream = pi._ClaudePrintStream(SESSION, requested)
    stream.feed(wire(events))
    stream.finish()
    return stream, stream.observations.snapshot()


def test_native_shapes_and_every_chunk_split():
    data = wire(frames())
    for split in range(len(data) + 1):
        stream = pi._ClaudePrintStream(SESSION, MODEL)
        stream.feed(data[:split])
        stream.feed(data[split:])
        stream.finish()
        observed = stream.observations.snapshot()
        assert stream.result_text == "Reviewed.\nAGREE"
        assert observed["model_status"] == "match"
        assert observed["init_models"] == observed["assistant_models"] == [MODEL]
        assert observed["tools"] == [{"tool_use_id_sha256": sha256(TOOL.encode()).hexdigest(),
            "name": "Read", "path_sha256": sha256(FILE.encode()).hexdigest(),
            "result": "success", "read_completed": True}]
        assert SESSION not in repr(observed) and TOOL not in repr(observed)
        assert FILE not in repr(observed) and "private file contents" not in repr(observed)


@pytest.mark.parametrize("index", [0, 1, 2, 3])
@pytest.mark.parametrize("session", [None, OTHER, 3, {}, []])
def test_foreign_missing_or_typed_sessions_cannot_supply_native_metadata(index, session):
    events = frames()
    events[index]["session_id"] = session
    stream, observed = observe(events)
    assert observed["valid"] is False
    assert observed["rejected_session_count"] == 1
    assert observed["model_status"] == "unproven"
    assert not any(tool["read_completed"] for tool in observed["tools"])
    if index in (0, 3):
        assert stream.violation == "claude_print_session_unproven"
    if index == 3:
        assert observed["result_subtype"] is None


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_duplicate_native_frames_invalidate_proof(index):
    events = frames()
    events.insert(index + 1, copy.deepcopy(events[index]))
    _, observed = observe(events)
    assert observed["valid"] is False
    assert not any(tool["read_completed"] for tool in observed["tools"])


@pytest.mark.parametrize("mutation", ["unknown-id", "result-first", "duplicate-id", "duplicate-result",
    "invalid-id", "nested", "bad-message", "bad-block", "bad-input", "null-error", "wrong-role", "inner-role", "bad-result-content"])
def test_tool_correlation_requires_well_formed_top_level_native_pairs(mutation):
    events = frames()
    use = events[1]["message"]["content"][0]
    result = events[2]["message"]["content"][0]
    if mutation == "unknown-id":
        result["tool_use_id"] = "toolu_other"
    elif mutation == "result-first":
        events[1], events[2] = events[2], events[1]
    elif mutation == "duplicate-id":
        events[1]["message"]["content"].append(copy.deepcopy(use))
    elif mutation == "duplicate-result":
        events[2]["message"]["content"].append(copy.deepcopy(result))
    elif mutation == "invalid-id":
        use["id"] = "x" * 129
    elif mutation == "nested":
        events[1]["parent_tool_use_id"] = "parent"
    elif mutation == "bad-message":
        events[1]["message"] = []
    elif mutation == "bad-block":
        events[1]["message"]["content"] = [None]
    elif mutation == "bad-input":
        use["input"] = []
    elif mutation == "null-error":
        result["is_error"] = None
    elif mutation == "inner-role":
        events[1]["message"]["role"] = "user"
    elif mutation == "bad-result-content":
        result["content"] = 3
    else:
        events[2]["type"] = "assistant"
    _, observed = observe(events)
    assert observed["valid"] is False
    assert not any(tool["read_completed"] for tool in observed["tools"])


@pytest.mark.parametrize("path", ["pyproject.toml", "/etc/passwd", "/seat/tree/../private",
    "/seat/tree//file", "/seat/tree/file\nidentity", "/seat/tree/", 3, {}])
def test_only_canonical_staged_file_paths_are_hashed(path):
    events = frames()
    events[1]["message"]["content"][0]["input"]["file_path"] = path
    _, observed = observe(events)
    assert observed["tools"][0]["path_sha256"] is None
    assert observed["tools"][0]["read_completed"] is False


@pytest.mark.parametrize("case,status", [
    ("missing-assistant", "missing"), ("missing-init-model", "unknown"),
    ("unknown-assistant", "unknown"), ("typed", "unknown"), ("wrong-both", "mismatch"),
    ("wrong-assistant", "contradictory"), ("unknown-request", "unknown"),
    ("dated", "match"), ("prose", "missing"),
])
def test_requested_model_is_distinct_from_native_model(case, status):
    events = frames()
    requested = MODEL
    if case in ("missing-assistant", "prose"):
        events = [events[0], events[3]]
        if case == "prose":
            events[-1]["result"] = f"I used {MODEL} and Read {FILE}.\nAGREE"
    elif case == "missing-init-model":
        del events[0]["model"]
    elif case == "unknown-assistant":
        events[1]["message"]["model"] = "someone@example.invalid"
    elif case == "typed":
        events[1]["message"]["model"] = []
    elif case == "wrong-both":
        events[0]["model"] = events[1]["message"]["model"] = "claude-sonnet-5"
    elif case == "wrong-assistant":
        events[1]["message"]["model"] = "claude-sonnet-5"
    elif case == "unknown-request":
        requested = "opus"
    else:
        requested = events[0]["model"] = events[1]["message"]["model"] = MODEL + "-20261001"
    _, observed = observe(events, requested)
    assert observed["model_status"] == status
    if status != "match":
        assert not any(tool["read_completed"] for tool in observed["tools"])
    assert "someone@example.invalid" not in repr(observed)
    if case == "prose":
        assert observed["tools"] == []


@pytest.mark.parametrize("subtype", sorted(co.RESULT_SUBTYPES - {"success"}) + ["private-error@example.invalid", {}])
def test_error_results_are_diagnostic_and_never_admitted(subtype):
    events = frames()
    events[-1].update(subtype=subtype, is_error=True, errors=["not logged in", "private-error@example.invalid"])
    stream, observed = observe(events)
    assert stream.violation == "claude_print_result_unproven"
    assert stream.result_text is None
    assert observed["result_subtype"] == (subtype if isinstance(subtype, str) and subtype in co.RESULT_SUBTYPES else "unknown")
    assert observed["error_count"] == 2
    assert observed["error_categories"] == ["auth", "unknown"]
    assert "private-error@example.invalid" not in repr(observed)


@pytest.mark.parametrize("error,category", [
    ("authentication_failed", "authentication_failed"), ("billing_error", "billing_error"),
    ("rate_limit", "rate_limit"), ("invalid_request", "invalid_request"),
    ("server_error", "server_error"), ("private error", "unknown"), ({}, "unknown"),
])
def test_assistant_error_labels_are_closed(error, category):
    events = frames()
    events[1]["error"] = error
    _, observed = observe(events)
    assert observed["error_count"] == 1 and observed["error_categories"] == [category]


@pytest.mark.parametrize("error", [{}, []])
def test_malformed_retry_categories_remain_refused(error):
    events = frames()
    events.insert(1, {"type": "system", "subtype": "api_retry", "session_id": SESSION,
                      "error": error})
    stream, observed = observe(events)
    assert stream.violation == "claude_print_result_unproven" and stream.result_text is None
    assert not observed["valid"]
    assert observed["error_categories"] == ["unknown"]


@pytest.mark.parametrize("errors", ["private error", [None], ["x"] * 100])
def test_malformed_and_excess_error_lists_are_bounded(errors):
    events = frames()
    events[-1].update(subtype="error_during_execution", is_error=True, errors=errors)
    _, observed = observe(events)
    assert observed["error_count"] <= co.MAX_ERRORS
    if not isinstance(errors, list) or len(errors) > co.MAX_ERRORS:
        assert not observed["valid"]


def test_all_observer_state_is_bounded():
    observer = co.ClaudePrintObservations(SESSION, MODEL, lambda _: "unknown")
    observer.event(frames()[0])
    for index in range(co.MAX_EVENTS * 2):
        event = frames()[1]
        event["uuid"] = f"event-{index}"
        event["message"]["content"][0]["id"] = f"tool-{index}"
        event["message"]["model"] = f"claude-opus-{index % 99}"
        observer.event(event)
    snapshot = observer.snapshot()
    assert snapshot["truncated"] and not snapshot["valid"]
    assert observer.events == co.MAX_EVENTS
    assert len(observer.tools) == co.MAX_TOOLS
    assert len(observer._uuids) <= co.MAX_EVENTS
    assert len(observer.models["assistant"]) <= co.MAX_MODELS
    assert len(json.dumps(snapshot)) < 20000
    assert not any(tool["read_completed"] for tool in snapshot["tools"])


def test_excess_content_blocks_and_post_result_frames_invalidate_proof():
    events = frames()
    events[1]["message"]["content"] *= co.MAX_BLOCKS + 1
    _, observed = observe(events)
    assert observed["truncated"] and not observed["valid"]
    assert observed["tools"] == []
    events = frames()
    events.append({**events[1], "uuid": "late-frame"})
    _, observed = observe(events)
    assert not observed["valid"]
    assert not any(tool["read_completed"] for tool in observed["tools"])


@pytest.mark.parametrize("case", ["missing-result", "read-error", "other-tool"])
def test_incomplete_or_unrecognized_tools_never_claim_a_completed_read(case):
    events = frames()
    if case == "missing-result":
        del events[2]
    elif case == "read-error":
        events[2]["message"]["content"][0]["is_error"] = True
    else:
        events[1]["message"]["content"][0]["name"] = "private@example.invalid"
    _, observed = observe(events)
    assert observed["model_status"] == "match"
    assert not observed["tools"][0]["read_completed"]
    assert "private@example.invalid" not in repr(observed)


@pytest.mark.parametrize("raw", [b"not-json\n", b"[]\n", b"null\n",
    b'{"type":"ignored", "type":"ignored"}\n'])
def test_malformed_lines_cannot_leave_positive_observer_claims(raw):
    stream = pi._ClaudePrintStream(SESSION, MODEL)
    stream.feed(wire(frames()[:3]) + raw + wire(frames()[3:]))
    assert stream.observations.snapshot()["valid"] is False
    assert not any(tool["read_completed"] for tool in stream.observations.snapshot()["tools"])


def inject(monkeypatch, events, *, rc=0, actual_rc=None, stderr="", timeout=False):
    def run(command, **kwargs):
        session = command[command.index("--session-id") + 1]
        data = wire([{**event, "session_id": session} for event in events])
        assert not kwargs["output_guard"]("stdout", data)
        kwargs["stdout_guard"](data)
        kwargs["process_returncode_sink"].append(rc if actual_rc is None else actual_rc)
        if timeout:
            raise subprocess.TimeoutExpired(command, 1, output=data, stderr=stderr)
        return pi._LegRun(rc, data.decode(), stderr)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)


@pytest.mark.parametrize("case", ["success", "error", "nonzero", "timeout", "missing-model", "mismatch", "missing-tool"])
def test_production_broker_copies_native_diagnostics_without_changing_admission(fake_seat, monkeypatch, case):
    seat, removed = fake_seat
    events = frames()
    rc, actual_rc = 0, 0
    if case == "error":
        events[-1].update(subtype="error_during_execution", is_error=True, errors=["not logged in"])
    elif case == "nonzero":
        rc = actual_rc = 17
    elif case == "timeout":
        events = events[:-1]
        actual_rc = -15
    elif case == "missing-model":
        del events[1]["message"]["model"]
    elif case == "mismatch":
        events[1]["message"]["model"] = "claude-sonnet-5"
    elif case == "missing-tool":
        events[1]["message"]["content"] = [{"type": "text", "text": f"I read {FILE}."}]
        del events[2]
    inject(monkeypatch, events, rc=rc, actual_rc=actual_rc, timeout=case == "timeout")
    evidence = {}
    status, text = _exec(seat, evidence)
    diagnostic = evidence["claude_native_protocol"]
    assert diagnostic["process_returncode"] == actual_rc
    assert len(removed) == 3
    if case in ("error", "nonzero", "timeout"):
        assert status in ("DEGRADED", "TIMEOUT") and text == ""
    else:
        # Observability adds no new admission requirement. Qualification must check
        # model status and the exact expected path receipt in addition to leg status.
        assert status == "OK"
    if case == "error":
        assert diagnostic["result_subtype"] == "error_during_execution"
        assert diagnostic["error_categories"] == ["auth"]
    if case in ("missing-model", "mismatch"):
        assert diagnostic["model_status"] != "match"
        assert not any(tool["read_completed"] for tool in diagnostic["tools"])
    if case == "missing-tool":
        assert diagnostic["model_status"] == "match"
        assert diagnostic["tools"] == []


@pytest.mark.parametrize("location", ["model", "path", "tool-id", "error", "auth-source", "stderr"])
@pytest.mark.parametrize("retained_only", [False, True])
def test_secrets_in_metadata_refuse_before_any_observations(fake_seat, monkeypatch, location, retained_only):
    seat, _ = fake_seat
    events = frames()
    secret = TOKEN.decode()
    stderr = ""
    if location == "model":
        events[1]["message"]["model"] = secret
    elif location == "path":
        events[1]["message"]["content"][0]["input"]["file_path"] = "/seat/tree/" + secret
    elif location == "tool-id":
        events[1]["message"]["content"][0]["id"] = secret
    elif location == "error":
        events[-1]["errors"] = [secret]
    elif location == "auth-source":
        events[0]["apiKeySource"] = secret
    else:
        stderr = secret
    def run(command, **kwargs):
        session = command[command.index("--session-id") + 1]
        data = wire([{**event, "session_id": session} for event in events])
        if not retained_only:
            refused = kwargs["output_guard"]("stdout", data)
            refused = kwargs["output_guard"]("stderr", stderr.encode()) or refused
            assert refused
            return pi._LegRun(-15, "", "provider_output_refused")
        kwargs["stdout_guard"](data)
        return pi._LegRun(0, data.decode(), stderr)
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    evidence, failures = {}, []
    assert _exec(seat, evidence, failure_detail_sink=failures) == ("DEGRADED", "")
    assert evidence["claude_native_protocol"] is None
    assert secret not in repr((evidence, failures))


def test_arbitrary_auth_source_is_not_copied(monkeypatch):
    events = frames()
    events[0]["apiKeySource"] = "person@example.invalid"
    inject(monkeypatch, events)
    observed = {}
    pi._run_claude_print_session(["/synthetic/claude", "--session-id", SESSION], "private prompt",
        env={}, cwd=Path("/tmp"), timeout_s=1, seat_jail=object(), seat_token=TOKEN, observed=observed)
    assert observed["api_key_source"] == "unknown"
    assert "person@example.invalid" not in repr(observed)


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_timeout_retained_secret_blocks_all_diagnostics(monkeypatch, channel):
    def run(command, **kwargs):
        kwargs["stdout_guard"](wire(frames()))
        kwargs["process_returncode_sink"].append(-15)
        raise subprocess.TimeoutExpired(command, 1,
            output=TOKEN if channel == "stdout" else b"",
            stderr=TOKEN if channel == "stderr" else b"")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    observed = {}
    result = pi._run_claude_print_session(["/synthetic/claude", "--session-id", SESSION], "private prompt",
        env={}, cwd=Path("/tmp"), timeout_s=1, seat_jail=object(), seat_token=TOKEN, observed=observed)
    assert result == (1, "", "claude_seat_token_in_output", "") and observed == {}


@pytest.mark.parametrize("timeout", [False, True])
@pytest.mark.usefixtures("owned_review_network")
def test_real_process_returncode_is_recorded_after_reap(tmp_path, timeout):
    # A local Python process, never an account/auth/model executable. Exercise the
    # actual runner finalizer, including the timeout exception's synthetic 124 path.
    sink = []
    command = ["/usr/bin/python3", "-c", "import time; time.sleep(5)" if timeout else "raise SystemExit(17)"]
    kwargs = dict(cwd=tmp_path, env={}, deadline_s=0.1 if timeout else 5,
                  process_returncode_sink=sink)
    if timeout:
        with pytest.raises(subprocess.TimeoutExpired):
            pi._run_leg_with_liveness(command, **kwargs)
        assert len(sink) == 1 and sink[0] < 0
    else:
        result = pi._run_leg_with_liveness(command, **kwargs)
        assert result.returncode == 17 and sink == [17]
