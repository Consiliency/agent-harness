"""The panel's default Gemini seat is Gemini 4 Argon (``gemini-4-argon``).

Every consumer of the panel default must LAUNCH the new id, not merely spell it
(agent-harness#777): the board seat, the legacy per-leg default, the composed review
board, every built-in preset, the HARDEN broker route, the brokered agy argv, the
review-policy seat alias, and the president ladder's ``gemini`` rung. The previous
default, ``gemini-3.8-flash``, stays an accepted explicit seat.
"""

from __future__ import annotations

import pytest

import phase_loop_runtime.panel_invoker as pi
from phase_loop_runtime.advisor_board import backing, presets
from phase_loop_runtime.advisor_board.composition import compose_review_board
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
from phase_loop_runtime.advisor_board.harness_mapping import (
    agy_model_effort,
    render_agy_model,
    render_seat_invocation,
)
from phase_loop_runtime.advisor_board.registries import DEFAULT_MODEL_REGISTRY
from phase_loop_runtime.advisor_board.schema import Board, Seat
from phase_loop_runtime.president_adapter import seat_for_rung

ARGON = "gemini-4-argon"  # model-id-source: test pins the panel default under test
ARGON_MEDIUM = "gemini-4-argon-medium"  # model-id-source: test pins the rendered agy id
FLASH = "gemini-3.8-flash"  # model-id-source: test pins the prior default staying accepted


def _gemini_seats(board: Board) -> list[Seat]:
    return [seat for seat in board.seats if seat.harness == "gemini"]


def test_default_board_gemini_seat_is_argon_medium():
    seat, = _gemini_seats(DEFAULT_BOARD)
    assert (seat.model, seat.effort) == (ARGON, "medium")
    assert render_seat_invocation("gemini", seat.model, seat.effort).model == ARGON_MEDIUM


def test_legacy_panel_leg_default_is_argon_medium():
    # invoke_panel (governed review / pre-merge) reads DEFAULT_LEG_MODELS with no override.
    assert pi.DEFAULT_LEG_MODELS["gemini"] == ARGON_MEDIUM


def test_composed_review_board_seats_argon():
    board = compose_review_board(is_available=lambda _h: True, auth_ok=lambda _h: True)
    seats = _gemini_seats(board)
    assert seats and all((s.model, s.effort) == (ARGON, "medium") for s in seats)


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
def test_every_builtin_preset_gemini_seat_is_argon(name):
    for seat in _gemini_seats(presets.PRESETS[name]):
        assert seat.model == ARGON, (name, seat.seat_key)


def test_harden_broker_route_resolves_argon():
    assert backing.harden_subscription_model("gemini", ARGON, "medium") == ARGON_MEDIUM
    assert backing.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["gemini"] == ARGON_MEDIUM
    assert DEFAULT_MODEL_REGISTRY.get(ARGON).default_lane == "gemini"


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_agy_renders_argon_with_effort_in_the_id(effort):
    # agy embeds effort in the model id; Argon offers the same low/medium/high ladder.
    assert render_agy_model(ARGON, effort) == f"{ARGON}-{effort}"
    assert render_agy_model(f"{ARGON}-{effort}") == f"{ARGON}-{effort}"
    assert agy_model_effort(f"{ARGON}-{effort}") == effort


def test_unknown_gemini_family_still_fails_loud():
    with pytest.raises(ValueError, match="unmapped gemini model id"):
        render_agy_model("gemini-4-bogus")
    with pytest.raises(ValueError):
        backing.harden_subscription_model("gemini", "gemini-4-bogus", "medium")


def test_brokered_heartbeat_argv_launches_argon():
    seat, = _gemini_seats(DEFAULT_BOARD)
    route = backing.harden_subscription_model("gemini", seat.model, seat.effort)
    argv = pi._brokered_gemini_command(model=route, deadline_s=0.0, monitoring_policy="heartbeat_only")
    assert argv[argv.index("--model") + 1] == ARGON_MEDIUM


def test_review_policy_and_president_rung_find_the_argon_seat():
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[ARGON] == "gemini"
    seat = seat_for_rung(DEFAULT_BOARD, "gemini")
    assert seat is not None and seat.model == ARGON
    # The default board satisfies the four-seat review policy without caller aliases.
    pi._validate_review_board_policy(
        DEFAULT_BOARD, pi.ReviewLandingPolicy(("sol", "gemini", "fable", "grok"), False), None
    )


def test_prior_default_stays_an_accepted_explicit_seat():
    assert DEFAULT_MODEL_REGISTRY.get(FLASH).default_lane == "gemini"
    assert backing.harden_subscription_model("gemini", FLASH, "medium") == "gemini-3.8-flash-medium"
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[FLASH] == "gemini"
    board = Board(name="explicit-flash", purpose="premerge-review",
                  seats=(Seat(model=FLASH, effort="medium", harness="gemini", lens="alternative-approach"),))
    assert seat_for_rung(board, "gemini").model == FLASH
    pi._validate_review_board_policy(board, pi.ReviewLandingPolicy(("gemini",), False), None)
