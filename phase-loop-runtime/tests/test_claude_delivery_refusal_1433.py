"""agent-harness#1433 / agent-harness#1434: an ended turn the route cannot accept is refused.

A Claude TUI seat whose provider turn has ENDED (its journal holds the completed answer) but
whose output the route cannot accept used to wait: under ``heartbeat_only`` forever, because
silence never ends such a leg and an ended turn journals nothing more. Two ways to get there:

* the canonical output file is absent, empty or not a completed review, on a route that
  takes its answer only from that file (``allow_transcript_final=False``);
* the session journal fails strict admission, so no output of that session is accepted.

Both now end the leg at once with ``claude_seat_delivery_refused``: DEGRADED, empty text,
never an approval, never a sealed or toolless substitute. A turn still in flight waits as
before.

Named mutations, each run against this file (all red):

* M-NOREFUSE: remove the refusal branch -> the two ``ended`` session cells wait for their
  guard and fail.
* M-ENDED: refuse without requiring an ended turn (any classified journal) -> the
  ``in flight`` cells are refused instead of waiting.
* M-REREAD: refuse on the output read taken before the journal read -> the ``read again``
  cell is refused although its review was written.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime import seat_jail
from test_review_seat_stall_1176 import (
    REQUEST, THINKING_FIRST, _JOURNAL, _ProviderTimer, _answer, _fast_tui,
)

CODE = "claude_seat_delivery_refused"


@pytest.fixture(autouse=True)
def _pin_claude_tui_route(monkeypatch):
    """These tests assert the PTY TUI route; the default is now headless print (Stage 1b).
    The session cells call ``_run_claude_tui_session`` directly; the leg cell reaches it only
    on this route."""
    monkeypatch.setenv("PHASE_LOOP_PANEL_CLAUDE_ROUTE", "tui")
REVIEW = "Review complete\nAGREE"


def _seat(records: list[dict], *, write_output: str | None = None,
          lifetime_s: float | None = None) -> list[str]:
    """A fake Claude TUI on the owned route: optionally writes its canonical output (in
    place, as the precreated file allows on every runtime), journals ``records``, then idles
    at its prompt, alive and silent, as the real TUI does after its turn."""
    body = "".join(json.dumps(record) + "\n" for record in records)
    script = (
        "import sys, time\nfrom pathlib import Path\n" + _JOURNAL +
        "print('Claude Code fake provider ready for review', flush=True)\n"
        "time.sleep(.2)\n"
        + (f"Path('panel-claude.txt').write_text({write_output!r})\n" if write_output else "") +
        f"_journal.write_text({body!r})\n"
        f"_end = None if {lifetime_s!r} is None else time.monotonic() + {lifetime_s!r}\n"
        "i = 0\n"
        "while _end is None or time.monotonic() < _end:\n"
        "    sys.stdout.write('\\r* Idle... (%ds)' % i); sys.stdout.flush()\n"
        "    i += 1; time.sleep(.05)\n"
    )
    return ["/usr/bin/python3", "-c", script]


def _run(tmp_path, monkeypatch, command, *, heartbeat_only: bool, guard_s: float = 15):
    """Run one session; returns ``(rc, text, log, elapsed, monitor)``. The guard only bounds
    the test: a heartbeat-only leg is cancelled, a bounded one's provider exits by itself."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    monitor = (panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                    stall_notice_s=3600) if heartbeat_only else None)
    guard = _ProviderTimer(monkeypatch, guard_s, lambda: monitor and monitor.cancel.set())
    started = time.monotonic()
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=command, cwd=tmp_path, prompt="input",
            output_file=tmp_path / "panel-claude.txt", timeout_s=600, backstop_s=600,
            stall_threshold_s=600, env=os.environ, review_monitor=monitor,
        )
    finally:
        guard.cancel()
    return rc, text, log, time.monotonic() - started, monitor


@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("heartbeat_only", [True, False])
@pytest.mark.parametrize("written", [None, "A review that never reaches its verdict.\n"],
                         ids=["absent", "no-verdict"])
def test_an_ended_turn_without_its_canonical_output_is_refused_at_once(
        tmp_path, monkeypatch, heartbeat_only, written):
    rc, text, log, elapsed, monitor = _run(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", REVIEW)], write_output=written,
              lifetime_s=None if heartbeat_only else 12),
        heartbeat_only=heartbeat_only)
    assert log == CODE and type(log) is panel._HarnessCode
    assert rc != 0 and text == ""
    assert elapsed < 10, "the leg waited on a turn that had already ended"
    assert panel._classify_leg(rc, text, log) != "OK"
    if monitor is not None:
        assert json.loads(monitor.path.read_text())["provider_terminal_state"] == CODE


