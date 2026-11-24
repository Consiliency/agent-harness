"""agent-harness#1823: a jailed seat's output-scan match is recorded as closed fields only.

When the Gemini or Codex seat's scan finds one of its configured values (the credential copy
or the egress-proxy session value) in the output, the leg is still refused with its unchanged
detail code, and its private ``leg_exec.v1`` record says which configured value matched and
where: the kind, the encoding, the stream, the phase, the allowlisted event, step and tool,
the Gemini field class, the line index and the byte offset. The record omits the value,
its digest and surrounding provider text. No provider is started.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_codex_credential as cred
from phase_loop_runtime import seat_jail

# Fixture values: neither is a credential. Each has three distinct base64 alignments whose
# standard and URL-safe forms differ, so every encoding is distinguishable.
BEARER = b"ya29.a0T4Q461?EDJ?Y8N9J.CD8Z5X>T7VJ~T>JZWM.MS3H"
PROXY = b"prxa25cf145ff3~1235>bc92a97~6a5f"
HEX_PROXY = b"b7c0f2e1a9d34e5f8c1b2a3d4e5f6071"  # the real shape: 32 hex characters

ENCODINGS = [("raw", 0), ("hex", 0), ("HEX", 0),
             ("b64", 0), ("b64", 1), ("b64", 2), ("b64url", 0), ("b64url", 1), ("b64url", 2)]


def _embed(secret: bytes, encoding: str, pad: int) -> bytes:
    if encoding == "raw":
        return secret
    if encoding == "hex":
        return secret.hex().encode()
    if encoding == "HEX":
        return secret.hex().upper().encode()
    encode = base64.b64encode if encoding == "b64" else base64.urlsafe_b64encode
    return encode(b"Q" * pad + secret)


def _expected_offset(line: bytes, secret: bytes) -> int:
    """Where the scan's own forms first occur in ``line`` (the reference the locator must
    agree with)."""
    return min(line.find(form) for form in seat_jail.secret_encodings(secret) if form in line)


def _assert_nothing_secret_derived(record: dict) -> None:
    # `attempt_id` is a random id (uuid4 hex), unrelated to any secret; leaving it out keeps
    # the 6-byte window check below from matching hex by chance.
    encoded = json.dumps({key: value for key, value in record.items() if key != "attempt_id"}).encode()
    for secret in (BEARER, PROXY, HEX_PROXY):
        assert not seat_jail.contains_secret(encoded, secret)
        for form in (secret, *seat_jail.secret_encodings(secret)):
            for start in range(0, len(form) - 5):
                assert form[start:start + 6] not in encoded, form[start:start + 6]
        assert hashlib.sha256(secret).hexdigest()[:12].encode() not in encoded


def _lines(*events) -> list[bytes]:
    return [json.dumps(event).encode() + b"\n" for event in events]


def _tool_line(marker: str, tool: str = "run_command", step: str = "tool",
               event: str = "step_update") -> bytes:
    return json.dumps({"event": event, "step_update": {
        "conversation_id": "c", "step_index": 2, "state": "DONE", "step_type": step,
        "tool_name": tool, "tool_info": {"name": tool, "output": f"env: {marker} tail"}}}).encode() + b"\n"


def _stream(form: bytes, **tool) -> tuple[bytes, int, int]:
    """A three-line agy stream with ``form`` inside the tool step's output: ``(bytes, line
    index, offset of the form's line)``."""
    head = b"".join(_lines(
        {"event": "init", "conversation_id": "c"},
        {"event": "step_update", "step_update": {"conversation_id": "c", "step_index": 0,
                                                 "state": "DONE", "step_type": "user_input"}}))
    line = _tool_line("@@MARK@@", **tool).replace(b"@@MARK@@", form)
    return head + line, 2, len(head)


# ------------------------------------------------------------------ the gemini seat

