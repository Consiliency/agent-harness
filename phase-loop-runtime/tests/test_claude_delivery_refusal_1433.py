"""agent-harness#1433 / agent-harness#1434: an ended turn the route cannot accept is refused.

A Claude TUI seat whose provider turn has ENDED (its journal holds the completed answer) but
whose output the route cannot accept used to wait: under ``heartbeat_only`` forever, because
silence never ends such a leg and an ended turn journals nothing more. Two ways to get there:

* the canonical output file is absent, empty or not a completed review, on a route that
  takes its answer only from that file (``allow_transcript_final=False``);
* the session journal fails strict admission, so no output of that session is accepted.

Both now end the leg with ``claude_seat_delivery_refused``: DEGRADED, never an approval,
never a sealed or toolless substitute. What the seat did write to its file is handed back as
it is, so a review without a verdict stays a nonconforming review (a governed BLOCK), not an
empty leg (a warn).

The refusal fires only on a journal state no further append of the same turn can change:
the journal ends in a newline, its last live record explicitly stopped, and the same answer
was seen ended on two consecutive checks (2 s apart by default). A last line still being written, a record with no
``stop_reason``, a tool call awaiting its result and a thinking block before its text are
all in flight and wait as before.

Named mutations, each run against this file (all red):

* M-NOREFUSE: remove the refusal branch -> the ``ended`` session cells wait for their guard.
* M-ENDED: refuse on any parsed answer, ended or not -> the ``unterminated`` and
  ``no stop_reason`` cells are refused.
* M-TAIL: count an unterminated last line as ended -> the two ``newline`` cells fail.
* M-STOPKEY: count a record with no ``stop_reason`` as ended -> that in-flight cell fails.
* M-REREAD: decide on the output read taken before the journal read -> the ``read taken
  after the journal read`` cell is refused although its review was written.
* M-SETTLE: refuse on the first sight of an ended turn -> the ``one check late`` cell fails,
  and the transcript-final route loses its own code.
* M-CONSEC: never forget a sighting -> the ``starts over`` cell is refused.
* M-VERSIONS: compare the record-version count too -> the ``do not defer`` cell waits.
* M-MONITOR-CLEAR: keep the first attempt's code in the monitor record -> the heartbeat-only
  retry cell fails.
* M-NOTEXT: hand back empty text -> the ``no-verdict`` and governed-block cells fail.
* M-RETRY: do not retry an ended, undelivered turn -> the retry cell fails.
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
          lifetime_s: float | None = None, newline_after_s: float | None = 0,
          retry_only: bool = False, churn: bool = False) -> list[str]:
    """A fake Claude TUI on the owned route: optionally writes its canonical output (in
    place, as the precreated file allows on every runtime), journals ``records``, then idles
    at its prompt, alive and silent, as the real TUI does after its turn.

    ``newline_after_s``: the journal's last newline is written that long after the rest
    (``None``: never) -- a record still being appended. ``retry_only``: the output is written
    only on the leg's retry (a cwd named ``claude-retry-*``). ``churn``: after its turn the
    seat keeps appending a new sidechain record every 20 ms."""
    side = {"type": "assistant", "isSidechain": True,
            "message": {"id": "side", "role": "assistant", "stop_reason": None, "content": []}}
    body = "".join(json.dumps(record) + "\n" for record in records)
    write = (f"Path('panel-claude.txt').write_text({write_output!r})\n" if write_output else "")
    if retry_only:
        write = "if 'claude-retry-' in os.getcwd():\n    " + write
    script = (
        "import sys, time\nfrom pathlib import Path\n" + _JOURNAL +
        "print('Claude Code fake provider ready for review', flush=True)\n"
        "time.sleep(.2)\n"
        + write +
        f"_journal.write_text({body[:-1]!r})\n"
        + ("" if newline_after_s is None else
           f"time.sleep({newline_after_s!r})\n"
           "with _journal.open('a') as handle: handle.write('\\n')\n") +
        f"_end = None if {lifetime_s!r} is None else time.monotonic() + {lifetime_s!r}\n"
        "i = 0\n"
        "import json\n"
        "while _end is None or time.monotonic() < _end:\n"
        "    sys.stdout.write('\\r* Idle... (%ds)' % i); sys.stdout.flush()\n"
        + ("    with _journal.open('a') as handle:\n"
           f"        handle.write(json.dumps(dict({side!r}, uuid='side-%d' % i)) + '\\n')\n"
           "    i += 1; time.sleep(.02)\n" if churn else
           "    i += 1; time.sleep(.05)\n")
    )
    return ["/usr/bin/python3", "-c", script]


def _run(tmp_path, monkeypatch, command, *, heartbeat_only: bool, guard_s: float = 15,
         **session):
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
            stall_threshold_s=600, env=os.environ, review_monitor=monitor, **session,
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
    # What the seat wrote is handed back as it is; nothing is invented for an absent file.
    assert rc != 0 and text == (written or "").strip()
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
    # Refused although the file holds a complete review: the journal is not admitted.
    assert (log, text) == (CODE, REVIEW) and rc != 0
    assert panel._classify_leg(rc, text, log) != "OK"
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
    # The answer parser reads a record with no ``stop_reason`` key as an answer; it is not
    # proof that the turn is over, so the refusal does not act on it.
    "an answer record with no stop_reason key": [REQUEST, {"type": "assistant", "uuid": "a", "message": {
        "id": "m", "role": "assistant", "content": [{"type": "text", "text": REVIEW}]}}],
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
def test_a_last_line_still_being_written_is_in_flight_not_refused(tmp_path, monkeypatch):
    """The journal's final record is complete JSON but its newline has not been written
    yet: the answer parser already reads the answer, strict admission does not admit it. That
    is a writer mid-append, not an ended turn. The leg waits, and accepts the review when the
    newline lands (it used to refuse at once and kill the writer)."""
    rc, text, log, elapsed, _monitor = _run(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", REVIEW)], write_output=REVIEW + "\n",
              newline_after_s=1.5),
        heartbeat_only=True)
    assert (rc, text, log) == (0, REVIEW, "claude_tui_file_output")
    assert elapsed >= 1.5


@pytest.mark.usefixtures("owned_review_network")
def test_a_journal_that_never_gets_its_newline_keeps_waiting(tmp_path, monkeypatch):
    """The other side of the boundary: with no file and the newline never written, the leg
    is not refused either; only the test's own cancel ends it."""
    rc, text, log, elapsed, _monitor = _run(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", REVIEW)], newline_after_s=None),
        heartbeat_only=True, guard_s=3)
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


