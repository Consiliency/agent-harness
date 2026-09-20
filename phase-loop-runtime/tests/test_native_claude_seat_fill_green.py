"""REVIEWTRUTH early slice — PR-2 GREEN-side regressions (the RED lane's NOT CLAIMED HERE ledger).

These are not falsifiers of the RED lane (which is frozen, EC-REVIEWTRUTH-0); they pin the
implementation's behaviour on the items the lane deliberately left to PR-2, plus the surviving
mutant the PR-2 board named (provenance attach as a no-op).
"""
from __future__ import annotations

import os
import tempfile
import unittest.mock
from pathlib import Path

import pytest

from harden_tdd_guard import invoke_sanctioned_review_transport
from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import legible_evidence as le
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import roadmap_assumptions as ra
from phase_loop_runtime.advisor_board import Board, Seat
from phase_loop_runtime.advisor_board.backing import BACKING_HOMEBREW
from test_native_claude_seat_fill import SUBJECT, _deferred_leg, _fill, _mixed_board, _seat, _typed_deferral_spawn

CC = {"CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")}
FABLE = "claude-fable-5"


def test_provenance_is_attached_to_a_bound_fill():
    """Board r1 (gemini): a no-op provenance attach must not survive."""
    seat = _seat()
    (bound,) = pi.apply_native_leg_fills([_deferred_leg(seat)], [_fill(pi.NativeLegFill, seat)])
    prov = getattr(bound, "_native_fill", None)
    assert isinstance(prov, dict) and prov["request_id"] == "r1" and prov["filled_by"] == "claude-code"
    assert prov["artifact_sha256"] == "a" * 64 and prov["composition_sha256"] == "c" * 64


def test_backing_refused_claude_seat_is_not_fillable():
    """`tui_backing_required` is a refusal, never a deferral: preflight refuses, apply raises."""
    other_backing = [b for b in ("omnigent", "gateway", "api") if b != BACKING_HOMEBREW][0]
    try:
        seat = Seat(model=FABLE, effort="max", harness="claude", lens="correctness", backing=other_backing)
    except Exception:
        pytest.skip("Seat rejects a non-homebrew backing at construction on this build")
    board = Board(name="b", purpose="premerge-review", seats=(seat, _seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")))
    fill = _fill(pi.NativeLegFill, seat)
    refusal = pi.preflight_native_leg_fills(board, [fill], artifact_sha256="a" * 64, brief_sha256="b" * 64,
                                            composition_sha256="c" * 64, env=dict(CC))
    assert refusal is not None and refusal.reason == pi.NATIVE_FILL_SEAT_NOT_DEFERRED
    refused = pi.PanelLegResult(leg="claude", status="UNAVAILABLE", text="", detail="tui_backing_required", seat_key=seat.seat_key)
    with pytest.raises(pi.NativeFillRefusalError):
        pi.apply_native_leg_fills([refused], [fill])


def test_author_excluded_claude_seat_cannot_be_restored_by_a_fill(tmp_path, monkeypatch):
    """The governed gate drops author-vendor seats before invoking; a fill for the dropped seat is
    refused before any launch (it is not a seat the composed board defers)."""
    from test_train_review_authorization import _canonical_repo
    repo = _canonical_repo(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    board = _mixed_board()
    fill = _fill(pi.NativeLegFill, board.seats[0])
    invoke = unittest.mock.Mock(side_effect=AssertionError("must not launch"))
    gate = gr.governed_board_gate(
        artifact="bundle\n", author_executor="claude", run_mode="governed", canonical_repo_authority=repo,
        compose=lambda: board, invoke=invoke, native_leg_fills=[fill],
    )
    assert not gate.promoted and invoke.call_count == 0
    assert gate.reason in {"native_fill_refused", "below_reviewer_floor", "no_disjoint_reviewer"}


def test_usable_reviewers_stay_at_three_when_the_fill_is_dropped(tmp_path):
    """A board whose claude seat stayed deferred counts 3 usable, never 4."""
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    result = invoke_sanctioned_review_transport(
        _mixed_board(), "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
    )
    assert len(result.usable_legs) == 2 and len(result.native_fill_requests) == 1  # 2 CLI seats in this fixture + deferred claude
    claude = next(l for l in result.legs if l.leg == "claude")
    assert not claude.usable


def test_audit_consumer_fails_closed_on_an_incomplete_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(le, "observe_reviewtruth_fable_transition", lambda *a, **k: le.FableObservationIncomplete("fill_requested"))
    with pytest.raises(ra.RoadmapAssumptionError):
        ra._observe_reviewtruth_fable_transition(tmp_path, dict(SUBJECT))


def test_cli_probe_raises_typed_on_an_incomplete_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(le, "observe_reviewtruth_fable_transition", lambda *a, **k: le.FableObservationIncomplete("native_fill_not_observable_on_host"))
    with pytest.raises(le.LegibleSidecarError) as excinfo:
        le.run_reviewtruth_fable_probe(tmp_path, repository="Consiliency/agent-harness", issue=396, model=FABLE)
    assert excinfo.value.code == le.REVIEWTRUTH_OBSERVATION_INCOMPLETE


def test_negative_flag_validation_on_both_commands(tmp_path):
    from phase_loop_runtime import cli as cli_mod
    from test_train_prebuilt import PREBUILT_1NODE_MD
    train = tmp_path / "train.md"
    train.write_text(PREBUILT_1NODE_MD)  # a parseable train, so the FLAG validation is what fires
    with unittest.mock.patch("sys.stderr"):
        with pytest.raises(SystemExit) as e:
            cli_mod.main(["run-train", "--train", str(train), "--governed", "--emit-native-request"])
        assert e.value.code == 2
        with pytest.raises(SystemExit) as e:
            cli_mod.main(["run-train", "--train", str(train), "--governed", "--review-only", "--native-leg", "grok=/nowhere"])
        assert e.value.code == 2
    with tempfile.TemporaryDirectory() as td:
        artifact = Path(td) / "a.md"
        artifact.write_text("x\n")
        with unittest.mock.patch("sys.stderr"):
            rc = cli_mod.main(["advisor-board", str(artifact), "--native-leg", "claude=/nowhere/at/all"])
        assert rc == 2