def _gemini_seat(tmp_path, proxy=PROXY, token=BEARER):
    jail = SimpleNamespace(
        env={"HTTPS_PROXY": f"http://srt:{proxy.decode()}@127.0.0.1:3128"} if proxy else {},
        profile_digest="d", profile_id="p", filter_digest="f",
        redacted_owner=lambda: [], pass_fds=())
    return pi._JailedSeat(jail=jail, probe_jail=jail, holder_pid=1, token=token,
                          review_dir=tmp_path, seat_dir=tmp_path, expires_at=None)


def _gemini_leg(monkeypatch, tmp_path, chunks, *, stderr=b"", live=True, proxy=PROXY,
                token=BEARER, decode_errors="strict"):
    """Run the real `_exec_jailed_gemini_leg` over a fake liveness loop that hands every stdout
    chunk to the leg's guard (when ``live``) and stops where the guard says so."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "unavailable")

    def fake(cmd, **kw):
        out = b""
        for chunk in chunks:
            out += chunk
            if live and kw["stdout_guard"](chunk):
                break
        return SimpleNamespace(returncode=-15 if live else 0,
                               stdout=out.decode(errors=decode_errors),
                               stderr=stderr.decode(errors=decode_errors))

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake)
    seat = _gemini_seat(tmp_path, proxy, token)
    sink: list = []

    @pi._retained_leg_exec
    def run(leg):
        return pi._exec_jailed_gemini_leg(seat, deadline_s=60, model="m", prompt="p",
                                          broker_evidence={}, failure_detail_sink=sink)

    result = run("gemini")
    records = list((tmp_path / "state").rglob("leg-*.json"))
    assert len(records) == 1
    return result, sink, json.loads(records[0].read_text())


def _split(data: bytes, offset: int, how: str) -> list[bytes]:
    if how == "one_chunk":
        return [data]
    if how == "line_boundary":
        cut = data.rfind(b"\n", 0, offset) + 1
        return [data[:cut], data[cut:]]
    if how == "inside_form":
        return [data[:offset + 5], data[offset + 5:]]
    return [data[index:index + 1] for index in range(len(data))]  # "bytewise"


@pytest.mark.parametrize("split", ["one_chunk", "line_boundary", "inside_form", "bytewise"])
@pytest.mark.parametrize("encoding,pad", ENCODINGS)
@pytest.mark.parametrize("kind,secret", [("bearer", BEARER), ("proxy_credential", PROXY)])
def test_a_live_match_names_the_kind_encoding_and_position(monkeypatch, tmp_path, kind, secret,
                                                           encoding, pad, split):
    data, line_index, line_start = _stream(_embed(secret, encoding, pad))
    line = data[line_start:]
    offset = _expected_offset(line, secret)
    (status, text), sink, record = _gemini_leg(
        monkeypatch, tmp_path, _split(data, line_start + offset, split))
    assert (status, text) == ("DEGRADED", "")
    assert sink[-1].template == "gemini_seat_token_in_output"  # the public code is unchanged
    assert record["secret_match"] == {
        "secret_kind": kind, "encoding": "hex" if encoding == "HEX" else encoding,
        "stream": "stdout", "phase": "live", "event_type": "step_update", "step_type": "tool",
        "tool_name": "run_command", "line_index": line_index, "byte_offset": offset,
        "field_class": "output",
    }
    # The launch ended (the guard stopped it) and the parent reached the stream checks.
    assert record["refusal"] == "gemini_seat_token_in_output" and record["stage"] == "stream"
    _assert_nothing_secret_derived(record)


@pytest.mark.parametrize("tool_info,expected", [
    ({"parameters": {"CommandLine": ["fixture", "@@MARK@@"]}, "output": "earlier"}, "argv"),
    ({"parameters": {"CommandLine": "earlier"}, "output": "@@MARK@@"}, "output"),
    ({"error": {"message": "@@MARK@@"}}, "diagnostic"),
    ({"unexpected": {"output": "@@MARK@@"}}, "unknown"),
    ({"output": "x" * 8192 + "@@MARK@@"}, "unknown"),
])
@pytest.mark.parametrize("live", [True, False])
def test_gemini_records_the_field_class_at_the_match(monkeypatch, tmp_path, tool_info, expected, live):
    line, = _lines({"event": "step_update", "step_update": {"tool_info": tool_info}})
    data = line.replace(b"@@MARK@@", PROXY)
    cut = data.index(PROXY) + 5
    result, sink, record = _gemini_leg(monkeypatch, tmp_path, [data[:cut], data[cut:]], live=live)
    assert result == ("DEGRADED", "")
    assert sink[-1].template == "gemini_seat_token_in_output"
    assert record["secret_match"]["field_class"] == expected
    _assert_nothing_secret_derived(record)


def test_gemini_board_notice_names_both_credential_kinds():
    from phase_loop_runtime.cli import _board_notices_json

    leg = pi.PanelLegResult(leg="gemini", status="DEGRADED", text="",
                            detail="gemini_seat_token_in_output")
    notice, = _board_notices_json([leg])
    assert "proxy credential" in notice["why"]
    assert "seat token" in notice["why"]


@pytest.mark.parametrize("encoding,expected", [("raw", "raw"), ("hex", "hex"), ("HEX", "hex"),
                                               ("b64", "b64")])
def test_the_real_proxy_shape_is_labelled(monkeypatch, tmp_path, encoding, expected):
    data, _index, start = _stream(_embed(HEX_PROXY, encoding, 0))
    _result, _sink, record = _gemini_leg(monkeypatch, tmp_path, [data], proxy=HEX_PROXY)
    assert record["secret_match"]["secret_kind"] == "proxy_credential"
    assert record["secret_match"]["encoding"] == expected
    assert record["secret_match"]["byte_offset"] == _expected_offset(data[start:], HEX_PROXY)
    _assert_nothing_secret_derived(record)


@pytest.mark.parametrize("tool,expected", [
    (dict(tool="exotic_tool"), {"event_type": "step_update", "step_type": "tool", "tool_name": "other"}),
    (dict(step="planning", tool="view_file"),
     {"event_type": "step_update", "step_type": "other", "tool_name": "view_file"}),
    (dict(event="telemetry"), {"event_type": "other", "step_type": "tool", "tool_name": "run_command"}),
])
def test_a_value_outside_an_allowlist_is_other(monkeypatch, tmp_path, tool, expected):
    data, _index, _start = _stream(BEARER, **tool)
    _result, _sink, record = _gemini_leg(monkeypatch, tmp_path, [data])
    match = record["secret_match"]
    assert {key: match[key] for key in expected} == expected
    raw = json.dumps(record)
    assert "exotic_tool" not in raw and "planning" not in raw and "telemetry" not in raw


def test_an_unparsed_line_and_an_init_event_carry_no_step_or_tool(monkeypatch, tmp_path):
    data = b'{"event": "init", "conversation_id": "c"}\nplain text ' + PROXY + b" more\n"
    _result, _sink, record = _gemini_leg(monkeypatch, tmp_path, [data])
    assert record["secret_match"] | {} == {
        "secret_kind": "proxy_credential", "encoding": "raw", "stream": "stdout", "phase": "live",
        "event_type": "unparsed", "step_type": None, "tool_name": None, "line_index": 1,
        "byte_offset": len(b"plain text "), "field_class": "unknown",
    }
    data = json.dumps({"event": "init", "note": BEARER.decode()}).encode() + b"\n"
    (tmp_path / "init").mkdir()
    _result, _sink, record = _gemini_leg(monkeypatch, tmp_path / "init", [data])
    assert record["secret_match"]["event_type"] == "init"
    assert record["secret_match"]["step_type"] is None and record["secret_match"]["line_index"] == 0


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_an_after_exit_match_names_its_stream(monkeypatch, tmp_path, stream):
    data, line_index, start = _stream(_embed(BEARER, "b64", 1))
    clean = b"".join(_lines({"event": "init", "conversation_id": "c"}))
    chunks, stderr = ([data], b"") if stream == "stdout" else ([clean], b"warn\n" + data)
    (status, _text), sink, record = _gemini_leg(monkeypatch, tmp_path, chunks, stderr=stderr,
                                                live=False)
    assert status == "DEGRADED" and sink[-1].template == "gemini_seat_token_in_output"
    match = record["secret_match"]
    assert (match["stream"], match["phase"], match["encoding"]) == (stream, "post_exit", "b64")
    assert match["line_index"] == (line_index if stream == "stdout" else line_index + 1)
    assert match["byte_offset"] == _expected_offset(data[start:], BEARER)
    assert record["stage"] == "stream" and record["refusal"] == "gemini_seat_token_in_output"
    _assert_nothing_secret_derived(record)


def test_a_clean_leg_records_no_match(monkeypatch, tmp_path):
    clean = b"".join(_lines({"event": "init", "conversation_id": "c"}))
    _result, _sink, record = _gemini_leg(monkeypatch, tmp_path, [clean], live=False)
    assert record["secret_match"] is None


# ------------------------------------------------------------------- the codex seat

def _codex_line(form: bytes, item: str = "command_execution") -> bytes:
    return json.dumps({"type": "item.completed", "item": {
        "id": "item_1", "type": item, "command": "env", "aggregated_output": "@@MARK@@",
        "exit_code": 0, "status": "completed"}}).encode().replace(b"@@MARK@@", form) + b"\n"


def _codex_leg(monkeypatch, tmp_path, *, stdout=(), stderr=(), output=b"AGREE", live=True):
    from phase_loop_runtime import seat_profile_codex

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_cleanup_jailed_seat", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "unavailable")
    monkeypatch.setattr(pi, "_record_executable_dependency_evidence", lambda *a, **k: None)
    monkeypatch.setattr(seat_profile_codex, "jailed_codex_command", lambda inputs: ["codex", "exec"])
    copy = cred.CodexSeatCopy(data=b"{}", secrets=(BEARER,), tokens_sha256="0" * 64,
                              expires_at=int(time.time()) + 3600)
    monkeypatch.setattr(pi._seat_uid, "read_in_h", lambda pid, root, relative, cap: (
        output if relative == "panel-codex.txt" else copy.data))

    def fake(cmd, **kw):
        out = err = b""
        for chunk in stdout:
            out += chunk
            if live and kw["stdout_guard"](chunk):
                break
        for chunk in stderr:
            err += chunk
            if live and kw["stderr_guard"](chunk):
                break
        return SimpleNamespace(returncode=0, stdout=out.decode(), stderr=err.decode())

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake)
    jail = SimpleNamespace(provider_argv0="/seat/bin/codex", profile_digest="d", profile_id="p",
                           filter_digest="f",
                           env={"HTTPS_PROXY": f"http://srt:{PROXY.decode()}@127.0.0.1:3128"})
    seat = SimpleNamespace(codex_copy=copy, jail=jail, probe_jail=jail, holder_pid=1,
                           seat_dir=tmp_path, notices=[])
    sink: list = []

    @pi._retained_leg_exec
    def run(leg):
        return pi._exec_jailed_codex_leg(seat, deadline_s=60, model="m", prompt="p",
                                         broker_evidence={}, failure_detail_sink=sink)

    result = run("codex")
    record = json.loads(next((tmp_path / "state").rglob("leg-*.json")).read_text())
    return result, sink, record


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("kind,secret", [("bearer", BEARER), ("proxy_credential", PROXY)])
def test_the_codex_seat_records_a_live_match_on_either_stream(monkeypatch, tmp_path, kind,
                                                              secret, stream):
    form = _embed(secret, "b64url", 2)
    line = _codex_line(form)
    first = b'{"type":"turn.started"}\n'
    chunks = [first + line[:40], line[40:]]
    result, sink, record = _codex_leg(monkeypatch, tmp_path, **{stream: chunks})
    assert result == ("DEGRADED", "") and sink[-1].template == "codex_seat_token_in_output"
    assert record["secret_match"] == {
        "secret_kind": kind, "encoding": "b64url", "stream": stream, "phase": "live",
        "event_type": "item.completed", "step_type": "command_execution", "tool_name": None,
        "line_index": 1, "byte_offset": _expected_offset(line, secret),
    }
    assert record["refusal"] == "codex_seat_token_in_output"
    _assert_nothing_secret_derived(record)


def test_the_codex_output_file_match_is_after_exit(monkeypatch, tmp_path):
    output = b"Review.\n\nsee " + _embed(PROXY, "hex", 0) + b"\nAGREE"
    clean = b'{"type":"turn.started"}\n'
    result, sink, record = _codex_leg(monkeypatch, tmp_path, stdout=[clean], output=output)
    assert sink[-1].template == "codex_seat_token_in_output"
    match = record["secret_match"]
    assert (match["stream"], match["phase"], match["secret_kind"], match["encoding"]) == (
        "output_file", "post_exit", "proxy_credential", "hex")
    assert (match["line_index"], match["byte_offset"], match["event_type"]) == (2, 4, "unparsed")
    _assert_nothing_secret_derived(record)


def test_a_codex_item_outside_the_allowlist_is_other(monkeypatch, tmp_path):
    line = _codex_line(BEARER, item="exotic_item")
    _result, _sink, record = _codex_leg(monkeypatch, tmp_path, stdout=[line])
    assert record["secret_match"]["step_type"] == "other"
    assert "exotic_item" not in json.dumps(record)


# ------------------------------------------------------------- the closed record field

@pytest.mark.parametrize("change", [
    {"tool_name": "run_command; cat ~/.gemini"}, {"secret_kind": "id_token"}, {"encoding": "b32"},
    {"line_index": -1}, {"byte_offset": True}, {"line_index": "3"}, {"extra": 1},
    {"stream": "stdout|stderr"}, {"stream": "stderr+stdout"},
    {"stream": "stdin"}, {"phase": "later"}, {"event_type": "free text"},
    {"field_class": "free text"}, {"field_class": None},
])
def test_the_record_drops_an_open_descriptor(change):
    valid = {"secret_kind": "bearer", "encoding": "raw", "stream": "stdout", "phase": "live",
             "event_type": "step_update", "step_type": "tool", "tool_name": "run_command",
             "line_index": 3, "byte_offset": None}
    assert pi.leg_exec_record("gemini", 1, [], secret_match=valid)["secret_match"] == valid
    record = pi.leg_exec_record("gemini", 1, [], secret_match={**valid, **change})
    assert record["secret_match"] is None


def test_the_record_drops_a_descriptor_holding_a_leg_secret():
    valid = {"secret_kind": "bearer", "encoding": "raw", "stream": "stdout", "phase": "live",
             "event_type": "step_update", "step_type": "tool", "tool_name": "run_command",
             "line_index": 3, "byte_offset": 0}
    secret = b"run_command"  # a leg secret that happens to equal an allowlisted value
    record = pi.leg_exec_record("gemini", 1, [], secret_match=valid, scan_secrets=(secret,))
    assert record["secret_match"] is None


def test_the_scan_and_its_forms_are_unchanged():
    """The locator reuses the scan's forms: whatever it labels is exactly what
    `contains_secret` matched."""
    for secret in (BEARER, PROXY, HEX_PROXY):
        for form in seat_jail.secret_encodings(secret):
            found = pi._first_secret_form(b"xx" + form + b"yy", (secret,))
            assert found is not None and found[0] == 2
            assert seat_jail.contains_secret(b"xx" + form + b"yy", secret)
    assert pi._first_secret_form(b"nothing here", (BEARER,)) is None


def test_the_cursor_bounds_what_it_holds():
    cap = pi._SECRET_MATCH_HEAD_CAP
    cursor = pi._StreamCursor(keep=64)
    cursor.advance(b"x" * (3 * cap))
    assert len(cursor.lines[-1][2]) == cap
    cursor.advance(b"\n" + b"y" * 10)
    assert cursor.lines[-1] == [1, 3 * cap + 1, b"y" * 10]
    # Only the lines overlapping the retained tail are kept, however many have passed.
    cursor.advance(b"z\n" * 5000)
    assert len(cursor.lines) <= 64 + 1
    assert all(len(head) <= cap for _index, _start, head in cursor.lines)
    assert cursor.lines[-1][0] == 1 + 5000


# ------------------------------------------- fix round 2: exact offsets across the tail

LF_TOKEN = b"zq7Y0b3Kp\nW8xR2mT5vN"  # a synthetic configured value with an LF inside it


@pytest.mark.parametrize("chunking", ["split-at-the-lf", "bytewise"])
def test_a_match_whose_line_began_before_the_retained_tail_keeps_its_offset(
        monkeypatch, tmp_path, chunking):
    """A match starting at byte 100 of line 0 spans a chunk boundary at the LF inside the
    value; the guard's retained tail (4 x 20 bytes) no longer holds the line's start."""
    stream = b"x" * 100 + LF_TOKEN + b" tail\n"
    cut = 100 + LF_TOKEN.index(b"\n") + 1
    assert cut > 4 * len(LF_TOKEN)  # the line start predates the retained bytes
    chunks = ([stream[:cut], stream[cut:]] if chunking == "split-at-the-lf"
              else [stream[index:index + 1] for index in range(len(stream))])
    (status, _text), sink, record = _gemini_leg(monkeypatch, tmp_path, chunks, proxy=None,
                                                token=LF_TOKEN)
    assert status == "DEGRADED" and sink[-1].template == "gemini_seat_token_in_output"
    match = record["secret_match"]
    assert (match["line_index"], match["byte_offset"], match["encoding"]) == (0, 100, "raw")
    assert match["event_type"] == "unparsed"


def test_the_cursor_keeps_every_line_overlapping_the_tail():
    cursor = pi._StreamCursor(keep=16)
    first = b"a" * 30 + b"\nb" + b"\n" + b"cc"          # lines 0..2; line 2 is current
    cursor.advance(first)
    tail = first[-16:]
    window = tail + b"dd"
    # A byte on line 0, which began 30 bytes before the retained tail did.
    line0 = window.index(b"a")
    assert cursor.locate(window, len(tail), line0)[:2] == (0, len(first) - len(tail) + line0)
    assert cursor.locate(window, len(tail), window.index(b"b"))[:2] == (1, 0)
    assert cursor.locate(window, len(tail), window.index(b"cc"))[:2] == (2, 0)
    assert cursor.locate(window, len(tail), window.index(b"dd"))[:2] == (2, 2)


# ------------------------------------------------- fix round 2: across stream joins

def test_a_gemini_match_across_the_stdout_stderr_join_names_both_streams(monkeypatch, tmp_path):
    form = BEARER
    stdout = b'{"event": "init", "conversation_id": "c"}\n' + b"tail " + form[:20]
    stderr = form[20:] + b" rest\n"
    (status, _text), sink, record = _gemini_leg(monkeypatch, tmp_path, [stdout], stderr=stderr,
                                                live=False)
    assert sink[-1].template == "gemini_seat_token_in_output"
    match = record["secret_match"]
    assert (match["stream"], match["phase"]) == ("stdout+stderr", "post_exit")
    assert (match["line_index"], match["byte_offset"]) == (1, len(b"tail "))
    _assert_nothing_secret_derived(record)


@pytest.mark.parametrize("stdout_bytes,stream", [
    (b'{"type":"turn.started"}\n', "output_file+stdout"),
    (b"", "output_file+stderr"),
])
def test_a_codex_match_across_the_output_file_join_names_the_streams(monkeypatch, tmp_path,
                                                                     stdout_bytes, stream):
    form = _embed(PROXY, "hex", 0)
    output = b"Review.\nsee " + form[:30]
    rest = form[30:] + b"\n"
    if stdout_bytes:
        stdout_chunks, stderr_chunks = [rest + stdout_bytes], []
    else:
        stdout_chunks, stderr_chunks = [], [rest]
    _result, sink, record = _codex_leg(monkeypatch, tmp_path, stdout=stdout_chunks,
                                       stderr=stderr_chunks, output=output)
    assert sink[-1].template == "codex_seat_token_in_output"
    match = record["secret_match"]
    assert (match["stream"], match["phase"], match["secret_kind"]) == (stream, "post_exit",
                                                                     "proxy_credential")
    assert (match["line_index"], match["byte_offset"]) == (1, len(b"see "))


def test_after_exit_offsets_address_the_decoded_scan_input(monkeypatch, tmp_path):
    """The after-exit check scans the decoded, redacted, re-encoded output: an invalid raw
    byte before the match (1 byte) is decoded to U+FFFD, which re-encodes to 3 bytes, and the
    offset counts the scan input's bytes, not the raw provider bytes."""
    raw = b"\xff" + BEARER + b"\n"
    (status, _text), _sink, record = _gemini_leg(monkeypatch, tmp_path, [raw], live=False,
                                                 decode_errors="replace")
    assert raw.index(BEARER) == 1
    assert record["secret_match"]["byte_offset"] == 3


