"""Frozen SL-0 canonical-corpus test support.

This module deliberately reads only the test-owned immutable fixture.  It never
provides a production parser, schema dispatcher, or redaction implementation.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
from unittest import mock
from urllib import request as urllib_request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pytest

CAPABILITY_MARKER = "spec@v0.2.1:b862f977897a7b87c4419680a3e83735d4ff07b0"
TDD_ENV = "PHASE_LOOP_TDD_EXPECT_CONFORM"
RUNNER_B2_EVIDENCE_ENV = "PHASE_LOOP_CONFORM_B2_EVIDENCE"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "phase-loop-runtime"
FIXTURE_ROOT = RUNTIME_ROOT / "tests" / "fixtures" / "outside_agent_contract_v0_2_1"
PROVENANCE_PATH = FIXTURE_ROOT / "PROVENANCE.json"
MANIFEST_PATH = FIXTURE_ROOT / "test-vectors" / "outside-agent" / "manifest.json"
PRODUCTION_SCAN_ROOT = REPO_ROOT / "phase-loop-runtime" / "src" / "phase_loop_runtime"
PRODUCTION_SCAN_ROOT_LITERAL = "phase-loop-runtime/src/phase_loop_runtime"
PRODUCER_TAG = "v0.2.1"
PRODUCER_COMMIT = "b862f977897a7b87c4419680a3e83735d4ff07b0"


def _normalize_sdist_gzip(path: Path, *, source_date_epoch: str) -> None:
    """Canonicalize sdist tar metadata and its gzip timestamp."""
    epoch = int(source_date_epoch)
    members: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(path, mode="r:gz") as source:
        for original in source.getmembers():
            member = copy.copy(original)
            extracted = source.extractfile(original) if original.isfile() else None
            members.append((member, extracted.read() if extracted is not None else None))

    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:", format=tarfile.PAX_FORMAT) as archive:
        for member, contents in members:
            member.mtime = epoch
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.pax_headers = {}
            archive.addfile(
                member,
                io.BytesIO(contents) if contents is not None else None,
            )

    with path.open("wb") as destination:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=destination,
            mtime=epoch,
        ) as archive:
            archive.write(payload.getvalue())

# This is deliberately not generated from PROVENANCE.json.  The fixture is a
# consumer copy and its provenance file is itself mutable test data; the literal
# producer records below are the immutable Consiliency/spec@v0.2.1 authority.
IMMUTABLE_SPEC_V0_2_1_FILES = (
    ("consiliency_spec/outside_agent_router.py", "consiliency_spec/outside_agent_router.py", "595cad861db098a71d05cd545c10de086ffeb7ec2d7fa4f5e1891a4eff3cb723"),
    ("schemas/outside-agent-route-verdict.schema.json", "schemas/outside-agent-route-verdict.schema.json", "86169277d3a0823db1a6c9fa4d20a838b0bc2820818ad00ebd53dcdd03c2b1c2"),
    ("schemas/outside-agent-submission.schema.json", "schemas/outside-agent-submission.schema.json", "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a"),
    ("test-vectors/outside-agent/invalid-empty-evidence-refs.json", "test-vectors/outside-agent/invalid-empty-evidence-refs.json", "0dbdf1593bc5909900adb64967bd22a88d230265a251fde991e11317118a48f9"),
    ("test-vectors/outside-agent/invalid-git-object-id-length.json", "test-vectors/outside-agent/invalid-git-object-id-length.json", "2f1013e724338b13f56c6136ce999924dbeb9be13f062ec1410b720a1ea8f7da"),
    ("test-vectors/outside-agent/invalid-missing-digest.json", "test-vectors/outside-agent/invalid-missing-digest.json", "335320352509d84a0785f37b6120d7e3ee0305167efad5ec502e9cbb168f72ee"),
    ("test-vectors/outside-agent/invalid-path-traversal.json", "test-vectors/outside-agent/invalid-path-traversal.json", "2a25669e4b2325f001ef45b61647132ec38d5352920936c63164021dec06f48d"),
    ("test-vectors/outside-agent/invalid-raw-payload.json", "test-vectors/outside-agent/invalid-raw-payload.json", "67c6d26205f0c5aa7200412cf39e65b7db22ce47848f72df4f36ce0acb5cc5fd"),
    ("test-vectors/outside-agent/invalid-source-bundle-mismatch.json", "test-vectors/outside-agent/invalid-source-bundle-mismatch.json", "5dde952f113fe262d6b73f362dd27843d432796493ede826939a79df017c696b"),
    ("test-vectors/outside-agent/invalid-unknown-producer-identity-posture.json", "test-vectors/outside-agent/invalid-unknown-producer-identity-posture.json", "7c96378cb8491fbc8556be109a1282d0ffd938ec50f262b3bf8aaf77fda567a1"),
    ("test-vectors/outside-agent/invalid-unsupported-verdict.json", "test-vectors/outside-agent/invalid-unsupported-verdict.json", "defc93516237989035ce809546727625ded0d1da42cf9c0b867d49b65fa612d3"),
    ("test-vectors/outside-agent/manifest.json", "test-vectors/outside-agent/manifest.json", "78858828e9eace93eaf31d90717666ddce54ccb3666113df9d033d67c20cfca0"),
    ("test-vectors/outside-agent/valid-ambiguity-report.json", "test-vectors/outside-agent/valid-ambiguity-report.json", "d71d97278acf136ed016994eec9ca82a6cad20285d3fa91416a0f17d1eed978f"),
    ("test-vectors/outside-agent/valid-implementation-submission.json", "test-vectors/outside-agent/valid-implementation-submission.json", "705b4ddf0f5f8be6bee061e9014c5bbde130aa3c0fa3affd04b815612f5658d8"),
    ("test-vectors/outside-agent/valid-work-request.json", "test-vectors/outside-agent/valid-work-request.json", "d332483663431017ac5ecb825c9c8d6767f752927af9ceb637619b30f9687327"),
)
IMMUTABLE_SPEC_V0_2_1_DIGESTS = {
    mirror_path: digest
    for source_path, mirror_path, digest in IMMUTABLE_SPEC_V0_2_1_FILES
    if source_path == mirror_path
}
EXPECTED_VENDOR_RECORD = {
    "source_repo": "Consiliency/spec",
    "source_ref": PRODUCER_TAG,
    "source_commit": PRODUCER_COMMIT,
    "files": [
        {
            "source_path": source_path,
            "mirror_path": mirror_path,
            "raw_byte_sha256": digest,
        }
        for source_path, mirror_path, digest in IMMUTABLE_SPEC_V0_2_1_FILES
    ],
}
EXPECTED_VENDOR_BYTES = json.dumps(EXPECTED_VENDOR_RECORD, sort_keys=True).encode("utf-8")


_CANDIDATE_ONLY_FORBIDDEN_IDENTITY_LABELS = (
    "final implementation commit",
    "final implementation tree",
    "final_commit",
    "final_tree",
    "final-candidate",
    "final_candidate",
    "final-candidate-tree",
    "final_candidate_tree",
    "final candidate",
    "implementation-landing",
    "implementation_landing",
    "implementation-landing-tree",
    "implementation_landing_tree",
    "implementation landing",
    "canonical-main",
    "canonical_main",
    "canonical-main-head",
    "canonical_main_head",
    "canonical-main-head-tree",
    "canonical_main_head_tree",
    "canonical main",
    "exact-main",
    "exact_main",
    "exact main",
)


def assert_candidate_identity_only_document(
    document: str,
    *,
    candidate_commit: str,
    candidate_tree: str,
    forbidden_identity_values: Mapping[str, str],
    anchor: str,
    require_candidate_identity: bool = False,
) -> None:
    """Assert that a candidate-owned document carries no final identities."""
    assert isinstance(document, str), anchor
    assert isinstance(candidate_commit, str) and candidate_commit, anchor
    assert isinstance(candidate_tree, str) and candidate_tree, anchor
    assert candidate_commit != candidate_tree, anchor
    assert all(
        isinstance(value, str)
        and value
        and value not in {candidate_commit, candidate_tree}
        for value in forbidden_identity_values.values()
    ), anchor
    lowered_document = document.lower()
    if require_candidate_identity:
        assert any(
            candidate_identity in lowered_document
            for candidate_identity in (
                f"candidate implementation commit: {candidate_commit}",
                f"candidate implementation commit: `{candidate_commit}`",
            )
        ), anchor
        assert any(
            candidate_identity in lowered_document
            for candidate_identity in (
                f"candidate implementation tree: {candidate_tree}",
                f"candidate implementation tree: `{candidate_tree}`",
            )
        ), anchor
    assert not any(
        label in lowered_document for label in _CANDIDATE_ONLY_FORBIDDEN_IDENTITY_LABELS
    ), anchor
    assert not any(
        value in document for value in forbidden_identity_values.values()
    ), anchor


def _extract_tar_archive(archive: tarfile.TarFile, destination: Path) -> None:
    """Apply the data-filter invariants on every supported Python version."""
    members = archive.getmembers()
    assert all(
        not Path(member.name).is_absolute()
        and ".." not in Path(member.name).parts
        and (member.isfile() or member.isdir())
        for member in members
    )
    archive.extractall(destination)

# These are the Git blob identities of the exact test-owned candidate files.
# They make the local fixture check hermetic: no sibling Consiliency/spec
# checkout is consulted while an eventual committed candidate is still bound to
# Git-object bytes rather than a mutable provenance self-report.
IMMUTABLE_SPEC_V0_2_1_GIT_BLOBS = {
    "consiliency_spec/outside_agent_router.py": "667a92f10d49809f84fe48a2aed4bc4752deccee",
    "schemas/outside-agent-route-verdict.schema.json": "033aa3321dd0ce75b79131f60ff7971eac925baa",
    "schemas/outside-agent-submission.schema.json": "eabf2e4a40fdd84c2f40e8013a9772fc80e71a25",
    "test-vectors/outside-agent/invalid-empty-evidence-refs.json": "760332495ac6b676ed3d850fef648582d613f46f",
    "test-vectors/outside-agent/invalid-git-object-id-length.json": "adc29abaf10c31e4ccee8e64c86740887a502e30",
    "test-vectors/outside-agent/invalid-missing-digest.json": "607ec2a23bda050fe11008a313e3145a9feeedbf",
    "test-vectors/outside-agent/invalid-path-traversal.json": "6a463dcfe0dd98006a608b6627636af48b5b1726",
    "test-vectors/outside-agent/invalid-raw-payload.json": "fd341dd50500fd191df0089d6ff3ac4193bfddf0",
    "test-vectors/outside-agent/invalid-source-bundle-mismatch.json": "e422bc21019caa07375d55b6cc13e76b5d1cbbdf",
    "test-vectors/outside-agent/invalid-unknown-producer-identity-posture.json": "e51c435c22b03d8bc7263701ae72e6ed5641d530",
    "test-vectors/outside-agent/invalid-unsupported-verdict.json": "f8a7521e074b2d8fc42eaf4a419f4caeff381c3e",
    "test-vectors/outside-agent/manifest.json": "f92ab906c34623cba579c89d4aef7701f523232e",
    "test-vectors/outside-agent/valid-ambiguity-report.json": "3a38b6d86ee658a40b4de3e9efe6e874c5787a7d",
    "test-vectors/outside-agent/valid-implementation-submission.json": "7ea2a14464c7b8c86a1fd4fb37b8c6a198e6dbe6",
    "test-vectors/outside-agent/valid-work-request.json": "24290361fce8689ca88479a5651211a73b28e638",
}

# These are agent-harness live blocker codes, intentionally separate from the
# canonical producer's ``expected_blocker_class`` field.
LIVE_BLOCKER_CODE_BY_INVALID_CASE = {
    "negative-raw-payload": "schema_validation_failed",
    "negative-missing-digest": "schema_validation_failed",
    "negative-source-bundle-mismatch": "source_bundle_mismatch",
    "negative-unsupported-verdict": "schema_validation_failed",
    "negative-unknown-producer-identity-posture": "schema_validation_failed",
    "negative-path-traversal": "schema_validation_failed",
    "negative-empty-evidence-refs": "schema_validation_failed",
    "negative-git-object-id-length": "schema_validation_failed",
}

CONFORM_PREEXISTING_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_malformed_submission_maps_to_exit_code_2",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_malformed_json_returns_exit_2",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_loads_pin_from_matching_spec_root",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_missing_contract_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_unknown_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_vector_manifest_hash_mismatch_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_submission_schema_byte_change_with_manifest_hash_held_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_verdict_schema_byte_change_with_manifest_hash_held_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_pin.py::test_expected_outside_agent_contract_pin_records_spec_identity",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_import_surface_preserves_oacontract_helpers",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_accepts_repo_relative_refs_and_digests",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_normalize_outside_agent_ref_rejects_unsafe_refs",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_absolute_path_traversal_empty_and_missing_digest_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_missing_digest_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_digest_mismatch_fails_closed_without_reading_local_files",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_malformed_json_returns_exit_2_and_writes_output",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_requires_output",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_malformed_object_maps_to_exit_2_and_calls_core_once",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_clean_metadata_only_submission_passes",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_raw_payload_provider_body_raw_logs_and_vector_bodies_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_secret_like_values_and_local_env_values_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_core_verdict_contains_only_metadata_refs_and_digests",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_sanitize_outside_agent_verdict_blocks_non_metadata_output",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_package_version_matches_runtime_version",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_outside_agent_public_release_surface_exports_validator_and_advisory_entrypoints",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_expected_outside_agent_contract_pin_release_fields_are_complete",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_workflows_keep_version_build_and_publish_boundaries_explicit",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_submission_kind_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unknown_top_level_field_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_missing_required_metadata_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_unknown_vector_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_manifest_digest_drift_fails_closed",
)
CONFORM_TEST_ONLY_INTEGRITY_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_manifest_partition_and_oracle_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_oracle_is_importable_and_matches_manifest",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_public_exports_and_frontmatter_import_are_preserved",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_oracle_passes_repo_root_ruff",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_frozen_inventory_counts_and_set_equations",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_frozen_command_literals_and_selector_partition",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_planted_non_enumerated_copy_reports_its_exact_path",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_conform_red_assertion_catalog_is_literal",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_closed_redaction_projection_inventory_is_exhaustive",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_redaction_mutation_definitions_are_independent",
)
CONFORM_NEW_PRODUCTION_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
)
CONFORM_DIALECT_MIGRATED_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_submission_kind_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unknown_top_level_field_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_missing_required_metadata_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_unknown_vector_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_manifest_digest_drift_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_core_verdict_contains_only_metadata_refs_and_digests",
)
CONFORM_MIGRATED_EXISTING_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_submission_kind_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unknown_top_level_field_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_missing_required_metadata_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_unknown_vector_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_manifest_digest_drift_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_core_verdict_contains_only_metadata_refs_and_digests",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch",
)
CONFORM_MIGRATED_RED_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch",
)
CONFORM_ACTIVATED_RED_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch",
)
CONFORM_SL2_STALE_DOC_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch",
)
A2_GREEN_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_malformed_submission_maps_to_exit_code_2",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_malformed_json_returns_exit_2",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_loads_pin_from_matching_spec_root",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_missing_contract_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_unknown_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_vector_manifest_hash_mismatch_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_submission_schema_byte_change_with_manifest_hash_held_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_verdict_schema_byte_change_with_manifest_hash_held_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_pin.py::test_expected_outside_agent_contract_pin_records_spec_identity",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_import_surface_preserves_oacontract_helpers",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_accepts_repo_relative_refs_and_digests",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_normalize_outside_agent_ref_rejects_unsafe_refs",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_absolute_path_traversal_empty_and_missing_digest_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_missing_digest_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_digest_mismatch_fails_closed_without_reading_local_files",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_malformed_json_returns_exit_2_and_writes_output",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_requires_output",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_malformed_object_maps_to_exit_2_and_calls_core_once",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_clean_metadata_only_submission_passes",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_raw_payload_provider_body_raw_logs_and_vector_bodies_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_secret_like_values_and_local_env_values_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_core_verdict_contains_only_metadata_refs_and_digests",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_sanitize_outside_agent_verdict_blocks_non_metadata_output",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_package_version_matches_runtime_version",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_outside_agent_public_release_surface_exports_validator_and_advisory_entrypoints",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_expected_outside_agent_contract_pin_release_fields_are_complete",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_workflows_keep_version_build_and_publish_boundaries_explicit",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_submission_kind_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unknown_top_level_field_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_missing_required_metadata_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_unknown_vector_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_manifest_digest_drift_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_manifest_partition_and_oracle_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_oracle_is_importable_and_matches_manifest",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_public_exports_and_frontmatter_import_are_preserved",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_oracle_passes_repo_root_ruff",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_frozen_inventory_counts_and_set_equations",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_frozen_command_literals_and_selector_partition",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_planted_non_enumerated_copy_reports_its_exact_path",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_conform_red_assertion_catalog_is_literal",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_closed_redaction_projection_inventory_is_exhaustive",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_redaction_mutation_definitions_are_independent",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
)
ALL_OUTSIDE_AGENT_NODE_IDS = (
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_malformed_submission_maps_to_exit_code_2",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_malformed_json_returns_exit_2",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_loads_pin_from_matching_spec_root",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_missing_contract_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_unknown_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_vector_manifest_hash_mismatch_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_submission_schema_byte_change_with_manifest_hash_held_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_verdict_schema_byte_change_with_manifest_hash_held_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_pin.py::test_expected_outside_agent_contract_pin_records_spec_identity",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_import_surface_preserves_oacontract_helpers",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_accepts_repo_relative_refs_and_digests",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_normalize_outside_agent_ref_rejects_unsafe_refs",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_absolute_path_traversal_empty_and_missing_digest_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_missing_digest_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_provenance.py::test_digest_mismatch_fails_closed_without_reading_local_files",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_malformed_json_returns_exit_2_and_writes_output",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_requires_output",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_malformed_object_maps_to_exit_2_and_calls_core_once",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_clean_metadata_only_submission_passes",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_raw_payload_provider_body_raw_logs_and_vector_bodies_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_secret_like_values_and_local_env_values_fail_closed",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_core_verdict_contains_only_metadata_refs_and_digests",
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_sanitize_outside_agent_verdict_blocks_non_metadata_output",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_package_version_matches_runtime_version",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_outside_agent_public_release_surface_exports_validator_and_advisory_entrypoints",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_expected_outside_agent_contract_pin_release_fields_are_complete",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_workflows_keep_version_build_and_publish_boundaries_explicit",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_submission_kind_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unknown_top_level_field_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_missing_required_metadata_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_unknown_vector_schema_version_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_manifest_digest_drift_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_manifest_partition_and_oracle_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_oracle_is_importable_and_matches_manifest",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_public_exports_and_frontmatter_import_are_preserved",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_oracle_passes_repo_root_ruff",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_frozen_inventory_counts_and_set_equations",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_frozen_command_literals_and_selector_partition",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_planted_non_enumerated_copy_reports_its_exact_path",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_conform_red_assertion_catalog_is_literal",
    "phase-loop-runtime/tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_closed_redaction_projection_inventory_is_exhaustive",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_redaction_mutation_definitions_are_independent",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
)
CONFORM_ACTIVATED_RED_ANCHORS = {
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows": "CONFORM_RED::canonical_submission_api_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows": "CONFORM_RED::canonical_submission_cli_accepts_three_valid_rows",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition": "CONFORM_RED::canonical_vector_runner_consumes_schema_target_partition",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli": "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli",
    "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance": "CONFORM_RED::digest_enumerated_contract_mirror_missing",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror": "CONFORM_RED::sdist_contract_mirror_missing",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes": "CONFORM_RED::documented_consumer_mirror_policy_allows_only_pinned_contract_bytes",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior": "CONFORM_RED::v7_disposition_records_merged_contract_and_final_installed_behavior",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes": "CONFORM_RED::submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
    "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest": "CONFORM_RED::submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access": "CONFORM_RED::builds_clean_advisory_evidence_without_external_access",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only": "CONFORM_RED::serialized_advisory_evidence_is_deterministic_and_metadata_only",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3": "CONFORM_RED::redaction_blocker_maps_to_exit_code_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4": "CONFORM_RED::provenance_blocker_maps_to_exit_code_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json": "CONFORM_RED::cli_clean_pass_outputs_advisory_json",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3": "CONFORM_RED::cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4": "CONFORM_RED::cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload": "CONFORM_RED::cli_writes_output_file_with_stdout_payload",
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries": "CONFORM_RED::advisory_fixture_outputs_match_stable_summaries",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority": "CONFORM_RED::sdk_serialization_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority": "CONFORM_RED::cli_stdout_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority": "CONFORM_RED::cli_output_file_never_claims_merge_authority",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict": "CONFORM_RED::public_core_api_returns_typed_metadata_only_verdict",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets": "CONFORM_RED::core_api_is_deterministic_and_does_not_require_secrets",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials": "CONFORM_RED::validation_does_not_use_network_or_provider_credentials",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation": "CONFORM_RED::fixture_invocations_do_not_run_vectors_for_live_validation",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner": "CONFORM_RED::ci_release_vector_evidence_runs_pinned_vector_runner",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout": "CONFORM_RED::cli_clean_pass_writes_file_and_stdout",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3": "CONFORM_RED::cli_redaction_violation_returns_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4": "CONFORM_RED::cli_provenance_failure_returns_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5": "CONFORM_RED::cli_contract_pin_failure_returns_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6": "CONFORM_RED::cli_other_conformance_blockers_return_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape": "CONFORM_RED::serializes_clean_governed_pipeline_verdict_shape",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json": "CONFORM_RED::serialized_real_verdict_is_deterministic_json",
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields": "CONFORM_RED::serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence": "CONFORM_RED::real_validator_wraps_core_once_with_metadata_only_evidence",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3": "CONFORM_RED::real_validator_redaction_violation_maps_to_exit_3",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4": "CONFORM_RED::real_validator_provenance_failure_maps_to_exit_4",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5": "CONFORM_RED::real_validator_contract_pin_failure_maps_to_exit_5",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6": "CONFORM_RED::real_validator_other_conformance_blocker_maps_to_exit_6",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths": "CONFORM_RED::real_validator_rejects_absolute_submitted_refs_without_raw_paths",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence": "CONFORM_RED::real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence",
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds": "CONFORM_RED::accepts_supported_submission_kinds",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes": "CONFORM_RED::vector_runner_matches_positive_and_negative_expected_outcomes",
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed": "CONFORM_RED::missing_expected_outcome_fails_closed",
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors": "CONFORM_RED::digest_enumerated_contract_mirror_missing",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary": "CONFORM_RED::release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch": "CONFORM_RED::public_docs_point_to_handoff_without_claiming_release_dispatch",
}
CONFORM_PREEXISTING_NODE_COUNT = 71
CONFORM_TEST_ONLY_INTEGRITY_NODE_COUNT = 12
CONFORM_NEW_PRODUCTION_NODE_COUNT = 10
CONFORM_DIALECT_MIGRATED_NODE_COUNT = 42
CONFORM_MIGRATED_EXISTING_NODE_COUNT = 45
CONFORM_MIGRATED_RED_NODE_COUNT = 38
CONFORM_ACTIVATED_RED_NODE_COUNT = 48
CONFORM_SL2_STALE_DOC_NODE_COUNT = 4
A2_GREEN_NODE_COUNT = 89
ALL_OUTSIDE_AGENT_NODE_COUNT = 93

A2_COMMAND = (
    "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest "
    'phase-loop-runtime/tests -q -k "outside_agent and not '
    "(test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes or "
    "test_v7_disposition_records_merged_contract_and_final_installed_behavior or "
    "test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary or "
    'test_public_docs_point_to_handoff_without_claiming_release_dispatch)"'
)
BROAD_COLLECT_COMMAND = (
    "PYTHONPATH=phase-loop-runtime/src python3 -m pytest "
    "phase-loop-runtime/tests -q --collect-only -k outside_agent"
)
A2_COLLECT_COMMAND = (
    "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest "
    'phase-loop-runtime/tests -q -k "outside_agent and not '
    "(test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes or "
    "test_v7_disposition_records_merged_contract_and_final_installed_behavior or "
    "test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary or "
    'test_public_docs_point_to_handoff_without_claiming_release_dispatch)" --collect-only'
)
B0_COMMAND = (
    "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q "
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::"
    "test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes "
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::"
    "test_v7_disposition_records_merged_contract_and_final_installed_behavior "
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::"
    "test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary "
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::"
    "test_public_docs_point_to_handoff_without_claiming_release_dispatch"
)
B0_COLLECT_COMMAND = (
    "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q "
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::"
    "test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes "
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::"
    "test_v7_disposition_records_merged_contract_and_final_installed_behavior "
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::"
    "test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary "
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::"
    "test_public_docs_point_to_handoff_without_claiming_release_dispatch --collect-only"
)

@dataclass(frozen=True)
class SourceMutation:
    """A frozen, shell-free candidate-only source mutation contract."""

    source_path: str
    anchor: str
    replacement: str
    argv: tuple[str, ...]
    expected_nodeid: str
    expected_anchor: str
    positive_control: tuple[str, ...]
    expected_observable: str
    source_fixture: str | None = None
    source_fixture_is_authoritative: bool = False
    parse_python: bool = False
    companion_argv: tuple[str, ...] | None = None
    companion_expected_nodeid: str | None = None
    companion_expected_anchor: str | None = None

    def apply(self, source: str) -> str:
        assert source.count(self.anchor) == 1, self.source_path
        return source.replace(self.anchor, self.replacement, 1)

    def complete_source(self) -> str:
        if self.source_fixture_is_authoritative:
            assert self.source_fixture is not None, self.source_path
            return self.source_fixture
        path = REPO_ROOT / self.source_path
        if path.exists():
            return path.read_text(encoding="utf-8")
        relative = Path(self.source_path).relative_to("phase-loop-runtime/src")
        if relative.suffix == ".py":
            module_name = ".".join(relative.with_suffix("").parts)
            spec = importlib.util.find_spec(module_name)
            if spec is not None and spec.origin is not None:
                installed_path = Path(spec.origin)
                if installed_path.is_file():
                    return installed_path.read_text(encoding="utf-8")
        assert self.source_fixture is not None, self.source_path
        return self.source_fixture


def _mutation_argv(nodeid: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        nodeid,
    )


_MUTATION_VENDOR_SOURCE = EXPECTED_VENDOR_BYTES.decode("utf-8")
CONFORM_MUTATION_DEFINITIONS = {
    "M-CONFORM-1-RESTORE-ALLOWLIST": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_core.py",
        """schema_result = validate_outside_agent_submission_schema(
        submission, contract_pin=contract_pin
    )""",
        """schema_result = validate_outside_agent_submission_schema(
        {key: submission[key] for key in ("submission_schema_version", "submission_kind", "metadata", "provenance_refs", "evidence_refs") if key in submission},
        contract_pin=contract_pin,
    )""",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows"),
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_api_accepts_three_valid_rows",
        "CONFORM_RED::canonical_submission_api_accepts_three_valid_rows",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows"),
        "canonical_submission_api_accepts_three_valid_rows",
        parse_python=True,
        companion_argv=_mutation_argv(
            "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_submission_cli_accepts_three_valid_rows"
        ),
        companion_expected_nodeid=(
            "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::"
            "test_canonical_submission_cli_accepts_three_valid_rows"
        ),
        companion_expected_anchor=(
            "CONFORM_RED::canonical_submission_cli_accepts_three_valid_rows"
        ),
    ),
    "M-CONFORM-2-RAW-CONSTRUCTION-GUARD": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/cli.py",
        "return hashlib.sha256(captured_input_bytes).hexdigest()",
        "return hashlib.sha256(submission_file.encode(\"utf-8\")).hexdigest()",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes"),
        "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
        "CONFORM_RED::submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest"),
        "submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
        '''def _digest_captured_submission_bytes(
    captured_input_bytes: bytes, *, submission_file: str
) -> str:
    return hashlib.sha256(captured_input_bytes).hexdigest()
''',
        True,
        parse_python=True,
    ),
    "M-CONFORM-3-FINAL-SERIALIZER-GUARD": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_real_output.py",
        "return _serialize_metadata_only_payload(payload)",
        'payload["submission_file"] = validation.submission_file\n    return _serialize_metadata_only_payload(payload)',
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest"),
        "phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
        "CONFORM_RED::submission_file_missing_unreadable_paths_fail_closed_without_path_derived_digest",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_redaction_separation.py::test_submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes"),
        "submission_file_locator_never_serializes_and_digest_tracks_only_captured_bytes",
        '''def serialize_outside_agent_validation_verdict(validation):
    payload = {"input_digest": validation.verdict.input_digest}
    return _serialize_metadata_only_payload(payload)
''',
        True,
        parse_python=True,
    ),
    "M-CONFORM-4-MISSING-MIRROR": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/VENDOR.json",
        '{"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a", "source_path": "schemas/outside-agent-submission.schema.json"}, ',
        "",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance"),
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
        "CONFORM_RED::digest_enumerated_contract_mirror_missing",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory"),
        "assert_packaged_contract_mirror",
        _MUTATION_VENDOR_SOURCE,
    ),
    "M-CONFORM-4-EXTRA-MIRROR": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/VENDOR.json",
        '{"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a", "source_path": "schemas/outside-agent-submission.schema.json"}',
        '{"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a", "source_path": "schemas/outside-agent-submission.schema.json"}, {"mirror_path": "extra.json", "raw_byte_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "source_path": "extra.json"}',
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance"),
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
        "CONFORM_RED::digest_enumerated_contract_mirror_missing",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory"),
        "assert_packaged_contract_mirror",
        _MUTATION_VENDOR_SOURCE,
    ),
    "M-CONFORM-4-DUPLICATE-MIRROR": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/VENDOR.json",
        '{"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a", "source_path": "schemas/outside-agent-submission.schema.json"}',
        '{"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a", "source_path": "schemas/outside-agent-submission.schema.json"}, {"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a", "source_path": "schemas/outside-agent-submission.schema.json"}',
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance"),
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
        "CONFORM_RED::digest_enumerated_contract_mirror_missing",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory"),
        "assert_packaged_contract_mirror",
        _MUTATION_VENDOR_SOURCE,
    ),
    "M-CONFORM-4-FIXED-VENDOR-BYTE": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/VENDOR.json",
        '{"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a", "source_path": "schemas/outside-agent-submission.schema.json"}',
        '{"mirror_path": "schemas/outside-agent-submission.schema.json", "raw_byte_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "source_path": "schemas/outside-agent-submission.schema.json"}',
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance"),
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_packaged_contract_mirror_matches_fixture_provenance",
        "CONFORM_RED::digest_enumerated_contract_mirror_missing",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_fixture_provenance_and_digest_inventory"),
        "assert_packaged_contract_mirror",
        _MUTATION_VENDOR_SOURCE,
    ),
    "M-CONFORM-5-SUBMISSION-SCHEMA-BYTE": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_imports.py",
        '''    _verify_source_sha256(
        submission_schema_bytes,
        expected_pin.submission_schema_sha256,
        "submission_schema_sha256_mismatch",
    )''',
        "    pass",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_submission_schema_byte_change_with_manifest_hash_held_fails_closed"),
        "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_submission_schema_byte_change_with_manifest_hash_held_fails_closed",
        "DID NOT RAISE",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_loads_pin_from_matching_spec_root"),
        "submission_schema_sha256_mismatch",
        parse_python=True,
    ),
    "M-CONFORM-5-VERDICT-SCHEMA-BYTE": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_imports.py",
        '''    _verify_source_sha256(
        verdict_schema_bytes,
        expected_pin.verdict_schema_sha256,
        "verdict_schema_sha256_mismatch",
    )''',
        "    pass",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_verdict_schema_byte_change_with_manifest_hash_held_fails_closed"),
        "phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_verdict_schema_byte_change_with_manifest_hash_held_fails_closed",
        "DID NOT RAISE",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_contract_imports.py::test_loads_pin_from_matching_spec_root"),
        "verdict_schema_sha256_mismatch",
        parse_python=True,
    ),
    "M-CONFORM-8-SWAP-SCHEMA": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_vectors.py",
        "for vector in manifest_data.get(\"vectors\", []):",
        "for vector in ({**item, \"schema_target\": \"outside_agent_submission.v0.1\"} if item.get(\"schema_target\") == \"outside_agent_route_verdict.v0.1\" else item for item in manifest_data.get(\"vectors\", [])): ",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli"),
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli",
        "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition"),
        "dispatch_observation",
        parse_python=True,
    ),
    "M-CONFORM-8-DISPATCH-BYPASS": SourceMutation(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_vectors.py",
        "for vector in manifest_data.get(\"vectors\", []):",
        "for vector in (item for item in manifest_data.get(\"vectors\", []) if item.get(\"schema_target\") != \"outside_agent_route_verdict.v0.1\"): ",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli"),
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_route_verdict_requires_selected_schema_not_submission_cli",
        "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli",
        _mutation_argv("phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::test_canonical_vector_runner_consumes_schema_target_partition"),
        "dispatch_observation",
        parse_python=True,
    ),
}

EC_CONFORM_PROBES = {
    f"EC-CONFORM-{index}": {
        "id": f"EC-CONFORM-{index}",
        "ordinal": index,
        "criterion": criterion,
    }
    for index, criterion in enumerate((
        "chronology_identity_equations",
        "corpus_valid_submissions_allowlist_falsifier",
        "redaction_seven_class_inventory",
        "redaction_posture_enforcement_guards",
        "contract_mirror_provenance_and_mutations",
        "per_schema_digest_mismatch_falsifiers",
        "v7_disposition_merged_spec_provenance",
        "package_release_handoff_and_no_copy",
        "adversarial_vectors_fail_closed_dispatch",
    ))
}

EVIDENCE_VERIFIER_INTERFACE = {
    "chronology": {
        "timing": "A2",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "chronology"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
    "corpus": {
        "timing": "A2",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "fixture_manifest", "mutations"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
    "package": {
        "timing": "A2",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "direct_wheel", "direct_sdist", "sdist_derived_wheel", "mutations"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
    "compatibility": {
        "timing": "B2-only",
        "inputs": ("candidate_commit", "candidate_tree", "head_commit", "head_tree", "module_path", "runner_manifest", "runner_log", "junit_xml", "ec_matrix", "mutations", "installed_package"),
        "outputs": ("mode", "candidate_commit", "head_commit", "module_path", "recomputed_input_digest", "recomputed_evidence_digest", "evidence"),
    },
}

EVIDENCE_VERIFIER_RECORD_IDS = {
    "chronology": ("preimplementation", "postimplementation"),
    "corpus": ("source-fixture", "package-mirror"),
    "package": ("direct-wheel", "sdist-derived-wheel"),
    "compatibility": ("ec-matrix", "installed-package"),
}
EVIDENCE_VERIFIER_RECORD_KEYS = (
    "record_id",
    "ordinal",
    "artifact_path",
    "artifact_sha256",
    "raw_log_path",
    "raw_log_sha256",
    "evidence",
)


def evidence_verifier_argv(mode: str, records_path: Path | None = None) -> tuple[str, ...]:
    assert mode in EVIDENCE_VERIFIER_INTERFACE
    argv = (
        sys.executable,
        "-m",
        "phase_loop_runtime.conformance.outside_agent_conform_evidence",
        mode,
    )
    if records_path is not None:
        argv += ("--records", str(records_path))
    return argv


def assert_evidence_verifier_entrypoint(nodeid: str) -> None:
    """Require the production verifier to be an invocable, mode-complete CLI.

    The SL-0 test-only candidate deliberately has no verifier module, so this is
    an explicit missing-production-surface RED under activation.  It does not
    trust a candidate-authored status boolean or fabricate verifier evidence.
    """
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "phase_loop_runtime.conformance.outside_agent_conform_evidence",
            "--help",
        ),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    anchor = _red_anchor(nodeid)
    assert completed.returncode == 0, anchor
    help_text = completed.stdout + completed.stderr
    for mode in EVIDENCE_VERIFIER_INTERFACE:
        assert mode in help_text, anchor


CONFORMANCE_EXPORT_SNAPSHOT = (
    "scan_consiliency_gates",
    "resolve_consiliency_gates_mode",
    "CONSILIENCY_GATES_ENV",
    "CONSILIENCY_GATES_MODES",
    "DEFAULT_CONSILIENCY_GATES_MODE",
    "evaluate_git_discipline",
    "self_heal_partition",
    "evaluate_governance_scope",
    "validate_certificate",
    "certificate_schema_available",
    "GIT_GROUNDED_KIND",
    "GIT_GROUNDED_PROJECTION_SCHEMA",
    "PORTAL_KIND_MISNOMER",
    "RAW_SHA256_DOMAIN",
    "GitGroundedContractAbsent",
    "GitGroundedProjection",
    "build_git_grounded_body",
    "build_projection_index_entry",
    "reconcile_git_grounded_projection",
    "OutsideAgentBlocker",
    "OutsideAgentConformanceVerdict",
    "OutsideAgentEvidenceRef",
    "OutsideAgentSubmissionKind",
    "OutsideAgentVerdictStatus",
    "validate_outside_agent_submission",
    "OutsideAgentAdvisoryEvidence",
    "OutsideAgentAdvisoryExitCode",
    "build_outside_agent_advisory_evidence",
    "serialize_outside_agent_advisory_evidence",
    "OutsideAgentContractError",
    "load_outside_agent_contract_pin",
    "EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN",
    "OutsideAgentContractPin",
    "OutsideAgentSubmittedRef",
    "OutsideAgentValidationExitCode",
    "OutsideAgentValidationVerdict",
    "build_outside_agent_validation_verdict",
    "digest_outside_agent_validation_bytes",
    "serialize_outside_agent_validation_verdict",
)

REDACTION_PROJECTION_CLASSES = {
    "read_locator_only": (
        "outside-agent-preflight:submission_file",
        "outside-agent-validate:submission_file",
    ),
    "forbidden_free_text": (
        "submission.submission_id",
        "submission.summary",
        "submission.producer.agent_name",
        "submission.producer.agent_version",
        "submission.evidence_refs[].source_bundle_refs[].bundle_id",
        "submission.evidence_refs[].repo_owner",
        "submission.evidence_refs[].repo_name",
        "submission.work_request.goal",
        "submission.work_request.constraints[]",
        "submission.implementation_submission.change_summary",
        "submission.ambiguity_report.ambiguity_summary",
        "submission.ambiguity_report.questions[]",
        "submission.unknown_keys[]",
        "submission.unknown_values[]",
        "submission.raw_payload",
        "submission.provider_response",
        "submission.raw_log",
        "submission.environment",
        "submission.evidence_refs[].raw_body",
        "submission.producer.identity_posture",
        "route_verdict.blocker.summary",
        "route_verdict.notes",
        "route_verdict.unknown_keys[]",
        "route_verdict.unknown_values[]",
        "route_verdict.raw_payload",
        "route_verdict.provider_response",
        "route_verdict.raw_log",
        "route_verdict.environment",
        "route_verdict.blocker.raw_body",
        "legacy_submission.metadata.submission_id",
        "legacy_submission.metadata.content_digest",
        "legacy_submission.unknown_keys[]",
        "legacy_submission.unknown_values[]",
        "legacy_submission.raw_payload",
        "legacy_submission.provider_response",
        "legacy_submission.raw_log",
        "legacy_submission.environment",
    ),
    "normalized_ref_projection": (
        "submission.evidence_refs[].repo_relative_path",
        "advisory_output.provenance_refs[]",
        "advisory_output.evidence_refs[].ref",
        "validation_output.submitted_refs[]",
        "validation_output.evidence_refs[].ref",
        "legacy_submission.provenance_refs[].ref",
        "legacy_submission.evidence_refs[].ref",
        "outside-agent-validate:submitted_ref[]",
    ),
    "structural_diagnostic_projection": (
        "advisory_output.blockers[].message",
        "advisory_output.blockers[].ref",
        "validation_output.blockers[].message",
        "validation_output.blockers[].ref",
    ),
    "validated_digest_projection": (
        "submission.evidence_refs[].immutable_git_ref",
        "submission.evidence_refs[].sha256",
        "submission.evidence_refs[].source_bundle_refs[].bundle_manifest_sha256",
        "submission.evidence_refs[].bundle_manifest_sha256",
        "submission.implementation_submission.head_commit_sha",
        "legacy_submission.provenance_refs[].digest",
        "legacy_submission.evidence_refs[].digest",
        "advisory_output.input_digest",
        "advisory_output.evidence_refs[].digest",
        "validation_output.input_digest",
        "validation_output.evidence_refs[].digest",
        "validation_output.vector_manifest_hash",
        "advisory_output.contract_pin.vector_manifest_hash",
        "validation_output.contract_pin.vector_manifest_hash",
        "advisory_output.contract_pin.contract_git_sha",
        "validation_output.contract_pin.contract_git_sha",
    ),
    "closed_vocabulary_projection": (
        "submission.submission_schema_version",
        "submission.submission_kind",
        "submission.claim_posture",
        "submission.acceptance_truth_owner",
        "submission.evidence_refs[].evidence_ref_schema_version",
        "submission.evidence_refs[].digest_algorithm",
        "submission.evidence_refs[].source_role",
        "submission.evidence_refs[].claimed_path_membership.proof_type",
        "submission.evidence_refs[].claimed_path_membership.included",
        "submission.evidence_refs[].redaction_posture",
        "route_verdict.verdict_schema_version",
        "route_verdict.route",
        "route_verdict.claim_posture",
        "route_verdict.acceptance_truth_owner",
        "route_verdict.blocker.class",
        "route_verdict.blocker.human_required",
        "advisory_output.authority",
        "advisory_output.classification",
        "advisory_output.exit_code",
        "advisory_output.verdict_schema_version",
        "advisory_output.submission_kind",
        "advisory_output.status",
        "advisory_output.contract_pin.schema_version",
        "advisory_output.contract_pin.verdict_schema_version",
        "advisory_output.contract_pin.contract_package",
        "advisory_output.contract_pin.contract_version",
        "advisory_output.contract_pin.vector_manifest_name",
        "advisory_output.contract_pin.source_owner",
        "advisory_output.contract_pin.redaction_posture",
        "advisory_output.redaction_posture",
        "advisory_output.metadata.source",
        "advisory_output.evidence_refs[].kind",
        "advisory_output.blockers[].code",
        "legacy_submission.submission_schema_version",
        "legacy_submission.submission_kind",
        "validation_output.gate_id",
        "validation_output.authority",
        "validation_output.validator_version",
        "validation_output.command",
        "validation_output.verdict_schema_version",
        "validation_output.contract_pin.schema_version",
        "validation_output.contract_pin.verdict_schema_version",
        "validation_output.contract_pin.contract_package",
        "validation_output.contract_pin.contract_version",
        "validation_output.contract_pin.vector_manifest_name",
        "validation_output.contract_pin.source_owner",
        "validation_output.contract_pin.redaction_posture",
        "validation_output.submission_kind",
        "validation_output.status",
        "validation_output.redaction_posture",
        "validation_output.vectors_executed",
        "validation_output.exit_code",
        "validation_output.evidence_refs[].kind",
        "validation_output.blockers[].code",
    ),
    "serialized_sink": (
        "outside-agent-preflight:stdout",
        "outside-agent-preflight:--output",
        "outside-agent-validate:stdout",
        "outside-agent-validate:--output",
    ),
}

CANONICAL_DYNAMIC_INPUTS = frozenset(
    channel
    for channel in REDACTION_PROJECTION_CLASSES["forbidden_free_text"]
    if channel.startswith(("submission.", "route_verdict."))
    and channel
    in {
        "submission.unknown_keys[]",
        "submission.unknown_values[]",
        "submission.raw_payload",
        "submission.provider_response",
        "submission.raw_log",
        "submission.environment",
        "submission.evidence_refs[].raw_body",
        "submission.producer.identity_posture",
        "route_verdict.unknown_keys[]",
        "route_verdict.unknown_values[]",
        "route_verdict.raw_payload",
        "route_verdict.provider_response",
        "route_verdict.raw_log",
        "route_verdict.environment",
        "route_verdict.blocker.raw_body",
    }
)


def recursive_schema_channels(schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Return every recursive property channel from one pinned schema."""
    definitions = schema.get("$defs", {})

    def resolve(node: Mapping[str, Any]) -> Mapping[str, Any]:
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            return definitions[reference.rsplit("/", 1)[1]]
        return node

    def walk(node: Mapping[str, Any], prefix: str = "") -> tuple[str, ...]:
        resolved = resolve(node)
        properties = resolved.get("properties")
        if isinstance(properties, Mapping):
            return tuple(
                channel
                for key, child in properties.items()
                for channel in walk(child, f"{prefix}.{key}" if prefix else key)
            )
        items = resolved.get("items")
        if isinstance(items, Mapping):
            return walk(items, prefix + "[]")
        return (prefix,)

    return walk(schema)


