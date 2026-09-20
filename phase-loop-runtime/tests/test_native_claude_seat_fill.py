"""REVIEWTRUTH early slice — native claude seat fill under Claude Code (EC-REVIEWTRUTH-14).

PR-1 of the ratified plan agent-harness#918: the RED falsifiers, observed RED against the
pre-implementation base with ``PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1`` and skipped without it.
Every activated falsifier observes BEHAVIOUR (launch counts, bytes written or not, returned
outcomes, what the president was shown), never a symbol's existence or a source substring, and
fails with an AssertionError at its unique anchor (``_reviewtruth_native_fill_tdd_guard``).
Positive controls and byte-identity pins are unguarded and must hold before AND after.

The exact interfaces these tests drive are the ones EC-REVIEWTRUTH-0 freezes for the slice;
the ratified plan's Changes list is descriptive and yields to them (plan r8).

NOT CLAIMED HERE (the plan's Tests bullets this RED lane deliberately leaves to PR-2's GREEN-side
regressions, each named so nothing is silently dropped):
- a ``tui_backing_required`` (non-homebrew backing) claude seat is NOT fillable — covered by the
  preflight's "seat not deferred" arm only indirectly; PR-2 adds the explicit case.
- a claude seat dropped by author-vendor exclusion cannot be restored by a fill (governed gate).
- ``usable_reviewers`` stays at 3 on the premerge loop when the fill is dropped (the unbound
  observation arm covers the probe's view of it; the loop's own count is PR-2's).
- two of the four probe consumers, ``audit_roadmap_assumptions`` and ``_probe_response_finding``
  (both fail-closed today; PR-2 routes them through the one observation function and regresses them).
- the president on the EARLY deferral path (a claude-only board cannot satisfy a president-requiring
  seat policy; only the bound-and-usable property is asserted here).
- the live emit → fill → invoke run with real seats (an acceptance run from the driving session,
  recorded on the implementation PR, not a unit falsifier).
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import os
import tempfile
import unittest.mock
from collections.abc import Mapping
from pathlib import Path

import pytest

import _reviewtruth_native_fill_tdd_guard as guard
from harden_tdd_guard import invoke_sanctioned_review_transport
from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import legible_evidence as le
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import roadmap_assumptions as ra
from phase_loop_runtime.advisor_board import Board, Seat
from phase_loop_runtime.advisor_board import composition as comp_mod
from phase_loop_runtime.panel_invoker import ReviewLandingTier
from president_fakes import deferring_president
from test_train_review_authorization import _canonical_repo

CC = {"CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")}
NOT_CC = {"PATH": os.environ.get("PATH", "")}
FABLE = "claude-fable-5"
activated = pytest.mark.skipif(not guard.active(), reason=guard.SKIP_REASON)
SUBJECT = {"repository": "Consiliency/agent-harness", "issue": 396, "model": FABLE, "source_anchor": "test"}


def _code_digest(fn) -> str:
    """SHA-256 of a function's AST with docstrings stripped: behaviour, not prose."""
    import ast
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def _seat(model: str = FABLE, harness: str = "claude") -> Seat:
    return Seat(model=model, effort="max", harness=harness, lens="correctness")


def _default_seat(harness: str) -> Seat:
    """The fleet-default seat for a vendor: its route is HARDEN-supported by construction."""
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
    return next(seat for seat in DEFAULT_SEATS if str(seat.harness).lower() == harness)


def _four_vendor_board() -> Board:
    return Board(name="four", purpose="premerge-review",
                 seats=tuple(_default_seat(h) for h in ("claude", "codex", "gemini", "grok")))


FILL_MARKER = "FILL-MARKER-7f3a"


