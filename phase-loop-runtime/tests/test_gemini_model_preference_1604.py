"""Local Gemini defaults must reach argv without changing explicit selections."""
from pathlib import Path

import pytest

from phase_loop_runtime.advisor_board import Seat, render_seat_invocation
from phase_loop_runtime.advisor_board.composition import compose_review_board_report
from phase_loop_runtime.advisor_board.config import load_boards
from phase_loop_runtime.advisor_board.harness_mapping import render_agy_model
from phase_loop_runtime.advisor_board.registries import DEFAULT_MODEL_REGISTRY
from phase_loop_runtime.launcher import build_gemini_command
from phase_loop_runtime.models import ExecutionPolicyRule
from phase_loop_runtime.profiles import (
    resolve_execution_policy,
    resolve_model_class,
    resolve_model_selection_from_policy,
    resolve_profile_for_executor,
    shipped_model_policy_rule,
)


def _launch(action, *, model=None, plan=None):
    selection = resolve_profile_for_executor(action=action, executor="gemini", model=model)
    policy = resolve_execution_policy(
        action=action, executor="gemini", model_selection=selection,
        operator_model=model, plan_policy=plan,
        model_policy_rule=shipped_model_policy_rule(action),
    )
    selection = resolve_model_selection_from_policy(profile=selection.profile, resolved_policy=policy)
    return build_gemini_command(Path("/repo"), selection, action=action, context_file="workflow.md")


@pytest.mark.parametrize("action", ["roadmap", "plan", "execute", "repair", "review"])
def test_local_argon_default_reaches_each_real_launcher_argv(monkeypatch, action):
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", "gemini-4-argon")
    command = _launch(action)
    assert command[command.index("--model") + 1] == "gemini-4-argon-high"
    assert ("--dangerously-skip-permissions" in command) == (action != "review")
    if action == "review":
        assert command[command.index("--add-dir") + 1].endswith("/repo")
        assert command[command.index("--add-dir") + 1] != "/repo"


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "Gemini 3.1 Pro (High)", "gpt-oss-120b-medium"])
def test_explicit_task_model_survives_even_an_invalid_local_preference(monkeypatch, model):
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", "not-a-model")
    command = _launch("review", model=model)
    assert command[command.index("--model") + 1] == render_agy_model(model, "high")