@pytest.mark.usefixtures("owned_review_network")
def test_an_output_that_lands_one_check_after_the_end_of_the_turn_is_accepted(
        tmp_path, monkeypatch):
    """The ended turn must be seen unchanged on two consecutive checks before the leg is
    refused. Simulated exactly: the first output read after the journal shows the end is
    still stale, the next one is not."""
    ended = threading.Event()
    late_reads = []
    real_outcome, real_output = panel._claude_transcript_outcome, panel._seat_output_text

    def outcome(*args, **kwargs):
        result = real_outcome(*args, **kwargs)
        if result.kind == "answer" and result.ended:
            ended.set()
        return result

    def output(profile, path):
        if not ended.is_set():
            return ""
        late_reads.append(1)
        return "" if len(late_reads) == 1 else real_output(profile, path)

    monkeypatch.setattr(panel, "_claude_transcript_outcome", outcome)
    monkeypatch.setattr(panel, "_seat_output_text", output)
    rc, text, log, _elapsed, _monitor = _run(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", REVIEW)], write_output=REVIEW + "\n"),
        heartbeat_only=True)
    assert (rc, text, log) == (0, REVIEW, "claude_tui_file_output")


@pytest.mark.usefixtures("owned_review_network")
def test_the_refusal_decides_on_an_output_read_taken_after_the_journal_read(tmp_path, monkeypatch):
    """Each pass reads the output first and the journal after it, so that first read can
    predate a file the seat wrote just before journaling the end of its turn. Simulated
    exactly: the file is visible ONLY to the read the refusal itself takes after its journal
    read (found by its line in the session), never to the read at the top of a pass. The
    review is accepted; deciding on the earlier read would refuse it."""
    import inspect
    import sys

    lines, first = inspect.getsourcelines(panel._run_claude_tui_session)
    marks = [index for index, line in enumerate(lines) if "# after the journal read" in line]
    assert len(marks) == 1 and "_current_output()" in lines[marks[0]]
    reread_line = first + marks[0]
    real_output = panel._seat_output_text

    def output(profile, path):
        frame, accepting = sys._getframe(1), False
        while frame is not None and frame.f_code.co_name != "_run_claude_tui_session":
            accepting = accepting or frame.f_code.co_name == "_finish"  # the accepted read
            frame = frame.f_back
        assert frame is not None
        return real_output(profile, path) if accepting or frame.f_lineno == reread_line else ""

    monkeypatch.setattr(panel, "_seat_output_text", output)
    rc, text, log, _elapsed, _monitor = _run(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", REVIEW)], write_output=REVIEW + "\n"),
        heartbeat_only=True)
    assert (rc, text, log) == (0, REVIEW, "claude_tui_file_output")


