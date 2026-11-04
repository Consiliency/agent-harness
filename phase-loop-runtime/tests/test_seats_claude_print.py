"""SEATS CLAUDE lane B: the jailed ``print`` transport (EC-CLAUDE-2; the print-route
record's §4a items 4 and 5).

Every admission control enters through ``claude_seat_print.run_jailed``. The CLI's stdout
is scripted, and it reaches the production reader the way a real one does: chunk by chunk
through the leg runner's ``stdout_guard``. None of the controls may admit. ``live_jail``
runs ``print`` at the real call site in a real jail with a fake subject.
"""

from __future__ import annotations

import base64
import hashlib
import json
import types

import pytest

from phase_loop_runtime import claude_seat_print as cp
from phase_loop_runtime import claude_seat_transport as ct
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail

TOKEN = b"fake-seat-token-" + b"k" * 32
REVIEW = "The change is sound.\n\nAGREE"


def _jail():
    return types.SimpleNamespace(
        leg="claude", provider_argv0="/seat/bin/claude", profile_id="jail",
        profile_digest="d" * 64, filter_digest="f" * 64,
        env={"HOME": "/seat/home", seat_jail.CLAUDE_TOKEN_FD_ENV: "3"},
        redacted_owner=lambda: ["bwrap", "--"], dependency=None, dependency_projection_digest="")


def _seat():
    jail = _jail()
    return types.SimpleNamespace(jail=jail, probe_jail=jail, token=TOKEN, notices=[],
                                 source="login", expires_at=None)


def _init(session, **extra):
    return {"type": "system", "subtype": "init", "apiKeySource": "none", "session_id": session,
            "model": "claude-opus-5-5", **extra}


def _result(session, text=REVIEW, **extra):
    return {"type": "result", "subtype": "success", "is_error": False, "result": text,
            "session_id": session, **extra}


def _lines(*frames) -> bytes:
    return b"".join((frame if isinstance(frame, bytes) else json.dumps(frame).encode()) + b"\n"
                    for frame in frames)


def drive(monkeypatch, script, *, rc=0, stderr="", chunk=None, evidence=None):
    """Run the REAL ``run_jailed`` with the leg runner replaced by a scripted CLI.
    ``script(session_id)`` returns the stdout bytes; they are fed through the production
    ``stdout_guard`` in chunks, and a guard that stops the run ends the feed."""
    seen: dict[str, object] = {}

    def runner(command, *, stdout_guard, input_text, **kwargs):
        seen["command"] = list(command)
        seen["stdin"] = input_text
        seen["kwargs"] = kwargs
        session = command[command.index("--session-id") + 1]
        data = script(session)
        size = chunk or max(1, len(data))
        for at in range(0, len(data), size):
            if stdout_guard(data[at:at + size]):
                return pi._LegRun(rc or 1, "", stderr)
        return pi._LegRun(rc, data.decode("utf-8", errors="replace"), stderr)

    cleaned: list[object] = []
    monkeypatch.setattr(pi, "_run_leg_with_liveness", runner)
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda seat, **k: cleaned.append(seat))
    sink: list[object] = []
    evidence = {} if evidence is None else evidence
    status, text = cp.run_jailed(_seat(), timeout_s=60, backstop_s=60, model=None, effort=None,
                                 prompt="PROMPT", broker_evidence=evidence,
                                 failure_detail_sink=sink)
    assert cleaned, "the seat is always torn down"
    codes = [getattr(f, "template", None) for f in sink]
    return status, text, codes, evidence, seen


# --------------------------------------------------------------------------------------
# §4a item 4: the argv.
# --------------------------------------------------------------------------------------

def test_the_argv_is_the_jailed_tui_command_plus_the_declared_delta(monkeypatch):
    _s, _t, _c, _e, seen = drive(monkeypatch, lambda s: _lines(_init(s), _result(s)))
    command = seen["command"]
    session = command[command.index("--session-id") + 1]
    tui = pi._broker_claude_tui_command(model=None, effort=None, session_id=session,
                                        sandboxed=_jail())
    assert command == [tui[0], *cp.CLI_DELTA, *tui[1:]]
    assert "--bare" not in command and "--no-session-persistence" in command
    assert command[command.index("--tools") + 1] == "default"
    assert command[command.index("--permission-mode") + 1] == "bypassPermissions"
    assert command[command.index("--output-format") + 1] == "stream-json"
    # The prompt goes on stdin, never in the argv.
    assert "PROMPT" not in "\0".join(command)
    assert seen["stdin"].endswith("PROMPT")
    assert seen["kwargs"]["seat_jail"] is seen["kwargs"]["probe_jail"]


def test_the_delta_adds_no_tool_permission_settings_or_credential_flag():
    for token in cp.CLI_DELTA:
        assert token not in ("--tools", "--allowedTools", "--permission-mode", "--settings",
                             "--setting-sources", "--mcp-config", "--agents", "--bare",
                             "--add-dir")
        assert "key" not in token.lower() and "token" not in token.lower()