@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("heartbeat_only", [True, False])
def test_an_ended_turn_with_an_inadmissible_journal_is_refused_at_once(
        tmp_path, monkeypatch, heartbeat_only):
    """The canonical file is complete and the answer parser accepts the final answer, but
    the journal holds a tool call that never got its result: strict admission refuses it, so
    nothing of this session is accepted -- and nothing more will arrive."""
    unmatched = {"type": "assistant", "uuid": "a-tool", "message": {
        "id": "m-tool", "role": "assistant", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}}
    records = [REQUEST, unmatched, _answer("a", "m", REVIEW)]
    data = "".join(json.dumps(record) + "\n" for record in records).encode()
    assert panel._final_assistant_text_from_jsonl(None, data=data) == REVIEW
    assert panel._validated_claude_journal(data, require_terminal=False) == ""
    rc, text, log, elapsed, _monitor = _run(
        tmp_path, monkeypatch,
        _seat(records, write_output=REVIEW + "\n", lifetime_s=None if heartbeat_only else 12),
        heartbeat_only=heartbeat_only)
    assert (log, text) == (CODE, "") and rc != 0
    assert elapsed < 10, "the leg waited on a turn that had already ended"


IN_FLIGHT = {
    "a tool call awaiting its result": [REQUEST, {"type": "assistant", "uuid": "a-tool", "message": {
        "id": "m-tool", "role": "assistant", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}}],
    "a thinking block flushed before its text": [REQUEST, THINKING_FIRST],
    "an answer still streaming": [REQUEST, {"type": "assistant", "uuid": "a", "message": {
        "id": "m", "role": "assistant", "stop_reason": None,
        "content": [{"type": "text", "text": REVIEW}]}}],
    "only the request": [REQUEST],
}


@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("shape", sorted(IN_FLIGHT))
def test_a_turn_still_in_flight_keeps_waiting(tmp_path, monkeypatch, shape):
    rc, text, log, elapsed, _monitor = _run(
        tmp_path, monkeypatch, _seat(IN_FLIGHT[shape]), heartbeat_only=True, guard_s=3)
    # Only the test's own guard (a user cancel) ended it: the leg itself kept waiting.
    assert (log, text) == ("review_operation_cancelled", "") and rc != 0
    assert elapsed >= 3


@pytest.mark.usefixtures("owned_review_network")
def test_a_delivered_review_is_still_accepted(tmp_path, monkeypatch):
    """The refusal never outranks a delivered review: output written, journal admitted."""
    rc, text, log, _elapsed, _monitor = _run(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", REVIEW)], write_output=REVIEW + "\n"),
        heartbeat_only=True)
    assert (rc, text, log) == (0, REVIEW, "claude_tui_file_output")


@pytest.mark.usefixtures("owned_review_network")
def test_an_output_read_before_the_turn_ended_is_read_again_before_refusing(tmp_path, monkeypatch):
    """The seat writes its output and THEN journals the end of its turn, and the session
    reads the output before it reads the journal. So the output read of the tick that first
    sees the ended turn may predate the write. Simulated exactly: every output read is
    stale (empty) until the journal has been seen ended. The refusal must look again."""
    ended = threading.Event()
    real_outcome, real_output = panel._claude_transcript_outcome, panel._seat_output_text

    def outcome(*args, **kwargs):
        result = real_outcome(*args, **kwargs)
        if result.kind == "answer":
            ended.set()
        return result

    monkeypatch.setattr(panel, "_claude_transcript_outcome", outcome)
    monkeypatch.setattr(panel, "_seat_output_text",
                        lambda profile, path: real_output(profile, path) if ended.is_set() else "")
    rc, text, log, _elapsed, _monitor = _run(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", REVIEW)], write_output=REVIEW + "\n"),
        heartbeat_only=True)
    assert (rc, text, log) == (0, REVIEW, "claude_tui_file_output")


def test_the_refusal_reaches_the_leg_degraded_with_its_code_and_fix(monkeypatch, tmp_path):
    monkeypatch.setattr(panel, "_run_claude_tui_session",
                        lambda **kw: (1, "", panel._HarnessCode(CODE), ""))
    monkeypatch.setattr(panel, "_claude_code_support_status", lambda: (True, "supported"))
    monkeypatch.setattr(panel, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(panel, "_under_claude_code", lambda env=None: False)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list = []
    status, text = panel._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 30, "bundle", env={}, failure_detail_sink=sink)
    assert (status, text) == ("DEGRADED", "")
    assert str(sink[-1].rendered()) == CODE
    leg = panel.PanelLegResult(leg="claude", status=status, text=text, detail=sink[-1].rendered(),
                               seat_key="claude:a")
    assert leg.detail == CODE
    notices = leg.seat_notices
    assert [notice.code for notice in notices] == [CODE]
    assert notices[0].what == "leg refused" and notices[0].fix


def test_the_code_is_registered_wherever_seat_codes_must_be():
    what, why, fix = seat_jail.NOTICES[CODE]
    assert what == "leg refused" and why and fix not in {"none", "report a defect"}
    assert CODE in panel._HARNESS_DETAIL_CODES
    assert panel._finalize_leg_detail(panel._HarnessCode(CODE)) == CODE
    assert panel._claude_terminal_code(panel._HarnessCode(CODE)) == CODE
    # Never a sealed (toolless) substitute, never an inline fallback.
    assert CODE not in seat_jail.SEALED_FALLBACK_CODES
    assert CODE not in seat_jail.JAIL_NOT_RUN_CODES
    assert not seat_jail.is_limit_detail(CODE)
    contracts = (Path(panel.__file__).parent / "advisor_board" / "CONTRACTS.md").read_text()
    assert f"`{CODE}`" in contracts
