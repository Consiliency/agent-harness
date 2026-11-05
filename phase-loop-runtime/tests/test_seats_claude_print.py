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


def drive(monkeypatch, script, *, rc=0, stderr="", chunk=None, evidence=None,
          review_monitor=None):
    """Run the REAL ``run_jailed`` with the leg runner replaced by a scripted CLI.
    ``script(session_id)`` returns the stdout bytes; stderr and then stdout are fed through
    the production ``stderr_guard`` and ``stdout_guard`` in chunks, and a guard that stops
    the run ends the feed."""
    seen: dict[str, object] = {}

    def runner(command, *, stdout_guard, input_text, **kwargs):
        seen["command"] = list(command)
        seen["stdin"] = input_text
        seen["kwargs"] = kwargs
        session = command[command.index("--session-id") + 1]
        data = script(session)
        err = stderr.encode("utf-8", errors="surrogatepass")
        stderr_guard = kwargs.get("stderr_guard")
        size = chunk or max(1, len(err))
        for at in range(0, len(err), size):
            if stderr_guard is not None and stderr_guard(err[at:at + size]):
                return pi._LegRun(rc or 1, "", "")
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
                                 failure_detail_sink=sink, review_monitor=review_monitor)
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
    # Nothing may follow the one result: valid, malformed, partial or oversized.
    ("frame-after-result", lambda s: _lines(_init(s), _result(s), {"type": "assistant",
                                                                    "session_id": s})),
    ("unparsed-after-result", lambda s: _lines(_init(s), _result(s)) + b'{"type":"result",\n'),
    ("text-glued-after-result", lambda s: _lines(_init(s), _result(s))
     + b"garbage" + _lines(_result(s, "Another.\n\nAGREE"))),
    ("partial-after-result", lambda s: _lines(_init(s), _result(s)) + b'{"type":"res'),
    ("text-after-result", lambda s: _lines(_init(s), _result(s)) + b"trailing words\n"),
])
def test_nothing_but_one_conforming_result_admits(monkeypatch, name, script):
    status, text, codes, evidence, _seen = drive(monkeypatch, script)
    assert status != "OK" and text == "", name
    assert codes == [cp.RESULT_UNPROVEN], name
    assert evidence["claude_admission"]["outcome"] != "admitted"


@pytest.mark.parametrize("chunk", [None, 5])
def test_an_oversized_frame_after_the_result_trips_the_one_result_rule(monkeypatch, chunk):
    monkeypatch.setattr(cp, "LINE_CAP_BYTES", 2048)
    status, text, codes, _e, _s = drive(
        monkeypatch, lambda s: _lines(_init(s), _result(s)) + b'{"pad":"' + b"p" * 4096 + b'"}\n',
        chunk=chunk)
    assert (status, text, codes) == ("DEGRADED", "", [cp.RESULT_UNPROVEN])


def test_a_frame_that_does_not_parse_refuses_and_hides_nothing(monkeypatch):
    """A line that opens a frame but does not parse is refused, never skipped."""
    def script(s):
        hidden = json.dumps(_result(s, is_error=True)).encode()[:-1] + b', "n": ' + b"9" * 5000 + b"}\n"
        return _lines(_init(s)) + hidden + _lines(_result(s))

    status, text, codes, _e, _s = drive(monkeypatch, script)
    assert (status, text, codes) == ("DEGRADED", "", [cp.STREAM_UNSAFE])


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


@pytest.mark.parametrize("name, script", [
    ("retry-error-list", lambda s: _lines(_init(s), {"type": "system", "subtype": "api_retry",
                                                            "error": [], "session_id": s}, _result(s))),
    ("retry-error-object", lambda s: _lines(_init(s), {"type": "system", "subtype": "api_retry",
                                                        "error": {"a": 1}, "session_id": s}, _result(s))),
    ("retry-error-number", lambda s: _lines(_init(s), {"type": "system", "subtype": "api_retry",
                                                        "error": 5, "session_id": s}, _result(s))),
    ("result-not-unicode", lambda s: _lines(_init(s)) + json.dumps(_result(s)).encode().replace(
        b"AGREE", b"AGR\\ud800EE") + b"\n"),
])
def test_a_hostile_field_value_is_a_typed_refusal(monkeypatch, name, script):
    status, text, codes, evidence, _s = drive(monkeypatch, script)
    assert (status, text, codes) == ("DEGRADED", "", [cp.STREAM_UNSAFE]), name
    assert evidence["claude_admission"] == {"outcome": "refused", "code": cp.STREAM_UNSAFE}


def test_the_stderr_cap_refuses_the_stream(monkeypatch):
    monkeypatch.setattr(cp, "STDERR_CAP_BYTES", 1024)
    status, text, codes, _e, _s = drive(monkeypatch, lambda s: _lines(_init(s), _result(s)),
                                        stderr="w" * 4096, chunk=512)
    assert (status, text, codes) == ("DEGRADED", "", [cp.STREAM_UNSAFE])


