"""The ordinary (observer-less) streaming launch keeps every line its child wrote
(agent-harness#2092 follow-up).

Two bugs on that path lost output:
- when the child exited, the loop drained only the lines already queued and stopped,
  while the reader thread still held the child's last lines;
- invalid UTF-8 raised in the text-mode reader thread, which then dropped every later
  line.

The first is reproduced without timing: the reader is held back until the launcher's
first post-exit dequeue has found the queue empty. The fix must keep the stdin codec
strict and bound the post-exit collection.
"""
from __future__ import annotations

import errno
import queue
import subprocess
import sys
import threading
import time

import pytest

from phase_loop_runtime import launcher, panel_invoker

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX streaming path")

MARKER = "phase-loop-drain-test-child"
LINES = ["first", "second", "third"]


def _child(script: str) -> list[str]:
    return [sys.executable, "-c", f"# {MARKER}\n" + script]


def _watch_exit(monkeypatch) -> threading.Event:
    """Set once the launcher's poll() has seen the test child exit."""
    exited = threading.Event()
    original_poll = subprocess.Popen.poll

    def poll(self):
        returncode = original_poll(self)
        if returncode is not None and MARKER in " ".join(map(str, self.args)):
            exited.set()
        return returncode

    monkeypatch.setattr(subprocess.Popen, "poll", poll)
    return exited


def test_lines_the_reader_still_holds_at_exit_are_kept(tmp_path, monkeypatch):
    exited = _watch_exit(monkeypatch)
    empty_after_exit = threading.Event()

    class GatedQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            if not exited.is_set():
                return super().get(block, timeout)
            try:
                return super().get(block=False)
            except queue.Empty:
                # The launcher has seen the exit and found nothing queued: only now
                # may the reader deliver the rest.
                empty_after_exit.set()
                if not block:
                    raise
            return super().get(block, timeout)

    monkeypatch.setattr(launcher, "Queue", GatedQueue)
    original_reader = launcher._read_lines
    released = []

    def held_reader(stdout, line_queue):
        def lines():
            iterator = iter(stdout)
            yield next(iterator)
            rest = list(iterator)  # the child has written everything; EOF is reached
            released.append(empty_after_exit.wait(10))
            yield from rest
        original_reader(lines(), line_queue)

    monkeypatch.setattr(launcher, "_read_lines", held_reader)
    script = "".join(f"print({line!r}, flush=True)\n" for line in LINES)
    result = launcher.launch(_child(script), log_path=tmp_path / "run" / "output.log")
    assert exited.is_set() and released == [True]
    assert result.returncode == 0
    assert result.output.splitlines() == LINES
    assert (tmp_path / "run" / "output.log").read_text(encoding="utf-8").splitlines() == LINES


def test_post_exit_collection_stops_at_its_budget(tmp_path, monkeypatch):
    exited = _watch_exit(monkeypatch)
    stop = time.monotonic() + 8

    class EndlessQueue(queue.Queue):
        """After exit, a record is always readable until well past the budget."""

        def get(self, block=True, timeout=None):
            if not exited.is_set():
                return super().get(block, timeout)
            if time.monotonic() < stop:
                time.sleep(0.005)
                return "more\n"
            if not block:
                raise queue.Empty
            return None

    monkeypatch.setattr(launcher, "Queue", EndlessQueue)
    started = time.monotonic()
    result = launcher.launch(_child("print('root', flush=True)\n"), log_path=tmp_path / "run" / "output.log")
    assert time.monotonic() - started < 5
    assert result.returncode == 0 and "root" in result.output and "more" in result.output


def test_invalid_output_bytes_do_not_kill_the_reader(tmp_path, monkeypatch):
    launch_owned = panel_invoker.launch_owned

    def launch_with_utf8(*args, **kwargs):
        return launch_owned(*args, **{**kwargs, "encoding": "utf-8"})

    monkeypatch.setattr(panel_invoker, "launch_owned", launch_with_utf8)
    failures = []
    monkeypatch.setattr(threading, "excepthook", lambda args: failures.append(args.exc_type))
    raw = b"before\n\xff\nafter\n"
    script = "import os\nos.write(1, " + repr(raw) + ")\n"
    result = launcher.launch(_child(script), log_path=tmp_path / "run" / "output.log")
    assert result.returncode == 0
    assert not failures
    assert result.output.splitlines() == ["before", "\ufffd", "after"]


def test_unencodable_stdin_still_fails(tmp_path):
    # A lone surrogate has no strict encoding in any codec, so the stdin codec must refuse
    # it rather than send a replacement character to the executor.
    with pytest.raises(UnicodeEncodeError):
        launcher.launch(_child("pass\n"), stdin_text="prompt \udc80",
                        log_path=tmp_path / "run" / "output.log")