@pytest.mark.usefixtures("owned_review_network")
def test_records_that_do_not_change_the_answer_do_not_defer_the_refusal(tmp_path, monkeypatch):
    """After its final answer the seat keeps appending new sidechain records, a new record
    version every 20 ms. The answer does not change, so the second sighting still comes and
    the leg is refused; counting record versions would have kept it waiting for good."""
    rc, text, log, elapsed, _monitor = _run(
        tmp_path, monkeypatch, _seat([REQUEST, _answer("a", "m", REVIEW)], churn=True),
        heartbeat_only=True)
    assert (log, text) == (CODE, "") and rc != 0
    assert elapsed < 10


@pytest.mark.usefixtures("owned_review_network")
def test_a_sighting_interrupted_by_a_turn_in_flight_starts_over(tmp_path, monkeypatch):
    """Two CONSECUTIVE sightings. Scripted exactly, through the journal the host reads: the
    turn is seen ended, then in flight again, then ended with the same answer. That third
    journal is a first sighting, so the leg is not refused on it; the output, which lands
    right after, is accepted. Counting the earlier sighting would refuse it."""
    ended = "".join(json.dumps(record) + "\n" for record in (REQUEST, _answer("a", "m", REVIEW)))
    in_flight = json.dumps(REQUEST) + "\n"
    seen: list[str] = []
    after_third = []
    real_outcome, real_output = panel._claude_transcript_outcome, panel._seat_output_text

    def outcome(path, *, require_terminal=False, data=None):
        if data is not None and not require_terminal:
            seen.append("ended" if data == ended.encode() else "in flight")
        return real_outcome(path, require_terminal=require_terminal, data=data)

    def journal(self):
        # ended, then in flight once that was classified, then ended again for good.
        return (ended if seen.count("ended") == 0 or "in flight" in seen else in_flight).encode()

    def third_journal_seen() -> bool:
        return "in flight" in seen and "ended" in seen[seen.index("in flight"):]

    def output(profile, path):
        if not third_journal_seen():
            return ""
        after_third.append(1)
        # Still absent for the read the refusal takes on that third journal; there after it.
        return "" if len(after_third) == 1 else REVIEW

    monkeypatch.setattr(panel, "_claude_transcript_outcome", outcome)
    monkeypatch.setattr(panel._SeatClaudeJournal, "read", journal)
    monkeypatch.setattr(panel, "_seat_output_text", output)
    rc, text, log, _elapsed, _monitor = _run(
        tmp_path, monkeypatch, _seat([REQUEST]), heartbeat_only=True)
    assert seen[0] == "ended" and third_journal_seen()
    assert (rc, text, log) == (0, REVIEW, "claude_tui_file_output")


@pytest.mark.usefixtures("owned_review_network")
def test_the_transcript_final_route_keeps_its_own_journal_refusal(tmp_path, monkeypatch):
    """On the route that takes its answer from the journal (``allow_transcript_final``), a
    parsed answer in a journal that is not admitted still ends with that route's own code,
    not with the delivery refusal."""
    unmatched = {"type": "assistant", "uuid": "a-tool", "message": {
        "id": "m-tool", "role": "assistant", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}}
    rc, text, log, elapsed, _monitor = _run(
        tmp_path, monkeypatch, _seat([REQUEST, unmatched, _answer("a", "m", REVIEW)]),
        heartbeat_only=True, allow_transcript_final=True,
        broker_transcript_path=tmp_path / "collected.jsonl")
    assert (rc, text, log) == (1, "", "claude_tui_journal_collection_refused")
    assert elapsed < 10


