"""``group_cpu_ticks`` — the CPU heartbeat for the leg-liveness monitor."""
from __future__ import annotations

import os

from phase_loop_runtime._proc_cpu import group_cpu_ticks


def test_own_group_has_consumed_cpu() -> None:
    assert group_cpu_ticks(os.getpgrp()) > 0


def test_monotonic_and_advances_under_load() -> None:
    pg = os.getpgrp()
    before = group_cpu_ticks(pg)
    x = 0
    for _ in range(5_000_000):
        x += 1
    after = group_cpu_ticks(pg)
    assert after >= before          # CPU never decreases (heartbeat is monotonic)


def test_unknown_group_is_zero() -> None:
    assert group_cpu_ticks(2_147_483_600) == 0
