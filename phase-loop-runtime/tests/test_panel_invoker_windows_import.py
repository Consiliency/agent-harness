from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import phase_loop_runtime.panel_invoker as panel_invoker


def test_panel_invoker_imports_without_posix_pty_modules() -> None:
    # Resolve the directory that makes ``phase_loop_runtime`` importable in *this*
    # interpreter. In the repo that is the ``src/`` layout; in the Gate A
    # clean-room (only ``tests/`` is copied, package installed from a wheel) it is
    # the venv's site-packages. Deriving it from the imported module keeps this
    # test layout-independent instead of assuming a sibling ``src/`` dir.
    package_parent = Path(panel_invoker.__file__).resolve().parents[1]
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
    # Inherit the real environment (so site-packages / PYTHONNOUSERSITE stay
    # intact under the clean-room) and just make sure the package parent is on
    # PYTHONPATH.
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(package_parent), existing] if existing else [str(package_parent)]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
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


def test_windows_process_termination_keeps_leader_only_wait_behavior() -> None:
    class Process:
        terminated = False
        killed = False
        waits: list[int] = []

        @staticmethod
        def poll():
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, *, timeout):
            self.waits.append(timeout)
            return 0

        def kill(self):
            self.killed = True

    process = Process()

    panel_invoker._terminate_process_group_windows(
        process, force_group=False,
    )

    assert process.terminated
    assert process.waits == [5]
    assert not process.killed
