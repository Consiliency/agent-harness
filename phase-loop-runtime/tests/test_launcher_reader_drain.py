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
