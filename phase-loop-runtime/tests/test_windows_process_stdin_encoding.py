"""The Windows admitted child sends the executor its prompt as UTF-8, whatever the
host code page is (agent-harness#2092).

The isolated child (``python -I -S``) does not inherit ``PYTHONUTF8``. Under a CP1252
locale, text-mode stdin used to send ``é`` as the wrong bytes and to raise
``UnicodeEncodeError`` on characters outside the code page, such as ``漢``. The test
forces CP1252 as the default text encoding ``subprocess`` picks for its pipes
(``subprocess._text_encoding``, which stands in for the locale code page).
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import types

import pytest

from phase_loop_runtime import windows_process

PROMPT = "café 漢字 ✓"


def _force_cp1252(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")


def _run_admitted_child(monkeypatch, tmp_path, stdin_text):
    sink = tmp_path / "executor-stdin.bin"
    executor = [sys.executable, "-c",
                "import sys; open(sys.argv[1], 'wb').write(sys.stdin.buffer.read())", str(sink)]
    admission = json.dumps({"command": executor, "stdin": stdin_text}).encode() + b"\n"
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(admission)))
    _force_cp1252(monkeypatch)
    return windows_process._admitted_child(), sink


def test_the_cp1252_simulation_is_effective(monkeypatch, tmp_path):
    _force_cp1252(monkeypatch)
    with pytest.raises(UnicodeEncodeError):
        subprocess.run([sys.executable, "-c", "pass"], input=PROMPT, text=True, check=False)


def test_admitted_child_sends_utf8_stdin_under_cp1252(monkeypatch, tmp_path):
    returncode, sink = _run_admitted_child(monkeypatch, tmp_path, PROMPT)
    assert returncode == 0
    assert sink.read_bytes() == PROMPT.encode("utf-8")


def test_admitted_child_without_stdin_still_gets_devnull(monkeypatch, tmp_path):
    returncode, sink = _run_admitted_child(monkeypatch, tmp_path, None)
    assert returncode == 0
    assert sink.read_bytes() == b""
