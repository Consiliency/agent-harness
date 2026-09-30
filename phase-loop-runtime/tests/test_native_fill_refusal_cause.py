"""agent-harness#1183: a native fill refused at binding names the leg's REAL outcome.

A claude seat that degraded before it could defer (for example on the staging free-space
floor) used to be refused with only "did not defer as under_claude_code", which sent the
operator chasing the routing instead of the environment. The refusal stays typed
(``native_fill_seat_not_deferred``) and still refuses; its detail now carries the leg's
status and closed-vocabulary detail.
"""
from __future__ import annotations

import pytest

from harden_tdd_guard import invoke_sanctioned_review_transport
from phase_loop_runtime import panel_invoker as pi
from test_native_claude_seat_fill import CC, _bound_fill, _deferred_leg, _fill, _mixed_board, _seat

FLOOR = "env_failure: staging filesystem below its free-space floor"


def _refusal(legs, fill) -> pi.NativeFillRefusal:
    with pytest.raises(pi.NativeFillRefusalError) as excinfo:
        pi.apply_native_leg_fills(legs, [fill])
    refusal = excinfo.value.refusal
    assert refusal.reason == pi.NATIVE_FILL_SEAT_NOT_DEFERRED and refusal.seat_key == fill.seat_key
    assert refusal.detail in str(excinfo.value)
    return refusal


def test_floor_degraded_seat_refusal_names_the_floor():
    seat = _seat()
    degraded = pi.PanelLegResult(leg="claude", status="DEGRADED", text="", detail=FLOOR, seat_key=seat.seat_key)
    refusal = _refusal([degraded], _fill(pi.NativeLegFill, seat))
    assert "DEGRADED" in refusal.detail and FLOOR in refusal.detail


def test_floor_degraded_seat_through_the_invoker_names_the_floor(tmp_path):
    """The matrix path: the claude seat's launch degrades on the floor, the other seats review."""
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    board = _mixed_board()

    def spawn(leg, art, **kw):
        if leg != "claude":
            return "OK", "Reviewed.\nAGREE"
        return "DEGRADED", "", FLOOR  # the 3-tuple form: a failure diagnostic bound for detail

    fill = _bound_fill(pi.NativeLegFill, board, board.seats[0], "review me\n")
    with pytest.raises(pi.NativeFillRefusalError) as excinfo:
        invoke_sanctioned_review_transport(
            board, "", spawn=spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
            native_leg_fills=[fill],
        )
    assert excinfo.value.refusal.reason == pi.NATIVE_FILL_SEAT_NOT_DEFERRED
    assert "DEGRADED" in str(excinfo.value) and FLOOR in str(excinfo.value)


def test_seat_with_a_valid_verdict_is_still_refused_and_says_so():
    seat = _seat()
    runtime = pi.PanelLegResult(leg="claude", status="OK", text="Runtime.\nDISAGREE", seat_key=seat.seat_key)
    legs = [runtime]
    refusal = _refusal(legs, _fill(pi.NativeLegFill, seat))
    assert "OK" in refusal.detail and "verdict" in refusal.detail
    assert legs[0] is runtime and runtime.text == "Runtime.\nDISAGREE"


def test_missing_leg_and_model_mismatch_name_their_cause():
    seat = _seat()
    other = _seat("gpt-5.6-sol", "codex")
    missing = _refusal([_deferred_leg(other)], _fill(pi.NativeLegFill, seat))
    assert "no leg" in missing.detail
    mismatch = _refusal([_deferred_leg(seat)], _fill(pi.NativeLegFill, seat, model="claude-sonnet-5"))
    assert "claude-sonnet-5" in mismatch.detail and seat.model in mismatch.detail


def test_deferred_seat_still_binds():
    seat = _seat()
    (bound,) = pi.apply_native_leg_fills([_deferred_leg(seat)], [_fill(pi.NativeLegFill, seat)])
    assert bound.status == "OK" and bound.detail == pi.NATIVE_FILL_DETAIL
