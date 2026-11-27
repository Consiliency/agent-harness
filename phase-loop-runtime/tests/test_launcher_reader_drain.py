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


def test_interrupt_during_post_exit_drain_skips_descendant_cleanup_after_reap(tmp_path, monkeypatch):
    """If KeyboardInterrupt fires during post-exit drain after leader_unreaped was set,
    _cleanup_process_group reaps the leader and post-exit descendant cleanup must NOT
    signal a potentially recycled PGID."""
    marker = tmp_path / "interrupt_grandchild.pid"
    script = (
        "import subprocess, sys\n"
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(marker)!r}, 'w').write(str(proc.pid))\n"
        "print('leader-done', flush=True)\n"
    )
    descendant_calls = []
    monkeypatch.setattr(
        launcher,
        "_cleanup_descendant_process_group",
        lambda *a, **k: descendant_calls.append((a, k)),
    )
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
        assert descendant_calls == []
    finally:
        _kill_pid_best_effort(marker)
