"""Focused regressions for FABPUB terminal-seal join diagnostics (agent-harness#1976)."""

from __future__ import annotations

import threading

from test_fabpub_shared_epoch import _format_thread_join_diagnostics


def test_format_thread_join_diagnostics_captures_live_stack_and_state() -> None:
    started = threading.Event()
    release = threading.Event()

    def _blocked_on_release_marker() -> None:
        started.set()
        release.wait(10)

    worker = threading.Thread(
        target=_blocked_on_release_marker, name="fabpub-owner", daemon=True
    )
    worker.start()
    try:
        assert started.wait(5)
        report = _format_thread_join_diagnostics(
            {"thread_a": worker, "thread_b": None},
            events={"started": started, "release": release},
            results={"a_error": RuntimeError("synthetic")},
            join_elapsed_s={"thread_a": 0.125},
        )
    finally:
        release.set()
        worker.join(5)

    assert not worker.is_alive()
    assert "alive=True" in report
    assert "join_elapsed=0.125s" in report
    assert "fabpub-owner" in report
    assert "_blocked_on_release_marker" in report
    assert "started=True" in report
    assert "release=False" in report
    assert "a_error=RuntimeError('synthetic')" in report
    assert "thread_b: not started" in report
