"""Exec'd lease supervisor for executor launches (agent-harness#1140).

``launcher.launch`` starts this file as its own program::

    python -I <this file> --lease-fd N --exec-status-fd W -- <executor argv>

so that no Python runs in a child forked from the (possibly threaded) launcher
before ``exec``.  The supervisor is a fresh single-threaded interpreter, which
makes its own ``fork`` of the executor safe.

This file must stay stdlib-only: ``-I`` drops ``PYTHONPATH``, so importing
``phase_loop_runtime`` here would resolve to whatever copy is installed rather
than the copy that launched us.  ``launcher`` re-exports ``LeaseSupervisor``.
"""

from __future__ import annotations

import ctypes
import os
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

# Python ignores these at startup; Popen's ``restore_signals`` handed the
# executor the default disposition when it was exec'd from the launcher child.
_STARTUP_IGNORED_SIGNALS = tuple(
    getattr(signal, name) for name in ("SIGPIPE", "SIGXFZ", "SIGXFSZ") if hasattr(signal, name)
)


class LeaseSupervisor:
    """POSIX supervisor retaining a lease until its executor tree is gone."""

    _DESCENDANT_REAP_GRACE_SECONDS = 5.0
    _DESCENDANT_KILL_GRACE_SECONDS = 1.0

    @staticmethod
    def enable_subreaper() -> None:
        ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER

    def reap_direct_child(self, process: subprocess.Popen) -> None:
        process.wait()

    @staticmethod
    def _adopted_descendants() -> tuple[int, ...]:
        """List the subreaper's live descendant tree without using a process group."""

        parent_by_pid: dict[int, int] = {}
        for stat_path in Path("/proc").glob("[0-9]*/stat"):
            try:
                pid = int(stat_path.parts[-2])
                fields = stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
                parent_by_pid[pid] = int(fields[1])
            except (IndexError, OSError, ValueError):
                continue
        descendants: set[int] = set()
        parents = {os.getpid()}
        while parents:
            children = {pid for pid, parent in parent_by_pid.items() if parent in parents}
            children.difference_update(descendants)
            descendants.update(children)
            parents = children
        return tuple(sorted(descendants))

    def _signal_adopted_descendants(self, signum: int) -> None:
        for pid in self._adopted_descendants():
            try:
                os.killpg(os.getpgid(pid), signum)
            except ProcessLookupError:
                continue

    def reap_descendants(self, process: subprocess.Popen) -> int:
        returncode = process.wait()
        # The executor is a session leader, but descendants can call ``setsid``
        # and leave that group. The subreaper adopts every surviving descendant,
        # so explicit child reaping establishes complete-tree emptiness and /proc
        # provides the signal targets for session-detached descendants at the
        # grace limit.
        reap_deadline = time.monotonic() + self._DESCENDANT_REAP_GRACE_SECONDS
        kill_deadline: float | None = None
        sent_sigkill = False
        while True:
            descendants = self._adopted_descendants()
            if not descendants:
                break
            for pid in descendants:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue
            now = time.monotonic()
            if kill_deadline is None and now >= reap_deadline:
                self._signal_adopted_descendants(signal.SIGTERM)
                kill_deadline = now + self._DESCENDANT_KILL_GRACE_SECONDS
            elif kill_deadline is not None and not sent_sigkill and now >= kill_deadline:
                self._signal_adopted_descendants(signal.SIGKILL)
                sent_sigkill = True
            time.sleep(0.01)
        return returncode


