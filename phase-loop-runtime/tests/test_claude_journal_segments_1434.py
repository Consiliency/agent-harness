"""agent-harness#1434: journal admission validates LOGICAL assistant messages.

Claude Code journals one API message as several records: a thinking block, a text block and
each tool call are separate records with their own uuids, and every one of them carries the
message's id and its ``stop_reason``. Measured on Claude Code 2.1.x journals: 44,007 of 63,871
tool-calling messages have a record with no tool block, every one of them has a tool block in
some record, and one message id recurs after a ``tool_result`` 3,904 times (parallel tool
calls), so the records of one message are not adjacent.

``_validated_claude_journal`` judged each record alone and refused a thinking or text record
that said ``stop_reason: tool_use`` without a tool block of its own, so a real tools-enabled
review was never admitted. The rule is now per message id. Every other refusal is unchanged.

Named mutations, each run against this file (both red):

* M-GROUP: key the tool-call rule by the record instead of the message id (the old
  per-record rule) -> every ``admitted`` cell below fails.
* M-GROUP-ALL: treat all assistant records as one message -> ``a tool-stopped message with
  no tool call in any record`` is admitted.
* M-PENDING: drop the pending-tool refusal -> the ``pending`` and ``unmatched`` cells are
  admitted.
"""
from __future__ import annotations

import json

import pytest

from phase_loop_runtime import panel_invoker as pi

FINAL_TEXT = "Complete fixture review.\nAGREE"
REQUEST = {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "Review."}}
THINKING = {"type": "thinking", "thinking": "", "signature": "sig"}


def assistant(uuid: str, message_id: str | None, stop: str | None, *blocks: dict) -> dict:
    message = {"role": "assistant", "stop_reason": stop, "content": list(blocks)}
    if message_id is not None:
        message["id"] = message_id
    return {"type": "assistant", "uuid": uuid, "message": message}


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def tool_use(tool_id: str, name: str = "Read") -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": {}}


def tool_result(uuid: str, *tool_ids: str) -> dict:
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"} for tool_id in tool_ids]}}


def journal(*records: dict, tail: str = "") -> bytes:
    return ("".join(json.dumps(record) + "\n" for record in records) + tail).encode()


FINAL = assistant("a-final", "final-message", "end_turn", text(FINAL_TEXT))

#: The issue's minimal reproduction, record for record.
ISSUE_FIXTURE = (
    REQUEST,
    assistant("a1", "tool-message", "tool_use", THINKING),
    assistant("a2", "tool-message", "tool_use", tool_use("t1")),
    tool_result("r1", "t1"),
    FINAL,
)

#: Shapes taken from real journals (block types and stop reasons only).
SEGMENTED = {
    "the issue's five records": ISSUE_FIXTURE,
    "thinking, text, tool": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", text("I will read the change first.")),
        assistant("a3", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        FINAL,
    ),
    "parallel tools, each result journaled before the next call": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", THINKING),
        assistant("a3", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        assistant("a4", "m1", "tool_use", tool_use("t2", "Grep")),
        tool_result("r2", "t2"),
        FINAL,
    ),
    "two tool messages, then a segmented final answer": (
        REQUEST,
        assistant("a1", "m1", "tool_use", text("Reading.")),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        assistant("a3", "m2", "tool_use", THINKING),
        assistant("a4", "m2", "tool_use", tool_use("t2", "Write")),
        tool_result("r2", "t2"),
        assistant("a5", "final-message", "end_turn", THINKING),
        assistant("a6", "final-message", "end_turn", text(FINAL_TEXT)),
    ),
    "a re-journaled tool segment is not a second pending call": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        {**assistant("a2", "m1", "tool_use", tool_use("t1")), "parentUuid": "re-journaled"},
        FINAL,
    ),
}


@pytest.mark.parametrize("shape", sorted(SEGMENTED))
def test_a_segmented_tool_message_is_admitted(shape):
    data = journal(*SEGMENTED[shape])
    # The route's own answer rule already accepted these; admission now agrees with it.
    assert pi._final_assistant_text_from_jsonl(None, data=data) == FINAL_TEXT
    assert pi._validated_claude_journal(data, require_terminal=False) == FINAL_TEXT


