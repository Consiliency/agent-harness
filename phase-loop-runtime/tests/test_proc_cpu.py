"""``group_cpu_ticks`` — the CPU heartbeat for the leg-liveness monitor."""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from phase_loop_runtime import _proc_cpu
from phase_loop_runtime._proc_cpu import group_cpu_ticks

_LINUX = sys.platform.startswith("linux") and os.path.isdir("/proc")
_needs_proc = pytest.mark.skipif(not _LINUX, reason="process-group CPU sampling needs linux /proc")


@_needs_proc
def test_own_group_has_consumed_cpu() -> None:
    assert group_cpu_ticks(os.getpgrp()) > 0


@_needs_proc
def test_monotonic_and_advances_under_load() -> None:
    # Sample a PRIVATE group, not this test's own. Under xdist the test's process
    # group also holds the controller, the sibling workers and their short-lived
    # children; one exiting between the two samples takes its ticks out of the sum
    # (py3.11 CI on agent-harness#956: 29034 -> 28938). A single busy child alone in a
    # new session is a group whose total can only grow.
    child = subprocess.Popen([sys.executable, "-c", "while True: pass"], start_new_session=True)
    try:
        before = group_cpu_ticks(child.pid)
        after = before
        deadline = time.monotonic() + 30
        while after <= before and time.monotonic() < deadline:
            time.sleep(0.05)
            after = group_cpu_ticks(child.pid)
            assert after >= before      # CPU never decreases (heartbeat is monotonic)
        assert after > before, "a busy process group's CPU ticks never advanced"
    finally:
        child.kill()
        child.wait()


@_needs_proc
def test_unknown_group_is_zero() -> None:
    assert group_cpu_ticks(2_147_483_600) == 0


def test_missing_proc_degrades_to_zero(monkeypatch) -> None:
    # The advertised non-Linux / no-/proc degradation: os.listdir("/proc") raises OSError
    # and group_cpu_ticks returns 0 (the runner then relies on the stdout/stderr heartbeat
    # alone — still correct: a streaming leg heartbeats, a silent-and-idle one is dead).
    def _boom(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(_proc_cpu.os, "listdir", _boom)
    assert group_cpu_ticks(os.getpgrp() if _LINUX else 1) == 0
