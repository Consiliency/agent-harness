"""Linux CPU observations for a process group and its descendants.

Owner wrappers can start a child in another session. Include that child tree
when sampling the leg. Missing /proc data yields zero; CPU activity alone does
not establish completion or grant heartbeat-only termination authority.
"""
from __future__ import annotations

import os


def _pgrp_and_ticks(pid: int) -> tuple[int, int]:
    """Return ``(process_group_id, utime+stime)`` for ``pid`` from /proc/<pid>/stat.

    The ``comm`` field (2nd) is wrapped in parens and may itself contain spaces or
    parens, so parse the fixed fields AFTER the last ``)``: from there field 3
    (state) is index 0, so pgrp (field 5) = index 2, utime (14) = index 11, and
    stime (15) = index 12.
    """
    with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as fh:
        data = fh.read()
    after = data[data.rfind(")") + 2 :].split()
    pgrp = int(after[2])
    return pgrp, int(after[11]) + int(after[12])


def group_cpu_ticks(leader_pid: int) -> int:
    """Sum observed ticks for the group and children, including new sessions."""
    samples = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii", errors="replace") as fh:
                data = fh.read()
            fields = data[data.rfind(")") + 2 :].split()
            samples[int(entry)] = (int(fields[1]), int(fields[2]),
                                   int(fields[11]) + int(fields[12]))
        except (OSError, ValueError, IndexError):
            continue  # process exited mid-scan, or an unreadable/odd stat line
    members = {pid for pid, (_, group, _) in samples.items() if group == leader_pid}
    if leader_pid in samples:
        members.add(leader_pid)
    children = {}
    for pid, (parent, _, _) in samples.items():
        children.setdefault(parent, []).append(pid)
    pending = list(members)
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in members:
                members.add(child)
                pending.append(child)
    return sum(samples[pid][2] for pid in members)
