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


# native seat r1 BLOCKING 2: a resume must not require the seats to reproduce their text.
def test_a_native_resume_succeeds_when_seats_would_word_things_differently(tmp_path):
    calls: list[str] = []

    def drifting_spawn(leg: str, artifact: str) -> tuple[str, str]:
        calls.append(leg)
        return "OK", f"{leg} found: concern worded differently on call {len(calls)}\nAGREE"

    stream = tmp_path / "stream"

    def dispatch(**extra):
        return invoke_sanctioned_board_control(
            _fable_president_board(), "artifact", spawn=drifting_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"}, stream_dir=stream, **extra,
        )

    deferred = dispatch()
    pending = deferred.needs_native_president
    seats_run = len(calls)
    ruling_text = "\n".join(
        f"FINDING {f.split(':', 1)[0]}: DEFERRED — ruled" for f in deferred.president_findings
    ) + "\nFORCING DECISION: LAND"
    fill = {"rung": pending["rung"], "brief_digest": pending["brief_digest"],
            "findings_digest": pending["findings_digest"], "text": ruling_text}
    resumed = dispatch(native_president_fill=fill)
    assert resumed.president is not None and resumed.president.text == ruling_text
    assert resumed.president_findings == deferred.president_findings
    assert [leg.text for leg in resumed.legs] == [leg.text for leg in deferred.legs]
    assert len(calls) == seats_run, "a resume re-ran seats"
    assert (stream / "president.ruling.json").is_file()


def test_a_str_subclass_with_a_lying_eq_is_refused_before_use():
    from types import SimpleNamespace

    from phase_loop_runtime.president_operation import (
        PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH,
        run_president_operation,
    )

    class Liar(str):
        def __eq__(self, other):
            return True

        def __ne__(self, other):
            return False

        __hash__ = str.__hash__

    invoked: list[object] = []
    with pytest.raises(PresidentPolicyError) as excinfo:
        run_president_operation(
            brief="b", findings=("F001: x",),
            authorization=SimpleNamespace(operation=Liar("public_board_review.v1")),
            invoke=lambda m, p: invoked.append(m) or {"status": "ok", "text": ""},
            max_substantive_rounds=3,
        )
    assert excinfo.value.code == PRESIDENT_OPERATION_AUTHORIZATION_MISMATCH
    assert invoked == []


@pytest.mark.parametrize("fill", [["not", "a", "mapping"], "text"])
def test_a_malformed_fill_is_a_typed_refusal(tmp_path, fill):
    from phase_loop_runtime.president_operation import PRESIDENT_FILL_DIGEST_MISMATCH

    stream = tmp_path / "stream"
    invoke_sanctioned_board_control(
        _fable_president_board(), "artifact", spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
        base_env={"CLAUDECODE": "1"}, stream_dir=stream,
    )
    with pytest.raises(PresidentPolicyError) as excinfo:
        invoke_sanctioned_board_control(
            _fable_president_board(), "artifact", spawn=_ok_spawn,
            landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
            base_env={"CLAUDECODE": "1"}, stream_dir=stream, native_president_fill=fill,
        )
    assert excinfo.value.code == PRESIDENT_FILL_DIGEST_MISMATCH
    assert not (stream / "president.ruling.json").exists()


# native seat r2 BLOCKING: a resume is bound to the run it resumes.
def _defer(tmp_path, artifact="artifact", board=None):
    stream = tmp_path / "stream"
    deferred = invoke_sanctioned_board_control(
        board or _fable_president_board(), artifact, spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=_POLICY,
        base_env={"CLAUDECODE": "1"}, stream_dir=stream,
    )
    pending = deferred.needs_native_president
    text = "\n".join(
        f"FINDING {f.split(':', 1)[0]}: DEFERRED — ruled" for f in deferred.president_findings
    ) + "\nFORCING DECISION: LAND"
    fill = {"rung": pending["rung"], "brief_digest": pending["brief_digest"],
            "findings_digest": pending["findings_digest"], "text": text}
    return stream, fill