def redaction_channel_assignment() -> dict[str, str]:
    assignments: dict[str, str] = {}
    for classification, channels in REDACTION_PROJECTION_CLASSES.items():
        for channel in channels:
            assert channel not in assignments, channel
            assignments[channel] = classification
    return assignments


def normalized_nodeid(nodeid: str) -> str:
    path, separator, test_name = nodeid.partition("::")
    parts = Path(path).parts
    if "tests" in parts:
        normalized_path = Path(*parts[parts.index("tests") :]).as_posix()
        if normalized_path.startswith("tests/"):
            return "phase-loop-runtime/" + normalized_path + separator + test_name
    if path.startswith("test_") and path.endswith(".py"):
        return "phase-loop-runtime/tests/" + path + separator + test_name
    return nodeid


def node_source_path(nodeid: str) -> Path:
    """Resolve a frozen test body from a checkout or Gate A's copied tests tree."""
    relative = nodeid.split("::", 1)[0]
    checkout_path = REPO_ROOT / relative
    if checkout_path.is_file():
        return checkout_path
    copied_path = Path(__file__).with_name(Path(relative).name)
    assert copied_path.is_file(), relative
    return copied_path


def canonical_mode_enabled() -> bool:
    if os.environ.get(TDD_ENV) == "1":
        return True
    try:
        from phase_loop_runtime.conformance import outside_agent_schema
    except ImportError:
        return False
    return getattr(outside_agent_schema, "CONFORM_V10_CAPABILITY_MARKER", None) == CAPABILITY_MARKER


