"""REVIEWTRUTH early slice (native claude seat fill) — tests-only activation guard.

PR-1 of the ratified plan ``plans/detailed-native-claude-seat-fill-396-20260920-1030.md``
(Consiliency/agent-harness#918), delivering EC-REVIEWTRUTH-14 as an early slice. Modelled on
``_fabpub_tdd_guard.py`` (the phase plan's forced-then-marker-inert shape):

* exact activation: ``PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1`` (the phase's own flag, already set
  by the REVIEWTRUTH phase plan's ``suite_command``);
* production marker, installed by the slice's PR-2 in its landing:
  ``phase_loop_runtime.reviewtruth_native_fill_capability.REVIEWTRUTH_NATIVE_FILL_CAPABILITY_VERSION
  == "reviewtruth.native-fill.v1"`` — deliberately NOT the phase-wide
  ``reviewtruth_capability`` marker, which the phase plan reserves for "after all SL-2 through
  SL-5 production paths are complete";
* one skip reason while inactive; guard-control tests never skip; every activated falsifier
  fails with an ``AssertionError`` carrying its unique RED anchor, never an ``ImportError``.
"""
from __future__ import annotations

import importlib
import os
from typing import Any

ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH"
MARKER_MODULE = "phase_loop_runtime.reviewtruth_native_fill_capability"
MARKER_ATTRIBUTE = "REVIEWTRUTH_NATIVE_FILL_CAPABILITY_VERSION"
MARKER_VERSION = "reviewtruth.native-fill.v1"
SKIP_REASON = (
    "REVIEWTRUTH native-fill capability is absent (PR-1 tests-only boundary): set "
    "PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH=1 to run this falsifier against production"
)
ANCHOR_PREFIX = "REVIEWTRUTH_NATIVE_FILL_RED::"


def marker_version() -> Any:
    try:
        module = importlib.import_module(MARKER_MODULE)
    except Exception:
        return None
    return getattr(module, MARKER_ATTRIBUTE, None)


def explicitly_activated() -> bool:
    return os.environ.get(ACTIVATION_ENV) == "1"


def active() -> bool:
    return explicitly_activated() or marker_version() == MARKER_VERSION


def symbol(module_name: str, attribute: str) -> Any:
    """``module.attribute`` (dotted attributes walk into classes) or ``None`` when absent."""
    try:
        current: Any = importlib.import_module(module_name)
    except Exception:
        return None
    for part in attribute.split("."):
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


#: One unique RED anchor per activated falsifier (nodeid basename → anchor).
RED_ANCHORS: dict[str, str] = {
    "test_claude_seat_request_is_built_under_claude_code_for_every_claude_model": ANCHOR_PREFIX + "claude_seat_request_is_built_under_claude_code_for_every_claude_model",
    "test_under_claude_code_is_a_typed_unavailable_detail": ANCHOR_PREFIX + "under_claude_code_is_a_typed_unavailable_detail",
    "test_early_deferral_path_attaches_a_request_for_the_fable_seat": ANCHOR_PREFIX + "early_deferral_path_attaches_a_request_for_the_fable_seat",
    "test_matrix_path_attaches_a_request_for_the_fable_seat": ANCHOR_PREFIX + "matrix_path_attaches_a_request_for_the_fable_seat",
    "test_native_leg_fill_is_a_frozen_record_with_the_binding_fields": ANCHOR_PREFIX + "native_leg_fill_is_a_frozen_record_with_the_binding_fields",
    "test_loader_takes_digests_from_the_emitted_request_only": ANCHOR_PREFIX + "loader_takes_digests_from_the_emitted_request_only",
    "test_preflight_refuses_each_ineligible_fill_with_a_typed_reason_and_accepts_an_eligible_one": ANCHOR_PREFIX + "preflight_refuses_each_ineligible_fill_with_a_typed_reason_and_accepts_an_eligible_one",
    "test_apply_counts_only_a_bound_conforming_fill": ANCHOR_PREFIX + "apply_counts_only_a_bound_conforming_fill",
    "test_apply_never_replaces_a_runtime_leg": ANCHOR_PREFIX + "apply_never_replaces_a_runtime_leg",
    "test_president_rules_on_the_bound_fill_on_both_deferral_paths": ANCHOR_PREFIX + "president_rules_on_the_bound_fill_on_both_deferral_paths",
    "test_composition_digest_is_content_only_and_order_independent": ANCHOR_PREFIX + "composition_digest_is_content_only_and_order_independent",
    "test_request_payload_carries_the_binding": ANCHOR_PREFIX + "request_payload_carries_the_binding",
    "test_gate_emit_arm_returns_the_request_without_minting_or_invoking": ANCHOR_PREFIX + "gate_emit_arm_returns_the_request_without_minting_or_invoking",
    "test_run_train_emit_arm_spends_nothing": ANCHOR_PREFIX + "run_train_emit_arm_spends_nothing",
    "test_run_train_refuses_a_stale_fill_before_spending_a_seat": ANCHOR_PREFIX + "run_train_refuses_a_stale_fill_before_spending_a_seat",
    "test_cli_emit_arm_writes_the_request_and_run_train_accepts_the_flags": ANCHOR_PREFIX + "cli_emit_arm_writes_the_request_and_run_train_accepts_the_flags",
    "test_observation_is_typed_incomplete_under_claude_code_without_a_fill_and_launches_nothing": ANCHOR_PREFIX + "observation_is_typed_incomplete_under_claude_code_without_a_fill_and_launches_nothing",
    "test_observation_is_typed_incomplete_outside_claude_code_and_never_launches_the_external_leg": ANCHOR_PREFIX + "observation_is_typed_incomplete_outside_claude_code_and_never_launches_the_external_leg",
    "test_assumption_probe_caller_fails_closed_on_an_incomplete_observation": ANCHOR_PREFIX + "assumption_probe_caller_fails_closed_on_an_incomplete_observation",
    "test_sidecar_capture_refuses_an_incomplete_observation_and_writes_nothing": ANCHOR_PREFIX + "sidecar_capture_refuses_an_incomplete_observation_and_writes_nothing",
}


def require(nodeid_basename: str, condition: Any, detail: str = "") -> None:
    anchor = RED_ANCHORS.get(nodeid_basename)
    assert anchor is not None, f"{ANCHOR_PREFIX}INVENTORY_DRIFT unknown falsifier {nodeid_basename!r}"
    assert condition, f"{anchor}: {detail}" if detail else anchor
