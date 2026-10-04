import os
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker, sandbox_policy


def test_bounded_brokered_gemini_receives_disk_scratch(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    home = tmp_path / "home"
    token = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    token.parent.mkdir(parents=True)
    token.write_text("test-reference")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", raising=False)
    monkeypatch.setattr(
        sandbox_policy, "_mount_fstype",
        lambda p: "tmpfs" if os.path.realpath(p) == "/tmp" else "ext4",
    )
    monkeypatch.setattr(panel_invoker, "_leg_auth_ok", lambda *a: (True, ""))
    seen = {}

    class LaunchReached(BaseException):
        pass

    def capture(command, **kwargs):
        seen.update(kwargs)
        raise LaunchReached

    monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", capture)
    review = tmp_path / "review"
    out = tmp_path / "out"
    review.mkdir()
    out.mkdir()
    with pytest.raises(LaunchReached):
        panel_invoker._exec_leg(
            "gemini", review, out, 60, "bundle", "review",
            panel_invoker.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["gemini"],
            env={"HOME": str(home), "PATH": "/usr/bin"},
            broker_prompt="Review this bundle", review_monitor=None,
        )
    assert "gemini_profile" not in seen
    assert seen["env"].get("TMPDIR") == str(cache / "phase-loop/tmp")