def runner_b2_evidence_enabled() -> bool:
    return os.environ.get(RUNNER_B2_EVIDENCE_ENV) == "1"


def runner_b2_evidence() -> dict[str, Any] | None:
    if not runner_b2_evidence_enabled():
        return None
    return sealed_release_evidence()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def provenance() -> dict[str, Any]:
    return load_json(PROVENANCE_PATH)


def manifest() -> dict[str, Any]:
    return load_json(MANIFEST_PATH)


def vector_entries() -> tuple[dict[str, Any], ...]:
    return tuple(manifest()["vectors"])


def vector_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return load_json(FIXTURE_ROOT / entry["path"])


def valid_submission_entries() -> tuple[dict[str, Any], ...]:
    return tuple(entry for entry in vector_entries() if entry["expected_valid"])


def submission_entries() -> tuple[dict[str, Any], ...]:
    return tuple(
        entry
        for entry in vector_entries()
        if entry["schema_target"] == "outside_agent_submission.v0.1"
    )


def route_verdict_entry() -> dict[str, Any]:
    entries = [
        entry
        for entry in vector_entries()
        if entry["schema_target"] == "outside_agent_route_verdict.v0.1"
    ]
    assert len(entries) == 1
    return entries[0]


def clean_canonical_submission() -> dict[str, Any]:
    return copy.deepcopy(vector_payload(valid_submission_entries()[0]))


