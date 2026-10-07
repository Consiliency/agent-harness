"""Unsupported review transports refuse before provider invocation."""

from types import SimpleNamespace

import pytest

from phase_loop_runtime import launcher, panel_invoker, sandbox_egress


@pytest.mark.parametrize("route", ["claude_channel", "claude_agent_view"])
def test_executor_review_refuses_an_unowned_transport(route, monkeypatch):
    spec = SimpleNamespace(available=True, prompt_bundle=SimpleNamespace(product_action="review"),
                           claude_route=route, executor="claude")
    monkeypatch.setattr(launcher, "_launch_claude_channel", lambda *a, **k: pytest.fail("channel ran"))
    monkeypatch.setattr(launcher, "_launch_claude_agent_view", lambda *a, **k: pytest.fail("agent view ran"))
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match="executor_review_route_unsupported"):
        launcher.launch_with_spec(spec)


def test_panel_agent_view_review_is_a_refusal(tmp_path):
    assert panel_invoker._exec_claude_agent_view_attempt(
        None, review_dir=tmp_path, timeout_s=30, prompt="synthetic request", env={},
    ) == ("UNAVAILABLE", "claude_agent_view_review_unsupported")


def test_trusted_channel_action_keeps_its_transport(monkeypatch):
    spec = SimpleNamespace(available=True, prompt_bundle=SimpleNamespace(product_action="execute"),
                           claude_route="claude_channel", executor="claude")
    expected = object()
    monkeypatch.setattr(launcher, "_launch_claude_channel", lambda *a, **k: expected)
    monkeypatch.setattr(launcher, "_result_with_spec", lambda result, spec: result)
    assert launcher.launch_with_spec(spec) is expected


def test_legacy_owner_composer_refuses_before_launch(tmp_path):
    import threading
    monitor = panel_invoker._ReviewMonitor(tmp_path / 'monitor.json', 'legacy-owner', 0,
                                           threading.Event())
    with pytest.raises(sandbox_egress.SeatIdentityUnverified, match='seat_launch_owner_required'):
        monitor.owned_command(['/bin/true'], cwd=tmp_path)