def _mixed_board() -> Board:
    return Board(name="mixed", purpose="premerge-review",
                 seats=(_seat(FABLE), _seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")))


def _typed_deferral_spawn(leg, artifact, **kw):
    """The injected spawn for matrix-path tests: the non-claude seats review; the claude seat
    returns exactly the typed deferral the production leg emits under Claude Code."""
    if leg != "claude":
        return "OK", "Reviewed.\nAGREE"
    return "UNAVAILABLE", "under_claude_code"


class _Never:
    def __init__(self, what: str = "callable"):
        self.what, self.calls = what, 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError(f"{self.what} must not be called")


class _Spy:
    def __init__(self, result=None):
        self.result, self.calls = result, []

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.result


def _run_claude_solo(model: str):
    """The 183 harness: a claude-only board under Claude Code, PRODUCTION spawn (early path)."""
    with tempfile.TemporaryDirectory() as td:
        artifact = Path(td) / "bundle.md"
        artifact.write_text("review me\n")
        scratch = Path(td) / "scratch"
        scratch.mkdir()
        board = Board(name="claude-solo", purpose="premerge-review", seats=(_seat(model),))
        with unittest.mock.patch.object(pi, "_claude_code_support_status", return_value=(True, "supported")):
            result = invoke_sanctioned_review_transport(
                board, "", artifact_ref=str(artifact.resolve()), repo_dir=str(scratch), base_env=dict(CC),
            )
    (leg,) = result.legs
    return result, leg


def _fill_symbols():
    return (guard.symbol("phase_loop_runtime.panel_invoker", "NativeLegFill"),
            guard.symbol("phase_loop_runtime.panel_invoker", "load_native_leg_fill"),
            guard.symbol("phase_loop_runtime.panel_invoker", "preflight_native_leg_fills"),
            guard.symbol("phase_loop_runtime.panel_invoker", "apply_native_leg_fills"))


def _fill(NativeLegFill, seat: Seat, text: str = "Reviewed.\nAGREE", **over):
    base = dict(seat_key=seat.seat_key, model=seat.model, text=text, artifact_sha256="a" * 64,
                brief_sha256="b" * 64, composition_sha256="c" * 64, request_id="r1",
                filled_by="claude-code", filled_at="t")
    base.update(over)
    return NativeLegFill(**base)


def _deferred_leg(seat: Seat) -> pi.PanelLegResult:
    leg = pi.PanelLegResult(leg="claude", status="UNAVAILABLE", text="", detail="under_claude_code", seat_key=seat.seat_key)
    pi.attach_native_agent_request(leg, pi.native_agent_leg_request(leg="claude", mode="review", env=dict(CC), model=seat.model))
    return leg


# ---------------------------------------------------------------------------
# Guard controls — never skip


class TestGuardControls:
    def test_guard_is_inactive_without_the_flag_or_marker(self, monkeypatch):
        monkeypatch.delenv(guard.ACTIVATION_ENV, raising=False)
        monkeypatch.setattr(guard, "marker_version", lambda: None)
        assert not guard.active()

    def test_flag_activates_exactly_on_the_string_one(self, monkeypatch):
        monkeypatch.setattr(guard, "marker_version", lambda: None)
        monkeypatch.setenv(guard.ACTIVATION_ENV, "true")
        assert not guard.active()
        monkeypatch.setenv(guard.ACTIVATION_ENV, "1")
        assert guard.active()

    def test_anchors_are_unique_and_cover_every_activated_falsifier(self):
        anchors = list(guard.RED_ANCHORS.values())
        assert len(anchors) == len(set(anchors))
        here = Path(__file__).read_text()
        for name in guard.RED_ANCHORS:
            assert f"def {name}(" in here, name
        activated_defs = here.count("@activated\n    def ")
        assert activated_defs == len(guard.RED_ANCHORS), (activated_defs, len(guard.RED_ANCHORS))

    def test_marker_module_absent_is_not_a_collection_error(self):
        assert guard.symbol(guard.MARKER_MODULE, guard.MARKER_ATTRIBUTE) is None or guard.marker_version() == guard.MARKER_VERSION


# ---------------------------------------------------------------------------
# Positive controls and byte-identity pins — never skip, must hold before AND after


class TestInvariantsThatSurviveTheSlice:
    def test_fable_request_is_still_forbidden_outside_claude_code(self):
        with pytest.raises(ValueError):
            pi.native_agent_leg_request(leg="claude", mode="review", env=dict(NOT_CC), model=FABLE)

    def test_a_board_without_a_claude_seat_emits_no_fill_request_under_claude_code(self, tmp_path):
        artifact = tmp_path / "bundle.md"
        artifact.write_text("review me\n")
        board = Board(name="no-claude", purpose="premerge-review",
                      seats=(_seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")))
        result = invoke_sanctioned_review_transport(
            board, "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
        )
        assert result.native_fill_requests == ()
        assert all(leg.needs_native_agent is None for leg in result.legs)

    def test_transition_classifier_and_flattener_are_byte_identical(self):
        # The instrument this slice is graded by: the two functions' CODE must not change. The
        # digest is over the AST with docstrings stripped (a docstring-only edit — e.g. a seam
        # rename mentioned in prose — is not a behaviour change; board r2, claude N1), pinned on
        # the base this lane was authored against. PR-2 must leave both untouched.
        assert (_code_digest(ra._classify_reviewtruth_transition), _code_digest(le._flatten_reviewtruth_observation)) == (
            "73554cee0ba7dda61a49f9efa5c3663e777c410dafff95b7637cc5033204df21",
            "07372f003a604aacda5f431a885011cff3ec7d1cd00de3cf4a70ef788f3cfc59",
        )


# ---------------------------------------------------------------------------
# D1 — routing under Claude Code (both deferral paths)


class TestRouting:
    @activated
    def test_claude_seat_request_is_built_under_claude_code_for_every_claude_model(self):
        n = "test_claude_seat_request_is_built_under_claude_code_for_every_claude_model"
        for model in (FABLE, "claude-opus-5", "claude-sonnet-5"):
            req, detail = None, ""
            try:
                req = pi.native_agent_leg_request(leg="claude", mode="review", env=dict(CC), model=model)
            except ValueError as exc:
                detail = str(exc)
            guard.require(n, req is not None, f"builder raised for {model} under Claude Code: {detail}")
            guard.require(n, req.reason == "under_claude_code" and req.model == model and bool(req.instructions),
                          f"{model}: reason={req.reason!r} model={req.model!r}")

    @activated
    def test_under_claude_code_is_a_typed_unavailable_detail(self):
        # Behavioural: a leg whose spawn returned the typed token has it RELOCATED into
        # ``detail`` with an empty body (the deferral signature every consumer keys on).
        leg = pi.PanelLegResult(leg="claude", status="UNAVAILABLE", text="under_claude_code")
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            result = invoke_sanctioned_review_transport(
                _mixed_board(), "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=td, base_env=dict(CC),
            )
        claude = next(l for l in result.legs if l.leg == "claude")
        guard.require("test_under_claude_code_is_a_typed_unavailable_detail",
                      claude.status == "UNAVAILABLE" and claude.text == "" and claude.detail == "under_claude_code",
                      f"{claude.status}/{claude.text!r}/{claude.detail!r} (raw leg text stays {leg.text!r} when untyped)")

    @activated
    def test_early_deferral_path_attaches_a_request_for_the_fable_seat(self):
        result, leg = _run_claude_solo(FABLE)
        n = "test_early_deferral_path_attaches_a_request_for_the_fable_seat"
        guard.require(n, leg.status == "UNAVAILABLE" and leg.text == "" and leg.detail == "under_claude_code",
                      f"{leg.status}/{leg.text!r}/{leg.detail!r}")
        guard.require(n, leg.needs_native_agent is not None and len(result.native_fill_requests) == 1,
                      "no NativeAgentLegRequest attached on the early path")

    @activated
    def test_matrix_path_attaches_a_request_for_the_fable_seat(self):
        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            result = invoke_sanctioned_review_transport(
                _mixed_board(), "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=td, base_env=dict(CC),
            )
        claude = next(l for l in result.legs if l.leg == "claude")
        n = "test_matrix_path_attaches_a_request_for_the_fable_seat"
        guard.require(n, claude.needs_native_agent is not None and claude.needs_native_agent.model == FABLE,
                      f"no request attached on the matrix path (detail={claude.detail!r})")
        guard.require(n, len(result.native_fill_requests) == 1, "board reports no fill request")


# ---------------------------------------------------------------------------
# D2 — ingestion contract


class TestIngestion:
    @activated
    def test_native_leg_fill_is_a_frozen_record_with_the_binding_fields(self):
        NativeLegFill = _fill_symbols()[0]
        n = "test_native_leg_fill_is_a_frozen_record_with_the_binding_fields"
        guard.require(n, NativeLegFill is not None, "panel_invoker.NativeLegFill is absent")
        fill = _fill(NativeLegFill, _seat())
        with pytest.raises(Exception):  # frozen: no field is assignable after construction
            setattr(fill, "text", "mutated")
        guard.require(n, fill.text == "Reviewed.\nAGREE" and fill.artifact_sha256 == "a" * 64, "record does not carry its fields")

    @activated
    def test_loader_takes_digests_from_the_emitted_request_only(self, tmp_path):
        load = _fill_symbols()[1]
        n = "test_loader_takes_digests_from_the_emitted_request_only"
        guard.require(n, load is not None, "panel_invoker.load_native_leg_fill is absent")
        import json
        (tmp_path / "request.json").write_text(json.dumps({
            "request_id": "r1", "seat_key": _seat().seat_key, "model": FABLE,
            "artifact_sha256": "a" * 64, "brief_sha256": "b" * 64, "composition_sha256": "c" * 64}))
        (tmp_path / "claude.md").write_text("Reviewed.\nAGREE\n")
        fill = load(tmp_path / "request.json", tmp_path / "claude.md")
        guard.require(n, (fill.artifact_sha256, fill.brief_sha256, fill.composition_sha256) == ("a" * 64, "b" * 64, "c" * 64)
                      and fill.text == "Reviewed.\nAGREE\n", "loader must carry the EMITTED digests and the review text, never recompute")

    @activated
    def test_preflight_refuses_each_ineligible_fill_with_a_typed_reason_and_accepts_an_eligible_one(self):
        NativeLegFill, _, preflight, _ = _fill_symbols()
        n = "test_preflight_refuses_each_ineligible_fill_with_a_typed_reason_and_accepts_an_eligible_one"
        guard.require(n, preflight is not None and NativeLegFill is not None, "preflight_native_leg_fills is absent")
        board = _mixed_board()
        claude = board.seats[0]
        staged = dict(artifact_sha256="a" * 64, brief_sha256="b" * 64, composition_sha256="c" * 64)
        ok = _fill(NativeLegFill, claude)
        cases = {
            "native_fill_duplicate_seat": ([ok, ok], dict(CC)),
            "native_fill_seat_not_deferred": ([ok], dict(NOT_CC)),
            "native_fill_seat_not_deferred (wrong seat)": ([_fill(NativeLegFill, board.seats[1])], dict(CC)),
            "native_fill_digest_mismatch (artifact)": ([_fill(NativeLegFill, claude, artifact_sha256="d" * 64)], dict(CC)),
            "native_fill_digest_mismatch (brief)": ([_fill(NativeLegFill, claude, brief_sha256="d" * 64)], dict(CC)),
            "native_fill_composition_drift": ([_fill(NativeLegFill, claude, composition_sha256="d" * 64)], dict(CC)),
        }
        for label, (fills, env) in cases.items():
            reason = label.split(" ")[0]
            refusal = preflight(board, fills, env=env, **staged)
            got = getattr(refusal, "reason", refusal)
            guard.require(n, refusal is not None and got == reason, f"{label}: expected {reason!r}, got {got!r}")
        guard.require(n, preflight(board, [ok], env=dict(CC), **staged) is None, "an eligible fill must pass preflight")

    @activated
    def test_apply_counts_only_a_bound_conforming_fill(self):
        NativeLegFill, _, _, apply = _fill_symbols()
        n = "test_apply_counts_only_a_bound_conforming_fill"
        guard.require(n, apply is not None and NativeLegFill is not None, "apply_native_leg_fills is absent")
        seat = _seat()
        good = apply([_deferred_leg(seat)], [_fill(NativeLegFill, seat)])
        guard.require(n, len(good) == 1 and good[0].usable and good[0].status == "OK", f"bound conforming fill not usable: {good}")
        bad = apply([_deferred_leg(seat)], [_fill(NativeLegFill, seat, text="I looked but reached no verdict.")])
        guard.require(n, len(bad) == 1 and not bad[0].usable, f"a fill without a conforming verdict was counted: {bad}")

    @activated
    def test_apply_never_replaces_a_runtime_leg(self):
        NativeLegFill, _, _, apply = _fill_symbols()
        n = "test_apply_never_replaces_a_runtime_leg"
        guard.require(n, apply is not None and NativeLegFill is not None, "apply_native_leg_fills is absent")
        seat = _seat()
        runtime = pi.PanelLegResult(leg="claude", status="OK", text="Runtime.\nDISAGREE", seat_key=seat.seat_key)
        legs = [runtime]
        with pytest.raises(Exception):
            apply(legs, [_fill(NativeLegFill, seat)])
        guard.require(n, legs[0] is runtime and runtime.text == "Runtime.\nDISAGREE", "the runtime leg was replaced")

    @activated
    def test_president_rules_on_the_bound_fill_on_both_deferral_paths(self, tmp_path):
        """Matrix path: the fleet-default four-vendor board under PRODUCTION_CODE (the tier that
        requires a president and all four vendors) with the claude seat filled — the president
        must be shown the FILLED board: the prompt it receives carries the fill's own text
        (a ruling made before the fill is bound cannot contain it). Early path: a claude-only
        board can never satisfy a president-requiring seat policy (pre-existing, correct), so the
        property there is that the fill is bound and usable on the common tail."""
        NativeLegFill = _fill_symbols()[0]
        n = "test_president_rules_on_the_bound_fill_on_both_deferral_paths"
        guard.require(n, NativeLegFill is not None, "NativeLegFill is absent")
        artifact = tmp_path / "bundle.md"
        artifact.write_text("review me\n")
        four = _four_vendor_board()
        claude_seat = next(seat for seat in four.seats if str(seat.harness).lower() == "claude")
        seen: list = []

        def president(model, prompt):
            seen.append(prompt)
            return deferring_president(model, prompt)

        fill = _fill(NativeLegFill, claude_seat, text=f"Reviewed carefully. {FILL_MARKER}\nAGREE")
        err, res = None, None
        try:
            res = invoke_sanctioned_review_transport(
                four, "", spawn=_typed_deferral_spawn, artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
                landing_tier=ReviewLandingTier.PRODUCTION_CODE, president_invoke=president, native_leg_fills=[fill],
            )
        except TypeError as exc:
            err = exc
        guard.require(n, err is None, f"matrix: invoke_board accepts no native_leg_fills: {err}")
        claude = next(l for l in res.legs if l.leg == "claude")
        guard.require(n, claude.usable, f"matrix: the bound fill is not usable ({claude.status}/{claude.detail})")
        guard.require(n, res.president is not None and res.president_findings and len(seen) >= 1,
                      "matrix: no ruling was made over the filled board")
        guard.require(n, any(FILL_MARKER in prompt for prompt in seen),
                      "matrix: the president ruled BEFORE the fill was bound (its prompt never carried the fill's text)")
        solo = Board(name="claude-solo", purpose="premerge-review", seats=(_seat(),))
        err = None
        with unittest.mock.patch.object(pi, "_claude_code_support_status", return_value=(True, "supported")):
            try:
                res = invoke_sanctioned_review_transport(
                    solo, "", artifact_ref=str(artifact), repo_dir=str(tmp_path), base_env=dict(CC),
                    native_leg_fills=[_fill(NativeLegFill, solo.seats[0])],
                )
            except TypeError as exc:
                err = exc
        guard.require(n, err is None, f"early: invoke_board accepts no native_leg_fills: {err}")
        (leg,) = res.legs
        guard.require(n, leg.usable and leg.status == "OK", f"early: the bound fill is not usable ({leg.status}/{leg.detail})")


# ---------------------------------------------------------------------------
# D3 — emit → fill → invoke protocol


class TestProtocol:
    @activated
    def test_composition_digest_is_content_only_and_order_independent(self):
        digest = guard.symbol("phase_loop_runtime.advisor_board.composition", "composition_digest")
        n = "test_composition_digest_is_content_only_and_order_independent"
        guard.require(n, digest is not None, "composition.composition_digest is absent")
        a, b, c = _seat(FABLE), _seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")
        ab = Board(name="x", purpose="premerge-review", seats=(a, b))
        ba = Board(name="y", purpose="premerge-review", seats=(b, a))
        abc = Board(name="x", purpose="premerge-review", seats=(a, b, c))
        guard.require(n, digest(ab) == digest(ba), "digest depends on seat order or board name")
        guard.require(n, digest(ab) != digest(abc) and len(digest(ab)) == 64, "digest does not change with the seat set")
        a2 = Seat(model=FABLE, effort="max", harness="claude", lens="adversarial")
        ab2 = Board(name="x", purpose="premerge-review", seats=(a2, b))
        guard.require(n, digest(ab) != digest(ab2), "digest ignores a seat's identity (same count, different lens)")

    @activated
    def test_request_payload_carries_the_binding(self):
        payload = guard.symbol("phase_loop_runtime.panel_invoker", "native_fill_request_payload")
        n = "test_request_payload_carries_the_binding"
        guard.require(n, payload is not None, "panel_invoker.native_fill_request_payload is absent")
        out = payload(_mixed_board(), "bundle text\n", brief_ref=None, env=dict(CC))
        need = {"request_id", "seat_key", "model", "lens", "effort", "artifact_sha256", "brief_sha256", "composition_sha256"}
        guard.require(n, isinstance(out, Mapping) and need <= set(out), f"missing keys: {sorted(need - set(out or {}))}")
        guard.require(n, out["artifact_sha256"] == hashlib.sha256(b"bundle text\n").hexdigest() and out["model"] == FABLE,
                      "artifact digest must be over the staged content and the seat must be the claude seat")

    @activated
    def test_gate_emit_arm_returns_the_request_without_minting_or_invoking(self, tmp_path, monkeypatch):
        from phase_loop_runtime.advisor_board import backing as backing_mod
        n = "test_gate_emit_arm_returns_the_request_without_minting_or_invoking"
        monkeypatch.setenv("CLAUDECODE", "1")
        mint, invoke = _Never("mint"), _Never("invoke")
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", mint)
        out, err = None, None
        try:
            out = gr.governed_board_gate(
                artifact="bundle\n", author_executor="train-coordinator", run_mode="governed",
                canonical_repo_authority=tmp_path, compose=_mixed_board, invoke=invoke,
                emit_native_request=True, native_fill_dir=tmp_path,
            )
        except TypeError as exc:
            err = exc
        guard.require(n, err is None, f"governed_board_gate has no emit arm: {err}")
        guard.require(n, mint.calls == 0 and invoke.calls == 0, "the emit arm minted or invoked")
        req = out if isinstance(out, Mapping) else getattr(out, "native_fill_request", None)
        guard.require(n, isinstance(req, Mapping) and req.get("artifact_sha256") == hashlib.sha256(b"bundle\n").hexdigest(),
                      f"no request with the staged digest was returned: {req}")
        guard.require(n, Path(str(req.get("request_path", ""))).is_file(), "request.json was not written")

    @activated
    def test_run_train_emit_arm_spends_nothing(self, tmp_path, monkeypatch):
        from phase_loop_runtime.train_roadmap import parse_train_roadmap
        from phase_loop_runtime.train_runner import run_train
        from test_train_prebuilt import PREBUILT_1NODE_MD, _make_prebuilt_publish_stub
        from test_train_review_authorization import ADMITTED, _ledger, _pr_is_open_true, _preflight_pass

        n = "test_run_train_emit_arm_spends_nothing"
        monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: _mixed_board())
        monkeypatch.setenv("CLAUDECODE", "1")
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {node.node_id: tmp_path / node.repo for node in roadmap.nodes}
        review, publish, merge = _Never("review"), _Never("publish"), _Never("merge")
        result, err = None, None
        try:
            result = run_train(
                roadmap, _ledger(tmp_path), run_mode="governed",
                resolve_workspace=lambda node: ws_map[node.node_id],
                _run_loop=lambda *a, **kw: (None, []), _publish=publish,
                _set_upstream_ref_fn=lambda *a, **kw: [], _preflight_fn=_preflight_pass,
                _pr_is_open=_pr_is_open_true, _live_pr_head_sha_fn=lambda ws, br: ADMITTED,
                _workspace_head_fn=lambda ws: ADMITTED, _is_ancestor_fn=lambda ws, a, b: True,
                _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"], _merge_phase_enabled=True,
                review_only=True, _train_review_fn=review, _merge_pr_fn=merge,
                _reverify_fn=lambda *a, **k: True, _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
                emit_native_request=True,
            )
        except TypeError as exc:
            err = exc
        guard.require(n, err is None, f"run_train has no emit arm: {err}")
        guard.require(n, result.get("status") == "native_fill_requested", f"status={result.get('status')!r}")
        guard.require(n, Path(result["request_path"]).is_file() and Path(result["artifact_path"]).is_file(), "request/artifact not staged")
        guard.require(n, review.calls == publish.calls == merge.calls == 0, "the emit arm spent a board, published or merged")
        _ = _make_prebuilt_publish_stub  # imported for fixture parity with the train suites

    @activated
    def test_run_train_refuses_a_stale_fill_before_spending_a_seat(self, tmp_path, monkeypatch):
        """emit → load → invoke: a fill loaded from the EMITTED request reaches the review exactly
        once (never refused as stale); the same fill against a moved train is refused as
        native_fill_stale_request before anything is minted. A runner that refuses every fill,
        or accepts every fill, fails one half."""
        from phase_loop_runtime.advisor_board import backing as backing_mod
        from phase_loop_runtime.train_roadmap import parse_train_roadmap
        from phase_loop_runtime.train_runner import run_train
        from test_train_prebuilt import PREBUILT_1NODE_MD
        from test_train_review_authorization import ADMITTED, _ledger, _pr_is_open_true, _preflight_pass

        NativeLegFill, load, _, _ = _fill_symbols()
        n = "test_run_train_refuses_a_stale_fill_before_spending_a_seat"
        guard.require(n, NativeLegFill is not None and load is not None, "NativeLegFill / load_native_leg_fill absent")
        monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: _mixed_board())
        monkeypatch.setenv("CLAUDECODE", "1")
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {node.node_id: tmp_path / node.repo for node in roadmap.nodes}
        publish, merge = _Never("publish"), _Never("merge")

        def _train(ledger, **extra):
            return run_train(
                roadmap, ledger, run_mode="governed",
                resolve_workspace=lambda node: ws_map[node.node_id],
                _run_loop=lambda *a, **kw: (None, []), _publish=publish,
                _set_upstream_ref_fn=lambda *a, **kw: [], _preflight_fn=_preflight_pass,
                _pr_is_open=_pr_is_open_true, _live_pr_head_sha_fn=lambda ws, br: ADMITTED,
                _workspace_head_fn=lambda ws: ADMITTED, _is_ancestor_fn=lambda ws, a, b: True,
                _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"], _merge_phase_enabled=True,
                review_only=True, _merge_pr_fn=merge,
                _reverify_fn=lambda *a, **k: True, _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
                **extra,
            )

        ledger = _ledger(tmp_path)
        err, emitted = None, None
        try:
            emitted = _train(ledger, emit_native_request=True)
        except TypeError as exc:
            err = exc
        guard.require(n, err is None and emitted.get("status") == "native_fill_requested", f"emit arm: {err or emitted}")
        request_path = Path(emitted["request_path"])
        (request_path.parent / "claude.md").write_text("Reviewed the train.\nAGREE\n")
        fill = load(request_path, request_path.parent / "claude.md")
        review = _Spy(result=None)

        def reviewing(artifact, run_mode, **kw):
            from phase_loop_runtime.governed_premerge import LoopResult
            review.calls.append((artifact, run_mode, kw))
            return LoopResult(mergeable=True, ran=True, rounds=1)

        ok = _train(ledger, native_leg_fills=[fill], _train_review_fn=reviewing)
        guard.require(n, ok.get("status") == "review_approved" and len(review.calls) == 1,
                      f"a fill loaded from the emitted request did not reach the review exactly once: {ok.get('status')} / {len(review.calls)}")
        mint = _Never("mint")
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", mint)
        # The SAME loaded fill (digests untouched) against a train that MOVED: the node's admitted
        # head on this ledger is different, so the bundle the runner REBUILDS differs from the
        # emitted one. A runner comparing against the saved emission instead of the rebuilt
        # bundle would accept it.
        from phase_loop_runtime.train_ledger import LedgerRecord, append_record
        moved_ledger = tmp_path / "moved" / "train.ledger.jsonl"
        append_record(moved_ledger, LedgerRecord(
            node_id="repo-a/specs/plan-a.md", status="pr_open", branch="feat/train-repo-a",
            head_sha="sha-moved-b", pr_url="https://gh.com/repo-a/pr/1", merge_order=0,
        ))
        halted = run_train(
            roadmap, moved_ledger, run_mode="governed",
            resolve_workspace=lambda node: ws_map[node.node_id],
            _run_loop=lambda *a, **kw: (None, []), _publish=publish,
            _set_upstream_ref_fn=lambda *a, **kw: [], _preflight_fn=_preflight_pass,
            _pr_is_open=_pr_is_open_true, _live_pr_head_sha_fn=lambda ws, br: "sha-moved-b",
            _workspace_head_fn=lambda ws: "sha-moved-b", _is_ancestor_fn=lambda ws, a, b: True,
            _prebuilt_owned_paths_fn=lambda ws, base: ["src/x.py"], _merge_phase_enabled=True,
            review_only=True, _merge_pr_fn=merge,
            _reverify_fn=lambda *a, **k: True, _pr_merged_sha_fn=lambda ws, br, base=None, head_sha=None: None,
            native_leg_fills=[fill], _train_review_fn=_Never("review"),
        )
        guard.require(n, halted.get("status") == "review_halted" and halted.get("reason") == "native_fill_stale_request",
                      f"a fill for a MOVED train was not refused as native_fill_stale_request: {halted.get('status')}/{halted.get('reason')}")
        guard.require(n, mint.calls == 0 and publish.calls == 0 and merge.calls == 0, "a seat was minted or a merge attempted")

    @activated
    def test_cli_emit_arm_writes_the_request_and_run_train_accepts_the_flags(self, tmp_path, monkeypatch, capsys):
        from phase_loop_runtime import cli as cli_mod
        n = "test_cli_emit_arm_writes_the_request_and_run_train_accepts_the_flags"
        monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: _mixed_board())
        monkeypatch.setenv("CLAUDECODE", "1")
        artifact = tmp_path / "bundle.md"
        artifact.write_text("review me\n")
        rc, err = None, None
        try:
            with unittest.mock.patch("sys.stderr"):
                rc = cli_mod.main(["advisor-board", str(artifact), "--emit-native-request", "--native-fill-dir", str(tmp_path), "--json"])
        except SystemExit as exc:
            err = exc
        guard.require(n, err is None and rc == 0, f"advisor-board --emit-native-request failed: rc={rc} err={err}")
        written = list((tmp_path / "native-fill").glob("*/request.json")) if (tmp_path / "native-fill").is_dir() else []
        guard.require(n, len(written) == 1, f"request.json not written under native-fill/: {written}")
        parser = guard.symbol("phase_loop_runtime.cli", "build_parser")
        guard.require(n, parser is not None, "cli.build_parser is absent")
        rejected = []
        for argv in (["run-train", "--train", "t.md", "--governed", "--review-only", "--emit-native-request"],
                     ["run-train", "--train", "t.md", "--governed", "--review-only", "--native-leg", "claude=/tmp/fill"]):
            try:
                with unittest.mock.patch("sys.stderr"):
                    parser().parse_args(argv)
            except (SystemExit, argparse.ArgumentError):
                rejected.append(argv)
        guard.require(n, not rejected, f"run-train rejects the protocol flags: {rejected}")


# ---------------------------------------------------------------------------
# D5 — the phase's live probe: one observation function, typed incompleteness, fail-closed


def _observe():
    return (guard.symbol("phase_loop_runtime.legible_evidence", "observe_reviewtruth_fable_transition"),
            guard.symbol("phase_loop_runtime.legible_evidence", "FableObservationIncomplete"))


class TestProbe:
    @activated
    def test_observation_is_typed_incomplete_under_claude_code_without_a_fill_and_launches_nothing(self, tmp_path, monkeypatch):
        observe, Incomplete = _observe()
        n = "test_observation_is_typed_incomplete_under_claude_code_without_a_fill_and_launches_nothing"
        guard.require(n, observe is not None and Incomplete is not None, "observe_reviewtruth_fable_transition / FableObservationIncomplete absent")
        repo = _canonical_repo(tmp_path)
        monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: _mixed_board())
        monkeypatch.setenv("CLAUDECODE", "1")
        spawn = _Never("any provider launch")
        monkeypatch.setattr(pi, "_default_spawn", spawn)
        out = observe(repo, SUBJECT, native_leg_fills=None, issue_snapshot={"state": "OPEN", "stateReason": None})
        guard.require(n, isinstance(out, Incomplete) and getattr(out, "reason", None) == "fill_requested",
                      f"expected Incomplete('fill_requested'), got {out!r}")
        guard.require(n, spawn.calls == 0, "a provider leg was launched by an unfilled observation")

    @activated
    def test_observation_is_typed_incomplete_outside_claude_code_and_never_launches_the_external_leg(self, tmp_path, monkeypatch):
        observe, Incomplete = _observe()
        n = "test_observation_is_typed_incomplete_outside_claude_code_and_never_launches_the_external_leg"
        guard.require(n, observe is not None and Incomplete is not None, "observe_reviewtruth_fable_transition / FableObservationIncomplete absent")
        repo = _canonical_repo(tmp_path)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        launched_without_marker = []

        def spawn(leg, artifact, **kw):
            env = kw.get("env") or {}
            if str(env.get("CLAUDECODE", "")).strip() != "1":
                launched_without_marker.append(leg)
                return "UNAVAILABLE", "external leg must not be launched"
            return "UNAVAILABLE", "under_claude_code"  # the marker run: the routing in force post-flip

        monkeypatch.setattr(pi, "_default_spawn", spawn)
        out = observe(repo, SUBJECT, native_leg_fills=None, issue_snapshot={"state": "OPEN", "stateReason": None})
        guard.require(n, isinstance(out, Incomplete) and getattr(out, "reason", None) == "native_fill_not_observable_on_host",
                      f"expected Incomplete('native_fill_not_observable_on_host'), got {out!r}")
        guard.require(n, not launched_without_marker, f"the external self-PTY leg was launched: {launched_without_marker}")

    @activated
    def test_filled_observation_completes_and_classifies_resolved(self, tmp_path, monkeypatch):
        """The resolved arm is PRODUCIBLE: with a fill, the observation runs the board (here a
        governed gate whose panel carries four usable legs, the claude leg bound) and yields the
        three fields the byte-identical flattener and classifier need to read `resolved`."""
        from phase_loop_runtime import governed_review as gr_mod
        observe, Incomplete = _observe()
        NativeLegFill = _fill_symbols()[0]
        n = "test_filled_observation_completes_and_classifies_resolved"
        guard.require(n, observe is not None and Incomplete is not None and NativeLegFill is not None, "D5/D2 symbols absent")
        repo = _canonical_repo(tmp_path)
        monkeypatch.setenv("CLAUDECODE", "1")
        four = _four_vendor_board()
        claude_seat = next(seat for seat in four.seats if str(seat.harness).lower() == "claude")
        fill = _fill(NativeLegFill, claude_seat)
        legs = [pi.PanelLegResult(leg=str(seat.harness).lower(), status="OK", text="Reviewed.\nAGREE", seat_key=seat.seat_key)
                for seat in four.seats if str(seat.harness).lower() != "claude"]
        apply = _fill_symbols()[3]
        bound = apply([_deferred_leg(claude_seat)], [fill]) if apply is not None else []
        panel = pi.PanelResult(legs=tuple(bound + legs))
        gate_calls = []

        def fake_gate(**kw):
            gate_calls.append(kw)
            return gr_mod.GateResult(ran=True, promoted=True, panel=panel)

        monkeypatch.setattr(gr_mod, "governed_board_gate", fake_gate)
        out = observe(repo, SUBJECT, native_leg_fills=[fill], issue_snapshot={"state": "CLOSED", "stateReason": "completed"})
        guard.require(n, isinstance(out, Mapping) and not isinstance(out, Incomplete), f"filled observation did not complete: {out!r}")
        guard.require(n, gate_calls and gate_calls[-1].get("native_leg_fills"), "the board was not run with the fill")
        flat = le._flatten_reviewtruth_observation(out)
        guard.require(n, flat.get("native_fill_request") is True and flat.get("verdict_bound") is True and flat.get("seat_count") == "FULL",
                      f"flattened observation lacks the resolved fields: {flat}")
        guard.require(n, ra._classify_reviewtruth_transition({**flat, "issue_state": "CLOSED", "issue_disposition": "completed"}) == "resolved",
                      f"the byte-identical classifier does not read resolved: {flat}")
        # Outcome-sensitive: the same call over a board whose claude seat stayed DEFERRED (the fill
        # was not bound) must NOT report a bound verdict or a full board — an observer that always
        # reports resolved fields would pass the case above and fail here.
        unbound = pi.PanelResult(legs=tuple([_deferred_leg(claude_seat)] + legs))
        monkeypatch.setattr(gr_mod, "governed_board_gate", lambda **kw: gr_mod.GateResult(ran=True, promoted=False, panel=unbound))
        out2 = observe(repo, SUBJECT, native_leg_fills=[fill], issue_snapshot={"state": "CLOSED", "stateReason": "completed"})
        flat2 = le._flatten_reviewtruth_observation(out2) if isinstance(out2, Mapping) and not isinstance(out2, Incomplete) else {}
        guard.require(n, isinstance(out2, Incomplete) or (flat2.get("verdict_bound") is False and flat2.get("seat_count") != "FULL"),
                      f"an unbound board was reported as bound/full: {out2!r} → {flat2}")
        guard.require(n, ra._classify_reviewtruth_transition({**flat2, "issue_state": "CLOSED", "issue_disposition": "completed"}) != "resolved"
                      if flat2 else True, "an unbound board classified resolved")

    @activated
    def test_assumption_probe_caller_fails_closed_on_an_incomplete_observation(self, tmp_path, monkeypatch):
        observe, Incomplete = _observe()
        n = "test_assumption_probe_caller_fails_closed_on_an_incomplete_observation"
        guard.require(n, observe is not None and Incomplete is not None, "observe_reviewtruth_fable_transition / FableObservationIncomplete absent")
        spy = _Spy(result=Incomplete("fill_requested"))
        monkeypatch.setattr(le, "observe_reviewtruth_fable_transition", spy)
        classify, flatten = _Never("classifier"), _Never("flattener")
        monkeypatch.setattr(ra, "_classify_reviewtruth_transition", classify)
        monkeypatch.setattr(le, "_flatten_reviewtruth_observation", flatten)
        raised = None
        try:
            ra.observe_assumption_probe(tmp_path, {"kind": "reviewtruth_fable_transition", "subject": dict(SUBJECT)})
        except Exception as exc:  # the caller must fail CLOSED with a typed error, never return
            raised = exc
        guard.require(n, raised is not None, "an incomplete observation was returned to the caller instead of raising")
        guard.require(n, len(spy.calls) == 1 and classify.calls == 0 and flatten.calls == 0,
                      f"delegation={len(spy.calls)} classifier={classify.calls} flattener={flatten.calls}")

    @activated
    def test_sidecar_capture_refuses_an_incomplete_observation_and_writes_nothing(self, tmp_path, monkeypatch):
        observe, Incomplete = _observe()
        n = "test_sidecar_capture_refuses_an_incomplete_observation_and_writes_nothing"
        guard.require(n, observe is not None and Incomplete is not None, "observe_reviewtruth_fable_transition / FableObservationIncomplete absent")
        repo = _canonical_repo(tmp_path)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        observer = _Spy(result=Incomplete("fill_requested"))
        monkeypatch.setattr(le, "observe_reviewtruth_fable_transition", observer)
        raised = None
        try:
            le.capture_fresh_process_verification_sidecar(
                repo, run_dir=run_dir, stage="verification", expected_head="0" * 40, process_start_token="tok",
            )
        except le.LegibleSidecarError as exc:
            raised = exc
        guard.require(n, raised is not None and len(observer.calls) == 1,
                      f"an incomplete observation was sealed into a sidecar, or the observer never ran ({len(observer.calls)} calls)")
        guard.require(n, not any(run_dir.iterdir()), f"bytes were written on refusal: {sorted(p.name for p in run_dir.iterdir())}")
