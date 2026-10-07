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

# Each fake provider below is a seat on the owned route (agent-harness#1222): it runs in the
# filtered namespace and journals where Claude Code does, under its private config dir; the
# host collects that exact journal (``_JOURNAL``).
_JOURNAL = (
    "import os, re\n"
    "_sid = sys.argv[sys.argv.index('--session-id') + 1]\n"
    "_journal = Path(os.environ['CLAUDE_CONFIG_DIR']) / 'projects' / "
    "re.sub(r'[^A-Za-z0-9.-]', '-', os.getcwd()) / (_sid + '.jsonl')\n"
)


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
        "import sys, time\nfrom pathlib import Path\n" + _JOURNAL +
        "print('Claude Code fake provider ready for review', flush=True)\n"
        "time.sleep(.2)\n"
        f"_journal.write_text({body!r})\n"
        "i = 0\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    sys.stdout.write('\\r* Thinking... (%ds . esc to interrupt)' % i); sys.stdout.flush()\n"
        "    i += 1; time.sleep(.05)\n"
    )
    return ["/usr/bin/python3", "-c", script]


@pytest.mark.usefixtures("owned_review_network")
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


@pytest.mark.usefixtures("owned_review_network")
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
                                  "claude_seat_provider_api_error", "claude_seat_usage_limited",
                                  "claude_seat_usage_limited: usage_limit (resets 18:00, Sep 30 2026)"])
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
    assert panel._finalize_leg_detail(panel._HarnessCode(code)) == code


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


@pytest.mark.usefixtures("owned_review_network")
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
    # r2 (Grok, Gemini seat): not only no give-up -- the completed review itself is returned.
    assert (rc, log, text) == (0, "claude_tui_broker_final_assistant", "Review complete\nAGREE")


@pytest.mark.usefixtures("owned_review_network")
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
        "import sys, time\nfrom pathlib import Path\n" + _JOURNAL +
        "print('Claude Code fake provider ready for review', flush=True)\n"
        f"p = _journal; p.write_text({body!r})\n"
        f"while not Path({str(release)!r}).exists():\n"
        f"    with p.open('a') as f: f.write({again!r})\n"
        "    sys.stdout.write('\\r* Thinking...'); sys.stdout.flush(); time.sleep(.05)\n"
    )
    return ["/usr/bin/python3", "-c", script]


@pytest.mark.usefixtures("owned_review_network")
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


@pytest.mark.usefixtures("owned_review_network")
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


# --- round 1 addendum (Opus seat N2, N3, N5) ---------------------------------------------------

def test_terminal_observation_ends_the_active_notice_but_keeps_its_history(tmp_path):
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event(), stall_notice_s=10)
    monitor.observe(11.0)
    assert monitor.record["progress_notice"] == "seat_progress_stalled"
    monitor.observe(terminal="completed")
    record = json.loads(monitor.path.read_text())
    assert record["progress_notice"] is None and record["progress_notice_count"] == 1
    assert record["last_progress_notice"] == "seat_progress_stalled"


def _usage_limit(**quota) -> dict:
    """The measured weekly-limit record: ``error: rate_limit`` plus a rejected ``quotaLimits``."""
    record = api_error("rate_limit")
    record["quotaLimits"] = {"status": "rejected", "rateLimitType": "seven_day", **quota}
    record["message"]["content"] = [{"type": "text", "text": "You've hit your weekly limit · resets 6pm (UTC)"}]
    return record


def test_usage_limit_is_told_apart_from_a_429_and_keeps_its_reset_time(tmp_path):
    path = tmp_path / "t.jsonl"
    code = panel._claude_transcript_provider_gave_up(
        write(path, [REQUEST, _usage_limit(resetsAt=1790877600)]))  # 2026-10-01T18:00:00Z
    assert code == "claude_seat_usage_limited: usage_limit (resets 18:00, Oct 1 2026)"
    assert panel._finalize_leg_detail(panel._HarnessCode(code)) == code
    assert panel._claude_transcript_provider_gave_up(
        write(path, [REQUEST, _usage_limit()])) == "claude_seat_usage_limited"
    for bad in ("soon", 12, True, 10**12):
        assert panel._claude_transcript_provider_gave_up(
            write(path, [REQUEST, _usage_limit(resetsAt=bad)])) == "claude_seat_usage_limited"
    plain = {**api_error("rate_limit"), "quotaLimits": {"status": "allowed_warning"}}
    assert panel._claude_transcript_provider_gave_up(write(path, [REQUEST, plain])) == "claude_seat_rate_limited"


def test_governed_record_carries_a_stalled_seat_as_a_warn(tmp_path):
    from phase_loop_runtime import governed_review
    leg = panel.PanelLegResult("claude", "OK", "Review complete\nAGREE", seat_key="claude")
    object.__setattr__(leg, "_review_monitoring", {"progress_notice": None, "progress_notice_count": 2,
                                                    "stall_notice_s": 3600.0})
    quiet = panel.PanelLegResult("codex", "OK", "Review complete\nAGREE", seat_key="codex")
    findings = governed_review._findings_from_panel(panel.PanelResult((leg, quiet)), "a" * 40)
    stalled = [f for f in findings if f.code == "seat_progress_stalled"]
    assert len(stalled) == 1 and stalled[0].severity == "warn"
    assert "claude" in stalled[0].reason and "3600s" in stalled[0].reason and "2 notice" in stalled[0].reason


