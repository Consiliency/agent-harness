"""Exec'd lease supervisor for executor launches (agent-harness#1140).

``launcher.launch`` starts this file as its own program::

    python -I -S <this file> --lease-fd N --exec-status-fd W -- <executor argv>

so that no Python runs in a child forked from the (possibly threaded) launcher
before ``exec``.  The supervisor is a fresh single-threaded interpreter, which
makes its own ``fork`` of the executor safe; ``-S`` keeps site initialization
(``.pth`` files, ``sitecustomize``) from starting threads before that fork.

Startup is a handshake, so the executor never runs unsupervised.  The forked
child first becomes a session and process-group leader and reports
``grouped`` on a private pipe, so that ``killpg(executor_pid)`` addresses it
from then on; it then blocks on a private go-pipe.  The supervisor waits for
``grouped``, installs its forwarding handlers, and only then releases the
child.  If the supervisor dies first, the child reads EOF and exits without
``exec``; if the child dies before ``grouped``, it is never released.

The status descriptor carries newline-terminated records to the launcher:
``released`` from the child once it holds the go signal and is about to
``exec``, ``exec:<errno>`` if that ``exec`` fails, and ``setup:<reason>`` if
anything before it fails.  No ``released`` record therefore means the
executor never ran.

This file must stay stdlib-only: ``-I`` drops ``PYTHONPATH``, so importing
``phase_loop_runtime`` here would resolve to whatever copy is installed rather
than the copy that launched us.  ``launcher`` re-exports ``LeaseSupervisor``.
"""

from __future__ import annotations

import ctypes
import errno
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

    def _signal_adopted_descendants(self, signum: int, exclude: int | None = None) -> None:
        for pid in self._adopted_descendants():
            if pid == exclude:
                continue
            try:
                os.killpg(os.getpgid(pid), signum)
            except ProcessLookupError:
                continue

    def reap_descendants(self, process: subprocess.Popen) -> int:
        # ``process.wait()`` observes the executor's exit WITHOUT reaping it: the
        # zombie leader keeps its pid and process-group number from being reused
        # while forwarding can still ``killpg`` them.  It is reaped by the caller
        # only after forwarding is switched off, and never in the loop below.
        returncode = process.wait()
        leader = process.pid
        # The executor is a session leader, but descendants can call ``setsid``
        # and leave that group. The subreaper adopts every surviving descendant,
        # so explicit child reaping establishes complete-tree emptiness and /proc
        # provides the signal targets for session-detached descendants at the
        # grace limit.
        reap_deadline = time.monotonic() + self._DESCENDANT_REAP_GRACE_SECONDS
        kill_deadline: float | None = None
        sent_sigkill = False
        while True:
            descendants = tuple(pid for pid in self._adopted_descendants() if pid != leader)
            if not descendants:
                break
            for pid in descendants:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue
            now = time.monotonic()
            if kill_deadline is None and now >= reap_deadline:
                self._signal_adopted_descendants(signal.SIGTERM, exclude=leader)
                kill_deadline = now + self._DESCENDANT_KILL_GRACE_SECONDS
            elif kill_deadline is not None and not sent_sigkill and now >= kill_deadline:
                self._signal_adopted_descendants(signal.SIGKILL, exclude=leader)
                sent_sigkill = True
            time.sleep(0.01)
        return returncode


class _ForkedExecutor:
    """Small Popen-compatible wait surface for the forked executor child.

    ``wait`` observes the exit but leaves the child a zombie (``WNOWAIT``), so
    its pid and group number stay reserved; ``reap`` collects it at the end.
    """

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.process_group_id = pid
        self.returncode: int | None = None

    def wait(self) -> int:
        if self.returncode is None:
            info = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOWAIT)
            if info.si_code == os.CLD_EXITED:
                self.returncode = info.si_status
            else:  # CLD_KILLED / CLD_DUMPED: same as waitstatus_to_exitcode
                self.returncode = -info.si_status
        return self.returncode

    def reap(self) -> None:
        # Non-blocking: after an unexpected supervisor error the executor may
        # still run, and the old supervisor never waited for it at that point.
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass


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


_GO = b"go"
_GROUPED = b"grouped"


def _above_stdio(fd: int) -> int:
    """Move a close-on-exec descriptor to 3 or above."""
    if fd > 2:
        return fd
    import fcntl  # POSIX-only, and ``launcher`` imports this module on every platform

    moved = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
    os.close(fd)
    return moved


def _signal_executor(executor_pid: int, signum: int) -> None:
    # Only the executor's process group, never its bare pid: the child is a
    # group leader before it can be released (``grouped``), and once its group
    # is gone a stale pid may name an unrelated process.
    try:
        os.killpg(executor_pid, signum)
    except ProcessLookupError:
        pass


