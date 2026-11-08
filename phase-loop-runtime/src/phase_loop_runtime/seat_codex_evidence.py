"""Parent-held Codex JSON stream evidence (IF-0-CODEX-4)."""

from dataclasses import dataclass
import json


CODEX_TOOL_EVENTS = frozenset({
    "thread.started", "turn.started", "item.started", "item.updated", "item.completed",
    "error", "turn.completed", "turn.failed",
})


@dataclass(frozen=True)
class CodexToolRecord:
    stream_valid: bool
    turn_completed: bool
    commands_completed: int
    commands_failed: int
    unknown_event: bool


def read_tool_record(stream: bytes) -> CodexToolRecord:
    valid = bool(stream) and stream.endswith(b"\n")
    completed = unknown = False
    successful = failed = 0
    started = False
    command_ids = set()
    for line in stream.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            valid = False
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            valid = False
            continue
        name = event["type"]
        if name not in CODEX_TOOL_EVENTS:
            unknown = True
        if completed:
            valid = False
        if name == "turn.started":
            if started:
                valid = False
            started = True
        if name == "turn.completed":
            completed = started
            if not started:
                valid = False
        if name == "turn.failed":
            valid = False
        if name != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            valid = False
            continue
        if item.get("type") != "command_execution":
            continue
        ident = item.get("id")
        if not started or not isinstance(ident, str) or ident in command_ids:
            valid = False
            continue
        command_ids.add(ident)
        if (item.get("status") == "completed" and type(item.get("exit_code")) is int
                and item["exit_code"] == 0 and isinstance(item.get("aggregated_output"), str)
                and item["aggregated_output"].strip()):
            successful += 1
        else:
            failed += 1
    return CodexToolRecord(valid, completed, successful, failed, unknown)


def tools_ran_code(record: CodexToolRecord) -> str | None:
    if record.unknown_event:
        return "codex_seat_unknown_event"
    if not record.stream_valid or not record.turn_completed or record.commands_completed < 1:
        return "codex_seat_tools_unavailable"
    return None