def fixture_digest_map() -> dict[str, str]:
    return dict(IMMUTABLE_SPEC_V0_2_1_DIGESTS)


def fixture_paths() -> tuple[str, ...]:
    return tuple(sorted(fixture_digest_map()))


def candidate_fixture_git_blob(path: Path) -> str:
    """Return the candidate fixture's Git-object identity without another checkout.

    ``git hash-object --stdin`` applies this repository's object format to the
    exact bytes under test.  A committed test candidate also has the same object
    address in its tree; an uncommitted SL-0 worktree is intentionally supported
    so the test can be frozen before the test-only landing exists.
    """
    relative = path.relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "hash-object", "--stdin"],
        cwd=REPO_ROOT,
        input=path.read_bytes(),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"candidate Git object unavailable: {relative}"
    return result.stdout.decode("ascii", "replace").strip()


def verify_fixture_digests() -> None:
    details = provenance()
    assert details["source_repo"] == "Consiliency/spec"
    assert details["tag"] == PRODUCER_TAG
    assert details["dereferenced_commit"] == PRODUCER_COMMIT
    records = tuple(
        (
            entry.get("source_path"),
            entry.get("mirror_path"),
            entry.get("raw_byte_sha256"),
        )
        for entry in details["files"]
    )
    assert len(records) == len(set(records)) == 15
    assert set(records) == set(IMMUTABLE_SPEC_V0_2_1_FILES)
    assert {record[0] for record in records} == {record[1] for record in records}
    assert len({record[0] for record in records}) == 15
    assert len({record[1] for record in records}) == 15
    expected_paths = {record[1] for record in IMMUTABLE_SPEC_V0_2_1_FILES}
    assert expected_paths == set(fixture_paths())
    assert set(IMMUTABLE_SPEC_V0_2_1_GIT_BLOBS) == expected_paths
    actual_fixture_paths = {
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file()
        and not (
            path.suffix == ".pyc"
            and path.parent.name == "__pycache__"
        )
    }
    assert actual_fixture_paths == expected_paths | {"PROVENANCE.json"}
    manifest_paths = {"test-vectors/outside-agent/manifest.json"}
    manifest_paths.update(entry["path"] for entry in vector_entries())
    assert manifest_paths <= expected_paths
    for source_path, mirror_path, expected in IMMUTABLE_SPEC_V0_2_1_FILES:
        assert source_path == mirror_path
        fixture_bytes = (FIXTURE_ROOT / mirror_path).read_bytes()
        assert hashlib.sha256(fixture_bytes).hexdigest() == expected, mirror_path
        assert candidate_fixture_git_blob(FIXTURE_ROOT / mirror_path) == (
            IMMUTABLE_SPEC_V0_2_1_GIT_BLOBS[mirror_path]
        ), source_path