class _ForkedExecutor:
    """Small Popen-compatible wait surface for the forked executor child."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.process_group_id = pid
        self.returncode: int | None = None

    def wait(self) -> int:
        if self.returncode is None:
            _, status = os.waitpid(self.pid, 0)
            self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode


def _close_descriptors_except(keep: tuple[int, ...]) -> None:
    max_fd = int(os.sysconf("SC_OPEN_MAX"))
    low = 0
    for fd in sorted(set(keep)):
        # An empty range must be skipped: CPython hands ``closerange(0, 0)``
        # to ``close_range(0, ~0U)``, which closes every descriptor.
        if low < fd:
            os.closerange(low, fd)
        low = fd + 1
    os.closerange(low, max_fd)


def _close_supervisor_descriptors(lease_fd: int) -> None:
    _close_descriptors_except((lease_fd,))


def _handed_through(fd: int) -> bool:
    """True only for a descriptor the launcher actually passed via ``pass_fds``.

    A descriptor the launcher did not pass is closed before this program runs;
    its number may since have been reused by the interpreter, which opens its
    own descriptors non-inheritable.  Either way it is not ours to hold.
    """

    try:
        inheritable = os.get_inheritable(fd)
    except OSError:
        return False
    if not inheritable:
        os.close(fd)
    return inheritable


def _initial_environment() -> dict[bytes, bytes]:
    """Return the environment exactly as the launcher passed it to ``exec``.

    Interpreter startup can rewrite ``os.environ`` (PEP 538 sets ``LC_CTYPE``
    under a C locale, and ``-I`` ignores ``PYTHONCOERCECLOCALE``);
    ``/proc/self/environ`` keeps the block the kernel received.
    """

    environment: dict[bytes, bytes] = {}
    for entry in Path("/proc/self/environ").read_bytes().split(b"\0"):
        if entry:
            key, _, value = entry.partition(b"=")
            environment[key] = value
    return environment


def _exec_executor(command: list[str], lease_fd: int | None, status_fd: int | None, environment: dict[bytes, bytes]) -> None:
    """Forked-executor half: become a subreaping session leader, then exec."""

    try:
        os.setsid()
        LeaseSupervisor.enable_subreaper()
        for signum in _STARTUP_IGNORED_SIGNALS:
            signal.signal(signum, signal.SIG_DFL)
        _close_descriptors_except(tuple(fd for fd in (0, 1, 2, lease_fd, status_fd) if fd is not None))
        if status_fd is not None:
            os.set_inheritable(status_fd, False)
        os.execvpe(command[0], command, environment)
    except OSError as exc:
        status = f"exec:{exc.errno or 0}"
    except BaseException:
        status = "setup"
    if status_fd is not None:
        try:
            os.write(status_fd, status.encode("ascii"))
        except OSError:
            pass
    os._exit(255)


def supervise(lease_fd: int, status_fd: int, command: list[str]) -> None:
    """Fork the executor, then retain the lease until its whole tree is gone."""

    held_lease_fd = lease_fd if _handed_through(lease_fd) else None
    held_status_fd = status_fd if _handed_through(status_fd) else None
    environment = _initial_environment()
    LeaseSupervisor.enable_subreaper()
    executor_pid = os.fork()
    if executor_pid == 0:
        _exec_executor(command, held_lease_fd, held_status_fd, environment)

    _close_supervisor_descriptors(lease_fd)

    def terminate_executor(_signum, _frame) -> None:
        try:
            os.killpg(executor_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        def force_kill(_alarm_signum, _alarm_frame) -> None:
            try:
                os.killpg(executor_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        signal.signal(signal.SIGALRM, force_kill)
        signal.setitimer(signal.ITIMER_REAL, 1)

    signal.signal(signal.SIGTERM, terminate_executor)
    signal.signal(signal.SIGINT, terminate_executor)
    try:
        executor = _ForkedExecutor(executor_pid)
        returncode = LeaseSupervisor().reap_descendants(executor)
    except BaseException:
        returncode = 1
    os._exit(returncode if isinstance(returncode, int) and 0 <= returncode <= 255 else 1)


def main(argv: list[str]) -> None:
    if len(argv) < 6 or argv[0] != "--lease-fd" or argv[2] != "--exec-status-fd" or argv[4] != "--":
        sys.stderr.write("usage: lease_supervisor.py --lease-fd N --exec-status-fd W -- COMMAND...\n")
        os._exit(2)
    supervise(int(argv[1]), int(argv[3]), argv[5:])


if __name__ == "__main__":
    main(sys.argv[1:])
