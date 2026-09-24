"""agent-harness#960: preserve all blocks of the request-owned final message."""

from __future__ import annotations

import json
import sys

import pytest

from phase_loop_runtime import panel_invoker as pi


_MISSING = object()


def _assistant(text, *, message_id="review", uuid=None, stop_reason=_MISSING):
    record = {
        "type": "assistant",
        "uuid": uuid,
        "message": {
            "id": message_id,
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }
    if stop_reason is not _MISSING:
        record["message"]["stop_reason"] = stop_reason
    return record


def _extract(tmp_path, records, *, ensure_ascii=True):
    path = tmp_path / "owned.jsonl"
    path.write_text("".join(json.dumps(record, ensure_ascii=ensure_ascii) + "\n" for record in records))
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


def test_replayed_uuid_from_earlier_message_cannot_restore_old_verdict(tmp_path):
    old = _assistant("Old review\nAGREE", message_id="old", uuid="old", stop_reason="end_turn")
    assert _extract(tmp_path, [
        old,
        _assistant("Current review\nDISAGREE", message_id="new", uuid="new", stop_reason="end_turn"),
        old,
    ]) == "Current review\nDISAGREE"


@pytest.mark.parametrize("message_ids", [("old", "new"), (None, None)])
def test_changed_uuid_reused_across_messages_fails_closed(tmp_path, message_ids):
    old_id, new_id = message_ids
    assert _extract(tmp_path, [
        _assistant("Old review\nAGREE", message_id=old_id, uuid="same", stop_reason="end_turn"),
        _assistant("Current review\nDISAGREE", message_id=new_id, uuid="same", stop_reason="end_turn"),
    ]) == ""


def test_replayed_uuid_after_user_boundary_cannot_restore_old_verdict(tmp_path):
    old = _assistant("Old review\nAGREE", uuid="old", stop_reason="end_turn")
    assert _extract(tmp_path, [
        old,
        {"type": "user", "message": {"role": "user", "content": "New request"}},
        old,
    ]) == ""


def test_replayed_null_block_does_not_undo_terminal_record(tmp_path):
    first = _assistant("Finding", uuid="first", stop_reason=None)
    terminal = _assistant("REVIEW END\nDISAGREE", uuid="last", stop_reason="end_turn")
    assert _extract(tmp_path, [first, terminal, first]) == "Finding\nREVIEW END\nDISAGREE"


def test_changed_record_with_same_uuid_can_reopen_completion(tmp_path):
    first = _assistant("Finding", uuid="first", stop_reason=None)
    terminal = _assistant("REVIEW END\nDISAGREE", uuid="last", stop_reason="end_turn")
    revised = _assistant("Revised finding", uuid="first", stop_reason=None)
    assert _extract(tmp_path, [first, terminal, revised]) == ""


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


def test_explicit_null_stop_reason_is_not_a_final_review(tmp_path):
    assert _extract(tmp_path, [_assistant("Unfinished\nAGREE", stop_reason=None)]) == ""


def test_null_stop_reason_requires_a_later_terminal_record(tmp_path):
    first = _assistant("First finding", uuid="one", stop_reason=None)
    terminal = _assistant("REVIEW END\nPARTIALLY AGREE", uuid="two", stop_reason="end_turn")
    assert _extract(tmp_path, [first, terminal]) == "First finding\nREVIEW END\nPARTIALLY AGREE"
    assert _extract(tmp_path, [first, terminal, _assistant("still writing", uuid="three", stop_reason=None)]) == ""


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


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_raw_unicode_separator_in_user_record_is_not_jsonl_boundary(tmp_path, separator):
    user = {"type": "user", "message": {"role": "user", "content": f"Prompt{separator}continued"}}
    assert _extract(tmp_path, [user, _assistant("Current review\nDISAGREE", stop_reason="end_turn")],
                    ensure_ascii=False) == "Current review\nDISAGREE"


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_raw_unicode_separator_in_final_text_is_preserved(tmp_path, separator):
    final = f"Finding{separator}detail\nREVIEW END\nDISAGREE"
    assert _extract(tmp_path, [_assistant(final, stop_reason="end_turn")],
                    ensure_ascii=False) == final


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_raw_unicode_separator_at_text_block_edge_survives(tmp_path, separator):
    records = [
        _assistant("First finding" + separator, uuid="first", stop_reason=None),
        _assistant("Further detail\nDISAGREE", uuid="last", stop_reason="end_turn"),
    ]
    assert _extract(tmp_path, records, ensure_ascii=False) == (
        "First finding" + separator + "\nFurther detail\nDISAGREE"
    )


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_raw_unicode_separator_at_message_edge_survives(tmp_path, separator):
    records = [
        _assistant(separator + "First finding", uuid="first", stop_reason=None),
        _assistant("DISAGREE" + separator, uuid="last", stop_reason="end_turn"),
    ]
    assert _extract(tmp_path, records, ensure_ascii=False) == (
        separator + "First finding\nDISAGREE" + separator
    )


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX PTY")
@pytest.mark.parametrize(("mode", "first", "last"), [
    ("review", "REVIEW START\n1. Must fix the first blocker", "REVIEW END\nPARTIALLY AGREE"),
    ("review", "REVIEW START\n1. Raw\u2028separator stays in text", "REVIEW END\nPARTIALLY AGREE"),
    ("review", "REVIEW START\n1. Edge separator\u2028", "REVIEW END\nPARTIALLY AGREE"),
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
Path("owned.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in json.loads(sys.argv[1])))
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
