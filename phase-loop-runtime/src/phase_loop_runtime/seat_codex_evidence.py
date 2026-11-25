"""Parent-held Codex JSON stream evidence (IF-0-CODEX-4)."""

from collections import Counter
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


# Error labels are generated from structured fields of known tool items.
_TOOL_FAILURE_CODES = {
    "command_execution": "command_failed",
    "mcp_tool_call": "mcp_tool_failed",
    "web_search": "web_search_failed",
}


def run_diagnostics(
    returncode: int | None = None, duration_ms: int | None = None,
    stdout: bytes | bytearray = b"", stderr_bytes: int = 0,
) -> dict[str, object]:
    """Summarize the native pipes independently of the review evidence gate."""
    events: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    attempts: set[str] = set()
    completions: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            events["malformed"] += 1
            continue
        if not isinstance(event, dict) or not isinstance(name := event.get("type"), str):
            events["malformed"] += 1
            continue
        events[name if name in CODEX_TOOL_EVENTS else "unknown"] += 1
        if name not in {"item.started", "item.updated", "item.completed"}:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        kind, ident = item.get("type"), item.get("id")
        if not isinstance(kind, str) or kind not in _TOOL_FAILURE_CODES or not isinstance(ident, str):
            continue
        attempts.add(ident)
        if name != "item.completed" or ident in completions:
            continue
        completions.add(ident)
        exit_code = item.get("exit_code")
        if kind == "command_execution" and type(exit_code) is int and exit_code != 0:
            errors["command_nonzero_exit"] += 1
        elif item.get("status") == "failed":
            errors[_TOOL_FAILURE_CODES[kind]] += 1

    stage = "not_launched" if duration_ms is None else "launch"
    if events["turn.completed"] or events["turn.failed"]:
        stage = "terminal_event"
    elif any(name != "malformed" for name in events):
        stage = "first_incoming_event"
    return {
        # A positive 128 + signal status from a wrapper is ambiguous.
        "native_exit_code": returncode if returncode is not None and returncode >= 0 else None,
        "native_signal": -returncode if returncode is not None and returncode < 0 else None,
        "native_duration_ms": duration_ms,
        "native_stdout_bytes": len(stdout),
        "native_stderr_bytes": stderr_bytes,
        "provider_stage_reached": stage,
        "provider_event_type_counts": dict(events),
        "provider_tool_calls_attempted": len(attempts),
        "provider_tool_calls_completed": len(completions),
        "provider_tool_calls_failed": sum(errors.values()),
        "provider_tool_error_codes": dict(errors),
    }
