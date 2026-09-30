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
    # A max-effort turn is progress-silent through its whole thinking phase (~10 min per
    # attempt in the measured journal), so the default must clear that with margin.
    assert default.record["stall_notice_s"] == panel._REVIEW_STALL_NOTICE_S >= 1800
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
