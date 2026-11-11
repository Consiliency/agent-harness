"""Small injectable memory policy boundary; cache amendment remains separate.

A seat's memory.max is a limit, not a measured per-child usage budget. Callers
use a configurable provisional 2 GiB policy budget, not measured consumption.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


DEFAULT_LANE_MEMORY_BUDGET_BYTES = 2 * 1024 ** 3


@dataclass(frozen=True)
class LaneCapacity:
    ceiling: int
    effective: int
    reason: str
    budget_bytes: int | None
    readings: tuple[int, ...] = ()

    def to_json(self):
        return asdict(self)


def memory_capacity(ceiling: int, budget_bytes: int | None, *, read: Callable[[Path], str] = Path.read_text) -> LaneCapacity:
    if ceiling < 1 or (budget_bytes is not None and budget_bytes < 1):
        raise ValueError("lane ceiling and memory budget must be positive")
    if budget_bytes is None:
        budget_bytes = DEFAULT_LANE_MEMORY_BUDGET_BYTES
    readings = []
    try:
        info = dict(line.split(":", 1) for line in read(Path("/proc/meminfo")).splitlines())
        readings.append(int(info["MemAvailable"].split()[0]) * 1024)
        relative = next(line[3:] for line in read(Path("/proc/self/cgroup")).splitlines() if line.startswith("0::"))
        if ".." in Path(relative).parts:
            raise ValueError("unresolved cgroup namespace")
        root = Path("/sys/fs/cgroup")
        group = root / relative.lstrip("/")
        while True:
            try:
                maximum = read(group / "memory.max").strip()
            except FileNotFoundError:
                if group == root:
                    break
                raise
            if maximum != "max":
                readings.append(max(0, int(maximum) - int(read(group / "memory.current"))))
            if group == root:
                break
            group = group.parent
        effective = min(ceiling, min(readings) // budget_bytes)
        return LaneCapacity(ceiling, effective, "capacity" if effective < ceiling else "available", budget_bytes, tuple(readings))
    except (OSError, ValueError, KeyError, StopIteration):
        return LaneCapacity(ceiling, ceiling, "capacity_unknown", budget_bytes, tuple(readings))