def _proc_alive(pid: int) -> bool:
    import os
    from pathlib import Path

    stat_path = Path("/proc") / str(pid) / "stat"
    if stat_path.exists():
        try:
            tail = stat_path.read_text().rpartition(")")[2].split()
            if tail and tail[0] in {"Z", "X", "x"}:
                return False
        except (FileNotFoundError, ProcessLookupError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_pid_best_effort(marker):
    import os
    import signal

    if not marker.exists():
        return
    try:
        pid = int(marker.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGKILL)
    except (OSError, ValueError):
        pass


def test_grandchild_holding_stdout_open_past_child_exit_is_bounded_and_cleaned(tmp_path):
    marker = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"Path({str(marker)!r}).write_text(str(p.pid), encoding='utf-8')\n"
        "print('child-done', flush=True)\n"
    )
    try:
        started = time.monotonic()
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.5,
        )
        elapsed = time.monotonic() - started
        assert elapsed < 1.5
        assert result.returncode == 0
        assert "child-done" in result.output
        assert result.drain_incomplete is True
        assert result.event_metadata()["drain_incomplete"] is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["reason"] == "post_exit_pipe_open"
        assert result.cleanup_evidence["result"] in {"terminated", "killed"}
        grandchild_pid = int(marker.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_grandchild_holding_stdout_open_marks_usage_unknown_and_cleans_group(tmp_path, monkeypatch):
    from test_jevdrill_usage import captures, synthetic_spec

    if not captures():
        pytest.skip("usage capture requires Linux")
    marker = tmp_path / "grandchild-usage.pid"
    tail = (
        "import subprocess\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"Path({str(marker)!r}).write_text(str(p.pid), encoding='utf-8')\n"
    )
    spec = synthetic_spec(tmp_path, monkeypatch, tail=tail)
    try:
        started = time.monotonic()
        result = launcher.launch_with_spec(
            spec.__class__(**{**spec.__dict__, "launch_timeout_seconds": 0.6}),
            codex_usage_capture=True,
        )
        elapsed = time.monotonic() - started
        assert elapsed < 2.0
        assert result.returncode == 0
        assert result.drain_incomplete is True
        assert result.jevdrill_usage is None
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["reason"] == "post_exit_pipe_open"
        assert result.cleanup_evidence["result"] in {"terminated", "killed"}
        grandchild_pid = int(marker.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_read_lines_handles_large_line_and_errors():
    import os

    r_fd, w_fd = os.pipe()
    try:
        q: queue.Queue = queue.Queue()
        stop = threading.Event()
        eof = threading.Event()
        payload = ("x" * (2 * 1024 * 1024)) + "\nsecond\n"

        def writer():
            view = memoryview(payload.encode("utf-8"))
            sent = 0
            while sent < len(view):
                sent += os.write(w_fd, view[sent:sent + 65536])
            os.close(w_fd)

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        fake_stream = type("S", (), {"fileno": lambda self: r_fd, "encoding": "utf-8"})()
        started = time.monotonic()
        launcher._read_lines(fake_stream, q, stop, eof)
        elapsed = time.monotonic() - started
        t.join(timeout=5)
        assert eof.is_set()
        assert elapsed < 2.0
        first = q.get_nowait()
        second = q.get_nowait()
        sentinel = q.get_nowait()
        assert len(first) == 2 * 1024 * 1024 + 1
        assert second == "second\n"
        assert sentinel is None
    finally:
        try:
            os.close(r_fd)
        except OSError:
            pass

    # A reader error must NOT fabricate EOF.
    err_q: queue.Queue = queue.Queue()
    err_eof = threading.Event()
    broken = type("Broken", (), {"fileno": lambda self: -1, "encoding": "utf-8"})()
    launcher._read_lines(broken, err_q, threading.Event(), err_eof)
    assert not err_eof.is_set()
    assert err_q.empty()


def test_read_lines_handles_high_fd():
    import fcntl
    import os

    r_fd, w_fd = os.pipe()
    high_fd = None
    try:
        try:
            high_fd = fcntl.fcntl(r_fd, fcntl.F_DUPFD, 1024)
        except OSError as exc:
            os.close(w_fd)
            pytest.skip(f"cannot allocate unused fd >= 1024: {exc}")
        assert high_fd >= 1024
        q: queue.Queue = queue.Queue()
        eof = threading.Event()
        os.write(w_fd, b"high-fd-line\n")
        os.close(w_fd)
        fake_stream = type("S", (), {"fileno": lambda self: high_fd, "encoding": "utf-8"})()
        launcher._read_lines(fake_stream, q, threading.Event(), eof)
        assert eof.is_set()
        assert q.get_nowait() == "high-fd-line\n"
        assert q.get_nowait() is None
    finally:
        for fd in (r_fd, high_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def test_pipe_writers_closed_detects_hangup_with_unread_bytes():
    """Kernel POLLHUP reports closed writers immediately even while unread bytes remain
    in the pipe buffer, independent of reader thread progress."""
    import os

    r_fd, w_fd = os.pipe()
    fake_pipe = type("P", (), {"fileno": lambda self: r_fd})()
    try:
        os.write(w_fd, b"buffered-before-close\n")
        assert launcher._pipe_writers_closed(fake_pipe) is False
        os.close(w_fd)
        w_fd = -1
        assert launcher._pipe_writers_closed(fake_pipe) is True
    finally:
        for fd in (r_fd, w_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def test_sigterm_trapping_descendant_closing_pipe_is_escalated_to_sigkill(tmp_path):
    """A descendant that catches SIGTERM, closes stdout/stderr, and keeps running must
    still be escalated to SIGKILL rather than reported terminated on pipe EOF."""
    marker = tmp_path / "trap_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'def trap(*_):\\n'\n"
        "    '    for fd in (1, 2):\\n'\n"
        "    '        try: os.close(fd)\\n'\n"
        "    '        except OSError: pass\\n'\n"
        "    'signal.signal(signal.SIGTERM, trap)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('leader-done', flush=True)\n"
    )
    try:
        started = time.monotonic()
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=1.0,
        )
        assert time.monotonic() - started < 5.0
        assert result.returncode == 0
        assert "leader-done" in result.output
        assert result.drain_incomplete is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_interrupt_during_post_exit_drain_cleans_up_descendant_before_reap(tmp_path, monkeypatch):
    """If KeyboardInterrupt fires during post-exit drain after leader_unreaped was set,
    cleanup must signal the pinned process group BEFORE reaping the leader and must NOT
    run a second cleanup after reap."""
    marker = tmp_path / "interrupt_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "open(marker, 'w').write(str(proc.pid))\n"
        "print('leader-done', flush=True)\n"
    )
    orig_descendant_cleanup = launcher._cleanup_descendant_process_group
    cleanup_calls = []

    def spy_descendant_cleanup(
        process_pid, process_group_id, *, reason, pipes_closed, include_leader=False, leader_exited=None, **kwargs,
    ):
        cleanup_calls.append((reason, process_pid, process_group_id))
        return orig_descendant_cleanup(
            process_pid,
            process_group_id,
            reason=reason,
            pipes_closed=pipes_closed,
            include_leader=include_leader,
            leader_exited=leader_exited,
            **kwargs,
        )

    monkeypatch.setattr(launcher, "_cleanup_descendant_process_group", spy_descendant_cleanup)
    interrupt_fired = False
    orig_waitid = launcher._child_exited_no_reap
    leader_exited = threading.Event()

    def tracking_exited(proc):
        exited, unreaped = orig_waitid(proc)
        if exited:
            leader_exited.set()
        return exited, unreaped

    class InterruptInDrainQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            nonlocal interrupt_fired
            if leader_exited.is_set() and not interrupt_fired:
                interrupt_fired = True
                raise KeyboardInterrupt
            return super().get(block, timeout)

    monkeypatch.setattr(launcher, "_child_exited_no_reap", tracking_exited)
    monkeypatch.setattr(launcher, "Queue", InterruptInDrainQueue)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=1.5,
        )
        assert interrupt_fired is True
        assert result.interrupted is True
        assert len(cleanup_calls) == 1
        assert cleanup_calls[0][0] == "interrupt"
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["reason"] == "interrupt"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_live_pgid_members_exist_detects_live_worker_thread_when_main_thread_is_zombie(tmp_path, monkeypatch):
    """If a multi-threaded descendant's main thread exits (state Z) while a worker thread
    remains alive under /proc/<pid>/task/, _live_pgid_members_exist must still report True."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux /proc layout test")
    fake_proc = tmp_path / "proc"
    pid_dir = fake_proc / "424242"
    (pid_dir / "task" / "424242").mkdir(parents=True)
    (pid_dir / "task" / "424243").mkdir(parents=True)
    (pid_dir / "stat").write_text("424242 (worker) Z 1 77777 77777 0 -1\n", encoding="ascii")
    (pid_dir / "task" / "424242" / "stat").write_text("424242 (worker) Z 1 77777 77777 0 -1\n", encoding="ascii")
    (pid_dir / "task" / "424243" / "stat").write_text("424243 (worker) S 1 77777 77777 0 -1\n", encoding="ascii")

    real_path = launcher.Path

    def patched_path(arg, *rest):
        if arg == "/proc" and not rest:
            return fake_proc
        return real_path(arg, *rest)

    monkeypatch.setattr(launcher, "Path", patched_path)
    assert launcher._live_pgid_members_exist(77777, leader_pid=100001) is True
    (pid_dir / "task" / "424243" / "stat").write_text("424243 (worker) Z 1 77777 77777 0 -1\n", encoding="ascii")
    assert launcher._live_pgid_members_exist(77777, leader_pid=100001) is False


def test_interrupt_before_exit_recorded_still_cleans_up_descendant(tmp_path, monkeypatch):
    """If the leader exits while the launcher is waiting on the queue (before the main
    loop records leader_unreaped=True) and KeyboardInterrupt fires, the interrupt handler
    must detect the exited unreaped leader via waitid(WNOWAIT) and signal the group."""
    marker = tmp_path / "pre_poll_interrupt_grandchild.pid"
    script = (
        "import subprocess, sys\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(marker)!r}, 'w').write(str(proc.pid))\n"
        "print('leader-done', flush=True)\n"
    )
    interrupt_fired = False

    class InterruptBeforePollQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            nonlocal interrupt_fired
            val = super().get(block, timeout)
            if not interrupt_fired and val == "leader-done\n":
                # Give the leader a moment to exit while the launcher is still inside
                # line_queue.get() (before _child_exited_no_reap has ever run).
                time.sleep(0.15)
                interrupt_fired = True
                raise KeyboardInterrupt
            return val

    monkeypatch.setattr(launcher, "Queue", InterruptBeforePollQueue)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=1.5,
        )
        assert interrupt_fired is True
        assert result.interrupted is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["reason"] == "interrupt"
        assert "SIGTERM" in result.cleanup_evidence["signals_sent"]
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_interrupt_during_post_exit_sigterm_grace_escalates_to_sigkill(tmp_path, monkeypatch):
    """A KeyboardInterrupt during the SIGTERM grace period of post-exit descendant cleanup
    must still escalate to SIGKILL, reap the leader, and kill a SIGTERM-trapping grandchild."""
    marker = tmp_path / "grace_interrupt_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('leader-done', flush=True)\n"
    )
    orig_sleep = launcher.time.sleep
    injected = False

    def interrupting_sleep(seconds):
        nonlocal injected
        if seconds == 0.01 and not injected:
            injected = True
            raise KeyboardInterrupt
        return orig_sleep(seconds)

    monkeypatch.setattr(launcher.time, "sleep", interrupting_sleep)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.8,
        )
        assert injected is True
        assert result.returncode == 0
        assert result.interrupted is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            orig_sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_post_exit_and_interrupt_cleanup_work_without_os_waitid(tmp_path, monkeypatch):
    """When os.waitid is absent (e.g., simulated macOS Python 3.12), non-reaping inspection
    must keep the leader unreaped through BOTH post-exit drain timeout AND Ctrl-C."""
    monkeypatch.delattr(launcher.os, "waitid", raising=False)
    marker = tmp_path / "no_waitid_grandchild.pid"
    script = (
        "import subprocess, sys\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(marker)!r}, 'w').write(str(proc.pid))\n"
        "print('leader-done', flush=True)\n"
    )
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.5,
        )
        assert result.returncode == 0
        assert result.drain_incomplete is True
        assert result.cleanup_evidence is not None
        assert "SIGTERM" in result.cleanup_evidence["signals_sent"]
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)

    # Now verify Ctrl-C after exit when os.waitid is absent still signals the pinned group.
    marker2 = tmp_path / "no_waitid_interrupt_grandchild.pid"
    script2 = (
        "import subprocess, sys\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(marker2)!r}, 'w').write(str(proc.pid))\n"
        "print('leader-done', flush=True)\n"
    )
    exited_seen = threading.Event()
    orig_exited = launcher._child_exited_no_reap

    def track_exited(proc):
        ex, un = orig_exited(proc)
        if ex:
            exited_seen.set()
        return ex, un

    fired = False

    class InterruptInDrain(queue.Queue):
        def get(self, block=True, timeout=None):
            nonlocal fired
            if exited_seen.is_set() and not fired:
                fired = True
                raise KeyboardInterrupt
            return super().get(block, timeout)

    monkeypatch.setattr(launcher, "_child_exited_no_reap", track_exited)
    monkeypatch.setattr(launcher, "Queue", InterruptInDrain)
    try:
        result2 = launcher.launch(
            _child(script2),
            log_path=tmp_path / "run2" / "output.log",
            timeout_seconds=1.5,
        )
        assert fired is True
        assert result2.interrupted is True
        assert result2.cleanup_evidence is not None
        assert "SIGTERM" in result2.cleanup_evidence["signals_sent"]
        grandchild_pid2 = int(marker2.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid2) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid2)
    finally:
        _kill_pid_best_effort(marker2)


def test_timeout_cleanup_escalates_sigkill_for_sigterm_ignoring_descendant(tmp_path):
    """Timeout cleanup must not stop as soon as the leader exits on SIGTERM while a
    SIGTERM-ignoring grandchild remains alive."""
    marker = tmp_path / "timeout_sigign_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.5,
        )
        assert result.timed_out is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_interrupt_without_proc_liveness_escalates_sigkill_when_leader_closes_pipes(tmp_path, monkeypatch):
    """When /proc liveness is unavailable (non-Linux fallback), a live leader that catches
    SIGTERM, closes stdout/stderr, and keeps running must still escalate to SIGKILL."""
    monkeypatch.setattr(launcher, "_live_pgid_members_exist", lambda *a, **k: None)
    script = (
        "import os, signal, time\n"
        "def trap(*_):\n"
        "    for fd in (1, 2):\n"
        "        try: os.close(fd)\n"
        "        except OSError: pass\n"
        "signal.signal(signal.SIGTERM, trap)\n"
        "print('armed', flush=True)\n"
        "time.sleep(30)\n"
    )
    fired = False

    class InterruptAfterArmed(queue.Queue):
        def get(self, block=True, timeout=None):
            nonlocal fired
            val = super().get(block, timeout)
            if val == "armed\n" and not fired:
                fired = True
                raise KeyboardInterrupt
            return val

    monkeypatch.setattr(launcher, "Queue", InterruptAfterArmed)
    started = time.monotonic()
    result = launcher.launch(
        _child(script),
        log_path=tmp_path / "run" / "output.log",
        timeout_seconds=3.0,
    )
    assert fired is True
    assert time.monotonic() - started < 3.0
    assert result.interrupted is True
    assert result.cleanup_evidence is not None
    assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
    assert result.cleanup_evidence["result"] == "killed"


def test_second_interrupt_during_interrupt_drain_still_reaps_leader(tmp_path, monkeypatch):
    """A second KeyboardInterrupt during the interrupt handler's drain must still run
    finalization to reap the leader and stop reader threads."""
    script = "import time\nprint('started', flush=True)\ntime.sleep(30)\n"
    interrupts = 0

    class DoubleInterruptQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            nonlocal interrupts
            if interrupts == 0:
                val = super().get(block, timeout)
                if val == "started\n":
                    interrupts = 1
                    raise KeyboardInterrupt
                return val
            if interrupts == 1:
                interrupts = 2
                raise KeyboardInterrupt
            return super().get(block, timeout)

    monkeypatch.setattr(launcher, "Queue", DoubleInterruptQueue)
    result = launcher.launch(
        _child(script),
        log_path=tmp_path / "run" / "output.log",
        timeout_seconds=2.0,
    )
    assert interrupts == 2
    assert result.interrupted is True
    assert result.returncode is not None


def test_consume_write_error_terminates_running_child_before_waiting(tmp_path, monkeypatch):
    """If consume() raises (e.g., BrokenPipeError on streaming stdout), finalization must
    terminate the running child instead of blocking indefinitely in process.wait()."""
    script = "import time\nprint('boom', flush=True)\ntime.sleep(30)\n"
    real_print = __builtins__["print"] if isinstance(__builtins__, dict) else __builtins__.print

    def broken_print(*args, **kwargs):
        if args and "boom" in str(args[0]):
            raise BrokenPipeError("broken stdout")
        return real_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", broken_print)
    started = time.monotonic()
    with pytest.raises(BrokenPipeError):
        launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            stream_output=True,
            timeout_seconds=10.0,
        )
    assert time.monotonic() - started < 3.0


def test_timeout_without_proc_liveness_kills_sigterm_ignoring_pipe_closing_descendant(tmp_path, monkeypatch):
    """Off Linux (no /proc liveness), a same-group descendant that ignores SIGTERM and
    closes its pipes after the leader exits must still be escalated to SIGKILL."""
    monkeypatch.setattr(launcher, "_live_pgid_members_exist", lambda *a, **k: None)
    marker = tmp_path / "noproc_timeout_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'def trap(*_):\\n'\n"
        "    '    for fd in (1, 2):\\n'\n"
        "    '        try: os.close(fd)\\n'\n"
        "    '        except OSError: pass\\n'\n"
        "    'signal.signal(signal.SIGTERM, trap)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.5,
        )
        assert result.timed_out is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_detached_pipe_holder_outside_owned_group_does_not_report_cleanup_failed(tmp_path):
    """On Linux, when a detached writer in another session holds stdout open while the
    child's own process group is empty, cleanup must NOT falsely set
    process_alive_after_cleanup=True."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux /proc group isolation test")
    marker = tmp_path / "detached_writer.pid"
    script = (
        "import subprocess, sys\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)\n"
        f"open({str(marker)!r}, 'w').write(str(proc.pid))\n"
        "print('leader-done', flush=True)\n"
    )
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.5,
        )
        assert result.returncode == 0
        assert result.drain_incomplete is True
        if result.cleanup_evidence is not None:
            assert result.cleanup_evidence.get("process_alive_after_cleanup") is False
            assert result.cleanup_evidence.get("result") != "cleanup_failed"
    finally:
        _kill_pid_best_effort(marker)


