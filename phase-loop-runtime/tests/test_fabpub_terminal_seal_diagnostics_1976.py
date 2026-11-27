"""Focused regressions for FABPUB terminal-seal join diagnostics (agent-harness#1976)."""

from __future__ import annotations

import threading

import pytest

from test_fabpub_shared_epoch import (
    _format_thread_join_diagnostics,
    _join_race_threads_or_fail,
)


def test_format_thread_join_diagnostics_covers_live_exited_and_absent_workers() -> None:
    started = threading.Event()
    release = threading.Event()

    def _blocked_on_release_marker() -> None:
        started.set()
        release.wait(10)

    live_worker = threading.Thread(
        target=_blocked_on_release_marker, name="fabpub-owner", daemon=True
    )
    exited_worker = threading.Thread(target=lambda: None, name="fabpub-exited", daemon=True)
    exited_worker.start()
    exited_worker.join(5)
    assert not exited_worker.is_alive()

    live_worker.start()
    try:
        assert started.wait(5)
        report = _format_thread_join_diagnostics(
            {"thread_a": live_worker, "thread_b": exited_worker, "thread_c": None},
            events={"started": started, "release": release},
            results={"a_error": RuntimeError("synthetic")},
            join_elapsed_s={"thread_a": 0.125, "thread_b": 0.002},
        )
    finally:
        release.set()
        live_worker.join(5)

    assert not live_worker.is_alive()
    assert "thread_a (name='fabpub-owner'" in report
    assert "alive=True, join_elapsed=0.125s)" in report
    assert "_blocked_on_release_marker" in report
    assert "thread_b (name='fabpub-exited'" in report
    assert "alive=False, join_elapsed=0.002s)" in report
    assert "thread_c: not started" in report
    assert "started=True" in report
    assert "release=False" in report
    assert "a_error=RuntimeError('synthetic')" in report


def test_format_thread_join_diagnostics_uses_single_liveness_observation() -> None:
    class _FlappingThread:
        name = "flapping-worker"
        ident = -1

        def __init__(self) -> None:
            self.calls = 0

        def is_alive(self) -> bool:
            self.calls += 1
            return self.calls == 1

    flapping = _FlappingThread()
    report = _format_thread_join_diagnostics(
        {"thread_a": flapping},  # type: ignore[dict-item]
        events={},
        results={},
        join_elapsed_s={"thread_a": 0.05},
    )
    assert flapping.calls == 1
    assert "alive=True, join_elapsed=0.050s)" in report
    assert "stack: <frame unavailable>" in report


def test_join_race_threads_attaches_stack_report_to_pending_barrier_failure() -> None:
    started = threading.Event()
    release = threading.Event()

    def _surviving_owner_marker() -> None:
        started.set()
        release.wait(10)

    worker = threading.Thread(
        target=_surviving_owner_marker, name="fabpub-owner", daemon=True
    )
    unstarted_contender = threading.Thread(
        target=lambda: None, name="fabpub-contender", daemon=True
    )
    started_threads: set[str] = set()
    pending_exc: BaseException | None = None

    worker.start()
    started_threads.add("thread_a")
    try:
        assert started.wait(5)
        with pytest.raises(AssertionError) as caught:
            try:
                raise AssertionError("train B never attempted the contested lock")
            except BaseException as exc:
                pending_exc = exc
                raise
            finally:
                _join_race_threads_or_fail(
                    {"thread_a": worker, "thread_b": unstarted_contender},
                    started_threads,
                    timeout_s=0.05,
                    events={"started": started, "release": release},
                    results={},
                    pending_exc=pending_exc,
                )
    finally:
        release.set()
        worker.join(5)

    assert not worker.is_alive()
    message = str(caught.value)
    assert "train B never attempted the contested lock" in message
    assert "terminal-seal race threads remained alive after bounded joins:" in message
    assert "_surviving_owner_marker" in message
    assert "thread_b: not started" in message
    assert isinstance(caught.value.__cause__, AssertionError)


def test_join_race_threads_skips_unstarted_worker_without_join_error() -> None:
    exited = threading.Thread(target=lambda: None, name="fabpub-owner", daemon=True)
    unstarted = threading.Thread(target=lambda: None, name="fabpub-contender", daemon=True)
    exited.start()
    _join_race_threads_or_fail(
        {"thread_a": exited, "thread_b": unstarted},
        {"thread_a"},
        timeout_s=5.0,
        events={},
        results={},
        pending_exc=None,
    )
    assert not exited.is_alive()
