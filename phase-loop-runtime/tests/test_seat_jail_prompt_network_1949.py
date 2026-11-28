"""Regression tests for Consiliency/agent-harness#1949:
Derive ``model_only_network`` on jailed review pointer prompts from the seat's egress
configuration (allowlisted proxy / ``profile.allowlist_id``) rather than hardcoding
``leg == "gemini"``, so jailed Codex (and other allowlisted jailed seats) are told they
have no network beyond their model while jailed Claude keeps its open-egress preamble.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_profile_grok
from test_seat_profile_codex import codex_profile as _codex_profile

codex_profile = _codex_profile


@pytest.fixture
def grok_profile(monkeypatch):
    from phase_loop_runtime import seat_admission, seat_profiles, seat_subject

    monkeypatch.setattr(seat_profiles, "_REGISTRY", dict(seat_profiles._REGISTRY))
    monkeypatch.setattr(seat_admission, "_GATES", dict(seat_admission._GATES))
    monkeypatch.setattr(
        seat_subject, "_PROVIDER_EXECUTABLES", dict(seat_subject._PROVIDER_EXECUTABLES)
    )
    monkeypatch.delitem(seat_profiles._REGISTRY, "grok", raising=False)
    seat_profile_grok.register_grok()
    return seat_profiles.profile_for("grok")


def test_jailed_seat_model_only_network_follows_allowlist_and_proxy(codex_profile, grok_profile):
    assert pi._jailed_seat_model_only_network("codex") is True
    assert pi._jailed_seat_model_only_network("gemini") is True
    assert pi._jailed_seat_model_only_network("grok") is True
    assert pi._jailed_seat_model_only_network("claude") is False
    # An active allowlisting egress proxy forces model-only even for an unknown leg.
    assert pi._jailed_seat_model_only_network("claude", egress_proxy=SimpleNamespace()) is True
    assert pi._jailed_seat_model_only_network("unregistered-leg") is False


def _run_jailed_default_spawn(monkeypatch, tmp_path: Path, leg: str) -> str:
    """Drive `_default_spawn` through the real pointer-prompt builder and capture `prompt`."""
    captured: list[str] = []
    lease = SimpleNamespace(seat_id=7, release=lambda: None)
    route = SimpleNamespace(jailed=True, lease=lease)
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (route, [], None))
    monkeypatch.setattr(pi._seat_uid, "holder_pid_from_prefix", lambda _: 42)
    monkeypatch.setattr(
        pi._seat_egress_proxy,
        "start_proxy",
        lambda **k: contextlib.nullcontext(
            SimpleNamespace(socket="fixture.sock", proxy_url="http://127.0.0.1:3128")
        ),
    )
    monkeypatch.setattr(
        pi._seat_egress_proxy,
        "start_private_gemini_proxy",
        lambda **k: contextlib.nullcontext(
            SimpleNamespace(socket="fixture.sock", proxy_url="http://127.0.0.1:3128")
        ),
    )
    monkeypatch.setattr(pi._seat_egress_proxy, "egress_evidence", lambda _: {})
    monkeypatch.setattr(
        pi._sandbox_egress, "isolated_network", lambda **k: contextlib.nullcontext(("fixture",))
    )
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda **k: {})
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)

    def staged(repo, review):
        tree = Path(review) / "pl-panel-stage-fixture"
        (tree / ".git").mkdir(parents=True, exist_ok=True)
        (tree / ".git/phase-loop-source-commit").write_text("c" * 40, encoding="utf-8")
        return tree

    monkeypatch.setattr(pi._review_stage, "stage_review_tree", staged)
    monkeypatch.setattr(
        pi._sandbox_policy,
        "select_sandbox_root",
        lambda **k: pi._sandbox_policy.SandboxRootChoice(
            host=None, path=k["fallback"], fell_back=False, reason=""
        ),
    )
    monkeypatch.setattr(pi._sandbox_policy, "ensure_staging_space", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_retention, "mark_as_sandbox", lambda *a, **k: None)
    monkeypatch.setattr(pi, "_bind_route_qualification", lambda seat, _route: seat)
    monkeypatch.setattr(pi, "_exception_failure", lambda exc: (_ for _ in ()).throw(exc))

    fake_seat = SimpleNamespace(notices=(), jail=SimpleNamespace(claude_code_version="unknown"))

    def record_prompt(*_args, **kwargs):
        captured.append(str(kwargs["prompt"]))
        return ("OK", "verdict body\nAGREE")

    if leg == "codex":
        monkeypatch.setattr(pi, "_prepare_jailed_codex", lambda *a, **k: fake_seat)
        monkeypatch.setattr(pi, "_exec_jailed_codex_leg", record_prompt)
    elif leg == "gemini":
        monkeypatch.setattr(pi, "_prepare_jailed_gemini", lambda *a, **k: fake_seat)
        monkeypatch.setattr(pi, "_exec_jailed_gemini_leg", record_prompt)
    elif leg == "claude":
        monkeypatch.setattr(pi, "_prepare_jailed_claude", lambda *a, **k: fake_seat)
        monkeypatch.setattr(pi, "_jailed_claude_login_proof", lambda *a, **k: SimpleNamespace())
        monkeypatch.setattr(pi, "_exec_jailed_claude_leg", record_prompt)
    elif leg == "grok":
        fake_grok_seat = SimpleNamespace(seat=fake_seat, notices=())
        monkeypatch.setattr(pi, "_prepare_jailed_grok", lambda *a, **k: fake_grok_seat)
        monkeypatch.setattr(pi, "_exec_jailed_grok_leg", record_prompt)
    else:
        raise AssertionError(f"unsupported leg {leg}")

    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(
        pi,
        "derive_review_leg_authorization",
        lambda *a, **k: SimpleNamespace(expires_monotonic_ns=0),
    )

    class _FakeBroker:
        def __init__(self, *args, **kwargs):
            self.evidence: dict[str, object] = {}

        def run_credentialless_client(self, adapter, **_kwargs):
            status, text = adapter()
            return {"schema": "v1", "status": status, "text": text}, dict(self.evidence)

        def close(self):
            return None

    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(pi, "_make_broker_inference_adapter", lambda fn, *_a, **_k: fn)

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    authorization = SimpleNamespace(staged_tree_sha256="a" * 64)
    result = pi._default_spawn(
        leg,
        "ARTIFACT",
        mode="review",
        repo_dir=repo,
        review_authorization=authorization,
    )
    assert tuple(result)[0] == "OK"
    assert len(captured) == 1
    return captured[0]


def test_default_spawn_jailed_codex_receives_model_only_network_prompt(
    tmp_path, monkeypatch, codex_profile
):
    prompt = _run_jailed_default_spawn(monkeypatch, tmp_path, "codex")
    assert "There is no network beyond your own model:" in prompt
    assert "PUBLIC internet" not in prompt


def test_default_spawn_jailed_gemini_receives_model_only_network_prompt(tmp_path, monkeypatch):
    prompt = _run_jailed_default_spawn(monkeypatch, tmp_path, "gemini")
    assert "There is no network beyond your own model:" in prompt
    assert "PUBLIC internet" not in prompt


def test_default_spawn_jailed_grok_receives_model_only_network_prompt(
    tmp_path, monkeypatch, grok_profile
):
    prompt = _run_jailed_default_spawn(monkeypatch, tmp_path, "grok")
    assert "There is no network beyond your own model:" in prompt
    assert "PUBLIC internet" not in prompt


def test_default_spawn_jailed_claude_keeps_open_egress_network_prompt(tmp_path, monkeypatch):
    prompt = _run_jailed_default_spawn(monkeypatch, tmp_path, "claude")
    assert "you MAY use the PUBLIC internet" in prompt
    assert "no network beyond your own model" not in prompt
