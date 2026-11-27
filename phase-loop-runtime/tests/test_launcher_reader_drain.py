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


def test_grandchild_holding_stdout_open_past_child_exit_is_bounded_and_cleaned(tmp_path):
    marker = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"Path({str(marker)!r}).write_text(str(p.pid), encoding='utf-8')\n"
        "print('child-done', flush=True)\n"
    )
    started = time.monotonic()
    result = launcher.launch(
        _child(script),
        log_path=tmp_path / "run" / "output.log",
        timeout_seconds=0.5,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 3.0
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
    started = time.monotonic()
    result = launcher.launch_with_spec(
        spec.__class__(**{**spec.__dict__, "launch_timeout_seconds": 0.6}),
        codex_usage_capture=True,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 3.0
    assert result.returncode == 0
    assert result.drain_incomplete is True
    assert result.jevdrill_usage is None
    assert result.cleanup_evidence is not None
    assert result.cleanup_evidence["reason"] == "post_exit_pipe_open"
    grandchild_pid = int(marker.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 1.0
    while _proc_alive(grandchild_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _proc_alive(grandchild_pid)