def test_explicit_plan_model_wins_over_valid_local_preference(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", "gemini-4-argon")
    command = _launch("execute", plan=ExecutionPolicyRule(model="gemini-3.8-flash"))
    assert command[command.index("--model") + 1] == "gemini-3.8-flash-high"


def test_board_default_preserves_effort_auth_lenses_and_other_vendors(monkeypatch):
    probes = {"is_available": lambda _: True, "auth_ok": lambda _: True}
    monkeypatch.delenv("PHASE_LOOP_GEMINI_MODEL", raising=False)
    baseline = compose_review_board_report(**probes).board
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", "gemini-3.8-flash")
    board = compose_review_board_report(**probes).board
    assert [s for s in board.seats if s.harness != "gemini"] == [s for s in baseline.seats if s.harness != "gemini"]
    seat = next(s for s in board.seats if s.harness == "gemini")
    assert render_seat_invocation(seat.harness, seat.model, seat.effort).model == "gemini-3.8-flash-medium"
    assert (seat.auth, seat.backing, seat.lens) == ("subscription", "homebrew", "alternative-approach")


def test_excluded_seat_names_the_effective_local_model(monkeypatch):
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", "gemini-3.8-flash")
    report = compose_review_board_report(is_available=lambda v: v != "gemini", auth_ok=lambda _: True)
    assert next(s for s in report.excluded if s.vendor == "gemini").seat_key.startswith("gemini:gemini-3.8-flash:")


def test_configured_board_seat_wins_over_local_defaults(tmp_path):
    config = tmp_path / "boards.toml"
    config.write_text('default_board = "custom"\n[[boards]]\nname = "custom"\npurpose = "review"\n'
                      '[[boards.seats]]\nmodel = "gemini-3.8-flash"\neffort = "low"\nharness = "gemini"\n')
    result = load_boards(config, env={"PHASE_LOOP_GEMINI_MODEL": "gemini-4-argon"},
                         is_available=lambda _: True, auth_ok=lambda _: True)
    assert result.get().seats[0] == Seat(model="gemini-3.8-flash", effort="low", harness="gemini")
    assert next(s for s in result.get("default").seats if s.harness == "gemini").model == "gemini-4-argon"


@pytest.mark.parametrize("value", ["", "gpt-6-astra", "gemini-4-argon-high", "gemini-5-argon"])
def test_invalid_local_preference_fails_before_board_probes(monkeypatch, value):
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", value)
    calls = []
    with pytest.raises(ValueError, match="PHASE_LOOP_GEMINI_MODEL"):
        compose_review_board_report(is_available=lambda v: calls.append(v) or True, auth_ok=lambda _: True)
    assert calls == []
    with pytest.raises(ValueError, match="PHASE_LOOP_GEMINI_MODEL"):
        resolve_profile_for_executor(action="execute", executor="gemini")
    assert resolve_profile_for_executor(action="execute", executor="codex").model == "gpt-6.1-sol"


def test_unset_preference_keeps_authored_gemini_tiers(monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_GEMINI_MODEL", raising=False)
    assert resolve_model_class("gemini", "worker") == "gemini-3.8-flash-high"
    assert resolve_model_class("gemini", "implementer") == "gemini-3.8-flash"


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_display_argon_registration_and_rendering_match_canonical_argv(effort):
    assert DEFAULT_MODEL_REGISTRY.get("Gemini 4 Argon").effort_ceiling == "high"
    assert render_seat_invocation("gemini", "Gemini 4 Argon", effort).model == f"gemini-4-argon-{effort}"
    assert render_agy_model(f"Gemini 4 Argon ({effort.title()})") == f"gemini-4-argon-{effort}"


@pytest.mark.parametrize("model", ["Gemini 4 Argon (Max)", "Gemini 4 Argon (Thinking)"])
def test_unqualified_display_argon_effort_is_rejected(model):
    with pytest.raises(ValueError):
        render_agy_model(model)


def test_display_argon_rejects_a_separate_thinking_effort():
    with pytest.raises(ValueError):
        render_agy_model("Gemini 4 Argon", "thinking")


def test_argon_embedded_effort_conflict_is_rejected():
    with pytest.raises(ValueError, match="conflicts"):
        render_agy_model("Gemini 4 Argon (High)", "low")


# Port of agent-harness#1615 onto main: the preference must respect the shipped roster.
# Unset, planning/review run on Argon and implementation on the roster's Flash id; set,
# only the UNPINNED Gemini routes move.
_PLANNING = ("roadmap", "plan", "review")


def test_unset_preference_keeps_the_shipped_roster(monkeypatch):
    from phase_loop_runtime.profiles import EXECUTOR_MODEL_OVERRIDES

    monkeypatch.delenv("PHASE_LOOP_GEMINI_MODEL", raising=False)
    for action in _PLANNING:
        command = _launch(action)
        assert command[command.index("--model") + 1] == "gemini-4-argon-high", action
    for action in ("execute", "repair"):
        command = _launch(action)
        expected = render_agy_model(EXECUTOR_MODEL_OVERRIDES["gemini"][action], "high")
        assert command[command.index("--model") + 1] == expected, action
        assert "argon" not in expected


def test_set_preference_moves_only_unpinned_gemini_routes(monkeypatch):
    monkeypatch.delenv("PHASE_LOOP_GEMINI_MODEL", raising=False)
    codex_plan = resolve_profile_for_executor(action="plan", executor="codex")
    monkeypatch.setenv("PHASE_LOOP_GEMINI_MODEL", "gemini-3.8-flash")
    for action in _PLANNING:
        command = _launch(action)
        assert command[command.index("--model") + 1] == "gemini-3.8-flash-high", action
        pinned = _launch(action, model="gemini-4-argon")
        assert pinned[pinned.index("--model") + 1] == "gemini-4-argon-high", action
    plan_pin = _launch("plan", plan=ExecutionPolicyRule(model="gemini-4-argon"))
    assert plan_pin[plan_pin.index("--model") + 1] == "gemini-4-argon-high"
    assert resolve_profile_for_executor(action="plan", executor="codex") == codex_plan
