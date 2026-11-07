"""Trusted child-side readback for :mod:`phase_loop_runtime.seat_resource_caps`.

This file is executed by path with isolated Python.  It deliberately imports no
package module: the child verifies its effective cgroup before it executes the
provider target.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def _own_cgroup(root: Path, proc_cgroup: Path) -> Path:
    for line in proc_cgroup.read_text(encoding="utf-8").splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            relative = fields[2].lstrip("/")
            child = (root / relative).resolve()
            resolved_root = root.resolve()
            if child != resolved_root and resolved_root in child.parents:
                return child
    raise ValueError("unified child cgroup unavailable")


def _read(path: Path) -> str:
    return path.read_text(encoding="ascii").strip()


def _weight(value: str) -> str:
    fields = value.split()
    return fields[-1] if fields else ""


def _io_max(value: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in value.splitlines():
        fields = line.split()
        if not fields:
            continue
        rows[fields[0]] = dict(item.split("=", 1) for item in fields[1:] if "=" in item)
    return rows


def verify(expected: dict[str, object], *, root: Path, proc_cgroup: Path,
           proc_swaps: Path) -> None:
    child = _own_cgroup(root, proc_cgroup)
    parent = child.parent
    scalar = {
        "memory.max": str(expected["memory.max"]),
        "cpu.weight": str(expected["cpu.weight"]),
        "cpu.max": str(expected["cpu.max"]),
        "pids.max": str(expected["pids.max"]),
    }
    for name, wanted in scalar.items():
        if _read(parent / name) != wanted:
            raise ValueError(f"{name} readback mismatch")
    if _weight(_read(parent / "io.weight")) != str(expected["io.weight"]):
        raise ValueError("io.weight readback mismatch")
    actual_io = _io_max(_read(parent / "io.max"))
    wanted_io = expected.get("io.max")
    if not isinstance(wanted_io, dict) or actual_io != wanted_io:
        raise ValueError("io.max readback mismatch")
    if expected.get("memory.swap.max") == "0":
        swap_max = parent / "memory.swap.max"
        if swap_max.exists():
            if _read(swap_max) != "0":
                raise ValueError("memory.swap.max readback mismatch")
        else:
            lines = proc_swaps.read_text(encoding="utf-8").splitlines()
            if any(line.strip() for line in lines[1:]):
                raise ValueError("active swap defeats the tmpfs carve-out")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attest-fd", type=int, required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--cgroup-root", default="/sys/fs/cgroup")
    parser.add_argument("--proc-cgroup", default="/proc/self/cgroup")
    parser.add_argument("--proc-swaps", default="/proc/swaps")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return 125
    try:
        expected = json.loads(args.expected)
        if not isinstance(expected, dict):
            return 125
        verify(expected, root=Path(args.cgroup_root), proc_cgroup=Path(args.proc_cgroup),
               proc_swaps=Path(args.proc_swaps))
        os.write(args.attest_fd, b"1")
        os.close(args.attest_fd)
        os.execvpe(command[0], command, dict(os.environ))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 125
    return 125


if __name__ == "__main__":
    raise SystemExit(main())
