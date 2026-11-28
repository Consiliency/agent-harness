"""Regression tests for Consiliency/agent-harness#1929.

Verifies that agy ``--print-timeout`` (``timeout waiting for response``) is named
distinctly (``Gemini broker native print timeout`` under bounded monitoring,
``Gemini broker native timeout under heartbeat-only`` under heartbeat-only) rather
than collapsing into generic ``Gemini broker native exit without an accepted review``,
while preserving security/containment precedence, quoted-timeout safety, healthy
reviews that mention timeouts, and structured exit/stream evidence retention.
"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi


def _jailed_seat(tmp_path, *, expires_at: float | None = None):
    jail = SimpleNamespace(
        env={"HOME": str(tmp_path), "HTTPS_PROXY": "http://u:proxy-secret-1929@127.0.0.1:3128"},
        profile_digest="d" * 64,
        profile_id="gemini-jailed-v1",
        filter_digest="f" * 64,
        redacted_owner=lambda: ("bwrap",),
    )
    return SimpleNamespace(
        token=b"ya29.secret-token-1929",
        private_proxy_token=b"proxy-secret-1929",
        jail=jail,
        probe_jail=None,
        holder_pid=1,
        review_dir=tmp_path / "review",
        seat_dir=tmp_path / "seat",
        image_sha256="a" * 64,
        notices=[],
        admission_class="release_qualified",
        expires_at=expires_at,
    )


def _run_jailed_with(
    monkeypatch,
    tmp_path,
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    expires_at: float | None = None,
    review_monitor=None,
):
    seat = _jailed_seat(tmp_path, expires_at=expires_at)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)

    def fake_run(*_args, native_run=None, **_kwargs):
        if native_run is not None:
            native_run.update(
                native_exit_code=returncode if returncode >= 0 else None,
                native_signal=-returncode if returncode < 0 else None,
                native_stdout_bytes=len(stdout.encode("utf-8")),
                native_stderr_bytes=len(stderr.encode("utf-8")),
            )
        return pi._LegRun(returncode, stdout, stderr)

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_run)
    evidence: dict[str, object] = {}
    sink: list[pi._LegFailure] = []
    status, text = pi._exec_jailed_gemini_leg(
        seat,
        deadline_s=60,
        model="gemini-4-argon",
        prompt="review this bundle",
        broker_evidence=evidence,
        failure_detail_sink=sink,
        review_monitor=review_monitor,
    )
    return status, text, sink, evidence, seat


def test_gemini_native_print_timeout_vocabulary_is_registered_and_valid():
    code = "Gemini broker native print timeout"
    assert code in pi._GEMINI_BROKER_DETAILS
    assert code in pi._HARNESS_DETAIL_CODES
    assert pi._detail_is_valid(code)
    assert pi._finalize_leg_detail(code) == code


def test_jailed_gemini_nonzero_print_timeout_named_distinctly_bounded(monkeypatch, tmp_path):
    status, text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=1,
        stdout="",
        stderr="Error: timeout waiting for response PRIVATE_SENTINEL_1929\n",
    )
    assert (status, text) == ("DEGRADED", "")
    assert sink[-1].template == "Gemini broker native print timeout"
    assert evidence["provider_error_class"] == "timeout"
    assert evidence["provider_stage_reached"] == "launch"
    assert evidence["provider_stream_outcome"] == "session_reset"
    assert "PRIVATE_SENTINEL_1929" not in json.dumps(evidence, default=str)
    assert "PRIVATE_SENTINEL_1929" not in sink[-1].rendered()


def test_jailed_gemini_nonzero_print_timeout_heartbeat_only_uses_heartbeat_code(monkeypatch, tmp_path):
    monitor = SimpleNamespace(cancel=threading.Event())
    status, text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=1,
        stdout="",
        stderr="Error: timeout waiting for response\n",
        review_monitor=monitor,
    )
    assert (status, text) == ("DEGRADED", "")
    assert sink[-1].template == "Gemini broker native timeout under heartbeat-only"
    assert evidence["provider_error_class"] == "timeout"


def test_jailed_gemini_ndjson_result_print_timeout_named_even_after_long_stream(monkeypatch, tmp_path):
    # Longer than 200 chars of valid NDJSON events followed by a failed result carrying the
    # --print-timeout error message must still classify as native print timeout.
    lines = [
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "step_update",
            "step_update": {
                "conversation_id": "conv-1",
                "step_type": "tool",
                "tool_info": {"note": "x" * 300},
            },
        }),
        json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {
                "status": "ERROR",
                "error": {"message": "timeout waiting for response PRIVATE_SENTINEL_1929"},
            },
        }),
    ]
    status, text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=1,
        stdout="\n".join(lines) + "\n",
        stderr="",
    )
    assert (status, text) == ("DEGRADED", "")
    assert sink[-1].template == "Gemini broker native print timeout"
    assert evidence["provider_error_class"] == "timeout"
    assert evidence["provider_stage_reached"] == "terminal_event"
    assert "PRIVATE_SENTINEL_1929" not in json.dumps(evidence, default=str)


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        json.dumps({"event": "init", "conversation_id": "conv-1"}) + "\n"
        + json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {"status": "SUCCESS", "response": ""},
        }) + "\n",
    ],
    ids=["native-timeout-zero-empty-stream", "empty-timeout-empty-success-result"],
)
def test_jailed_gemini_zero_exit_with_print_timeout_stderr_named_distinctly(
    monkeypatch, tmp_path, stdout,
):
    status, text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=0,
        stdout=stdout,
        stderr="Error: timeout waiting for response\n",
    )
    assert (status, text) == ("DEGRADED", "")
    assert sink[-1].template == "Gemini broker native print timeout"
    assert evidence["provider_error_class"] == "timeout"


def test_short_json_success_and_malformed_json_are_not_mistaken_for_print_timeout(
    monkeypatch, tmp_path,
):
    """Round 1 P2 #1: short JSON-shaped stdout quoting `timeout waiting for response`
    must never trigger the plain-CLI fallback."""
    # Short valid SUCCESS JSON quoting timeout, followed by nonzero exit.
    short_success = json.dumps({
        "event": "result",
        "conversation_id": "c1",
        "result": {"status": "SUCCESS", "response": "timeout waiting for response"},
    }) + "\n"
    assert len(short_success) < 200
    status, _text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch, tmp_path, returncode=1, stdout=short_success, stderr="",
    )
    assert status == "DEGRADED"
    assert sink[-1].template == "Gemini broker native exit without an accepted review"
    assert evidence["provider_error_class"] == "unknown"

    # Short malformed JSON quoting timeout on rc=0 keeps its malformed JSON parse detail.
    short_malformed = '{"broken": "timeout waiting for response'
    assert len(short_malformed) < 200
    status, _text, sink, _ev, _seat = _run_jailed_with(
        monkeypatch, tmp_path, returncode=0, stdout=short_malformed, stderr="",
    )
    assert status == "DEGRADED"
    assert sink[-1].template == "Gemini broker stream rejected: malformed JSON"


def test_whitespace_padded_plain_stdout_print_timeout_is_detected(monkeypatch, tmp_path):
    """Round 1 P3: plain CLI diagnostic padded with >400 spaces is still detected."""
    padded = (" " * 500) + "Error: timeout waiting for response\n"
    status, _text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch, tmp_path, returncode=1, stdout=padded, stderr="",
    )
    assert status == "DEGRADED"
    assert sink[-1].template == "Gemini broker native print timeout"
    assert evidence["provider_error_class"] == "timeout"


@pytest.mark.parametrize(
    ("stderr", "expected_class"),
    [
        ("HTTP 401 UNAUTHENTICATED: timeout waiting for response\n", "auth_missing"),
        ("HTTP 429 RESOURCE_EXHAUSTED: timeout waiting for response\n", "quota_exhausted"),
    ],
)
def test_higher_priority_provider_error_class_prevents_print_timeout_mismatch(
    monkeypatch, tmp_path, stderr, expected_class,
):
    """Round 1 P2 #3: when HTTP 401/429 wins precedence over timeout, detail and
    provider_error_class stay aligned instead of contradicting each other."""
    status, _text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch, tmp_path, returncode=1, stdout="", stderr=stderr,
    )
    assert status == "DEGRADED"
    assert evidence["provider_error_class"] == expected_class
    assert sink[-1].template == "Gemini broker native exit without an accepted review"


def test_jailed_gemini_precedence_token_leak_expired_and_containment_beat_print_timeout(
    monkeypatch, tmp_path,
):
    # 1. Token leak beats print timeout.
    status, _text, sink, _ev, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=1,
        stdout="ya29.secret-token-1929",
        stderr="Error: timeout waiting for response\n",
    )
    assert status == "DEGRADED"
    assert sink[-1].template == "gemini_seat_token_in_output"

    # 2. Expired seat token beats print timeout.
    status, _text, sink, _ev, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=1,
        stdout="",
        stderr="Error: timeout waiting for response\n",
        expires_at=1.0,
    )
    assert status == "DEGRADED"
    assert sink[-1].template == "gemini_seat_token_expired"

    # 3. Containment refusal (subagent / unknown event) beats print timeout.
    subagent_stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "step_update",
            "step_update": {
                "conversation_id": "conv-1",
                "step_type": "subagent",
                "subagent_info": {},
            },
        }),
    ]) + "\n"
    status, _text, sink, _ev, seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=0,
        stdout=subagent_stream,
        stderr="Error: timeout waiting for response\n",
    )
    assert status == "DEGRADED"
    assert sink[-1].template == pi._JAILED_GEMINI_UNKNOWN_EVENT
    assert pi._JAILED_GEMINI_UNKNOWN_EVENT in seat.notices


def test_jailed_gemini_healthy_review_quoting_timeout_stays_ok(monkeypatch, tmp_path):
    stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {
                "status": "SUCCESS",
                "response": "Note: agy prints 'timeout waiting for response' when --print-timeout fires.\n\nAGREE",
            },
        }),
    ]) + "\n"
    status, text, sink, _ev, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=0,
        stdout=stream,
        stderr="",
    )
    assert status == "OK"
    assert text.endswith("AGREE")
    assert sink == []


def test_jailed_gemini_quoted_timeout_malformed_json_stays_malformed_json(monkeypatch, tmp_path):
    status, text, sink, _ev, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=0,
        stdout="{{" + ("x" * 220) + " timeout waiting for response",
        stderr="",
    )
    assert (status, text) == ("DEGRADED", "")
    assert sink[-1].template == "Gemini broker stream rejected: malformed JSON"


def test_jailed_gemini_non_timeout_native_exit_keeps_generic_detail_and_retains_facts(
    monkeypatch, tmp_path,
):
    status, text, sink, evidence, _seat = _run_jailed_with(
        monkeypatch,
        tmp_path,
        returncode=7,
        stdout=json.dumps({"event": "init", "conversation_id": "conv-1"}) + "\n",
        stderr="HTTP 429 RESOURCE_EXHAUSTED\n",
    )
    assert (status, text) == ("DEGRADED", "")
    assert sink[-1].template == "Gemini broker native exit without an accepted review"
    assert evidence["provider_error_class"] == "quota_exhausted"
    assert evidence["provider_stage_reached"] == "first_incoming_event"
    assert evidence["provider_stream_incoming_event_count"] == 1
    assert evidence["provider_stream_result_count"] == 0
    assert evidence["provider_stream_outcome"] == "result_count_mismatch"


def test_brokered_bounded_gemini_print_timeout_retries_then_names_print_timeout(
    monkeypatch, tmp_path,
):
    import contextlib

    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    attempts = 0

    @contextlib.contextmanager
    def fake_agy_env(_env, _evidence):
        yield {"HOME": str(tmp_path)}

    monkeypatch.setattr(pi, "_brokered_agy_environment", fake_agy_env)

    def fake_liveness(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return pi._LegRun(1, "", "Error: timeout waiting for response PRIVATE_SENTINEL_1929\n")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    broker_model = pi.harden_subscription_model("gemini", "gemini-4-argon", None)
    rc, text, log = pi._exec_leg(
        "gemini",
        review_dir,
        out_dir,
        timeout_s=60,
        artifact="synthetic artifact",
        mode="review",
        model=broker_model,
        deadline_s=120,
        broker_prompt="review this bundle",
        broker_evidence={},
    )
    assert attempts == 2
    assert rc == 1
    assert text == ""
    assert log == "Gemini broker native print timeout"
    assert type(log) is pi._HarnessCode
    assert log in pi._GEMINI_BROKER_DETAILS
    assert "PRIVATE_SENTINEL_1929" not in log


def test_brokered_bounded_gemini_print_timeout_recovers_on_retry(
    monkeypatch, tmp_path,
):
    import contextlib

    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()
    attempts = 0

    @contextlib.contextmanager
    def fake_agy_env(_env, _evidence):
        yield {"HOME": str(tmp_path)}

    monkeypatch.setattr(pi, "_brokered_agy_environment", fake_agy_env)
    ok_stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {"status": "SUCCESS", "response": "No blocking issues.\n\nAGREE"},
        }),
    ]) + "\n"

    def fake_liveness(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return pi._LegRun(1, "", "Error: timeout waiting for response\n")
        return pi._LegRun(0, ok_stream, "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    broker_model = pi.harden_subscription_model("gemini", "gemini-4-argon", None)
    rc, text, log = pi._exec_leg(
        "gemini",
        review_dir,
        out_dir,
        timeout_s=60,
        artifact="synthetic artifact",
        mode="review",
        model=broker_model,
        deadline_s=120,
        broker_prompt="review this bundle",
        broker_evidence={},
    )
    assert attempts == 2
    assert rc == 0
    assert text.endswith("AGREE")
    assert log == ""


def test_brokered_bounded_zero_exit_empty_timeout_preserves_retry_and_names_timeout(
    monkeypatch, tmp_path,
):
    """Connector P2: zero-exit empty SUCCESS stream + timeout stderr must keep its
    bounded single retry (recovering if retry succeeds, naming print timeout if it repeats)."""
    import contextlib

    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()

    @contextlib.contextmanager
    def fake_agy_env(_env, _evidence):
        yield {"HOME": str(tmp_path)}

    monkeypatch.setattr(pi, "_brokered_agy_environment", fake_agy_env)
    broker_model = pi.harden_subscription_model("gemini", "gemini-4-argon", None)
    empty_stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {"status": "SUCCESS", "response": ""},
        }),
    ]) + "\n"
    ok_stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {"status": "SUCCESS", "response": "Recovered.\n\nAGREE"},
        }),
    ]) + "\n"

    # Case 1: retry recovers -> OK on attempt 2.
    attempts = 0

    def recover_on_second(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return pi._LegRun(0, empty_stream, "Error: timeout waiting for response\n")
        return pi._LegRun(0, ok_stream, "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", recover_on_second)
    rc, text, log = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="synthetic artifact",
        mode="review", model=broker_model, deadline_s=120,
        broker_prompt="review this bundle", broker_evidence={},
    )
    assert attempts == 2 and rc == 0 and text.endswith("AGREE") and log == ""

    # Case 2: both attempts hit empty timeout -> retried once, then named print timeout.
    attempts = 0

    def always_empty_timeout(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return pi._LegRun(0, empty_stream, "Error: timeout waiting for response\n")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", always_empty_timeout)
    rc, text, log = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="synthetic artifact",
        mode="review", model=broker_model, deadline_s=120,
        broker_prompt="review this bundle", broker_evidence={},
    )
    assert attempts == 2 and rc == 1 and text == "" and log == "Gemini broker native print timeout"


def test_brokered_bounded_structured_ndjson_timeout_retries_consistently(
    monkeypatch, tmp_path,
):
    """Round 1 P3: a fast structured NDJSON result timeout with empty stderr and >200-char
    stdout receives the same bounded single retry as stderr timeout."""
    import contextlib

    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()

    @contextlib.contextmanager
    def fake_agy_env(_env, _evidence):
        yield {"HOME": str(tmp_path)}

    monkeypatch.setattr(pi, "_brokered_agy_environment", fake_agy_env)
    broker_model = pi.harden_subscription_model("gemini", "gemini-4-argon", None)
    long_timeout_stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "step_update",
            "step_update": {"conversation_id": "conv-1", "step_type": "user_input", "note": "x" * 250},
        }),
        json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {"status": "ERROR", "error": {"message": "timeout waiting for response"}},
        }),
    ]) + "\n"
    assert len(long_timeout_stream) > 200
    attempts = 0

    def always_ndjson_timeout(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return pi._LegRun(1, long_timeout_stream, "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", always_ndjson_timeout)
    rc, text, log = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="synthetic artifact",
        mode="review", model=broker_model, deadline_s=120,
        broker_prompt="review this bundle", broker_evidence={},
    )
    assert attempts == 2 and rc == 1 and text == "" and log == "Gemini broker native print timeout"


def test_brokered_bounded_preserves_tool_denial_and_stream_refusal_over_timeout(
    monkeypatch, tmp_path,
):
    """Round 1 P2 #2: bounded timeout handling must never mask headless tool denials or
    tool/subagent stream refusals, and must not retry either refusal."""
    import contextlib

    review_dir = tmp_path / "review"
    out_dir = tmp_path / "out"
    review_dir.mkdir()
    out_dir.mkdir()

    @contextlib.contextmanager
    def fake_agy_env(_env, _evidence):
        yield {"HOME": str(tmp_path)}

    monkeypatch.setattr(pi, "_brokered_agy_environment", fake_agy_env)
    broker_model = pi.harden_subscription_model("gemini", "gemini-4-argon", None)

    # 1. Empty SUCCESS result + stderr containing BOTH tool denial AND timeout marker.
    empty_stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "result",
            "conversation_id": "conv-1",
            "result": {"status": "SUCCESS", "response": ""},
        }),
    ]) + "\n"
    attempts = 0

    def denied_with_timeout(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return pi._LegRun(0, empty_stream, "auto-denied tool permission; timeout waiting for response\n")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", denied_with_timeout)
    rc, text, log = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="synthetic artifact",
        mode="review", model=broker_model, deadline_s=120,
        broker_prompt="review this bundle", broker_evidence={},
    )
    assert attempts == 1
    assert rc == 1 and text == ""
    assert log == "Gemini broker denied a tool permission without review text"

    # 2. Rejected tool/subagent stream + timeout marker on stderr.
    tool_stream = "\n".join([
        json.dumps({"event": "init", "conversation_id": "conv-1"}),
        json.dumps({
            "event": "step_update",
            "step_update": {"conversation_id": "conv-1", "step_type": "tool", "tool_info": {}},
        }),
    ]) + "\n"
    attempts = 0

    def tool_stream_with_timeout(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return pi._LegRun(0, tool_stream, "Error: timeout waiting for response\n")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", tool_stream_with_timeout)
    rc, text, log = pi._exec_leg(
        "gemini", review_dir, out_dir, timeout_s=60, artifact="synthetic artifact",
        mode="review", model=broker_model, deadline_s=120,
        broker_prompt="review this bundle", broker_evidence={},
    )
    assert attempts == 1
    assert rc == 1 and text == ""
    assert log == "Gemini broker stream rejected: tool or subagent activity observed"
