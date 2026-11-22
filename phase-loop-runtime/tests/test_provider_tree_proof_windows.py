"""``provider_tree_proof`` imports on native Windows and fails closed there
(agent-harness#2086, JEVHOST contract S5); its POSIX readiness mask is unchanged.

The Windows case runs in a fresh interpreter. It imports the module's stdlib
dependencies first. It then removes ``select.poll`` and every ``select.POLL*`` name,
blocks ``fcntl``, and drops the POSIX-only ``os`` and ``signal`` names before importing
the module.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import textwrap

import pytest

from phase_loop_runtime import provider_tree_proof as tp

_WINDOWS_SIM = textwrap.dedent(
    """
    import json, os, select, signal, sys
    # The stdlib takes its own win32 branches on Windows: import it before stripping names.
    import errno, pathlib, re, subprocess, threading, time, typing, weakref
    for name in [n for n in dir(select) if n.startswith(("POLL", "EPOLL"))] + ["poll", "epoll"]:
        if hasattr(select, name):
            delattr(select, name)
    sys.modules["fcntl"] = None
    for name in ("killpg", "getpgid", "setsid", "pidfd_open", "WNOHANG", "pread"):
        if hasattr(os, name):
            delattr(os, name)
    for name in ("SIGKILL", "pidfd_send_signal"):
        if hasattr(signal, name):
            delattr(signal, name)
    from phase_loop_runtime import provider_tree_proof as tp
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"x")  # readable: a poll-based read would report it ready
    observed = tp.TreeProof.bwrap_init(read_fd)
    waited = tp.TreeProof.bwrap_init(os.dup(read_fd))
    events = tp.TreeProof.cgroup(os.dup(read_fd), None, unit="u.scope",
                                 kill_fallback=lambda timeout: None)
    print(json.dumps({
        "ready": tp._PIDFD_READY,
        "observe": observed.observe(),
        "observe_status": [observed.status, observed.reason],
        "wait": waited.wait(time.monotonic() + 0.2),
        "wait_status": [waited.status, waited.reason],
        "cgroup": events.observe(),
        "cgroup_status": [events.status, events.reason],
    }))
    """
)


def test_imports_and_fails_closed_without_select_poll():
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    done = subprocess.run([sys.executable, "-c", _WINDOWS_SIM], capture_output=True,
                          text=True, timeout=60, env=env)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["ready"] is None
    assert result["observe"] is False
    assert result["observe_status"] == [tp.UNKNOWN, "poll_unavailable"]
    assert result["wait"] is False
    assert result["wait_status"] == [tp.UNKNOWN, "poll_unavailable"]
    assert result["cgroup"] is False
    assert result["cgroup_status"] == [tp.UNKNOWN, "poll_unavailable"]


@pytest.mark.skipif(not hasattr(select, "poll"), reason="POSIX select.poll only")
def test_posix_pidfd_ready_mask_is_unchanged():
    assert tp._PIDFD_READY == select.POLLIN | select.POLLHUP | select.POLLERR
    if sys.platform.startswith("linux"):
        assert tp._PIDFD_READY == 0x19  # POLLIN 0x1 | POLLERR 0x8 | POLLHUP 0x10
