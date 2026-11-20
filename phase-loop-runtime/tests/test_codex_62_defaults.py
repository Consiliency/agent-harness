"""The OpenAI defaults are GPT-6.2 Astra and GPT-6.2 Sol (owner decision D1, 2026-11-19).

``gpt-6.2-astra`` is the codex heavy model (roadmap / plan / review, ``skill-maintenance``
and the ``command`` executor's ``DEFAULT_PROFILES`` fallback) and the panel's OpenAI seat
on every shipped board. ``gpt-6.2-sol`` is the codex regular tier, so codex execute and
repair run it at medium. Every consumer must LAUNCH the new id, not merely spell it
(agent-harness#777): the executor argv, the class map, the tier matrix, the panel leg, the
composed and named boards, the HARDEN broker route and the brokered codex argv, the
review-seat alias and the president's ``sol`` rung. The prior defaults ``gpt-6-astra`` and
``gpt-6.1-sol`` stay registered explicit seats, so rollback is a revert.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import phase_loop_runtime.panel_invoker as pi
from phase_loop_runtime import profiles
from phase_loop_runtime.advisor_board import backing, presets
from phase_loop_runtime.advisor_board.composition import compose_review_board
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD, DEFAULT_SEAT_RENDERED_MODEL
from phase_loop_runtime.advisor_board.harness_mapping import render_seat_invocation
from phase_loop_runtime.advisor_board.registries import DEFAULT_MODEL_REGISTRY
from phase_loop_runtime.advisor_board.schema import Board, Seat
from phase_loop_runtime.launcher import build_codex_command
from phase_loop_runtime.president_adapter import seat_for_rung

ASTRA = "gpt-6.2-astra"  # model-id-source: test pins the codex heavy / panel default under test
SOL = "gpt-6.2-sol"  # model-id-source: test pins the codex implementer default under test
PRIOR_ASTRA = "gpt-6-astra"  # model-id-source: test pins the prior heavy default staying accepted
PRIOR_SOL = "gpt-6.1-sol"  # model-id-source: test pins the prior implementer default staying accepted


def _codex_seats(board: Board) -> list[Seat]:
    return [seat for seat in board.seats if seat.harness == "codex"]


# --------------------------------------------------------------------- executor routes


@pytest.mark.parametrize(("action", "expected"), [
    ("roadmap", (ASTRA, "high")),
    ("plan", (ASTRA, "high")),
    ("review", (ASTRA, "high")),
    ("execute", (SOL, "medium")),
    ("repair", (SOL, "medium")),
])
def test_codex_executor_defaults(action, expected):
    selection = profiles.resolve_profile_for_executor(action=action, executor="codex")
    assert (selection.model, selection.effort) == expected


@pytest.mark.parametrize(("action", "model", "effort"), [
    ("plan", ASTRA, "high"),
    ("execute", SOL, "medium"),
])
def test_codex_argv_launches_the_new_ids(action, model, effort):
    selection = profiles.resolve_profile_for_executor(action=action, executor="codex")
    argv = build_codex_command(Path("/repo"), selection, "prompt")
    assert argv[argv.index("--model") + 1] == model
    assert f'model_reasoning_effort="{effort}"' in argv


def test_codex_class_map():
    assert profiles.resolve_model_class("codex", "planner") == ASTRA
    assert profiles.resolve_model_class("codex", "reviewer") == ASTRA
    assert profiles.resolve_model_class("codex", "implementer") == SOL


def test_codex_tier_matrix():
    assert profiles.CODEX_HEAVY_MODEL == profiles.OPENAI_HEAVY_MODEL == ASTRA
    assert profiles.CODEX_REGULAR_MODEL == profiles.OPENAI_IMPLEMENTER_MODEL == SOL
    assert profiles.resolve("plan", "codex").model_id == ASTRA
    assert profiles.resolve("review", "codex").model_id == ASTRA
    assert profiles.resolve("execute", "codex").model_id == SOL


def test_collateral_default_profiles_consumers_follow_the_heavy_model():
    # maintain-skills resolves "skill-maintenance" straight from DEFAULT_PROFILES.
    selection = profiles.resolve_profile("skill-maintenance")
    assert (selection.model, selection.effort) == (ASTRA, "high")
    # The `command` executor has no tier vendor, so it stays on DEFAULT_PROFILES.
    for action in ("roadmap", "plan", "execute", "repair", "review"):
        selection = profiles.resolve_profile_for_executor(action=action, executor="command")
        assert selection.model == ASTRA, action


# --------------------------------------------------------------------- panel and boards


def test_panel_leg_and_default_board_seat():
    assert pi.DEFAULT_LEG_MODELS["codex"] == ASTRA
    assert DEFAULT_SEAT_RENDERED_MODEL["codex"] == ASTRA
    seat, = _codex_seats(DEFAULT_BOARD)
    assert (seat.model, seat.effort, seat.lens) == (ASTRA, "high", "red-team")
    inv = render_seat_invocation("codex", seat.model, seat.effort)
    assert (inv.model, inv.effort_args) == (ASTRA, ("-c", "model_reasoning_effort=high"))


def test_composed_code_review_board_seats_astra():
    board = compose_review_board(is_available=lambda _h: True, auth_ok=lambda _h: True)
    seats = _codex_seats(board)
    assert seats and all((s.model, s.effort, s.lens) == (ASTRA, "high", "red-team") for s in seats)


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
def test_every_builtin_preset_codex_seat_is_astra(name):
    for seat in _codex_seats(presets.PRESETS[name]):
        assert seat.model == ASTRA, (name, seat.seat_key)


def test_harden_codex_route_and_brokered_argv():
    assert backing.harden_subscription_model("codex", ASTRA, "high") == ASTRA
    assert backing.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["codex"] == ASTRA
    argv = pi._brokered_codex_command(
        model=None, out_dir=Path("/out"), out_file=Path("/out/last.txt"),
        codex_effort_args=("-c", "model_reasoning_effort=high"),
    )
    assert argv[argv.index("--model") + 1] == ASTRA


def test_review_policy_and_president_sol_rung_find_the_astra_seat():
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[ASTRA] == "sol"
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[SOL] == "sol"
    assert "sol" in pi.PRESIDENT_LADDER
    seat = seat_for_rung(DEFAULT_BOARD, "sol")
    assert seat is not None and seat.model == ASTRA
    pi._validate_review_board_policy(
        DEFAULT_BOARD, pi.ReviewLandingPolicy(("sol", "gemini", "fable", "grok"), False), None
    )


# --------------------------------------------------------------------- registration


@pytest.mark.parametrize("model", [ASTRA, SOL])
def test_new_ids_are_registered_codex_seats(model):
    spec = DEFAULT_MODEL_REGISTRY.get(model)
    assert (spec.default_lane, spec.effort_ceiling) == ("codex", "max")
    assert spec.runnable_by == ("codex", "opencode")
    inv = render_seat_invocation("codex", model, "max")
    assert (inv.model, inv.effort_args) == (model, ("-c", "model_reasoning_effort=xhigh"))


def test_gpt_6_2_sol_is_not_a_board_default():
    assert SOL not in {s.model for board in presets.PRESETS.values() for s in board.seats}
    assert SOL not in {s.model for s in DEFAULT_BOARD.seats}


@pytest.mark.parametrize("model", [PRIOR_ASTRA, PRIOR_SOL])
def test_prior_defaults_stay_accepted_explicit_seats(model):
    spec = DEFAULT_MODEL_REGISTRY.get(model)
    assert (spec.default_lane, spec.effort_ceiling) == ("codex", "max")
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[model] == "sol"
    assert backing.harden_subscription_model("codex", model, "high") == model
    board = Board(name="explicit-prior", purpose="premerge-review",
                  seats=(Seat(model=model, effort="high", harness="codex", lens="red-team"),))
    assert seat_for_rung(board, "sol").model == model
    pi._validate_review_board_policy(board, pi.ReviewLandingPolicy(("sol",), False), None)


@pytest.mark.parametrize("model", [ASTRA, SOL])
def test_new_ids_stay_openai_family_only(model):
    from phase_loop_runtime.advisor_board.matrix import default_matrix

    matrix = default_matrix(probe=lambda _cli: True, env={})
    assert matrix.is_valid(model, "codex")[0]
    assert not matrix.is_valid(model, "claude")[0]
    assert not matrix.is_valid(model, "grok")[0]
