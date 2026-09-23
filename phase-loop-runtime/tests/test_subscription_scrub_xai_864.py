"""agent-harness#864: the subscription scrub removes the xAI/Grok API-key variables.

Variable names come from the grok CLI 1.0.41 documentation: ``XAI_API_KEY`` ("API key sent
as ``Authorization: Bearer``") and ``GROK_CODE_XAI_API_KEY`` (accepted for backward
compatibility). grok is a SUBSCRIPTION-ONLY harness, so these vars are scrub-only: they
are never part of the per-vendor injection map (``VENDOR_API_KEY_VARS``).
"""
from __future__ import annotations

import pytest

from phase_loop_runtime import panel_invoker
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.backing import (
    VENDOR_API_KEY_VARS,
    resolve_seat_env,
    scrub_subscription_env,
)
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS

XAI_VARS = ("XAI_API_KEY", "GROK_CODE_XAI_API_KEY")


@pytest.mark.parametrize("var", XAI_VARS)
def test_the_subscription_scrub_removes_the_xai_key(var):
    env = scrub_subscription_env({var: "test-only", "PATH": "/usr/bin", "LANG": "C"})
    assert env == {"PATH": "/usr/bin", "LANG": "C"}  # unrelated values retained


@pytest.mark.parametrize("var", XAI_VARS)
def test_the_panel_subscription_env_removes_the_xai_key(var):
    assert var not in panel_invoker._subscription_env({var: "test-only", "PATH": "/usr/bin"})


@pytest.mark.parametrize("var", XAI_VARS)
def test_a_grok_subscription_seat_gets_no_xai_key(var):
    seat = next(s for s in DEFAULT_SEATS if s.harness == "grok")
    assert var not in resolve_seat_env(seat, {var: "test-only", "PATH": "/usr/bin"})


def test_xai_keys_are_scrub_only_never_injectable():
    # grok is subscription-only: no vendor maps to an xAI key, so no api-key opt-in can
    # inject one (the frozen cross-vendor map is unchanged).
    injectable = {var for vars_ in VENDOR_API_KEY_VARS.values() for var in vars_}
    assert not injectable & set(XAI_VARS)
    assert set(XAI_VARS) <= set(backing.SUBSCRIPTION_SCRUB_ONLY_VARS)


@pytest.mark.parametrize("var", backing.GROK_SUBSCRIPTION_BLOCKED_ENV_VARS)
def test_grok_endpoint_redirects_are_scrubbed(var):
    # native seat F1: a subscription grok child must not be redirected off the service.
    seat = next(s for s in DEFAULT_SEATS if s.harness == "grok")
    env = {var: "https://elsewhere.invalid/v1", "PATH": "/usr/bin"}
    assert scrub_subscription_env(env) == {"PATH": "/usr/bin"}
    assert var not in resolve_seat_env(seat, env)


def test_the_convergence_child_environment_is_scrubbed(monkeypatch):
    from phase_loop_runtime.convergence.adapters import base

    for var in XAI_VARS:
        monkeypatch.setenv(var, "test-only")
    env = base._child_environment()
    assert not set(XAI_VARS) & set(env)