def _resume(stream, fill, artifact="artifact", board=None, policy=_POLICY):
    return invoke_sanctioned_board_control(
        board or _fable_president_board(), artifact, spawn=_ok_spawn,
        landing_tier=ReviewLandingTier.PRODUCTION_CODE, review_policy=policy,
        base_env={"CLAUDECODE": "1"}, stream_dir=stream, native_president_fill=fill,
    )


def _refused(fn):
    from phase_loop_runtime.president_operation import PRESIDENT_FILL_DIGEST_MISMATCH

    with pytest.raises(PresidentPolicyError) as excinfo:
        fn()
    assert excinfo.value.code == PRESIDENT_FILL_DIGEST_MISMATCH


def test_a_resume_on_a_different_artifact_is_refused(tmp_path):
    stream, fill = _defer(tmp_path, artifact="HEAD-A bundle")
    _refused(lambda: _resume(stream, fill, artifact="HEAD-B bundle"))
    assert not (stream / "president.ruling.json").exists()
    assert _resume(stream, fill, artifact="HEAD-A bundle").president is not None


def test_a_pending_request_from_a_different_board_is_refused(tmp_path):
    two_seat = Board(
        name="two", purpose="premerge-review",
        seats=tuple(s for s in DEFAULT_SEATS if s.harness in {"claude", "grok"}),
    )
    policy_two = panel_invoker.ReviewLandingPolicy(required_seats=("fable", "grok"), requires_president=True)
    stream = tmp_path / "stream"
    deferred = invoke_sanctioned_board_control(
        two_seat, "artifact", spawn=_ok_spawn, landing_tier=ReviewLandingTier.PRODUCTION_CODE,
        review_policy=policy_two, base_env={"CLAUDECODE": "1"}, stream_dir=stream,
    )
    pending = deferred.needs_native_president
    text = "\n".join(
        f"FINDING {f.split(':', 1)[0]}: DEFERRED — ruled" for f in deferred.president_findings
    ) + "\nFORCING DECISION: LAND"
    fill = {"rung": pending["rung"], "brief_digest": pending["brief_digest"],
            "findings_digest": pending["findings_digest"], "text": text}
    _refused(lambda: _resume(stream, fill))


@pytest.mark.parametrize("mutation", ["truncate_legs", "rung_to_sol", "rung_bogus"])
def test_a_pending_request_that_does_not_fit_this_board_is_refused(tmp_path, mutation):
    stream, fill = _defer(tmp_path)
    path = stream / panel_invoker.PRESIDENT_PENDING_FILENAME
    pending = json.loads(path.read_text())
    if mutation == "truncate_legs":
        pending["legs"] = pending["legs"][:1]
    elif mutation == "rung_to_sol":
        pending["rung"] = fill["rung"] = "sol"
    else:
        pending["rung"] = fill["rung"] = "nobody"
    path.write_text(json.dumps(pending))
    _refused(lambda: _resume(stream, fill))
    assert not (stream / "president.ruling.json").exists()


def test_a_pending_request_answers_exactly_once(tmp_path):
    stream, fill = _defer(tmp_path)
    assert _resume(stream, fill).president is not None
    _refused(lambda: _resume(stream, fill))


# codex r2 B2 / grok r2: the WHOLE pending record is self-consistent, including edits that
# finding extraction cannot see (a verdict line) and the prompt the native session ruled on.
@pytest.mark.parametrize("mutation", ["verdict_line", "prompt", "schema"])
def test_a_self_inconsistent_pending_record_is_refused(tmp_path, mutation):
    stream, fill = _defer(tmp_path)
    path = stream / panel_invoker.PRESIDENT_PENDING_FILENAME
    pending = json.loads(path.read_text())
    if mutation == "verdict_line":
        leg = pending["legs"][0]
        assert leg["text"].endswith("AGREE")
        leg["text"] = leg["text"][: -len("AGREE")] + "DISAGREE"
    elif mutation == "prompt":
        pending["prompt"] = pending["prompt"] + "\nF999: [x] an extra finding to rule on"
    else:
        pending["schema"] = "president.pending.v0"
    path.write_text(json.dumps(pending))
    _refused(lambda: _resume(stream, fill))
    assert not (stream / "president.ruling.json").exists()