def test_the_issue_fixture_is_admitted_on_the_president_rule_too():
    data = journal(*ISSUE_FIXTURE)
    terminal = pi._final_assistant_text_from_jsonl(None, require_terminal=True, data=data)
    assert pi._validated_claude_journal(data, require_terminal=True) == terminal


REFUSED = {
    # --- pending or unmatched tool uses ---
    "pending: one of two parallel calls has no result": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        assistant("a3", "m1", "tool_use", tool_use("t2")),
        tool_result("r1", "t1"),
        FINAL,
    ),
    "pending: the segmented call has no result at all": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        FINAL,
    ),
    "unmatched: a result for a call no record made": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "other"),
        FINAL,
    ),
    "unmatched: a result journaled before its call": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        tool_result("r1", "t1"),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        FINAL,
    ),
    "a tool call without an id": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", {"type": "tool_use", "name": "Read", "input": {}}),
        FINAL,
    ),
    # --- a tool-stopped message must hold a tool call in SOME record of that message ---
    "a tool-stopped message with no tool call in any record": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", text("I will read the change.")),
        assistant("a3", "m2", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        FINAL,
    ),
    "a tool-stopped record without a message id has no other record to lean on": (
        REQUEST,
        assistant("a1", None, "tool_use", THINKING),
        assistant("a2", None, "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        FINAL,
    ),
    # --- the user-turn count ---
    "a second user turn": (
        REQUEST,
        {"type": "user", "uuid": "u2", "message": {"role": "user", "content": "And another."}},
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        FINAL,
    ),
    "a user turn after the assistant started": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        {"type": "user", "uuid": "u2", "message": {"role": "user", "content": "One more thing."}},
        FINAL,
    ),
    # --- the incomplete tail ---
    "the tool segment of the last message is not journaled yet": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
    ),
    "the turn stops at a tool result": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
    ),
    "the final answer is still open": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        assistant("a-final", "final-message", None, text(FINAL_TEXT)),
    ),
    # --- any other stop ---
    "a capped segment": (
        REQUEST,
        assistant("a1", "m1", "max_tokens", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        FINAL,
    ),
    # --- an API error is never an answer ---
    "the turn ends in a journaled API error": (
        REQUEST,
        assistant("a1", "m1", "tool_use", THINKING),
        assistant("a2", "m1", "tool_use", tool_use("t1")),
        tool_result("r1", "t1"),
        {**assistant("err", "m-err", "stop_sequence", text("API Error: overloaded")),
         "isApiErrorMessage": True, "error": "overloaded"},
    ),
}


@pytest.mark.parametrize("shape", sorted(REFUSED))
@pytest.mark.parametrize("president", [False, True])
def test_every_other_refusal_holds_on_segmented_journals(shape, president):
    data = journal(*REFUSED[shape])
    assert pi._validated_claude_journal(data, require_terminal=president) == ""


def test_a_partial_last_line_is_refused():
    whole = journal(*ISSUE_FIXTURE)
    assert pi._validated_claude_journal(whole) == FINAL_TEXT
    assert pi._validated_claude_journal(whole[:-1]) == ""  # the writer is mid-append
    assert pi._validated_claude_journal(whole + b'{"type": "assistant", "mess') == ""


def test_admission_is_not_a_last_line_verdict_match():
    """A journal whose last record is a completed verdict, but whose turn holds an unmatched
    tool call, is refused: admission reads the whole turn, never only its tail."""
    data = journal(REQUEST, assistant("a1", "m1", "tool_use", tool_use("t1")), FINAL)
    assert data.rstrip(b"\n").split(b"\n")[-1] == json.dumps(FINAL).encode()
    assert pi._final_assistant_text_from_jsonl(None, data=data) == FINAL_TEXT
    assert pi._validated_claude_journal(data) == ""
