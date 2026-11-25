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


def empty_run_diagnostics() -> dict[str, object]:
    """Initial diagnostics for a routed leg before any launch is attempted."""
    return {
        "native_exit_code": None,
        "native_signal": None,
        "native_duration_ms": None,
        "native_stdout_bytes": 0,
        "native_stderr_bytes": 0,
        "provider_stage_reached": "not_launched",
        "provider_event_type_counts": {},
        "provider_tool_calls_attempted": 0,
        "provider_tool_calls_completed": 0,
        "provider_tool_calls_failed": 0,
        "provider_tool_error_codes": {},
    }


class CodexStreamDiagnostics:
    """Summarize raw stdout before redaction, independently of the evidence gate."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._events: Counter[str] = Counter()
        self._errors: Counter[str] = Counter()
        self._attempts: set[str] = set()
        self._completions: set[str] = set()

    def feed(self, chunk: bytes) -> None:
        lines = chunk.split(b"\n")
        self._pending.extend(lines[0])
        if len(lines) == 1:
            return
        self._observe_line(self._pending)
        for line in lines[1:-1]:
            self._observe_line(line)
        self._pending = bytearray(lines[-1])

    def _observe_line(self, line: bytes | bytearray) -> None:
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            self._events["malformed"] += 1
            return
        if not isinstance(event, dict) or not isinstance(name := event.get("type"), str):
            self._events["malformed"] += 1
            return
        self._events[name if name in CODEX_TOOL_EVENTS else "unknown"] += 1
        if name not in {"item.started", "item.updated", "item.completed"}:
            return
        item = event.get("item")
        if not isinstance(item, dict):
            return
        kind, ident = item.get("type"), item.get("id")
        if not isinstance(kind, str) or kind not in _TOOL_FAILURE_CODES or not isinstance(ident, str):
            return
        self._attempts.add(ident)
        if name != "item.completed" or ident in self._completions:
            return
        self._completions.add(ident)
        exit_code = item.get("exit_code")
        if kind == "command_execution" and type(exit_code) is int and exit_code != 0:
            self._errors["command_nonzero_exit"] += 1
        elif item.get("status") == "failed":
            self._errors[_TOOL_FAILURE_CODES[kind]] += 1

    def finish(self, evidence: dict[str, object]) -> None:
        if self._pending:
            self._observe_line(self._pending)
            self._pending.clear()
        if self._events["turn.completed"] or self._events["turn.failed"]:
            evidence["provider_stage_reached"] = "terminal_event"
        elif any(name != "malformed" for name in self._events):
            evidence["provider_stage_reached"] = "first_incoming_event"
        evidence.update(
            provider_event_type_counts=dict(self._events),
            provider_tool_calls_attempted=len(self._attempts),
            provider_tool_calls_completed=len(self._completions),
            provider_tool_calls_failed=sum(self._errors.values()),
            provider_tool_error_codes=dict(self._errors),
        )
