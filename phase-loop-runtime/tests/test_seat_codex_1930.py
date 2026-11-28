"""Regression tests for Consiliency/agent-harness#1930.

Verifies that adding ``codex`` to ``_SANDBOX_INCAPABLE_BROKERED_LEGS`` accurately
classifies the retained sealed non-jailed brokered Codex route as sealed (not
``seat_filesystem_unconfined``), delivers the sealed inline prompt, excludes it from
``claude_bakeoff.effective_unconfined_co_seats()``, and keeps jailed Codex review seats
and non-brokered Codex research seats sandbox-capable.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
import time
from types import SimpleNamespace

from phase_loop_runtime import (
    claude_bakeoff,
    panel_invoker as pi,
    seat_preflight as sp,
)


def test_non_jailed_brokered_codex_launch_mode_is_sealed_not_unconfined(monkeypatch):
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (None, [], None))
    board = SimpleNamespace(
        seats=[SimpleNamespace(harness="codex", seat_key="codex:a", model="gpt-5.4")]
    )
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    (mode,) = pi._seat_launch_modes(board, mode="review", review_authorization=auth, base_env={})
    assert mode.mode == sp.MODE_SEALED
    assert mode.code is None
    assert mode.why == "this route has no file tools"


def test_non_jailed_brokered_codex_default_spawn_omits_unconfined_notice_and_uses_sealed_prompt(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(pi, "_gc_stale_panel_scratch", lambda: None)
    pi._JAILCORE_ROUTE_CACHE.clear()
    monkeypatch.setattr(pi, "_seat_route_for_spawn", lambda *a, **k: (None, [], None))
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network", lambda **k: contextlib.nullcontext(("fixture",)))
    monkeypatch.setattr(pi._sandbox_egress, "enforcement_report", lambda **k: {})
    monkeypatch.setattr(pi._sandbox_egress, "egress_required", lambda: False)
    monkeypatch.setattr(pi._sandbox_policy, "ensure_staging_space", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_retention, "mark_as_sandbox", lambda *a, **k: None)

    def staged(repo, review):
        tree = Path(review) / "pl-panel-stage-fixture"
        (tree / ".git").mkdir(parents=True)
        (tree / ".git/phase-loop-source-commit").write_text("c" * 40)
        return tree

    monkeypatch.setattr(pi._review_stage, "stage_review_tree", staged)
    monkeypatch.setattr(
        pi._sandbox_policy, "select_sandbox_root",
        lambda **k: pi._sandbox_policy.SandboxRootChoice(host=None, path=k["fallback"], fell_back=False, reason=""),
    )

    seen_prompts: list[str] = []
    real_render = pi._render_broker_inline_prompt

    def spy_render(*args, **kwargs):
        rendered = real_render(*args, **kwargs)
        seen_prompts.append(rendered)
        return rendered

    monkeypatch.setattr(pi, "_render_broker_inline_prompt", spy_render)

    class FakeBroker:
        def __init__(self, *args, **kwargs):
            self.evidence: dict[str, object] = {}

        def run_credentialless_client(self, adapter, *, deadline_s=None, cancel_event=None):
            return {"schema": "parent_unix_broker_v1", "status": "OK", "text": "Reviewed.\n\nAGREE"}, dict(self.evidence)

        def close(self):
            pass

    monkeypatch.setattr(pi, "ParentUnixBroker", FakeBroker)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(
        pi, "derive_review_leg_authorization",
        lambda *a, **k: SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12),
    )
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a: (False, "missing_claude_cli"))
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    spawned = pi._default_spawn(
        "codex", "ARTIFACT", mode="review", model="m",
        review_authorization=SimpleNamespace(staged_tree_sha256="a" * 64),
        canonical_repo_authority=tmp_path,
    )
    assert spawned[0] == "OK", (spawned, spawned.seat_notices)
    assert "seat_filesystem_unconfined" not in spawned.seat_notices
    assert len(seen_prompts) == 1
    assert "Do not use or request tools" in seen_prompts[0]
    assert "You MAY run commands" not in seen_prompts[0]


def test_jailed_codex_and_non_brokered_research_codex_remain_sandbox_usable(monkeypatch):
    # Jailed Codex review seat passes jailed=True -> readable in pointer-brief preflight.
    monkeypatch.setattr(pi, "_seat_jailed_at_launch", lambda leg, *a, **k: leg == "codex")
    board = SimpleNamespace(
        seats=[SimpleNamespace(harness="codex", seat_key="codex:a", model="gpt-5.4")]
    )
    notices = pi._publish_seat_preflight(
        board,
        pointer_brief=True,
        mode="review",
        review_authorization=SimpleNamespace(staged_tree_sha256="a" * 64),
        base_env={},
        stream_dir=None,
        on_seat_preflight=None,
    )
    assert notices == ()

    # Non-brokered Codex (including research seats) retains brokered=False sandbox usability.
    assert pi.sandbox_usable_by("codex", brokered=False) is True
    assert pi.sandbox_usable_by("codex", brokered=True, jailed=True) is True
    assert pi.sandbox_usable_by("codex", brokered=True, jailed=False) is False

    # Bakeoff co-seat unconfined accounting excludes codex.
    from phase_loop_runtime.advisor_board import composition

    full_board = composition.compose_review_board(
        is_available=lambda vendor: vendor in {"claude", "codex", "grok", "gemini"}
    )
    monkeypatch.setattr(composition, "compose_review_board", lambda *a, **k: full_board)
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_DISABLE", raising=False)
    assert claude_bakeoff.effective_unconfined_co_seats() == ("grok",)


def test_pointer_preflight_tracks_codex_jail_decision_per_board_position(tmp_path, monkeypatch):
    """When two Codex seats share a board and only one jail lease is available, only the
    unjailed seat gets ``seat_pointer_brief_unreadable``; the jailed seat stays grounded."""
    import dataclasses

    from phase_loop_runtime import sandbox_egress, seat_egress_proxy, seat_profiles, seat_route
    from test_seat_login_wait_a3_1166 import _route_claude_jailed

    _route_claude_jailed(monkeypatch, fake_capacity=False)
    codex_profile = dataclasses.replace(
        seat_profiles.profile_for("codex"),
        credential_present=lambda *_a, **_k: True,
        preconditions=(),
        require_projected_runtime=False,
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "codex", codex_profile)
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: True)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: None)
    monkeypatch.setattr(seat_route, "_allowlist_digest_for_launch", lambda _profile: "e" * 64)

    leased = {"count": 0}

    class OneLease:
        seat_id = 7

        def release(self):
            return None

    class SingleSlotCapacity:
        def try_lease(self):
            if leased["count"] >= 1:
                return None
            leased["count"] += 1
            return OneLease()

    monkeypatch.setattr(pi._seat_uid, "SeatIdCapacity", SingleSlotCapacity)
    pi._JAILCORE_ROUTE_CACHE.clear()

    board = SimpleNamespace(
        seats=[
            SimpleNamespace(harness="codex", seat_key="codex:a", model="gpt-5.4"),
            SimpleNamespace(harness="codex", seat_key="codex:b", model="gpt-5.4"),
        ]
    )
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    env = {"HOME": str(tmp_path / "no-login-home"), "CODEX_HOME": str(tmp_path / "no-codex")}
    modes = pi._seat_launch_modes(board, mode="review", review_authorization=auth, base_env=env)
    assert [m.mode for m in modes] == [sp.MODE_JAILED, sp.MODE_DEGRADED]

    # Reset the single-slot fixture and cache so preflight resolves the exact same one-lease
    # scenario independently.
    leased["count"] = 0
    pi._JAILCORE_ROUTE_CACHE.clear()
    notices = pi._publish_seat_preflight(
        board,
        pointer_brief=True,
        mode="review",
        review_authorization=auth,
        base_env=env,
        stream_dir=None,
        on_seat_preflight=None,
    )
    assert [(n.position, n.seat_key, n.leg, n.code) for n in notices] == [
        (1, "codex:b", "codex", sp.POINTER_BRIEF_UNREADABLE),
    ]