def test_proc_exit_fallback_detects_live_worker_thread_when_main_thread_is_zombie(tmp_path, monkeypatch):
    """Linux /proc exit fallback (when os.waitid is absent) must report a multithreaded
    child with a zombie main thread and a live worker thread as still live (False)."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux /proc layout test")
    fake_proc = tmp_path / "proc"
    pid_dir = fake_proc / "515151"
    (pid_dir / "task" / "515151").mkdir(parents=True)
    (pid_dir / "task" / "515152").mkdir(parents=True)
    (pid_dir / "stat").write_text("515151 (worker) Z 1 515151 515151 0 -1\n", encoding="ascii")
    (pid_dir / "task" / "515151" / "stat").write_text("515151 (worker) Z 1 515151 515151 0 -1\n", encoding="ascii")
    (pid_dir / "task" / "515152" / "stat").write_text("515152 (worker) S 1 515151 515151 0 -1\n", encoding="ascii")

    real_path = launcher.Path

    def patched_path(arg, *rest):
        if arg == "/proc" and not rest:
            return fake_proc
        return real_path(arg, *rest)

    monkeypatch.delattr(launcher.os, "waitid", raising=False)
    monkeypatch.setattr(launcher, "Path", patched_path)
    assert launcher._waitid_nowait(515151) is False
    (pid_dir / "task" / "515152" / "stat").write_text("515152 (worker) Z 1 515151 515151 0 -1\n", encoding="ascii")
    assert launcher._waitid_nowait(515151) is True


def test_interrupt_during_post_sigkill_liveness_probe_still_reaps_leader(tmp_path, monkeypatch):
    """A KeyboardInterrupt raised inside _live_pgid_members_exist() during the post-SIGKILL
    wait loop must not escape or bypass process.wait() reaping."""
    marker = tmp_path / "sigkill_probe_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('leader-done', flush=True)\n"
    )
    orig_live = launcher._live_pgid_members_exist
    orig_killpg = launcher.os.killpg
    sigkill_sent = False
    probe_interrupted = False

    def spy_killpg(pgid, sig):
        nonlocal sigkill_sent
        if sig == launcher.signal.SIGKILL:
            sigkill_sent = True
        return orig_killpg(pgid, sig)

    def interrupting_live(pgid, *, leader_pid):
        nonlocal probe_interrupted
        if sigkill_sent and not probe_interrupted:
            probe_interrupted = True
            raise KeyboardInterrupt
        return orig_live(pgid, leader_pid=leader_pid)

    monkeypatch.setattr(launcher.os, "killpg", spy_killpg)
    monkeypatch.setattr(launcher, "_live_pgid_members_exist", interrupting_live)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.8,
        )
        assert sigkill_sent is True
        assert probe_interrupted is True
        assert result.returncode == 0
        assert result.interrupted is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_broken_pipe_during_post_exit_drain_still_cleans_up_descendant(tmp_path, monkeypatch):
    """If consume() raises BrokenPipeError during post-exit drain after leader exit,
    the finally block must still clean up same-group descendants before reaping the leader."""
    marker = tmp_path / "post_exit_broken_pipe_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('first-line', flush=True)\n"
        "print('post-exit-line', flush=True)\n"
    )
    orig_print = print

    def broken_on_second(*args, **kwargs):
        if args and "post-exit-line" in str(args[0]):
            raise BrokenPipeError("stdout closed during post-exit drain")
        return orig_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", broken_on_second)
    try:
        with pytest.raises(BrokenPipeError):
            launcher.launch(
                _child(script),
                log_path=tmp_path / "run" / "output.log",
                stream_output=True,
                timeout_seconds=10.0,
            )
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_interrupt_on_monotonic_after_sigterm_still_escalates_to_sigkill(tmp_path, monkeypatch):
    """A KeyboardInterrupt raised on time.monotonic() right after SIGTERM dispatch must
    not escape cleanup; it must proceed to SIGKILL and kill SIGTERM-ignoring descendants."""
    marker = tmp_path / "monotonic_interrupt_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('leader-done', flush=True)\n"
    )
    orig_killpg = launcher.os.killpg
    orig_monotonic = launcher.time.monotonic
    sigterm_sent = False
    injected = False

    def spy_killpg(pgid, sig):
        nonlocal sigterm_sent
        if sig == launcher.signal.SIGTERM:
            sigterm_sent = True
        return orig_killpg(pgid, sig)

    def interrupting_monotonic():
        nonlocal injected
        if sigterm_sent and not injected:
            injected = True
            raise KeyboardInterrupt
        return orig_monotonic()

    monkeypatch.setattr(launcher.os, "killpg", spy_killpg)
    monkeypatch.setattr(launcher.time, "monotonic", interrupting_monotonic)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.8,
        )
        assert injected is True
        assert result.returncode == 0
        assert result.interrupted is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_waitid_eperm_falls_back_to_linux_proc_without_premature_reap(tmp_path, monkeypatch):
    """When os.waitid fails with EPERM on Linux, _waitid_nowait must fall back to /proc
    so the leader stays unreaped and post-exit descendant cleanup runs."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux /proc fallback test")
    marker = tmp_path / "eperm_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('leader-done', flush=True)\n"
    )

    def eperm_waitid(*args, **kwargs):
        raise PermissionError(errno.EPERM, "waitid blocked by seccomp")

    monkeypatch.setattr(launcher.os, "waitid", eperm_waitid)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.8,
        )
        assert result.returncode == 0
        assert result.drain_incomplete is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["reason"] == "post_exit_pipe_open"
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_provisional_empty_proc_scan_does_not_skip_sigkill_for_forked_replacement(tmp_path, monkeypatch):
    """A single empty /proc scan during SIGTERM handling (when a worker forks a replacement
    and exits mid-scan) must be treated as provisional so a second scan catches the
    replacement and escalates to SIGKILL."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux /proc scan confirmation test")
    marker = tmp_path / "fork_replacement.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('leader-done', flush=True)\n"
    )
    orig_live = launcher._live_pgid_members_exist
    calls = 0

    def transient_empty_first_scan(pgid, *, leader_pid):
        nonlocal calls
        calls += 1
        if calls == 1:
            return False
        return orig_live(pgid, leader_pid=leader_pid)

    monkeypatch.setattr(launcher, "_live_pgid_members_exist", transient_empty_first_scan)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.8,
        )
        assert calls >= 2
        assert result.returncode == 0
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_leased_timeout_preserves_supervisor_window_to_kill_sigterm_ignoring_executor(tmp_path):
    """For leased launches, cleanup must give lease_supervisor its full 1 s escalation +
    reaping window before falling back to SIGKILLing the supervisor, so a SIGTERM-ignoring
    executor running in a separate session is killed and reaped."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux lease_supervisor test")
    import fcntl
    import os
    from types import SimpleNamespace

    marker = tmp_path / "leased_executor.pid"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(marker)!r}, 'w').write(str(os.getpid()))\n"
        "print('executor-ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    fd = os.open(tmp_path / "lease", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    authority = SimpleNamespace(fileno=lambda: fd, generation="synthetic", identity=None)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.4,
            lease_authority=authority,
        )
        assert result.timed_out is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM"]
        assert result.cleanup_evidence["result"] == "terminated"
        exec_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(exec_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(exec_pid)
    finally:
        os.close(fd)
        _kill_pid_best_effort(marker)


def test_second_interrupt_during_codex_usage_drain_invalidates_usage_observer(tmp_path, monkeypatch):
    """If a second KeyboardInterrupt aborts the Codex usage post-exit drain after a valid
    turn.completed record, drain_incomplete=True must invalidate the usage observer."""
    observer = launcher._CodexUsageCollector()
    script = (
        "import json, time\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 't1'}), flush=True)\n"
        "print(json.dumps({'type': 'turn.started'}), flush=True)\n"
        "print(json.dumps({'type': 'turn.completed', 'usage': {"
        "'input_tokens': 10, 'cached_input_tokens': 2, 'output_tokens': 5}}), flush=True)\n"
        "time.sleep(30)\n"
    )
    orig_get = launcher.Queue.get
    saw_turn = False
    interrupts = 0

    def interrupting_get(self, *args, **kwargs):
        nonlocal saw_turn, interrupts
        if saw_turn and interrupts < 2:
            interrupts += 1
            raise KeyboardInterrupt
        item = orig_get(self, *args, **kwargs)
        if isinstance(item, tuple) and len(item) == 3 and "turn.completed" in str(item[2]):
            saw_turn = True
        return item

    monkeypatch.setattr(launcher.Queue, "get", interrupting_get)
    result = launcher.launch(
        _child(script),
        log_path=tmp_path / "run" / "output.log",
        timeout_seconds=10.0,
        _codex_usage_observer=observer,
    )
    assert interrupts == 2
    assert result.interrupted is True
    assert result.drain_incomplete is True
    assert observer.diagnostics()["usage_valid"] is False
    assert observer.failure_reason == "incomplete_drain"


def test_interrupt_during_post_exit_broken_pipe_unwind_still_cleans_up_and_reaps(tmp_path, monkeypatch):
    """A KeyboardInterrupt during exception unwind after a confirmed post-exit BrokenPipeError
    must reuse the recorded exit state, still clean up the descendant, and still reap."""
    marker = tmp_path / "unwind_interrupt_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('first-line', flush=True)\n"
        "print('post-exit-line', flush=True)\n"
    )
    orig_print = print
    orig_cleanup = launcher._cleanup_descendant_process_group
    broken_raised = False
    unwind_interrupted = False

    def broken_on_second(*args, **kwargs):
        nonlocal broken_raised
        if args and "post-exit-line" in str(args[0]):
            broken_raised = True
            raise BrokenPipeError("stdout closed during post-exit drain")
        return orig_print(*args, **kwargs)

    def interrupt_once_in_unwind(*args, **kwargs):
        nonlocal unwind_interrupted
        if broken_raised and not unwind_interrupted:
            unwind_interrupted = True
            raise KeyboardInterrupt
        return orig_cleanup(*args, **kwargs)

    monkeypatch.setattr("builtins.print", broken_on_second)
    monkeypatch.setattr(launcher, "_cleanup_descendant_process_group", interrupt_once_in_unwind)
    try:
        with pytest.raises(BrokenPipeError):
            launcher.launch(
                _child(script),
                log_path=tmp_path / "run" / "output.log",
                stream_output=True,
                timeout_seconds=10.0,
            )
        assert broken_raised is True
        assert unwind_interrupted is True
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_double_interrupt_during_post_exit_broken_pipe_unwind_preserves_error_and_reaps(tmp_path, monkeypatch):
    """Two consecutive KeyboardInterrupts during exception unwind must keep retrying inside
    the protected loop, preserve the original BrokenPipeError, clean up descendants, and reap."""
    marker = tmp_path / "double_unwind_interrupt_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('first-line', flush=True)\n"
        "print('post-exit-line', flush=True)\n"
    )
    orig_print = print
    orig_cleanup = launcher._cleanup_descendant_process_group
    broken_raised = False
    interrupt_count = 0

    def broken_on_second(*args, **kwargs):
        nonlocal broken_raised
        if args and "post-exit-line" in str(args[0]):
            broken_raised = True
            raise BrokenPipeError("stdout closed during post-exit drain")
        return orig_print(*args, **kwargs)

    def interrupt_twice_in_unwind(*args, **kwargs):
        nonlocal interrupt_count
        if broken_raised and interrupt_count < 2:
            interrupt_count += 1
            raise KeyboardInterrupt
        return orig_cleanup(*args, **kwargs)

    monkeypatch.setattr("builtins.print", broken_on_second)
    monkeypatch.setattr(launcher, "_cleanup_descendant_process_group", interrupt_twice_in_unwind)
    try:
        with pytest.raises(BrokenPipeError):
            launcher.launch(
                _child(script),
                log_path=tmp_path / "run" / "output.log",
                stream_output=True,
                timeout_seconds=10.0,
            )
        assert broken_raised is True
        assert interrupt_count == 2
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_unleased_timeout_gives_live_executor_grace_to_flush_checkpoint(tmp_path):
    """Unleased timeout cleanup must preserve the 2 s SIGTERM grace for a live executor
    so a handler needing ~450 ms to flush a checkpoint finishes cleanly instead of -9."""
    checkpoint = tmp_path / "checkpoint.txt"
    script = (
        "import signal, sys, time\n"
        "def on_term(*_):\n"
        "    time.sleep(0.45)\n"
        f"    open({str(checkpoint)!r}, 'w').write('flushed')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, on_term)\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    result = launcher.launch(
        _child(script),
        log_path=tmp_path / "run" / "output.log",
        timeout_seconds=0.35,
    )
    assert result.timed_out is True
    assert result.returncode == 0
    assert checkpoint.read_text() == "flushed"
    assert result.cleanup_evidence is not None
    assert result.cleanup_evidence["signals_sent"] == ["SIGTERM"]
    assert result.cleanup_evidence["result"] == "terminated"