def _leg(tmp_path, monkeypatch, command, **kwargs):
    """``_exec_claude_tui_leg`` on the TUI route with the real session and a fake seat."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_SUBMIT_DELAY_S", .01)
    monkeypatch.setattr(panel, "_CLAUDE_TUI_READY_QUIESCENCE_S", .01)
    monkeypatch.setattr(panel, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    monkeypatch.setattr(panel, "_claude_subscription_auth_ok", lambda env: (True, ""))
    monkeypatch.setattr(panel, "_under_claude_code", lambda env=None: False)
    monkeypatch.setattr(panel, "_subscription_env", lambda env=None: dict(os.environ))
    monkeypatch.setattr(panel, "_claude_tui_command", lambda *a, **k: list(command))
    sessions = []
    real_session = panel._run_claude_tui_session

    def session(**call):
        result = real_session(**call)
        sessions.append((Path(call["cwd"]).name, result[0], str(result[2])))
        return result

    monkeypatch.setattr(panel, "_run_claude_tui_session", session)
    (tmp_path / "review").mkdir()
    (tmp_path / "out").mkdir()
    sink: list = []
    status, text = panel._exec_claude_tui_leg(
        tmp_path / "review", tmp_path / "out", 60, "bundle", env={},
        repo_dir=tmp_path / "review", failure_detail_sink=sink, backstop_s=60, **kwargs)
    return status, text, sink, sessions


@pytest.mark.usefixtures("owned_review_network")
def test_an_ended_undelivered_turn_gets_the_one_retry_in_a_fresh_directory(tmp_path, monkeypatch):
    """agent-harness#343's retry, with the real session: a non-brokered leg whose first turn
    ends without its file used to stall and then retry once in a fresh directory. It is now
    refused at once instead of stalling, and still retried once. The second attempt delivers."""
    status, text, sink, sessions = _leg(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", "I have finished.")],
              write_output="Second attempt\nAGREE\n", retry_only=True))
    assert (status, text) == ("OK", "Second attempt\nAGREE")
    assert [(rc, log) for _cwd, rc, log in sessions] == [(1, CODE), (0, "claude_tui_file_output")]
    assert sessions[0][0] == "out" and sessions[1][0].startswith("claude-retry-")
    assert sink == []


@pytest.mark.usefixtures("owned_review_network")
def test_a_heartbeat_only_leg_is_retried_too_and_its_record_names_how_the_leg_ended(
        tmp_path, monkeypatch):
    """Under ``heartbeat_only`` this state used to wait for good, so there was no retry to
    keep; the leg now gets the same one retry. The monitor record names the code that ended
    the LEG: after a retry that delivers, that is nothing, not the first attempt's refusal."""
    monitor = panel._ReviewMonitor(tmp_path / "monitor.json", "t", 0, threading.Event(),
                                   stall_notice_s=3600)
    status, text, sink, sessions = _leg(
        tmp_path, monkeypatch,
        _seat([REQUEST, _answer("a", "m", "I have finished.")],
              write_output="Second attempt\nAGREE\n", retry_only=True),
        review_monitor=monitor)
    assert (status, text) == ("OK", "Second attempt\nAGREE")
    assert [(rc, log) for _cwd, rc, log in sessions] == [(1, CODE), (0, "claude_tui_file_output")]
    assert json.loads(monitor.path.read_text())["provider_terminal_state"] is None


@pytest.mark.usefixtures("owned_review_network")
@pytest.mark.parametrize("case", ["a review without a verdict", "a verdict in an unadmitted session"])
def test_what_the_seat_wrote_fails_closed_on_the_governed_path(tmp_path, monkeypatch, case):
    """A leg refused with text is never read as approval. ``governed_review`` records an
    unusable leg WITH text as ``panel_nonconforming`` (severity block), and one with no text
    as the non-gating ``panel_leg_degraded`` warn. So the seat's written review, verdict or
    not, blocks promotion beside an agreeing seat; an empty text would have let it through."""
    from phase_loop_runtime.governed_review import _findings_from_panel

    unmatched = {"type": "assistant", "uuid": "a-tool", "message": {
        "id": "m-tool", "role": "assistant", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}}
    if case == "a review without a verdict":
        records, written = [REQUEST, _answer("a", "m", "AGREE")], "This must not merge as it is.\n"
    else:
        records, written = [REQUEST, unmatched, _answer("a", "m", "AGREE")], REVIEW + "\n"
    status, text, sink, sessions = _leg(tmp_path, monkeypatch, _seat(records, write_output=written))
    assert (status, text) == ("DEGRADED", written.strip())
    assert [log for _cwd, _rc, log in sessions] == [CODE, CODE]  # the attempt and its one retry
    assert str(sink[-1].rendered()) == CODE
    refused = panel.PanelLegResult(leg="claude", status=status, text=text,
                                   detail=sink[-1].rendered(), seat_key="claude:a")
    agreeing = panel.PanelLegResult(leg="codex", status="OK", text="Looks fine.\n\nAGREE",
                                    seat_key="codex:a")
    findings = _findings_from_panel(panel.PanelResult(legs=(refused, agreeing)), "a" * 40)
    blocking = [finding.code for finding in findings if finding.severity == "block"]
    assert "panel_nonconforming" in blocking, [(f.code, f.severity) for f in findings]


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
