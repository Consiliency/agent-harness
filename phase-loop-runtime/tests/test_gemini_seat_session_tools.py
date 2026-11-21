"""The tooled Gemini stream parser's tool-name rule.

On the retained stream, the parser refuses a step whose tool name is in a fixed set of agy
1.5.13 tool names (``_JAILED_GEMINI_REFUSED_TOOLS``), compared after canonicalisation. It
also refuses a tool step that carries no valid tool name. It refuses with the existing
``gemini_seat_subagent_or_unknown_event`` code, and the private ``stream_rejection`` record
names the reason: ``refused_tool`` or ``bad_tool_name``. Every other valid name is accepted
as before.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi

UNKNOWN = pi._JAILED_GEMINI_UNKNOWN_EVENT
_CONVERTER = Path(__file__).resolve().parents[1] / "scripts" / "convert_agy_record_v2.py"

#: The refused names, each from agy 1.5.13's own tool vocabulary.
REFUSED = ("invoke_subagent", "define_subagent", "manage_subagents", "agent",
           "browser_subagent", "send_message", "swarm", "post_message", "read_board",
           "swarm_wait")
#: Valid names of tools a single-session Default-mode review uses, including the agent's
#: own background tasks, inbox, timers and step list.
ORDINARY = ("run_command", "view_file", "read_file", "code_search", "edit_file", "write_file",
            "multi_replace_file_content", "replace_file_content", "write_to_file",
            "search_in_file", "grep_search", "find_by_name", "list_dir", "command_status",
            "manage_task", "manage_inbox", "schedule", "update_focus", "update_steps",
            "search_web", "read_url_content", "skill_search", "trajectory_search")
#: Spellings of a refused name that canonicalise to it: refused as that name.
DISGUISED = ("Send_Message", "SEND_MESSAGE", " send_message", "send_message\t",
             "default_api:send_message", "DEFAULT_API:Browser_Subagent", "x:y:swarm_wait",
             "\nagent ")
#: Values that are not a valid tool name: refused as ``bad_tool_name``.
INVALID = (None, 7, 1.5, True, [], {}, ["send_message"], {"name": "send_message"}, "",
           "   ", "send message", "send-message", "default_api.send_message", "send_message:",
           "ſend_message", "sénd_message", "send_​message", "141", "_agent",
           "a" * 129, "generic", "Generic", "call_mcp_tool", "default_api:generic")
#: Non-ASCII spaces and zero-width characters, leading or trailing, on a refused name and an
#: ordinary one, and ASCII separators that Python's own ``str.strip()`` would remove: the raw
#: value is judged before any stripping, so each is ``bad_tool_name``.
UNICODE_EDGES = tuple(
    edge for char in ("\u00a0", "\u2007", "\u200b", "\ufeff")
    for base in ("send_message", "run_command")
    for edge in (char + base, base + char)
) + ("\x1csend_message", "run_command\x1f", "\x85run_command", "\u3000send_message")
#: Distinct valid names, and the namespaced form agy itself reads as a plain name: accepted.
DISTINCT = ("send_message_to_user", "manage_tasks", "agents", "swarm_status",
            "default_api:view_file", "a" * 128)

_INIT = {"event": "init", "conversation_id": "c",
         "init": {"model": "m", "permission_mode": "always-proceed"}}
_RESULT = {"event": "result", "result": {"conversation_id": "c", "status": "SUCCESS",
                                         "response": "Review.\nAGREE"}}


def _step(**fields):
    return {"event": "step_update", "step_update": {"conversation_id": "c", **fields}}


def _tool(name, **fields):
    return _step(step_index=1, state="DONE", step_type="tool", tool_name=name,
                 tool_info={"name": "x", "parameters": {}}, duration_seconds=0.5, **fields)


_TEXT = _step(step_index=2, state="DONE", step_type="agent_response", text_delta="t")


def _stream(*lines):
    return "\n".join(json.dumps(row) for row in (_INIT, *lines, _RESULT)) + "\n"


def _parse(raw, tooled=True):
    protocol = pi._broker_gemini_stream_protocol("prompt", tooled=tooled)
    return pi._broker_gemini_stream_result(raw, protocol, tooled=tooled)


def _refused(raw):
    rc, text, detail, metadata = _parse(raw)
    return (rc, text, detail, metadata["provider_stream_outcome"]) == (
        1, "", UNKNOWN, "parse_error")


def _record(raw):
    found = pi._jailed_gemini_stream_rejection(raw)
    assert found is not None and pi._stream_rejection_valid(found)
    return found


# ---------------------------------------------------------------------------------------
# The parser.
# ---------------------------------------------------------------------------------------

def test_the_refused_set_is_exactly_the_session_tools():
    assert pi._JAILED_GEMINI_REFUSED_TOOLS == frozenset(REFUSED)
    assert pi._JAILED_GEMINI_UNNAMED_TOOLS == frozenset({"generic", "call_mcp_tool"})
    assert not pi._JAILED_GEMINI_REFUSED_TOOLS & set(ORDINARY)


@pytest.mark.parametrize("name", REFUSED)
def test_a_refused_tool_step_is_refused(name):
    assert _refused(_stream(_tool("run_command"), _tool(name), _TEXT))


def test_a_browser_subagent_step_without_subagent_info_is_refused():
    # The shape agy 1.5.13 emits for its browser subagent: a plain tool step, no subagent_info.
    line = _step(step_index=4, state="DONE", step_type="tool", tool_name="browser_subagent",
                 tool_info={"name": "browser_subagent", "parameters": {}},
                 duration_seconds=3.0, usage={"input_tokens": 1})
    assert "subagent_info" not in line["step_update"]
    assert _refused(_stream(line, _TEXT))


@pytest.mark.parametrize("name", DISGUISED)
def test_a_disguised_refused_name_is_refused(name):
    assert _refused(_stream(_tool(name), _TEXT))


@pytest.mark.parametrize("name", INVALID, ids=repr)
def test_a_tool_step_without_a_valid_name_is_refused(name):
    assert _refused(_stream(_tool(name), _TEXT))


@pytest.mark.parametrize("name", UNICODE_EDGES, ids=repr)
def test_a_non_ascii_or_control_edge_is_refused_before_any_stripping(name):
    assert _refused(_stream(_tool(name), _TEXT))
    assert _record(_stream(_tool(name), _TEXT))["reason"] == "bad_tool_name"
    assert pi._jailed_gemini_tool_refusal({"step_type": "tool", "tool_name": name}) == (
        "bad_tool_name")


def test_a_tool_step_without_a_name_is_refused():
    line = _step(step_index=1, state="DONE", step_type="tool", tool_info={})
    assert _refused(_stream(line, _TEXT))


@pytest.mark.parametrize("name", [*REFUSED, None, "", "Send_Message"], ids=repr)
@pytest.mark.parametrize("step_type", ["agent_response", "user_input"])
def test_a_tool_name_on_another_recorded_step_is_judged_too(step_type, name):
    assert _refused(_stream(_step(step_type=step_type, tool_name=name)))


@pytest.mark.parametrize("name", ORDINARY + DISTINCT)
def test_a_valid_unrefused_tool_name_still_passes(name):
    rc, text, detail, metadata = _parse(_stream(_tool(name), _TEXT))
    assert (rc, detail) == (0, "") and text.endswith("AGREE")
    assert metadata["provider_stream_tool_steps"] == 1


def test_a_step_without_a_tool_name_key_that_is_not_a_tool_step_passes():
    assert _parse(_stream(_tool("run_command"), _TEXT))[0] == 0


@pytest.mark.parametrize("step_type", ["error_message", "system_message", "unknown"])
def test_agys_other_step_types_stay_refused(step_type):
    assert _refused(_stream(_tool("run_command"), _step(step_type=step_type, state="DONE")))


def test_the_no_tool_route_is_unchanged():
    rc, _text, detail, _ = _parse(_stream(_tool("run_command")), tooled=False)
    assert (rc, detail) == (1, "Gemini broker stream rejected: tool or subagent activity observed")


# ---------------------------------------------------------------------------------------
# The stream_rejection record names the reason, from the parser's own helper.
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", REFUSED)
def test_the_record_names_the_refused_tool(name):
    found = _record(_stream(_tool("run_command"), _tool(name), _TEXT))
    assert (found["reason"], found["step_type"], found["tool_name"]) == (
        "refused_tool", "tool", name)
    assert (found["line_index"], found["rejected_lines"]) == (2, 1)
    assert found["tool_counts"] == {name: 1, "run_command": 1}


@pytest.mark.parametrize("name", DISGUISED)
def test_a_disguised_name_is_recorded_as_refused_without_its_spelling(name):
    found = _record(_stream(_tool(name), _TEXT))
    assert found["reason"] == "refused_tool" and found["tool_name"] == "other"
    assert found["tool_counts"] == {"other": 1}  # the spelling itself is never recorded


@pytest.mark.parametrize("name", INVALID, ids=repr)
def test_an_invalid_name_is_recorded_as_bad_tool_name(name):
    found = _record(_stream(_tool(name), _TEXT))
    assert found["reason"] == "bad_tool_name" and found["step_type"] == "tool"
    assert found["tool_name"] in {"other", "generic", "call_mcp_tool"}


def test_a_missing_name_is_recorded_as_bad_tool_name():
    found = _record(_stream(_step(step_type="tool", state="DONE"), _TEXT))
    assert found["reason"] == "bad_tool_name" and found["tool_name"] is None
    assert "tool_name" not in found["step_keys"]


@pytest.mark.parametrize(("step", "reason"), [
    ({"step_type": "subagent", "tool_name": "invoke_subagent"}, "bad_step_type"),
    ({"step_type": "tool", "tool_name": "browser_subagent", "subagent_info": {}},
     "subagent_info"),
    ({"step_type": "tool", "tool_name": "send_message"}, "refused_tool"),
    ({"step_type": "tool"}, "bad_tool_name"),
])
def test_the_record_keeps_the_parsers_rule_order(step, reason):
    assert _record(_stream(_step(**step)))["reason"] == reason


@pytest.mark.parametrize("name", [*REFUSED, *DISGUISED, *INVALID, *UNICODE_EDGES, *ORDINARY,
                                  *DISTINCT], ids=repr)
def test_the_record_agrees_with_the_parser_on_every_name(name):
    raw = _stream(_tool(name), _TEXT)
    refused = _parse(raw)[0] == 1
    found = pi._jailed_gemini_stream_rejection(raw)
    assert refused == (found is not None)
    assert found is None or found["reason"] == pi._jailed_gemini_tool_refusal(
        json.loads(raw.splitlines()[1])["step_update"])


def test_every_refused_line_is_counted():
    raw = _stream(_tool("send_message"), _tool("run_command"), _tool(None), _TEXT)
    found = _record(raw)
    assert (found["line_index"], found["rejected_lines"], found["tool_name"]) == (
        1, 2, "send_message")


def test_an_ordinary_stream_records_no_rejection():
    assert pi._jailed_gemini_stream_rejection(_stream(_tool("manage_task"), _TEXT)) is None


def test_the_helper_never_raises():
    for value in ({}, {"tool_name": object()}, {"step_type": "tool", "tool_name": b"x"},
                  {"step_type": "tool", "tool_name": "x" * 10_000}):
        pi._jailed_gemini_tool_refusal(value)


def test_the_rule_is_in_the_validator_closure_and_named_by_the_record():
    assert set(REFUSED) <= pi._STREAM_REJECTION_TOOLS
    assert {"refused_tool", "bad_tool_name"} <= pi._STREAM_REJECTION_REASONS
    spec = importlib.util.spec_from_file_location("convert_agy_record_v2_for_tools", _CONVERTER)
    converter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(converter)
    table = converter.validator_closure(Path(pi.__file__).resolve().parent)
    for node in ("_broker_gemini_stream_result", "_jailed_gemini_tool_refusal",
                 "_JAILED_GEMINI_REFUSED_TOOLS", "_JAILED_GEMINI_UNNAMED_TOOLS",
                 "_JAILED_GEMINI_TOOL_NAME_MAX"):
        assert f"panel_invoker:{node}" in table