def test_leased_timeout_kills_session_detached_worker_via_supervisor(tmp_path):
    """A leased launch timeout must preserve the lease_supervisor's full adopted-descendant
    reap/kill grace window so a start_new_session=True worker is killed and reaped."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux lease_supervisor test")
    import fcntl
    import os
    from types import SimpleNamespace

    marker = tmp_path / "detached_worker.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "worker = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'],\n"
        "    start_new_session=True,\n"
        ")\n"
        "open(marker, 'w').write(str(worker.pid))\n"
        "print('worker-ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    fd = os.open(tmp_path / "lease", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    authority = SimpleNamespace(fileno=lambda: fd, generation="synthetic", identity=None)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.35,
            lease_authority=authority,
        )
        assert result.timed_out is True
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM"]
        assert result.cleanup_evidence["result"] == "terminated"
        worker_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(worker_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(worker_pid)
    finally:
        os.close(fd)
        _kill_pid_best_effort(marker)


def test_normal_exit_past_deadline_still_drains_closed_pipe_and_queued_output(tmp_path, monkeypatch):
    """If a child prints multiple lines and exits normally with closed pipes just as
    timeout_seconds elapses (e.g., during a delayed heartbeat write), post-exit drain must
    keep all queued/buffered lines and report drain_incomplete=False."""
    orig_write_hb = launcher.write_run_heartbeat
    delayed = False

    def slow_heartbeat(path, summary):
        nonlocal delayed
        if not delayed:
            delayed = True
            time.sleep(0.35)
        return orig_write_hb(path, summary)

    monkeypatch.setattr(launcher, "write_run_heartbeat", slow_heartbeat)
    script = (
        "print('line-one', flush=True)\n"
        "print('line-two', flush=True)\n"
    )
    result = launcher.launch(
        _child(script),
        log_path=tmp_path / "run" / "output.log",
        heartbeat_interval_seconds=0.0,
        timeout_seconds=0.2,
    )
    assert result.returncode == 0
    assert result.timed_out is False
    assert result.drain_incomplete is False
    assert result.output.splitlines() == ["line-one", "line-two"]


def test_slow_queued_drain_respects_bounded_flush_deadline(tmp_path, monkeypatch):
    """Queued records must still respect the bounded drain deadline when stream writes are
    slow, rather than draining an entire queue snapshot past timeout_seconds."""
    orig_print = print

    def slow_print(*args, **kwargs):
        time.sleep(0.01)
        return orig_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", slow_print)
    script = (
        "for i in range(220):\n"
        "    print(f'line-{i}', flush=True)\n"
    )
    started = time.monotonic()
    result = launcher.launch(
        _child(script),
        log_path=tmp_path / "run" / "output.log",
        stream_output=True,
        timeout_seconds=0.3,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    assert elapsed < 1.2
    assert result.drain_incomplete is True


def test_fast_exiting_leader_when_getpgid_returns_esrch_still_cleans_up_group(tmp_path, monkeypatch):
    """If getpgid() fails with ESRCH (as on macOS for a fast-exiting unreaped leader
    spawned with start_new_session=True), the launcher must record process.pid as the owned
    PGID and still clean up surviving same-group descendants."""
    marker = tmp_path / "esrch_pgid_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('leader-done', flush=True)\n"
    )
    monkeypatch.setattr(launcher, "_process_group_id", lambda _pid: None)
    try:
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            timeout_seconds=0.8,
        )
        assert result.returncode == 0
        assert result.process_group_id == result.process_pid
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        assert result.cleanup_evidence["result"] == "killed"
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_unterminated_final_line_with_inherited_writer_is_collected_after_cleanup(tmp_path):
    """When a leader writes an unterminated final line and a same-group descendant holds
    stdout open, killing the descendant closes the pipe so the bounded final collection
    captures the partial line in both LaunchResult.output and the log file."""
    marker = tmp_path / "partial_line_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, time\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "sys.stdout.write('first-line\\nfinal-partial')\n"
        "sys.stdout.flush()\n"
    )
    log_path = tmp_path / "run" / "output.log"
    try:
        result = launcher.launch(
            _child(script),
            log_path=log_path,
            timeout_seconds=0.8,
        )
        assert result.returncode == 0
        assert result.drain_incomplete is True
        assert result.cleanup_evidence is not None
        assert "final-partial" in result.output
        assert "final-partial" in log_path.read_text(encoding="utf-8")
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        _kill_pid_best_effort(marker)


def test_single_blocked_drain_write_respects_deadline_and_cleans_up_descendant(tmp_path, monkeypatch):
    """A single blocked output write during post-exit drain must not overrun the drain
    deadline or delay descendant process-group cleanup."""
    marker = tmp_path / "blocked_write_grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "child_code = (\n"
        "    'import os, signal, time\\n'\n"
        "    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n'\n"
        "    f'open({marker!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'time.sleep(30)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(marker) or os.path.getsize(marker) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('post-exit-blocked', flush=True)\n"
    )
    orig_print = print
    orig_no_reap = launcher._child_exited_no_reap
    leader_observed_exited = False
    release_block = threading.Event()
    blocked_entered = threading.Event()

    def tracking_no_reap(proc):
        nonlocal leader_observed_exited
        exited, unreaped = orig_no_reap(proc)
        if exited:
            leader_observed_exited = True
        return exited, unreaped

    def blocking_print(*args, **kwargs):
        if args and "post-exit-blocked" in str(args[0]) and leader_observed_exited:
            blocked_entered.set()
            release_block.wait(timeout=3.0)
        return orig_print(*args, **kwargs)

    # Hold the line in the queue until leader exit is observed so the blocked write
    # definitely occurs inside post-exit drain rather than the main polling loop.
    orig_get = launcher.Queue.get

    def hold_until_exit(self, *args, **kwargs):
        if not leader_observed_exited:
            raise launcher.Empty
        return orig_get(self, *args, **kwargs)

    monkeypatch.setattr(launcher, "_child_exited_no_reap", tracking_no_reap)
    monkeypatch.setattr(launcher.Queue, "get", hold_until_exit)
    monkeypatch.setattr("builtins.print", blocking_print)
    try:
        started = time.monotonic()
        result = launcher.launch(
            _child(script),
            log_path=tmp_path / "run" / "output.log",
            stream_output=True,
            timeout_seconds=0.35,
        )
        elapsed = time.monotonic() - started
        assert blocked_entered.is_set()
        assert result.returncode == 0
        assert result.drain_incomplete is True
        assert elapsed < 1.0
        assert result.cleanup_evidence is not None
        assert result.cleanup_evidence["signals_sent"] == ["SIGTERM", "SIGKILL"]
        grandchild_pid = int(marker.read_text().strip())
        deadline = time.monotonic() + 1.0
        while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _proc_alive(grandchild_pid)
    finally:
        release_block.set()
        _kill_pid_best_effort(marker)


def test_writer_closing_at_drain_boundary_still_collects_final_partial_line(tmp_path, monkeypatch):
    """If the initial post-exit drain expires and an inherited pipe writer closes on its own
    before descendant cleanup runs (so no signal is sent), a bounded final collection must
    still capture the final unterminated partial line in output and the log."""
    close_trigger = tmp_path / "close_writer.flag"
    ready_flag = tmp_path / "writer_ready.flag"
    script = (
        "import os, subprocess, sys, time\n"
        f"ready_flag = {str(ready_flag)!r}\n"
        f"close_trigger = {str(close_trigger)!r}\n"
        "child_code = (\n"
        "    'import os, time\\n'\n"
        "    f'open({ready_flag!r}, \"w\").write(str(os.getpid()))\\n'\n"
        "    'deadline = time.monotonic() + 5.0\\n'\n"
        "    f'while not os.path.exists({close_trigger!r}) and time.monotonic() < deadline:\\n'\n"
        "    '    time.sleep(0.005)\\n'\n"
        ")\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        "deadline = time.monotonic() + 5.0\n"
        "while (not os.path.exists(ready_flag) or os.path.getsize(ready_flag) == 0) and time.monotonic() < deadline:\n"
        "    time.sleep(0.005)\n"
        "sys.stdout.write('first-line\\nboundary-partial')\n"
        "sys.stdout.flush()\n"
    )
    orig_writers_closed = launcher._pipe_writers_closed
    checks = 0

    def close_before_cleanup_check(pipe):
        nonlocal checks
        checks += 1
        # Check 1 runs right before drain_plain() (writers_closed_before_drain) and check 2
        # runs in post_exit_deadline(); both see the inherited writer open. On check 3 (the
        # post-drain cleanup guard), release the writer and wait briefly for it to close so
        # cleanup sees pipe_writers_all_closed() == True and skips signaling.
        if checks >= 3 and not close_trigger.exists():
            close_trigger.write_text("close", encoding="utf-8")
            deadline = time.monotonic() + 1.0
            while not orig_writers_closed(pipe) and time.monotonic() < deadline:
                time.sleep(0.005)
        return orig_writers_closed(pipe)

    monkeypatch.setattr(launcher, "_pipe_writers_closed", close_before_cleanup_check)
    log_path = tmp_path / "run" / "output.log"
    try:
        result = launcher.launch(
            _child(script),
            log_path=log_path,
            timeout_seconds=0.35,
        )
        assert result.returncode == 0
        assert result.cleanup_evidence is None
        assert result.drain_incomplete is True
        assert "boundary-partial" in result.output
        assert "boundary-partial" in log_path.read_text(encoding="utf-8")
    finally:
        close_trigger.write_text("close", encoding="utf-8")
        _kill_pid_best_effort(ready_flag)


def test_real_full_stdout_pipe_bounds_drain_and_exits_cleanly_without_abort(tmp_path):
    """On a real full OS stdout pipe, live streaming must not block exit detection, drop
    captured output/log lines, block quiet heartbeat timeout cleanup, or leave sys.stdout's
    BufferedWriter lock held."""
    import fcntl
    import json
    import os
    import select
    import subprocess

    report_path = tmp_path / "report.json"
    log_path = tmp_path / "run" / "output.log"
    hb_path = tmp_path / "run" / "heartbeat.json"
    driver = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "from phase_loop_runtime import launcher\n"
        f"log_path = Path({str(log_path)!r})\n"
        f"hb_path = Path({str(hb_path)!r})\n"
        f"report_path = Path({str(report_path)!r})\n"
        "# Scenario 1: child prints first, waits 100ms, prints last, exits with 1.5s budget.\n"
        "child1 = [sys.executable, '-c', \"import time; print('first', flush=True); time.sleep(0.1); print('last', flush=True)\"]\n"
        "t0 = time.monotonic()\n"
        "res1 = launcher.launch(child1, log_path=log_path, stream_output=True, timeout_seconds=1.5)\n"
        "el1 = time.monotonic() - t0\n"
        "# Scenario 2: quiet child with heartbeat emission and 0.25s timeout.\n"
        "child2 = [sys.executable, '-c', 'import time; time.sleep(30)']\n"
        "t1 = time.monotonic()\n"
        "res2 = launcher.launch(child2, log_path=log_path.with_name('quiet.log'), heartbeat_path=hb_path, heartbeat_interval_seconds=0.05, quiet_warning_seconds=0.0, quiet_blocker_seconds=10.0, stream_output=True, timeout_seconds=0.25)\n"
        "el2 = time.monotonic() - t1\n"
        "report_path.write_text(json.dumps({\n"
        "    'rc1': res1.returncode,\n"
        "    'out1': res1.output,\n"
        "    'log1': log_path.read_text(encoding='utf-8'),\n"
        "    'drain1': res1.drain_incomplete,\n"
        "    'el1': el1,\n"
        "    'timed_out2': res2.timed_out,\n"
        "    'el2': el2,\n"
        "}), encoding='utf-8')\n"
        "print('summary-after-launch', flush=True)\n"
    )
    read_fd, write_fd = os.pipe()
    try:
        # Fill the pipe buffer completely so any blocking write to stdout would stall.
        flags = fcntl.fcntl(write_fd, fcntl.F_GETFL)
        fcntl.fcntl(write_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        filled = 0
        try:
            while True:
                filled += os.write(write_fd, b"Z" * 4096)
        except BlockingIOError:
            pass
        assert filled > 0
        fcntl.fcntl(write_fd, fcntl.F_SETFL, flags)

        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        proc = subprocess.Popen(
            [sys.executable, "-c", driver],
            stdout=write_fd,
            stderr=subprocess.PIPE,
            env=env,
        )
        os.close(write_fd)
        write_fd = -1

        # Wait until BOTH launches finish and write their report while stdout pipe is STILL FULL.
        deadline = time.monotonic() + 3.0
        while not report_path.exists() and time.monotonic() < deadline:
            assert proc.poll() is None, proc.stderr.read().decode(errors="replace")
            time.sleep(0.02)
        assert report_path.exists(), "launch() remained blocked on the full stdout pipe"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["rc1"] == 0
        assert report["drain1"] is False
        assert report["out1"].splitlines() == ["first", "last"]
        assert report["log1"].splitlines() == ["first", "last"]
        assert report["el1"] < 0.9
        assert report["timed_out2"] is True
        assert report["el2"] < 1.2

        # Now drain the pipe so the driver's post-launch print() and interpreter shutdown finish.
        chunks = []
        rflags = fcntl.fcntl(read_fd, fcntl.F_GETFL)
        fcntl.fcntl(read_fd, fcntl.F_SETFL, rflags | os.O_NONBLOCK)
        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            ready, _, _ = select.select([read_fd], [], [], 0.05)
            if ready:
                data = os.read(read_fd, 65536)
                if not data:
                    break
                chunks.append(data)
            elif proc.poll() is not None:
                break
        rc = proc.wait(timeout=3.0)
        stderr_text = proc.stderr.read().decode(errors="replace")
        assert rc == 0, f"process exited {rc}: {stderr_text}"
        assert b"summary-after-launch" in b"".join(chunks)
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def test_prebuffered_stdout_with_4k_pipe_does_not_block_on_flush(tmp_path):
    """If the caller already has >4 KiB buffered in Python's sys.stdout over an empty 4 KiB
    OS pipe, live streaming must not call sys.stdout.flush() and block past the deadline."""
    import fcntl
    import json
    import os
    import select
    import subprocess

    if not sys.platform.startswith("linux") or not hasattr(fcntl, "F_SETPIPE_SZ"):
        pytest.skip("Linux F_SETPIPE_SZ test")
    report_path = tmp_path / "prebuf_report.json"
    driver = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from phase_loop_runtime import launcher\n"
        "sys.stdout.write('B' * 6000)\n"
        "t0 = time.monotonic()\n"
        f"res = launcher.launch([sys.executable, '-c', \"print('ok-line', flush=True)\"], log_path=Path({str(tmp_path / 'prebuf.log')!r}), stream_output=True, timeout_seconds=0.25)\n"
        "el = time.monotonic() - t0\n"
        f"Path({str(report_path)!r}).write_text(json.dumps({{'rc': res.returncode, 'out': res.output, 'el': el}}), encoding='utf-8')\n"
    )
    read_fd, write_fd = os.pipe()
    try:
        fcntl.fcntl(write_fd, fcntl.F_SETPIPE_SZ, 4096)
        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        proc = subprocess.Popen(
            [sys.executable, "-c", driver],
            stdout=write_fd,
            stderr=subprocess.PIPE,
            env=env,
        )
        os.close(write_fd)
        write_fd = -1

        deadline = time.monotonic() + 3.0
        while not report_path.exists() and time.monotonic() < deadline:
            assert proc.poll() is None, proc.stderr.read().decode(errors="replace")
            time.sleep(0.02)
        assert report_path.exists(), "launch() blocked flushing pre-buffered sys.stdout"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["rc"] == 0
        assert "ok-line" in report["out"]
        assert report["el"] < 0.8

        rflags = fcntl.fcntl(read_fd, fcntl.F_GETFL)
        fcntl.fcntl(read_fd, fcntl.F_SETFL, rflags | os.O_NONBLOCK)
        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            ready, _, _ = select.select([read_fd], [], [], 0.05)
            if ready:
                if not os.read(read_fd, 65536):
                    break
            elif proc.poll() is not None:
                break
        assert proc.wait(timeout=3.0) == 0, proc.stderr.read().decode(errors="replace")
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def test_stream_output_handles_high_numbered_stdout_pipe_fd(tmp_path):
    """Live streaming on a writable stdout pipe with fd >= 1024 must use poll() rather
    than select.select() so FD_SETSIZE does not raise ValueError."""
    import os
    import resource
    import subprocess

    soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft <= 1025:
        pytest.skip("RLIMIT_NOFILE too low for fd >= 1024 probe")
    driver = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from phase_loop_runtime import launcher\n"
        "r_fd, w_fd = os.pipe()\n"
        "os.dup2(w_fd, 1024)\n"
        "os.close(w_fd)\n"
        "old_stdout = sys.stdout\n"
        "sys.stdout = os.fdopen(1024, 'w', encoding='utf-8')\n"
        "try:\n"
        f"    res = launcher.launch([sys.executable, '-c', \"print('high-fd-ok', flush=True)\"], log_path=Path({str(tmp_path / 'hi.log')!r}), stream_output=True, timeout_seconds=5.0)\n"
        "    assert res.returncode == 0\n"
        "    assert 'high-fd-ok' in res.output\n"
        "    assert b'high-fd-ok' in os.read(r_fd, 4096)\n"
        "finally:\n"
        "    sys.stdout.close()\n"
        "    sys.stdout = old_stdout\n"
        "    os.close(r_fd)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    completed = subprocess.run([sys.executable, "-c", driver], env=env, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr


def test_competing_stdout_writer_and_temporary_backpressure_resume(tmp_path):
    """(1) If a competing writer fills a 4 KiB stdout pipe right between readiness check
    and os.write(), non-blocking write catches BlockingIOError without defeating the launch
    deadline and restores blocking mode. (2) After temporary backpressure clears, live
    streaming resumes for subsequent records."""
    import fcntl
    import json
    import os
    import select
    import subprocess

    if not sys.platform.startswith("linux") or not hasattr(fcntl, "F_SETPIPE_SZ"):
        pytest.skip("Linux F_SETPIPE_SZ test")

    # Part 1: competing writer fills pipe between readiness poll and os.write().
    report1 = tmp_path / "competing.json"
    driver1 = (
        "import fcntl, json, os, sys, time\n"
        "from pathlib import Path\n"
        "from phase_loop_runtime import launcher\n"
        "orig_write = os.write\n"
        "stdout_fd = sys.stdout.fileno()\n"
        "filled_once = False\n"
        "def competing_write(fd, data):\n"
        "    global filled_once\n"
        "    if fd == stdout_fd and not filled_once:\n"
        "        filled_once = True\n"
        "        # Fill the 4 KiB pipe right before launcher's own non-blocking os.write().\n"
        "        try:\n"
        "            while True:\n"
        "                orig_write(fd, b'C' * 4096)\n"
        "        except BlockingIOError:\n"
        "            pass\n"
        "    return orig_write(fd, data)\n"
        "os.write = competing_write\n"
        "t0 = time.monotonic()\n"
        f"res = launcher.launch([sys.executable, '-c', \"print('raced-line', flush=True)\"], log_path=Path({str(tmp_path / 'race.log')!r}), stream_output=True, timeout_seconds=0.2)\n"
        "el = time.monotonic() - t0\n"
        f"Path({str(report1)!r}).write_text(json.dumps({{'rc': res.returncode, 'out': res.output, 'el': el, 'blocking': os.get_blocking(stdout_fd), 'filled': filled_once}}), encoding='utf-8')\n"
    )
    r1, w1 = os.pipe()
    try:
        fcntl.fcntl(w1, fcntl.F_SETPIPE_SZ, 4096)
        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        p1 = subprocess.Popen([sys.executable, "-c", driver1], stdout=w1, stderr=subprocess.PIPE, env=env)
        os.close(w1)
        w1 = -1
        deadline = time.monotonic() + 2.0
        while not report1.exists() and time.monotonic() < deadline:
            assert p1.poll() is None, p1.stderr.read().decode(errors="replace")
            time.sleep(0.01)
        assert report1.exists(), "launch() blocked after competing writer filled pipe"
        data1 = json.loads(report1.read_text(encoding="utf-8"))
        assert data1["filled"] is True
        assert data1["rc"] == 0
        assert "raced-line" in data1["out"]
        assert data1["el"] < 0.7
        assert data1["blocking"] is True
        # Drain pipe so process exits cleanly.
        rflags = fcntl.fcntl(r1, fcntl.F_GETFL)
        fcntl.fcntl(r1, fcntl.F_SETFL, rflags | os.O_NONBLOCK)
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            ready, _, _ = select.select([r1], [], [], 0.05)
            if ready:
                if not os.read(r1, 65536):
                    break
            elif p1.poll() is not None:
                break
        assert p1.wait(timeout=2.0) == 0, p1.stderr.read().decode(errors="replace")
    finally:
        os.close(r1)
        if w1 >= 0:
            os.close(w1)

    # Part 2: temporary backpressure clears before 'last' -> live display resumes!
    # Synchronize on the rejected stdout readiness check (not log flush) before draining.
    backpressured_flag = tmp_path / "first_backpressured.flag"
    release_last = tmp_path / "release_last.flag"
    log2 = tmp_path / "resume.log"
    driver2 = (
        "import os, select, sys, time\n"
        "from pathlib import Path\n"
        "from phase_loop_runtime import launcher\n"
        f"log2 = Path({str(log2)!r})\n"
        f"backpressured_flag = Path({str(backpressured_flag)!r})\n"
        f"release_last = {str(release_last)!r}\n"
        "stdout_fd = sys.stdout.fileno()\n"
        "orig_poll_cls = select.poll\n"
        "class SpyPoll:\n"
        "    def __init__(self):\n"
        "        self._p = orig_poll_cls()\n"
        "        self._watching_stdout = False\n"
        "    def register(self, fd, eventmask):\n"
        "        if fd == stdout_fd and (eventmask & select.POLLOUT):\n"
        "            self._watching_stdout = True\n"
        "        return self._p.register(fd, eventmask)\n"
        "    def poll(self, timeout=None):\n"
        "        events = self._p.poll(timeout)\n"
        "        if self._watching_stdout and not events and not backpressured_flag.exists():\n"
        "            backpressured_flag.write_text('rejected', encoding='utf-8')\n"
        "        return events\n"
        "select.poll = SpyPoll\n"
        "child_script = (\n"
        "    'import os, time\\n'\n"
        "    'print(\"first\", flush=True)\\n'\n"
        "    'deadline = time.monotonic() + 5.0\\n'\n"
        "    f'while not os.path.exists({release_last!r}) and time.monotonic() < deadline:\\n'\n"
        "    '    time.sleep(0.01)\\n'\n"
        "    'print(\"last\", flush=True)\\n'\n"
        ")\n"
        "res = launcher.launch([sys.executable, '-c', child_script], log_path=log2, stream_output=True, timeout_seconds=5.0)\n"
        "assert res.returncode == 0\n"
        "assert res.output.splitlines() == ['first', 'last']\n"
    )
    r2, w2 = os.pipe()
    try:
        # Fill pipe completely so 'first' hits backpressure.
        fl2 = fcntl.fcntl(w2, fcntl.F_GETFL)
        fcntl.fcntl(w2, fcntl.F_SETFL, fl2 | os.O_NONBLOCK)
        try:
            while True:
                os.write(w2, b"Z" * 4096)
        except BlockingIOError:
            pass
        fcntl.fcntl(w2, fcntl.F_SETFL, fl2)

        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        p2 = subprocess.Popen([sys.executable, "-c", driver2], stdout=w2, stderr=subprocess.PIPE, env=env)
        os.close(w2)
        w2 = -1

        # Wait until stdout readiness check ACTUALLY rejected 'first' under backpressure.
        deadline = time.monotonic() + 3.0
        while not backpressured_flag.exists() and time.monotonic() < deadline:
            assert p2.poll() is None, p2.stderr.read().decode(errors="replace")
            time.sleep(0.01)
        assert backpressured_flag.exists(), "first record did not hit stdout backpressure"

        # Drain the pipe completely, then release the child to print 'last'.
        rflags = fcntl.fcntl(r2, fcntl.F_GETFL)
        fcntl.fcntl(r2, fcntl.F_SETFL, rflags | os.O_NONBLOCK)
        drained_initial = b""
        while True:
            try:
                chunk = os.read(r2, 65536)
                if not chunk:
                    break
                drained_initial += chunk
            except BlockingIOError:
                break
        assert len(drained_initial) > 0
        release_last.write_text("go", encoding="utf-8")

        resumed_chunks = []
        end = time.monotonic() + 3.0
        while time.monotonic() < end:
            ready, _, _ = select.select([r2], [], [], 0.05)
            if ready:
                chunk = os.read(r2, 65536)
                if not chunk:
                    break
                resumed_chunks.append(chunk)
            elif p2.poll() is not None:
                break
        assert p2.wait(timeout=3.0) == 0, p2.stderr.read().decode(errors="replace")
        resumed = b"".join(resumed_chunks)
        assert b"first" not in resumed
        assert b"last" in resumed
    finally:
        release_last.write_text("go", encoding="utf-8")
        os.close(r2)
        if w2 >= 0:
            os.close(w2)

    # Part 3: while launch 1 is paused inside os.write() holding the live stdout lock,
    # launch 2 finishes within its 0.15 s budget without waiting on launch 1 or racing on
    # fd blocking mode, and Ctrl-C right after os.set_blocking(False) still restores blocking.
    report3 = tmp_path / "concurrent.json"
    driver3 = (
        "import json, os, signal, sys, threading, time\n"
        "from pathlib import Path\n"
        "from phase_loop_runtime import launcher\n"
        "stdout_fd = sys.stdout.fileno()\n"
        "orig_write = os.write\n"
        "t1_in_write = threading.Event()\n"
        "t2_done = threading.Event()\n"
        "t1_tid = None\n"
        "t2_saw_write = False\n"
        "def spy_write(fd, data):\n"
        "    global t2_saw_write\n"
        "    if fd == stdout_fd:\n"
        "        if threading.get_ident() == t1_tid and not t1_in_write.is_set():\n"
        "            t1_in_write.set()\n"
        "            t2_done.wait(timeout=2.0)\n"
        "        elif threading.get_ident() != t1_tid:\n"
        "            t2_saw_write = True\n"
        "    return orig_write(fd, data)\n"
        "os.write = spy_write\n"
        "results = {}\n"
        "def run_t1():\n"
        "    global t1_tid\n"
        "    t1_tid = threading.get_ident()\n"
        f"    res = launcher.launch([sys.executable, '-c', \"print('A' * 1024, flush=True)\"], log_path=Path({str(tmp_path)!r}) / 't1.log', stream_output=True, timeout_seconds=5.0)\n"
        "    results['t1'] = (res.returncode, len(res.output))\n"
        "def run_t2():\n"
        "    t0 = time.monotonic()\n"
        f"    res = launcher.launch([sys.executable, '-c', \"print('B' * 64, flush=True)\"], log_path=Path({str(tmp_path)!r}) / 't2.log', stream_output=True, timeout_seconds=0.15)\n"
        "    results['t2'] = (res.returncode, time.monotonic() - t0, res.output.strip())\n"
        "    t2_done.set()\n"
        "th1 = threading.Thread(target=run_t1)\n"
        "th1.start()\n"
        "assert t1_in_write.wait(timeout=2.0)\n"
        "th2 = threading.Thread(target=run_t2)\n"
        "th2.start()\n"
        "assert t2_done.wait(timeout=2.0)\n"
        "th2.join(timeout=2.0)\n"
        "th1.join(timeout=2.0)\n"
        "os.write = orig_write\n"
        "# Also verify all three Ctrl-C interrupt windows on a fresh writable pipe:\n"
        "# (a) right after os.set_blocking(fd, False),\n"
        "# (b) right after _LIVE_STDOUT_LOCK.acquire(blocking=False),\n"
        "# (c) during os.set_blocking(fd, True) restoration.\n"
        "cr, cw = os.pipe()\n"
        "old_stdout = sys.stdout\n"
        "sys.stdout = os.fdopen(cw, 'w', encoding='utf-8')\n"
        "orig_set_blocking = os.set_blocking\n"
        "interrupted_set = False\n"
        "interrupted_acq = False\n"
        "interrupted_restore = False\n"
        "def drain_pipe_nb(fd):\n"
        "    out = bytearray()\n"
        "    os.set_blocking(fd, False)\n"
        "    try:\n"
        "        while True:\n"
        "            try:\n"
        "                chunk = os.read(fd, 65536)\n"
        "            except BlockingIOError:\n"
        "                break\n"
        "            if not chunk:\n"
        "                break\n"
        "            out.extend(chunk)\n"
        "    finally:\n"
        "        os.set_blocking(fd, True)\n"
        "    return out.decode('utf-8', errors='replace')\n"
        "def lock_is_free_from_other_thread():\n"
        "    ok_box = []\n"
        "    def probe():\n"
        "        ok = launcher._LIVE_STDOUT_LOCK.acquire(blocking=False)\n"
        "        ok_box.append(ok)\n"
        "        if ok:\n"
        "            launcher._LIVE_STDOUT_LOCK.release()\n"
        "    th = threading.Thread(target=probe)\n"
        "    th.start()\n"
        "    th.join(timeout=2.0)\n"
        "    return ok_box == [True]\n"
        "def interrupt_after_nonblock(fd, flag):\n"
        "    global interrupted_set\n"
        "    orig_set_blocking(fd, flag)\n"
        "    if fd == cw and flag is False and not interrupted_set:\n"
        "        interrupted_set = True\n"
        "        raise KeyboardInterrupt\n"
        "os.set_blocking = interrupt_after_nonblock\n"
        "try:\n"
        f"    res_int = launcher.launch([sys.executable, '-c', \"print('ctrlc-line', flush=True)\"], log_path=Path({str(tmp_path)!r}) / 'ctrlc.log', stream_output=True, timeout_seconds=2.0)\n"
        "    restored_ctrlc = os.get_blocking(cw) and lock_is_free_from_other_thread()\n"
        "    os.set_blocking = orig_set_blocking\n"
        "    # (b) Real SIGINT delivered at the exact C-return boundary of _LIVE_STDOUT_LOCK.acquire(blocking=False)\n"
        "    def profile_acquire_c_return(frame, event, arg):\n"
        "        global interrupted_acq\n"
        "        if (\n"
        "            event == 'c_return'\n"
        "            and not interrupted_acq\n"
        "            and frame.f_code.co_name == '_stream_live_text'\n"
        "            and getattr(arg, '__name__', None) == 'acquire'\n"
        "        ):\n"
        "            interrupted_acq = True\n"
        "            sys.setprofile(None)\n"
        "            os.kill(os.getpid(), signal.SIGINT)\n"
        "    sys.setprofile(profile_acquire_c_return)\n"
        "    try:\n"
        f"        res_int_acq = launcher.launch([sys.executable, '-c', \"print('acq-line', flush=True)\"], log_path=Path({str(tmp_path)!r}) / 'ctrlc_acq.log', stream_output=True, timeout_seconds=2.0)\n"
        "    finally:\n"
        "        sys.setprofile(None)\n"
        "    lock_free_after_acq = lock_is_free_from_other_thread()\n"
        "    drain_pipe_nb(cr)\n"
        f"    res_after_acq = launcher.launch([sys.executable, '-c', \"print('after-acq-ok', flush=True)\"], log_path=Path({str(tmp_path)!r}) / 'after_acq.log', stream_output=True, timeout_seconds=2.0)\n"
        "    displayed_after_acq = drain_pipe_nb(cr)\n"
        "    # (c) Ctrl-C during os.set_blocking(fd, True) restoration\n"
        "    def interrupt_during_restore(fd, flag):\n"
        "        global interrupted_restore\n"
        "        if fd == cw and flag is True and not interrupted_restore:\n"
        "            interrupted_restore = True\n"
        "            raise KeyboardInterrupt\n"
        "        orig_set_blocking(fd, flag)\n"
        "    os.set_blocking = interrupt_during_restore\n"
        "    try:\n"
        f"        res_int_restore = launcher.launch([sys.executable, '-c', \"print('restore-line', flush=True)\"], log_path=Path({str(tmp_path)!r}) / 'ctrlc_restore.log', stream_output=True, timeout_seconds=2.0)\n"
        "    finally:\n"
        "        os.set_blocking = orig_set_blocking\n"
        "    restored_after_restore_int = os.get_blocking(cw) and lock_is_free_from_other_thread()\n"
        "    drain_pipe_nb(cr)\n"
        f"    res_after_restore = launcher.launch([sys.executable, '-c', \"print('after-restore-ok', flush=True)\"], log_path=Path({str(tmp_path)!r}) / 'after_restore.log', stream_output=True, timeout_seconds=2.0)\n"
        "    displayed_after_restore = drain_pipe_nb(cr)\n"
        "finally:\n"
        "    sys.setprofile(None)\n"
        "    os.set_blocking = orig_set_blocking\n"
        "    sys.stdout.close()\n"
        "    sys.stdout = old_stdout\n"
        "    os.close(cr)\n"
        f"Path({str(report3)!r}).write_text(json.dumps({{'results': results, 't2_saw_write': t2_saw_write, 'interrupted_set': interrupted_set, 'res_int_interrupted': res_int.interrupted, 'interrupted_acq': interrupted_acq, 'res_int_acq_interrupted': res_int_acq.interrupted, 'lock_free_after_acq': lock_free_after_acq, 'displayed_after_acq': displayed_after_acq, 'interrupted_restore': interrupted_restore, 'res_int_restore_interrupted': res_int_restore.interrupted, 'restored_after_restore_int': restored_after_restore_int, 'displayed_after_restore': displayed_after_restore, 'restored_blocking': os.get_blocking(stdout_fd) and restored_ctrlc}}), encoding='utf-8')\n"
    )
    r3, w3 = os.pipe()
    try:
        fcntl.fcntl(w3, fcntl.F_SETPIPE_SZ, 4096)
        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        p3 = subprocess.Popen([sys.executable, "-c", driver3], stdout=w3, stderr=subprocess.PIPE, env=env)
        os.close(w3)
        w3 = -1
        deadline = time.monotonic() + 6.0
        while not report3.exists() and time.monotonic() < deadline:
            assert p3.poll() is None, p3.stderr.read().decode(errors="replace")
            time.sleep(0.01)
        assert report3.exists(), "concurrent launch blocked on shared 4 KiB stdout pipe"
        data3 = json.loads(report3.read_text(encoding="utf-8"))
        assert data3["results"]["t1"][0] == 0
        assert data3["results"]["t2"][0] == 0
        assert data3["results"]["t2"][1] < 0.8
        assert data3["results"]["t2"][2] == "B" * 64
        assert data3["t2_saw_write"] is False
        assert data3["interrupted_set"] is True
        assert data3["res_int_interrupted"] is True
        assert data3["interrupted_acq"] is True
        assert data3["res_int_acq_interrupted"] is True
        assert data3["lock_free_after_acq"] is True
        assert "after-acq-ok" in data3["displayed_after_acq"]
        assert data3["interrupted_restore"] is True
        assert data3["res_int_restore_interrupted"] is True
        assert data3["restored_after_restore_int"] is True
        assert "after-restore-ok" in data3["displayed_after_restore"]
        assert data3["restored_blocking"] is True
        rflags = fcntl.fcntl(r3, fcntl.F_GETFL)
        fcntl.fcntl(r3, fcntl.F_SETFL, rflags | os.O_NONBLOCK)
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            ready, _, _ = select.select([r3], [], [], 0.05)
            if ready:
                if not os.read(r3, 65536):
                    break
            elif p3.poll() is not None:
                break
        assert p3.wait(timeout=2.0) == 0, p3.stderr.read().decode(errors="replace")
    finally:
        os.close(r3)
        if w3 >= 0:
            os.close(w3)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipe stdout test")
def test_live_stdout_streaming_stops_when_deadline_expires_between_chunks(tmp_path):
    """Deterministic fake-clock test: synchronize on leader exit, continuously drain a
    4 KiB stdout pipe so the sink stays writable after chunk 1, and verify that expiring
    the post-exit deadline after chunk 1 stops live streaming while full output is captured."""
    import fcntl
    import json
    import os

    report = tmp_path / "chunk_deadline.json"
    log_path = tmp_path / "chunk_deadline.log"
    driver = (
        "import json, os, select, subprocess, sys, threading, time\n"
        "from pathlib import Path\n"
        "from phase_loop_runtime import launcher\n"
        "stdout_fd = sys.stdout.fileno()\n"
        "real_monotonic = time.monotonic\n"
        "clock_offset = 0.0\n"
        "def fake_monotonic():\n"
        "    return real_monotonic() + clock_offset\n"
        "time.monotonic = fake_monotonic\n"
        "orig_popen = launcher.subprocess.Popen\n"
        "child_proc = None\n"
        "def spy_popen(*args, **kwargs):\n"
        "    global child_proc\n"
        "    child_proc = orig_popen(*args, **kwargs)\n"
        "    return child_proc\n"
        "launcher.subprocess.Popen = spy_popen\n"
        "orig_write = os.write\n"
        "chunk_writes = 0\n"
        "writable_after_chunk1 = False\n"
        "def advancing_write(fd, data):\n"
        "    global clock_offset, chunk_writes, writable_after_chunk1\n"
        "    n = orig_write(fd, data)\n"
        "    if fd == stdout_fd:\n"
        "        chunk_writes += 1\n"
        "        if chunk_writes == 1:\n"
        "            # Wait until the parent reader drains chunk 1 so stdout_fd is provably\n"
        "            # writable again before expiring the deadline; without the per-chunk\n"
        "            # deadline guard, chunks 2 and 3 would also be written.\n"
        "            poller = select.poll()\n"
        "            poller.register(stdout_fd, select.POLLOUT)\n"
        "            writable_after_chunk1 = bool(poller.poll(2000))\n"
        "            clock_offset += 5.0\n"
        "    return n\n"
        "os.write = advancing_write\n"
        "orig_get = launcher.Queue.get\n"
        "first_get = True\n"
        "def sync_after_leader_exit(self, *args, **kwargs):\n"
        "    global first_get\n"
        "    if first_get:\n"
        "        first_get = False\n"
        "        assert child_proc is not None\n"
        "        child_proc.wait(timeout=5.0)\n"
        "    return orig_get(self, *args, **kwargs)\n"
        "launcher.Queue.get = sync_after_leader_exit\n"
        "payload_len = 3 * launcher._STREAM_CHUNK_BYTES\n"
        "try:\n"
        f"    res = launcher.launch([sys.executable, '-c', f\"print('X' * {{payload_len}}, flush=True)\"], log_path=Path({str(log_path)!r}), stream_output=True, timeout_seconds=1.0)\n"
        "finally:\n"
        "    os.write = orig_write\n"
        "    time.monotonic = real_monotonic\n"
        "    launcher.Queue.get = orig_get\n"
        "    launcher.subprocess.Popen = orig_popen\n"
        "lock_free_box = []\n"
        "def check_lock():\n"
        "    ok = launcher._LIVE_STDOUT_LOCK.acquire(blocking=False)\n"
        "    lock_free_box.append(ok)\n"
        "    if ok:\n"
        "        launcher._LIVE_STDOUT_LOCK.release()\n"
        "th = threading.Thread(target=check_lock)\n"
        "th.start(); th.join(timeout=2.0)\n"
        f"Path({str(report)!r}).write_text(json.dumps({{'returncode': res.returncode, 'chunk_writes': chunk_writes, 'writable_after_chunk1': writable_after_chunk1, 'output_len': len(res.output.strip()), 'log_len': len(Path({str(log_path)!r}).read_text(encoding='utf-8').strip()), 'lock_free': lock_free_box == [True], 'blocking': os.get_blocking(stdout_fd), 'chunk_bytes': launcher._STREAM_CHUNK_BYTES}}), encoding='utf-8')\n"
    )
    r, w = os.pipe()
    displayed = bytearray()
    def _drain_reader():
        while True:
            chunk = os.read(r, 65536)
            if not chunk:
                break
            displayed.extend(chunk)
    reader = threading.Thread(target=_drain_reader, daemon=True)
    try:
        fcntl.fcntl(w, fcntl.F_SETPIPE_SZ, 4096)
        reader.start()
        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        proc = subprocess.Popen([sys.executable, "-c", driver], stdout=w, stderr=subprocess.PIPE, env=env)
        os.close(w)
        w = -1
        assert proc.wait(timeout=5.0) == 0, proc.stderr.read().decode(errors="replace")
        reader.join(timeout=2.0)
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["returncode"] == 0
        assert data["writable_after_chunk1"] is True
        assert data["chunk_writes"] == 1
        assert len(displayed) == data["chunk_bytes"]
        assert data["output_len"] == 3 * data["chunk_bytes"]
        assert data["log_len"] == 3 * data["chunk_bytes"]
        assert data["lock_free"] is True
        assert data["blocking"] is True
    finally:
        if w >= 0:
            os.close(w)
        reader.join(timeout=1.0)
        os.close(r)


def test_first_record_dequeued_after_leader_exit_uses_bounded_drain(tmp_path, monkeypatch):
    """If the leader has already exited when the main loop dequeues a record from line_queue,
    that record must go through the bounded post-exit drain rather than an unbounded sync write."""
    orig_print = print
    release = threading.Event()
    blocked = threading.Event()

    def slow_first_print(*args, **kwargs):
        if args and "first-after-exit" in str(args[0]):
            blocked.set()
            release.wait(timeout=3.0)
        return orig_print(*args, **kwargs)

    # Delay the very first line_queue.get just long enough for the fast leader to exit.
    orig_get = launcher.Queue.get
    first = True

    def delayed_first_get(self, *args, **kwargs):
        nonlocal first
        if first:
            first = False
            time.sleep(0.08)
        return orig_get(self, *args, **kwargs)

    monkeypatch.setattr("builtins.print", slow_first_print)
    monkeypatch.setattr(launcher.Queue, "get", delayed_first_get)
    try:
        started = time.monotonic()
        result = launcher.launch(
            _child("print('first-after-exit', flush=True)\n"),
            log_path=tmp_path / "run" / "output.log",
            stream_output=True,
            timeout_seconds=0.25,
        )
        elapsed = time.monotonic() - started
        assert blocked.is_set()
        assert result.returncode == 0
        assert result.drain_incomplete is True
        assert elapsed < 1.0
    finally:
        release.set()


def test_interrupt_right_after_sink_submission_preserves_incomplete_drain(tmp_path, monkeypatch):
    """A KeyboardInterrupt firing immediately after sink_queue.put() must mark sink_stalled
    so the interrupt drain preserves drain_incomplete=True and teardown does not block."""
    orig_print = print
    release = threading.Event()
    interrupted_once = False

    def blocking_print(*args, **kwargs):
        if args and "in-flight" in str(args[0]):
            release.wait(timeout=3.0)
        return orig_print(*args, **kwargs)

    base_simple_queue = launcher.SimpleQueue

    class InterruptingSimpleQueue:
        def __init__(self):
            self._inner = base_simple_queue()

        def get(self, *args, **kwargs):
            return self._inner.get(*args, **kwargs)

        def put(self, item, *args, **kwargs):
            nonlocal interrupted_once
            self._inner.put(item, *args, **kwargs)
            if not interrupted_once and isinstance(item, tuple) and "in-flight" in str(item[0]):
                interrupted_once = True
                raise KeyboardInterrupt

    orig_get = launcher.Queue.get
    first = True

    def delayed_first_get(self, *args, **kwargs):
        nonlocal first
        if first:
            first = False
            time.sleep(0.08)
        return orig_get(self, *args, **kwargs)

    monkeypatch.setattr("builtins.print", blocking_print)
    monkeypatch.setattr(launcher, "SimpleQueue", InterruptingSimpleQueue)
    monkeypatch.setattr(launcher.Queue, "get", delayed_first_get)
    try:
        started = time.monotonic()
        result = launcher.launch(
            _child("print('in-flight', flush=True)\n"),
            log_path=tmp_path / "run" / "output.log",
            stream_output=True,
            timeout_seconds=5.0,
        )
        elapsed = time.monotonic() - started
        assert interrupted_once is True
        assert result.interrupted is True
        assert result.drain_incomplete is True
        assert elapsed < 0.8
    finally:
        release.set()
