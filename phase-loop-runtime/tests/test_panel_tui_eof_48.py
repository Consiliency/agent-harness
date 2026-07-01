"""#48 — the advisor-panel Claude TUI leg must not hang when the child CLI exits.

When the child (and its descendants) close the PTY slave, ``os.read`` hits EOF.
An EOF fd is always "readable", so without an explicit EOF branch the read loop
busy-spins to the (input-scaled, up to 30-min) deadline whenever the launched
process is a wrapper whose parent lingers after the CLI exits (``proc.poll()``
never fires). The leg must instead return a structured result promptly.
"""

from __future__ import annotations

import shutil
import time

import pytest

from phase_loop_runtime.panel_invoker import _classify_leg, _run_claude_tui_session

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs POSIX sh")


def test_claude_tui_leg_returns_promptly_on_pty_eof(tmp_path):
    # The child closes all three PTY fds (EOF fires immediately) but the process
    # lingers (sleep 60), so proc.poll() stays None — the exact wrapper-lingers
    # hang from #48. Deadline is 20s; the EOF path must return long before that.
    output_file = tmp_path / "panel-claude.txt"  # intentionally: no verdict written

    start = time.monotonic()
    rc, text, status = _run_claude_tui_session(
        command=["sh", "-c", "exec 0<&- 1>&- 2>&-; sleep 60"],
        cwd=tmp_path,
        prompt="review this",
        output_file=output_file,
        timeout_s=20,
        env={"PATH": "/usr/bin:/bin"},
    )
    elapsed = time.monotonic() - start

    assert elapsed < 10, (
        f"#48: TUI leg hung ~{elapsed:.1f}s toward the deadline instead of "
        f"returning promptly on PTY EOF"
    )
    assert status == "claude_tui_pty_eof_no_output", status
    # Structured, fail-closed classification — never a silent pass, never a hang.
    assert _classify_leg(rc, text, status) in {"ERROR", "EMPTY"}, (rc, status)
