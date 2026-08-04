"""proofgate_tdd_guard.py — PROOFGATE SL0-T1 TDD guard & inventory contract."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pytest


def normalize_nodeid(nodeid: str) -> str:
    """Normalizes relative tests/... pytest node IDs to canonical phase-loop-runtime/tests/... node IDs."""
    if nodeid and not nodeid.startswith("phase-loop-runtime/") and nodeid.startswith("tests/"):
        return f"phase-loop-runtime/{nodeid}"
    return nodeid


EXPECTED_PHASE_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_bootstrap_records_are_single_use_and_server_bound",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_implementation_authorization_requires_activation_preflight_panel_and_red_order",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_runner_routes_reject_child_claims_and_missing_latest_external_head",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_isolation_preflight_masks_host_sibling_receipt_logs_fds_and_credentials",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_capability_socket_rejects_privileged_unknown_replayed_or_wrong_peer_requests",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_execute_and_panel_routes_use_remote_less_assigned_clone_or_refuse",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py::test_attestation_workflow_is_github_hosted_exact_subject_and_blob_bound",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_requires_two_parent_tests_bootstrap_and_implementation_landings",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_tests_only_range_with_non_test_bytes",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_bootstrap_range_outside_frozen_set_or_test_edit",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_implementation_range_test_guard_selector_nodeid_count_or_anchor_edit",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_same_branch_squash_rebase_direct_push_copy_or_hidden_parent",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_candidate_snapshot_is_source_head_parented_and_rematerializes_byte_identically",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_fresh_process_lifecycle_rejects_builder_stale_head_loaded_parent_or_same_process",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_unmatched_anchor_is_mutation_not_applied",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_candidate_or_command_digest_drift",
    "phase-loop-runtime/tests/test_closeout_verification_gate.py::CloseoutVerificationGateTest::test_proofgate_closeout_rejects_missing_or_invalid_attested_proof",
    "phase-loop-runtime/tests/test_preflight_verification.py::PreflightVerificationTest::test_proofgate_preflight_requires_attested_authorization_and_exact_candidate",
    "phase-loop-runtime/tests/test_train_invariants.py::TestInvariant6LiveReverifyRunsVerification::test_proofgate_train_reverify_requires_exact_attested_proof",
    "phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageTest::test_acceptance_contracts_classify_valid_invalid_and_grandfathered",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_288_ac1_and_ac4_are_rejected",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence",
    "phase-loop-runtime/tests/test_skills_canon_parity.py::SkillsCanonParityTest::test_plan_phase_skills_publish_falsifier_grammar",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py::SkillsBundleDriftTest::test_proofgate_validator_and_guidance_are_generated_without_drift",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py::test_codex_execute_command_is_danger_full_access_and_live_repo",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation",
)

DEFAULT_SKIP_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_bootstrap_records_are_single_use_and_server_bound",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_implementation_authorization_requires_activation_preflight_panel_and_red_order",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_runner_routes_reject_child_claims_and_missing_latest_external_head",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_isolation_preflight_masks_host_sibling_receipt_logs_fds_and_credentials",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_capability_socket_rejects_privileged_unknown_replayed_or_wrong_peer_requests",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_execute_and_panel_routes_use_remote_less_assigned_clone_or_refuse",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py::test_attestation_workflow_is_github_hosted_exact_subject_and_blob_bound",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_requires_two_parent_tests_bootstrap_and_implementation_landings",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_tests_only_range_with_non_test_bytes",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_bootstrap_range_outside_frozen_set_or_test_edit",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_implementation_range_test_guard_selector_nodeid_count_or_anchor_edit",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_same_branch_squash_rebase_direct_push_copy_or_hidden_parent",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_candidate_snapshot_is_source_head_parented_and_rematerializes_byte_identically",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_fresh_process_lifecycle_rejects_builder_stale_head_loaded_parent_or_same_process",
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_unmatched_anchor_is_mutation_not_applied",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_candidate_or_command_digest_drift",
    "phase-loop-runtime/tests/test_closeout_verification_gate.py::CloseoutVerificationGateTest::test_proofgate_closeout_rejects_missing_or_invalid_attested_proof",
    "phase-loop-runtime/tests/test_preflight_verification.py::PreflightVerificationTest::test_proofgate_preflight_requires_attested_authorization_and_exact_candidate",
    "phase-loop-runtime/tests/test_train_invariants.py::TestInvariant6LiveReverifyRunsVerification::test_proofgate_train_reverify_requires_exact_attested_proof",
    "phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageTest::test_acceptance_contracts_classify_valid_invalid_and_grandfathered",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_288_ac1_and_ac4_are_rejected",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence",
    "phase-loop-runtime/tests/test_skills_canon_parity.py::SkillsCanonParityTest::test_plan_phase_skills_publish_falsifier_grammar",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py::SkillsBundleDriftTest::test_proofgate_validator_and_guidance_are_generated_without_drift",
)

ACTIVATION_MIGRATED_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_review_leg_sandbox.py::test_codex_execute_command_is_danger_full_access_and_live_repo",
)

TYPED_ORACLE_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation",
)
POSITIVE_CONTROL_NODEIDS: tuple[str, ...] = TYPED_ORACLE_NODEIDS

assert len(EXPECTED_PHASE_NODEIDS) == 39
assert len(DEFAULT_SKIP_NODEIDS) == 36
assert len(ACTIVATION_MIGRATED_NODEIDS) == 1
assert len(TYPED_ORACLE_NODEIDS) == 2
assert set(EXPECTED_PHASE_NODEIDS) == set(DEFAULT_SKIP_NODEIDS) | set(ACTIVATION_MIGRATED_NODEIDS) | set(TYPED_ORACLE_NODEIDS)
assert len(set(DEFAULT_SKIP_NODEIDS) & set(ACTIVATION_MIGRATED_NODEIDS)) == 0
assert len(set(DEFAULT_SKIP_NODEIDS) & set(TYPED_ORACLE_NODEIDS)) == 0
assert len(set(ACTIVATION_MIGRATED_NODEIDS) & set(TYPED_ORACLE_NODEIDS)) == 0

ORDINARY_BROAD_PHASE_NODEIDS: tuple[str, ...] = EXPECTED_PHASE_NODEIDS
ATTENDED_PHASE_NODEIDS: tuple[str, ...] = EXPECTED_PHASE_NODEIDS

ATTENDED_REAL_PROVIDER_CASES: tuple[str, ...] = (
    "fable_subscription_transport_reachable",
    "sol_terra_subscription_transport_reachable",
    "gemini_subscription_transport_reachable",
    "grok_subscription_transport_reachable",
)

PROOFGATE_LITERAL_CASE_IDS: tuple[str, ...] = (
    "acceptance_exact_cutoff_raw_bytes_warn_only",
    "acceptance_grandfather_record_carries_server_attested_pre_grammar_date",
    "acceptance_invalid_rejected_at_intake_and_closeout",
    "broker_rejects_credential_exfiltration_before_network",
    "broker_rejects_method_path_header_body_model_misuse",
    "broker_rejects_redirect_secondary_endpoint_proxy_and_raw_tls",
    "broker_result_taint_rejected",
    "check_p_non_grandfathered_missing_falsifier_returns_nonzero",
    "check_p_non_grandfathered_missing_path_entered_returns_nonzero",
    "check_p_non_grandfathered_vacuous_corpus_returns_nonzero",
    "child_log_taint_rejected",
    "child_multi_turn_local_tool_loop_reachable",
    "credential_argv_absent",
    "credential_env_absent",
    "credential_fd_absent",
    "credential_mount_absent",
    "credentialless_artifact_scanner_has_no_live_secret_corpus",
    "credentialless_parser_and_adapter_diagnostics_taint_rejected",
    "credentialless_request_semantics_validated_before_owner",
    "credentialless_response_parser_has_no_session_access",
    "encoded_and_split_taint_rejected",
    "external_head_attested_core_then_bundle_then_append_is_acyclic",
    "external_head_complete_history_recovery",
    "external_head_concurrent_cas_single_winner",
    "external_head_core_bundle_append_or_latest_tamper_rejected",
    "external_head_core_bundle_append_replay_rejected",
    "external_head_core_filename_subject_append_binding_tamper_rejected",
    "external_head_core_self_digest_field_rejected",
    "external_head_missing_pointer_genesis_or_fail_closed",
    "external_head_older_signed_prefix_rollback_rejected",
    "external_head_queryable_without_subject_digest",
    "external_head_ruleset_workflow_environment_bound",
    "external_head_stale_expected_oid_rejected",
    "fable_subscription_transport_reachable",
    "gemini_subscription_transport_reachable",
    "grok_subscription_transport_reachable",
    "hostile_prompt_parent_read_refused",
    "hostile_prompt_parent_write_delete_git_publish_cloud_refused",
    "hostile_prompt_secret_retrieval_and_arbitrary_egress_refused",
    "inference_exact_provider_model_seat",
    "inference_output_provenance_bound",
    "inference_rejects_method_url_header_path",
    "inference_request_result_frame_immutable",
    "mandatory_provider_real_inference_reachable",
    "owner_auth_challenge_response_rejected",
    "owner_cannot_read_repo_logs_source_or_git_objects",
    "owner_complete_reassembly_precedes_release",
    "owner_raw_response_live_credential_bytes_rejected",
    "owner_redirect_response_rejected",
    "owner_refresh_response_rejected",
    "owner_releases_only_bounded_content_frame",
    "owner_rotated_token_response_rejected",
    "owner_set_cookie_response_rejected",
    "owner_transform_closure_base64_standard_url_padded_unpadded_rejected",
    "owner_transform_closure_every_chunk_split_rejected",
    "owner_transform_closure_limits_and_metadata_nonexport",
    "owner_transform_closure_percent_hex_json_backslash_rejected",
    "owner_transform_closure_raw_header_cookie_rejected",
    "owner_unsupported_control_metadata_rejected",
    "owner_unsupported_encoding_or_framing_rejected",
    "provider_adapter_has_no_subscription_projection",
    "provider_adapter_image_rootfs_protocol_policy_bound",
    "safe_intended_inference_and_import_succeeds",
    "semantic_namespaces_cannot_read_owner_memory_files_fds_or_socket",
    "session_owner_has_no_semantic_parser_or_general_scanner",
    "session_owner_preregistered_bytes_pre_network_exact_equality",
    "sol_terra_subscription_transport_reachable",
    "submitted_result_taint_rejected",
    "subscription_state_absent",
    "subscription_transport_broker_exclusive_session_owner",
    "taint_required_before_attestation",
    "taint_required_before_commit",
    "taint_required_before_push",
    "tracked_source_taint_rejected",
    "trusted_parent_outside_model_tool_boundary",
    "untracked_source_taint_rejected",
    "untrusted_model_text_cannot_become_executable_or_auth_state",
)

assert len(PROOFGATE_LITERAL_CASE_IDS) == 77
assert len(set(PROOFGATE_LITERAL_CASE_IDS)) == 77

PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES = (
    "# PROOFGATE route rejection\n\n"
    "## Acceptance Criteria\n"
    "- [ ] EC-PROOFGATE-ROUTE-1 — proven by `python3 -c \"print('ok')\"`, "
    "falsified by `fails if invalid key is accepted`\n"
)

COORDINATOR_EVIDENCE_FILES: dict[str, tuple[str, str]] = {
    "proofgate-tests-only-default.junit.xml": ("proofgate-tests-only-default.phase-reports.json", "default"),
    "proofgate-tests-only-red.junit.xml": ("proofgate-tests-only-red.phase-reports.json", "forced_red"),
    "proofgate-candidate-ordinary.junit.xml": ("proofgate-candidate-ordinary.phase-reports.json", "ordinary_hermetic"),
    "proofgate-candidate-attended.junit.xml": ("proofgate-candidate-attended.phase-reports.json", "attended_live"),
}


def _coordinator_capture_target(run_dir: Path) -> tuple[Path, str, str] | None:
    """Return the plan-named report path only for an explicit coordinator JUnit command."""
    for arg in sys.argv:
        if not arg.startswith("--junitxml="):
            continue
        raw_junit_path = arg.split("=", 1)[1]
        if raw_junit_path.startswith("$PHASE_LOOP_RUN_DIR/"):
            raw_junit_path = str(run_dir / raw_junit_path.removeprefix("$PHASE_LOOP_RUN_DIR/"))
        junit_path = Path(raw_junit_path).resolve()
        if junit_path.parent != run_dir:
            continue
        mapped = COORDINATOR_EVIDENCE_FILES.get(junit_path.name)
        if mapped is not None:
            phase_reports_filename, mode = mapped
            return run_dir / phase_reports_filename, junit_path.name, mode
    return None

PROOFGATE_SOURCE_ANCHOR_ROWS_V1: tuple[str, ...] = (
    "| `PG-A-LAUNCH` | `phase-loop-runtime/src/phase_loop_runtime/launcher.py`: `command.extend([\"--sandbox\", \"danger-full-access\"])` |\n",
    "| `PG-A-PANEL` | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`: `env = _subscription_env() if env is None else dict(env)` |\n",
    "| `PG-A-RUNNER` | `phase-loop-runtime/src/phase_loop_runtime/runner.py`: `from .dispatch_lock import DispatchLock, DispatchLockContention` |\n",
    "| `PG-A-GOAL` | `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`: `_ACCEPTANCE_SECTION_RE = re.compile(` |\n",
    "| `PG-A-VERIFY-V3` | semantic predecessor interface captured from the exact fetched two-parent LEGIBLE landing: `verification_evidence.v3` is supported; one generic extension registry, reader, and seal protocol are present; `phase_loop_runtime.legible_evidence` is registered and accepted; and `phase_loop_runtime.proofgate_evidence` is absent. Before tests, bind the landing OID plus the exact implementing source blobs/semantic probe output and prove PROOFGATE will add only its own namespace |\n",
    "| `PG-A-CLOSEOUT` | `phase-loop-runtime/src/phase_loop_runtime/closeout.py`: `def _apply_verification_evidence_gate(` |\n",
    "| `PG-A-TRAIN` | `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`: `def _live_reverify(workspace: Path, roadmap_path: Path, run_mode: str) -> bool:` |\n",
    "| `PG-A-VALIDATOR` | `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`: `def _check_p_goal_id_coverage(` |\n",
    "| `PG-A-WORKFLOW` | `.github/workflows/test.yml`: `permissions:` followed by `contents: read`, and `run: python -m pytest -m \"not dotfiles_integration\"` |\n",
    "| `PG-A-BROKER-GITHUB` | `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`: the `Path(broker_root), admission_policy or _default_admission_policy, epoch_blocked=lambda: evidence_store.epoch_blocked,` constructor context |\n",
    "| `PG-A-BROKER-ROUTING` | `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`: the `root, self._admission_policy, epoch_blocked=lambda: evidence_store.epoch_blocked` constructor context |\n",
)

RED_CASES_BY_NODEID: dict[str, tuple[str, str | tuple[str, ...]]] = {
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_bootstrap_records_are_single_use_and_server_bound": (
        "PG-A-RUNNER",
        "bootstrap_records_are_single_use_and_server_bound",
    ),
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill": (
        "PG-A-RUNNER",
        "receipt_chain_rejects_rewrite_truncation_fork_or_backfill",
    ),
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp": (
        "PG-A-RUNNER",
        "receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp",
    ),
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_implementation_authorization_requires_activation_preflight_panel_and_red_order": (
        "PG-A-RUNNER",
        "implementation_authorization_requires_activation_preflight_panel_and_red_order",
    ),
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_runner_routes_reject_child_claims_and_missing_latest_external_head": (
        "PG-A-RUNNER",
        "runner_routes_reject_child_claims_and_missing_latest_external_head",
    ),
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_isolation_preflight_masks_host_sibling_receipt_logs_fds_and_credentials": (
        "PG-A-LAUNCH",
        PROOFGATE_LITERAL_CASE_IDS,
    ),
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material": (
        "PG-A-PANEL",
        PROOFGATE_LITERAL_CASE_IDS,
    ),
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_capability_socket_rejects_privileged_unknown_replayed_or_wrong_peer_requests": (
        "PG-A-LAUNCH",
        PROOFGATE_LITERAL_CASE_IDS,
    ),
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_execute_and_panel_routes_use_remote_less_assigned_clone_or_refuse": (
        "PG-A-LAUNCH",
        PROOFGATE_LITERAL_CASE_IDS,
    ),
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py::test_attestation_workflow_is_github_hosted_exact_subject_and_blob_bound": (
        "PG-A-WORKFLOW",
        "attestation_workflow_is_github_hosted_exact_subject_and_blob_bound",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid": (
        "PG-A-GOAL",
        "missing_falsifier_is_invalid",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control": (
        "PG-A-GOAL",
        "negative_assertion_requires_path_entered_control",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site": (
        "PG-A-GOAL",
        "guard_requires_production_construction_site",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage": (
        "PG-A-GOAL",
        "mutation_manifest_requires_exact_criterion_parameter_and_command_coverage",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_requires_two_parent_tests_bootstrap_and_implementation_landings": (
        "PG-A-RUNNER",
        "chronology_requires_two_parent_tests_bootstrap_and_implementation_landings",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_tests_only_range_with_non_test_bytes": (
        "PG-A-RUNNER",
        "chronology_rejects_tests_only_range_with_non_test_bytes",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_bootstrap_range_outside_frozen_set_or_test_edit": (
        "PG-A-RUNNER",
        "chronology_rejects_bootstrap_range_outside_frozen_set_or_test_edit",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_implementation_range_test_guard_selector_nodeid_count_or_anchor_edit": (
        "PG-A-RUNNER",
        "chronology_rejects_implementation_range_test_guard_selector_nodeid_count_or_anchor_edit",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_same_branch_squash_rebase_direct_push_copy_or_hidden_parent": (
        "PG-A-RUNNER",
        "chronology_rejects_same_branch_squash_rebase_direct_push_copy_or_hidden_parent",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_candidate_snapshot_is_source_head_parented_and_rematerializes_byte_identically": (
        "PG-A-RUNNER",
        "candidate_snapshot_is_source_head_parented_and_rematerializes_byte_identically",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_fresh_process_lifecycle_rejects_builder_stale_head_loaded_parent_or_same_process": (
        "PG-A-RUNNER",
        "fresh_process_lifecycle_rejects_builder_stale_head_loaded_parent_or_same_process",
    ),
    "phase-loop-runtime/tests/test_tdd_chronology.py::test_junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips": (
        "PG-A-RUNNER",
        "junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_unmatched_anchor_is_mutation_not_applied": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_unmatched_anchor_is_mutation_not_applied",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_candidate_or_command_digest_drift": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_rejects_candidate_or_command_digest_drift",
    ),
    "phase-loop-runtime/tests/test_closeout_verification_gate.py::CloseoutVerificationGateTest::test_proofgate_closeout_rejects_missing_or_invalid_attested_proof": (
        "PG-A-CLOSEOUT",
        "proofgate_closeout_rejects_missing_or_invalid_attested_proof",
    ),
    "phase-loop-runtime/tests/test_preflight_verification.py::PreflightVerificationTest::test_proofgate_preflight_requires_attested_authorization_and_exact_candidate": (
        "PG-A-RUNNER",
        "proofgate_preflight_requires_attested_authorization_and_exact_candidate",
    ),
    "phase-loop-runtime/tests/test_train_invariants.py::TestInvariant6LiveReverifyRunsVerification::test_proofgate_train_reverify_requires_exact_attested_proof": (
        "PG-A-TRAIN",
        "proofgate_train_reverify_requires_exact_attested_proof",
    ),
    "phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageTest::test_acceptance_contracts_classify_valid_invalid_and_grandfathered": (
        "PG-A-GOAL",
        "acceptance_contracts_classify_valid_invalid_and_grandfathered",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected": (
        "PG-A-VALIDATOR",
        "agent_harness_358_original_is_rejected",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_288_ac1_and_ac4_are_rejected": (
        "PG-A-VALIDATOR",
        "agent_harness_288_ac1_and_ac4_are_rejected",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns": (
        "PG-A-VALIDATOR",
        "grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence": (
        "PG-A-VALIDATOR",
        "changed_or_new_criterion_requires_v3_evidence",
    ),
    "phase-loop-runtime/tests/test_skills_canon_parity.py::SkillsCanonParityTest::test_plan_phase_skills_publish_falsifier_grammar": (
        "PG-A-VALIDATOR",
        "plan_phase_skills_publish_falsifier_grammar",
    ),
    "phase-loop-runtime/tests/test_skills_bundle_drift.py::SkillsBundleDriftTest::test_proofgate_validator_and_guidance_are_generated_without_drift": (
        "PG-A-VALIDATOR",
        "proofgate_validator_and_guidance_are_generated_without_drift",
    ),
    "phase-loop-runtime/tests/test_review_leg_sandbox.py::test_codex_execute_command_is_danger_full_access_and_live_repo": (
        "PG-A-LAUNCH",
        "codex_execute_command_is_danger_full_access_and_live_repo",
    ),
}

assert len(RED_CASES_BY_NODEID) == 37
assert set(RED_CASES_BY_NODEID.keys()) == set(DEFAULT_SKIP_NODEIDS) | set(ACTIVATION_MIGRATED_NODEIDS)


def red_case_ids(nodeid: str) -> tuple[str, ...]:
    raw_cases = RED_CASES_BY_NODEID[nodeid][1]
    return raw_cases if isinstance(raw_cases, tuple) else (raw_cases,)


def primary_red_case_id(nodeid: str) -> str:
    return red_case_ids(nodeid)[0]


for _isolation_nodeid in (
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_isolation_preflight_masks_host_sibling_receipt_logs_fds_and_credentials",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_capability_socket_rejects_privileged_unknown_replayed_or_wrong_peer_requests",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_execute_and_panel_routes_use_remote_less_assigned_clone_or_refuse",
):
    assert red_case_ids(_isolation_nodeid) == PROOFGATE_LITERAL_CASE_IDS

MUTATION_RULES_BY_PARAMETER: dict[str, tuple[str, str, str, str, str, str]] = {
    "ec-proofgate-0.chronology-guard": (
        "EC-PROOFGATE-0",
        "1c6230d9b116fc9fb758df530f4319d2570c4500fc0f793e960bfffea0beb4b1",
        "ec-proofgate-0.chronology-guard",
        "tdd_chronology_rejection",
        "phase-loop-runtime/tests/test_tdd_chronology.py::test_junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips",
        "chronology_guard_unwired",
    ),
    "ec-proofgate-1.missing-falsifier": (
        "EC-PROOFGATE-1",
        "2eb6215c889f5db9d6c5559819a4374be8a89e2a426833c565636c967634b62f",
        "ec-proofgate-1.missing-falsifier",
        "missing_falsifier_rejection",
        "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid",
        "missing_falsifier_unwired",
    ),
    "ec-proofgate-2.mutation-application": (
        "EC-PROOFGATE-2",
        "f379956954c1096e75b3b81635e171827be747eef7c565a8e6f68e6db4039e7d",
        "ec-proofgate-2.mutation-application",
        "mutation_application_rejection",
        "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_candidate_or_command_digest_drift",
        "declared_contract_rejection_is_killed",
    ),
    "ec-proofgate-3.vacuous-falsifier": (
        "EC-PROOFGATE-3",
        "c33f5018894552d5af14a0ed4097838d61936f46b4a486186c1a8dd8e0cd03c9",
        "ec-proofgate-3.vacuous-falsifier",
        "vacuous_falsifier_rejection",
        "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected",
        "vacuous_falsifier_unwired",
    ),
    "ec-proofgate-4.github-builder-epoch-blocked": (
        "EC-PROOFGATE-4",
        "2b1d58a75fabc43e45c908b4e44d616778a29cf5011612e09d9bffa0689d4e7b",
        "ec-proofgate-4.github-builder-epoch-blocked",
        "production_construction_site_rejection",
        "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation",
        "github_builder_epoch_blocked_unwired",
    ),
    "ec-proofgate-4.routing-builder-epoch-blocked": (
        "EC-PROOFGATE-4",
        "2b1d58a75fabc43e45c908b4e44d616778a29cf5011612e09d9bffa0689d4e7b",
        "ec-proofgate-4.routing-builder-epoch-blocked",
        "production_construction_site_rejection",
        "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation",
        "routing_builder_epoch_blocked_unwired",
    ),
    "ec-proofgate-5.parameter-coverage": (
        "EC-PROOFGATE-5",
        "cdd99cae0696b659640cc3481195e93e54af35198f76fd1ae727f9720b4de4c0",
        "ec-proofgate-5.parameter-coverage",
        "parameter_coverage_rejection",
        "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
        "parameter_coverage_unwired",
    ),
    "ec-proofgate-6.missing-path-entered": (
        "EC-PROOFGATE-6",
        "397cd8f421b1149d64b9039eb87e6da17114cdb7842f64e28937548dd0169526",
        "ec-proofgate-6.missing-path-entered",
        "missing_path_entered_control_rejection",
        "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control",
        "missing_path_entered_control_unwired",
    ),
    "ec-proofgate-7.grandfathering": (
        "EC-PROOFGATE-7",
        "84456823b1ff6fac271929a429b5b0acaf6af47884ef59a5dda011f65f6f3f0a",
        "ec-proofgate-7.grandfathering",
        "grandfathering_rejection",
        "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
        "grandfathering_unwired",
    ),
}

# These are assertion identities, not source-anchor identities.  They deliberately
# stay test-owned because the runner must compare the emitted JUnit property rather
# than reconstructing it from a declaration, nodeid, or failure text.
EC_PROOFGATE_4_ASSERTION_IDS: dict[str, str] = {
    "ec-proofgate-4.github-builder-epoch-blocked": "github_builder_epoch_blocked_wiring",
    "ec-proofgate-4.routing-builder-epoch-blocked": "routing_builder_epoch_blocked_wiring",
}


def proofgate_active() -> bool:
    """True if PROOFGATE mode is active via environment or capability marker."""
    return (
        os.environ.get("PHASE_LOOP_TDD_EXPECT_PROOFGATE") == "1"
        or proofgate_capability_version() == "proofgate.v1"
    )


def proofgate_capability_version() -> str:
    """Returns 'proofgate.v1' if production proofgate capabilities are implemented, else 'unimplemented'."""
    try:
        from phase_loop_runtime.proofgate_capability import PROOFGATE_CAPABILITY_VERSION
        return str(PROOFGATE_CAPABILITY_VERSION)
    except (ImportError, AttributeError):
        pass
    return "unimplemented"


def proofgate_attended_live() -> bool:
    """Returns True iff attended live runner mode is requested."""
    return os.environ.get("PHASE_LOOP_PROOFGATE_ATTENDED_LIVE") == "1"


def _consume_attended_runner_envelope() -> dict[str, Any] | None:
    raw = os.environ.pop("PHASE_LOOP_PROOFGATE_RUNNER_ENVELOPE", None)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"invalid": True}
    return payload if isinstance(payload, dict) else {"invalid": True}


_ATTENDED_RUNNER_ENVELOPE = _consume_attended_runner_envelope()


def proofgate_attended_runner_envelope() -> dict[str, Any] | None:
    if _ATTENDED_RUNNER_ENVELOPE is None:
        return None
    return json.loads(json.dumps(_ATTENDED_RUNNER_ENVELOPE))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def assert_source_anchor(anchor_id: str) -> None:
    root = _repo_root()
    if anchor_id == "PG-A-LAUNCH":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/launcher.py"
        content = path.read_text(encoding="utf-8")
        assert 'command.extend(["--sandbox", "danger-full-access"])' in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-PANEL":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py"
        content = path.read_text(encoding="utf-8")
        assert "env = _subscription_env() if env is None else dict(env)" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-RUNNER":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/runner.py"
        content = path.read_text(encoding="utf-8")
        assert "from .dispatch_lock import DispatchLock, DispatchLockContention" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-GOAL":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py"
        content = path.read_text(encoding="utf-8")
        assert "_ACCEPTANCE_SECTION_RE = re.compile(" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-VERIFY-V3":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py"
        content = path.read_text(encoding="utf-8")
        assert "EXTENSION_NAMESPACE_REGISTRY" in content, f"Anchor {anchor_id} missing in {path}"
        from phase_loop_runtime.verification_evidence import EXTENSION_NAMESPACE_REGISTRY
        assert "phase_loop_runtime.legible_evidence" in EXTENSION_NAMESPACE_REGISTRY, f"Anchor {anchor_id} legible missing"
        assert "phase_loop_runtime.proofgate_evidence" not in EXTENSION_NAMESPACE_REGISTRY, f"Anchor {anchor_id} proofgate present"
    elif anchor_id == "PG-A-CLOSEOUT":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/closeout.py"
        content = path.read_text(encoding="utf-8")
        assert "def _apply_verification_evidence_gate(" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-TRAIN":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/train_runner.py"
        content = path.read_text(encoding="utf-8")
        assert "def _live_reverify(workspace: Path, roadmap_path: Path, run_mode: str) -> bool:" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-VALIDATOR":
        path = root / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
        content = path.read_text(encoding="utf-8")
        assert "def _check_p_goal_id_coverage(" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-WORKFLOW":
        path = root / ".github/workflows/test.yml"
        content = path.read_text(encoding="utf-8")
        assert "permissions:" in content and "contents: read" in content and 'python -m pytest -m "not dotfiles_integration"' in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-BROKER-GITHUB":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py"
        content = path.read_text(encoding="utf-8")
        assert "epoch_blocked=lambda: evidence_store.epoch_blocked" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-BROKER-ROUTING":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py"
        content = path.read_text(encoding="utf-8")
        assert "epoch_blocked=lambda: evidence_store.epoch_blocked" in content, f"Anchor {anchor_id} missing in {path}"
    else:
        raise ValueError(f"Unknown anchor ID {anchor_id}")


def guard_proofgate_nodeid(nodeid: str) -> bool:
    """TDD lifecycle guard for a PROOFGATE nodeid.

    Returns:
        True if capability marker is present or forced RED mode (run candidate/substantive test),
        False if test should execute legacy/positive assertions (when inactive or positive control).
    """
    if not proofgate_active():
        if nodeid in DEFAULT_SKIP_NODEIDS:
            pytest.skip("PROOFGATE capability or PHASE_LOOP_TDD_EXPECT_PROOFGATE required")
        return False

    cap = proofgate_capability_version()
    if cap == "proofgate.v1":
        return True

    if nodeid in TYPED_ORACLE_NODEIDS:
        return True

    if nodeid in RED_CASES_BY_NODEID:
        anchor_id, _ = RED_CASES_BY_NODEID[nodeid]
        assert_source_anchor(anchor_id)

    return True


def proofgate_red_message(nodeid: str) -> str:
    """Returns the typed PROOFGATE_RED message for a nodeid."""
    if nodeid in RED_CASES_BY_NODEID:
        return f"PROOFGATE_RED::{primary_red_case_id(nodeid)}"
    return f"PROOFGATE_RED::{nodeid}"


class ProofgateMissingCapabilityError(Exception):
    """Raised by a PROOFGATE test contract when an expected capability is absent on an existing module."""


def run_proofgate_contract(nodeid: str, contract_fn) -> None:
    """Executes a PROOFGATE test contract for a nodeid.

    If proofgate capability is active (proofgate.v1), runs contract_fn().
    In forced RED mode against unchanged production, converts pre-implementation missing capability into the nodeid's typed RED failure.
    Semantic assertions (AssertionError) and ValueErrors are NOT caught.
    """
    if proofgate_capability_version() == "proofgate.v1":
        contract_fn()
        return

    if nodeid in TYPED_ORACLE_NODEIDS:
        contract_fn()
        return

    if nodeid in RED_CASES_BY_NODEID:
        anchor_id, _ = RED_CASES_BY_NODEID[nodeid]
        assert_source_anchor(anchor_id)
        try:
            contract_fn()
        except ProofgateMissingCapabilityError as exc:
            msg = proofgate_red_message(nodeid)
            raise AssertionError(msg) from exc
        msg = proofgate_red_message(nodeid)
        raise AssertionError(f"Expected ProofgateMissingCapabilityError for {nodeid}, but contract completed without raising expected missing capability exception")

    contract_fn()


def emit_mutation_observable(param_id: str, record_property: Any) -> None:
    """Emits a proofgate_mutation_observable.v1 JUnit property immediately before assertion rejection."""
    if record_property is None or param_id not in MUTATION_RULES_BY_PARAMETER:
        return
    crit_id, crit_sha, rule_id, fail_class, nodeid, res_code = MUTATION_RULES_BY_PARAMETER[param_id]
    assertion_id = EC_PROOFGATE_4_ASSERTION_IDS.get(param_id, "PG-A-GOAL")
    if param_id not in EC_PROOFGATE_4_ASSERTION_IDS and nodeid in RED_CASES_BY_NODEID:
        assertion_id, _ = RED_CASES_BY_NODEID[nodeid]
    observable = {
        "schema": "proofgate_mutation_observable.v1",
        "roadmap_criterion_id": crit_id,
        "roadmap_criterion_sha256": crit_sha,
        "rule_id": rule_id,
        "failure_class": fail_class,
        "target_nodeid": nodeid,
        "result_code": res_code,
        "assertion_id": assertion_id,
    }
    record_property("proofgate_mutation_observable", json.dumps(observable, sort_keys=True))


def assert_exact_mutation_observable(param_id: str, properties: list[tuple[str, str]]) -> None:
    """Rejects absent, substituted, or synthesized mutation oracle fields.

    This small test-owned oracle intentionally accepts only the one exact call-phase
    property for a declared parameter.  In particular, EC-PROOFGATE-4 assertion IDs
    cannot be replaced with their PG-A source anchors or inferred from the nodeid.
    """
    if param_id not in MUTATION_RULES_BY_PARAMETER:
        raise AssertionError(f"unknown mutation parameter: {param_id}")
    if len(properties) != 1 or properties[0][0] != "proofgate_mutation_observable":
        raise AssertionError("mutation observable must contain exactly one canonical property")
    try:
        actual = json.loads(properties[0][1])
    except (TypeError, json.JSONDecodeError) as exc:
        raise AssertionError("mutation observable property must contain canonical JSON") from exc
    if not isinstance(actual, dict):
        raise AssertionError("mutation observable JSON must be an object")

    crit_id, crit_sha, rule_id, fail_class, nodeid, res_code = MUTATION_RULES_BY_PARAMETER[param_id]
    assertion_id = EC_PROOFGATE_4_ASSERTION_IDS.get(param_id, "PG-A-GOAL")
    if param_id not in EC_PROOFGATE_4_ASSERTION_IDS and nodeid in RED_CASES_BY_NODEID:
        assertion_id, _ = RED_CASES_BY_NODEID[nodeid]
    expected = {
        "schema": "proofgate_mutation_observable.v1",
        "roadmap_criterion_id": crit_id,
        "roadmap_criterion_sha256": crit_sha,
        "rule_id": rule_id,
        "failure_class": fail_class,
        "target_nodeid": nodeid,
        "result_code": res_code,
        "assertion_id": assertion_id,
    }
    if actual != expected:
        raise AssertionError(f"mutation observable mismatch for {param_id}: {actual!r}")


def validate_mutation_manifest_structure(manifest_data: dict[str, Any] | str | Path, repo_root: Path | None = None) -> dict[str, Any]:
    """Validates structural properties of a mutation manifest.

    Proves:
    - 8 criteria and 9 unique parameters
    - Exact raw criterion-byte digests
    - Map/manifest equality
    - Unique anchors within each target file (count == 1)
    - Valid argv (shell-free, starts with env/python3)
    - Exact one-node selection
    - Real non-identical replacements
    - Syntactically viable complete mutated Python source for all 9 target modules
    """
    if isinstance(manifest_data, (str, Path)):
        p = Path(manifest_data)
        content = p.read_text(encoding="utf-8")
        manifest = json.loads(content)
    else:
        manifest = manifest_data

    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    roadmap_file = repo_root / "specs/phase-plans-v10.md"
    recomputed_digests: dict[str, str] = {}
    if roadmap_file.exists():
        import hashlib, re
        roadmap_content = roadmap_file.read_text(encoding="utf-8")
        items: dict[str, list[str]] = {}
        current_id: str | None = None
        for line in roadmap_content.splitlines(keepends=True):
            m = re.match(r"^- \[[ xX]\]\s*(EC-PROOFGATE-[0-7])\b", line)
            if m:
                current_id = m.group(1)
                if current_id in items:
                    raise ValueError(f"Duplicate criterion in roadmap: {current_id}")
                items[current_id] = [line]
            elif current_id is not None:
                if re.match(r"^- \[[ xX]\]", line) or line.startswith("#") or line.startswith("**") or not line.strip():
                    current_id = None
                else:
                    items[current_id].append(line)

        expected_ids = {f"EC-PROOFGATE-{i}" for i in range(8)}
        if set(items.keys()) != expected_ids:
            raise ValueError(f"Roadmap criteria set mismatch: expected {expected_ids}, got {set(items.keys())}")

        for crit_id, crit_lines in items.items():
            raw_text = "".join(crit_lines)
            recomputed_digests[crit_id] = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    declarations = manifest.get("declarations", [])
    criteria_seen = set()
    parameters_seen = set()
    anchors_by_target: dict[str, set[str]] = {}

    for decl in declarations:
        crit_id = decl["criterion_id"]
        criteria_seen.add(crit_id)
        for param in decl["parameters"]:
            pid = param["parameter_id"]
            if pid in parameters_seen:
                raise ValueError(f"Duplicate parameter_id: {pid}")
            parameters_seen.add(pid)

            if pid not in MUTATION_RULES_BY_PARAMETER:
                raise ValueError(f"Parameter {pid} not in MUTATION_RULES_BY_PARAMETER")

            expected_rule = MUTATION_RULES_BY_PARAMETER[pid]
            exp_obs = param["expected_observable"]
            if exp_obs["roadmap_criterion_id"] != expected_rule[0]:
                raise ValueError(f"Criterion mismatch for {pid}")
            if exp_obs["roadmap_criterion_sha256"] != expected_rule[1]:
                raise ValueError(f"Criterion SHA mismatch for {pid}")
            if crit_id in recomputed_digests and exp_obs["roadmap_criterion_sha256"] != recomputed_digests[crit_id]:
                raise ValueError(f"Criterion SHA mismatch against recomputed roadmap for {pid}")
            if crit_id in recomputed_digests and expected_rule[1] != recomputed_digests[crit_id]:
                raise ValueError(f"Constant map SHA mismatch against recomputed roadmap for {pid}")
            if exp_obs["rule_id"] != expected_rule[2]:
                raise ValueError(f"Rule ID mismatch for {pid}")
            if param["expected_failure_class"] != expected_rule[3]:
                raise ValueError(f"Failure class mismatch for {pid}")
            if param["target_nodeid"] != expected_rule[4]:
                raise ValueError(f"Target nodeid mismatch for {pid}")
            if exp_obs["result_code"] != expected_rule[5]:
                raise ValueError(f"Result code mismatch for {pid}")

            target_path = param["target_path"]
            anchor = param["injection_anchor"]
            if target_path not in anchors_by_target:
                anchors_by_target[target_path] = set()
            if anchor in anchors_by_target[target_path]:
                raise ValueError(f"Duplicate injection anchor '{anchor}' in target '{target_path}'")
            anchors_by_target[target_path].add(anchor)

            cmd = param["proof_command"]
            if not isinstance(cmd, list) or not cmd:
                raise ValueError(f"Invalid proof_command for {pid}: {cmd}")
            if cmd[0] not in ("python3", "env") and not cmd[0].endswith("python3"):
                raise ValueError(f"Invalid shell-free argv proof_command for {pid}: {cmd}")
            if "-o" not in cmd or "junit_family=legacy" not in cmd:
                raise ValueError(f"proof_command for {pid} missing '-o junit_family=legacy'")

            junit_args = [arg for arg in cmd if arg.startswith("--junitxml=") or arg == "--junitxml"]
            if len(junit_args) != 1:
                raise ValueError(f"proof_command for {pid} must contain '--junitxml' exactly once")
            junit_val = next(arg for arg in cmd if arg.startswith("--junitxml="))
            if "$PHASE_LOOP_RUN_DIR" not in junit_val and "{PHASE_LOOP_RUN_DIR}" not in junit_val:
                raise ValueError(f"proof_command for {pid} --junitxml must target $PHASE_LOOP_RUN_DIR placeholder")

            if cmd.count(param["target_nodeid"]) != 1 and not any(param["target_nodeid"] in arg for arg in cmd):
                raise ValueError(f"proof_command for {pid} does not select target nodeid exactly once")

            repl = param["replacement_bytes"]
            if repl == anchor or repl.startswith("# MUTATED_ANCHOR"):
                raise ValueError(f"Parameter {pid} replacement is a no-op comment or identical")

            target_file_path = repo_root / target_path
            if target_file_path.exists():
                target_src = target_file_path.read_text(encoding="utf-8")
                anchor_cnt = target_src.count(anchor)
                if anchor_cnt != 1:
                    raise ValueError(f"Anchor for {pid} must occur exactly once in {target_path}, found {anchor_cnt}")
                mutated_src = target_src.replace(anchor, repl, 1)
                try:
                    ast.parse(mutated_src)
                except SyntaxError as exc:
                    raise ValueError(f"Mutated module for {pid} ({target_path}) fails Python AST parse: {exc}") from exc

    if len(criteria_seen) != 8:
        raise ValueError(f"Expected 8 criteria, got {len(criteria_seen)}")
    if len(parameters_seen) != 9:
        raise ValueError(f"Expected 9 parameters, got {len(parameters_seen)}")

    return {
        "status": "valid",
        "is_valid": True,
        "criteria_count": len(criteria_seen),
        "parameters_count": len(parameters_seen),
        "criteria": sorted(list(criteria_seen)),
        "parameters": sorted(list(parameters_seen)),
        "recomputed_digests": recomputed_digests,
    }

def _recover_runs_from_text(text: str) -> list[dict[str, Any]]:
    """Recovers complete run objects from truncated or malformed JSON text."""
    runs: list[dict[str, Any]] = []
    if not text:
        return runs
    import re
    pos = 0
    decoder = json.JSONDecoder()
    while pos < len(text):
        match = re.search(r'\{\s*"(?:exitstatus|reports|run_identity)"', text[pos:])
        if not match:
            break
        start = pos + match.start()
        try:
            obj, end = decoder.raw_decode(text[start:])
            if isinstance(obj, dict) and "run_identity" in obj and "reports" in obj:
                if not any(r.get("run_identity") == obj.get("run_identity") and r.get("reports") == obj.get("reports") for r in runs):
                    runs.append(obj)
            pos = start + max(end, 1)
        except Exception:
            pos = start + 1
    return runs


class ProofgateReportingPlugin:
    """Explicitly registered pytest plugin contract for PROOFGATE test phase reporting.

    Persists typed collection, setup, call, teardown phase reports and direct properties
    to a production-consumable artifact.
    """

    def __init__(self, output_path: Path | None = None) -> None:
        self.output_path = output_path
        self.phase_reports: list[dict[str, Any]] = []

    def record_phase_report(self, item: Any, call: Any | None = None, when: str = "unknown") -> dict[str, Any]:
        import hashlib, sys
        nodeid = normalize_nodeid(getattr(item, "nodeid", getattr(call, "nodeid", "")))
        phase = when if call is None else getattr(call, "when", when)
        exc_type = None
        outcome = "passed"

        if getattr(call, "skipped", False) or getattr(call, "outcome", None) == "skipped" or getattr(item, "skipped", False):
            outcome = "skipped"
            exc_type = "Skipped"
        elif getattr(call, "outcome", None) == "failed" or getattr(call, "failed", False) or getattr(item, "failed", False):
            outcome = "failed"
            if call is not None and getattr(call, "excinfo", None) is not None:
                exc_type = call.excinfo.typename
            elif call is not None and hasattr(call, "longrepr"):
                longrepr = str(getattr(call, "longrepr", ""))
                if "AssertionError" in longrepr:
                    exc_type = "AssertionError"
                elif "ProofgateBootstrapVerifierError" in longrepr:
                    exc_type = "ProofgateBootstrapVerifierError"
                else:
                    exc_type = "AssertionError"
            else:
                exc_type = "AssertionError"
        else:
            outcome = "passed"

        props = {}
        user_properties = getattr(item, "user_properties", [])
        for k, v in user_properties:
            props[k] = v

        candidate = os.environ.get("PHASE_LOOP_CANDIDATE_OID", "unknown")
        argv_list = list(sys.argv)
        cmd_digest = hashlib.sha256(json.dumps(argv_list).encode("utf-8")).hexdigest()
        run_identity = os.environ.get("PHASE_LOOP_RUN_ID", os.environ.get("PHASE_LOOP_RUN_DIR", "default"))
        parameter = os.environ.get("PROOFGATE_MUTATION_PARAMETER", props.get("proofgate_mutation_parameter", "none"))
        criterion = MUTATION_RULES_BY_PARAMETER[parameter][0] if parameter in MUTATION_RULES_BY_PARAMETER else props.get("proofgate_criterion", "none")

        record = {
            "nodeid": nodeid,
            "phase": phase,
            "outcome": outcome,
            "exception_type": exc_type,
            "candidate": candidate,
            "argv": argv_list,
            "command_digest": cmd_digest,
            "run_identity": run_identity,
            "parameter": parameter,
            "criterion": criterion,
            "properties": props,
        }
        self.phase_reports.append(record)
        return record

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_runtest_makereport(self, item: Any, call: Any):
        outcome = yield
        report = outcome.get_result()
        norm_id = normalize_nodeid(getattr(item, "nodeid", getattr(report, "nodeid", "")))
        if norm_id in EXPECTED_PHASE_NODEIDS:
            if (report.when == "setup" and report.outcome in ("skipped", "failed")) or report.when == "call":
                if not any(r.get("nodeid") == norm_id for r in self.phase_reports):
                    info = self.record_phase_report(item, report, when="call")
                    report.proofgate_phase_info = info

    def pytest_collectreport(self, report: Any):
        if getattr(report, "failed", False):
            norm_id = normalize_nodeid(getattr(report, "nodeid", ""))
            self.phase_reports.append({
                "nodeid": norm_id,
                "phase": "collection",
                "outcome": "failed",
                "exception_type": "CollectionError",
                "properties": {},
            })

    def pytest_sessionfinish(self, session: Any, exitstatus: int):
        run_dir = os.environ.get("PHASE_LOOP_RUN_DIR")
        target_path = self.output_path
        coordinator_capture: tuple[Path, str, str] | None = None
        if target_path is None and run_dir:
            resolved_run_dir = Path(run_dir).resolve()
            coordinator_capture = _coordinator_capture_target(resolved_run_dir)
            target_path = coordinator_capture[0] if coordinator_capture else resolved_run_dir / "proofgate_phase_reports.json"
        if target_path:
            target_path = Path(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = target_path.with_suffix(".lock")
            jsonl_path = target_path.with_suffix(".jsonl")
            import fcntl
            with open(lock_path, "a+", encoding="utf-8") as lock_f:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
                try:
                    existing_runs: list[dict[str, Any]] = []
                    existing_reports: list[dict[str, Any]] = []
                    content = ""
                    if target_path.exists():
                        try:
                            content = target_path.read_text(encoding="utf-8").strip()
                        except Exception:
                            content = ""

                    if content:
                        try:
                            existing_data = json.loads(content)
                            if isinstance(existing_data, dict):
                                existing_runs = existing_data.get("runs", [])
                                existing_reports = existing_data.get("reports", [])
                        except Exception:
                            existing_runs = _recover_runs_from_text(content)
                            for r in existing_runs:
                                if isinstance(r.get("reports"), list):
                                    existing_reports.extend(r["reports"])

                    # Also inspect append-only jsonl log for prior runs
                    if jsonl_path.exists():
                        try:
                            with open(jsonl_path, "r", encoding="utf-8") as jf:
                                for line in jf:
                                    line_str = line.strip()
                                    if line_str:
                                        try:
                                            j_run = json.loads(line_str)
                                            if isinstance(j_run, dict) and "run_identity" in j_run and "reports" in j_run:
                                                if not any(r.get("run_identity") == j_run.get("run_identity") and r.get("reports") == j_run.get("reports") for r in existing_runs):
                                                    existing_runs.append(j_run)
                                                    if isinstance(j_run.get("reports"), list):
                                                        existing_reports.extend(j_run["reports"])
                                        except Exception:
                                            pass
                        except Exception:
                            pass

                    run_identity = os.environ.get("PHASE_LOOP_RUN_ID", os.environ.get("PHASE_LOOP_RUN_DIR", "default"))
                    new_run = {
                        "run_identity": run_identity,
                        "exitstatus": exitstatus,
                        "reports": self.phase_reports,
                    }

                    # Append to jsonl log immediately
                    try:
                        with open(jsonl_path, "a", encoding="utf-8") as jf:
                            jf.write(json.dumps(new_run) + "\n")
                            jf.flush()
                            os.fsync(jf.fileno())
                    except Exception:
                        pass

                    merged_runs = existing_runs + [new_run]
                    merged_reports = existing_reports + self.phase_reports

                    all_statuses = [r.get("exitstatus", 0) for r in merged_runs if isinstance(r, dict)]
                    eff_exitstatus = exitstatus if exitstatus != 0 else next((s for s in reversed(all_statuses) if s != 0), 0)

                    payload = {
                        "schema": "proofgate_phase_reports.v1",
                        "exitstatus": eff_exitstatus,
                        "runs": merged_runs,
                        "reports": merged_reports,
                    }
                    if coordinator_capture is not None:
                        _phase_reports_path, junit_filename, _mode = coordinator_capture
                        junit_path = Path(run_dir).resolve() / junit_filename
                        try:
                            junit_bytes = junit_path.read_bytes()
                        except OSError:
                            junit_bytes = b""
                        payload["capture"] = {
                            "schema": "proofgate_coordinator_evidence_capture.v1",
                            "plugin": "tests.proofgate_tdd_guard",
                            "junit_family": "legacy",
                            "junit_filename": junit_filename,
                            "junit_sha256": hashlib.sha256(junit_bytes).hexdigest(),
                            "pytest_args_sha256": hashlib.sha256(json.dumps(sys.argv[1:]).encode("utf-8")).hexdigest(),
                        }
                        if _ATTENDED_RUNNER_ENVELOPE is not None:
                            payload["runner_envelope"] = _ATTENDED_RUNNER_ENVELOPE

                    # Atomic write to target_path via temporary file
                    tmp_path = target_path.with_suffix(".tmp")
                    with open(tmp_path, "w", encoding="utf-8") as tmp_f:
                        tmp_f.write(json.dumps(payload, indent=2, sort_keys=True))
                        tmp_f.flush()
                        os.fsync(tmp_f.fileno())
                    os.replace(tmp_path, target_path)
                finally:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


_GLOBAL_REPORTING_PLUGIN = ProofgateReportingPlugin()


def record_proofgate_test_phase_report(item: Any, call: Any) -> dict[str, Any]:
    """Test-owned typed pytest report hook."""
    return _GLOBAL_REPORTING_PLUGIN.record_phase_report(item, call)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: Any, call: Any):
    """Pytest reporting hook capturing phase reports for proofgate nodeids."""
    outcome = yield
    report = outcome.get_result()
    norm_id = normalize_nodeid(getattr(item, "nodeid", getattr(report, "nodeid", "")))
    if norm_id in EXPECTED_PHASE_NODEIDS:
        if (report.when == "setup" and report.outcome in ("skipped", "failed")) or report.when == "call":
            if not any(r.get("nodeid") == norm_id for r in _GLOBAL_REPORTING_PLUGIN.phase_reports):
                info = _GLOBAL_REPORTING_PLUGIN.record_phase_report(item, report, when="call")
                report.proofgate_phase_info = info


def pytest_collectreport(report: Any):
    """Pytest collection reporting hook."""
    return _GLOBAL_REPORTING_PLUGIN.pytest_collectreport(report)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: Any, exitstatus: int):
    """Pytest session finish hook."""
    return _GLOBAL_REPORTING_PLUGIN.pytest_sessionfinish(session, exitstatus)


PROOFGATE_OBSERVATION_SCHEMA = "proofgate_external_observation.v1"

# A locator/request may never carry evidence bytes, a status, a decisive flag, or an
# authority mapping. A sealed observation may never carry a verdict of its own: authority
# comes only from comparing the observation to an independently supplied expected config.
FORBIDDEN_LOCATOR_FIELD_TOKENS: tuple[str, ...] = (
    "status",
    "decisive",
    "evidence",
    "authoriz",
    "verdict",
    "receipt",
    "bundle",
    "attestation",
    "proof",
    "signer",
    "bytes",
    "digest",
    "sha256",
    "claim",
    "token",
    "credential",
    "secret",
)
FORBIDDEN_OBSERVATION_AUTHORITY_FIELDS: tuple[str, ...] = (
    "status",
    "decisive",
    "evidence_kind",
    "authorized",
    "verdict",
    "blocker_class",
    "human_required",
)


@dataclasses.dataclass(frozen=True, slots=True)
class ProofgateExpectedConfig:
    """Immutable expected configuration, supplied to a verifier independently of observations.

    This object is the sole authority for what PROOFGATE expects. It is never derived from an
    observation, an observation provider, or any verifier-owned constant, and it cannot be
    mutated in place: substituting or editing an observation provider cannot move expectations.
    """

    repository_id: str
    repository_owner_id: str
    repository_name: str
    dedicated_app_integration_id: str
    dedicated_app_installation_id: str
    app_repository_selection: str
    app_permissions: tuple[tuple[str, str], ...]
    required_reviewer_id: str
    ruleset_name: str
    ruleset_required_rule_types: tuple[str, ...]
    broker_deployment_id: str
    broker_key_version: str
    broker_claim_policy_digest: str
    oidc_audience: str
    workflow_ref: str
    workflow_path: str
    workflow_sha256: str
    event_name: str
    runner_environment: str
    environment_name: str
    external_head_ref: str
    accepted_refs: tuple[str, ...]
    actor: str
    subject: str
    run_id: str
    run_attempt: str
    expected_nodeid_count: int
    forced_red_passed: int
    forced_red_failed: int
    required_panel_seats: tuple[str, ...]


PROOFGATE_EXPECTED_CONFIG_V1 = ProofgateExpectedConfig(
    repository_id="1280382652",
    repository_owner_id="159201120",
    repository_name="Consiliency/agent-harness",
    dedicated_app_integration_id="1159201",
    dedicated_app_installation_id="6159201",
    app_repository_selection="selected",
    app_permissions=(("contents", "write"),),
    required_reviewer_id="7159201",
    ruleset_name="proofgate-receipt-head-v1",
    ruleset_required_rule_types=(
        "creation",
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "update",
    ),
    broker_deployment_id="proofgate-broker-v1",
    broker_key_version="v1",
    broker_claim_policy_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    oidc_audience="urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
    workflow_ref="Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
    workflow_path=".github/workflows/proofgate-receipt-attestation.yml",
    workflow_sha256="3c365db032ad94622149fde1cadcb84b45480d65d8d789387ef47de286b59c44",
    event_name="workflow_dispatch",
    runner_environment="github-hosted",
    environment_name="proofgate-receipt-head-v1",
    external_head_ref="refs/heads/proofgate-receipt-head-v1",
    accepted_refs=("refs/heads/main", "refs/heads/proofgate-receipt-head-v1"),
    actor="proofgate-app[bot]",
    subject="cores/00000000000000000001-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.json",
    run_id="1000000001",
    run_attempt="1",
    expected_nodeid_count=39,
    forced_red_passed=2,
    forced_red_failed=37,
    required_panel_seats=("fable", "gemini", "gpt-5.6-sol", "grok"),
)

# Versioned authority source for the configuration accepted by the bootstrap verifier.
# This is deliberately a checked-in canonical digest, not a digest supplied by its caller.
PROOFGATE_EXPECTED_CONFIG_V1_CANONICAL_SHA256 = "99afbca46a55ebd992bb0c98b9309729e92f08f1f86fa277e8e7fb1a19ba87af"


def canonical_expected_config_digest(expected: ProofgateExpectedConfig) -> str:
    """Returns the deterministic digest of an exact expected-configuration instance."""
    if type(expected) is not ProofgateExpectedConfig:
        raise TypeError("canonical_expected_config_digest requires an exact ProofgateExpectedConfig")
    payload = json.dumps(dataclasses.asdict(expected), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class ProofgateObservationRequest:
    """Immutable locator/request handed to the external observation boundary.

    It names *what to observe* and nothing else: no evidence bytes, no status, no decisive
    flag, no authority mapping, no digests and no identities.
    """

    repository: str
    ref: str
    environment: str
    external_head_ref: str
    candidate_oid: str = ""
    plan_path: str = ""
    sequence: int = 0

    def __post_init__(self) -> None:
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise TypeError(f"Locator field '{f.name}' must be a plain str or int, got {type(value).__name__}")


@dataclasses.dataclass(frozen=True, slots=True)
class ProofgateExternalObservation:
    """Sealed, read-only observation returned by the external observation boundary.

    It records only what the boundary observed. It carries no status, no decisive flag and no
    evidence kind: a verifier's authority derives solely from comparing these observed values
    to an independently supplied `ProofgateExpectedConfig`.
    """

    schema: str
    repository_id: str
    repository_owner_id: str
    repository_name: str
    app_integration_id: str
    app_installation_id: str
    app_repository_selection: str
    app_permissions: tuple[tuple[str, str], ...]
    ruleset_name: str
    ruleset_rule_types: tuple[str, ...]
    ruleset_ref_includes: tuple[str, ...]
    ruleset_bypass_actors: tuple[tuple[str, str, str], ...]
    environment_name: str
    environment_can_admins_bypass: bool
    environment_prevent_self_review: bool
    environment_required_reviewer_ids: tuple[str, ...]
    oidc_claims: tuple[tuple[str, str], ...]
    broker_deployment_id: str
    broker_key_version: str
    broker_claim_policy_digest: str
    external_head_ref: str
    external_head_oid: str
    candidate_oid: str
    plan_sha256: str
    workflow_ref: str
    workflow_path: str
    workflow_sha256: str
    runner_environment: str
    event_name: str
    actor: str
    subject: str
    run_id: str
    run_attempt: str
    core_sha256: str
    bundle_sha256: str
    append_sha256: str
    sequence: int
    panel_seat_verdicts: tuple[tuple[str, str, str], ...]
    red_lifecycle_passed: int
    red_lifecycle_failed: int
    red_lifecycle_nodeids: int


@runtime_checkable
class ProofgateObservationBoundary(Protocol):
    """Read-only external observation boundary.

    `observe` is the entire surface: the boundary accepts a locator/request and returns the
    sealed observation. It exposes no writer, no mutator and no authority-bearing method.
    """

    def observe(self, request: ProofgateObservationRequest) -> ProofgateExternalObservation:
        ...


PROOFGATE_OBSERVATION_BOUNDARY_METHODS: tuple[str, ...] = ("observe",)


class ProofgateObservationUnavailable(RuntimeError):
    """Raised by an observation boundary that cannot produce an observation."""


class RecordingObservationBoundary:
    """Deterministic recording fake boundary used by positive tests.

    It returns a pre-sealed observation, records the exact call trace, and refuses anything
    that is not a `ProofgateObservationRequest` locator.
    """

    def __init__(self, observation: ProofgateExternalObservation) -> None:
        if not isinstance(observation, ProofgateExternalObservation):
            raise TypeError("RecordingObservationBoundary requires a sealed ProofgateExternalObservation")
        self._observation = observation
        self._calls: list[ProofgateObservationRequest] = []

    @property
    def calls(self) -> tuple[ProofgateObservationRequest, ...]:
        return tuple(self._calls)

    def observe(self, request: ProofgateObservationRequest) -> ProofgateExternalObservation:
        if not isinstance(request, ProofgateObservationRequest):
            raise TypeError("Observation boundary accepts only a ProofgateObservationRequest locator")
        self._calls.append(request)
        return self._observation


class UnavailableObservationBoundary:
    """Boundary that cannot observe; verifiers must fail closed rather than authorize."""

    def __init__(self) -> None:
        self._calls: list[ProofgateObservationRequest] = []

    @property
    def calls(self) -> tuple[ProofgateObservationRequest, ...]:
        return tuple(self._calls)

    def observe(self, request: ProofgateObservationRequest) -> ProofgateExternalObservation:
        if not isinstance(request, ProofgateObservationRequest):
            raise TypeError("Observation boundary accepts only a ProofgateObservationRequest locator")
        self._calls.append(request)
        raise ProofgateObservationUnavailable("external observation boundary unavailable")


def observation_digest(observation: ProofgateExternalObservation) -> str:
    """Canonical SHA-256 over the sealed observation's frozen bytes."""
    if not isinstance(observation, ProofgateExternalObservation):
        raise TypeError("observation_digest requires a sealed ProofgateExternalObservation")
    payload = json.dumps(dataclasses.asdict(observation), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def subject_sequence_and_core_digest(expected: ProofgateExpectedConfig) -> tuple[int, str]:
    """Parses the exact `cores/<20-digit-sequence>-<core_sha256>.json` subject bound by `expected`."""
    name = expected.subject.split("/")[-1]
    if not expected.subject.startswith("cores/") or not name.endswith(".json"):
        raise ValueError(f"Expected subject is not a cores/<sequence>-<core_sha256>.json name: {expected.subject}")
    stem = name[: -len(".json")]
    seq_str, _, core_sha256 = stem.partition("-")
    if len(seq_str) != 20 or not seq_str.isdigit() or len(core_sha256) != 64:
        raise ValueError(f"Expected subject has a malformed sequence/core digest: {expected.subject}")
    return int(seq_str), core_sha256


def expected_bundle_digest(core_sha256: str, workflow_sha256: str) -> str:
    """Derived attestation bundle digest, bound to the core digest and the attested workflow blob."""
    return hashlib.sha256((core_sha256 + workflow_sha256).encode("utf-8")).hexdigest()


def expected_append_digest(sequence: int, core_sha256: str, bundle_sha256: str) -> str:
    """Derived external-head append digest over the canonical append record."""
    record = {
        "schema": "proofgate_external_head_append.v1",
        "sequence": sequence,
        "core_sha256": core_sha256,
        "bundle_sha256": bundle_sha256,
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def conforming_observation(
    expected: ProofgateExpectedConfig,
    *,
    external_head_oid: str,
    candidate_oid: str,
    plan_sha256: str,
) -> ProofgateExternalObservation:
    """Builds the sealed observation an honest boundary would return for `expected`.

    Every identity is projected from the independently supplied expected configuration, so a
    test never types an identity, a claim or a permission of its own.
    """
    if not isinstance(expected, ProofgateExpectedConfig):
        raise TypeError("conforming_observation requires an immutable ProofgateExpectedConfig")
    sequence, core_sha256 = subject_sequence_and_core_digest(expected)
    bundle_sha256 = expected_bundle_digest(core_sha256, expected.workflow_sha256)
    append_sha256 = expected_append_digest(sequence, core_sha256, bundle_sha256)
    oidc_claims = (
        ("actor", expected.actor),
        ("aud", expected.oidc_audience),
        ("broker_claim_policy_digest", expected.broker_claim_policy_digest),
        ("broker_deployment_id", expected.broker_deployment_id),
        ("broker_key_version", expected.broker_key_version),
        ("environment", expected.environment_name),
        ("event_name", expected.event_name),
        ("ref", expected.accepted_refs[0]),
        ("repository", expected.repository_name),
        ("repository_id", expected.repository_id),
        ("repository_owner_id", expected.repository_owner_id),
        ("run_attempt", expected.run_attempt),
        ("run_id", expected.run_id),
        ("runner_environment", expected.runner_environment),
        ("subject", expected.subject),
        ("workflow_path", expected.workflow_path),
        ("workflow_ref", expected.workflow_ref),
        ("workflow_sha", expected.workflow_sha256),
    )
    return ProofgateExternalObservation(
        schema=PROOFGATE_OBSERVATION_SCHEMA,
        repository_id=expected.repository_id,
        repository_owner_id=expected.repository_owner_id,
        repository_name=expected.repository_name,
        app_integration_id=expected.dedicated_app_integration_id,
        app_installation_id=expected.dedicated_app_installation_id,
        app_repository_selection=expected.app_repository_selection,
        app_permissions=expected.app_permissions,
        ruleset_name=expected.ruleset_name,
        ruleset_rule_types=expected.ruleset_required_rule_types,
        ruleset_ref_includes=(expected.external_head_ref,),
        ruleset_bypass_actors=(("Integration", "always", expected.dedicated_app_integration_id),),
        environment_name=expected.environment_name,
        environment_can_admins_bypass=False,
        environment_prevent_self_review=True,
        environment_required_reviewer_ids=(expected.required_reviewer_id,),
        oidc_claims=oidc_claims,
        broker_deployment_id=expected.broker_deployment_id,
        broker_key_version=expected.broker_key_version,
        broker_claim_policy_digest=expected.broker_claim_policy_digest,
        external_head_ref=expected.external_head_ref,
        external_head_oid=external_head_oid,
        candidate_oid=candidate_oid,
        plan_sha256=plan_sha256,
        workflow_ref=expected.workflow_ref,
        workflow_path=expected.workflow_path,
        workflow_sha256=expected.workflow_sha256,
        runner_environment=expected.runner_environment,
        event_name=expected.event_name,
        actor=expected.actor,
        subject=expected.subject,
        run_id=expected.run_id,
        run_attempt=expected.run_attempt,
        core_sha256=core_sha256,
        bundle_sha256=bundle_sha256,
        append_sha256=append_sha256,
        sequence=sequence,
        panel_seat_verdicts=tuple(
            (seat, "AGREE", f"run-{seat}-1") for seat in expected.required_panel_seats
        ),
        red_lifecycle_passed=expected.forced_red_passed,
        red_lifecycle_failed=expected.forced_red_failed,
        red_lifecycle_nodeids=expected.expected_nodeid_count,
    )


def assert_frozen_authority_contract() -> None:
    """Direct control: the typed authority contracts are frozen and authority-free.

    Proves the expected configuration cannot be mutated in place, the locator carries no
    evidence/status/decisive/authority field, the sealed observation carries no verdict of its
    own, and the observation boundary's whole surface is a read-only `observe(request)`.
    """
    assert dataclasses.is_dataclass(ProofgateExpectedConfig), "expected configuration must be a dataclass"
    assert ProofgateExpectedConfig.__dataclass_params__.frozen, "expected configuration must be frozen"
    assert isinstance(PROOFGATE_EXPECTED_CONFIG_V1, ProofgateExpectedConfig)
    for attr, value in (
        ("repository_id", "42"),
        ("repository_owner_id", "42"),
        ("required_reviewer_id", "43"),
    ):
        try:
            setattr(PROOFGATE_EXPECTED_CONFIG_V1, attr, value)
        except (dataclasses.FrozenInstanceError, AttributeError):
            pass
        else:
            raise AssertionError(f"Expected configuration field '{attr}' is mutable in place")
        assert getattr(PROOFGATE_EXPECTED_CONFIG_V1, attr) != value, f"Expected configuration '{attr}' drifted"

    assert dataclasses.is_dataclass(ProofgateObservationRequest)
    assert ProofgateObservationRequest.__dataclass_params__.frozen, "locator must be frozen"
    locator_fields = tuple(f.name for f in dataclasses.fields(ProofgateObservationRequest))
    assert locator_fields == (
        "repository",
        "ref",
        "environment",
        "external_head_ref",
        "candidate_oid",
        "plan_path",
        "sequence",
    ), f"Locator field set drifted: {locator_fields}"
    for name in locator_fields:
        for token in FORBIDDEN_LOCATOR_FIELD_TOKENS:
            assert token not in name, f"Locator field '{name}' carries forbidden authority token '{token}'"

    assert dataclasses.is_dataclass(ProofgateExternalObservation)
    assert ProofgateExternalObservation.__dataclass_params__.frozen, "sealed observation must be frozen"
    observation_fields = {f.name for f in dataclasses.fields(ProofgateExternalObservation)}
    for name in FORBIDDEN_OBSERVATION_AUTHORITY_FIELDS:
        assert name not in observation_fields, f"Sealed observation carries its own authority field '{name}'"

    boundary_methods = tuple(
        sorted(n for n in vars(ProofgateObservationBoundary) if not n.startswith("_"))
    )
    assert boundary_methods == PROOFGATE_OBSERVATION_BOUNDARY_METHODS, (
        f"Observation boundary surface drifted: {boundary_methods}"
    )

    probe_request = ProofgateObservationRequest(
        repository=PROOFGATE_EXPECTED_CONFIG_V1.repository_name,
        ref=PROOFGATE_EXPECTED_CONFIG_V1.accepted_refs[0],
        environment=PROOFGATE_EXPECTED_CONFIG_V1.environment_name,
        external_head_ref=PROOFGATE_EXPECTED_CONFIG_V1.external_head_ref,
    )
    probe_observation = conforming_observation(
        PROOFGATE_EXPECTED_CONFIG_V1,
        external_head_oid="a" * 40,
        candidate_oid="a" * 40,
        plan_sha256="b" * 64,
    )
    boundary = RecordingObservationBoundary(probe_observation)
    assert boundary.calls == ()
    assert boundary.observe(probe_request) is probe_observation
    assert boundary.calls == (probe_request,), "Recording boundary must record the exact call trace"
    try:
        boundary.observe({"external_head_oid": "a" * 40})
    except TypeError:
        pass
    else:
        raise AssertionError("Observation boundary accepted a caller-authored mapping instead of a locator")
    assert boundary.calls == (probe_request,), "Refused call must not enter the call trace"
    assert observation_digest(probe_observation) == observation_digest(probe_observation)