def _read_exactly(fd: int, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = os.read(fd, size - len(data))
        if not chunk:
            break
        data += chunk
    return data


def _report(status_fd: int | None, record: str) -> None:
    if status_fd is not None:
        try:
            os.write(status_fd, record.encode("ascii") + b"\n")
        except OSError:
            pass


def _setup_reason(exc: BaseException) -> str:
    code = getattr(exc, "errno", None)
    if isinstance(code, int) and code:
        return f"setup:{errno.errorcode.get(code, code)}"
    return f"setup:{type(exc).__name__}"


def _exec_executor(
    command: list[str],
    lease_fd: int | None,
    status_fd: int | None,
    go_fd: int,
    grouped_fd: int,
    environment: dict[bytes, bytes],
    inherited_sigchld: object = signal.SIG_DFL,
) -> None:
    """Forked-executor half: become a subreaping session leader, wait for go, then exec."""

    try:
        try:
            os.setsid()
        except BaseException as exc:
            _report(status_fd, _setup_reason(exc))
            return
        try:
            os.write(grouped_fd, _GROUPED)
        except OSError:
            return  # EPIPE: the supervisor is gone (the child holds no read end): never exec
        try:
            LeaseSupervisor.enable_subreaper()
            for signum in _STARTUP_IGNORED_SIGNALS:
                signal.signal(signum, signal.SIG_DFL)
            # The executor inherits exactly the SIGCHLD disposition we were given.
            signal.signal(signal.SIGCHLD, inherited_sigchld)
            _close_descriptors_except(tuple(fd for fd in (0, 1, 2, lease_fd, status_fd, go_fd) if fd is not None))
            if status_fd is not None:
                os.set_inheritable(status_fd, False)
            os.set_inheritable(go_fd, False)
        except BaseException as exc:
            _report(status_fd, _setup_reason(exc))
            return
        if os.read(go_fd, len(_GO)) != _GO:
            return  # the supervisor died before supervision was ready: never exec
        _report(status_fd, "released")
        try:
            os.execvpe(command[0], command, environment)
        except OSError as exc:
            _report(status_fd, f"exec:{exc.errno or 0}")
        except BaseException as exc:
            _report(status_fd, _setup_reason(exc))
    finally:
        os._exit(255)


def supervise(lease_fd: int, status_fd: int, command: list[str]) -> None:
    """Fork the executor, then retain the lease until its whole tree is gone."""

    held_status_fd: int | None = None
    try:
        held_status_fd = status_fd if _handed_through(status_fd) else None
        held_lease_fd = lease_fd if _handed_through(lease_fd) else None
        environment = _initial_environment()
        # An inherited SIGCHLD=SIG_IGN would make the kernel auto-reap the
        # executor, so its zombie could not pin pid/pgid E (and its status would
        # be lost).  Supervise with the default; the child restores the original.
        inherited_sigchld = signal.getsignal(signal.SIGCHLD)
        if inherited_sigchld not in (signal.SIG_DFL, signal.SIG_IGN):
            inherited_sigchld = signal.SIG_DFL
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        go_read, go_write = (_above_stdio(fd) for fd in os.pipe())
        grouped_read, grouped_write = (_above_stdio(fd) for fd in os.pipe())
        LeaseSupervisor.enable_subreaper()
        executor_pid = os.fork()
    except BaseException as exc:
        _report(held_status_fd, _setup_reason(exc))
        os._exit(255)
    if executor_pid == 0:
        # Drop the supervisor's ends at once: with no other reader left, the
        # ``grouped`` write fails (EPIPE, SIGPIPE being ignored here) if the
        # supervisor is already gone, and the GO read sees EOF.
        os.close(go_write)
        os.close(grouped_read)
        _exec_executor(command, held_lease_fd, held_status_fd, go_read, grouped_write, environment, inherited_sigchld)

    os.close(go_read)
    os.close(grouped_write)
    grouped = _read_exactly(grouped_read, len(_GROUPED)) == _GROUPED
    os.close(grouped_read)
    if not grouped:
        # The child died before becoming a group leader; it is never released.
        os.close(go_write)
        _close_supervisor_descriptors(lease_fd)
        executor = _ForkedExecutor(executor_pid)
        returncode = _reap(executor)
        executor.reap()
        _exit_with(returncode)

    terminated = False

    def terminate_executor(_signum, _frame) -> None:
        nonlocal terminated
        terminated = True
        _signal_executor(executor_pid, signal.SIGTERM)

        def force_kill(_alarm_signum, _alarm_frame) -> None:
            _signal_executor(executor_pid, signal.SIGKILL)

        signal.signal(signal.SIGALRM, force_kill)
        signal.setitimer(signal.ITIMER_REAL, 1)

    # Forwarding is live before the child may exec: release it only afterwards,
    # and not at all once a termination request has arrived.  TERM/INT are held
    # across the flag test and the release so neither can fall between them; a
    # held signal is forwarded to the (already existing) group on unblock.
    signal.signal(signal.SIGTERM, terminate_executor)
    signal.signal(signal.SIGINT, terminate_executor)
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    try:
        _close_descriptors_except((lease_fd, go_write))
        if not terminated:
            try:
                os.write(go_write, _GO)
            except OSError:
                pass
        os.close(go_write)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    _close_supervisor_descriptors(lease_fd)
    executor = _ForkedExecutor(executor_pid)
    returncode = _reap(executor)
    # Forwarding off before the leader is reaped: after that its pid and group
    # number are free for reuse.
    signal.setitimer(signal.ITIMER_REAL, 0)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
        signal.signal(signum, signal.SIG_IGN)
    executor.reap()
    _exit_with(returncode)


def _reap(executor: _ForkedExecutor) -> object:
    try:
        return LeaseSupervisor().reap_descendants(executor)
    except BaseException:
        return 1


def _exit_with(returncode: object) -> None:
    os._exit(returncode if isinstance(returncode, int) and 0 <= returncode <= 255 else 1)


def main(argv: list[str]) -> None:
    if len(argv) < 6 or argv[0] != "--lease-fd" or argv[2] != "--exec-status-fd" or argv[4] != "--":
        sys.stderr.write("usage: lease_supervisor.py --lease-fd N --exec-status-fd W -- COMMAND...\n")
        os._exit(2)
    supervise(int(argv[1]), int(argv[3]), argv[5:])


if __name__ == "__main__":
    main(sys.argv[1:])
