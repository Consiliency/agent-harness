"""The ordinary (observer-less) launch keeps every line its child wrote
(agent-harness#2092 follow-up).

Two races on the streaming path lost output:
- when the child exited, the loop drained only the lines already queued and stopped,
  while the reader thread still held the child's last lines;
- invalid UTF-8 raised in the text-mode reader thread, which then dropped every later
  line.

The first race is made deterministic by holding the reader back until the launcher has
seen the child exit.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from phase_loop_runtime import launcher

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX streaming path")

LINES = ["first", "second", "third"]


def _child(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_lines_the_reader_still_holds_at_exit_are_kept(tmp_path, monkeypatch):
    exited = threading.Event()
    original_poll = subprocess.Popen.poll

    def poll(self):
        returncode = original_poll(self)
        if returncode is not None:
            exited.set()
        return returncode

    monkeypatch.setattr(subprocess.Popen, "poll", poll)
    original_reader = launcher._read_lines

    def lagging_reader(stdout, line_queue):
        def lines():
            iterator = iter(stdout)
            yield next(iterator)
            # The launcher has now seen the exit; the rest arrives just after.
            exited.wait(10)
            time.sleep(0.05)
            yield from iterator
        original_reader(lines(), line_queue)

    monkeypatch.setattr(launcher, "_read_lines", lagging_reader)
    script = "import sys\n" + "".join(f"print({line!r}, flush=True)\n" for line in LINES)
    result = launcher.launch(_child(script), log_path=tmp_path / "run" / "output.log")
    assert exited.is_set()
    assert result.returncode == 0
    assert result.output.splitlines() == LINES
    assert (tmp_path / "run" / "output.log").read_text(encoding="utf-8").splitlines() == LINES


def test_invalid_utf8_does_not_kill_the_reader(tmp_path, monkeypatch):
    failures = []
    monkeypatch.setattr(threading, "excepthook", lambda args: failures.append(args.exc_type))
    script = "import os\nos.write(1, b'before\\n\\xff\\nafter\\n')\n"
    result = launcher.launch(_child(script), log_path=tmp_path / "run" / "output.log")
    assert result.returncode == 0
    assert not failures
    assert result.output.splitlines() == ["before", "�", "after"]


def test_a_descendant_holding_the_pipe_cannot_extend_the_launch(tmp_path):
    script = ("import os, time\nprint('root', flush=True)\n"
              "if os.fork() == 0:\n time.sleep(5); os._exit(0)\nos._exit(0)\n")
    started = time.monotonic()
    result = launcher.launch(_child(script), log_path=tmp_path / "run" / "output.log")
    assert time.monotonic() - started < 4
    assert result.returncode == 0 and "root" in result.output
