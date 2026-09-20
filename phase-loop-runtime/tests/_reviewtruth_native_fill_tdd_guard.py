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
    "test_fable_seat_request_is_built_under_claude_code": ANCHOR_PREFIX + "routing_builder_fable_under_claude_code",
    "test_under_claude_code_is_a_typed_unavailable_detail": ANCHOR_PREFIX + "routing_typed_detail",
    "test_early_deferral_path_attaches_a_request_for_the_fable_seat": ANCHOR_PREFIX + "routing_early_path_request",
    "test_matrix_path_attaches_a_request_for_the_fable_seat": ANCHOR_PREFIX + "routing_matrix_path_request",
    "test_native_leg_fill_is_a_frozen_record_with_the_binding_fields": ANCHOR_PREFIX + "ingestion_fill_record",
    "test_loader_takes_digests_from_the_emitted_request_only": ANCHOR_PREFIX + "ingestion_loader_emitted_digests",
    "test_preflight_refuses_each_ineligible_fill_with_a_typed_reason": ANCHOR_PREFIX + "ingestion_preflight_refusals",
    "test_apply_counts_only_a_bound_conforming_fill": ANCHOR_PREFIX + "ingestion_apply_bound_only",
    "test_apply_never_replaces_a_runtime_leg": ANCHOR_PREFIX + "ingestion_never_replaces_runtime_leg",
    "test_composition_digest_is_over_sorted_seat_keys": ANCHOR_PREFIX + "protocol_composition_digest",
    "test_request_payload_carries_the_binding": ANCHOR_PREFIX + "protocol_request_payload",
    "test_gate_emit_arm_returns_a_request_without_minting_or_invoking": ANCHOR_PREFIX + "protocol_gate_emit_arm",
    "test_run_train_emit_arm_spends_nothing": ANCHOR_PREFIX + "protocol_train_emit_arm",
    "test_cli_flags_parse_on_both_commands": ANCHOR_PREFIX + "protocol_cli_flags",
    "test_one_observation_function_exists_with_a_typed_incomplete_result": ANCHOR_PREFIX + "probe_one_observation_function",
    "test_assumption_probe_caller_delegates_to_the_one_function": ANCHOR_PREFIX + "probe_caller_delegates",
    "test_sidecar_capture_refuses_an_incomplete_observation": ANCHOR_PREFIX + "probe_capture_refuses_incomplete",
}


def require(nodeid_basename: str, condition: Any, detail: str = "") -> None:
    anchor = RED_ANCHORS.get(nodeid_basename)
    assert anchor is not None, f"{ANCHOR_PREFIX}INVENTORY_DRIFT unknown falsifier {nodeid_basename!r}"
    assert condition, f"{anchor}: {detail}" if detail else anchor