# ----------------------------------------------- fix round 2: labels read by structure

def _labels(vendor, line: bytes) -> dict:
    return pi._secret_match_labels(vendor, line)


@pytest.mark.parametrize("line,expected", [
    # Reordered: the step object before the event key.
    (b'{"step_update":{"tool_name":"view_file","step_type":"tool"},"event":"step_update","x":"',
     {"event_type": "step_update", "step_type": "tool", "tool_name": "view_file"}),
    # Nested keys of the same names never win.
    (b'{"event":"step_update","meta":{"event":"init","tool_name":"list_dir","step_type":"user_input"},'
     b'"step_update":{"step_type":"tool","tool_name":"run_command","out":"',
     {"event_type": "step_update", "step_type": "tool", "tool_name": "run_command"}),
    # Out-of-vocabulary parsed values are `other`, not absent.
    (b'{"event":"weird","step_update":{"step_type":7,"tool_name":"future tool","x":"',
     {"event_type": "other", "step_type": "other", "tool_name": "other"}),
    (b'{"event":"step_update","step_update":{"tool_name":{"name":"run_command"},"x":"',
     {"event_type": "step_update", "step_type": None, "tool_name": "other"}),
    # A label the prefix does not establish is null.
    (b'{"note":"', {"event_type": None, "step_type": None, "tool_name": None}),
    (b'{"event":"step_up', {"event_type": None, "step_type": None, "tool_name": None}),
    # Inside an array is not the path.
    (b'{"event":"step_update","list":[{"tool_name":"run_command"}],"x":"',
     {"event_type": "step_update", "step_type": None, "tool_name": None}),
    # An escaped key is the key it decodes to.
    (b'{"\\u0065vent":"init","x":"', {"event_type": "init", "step_type": None, "tool_name": None}),
    (b"plain text ", {"event_type": "unparsed", "step_type": None, "tool_name": None}),
])
def test_gemini_labels_are_read_by_structure(line, expected):
    assert _labels("gemini", line) == {**expected, "field_class": "unknown"}


