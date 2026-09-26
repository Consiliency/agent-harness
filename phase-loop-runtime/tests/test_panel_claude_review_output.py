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


def _extract(tmp_path, records, *, ensure_ascii=True, require_terminal=False):
    path = tmp_path / "owned.jsonl"
    path.write_text("".join(json.dumps(record, ensure_ascii=ensure_ascii) + "\n" for record in records))
    if require_terminal:
        return pi._final_assistant_text_from_jsonl(path, require_terminal=True)
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


def test_president_terminal_status_ignores_replayed_null_block(tmp_path):
    first = _assistant("Finding", uuid="first", stop_reason=None)
    terminal = _assistant("I think it is fine", uuid="last", stop_reason="end_turn")
    assert _extract(tmp_path, [first, terminal, first], require_terminal=True) == (
        "Finding\nI think it is fine"
    )


def test_president_terminal_status_ignores_replayed_old_turn(tmp_path):
    old = _assistant("Old ruling", message_id="old", uuid="old", stop_reason="end_turn")
    current = _assistant("Current unfinished ruling", message_id="current", uuid="current")
    assert _extract(tmp_path, [
        old, {"type": "user", "message": {"role": "user", "content": "New request"}},
        current, old,
    ], require_terminal=True) == ""


def test_president_terminal_status_requires_explicit_completion(tmp_path):
    assert _extract(tmp_path, [_assistant("Current ruling", uuid="current")],
                    require_terminal=True) == ""


def test_president_terminal_status_reopened_by_changed_record(tmp_path):
    terminal = _assistant("Ruling", uuid="ruling", stop_reason="end_turn")
    revised = _assistant("Ruling revised", uuid="ruling")
    assert _extract(tmp_path, [terminal, revised], require_terminal=True) == ""


@pytest.mark.parametrize("stop_reason", [None, "max_tokens", "tool_use", "stop_sequence"])
def test_president_terminal_status_rejects_incomplete_or_unsupported_stop(tmp_path, stop_reason):
    assert _extract(tmp_path, [_assistant("Ruling", stop_reason=stop_reason)],
                    require_terminal=True) == ""


@pytest.mark.parametrize("error_field", ["model", "isApiErrorMessage"])
def test_president_terminal_status_rejects_synthetic_errors(tmp_path, error_field):
    record = _assistant("API Error: Request was aborted", stop_reason="end_turn")
    record["message"][error_field] = "<synthetic>" if error_field == "model" else True
    assert _extract(tmp_path, [record], require_terminal=True) == ""


def test_president_terminal_status_rejects_new_user_or_partial_json(tmp_path):
    terminal = _assistant("Ruling", stop_reason="end_turn")
    user = {"type": "user", "message": {"role": "user", "content": "New request"}}
    assert _extract(tmp_path, [terminal, user], require_terminal=True) == ""
    path = tmp_path / "owned.jsonl"
    path.write_text(json.dumps(terminal) + "\n{\"type\":")
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


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


def test_user_boundary_prevents_turns_from_joining(tmp_path):
    # r3: the fixture used to reuse one message id across the boundary; the API never reuses
    # an id, so that now fails closed (pinned below) and this keeps the boundary property.
    assert _extract(tmp_path, [
        _assistant("Old review", uuid="one", message_id="old"),
        {"type": "user", "message": {"role": "user", "content": "Continue"}},
        _assistant("New review\nDISAGREE", uuid="two"),
    ]) == "New review\nDISAGREE"


def test_a_history_message_id_reused_under_a_new_uuid_fails_closed(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Old review", uuid="one"),
        {"type": "user", "message": {"role": "user", "content": "Continue"}},
        _assistant("New review\nDISAGREE", uuid="two"),
    ]) == ""


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


# agent-harness#1002 round 1 (codex, claude): replay and interleave sequences.
def _jsonl(tmp_path, records):
    import json as _json
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(_json.dumps(r) for r in records) + "\n")
    return path


def _asst(text, *, mid, uuid=None, stop="end_turn"):
    rec = {"type": "assistant", "message": {"id": mid, "role": "assistant", "stop_reason": stop,
                                            "content": [{"type": "text", "text": text}]}}
    if uuid is not None:
        rec["uuid"] = uuid
    return rec


