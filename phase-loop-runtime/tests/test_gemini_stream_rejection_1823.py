"""agent-harness#1823: a jailed Gemini seat whose tooled stream is refused with
``gemini_seat_subagent_or_unknown_event`` says, in its private ``leg_exec.v1`` record, what
kind of line was refused -- closed names, counts and positions only, never a line, a value or
provider text. The parser is a validator-closure entry point and is not touched: a separate
helper re-reads the retained stdout with the same rules. A jailed leg whose provider exited 0
but whose output the seat refused is ``leg_execution_refused``, not completed.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import types
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_jail

UNKNOWN = pi._JAILED_GEMINI_UNKNOWN_EVENT
#: Text that must never reach a record: every value and every unlisted name in the streams
#: below carries it.
SENTINEL = "zq7-sentinel-value"
_CONVERTER = Path(__file__).resolve().parents[1] / "scripts" / "convert_agy_record_v2.py"

_INIT = {"event": "init", "conversation_id": "c", "init": {
    "model": f"m-{SENTINEL}", "cwd": f"/{SENTINEL}", "tools": [SENTINEL],
    "permission_mode": "request-review"}}
_RESULT = {"event": "result", "result": {"conversation_id": "c", "status": "SUCCESS",
                                         "response": f"{SENTINEL}\nAGREE"}}


def _step(**fields):
    return {"event": "step_update", "step_update": {"conversation_id": "c", **fields}}


_TOOL = _step(step_index=1, state="DONE", step_type="tool", tool_name="run_command",
              tool_info={"name": "run_command", "parameters": {"CommandLine": SENTINEL}})
_TEXT = _step(step_index=2, state="DONE", step_type="agent_response", text_delta=SENTINEL)


def _stream(*lines, init=_INIT, result=_RESULT):
    rows = [*([init] if init is not None else []), *lines, *([result] if result else [])]
    return "\n".join(row if isinstance(row, str) else json.dumps(row) for row in rows) + "\n"


def _parse(raw):
    protocol = pi._broker_gemini_stream_protocol("prompt", tooled=True)
    return pi._broker_gemini_stream_result(raw, protocol, tooled=True)


def _descriptor(raw):
    rc, _text, detail, _ = _parse(raw)
    assert (rc, detail) == (1, UNKNOWN)
    found = pi._jailed_gemini_stream_rejection(raw)
    assert found is not None and pi._stream_rejection_valid(found)
    return found


# ---------------------------------------------------------------------------------------
# Each reason.
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(("line", "reason", "event", "step_type"), [
    ({"event": "error", "error": {"message": SENTINEL}}, "unknown_event", "error", None),
    (_step(step_index=3, state="DONE", text_delta=SENTINEL), "bad_step_type", "step_update", None),
    (_step(step_type="browser"), "bad_step_type", "step_update", "browser"),
    (_step(step_type="subagent", tool_name="invoke_subagent"), "bad_step_type",
     "step_update", "subagent"),
    (_step(step_type="subagent", tool_name="invoke_subagent", subagent_info={}),
     "bad_step_type", "step_update", "subagent"),
    (_step(step_type="agent_response", subagent_info=None), "subagent_info",
     "step_update", "agent_response"),
    (_step(step_type="tool", state="DONE", tool_name="browser_subagent"), "refused_tool",
     "step_update", "tool"),
])
def test_each_reason_is_recorded(line, reason, event, step_type):
    found = _descriptor(_stream(_TOOL, line, _TEXT))
    assert found["reason"] == reason
    assert (found["event_type"], found["step_type"]) == (event, step_type)
    assert found["line_index"] == 2 and found["line_count"] == 5
    assert found["rejected_lines"] == 1


@pytest.mark.parametrize("step", [
    {"step_type": "workflow", "subagent_info": None},
    {"step_type": "subagent", "tool_name": "invoke_subagent", "subagent_info": {}},
    {"subagent_info": {"name": "n"}},                       # no step type at all
    {"step_type": 7, "subagent_info": {}},
    {"step_type": SENTINEL, "subagent_info": [SENTINEL]},
])
def test_a_step_matching_both_rules_gets_the_rule_the_parser_hits_first(step):
    # The parser's predicate is `step_type not in recorded or "subagent_info" in step`: an
    # unrecorded step type short-circuits it, so the key is never what refused the line.
    found = _descriptor(_stream(_step(**step)))
    assert found["reason"] == "bad_step_type"
    assert "subagent_info" in found["step_keys"]  # key presence is kept separately


@pytest.mark.parametrize("step_type", sorted(pi._JAILED_GEMINI_STEP_TYPES))
def test_a_recorded_step_type_with_subagent_info_is_the_subagent_info_rule(step_type):
    found = _descriptor(_stream(_step(step_type=step_type, subagent_info={})))
    assert found["reason"] == "subagent_info" and found["step_type"] == step_type


@pytest.mark.parametrize("step", [
    {"step_type": "tool", "subagent_info": None}, {"step_type": "browser"},
    {"step_type": "subagent", "subagent_info": {}}, {"subagent_info": {}}, {},
    {"step_type": None, "subagent_info": {}}, {"step_type": "user_input", "subagent_info": 1},
])
def test_the_reason_is_the_parsers_first_matching_rule(step):
    found = _descriptor(_stream(_step(**step)))
    expected = ("bad_step_type" if step.get("step_type") not in pi._JAILED_GEMINI_STEP_TYPES
                else "subagent_info")
    assert found["reason"] == expected


def test_an_absent_step_type_is_null_and_its_count_is_absent():
    found = _descriptor(_stream(_TOOL, _step(step_index=3, state="DONE")))
    assert found["step_type"] is None and "step_type" not in found["step_keys"]
    assert found["step_counts"] == {"absent": 1, "tool": 1}


# ---------------------------------------------------------------------------------------
# Allowlisted names, `other` outside them.
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(("field", "line", "hit"), [
    ("event_type", {"event": "warning"}, "warning"),
    ("step_type", _step(step_type="background_task"), "background_task"),
    ("tool_name", _step(step_type="subagent", tool_name="define_subagent"), "define_subagent"),
    ("state", _step(step_type="finish", state="ERROR"), "ERROR"),
])
def test_an_allowlisted_name_is_kept(field, line, hit):
    assert _descriptor(_stream(line))[field] == hit


@pytest.mark.parametrize(("field", "line"), [
    ("event_type", {"event": SENTINEL}),
    ("step_type", _step(step_type=SENTINEL)),
    ("step_type", _step(step_type=7)),
    ("tool_name", _step(step_type="subagent", tool_name=SENTINEL)),
    ("tool_name", _step(step_type="subagent", tool_name={"name": SENTINEL})),
    ("state", _step(step_type="finish", state=SENTINEL)),
])
def test_a_name_outside_its_allowlist_is_other(field, line):
    found = _descriptor(_stream(line))
    assert found[field] == "other"
    assert SENTINEL not in json.dumps(found)


def test_a_field_of_an_unknown_event_is_null():
    found = _descriptor(_stream({"event": "notice", "tool_name": SENTINEL}))
    assert (found["step_type"], found["tool_name"], found["state"]) == (None, None, None)
    assert found["step_keys"] is None and found["subagent_info_keys"] is None
    assert found["line_keys"] == ["event", "other"]


# ---------------------------------------------------------------------------------------
# Key presence.
# ---------------------------------------------------------------------------------------

def test_key_presence_is_names_from_the_allowlists():
    line = {"event": "step_update", "conversation_id": "c", SENTINEL: 1,
            "step_update": {"conversation_id": "c", "step_type": "subagent",
                            "tool_name": "invoke_subagent", f"{SENTINEL}-a": 1,
                            f"{SENTINEL}-b": 2, "subagent_info": {
                                "conversation_id": SENTINEL, "name": SENTINEL,
                                "model": SENTINEL, SENTINEL: SENTINEL}}}
    found = _descriptor(_stream(line))
    assert found["line_keys"] == ["conversation_id", "event", "other", "step_update"]
    assert found["step_keys"] == ["conversation_id", "other", "step_type", "subagent_info",
                                  "tool_name"]
    assert found["subagent_info_keys"] == ["conversation_id", "model", "name", "other"]
    assert SENTINEL not in json.dumps(found)


@pytest.mark.parametrize(("info", "keys"), [({}, []), (None, None), ([SENTINEL], None)])
def test_subagent_info_keys_distinguish_empty_from_not_an_object(info, keys):
    found = _descriptor(_stream(_step(step_type="agent_response", subagent_info=info)))
    assert found["subagent_info_keys"] == keys
    assert "subagent_info" in found["step_keys"]


# ---------------------------------------------------------------------------------------
# The init line's mode.
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(("payload", "line", "modes"), [
    ({"permission_mode": "request-review"}, {}, {"permission_mode": "request-review"}),
    ({"permission_mode": "always-proceed", "agent_mode": "auto"}, {},
     {"agent_mode": "auto", "permission_mode": "always-proceed"}),
    ({"agentMode": ""}, {}, {"agentMode": "empty"}),
    ({"mode": SENTINEL}, {}, {"mode": "other"}),
    ({"agent_mode": None}, {}, {"agent_mode": "other"}),
    ({}, {"mode": "plan"}, {"mode": "plan"}),
    ({"mode": "auto"}, {"mode": "plan"}, {"mode": "auto"}),  # the payload's wins
    ({"model": SENTINEL}, {}, {}),
])
def test_the_init_mode_is_recorded_from_an_allowlist(payload, line, modes):
    init = {"event": "init", "conversation_id": "c", "init": payload, **line}
    found = _descriptor(_stream(_step(step_type="subagent"), init=init))
    assert found["init_modes"] == modes
    assert SENTINEL not in json.dumps(found)


def test_the_init_keys_are_names_from_the_allowlist():
    found = _descriptor(_stream(_step(step_type="subagent")))
    assert found["init_keys"] == ["cwd", "model", "permission_mode", "tools"]
    init = {"event": "init", "init": {"model": "m", SENTINEL: 1, "agentMode": "auto"}}
    assert _descriptor(_stream(_step(step_type="subagent"), init=init))["init_keys"] == [
        "agentMode", "model", "other"]


def test_no_init_line_records_null_init_fields():
    found = _descriptor(_stream(_step(step_type="subagent"), init=None))
    assert found["init_keys"] is None and found["init_modes"] is None
    no_payload = {"event": "init", "conversation_id": "c"}
    found = _descriptor(_stream(_step(step_type="subagent"), init=no_payload))
    assert found["init_keys"] is None and found["init_modes"] == {}


# ---------------------------------------------------------------------------------------
# agy 1.5.13's own vocabulary is named, and naming a step type never admits it.
# ---------------------------------------------------------------------------------------

#: agy's closed ``step_type`` vocabulary outside the three recorded step types and the bare
#: ``system_message`` (admitted only in its inert shape: see
#: ``test_gemini_seat_session_tools.py``).
_AGY_UNRECORDED_STEP_TYPES = ("subagent", "checkpoint", "error_message", "finish", "unknown")


@pytest.mark.parametrize("step_type", _AGY_UNRECORDED_STEP_TYPES)
def test_each_agy_step_type_is_named_and_still_refused(step_type):
    line = _step(step_index=27, state="DONE", step_type=step_type, duration_seconds=1.5,
                 usage={"input_tokens": 1})
    found = _descriptor(_stream(_TOOL, line, _TEXT))  # `_descriptor` asserts the refusal
    assert (found["reason"], found["step_type"], found["line_index"]) == (
        "bad_step_type", step_type, 2)
    assert found["step_counts"] == {"agent_response": 1, step_type: 1, "tool": 1}
    assert found["step_keys"] == ["conversation_id", "duration_seconds", "state",
                                  "step_index", "step_type", "usage"]


def test_the_recorded_step_types_are_unchanged():
    assert pi._JAILED_GEMINI_STEP_TYPES == frozenset({"user_input", "agent_response", "tool"})
    assert not pi._JAILED_GEMINI_STEP_TYPES & set(_AGY_UNRECORDED_STEP_TYPES)
    assert set(_AGY_UNRECORDED_STEP_TYPES) <= pi._STREAM_REJECTION_STEPS
    assert "system_message" in pi._STREAM_REJECTION_STEPS
    assert pi._JAILED_GEMINI_SYSTEM_STEP_KEYS == frozenset({
        "conversation_id", "step_index", "state", "step_type", "duration_seconds"})


def test_a_non_inert_system_message_is_named_and_still_refused():
    # The shape `test_each_agy_step_type_is_named_and_still_refused` used before: `usage` is
    # outside the inert allowlist, so the step is refused and recorded as before.
    line = _step(step_index=27, state="DONE", step_type="system_message", duration_seconds=1.5,
                 usage={"input_tokens": 1})
    found = _descriptor(_stream(_TOOL, line, _TEXT))
    assert (found["reason"], found["step_type"], found["line_index"]) == (
        "bad_step_type", "system_message", 2)
    assert found["step_keys"] == ["conversation_id", "duration_seconds", "state",
                                  "step_index", "step_type", "usage"]


def test_a_bare_system_message_records_no_rejection_and_is_counted_on_a_later_refusal():
    bare = _step(step_index=27, state="DONE", step_type="system_message", duration_seconds=1.5)
    assert pi._jailed_gemini_stream_rejection(_stream(_TOOL, bare, _TEXT)) is None
    found = _descriptor(_stream(_TOOL, bare, _step(step_type="subagent"), _TEXT))
    assert (found["line_index"], found["rejected_lines"], found["step_type"]) == (3, 1, "subagent")
    assert found["step_counts"] == {"agent_response": 1, "subagent": 1, "system_message": 1,
                                    "tool": 1}


@pytest.mark.parametrize("tool_name", [
    "code_search", "moma_search", "multi_replace_file_content", "write_file", "edit_file",
    "notebook_edit", "generate_image", "schedule", "skill_search", "manage_inbox",
])
def test_agys_own_tool_names_are_named(tool_name):
    raw = _stream(_step(step_type="tool", tool_name=tool_name), _step(step_type="unknown"))
    found = _descriptor(raw)
    assert found["tool_counts"] == {tool_name: 1}
    assert found["step_counts"] == {"tool": 1, "unknown": 1}


def test_an_unlisted_step_type_and_tool_name_stay_other():
    # A valid, unlisted tool name passes the parser and is counted as `other`; the unlisted
    # step type after it is the refused line. Neither value is recorded.
    unlisted_tool = "zq7_sentinel_tool"
    raw = _stream(_step(step_type="tool", tool_name=unlisted_tool), _step(step_type=SENTINEL))
    found = _descriptor(raw)
    assert found["step_type"] == "other"
    assert found["tool_counts"] == {"other": 1}
    assert found["step_counts"] == {"other": 1, "tool": 1}
    assert SENTINEL not in json.dumps(found) and unlisted_tool not in json.dumps(found)


# ---------------------------------------------------------------------------------------
# Positions and whole-stream counts.
# ---------------------------------------------------------------------------------------

def test_counts_cover_the_whole_stream():
    raw = _stream(_TOOL, _TEXT, _step(step_type="subagent", tool_name="invoke_subagent",
                                      subagent_info={}),
                  _TOOL, {"event": "error"}, _step(step_type=SENTINEL, tool_name=SENTINEL),
                  "not json", "[1]", _TEXT)
    found = _descriptor(raw)
    assert found["line_index"] == 3 and found["line_count"] == 11
    assert found["reason"] == "bad_step_type"  # `subagent` is not a recorded step type
    assert found["rejected_lines"] == 3  # the subagent step, the error event, the odd step
    assert found["event_counts"] == {"error": 1, "init": 1, "malformed": 1, "result": 1,
                                     "step_update": 6, "unparsed": 1}
    assert found["step_counts"] == {"agent_response": 2, "other": 1, "subagent": 1, "tool": 2}
    assert found["tool_counts"] == {"invoke_subagent": 1, "other": 1, "run_command": 2}
    assert SENTINEL not in json.dumps(found)


# ---------------------------------------------------------------------------------------
# Parity with the parser: a descriptor exactly when the parser refused with the code.
# ---------------------------------------------------------------------------------------

_PARITY = [
    _stream(_TOOL, _TEXT),                                                  # accepted
    _stream({"event": "error"}),
    _stream(_step(step_type="browser")),
    _stream(_TOOL, _step(step_type="tool", tool_name="send_message")),     # a refused tool
    _stream(_step(step_type="tool", subagent_info={})),
    _stream("{not json", {"event": "error"}),                               # malformed JSON first
    _stream("", {"event": "error"}),                                        # an empty line first
    _stream("[1]", {"event": "error"}),                                     # not an object first
    _stream({"event": 1}, {"event": "error"}),                              # a non-string event
    _stream({"event": "step_update", "step_update": [1]}, {"event": "error"}),
    _stream(_step(step_type=[1], subagent_info={}), {"event": "error"}),    # unhashable step type
    _stream({"event": "result", "result": "x"}, {"event": "error"}),       # a malformed result
    _stream({"event": "error"}, "{not json"),                               # refused, then garbage
    _stream(_TOOL, init=None, result=None),                                 # accepted lines, no result
    _stream(_TOOL, _step(step_type="system_message", state="DONE"), _TEXT),  # inert: accepted
    _stream(_step(step_type="system_message", tool_name="run_command")),    # not inert
    _stream(_step(step_type="system_message", subagent_info={})),
]


@pytest.mark.parametrize("raw", _PARITY)
def test_the_helper_locates_a_line_exactly_when_the_parser_refused_with_the_code(raw):
    _rc, _text, detail, _ = _parse(raw)
    found = pi._jailed_gemini_stream_rejection(raw)
    assert (found is not None) == (detail == UNKNOWN)
    if found is not None:
        assert pi._stream_rejection_valid(found)


#: A line nested past the JSON decoder's bound: decoding it raises `RecursionError`.
_TOO_DEEP = "[" * 100_000 + "]" * 100_000


def test_a_later_line_past_the_decoder_bound_does_not_lose_the_refusal():
    raw = _stream({"event": "warning"}, _TOO_DEEP, _TEXT, {"event": "error"})
    found = _descriptor(raw)
    assert (found["reason"], found["line_index"], found["event_type"]) == (
        "unknown_event", 1, "warning")
    assert found["event_counts"] == {"error": 1, "init": 1, "result": 1, "step_update": 1,
                                     "unparsed": 1, "warning": 1}
    assert found["rejected_lines"] == 2 and found["line_count"] == 6


def test_a_line_past_the_decoder_bound_before_any_refusal_gives_no_descriptor():
    # The parser never reaches a refusal there (its decode raises), so nothing is located.
    raw = _stream(_TOO_DEEP, {"event": "warning"})
    with pytest.raises(RecursionError):
        _parse(raw)
    assert pi._jailed_gemini_stream_rejection(raw) is None


def test_the_helper_never_raises(monkeypatch):
    monkeypatch.setattr(pi, "_stream_rejection_walk", lambda raw: 1 / 0)
    assert pi._jailed_gemini_stream_rejection(_stream({"event": "error"})) is None


def test_the_helper_is_outside_the_validator_closure():
    spec = importlib.util.spec_from_file_location("convert_agy_record_v2_for_1823", _CONVERTER)
    converter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(converter)
    table = converter.validator_closure(Path(pi.__file__).resolve().parent)
    assert "panel_invoker:_broker_gemini_stream_result" in table
    assert not any(key.startswith(("panel_invoker:_stream_rejection", "panel_invoker:_stream_",
                                   "panel_invoker:_STREAM_REJECTION",
                                   "panel_invoker:_jailed_gemini_stream_rejection",
                                   "panel_invoker:_note_stream_rejection",
                                   "panel_invoker:_note_exec_output_refused"))
                   for key in table)


# ---------------------------------------------------------------------------------------
# The record field: closed values only, scanned, bounded.
# ---------------------------------------------------------------------------------------

def _valid():
    return _descriptor(_stream(_TOOL, _step(step_type="subagent", tool_name="invoke_subagent",
                                            subagent_info={"name": "n"})))


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(reason="subagent"),
    lambda d: d.update(extra=1),
    lambda d: d.pop("tool_counts"),
    lambda d: d.update(event_type=SENTINEL),
    lambda d: d.update(step_type=SENTINEL),
    lambda d: d.update(tool_name=SENTINEL),
    lambda d: d.update(state="done"),
    lambda d: d.update(line_index="2"),
    lambda d: d.update(line_count=True),
    lambda d: d.update(rejected_lines=-1),
    lambda d: d.update(line_index=2 ** 53),
    lambda d: d.update(line_keys=["step_update", "event"]),
    lambda d: d.update(step_keys=[SENTINEL]),
    lambda d: d.update(subagent_info_keys="name"),
    lambda d: d.update(event_counts={SENTINEL: 1}),
    lambda d: d.update(step_counts={"tool": 0}),
    lambda d: d.update(tool_counts={"run_command": "1"}),
    lambda d: d.update(init_modes={SENTINEL: "auto"}),
    lambda d: d.update(init_modes={"mode": SENTINEL}),
    lambda d: d.update(init_keys=[1]),
])
def test_an_open_value_is_not_a_descriptor(mutate):
    found = _valid()
    assert pi._stream_rejection_valid(found)
    bad = copy.deepcopy(found)
    mutate(bad)
    assert not pi._stream_rejection_valid(bad)
    assert pi.leg_exec_record("gemini", 0, [], scan_secrets=(), stream_rejection=bad)[
        "stream_rejection"] is None


@pytest.mark.parametrize(("field", "names"), [
    ("line_keys", [{}]),
    ("line_keys", ["event", 0]),
    ("line_keys", [None]),
    ("line_keys", [["event"]]),
    ("step_keys", [{}, "step_type"]),
    ("subagent_info_keys", [1, "name"]),
    ("init_keys", [{"model": 1}]),
    ("init_keys", ("model",)),
])
def test_a_malformed_key_list_is_not_a_descriptor_and_never_raises(field, names):
    bad = _valid()
    bad[field] = names
    assert pi._stream_rejection_valid(bad) is False
    record = pi.leg_exec_record("gemini", 0, [], scan_secrets=(), stream_rejection=bad)
    assert record["stream_rejection"] is None


@pytest.mark.parametrize("value", [None, [], "x", {"reason": {}}, {frozenset(): 1}])
def test_any_other_shape_is_not_a_descriptor(value):
    assert pi._stream_rejection_valid(value) is False


def test_the_validator_never_raises(monkeypatch):
    found = _valid()

    def boom(value):
        raise TypeError("unforeseen")
    monkeypatch.setattr(pi, "_stream_rejection_closed", boom)
    assert pi._stream_rejection_valid(found) is False
    assert pi.leg_exec_record("gemini", 0, [], scan_secrets=(), stream_rejection=found)[
        "stream_rejection"] is None


def test_the_field_is_kept_and_still_scanned_for_the_legs_secrets():
    found = _valid()
    for secrets in (None, (), (b"ya29.fixture-token",)):
        record = pi.leg_exec_record("gemini", 0, [], scan_secrets=secrets, stream_rejection=found)
        assert record["stream_rejection"] == found
    # A configured value that a closed name happens to spell drops the field.
    record = pi.leg_exec_record("gemini", 0, [], scan_secrets=(b"invoke_subagent",),
                                stream_rejection=found)
    assert record["stream_rejection"] is None


def test_the_record_stays_within_its_bound_at_the_largest_descriptor():
    other, big = pi._STREAM_REJECTION_OTHER, 2 ** 53 - 1

    def every(names, *extra):
        return sorted({*names, other, *extra})

    largest = {
        "reason": "unknown_event", "line_index": big, "line_count": big, "rejected_lines": big,
        "event_type": max(pi._STREAM_REJECTION_EVENTS, key=len),
        "step_type": max(pi._STREAM_REJECTION_STEPS, key=len),
        "tool_name": max(pi._STREAM_REJECTION_TOOLS, key=len), "state": "CANCELLED",
        "line_keys": every(pi._STREAM_REJECTION_LINE_KEYS),
        "step_keys": every(pi._STREAM_REJECTION_STEP_KEYS),
        "subagent_info_keys": every(pi._STREAM_REJECTION_SUBAGENT_KEYS),
        "init_keys": every(pi._STREAM_REJECTION_INIT_KEYS),
        "event_counts": dict.fromkeys(every(pi._STREAM_REJECTION_EVENTS, "unparsed",
                                            "malformed"), big),
        "step_counts": dict.fromkeys(every(pi._STREAM_REJECTION_STEPS, "absent"), big),
        "tool_counts": dict.fromkeys(every(pi._STREAM_REJECTION_TOOLS), big),
        "init_modes": dict.fromkeys(pi._STREAM_REJECTION_MODE_KEYS, "proceed-in-sandbox"),
    }
    assert pi._stream_rejection_valid(largest)
    record = pi.leg_exec_record("gemini", 0, sorted(pi._EXEC_FLAGS), scan_secrets=(),
                                output_refused=True, stream_rejection=largest)
    assert record["stream_rejection"] == largest
    assert len(json.dumps(record, sort_keys=True, separators=(",", ":"))) <= record["bound_bytes"]


# ---------------------------------------------------------------------------------------
# The outcome: a refused leg is not completed.
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(("rc", "refused", "outcome"), [
    (0, True, "leg_execution_refused"),
    (0, False, "leg_execution_completed"),
    (1, True, "leg_execution_failed"),
    (None, True, "leg_execution_failed"),
])
def test_the_outcome_of_a_refused_leg(rc, refused, outcome):
    assert pi.leg_exec_record("gemini", rc, [], output_refused=refused)["outcome"] == outcome


def _records(state):
    return [json.loads(path.read_text()) for path in sorted(state.rglob("leg-*.json"))]


@pytest.mark.parametrize(("returned", "outcome"), [
    (("DEGRADED", ""), "leg_execution_refused"),
    (("OK", "AGREE"), "leg_execution_completed"),  # accepted after all: the refusal is stale
])
def test_the_retained_record_reads_the_refusal(tmp_path, monkeypatch, returned, outcome):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    @pi._retained_leg_exec
    def leg(_leg):
        pi._note_exec_result(0, ["agy"], {})
        pi._jailed_failure("Gemini broker completed without review text", [])
        return returned

    leg("gemini")
    (record,) = _records(tmp_path / "state")
    assert (record["exit_code"], record["outcome"]) == (0, outcome)


# ---------------------------------------------------------------------------------------
# The jailed leg, end to end.
# ---------------------------------------------------------------------------------------

_PROXY_TOKEN = "b7c0f2e1a9d34e5f8c1b2a3d4e5f6071"


def _seat(tmp_path, token=b"ya29.secret-access-token-value"):
    jail = types.SimpleNamespace(
        env={"HTTPS_PROXY": f"http://srt:{_PROXY_TOKEN}@127.0.0.1:3128"},
        profile_digest="d", profile_id="p", filter_digest="f",
        redacted_owner=lambda: [], pass_fds=())
    return pi._JailedSeat(jail=jail, probe_jail=jail, holder_pid=1, token=token,
                          review_dir=tmp_path, seat_dir=tmp_path, expires_at=None)


def _run_jailed(monkeypatch, tmp_path, stdout, returncode=0):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda cmd, **kw: types.SimpleNamespace(
        returncode=returncode, stdout=stdout, stderr=""))
    monkeypatch.setattr(seat_jail, "close_jail_fds", lambda jail: None)
    monkeypatch.setattr(pi._seat_uid, "teardown_in_h", lambda pid, parent: [])
    seat, sink = _seat(tmp_path), []

    @pi._retained_leg_exec
    def leg(_leg):
        return pi._exec_jailed_gemini_leg(seat, deadline_s=60, model="m", prompt="p",
                                          broker_evidence={}, failure_detail_sink=sink)

    result = leg("gemini")
    (record,) = _records(tmp_path / "state")
    return result, sink, seat, record


def test_a_refused_stream_is_described_in_the_leg_record(monkeypatch, tmp_path):
    raw = _stream(_TOOL, _TEXT, _step(step_index=4, state="ACTIVE", step_type="subagent",
                                      tool_name="invoke_subagent",
                                      subagent_info={"conversation_id": SENTINEL}), _TEXT)
    result, sink, seat, record = _run_jailed(monkeypatch, tmp_path, raw)
    # The leg is refused exactly as before.
    assert (result[0], result[1]) == ("DEGRADED", "")
    assert sink[-1].template == UNKNOWN and UNKNOWN in seat.notices
    assert (record["exit_code"], record["outcome"]) == (0, "leg_execution_refused")
    assert record["model_turn"] is None
    assert record["stream_rejection"] == {
        "reason": "bad_step_type", "line_index": 3, "line_count": 6, "rejected_lines": 1,
        "event_type": "step_update", "step_type": "subagent", "tool_name": "invoke_subagent",
        "state": "ACTIVE", "line_keys": ["event", "step_update"],
        "step_keys": ["conversation_id", "state", "step_index", "step_type", "subagent_info",
                      "tool_name"],
        "subagent_info_keys": ["conversation_id"],
        "event_counts": {"init": 1, "result": 1, "step_update": 4},
        "step_counts": {"agent_response": 2, "subagent": 1, "tool": 1},
        "tool_counts": {"invoke_subagent": 1, "run_command": 1},
        "init_keys": ["cwd", "model", "permission_mode", "tools"],
        "init_modes": {"permission_mode": "request-review"},
    }
    # No line text and no value: not the sentinel, not a conversation id, not a line.
    stored = "".join(path.read_text() for path in (tmp_path / "state").rglob("leg-*.json"))
    assert SENTINEL not in stored and '"c"' not in stored
    for line in raw.splitlines():
        assert line not in stored


def test_an_accepted_stream_records_no_rejection(monkeypatch, tmp_path):
    result, sink, _seat_, record = _run_jailed(monkeypatch, tmp_path, _stream(_TOOL, _TEXT))
    assert result[0] == "OK" and not sink
    assert (record["outcome"], record["stream_rejection"]) == ("leg_execution_completed", None)
    assert record["model_turn"] is True


@pytest.mark.parametrize(("stdout", "detail"), [
    (_stream("{not json"), "Gemini broker stream rejected: malformed JSON"),
    (_stream(result=None), "Gemini broker stream has an incomplete ingestion result sequence"),
    (_stream(_TOOL, result={"event": "result", "result": {
        "conversation_id": "c", "status": "SUCCESS", "response": "no verdict here"}}),
     "Gemini broker response lacks a terminal verdict"),
    (json.dumps({"event": "init", "x": "ya29.secret-access-token-value"}) + "\n",
     "gemini_seat_token_in_output"),
])
def test_another_refusal_after_a_clean_exit_is_refused_without_a_descriptor(
        monkeypatch, tmp_path, stdout, detail):
    result, sink, _seat_, record = _run_jailed(monkeypatch, tmp_path, stdout)
    assert result[0] == "DEGRADED" and sink[-1].template == detail
    assert (record["exit_code"], record["outcome"]) == (0, "leg_execution_refused")
    assert record["stream_rejection"] is None


def test_a_nonzero_exit_stays_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    result, sink, _seat_, record = _run_jailed(monkeypatch, tmp_path, _stream({"event": "error"}),
                                               returncode=3)
    assert result[0] == "DEGRADED"
    assert sink[-1].template == "Gemini broker native exit without an accepted review"
    assert (record["exit_code"], record["outcome"]) == (3, "leg_execution_failed")
    assert record["stream_rejection"] is None