@pytest.mark.parametrize("line,expected", [
    (b'{"meta":{"type":"item.completed"},"type":"item.started","item":{"id":"i",'
     b'"type":"command_execution","aggregated_output":"',
     {"event_type": "item.started", "step_type": "command_execution", "tool_name": None}),
    (b'{"item":{"type":"reasoning","x":{"type":"command_execution"}},"type":"item.updated","y":"',
     {"event_type": "item.updated", "step_type": "reasoning", "tool_name": None}),
    (b'{"type":"brand.new","item":{"type":"brand new item","x":"',
     {"event_type": "other", "step_type": "other", "tool_name": None}),
])
def test_codex_labels_are_read_by_structure(line, expected):
    assert _labels("codex", line) == expected


def test_the_prefix_reader_is_bounded_and_takes_only_complete_values():
    def fields(text, wanted):
        return pi._json_prefix_fields(text, wanted)[0]

    wanted = frozenset({("a",), ("b", "c")})
    assert fields('{"a":"x","b":{"c":"y"}}', wanted) == {("a",): "x", ("b", "c"): "y"}
    assert fields('{"a":12', wanted) == {}            # a number the prefix may have cut short
    assert fields('{"a":12,"b":{"c":tr', wanted) == {("a",): pi._NOT_A_STRING}
    assert fields('{"a":"x","a":"z"}', wanted) == {("a",): "x"}  # the first occurrence wins
    deep_path = ("k",) * 40 + ("c",)
    deep = '{"k":' * 40 + '{"c":"y"}'
    assert fields(deep, frozenset({deep_path})) == {}   # past the nesting bound: not read
    shallow = '{"k":' * 3 + '{"c":"y"}'
    assert fields(shallow, frozenset({("k",) * 3 + ("c",)})) == {("k",) * 3 + ("c",): "y"}
    assert fields('[{"a":"x"}]', wanted) == {}        # the top level must be an object


