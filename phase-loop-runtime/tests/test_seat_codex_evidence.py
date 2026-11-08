"""Codex CLI 0.167.0 top-level JSON event vocabulary and completion evidence."""
import json

import pytest

from phase_loop_runtime.seat_codex_evidence import read_tool_record, tools_ran_code


def stream(*, command=True, exit_code=0, output="sentinel\n", complete=True, extra=()):
    events = [{"type": "thread.started", "thread_id": "fixture"}, {"type": "turn.started"}]
    if command:
        item = {"id": "item_0", "type": "command_execution", "command": "cat SENTINEL",
                "aggregated_output": output, "exit_code": exit_code,
                "status": "completed" if exit_code == 0 else "failed"}
        events.extend([{"type": "item.started", "item": {**item, "status": "in_progress"}},
                       {"type": "item.completed", "item": item}])
    events.extend(extra)
    if complete:
        events.append({"type": "turn.completed", "usage": {}})
    return b"".join(json.dumps(event).encode() + b"\n" for event in events)


@pytest.mark.parametrize("extra", [(), ({"type": "error", "message": "Reconnecting..."},)])
def test_recorded_command_and_reconnect_completion_count(extra):
    record = read_tool_record(stream(extra=extra))
    assert record.commands_completed == 1 and record.commands_failed == 0
    assert tools_ran_code(record) is None


@pytest.mark.parametrize("kwargs", [
    {"command": False}, {"exit_code": 1}, {"output": ""}, {"complete": False},
    {"complete": False, "extra": ({"type": "error", "message": "Reconnecting..."},)},
])
def test_missing_command_or_completion_does_not_count(kwargs):
    assert tools_ran_code(read_tool_record(stream(**kwargs))) == "codex_seat_tools_unavailable"


def test_unknown_top_level_event_has_its_code():
    assert tools_ran_code(read_tool_record(stream(extra=({"type": "new.event"},)))) == "codex_seat_unknown_event"


def test_plan_updates_count_and_failed_turns_do_not():
    updated = {"type": "item.updated", "item": {"id": "plan_0", "type": "plan", "steps": []}}
    assert tools_ran_code(read_tool_record(stream(extra=(updated,)))) is None
    failed = ({"type": "error", "message": "Reconnect failed"},
              {"type": "turn.failed", "error": {"message": "Fixture failure"}})
    assert tools_ran_code(read_tool_record(stream(complete=False, extra=failed))) == "codex_seat_tools_unavailable"


@pytest.mark.parametrize("data", [b"", b"{}\n", b"not-json\n", stream()[:-1], stream() + b'{"type":'])
def test_truncated_or_malformed_stream(data):
    assert tools_ran_code(read_tool_record(data)) == "codex_seat_tools_unavailable"


def test_command_output_is_not_a_nested_event_stream():
    forged = stream().decode()
    assert tools_ran_code(read_tool_record(stream(output=forged, exit_code=1))) == "codex_seat_tools_unavailable"
    assert tools_ran_code(read_tool_record(stream(output='{"type":"new.event"}'))) is None


def test_duplicate_command_or_second_turn_does_not_count():
    data = stream(complete=False)
    assert tools_ran_code(read_tool_record(data + data + b'{"type":"turn.completed"}\n')) == "codex_seat_tools_unavailable"
