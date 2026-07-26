from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path

import phase_loop_runtime.panel_invoker as panel_invoker


def test_panel_invoker_imports_without_posix_pty_modules() -> None:
    package_root = Path(__file__).resolve().parents[1] / "src"
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name in {"fcntl", "pty", "termios"}:
        raise ImportError(f"blocked {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import phase_loop_runtime.panel_invoker
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=package_root,
        env={"PYTHONPATH": str(package_root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_claude_tui_fails_closed_without_posix_pty(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(panel_invoker, "fcntl", None)
    monkeypatch.setattr(panel_invoker, "pty", None)
    monkeypatch.setattr(panel_invoker, "termios", None)

    assert panel_invoker._run_claude_tui_session(
        command=["claude"],
        cwd=tmp_path,
        prompt="review",
        output_file=tmp_path / "review.txt",
        timeout_s=1,
        env={},
    ) == (1, "", "claude_tui_unsupported_platform", "")