# ------------------------------------------------------------------------ fix round 3

@pytest.mark.parametrize("literal", ["true", "false", "null"])
def test_a_complete_literal_before_the_match_is_a_parsed_value(literal):
    wanted = frozenset({("type",), ("item", "type")})
    # The prefix ends right after the literal (the match begins at the next comma).
    found, _path = pi._json_prefix_fields('{"type":' + literal, wanted)
    assert found == {("type",): pi._NOT_A_STRING}
    assert _labels("codex", ('{"type":' + literal).encode())["event_type"] == "other"
    assert _labels("gemini", ('{"event":' + literal).encode())["event_type"] == "other"
    # A literal the prefix cut short is not established.
    assert pi._json_prefix_fields('{"type":' + literal[:-1], wanted) == ({}, ())


@pytest.mark.parametrize("prefix,established", [
    ('{"type":12', False),        # a number at the end may continue: not established
    ('{"type":-3.5e', False),
    ('{"type":12,', True),        # a delimiter completes it
    ('{"type":12 ', True),
])
def test_only_a_number_at_the_end_may_be_cut_short(prefix, established):
    found, _path = pi._json_prefix_fields(prefix, frozenset({("type",)}))
    assert (found == {("type",): pi._NOT_A_STRING}) is established


def test_an_output_file_match_uses_the_raw_file_coordinates(monkeypatch, tmp_path):
    """Codex's output file is scanned as its raw bytes: an invalid byte before the match
    counts as one byte there (stdout and stderr would count its re-encoded three)."""
    form = _embed(PROXY, "hex", 0)
    output = b"Review.\n\xffsee " + form + b"\nAGREE"
    _result, sink, record = _codex_leg(monkeypatch, tmp_path, stdout=[b'{"type":"turn.started"}\n'],
                                       output=output)
    assert sink[-1].template == "codex_seat_token_in_output"
    match = record["secret_match"]
    assert (match["stream"], match["line_index"]) == ("output_file", 1)
    assert match["byte_offset"] == len(b"\xffsee ") == 5


def test_a_cross_stream_match_starting_in_the_output_file_uses_its_raw_coordinates(
        monkeypatch, tmp_path):
    form = _embed(PROXY, "hex", 0)
    output = b"Review.\n\xffsee " + form[:30]
    _result, sink, record = _codex_leg(
        monkeypatch, tmp_path, stdout=[form[30:] + b'\n{"type":"turn.started"}\n'], output=output)
    match = record["secret_match"]
    assert match["stream"] == "output_file+stdout"
    assert (match["line_index"], match["byte_offset"]) == (1, 5)

