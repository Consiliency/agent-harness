"""Round 10 (agent-harness#1160): the supervisor role is an exclusive slot.

Three seats found the same defect independently: concurrent revivers (an
exiting supervisor's ``finally`` and an exiting owner candidate) each started a
supervisor, and the displaced ones ran until close -- one leaked thread per
raced interruption.  Below: codex's falsifier and the GROK stand-in's probe,
both VERBATIM (they fail on 4c554ab1 and pass here), then the concurrent-reviver
sweep the round asked for (in test_phase_loop_baml_v1_runtime.py, next to the
other supervisor sweeps).
"""
import _thread
import ctypes
import threading
import time

import pytest

from phase_loop_runtime import baml_modular as m
from test_phase_loop_baml_v1_runtime import _supervisors_of


# --- codex r10 F001, verbatim ----------------------------------------------

def test_concurrent_candidate_revives_leak_supervisors_after_repeated_interruptions():
    import sys  # noqa: F401 - verbatim: codex's falsifier imports it unused
    import threading
    from unittest.mock import patch

    from phase_loop_runtime import baml_modular as m
    from test_phase_loop_baml_v1_runtime import _line_of, _supervisors_of, _wait

    client = m._Client(test_mode=True)
    held_baton = client.baton.get_nowait()
    real_start = threading.Thread.start
    previous = threading.gettrace()
    interrupt_ids = set()
    gate = {}
    fired = []
    live_counts = []
    supervise_code = m._Client._supervise.__code__
    interrupt_line = _line_of(m._Client._supervise, "time.sleep(_SUPERVISE_S)")
    real_own = client._own
    candidate_done = threading.Event()

    def own():
        try:
            real_own()
        finally:
            candidate_done.set()

    def trace(frame, event, arg):
        ident = threading.get_ident()
        if (frame.f_code is supervise_code and event == "line"
                and frame.f_lineno == interrupt_line
                and ident in interrupt_ids):
            interrupt_ids.remove(ident)
            fired.append(ident)
            raise SystemExit
        return trace

    def start(thread):
        if (thread.name == "phase-loop-baml-supervisor"
                and threading.get_ident() == gate.get("ident")):
            gate["entered"].set()
            assert gate["release"].wait(3), "successor was never released"
        return real_start(thread)

    threading.settrace(trace)
    try:
        with patch.object(threading.Thread, "start", start), \
                patch.object(m, "_SUPERVISE_S", 0.005), \
                patch.object(m, "_OWNER_LAUNCH_BUCKET_S", 0.001), \
                patch.object(client, "_own", own):
            client._ensure_supervisor()
            for _ in range(8):
                victim = client.supervisor
                assert victim is not None and victim.is_alive()
                entered, release = threading.Event(), threading.Event()
                gate.update(ident=victim.ident, entered=entered, release=release)
                interrupt_ids.add(victim.ident)
                assert entered.wait(3), "protected supervisor interruption did not fire"
                # The successor is recorded, but not started.  An ordinary
                # no-op candidate's finally now starts a different successor.
                recorded = client.supervisor
                assert recorded is not victim and not recorded.is_alive()
                candidate_done.clear()
                client._launch_owner()
                assert candidate_done.wait(3), "no-op candidate did not finish"
                release.set()
                victim.join(3)
                assert not victim.is_alive()
                assert _wait(lambda: client.supervisor.is_alive(), 3)
                live_counts.append(sum(t.is_alive() for t in _supervisors_of(client)))
            assert len(fired) == 8
            assert client.baton_ref() is held_baton and client.baton.empty()
            print("live supervisor counts:", live_counts)
            # All interruptions have stopped; the extra supervisors persist.
            assert _wait(lambda: sum(t.is_alive() for t in _supervisors_of(client)) <= 1,
                         m._REAP_BOUND_S + 0.5), live_counts
    finally:
        threading.settrace(previous)
        if gate:
            gate["release"].set()
        client.closed = True
        client.baton.put(held_baton)
        for thread in _supervisors_of(client):
            if thread.ident is not None:
                thread.join(3)


# --- GROK stand-in r10 G1 probe (probes/test_finding_dupsup.py), verbatim ----

ENSURE = m._Client._ensure_supervisor


def _start_line():
    lines = open(ENSURE.__code__.co_filename).read().splitlines()
    return next(i for i in range(ENSURE.__code__.co_firstlineno, len(lines) + 1)
                if lines[i - 1].strip() == "supervisor.start()")


def _run_candidate(client):
    done = threading.Event()
    _thread.start_new_thread(lambda: (m._Client._own(client), done.set()), ())
    assert done.wait(10)


@pytest.mark.parametrize("interrupt_first", [False, True])
def test_concurrent_revivers_leave_at_most_one_supervisor(interrupt_first):
    client = m._Client(test_mode=True)
    held = client.baton.get_nowait()  # a live owner holds the baton: candidates are no-ops
    line, who = _start_line(), {}
    paused, go = threading.Event(), threading.Event()

    def trace(frame, event, arg):
        if (event == "line" and frame.f_code is ENSURE.__code__ and frame.f_lineno == line
                and who.get("t") == threading.get_ident()):
            who.clear(); paused.set(); go.wait(10)
        return trace

    threading.settrace(trace)
    try:
        if interrupt_first:
            client._ensure_supervisor()
            time.sleep(0.1)
            first = client.supervisor
            who["t"] = first.ident  # its finally pauses in the successor's start()
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(first.ident), ctypes.py_object(SystemExit))
        else:
            starter = threading.Thread(target=lambda: (who.__setitem__("t", threading.get_ident()), client._ensure_supervisor()))
            starter.start()
        assert paused.wait(5)
        _run_candidate(client)  # an exiting candidate revives "the dead" recorded-but-unstarted supervisor
        go.set()
        time.sleep(4 * m._SUPERVISE_S)
        assert len([t for t in _supervisors_of(client) if t.is_alive()]) <= 1  # at most one
    finally:
        threading.settrace(None)
        go.set()
        client.baton.put(held)
        client.closed = True
        for t in _supervisors_of(client):
            t.join(2)
