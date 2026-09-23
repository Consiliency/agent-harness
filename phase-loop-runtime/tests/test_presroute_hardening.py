"""PRESROUTE review-round hardening (agent-harness#998 r1, codex BLOCKING 1 and 2).

Not part of the SL-0 frozen corpus.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from harden_tdd_guard import invoke_sanctioned_board_control
from phase_loop_runtime import panel_invoker, president_adapter
from phase_loop_runtime.advisor_board import backing
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD, DEFAULT_SEATS
from phase_loop_runtime.advisor_board.schema import Board
from phase_loop_runtime.panel_invoker import PresidentPolicyError, ReviewLandingTier


def _ok_spawn(leg: str, artifact: str) -> tuple[str, str]:
    return "OK", f"{leg} found: the {leg} concern\nAGREE"


def _fable_president_board() -> Board:
    return Board(
        name="fable-president",
        purpose="premerge-review",
        seats=tuple(seat for seat in DEFAULT_SEATS if seat.harness != "codex"),
    )


_POLICY = panel_invoker.ReviewLandingPolicy(
    required_seats=("fable", "gemini", "grok"), requires_president=True
)


# codex BLOCKING 1: every launch uses the revalidated authorization's route; a seat the
# authorization does not route is refused WITHOUT launching -- no fallback to the seat's
# own model.
@pytest.mark.parametrize("rung", ["fable", "sol", "grok", "gemini"])
def test_a_rung_without_an_authorized_route_never_launches(tmp_path, rung):
    real = backing._president_routes

    def routes_without_rung(board):
        seat = president_adapter.seat_for_rung(DEFAULT_BOARD, rung)
        return tuple(r for r in real(board) if r[0] != seat.harness)

    launched: list[object] = []

    def forbid(*args, **kwargs):
        launched.append(args)
        raise AssertionError("launched without an authorized route")

    with patch.object(backing, "_president_routes", routes_without_rung), patch.object(
        panel_invoker, "_run_claude_tui_session", forbid
    ), patch.object(panel_invoker, "_exec_leg", forbid), patch.object(
        panel_invoker, "launch_provider", forbid
    ):
        seam = president_adapter.build_president_invoke(
            DEFAULT_BOARD, repo_dir=str(tmp_path), base_env={}
        )
        response = seam(rung, "F001: [x] y")
    assert launched == []
    assert response["status"] == "failed"
    assert response["code"] == "president_invocation_failed"
    assert "no authorized president route" in response["detail"]


# codex BLOCKING 2: the native defer -> resume is DURABLE; without a stream there is no
# pending request to check a resume against and nowhere to write the ruling.
def test_a_native_deferral_without_a_stream_dir_is_refused():
    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_sanctioned_board_control(
            _fable_president_board(), "artifact", spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"},
        )
    assert excinfo.value.code == panel_invoker.PRESIDENT_NATIVE_FILL_STREAM_REQUIRED


def test_a_native_fill_without_a_stream_dir_is_refused_and_persists_nothing():
    fill = {"rung": "fable", "brief_digest": "b" * 64, "findings_digest": "f" * 64,
            "text": "FINDING F001: DEFERRED — x\nFORCING DECISION: LAND"}
    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_sanctioned_board_control(
            _fable_president_board(), "artifact", spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"}, native_president_fill=fill,
        )
    assert excinfo.value.code == panel_invoker.PRESIDENT_NATIVE_FILL_STREAM_REQUIRED


@pytest.mark.parametrize("pending", [None, "{not json", "[]"])
def test_a_fill_without_a_valid_persisted_pending_request_is_refused(tmp_path, pending):
    stream = tmp_path / "stream"
    stream.mkdir()
    if pending is not None:
        (stream / panel_invoker.PRESIDENT_PENDING_FILENAME).write_text(pending, encoding="utf-8")

    def dispatch(**extra):
        return invoke_sanctioned_board_control(
            _fable_president_board(), "artifact", spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"}, stream_dir=stream, **extra,
        )

    # Derive the digests THIS run would produce (from a throwaway stream) so the fill
    # would match the current request -- only the persisted pending is missing/bad.
    probe = tmp_path / "probe"
    request = invoke_sanctioned_board_control(
        _fable_president_board(), "artifact", spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
        base_env={"CLAUDECODE": "1"}, stream_dir=probe,
    ).needs_native_president
    fill = {"rung": request["rung"], "brief_digest": request["brief_digest"],
            "findings_digest": request["findings_digest"],
            "text": "FINDING F001: DEFERRED — x\nFORCING DECISION: LAND"}
    with pytest.raises(PresidentPolicyError) as excinfo:
        dispatch(native_president_fill=fill)
    from phase_loop_runtime.president_operation import PRESIDENT_FILL_DIGEST_MISMATCH

    assert excinfo.value.code == PRESIDENT_FILL_DIGEST_MISMATCH
    assert not (stream / "president.ruling.json").exists()
    assert json.loads((probe / panel_invoker.PRESIDENT_PENDING_FILENAME).read_text())["rung"] == "fable"
