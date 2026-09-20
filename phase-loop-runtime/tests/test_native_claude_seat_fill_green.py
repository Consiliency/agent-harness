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


def test_direct_invoker_refuses_a_fill_whose_binding_does_not_match(tmp_path):
    """#921 board r1 (codex): a direct invoke_board caller cannot count a fill the gate/CLI would
    have refused — the invoker validates the binding itself, typed, before any launch."""
    artifact = tmp_path / "bundle.md"
    artifact.write_text("review me\n")
    board = _mixed_board()
    mismatched = _fill(pi.NativeLegFill, board.seats[0], artifact_sha256="0" * 64)
    launched = []

    def spawn(leg, art, **kw):
        launched.append(leg)
        return _typed_deferral_spawn(leg, art, **kw)

    result = invoke_sanctioned_review_transport(
        board, "", spawn=spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
        native_leg_fills=[mismatched],
    )
    assert not result.usable_legs and launched == []
    assert all(leg.status == "UNAVAILABLE" and "native_fill_refused:native_fill_digest_mismatch" in (leg.detail or "") for leg in result.legs)


def test_gate_preflight_refuses_before_minting(tmp_path, monkeypatch):
    """Deleting the gate's preflight block must not survive: a mismatched fill is refused before
    the isolation authorization is minted (the invoker's own check would only fire after)."""
    from phase_loop_runtime.advisor_board import backing as backing_mod
    from test_train_review_authorization import _canonical_repo
    repo = _canonical_repo(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    mint = unittest.mock.Mock(side_effect=AssertionError("must not mint"))
    monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", mint)
    board = _mixed_board()
    gate = gr.governed_board_gate(
        artifact="bundle\n", author_executor="train-coordinator", run_mode="governed", canonical_repo_authority=repo,
        compose=lambda: board, invoke=unittest.mock.Mock(side_effect=AssertionError("must not invoke")),
        native_leg_fills=[_fill(pi.NativeLegFill, board.seats[0], artifact_sha256="0" * 64)],
    )
    assert not gate.promoted and gate.reason == "native_fill_refused" and mint.call_count == 0


def test_cr_bearing_bundle_digests_agree_between_emit_and_train_rebuild(tmp_path, monkeypatch):
    """#921 delta r2 (claude): the emit arm digests the READ-BACK staged text; the train's rebuild
    comparison normalises newlines the same way, so a CR in a roadmap title never false-refuses."""
    from phase_loop_runtime.advisor_board import composition as comp_mod
    monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: _mixed_board())
    monkeypatch.setenv("CLAUDECODE", "1")
    bundle = "# Train\r\n\r\ntitle with CR\r\nbundle\r\n"
    out = gr.governed_board_gate(artifact=bundle, author_executor="train-coordinator", run_mode="governed",
                                 canonical_repo_authority=tmp_path, emit_native_request=True, native_fill_dir=tmp_path)
    assert isinstance(out, dict)
    normalised = bundle.replace("\r\n", "\n").replace("\r", "\n")
    assert out["artifact_sha256"] == pi.content_sha256(normalised) != pi.content_sha256(bundle)
    assert pi.content_sha256(Path(out["artifact_path"]).read_text(encoding="utf-8")) == out["artifact_sha256"]


def test_directory_form_accepts_the_legacy_review_filename(tmp_path):
    import json
    d = tmp_path / "native-fill" / "r1"
    d.mkdir(parents=True)
    (d / "request.json").write_text(json.dumps({"request_id": "r1", "seat_key": _seat().seat_key, "model": FABLE,
                                                "artifact_sha256": "a" * 64, "brief_sha256": "b" * 64, "composition_sha256": "c" * 64}))
    (d / "claude.md").write_text("Reviewed.\nAGREE\n")
    fill = pi.load_native_leg_fills(f"claude={d}")
    assert fill.text == "Reviewed.\nAGREE\n" and fill.request_id == "r1"
    (d / "review.md").write_text("Preferred.\nAGREE\n")
    assert pi.load_native_leg_fills(f"claude={d}").text == "Preferred.\nAGREE\n"


def test_premerge_loop_forwards_fills_on_the_first_round_only():
    from phase_loop_runtime.governed_premerge import run_governed_premerge_loop
    from phase_loop_runtime.closeout_validators import ReviewFinding
    seen: list = []
    rounds = {"n": 0}

    def invoke(**kw):
        rounds["n"] += 1
        seen.append(kw.get("native_leg_fills"))
        if rounds["n"] == 1:  # first round blocks → a fix round follows without the fill
            return gr.GateResult(ran=True, promoted=False, reason="block",
                                 findings=(ReviewFinding(code="x", reason="fix me", severity="block", blocker_class="review_gate_block"),))
        return gr.GateResult(ran=True, promoted=True)

    fill = _fill(pi.NativeLegFill, _seat())
    run_governed_premerge_loop(artifact="a", author_executor="codex", run_mode="governed", invoke=invoke,
                               apply_fix=lambda rnd, art, findings: art + "\nfixed", max_rounds=2, native_leg_fills=[fill])
    assert rounds["n"] == 2 and seen[0] == (fill,) and seen[1] is None
