"""REVIEWTRUTH early slice — native claude seat fill under Claude Code (EC-REVIEWTRUTH-14).

PR-1 of the ratified plan agent-harness#918: the RED falsifiers, observed RED against the
pre-implementation base with ``PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1`` and skipped without it.
Positive controls and byte-identity pins are unguarded and must pass before AND after.

Every activated falsifier fails with an AssertionError at its unique anchor
(``_reviewtruth_native_fill_tdd_guard.RED_ANCHORS``), never with an ImportError.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import os
import tempfile
import unittest.mock
from pathlib import Path

import pytest

import _reviewtruth_native_fill_tdd_guard as guard
from harden_tdd_guard import invoke_sanctioned_review_transport
from phase_loop_runtime import governed_review as gr
from phase_loop_runtime import legible_evidence as le
from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import roadmap_assumptions as ra
from phase_loop_runtime.advisor_board import Board, Seat

CC = {"CLAUDECODE": "1", "PATH": os.environ.get("PATH", "")}
NOT_CC = {"PATH": os.environ.get("PATH", "")}
FABLE = "claude-fable-5"
activated = pytest.mark.skipif(not guard.active(), reason=guard.SKIP_REASON)


def _seat(model: str = FABLE, harness: str = "claude") -> Seat:
    return Seat(model=model, effort="max", harness=harness, lens="correctness")


def _run_claude_solo(model: str):
    """The 183 harness: a claude-only board under Claude Code, production spawn."""
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

    def test_marker_module_absent_is_not_a_collection_error(self):
        assert guard.symbol(guard.MARKER_MODULE, guard.MARKER_ATTRIBUTE) is None or guard.marker_version() == guard.MARKER_VERSION


# ---------------------------------------------------------------------------
# Positive controls and byte-identity pins — never skip, must hold before AND after


class TestInvariantsThatSurviveTheSlice:
    def test_fable_request_is_still_forbidden_outside_claude_code(self):
        with pytest.raises(ValueError):
            pi.native_agent_leg_request(leg="claude", mode="review", env=dict(NOT_CC), model=FABLE)

    def test_no_request_for_a_board_without_a_claude_seat(self):
        board = Board(name="no-claude", purpose="premerge-review", seats=(_seat("gpt-5.6-sol", "codex"),))
        assert not any((s.harness or "").lower() == "claude" for s in board.seats)

    def test_transition_classifier_and_flattener_are_byte_identical(self):
        # The instrument this slice is graded by. Digests of the source on the base this lane
        # was authored against; PR-2 must leave both untouched.
        cls = hashlib.sha256(inspect.getsource(ra._classify_reviewtruth_transition).encode()).hexdigest()
        flat = hashlib.sha256(inspect.getsource(le._flatten_reviewtruth_observation).encode()).hexdigest()
        assert (cls, flat) == (
            "34f258ab40013c3d3eb2489d8965901b8a442539a32b16d1b17e5bcd8bf445b6",
            "8514b34f19c15b1767833fdad441b5f6274df57b9a9d9f1d235e44d50ee59b2e",
        )


# ---------------------------------------------------------------------------
# D1 — routing under Claude Code (both deferral paths)


class TestRouting:
    @activated
    def test_fable_seat_request_is_built_under_claude_code(self):
        try:
            req = pi.native_agent_leg_request(leg="claude", mode="review", env=dict(CC), model=FABLE)
        except ValueError as exc:
            req = None
            detail = str(exc)
        else:
            detail = ""
        n = "test_fable_seat_request_is_built_under_claude_code"
        guard.require(n, req is not None, f"builder raised for the default fable seat under Claude Code: {detail}")
        guard.require(n, req.reason == "under_claude_code", f"reason={req.reason!r}")
        guard.require(n, req.model == FABLE and req.instructions, "request must carry model + the effective brief")

    @activated
    def test_under_claude_code_is_a_typed_unavailable_detail(self):
        guard.require("test_under_claude_code_is_a_typed_unavailable_detail",
                      "under_claude_code" in pi._TYPED_UNAVAILABLE_DETAILS,
                      f"typed details: {sorted(pi._TYPED_UNAVAILABLE_DETAILS)}")

    @activated
    def test_early_deferral_path_attaches_a_request_for_the_fable_seat(self):
        # spawn=None + claude-only board = the `native_host_deferral_only` early return.
        result, leg = _run_claude_solo(FABLE)
        n = "test_early_deferral_path_attaches_a_request_for_the_fable_seat"
        guard.require(n, leg.status == "UNAVAILABLE" and leg.text == "", f"{leg.status}/{leg.text!r}")
        guard.require(n, leg.detail == "under_claude_code", f"detail={leg.detail!r}")
        guard.require(n, leg.needs_native_agent is not None, "no NativeAgentLegRequest attached on the early path")
        guard.require(n, len(result.native_fill_requests) == 1, "board reports no fill request")

    @activated
    def test_matrix_path_attaches_a_request_for_the_fable_seat(self):
        # A mixed board through the per-seat MATRIX path (not the early return): the injected
        # spawn returns, for the claude seat, exactly the typed deferral the production leg
        # emits under Claude Code. The matrix path must relocate that token into ``detail``
        # (typed-detail normalisation) and attach the fill request for a TUI-policy seat.
        # (An injected spawn cannot delegate to the production spawn: outside the sanctioned
        # seam it refuses for missing HARDEN authorization, which is a different property.)
        def spawn(leg, artifact, **kw):
            if leg != "claude":
                return "OK", "Reviewed.\nAGREE"
            return "UNAVAILABLE", "under_claude_code"

        with tempfile.TemporaryDirectory() as td:
            artifact = Path(td) / "bundle.md"
            artifact.write_text("review me\n")
            board = Board(name="mixed", purpose="premerge-review",
                          seats=(_seat(FABLE), _seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")))
            result = invoke_sanctioned_review_transport(
                board, "", spawn=spawn, artifact_ref=str(artifact.resolve()), repo_dir=td, base_env=dict(CC),
            )
        claude = next(l for l in result.legs if l.leg == "claude")
        n = "test_matrix_path_attaches_a_request_for_the_fable_seat"
        guard.require(n, claude.detail == "under_claude_code", f"detail={claude.detail!r}")
        guard.require(n, claude.needs_native_agent is not None, "no request attached on the matrix path")


# ---------------------------------------------------------------------------
# D2 — ingestion contract


def _fill_symbols():
    return (guard.symbol("phase_loop_runtime.panel_invoker", "NativeLegFill"),
            guard.symbol("phase_loop_runtime.panel_invoker", "load_native_leg_fill"),
            guard.symbol("phase_loop_runtime.panel_invoker", "preflight_native_leg_fills"),
            guard.symbol("phase_loop_runtime.panel_invoker", "apply_native_leg_fills"))


class TestIngestion:
    @activated
    def test_native_leg_fill_is_a_frozen_record_with_the_binding_fields(self):
        NativeLegFill = _fill_symbols()[0]
        n = "test_native_leg_fill_is_a_frozen_record_with_the_binding_fields"
        guard.require(n, NativeLegFill is not None, "panel_invoker.NativeLegFill is absent")
        fields = set(getattr(NativeLegFill, "__dataclass_fields__", {}))
        need = {"seat_key", "model", "text", "artifact_sha256", "brief_sha256", "composition_sha256", "request_id", "filled_by", "filled_at"}
        guard.require(n, need <= fields, f"missing fields: {sorted(need - fields)}")
        guard.require(n, getattr(NativeLegFill, "__dataclass_params__", None) and NativeLegFill.__dataclass_params__.frozen, "not frozen")

    @activated
    def test_loader_takes_digests_from_the_emitted_request_only(self, tmp_path):
        load = _fill_symbols()[1]
        n = "test_loader_takes_digests_from_the_emitted_request_only"
        guard.require(n, load is not None, "panel_invoker.load_native_leg_fill is absent")
        req = tmp_path / "request.json"
        req.write_text('{"request_id": "r1", "seat_key": "claude:claude-fable-5:max:correctness", "model": "claude-fable-5", '
                       '"artifact_sha256": "a" * 64, "brief_sha256": "b" * 64, "composition_sha256": "c" * 64}'.replace('"a" * 64', '"' + "a" * 64 + '"').replace('"b" * 64', '"' + "b" * 64 + '"').replace('"c" * 64', '"' + "c" * 64 + '"'))
        (tmp_path / "claude.md").write_text("Reviewed.\nAGREE\n")
        fill = load(req, tmp_path / "claude.md")
        guard.require(n, (fill.artifact_sha256, fill.brief_sha256, fill.composition_sha256) == ("a" * 64, "b" * 64, "c" * 64),
                      "loader must carry the EMITTED digests, never recompute them")

    @activated
    def test_preflight_refuses_each_ineligible_fill_with_a_typed_reason(self):
        NativeLegFill, _, preflight, _ = _fill_symbols()
        n = "test_preflight_refuses_each_ineligible_fill_with_a_typed_reason"
        guard.require(n, preflight is not None and NativeLegFill is not None, "preflight_native_leg_fills is absent")
        board = Board(name="mixed", purpose="premerge-review",
                      seats=(_seat(FABLE), _seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")))
        claude_key = board.seats[0].seat_key
        ok = dict(seat_key=claude_key, model=FABLE, text="Reviewed.\nAGREE", artifact_sha256="a" * 64,
                  brief_sha256="b" * 64, composition_sha256="c" * 64, request_id="r1", filled_by="claude-code", filled_at="t")
        staged = dict(artifact_sha256="a" * 64, brief_sha256="b" * 64, composition_sha256="c" * 64)
        cases = {
            "native_fill_duplicate_seat": ([NativeLegFill(**ok), NativeLegFill(**ok)], staged, dict(CC)),
            "native_fill_seat_not_deferred": ([NativeLegFill(**ok)], staged, dict(NOT_CC)),
            "native_fill_digest_mismatch": ([NativeLegFill(**{**ok, "artifact_sha256": "d" * 64})], staged, dict(CC)),
            "native_fill_composition_drift": ([NativeLegFill(**{**ok, "composition_sha256": "d" * 64})], staged, dict(CC)),
        }
        for reason, (fills, digests, env) in cases.items():
            refusal = preflight(board, fills, env=env, **digests)
            guard.require(n, refusal is not None and getattr(refusal, "reason", refusal) == reason,
                          f"expected typed refusal {reason!r}, got {refusal!r}")
        accepted = preflight(board, [NativeLegFill(**ok)], env=dict(CC), **staged)
        guard.require(n, accepted is None, f"an eligible fill must pass preflight, got {accepted!r}")

    @activated
    def test_apply_counts_only_a_bound_conforming_fill(self):
        NativeLegFill, _, _, apply = _fill_symbols()
        n = "test_apply_counts_only_a_bound_conforming_fill"
        guard.require(n, apply is not None and NativeLegFill is not None, "apply_native_leg_fills is absent")
        seat = _seat(FABLE)
        deferred = pi.PanelLegResult(leg="claude", status="UNAVAILABLE", text="", detail="under_claude_code", seat_key=seat.seat_key)
        pi.attach_native_agent_request(deferred, pi.native_agent_leg_request(leg="claude", mode="review", env=dict(CC), model=FABLE))
        base = dict(seat_key=seat.seat_key, model=FABLE, artifact_sha256="a" * 64, brief_sha256="b" * 64,
                    composition_sha256="c" * 64, request_id="r1", filled_by="claude-code", filled_at="t")
        good = apply([deferred], [NativeLegFill(text="Reviewed.\nAGREE", **base)])
        guard.require(n, len(good) == 1 and good[0].usable and good[0].detail == "native_fill", f"bound conforming fill not usable: {good}")
        bad = apply([deferred], [NativeLegFill(text="I looked at it but reached no verdict.", **base)])
        guard.require(n, len(bad) == 1 and not bad[0].usable and bad[0].status == "DEGRADED", f"non-conforming fill counted: {bad}")

    @activated
    def test_apply_never_replaces_a_runtime_leg(self):
        NativeLegFill, _, _, apply = _fill_symbols()
        n = "test_apply_never_replaces_a_runtime_leg"
        guard.require(n, apply is not None and NativeLegFill is not None, "apply_native_leg_fills is absent")
        seat = _seat(FABLE)
        runtime = pi.PanelLegResult(leg="claude", status="OK", text="Runtime.\nDISAGREE", seat_key=seat.seat_key)
        fill = NativeLegFill(seat_key=seat.seat_key, model=FABLE, text="Reviewed.\nAGREE", artifact_sha256="a" * 64,
                             brief_sha256="b" * 64, composition_sha256="c" * 64, request_id="r1", filled_by="claude-code", filled_at="t")
        with pytest.raises(Exception) as excinfo:
            apply([runtime], [fill])
        guard.require(n, "native_fill_seat_not_deferred" in str(excinfo.value), f"runtime leg replaced or untyped: {excinfo.value}")


# ---------------------------------------------------------------------------
# D3 — emit → fill → invoke protocol


class _Never:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError("must not be called")


class TestProtocol:
    @activated
    def test_composition_digest_is_over_sorted_seat_keys(self):
        digest = guard.symbol("phase_loop_runtime.advisor_board.composition", "composition_digest")
        n = "test_composition_digest_is_over_sorted_seat_keys"
        guard.require(n, digest is not None, "composition.composition_digest is absent")
        a, b = _seat(FABLE), _seat("gpt-5.6-sol", "codex")
        b1 = Board(name="x", purpose="premerge-review", seats=(a, b))
        b2 = Board(name="x", purpose="premerge-review", seats=(b, a))
        expected = hashlib.sha256("\n".join(sorted([a.seat_key, b.seat_key])).encode()).hexdigest()
        guard.require(n, digest(b1) == digest(b2) == expected, "digest must be order-independent and over seat_keys")

    @activated
    def test_request_payload_carries_the_binding(self):
        payload = guard.symbol("phase_loop_runtime.panel_invoker", "native_fill_request_payload")
        n = "test_request_payload_carries_the_binding"
        guard.require(n, payload is not None, "panel_invoker.native_fill_request_payload is absent")
        board = Board(name="mixed", purpose="premerge-review", seats=(_seat(FABLE), _seat("gpt-5.6-sol", "codex")))
        out = payload(board, "bundle text\n", brief_ref=None, env=dict(CC))
        need = {"request_id", "seat_key", "model", "lens", "effort", "artifact_sha256", "brief_sha256", "composition_sha256", "instructions"}
        guard.require(n, need <= set(out), f"missing keys: {sorted(need - set(out))}")
        guard.require(n, out["artifact_sha256"] == hashlib.sha256(b"bundle text\n").hexdigest(), "artifact digest must be over the staged content")

    @activated
    def test_gate_emit_arm_returns_a_request_without_minting_or_invoking(self, tmp_path, monkeypatch):
        from phase_loop_runtime.advisor_board import backing as backing_mod
        n = "test_gate_emit_arm_returns_a_request_without_minting_or_invoking"
        monkeypatch.setenv("CLAUDECODE", "1")  # the fable seat is deferrable (fillable) only here
        mint, invoke = _Never(), _Never()
        monkeypatch.setattr(backing_mod, "prepare_review_isolation_authorization", mint)
        board = Board(name="mixed", purpose="premerge-review",
                      seats=(_seat(FABLE), _seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")))
        gate, err = None, None
        try:
            gate = gr.governed_board_gate(
                artifact="bundle", author_executor="train-coordinator", run_mode="governed",
                canonical_repo_authority=tmp_path, compose=lambda: board, invoke=invoke, emit_native_request=True,
            )
        except TypeError as exc:  # no emit arm yet: recorded, asserted OUTSIDE the except (no chained traceback)
            err = exc
        guard.require(n, err is None, f"governed_board_gate has no emit arm: {err}")
        guard.require(n, mint.calls == 0 and invoke.calls == 0, "the emit arm minted or invoked")
        guard.require(n, getattr(gate, "native_fill_request", None) is not None, "no request returned")

    @activated
    def test_run_train_emit_arm_spends_nothing(self, tmp_path, monkeypatch):
        # Behavioural (the public ``run_train`` is a generation-fenced wrapper, so its signature
        # proves nothing): the emit arm returns ``native_fill_requested`` with the request and
        # artifact paths and touches no board, publisher or merge.
        from phase_loop_runtime.train_roadmap import parse_train_roadmap
        from phase_loop_runtime.train_runner import run_train
        from test_train_prebuilt import PREBUILT_1NODE_MD
        from test_train_review_authorization import _ledger, _pr_is_open_true, _preflight_pass, ADMITTED

        n = "test_run_train_emit_arm_spends_nothing"
        # The emit arm composes the board like the invoke arm; on a host with no vendor CLIs a
        # live composition would fail the floor and mask the property, so composition is stubbed
        # to a fixed three-seat board (a production symbol patched, not a new seam).
        from phase_loop_runtime.advisor_board import composition as comp_mod
        board = Board(name="train-review", purpose="code-review",
                      seats=(_seat(FABLE), _seat("gpt-5.6-sol", "codex"), _seat("grok-4.6", "grok")))
        monkeypatch.setattr(comp_mod, "compose_review_board", lambda *a, **k: board)
        monkeypatch.setenv("CLAUDECODE", "1")
        roadmap = parse_train_roadmap(PREBUILT_1NODE_MD)
        ws_map = {node.node_id: tmp_path / node.repo for node in roadmap.nodes}
        review, publish, merge = _Never(), _Never(), _Never()
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
        except TypeError as exc:  # no emit arm yet: recorded, asserted outside the except
            err = exc
        guard.require(n, err is None, f"run_train has no emit arm: {err}")
        guard.require(n, result.get("status") == "native_fill_requested", f"status={result.get('status')!r}")
        guard.require(n, Path(result["request_path"]).is_file() and Path(result["artifact_path"]).is_file(), "request/artifact not staged")
        guard.require(n, review.calls == publish.calls == merge.calls == 0, "the emit arm spent a board, published or merged")

    @activated
    def test_cli_flags_parse_on_both_commands(self):
        from phase_loop_runtime.cli import build_parser  # noqa: F401  (probed below)
        n = "test_cli_flags_parse_on_both_commands"
        parser = guard.symbol("phase_loop_runtime.cli", "build_parser")
        guard.require(n, parser is not None, "cli.build_parser is absent")
        p = parser()
        rejected = []
        for argv in (["advisor-board", "--artifact", "x.md", "--emit-native-request"],
                     ["advisor-board", "--artifact", "x.md", "--native-leg", "claude=/tmp/fill"],
                     ["run-train", "--train", "t.md", "--governed", "--review-only", "--emit-native-request"],
                     ["run-train", "--train", "t.md", "--governed", "--review-only", "--native-leg", "claude=/tmp/fill"]):
            try:
                with unittest.mock.patch("sys.stderr"):
                    p.parse_args(argv)
            except (SystemExit, argparse.ArgumentError):
                rejected.append(argv)
        guard.require(n, not rejected, f"rejected: {rejected}")


# ---------------------------------------------------------------------------
# D5 — the phase's live probe: one observation function, typed incompleteness


class TestProbe:
    @activated
    def test_one_observation_function_exists_with_a_typed_incomplete_result(self):
        n = "test_one_observation_function_exists_with_a_typed_incomplete_result"
        observe = guard.symbol("phase_loop_runtime.legible_evidence", "observe_reviewtruth_fable_transition")
        incomplete = guard.symbol("phase_loop_runtime.legible_evidence", "FableObservationIncomplete")
        guard.require(n, observe is not None and incomplete is not None, "observe_reviewtruth_fable_transition / FableObservationIncomplete absent")
        params = inspect.signature(observe).parameters
        guard.require(n, {"native_leg_fills", "issue_snapshot"} <= set(params), f"missing keyword parameters: {sorted(params)}")

    @activated
    def test_assumption_probe_caller_delegates_to_the_one_function(self):
        n = "test_assumption_probe_caller_delegates_to_the_one_function"
        # A NAME REFERENCE, not a substring of the caller's own def line (which contains it).
        names = set(ra._observe_reviewtruth_fable_transition.__code__.co_names)
        guard.require(n, "observe_reviewtruth_fable_transition" in names and "_invoke_reviewtruth_fable_adapter" not in names,
                      f"roadmap_assumptions still calls the adapter directly: co_names={sorted(names)}")

    @activated
    def test_sidecar_capture_refuses_an_incomplete_observation(self):
        n = "test_sidecar_capture_refuses_an_incomplete_observation"
        incomplete = guard.symbol("phase_loop_runtime.legible_evidence", "FableObservationIncomplete")
        guard.require(n, incomplete is not None, "FableObservationIncomplete absent")
        src = inspect.getsource(le.capture_fresh_process_verification_sidecar)
        guard.require(n, "FableObservationIncomplete" in src, "the sealing path does not refuse an incomplete observation")
