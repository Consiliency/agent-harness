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
            assert after >= before      # a STABLE group's total never decreases
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


@_needs_proc
def test_sums_every_member_of_the_group() -> None:
    # The monotonic test above samples a ONE-process group, so it cannot tell a sum
    # from a single member's ticks. Two busy processes in one new session: the group
    # total, read AFTER each member's own ticks, is at least their sum (ticks only
    # grow while a process lives).
    leader = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess, sys, time\n"
         "subprocess.Popen([sys.executable, '-c', 'while True: pass'])\n"
         "while True: pass"],
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        members: list[int] = []
        while len(members) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
            members = [int(e) for e in os.listdir("/proc") if e.isdigit()
                       and _pgrp_of(int(e)) == leader.pid]
        assert len(members) == 2, f"expected leader + one child in the group, found {members}"
        while time.monotonic() < deadline:
            per_member = [_proc_cpu._pgrp_and_ticks(pid)[1] for pid in members]
            if all(per_member):
                break
            time.sleep(0.05)
        assert all(per_member), "a busy member never accrued a tick"
        assert group_cpu_ticks(leader.pid) >= sum(per_member)
        assert group_cpu_ticks(leader.pid) > max(per_member), "the group total is one member, not a sum"
    finally:
        os.killpg(leader.pid, 9)
        leader.wait()


def _pgrp_of(pid: int) -> int | None:
    try:
        return _proc_cpu._pgrp_and_ticks(pid)[0]
    except (OSError, ValueError, IndexError):
        return None
