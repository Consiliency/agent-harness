"""Gemini planning, roadmap and review routes and the heavy tier launch Gemini 4 NEON.

Before Gemini 4 Argon they used the `pro` alias, which renders "Gemini 3.1 Pro (High)"; agy no
longer accepts that label (measured 2026-10-14 on agy 1.3.1). The effort stays what the route
asked for: the shipped policy requests max, gemini clamps it to high, so the argv is
`gemini-4-neon-high` (never agy's `gemini-4-neon-xhigh`). Implementers and workers follow the
roster, not NEON. Argon stays selectable by explicit model and by PHASE_LOOP_GEMINI_MODEL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phase_loop_runtime.launcher import (
    _gemini_cli_model,
    build_gemini_command,
    build_launch_request,
    build_launch_spec,
)
from phase_loop_runtime.profiles import (
    CLASS_MODEL_OVERRIDES,
    EXECUTOR_MODEL_OVERRIDES,
    resolve,
    resolve_execution_policy,
    resolve_model_class,
    resolve_model_selection_from_policy,
    resolve_profile_for_executor,
    shipped_model_policy_rule,
)
from phase_loop_runtime.prompts import build_prompt

NEON = "gemini-4-neon"  # model-id-source: test pins the planning/heavy default under test
NEON_HIGH = "gemini-4-neon-high"  # model-id-source: test pins the rendered agy id
ARGON = "gemini-4-argon"  # model-id-source: test pins the prior default staying selectable
PLANNING_ACTIONS = ("roadmap", "plan", "review")


def _runner_selection(action, *, model=None, effort=None):
    # The runner's own chain (runner.py): executor default -> shipped model_policy -> selection.
    selection = resolve_profile_for_executor(action=action, executor="gemini", model=model, effort=effort)
    policy = resolve_execution_policy(
        action=action, executor="gemini", model_selection=selection,
        operator_model=model, operator_effort=effort,
        model_policy_rule=shipped_model_policy_rule(action),
    )
    return resolve_model_selection_from_policy(profile=selection.profile, resolved_policy=policy)


def _argv_model(action, **kwargs):
    command = build_gemini_command(
        Path("/repo"), _runner_selection(action, **kwargs), action=action, context_file="workflow.md",
    )
    return command[command.index("--model") + 1]


@pytest.mark.parametrize("action", PLANNING_ACTIONS)
def test_planning_routes_launch_neon_high(action):
    assert _argv_model(action) == NEON_HIGH


def test_plan_launch_spec_carries_neon():
    roadmap = Path("/repo/specs/phase-plans-v1.md")
    request = build_launch_request(
        executor="gemini", action="plan", repo=Path("/repo"), roadmap=roadmap, phase="RUNNER",
        plan=None, model_selection=_runner_selection("plan"),
        prompt_bundle=build_prompt("plan", roadmap, phase="RUNNER", harness_target="gemini"),
        json_output=False, bypass_approvals=False,
    )
    spec = build_launch_spec(request)
    assert spec.selected_model == NEON
    assert spec.command[:3] == ["agy", "--model", NEON_HIGH]


def test_executor_defaults_and_class_map_agree_with_the_heavy_tier():
    heavy = resolve("heavy", "gemini")
    assert heavy.model_id == NEON
    for action in PLANNING_ACTIONS:
        assert EXECUTOR_MODEL_OVERRIDES["gemini"][action] == NEON, action
    assert CLASS_MODEL_OVERRIDES["gemini"]["planner"] == NEON
    assert resolve_model_class("gemini", "reviewer") == NEON


def test_heavy_and_ultra_tiers_are_neon_and_stay_volatile():
    heavy, ultra = resolve("heavy", "gemini"), resolve("ultra", "gemini")
    assert (heavy.model_id, heavy.effort, heavy.volatile) == (NEON, "xhigh", True)
    assert (ultra.model_id, ultra.effort, ultra.volatile) == (NEON, "max", True)
    assert _gemini_cli_model(heavy.model_id) == NEON_HIGH


def test_requested_effort_is_clamped_or_carried_into_the_neon_id():
    assert _argv_model("plan", effort="max") == NEON_HIGH
    assert _argv_model("review", effort="medium") == "gemini-4-neon-medium"


def test_explicit_task_model_still_wins_on_a_planning_route():
    assert _argv_model("plan", model="gemini-3.8-flash") == "gemini-3.8-flash-high"


@pytest.mark.parametrize("action", ("execute", "repair"))
def test_implementation_routes_are_not_neon_or_argon(action):
    for family in ("neon", "argon"):
        assert family not in _argv_model(action)
        assert family not in EXECUTOR_MODEL_OVERRIDES["gemini"][action]


@pytest.mark.parametrize("model_class", ("implementer", "worker"))
def test_implementer_and_worker_classes_are_not_neon_or_argon(model_class):
    for family in ("neon", "argon"):
        assert family not in resolve_model_class("gemini", model_class)


@pytest.mark.parametrize("action", PLANNING_ACTIONS)
def test_explicit_argon_still_launches_on_a_planning_route(action):
    assert _argv_model(action, model=ARGON) == "gemini-4-argon-high"


@pytest.mark.parametrize("value, rendered", [(NEON, NEON_HIGH), (ARGON, "gemini-4-argon-high")])
def test_local_preference_accepts_neon_and_argon(monkeypatch, value, rendered):
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", value)
    for action in PLANNING_ACTIONS:
        assert _argv_model(action) == rendered, action


@pytest.mark.parametrize("value", ["gemini-4-neon-high", "gemini-4-neon-xhigh", "gemini-4-other"])
def test_local_preference_refuses_suffixed_or_unregistered_neon(monkeypatch, value):
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", value)
    with pytest.raises(ValueError, match="PHASE_LOOP_GEMINI_MODEL"):
        resolve_profile_for_executor(action="plan", executor="gemini")


def test_xhigh_request_never_reaches_the_argv():
    # The executor policy caps Gemini at high; an xhigh-style max request renders -high.
    assert _argv_model("review", effort="max") == NEON_HIGH
    assert "xhigh" not in _argv_model("plan", effort="max")