def test_cancel_comes_from_the_monitor_not_from_cli_text(monkeypatch):
    """Text the CLI writes on stderr never decides that the review was cancelled."""
    status, _t, codes, _e, _s = drive(monkeypatch, lambda s: _lines(_init(s)), rc=1,
                                      stderr="review_operation_cancelled")
    assert status == "DEGRADED" and codes == [cp.RESULT_UNPROVEN]

    class _Monitor:
        def __init__(self):
            import threading
            self.cancel = threading.Event()

    monitor = _Monitor()

    def script(s):
        monitor.cancel.set()  # the operator cancels while the CLI runs
        return _lines(_init(s))

    status, text, codes, _e, _s = drive(monkeypatch, script, rc=1, review_monitor=monitor)
    assert (status, text, codes) == ("UNAVAILABLE", "review_operation_cancelled", [])


def test_the_stream_byte_cap_holds_across_many_small_lines(monkeypatch):
    monkeypatch.setattr(cp, "STREAM_CAP_BYTES", 4096)
    filler = {"type": "assistant", "session_id": "x", "message": {"role": "assistant",
                                                                   "content": "y" * 100}}
    status, _t, codes, _e, _s = drive(
        monkeypatch, lambda s: _lines(_init(s), *([filler] * 60), _result(s)), chunk=256)
    assert status == "DEGRADED" and codes == [cp.STREAM_UNSAFE]


def test_a_second_result_stops_the_run_at_once():
    stream = cp.StreamAdmission(token=TOKEN, session_id="s")
    assert stream.feed(_lines(_init("s"), _result("s"))) is False
    assert stream.feed(_lines(_result("s"))) is True
    assert stream.violation == cp.RESULT_UNPROVEN and not stream.admitted(0)


def test_a_partial_frame_after_the_result_stops_the_run_at_once():
    stream = cp.StreamAdmission(token=TOKEN, session_id="s")
    assert stream.feed(_lines(_init("s"), _result("s"))) is False
    assert stream.feed(b"\n  \n") is False  # blank lines are not frames
    assert stream.feed(b'{"type":"res') is True
    assert stream.violation == cp.RESULT_UNPROVEN and not stream.admitted(0)


def test_the_frame_reader_refuses_the_token_in_a_kept_value():
    """The frame reader refuses it at once, before the value is kept."""
    stream = cp.StreamAdmission(token=TOKEN, session_id="s")
    line = json.dumps(_result("s", "x TOKEN_HERE\n\nAGREE")).replace(
        "TOKEN_HERE", _spelled(TOKEN.decode(), {0})).encode() + b"\n"
    assert stream.feed(_lines(_init("s")) + line) is True
    assert stream.violation == cp.TOKEN_IN_OUTPUT and stream.result_text is None


@pytest.mark.parametrize("error", [RecursionError, TypeError, KeyError])
def test_a_parser_failure_is_typed(monkeypatch, error):
    def explode(*_a, **_k):
        raise error("deep")

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


@pytest.mark.parametrize("chunk", [None, 3])
def test_the_token_on_stderr_refuses(monkeypatch, chunk):
    status, _t, codes, _e, _s = drive(monkeypatch, lambda s: _lines(_init(s), _result(s)),
                                      stderr="boom " + TOKEN.decode(), chunk=chunk)
    assert status == "DEGRADED" and codes == [cp.TOKEN_IN_OUTPUT]


def _spelled(token: str, positions) -> str:
    """``token`` with the characters at ``positions`` spelled another way JSON allows."""
    return "".join(f"\\u{ord(ch):04x}" if at in positions else ch for at, ch in enumerate(token))


@pytest.mark.parametrize("positions", [{0}, {17}, set(range(len(TOKEN)))])
@pytest.mark.parametrize("chunk", [None, 7])
def test_the_kept_text_never_carries_the_token(monkeypatch, positions, chunk):
    """Whatever the spelling on the wire, the text the parent would keep never carries the
    token: it is refused, and nothing is returned or kept."""
    def script(s):
        line = json.dumps(_result(s, "see TOKEN_HERE\n\nAGREE")).replace(
            "TOKEN_HERE", _spelled(TOKEN.decode(), positions)).encode() + b"\n"
        assert not seat_jail.contains_secret(line, TOKEN)
        return _lines(_init(s)) + line

    status, text, codes, evidence, _s = drive(monkeypatch, script, chunk=chunk)
    assert (status, text, codes) == ("DEGRADED", "", [cp.TOKEN_IN_OUTPUT])
    assert evidence["claude_admission"] == {"outcome": "refused", "code": cp.TOKEN_IN_OUTPUT}
    assert TOKEN.decode() not in json.dumps(evidence, default=str)


def test_the_returned_text_is_scanned_before_it_is_admitted():
    """The last check before ``OK``: an admitted stream whose kept text carries the token
    is refused, whatever the frame reader concluded."""
    stream = cp.StreamAdmission(token=TOKEN, session_id="s")
    stream.feed(_lines(_init("s"), _result("s")))
    stream.result_text = f"see {TOKEN.decode()}\n\nAGREE"
    assert stream.admitted(0)
    evidence: dict = {}
    sink: list = []
    run = pi._LegRun(0, "", "")
    status, text = cp._outcome(pi, stream, run, False, evidence, sink, seat=_seat())
    assert (status, text) == ("DEGRADED", "")
    assert [getattr(f, "template", None) for f in sink] == [cp.TOKEN_IN_OUTPUT]


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