def _user(uuid, text="Review"):
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": text}}


def test_an_identityless_replay_after_a_new_request_is_not_the_answer(tmp_path):
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    path = _jsonl(tmp_path, [_asst("Old review\nAGREE", mid="old"), _user("new-request", "Review again"),
                             _asst("Old review\nAGREE", mid="old")])
    assert _final_assistant_text_from_jsonl(path) == ""


def test_a_replayed_request_and_answer_pair_keeps_the_answer(tmp_path):
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    pair = [_user("request"), _asst("Complete review\nAGREE", mid="review", uuid="answer")]
    assert _final_assistant_text_from_jsonl(_jsonl(tmp_path, pair + pair)) == "Complete review\nAGREE"


def test_a_message_interleaved_by_another_fails_closed(tmp_path):
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    path = _jsonl(tmp_path, [
        _asst("REVIEW START\n1. Blocking finding", mid="final", uuid="u1", stop=None),
        _asst("x", mid="other", uuid="u2"),
        _asst("REVIEW END\nPARTIALLY AGREE", mid="final", uuid="u3"),
    ])
    assert _final_assistant_text_from_jsonl(path) == ""


def test_a_rejournaled_user_turn_with_new_metadata_is_still_a_replay(tmp_path):
    """The real CLI re-journals a user record under the same uuid with a different promptId."""
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    first = {**_user("request"), "promptId": "p1"}
    again = {**_user("request"), "promptId": "p2"}
    path = _jsonl(tmp_path, [first, _asst("Complete review\nAGREE", mid="review", uuid="answer"), again])
    assert _final_assistant_text_from_jsonl(path) == "Complete review\nAGREE"


def test_a_user_record_with_a_different_message_is_a_new_turn(tmp_path):
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    path = _jsonl(tmp_path, [_user("request", "Review"), _asst("A\nAGREE", mid="m1", uuid="a1"),
                             _user("request", "Something else"), _asst("B\nAGREE", mid="m2", uuid="a2")])
    assert _final_assistant_text_from_jsonl(path) == "B\nAGREE"


def test_tool_use_content_in_the_final_group_fails_closed(tmp_path):
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    path = _jsonl(tmp_path, [
        _asst("Review\nAGREE", mid="review", uuid="a", stop=None),
        {"type": "assistant", "uuid": "b", "message": {"id": "review", "role": "assistant", "stop_reason": "end_turn",
                                                       "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]}},
    ])
    assert _final_assistant_text_from_jsonl(path) == ""


def test_a_rejournaled_answer_with_new_accounting_is_still_a_replay(tmp_path):
    """Measured on real CLI 2.1.282 transcripts: an assistant record re-journaled under the same
    uuid differs only in ``message.usage`` and ``parentUuid``; it must not fail the extraction."""
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    first = _asst("Complete review\nAGREE", mid="review", uuid="answer")
    first["message"]["usage"] = {"input_tokens": 6, "output_tokens": 40}
    first["parentUuid"] = "p1"
    again = _asst("Complete review\nAGREE", mid="review", uuid="answer")
    again["message"]["usage"] = {"input_tokens": 0, "output_tokens": 0}
    again["parentUuid"] = "p2"
    path = _jsonl(tmp_path, [_user("request"), first, _user("later-tool-result", "result"),
                             _asst("tool step", mid="tool", uuid="t1", stop="tool_use"), again])
    assert _final_assistant_text_from_jsonl(path) == ""  # a replay is not the answer to the LATER request
    path = _jsonl(tmp_path, [_user("request"), first, again])
    assert _final_assistant_text_from_jsonl(path) == "Complete review\nAGREE"


def test_a_rejournaled_answer_with_changed_content_fails_closed(tmp_path):
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    first = _asst("Complete review\nAGREE", mid="review", uuid="answer")
    edited = _asst("Complete review\nDISAGREE", mid="review", uuid="answer")
    path = _jsonl(tmp_path, [_user("request"), first, _user("later", "x"), edited])
    assert _final_assistant_text_from_jsonl(path) == ""


def test_a_damaged_line_mid_journal_does_not_block_a_later_answer(tmp_path):
    from phase_loop_runtime.panel_invoker import _final_assistant_text_from_jsonl
    import json as _json
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join([_json.dumps(_user("r1")), '{"type": "user", "message": {"role": "us',
                                _json.dumps(_user("r2")), _json.dumps(_asst("Review\nAGREE", mid="m", uuid="a"))]) + "\n")
    assert _final_assistant_text_from_jsonl(path) == "Review\nAGREE"


# agent-harness#1002 round 2 (codex, grok, claude): every sequence the board found.
def test_r2_identityless_replay_after_id_reuse_fails_closed(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Old review\nAGREE", stop_reason="end_turn"),
        _user("request-2", "Review again"),
        _assistant("Current review\nDISAGREE", uuid="answer-2", stop_reason="end_turn"),
        _assistant("Old review\nAGREE", stop_reason="end_turn"),
    ]) == ""


