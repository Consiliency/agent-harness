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


def test_cli_reports_a_binding_refusal_as_a_native_fill_refusal(tmp_path, monkeypatch):
    """The operator surface: a refusal raised at binding is not relabeled as an artifact-staging
    failure; it prints the typed reason and the seat's real outcome."""
    import json
    from pathlib import Path

    from test_advisor_board_advisory_cli_802 import _BUNDLE, _Run, _repo_root

    bundle = tmp_path / "bundle.md"
    bundle.write_text(_BUNDLE, encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir(_repo_root())
    fill_dir = tmp_path / "fills"
    rc, out, err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--emit-native-request", "--native-fill-dir", str(fill_dir), "--json"])
    assert rc == 0, err
    request = json.loads(out)
    request_dir = Path(request["request_path"]).parent
    (request_dir / pi.NATIVE_FILL_REVIEW_FILE).write_text("Reviewed.\nAGREE\n", encoding="utf-8")

    run = _Run(monkeypatch)
    detail = f"seat {request['seat_key']} did not defer as under_claude_code with a fill request: the seat returned DEGRADED ({FLOOR})"

    def refuse(board, artifact, **kwargs):
        raise pi.NativeFillRefusalError(pi.NativeFillRefusal(pi.NATIVE_FILL_SEAT_NOT_DEFERRED, detail, request["seat_key"]))

    monkeypatch.setattr(pi, "invoke_board", refuse)
    rc, out, err = run(["advisor-board", str(bundle), "--native-leg", f"claude={request_dir}", "--json"])
    assert rc == 2
    assert f"native fill refused [{pi.NATIVE_FILL_SEAT_NOT_DEFERRED}]" in err and FLOOR in err
    assert "could not stage the artifact" not in err
    payload = json.loads(out)
    assert payload["status"] == "native_fill_refused"
    assert payload["usable"] is False
    assert payload["refusal"]["reason"] == pi.NATIVE_FILL_SEAT_NOT_DEFERRED
    assert FLOOR in payload["refusal"]["detail"]
    assert payload["board_wide_failure"] is None


def test_board_wide_staging_floor_failure_is_named_in_refusal_and_error_legs(tmp_path):
    """When every seat degrades on the staging floor, the refusal names the board-wide
    failure and attaches all legs to `NativeFillRefusalError`."""
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    board = _mixed_board()

    def spawn(leg, art, **kw):
        return "DEGRADED", "", FLOOR

    fill = _bound_fill(pi.NativeLegFill, board, board.seats[0], "review me\n")
    with pytest.raises(pi.NativeFillRefusalError) as excinfo:
        invoke_sanctioned_review_transport(
            board, "", spawn=spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
            native_leg_fills=[fill],
        )
    assert excinfo.value.refusal.reason == pi.NATIVE_FILL_SEAT_NOT_DEFERRED
    assert f"all {len(board.seats)} seats failed with {FLOOR}" in excinfo.value.refusal.detail
    assert len(excinfo.value.legs) == len(board.seats)
    assert all(leg.detail == FLOOR for leg in excinfo.value.legs)


def test_cli_board_wide_unknown_failure_emits_json_summary_and_retains_leg_logs(tmp_path, monkeypatch):
    """Reproduces the 2026-11-08 partial-clone failure on agent-harness#1183: when every
    seat fails with per-seat leg logs, `advisor-board --native-leg ... --json` prints a
    top-level board-wide failure notice, emits structured JSON on stdout, and keeps the
    referenced leg-log files instead of deleting them in `finally`."""
    import json
    from pathlib import Path

    from test_advisor_board_advisory_cli_802 import _BUNDLE, _Run, _repo_root

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    bundle = tmp_path / "bundle.md"
    bundle.write_text(_BUNDLE, encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir(_repo_root())
    fill_dir = tmp_path / "fills"
    rc, out, err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--emit-native-request", "--native-fill-dir", str(fill_dir), "--json"])
    assert rc == 0, err
    request = json.loads(out)
    request_dir = Path(request["request_path"]).parent
    (request_dir / pi.NATIVE_FILL_REVIEW_FILE).write_text("Reviewed.\nAGREE\n", encoding="utf-8")

    run = _Run(monkeypatch)
    created_logs: list[Path] = []

    def refuse_all_seats(board, artifact, **kwargs):
        leg_log_dir = Path(kwargs["leg_log_dir"])
        failed_legs = []
        for seat in board.seats:
            detail = pi._resolve_leg_detail(
                pi._LegFailure(pi._UNKNOWN_DETAIL, raw="fatal: partial clone exit 128\n", unknown=True, rc=128),
                leg_log_dir,
                seat.seat_key,
            )
            failed_legs.append(
                pi.PanelLegResult(leg=seat.harness, status="DEGRADED", text="", detail=detail, seat_key=seat.seat_key)
            )
        created_logs.extend(sorted((leg_log_dir / "leg-logs").glob("*.log")))
        fills = kwargs["native_leg_fills"]
        pi.apply_native_leg_fills(failed_legs, fills)

    monkeypatch.setattr(pi, "invoke_board", refuse_all_seats)
    rc, out, err = run(["advisor-board", str(bundle), "--native-leg", f"claude={request_dir}", "--json"])
    assert rc == 2
    assert "advisor-board: board-wide failure:" in err
    assert f"all {len(created_logs)} seats failed/degraded" in err
    assert "leg failure logs kept in " in err
    payload = json.loads(out)
    assert payload["status"] == "native_fill_refused"
    assert payload["usable"] is False
    assert payload["refusal"]["reason"] == pi.NATIVE_FILL_SEAT_NOT_DEFERRED
    assert payload["board_wide_failure"] is not None
    assert f"all {len(created_logs)} seats failed/degraded; inspect retained leg logs" == payload["board_wide_failure"]
    assert "staging" not in payload["board_wide_failure"]
    assert len(payload["legs"]) == len(created_logs)
    assert all(path.is_file() for path in created_logs), "leg logs must be retained on NativeFillRefusalError"


def test_apply_native_leg_fills_keeps_original_legs_snapshot_when_later_fill_refuses():
    """P2 regression: when an earlier fill binds or degrades tentatively before a later
    fill refuses, `NativeFillRefusalError.legs` and the board-wide summary reflect the
    original pre-fill legs, never tentative replacements."""
    seat_a = _seat("claude-opus-5", "claude")
    seat_b = _seat("claude-sonnet-5", "claude")
    original_a = _deferred_leg(seat_a)
    original_b = pi.PanelLegResult(leg="claude", status="DEGRADED", text="", detail=FLOOR, seat_key=seat_b.seat_key)
    legs = [original_a, original_b]

    # Case 1: first fill has a conforming verdict (tentatively OK), second fill refuses.
    with pytest.raises(pi.NativeFillRefusalError) as ok_exc:
        pi.apply_native_leg_fills(legs, [_fill(pi.NativeLegFill, seat_a), _fill(pi.NativeLegFill, seat_b)])
    assert ok_exc.value.legs == (original_a, original_b)
    assert ok_exc.value.legs[0].status == "UNAVAILABLE"

    # Case 2: first fill is verdict-less (would tentatively turn DEGRADED); board-wide summary
    # must stay None because original seat_a deferred cleanly.
    with pytest.raises(pi.NativeFillRefusalError) as bad_exc:
        pi.apply_native_leg_fills(
            legs,
            [_fill(pi.NativeLegFill, seat_a, text="no verdict"), _fill(pi.NativeLegFill, seat_b)],
        )
    assert bad_exc.value.legs == (original_a, original_b)
    assert pi.board_wide_failure_summary(bad_exc.value.legs) is None
    assert "all 2 seats" not in bad_exc.value.refusal.detail


def test_cli_preflight_native_fill_refusal_sanitizes_unvalidated_request_fields_in_json(
    tmp_path, monkeypatch,
):
    """P3 regression: preflight refusal JSON uses fixed closed-vocabulary detail and drops
    unvalidated seat_key / model strings from request.json."""
    import json

    from test_advisor_board_advisory_cli_802 import _BUNDLE, _Run, _repo_root

    bundle = tmp_path / "bundle.md"
    bundle.write_text(_BUNDLE, encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir(_repo_root())
    bad_dir = tmp_path / "bad-fill"
    bad_dir.mkdir()
    untrusted_seat = "claude:UNTRUSTED-INJECTED-SEAT"
    untrusted_model = "UNTRUSTED-INJECTED-MODEL"
    (bad_dir / "request.json").write_text(json.dumps({
        "request_id": "r1",
        "seat_key": untrusted_seat,
        "model": untrusted_model,
        "artifact_sha256": "a" * 64,
        "brief_sha256": "b" * 64,
        "composition_sha256": "c" * 64,
    }), encoding="utf-8")
    (bad_dir / pi.NATIVE_FILL_REVIEW_FILE).write_text("Reviewed.\nAGREE\n", encoding="utf-8")

    rc, out, err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--native-leg", f"claude={bad_dir}", "--json"])
    assert rc == 2
    assert f"native fill refused [{pi.NATIVE_FILL_SEAT_NOT_DEFERRED}]" in err
    payload = json.loads(out)
    assert payload["status"] == "native_fill_refused"
    assert payload["refusal"]["reason"] == pi.NATIVE_FILL_SEAT_NOT_DEFERRED
    assert payload["refusal"]["seat_key"] is None
    assert untrusted_seat not in out
    assert untrusted_model not in out


def test_cli_preflight_native_fill_refusal_emits_structured_json(tmp_path, monkeypatch):
    """Preflight native-fill refusals also emit structured JSON when `--json` is passed."""
    import json
    from pathlib import Path

    from test_advisor_board_advisory_cli_802 import _BUNDLE, _Run, _repo_root

    bundle = tmp_path / "bundle.md"
    bundle.write_text(_BUNDLE, encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir(_repo_root())
    fill_dir = tmp_path / "fills"
    rc, out, err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--emit-native-request", "--native-fill-dir", str(fill_dir), "--json"])
    assert rc == 0, err
    request = json.loads(out)
    request_dir = Path(request["request_path"]).parent
    (request_dir / pi.NATIVE_FILL_REVIEW_FILE).write_text("Reviewed.\nAGREE\n", encoding="utf-8")

    # Mutate bundle so preflight refuses with digest mismatch before any reviewer launch.
    bundle.write_text(_BUNDLE + "\nextra\n", encoding="utf-8")
    rc, out, err = _Run(monkeypatch)(
        ["advisor-board", str(bundle), "--native-leg", f"claude={request_dir}", "--json"])
    assert rc == 2
    assert f"native fill refused [{pi.NATIVE_FILL_DIGEST_MISMATCH}]" in err
    payload = json.loads(out)
    assert payload["status"] == "native_fill_refused"
    assert payload["usable"] is False
    assert payload["refusal"]["reason"] == pi.NATIVE_FILL_DIGEST_MISMATCH
    assert payload["board_wide_failure"] is None
    assert payload["legs"] == []
