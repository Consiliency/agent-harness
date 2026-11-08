"""OD-4 retires agent-harness#1470's inner-sandbox writable-tree grant."""
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi, sandbox_egress


@pytest.mark.parametrize("harness", ["codex", "grok", "gemini"])
@pytest.mark.parametrize("sandbox", ["workspace-write", "read-only", "danger-full-access"])
def test_stale_writable_tree_grant_is_refused_before_any_setup(tmp_path, monkeypatch, harness, sandbox):
    tree = tmp_path / "tree"
    tree.mkdir()
    out = tmp_path / "out"
    def unexpected(*args, **kwargs):
        pytest.fail("retired writable-tree grant reached credential or provider setup")
    monkeypatch.setattr(pi, "_seat_provider_source", unexpected)
    command = [harness, "exec", "--cd", str(tree), "--sandbox", sandbox]
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
        with pi._seat_command_profile(command, env={}, cwd=tmp_path, outputs=(out,), writable_tree=tree):
            pytest.fail("retired grant admitted")
    assert not out.exists()


def test_retry_cannot_resurrect_a_checked_writable_tree_grant(tmp_path):
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="seat_bind_source_unavailable"):
        with pi._seat_command_profile(["codex"], env={}, cwd=tmp_path, writable_tree_checked=True):
            pytest.fail("checked-grant marker bypassed retirement")


def test_brokered_staged_codex_keeps_no_capabilities_or_writable_grants(tmp_path, monkeypatch):
    calls = []
    out = tmp_path / "out"
    out.mkdir()
    review = tmp_path / "review"
    (review / "reviewed-tree").mkdir(parents=True)
    def run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[command.index("--output-last-message") + 1]).write_text("AGREE")
        return pi._LegRun(0, "AGREE", "")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    monkeypatch.setattr(pi, "_codex_command_sandbox_cannot_start", lambda *a, **k:
                        pytest.fail("sealed broker route probed an inner sandbox"))
    rc, text, _ = pi._exec_leg("codex", review, out, env={}, artifact="fixture",
                              broker_prompt="fixture", broker_evidence={})
    assert (rc, text) == (0, "AGREE")
    assert calls
    for command, kwargs in calls:
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert command[command.index("--cd") + 1] == str(out)
        assert not kwargs.get("retain_caps")
        assert "writable_tree" not in kwargs and "writable_tree_checked" not in kwargs