def test_r2_history_interleave_does_not_block_a_later_answer(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Earlier first block", message_id="A", uuid="a1", stop_reason=None),
        _assistant("Interleaved message", message_id="B", uuid="b1", stop_reason="end_turn"),
        _assistant("Earlier final block", message_id="A", uuid="a2", stop_reason="end_turn"),
        _user("new-request", "Perform a new review"),
        _assistant("Current complete review\nDISAGREE", message_id="C", uuid="c1", stop_reason="end_turn"),
    ]) == "Current complete review\nDISAGREE"


def test_r2_absent_then_null_stop_reason_is_not_final(tmp_path):
    assert _extract(tmp_path, [
        _assistant("Review\nAGREE", uuid="answer"),
        _assistant("Review\nAGREE", uuid="answer", stop_reason=None),
    ]) == ""


def test_r2_an_older_message_cannot_replace_a_newer_one(tmp_path):
    assert _extract(tmp_path, [
        _assistant("First review\nAGREE", message_id="m1", uuid="a1", stop_reason="end_turn"),
        _user("q2", "Second"),
        _assistant("Second review\nDISAGREE", message_id="m2", uuid="a2", stop_reason="end_turn"),
        _assistant("First review\nAGREE", message_id="m1", uuid="a3", stop_reason="end_turn"),
    ]) == ""


def test_r2_an_old_answer_after_a_pending_new_one_fails_closed(tmp_path):
    assert _extract(tmp_path, [
        _user("u1"), _assistant("Old\nAGREE", message_id="old", uuid="a1", stop_reason="end_turn"),
        _user("u2", "Review again"),
        _assistant("REVIEW START\n1. Blocking", message_id="new", uuid="b1", stop_reason=None),
        _assistant("Old\nAGREE", message_id="old", uuid="a1-copy", stop_reason="end_turn"),
    ]) == ""


def test_r2_a_completed_record_rewritten_under_its_uuid_fails_closed(tmp_path):
    v1 = _assistant("1. Blocking\nDISAGREE", uuid="r1", stop_reason="end_turn")
    v2 = _assistant("No findings\nAGREE", uuid="r1", stop_reason="end_turn")
    assert _extract(tmp_path, [_user("u1"), v1, v2, v1]) == ""


# Round 3 (agent-harness#1002): a record in the final turn that copies or updates history
# fails closed, history rewrites never block a later answer, and a changed request is a turn.