@pytest.mark.usefixtures("owned_review_network")
def test_an_unchanged_transcript_is_parsed_once_not_every_tick(tmp_path, monkeypatch):
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    calls = {"final": 0, "state": 0}
    final, state = panel._final_assistant_text_from_jsonl, panel._claude_transcript_state

    def counted_final(*a, **k):
        calls["final"] += 1
        return final(*a, **k)

    def counted_state(*a, **k):
        calls["state"] += 1
        return state(*a, **k)

    monkeypatch.setattr(panel, "_final_assistant_text_from_jsonl", counted_final)
    monkeypatch.setattr(panel, "_claude_transcript_state", counted_state)
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=3600)
    ticks = 0
    observe = monitor.observe

    def capture(*args, **kwargs):
        nonlocal ticks
        ticks += 1
        observe(*args, **kwargs)

    monkeypatch.setattr(monitor, "observe", capture)
    guard = threading.Timer(2, monitor.cancel.set)
    guard.start()
    try:
        panel._run_claude_tui_session(
            command=_provider(transcript, [*META, REQUEST, capped(1), resume(1)], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent", timeout_s=1,
            backstop_s=1, stall_threshold_s=.05, env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert ticks > 20
    # while the file is absent, once it is written, and at most one more read across a write
    assert calls["final"] <= 3 and calls["state"] <= 3, calls


# --- round 2 (Grok and Gemini seats): an API-error record is never answer text ------------------

def _answer(uuid: str, mid: str, text: str) -> dict:
    return {"type": "assistant", "uuid": uuid, "message": {
        "id": mid, "role": "assistant", "model": "claude-sonnet-5", "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}]}}


def test_r2_the_answer_parser_skips_a_stray_error_after_a_completed_review(tmp_path):
    """The seats' direct-call repro: before r2 each returned the stray 'API Error: ...' text."""
    path = tmp_path / "t.jsonl"
    for kind in ("max_output_tokens", "rate_limit", "server_error"):
        write(path, [REQUEST, ANSWER, api_error(kind)])
        assert panel._final_assistant_text_from_jsonl(path) == "Review complete\nAGREE"
    second = {"type": "user", "uuid": "u-2", "message": {"role": "user", "content": "Second request."}}
    write(path, [REQUEST, _answer("a-1", "m-1", "First\nAGREE"), second,
                 _answer("a-2", "m-2", "Second\nDISAGREE"), api_error("server_error")])
    assert panel._final_assistant_text_from_jsonl(path) == "Second\nDISAGREE"
    assert panel._claude_transcript_provider_gave_up(path) is None
    # an error with no answer before it is still no answer, and still a give-up
    write(path, [REQUEST, capped(1), api_error("max_output_tokens")])
    assert panel._final_assistant_text_from_jsonl(path) == ""
    assert panel._claude_transcript_provider_gave_up(path) == "claude_seat_output_budget_exhausted"


@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("heartbeat_only", [True, False])
def test_r2_session_returns_the_completed_review_not_the_stray_error(tmp_path, monkeypatch, heartbeat_only):
    """The seats' full-session repro. Before r2: bounded ended claude_tui_stalled with
    text='API Error: max_output_tokens'; heartbeat_only never resolved."""
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = (panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                    stall_notice_s=3600) if heartbeat_only else None)
    guard = threading.Timer(15, lambda: (release.touch(), monitor and monitor.cancel.set()))
    guard.start()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, [REQUEST, ANSWER, api_error("max_output_tokens")], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent", timeout_s=600,
            backstop_s=600, stall_threshold_s=1.5, env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert (rc, log, text) == (0, "claude_tui_broker_final_assistant", "Review complete\nAGREE")


@pytest.mark.usefixtures("owned_review_network")
def test_r2_president_route_fails_closed_then_gives_up_instead_of_hanging(tmp_path, monkeypatch):
    """The president parser rejects any turn holding an error record (ah#1016/#1017), so no
    answer there can be accepted; the give-up must end that leg rather than leave it waiting."""
    ruling = _answer("a-r", "m-r", "No blocking findings.\nFORCING DECISION: APPROVE")
    records = [REQUEST, ruling, api_error("server_error")]
    path = write(tmp_path / "t.jsonl", records)
    assert panel._final_assistant_text_from_jsonl(path, require_terminal=True) == ""
    assert panel._claude_transcript_state(path, require_terminal=True)[1] == "claude_seat_provider_api_error"
    assert panel._claude_transcript_state(path)[1] is None
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=3600)
    guard = threading.Timer(15, lambda: (release.touch(), monitor.cancel.set()))
    guard.start()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, records, release), cwd=tmp_path, prompt="input",
            output_file=tmp_path / "absent", timeout_s=600, backstop_s=600, stall_threshold_s=600,
            env=os.environ, mode="president", review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert (log, text) == ("claude_seat_provider_api_error", "") and rc != 0


# --- round 2 (codex): the verbatim falsifiers ----------------------------------------------------

@pytest.mark.usefixtures("owned_review_network")
def test_codex_r2_f001_completed_review_survives_stray_error(tmp_path, monkeypatch):
    """codex r2 F001 falsifier, verbatim."""
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(
        tmp_path / "monitor.json", "review", 0, threading.Event(),
        stall_notice_s=3600,
    )
    guard = threading.Timer(3, monitor.cancel.set)
    guard.start()
    try:
        rc, text, log, _ = panel._run_claude_tui_session(
            command=_provider(transcript, [REQUEST, ANSWER,
                api_error("max_output_tokens")], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent",
            timeout_s=600, backstop_s=600, stall_threshold_s=600,
            env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert (rc, text) == (0, "Review complete\nAGREE"), (rc, text, log)


def test_codex_r2_f002_replayed_open_version_cannot_restore_give_up(tmp_path):
    """codex r2 F002 falsifier, verbatim."""
    transcript = tmp_path / "session.jsonl"
    opened = {**ANSWER, "message": {
        **ANSWER["message"], "stop_reason": None,
    }}
    records = [REQUEST, opened, ANSWER, api_error("rate_limit")]
    count, gave_up = panel._claude_transcript_state(write(transcript, records))
    assert gave_up is None
    replay = {**opened, "parentUuid": "re-journaled"}
    after_count, after_give_up = panel._claude_transcript_state(
        write(transcript, [*records, replay]),
    )
    assert after_count == count
    assert after_give_up is None, "a stale open replay undid the completed answer"


def test_r3_a_changed_record_after_a_stop_is_a_rejected_answer_and_the_give_up_ends_it(tmp_path):
    """r3 (codex F001, Grok G3-1). The parser fails closed on a record whose content changes
    after it stopped (agent-harness#1002), so no answer is accepted; the turn then ends in an
    error record, so the outcome is the give-up. A replay of the earlier version changes
    nothing. CHANGED from r2, which asserted the give-up was suppressed (``None``) here --
    the detector/parser disagreement that left a heartbeat_only seat waiting."""
    early = {**ANSWER, "message": {**ANSWER["message"], "stop_reason": "max_tokens",
                                    "content": [{"type": "thinking", "thinking": "", "signature": "s"}]}}
    records = [REQUEST, early, ANSWER, api_error("server_error")]
    path = write(tmp_path / "t.jsonl", records)
    for shape in (records, [*records, early]):
        write(path, shape)
        assert panel._final_assistant_text_from_jsonl(path) == ""
        assert panel._claude_transcript_provider_gave_up(path) == "claude_seat_provider_api_error"


@pytest.mark.parametrize("variant", ["A1-changed-content", "A2-missing-stop-key"])
def test_r3_grok_g3_1_unseen_open_version_then_error_ends_degraded(tmp_path, variant):
    """Grok r3 G3-1, both shapes. CHANGED from r2's
    ``test_r2_completion_is_sticky_against_an_unseen_open_version``, which asserted ``None``."""
    if variant == "A1-changed-content":
        reopened = {**ANSWER, "message": {**ANSWER["message"], "stop_reason": None,
                                           "content": [{"type": "text", "text": "partial"}]}}
    else:
        reopened = {**ANSWER, "message": {k: v for k, v in ANSWER["message"].items() if k != "stop_reason"}}
    path = write(tmp_path / "t.jsonl", [REQUEST, ANSWER, reopened, api_error("server_error")])
    assert panel._final_assistant_text_from_jsonl(path) == ""
    assert panel._claude_transcript_provider_gave_up(path) == "claude_seat_provider_api_error"


@pytest.mark.usefixtures("owned_review_network")
def test_codex_r3_f001_unseen_open_replay_cannot_hold_a_give_up_open(tmp_path, monkeypatch):
    """codex r3 F001 falsifier, verbatim."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    reopened = {**ANSWER, "message": {
        **ANSWER["message"], "stop_reason": None,
        "content": [{"type": "text", "text": "partial"}],
    }}
    monitor = panel._ReviewMonitor(
        tmp_path / "monitor.json", "review", 0, threading.Event(),
        stall_notice_s=3600,
    )
    guard = threading.Timer(3, monitor.cancel.set)
    guard.start()
    try:
        rc, text, log, _ = panel._run_claude_tui_session(
            command=_provider(transcript, [REQUEST, ANSWER, reopened,
                api_error("server_error")], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent",
            timeout_s=600, backstop_s=600, stall_threshold_s=600,
            env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert log != "review_operation_cancelled", (rc, text, log)


# --- round 3: one classifier; every terminal outcome ends the leg -------------------------------

def test_r3_president_error_then_ruling_is_rejected_not_pending(tmp_path):
    """Grok r3 N1: the president parser fails closed on any error record in the turn, and the
    turn then ENDED (end_turn) -- terminal, so ``rejected``, never left pending."""
    ruling = _answer("a-r", "m-r", "No blocking findings.\nFORCING DECISION: APPROVE")
    path = write(tmp_path / "t.jsonl", [REQUEST, api_error("server_error"), ruling])
    outcome = panel._claude_transcript_outcome(path, require_terminal=True)
    assert (outcome.kind, outcome.code, outcome.text) == ("rejected", "claude_seat_transcript_rejected", "")
    assert panel._claude_transcript_outcome(path).kind == "answer"  # the review route accepts it


@pytest.mark.usefixtures("owned_review_network")
def test_r3_a_completed_review_without_a_verdict_is_handed_back_not_left_waiting(tmp_path, monkeypatch):
    """Grok r3 N2: a completed answer the review route cannot accept as a verdict used to leave a
    heartbeat_only seat waiting forever. It is a terminal outcome: handed back as it is."""
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=3600)
    guard = threading.Timer(15, lambda: (release.touch(), monitor.cancel.set()))
    guard.start()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, [REQUEST, _answer("a", "m", "Review complete")], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent", timeout_s=600,
            backstop_s=600, stall_threshold_s=600, env=os.environ, review_monitor=monitor,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert (rc, text, log) == (0, "Review complete", "claude_tui_broker_terminal_nonconforming")
    assert panel._classify_leg(rc, text, log) == "DEGRADED"


def test_r3_rejected_reaches_the_leg_as_degraded_with_its_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "_run_claude_tui_session",
                        lambda **kw: (1, "", panel._HarnessCode("claude_seat_transcript_rejected"), ""))
    monkeypatch.setattr(panel, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(panel, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(panel, "_under_claude_code", lambda env=None: False)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list = []
    status, text = panel._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink)
    assert (status, text, str(sink[-1].rendered())) == ("DEGRADED", "", "claude_seat_transcript_rejected")


def _generated_transcript(rng) -> tuple[list[dict], str, bool]:
    """A random journal from the measured record shapes, re-journaling included. Returns the
    records, an optional damaged tail, and whether its LAST line is a fresh terminal record
    (an API error, or a completed answer) journaled after a genuine request."""
    records: list[dict] = [*META]
    assistants: list[dict] = []
    requested = False
    fresh_terminal = False
    for step in range(rng.randint(1, 9)):
        roll = rng.random()
        n = f"{step}-{rng.randrange(10**6)}"
        fresh_terminal = False
        if roll < .15 or not requested:
            records.append({"type": "user", "uuid": f"u-{n}", "message": {"role": "user", "content": f"request {n}"}})
            requested = True
        elif roll < .25:
            records.append(resume(int(step)))
        elif roll < .35:
            record = capped(int(step))
            record["uuid"], record["message"]["id"] = f"c-{n}", f"mc-{n}"
            records.append(record)
            assistants.append(record)
        elif roll < .45:
            record = {"type": "assistant", "uuid": f"o-{n}", "message": {
                "id": f"mo-{n}", "role": "assistant", "stop_reason": None,
                "content": [{"type": "text", "text": "partial"}]}}
            records.append(record)
            assistants.append(record)
        elif roll < .60:
            text = rng.choice(["Review complete\nAGREE", "Review complete", "x\nDISAGREE"])
            record = _answer(f"a-{n}", f"ma-{n}", text)
            if rng.random() < .5:  # streamed: journaled open first, then stopped
                streaming = {**record, "message": {**record["message"], "stop_reason": None}}
                records.append(streaming)
                assistants.append(streaming)
            records.append(record)
            assistants.append(record)
            fresh_terminal = True
        elif roll < .75:
            record = api_error(rng.choice(["max_output_tokens", "rate_limit", "server_error"]))
            record["uuid"], record["message"]["id"] = f"e-{n}", f"me-{n}"
            records.append(record)
            assistants.append(record)
            fresh_terminal = True
        elif roll < .80 and assistants:
            earlier = rng.choice(assistants)
            records.append({**earlier, "parentUuid": f"replay-{n}"})
        elif roll < .85 and assistants:
            # r4 (codex F001): an API-error UPDATE under an earlier record's uuid and id, with
            # a null, missing or ordinary stop_reason -- terminal evidence, never a replay.
            earlier = rng.choice(assistants)
            record = api_error(rng.choice(["max_output_tokens", "rate_limit", "server_error"]))
            record["uuid"], record["message"]["id"] = earlier["uuid"], earlier["message"]["id"]
            stop = rng.choice(["null", "missing", "kept"])
            if stop == "null":
                record["message"]["stop_reason"] = None
            elif stop == "missing":
                del record["message"]["stop_reason"]
            records.append(record)
            assistants.append(record)
            fresh_terminal = record not in records[:-1]
        elif roll < .88:
            # r4 (codex F001): an open sidechain record interleaved anywhere
            records.append({"type": "assistant", "uuid": f"side-{n}", "isSidechain": True,
                            "message": {"id": f"ms-{n}", "role": "assistant", "stop_reason": None,
                                        "content": []}})
        elif roll < .93 and assistants:
            earlier = rng.choice(assistants)
            records.append({**earlier, "message": {**earlier["message"], "stop_reason": None,
                                                    "content": [{"type": "text", "text": f"changed {n}"}]}})
        else:
            records.extend(META)
    tail = '{"type": "assist' if rng.random() < .1 else ""
    return records, tail, fresh_terminal and not tail


def test_r3_property_views_agree_and_a_terminal_turn_is_never_pending(tmp_path):
    """Over generated journals, on both routes: the parser view and the give-up view are views of
    one outcome (they always agree), and a turn whose last line is a fresh terminal record
    after a genuine request is never ``pending`` -- so it can never leave a seat waiting."""
    import random

    path = tmp_path / "t.jsonl"
    rng = random.Random(1194)
    terminal_cases = 0
    for _ in range(1500):
        records, tail, fresh_terminal = _generated_transcript(rng)
        write(path, records, tail)
        for president in (False, True):
            outcome = panel._claude_transcript_outcome(path, require_terminal=president)
            assert panel._final_assistant_text_from_jsonl(path, require_terminal=president) == outcome.text
            assert panel._claude_transcript_state(path, require_terminal=president) == (
                outcome.versions, outcome.code if outcome.kind in ("gave_up", "rejected") else None)
            assert (outcome.kind == "answer") == bool(outcome.text)
            assert (outcome.code is None) == (outcome.kind in ("answer", "pending"))
            if fresh_terminal:
                terminal_cases += 1
                assert outcome.kind != "pending", (president, records)
    assert terminal_cases > 500  # the property was exercised, not vacuously true


def test_r4_property_a_sidechain_after_a_terminal_record_never_makes_it_pending(tmp_path):
    """Sidechain records never decide the main turn's last record: appending open sidechain
    records after any terminal journal leaves the outcome unchanged."""
    import random

    path = tmp_path / "t.jsonl"
    rng = random.Random(4)
    checked = 0
    for _ in range(600):
        records, tail, fresh_terminal = _generated_transcript(rng)
        if not fresh_terminal:
            continue
        side = {"type": "assistant", "uuid": "side-x", "isSidechain": True,
                "message": {"id": "side-m", "role": "assistant", "stop_reason": None, "content": []}}
        for president in (False, True):
            before = panel._claude_transcript_outcome(write(path, records), require_terminal=president)
            after = panel._claude_transcript_outcome(write(path, [*records, side, side]),
                                                     require_terminal=president)
            assert (after.kind, after.code) == (before.kind, before.code) and after.kind != "pending"
            checked += 1
    assert checked > 200


def test_r3_a_replayed_streaming_version_cannot_reopen_a_ended_turn(tmp_path):
    """The forward-only rule still decides between terminal and pending when there is no
    answer: on the president route a turn holding an error and then an ended ruling is
    ``rejected``; replaying the ruling's earlier open version must not make it ``pending``."""
    ruling = _answer("a-r", "m-r", "No blocking findings.\nFORCING DECISION: APPROVE")
    streaming = {**ruling, "message": {**ruling["message"], "stop_reason": None}}
    records = [REQUEST, api_error("server_error"), streaming, ruling]
    path = tmp_path / "t.jsonl"
    for shape in (records, [*records, {**streaming, "parentUuid": "re-journaled"}]):
        write(path, shape)
        assert panel._claude_transcript_outcome(path, require_terminal=True).kind == "rejected"


@pytest.mark.usefixtures("owned_review_network")
def test_r3_president_session_ends_rejected_instead_of_waiting(tmp_path, monkeypatch):
    _fast_tui(monkeypatch)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    ruling = _answer("a-r", "m-r", "No blocking findings.\nFORCING DECISION: APPROVE")
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=3600)
    guard = threading.Timer(15, lambda: (release.touch(), monitor.cancel.set()))
    guard.start()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, [REQUEST, api_error("server_error"), ruling], release),
            cwd=tmp_path, prompt="input", output_file=tmp_path / "absent", timeout_s=600,
            backstop_s=600, stall_threshold_s=600, env=os.environ, mode="president",
            review_monitor=monitor, allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert (log, text) == ("claude_seat_transcript_rejected", "") and rc != 0
    assert monitor.record["provider_terminal_state"] == "claude_seat_transcript_rejected"



# --- round 4 (codex F001): an API-error update is terminal evidence; "last" is append order -----

@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("mode", ["review", "president"])
@pytest.mark.parametrize("heartbeat_only", [False, True])
@pytest.mark.parametrize("shape", ["null-stop", "missing-stop", "interleaved"])
def test_codex_r4_f001_terminal_api_error_update_cannot_remain_pending(
    tmp_path, monkeypatch, mode, heartbeat_only, shape,
):
    """codex r4 F001 falsifier, verbatim (12 cases)."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    cap = capped(1)
    error = api_error("max_output_tokens")
    error["uuid"], error["message"]["id"] = cap["uuid"], cap["message"]["id"]
    records = [REQUEST, cap, error]
    if shape == "null-stop":
        error["message"]["stop_reason"] = None
    elif shape == "missing-stop":
        del error["message"]["stop_reason"]
    else:
        records.insert(2, {
            "type": "assistant", "uuid": "side", "isSidechain": True,
            "message": {"id": "side-msg", "role": "assistant",
                        "stop_reason": None, "content": []},
        })
    monitor = panel._ReviewMonitor(
        tmp_path / "monitor.json", "review", 0, threading.Event(),
        stall_notice_s=3600,
    )
    guard = threading.Timer(2, monitor.cancel.set)
    guard.start()
    try:
        rc, text, log, _ = panel._run_claude_tui_session(
            command=_provider(transcript, records, release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=10,
            backstop_s=10, stall_threshold_s=.4, env=os.environ, mode=mode,
            review_monitor=monitor if heartbeat_only else None,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    outcome = panel._claude_transcript_outcome(
        transcript, require_terminal=mode == "president",
    )
    assert log == "claude_seat_output_budget_exhausted", (rc, text, log, outcome)
    assert rc != 0 and text == ""


def test_r4_last_is_append_order_not_first_seen_position(tmp_path):
    """A record updated later keeps no earlier position: an open block journaled first and
    stopped AFTER an error record is the turn's last record (the turn went on), and an exact
    replay of the error after it changes nothing."""
    block = {"type": "assistant", "uuid": "b-1", "message": {
        "id": "mb", "role": "assistant", "stop_reason": None, "content": [{"type": "text", "text": "x"}]}}
    error = api_error("server_error")
    stopped = {**block, "message": {**block["message"], "stop_reason": "max_tokens"}}
    path = write(tmp_path / "t.jsonl", [REQUEST, block, error, stopped, {**error, "parentUuid": "re"}])
    assert panel._claude_transcript_outcome(path).kind == "pending"  # capped: the CLI continues


# --- round 5 (C5-1 / G5-1): the live turn is the current request's records by MEMBERSHIP ------

REQ2 = {"type": "user", "uuid": "u-2", "message": {"role": "user", "content": "Second request."}}
# ANSWER's uuid (first seen under REQUEST) re-journaled open with changed content after REQ2's give-up
LATE_EARLIER = {**ANSWER, "message": {**ANSWER["message"], "stop_reason": None,
                                      "content": [{"type": "text", "text": "Review"}]}}


@pytest.mark.parametrize("president", [False, True])
def test_r5_an_earlier_requests_record_never_masks_the_current_give_up(tmp_path, president):
    """C5-1 / G5-1: a record whose uuid was first seen before the current request is never
    evidence for it, whatever position it is appended at. At r4 the position slice took it as
    the last record (open, so ``pending``) and the seat waited forever."""
    path = write(tmp_path / "t.jsonl", [REQUEST, ANSWER, REQ2, api_error("server_error"), LATE_EARLIER])
    outcome = panel._claude_transcript_outcome(path, require_terminal=president)
    assert (outcome.kind, outcome.code) == ("gave_up", "claude_seat_provider_api_error")
    # an earlier request's record re-journaled under ANY content or state is never evidence
    stopped = {**LATE_EARLIER, "message": {**LATE_EARLIER["message"], "stop_reason": "end_turn"}}
    capped_earlier = {**LATE_EARLIER, "message": {**LATE_EARLIER["message"], "stop_reason": "max_tokens"}}
    for late in (stopped, capped_earlier, {**REQUEST, "toolUseResult": "x", "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "late"}]}}):
        write(path, [REQUEST, ANSWER, REQ2, api_error("server_error"), late])
        outcome = panel._claude_transcript_outcome(path, require_terminal=president)
        assert (outcome.kind, outcome.code) == ("gave_up", "claude_seat_provider_api_error"), late
    # an error record stays terminal evidence under any uuid, an earlier request's included
    late_error = api_error("rate_limit")
    late_error["uuid"] = ANSWER["uuid"]
    write(path, [REQUEST, ANSWER, REQ2, capped(1), late_error])
    outcome = panel._claude_transcript_outcome(path, require_terminal=president)
    assert (outcome.kind, outcome.code) == ("gave_up", "claude_seat_rate_limited")


@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("heartbeat_only", [False, True])
@pytest.mark.parametrize("mode", ["review", "president"])
def test_r5_session_ends_on_the_give_up_behind_an_earlier_requests_record(
    tmp_path, monkeypatch, heartbeat_only, mode,
):
    """C5-1 / G5-1, full session. At r4: bounded ``claude_tui_stalled``; heartbeat_only ran until
    cancelled."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    records = [REQUEST, ANSWER, REQ2, api_error("server_error"), LATE_EARLIER]
    monitor = panel._ReviewMonitor(
        tmp_path / "monitor.json", "review", 0, threading.Event(), stall_notice_s=3600)
    guard = threading.Timer(3, monitor.cancel.set)
    guard.start()
    try:
        rc, text, log, _ = panel._run_claude_tui_session(
            command=_provider(transcript, records, release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=10,
            backstop_s=10, stall_threshold_s=.4, env=os.environ, mode=mode,
            review_monitor=monitor if heartbeat_only else None,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert (log, text) == ("claude_seat_provider_api_error", "") and rc != 0


def test_r5_property_an_earlier_requests_record_never_changes_a_terminal_outcome(tmp_path):
    """Over generated journals, on both routes: appending a changed version (any stop state)
    of a record first seen BEFORE the current request never changes a terminal outcome."""
    import random

    path = tmp_path / "t.jsonl"
    rng = random.Random(5)
    checked = 0
    for _ in range(1500):
        records, tail, fresh_terminal = _generated_transcript(rng)
        if not fresh_terminal:
            continue
        last_request = max(i for i, r in enumerate(records) if r.get("type") == "user" and not r.get("isMeta"))
        earlier = [r for r in records[:last_request] if r.get("type") == "assistant"
                   and not r.get("isApiErrorMessage")]
        if not earlier:
            continue
        old = rng.choice(earlier)
        late = {**old, "message": {**old["message"], "stop_reason": rng.choice([None, "end_turn", "max_tokens"]),
                                   "content": [{"type": "text", "text": f"late {rng.randrange(10**6)}"}]}}
        for president in (False, True):
            before = panel._claude_transcript_outcome(write(path, records), require_terminal=president)
            if before.kind not in ("gave_up", "rejected"):
                continue
            after = panel._claude_transcript_outcome(write(path, [*records, late]), require_terminal=president)
            assert (after.kind, after.code) == (before.kind, before.code), (president, records, late)
            checked += 1
    assert checked > 100


# --- round 5: tests for the two clauses mutation M2 and M7 showed unpinned --------------------

def test_r5_a_stale_open_copy_of_a_stopped_record_is_not_the_last_record(tmp_path):
    """Mutation M2 (drop the stale-open-copy rule): an open copy of a record that already
    stopped, with its content unchanged, is not streaming -- the turn stays ended."""
    ruling = _answer("a-r", "m-r", "No blocking findings.\nFORCING DECISION: APPROVE")
    open_ruling = {**ruling, "message": {**ruling["message"], "stop_reason": None}}
    path = write(tmp_path / "t.jsonl", [REQUEST, api_error("server_error"), ruling, open_ruling])
    outcome = panel._claude_transcript_outcome(path, require_terminal=True)
    assert (outcome.kind, outcome.code) == ("rejected", "claude_seat_transcript_rejected")
    missing_key = {**ANSWER, "message": {k: v for k, v in ANSWER["message"].items() if k != "stop_reason"}}
    write(path, [REQUEST, ANSWER, missing_key])
    outcome = panel._claude_transcript_outcome(path)
    assert (outcome.kind, outcome.code) == ("rejected", "claude_seat_transcript_rejected")


def test_r5_a_turn_that_stops_on_a_stop_sequence_is_terminal(tmp_path):
    """Mutation M7 (``rejected`` on end_turn only): a ``stop_sequence`` stop is a completed
    turn too. The president route refuses a ruling that does not end with end_turn."""
    ruling = _answer("a-r", "m-r", "No blocking findings.\nFORCING DECISION: APPROVE")
    ruling["message"]["stop_reason"] = "stop_sequence"
    path = write(tmp_path / "t.jsonl", [REQUEST, ruling])
    outcome = panel._claude_transcript_outcome(path, require_terminal=True)
    assert (outcome.kind, outcome.code) == ("rejected", "claude_seat_transcript_rejected")


# --- round 5 (N4-1 / G4-1): a thinking block flushed before its text is not yet the answer ----

THINKING_FIRST = {"type": "assistant", "uuid": "a-think", "message": {
    "id": "msg_m", "role": "assistant", "model": "claude-sonnet-5", "stop_reason": "end_turn",
    "content": [{"type": "thinking", "thinking": "", "signature": "sig"}]}}
TEXT_AFTER = {"type": "assistant", "uuid": "a-text", "parentUuid": "a-think", "message": {
    "id": "msg_m", "role": "assistant", "model": "claude-sonnet-5", "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "Review complete\nAGREE"}]}}


def test_r5_a_thinking_record_without_text_is_not_a_rejected_answer(tmp_path):
    path = write(tmp_path / "t.jsonl", [REQUEST, THINKING_FIRST])
    assert panel._claude_transcript_outcome(path).kind == "pending"
    write(path, [REQUEST, THINKING_FIRST, TEXT_AFTER])
    assert panel._claude_transcript_outcome(path).text == "Review complete\nAGREE"


@pytest.mark.parametrize("heartbeat_only", [False, True])
def test_r5_session_waits_for_the_text_flushed_after_its_thinking(tmp_path, monkeypatch, heartbeat_only):
    """N4-1 / G4-1, staged: the text record lands 1 s after its thinking record. At r4 the leg
    ended ``claude_seat_transcript_rejected`` before the answer arrived."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    first = "".join(json.dumps(r) + "\n" for r in [REQUEST, THINKING_FIRST])
    second = json.dumps(TEXT_AFTER) + "\n"
    script = (
        "import sys, time\nfrom pathlib import Path\n"
        "print('Claude Code fake provider ready for review', flush=True)\n"
        f"p = Path({str(transcript)!r}); time.sleep(.2); p.write_text({first!r})\n"
        "time.sleep(1)\n"
        f"with p.open('a') as f: f.write({second!r})\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    sys.stdout.write('\\r* Thinking...'); sys.stdout.flush(); time.sleep(.05)\n"
    )
    monitor = panel._ReviewMonitor(
        tmp_path / "monitor.json", "review", 0, threading.Event(), stall_notice_s=3600)
    guard = threading.Timer(6, monitor.cancel.set)
    guard.start()
    try:
        rc, text, log, _ = panel._run_claude_tui_session(
            command=[sys.executable, "-c", script], cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=10,
            backstop_s=10, stall_threshold_s=3, env=os.environ,
            review_monitor=monitor if heartbeat_only else None,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert text == "Review complete\nAGREE", (rc, text, log)


# --- round 5 (codex F001): a request replay is a replay whatever its completion metadata -------

@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("mode", ["review", "president"])
@pytest.mark.parametrize("heartbeat_only", [False, True])
@pytest.mark.parametrize("null_first", [False, True])
@pytest.mark.parametrize("earlier_request", [False, True])
def test_request_replay_cannot_hide_a_provider_give_up(
    tmp_path, monkeypatch, mode, heartbeat_only, null_first, earlier_request,
):
    """codex r5 F001 falsifier, verbatim (16 cases)."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    request = {**REQUEST, "message": {**REQUEST["message"]}}
    replay = {**request, "message": {**request["message"]}, "parentUuid": "re-journaled"}
    (request if null_first else replay)["message"]["stop_reason"] = None
    records = [request, capped(1)]
    if earlier_request:
        records.append({**REQUEST, "uuid": "u-next",
                        "message": {"role": "user", "content": "Next request"}})
    records.extend([api_error("max_output_tokens"), replay])
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "review", 0,
                                   threading.Event(), stall_notice_s=3600)
    guard = threading.Timer(2, monitor.cancel.set)
    guard.start()
    try:
        rc, text, log, _ = panel._run_claude_tui_session(
            command=_provider(transcript, records, release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=10,
            backstop_s=10, stall_threshold_s=.4, env=os.environ, mode=mode,
            review_monitor=monitor if heartbeat_only else None,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    assert log == "claude_seat_output_budget_exhausted", (rc, text, log)
    assert rc != 0 and text == ""


@pytest.mark.parametrize("president", [False, True])
def test_r5_the_walk_and_the_parser_agree_on_which_user_record_is_the_request(tmp_path, president):
    """codex r5 F001, classifier: the walk's request boundary is the parser's. A replayed request
    (completion metadata added or dropped) is not newer; a changed request under a reused uuid
    is a new request on both views, so the earlier give-up is not its evidence."""
    replay = {**REQUEST, "parentUuid": "re", "message": {**REQUEST["message"], "stop_reason": None}}
    path = write(tmp_path / "t.jsonl", [REQUEST, capped(1), api_error("max_output_tokens")])
    before = panel._claude_transcript_outcome(path, require_terminal=president).versions
    write(path, [REQUEST, capped(1), api_error("max_output_tokens"), replay])
    outcome = panel._claude_transcript_outcome(path, require_terminal=president)
    assert (outcome.kind, outcome.code) == ("gave_up", "claude_seat_output_budget_exhausted")
    assert outcome.versions == before  # a replayed request is not progress either
    changed = {**REQUEST, "message": {**REQUEST["message"], "content": "A changed request."}}
    write(path, [REQUEST, capped(1), api_error("max_output_tokens"), changed])
    assert panel._claude_transcript_outcome(path, require_terminal=president).kind == "pending"


# --- round 6 (codex F001): the answer parser accepts only a member of the current request ------

@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("mode", ["review", "president"])
@pytest.mark.parametrize("heartbeat_only", [False, True])
@pytest.mark.parametrize("terminal_error", [False, True])
def test_an_earlier_sidechain_record_cannot_answer_the_current_request(
    tmp_path, monkeypatch, mode, heartbeat_only, terminal_error,
):
    """codex r6 F001 falsifier, verbatim (8 cases)."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    answer = _answer("a-side", "m-side", "Review complete\nAGREE" if mode == "review"
                     else "No blocking findings.\nFORCING DECISION: APPROVE")
    records = [{**answer, "isSidechain": True}, REQUEST]
    if terminal_error:
        records.append(api_error("server_error"))
    records.append({**answer, "parentUuid": REQUEST["uuid"]})
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "review", 0,
                                   threading.Event(), stall_notice_s=.2)
    guard = threading.Timer(2, monitor.cancel.set)
    guard.start()
    try:
        rc, text, log, _ = panel._run_claude_tui_session(
            command=_provider(transcript, records, release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=10,
            backstop_s=10, stall_threshold_s=.8, env=os.environ, mode=mode,
            review_monitor=monitor if heartbeat_only else None,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        guard.cancel()
        release.touch()
    outcome = panel._claude_transcript_outcome(transcript, require_terminal=mode == "president")
    _, _, turn = panel._claude_live_turn(transcript.read_text().split("\n"))
    assert not any(payload.get("uuid") == answer["uuid"] for payload, _ in turn)
    assert rc != 0 and text == "", (rc, text, log, outcome)
    assert outcome.kind == ("gave_up" if terminal_error else "pending")
    if terminal_error:
        assert log == "claude_seat_provider_api_error"


@pytest.mark.parametrize("president", [False, True])
def test_r6_parser_and_walk_share_one_member_set(tmp_path, president):
    """One membership for both views: a record of an earlier request (main line or sidechain)
    never answers the current request, while the same answer first seen in it does. With no
    request journaled every record is a member, as before."""
    text = "Review complete\nAGREE" if not president else "No blocking findings.\nFORCING DECISION: APPROVE"
    answer = _answer("a-m", "m-m", text)
    req2 = {**REQUEST, "uuid": "u-2", "message": {"role": "user", "content": "Second request."}}
    for earlier in ([REQUEST, answer, req2], [{**answer, "isSidechain": True}, req2]):
        path = write(tmp_path / "t.jsonl", [*earlier, {**answer, "parentUuid": "u-2"}])
        assert panel._claude_transcript_outcome(path, require_terminal=president).kind == "pending"
    write(path, [REQUEST, answer])
    assert panel._claude_transcript_outcome(path, require_terminal=president).text == text
    write(path, [answer])
    assert panel._claude_transcript_outcome(path, require_terminal=president).text == text


def test_r6_a_uuid_less_record_counts_by_position(tmp_path):
    """Disclosed design (b), pinned (mutation MC): a record without a uuid has no identity to be
    first seen by, so after the current request it is that request's record. An open one after
    a give-up therefore reads as streaming."""
    req2 = {**REQUEST, "uuid": "u-2", "message": {"role": "user", "content": "Second request."}}
    open_anon = {"type": "assistant", "message": {"id": "m-anon", "role": "assistant",
                                                  "stop_reason": None, "content": []}}
    path = write(tmp_path / "t.jsonl", [REQUEST, ANSWER, req2, api_error("server_error"), open_anon])
    assert panel._claude_transcript_outcome(path).kind == "pending"