def test_the_module_is_admitted_with_its_activation_citing_4a():
    assert cp.ADMITTED is True
    assert cp.ACTIVATION == ct.RecordCitation(
        ct.DECISION_RECORD, "4a",
        "7af0fb700ef10d444a904b01169c8b08aa056ba25ca496c7adcca7c646852cdb",
        "agent-harness#1775")
    assert ct.transport_module("print") is cp
    assert ct.resolve_jailed_claude_transport({ct.ROUTE_ENV: "print"}) == ("print", None)


# --------------------------------------------------------------------------------------
# §4a item 5: one admitted result, nothing salvaged.
# --------------------------------------------------------------------------------------

def test_one_conforming_result_admits_and_records_its_evidence(monkeypatch):
    status, text, codes, evidence, _seen = drive(monkeypatch, lambda s: _lines(_init(s), _result(s)))
    assert (status, text, codes) == ("OK", REVIEW, [])
    assert evidence["claude_transport"] == "print"
    assert evidence["claude_admission"] == {"outcome": "admitted", "code": "none"}
    assert evidence["claude_api_key_source"] == "none"
    assert evidence["claude_code_entrypoint"] == "unset"
    assert evidence["jail_profile_digest"] == "d" * 64
    assert evidence["claude_result_count"] == 1
    assert evidence["claude_item7_diagnostics"]["schema"] == "claude-print-observations.v1"


@pytest.mark.parametrize("source", ["ANTHROPIC_API_KEY", "/login managed key",
                                    "helper:custom-source-x", None, ""])
def test_a_key_source_other_than_none_refuses_as_a_security_code(monkeypatch, source):
    def script(s):
        init = _init(s)
        if source is None:
            del init["apiKeySource"]
        else:
            init["apiKeySource"] = source
        return _lines(init, _result(s))

    status, text, codes, evidence, _seen = drive(monkeypatch, script)
    assert (status, text, codes) == ("DEGRADED", "", [cp.API_KEY_SOURCE])
    assert ct.CODES[cp.API_KEY_SOURCE][0] == ct.SECURITY
    if source:
        assert source not in json.dumps(evidence, default=str)


@pytest.mark.parametrize("name, script", [
    ("second-result", lambda s: _lines(_init(s), _result(s), _result(s, "Another.\n\nAGREE"))),
    ("second-result-split", lambda s: _lines(_init(s), _result(s)) + _lines(_result(s))),
    ("second-init", lambda s: _lines(_init(s), _init(s), _result(s))),
    ("no-init", lambda s: _lines(_result(s))),
    ("result-before-init", lambda s: _lines(_result(s), _init(s))),
    ("salvaged-turn", lambda s: _lines(_init(s), {"type": "assistant", "session_id": s,
                                                   "message": {"role": "assistant",
                                                               "content": [{"type": "text",
                                                                            "text": REVIEW}]}})),
    ("error-result", lambda s: _lines(_init(s), _result(s, is_error=True))),
    ("non-success", lambda s: _lines(_init(s), _result(s, subtype="error_max_turns"))),
    ("other-session-result", lambda s: _lines(_init(s), _result("another-session"))),
    ("other-session-init", lambda s: _lines(_init("another-session"), _result(s))),
    ("non-conforming-verdict", lambda s: _lines(_init(s), _result(s, "No verdict here."))),
    ("is-error-as-string", lambda s: _lines(_init(s), _result(s, is_error="false"))),
    ("empty", lambda s: b""),
])
def test_nothing_but_one_conforming_result_admits(monkeypatch, name, script):
    status, text, codes, evidence, _seen = drive(monkeypatch, script)
    assert status != "OK" and text == "", name
    assert codes == [cp.RESULT_UNPROVEN], name
    assert evidence["claude_admission"]["outcome"] != "admitted"


def test_a_nonzero_exit_does_not_admit(monkeypatch):
    status, _t, codes, _e, _s = drive(monkeypatch, lambda s: _lines(_init(s), _result(s)), rc=1)
    assert status == "DEGRADED" and codes == [cp.RESULT_UNPROVEN]


def test_an_auth_retry_drift_stops_the_run(monkeypatch):
    status, _t, codes, _e, _s = drive(monkeypatch, lambda s: _lines(
        _init(s), {"type": "system", "subtype": "api_retry", "error": "billing_error",
                   "session_id": s}, _result(s)))
    assert status == "DEGRADED" and codes == [cp.AUTH_DRIFT]


# --------------------------------------------------------------------------------------
# Stream hardening: each refuses claude_seat_stream_unsafe.
# --------------------------------------------------------------------------------------

def _deep(depth: int) -> dict:
    value: object = "x"
    for _ in range(depth):
        value = {"k": value}
    return value  # type: ignore[return-value]


