"""Availability-aware 4-vendor board composition — the load-bearing behavior.

Proves the core requirement: a panel NEVER collapses to one or two reviewers just
because one or two vendors are down. For 4 / 3 / 2 / 1 available vendors the
composer produces a full ``target`` (=4) seats, never below the floor (=3), with
NO duplicate ``(vendor, model, lens)`` seat and lens diversity when backfilling.
The 1-vendor case yields 4 distinct-lens seats on that one vendor.

Availability is SIMULATED via an injected probe (``is_available``), the same seam
the live composer defaults to ``DEFAULT_HARNESS_REGISTRY.is_available`` — so these
tests exercise the exact fallback the runtime uses, without touching the network
or PATH.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harden_tdd_guard import (
    assert_exact_unavailable,
    harden_require,
    invoke_sanctioned_board_control,
)
from phase_loop_runtime.advisor_board import (
    DEFAULT_TARGET_SEATS,
    FLOOR_SEATS,
    LENS_CYCLE,
    board_independence,
    compose_review_board,
    default_board_auth_ok,
    default_matrix,
    validate_board,
)
from phase_loop_runtime.advisor_board import composition as _composition

ALL_VENDORS = ("grok", "claude", "codex", "gemini")


def _probe(up):
    up = set(up)
    return lambda vendor: vendor in up


def _keys(board):
    """Dedup identity per seat = (vendor-lane, model, lens)."""
    return [(s.harness, s.model, s.lens) for s in board.seats]


def test_review_leg_isolation_refuses_unbound_direct_invocation():
    harden_require("review-leg-isolation")
    import subprocess

    from phase_loop_runtime import agy_canary_evidence as evidence
    from phase_loop_runtime import panel_invoker as invoker
    from phase_loop_runtime.advisor_board import (
        BACKING_OMNIGENT,
        Board,
        ResearchPolicy,
        ResearchRunConfig,
        ResearchSeatConfig,
        Seat,
    )
    from phase_loop_runtime.advisor_board import matrix as matrix_mod
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    from phase_loop_runtime.panel_invoker import invoke_board

    effects: list[object] = []
    completion_effects: list[object] = []
    sink_effects: list[object] = []
    provider_effects: list[object] = []
    child_effects: list[object] = []
    omnigent_effects: list[str] = []
    raw_default_matrix_calls: list[object] = []
    raw_availability_calls: list[object] = []
    raw_incremental_verdict_calls: list[object] = []
    raw_leg_auth_calls: list[object] = []
    raw_claude_auth_calls: list[object] = []
    raw_claude_support_calls: list[object] = []
    raw_staged_input_calls: list[object] = []
    raw_provider_authority_calls: list[object] = []
    raw_provider_launch_seal_calls: list[object] = []
    raw_cleanup_root_allocation_calls: list[object] = []

    def direct_effect(*args, **kwargs):
        effects.append((args, kwargs))
        return "OK", "unexpected direct provider effect"

    def provider_effect(*args, **kwargs):
        provider_effects.append((args, kwargs))
        return "OK", "unexpected provider effect"

    def child_effect(*args, **kwargs):
        child_effects.append((args, kwargs))
        return "OK", "unexpected direct child effect"

    class RawEffectSink:
        def emit(self, event: object) -> None:
            sink_effects.append(event)

    original_default_matrix = invoker.default_matrix
    original_write_incremental_verdict = invoker._write_incremental_verdict

    def raw_default_matrix(*args: object, **matrix_kwargs: object) -> object:
        raw_default_matrix_calls.append((args, matrix_kwargs))
        deterministic_kwargs = dict(matrix_kwargs)
        deterministic_kwargs["env"] = {}
        return original_default_matrix(*args, **deterministic_kwargs)

    def raw_live_availability(*args: object, **availability_kwargs: object) -> bool:
        raw_availability_calls.append((args, availability_kwargs))
        return True

    def raw_write_incremental_verdict(*args: object, **verdict_kwargs: object) -> object:
        raw_incremental_verdict_calls.append((args, verdict_kwargs))
        return original_write_incremental_verdict(*args, **verdict_kwargs)

    def raw_leg_auth_ok(*args: object, **auth_kwargs: object) -> tuple[bool, str]:
        raw_leg_auth_calls.append((args, auth_kwargs))
        return True, ""

    def raw_claude_subscription_auth_ok(
        *args: object, **auth_kwargs: object
    ) -> tuple[bool, str]:
        raw_claude_auth_calls.append((args, auth_kwargs))
        return True, ""

    def raw_claude_code_support_status(
        *args: object, **support_kwargs: object
    ) -> tuple[bool, str]:
        raw_claude_support_calls.append((args, support_kwargs))
        return True, ""

    def raw_bind_staged_review_inputs(*args: object, **stage_kwargs: object) -> None:
        raw_staged_input_calls.append((args, stage_kwargs))

    def raw_prepare_provider_launch_authorities(
        *args: object, **authority_kwargs: object
    ) -> dict[str, object]:
        raw_provider_authority_calls.append((args, authority_kwargs))
        return {}

    def raw_seal_provider_launches(*args: object, **seal_kwargs: object) -> None:
        raw_provider_launch_seal_calls.append((args, seal_kwargs))

    def raw_create_owned_cleanup_root(
        *args: object, **cleanup_kwargs: object
    ) -> object:
        raw_cleanup_root_allocation_calls.append((args, cleanup_kwargs))
        raise AssertionError("raw capture must refuse before cleanup-root allocation")

    advisory_board = Board(
        name="raw-advisory-control",
        purpose="general",
        seats=DEFAULT_BOARD.seats,
    )
    magic_board = Board(
        name="raw-magic-purpose-control",
        purpose="x",
        seats=DEFAULT_BOARD.seats,
    )
    research_advisory_board = Board(
        name="raw-configured-research-advisory-control",
        purpose="general",
        research_policy=ResearchPolicy(enabled=True),
        seats=DEFAULT_BOARD.seats,
    )
    fake_omnigent_board = Board(
        name="raw-fake-omnigent-control",
        purpose="general",
        seats=(
            Seat(
                model="gpt-5.6-sol",
                effort="high",
                harness="opencode",
                backing=BACKING_OMNIGENT,
            ),
        ),
    )

    class FakeOmnigentOnly:
        def catalog_harnesses(self):
            omnigent_effects.append("catalog")
            return frozenset({"opencode"})

        def run_seat(self, *_args, **_kwargs):
            omnigent_effects.append("run")
            return "OK", "unexpected omnigent effect"

    canonical_repo = Path(
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    ).resolve()
    with tempfile.TemporaryDirectory(prefix="harden-raw-controls-") as td:
        root = Path(td)
        raw_stream_dir = root / "stream"
        research_root = root / "research-run"
        research_root.mkdir()
        policy_path = research_root / "policy.json"
        provider_config_path = research_root / ".mcp.json"
        manifest_dir = research_root / ".pmcp"
        manifest_dir.mkdir()
        manifest_path = manifest_dir / "manifest.yaml"
        for path in (policy_path, provider_config_path, manifest_path):
            path.write_text("{}\n", encoding="utf-8")
        for index in range(len(research_advisory_board.seats)):
            (research_root / f"seat-{index:04d}" / "lock").mkdir(parents=True)
        research_run = ResearchRunConfig(
            root=research_root,
            run_correlation_id="harden-raw-research-run",
            policy_digest="0" * 64,
            seats=tuple(
                ResearchSeatConfig(
                    lane=(seat.harness or "").lower(),
                    run_correlation_id="harden-raw-research-run",
                    seat_correlation_id=f"seat-{index:04d}",
                    evidence_label=f"research-evidence-{index:04d}",
                    evidence_label_digest="1" * 64,
                    policy_path=policy_path,
                    provider_config_path=provider_config_path,
                    manifest_path=manifest_path,
                    policy_digest="0" * 64,
                    lock_dir=research_root / f"seat-{index:04d}" / "lock",
                    audit_path=research_root / f"seat-{index:04d}" / "audit.jsonl",
                    pmcp_command=research_advisory_board.research_policy.pmcp_command,
                )
                for index, seat in enumerate(research_advisory_board.seats)
            ),
        )
        review_capture_root = tempfile.TemporaryDirectory(prefix="harden-raw-review-capture-")
        advisory_capture_root = tempfile.TemporaryDirectory(prefix="harden-raw-advisory-capture-")
        review_capture = evidence.AgyCanaryCapture(
            *evidence._validate_private_root(Path(review_capture_root.name))
        )
        advisory_capture = evidence.AgyCanaryCapture(
            *evidence._validate_private_root(Path(advisory_capture_root.name))
        )
        try:
            with patch.object(
            invoker,
            "default_matrix",
            side_effect=raw_default_matrix,
        ), patch.object(
            matrix_mod.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            side_effect=raw_live_availability,
        ), patch.object(
            invoker,
            "_write_incremental_verdict",
            side_effect=raw_write_incremental_verdict,
        ), patch.object(
            invoker,
            "materialize_research_run",
            return_value=research_run,
        ) as materialize_spy, patch.object(
            invoker,
            "_default_spawn",
            side_effect=child_effect,
        ), patch.object(
            invoker,
            "_default_spawn_via_provider",
            side_effect=provider_effect,
        ), patch.object(
            invoker,
            "_create_owned_cleanup_root",
            side_effect=raw_create_owned_cleanup_root,
        ), patch.object(
            invoker,
            "_leg_auth_ok",
            side_effect=raw_leg_auth_ok,
        ), patch.object(
            invoker,
            "_claude_subscription_auth_ok",
            side_effect=raw_claude_subscription_auth_ok,
        ), patch.object(
            invoker,
            "_claude_code_support_status",
            side_effect=raw_claude_code_support_status,
        ), patch.object(
            invoker,
            "bind_staged_review_inputs",
            side_effect=raw_bind_staged_review_inputs,
        ), patch.object(
            invoker,
            "prepare_provider_launch_authorities",
            side_effect=raw_prepare_provider_launch_authorities,
        ), patch.object(
            invoker,
            "seal_provider_launches",
            side_effect=raw_seal_provider_launches,
        ):
                result = invoke_board(
                    DEFAULT_BOARD,
                    "review bundle",
                    spawn=direct_effect,
                    mode="review",
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                advisory_result = invoke_board(
                    advisory_board,
                    "advisory bundle",
                    spawn=direct_effect,
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                scratch = root / "private-scratch"
                scratch.mkdir()
                advisory_authority_result = invoker.invoke_board(
                    advisory_board,
                    "bounded derived-advisory fixture",
                    spawn=direct_effect,
                    repo_dir=scratch,
                    canonical_repo_authority=canonical_repo,
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                magic_result = invoker.invoke_board(
                    magic_board,
                    "magic-purpose bundle",
                    spawn=direct_effect,
                    mode="advisory",
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                provider_patch_result = invoker.invoke_board(
                    DEFAULT_BOARD,
                    "provider-patch bundle",
                    mode="review",
                    base_env={},
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                magic_provider_result = invoker.invoke_board(
                    magic_board,
                    "magic-purpose provider-patch bundle",
                    mode="advisory",
                    base_env={},
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                research_provider_result = invoker.invoke_board(
                    research_advisory_board,
                    "configured-research provider-patch bundle",
                    mode="advisory",
                    base_env={},
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                fake_omnigent_result = invoker.invoke_board(
                    fake_omnigent_board,
                    "fake-omnigent bundle",
                    omnigent=FakeOmnigentOnly(),
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                fake_omnigent_review_result = invoker.invoke_board(
                    fake_omnigent_board,
                    "fake-omnigent review bundle",
                    omnigent=FakeOmnigentOnly(),
                    mode="review",
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                raw_review_capture_result = invoker.invoke_board(
                    DEFAULT_BOARD,
                    "raw review capture bundle",
                    agy_canary_capture=review_capture,
                    base_env={},
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
                raw_advisory_capture_result = invoker.invoke_board(
                    advisory_board,
                    "raw advisory capture bundle",
                    mode="advisory",
                    agy_canary_capture=advisory_capture,
                    base_env={},
                    on_leg_complete=completion_effects.append,
                    sink=RawEffectSink(),
                    stream_dir=raw_stream_dir,
                )
        finally:
            review_capture.close()
            advisory_capture.close()
            review_capture_root.cleanup()
            advisory_capture_root.cleanup()
        assert not tuple(raw_stream_dir.glob("*.verdict.json"))

    assert not effects
    assert not completion_effects
    assert not sink_effects
    assert not provider_effects
    assert not child_effects
    assert not omnigent_effects
    assert not raw_default_matrix_calls
    assert not raw_availability_calls
    assert not raw_incremental_verdict_calls
    assert not raw_leg_auth_calls
    assert not raw_claude_auth_calls
    assert not raw_claude_support_calls
    assert not raw_staged_input_calls
    assert not raw_provider_authority_calls
    assert not raw_provider_launch_seal_calls
    assert not raw_cleanup_root_allocation_calls
    materialize_spy.assert_not_called()
    assert_exact_unavailable(DEFAULT_BOARD, result)
    assert_exact_unavailable(advisory_board, advisory_result)
    assert_exact_unavailable(advisory_board, advisory_authority_result)
    assert_exact_unavailable(magic_board, magic_result)
    assert_exact_unavailable(DEFAULT_BOARD, provider_patch_result)
    assert_exact_unavailable(magic_board, magic_provider_result)
    assert_exact_unavailable(research_advisory_board, research_provider_result)
    assert_exact_unavailable(fake_omnigent_board, fake_omnigent_result)
    assert_exact_unavailable(fake_omnigent_board, fake_omnigent_review_result)
    assert_exact_unavailable(DEFAULT_BOARD, raw_review_capture_result)
    assert_exact_unavailable(advisory_board, raw_advisory_capture_result)


def test_derived_review_refuses_missing_or_forged_authority_before_callback():
    """A mode-omitted premerge board cannot spend either execution seam unbound."""

    harden_require("review-leg-isolation")
    import subprocess

    from phase_loop_runtime import agy_canary_evidence as evidence
    from phase_loop_runtime import panel_invoker as invoker
    from phase_loop_runtime.advisor_board import backing as backing_mod
    from phase_loop_runtime.advisor_board import matrix as matrix_mod
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    canonical_repo = Path(
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
    ).resolve()
    callback_effects: list[str] = []
    provider_effects: list[object] = []
    child_effects: list[object] = []
    completion_effects: list[object] = []
    sink_effects: list[object] = []
    raw_default_matrix_calls: list[object] = []
    raw_availability_calls: list[object] = []
    raw_incremental_verdict_calls: list[object] = []
    raw_leg_auth_calls: list[object] = []
    raw_claude_auth_calls: list[object] = []
    raw_claude_support_calls: list[object] = []

    def callback(*_args, **_kwargs):
        callback_effects.append("callback")
        return "OK", "unexpected unbound callback\nAGREE"

    valid_artifact = "bounded raw-valid-review fixture"
    valid_authorization = backing_mod.prepare_review_isolation_authorization(
        DEFAULT_BOARD,
        valid_artifact,
        mode="review",
        canonical_repo_authority=canonical_repo,
    )
    valid_callback_effects: list[str] = []

    def valid_callback(*_args, **_kwargs):
        valid_callback_effects.append("callback")
        return "OK", "unexpected raw valid callback\nAGREE"

    def provider_effect(*args, **kwargs):
        provider_effects.append((args, kwargs))
        return "OK", "unexpected raw provider effect"

    def child_effect(*args, **kwargs):
        child_effects.append((args, kwargs))
        return "OK", "unexpected raw child effect"

    class RawRefusalSink:
        def emit(self, event: object) -> None:
            sink_effects.append(event)

    original_default_matrix = invoker.default_matrix
    original_write_incremental_verdict = invoker._write_incremental_verdict

    def raw_default_matrix(*args: object, **matrix_kwargs: object) -> object:
        raw_default_matrix_calls.append((args, matrix_kwargs))
        deterministic_kwargs = dict(matrix_kwargs)
        deterministic_kwargs["env"] = {}
        return original_default_matrix(*args, **deterministic_kwargs)

    def raw_live_availability(*args: object, **availability_kwargs: object) -> bool:
        raw_availability_calls.append((args, availability_kwargs))
        return True

    def raw_write_incremental_verdict(*args: object, **verdict_kwargs: object) -> object:
        raw_incremental_verdict_calls.append((args, verdict_kwargs))
        return original_write_incremental_verdict(*args, **verdict_kwargs)

    def raw_leg_auth_ok(*args: object, **auth_kwargs: object) -> tuple[bool, str]:
        raw_leg_auth_calls.append((args, auth_kwargs))
        return True, ""

    def raw_claude_subscription_auth_ok(
        *args: object, **auth_kwargs: object
    ) -> tuple[bool, str]:
        raw_claude_auth_calls.append((args, auth_kwargs))
        return True, ""

    def raw_claude_code_support_status(
        *args: object, **support_kwargs: object
    ) -> tuple[bool, str]:
        raw_claude_support_calls.append((args, support_kwargs))
        return True, ""

    with tempfile.TemporaryDirectory(prefix="harden-raw-review-") as td:
        root = Path(td)
        scratch = root / "private-scratch"
        scratch.mkdir()
        assert scratch.resolve() != canonical_repo
        raw_stream_dir = root / "stream"
        with patch.object(
            invoker,
            "default_matrix",
            side_effect=raw_default_matrix,
        ), patch.object(
            matrix_mod.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            side_effect=raw_live_availability,
        ), patch.object(
            invoker,
            "_write_incremental_verdict",
            side_effect=raw_write_incremental_verdict,
        ), patch.object(
            invoker,
            "_default_spawn",
            side_effect=child_effect,
        ), patch.object(
            invoker,
            "_default_spawn_via_provider",
            side_effect=provider_effect,
        ), patch.object(
            invoker,
            "_leg_auth_ok",
            side_effect=raw_leg_auth_ok,
        ), patch.object(
            invoker,
            "_claude_subscription_auth_ok",
            side_effect=raw_claude_subscription_auth_ok,
        ), patch.object(
            invoker,
            "_claude_code_support_status",
            side_effect=raw_claude_code_support_status,
        ):
            missing = invoker.invoke_board(
                DEFAULT_BOARD,
                "bounded derived-review fixture",
                spawn=callback,
                repo_dir=scratch,
                canonical_repo_authority=canonical_repo,
                on_leg_complete=completion_effects.append,
                sink=RawRefusalSink(),
                stream_dir=raw_stream_dir,
            )
            forged = invoker.invoke_board(
                DEFAULT_BOARD,
                "bounded derived-review fixture",
                spawn=callback,
                repo_dir=scratch,
                canonical_repo_authority=canonical_repo,
                review_authorization=object(),
                on_leg_complete=completion_effects.append,
                sink=RawRefusalSink(),
                stream_dir=raw_stream_dir,
            )
            valid = invoker.invoke_board(
                DEFAULT_BOARD,
                valid_artifact,
                spawn=valid_callback,
                repo_dir=scratch,
                mode="review",
                canonical_repo_authority=canonical_repo,
                review_authorization=valid_authorization,
                base_env={},
                max_concurrency=1,
                on_leg_complete=completion_effects.append,
                sink=RawRefusalSink(),
                stream_dir=raw_stream_dir,
            )
        assert not tuple(raw_stream_dir.glob("*.verdict.json"))

    assert not valid_callback_effects
    assert not callback_effects
    assert not provider_effects
    assert not child_effects
    assert not completion_effects
    assert not sink_effects
    assert not raw_default_matrix_calls
    assert not raw_availability_calls
    assert not raw_incremental_verdict_calls
    assert not raw_leg_auth_calls
    assert not raw_claude_auth_calls
    assert not raw_claude_support_calls
    assert_exact_unavailable(DEFAULT_BOARD, missing)
    assert_exact_unavailable(DEFAULT_BOARD, forged)
    assert_exact_unavailable(DEFAULT_BOARD, valid)

    marked_effects: list[str] = []
    artifact = "bounded marked review fixture"
    forged_authorization = object()
    stale_authorization = backing_mod.prepare_review_isolation_authorization(
        DEFAULT_BOARD,
        "stale marked review fixture",
        mode="review",
        canonical_repo_authority=canonical_repo,
    )

    def marked_callback(*_args, **_kwargs):
        marked_effects.append("callback")
        return "OK", "unexpected marked callback\nAGREE"

    def marked_provider(*_args, **_kwargs):
        marked_effects.append("provider")
        return "OK", "unexpected marked provider\nAGREE"

    marked_completion_effects: list[object] = []
    marked_sink_effects: list[object] = []

    class MarkedRefusalSink:
        def emit(self, event: object) -> None:
            marked_sink_effects.append(event)

    with tempfile.TemporaryDirectory(prefix="harden-marked-refusal-") as td:
        marked_stream_dir = Path(td)
        marked_capture = evidence.AgyCanaryCapture(
            *evidence._validate_private_root(marked_stream_dir)
        )
        try:
            with patch.object(
                invoker,
                "revalidate_review_isolation_authorization",
                wraps=invoker.revalidate_review_isolation_authorization,
            ) as revalidate_spy, patch.object(
                invoker,
                "_default_spawn_via_provider",
                side_effect=marked_provider,
            ):
                marked_forged = invoke_sanctioned_board_control(
                    DEFAULT_BOARD,
                    artifact,
                    spawn=marked_callback,
                    mode="review",
                    base_env={},
                    agy_canary_capture=marked_capture,
                    on_leg_complete=marked_completion_effects.append,
                    sink=MarkedRefusalSink(),
                    stream_dir=marked_stream_dir,
                    factory_authorization=forged_authorization,
                    forbid_pre_authorization_effects=True,
                )
                marked_stale = invoke_sanctioned_board_control(
                    DEFAULT_BOARD,
                    artifact,
                    spawn=marked_callback,
                    mode="review",
                    base_env={},
                    agy_canary_capture=marked_capture,
                    on_leg_complete=marked_completion_effects.append,
                    sink=MarkedRefusalSink(),
                    stream_dir=marked_stream_dir,
                    factory_authorization=stale_authorization,
                    forbid_pre_authorization_effects=True,
                )
        finally:
            marked_capture.close()
        assert not tuple(marked_stream_dir.glob("*.verdict.json"))

    assert revalidate_spy.call_count >= 2
    revalidated_authorizations = [call.args[0] for call in revalidate_spy.call_args_list]
    assert any(auth is forged_authorization for auth in revalidated_authorizations)
    assert any(auth is stale_authorization for auth in revalidated_authorizations)
    assert not marked_effects
    assert not marked_completion_effects
    assert not marked_sink_effects
    assert_exact_unavailable(DEFAULT_BOARD, marked_forged)
    assert_exact_unavailable(DEFAULT_BOARD, marked_stale)


def test_derived_review_explicit_spawn_remains_hermetic_after_marker():
    """A factory-marked, pre-minted review-authorized control stays hermetic.

    This deliberately derives review mode and carries a governed landing tier while
    the explicit helper supplies the factory marker and review authorization.
    """

    harden_require("review-leg-isolation")
    from phase_loop_runtime import panel_invoker as invoker
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    callback_calls: list[str] = []

    def hermetic_spawn(leg: str, artifact: str):
        callback_calls.append(leg)
        return "OK", f"{leg} hermetic control\nAGREE"

    with patch.object(
        invoker,
        "revalidate_review_isolation_authorization",
        wraps=invoker.revalidate_review_isolation_authorization,
    ) as revalidate_spy, patch.object(
        invoker,
        "_default_spawn_via_provider",
        side_effect=AssertionError("a hermetic spawn must not reach provider launch"),
    ) as provider_spy:
        result = invoke_sanctioned_board_control(
            DEFAULT_BOARD,
            "hermetic control",
            spawn=hermetic_spawn,
            base_env={},
            landing_tier=invoker.ReviewLandingTier.PRODUCTION_CODE,
            max_concurrency=1,
        )

    assert revalidate_spy.called
    provider_spy.assert_not_called()
    assert [leg.status for leg in result.legs] == ["OK"] * len(DEFAULT_BOARD.seats)
    assert sorted(callback_calls) == sorted(seat.harness for seat in DEFAULT_BOARD.seats)


def test_derived_review_bounded_capture_control_reaches_stage_without_auth(monkeypatch):
    """A marked capture seals exact staged inputs before its direct-child stop."""

    import phase_loop_runtime.capability_registry as capability_module

    simulation_requested = (
        os.environ.get("HARDEN_TEST_POST_MARKER_SIMULATION") == "1"
    )
    simulate_marker = simulation_requested and getattr(
        capability_module, "HARDEN_CAPABILITY_VERSION", None
    ) is None
    # The adapter exists only for this pre-marker RED tree.  Once production owns
    # the marker the node leaves invoke_board untouched and exercises the real
    # policy/factory/revalidation protocol through the reusable guard.
    if simulate_marker:
        monkeypatch.setattr(
            capability_module, "HARDEN_CAPABILITY_VERSION", 1, raising=False
        )
    harden_require("review-leg-isolation")
    from phase_loop_runtime import agy_canary_evidence as evidence
    from phase_loop_runtime import panel_invoker as invoker
    from phase_loop_runtime.advisor_board import backing
    from phase_loop_runtime.advisor_board import matrix as matrix_module
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD

    marker_invocations: list[tuple[object, object, str, Path, object]] = []
    if simulate_marker:
        def simulated_prepare_review_authorization(*_args: object, **_kwargs: object) -> object:
            return object()

        def simulated_revalidate_review_authorization(
            *_args: object, **_kwargs: object
        ) -> bool:
            return True

        def simulated_marker_invoke(
            review_board: object, review_artifact: object, **invoke_kwargs: object
        ) -> object:
            try:
                supplied_authorization = invoke_kwargs.pop("review_authorization")
                canonical_repo_authority = Path(
                    invoke_kwargs.pop("canonical_repo_authority")
                ).resolve()
            except KeyError as exc:
                raise AssertionError(
                    "post-marker capture simulation took the legacy direct invocation"
                ) from exc
            effective_mode = invoke_kwargs.get("mode") or invoker._mode_for_purpose(
                review_board.purpose
            )
            if effective_mode not in invoker.PANEL_MODES:
                raise ValueError(f"unknown panel mode {effective_mode!r}")
            effective_research = invoker._effective_research_policy(
                review_board.research_policy,
                invoke_kwargs.get("research_policy"),
            )
            repo_dir = invoke_kwargs.get("repo_dir")
            switched = invoker._govlean_authority_switched(repo_dir)
            landing_tier = invoke_kwargs.get("landing_tier")
            review_policy = invoke_kwargs.get("review_policy")
            if landing_tier is None and review_policy is None:
                if switched:
                    raise invoker.PresidentPolicyError(
                        "review_landing_tier_required",
                        "post-switch board invocation requires an explicit landing tier or policy",
                    )
            else:
                policy = review_policy or invoker.review_policy_for_tier(
                    invoker._coerce_review_landing_tier(landing_tier)
                )
                invoker._validate_review_board_policy(
                    review_board,
                    policy,
                    invoke_kwargs.get("review_seat_aliases"),
                )
            resolved_inline = invoker._resolve_artifact(
                review_artifact, invoke_kwargs.get("artifact_ref")
            )
            resolved = invoker._apply_context_refs(
                resolved_inline,
                invoke_kwargs.get("context_refs"),
                soft_warn=bool(invoke_kwargs.get("context_refs_soft_warn", False)),
            )
            prepared_authorization = backing.prepare_review_isolation_authorization(
                review_board,
                resolved,
                mode=effective_mode,
                canonical_repo_authority=canonical_repo_authority,
            )
            if prepared_authorization is not supplied_authorization:
                raise AssertionError(
                    "post-marker capture simulation did not use the dynamically "
                    "prepared authorization"
                )
            if not invoker.revalidate_review_isolation_authorization(
                supplied_authorization,
                review_board,
                resolved,
                mode=effective_mode,
                canonical_repo_authority=canonical_repo_authority,
            ):
                raise AssertionError(
                    "post-marker capture simulation rejected its valid authorization"
                )
            marker_invocations.append(
                (
                    review_board,
                    resolved,
                    effective_mode,
                    canonical_repo_authority,
                    supplied_authorization,
                )
            )

            capture = invoke_kwargs.get("agy_canary_capture")
            if capture is None or invoke_kwargs.get("spawn") is not None:
                raise AssertionError(
                    "post-marker compatibility simulation requires production capture"
                )
            if effective_research.enabled:
                raise AssertionError("capture simulation cannot enable research")
            static_matrix = matrix_module.default_matrix(
                env={}, probe=invoker._LEG_CLI.__contains__
            )
            capture_board = invoker._resolve_and_validate_board(
                review_board, static_matrix
            )
            capture_seats = tuple(capture_board.seats)
            providers = tuple((seat.harness or "").lower() for seat in capture_seats)
            if len(capture_seats) != len(providers) or any(
                provider not in invoker._LEG_CLI for provider in providers
            ):
                raise AssertionError("capture simulation lost a provider identity")

            capture_launches: dict[str, tuple[object, Path, Path, object]] = {}
            scratch_authorities: list[object] = []
            try:
                bundle_bytes = resolved.encode("utf-8")
                instruction_bytes = invoker._resolve_brief(
                    effective_mode, invoke_kwargs.get("brief_ref")
                ).encode("utf-8")
                for index, (seat, provider) in enumerate(
                    zip(capture_seats, providers, strict=True)
                ):
                    scratch, scratch_authority = invoker._create_owned_cleanup_root(
                        kind="scratch"
                    )
                    scratch_authorities.append(scratch_authority)
                    stage = scratch / "review"
                    stage.mkdir(mode=0o700)
                    (stage / "review-bundle.md").write_bytes(bundle_bytes)
                    (stage / "review-instructions.md").write_bytes(
                        instruction_bytes
                    )
                    for name in ("review-bundle.md", "review-instructions.md"):
                        (stage / name).chmod(0o600)
                    if index == 0:
                        invoker.bind_staged_review_inputs(
                            capture=capture,
                            review_dir=stage,
                            bundle_bytes=bundle_bytes,
                            instruction_bytes=instruction_bytes,
                            generator_identity=(
                                "phase_loop_runtime.panel_invoker._resolve_brief.v1"
                            ),
                        )
                    authority = invoker.prepare_provider_launch_authorities(
                        capture=capture,
                        stage=stage,
                        providers=(provider,),
                    )[provider]
                    capture_launches[str(seat.seat_key)] = (
                        authority,
                        stage,
                        scratch,
                        scratch_authority,
                    )
                invoker.seal_provider_launches(
                    capture=capture,
                    launches=tuple(
                        (
                            provider,
                            str(seat.seat_key),
                            capture_launches[str(seat.seat_key)][0],
                        )
                        for seat, provider in zip(
                            capture_seats, providers, strict=True
                        )
                    ),
                )

                live_matrix = invoker.default_matrix(
                    env=invoke_kwargs.get("base_env")
                )
                execution_board = invoker._resolve_and_validate_board(
                    capture_board, live_matrix
                )
                if tuple(
                    ((seat.harness or "").lower(), str(seat.seat_key))
                    for seat in execution_board.seats
                ) != tuple(
                    (provider, str(seat.seat_key))
                    for seat, provider in zip(
                        capture_seats, providers, strict=True
                    )
                ):
                    raise AssertionError(
                        "live matrix changed the sealed provider-seat order"
                    )

                sink = invoke_kwargs.get("sink")
                observer = (
                    invoker.BoardObserver(sink, board_name=execution_board.name)
                    if sink is not None
                    else None
                )
                if observer is not None:
                    observer.board_started()
                results = []
                timeouts = dict(invoke_kwargs.get("timeouts_by_leg") or {})
                for index, (seat, provider) in enumerate(
                    zip(execution_board.seats, providers, strict=True)
                ):
                    authority, stage, scratch, _scratch_authority = (
                        capture_launches[str(seat.seat_key)]
                    )
                    spawned = invoker._default_spawn_via_provider(
                        provider,
                        resolved,
                        repo_dir=repo_dir,
                        mode=effective_mode,
                        model=seat.model,
                        effort=seat.effort,
                        env=invoke_kwargs.get("base_env") or {},
                        brief_ref=invoke_kwargs.get("brief_ref"),
                        timeout_s=timeouts.get(provider),
                        agy_capture=capture,
                        seat_key=seat.seat_key,
                        provider_authority=authority,
                        capture_stage=stage,
                        capture_scratch=scratch,
                    )
                    detail = None
                    if isinstance(spawned, tuple) and len(spawned) == 3:
                        status, text, detail = spawned
                    else:
                        status, text = spawned
                    result = invoker.PanelLegResult(
                        leg=provider,
                        status=status,
                        text=str(text),
                        detail=detail,
                        seat_key=seat.seat_key,
                    )
                    invoker.record_provider_result(
                        capture=capture,
                        provider=provider,
                        seat_key=str(seat.seat_key),
                        authority=authority,
                        status=result.status,
                        text=result.text,
                        detail=result.detail,
                    )
                    stream_dir = invoke_kwargs.get("stream_dir")
                    if stream_dir is not None:
                        invoker._write_incremental_verdict(
                            Path(stream_dir), index, result
                        )
                    on_leg_complete = invoke_kwargs.get("on_leg_complete")
                    if on_leg_complete is not None:
                        on_leg_complete(result)
                    results.append(result)
                if observer is not None:
                    for seat, result in zip(
                        execution_board.seats, results, strict=True
                    ):
                        observer.seat_started(seat)
                        observer.seat_result(seat, result)
                    observer.board_completed(results)
                panel_result = invoker.PanelResult(legs=tuple(results))
                object.__setattr__(
                    panel_result, "_agy_canary_capture", invoker.capture_summary(capture)
                )
                return panel_result
            finally:
                invoker._cleanup_capture_launches(
                    capture_launches, scratch_authorities
                )

        monkeypatch.setattr(
            backing,
            "prepare_review_isolation_authorization",
            simulated_prepare_review_authorization,
            raising=False,
        )
        monkeypatch.setattr(
            invoker,
            "revalidate_review_isolation_authorization",
            simulated_revalidate_review_authorization,
            raising=False,
        )
        monkeypatch.setattr(invoker, "bind_staged_review_inputs", lambda **_kwargs: None)
        monkeypatch.setattr(
            invoker,
            "prepare_provider_launch_authorities",
            lambda *, providers, **_kwargs: {provider: object() for provider in providers},
        )
        monkeypatch.setattr(invoker, "seal_provider_launches", lambda **_kwargs: None)
        monkeypatch.setattr(invoker, "record_provider_result", lambda **_kwargs: None)
        monkeypatch.setattr(invoker, "capture_summary", lambda _capture: {"simulated": True})
        monkeypatch.setattr(
            invoker,
            "_cleanup_capture_launches",
            lambda _launches, scratch_roots: evidence._cleanup_owned_roots(scratch_roots),
        )
        monkeypatch.setattr(invoker, "invoke_board", simulated_marker_invoke)

    staged: list[Path] = []
    expected_launch_identities = tuple(
        ((seat.harness or "").lower(), str(seat.seat_key))
        for seat in DEFAULT_BOARD.seats
    )
    prepared_chains: list[tuple[str, str, Path, Path, object]] = []
    sealed_launches: list[tuple[tuple[str, str, Path, Path, object], ...]] = []
    direct_child_artifacts: list[str] = []
    direct_child_chains: list[tuple[str, str, Path, Path, object]] = []
    direct_child_repositories: list[Path] = []
    observed_switch_repositories: list[Path] = []
    allocated_roots: list[Path] = []
    completion_results: list[object] = []
    sink_events: list[object] = []
    live_matrix_calls: list[object] = []
    incremental_verdict_calls: list[object] = []
    protocol_steps: list[str] = []
    with tempfile.TemporaryDirectory(prefix="harden-capture-input-", dir="/tmp") as input_td, \
            tempfile.TemporaryDirectory(prefix="harden-capture-", dir="/tmp") as td:
        input_root = Path(input_td)
        root = Path(td)
        artifact_ref = input_root / "board-artifact.md"
        context_ref = input_root / "board-context.txt"
        caller_repo = input_root / "switched-repo"
        switch_manifest = caller_repo / "plans" / "manifest.json"
        switch_manifest_bytes = (
            b'{"schema_version":1,"plans":[{"slug":"v10-GOVLEAN","lifecycle":'
            b'[{"transition":"authority_switch"}]}]}\n'
        )
        artifact_ref.write_text("FROM_BOARD_REF", encoding="utf-8")
        context_ref.write_text("context stays by reference", encoding="utf-8")
        switch_manifest.parent.mkdir(parents=True)
        switch_manifest.write_bytes(switch_manifest_bytes)
        expected_artifact = invoker._apply_context_refs(
            invoker._resolve_artifact("INLINE", str(artifact_ref)),
            (str(context_ref),),
            soft_warn=False,
        )
        expected_bundle_bytes = expected_artifact.encode("utf-8")
        stream_dir = root / "stream"
        capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
        try:
            original_bind_staged_review_inputs = invoker.bind_staged_review_inputs
            original_prepare_provider_launch_authorities = (
                invoker.prepare_provider_launch_authorities
            )
            original_seal_provider_launches = invoker.seal_provider_launches
            original_create_owned_cleanup_root = invoker._create_owned_cleanup_root
            original_default_matrix = invoker.default_matrix
            original_write_incremental_verdict = invoker._write_incremental_verdict
            original_govlean_authority_switched = invoker._govlean_authority_switched

            def bind_stage(*, capture: object, review_dir: Path, bundle_bytes: bytes,
                           instruction_bytes: bytes, **_kwargs: object) -> None:
                assert capture is bounded_capture
                assert review_dir.is_dir()
                assert review_dir.parent in allocated_roots
                assert bundle_bytes == expected_bundle_bytes
                assert (review_dir / "review-bundle.md").read_bytes() == bundle_bytes
                assert (
                    review_dir / "review-instructions.md"
                ).read_bytes() == instruction_bytes
                staged.append(review_dir)
                original_bind_staged_review_inputs(
                    capture=capture,
                    review_dir=review_dir,
                    bundle_bytes=bundle_bytes,
                    instruction_bytes=instruction_bytes,
                    generator_identity="phase_loop_runtime.panel_invoker._resolve_brief.v1",
                )

            def prepare_provider_authority(
                *, capture: object, stage: Path, providers: tuple[str, ...]
            ) -> object:
                assert capture is bounded_capture
                assert staged
                index = len(prepared_chains)
                expected_provider, expected_seat_key = expected_launch_identities[index]
                assert len(providers) == 1
                assert providers == (expected_provider,)
                assert stage == allocated_roots[index] / "review"
                assert (stage / "review-bundle.md").read_bytes() == expected_bundle_bytes
                authorities = original_prepare_provider_launch_authorities(
                    capture=capture, stage=stage, providers=providers
                )
                authority = authorities[expected_provider]
                prepared_chains.append(
                    (
                        expected_provider,
                        expected_seat_key,
                        allocated_roots[index],
                        stage,
                        authority,
                    )
                )
                return authorities

            def seal_provider_launches(
                *, capture: object, launches: tuple[tuple[str, str, object], ...]
            ) -> object:
                assert capture is bounded_capture
                assert len(staged) == 1
                assert len(prepared_chains) == len(expected_launch_identities)
                assert tuple(
                    (provider, seat_key)
                    for provider, seat_key, _root, _stage, _authority in prepared_chains
                ) == expected_launch_identities
                assert [(root, stage) for _provider, _seat_key, root, stage, _authority in prepared_chains] == [
                    (allocated_root, allocated_root / "review")
                    for allocated_root in allocated_roots
                ]
                assert len(launches) == len(expected_launch_identities)
                sealed_chain: list[tuple[str, str, Path, Path, object]] = []
                for launch, expected in zip(
                    launches, prepared_chains, strict=True
                ):
                    provider, seat_key, authority = launch
                    (
                        expected_provider,
                        expected_seat_key,
                        expected_root,
                        expected_stage,
                        expected_authority,
                    ) = expected
                    assert (provider, seat_key) == (
                        expected_provider,
                        expected_seat_key,
                    )
                    assert authority is expected_authority
                    sealed_chain.append(
                        (
                            provider,
                            seat_key,
                            expected_root,
                            expected_stage,
                            authority,
                        )
                    )
                result = original_seal_provider_launches(
                    capture=capture, launches=launches
                )
                sealed_launches.append(tuple(sealed_chain))
                return result

            def allocate_owned_cleanup_root(
                *args: object, **cleanup_kwargs: object
            ) -> object:
                result = original_create_owned_cleanup_root(*args, **cleanup_kwargs)
                allocated_roots.append(result[0])
                return result

            def stop_at_direct_child(leg: str, artifact: str, **child_kwargs: object) -> object:
                assert sealed_launches
                assert artifact == expected_artifact
                child_repo = Path(child_kwargs["repo_dir"]).resolve()
                assert child_repo != caller_repo.resolve()
                assert child_repo.stat().st_mode & 0o777 == 0o700
                assert (
                    child_repo / "plans" / "manifest.json"
                ).read_bytes() == switch_manifest_bytes
                seat_key = child_kwargs.get("seat_key")
                stage = child_kwargs.get("capture_stage")
                scratch = child_kwargs.get("capture_scratch")
                authority = child_kwargs.get("provider_authority")
                assert isinstance(seat_key, str)
                assert isinstance(stage, Path)
                assert isinstance(scratch, Path)
                matching = [
                    chain
                    for chain in sealed_launches[0]
                    if chain[0] == leg
                    and chain[1] == seat_key
                    and chain[2] == scratch
                    and chain[3] == stage
                    and chain[4] is authority
                ]
                assert len(matching) == 1
                direct_child_artifacts.append(artifact)
                direct_child_chains.append((leg, seat_key, scratch, stage, authority))
                direct_child_repositories.append(child_repo)
                return "DEGRADED", "deliberately stopped at direct child"

            def require_real_authority_switch(repo_dir: Path | str | None) -> bool:
                assert repo_dir is not None
                observed_repo = Path(repo_dir).resolve()
                assert observed_repo != caller_repo.resolve()
                assert (
                    observed_repo / "plans" / "manifest.json"
                ).read_bytes() == switch_manifest_bytes
                switched = original_govlean_authority_switched(observed_repo)
                assert switched is True
                observed_switch_repositories.append(observed_repo)
                return switched

            def mutate_artifact_after_factory() -> None:
                artifact_ref.write_text("MUTATED_AFTER_AUTHORIZATION", encoding="utf-8")

            def complete_leg(result: object) -> None:
                assert sealed_launches
                completion_results.append(result)

            class CaptureSink:
                def emit(self, event: object) -> None:
                    assert sealed_launches
                    sink_events.append(event)

            def live_matrix(*args: object, **matrix_kwargs: object) -> object:
                assert sealed_launches
                live_matrix_calls.append((args, matrix_kwargs))
                return original_default_matrix(*args, **matrix_kwargs)

            def write_incremental_verdict(
                *args: object, **verdict_kwargs: object
            ) -> object:
                assert sealed_launches
                incremental_verdict_calls.append((args, verdict_kwargs))
                return original_write_incremental_verdict(*args, **verdict_kwargs)

            bounded_capture = capture
            assert root.parent == Path("/tmp")
            assert root.stat().st_mode & 0o777 == 0o700
            with patch.object(
                invoker,
                "revalidate_review_isolation_authorization",
                wraps=invoker.revalidate_review_isolation_authorization,
            ) as revalidate_spy, patch.object(
                invoker,
                "bind_staged_review_inputs",
                side_effect=bind_stage,
            ), patch.object(
                invoker,
                "prepare_provider_launch_authorities",
                side_effect=prepare_provider_authority,
            ), patch.object(
                invoker,
                "seal_provider_launches",
                side_effect=seal_provider_launches,
            ), patch.object(
                invoker,
                "_create_owned_cleanup_root",
                side_effect=allocate_owned_cleanup_root,
            ), patch.object(
                invoker,
                "_govlean_authority_switched",
                side_effect=require_real_authority_switch,
            ), patch.object(
                invoker,
                "default_matrix",
                side_effect=live_matrix,
            ), patch.object(
                invoker,
                "_write_incremental_verdict",
                side_effect=write_incremental_verdict,
            ), patch.object(
                invoker,
                "_leg_auth_ok",
                side_effect=AssertionError("capture must not reach auth probing"),
            ), patch.object(
                invoker,
                "_default_spawn",
                side_effect=stop_at_direct_child,
            ):
                result = invoke_sanctioned_board_control(
                    DEFAULT_BOARD,
                    "INLINE",
                    artifact_ref=str(artifact_ref),
                    context_refs=(str(context_ref),),
                    repo_dir=caller_repo,
                    agy_canary_capture=bounded_capture,
                    base_env={},
                    landing_tier=invoker.ReviewLandingTier.PRODUCTION_CODE,
                    max_concurrency=1,
                    on_leg_complete=complete_leg,
                    sink=CaptureSink(),
                    stream_dir=stream_dir,
                    require_live_matrix_probe=True,
                    mutate_artifact_after_factory=mutate_artifact_after_factory,
                    observe_protocol_step=protocol_steps.append,
                )

            assert revalidate_spy.called
            if simulate_marker:
                assert revalidate_spy.call_count == 1
                assert len(marker_invocations) == 1
                assert marker_invocations[0][0] is DEFAULT_BOARD
                assert marker_invocations[0][1] == expected_artifact
                assert marker_invocations[0][2] == "review"
            assert len(staged) == 1
            assert len(allocated_roots) == len(DEFAULT_BOARD.seats)
            assert len(sealed_launches) == 1
            assert tuple(
                (provider, seat_key)
                for provider, seat_key, _root, _stage, _authority in prepared_chains
            ) == expected_launch_identities
            assert tuple(
                (provider, seat_key)
                for provider, seat_key, _root, _stage, _authority in sealed_launches[0]
            ) == expected_launch_identities
            assert [(root, stage) for _provider, _seat_key, root, stage, _authority in prepared_chains] == [
                (allocated_root, allocated_root / "review")
                for allocated_root in allocated_roots
            ]
            assert len(direct_child_chains) == len(expected_launch_identities)
            assert tuple(
                (provider, seat_key)
                for provider, seat_key, _root, _stage, _authority in direct_child_chains
            ) == expected_launch_identities
            assert [(root, stage) for _provider, _seat_key, root, stage, _authority in direct_child_chains] == [
                (allocated_root, allocated_root / "review")
                for allocated_root in allocated_roots
            ]
            for direct, sealed in zip(direct_child_chains, sealed_launches[0], strict=True):
                direct_provider, direct_seat_key, direct_root, direct_stage, direct_authority = direct
                sealed_provider, sealed_seat_key, sealed_root, sealed_stage, sealed_authority = sealed
                assert (direct_provider, direct_seat_key, direct_root, direct_stage) == (
                    sealed_provider,
                    sealed_seat_key,
                    sealed_root,
                    sealed_stage,
                )
                assert direct_authority is sealed_authority
            assert direct_child_artifacts == [expected_artifact] * len(DEFAULT_BOARD.seats)
            assert len(observed_switch_repositories) == 1
            assert direct_child_repositories == observed_switch_repositories * len(
                DEFAULT_BOARD.seats
            )
            assert switch_manifest.read_bytes() == switch_manifest_bytes
            assert not observed_switch_repositories[0].exists()
            assert len(completion_results) == len(DEFAULT_BOARD.seats)
            assert sink_events
            assert live_matrix_calls
            expected_preparation = [
                "policy:switch",
                "policy:validate",
                "factory",
                "revalidation",
            ]
            for index, (provider, _seat_key) in enumerate(
                expected_launch_identities
            ):
                expected_preparation.append("allocation")
                if index == 0:
                    expected_preparation.append("stage")
                expected_preparation.append(f"authority:{provider}")
            expected_preparation.append("seal")
            assert protocol_steps[: len(expected_preparation)] == expected_preparation
            seal_index = protocol_steps.index("seal")
            matrix_start = protocol_steps.index("matrix:start")
            matrix_complete = protocol_steps.index("matrix:complete")
            availability_indices = [
                index
                for index, step in enumerate(protocol_steps)
                if step == "availability"
            ]
            assert availability_indices
            assert seal_index < matrix_start
            first_provider = next(
                index
                for index, step in enumerate(protocol_steps)
                if step.startswith("provider:")
            )
            assert all(
                matrix_complete < index < first_provider
                for index in availability_indices
            )
            assert [
                step for step in protocol_steps if step.startswith("provider:")
            ] == [
                f"provider:{provider}"
                for provider, _seat_key in expected_launch_identities
            ]
            assert [
                step for step in protocol_steps if step.startswith("child:")
            ] == [
                f"child:{provider}"
                for provider, _seat_key in expected_launch_identities
            ]
            for index, step in enumerate(protocol_steps):
                if step.startswith(("provider:", "child:")) or step in {
                    "writer",
                    "completion",
                    "sink",
                }:
                    assert index > matrix_complete
            assert len(incremental_verdict_calls) == len(DEFAULT_BOARD.seats)
            assert len(tuple(stream_dir.glob("*.verdict.json"))) == len(DEFAULT_BOARD.seats)
            assert [leg.status for leg in result.legs] == ["DEGRADED"] * len(
                DEFAULT_BOARD.seats
            )
            assert allocated_roots
            assert all(not path.exists() for path in allocated_roots)
        finally:
            capture.close()


class AvailabilitySimulationTests(unittest.TestCase):
    def _assert_full_and_clean(self, board, *, expect_vendors):
        # (a) exactly the target seat count …
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        # (b) … which is never below the floor (target ≥ floor, and we hit target).
        self.assertGreaterEqual(len(board.seats), FLOOR_SEATS)
        # (c) NO duplicate (vendor, model, lens) seat.
        keys = _keys(board)
        self.assertEqual(len(keys), len(set(keys)), f"duplicate seat: {keys}")
        # every seat runs on an AVAILABLE vendor (never a down one).
        self.assertTrue(all(s.harness in expect_vendors for s in board.seats))
        # every lens on a given vendor is distinct (lens diversity on backfill).
        by_vendor: dict[str, list[str]] = {}
        for s in board.seats:
            by_vendor.setdefault(s.harness, []).append(s.lens)
        for vendor, lenses in by_vendor.items():
            self.assertEqual(len(lenses), len(set(lenses)), f"{vendor} repeats a lens: {lenses}")
            for lens in lenses:
                self.assertIn(lens, LENS_CYCLE)

    def test_four_vendors_up_one_pure_seat_each(self) -> None:
        board = compose_review_board(is_available=_probe(ALL_VENDORS))
        self._assert_full_and_clean(board, expect_vendors=set(ALL_VENDORS))
        # all four vendors seated, exactly once, distinct lenses.
        self.assertEqual({s.harness for s in board.seats}, set(ALL_VENDORS))
        self.assertEqual(len({s.lens for s in board.seats}), 4)

    def test_three_vendors_up_three_pure_plus_one_backfill(self) -> None:
        up = ("claude", "codex", "gemini")  # grok down
        board = compose_review_board(is_available=_probe(up))
        self._assert_full_and_clean(board, expect_vendors=set(up))
        self.assertNotIn("grok", {s.harness for s in board.seats})
        # one vendor carries 2 seats (the backfill), the rest carry 1 — total 4.
        counts = {v: sum(1 for s in board.seats if s.harness == v) for v in up}
        self.assertEqual(sorted(counts.values()), [1, 1, 2])

    def test_two_vendors_up_two_pure_plus_two_backfill(self) -> None:
        up = ("grok", "codex")  # claude + gemini down
        board = compose_review_board(is_available=_probe(up))
        self._assert_full_and_clean(board, expect_vendors=set(up))
        counts = {v: sum(1 for s in board.seats if s.harness == v) for v in up}
        self.assertEqual(sorted(counts.values()), [2, 2])  # backfilled evenly

    def test_one_vendor_up_yields_four_distinct_lens_seats(self) -> None:
        board = compose_review_board(is_available=_probe(("grok",)))
        self._assert_full_and_clean(board, expect_vendors={"grok"})
        # ALL four seats on the single available vendor, each a DIFFERENT lens.
        self.assertEqual({s.harness for s in board.seats}, {"grok"})
        self.assertEqual(len({s.lens for s in board.seats}), 4)
        self.assertEqual({s.model for s in board.seats}, {"grok-4.6"})

    def test_never_below_floor_for_any_nonempty_availability(self) -> None:
        # Exhaustively: every non-empty subset of vendors reaches the target and is
        # never below the floor — the panel can't be "choked" to 1–2 reviewers.
        from itertools import combinations

        for r in range(1, len(ALL_VENDORS) + 1):
            for up in combinations(ALL_VENDORS, r):
                board = compose_review_board(is_available=_probe(up))
                self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS, up)
                self.assertGreaterEqual(len(board.seats), FLOOR_SEATS, up)
                keys = _keys(board)
                self.assertEqual(len(keys), len(set(keys)), up)

    def test_zero_vendors_up_is_an_empty_board(self) -> None:
        # No vendor available ⇒ nothing to seat (the run degrades wholesale). The
        # floor is a count of reviewers to seat on AVAILABLE vendors; with none up
        # there is no reviewer to seat.
        board = compose_review_board(is_available=_probe(()))
        self.assertEqual(len(board.seats), 0)

    def test_composed_board_is_deterministic(self) -> None:
        a = compose_review_board(is_available=_probe(("grok", "codex")))
        b = compose_review_board(is_available=_probe(("grok", "codex")))
        self.assertEqual(_keys(a), _keys(b))

    def test_every_composed_board_passes_matrix_validation(self) -> None:
        # A composed board is only useful if its seats are all VALID (grok-4.6 on the
        # grok lane, gpt on codex, …) — validate each availability scenario.
        from itertools import combinations

        matrix = default_matrix()
        for r in range(1, len(ALL_VENDORS) + 1):
            for up in combinations(ALL_VENDORS, r):
                validate_board(compose_review_board(is_available=_probe(up)), matrix)

    def test_default_probe_is_the_registry_path_probe(self) -> None:
        # With no injected probe the composer uses the advisor-board's canonical PATH
        # probe (DEFAULT_HARNESS_REGISTRY.is_available), so composition is
        # registration-driven. We can't assert which vendors are on PATH here, but
        # the board must still be well-formed (≤ target, no dup, all seats valid).
        # Pin auth to pass-through so this exercises the PATH probe ONLY and never
        # shells out to the real, subprocess-backed auth gate (the auth dimension is
        # proven in AuthAwareCompositionTests).
        board = compose_review_board(auth_ok=lambda _v: True)
        self.assertLessEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        keys = _keys(board)
        self.assertEqual(len(keys), len(set(keys)))
        if board.seats:
            validate_board(board, default_matrix())

    def test_target_below_floor_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compose_review_board(is_available=_probe(ALL_VENDORS), target=2, floor=3)


class AuthAwareCompositionTests(unittest.TestCase):
    """REVIEWGOV-W1 / #151 — composition gates on ``is_available ∧ auth_ok``, so a
    PATH-present-but-UNAUTHENTICATED vendor is treated as down (dropped +
    backfilled), exactly like a PATH-absent one. This closes the hole where the
    board composed on PATH alone and seated a vendor whose leg would then
    fail-closed to DEGRADED."""

    def test_unauthed_grok_is_not_seated_and_is_backfilled(self) -> None:
        # grok's CLI is on PATH (available) but it is NOT authenticated. It must be
        # dropped and its seat backfilled onto an authed vendor — never seated to
        # then fail-closed.
        board = compose_review_board(
            is_available=_probe(ALL_VENDORS),          # all four CLIs present
            auth_ok=_probe(("claude", "codex", "gemini")),  # grok unauthed
        )
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)     # still a full board
        self.assertNotIn("grok", {s.harness for s in board.seats})   # unauthed vendor dropped
        self.assertTrue(all(s.harness in {"claude", "codex", "gemini"} for s in board.seats))
        keys = _keys(board)
        self.assertEqual(len(keys), len(set(keys)))                  # no duplicate seat
        # exactly one authed vendor carries the backfilled 4th seat.
        counts = {v: sum(1 for s in board.seats if s.harness == v) for v in ("claude", "codex", "gemini")}
        self.assertEqual(sorted(counts.values()), [1, 1, 2])

    def test_all_authed_is_identical_to_availability_only(self) -> None:
        # With every available vendor authed, the auth gate is a no-op: the board is
        # byte-identical to the availability-only 4-vendor board.
        avail_only = compose_review_board(is_available=_probe(ALL_VENDORS))
        authed = compose_review_board(
            is_available=_probe(ALL_VENDORS), auth_ok=_probe(ALL_VENDORS)
        )
        self.assertEqual(_keys(avail_only), _keys(authed))

    def test_unavailable_and_unauthed_both_drop(self) -> None:
        # grok is DOWN (not on PATH) and codex is UP-but-UNAUTHED — both are treated
        # as down; the board backfills onto the two remaining authed-and-up vendors.
        board = compose_review_board(
            is_available=_probe(("claude", "codex", "gemini")),  # grok absent
            auth_ok=_probe(("claude", "gemini")),                # codex unauthed
        )
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        self.assertEqual({s.harness for s in board.seats}, {"claude", "gemini"})

    def test_injected_availability_alone_defaults_auth_passthrough(self) -> None:
        # Documented test affordance: injecting availability WITHOUT auth_ok defaults
        # auth to pass-through (so a simulation caller never shells out). All four
        # available vendors are seated even though no real auth ran.
        board = compose_review_board(is_available=_probe(ALL_VENDORS))
        self.assertEqual({s.harness for s in board.seats}, set(ALL_VENDORS))

    def test_no_vendor_authed_is_an_empty_board(self) -> None:
        board = compose_review_board(
            is_available=_probe(ALL_VENDORS), auth_ok=_probe(())
        )
        self.assertEqual(len(board.seats), 0)

    def test_production_default_gates_on_both_availability_and_auth(self) -> None:
        # The bare production call (no injected probes) must gate on
        # is_available ∧ auth_ok. Patch BOTH seams — grok on PATH but unauthed — so
        # it is dropped + backfilled, with NO real subprocess auth probe.
        with patch.object(_composition.DEFAULT_HARNESS_REGISTRY, "is_available", lambda _v: True), \
                patch.object(_composition, "default_board_auth_ok", lambda v: v != "grok"):
            board = compose_review_board()
        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        self.assertNotIn("grok", {s.harness for s in board.seats})

    def test_harden_preflight_authorizes_before_every_capability_auth_ok(self) -> None:
        """The default composer uses one real, validated preflight before probes."""
        harden_require("review-leg-isolation")
        real_preflight = _composition.prepare_review_composition_authorization
        real_revalidate = _composition.revalidate_review_composition_authorization
        effects: list[tuple[str, str] | tuple[str]] = []
        prepared: list[object] = []
        validated: list[object] = []

        def preflight(*args, **kwargs):
            self.assertFalse(effects, "preflight itself must precede every probe")
            authorization = real_preflight(*args, **kwargs)
            self.assertIsNotNone(authorization)
            prepared.append(authorization)
            effects.append(("preflight",))
            return authorization

        def revalidate(authorization, *args, **kwargs):
            self.assertEqual(prepared, [authorization])
            self.assertFalse(
                any(kind in {"availability", "auth_session_provider"} for kind, *_ in effects)
            )
            result = real_revalidate(authorization, *args, **kwargs)
            validated.append(authorization)
            effects.append(("validated",))
            return result

        def available(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("availability", vendor))
            return True

        def authenticated(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("auth_session_provider", vendor))
            return True

        with patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=preflight,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=revalidate,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY, "is_available", available
        ), patch.object(_composition, "default_board_auth_ok", authenticated):
            board = compose_review_board()

        self.assertEqual(len(board.seats), DEFAULT_TARGET_SEATS)
        self.assertEqual(len(prepared), 1)
        self.assertTrue(validated)
        self.assertTrue(all(value is prepared[0] for value in validated))
        self.assertLess(
            next(i for i, effect in enumerate(effects) if effect[0] == "validated"),
            next(i for i, effect in enumerate(effects) if effect[0] == "availability"),
        )
        self.assertEqual(
            {entry[1] for entry in effects if entry[0] == "availability"},
            set(ALL_VENDORS),
        )
        self.assertEqual(
            {entry[1] for entry in effects if entry[0] == "auth_session_provider"},
            set(ALL_VENDORS),
        )

    def test_harden_preflight_denial_blocks_compose_before_every_probe(self) -> None:
        """A failed or forged composer preflight cannot reach a probe seam."""
        harden_require("review-leg-isolation")
        effects: list[tuple[str, str] | tuple[str]] = []

        def forbidden(kind: str):
            def probe(vendor: str) -> bool:
                effects.append((kind, vendor))
                self.fail(f"{kind} effect reached after failed HARDEN preflight")

            return probe

        def denied(*_args, **_kwargs):
            effects.append(("preflight_denied",))
            raise ValueError("denied HARDEN composition preflight")

        with patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=denied,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=AssertionError("a denied preflight must not be revalidated"),
        ) as validate_spy, patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            _composition,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaisesRegex(ValueError, "denied HARDEN composition preflight"):
                compose_review_board()

        validate_spy.assert_not_called()
        self.assertEqual(effects, [("preflight_denied",)])

        effects.clear()

        def forged(*_args, **_kwargs):
            effects.append(("preflight_forged",))
            return object()

        with patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=forged,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            _composition,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaises(ValueError):
                compose_review_board()

        self.assertEqual(effects, [("preflight_forged",)])

    def test_harden_preflight_covers_default_load_boards_probes(self) -> None:
        """``load_boards`` uses the same real, validated preflight boundary."""
        harden_require("review-leg-isolation")
        from phase_loop_runtime.advisor_board import config as config_mod

        real_preflight = _composition.prepare_review_composition_authorization
        real_revalidate = _composition.revalidate_review_composition_authorization
        effects: list[tuple[str, str] | tuple[str]] = []
        prepared: list[object] = []
        validated: list[object] = []

        def preflight(*args, **kwargs):
            self.assertFalse(effects, "preflight itself must precede every probe")
            authorization = real_preflight(*args, **kwargs)
            self.assertIsNotNone(authorization)
            prepared.append(authorization)
            effects.append(("preflight",))
            return authorization

        def revalidate(authorization, *args, **kwargs):
            self.assertEqual(prepared, [authorization])
            self.assertFalse(
                any(kind in {"availability", "auth_session_provider"} for kind, *_ in effects)
            )
            result = real_revalidate(authorization, *args, **kwargs)
            validated.append(authorization)
            effects.append(("validated",))
            return result

        def available(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("availability", vendor))
            return True

        def authenticated(vendor: str) -> bool:
            self.assertTrue(validated and validated[-1] is prepared[0])
            effects.append(("auth_session_provider", vendor))
            return True

        with tempfile.TemporaryDirectory() as td, patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=preflight,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=revalidate,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY, "is_available", available
        ), patch.object(config_mod, "default_board_auth_ok", authenticated):
            loaded = config_mod.load_boards(
                path=Path(td) / "missing.toml", validate=False
            )

        self.assertIn("code-review", loaded.boards)
        self.assertEqual(len(prepared), 1)
        self.assertTrue(validated)
        self.assertTrue(all(value is prepared[0] for value in validated))
        self.assertLess(
            next(i for i, effect in enumerate(effects) if effect[0] == "validated"),
            next(i for i, effect in enumerate(effects) if effect[0] == "availability"),
        )
        self.assertTrue(any(kind == "availability" for kind, *_ in effects))
        self.assertTrue(any(kind == "auth_session_provider" for kind, *_ in effects))

    def test_harden_preflight_denial_blocks_load_boards_before_every_probe(self) -> None:
        """``load_boards`` fails closed before capability/auth/session effects."""
        harden_require("review-leg-isolation")
        from phase_loop_runtime.advisor_board import config as config_mod

        effects: list[tuple[str, str] | tuple[str]] = []

        def forbidden(kind: str):
            def probe(vendor: str) -> bool:
                effects.append((kind, vendor))
                self.fail(f"{kind} effect reached after failed HARDEN preflight")

            return probe

        def denied(*_args, **_kwargs):
            effects.append(("preflight_denied",))
            raise ValueError("denied HARDEN load_boards preflight")

        with tempfile.TemporaryDirectory() as td, patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=denied,
        ), patch.object(
            _composition,
            "revalidate_review_composition_authorization",
            side_effect=AssertionError("a denied preflight must not be revalidated"),
        ) as validate_spy, patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            config_mod,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaisesRegex(ValueError, "denied HARDEN load_boards preflight"):
                config_mod.load_boards(path=Path(td) / "missing.toml", validate=False)

        validate_spy.assert_not_called()
        self.assertEqual(effects, [("preflight_denied",)])

        effects.clear()

        def forged(*_args, **_kwargs):
            effects.append(("preflight_forged",))
            return object()

        with tempfile.TemporaryDirectory() as td, patch.object(
            _composition,
            "prepare_review_composition_authorization",
            side_effect=forged,
        ), patch.object(
            _composition.DEFAULT_HARNESS_REGISTRY,
            "is_available",
            forbidden("availability"),
        ), patch.object(
            config_mod,
            "default_board_auth_ok",
            forbidden("auth_session_provider"),
        ):
            with self.assertRaises(ValueError):
                config_mod.load_boards(path=Path(td) / "missing.toml", validate=False)

        self.assertEqual(effects, [("preflight_forged",)])

    def test_default_board_auth_ok_fails_closed_on_unknown_vendor(self) -> None:
        # An unregistered vendor (or any lookup/probe error) fails CLOSED — treated
        # as unauthed, never an optimistic pass.
        self.assertFalse(default_board_auth_ok("no-such-vendor"))


class BoardIndependenceReportingTests(unittest.TestCase):
    """The composed board must REPORT cross-vendor independence (independent vs
    degraded) so a governed gate (gp's degraded_independence) can fire on a
    backfilled panel instead of trusting it as cross-vendor — the unanimous
    4-vendor CR finding on #134."""

    def test_four_distinct_vendors_is_independent(self) -> None:
        ind = board_independence(compose_review_board(is_available=_probe(ALL_VENDORS)))
        self.assertEqual(ind.level, "independent")
        self.assertEqual(ind.distinct_vendors, 4)
        self.assertEqual(ind.seats, DEFAULT_TARGET_SEATS)

    def test_backfilled_boards_report_degraded(self) -> None:
        for up in (("grok", "claude"), ("grok",)):
            ind = board_independence(compose_review_board(is_available=_probe(up)))
            self.assertEqual(ind.seats, DEFAULT_TARGET_SEATS)   # never choked below target
            self.assertEqual(ind.level, "degraded")             # but honestly degraded
            self.assertEqual(ind.distinct_vendors, len(up))

    def test_no_vendors_is_none(self) -> None:
        ind = board_independence(compose_review_board(is_available=_probe(())))
        self.assertEqual(ind.level, "none")
        self.assertEqual(ind.seats, 0)


if __name__ == "__main__":
    unittest.main()
