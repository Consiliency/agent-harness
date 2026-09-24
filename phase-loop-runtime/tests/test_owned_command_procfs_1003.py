"""agent-harness#1003: the heartbeat owner wrapper gives its PID namespace its OWN procfs.

``_ReviewMonitor.owned_command`` runs the provider in a new PID namespace. With the host
/proc merely bind-mounted, a provider that starts its own bubblewrap sandbox (codex's
``workspace-write`` sandbox, ``--as-pid-1 --unshare-pid --proc /proc``) resolved
``/proc/<pid>/ns`` entries in the wrong PID namespace and failed before any command ran:
``bwrap: open /proc/26/ns/ns failed`` (codex-cli 0.156.1, bubblewrap 0.9.0, Linux 7.0;
reproduced on that host, and fixed there by ``--proc /proc``). The property that fix
establishes is kernel-independent and asserted here without any provider: inside the
wrapper, ``/proc`` describes the wrapper's own PID namespace.
"""
from __future__ import annotations

import shutil
import subprocess
import threading

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress

PROBE = [
    "/bin/sh", "-c",
    "readlink /proc/self/ns/pid; readlink /proc/1/ns/pid; cat /proc/1/comm",
]

needs_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None and not __import__("os").path.exists("/usr/bin/bwrap"),
    reason="bubblewrap is not installed on this host",
)


def _run(monitor, *, prefix=()):
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
    try:
        proc = panel_invoker.launch_provider(
            PROBE, process_owner=monitor.owned_command(()),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, err = proc.communicate(timeout=30)
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert proc.returncode == 0, err.decode()
    return out.decode().split("\n")


def _assert_own_procfs(lines):
    self_ns, init_ns, init_comm = lines[0], lines[1], lines[2]
    # /proc/1 is THIS namespace's init, so it shares the probe's PID namespace ...
    assert self_ns == init_ns, f"/proc shows another PID namespace: self={self_ns} /proc/1={init_ns}"
    # ... and it is the wrapper's init, never the host's (systemd / init).
    assert init_comm not in ("systemd", "init"), init_comm


def test_the_owner_argv_mounts_a_fresh_procfs(tmp_path):
    monitor = panel_invoker._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event())
    argv = monitor.owned_command(())
    assert argv[argv.index("--proc") + 1] == "/proc"
    assert argv.index("--unshare-pid") < argv.index("--proc") < argv.index("--")


@needs_bwrap
def test_the_owned_namespace_sees_its_own_procfs(tmp_path):
    monitor = panel_invoker._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event())
    _assert_own_procfs(_run(monitor))


@needs_bwrap
@pytest.mark.skipif(
    not sandbox_egress.egress_isolation_available(),
    reason="this host cannot enforce egress isolation (sandbox_egress.egress_isolation_available() is False)",
)
def test_the_owned_namespace_sees_its_own_procfs_inside_the_egress_namespace(tmp_path):
    # The production heartbeat composition: egress prefix, then the owner wrapper.
    monitor = panel_invoker._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event())
    with sandbox_egress.isolated_network(timeout_s=None) as prefix:
        _assert_own_procfs(_run(monitor, prefix=prefix))