@pytest.mark.parametrize("name, script", [
    ("byte-cap", lambda s: _lines(_init(s)) + b'{"type":"assistant","pad":"' + b"a" * (cp.STREAM_CAP_BYTES + 1) + b'"}\n'),
    ("line-cap", lambda s: _lines(_init(s)) + b"x" * (cp.LINE_CAP_BYTES + 2)),
    ("invalid-utf8-result", lambda s: _lines(_init(s)) + json.dumps(_result(s)).encode().replace(b"AGREE", b"AGR\xffE") + b"\n"),
    ("invalid-utf8-init", lambda s: json.dumps(_init(s)).encode().replace(b"claude-opus", b"claude-\xc3opus") + b"\n" + _lines(_result(s))),
    ("duplicate-key-result", lambda s: _lines(_init(s)) + json.dumps(_result(s)).encode().replace(b'"is_error": false', b'"is_error": true, "is_error": false') + b"\n"),
    ("duplicate-key-init", lambda s: json.dumps(_init(s)).encode().replace(b'"apiKeySource": "none"', b'"apiKeySource": "x", "apiKeySource": "none"') + b"\n" + _lines(_result(s))),
    ("nesting-result", lambda s: _lines(_init(s), _result(s, extra=_deep(cp.NESTING_BOUND + 5)))),
    ("nesting-system", lambda s: _lines(_init(s, extra=_deep(cp.NESTING_BOUND + 5)), _result(s))),
    ("recursion", lambda s: _lines(_init(s)) + b'{"type":"result","x":' + b"[" * 200_000 + b"]" * 200_000 + b"}\n"),
])
def test_each_hardening_case_refuses_the_stream(monkeypatch, name, script):
    status, text, codes, _e, _s = drive(monkeypatch, script, chunk=1 << 20)
    assert (status, text) == ("DEGRADED", ""), name
    assert codes == [cp.STREAM_UNSAFE], name


def test_a_parser_recursion_error_is_typed(monkeypatch):
    def explode(*_a, **_k):
        raise RecursionError("deep")

    monkeypatch.setattr(cp.json, "loads", explode)
    status, _t, codes, _e, _s = drive(monkeypatch, lambda s: _lines(_init(s), _result(s)))
    assert status == "DEGRADED" and codes == [cp.STREAM_UNSAFE]


# --------------------------------------------------------------------------------------
# The token is scanned for in everything the parent keeps.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("encode", [
    lambda t: t, lambda t: base64.b64encode(t), lambda t: t.hex().encode(),
    lambda t: base64.urlsafe_b64encode(b"x" + t),
])
@pytest.mark.parametrize("chunk", [None, 7])
def test_the_token_in_any_frame_refuses_and_is_never_kept(monkeypatch, encode, chunk):
    leaked = encode(TOKEN).decode()
    status, text, codes, evidence, _s = drive(
        monkeypatch, lambda s: _lines(_init(s), _result(s, f"see {leaked}\n\nAGREE")), chunk=chunk)
    assert (status, text, codes) == ("DEGRADED", "", [cp.TOKEN_IN_OUTPUT])
    assert TOKEN.decode() not in json.dumps(evidence, default=str)
    assert leaked not in json.dumps(evidence, default=str)


def test_the_token_on_stderr_refuses(monkeypatch):
    status, _t, codes, _e, _s = drive(monkeypatch, lambda s: _lines(_init(s), _result(s)),
                                      stderr="boom " + TOKEN.decode())
    assert status == "DEGRADED" and codes == [cp.TOKEN_IN_OUTPUT]


def test_a_token_wins_over_an_earlier_violation():
    stream = cp.StreamAdmission(token=TOKEN, session_id="s")
    stream.feed(_lines(_init("s", apiKeySource="ANTHROPIC_API_KEY")))
    assert stream.violation == cp.API_KEY_SOURCE
    stream.violation = None
    stream.feed(_lines(_init("s")))
    stream._stop(cp.STREAM_UNSAFE)
    stream._stop(cp.TOKEN_IN_OUTPUT)
    assert stream.violation == cp.TOKEN_IN_OUTPUT


# --------------------------------------------------------------------------------------
# live_jail: `print` at the real call site in a real jail.
# --------------------------------------------------------------------------------------

def test_live_jail_print_admits_one_result_from_the_jailed_subject(monkeypatch, tmp_path):
    from test_seats_claude_transport import _argv_shape, live_call_site, require_live_jail

    require_live_jail()
    with monkeypatch.context() as m:
        base = tmp_path / "tui"
        base.mkdir()
        _s, tui_observed, _e, _t = live_call_site(m, base, "tui")
    with monkeypatch.context() as m:
        base = tmp_path / "print"
        base.mkdir()
        spawned, observed, evidence, token = live_call_site(m, base, "print")
    status, text = tuple(spawned)[:2]
    assert (status, text) == ("OK", "observed\n\nAGREE")
    leg = observed["seat:leg"]
    assert leg["token_sha256"] == hashlib.sha256(token).hexdigest()
    tui_shape = _argv_shape(tui_observed["seat:leg"]["argv"])
    print_shape = _argv_shape(leg["argv"])
    assert print_shape == [*cp.CLI_DELTA, *tui_shape]
    assert evidence["claude_admission"] == {"outcome": "admitted", "code": "none"}
    assert evidence["claude_transport"] == "print"
