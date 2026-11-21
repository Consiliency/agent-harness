"""The panel's default Gemini seat is Gemini 4 NEON (``gemini-4-neon``) at ``high``.

Every consumer of the panel default must LAUNCH the new id, not merely spell it
(agent-harness#777): the board seat, the legacy per-leg default, the composed review
board, every built-in preset, the HARDEN broker route, the brokered agy argv, the
review-policy seat alias, and the president ladder's ``gemini`` rung. The previous
default, ``gemini-4-argon``, and the one before it, ``gemini-3.8-flash``, stay accepted
explicit seats. agy lists ``gemini-4-neon-xhigh``; it is not admitted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import phase_loop_runtime.panel_invoker as pi
from phase_loop_runtime.launcher import build_gemini_command
from phase_loop_runtime.models import ModelSelection
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

NEON = "gemini-4-neon"  # model-id-source: test pins the panel default under test
NEON_HIGH = "gemini-4-neon-high"  # model-id-source: test pins the rendered agy id
ARGON = "gemini-4-argon"  # model-id-source: test pins the prior default staying accepted
ARGON_MEDIUM = "gemini-4-argon-medium"  # model-id-source: test pins the prior rendered agy id
FLASH = "gemini-3.8-flash"  # model-id-source: test pins an earlier default staying accepted


def _gemini_seats(board: Board) -> list[Seat]:
    return [seat for seat in board.seats if seat.harness == "gemini"]


def test_default_board_gemini_seat_is_neon_high():
    seat, = _gemini_seats(DEFAULT_BOARD)
    assert (seat.model, seat.effort) == (NEON, "high")
    assert render_seat_invocation("gemini", seat.model, seat.effort).model == NEON_HIGH


def test_legacy_panel_leg_default_is_neon_high():
    # invoke_panel (governed review / pre-merge) reads DEFAULT_LEG_MODELS with no override.
    assert pi.DEFAULT_LEG_MODELS["gemini"] == NEON_HIGH


def test_composed_review_board_seats_neon_high():
    board = compose_review_board(is_available=lambda _h: True, auth_ok=lambda _h: True)
    seats = _gemini_seats(board)
    assert seats and all((s.model, s.effort) == (NEON, "high") for s in seats)


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
def test_every_builtin_preset_gemini_seat_is_neon_high(name):
    for seat in _gemini_seats(presets.PRESETS[name]):
        assert (seat.model, seat.effort) == (NEON, "high"), (name, seat.seat_key)


def test_harden_broker_route_resolves_neon_high():
    assert backing.harden_subscription_model("gemini", NEON, "high") == NEON_HIGH
    assert backing.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["gemini"] == NEON_HIGH
    assert DEFAULT_MODEL_REGISTRY.get(NEON).default_lane == "gemini"
    assert DEFAULT_MODEL_REGISTRY.get(NEON).effort_ceiling == "high"


@pytest.mark.parametrize("model", [NEON, ARGON])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_agy_renders_neon_and_argon_with_effort_in_the_id(model, effort):
    # agy embeds effort in the model id; NEON is admitted on the same low/medium/high ladder.
    assert render_agy_model(model, effort) == f"{model}-{effort}"
    assert render_agy_model(f"{model}-{effort}") == f"{model}-{effort}"
    assert agy_model_effort(f"{model}-{effort}") == effort


def test_neon_xhigh_and_max_are_not_admitted():
    # agy lists gemini-4-neon-xhigh, but Gemini effort stays capped at high.
    with pytest.raises(ValueError, match="unmapped gemini model id"):
        render_agy_model("gemini-4-neon-xhigh")
    with pytest.raises(ValueError):
        render_agy_model(NEON, "xhigh")
    with pytest.raises(ValueError):
        render_agy_model(NEON, "max")
    with pytest.raises(ValueError):
        backing.harden_subscription_model("gemini", "gemini-4-neon-xhigh", None)
    # A board seat asking for max is refused by the agy renderer, exactly as for Argon
    # (executor policy clamps max to high before rendering; see test_gemini_neon_planning).
    for model in (NEON, ARGON):
        with pytest.raises(ValueError, match="requires a supported agy effort"):
            render_seat_invocation("gemini", model, "max")


@pytest.mark.parametrize("model", [
    "gemini-4-pro", "gemini-3-flash", "gemini-38-flash", "gemini-04-argon", "gemini-4.1-argon",
    "gemini-4-bogus-high", "gemini-4-pro-high", "gemini-04-argon-medium", "gemini-4.1-argon-high",
    "gemini-04-neon", "gemini-4.1-neon-high", "gemini-4-other-medium", "gemini-4-neons-high",
])
def test_grammar_admits_gemini_4_neon_and_argon_only(model):
    # Only the literals ``gemini-4-neon`` and ``gemini-4-argon`` lack a minor version; every malformed or
    # unregistered id still fails loud on the board renderer AND the launcher route.
    with pytest.raises(ValueError, match="unmapped gemini model id"):
        render_agy_model(model)
    selection = ModelSelection(profile="execute", model=model, effort="high")
    with pytest.raises(ValueError, match="unmapped gemini model id"):
        build_gemini_command(Path("/repo"), selection, action="execute", context_file="ctx.md")


def test_unknown_gemini_family_still_fails_loud():
    with pytest.raises(ValueError, match="unmapped gemini model id"):
        render_agy_model("gemini-4-bogus")
    with pytest.raises(ValueError):
        backing.harden_subscription_model("gemini", "gemini-4-bogus", "medium")


def test_brokered_heartbeat_argv_launches_neon_high():
    seat, = _gemini_seats(DEFAULT_BOARD)
    route = backing.harden_subscription_model("gemini", seat.model, seat.effort)
    argv = pi._brokered_gemini_command(model=route, deadline_s=0.0, monitoring_policy="heartbeat_only")
    assert argv[argv.index("--model") + 1] == NEON_HIGH


def test_review_policy_and_president_rung_find_the_neon_seat():
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[NEON] == "gemini"
    seat = seat_for_rung(DEFAULT_BOARD, "gemini")
    assert seat is not None and seat.model == NEON
    # The default board satisfies the four-seat review policy without caller aliases.
    pi._validate_review_board_policy(
        DEFAULT_BOARD, pi.ReviewLandingPolicy(("sol", "gemini", "fable", "grok"), False), None
    )


def test_argon_display_alias_stays_registered():
    assert DEFAULT_MODEL_REGISTRY.get("Gemini 4 Argon").default_lane == "gemini"
    assert backing.harden_subscription_model("gemini", "Gemini 4 Argon", "medium") == ARGON_MEDIUM


def test_argon_stays_an_accepted_explicit_seat():
    model = ARGON
    assert DEFAULT_MODEL_REGISTRY.get(model).default_lane == "gemini"
    assert backing.harden_subscription_model("gemini", model, "medium") == ARGON_MEDIUM
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[ARGON] == "gemini"
    board = Board(name="explicit-argon", purpose="premerge-review",
                  seats=(Seat(model=model, effort="medium", harness="gemini", lens="alternative-approach"),))
    assert seat_for_rung(board, "gemini").model == model
    pi._validate_review_board_policy(board, pi.ReviewLandingPolicy(("gemini",), False), None)
    route = backing.harden_subscription_model("gemini", model, "medium")
    argv = pi._brokered_gemini_command(model=route, deadline_s=0.0, monitoring_policy="heartbeat_only")
    assert argv[argv.index("--model") + 1] == ARGON_MEDIUM


def test_earlier_default_stays_an_accepted_explicit_seat():
    assert DEFAULT_MODEL_REGISTRY.get(FLASH).default_lane == "gemini"
    assert backing.harden_subscription_model("gemini", FLASH, "medium") == "gemini-3.8-flash-medium"
    assert pi.DEFAULT_REVIEW_SEAT_ALIASES[FLASH] == "gemini"
    board = Board(name="explicit-flash", purpose="premerge-review",
                  seats=(Seat(model=FLASH, effort="medium", harness="gemini", lens="alternative-approach"),))
    assert seat_for_rung(board, "gemini").model == FLASH
    pi._validate_review_board_policy(board, pi.ReviewLandingPolicy(("gemini",), False), None)


def test_the_profiles_panel_leg_comment_names_the_live_leg_defaults():
    # The tier-bridge comment in profiles.py restates DEFAULT_LEG_MODELS; it went stale once
    # (it named 3.8 Flash while the leg ran Argon). Keep it naming the actual per-leg values.
    import phase_loop_runtime.profiles as profiles

    text = Path(profiles.__file__).read_text(encoding="utf-8")
    line = next(row for row in text.splitlines() if "panel_invoker.DEFAULT_LEG_MODELS =" in row)
    named = line.split("DEFAULT_LEG_MODELS =", 1)[1].split(")", 1)[0]
    assert [part.strip() for part in named.split("/")] == [
        pi.DEFAULT_LEG_MODELS[leg] for leg in ("claude", "codex", "gemini", "grok")
    ]