def load_oracle() -> ModuleType:
    oracle_path = FIXTURE_ROOT / "consiliency_spec" / "outside_agent_router.py"
    spec = importlib.util.spec_from_file_location("outside_agent_contract_v0_2_1_oracle", oracle_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_mirror_paths() -> tuple[str, ...]:
    return tuple(
        "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/" + path
        for path in fixture_paths()
    )


def source_runtime_available() -> bool:
    return (RUNTIME_ROOT / "src" / "phase_loop_runtime").is_dir()


def packaged_contract_mirror_root() -> Path:
    if source_runtime_available():
        return RUNTIME_ROOT / "src" / "phase_loop_runtime" / "conformance" / "_contract"
    import phase_loop_runtime

    return (
        Path(phase_loop_runtime.__file__).resolve().parent
        / "conformance"
        / "_contract"
    )


def find_non_enumerated_canonical_copies(repo_root: Path) -> tuple[tuple[str, ...], int]:
    root = repo_root / PRODUCTION_SCAN_ROOT_LITERAL
    relative_to = repo_root
    allowed = set(production_mirror_paths())
    if repo_root == REPO_ROOT and not root.is_dir():
        import phase_loop_runtime

        root = Path(phase_loop_runtime.__file__).resolve().parent
        relative_to = root
        allowed = {
            "conformance/_contract/" + relative for relative in fixture_paths()
        }
    scanned = [path for path in root.rglob("*") if path.is_file()]
    copied = tuple(
        relative
        for path in scanned
        if (relative := path.relative_to(relative_to).as_posix()) not in allowed
        and _looks_like_canonical_contract_copy(path)
    )
    return copied, len(scanned)


SEALED_RELEASE_EVIDENCE_PATH = REPO_ROOT / ".phase-loop" / "runs" / "CONFORM-T2" / "sealed-release-evidence.json"

# The release handoff cannot choose its own candidate or contract archive
# inventory.  These are the exact SL-1 paths declared by the ratified plan.
# Existing parent files are pinned to the Git blobs already present at the
# reviewed base; the evidence module and digest-enumerated contract mirror are
# correctly absent there.  A candidate that changes only a convenient source
# file, invents a parent, or replaces this transition with CAPABILITY bytes is
# therefore not a CONFORM candidate.
SEALED_RELEASE_CANDIDATE_PARENT_BLOBS = {
    "phase-loop-runtime/MANIFEST.in": "f090e7edff35a13ffe580750224c9d43285008c9",
    "phase-loop-runtime/pyproject.toml": "5dbc9e37747bd4dba6fe45bfa51d246cadaabb8b",
    "phase-loop-runtime/src/phase_loop_runtime/cli.py": "780ed1a41100e3302dff7fb084458ecb8bcf8e6a",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_advisory.py": "8e7426442c7f64486de4d55a8eeda4c19b065a32",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py": None,
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_core.py": "25a2db9055f385cc977cef389eb5e7420659355a",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_real.py": "ebd754174c0fa75ec2048da67f098b98b29c57d2",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_real_output.py": "c0f4bb629f9f5bdd250590b78abd858a596ba352",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_redaction.py": "a2e64b24a3f90e5dbdc7695b31f1832583d23876",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_schema.py": "1afef421c70af4e2315ce91cb93b824c0c858930",
    "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_vectors.py": "cae62bca74949713f0ece774018f323b5588fe43",
    **{
        "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/" + relative: None
        for relative in fixture_paths()
    },
    "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/VENDOR.json": None,
}
SEALED_RELEASE_CANDIDATE_PATHS = tuple(sorted(SEALED_RELEASE_CANDIDATE_PARENT_BLOBS))
SEALED_RELEASE_FINAL_PARENT_BLOBS = {
    "CHANGELOG.md": "d1c607477ee242821c2640bc4bd6f89d191da54e",
    "docs/outside-agent-conformance.md": "aed512fc04e32464c1426913089c6d524fa69272",
    "docs/releases/outside-agent-release-handoff.md": "29cd326cb95b7ef35b0e886446137a4e983c53c9",
    "specs/phase-plans-v7.md": "f79c82763618714f6dda1cfbf3ccd150bd2bcb54",
}
SEALED_RELEASE_FINAL_PATHS = tuple(sorted(SEALED_RELEASE_FINAL_PARENT_BLOBS))
SEALED_RELEASE_ARCHIVE_MEMBERS = (
    "phase_loop_runtime/conformance/_contract/VENDOR.json",
    "phase_loop_runtime/conformance/_contract/consiliency_spec/outside_agent_router.py",
    "phase_loop_runtime/conformance/_contract/schemas/outside-agent-route-verdict.schema.json",
    "phase_loop_runtime/conformance/_contract/schemas/outside-agent-submission.schema.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-empty-evidence-refs.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-git-object-id-length.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-missing-digest.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-path-traversal.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-raw-payload.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-source-bundle-mismatch.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-unknown-producer-identity-posture.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/invalid-unsupported-verdict.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/manifest.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/valid-ambiguity-report.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/valid-implementation-submission.json",
    "phase_loop_runtime/conformance/_contract/test-vectors/outside-agent/valid-work-request.json",
)
SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS = {
    "phase_loop_runtime/conformance/_contract/VENDOR.json": hashlib.sha256(
        EXPECTED_VENDOR_BYTES
    ).hexdigest(),
    **{
        "phase_loop_runtime/conformance/_contract/" + relative: digest
        for relative, digest in IMMUTABLE_SPEC_V0_2_1_DIGESTS.items()
    },
}
assert tuple(sorted(SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS)) == SEALED_RELEASE_ARCHIVE_MEMBERS


def _sealed_manifest_sha256(evidence: Mapping[str, Any]) -> str:
    payload = dict(evidence)
    payload.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _a2_package_evidence_sha256(evidence: Mapping[str, Any]) -> str:
    """Hash only pre-document package inputs, never a final document or identity."""
    payload = dict(evidence)
    payload.pop("a2_package_evidence_sha256", None)
    assert not {
        "final_commit",
        "final_tree",
        "final_members",
        "final_paths",
        "final_parent_blobs",
    } & set(payload)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _build_a2_package_evidence(
    *,
    candidate_commit: str,
    candidate_tree: str,
    candidate_members: Mapping[str, str],
    archives: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Normalize the only digestable pre-document A2 package-evidence schema."""
    evidence: dict[str, Any] = {
        "candidate_commit": candidate_commit,
        "candidate_tree": candidate_tree,
        "candidate_members": dict(candidate_members),
        "archives": {
            label: {
                "sha256": archive["sha256"],
                "members": dict(archive["members"]),
            }
            for label, archive in sorted(archives.items())
        },
    }
    evidence["a2_package_evidence_sha256"] = _a2_package_evidence_sha256(evidence)
    return evidence


def _git_output(repository: Path, *argv: str) -> str:
    completed = subprocess.run(
        ["git", *argv],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, "CONFORM_RED::sealed_release_evidence_git_object_missing"
    return completed.stdout.strip()


def _git_bytes(repository: Path, object_id: str) -> bytes:
    completed = subprocess.run(
        ["git", "cat-file", "-p", object_id],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, "CONFORM_RED::sealed_release_evidence_git_object_missing"
    return completed.stdout


def _sealed_candidate_parent(repository: Path, candidate_commit: str) -> str:
    """Derive the unique reviewed parent of a potentially stacked candidate."""
    commits = _git_output(repository, "rev-list", "--parents", candidate_commit).splitlines()
    parent_vectors = {
        fields[0]: fields[1:]
        for line in commits
        if (fields := line.split())
    }
    matches: dict[str, bool] = {}

    def matches_parent_blobs(commit: str) -> bool:
        if commit not in matches:
            matched = True
            for path, expected_blob in SEALED_RELEASE_CANDIDATE_PARENT_BLOBS.items():
                actual = subprocess.run(
                    ["git", "rev-parse", f"{commit}:{path}"],
                    cwd=repository,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if expected_blob is None:
                    matched = matched and actual.returncode != 0
                else:
                    matched = matched and actual.returncode == 0 and actual.stdout.strip() == expected_blob
            matches[commit] = matched
        return matches[commit]

    boundaries = [
        parent
        for commit, parents in parent_vectors.items()
        if not matches_parent_blobs(commit)
        for parent in parents
        if matches_parent_blobs(parent)
    ]
    assert len(boundaries) == 1, "CONFORM_RED::sealed_release_evidence_candidate_transition"
    return boundaries[0]


def sealed_release_parent_bytes(
    repository: Path = REPO_ROOT,
) -> dict[str, bytes | None]:
    """Materialize the exact reviewed-base blobs, never ambient working bytes."""
    return {
        path: _git_bytes(repository, blob) if blob is not None else None
        for path, blob in SEALED_RELEASE_CANDIDATE_PARENT_BLOBS.items()
    }


def sealed_release_candidate_bytes(
    repository: Path = REPO_ROOT,
) -> dict[str, bytes]:
    """Build the deterministic full SL-1 transition from reviewed-base blobs."""
    parent = sealed_release_parent_bytes(repository)
    vendor = EXPECTED_VENDOR_BYTES
    result: dict[str, bytes] = {}
    for path in SEALED_RELEASE_CANDIDATE_PATHS:
        if path.endswith("/VENDOR.json"):
            result[path] = vendor
        elif "/_contract/" in path:
            result[path] = (FIXTURE_ROOT / path.rsplit("/_contract/", 1)[1]).read_bytes()
        else:
            baseline = parent[path] or b""
            component = path.rsplit("/", 1)[-1].replace(".", "_").upper()
            transition = f"\n# CONFORM_SL1_TRANSITION:{component}: canonical-contract-and-evidence\n"
            if path.endswith("MANIFEST.in"):
                transition += (
                    "recursive-include src/phase_loop_runtime/conformance/_contract *\n"
                )
            elif path.endswith("pyproject.toml"):
                package_data_entry = b'    "advisor_board/CONTRACTS.md",\n]'
                assert package_data_entry in baseline
                baseline = baseline.replace(
                    package_data_entry,
                    b'    "advisor_board/CONTRACTS.md",\n'
                    b'    "conformance/_contract/**",\n]',
                )
            elif path.endswith("outside_agent_schema.py"):
                transition += f'CONFORM_V10_CAPABILITY_MARKER = "{CAPABILITY_MARKER}"\n'
            elif path.endswith("outside_agent_conform_evidence.py"):
                transition += "def verify_conform_evidence_records(*_args):\n    return {}\n"
            elif path.endswith("cli.py"):
                transition += '# registers "outside-agent-validate" evidence command\n'
            result[path] = baseline + transition.encode("utf-8")
    assert set(result) == set(SEALED_RELEASE_CANDIDATE_PATHS)
    assert all(b"CAPABILITY = 'candidate'" not in contents for contents in result.values())
    return result


def sealed_release_final_bytes(
    candidate: Mapping[str, bytes], repository: Path = REPO_ROOT
) -> dict[str, bytes]:
    """Add only the ratified SL-2 documentation transition to an SL-1 tree."""
    result = dict(candidate)
    for path, blob in SEALED_RELEASE_FINAL_PARENT_BLOBS.items():
        result[path] = _git_bytes(repository, blob) + (
            f"\n<!-- CONFORM_SL2_TRANSITION:{path}: installed-evidence-disposition -->\n"
        ).encode("utf-8")
    return result


def _member_digests(contents: Mapping[str, bytes]) -> dict[str, str]:
    return {path: hashlib.sha256(value).hexdigest() for path, value in contents.items()}


def _archive_member_digests(path: Path) -> dict[str, str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return {
                member: hashlib.sha256(archive.read(member)).hexdigest()
                for member in archive.namelist()
                if not member.endswith("/")
            }
    with tarfile.open(path) as archive:
        result = {}
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            result[member.name] = hashlib.sha256(extracted.read()).hexdigest()
    return result


def _normalized_archive_member_digests(path: Path) -> dict[str, str]:
    """Return package-relative member digests for a wheel or source archive."""
    members = _archive_member_digests(path)
    if path.suffix == ".whl":
        return members
    return {
        member.split("/src/", 1)[1] if "/src/" in member else member: digest
        for member, digest in members.items()
    }


def _candidate_package_member_digests(
    repository: Path, candidate_commit: str
) -> dict[str, str]:
    """Return every packaged runtime source member from the sealed candidate tree."""
    paths = _git_output(
        repository,
        "ls-tree",
        "-r",
        "--name-only",
        candidate_commit,
        "--",
        "phase-loop-runtime/src/phase_loop_runtime",
    ).splitlines()
    prefix = "phase-loop-runtime/src/"
    assert paths and all(path.startswith(prefix) for path in paths)
    result = {}
    for path in paths:
        member = path.removeprefix(prefix)
        result[member] = hashlib.sha256(
            _git_bytes(repository, f"{candidate_commit}:{path}")
        ).hexdigest()
    return result


def _assert_package_archive_shape(label: str, path: Path, members: Mapping[str, str]) -> None:
    expected_suffix = {
        "direct-wheel": ".whl",
        "direct-sdist": ".tar.gz",
        "sdist-derived-wheel": ".whl",
    }[label]
    assert path.name.endswith(expected_suffix), label
    if expected_suffix == ".whl":
        assert any(member.endswith(".dist-info/METADATA") for member in members), label
        assert any(member.endswith(".dist-info/WHEEL") for member in members), label
        assert any(member.endswith(".dist-info/RECORD") for member in members), label
    else:
        raw_members = _archive_member_digests(path)
        roots = {member.split("/", 1)[0] for member in raw_members if "/" in member}
        assert len(roots) == 1, label
        root = next(iter(roots))
        assert f"{root}/PKG-INFO" in raw_members, label
        assert f"{root}/pyproject.toml" in raw_members, label


def _rebuilt_release_archive_digests(
    repository: Path,
    candidate_commit: str,
    source_date_epoch: str,
    direct_sdist: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Rebuild both release paths from their immutable source provenance."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        candidate_export = root / "candidate-export"
        candidate_export.mkdir()
        exported = subprocess.run(
            ["git", "archive", "--format=tar", candidate_commit],
            cwd=repository,
            capture_output=True,
            check=False,
        )
        assert exported.returncode == 0, "CONFORM_RED::sealed_release_evidence_git_object_missing"
        with tarfile.open(fileobj=io.BytesIO(exported.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                assert member.isfile() and not member.issym() and not member.islnk()
                assert not member.name.startswith("/") and ".." not in Path(member.name).parts
                extracted = archive.extractfile(member)
                assert extracted is not None
                destination = candidate_export / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(extracted.read())
        candidate_runtime = candidate_export / "phase-loop-runtime"
        build_env = {**os.environ, "SOURCE_DATE_EPOCH": source_date_epoch}
        direct_wheel_dist = root / "direct-wheel-dist"
        direct_sdist_dist = root / "direct-sdist-dist"
        for arguments, dist_root in (
            (("--wheel",), direct_wheel_dist),
            (("--sdist",), direct_sdist_dist),
        ):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    *arguments,
                    "--no-isolation",
                    "--outdir",
                    str(dist_root),
                    str(candidate_runtime),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=build_env,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
        rebuilt_direct_wheel = next(direct_wheel_dist.glob("*.whl"))
        rebuilt_direct_sdist = next(direct_sdist_dist.glob("*.tar.gz"))
        sdist_export = root / "recorded-sdist-export"
        sdist_export.mkdir()
        with tarfile.open(direct_sdist) as archive:
            _extract_tar_archive(archive, sdist_export)
        sdist_roots = [path for path in sdist_export.iterdir() if path.is_dir()]
        assert len(sdist_roots) == 1, "CONFORM_RED::sealed_release_evidence_derived_sdist"
        derived_wheel_dist = root / "sdist-derived-wheel-dist"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(derived_wheel_dist),
                str(sdist_roots[0]),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=build_env,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        rebuilt_derived_wheel = next(derived_wheel_dist.glob("*.whl"))
        return (
            {
                "direct-wheel": hashlib.sha256(rebuilt_direct_wheel.read_bytes()).hexdigest(),
                "sdist-derived-wheel": hashlib.sha256(rebuilt_derived_wheel.read_bytes()).hexdigest(),
            },
            _normalized_archive_member_digests(rebuilt_direct_sdist),
        )


def sealed_release_evidence(
    evidence_path: Path = SEALED_RELEASE_EVIDENCE_PATH,
    repository: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Verify runner-owned exact-candidate release evidence against real bytes."""
    assert evidence_path.is_file(), "CONFORM_RED::sealed_release_evidence_manifest_missing"
    evidence = load_json(evidence_path)
    assert evidence.get("owner") == "phase-loop-runner", "CONFORM_RED::sealed_release_evidence_not_runner_owned"
    assert evidence.get("source_date_epoch"), "CONFORM_RED::sealed_release_evidence_source_metadata_missing"
    forbidden = {"tbd", "todo", "placeholder", "ambient_head", "self_derived", "verified", "status"}
    assert not forbidden & set(evidence), "CONFORM_RED::sealed_release_evidence_placeholder"
    assert evidence.get("manifest_sha256") == _sealed_manifest_sha256(evidence), (
        "CONFORM_RED::sealed_release_evidence_manifest_digest_mismatch"
    )
    for key in ("candidate_commit", "candidate_tree", "final_commit", "final_tree"):
        value = evidence.get(key)
        assert isinstance(value, str) and len(value) in {40, 64} and all(character in "0123456789abcdef" for character in value), key
    for commit_key, tree_key in (("candidate_commit", "candidate_tree"), ("final_commit", "final_tree")):
        commit = evidence[commit_key]
        assert _git_output(repository, "rev-parse", f"{commit}^{{commit}}") == commit, (
            "CONFORM_RED::sealed_release_evidence_git_object_missing"
        )
        assert _git_output(repository, "rev-parse", f"{commit}^{{tree}}") == evidence[tree_key], (
            "CONFORM_RED::sealed_release_evidence_git_tree_mismatch"
        )
    candidate_paths = evidence.get("candidate_paths")
    candidate_members = evidence.get("candidate_members")
    candidate_parent_blobs = evidence.get("candidate_parent_blobs")
    assert candidate_paths == list(SEALED_RELEASE_CANDIDATE_PATHS), (
        "CONFORM_RED::sealed_release_evidence_candidate_inventory"
    )
    assert candidate_parent_blobs == SEALED_RELEASE_CANDIDATE_PARENT_BLOBS, (
        "CONFORM_RED::sealed_release_evidence_candidate_inventory"
    )
    assert isinstance(candidate_members, Mapping) and set(candidate_members) == set(
        SEALED_RELEASE_CANDIDATE_PATHS
    ), "CONFORM_RED::sealed_release_evidence_candidate_inventory"
    assert all(
        isinstance(path, str)
        and path.startswith("phase-loop-runtime/")
        and not path.startswith("/")
        and ".." not in Path(path).parts
        and isinstance(digest, str)
        and len(digest) == 64
        for path, digest in candidate_members.items()
    ), "CONFORM_RED::sealed_release_evidence_candidate_inventory"
    parent = _sealed_candidate_parent(repository, evidence["candidate_commit"])
    changed_paths = _git_output(
        repository,
        "diff",
        "--name-only",
        parent,
        evidence["candidate_commit"],
    ).splitlines()
    assert tuple(sorted(changed_paths)) == SEALED_RELEASE_CANDIDATE_PATHS, (
        "CONFORM_RED::sealed_release_evidence_candidate_inventory"
    )
    candidate_bytes: dict[str, bytes] = {}
    for candidate_path in SEALED_RELEASE_CANDIDATE_PATHS:
        digest = candidate_members[candidate_path]
        actual = subprocess.run(
            ["git", "show", f"{evidence['candidate_commit']}:{candidate_path}"],
            cwd=repository,
            capture_output=True,
            check=False,
        )
        assert actual.returncode == 0, "CONFORM_RED::sealed_release_evidence_candidate_inventory"
        assert hashlib.sha256(actual.stdout).hexdigest() == digest, (
            "CONFORM_RED::sealed_release_evidence_candidate_inventory"
        )
        candidate_bytes[candidate_path] = actual.stdout
        parent_member = subprocess.run(
            ["git", "show", f"{parent}:{candidate_path}"],
            cwd=repository,
            capture_output=True,
            check=False,
        )
        expected_parent_blob = SEALED_RELEASE_CANDIDATE_PARENT_BLOBS[candidate_path]
        if expected_parent_blob is None:
            assert parent_member.returncode != 0, "CONFORM_RED::sealed_release_evidence_candidate_transition"
        else:
            assert parent_member.returncode == 0
            assert _git_output(repository, "rev-parse", f"{parent}:{candidate_path}") == expected_parent_blob
            assert actual.stdout != parent_member.stdout, (
                "CONFORM_RED::sealed_release_evidence_candidate_transition"
            )
    assert b"CAPABILITY = 'candidate'" not in b"".join(candidate_bytes.values()), (
        "CONFORM_RED::sealed_release_evidence_candidate_toy"
    )
    assert CAPABILITY_MARKER.encode("utf-8") in candidate_bytes[
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_schema.py"
    ], "CONFORM_RED::sealed_release_evidence_candidate_toy"
    assert b"verify_conform_evidence_records" in candidate_bytes[
        "phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py"
    ], "CONFORM_RED::sealed_release_evidence_candidate_toy"
    assert b"outside-agent-validate" in candidate_bytes[
        "phase-loop-runtime/src/phase_loop_runtime/cli.py"
    ], "CONFORM_RED::sealed_release_evidence_candidate_toy"
    assert parent != evidence["candidate_commit"]
    final_parent = _git_output(repository, "rev-parse", f"{evidence['final_commit']}^")
    assert final_parent == evidence["candidate_commit"], (
        "CONFORM_RED::sealed_release_evidence_final_transition"
    )
    final_paths = evidence.get("final_paths")
    final_members = evidence.get("final_members")
    final_parent_blobs = evidence.get("final_parent_blobs")
    assert final_paths == list(SEALED_RELEASE_FINAL_PATHS), (
        "CONFORM_RED::sealed_release_evidence_final_transition"
    )
    assert final_parent_blobs == SEALED_RELEASE_FINAL_PARENT_BLOBS, (
        "CONFORM_RED::sealed_release_evidence_final_transition"
    )
    assert isinstance(final_members, Mapping) and set(final_members) == set(
        SEALED_RELEASE_FINAL_PATHS
    ), "CONFORM_RED::sealed_release_evidence_final_transition"
    changed_final_paths = _git_output(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        evidence["final_commit"],
    ).splitlines()
    assert tuple(sorted(changed_final_paths)) == SEALED_RELEASE_FINAL_PATHS, (
        "CONFORM_RED::sealed_release_evidence_final_transition"
    )
    for final_path in SEALED_RELEASE_FINAL_PATHS:
        assert _git_output(repository, "rev-parse", f"{parent}:{final_path}") == (
            SEALED_RELEASE_FINAL_PARENT_BLOBS[final_path]
        )
        candidate_member = subprocess.run(
            ["git", "show", f"{evidence['candidate_commit']}:{final_path}"],
            cwd=repository,
            capture_output=True,
            check=False,
        )
        final_member = subprocess.run(
            ["git", "show", f"{evidence['final_commit']}:{final_path}"],
            cwd=repository,
            capture_output=True,
            check=False,
        )
        assert candidate_member.returncode == final_member.returncode == 0
        assert hashlib.sha256(final_member.stdout).hexdigest() == final_members[final_path]
        assert candidate_member.stdout != final_member.stdout, (
            "CONFORM_RED::sealed_release_evidence_final_transition"
        )
    archives = evidence.get("archives")
    assert isinstance(archives, dict) and set(archives) == {"direct-wheel", "direct-sdist", "sdist-derived-wheel"}
    source_date_epoch = evidence["source_date_epoch"]
    assert isinstance(source_date_epoch, str) and source_date_epoch.isdecimal(), (
        "CONFORM_RED::sealed_release_evidence_source_metadata_missing"
    )
    candidate_package_members = _candidate_package_member_digests(
        repository, evidence["candidate_commit"]
    )
    for label, archive in archives.items():
        assert isinstance(archive, dict)
        path_value = archive.get("path")
        assert isinstance(path_value, str), label
        path = Path(path_value)
        assert path.is_file(), label
        assert archive.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest(), label
        members = archive.get("members")
        assert members == SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS, label
        actual_members = _normalized_archive_member_digests(path)
        assert all(
            not member.startswith("/") and ".." not in Path(member).parts
            for member in actual_members
        ), label
        _assert_package_archive_shape(label, path, actual_members)
        contract_members = {
            member: digest
            for member, digest in actual_members.items()
            if member.startswith("phase_loop_runtime/conformance/_contract/")
        }
        assert contract_members == SEALED_RELEASE_ARCHIVE_MEMBER_DIGESTS, label
        assert all(
            actual_members.get(member) == digest
            for member, digest in candidate_package_members.items()
        ), label
        vendor_member = "phase_loop_runtime/conformance/_contract/VENDOR.json"
        assert vendor_member in contract_members, label
        vendor_bytes = (
            zipfile.ZipFile(path).read(vendor_member)
            if path.suffix == ".whl"
            else next(
                archive.extractfile(member).read()
                for archive in [tarfile.open(path)]
                for member in archive.getmembers()
                if member.isfile()
                and (member.name.split("/src/", 1)[1] if "/src/" in member.name else member.name)
                == vendor_member
            )
        )
        vendor = json.loads(vendor_bytes)
        vendor_records = {
            (record["source_path"], record["mirror_path"], record["raw_byte_sha256"])
            for record in vendor.get("files", [])
        }
        assert vendor_records == set(IMMUTABLE_SPEC_V0_2_1_FILES), label
        assert len(vendor_records) == len(vendor.get("files", [])) == 15, label
        for relative, digest in IMMUTABLE_SPEC_V0_2_1_DIGESTS.items():
            member = "phase_loop_runtime/conformance/_contract/" + relative
            assert contract_members.get(member) == digest, (label, member)
    rebuilt_wheel_digests, rebuilt_sdist_members = _rebuilt_release_archive_digests(
        repository,
        evidence["candidate_commit"],
        source_date_epoch,
        Path(archives["direct-sdist"]["path"]),
    )
    assert _normalized_archive_member_digests(Path(archives["direct-sdist"]["path"])) == rebuilt_sdist_members, (
        "CONFORM_RED::sealed_release_evidence_archive_provenance",
        "direct-sdist",
    )
    for label in ("direct-wheel", "sdist-derived-wheel"):
        assert archives[label]["sha256"] == rebuilt_wheel_digests[label], (
            "CONFORM_RED::sealed_release_evidence_archive_provenance",
            label,
        )
    a2_package_evidence = evidence.get("a2_package_evidence")
    assert isinstance(a2_package_evidence, Mapping), (
        "CONFORM_RED::sealed_release_evidence_a2_package_missing"
    )
    expected_a2_package_evidence = _build_a2_package_evidence(
        candidate_commit=evidence["candidate_commit"],
        candidate_tree=evidence["candidate_tree"],
        candidate_members=candidate_members,
        archives=archives,
    )
    assert dict(a2_package_evidence) == {
        key: value
        for key, value in expected_a2_package_evidence.items()
        if key != "a2_package_evidence_sha256"
    }, (
        "CONFORM_RED::sealed_release_evidence_a2_package_mismatch"
    )
    assert evidence.get("a2_package_evidence_sha256") == expected_a2_package_evidence[
        "a2_package_evidence_sha256"
    ], "CONFORM_RED::sealed_release_evidence_a2_package_digest_mismatch"
    return evidence


def _looks_like_canonical_contract_copy(path: Path) -> bool:
    """Detect a canonical artifact even if its bytes were reformatted or edited.

    The test is intentionally narrower than a textual version-string search: normal
    production consumers may mention the contract version, but only a schema,
    manifest, vector, or oracle-shaped source is a forbidden second authority copy.
    """
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() in set(IMMUTABLE_SPEC_V0_2_1_DIGESTS.values()):
        return True
    if path.suffix == ".py":
        source = raw.decode("utf-8", errors="replace")
        return "def route(" in source and "def blocker_class_of(" in source
    if path.suffix != ".json":
        return False
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(value, Mapping):
        return False
    if _matches_canonical_schema_shape(value):
        return True
    if _matches_canonical_manifest_shape(value):
        return True
    if _matches_canonical_route_vector_shape(value):
        return True
    return (
        value.get("submission_schema_version") == "outside_agent_submission.v0.1"
        and value.get("claim_posture") == "claims_only"
        and value.get("acceptance_truth_owner") == "governed_pipeline"
        and isinstance(value.get("evidence_refs"), list)
    )


def _matches_canonical_route_vector_shape(value: Mapping[str, Any]) -> bool:
    canonical = load_json(
        FIXTURE_ROOT
        / "test-vectors/outside-agent/invalid-unsupported-verdict.json"
    )
    canonical_keys = set(canonical)
    if len(set(value) & canonical_keys) < len(canonical_keys) - 1:
        return False
    blocker = value.get("blocker")
    canonical_blocker = canonical["blocker"]
    return isinstance(blocker, Mapping) and (
        len(set(blocker) & set(canonical_blocker))
        >= len(canonical_blocker) - 1
    )


def _matches_canonical_schema_shape(value: Mapping[str, Any]) -> bool:
    """Recognize the producer schemas by structure, never mutable labels."""
    if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        return False
    if value.get("type") != "object" or value.get("additionalProperties") is not False:
        return False
    properties = value.get("properties")
    if not isinstance(properties, Mapping):
        return False
    candidate_keys = set(properties)
    for relative in (
        "schemas/outside-agent-submission.schema.json",
        "schemas/outside-agent-route-verdict.schema.json",
    ):
        canonical = load_json(FIXTURE_ROOT / relative)
        canonical_properties = canonical.get("properties")
        assert isinstance(canonical_properties, Mapping)
        canonical_keys = set(canonical_properties)
        # Altering a title, $id, formatting, or one nested/top-level property
        # leaves this producer-specific structural signature intact.  A wholly
        # unrelated JSON schema cannot match the near-complete key set.
        if len(candidate_keys & canonical_keys) >= len(canonical_keys) - 1:
            return True
    return False


def _matches_canonical_manifest_shape(value: Mapping[str, Any]) -> bool:
    vectors = value.get("vectors")
    if not isinstance(vectors, list):
        return False
    canonical_ids = {entry["case_id"] for entry in vector_entries()}
    candidate_ids = {
        entry.get("case_id")
        for entry in vectors
        if isinstance(entry, Mapping) and isinstance(entry.get("case_id"), str)
    }
    return len(candidate_ids & canonical_ids) >= len(canonical_ids) - 1


def assert_packaged_contract_mirror() -> None:
    mirror_root = packaged_contract_mirror_root()
    vendor_path = mirror_root / "VENDOR.json"
    assert vendor_path.exists(), (
        "CONFORM_RED::digest_enumerated_contract_mirror_missing: "
        "phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/VENDOR.json"
    )
    vendor = load_json(vendor_path)
    assert vendor["source_repo"] == "Consiliency/spec"
    assert vendor["source_ref"] == "v0.2.1"
    assert vendor["source_commit"] == "b862f977897a7b87c4419680a3e83735d4ff07b0"
    vendor_records = tuple(
        (
            entry.get("source_path"),
            entry.get("mirror_path"),
            entry.get("raw_byte_sha256"),
        )
        for entry in vendor["files"]
    )
    assert len(vendor_records) == len(set(vendor_records)) == 15
    assert set(vendor_records) == set(IMMUTABLE_SPEC_V0_2_1_FILES)
    actual_paths = {
        path.relative_to(mirror_root).as_posix()
        for path in mirror_root.rglob("*")
        if path.is_file() and path.name != "VENDOR.json"
    }
    expected_paths = set(fixture_paths())
    assert actual_paths == expected_paths
    for relative, expected in IMMUTABLE_SPEC_V0_2_1_DIGESTS.items():
        assert hashlib.sha256((mirror_root / relative).read_bytes()).hexdigest() == expected
    copied, scanned = find_non_enumerated_canonical_copies(REPO_ROOT)
    assert scanned > 0, PRODUCTION_SCAN_ROOT_LITERAL
    assert copied == ()


def _red_anchor(nodeid: str) -> str:
    return CONFORM_ACTIVATED_RED_ANCHORS[nodeid]


@dataclass(frozen=True)
class CanonicalMigrationCase:
    """One named legacy node's activated canonical contract.

    ``mutation`` is always applied to a canonical-valid producer payload.  A
    negative case is therefore never allowed to pass by re-running a clean
    acceptance check or by relying on the legacy five-field dialect.
    """

    role: str
    seam: str
    mutation: str | None = None
    expected_code: str | None = None
    expected_exit: int | None = None


def _case(role: str, seam: str, mutation: str | None = None, expected_code: str | None = None, expected_exit: int | None = None) -> CanonicalMigrationCase:
    return CanonicalMigrationCase(role, seam, mutation, expected_code, expected_exit)


CONFORM_CANONICAL_CASES = {
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_builds_clean_advisory_evidence_without_external_access": _case("advisory_valid_acceptance_without_network_or_secrets", "advisory"),
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_serialized_advisory_evidence_is_deterministic_and_metadata_only": _case("advisory_deterministic_metadata_serialization", "advisory"),
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_redaction_blocker_maps_to_exit_code_3": _case("advisory_raw_payload_schema_rejection", "advisory", "raw_payload", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::test_provenance_blocker_maps_to_exit_code_4": _case("advisory_path_traversal_schema_rejection", "advisory", "path_traversal", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_clean_pass_outputs_advisory_json": _case("advisory_cli_valid_acceptance", "preflight_cli"),
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_redaction_violation_returns_exit_3": _case("advisory_cli_raw_payload_schema_rejection", "preflight_cli", "raw_payload", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_provenance_failure_returns_exit_4": _case("advisory_cli_path_traversal_schema_rejection", "preflight_cli", "path_traversal", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_advisory_cli.py::test_cli_writes_output_file_with_stdout_payload": _case("advisory_cli_stdout_output_byte_parity", "preflight_cli"),
    "phase-loop-runtime/tests/test_outside_agent_advisory_fixtures.py::test_advisory_fixture_outputs_match_stable_summaries": _case("advisory_fixture_deterministic_serialization", "advisory"),
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_sdk_serialization_never_claims_merge_authority": _case("sdk_authority_boundary", "real"),
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_stdout_never_claims_merge_authority": _case("validation_cli_stdout_authority_boundary", "validate_cli"),
    "phase-loop-runtime/tests/test_outside_agent_authority_boundary.py::test_cli_output_file_never_claims_merge_authority": _case("validation_cli_output_authority_boundary", "validate_cli"),
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_public_core_api_returns_typed_metadata_only_verdict": _case("core_typed_metadata_only_acceptance", "core"),
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_core_api_is_deterministic_and_does_not_require_secrets": _case("core_deterministic_secretless_acceptance", "core"),
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::test_validation_does_not_use_network_or_provider_credentials": _case("core_no_network_no_provider_credentials", "core"),
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_fixture_invocations_do_not_run_vectors_for_live_validation": _case("live_validation_does_not_run_vectors", "real"),
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::test_ci_release_vector_evidence_runs_pinned_vector_runner": _case("pinned_vector_runner_corpus_evidence", "vector"),
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_clean_pass_writes_file_and_stdout": _case("validation_cli_valid_stdout_output_byte_parity", "validate_cli"),
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_redaction_violation_returns_exit_3": _case("validation_cli_raw_payload_schema_rejection", "validate_cli", "raw_payload", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_provenance_failure_returns_exit_4": _case("validation_cli_path_traversal_schema_rejection", "validate_cli", "path_traversal", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_contract_pin_failure_returns_exit_5": _case("validation_cli_contract_pin_exit_parity", "validate_cli", "unsupported_schema", "unsupported_schema_version", 5),
    "phase-loop-runtime/tests/test_outside_agent_real_cli.py::test_cli_other_conformance_blockers_return_exit_6": _case("validation_cli_unknown_identity_posture_schema_rejection", "validate_cli", "unknown_producer", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serializes_clean_governed_pipeline_verdict_shape": _case("validation_output_closed_shape", "real"),
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_real_verdict_is_deterministic_json": _case("validation_output_deterministic_serialization", "real"),
    "phase-loop-runtime/tests/test_outside_agent_real_output.py::test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields": _case("validation_output_raw_payload_schema_rejection", "real", "raw_payload", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_wraps_core_once_with_metadata_only_evidence": _case("validation_runtime_core_once_metadata_only", "real"),
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_redaction_violation_maps_to_exit_3": _case("validation_runtime_raw_payload_schema_rejection", "real", "raw_payload", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_provenance_failure_maps_to_exit_4": _case("validation_runtime_path_traversal_schema_rejection", "real", "path_traversal", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_contract_pin_failure_maps_to_exit_5": _case("validation_runtime_contract_pin_exit_parity", "real", "unsupported_schema", "unsupported_schema_version", 5),
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_other_conformance_blocker_maps_to_exit_6": _case("validation_runtime_unknown_identity_posture_schema_rejection", "real", "unknown_producer", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::test_real_validator_rejects_absolute_submitted_refs_without_raw_paths": _case("validation_runtime_normalized_ref_schema_rejection", "real", "path_traversal", "schema_validation_failed", 2),
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_real_validator_and_advisory_outputs_share_pinned_metadata_only_contract_evidence": _case("release_surface_pinned_metadata_only_contract", "real"),
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_accepts_supported_submission_kinds": _case("schema_accepts_all_three_canonical_kinds", "schema"),
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_schema_version_fails_closed": _case("schema_typed_unsupported_version_rejection", "schema", "unsupported_schema", "unsupported_schema_version"),
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unsupported_submission_kind_fails_closed": _case("schema_typed_unsupported_kind_rejection", "schema", "unsupported_kind", "unsupported_submission_kind"),
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_unknown_top_level_field_fails_closed": _case("schema_typed_unknown_field_rejection", "schema", "unknown_field", "unknown_field"),
    "phase-loop-runtime/tests/test_outside_agent_schema_validation.py::test_missing_required_metadata_fails_closed": _case("schema_typed_missing_required_rejection", "schema", "missing_required", "schema_validation_failed"),
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_vector_runner_matches_positive_and_negative_expected_outcomes": _case("vectors_exact_corpus_valid_invalid_parity", "vector"),
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_unknown_vector_schema_version_fails_closed": _case("vectors_typed_unknown_schema_rejection", "vector", "vector_unknown_schema", "unsupported_schema_version"),
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_missing_expected_outcome_fails_closed": _case("vectors_typed_missing_expected_rejection", "vector", "vector_missing_expected", "schema_validation_failed"),
    "phase-loop-runtime/tests/test_outside_agent_vectors.py::test_manifest_digest_drift_fails_closed": _case("vectors_typed_manifest_digest_rejection", "vector", "vector_digest_drift", "digest_mismatch"),
    "phase-loop-runtime/tests/test_outside_agent_redaction.py::test_core_verdict_contains_only_metadata_refs_and_digests": _case("core_metadata_only_projection", "redaction"),
    "phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_no_copied_canonical_outside_agent_schema_or_vectors": _case("exact_enumerated_contract_mirror_only", "mirror"),
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary": _case("release_handoff_complete_package_dispatch_surface", "release_handoff"),
    "phase-loop-runtime/tests/test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch": _case("public_docs_complete_release_boundary_surface", "public_docs"),
}


def _mutated_canonical_submission(mutation: str | None) -> dict[str, Any]:
    payload = clean_canonical_submission()
    if mutation is None:
        return payload
    evidence = payload["evidence_refs"][0]
    if mutation == "raw_payload":
        payload["raw_payload"] = {"body": "CONFORM-SL0-raw-sentinel"}
    elif mutation == "path_traversal":
        evidence["repo_relative_path"] = "../CONFORM-SL0-path-sentinel"
    elif mutation == "unsupported_schema":
        payload["submission_schema_version"] = "outside_agent_submission.v9"
    elif mutation == "unsupported_kind":
        payload["submission_kind"] = "unsupported_kind"
    elif mutation == "unknown_field":
        payload["unexpected_field"] = True
    elif mutation == "missing_required":
        payload.pop("summary")
    elif mutation == "unknown_producer":
        payload["producer"]["identity_posture"] = "unknown"
    else:
        raise AssertionError(f"unknown canonical mutation: {mutation}")
    return payload


def _assert_status_and_codes(nodeid: str, status: str, codes: set[str], case: CanonicalMigrationCase) -> None:
    anchor = CONFORM_ACTIVATED_RED_ANCHORS.get(nodeid, f"CONFORM_GREEN::{case.role}")
    if case.expected_code is None:
        assert status == "pass", anchor
        assert codes == set(), anchor
    else:
        assert status == "blocked", anchor
        assert case.expected_code in codes, anchor


NAMED_SAFETY_NODE_IDS = {
    "phase-loop-runtime/tests/test_outside_agent_advisory.py::"
    "test_builds_clean_advisory_evidence_without_external_access": "advisory_network",
    "phase-loop-runtime/tests/test_outside_agent_core_api.py::"
    "test_validation_does_not_use_network_or_provider_credentials": "network",
    "phase-loop-runtime/tests/test_outside_agent_real_ci.py::"
    "test_fixture_invocations_do_not_run_vectors_for_live_validation": "vectors",
    "phase-loop-runtime/tests/test_outside_agent_real_runtime.py::"
    "test_real_validator_wraps_core_once_with_metadata_only_evidence": "core_once",
}


def _assert_named_safety_observables(
    nodeid: str,
    *,
    network_calls: list[str] | None = None,
    credential_reads: list[str] | None = None,
    vectors_executed: bool | None = None,
    vector_calls: int | None = None,
    core_calls: int | None = None,
) -> None:
    """Reject status/code-only substitutes for the named migrated guarantees."""
    guarantee = NAMED_SAFETY_NODE_IDS[nodeid]
    if guarantee in {"advisory_network", "network"}:
        assert network_calls == [], _red_anchor(nodeid)
        assert credential_reads == [], _red_anchor(nodeid)
    elif guarantee == "vectors":
        assert vectors_executed is False, _red_anchor(nodeid)
        assert vector_calls == 0, _red_anchor(nodeid)
    elif guarantee == "core_once":
        assert core_calls == 1, _red_anchor(nodeid)
    else:
        raise AssertionError(f"unknown named safety guarantee: {guarantee}")


def assert_status_code_only_replacement_is_rejected() -> None:
    """Directly mutate each named node to status/code-only and require rejection."""
    for nodeid in NAMED_SAFETY_NODE_IDS:
        try:
            _assert_named_safety_observables(nodeid)
        except AssertionError:
            continue
        raise AssertionError(f"CONFORM_RED::status_code_only_replacement_survived:{nodeid}")


def _assert_core_uses_no_network_or_provider_credentials(
    nodeid: str,
    *,
    core_validator: Any | None = None,
) -> None:
    from phase_loop_runtime.conformance.outside_agent_core import (
        validate_outside_agent_submission,
    )

    network_calls: list[str] = []
    credential_reads: list[str] = []
    validator = core_validator or validate_outside_agent_submission
    original_environ_get = os.environ.get
    original_environ_getitem = type(os.environ).__getitem__

    def rejected_network(*_args: object, **_kwargs: object) -> None:
        network_calls.append("network")
        raise AssertionError(_red_anchor(nodeid))

    def guarded_credential_read(route: str, key: object, read: Any) -> Any:
        if isinstance(key, str) and any(
            token in key.upper() for token in ("KEY", "TOKEN", "SECRET", "CREDENTIAL")
        ):
            credential_reads.append(route)
            raise AssertionError(_red_anchor(nodeid))
        return read()

    def guarded_getenv(key: str, default: str | None = None) -> str | None:
        return guarded_credential_read(
            "os.getenv", key, lambda: original_environ_get(key, default)
        )

    def guarded_environ_get(key: str, default: str | None = None) -> str | None:
        return guarded_credential_read(
            "os.environ.get", key, lambda: original_environ_get(key, default)
        )

    def guarded_environ_getitem(key: object) -> str:
        return guarded_credential_read(
            "os.environ[]",
            key,
            lambda: original_environ_getitem(os.environ, key),
        )

    with (
        mock.patch.object(os, "system", side_effect=rejected_network),
        mock.patch.object(os, "popen", side_effect=rejected_network),
        mock.patch.object(subprocess, "Popen", side_effect=rejected_network),
        mock.patch.object(subprocess, "run", side_effect=rejected_network),
        mock.patch.object(socket.socket, "connect", side_effect=rejected_network),
        mock.patch.object(socket.socket, "connect_ex", side_effect=rejected_network),
        mock.patch.object(socket.socket, "sendto", side_effect=rejected_network),
        mock.patch.object(socket, "create_connection", side_effect=rejected_network),
        mock.patch.object(socket, "getaddrinfo", side_effect=rejected_network),
        mock.patch.object(socket, "gethostbyaddr", side_effect=rejected_network),
        mock.patch.object(socket, "gethostbyname", side_effect=rejected_network),
        mock.patch.object(socket, "gethostbyname_ex", side_effect=rejected_network),
        mock.patch.object(urllib_request, "urlopen", side_effect=rejected_network),
        mock.patch.object(os, "getenv", side_effect=guarded_getenv),
        mock.patch.object(os.environ, "get", side_effect=guarded_environ_get),
        mock.patch.object(
            type(os.environ), "__getitem__", side_effect=guarded_environ_getitem
        ),
    ):
        verdict = validator(clean_canonical_submission())
    _assert_status_and_codes(nodeid, verdict.status.value, {b.code for b in verdict.blockers}, CONFORM_CANONICAL_CASES[nodeid])
    _assert_named_safety_observables(
        nodeid, network_calls=network_calls, credential_reads=credential_reads
    )


def _assert_advisory_uses_no_external_access(
    nodeid: str, *, advisory_builder: Any | None = None
) -> None:
    from phase_loop_runtime.conformance.outside_agent_advisory import (
        build_outside_agent_advisory_evidence,
        serialize_outside_agent_advisory_evidence,
    )

    network_calls: list[str] = []
    builder = advisory_builder or build_outside_agent_advisory_evidence

    def rejected_network(*_args: object, **_kwargs: object) -> None:
        network_calls.append("network")
        raise AssertionError(_red_anchor(nodeid))

    with (
        mock.patch.object(os, "system", side_effect=rejected_network),
        mock.patch.object(os, "popen", side_effect=rejected_network),
        mock.patch.object(subprocess, "Popen", side_effect=rejected_network),
        mock.patch.object(subprocess, "run", side_effect=rejected_network),
        mock.patch.object(socket.socket, "connect", side_effect=rejected_network),
        mock.patch.object(socket.socket, "connect_ex", side_effect=rejected_network),
        mock.patch.object(socket.socket, "sendto", side_effect=rejected_network),
        mock.patch.object(socket, "create_connection", side_effect=rejected_network),
        mock.patch.object(socket, "getaddrinfo", side_effect=rejected_network),
        mock.patch.object(socket, "gethostbyaddr", side_effect=rejected_network),
        mock.patch.object(socket, "gethostbyname", side_effect=rejected_network),
        mock.patch.object(socket, "gethostbyname_ex", side_effect=rejected_network),
        mock.patch.object(urllib_request, "urlopen", side_effect=rejected_network),
    ):
        rendered = serialize_outside_agent_advisory_evidence(
            builder(clean_canonical_submission())
        )
    _assert_status_and_codes(
        nodeid,
        rendered["status"],
        {blocker["code"] for blocker in rendered["blockers"]},
        CONFORM_CANONICAL_CASES[nodeid],
    )
    _assert_named_safety_observables(
        nodeid, network_calls=network_calls, credential_reads=[]
    )


def assert_named_safety_mutations_rejected() -> None:
    """Kill double-call and all provider-credential-read safety mutations."""
    core_once_nodeid = next(
        nodeid
        for nodeid, guarantee in NAMED_SAFETY_NODE_IDS.items()
        if guarantee == "core_once"
    )
    try:
        _assert_named_safety_observables(core_once_nodeid, core_calls=2)
    except AssertionError:
        pass
    else:
        raise AssertionError("CONFORM_RED::double_core_validator_call_survived")

    credential_nodeid = next(
        nodeid
        for nodeid, guarantee in NAMED_SAFETY_NODE_IDS.items()
        if guarantee == "network"
    )
    from phase_loop_runtime.conformance.outside_agent_core import (
        validate_outside_agent_submission,
    )

    credential_routes = {
        "os.getenv": lambda: os.getenv("PROVIDER_TOKEN"),
        "os.environ.get": lambda: os.environ.get("PROVIDER_TOKEN"),
        "os.environ[]": lambda: os.environ["PROVIDER_TOKEN"],
    }
    for route, read_credential in credential_routes.items():
        def mutated_validator(submission: object, *, read_credential: Any = read_credential) -> Any:
            read_credential()
            return validate_outside_agent_submission(submission)

        try:
            _assert_core_uses_no_network_or_provider_credentials(
                credential_nodeid, core_validator=mutated_validator
            )
        except AssertionError:
            continue
        raise AssertionError(f"CONFORM_RED::credential_read_mutation_survived:{route}")

    advisory_nodeid = next(
        nodeid
        for nodeid, guarantee in NAMED_SAFETY_NODE_IDS.items()
        if guarantee == "advisory_network"
    )
    from phase_loop_runtime.conformance.outside_agent_advisory import (
        build_outside_agent_advisory_evidence,
    )

    external_routes = {
        "os.popen": lambda: os.popen("true"),
        "subprocess.Popen": lambda: subprocess.Popen([sys.executable, "-c", ""]),
        "socket.connect": lambda: socket.socket().connect(("127.0.0.1", 9)),
        "socket.connect_ex": lambda: socket.socket().connect_ex(("127.0.0.1", 9)),
        "socket.sendto": lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
            b"CONFORM", ("127.0.0.1", 9)
        ),
    }
    for route, external_access in external_routes.items():
        def mutated_builder(
            submission: object, *, external_access: Any = external_access
        ) -> Any:
            external_access()
            return build_outside_agent_advisory_evidence(submission)

        try:
            _assert_advisory_uses_no_external_access(
                advisory_nodeid, advisory_builder=mutated_builder
            )
        except AssertionError:
            continue
        raise AssertionError(f"CONFORM_RED::external_access_mutation_survived:{route}")


def _assert_live_validation_runs_zero_vectors(nodeid: str) -> None:
    from phase_loop_runtime.conformance import outside_agent_real, outside_agent_vectors
    from phase_loop_runtime.conformance.outside_agent_real_output import (
        serialize_outside_agent_validation_verdict,
    )

    vector_calls: list[object] = []

    def rejected_vector_execution(*args: object, **kwargs: object) -> None:
        vector_calls.append((args, kwargs))
        raise AssertionError(_red_anchor(nodeid))

    patches = [
        mock.patch.object(
            outside_agent_vectors,
            "run_outside_agent_vectors",
            side_effect=rejected_vector_execution,
        )
    ]
    if hasattr(outside_agent_real, "run_outside_agent_vectors"):
        patches.append(
            mock.patch.object(
                outside_agent_real,
                "run_outside_agent_vectors",
                side_effect=rejected_vector_execution,
            )
        )
    with patches[0]:
        if len(patches) == 2:
            with patches[1]:
                verdict = outside_agent_real.build_outside_agent_validation_verdict(
                    clean_canonical_submission()
                )
        else:
            verdict = outside_agent_real.build_outside_agent_validation_verdict(
                clean_canonical_submission()
            )
    rendered = serialize_outside_agent_validation_verdict(verdict)
    _assert_status_and_codes(
        nodeid, rendered["status"], {b["code"] for b in rendered["blockers"]}, CONFORM_CANONICAL_CASES[nodeid]
    )
    _assert_named_safety_observables(
        nodeid,
        vectors_executed=rendered.get("vectors_executed"),
        vector_calls=len(vector_calls),
    )


def _assert_real_validator_wraps_core_once(nodeid: str) -> None:
    from phase_loop_runtime.conformance.outside_agent_core import (
        validate_outside_agent_submission,
    )
    from phase_loop_runtime.conformance.outside_agent_real import (
        build_outside_agent_validation_verdict,
    )
    from phase_loop_runtime.conformance.outside_agent_real_output import (
        serialize_outside_agent_validation_verdict,
    )

    payload = clean_canonical_submission()
    calls: list[object] = []

    def core(submission: object, *, contract_pin: object):
        calls.append((submission, contract_pin))
        return validate_outside_agent_submission(submission, contract_pin=contract_pin)

    verdict = build_outside_agent_validation_verdict(payload, core_validator=core)
    rendered = serialize_outside_agent_validation_verdict(verdict)
    _assert_status_and_codes(
        nodeid, rendered["status"], {b["code"] for b in rendered["blockers"]}, CONFORM_CANONICAL_CASES[nodeid]
    )
    assert calls and calls[0][0] == payload, _red_anchor(nodeid)
    _assert_named_safety_observables(nodeid, core_calls=len(calls))


def _run_cli_case(nodeid: str, case: CanonicalMigrationCase, command: str) -> None:
    payload = _mutated_canonical_submission(case.mutation)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        submission_path = root / "canonical-submission.json"
        output_path = root / "canonical-output.json"
        submission_path.write_text(json.dumps(payload), encoding="utf-8")
        argv = [sys.executable, "-m", "phase_loop_runtime.cli", command, str(submission_path)]
        if command == "outside-agent-validate" or case.role.endswith("output_byte_parity"):
            argv.extend(["--output", str(output_path)])
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
        rendered = json.loads(completed.stdout)
        _assert_status_and_codes(nodeid, rendered["status"], {b["code"] for b in rendered["blockers"]}, case)
        expected_exit = case.expected_exit if case.expected_exit is not None else 0
        assert completed.returncode == expected_exit, _red_anchor(nodeid)
        if output_path.exists():
            assert output_path.read_text(encoding="utf-8") == completed.stdout, _red_anchor(nodeid)
        if "authority_boundary" in case.role:
            assert "accepted_for_merge" not in completed.stdout
            assert "merge_verdict" not in completed.stdout


def _assert_legacy_same_version_payload_is_rejected(nodeid: str) -> None:
    """Prove strict marker mode has no five-field compatibility bypass."""
    from phase_loop_runtime.conformance.outside_agent_core import (
        validate_outside_agent_submission,
    )

    legacy_payload = {
        "submission_schema_version": "outside_agent_submission.v0.1",
        "submission_kind": "work_request",
        "metadata": {"submission_id": "legacy-oa-1", "content_digest": "a" * 64},
        "provenance_refs": [{"ref": "requests/legacy-oa-1.json", "digest": "b" * 64}],
        "evidence_refs": [{"ref": "evidence/legacy-oa-1.json", "digest": "c" * 64}],
    }
    verdict = validate_outside_agent_submission(legacy_payload)
    assert verdict.status.value == "blocked", _red_anchor(nodeid)
    assert {blocker.code for blocker in verdict.blockers} == {"schema_validation_failed"}, (
        _red_anchor(nodeid)
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        submission_path = root / "legacy-submission.json"
        submission_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
        for command in ("outside-agent-preflight", "outside-agent-validate"):
            output_path = root / f"{command}.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "phase_loop_runtime.cli",
                    command,
                    str(submission_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            rendered = json.loads(completed.stdout)
            assert completed.returncode == 2, _red_anchor(nodeid)
            assert rendered["status"] == "blocked", _red_anchor(nodeid)
            assert {blocker["code"] for blocker in rendered["blockers"]} == {
                "schema_validation_failed"
            }, _red_anchor(nodeid)
            assert output_path.read_text(encoding="utf-8") == completed.stdout, (
                _red_anchor(nodeid)
            )


def _run_vector_case(nodeid: str, case: CanonicalMigrationCase) -> None:
    from phase_loop_runtime.conformance.outside_agent_vectors import run_outside_agent_vectors

    candidate_manifest = copy.deepcopy(manifest())
    if case.mutation == "vector_unknown_schema":
        candidate_manifest["manifest_schema_version"] = "outside_agent_vector_manifest.v9"
    elif case.mutation == "vector_missing_expected":
        del candidate_manifest["vectors"][0]["expected_valid"]
    elif case.mutation == "vector_digest_drift":
        candidate_manifest["manifest_digest"] = "0" * 64
    results = run_outside_agent_vectors(candidate_manifest)
    if case.expected_code is None:
        assert {result.vector_name for result in results} == {row["case_id"] for row in vector_entries()}, _red_anchor(nodeid)
        assert all(result.matched for result in results), _red_anchor(nodeid)
        return
    assert len(results) == 1, _red_anchor(nodeid)
    _assert_status_and_codes(nodeid, results[0].status.value, {b.code for b in results[0].blockers}, case)
    if case.mutation == "vector_missing_expected":
        assert {blocker.ref for blocker in results[0].blockers} == {"vectors.0.expected_valid"}, _red_anchor(nodeid)


def _assert_release_handoff_surface(nodeid: str) -> None:
    import phase_loop_runtime
    from phase_loop_runtime.conformance import EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN

    handoff = (
        REPO_ROOT / "docs" / "releases" / "outside-agent-release-handoff.md"
    ).read_text(encoding="utf-8").lower()
    pin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN
    required = {
        "phase-loop-runtime",
        phase_loop_runtime.__version__,
        "validator version",
        "governed_pipeline_validator",
        "outside-agent-preflight",
        "outside-agent-validate",
        pin.contract_package,
        pin.contract_version,
        pin.contract_git_tag,
        pin.contract_git_sha,
        pin.schema_version,
        pin.verdict_schema_version,
        pin.submission_schema_sha256,
        pin.verdict_schema_sha256,
        pin.vector_manifest_name,
        pin.vector_manifest_hash,
        pin.source_owner,
        pin.redaction_posture,
        f"phase_loop_runtime-{phase_loop_runtime.__version__}-py3-none-any.whl",
        f"phase_loop_runtime-{phase_loop_runtime.__version__}.tar.gz",
        "digest-enumerated",
        "direct-wheel",
        "sdist-derived-wheel",
        "maintainer",
        "not published",
        "not dispatched",
    }
    assert all(term.lower() in handoff for term in required), _red_anchor(nodeid)
    assert not any(
        term in handoff
        for term in {
            "accepted_for_merge",
            "merge_verdict",
            "provider payload",
            "local env",
            "tbd",
            "todo",
            "/home/",
            "/mnt/",
        }
    ), _red_anchor(nodeid)
    evidence = runner_b2_evidence()
    if evidence is None:
        return
    candidate_anchor = "CONFORM_RED::release_handoff_candidate_identity_only"
    candidate_commit = evidence["candidate_commit"]
    candidate_tree = evidence["candidate_tree"]
    final_commit = evidence["final_commit"]
    final_tree = evidence["final_tree"]
    assert all(
        isinstance(value, str)
        for value in (candidate_commit, candidate_tree, final_commit, final_tree)
    )
    forbidden_identity_values = {
        "final_commit": final_commit,
        "final_tree": final_tree,
    }

    def assert_candidate_only(document: str) -> None:
        assert_candidate_identity_only_document(
            document,
            candidate_commit=candidate_commit,
            candidate_tree=candidate_tree,
            forbidden_identity_values=forbidden_identity_values,
            anchor=candidate_anchor,
            require_candidate_identity=True,
        )

    assert_candidate_only(handoff)
    assert (
        f"pre-doc a2 package evidence sha256: {evidence['a2_package_evidence_sha256']}"
        in handoff
    ), _red_anchor(nodeid)
    for label, archive in evidence["archives"].items():
        assert f"{label} sha256: {archive['sha256']}" in handoff, _red_anchor(nodeid)
    candidate_handoff = "\n".join(
        (
            f"candidate implementation commit: {evidence['candidate_commit']}",
            f"candidate implementation tree: {evidence['candidate_tree']}",
            "pre-doc A2 package evidence sha256: "
            + evidence["a2_package_evidence_sha256"],
            *(f"{label} sha256: {archive['sha256']}" for label, archive in evidence["archives"].items()),
        )
    )
    assert_candidate_only(candidate_handoff)
    for forged in (
        candidate_handoff.replace(
            f"candidate implementation commit: {evidence['candidate_commit']}",
            f"final implementation commit: {evidence['final_commit']}",
        ),
        candidate_handoff.replace(evidence["candidate_tree"], evidence["final_tree"]),
    ):
        assert forged != candidate_handoff
        with pytest.raises(AssertionError, match=candidate_anchor):
            assert_candidate_only(forged)


def _assert_public_docs_surface(nodeid: str) -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").lower()
    readme_required = {
        "docs/releases/outside-agent-release-handoff.md",
        "docs/outside-agent-conformance.md",
        "outside-agent-preflight",
        "outside-agent-validate",
        "governed-pipeline",
    }
    changelog_required = {
        "outside-agent conformance runtime (oarelease)",
        "release handoff",
        "governed-pipeline pinning instructions",
        "maintainer-owned publish/tag/workflow-dispatch",
        "consiliency/spec@v0.2.1",
        "digest-enumerated",
        "0.5.0",
    }
    forbidden = {"accepted_for_merge", "merge_verdict"}
    assert all(term in readme for term in readme_required), _red_anchor(nodeid)
    assert all(term in changelog for term in changelog_required), _red_anchor(nodeid)
    assert not any(term in readme or term in changelog for term in forbidden), _red_anchor(nodeid)


def assert_named_canonical_capability(nodeid: str) -> None:
    """Run the strict, dialect-adapted body for one migrated test name."""
    assert set(CONFORM_CANONICAL_CASES) == set(CONFORM_MIGRATED_EXISTING_NODE_IDS)
    case = CONFORM_CANONICAL_CASES[nodeid]
    if nodeid in NAMED_SAFETY_NODE_IDS:
        if NAMED_SAFETY_NODE_IDS[nodeid] == "advisory_network":
            _assert_advisory_uses_no_external_access(nodeid)
        elif NAMED_SAFETY_NODE_IDS[nodeid] == "network":
            _assert_core_uses_no_network_or_provider_credentials(nodeid)
        elif NAMED_SAFETY_NODE_IDS[nodeid] == "vectors":
            _assert_live_validation_runs_zero_vectors(nodeid)
        else:
            _assert_real_validator_wraps_core_once(nodeid)
        return
    if case.seam == "mirror":
        assert_packaged_contract_mirror()
        return
    if case.seam == "release_handoff":
        _assert_release_handoff_surface(nodeid)
        return
    if case.seam == "public_docs":
        _assert_public_docs_surface(nodeid)
        return
    if case.seam == "preflight_cli":
        _run_cli_case(nodeid, case, "outside-agent-preflight")
        return
    if case.seam == "validate_cli":
        _run_cli_case(nodeid, case, "outside-agent-validate")
        return
    if case.seam == "vector":
        _run_vector_case(nodeid, case)
        return
    payload = _mutated_canonical_submission(case.mutation)
    if case.seam == "redaction":
        from phase_loop_runtime.conformance.outside_agent_redaction import assert_outside_agent_metadata_only

        blockers = assert_outside_agent_metadata_only(payload)
        _assert_status_and_codes(nodeid, "pass" if not blockers else "blocked", {b.code for b in blockers}, case)
        return
    if case.seam == "schema":
        from phase_loop_runtime.conformance.outside_agent_schema import validate_outside_agent_submission_schema

        if case.role == "schema_accepts_all_three_canonical_kinds":
            for entry in valid_submission_entries():
                result = validate_outside_agent_submission_schema(vector_payload(entry))
                assert result.blockers == (), _red_anchor(nodeid)
            return
        result = validate_outside_agent_submission_schema(payload)
        _assert_status_and_codes(nodeid, "pass" if not result.blockers else "blocked", {b.code for b in result.blockers}, case)
        return
    if case.seam == "advisory":
        from phase_loop_runtime.conformance.outside_agent_advisory import build_outside_agent_advisory_evidence, serialize_outside_agent_advisory_evidence

        rendered = serialize_outside_agent_advisory_evidence(build_outside_agent_advisory_evidence(payload))
        _assert_status_and_codes(nodeid, rendered["status"], {b["code"] for b in rendered["blockers"]}, case)
        assert rendered["exit_code"] == (case.expected_exit if case.expected_exit is not None else 0), _red_anchor(nodeid)
        if "deterministic" in case.role:
            assert rendered == serialize_outside_agent_advisory_evidence(build_outside_agent_advisory_evidence(payload)), _red_anchor(nodeid)
        return
    if case.seam == "real":
        from phase_loop_runtime.conformance.outside_agent_real import build_outside_agent_validation_verdict
        from phase_loop_runtime.conformance.outside_agent_real_output import serialize_outside_agent_validation_verdict

        rendered = serialize_outside_agent_validation_verdict(build_outside_agent_validation_verdict(payload))
        _assert_status_and_codes(nodeid, rendered["status"], {b["code"] for b in rendered["blockers"]}, case)
        assert rendered["exit_code"] == (case.expected_exit if case.expected_exit is not None else 0), _red_anchor(nodeid)
        if "deterministic" in case.role:
            assert rendered == serialize_outside_agent_validation_verdict(build_outside_agent_validation_verdict(payload)), _red_anchor(nodeid)
        if "authority_boundary" in case.role or "typed_blocker_boundary" in case.role:
            assert "accepted_for_merge" not in json.dumps(rendered, sort_keys=True)
            assert "merge_verdict" not in json.dumps(rendered, sort_keys=True)
        return
    if case.seam == "core":
        from phase_loop_runtime.conformance.outside_agent_core import validate_outside_agent_submission

        if case.role == "core_typed_metadata_only_acceptance":
            _assert_legacy_same_version_payload_is_rejected(nodeid)
        verdict = validate_outside_agent_submission(payload)
        _assert_status_and_codes(nodeid, verdict.status.value, {b.code for b in verdict.blockers}, case)
        if "deterministic" in case.role:
            assert verdict == validate_outside_agent_submission(payload), _red_anchor(nodeid)
        if "metadata_only" in case.role:
            assert verdict.redaction_posture == "metadata_only", _red_anchor(nodeid)
        return
    raise AssertionError(f"unhandled canonical seam: {case.seam}")
