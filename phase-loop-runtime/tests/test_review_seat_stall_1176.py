"""agent-harness#1176: a heartbeat_only seat that makes no genuine progress must not wait silently.

Two mechanisms, measured on the hung seats of 2026-09-29:

* The Claude TUI gave up on its own: four thinking-only ``max_tokens`` stops, then a
  ``<synthetic>`` ``isApiErrorMessage`` record (``error: max_output_tokens``), then idle at the
  prompt. That journaled give-up ends the leg at once, DEGRADED with a typed reason.
* Silence alone never ends a heartbeat_only leg (ah#892). Past a generous, configurable window
  of no genuine progress the monitor record carries a typed ``seat_progress_stalled`` notice and
  one operator warning is logged; the leg keeps waiting.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as panel


# --- transcript fixtures, shaped on the real hung-seat journal (Claude Code 2.1.28x) ---------

REQUEST = {"type": "user", "uuid": "u-request",
           "message": {"role": "user", "content": "Please perform the review requested."}}
META = [{"type": "last-prompt"}, {"type": "ai-title"}, {"type": "mode"},
        {"type": "permission-mode"}, {"type": "atis-latch"}]


def capped(i: int) -> dict:
    return {"type": "assistant", "uuid": f"a-{i}",
            "message": {"id": f"msg_{i}", "role": "assistant", "model": "claude-sonnet-5",
                        "stop_reason": "max_tokens",
                        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}]}}


def resume(i: int) -> dict:
    return {"type": "user", "uuid": f"r-{i}", "isMeta": True,
            "message": {"role": "user", "content": [{"type": "text", "text": panel._CLAUDE_RESUME_PROMPT}]}}


def api_error(kind: str) -> dict:
    record = {"type": "assistant", "uuid": f"err-{kind}", "isApiErrorMessage": True, "error": kind,
              "message": {"id": f"msg_err_{kind}", "role": "assistant", "model": "<synthetic>",
                          "stop_reason": "stop_sequence",
                          "content": [{"type": "text", "text": f"API Error: {kind}"}]}}
    if kind == "max_output_tokens":
        record["apiError"] = kind
    if kind == "rate_limit":
        record["apiErrorStatus"] = 429
    return record


def retries_exhausted(kind: str = "max_output_tokens") -> list[dict]:
    return [*META, REQUEST, capped(1), resume(1), capped(2), resume(2), capped(3), resume(3),
            capped(4), api_error(kind), {"type": "system", "subtype": "turn_duration"}, *META]


def write(path: Path, records: list[dict], tail: str = "") -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + tail, encoding="utf-8")
    return path


# --- the typed terminal state ------------------------------------------------------------------

@pytest.mark.parametrize("kind,code", [
    ("max_output_tokens", "claude_seat_output_budget_exhausted"),
    ("rate_limit", "claude_seat_rate_limited"),
    ("server_error", "claude_seat_provider_api_error"),
])
def test_journaled_give_up_is_a_typed_terminal_state(tmp_path, kind, code):
    path = write(tmp_path / "t.jsonl", retries_exhausted(kind))
    assert panel._claude_transcript_provider_gave_up(path) == code


@pytest.mark.parametrize("records,tail", [
    # (a) mid-retry: a max_tokens stop plus the CLI's own resume prompt is still in flight
    #     (agent-harness#1077 continues exactly this shape into a real answer).
    ([*META, REQUEST, capped(1), resume(1)], ""),
    ([*META, REQUEST, capped(1), resume(1), capped(2)], ""),
    # (b) the CLI went on after the error: a newer user record follows it.
    ([*META, REQUEST, capped(1), api_error("max_output_tokens"), resume(9)], ""),
    # (c) the error belongs to an earlier request, not the current one.
    ([*META, REQUEST, api_error("rate_limit"),
      {**REQUEST, "uuid": "u-second", "message": {"role": "user", "content": "second request"}}], ""),
    # a genuine assistant record after the error: the CLI did not stop there.
    ([*META, REQUEST, api_error("server_error"),
      {"type": "assistant", "uuid": "a-late", "message": {"id": "msg_late", "role": "assistant",
                                                            "stop_reason": None, "content": []}}], ""),
    # (d) the writer is mid-append: the last line does not parse yet.
    (retries_exhausted(), '{"type": "last-pro'),
    # no genuine request at all: none, only the CLI's own meta prompt, only a tool_result.
    ([*META, api_error("rate_limit")], ""),
    ([*META, resume(1), api_error("rate_limit")], ""),
    ([*META, {"type": "user", "uuid": "u-tool", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "x"}]}}, api_error("rate_limit")], ""),
    ([*META], ""),
    ([], ""),
])
def test_anything_short_of_a_journaled_give_up_is_not_terminal(tmp_path, records, tail):
    path = write(tmp_path / "t.jsonl", records, tail)
    assert panel._claude_transcript_provider_gave_up(path) is None


def test_missing_transcript_is_not_terminal(tmp_path):
    assert panel._claude_transcript_provider_gave_up(tmp_path / "absent.jsonl") is None


# --- the live TUI session: a fake provider that keeps its heartbeat alive ---------------------

def _fast_tui(monkeypatch):
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READ_INTERVAL_S", .02)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_TRANSCRIPT_INTERVAL_S", .05)
    monkeypatch.setattr(panel, "_LEG_LIVENESS_READ_INTERVAL_S", .05)


def _provider(transcript: Path, records: list[dict], release: Path) -> list[str]:
    """A fake Claude TUI: prints a banner, journals ``records``, then repaints its spinner
    (cosmetic, never novel) until ``release`` exists -- alive, but no genuine progress."""
    body = "".join(json.dumps(r) + "\n" for r in records)
    script = (
        "import sys, time\nfrom pathlib import Path\n"
        "print('Claude Code fake provider ready for review', flush=True)\n"
        "time.sleep(.2)\n"
        f"Path({str(transcript)!r}).write_text({body!r})\n"
        "i = 0\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    sys.stdout.write('\\r* Thinking... (%ds . esc to interrupt)' % i); sys.stdout.flush()\n"
        "    i += 1; time.sleep(.05)\n"
    )
    return [sys.executable, "-c", script]


@pytest.mark.parametrize("heartbeat_only", [True, False])
def test_retry_exhausted_provider_ends_the_leg_degraded_at_once(tmp_path, monkeypatch, heartbeat_only):
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = (panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                    stall_notice_s=3600) if heartbeat_only else None)
    # Only an emergency guard: the assertion below is that the leg ends LONG before it.
    guard = threading.Timer(20, lambda: (release.touch(), monitor and monitor.cancel.set()))
    guard.start()
    started = time.monotonic()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, retries_exhausted(), release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=600, backstop_s=600,
            stall_threshold_s=600, env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert log == "claude_seat_output_budget_exhausted"
    assert type(log) is panel._HarnessCode
    assert rc != 0 and text == ""
    assert time.monotonic() - started < 10
    if monitor is not None:
        record = json.loads(monitor.path.read_text())
        assert record["provider_terminal_state"] == "claude_seat_output_budget_exhausted"


def test_live_but_progressless_seat_is_surfaced_not_killed(tmp_path, monkeypatch, caplog):
    """The provider keeps its spinner (heartbeat) alive mid-retry and journals nothing new. The
    seat is NOT ended; its record carries a typed stalled notice and one warning is logged."""
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=.3)
    notices: list[dict] = []
    observe = monitor.observe

    def capture(*args, **kwargs):
        observe(*args, **kwargs)
        row = json.loads(monitor.path.read_text())
        if row["progress_notice"] == "seat_progress_stalled":
            notices.append(row)
            if len(notices) >= 5:  # well past the window, still waiting: now cancel it
                monitor.cancel.set()

    monkeypatch.setattr(monitor, "observe", capture)
    guard = threading.Timer(20, monitor.cancel.set)
    guard.start()
    caplog.set_level(logging.WARNING, logger=panel.__name__)
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, [*META, REQUEST, capped(1), resume(1)], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent", timeout_s=1,
            backstop_s=1, stall_threshold_s=.05, env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert log == "review_operation_cancelled", "the stalled seat was ended instead of surfaced"
    assert notices, "no typed stalled notice was ever surfaced"
    assert notices[0]["progress_notice_count"] == 1
    assert notices[0]["stall_notice_s"] == .3
    assert notices[0]["provider_terminal_state"] is None
    warnings = [r.getMessage() for r in caplog.records if "seat_progress_stalled" in r.getMessage()]
    assert len(warnings) == 1, warnings
    assert "Thinking" not in warnings[0] and "Please perform" not in warnings[0]


def test_print_mode_leg_with_cpu_heartbeat_but_no_output_is_surfaced(tmp_path, monkeypatch):
    """The print-mode liveness loop shares the monitor: a child burning CPU (its heartbeat) with
    no output gets the notice and still runs to completion."""
    monkeypatch.setattr(panel, "_LEG_LIVENESS_READ_INTERVAL_S", .02)
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=.2)
    observe = monitor.observe

    def capture(*args, **kwargs):
        observe(*args, **kwargs)
        if json.loads(monitor.path.read_text())["progress_notice"] == "seat_progress_stalled":
            release.touch()

    monkeypatch.setattr(monitor, "observe", capture)
    guard = threading.Timer(20, release.touch)
    guard.start()
    try:
        result = panel._run_leg_with_liveness(
            [sys.executable, "-c",
             "from pathlib import Path\n"
             f"while not Path({str(release)!r}).exists():\n    sum(range(10000))\n"
             "print('verdict')\n"],
            cwd=tmp_path, env=os.environ, deadline_s=.05, stall_threshold_s=.05,
            review_monitor=monitor,
        )
    finally:
        guard.cancel()
    assert result.returncode == 0 and result.stdout == "verdict\n"
    assert monitor.record["progress_notice_count"] >= 1


# --- the notice itself --------------------------------------------------------------------------

def test_notice_rises_once_per_crossing_and_clears_on_progress(tmp_path):
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event(), stall_notice_s=10)
    monitor.observe(1.0)
    assert monitor.record["progress_notice"] is None
    monitor.observe(10.0)
    monitor.observe(11.0)
    assert monitor.record["progress_notice"] == "seat_progress_stalled"
    assert monitor.record["progress_notice_count"] == 1
    monitor.observe(0.1)  # genuine progress resumed
    assert monitor.record["progress_notice"] is None
    monitor.observe(12.0)
    assert monitor.record["progress_notice_count"] == 2
    assert json.loads(monitor.path.read_text())["progress_notice"] == "seat_progress_stalled"


def test_never_observed_progress_counts_from_seat_start(tmp_path):
    """Issue comment 2: 'the review exists but was never observed' must surface too."""
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event(), stall_notice_s=10)
    monitor.observe()
    assert monitor.record["progress_notice"] is None
    monitor.started -= 11
    monitor.observe()
    assert monitor.record["progress_notice"] == "seat_progress_stalled"


def test_notice_window_is_configurable_and_generous_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(panel._REVIEW_STALL_NOTICE_ENV, raising=False)
    default = panel._ReviewMonitor(tmp_path / "a.json", "t", 0, threading.Event())
    # A max-effort turn is progress-silent through its whole thinking phase (10 to 20 min per
    # attempt, and one healthy seat had a 27-minute gap), so the default clears that widely.
    assert default.record["stall_notice_s"] == panel._REVIEW_STALL_NOTICE_S >= 3600
    monkeypatch.setenv(panel._REVIEW_STALL_NOTICE_ENV, "7200")
    assert panel._ReviewMonitor(tmp_path / "b.json", "t", 0, threading.Event()).record["stall_notice_s"] == 7200
    for bad in ("0", "-5", "nan", "inf", "soon"):
        monkeypatch.setenv(panel._REVIEW_STALL_NOTICE_ENV, bad)
        assert panel._ReviewMonitor(tmp_path / "c.json", "t", 0, threading.Event()).record[
            "stall_notice_s"] == panel._REVIEW_STALL_NOTICE_S


def test_terminal_observation_never_raises_a_notice(tmp_path):
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event(), stall_notice_s=1)
    monitor.started -= 100
    monitor.observe(terminal="completed")
    assert monitor.record["progress_notice"] is None


# --- the leg result -----------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["claude_seat_output_budget_exhausted", "claude_seat_rate_limited",
                                  "claude_seat_provider_api_error"])
def test_give_up_code_reaches_the_leg_as_degraded_with_its_reason(monkeypatch, tmp_path, code):
    monkeypatch.setattr(panel, "_run_claude_tui_session",
                        lambda **kw: (1, "", panel._HarnessCode(code), ""))
    monkeypatch.setattr(panel, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(panel, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(panel, "_under_claude_code", lambda env=None: False)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list = []
    status, text = panel._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink)
    assert (status, text) == ("DEGRADED", "")
    assert sink and str(sink[-1].rendered()) == code
    assert code in panel._HARNESS_DETAIL_CODES


# --- round 1 (agent-harness#1194): a give-up never outranks a review ---------------------------

ANSWER = {"type": "assistant", "uuid": "a-real",
          "message": {"id": "msg_real", "role": "assistant", "model": "claude-sonnet-5",
                      "stop_reason": "end_turn",
                      "content": [{"type": "text", "text": "Review complete\nAGREE"}]}}


def test_grok_a_completed_answer_before_an_error_is_not_a_give_up(tmp_path):
    """Grok r1 Finding A, verbatim shape: request, completed answer, then an error record."""
    for kind in ("max_output_tokens", "rate_limit", "server_error"):
        path = write(tmp_path / "t.jsonl", [REQUEST, ANSWER, api_error(kind)])
        assert panel._claude_transcript_provider_gave_up(path) is None


def test_grok_a_session_never_turns_a_completed_answer_into_a_degraded_give_up(tmp_path, monkeypatch):
    """The live loop on Grok's transcript: the leg is NOT ended as a give-up. (The existing
    fail-closed answer parser does not accept an answer an error record follows, so the bounded
    leg is reclaimed by its stall timer; the typed give-up never fires.)"""
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    guard = threading.Timer(20, release.touch)
    guard.start()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, [REQUEST, ANSWER, api_error("max_output_tokens")], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent", timeout_s=600,
            backstop_s=600, stall_threshold_s=1.5, env=os.environ,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert log not in ("claude_seat_output_budget_exhausted", "claude_seat_rate_limited",
                       "claude_seat_provider_api_error"), log


def test_an_accepted_review_file_wins_over_a_journaled_give_up(tmp_path, monkeypatch):
    """The ordering invariant: the review path is checked first."""
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    output = tmp_path / "panel-claude.txt"
    output.write_text("Review complete\nAGREE\n")
    release = tmp_path / "release"
    guard = threading.Timer(20, release.touch)
    guard.start()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, retries_exhausted(), release), cwd=tmp_path,
            prompt="input", output_file=output, timeout_s=600, backstop_s=600,
            stall_threshold_s=600, env=os.environ,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert (rc, log) == (0, "claude_tui_file_output")
    assert text.strip().endswith("AGREE")


# --- round 1: re-journaled records are identity, not position or progress (codex F001) ----------

def test_codex_f001_replayed_api_error_does_not_end_current_request(tmp_path):
    """codex r1 F001 falsifier, verbatim."""
    request = {"type": "user", "uuid": "u1", "message": {
        "role": "user", "content": "Review change A."}}
    error = {"type": "assistant", "uuid": "error-a", "isApiErrorMessage": True,
             "error": "rate_limit", "apiErrorStatus": 429, "parentUuid": "u1",
             "message": {"id": "error-message", "role": "assistant",
                         "model": "<synthetic>", "stop_reason": "stop_sequence",
                         "content": [{"type": "text", "text": "API Error: rate_limit"}]}}
    current = {"type": "user", "uuid": "u2", "message": {
        "role": "user", "content": "Review change B."}}
    thinking = {"type": "assistant", "uuid": "thinking-b", "message": {
        "id": "message-b", "role": "assistant", "stop_reason": None,
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}]}}
    replay = {**error, "parentUuid": "thinking-b",
              "message": {**error["message"], "usage": {"input_tokens": 0}}}
    transcript = tmp_path / "session.jsonl"
    answer = {"type": "assistant", "uuid": "answer-b", "message": {
        "id": "message-b", "role": "assistant", "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Review complete\nAGREE"}]}}
    detected = []
    for later_request in ([], [current]):
        records = [request, error, *later_request, thinking, replay]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in records))
        detected.append(panel._claude_transcript_provider_gave_up(transcript))
        assert panel._final_assistant_text_from_jsonl(transcript) == ""
        records.append(answer)
        transcript.write_text("".join(json.dumps(row) + "\n" for row in records))
        assert panel._final_assistant_text_from_jsonl(transcript) == "Review complete\nAGREE"
    records = [request, error, {**request, "promptId": "re-journaled"}]
    transcript.write_text("".join(json.dumps(row) + "\n" for row in records))
    missed = panel._claude_transcript_provider_gave_up(transcript)
    assert (detected, missed) == ([None, None], "claude_seat_rate_limited")


def test_a_changed_request_under_a_reused_uuid_is_a_new_request(tmp_path):
    changed = {**REQUEST, "message": {"role": "user", "content": "A different request."}}
    path = write(tmp_path / "t.jsonl", [REQUEST, api_error("rate_limit"), changed])
    assert panel._claude_transcript_provider_gave_up(path) is None


def test_record_versions_grow_only_with_new_provider_records(tmp_path):
    path = tmp_path / "t.jsonl"
    base = [*META, REQUEST, capped(1), resume(1)]
    count, _ = panel._claude_transcript_state(write(path, base))
    # rewritten metadata and exact or re-linked replays are not progress
    replays = [*base, *META, capped(1), {**resume(1), "promptId": "x"},
               {**capped(1), "parentUuid": "elsewhere"}]
    assert panel._claude_transcript_state(write(path, replays))[0] == count
    # a new record, and a new version of an open record, are
    assert panel._claude_transcript_state(write(path, [*replays, capped(2)]))[0] == count + 1
    open_block = {"type": "assistant", "uuid": "s-1", "message": {
        "id": "msg_s", "role": "assistant", "stop_reason": None,
        "content": [{"type": "text", "text": "partial"}]}}
    closed = {**open_block, "message": {**open_block["message"], "stop_reason": "end_turn"}}
    grown = panel._claude_transcript_state(write(path, [*base, open_block]))[0]
    assert panel._claude_transcript_state(write(path, [*base, open_block, closed]))[0] == grown + 1


def _replaying_provider(transcript: Path, records: list[dict], release: Path) -> list[str]:
    """Like ``_provider``, but it keeps re-journaling the same records and metadata, so the
    transcript FILE grows forever while the provider makes no genuine progress."""
    body = "".join(json.dumps(r) + "\n" for r in records)
    again = "".join(json.dumps(r) + "\n" for r in [*META, records[-1]])
    script = (
        "import sys, time\nfrom pathlib import Path\n"
        "print('Claude Code fake provider ready for review', flush=True)\n"
        f"p = Path({str(transcript)!r}); p.write_text({body!r})\n"
        f"while not Path({str(release)!r}).exists():\n"
        f"    with p.open('a') as f: f.write({again!r})\n"
        "    sys.stdout.write('\\r* Thinking...'); sys.stdout.flush(); time.sleep(.05)\n"
    )
    return [sys.executable, "-c", script]


def test_re_journaled_records_do_not_mask_a_stall(tmp_path, monkeypatch):
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=.5)
    observe = monitor.observe

    def capture(*args, **kwargs):
        observe(*args, **kwargs)
        if monitor.record["progress_notice"] == "seat_progress_stalled":
            monitor.cancel.set()

    monkeypatch.setattr(monitor, "observe", capture)
    # Well inside the TUI's 8 s submit delay, so nothing but the replays is in play.
    guard = threading.Timer(4, lambda: (release.touch(), monitor.cancel.set()))
    guard.start()
    started = time.monotonic()
    try:
        _rc, _text, log, _tail = panel._run_claude_tui_session(
            command=_replaying_provider(transcript, [*META, REQUEST, capped(1), resume(1)], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent", timeout_s=1,
            backstop_s=1, stall_threshold_s=.05, env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert log == "review_operation_cancelled"
    assert monitor.record["progress_notice_count"] >= 1, "re-journaling masked the stall"
    assert time.monotonic() - started < 3.5


def test_api_error_flag_as_string_true_is_still_a_give_up(tmp_path):
    record = {**api_error("max_output_tokens"), "isApiErrorMessage": "true"}
    path = write(tmp_path / "t.jsonl", [REQUEST, capped(1), record])
    assert panel._claude_transcript_provider_gave_up(path) == "claude_seat_output_budget_exhausted"


def test_unbrokered_leg_never_reads_a_neighbouring_give_up(tmp_path, monkeypatch):
    """Claude r1 N4: only the exact brokered transcript may end a leg. An unbrokered session whose
    cwd project dir holds another session's give-up journal is not ended by it."""
    _fast_tui(monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    write(project / "neighbour.jsonl", retries_exhausted())
    monkeypatch.setattr(panel, "_claude_project_dir_for_cwd", lambda cwd: project)
    release = tmp_path / "release"
    timer = threading.Timer(1.5, release.touch)
    timer.start()
    try:
        _rc, _text, log, _tail = panel._run_claude_tui_session(
            command=_provider(tmp_path / "unused.jsonl", [], release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=600, backstop_s=600,
            stall_threshold_s=600, env=os.environ,
        )
    finally:
        timer.cancel()
        release.touch()
    assert log not in ("claude_seat_output_budget_exhausted", "claude_seat_rate_limited",
                       "claude_seat_provider_api_error"), log


# --- round 1: the notice reaches the board (codex F002, Gemini seat) ---------------------------

def _stalled_board(tmp_path, monkeypatch):
    from phase_loop_runtime import cli
    from phase_loop_runtime.advisor_board import backing
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "review", 0,
                                   threading.Event(), stall_notice_s=10)
    monitor.observe(11)
    monitor.observe(terminal="user_cancel")
    legs = [panel.PanelLegResult(seat.harness, "OK", "Review complete\nAGREE",
                                 seat_key=seat.seat_key) for seat in DEFAULT_BOARD.seats]
    legs[0] = panel.PanelLegResult(legs[0].leg, "UNAVAILABLE", "",
                                   detail="review_operation_cancelled",
                                   seat_key=legs[0].seat_key)
    object.__setattr__(legs[0], "_review_monitoring", dict(monitor.record))
    monkeypatch.setattr(panel, "_preflight_gemini_heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(backing, "prepare_review_composition_authorization",
                        lambda *a, **k: object())
    monkeypatch.setattr(backing, "prepare_review_isolation_authorization",
                        lambda *a, **k: object())
    monkeypatch.setattr(panel, "invoke_board",
                        lambda *a, **k: panel.PanelResult(tuple(legs)))
    bundle = tmp_path / "bundle.md"
    bundle.write_text("Review material\n")
    return cli, bundle, legs


def test_codex_f002_board_json_retains_stalled_seat_monitoring(tmp_path, monkeypatch, capsys):
    """codex r1 F002 falsifier, verbatim assertions."""
    cli, bundle, legs = _stalled_board(tmp_path, monkeypatch)
    assert cli.main(["advisor-board", str(bundle), "--monitoring-policy",
                     "heartbeat_only", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "seat_progress_stalled" in json.dumps(payload)
    stalled = payload["legs"][0]["review_monitoring"]
    assert stalled["progress_notice_count"] == 1 and stalled["stall_notice_s"] == 10
    assert all("review_monitoring" not in leg for leg in payload["legs"][1:])


def test_board_text_summary_names_the_stalled_seat(tmp_path, monkeypatch, capsys):
    cli, bundle, legs = _stalled_board(tmp_path, monkeypatch)
    cli.main(["advisor-board", str(bundle), "--monitoring-policy", "heartbeat_only"])
    err = capsys.readouterr().err
    line = [row for row in err.splitlines() if "[seat_progress_stalled]" in row]
    assert len(line) == 1 and str(legs[0].seat_key) in line[0] and "10s" in line[0], err


def test_streamed_verdict_file_carries_the_monitoring_record(tmp_path):
    leg = panel.PanelLegResult("claude", "DEGRADED", "", detail="claude_seat_rate_limited",
                               seat_key="claude")
    object.__setattr__(leg, "_review_monitoring", {"progress_notice": "seat_progress_stalled",
                                                    "progress_notice_count": 2})
    panel._write_incremental_verdict(tmp_path, 0, leg)
    body = json.loads(next(tmp_path.glob("leg-0000-*.verdict.json")).read_text())
    assert body["review_monitoring"]["progress_notice_count"] == 2
    plain = panel.PanelLegResult("codex", "OK", "Review complete\nAGREE", seat_key="codex")
    panel._write_incremental_verdict(tmp_path, 1, plain)
    assert "review_monitoring" not in json.loads(
        next(tmp_path.glob("leg-0001-*.verdict.json")).read_text())
