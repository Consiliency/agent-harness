"""An owned Claude TUI seat reports the owner's own refusal by its typed code.

The owner's final link runs before the seat's terminal is attached, so its refusal
message goes to a private host file rather than the PTY (a host process holding the PTY
would hide the seat's EOF). The leg still ends with the typed code, not a generic EOF.
"""

from __future__ import annotations

import os
import shutil

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_seccomp

pytestmark = [pytest.mark.skipif(shutil.which("sh") is None, reason="needs POSIX sh"),
              pytest.mark.usefixtures("owned_review_network")]


def test_a_final_link_refusal_is_typed_on_the_tui_route(tmp_path, monkeypatch):
    def _unsealed():
        descriptor = os.memfd_create("unsealed-filter", os.MFD_CLOEXEC)
        os.write(descriptor, seat_seccomp.keyring_filter())
        return descriptor

    # An unsealed filter is refused by the final link before anything else runs.
    monkeypatch.setattr(seat_seccomp, "sealed_keyring_filter", _unsealed)
    rc, text, status, _tail = pi._run_claude_tui_session(
        command=["sh", "-c", "echo should-not-run; sleep 5"], cwd=tmp_path, prompt="review",
        output_file=tmp_path / "out.txt", timeout_s=20, env={"PATH": "/usr/bin:/bin"},
    )
    assert (rc, text, status) == (127, "", "seat_keyring_unavailable")
