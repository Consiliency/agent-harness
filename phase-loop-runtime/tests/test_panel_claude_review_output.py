"""agent-harness#960: preserve all blocks of the request-owned final message."""

from __future__ import annotations

import json
import sys

import pytest

from phase_loop_runtime import panel_invoker as pi


def _assistant(text, *, message_id="review", uuid=None, stop_reason=None):
    return {
        "type": "assistant",
        "uuid": uuid,
        "message": {
            "id": message_id,
            "role": "assistant",
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}],
        },
    }


def _extract(tmp_path, records):
    path = tmp_path / "owned.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return pi._final_assistant_text_from_jsonl(path)


def test_all_blocks_of_final_message_survive(tmp_path):
    records = [
        _assistant("Earlier commentary", message_id="old"),
        _assistant("REVIEW START\n1. Blocking finding", uuid="block-1"),
        {"type": "progress", "data": "not assistant text"},
        _assistant("2. Another blocker", uuid="block-2"),
        _assistant("REVIEW END\nPARTIALLY AGREE", uuid="block-3", stop_reason="end_turn"),
    ]
    assert _extract(tmp_path, records) == (
        "REVIEW START\n1. Blocking finding\n2. Another blocker\n"
        "REVIEW END\nPARTIALLY AGREE"
    )


def test_distinct_responses_are_not_concatenated(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Old blocking review\nDISAGREE", message_id="old"),
        _assistant("Current complete review\nAGREE", message_id="new"),
    ]) == "Current complete review\nAGREE"


def test_duplicate_record_is_not_duplicated_but_distinct_blocks_are(tmp_path):
    first = _assistant("Repeated text", uuid="one")
    assert _extract(tmp_path, [
        first, first, _assistant("Repeated text", uuid="two"),
        _assistant("AGREE", uuid="three", stop_reason="end_turn"),
    ]) == "Repeated text\nRepeated text\nAGREE"


def test_record_update_replaces_only_its_own_block(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Initial", uuid="one"),
        _assistant("Corrected", uuid="one"),
        _assistant("AGREE", uuid="two", stop_reason="end_turn"),
    ]) == "Corrected\nAGREE"


@pytest.mark.parametrize("boundary", [
    {"type": "user", "message": {"role": "user", "content": "New request"}},
    {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "AGREE"}]}},
    {"type": "assistant", "message": {"id": "new", "role": "assistant", "content": [{"type": "thinking", "thinking": "private"}]}},
    {"type": "assistant", "message": {"id": "new", "role": "assistant", "content": [{"type": "tool_use", "id": "tool"}]}},
])
def test_new_turn_or_nonfinal_message_cannot_reuse_prior_verdict(tmp_path, boundary):
    assert _extract(tmp_path, [_assistant("Old review\nAGREE"), boundary]) == ""


def test_user_boundary_prevents_id_reuse_from_joining_turns(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Old review", uuid="one"),
        {"type": "user", "message": {"role": "user", "content": "Continue"}},
        _assistant("New review\nDISAGREE", uuid="two"),
    ]) == "New review\nDISAGREE"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "tool_use"])
def test_explicitly_incomplete_message_is_not_a_final_review(tmp_path, stop_reason):
    assert _extract(tmp_path, [_assistant("Unfinished\nAGREE", stop_reason=stop_reason)]) == ""


def test_thinking_blocks_are_never_returned(tmp_path):
    record = _assistant("Public review\nAGREE")
    record["message"]["content"].insert(0, {"type": "thinking", "thinking": "private"})
    assert _extract(tmp_path, [record]) == "Public review\nAGREE"


def test_legacy_single_message_without_id_still_works(tmp_path):
    record = _assistant("Complete legacy review\nAGREE")
    del record["message"]["id"]
    assert _extract(tmp_path, [record]) == "Complete legacy review\nAGREE"


def test_identityless_messages_are_not_joined(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Old text", message_id=None),
        _assistant("Current review\nAGREE", message_id=None),
    ]) == "Current review\nAGREE"


def test_incomplete_json_tail_does_not_reuse_stale_verdict(tmp_path):
    path = tmp_path / "owned.jsonl"
    path.write_text(json.dumps(_assistant("Old review\nAGREE")) + '\n{"type":"assistant",')
    assert pi._final_assistant_text_from_jsonl(path) == ""


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX PTY")
@pytest.mark.parametrize(("mode", "first", "last"), [
    ("review", "REVIEW START\n1. Must fix the first blocker", "REVIEW END\nPARTIALLY AGREE"),
    ("president", "FINDING F001: BLOCKING — Preserve the first finding", "FORCING DECISION: Fix F001 before landing"),
])
def test_brokered_tui_returns_complete_split_review(tmp_path, monkeypatch, mode, first, last):
    monkeypatch.setattr(pi, "_CLAUDE_TUI_SUBMIT_DELAY_S", 0.1)
    monkeypatch.setattr(pi, "_CLAUDE_TUI_READY_QUIESCENCE_S", 0.1)
    completion_inputs = []
    real_completion_ok = pi._completion_ok

    def record_completion(text, mode="review"):
        completion_inputs.append((text, mode))
        return real_completion_ok(text, mode)

    monkeypatch.setattr(pi, "_completion_ok", record_completion)
    records = [
        _assistant(first, uuid="first"),
        _assistant(last, uuid="last", stop_reason="end_turn"),
    ]
    script = r'''
import json, os, sys, tty
from pathlib import Path
tty.setraw(0)
print("Claude Code ready for your message", flush=True)
wire = b""
while not wire.endswith(b"\x1bOM"):
    wire += os.read(0, 65536)
Path("owned.jsonl").write_text("".join(json.dumps(r) + "\n" for r in json.loads(sys.argv[1])))
'''
    rc, text, status, _ = pi._run_claude_tui_session(
        command=[sys.executable, "-c", script, json.dumps(records)],
        cwd=tmp_path,
        prompt="Review the supplied synthetic example.",
        output_file=tmp_path / "unused-review.txt",
        timeout_s=15,
        backstop_s=15,
        env={"PATH": "/usr/bin:/bin"},
        mode=mode,
        allow_transcript_final=True,
        broker_transcript_path=tmp_path / "owned.jsonl",
    )
    assert rc == 0, (status, text)
    assert status == "claude_tui_broker_final_assistant"
    assert text == first + "\n" + last
    assert (text, mode) in completion_inputs
    evidence = {}
    assert pi._cleanup_broker_claude_transcript(tmp_path / "owned.jsonl", evidence)
    assert evidence["claude_transcript_cleanup_verified"]
    assert not (tmp_path / "owned.jsonl").exists()