def test_r3_a_changed_request_under_a_reused_user_uuid_is_a_new_turn(tmp_path):
    path = _jsonl(tmp_path, [_user("u", "Review A"), _asst("Old\nAGREE", mid="m", uuid="a"),
                             _user("u", "Review B")])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r3_an_identityless_copy_of_history_cannot_replace_the_answer(tmp_path):
    old = {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
                                            "content": [{"type": "text", "text": "Old\nAGREE"}]}}
    current = {"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
                                                "content": [{"type": "text", "text": "Current\nDISAGREE"}]}}
    path = _jsonl(tmp_path, [old, _user("u2", "Review again"), current, old])
    assert pi._final_assistant_text_from_jsonl(path) == ""
    path = _jsonl(tmp_path, [old, _user("u2", "Review again"), old])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r3_a_rewrite_in_history_does_not_block_a_later_answer(tmp_path):
    path = _jsonl(tmp_path, [
        _asst("Old\nAGREE", mid="m1", uuid="a1"), _asst("Rewritten\nDISAGREE", mid="m1", uuid="a1"),
        _user("u2", "Independent new review"), _asst("Current\nDISAGREE", mid="m2", uuid="a2"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == "Current\nDISAGREE"


@pytest.mark.parametrize("text", ["Old review\nDISAGREE", "No findings\nAGREE"])
def test_r3_a_completed_message_id_copied_under_a_fresh_uuid_fails_closed(tmp_path, text):
    path = _jsonl(tmp_path, [
        _user("u1", "Review the change"), _asst("Old review\nDISAGREE", mid="msg_1", uuid="a1"),
        _user("u2", "Review again"), _asst(text, mid="msg_1", uuid="a2"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r3_a_fresh_uuid_copy_after_the_current_answer_fails_closed(tmp_path):
    path = _jsonl(tmp_path, [
        _asst("Old review\nAGREE", mid="review"), _user("request-2", "Review again"),
        _asst("Current review\nDISAGREE", mid="review", uuid="answer-2"),
        _asst("Old review\nAGREE", mid="review", uuid="old-copy"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r3_a_message_cannot_be_rewritten_after_a_non_final_stop(tmp_path):
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("1. Blocking\nDISAGREE", mid="m", uuid="r1", stop="max_tokens"),
        _asst("No findings\nAGREE", mid="m", uuid="r1"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r3_a_history_record_completed_after_a_new_request_is_not_the_answer(tmp_path):
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("Old\nAGREE", mid="m", uuid="a1", stop=None),
        _user("u2", "Review again"), _asst("Old\nAGREE", mid="m", uuid="a1"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r3_a_same_uuid_update_from_null_to_end_turn_completes_the_message(tmp_path):
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("Findings\nAGREE", mid="m", uuid="a1", stop=None),
        _asst("Findings\nAGREE", mid="m", uuid="a1"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == "Findings\nAGREE"


def test_r3_a_raw_separator_in_a_later_user_record_still_moves_the_boundary(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(_asst("Old\nAGREE", mid="m", uuid="a1")) + "\n"
                    + json.dumps(_user("u2", "Review \u2028 again"), ensure_ascii=False) + "\n"
                    + json.dumps({"type": "summary", "summary": "s"}) + "\n",
                    encoding="utf-8")  # the trailing line keeps a splitlines() break from being the tail
    assert pi._final_assistant_text_from_jsonl(path) == ""


@pytest.mark.parametrize("bad_id", [["m"], {"id": "m"}, 7])
def test_r3_a_non_string_message_id_fails_closed(tmp_path, bad_id):
    path = _jsonl(tmp_path, [_user("u1"), _asst("Findings\nAGREE", mid=bad_id, uuid="a1")])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r3_a_parallel_tool_call_continuing_across_a_tool_result_keeps_the_answer(tmp_path):
    # Measured shape (Claude Code 2.1.282): the second tool_use block of one message is written
    # after the first tool_result, so a message id legitimately spans that user record.
    tool = {"type": "tool_use", "id": "t", "name": "x", "input": {}}
    first = {"type": "assistant", "uuid": "b1", "message": {"id": "m1", "role": "assistant",
                                                             "stop_reason": "tool_use", "content": [tool]}}
    second = {"type": "assistant", "uuid": "b2", "message": {"id": "m1", "role": "assistant",
                                                              "stop_reason": "tool_use", "content": [tool]}}
    result = {"type": "user", "uuid": "r1", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}
    path = _jsonl(tmp_path, [_user("u1"), first, result, second, _asst("Done\nAGREE", mid="m2", uuid="b3")])
    assert pi._final_assistant_text_from_jsonl(path) == "Done\nAGREE"


# Round 4 (agent-harness#1002): replays of superseded versions, stop-state rewrites, stripped
# identity, and the two fail-closed clauses no earlier test reached.


def test_r4_a_replay_of_the_open_version_after_completion_keeps_the_answer(tmp_path):
    open_ = _asst("Review\nAGREE", mid="m", uuid="a", stop=None)
    path = _jsonl(tmp_path, [_user("u"), open_, _asst("Review\nAGREE", mid="m", uuid="a"), open_])
    assert pi._final_assistant_text_from_jsonl(path) == "Review\nAGREE"


def test_r4_a_replay_of_a_superseded_block_does_not_revert_it(tmp_path):
    first = _asst("1. Blocking\nDISAGREE", mid="m", uuid="a1", stop=None)
    path = _jsonl(tmp_path, [_user("u1"), first, _asst("No findings", mid="m", uuid="a1", stop=None),
                             first, _asst("REVIEW END", mid="m", uuid="a2")])
    assert pi._final_assistant_text_from_jsonl(path) == "No findings\nREVIEW END"


@pytest.mark.parametrize("before", ["max_tokens", _MISSING])
def test_r4_only_an_open_stop_reason_may_change(tmp_path, before):
    first = _asst("1. Blocking\nDISAGREE", mid="m", uuid="r1")
    if before is _MISSING:
        del first["message"]["stop_reason"]
    else:
        first["message"]["stop_reason"] = before
    path = _jsonl(tmp_path, [_user("u1"), first, _asst("1. Blocking\nDISAGREE", mid="m", uuid="r1")])
    assert pi._final_assistant_text_from_jsonl(path) == ""


@pytest.mark.parametrize("tail_uuid", [None, "fresh"])
@pytest.mark.parametrize("current", [True, False])
def test_r4_a_history_answer_stripped_of_its_id_cannot_become_the_answer(tmp_path, tail_uuid, current):
    records = [_asst("Old review\nAGREE", mid="old", uuid="a0"), _user("u2", "Review again")]
    if current:
        records.append(_asst("Current review\nDISAGREE", mid="new", uuid="a1"))
    records.append(_asst("Old review\nAGREE", mid=None, uuid=tail_uuid))
    assert pi._final_assistant_text_from_jsonl(_jsonl(tmp_path, records)) == ""


def test_r4_a_repeated_identityless_record_in_the_turn_fails_closed(tmp_path):
    path = _jsonl(tmp_path, [_user("u2"), _asst("Old\nAGREE", mid=None), _asst("Current\nDISAGREE", mid=None),
                             _asst("Old\nAGREE", mid=None)])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r4_uuid_and_uuidless_records_of_the_final_message_fail_closed(tmp_path):
    path = _jsonl(tmp_path, [_user("u1"), _asst("Current\nDISAGREE", mid="m", uuid="a1", stop=None),
                             _asst("Old\nAGREE", mid="m")])
    assert pi._final_assistant_text_from_jsonl(path) == ""


# Round 5 (agent-harness#1002).


@pytest.mark.parametrize("tail_uuid", [None, "fresh"])
def test_r5_an_identityless_copy_of_an_earlier_answer_in_the_same_turn_fails_closed(tmp_path, tail_uuid):
    path = _jsonl(tmp_path, [_user("u1", "Review this change"),
                             _asst("Earlier review\nAGREE", mid="old", uuid="a0"),
                             _asst("Current review\nDISAGREE", mid="current", uuid="a1"),
                             _asst("Earlier review\nAGREE", mid=None, uuid=tail_uuid)])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r5_an_identityless_answer_keeps_its_own_open_version(tmp_path):
    path = _jsonl(tmp_path, [_user("u1"), _asst("Findings\nAGREE", mid=None, uuid="a1", stop=None),
                             _asst("Findings\nAGREE", mid=None, uuid="a1")])
    assert pi._final_assistant_text_from_jsonl(path) == "Findings\nAGREE"


@pytest.mark.parametrize("bad_stop", [{}, ["end_turn"], 1])
def test_r5_a_non_string_stop_reason_fails_closed(tmp_path, bad_stop):
    path = _jsonl(tmp_path, [_user("u1"), _asst("Review\nAGREE", mid="m", uuid="a1", stop=bad_stop)])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_r5_a_stale_open_copy_of_a_stopped_history_record_does_not_blank_the_answer(tmp_path):
    path = _jsonl(tmp_path, [_user("u1", "Round 4"), _asst("Old\nDISAGREE", mid="old", uuid="a0"),
                             _user("u2", "Round 5"), _asst("Old\nDISAGREE", mid="old", uuid="a0", stop=None),
                             _asst("New\nAGREE", mid="new", uuid="a1")])
    assert pi._final_assistant_text_from_jsonl(path) == "New\nAGREE"


def test_r5_an_open_stop_reason_cannot_become_absent(tmp_path):
    record = _asst("1. Blocking\nDISAGREE", mid="m", uuid="a1")
    del record["message"]["stop_reason"]
    path = _jsonl(tmp_path, [_user("u1"), _asst("1. Blocking\nDISAGREE", mid="m", uuid="a1", stop=None), record])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_president_route_rejects_a_record_level_api_error(tmp_path):
    record = _asst("Upstream failure", mid="m", uuid="a1")
    record["isApiErrorMessage"] = True
    path = _jsonl(tmp_path, [_user("u1"), record])
    assert pi._final_assistant_text_from_jsonl(path) == "Upstream failure"
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


def test_president_route_rejects_a_stop_sequence_on_any_block_of_the_answer(tmp_path):
    path = _jsonl(tmp_path, [_user("u1"), _asst("Part one", mid="m", uuid="a", stop=None),
                             _asst("FORCING DECISION: APPROVE", mid="m", uuid="b"),
                             _asst("Part one", mid="m", uuid="a", stop="stop_sequence")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


def test_president_route_accepts_open_earlier_blocks_before_the_end_turn(tmp_path):
    path = _jsonl(tmp_path, [_user("u1"), _asst("Part one", mid="m", uuid="a", stop=None),
                             _asst("FORCING DECISION: APPROVE", mid="m", uuid="b")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == (
        "Part one\nFORCING DECISION: APPROVE")


@pytest.mark.parametrize("mid", ["m", None])
@pytest.mark.parametrize("flag", ["model", "message_error", "record_error"])
def test_president_route_rejects_a_flag_on_a_superseded_version(tmp_path, flag, mid):
    open_ = _asst("FORCING DECISION: APPROVE", mid=mid, uuid="a", stop=None)
    if flag == "model":
        open_["message"]["model"] = "<synthetic>"
    elif flag == "message_error":
        open_["message"]["isApiErrorMessage"] = True
    else:
        open_["isApiErrorMessage"] = True
    path = _jsonl(tmp_path, [_user("u1"), open_, _asst("FORCING DECISION: APPROVE", mid=mid, uuid="a")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


@pytest.mark.parametrize("flag", ["model", "message_error", "record_error"])
def test_president_route_rejects_a_marked_exact_replay_of_the_answer(tmp_path, flag):
    # agent-harness#1017 r6 (codex): the replay rule ignores these markers, so the marked copy
    # is dropped as an exact replay unless the president gate scans raw records.
    answer = _asst("FORCING DECISION: APPROVE", mid="m", uuid="a")
    marked = _asst("FORCING DECISION: APPROVE", mid="m", uuid="a")
    if flag == "model":
        marked["message"]["model"] = "<synthetic>"
    elif flag == "message_error":
        marked["message"]["isApiErrorMessage"] = True
    else:
        marked["isApiErrorMessage"] = True
    path = _jsonl(tmp_path, [_user("u1"), answer, marked])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


def test_president_route_rejects_a_superseded_tool_use_version(tmp_path):
    tool = _asst("", mid="m", uuid="a", stop=None)
    tool["message"]["content"] = [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]
    path = _jsonl(tmp_path, [_user("u1"), tool, _asst("FORCING DECISION: APPROVE", mid="m", uuid="a")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


@pytest.mark.parametrize("earlier_mid", [None, "x"])
def test_president_route_rejects_a_flagged_record_under_the_answer_uuid_with_another_id(tmp_path, earlier_mid):
    # agent-harness#1017 r5 (claude): the flagged record shares the answer's uuid but not its id.
    flagged = _asst("FORCING DECISION: APPROVE", mid=earlier_mid, uuid="a", stop=None)
    flagged["isApiErrorMessage"] = True
    path = _jsonl(tmp_path, [_user("u1"), flagged, _asst("FORCING DECISION: APPROVE", mid="m", uuid="a")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


@pytest.mark.parametrize("flag", ["model", "message_error", "record_error"])
def test_president_route_rejects_a_marked_answer_with_neither_id_nor_uuid(tmp_path, flag):
    # agent-harness#1017 r7 (codex, claude, grok): the raw scan selected by id or uuid only.
    answer = _asst("API Error: Request was aborted", mid=None)
    if flag == "model":
        answer["message"]["model"] = "<synthetic>"
    elif flag == "message_error":
        answer["message"]["isApiErrorMessage"] = True
    else:
        answer["isApiErrorMessage"] = True
    path = _jsonl(tmp_path, [_user("u1"), answer])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


def test_president_route_rejects_a_damaged_newer_request_followed_by_metadata(tmp_path):
    # agent-harness#1017 r8 (codex): the damaged user line is not the last line, so the review
    # route skips it as history; the president route must fail closed instead.
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(_user("u1", "First request")) + "\n"
                    + json.dumps(_asst("I think it is fine", mid="m1", uuid="a1")) + "\n"
                    + '{"type":"user","uuid":"u2","message":{"role":"user","content":\n'
                    + json.dumps({"type": "progress"}) + "\n")
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""
    assert pi._final_assistant_text_from_jsonl(path) == "I think it is fine"  # review route unchanged


@pytest.mark.parametrize("earlier", ["stop_sequence", "tool_use", "synthetic", "api_error"])
def test_president_route_rejects_a_bad_earlier_message_in_the_final_turn(tmp_path, earlier):
    # agent-harness#1017 r8 differential sweep: an earlier message of the final turn that is not
    # a clean completed block means the turn is not a genuine single completed answer.
    first = _asst("partial", mid="m1", uuid="a1", stop=None)
    if earlier == "stop_sequence":
        first["message"]["stop_reason"] = "stop_sequence"
    elif earlier == "tool_use":
        first["message"]["content"] = [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]
    elif earlier == "synthetic":
        first["message"]["model"] = "<synthetic>"
    else:
        first["isApiErrorMessage"] = True
    path = _jsonl(tmp_path, [_user("u1"), first, _asst("FORCING DECISION: APPROVE", mid="m2", uuid="a2")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""


# agent-harness#1077: an answer capped at max_tokens and auto-continued after an isMeta
# "resume" user record is ONE answer; returning only the continuation drops its head.


def _resume(uuid="r1"):
    return {"type": "user", "uuid": uuid, "isMeta": True,
            "message": {"role": "user", "content": "Output token limit hit. Resume directly."}}


def test_1077_a_capped_answer_is_joined_with_its_continuation(tmp_path):
    path = _jsonl(tmp_path, [
        _user("u1"),
        _asst("REVIEW START\n1. Blocking finding", mid="msg_1", uuid="a1", stop="max_tokens"),
        _resume(),
        _asst("REVIEW END\nPARTIALLY AGREE", mid="msg_2", uuid="a2"),
    ])
    expected = "REVIEW START\n1. Blocking finding\nREVIEW END\nPARTIALLY AGREE"
    assert pi._final_assistant_text_from_jsonl(path) == expected
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == expected


def test_1077_a_chain_of_three_is_joined_in_order(tmp_path):
    path = _jsonl(tmp_path, [
        _user("u1"),
        _asst("part one", mid="m1", uuid="a1", stop="max_tokens"), _resume("r1"),
        _asst("part two", mid="m2", uuid="a2", stop="max_tokens"), _resume("r2"),
        _asst("part three\nAGREE", mid="m3", uuid="a3"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == "part one\npart two\npart three\nAGREE"


def test_1077_a_continuation_whose_head_is_not_capped_fails_closed(tmp_path):
    # A CLI resume record after a NON-capped message continues nothing and cannot be a
    # genuine request either, so the journal is ambiguous and fails closed (#1088 r1).
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("done\nAGREE", mid="m1", uuid="a1"),
        _resume(), _asst("unrelated", mid="m2", uuid="a2"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_1077_a_capped_head_with_a_tool_call_fails_closed(tmp_path):
    head = _asst("partial", mid="m1", uuid="a1", stop="max_tokens")
    head["message"]["content"].append({"type": "tool_use", "id": "t", "name": "x", "input": {}})
    path = _jsonl(tmp_path, [_user("u1"), head, _resume(), _asst("rest\nAGREE", mid="m2", uuid="a2")])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_1077_an_identityless_continuation_fails_closed_rather_than_truncating(tmp_path):
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("head", mid=None, uuid="a1", stop="max_tokens"),
        _resume(), _asst("tail\nAGREE", mid="m2", uuid="a2"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == ""


def test_1077_a_non_meta_user_after_max_tokens_is_a_new_request(tmp_path):
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("head", mid="m1", uuid="a1", stop="max_tokens"),
        _user("u2", "A different request"), _asst("answer\nAGREE", mid="m2", uuid="a2"),
    ])
    assert pi._final_assistant_text_from_jsonl(path) == "answer\nAGREE"


@pytest.mark.parametrize("marker", ["synthetic", "api_error"])
def test_1077_the_president_route_still_rejects_a_marked_capped_head(tmp_path, marker):
    head = _asst("head", mid="m1", uuid="a1", stop="max_tokens")
    if marker == "synthetic":
        head["message"]["model"] = "<synthetic>"
    else:
        head["isApiErrorMessage"] = True
    path = _jsonl(tmp_path, [_user("u1"), head, _resume(), _asst("FORCING DECISION: APPROVE", mid="m2", uuid="a2")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=True) == ""



# agent-harness#1088 round 1: each reviewer sequence, on both routes.

def _meta(uuid, text):
    return {"type": "user", "uuid": uuid, "isMeta": True, "message": {"role": "user", "content": text}}


@pytest.mark.parametrize("terminal", [False, True])
def test_1088_an_unrecognised_meta_record_after_a_cap_fails_closed(tmp_path, terminal):
    # codex r1 (1): an isMeta record that is not the CLI's resume must not join two answers.
    path = _jsonl(tmp_path, [
        _user("u1", "Review change A."), _asst("A head", mid="m1", uuid="a1", stop="max_tokens"),
        _meta("u2", "New request: review change B only."), _asst("B answer", mid="m2", uuid="a2"),
    ])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=terminal) == ""


@pytest.mark.parametrize("terminal", [False, True])
def test_1088_a_stale_open_replay_does_not_hide_the_cap(tmp_path, terminal):
    # codex r1 (2) / grok: the head is joined, not dropped as history.
    head = _asst("HEAD: blocking finding", mid="m1", uuid="a1", stop="max_tokens")
    stale = _asst("HEAD: blocking finding", mid="m1", uuid="a1", stop=None)
    path = _jsonl(tmp_path, [_user("u1"), head, stale, _resume(), _asst("TAIL\nDISAGREE", mid="m2", uuid="a2")])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=terminal) == "HEAD: blocking finding\nTAIL\nDISAGREE"


@pytest.mark.parametrize("terminal", [False, True])
def test_1088_an_exact_replay_of_the_resume_is_not_a_new_request(tmp_path, terminal):
    # codex r1 (3): #1002's exact-user-replay rule holds for resume records too.
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("HEAD", mid="m1", uuid="a1", stop="max_tokens"),
        _resume("r1"), _asst("TAIL\nAGREE", mid="m2", uuid="a2"), _resume("r1"),
    ])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=terminal) == "HEAD\nTAIL\nAGREE"


@pytest.mark.parametrize("terminal", [False, True])
def test_1088_a_continuation_that_crosses_a_tool_call_fails_closed(tmp_path, terminal):
    # grok r1: the head would otherwise be history behind the tool_result boundary.
    tool = _asst("", mid="m2", uuid="a2", stop="tool_use")
    tool["message"]["content"] = [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]
    result = {"type": "user", "uuid": "t1", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}
    path = _jsonl(tmp_path, [
        _user("u1"), _asst("BLOCKING: auth missing", mid="m1", uuid="a1", stop="max_tokens"),
        _resume(), tool, result, _asst("AGREE", mid="m3", uuid="a3"),
    ])
    assert pi._final_assistant_text_from_jsonl(path, require_terminal=terminal) == ""


def test_1088_the_resume_text_may_arrive_as_a_text_block(tmp_path):
    resume = {"type": "user", "uuid": "r1", "isMeta": True, "message": {"role": "user", "content": [
        {"type": "text", "text": "Output token limit hit. Resume directly."}]}}
    path = _jsonl(tmp_path, [_user("u1"), _asst("head", mid="m1", uuid="a1", stop="max_tokens"),
                             resume, _asst("tail\nAGREE", mid="m2", uuid="a2")])
    assert pi._final_assistant_text_from_jsonl(path) == "head\ntail\nAGREE"
