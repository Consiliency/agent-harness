"""proofgate_bootstrap_verifier.py — Test-owned immutable verifier for PROOFGATE landings."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

try:
    from .proofgate_tdd_guard import (
        ATTENDED_REAL_PROVIDER_CASES,
        BOOTSTRAP_PATHS,
        BOOTSTRAP_PATHS_SHA256,
        BOOTSTRAP_CANDIDATE_NODEIDS,
        BOOTSTRAP_CANDIDATE_NODEIDS_SHA256,
        CANDIDATE_BINDING_FIELDS,
        DEFAULT_SKIP_NODEIDS,
        EXPECTED_PHASE_NODEIDS,
        ORIGINAL_TESTS_LANDING_OID,
        PROOFGATE_EXPECTED_CONFIG_V1_CANONICAL_SHA256,
        PROOFGATE_LITERAL_CASE_IDS,
        PROOFGATE_OBSERVATION_SCHEMA,
        RED_CASES_BY_NODEID,
        SELECTOR_MODULES,
        SELECTOR_MODULES_SHA256,
        SELECTOR_REPAIR_PATHS,
        SELECTOR_REPAIR_PATHS_SHA256,
        TEST_CONTRACT_FILES,
        ProofgateExpectedConfig,
        ProofgateExternalObservation,
        ProofgateObservationRequest,
        ProofgateObservationUnavailable,
        RecordingObservationBoundary,
        UnavailableObservationBoundary,
        canonical_expected_config_digest,
        conforming_observation,
        expected_append_digest,
        expected_bundle_digest,
        observation_digest,
        primary_red_case_id,
        subject_sequence_and_core_digest,
    )
except ImportError:
    from proofgate_tdd_guard import (
        ATTENDED_REAL_PROVIDER_CASES,
        BOOTSTRAP_PATHS,
        BOOTSTRAP_PATHS_SHA256,
        BOOTSTRAP_CANDIDATE_NODEIDS,
        BOOTSTRAP_CANDIDATE_NODEIDS_SHA256,
        CANDIDATE_BINDING_FIELDS,
        DEFAULT_SKIP_NODEIDS,
        EXPECTED_PHASE_NODEIDS,
        ORIGINAL_TESTS_LANDING_OID,
        PROOFGATE_EXPECTED_CONFIG_V1_CANONICAL_SHA256,
        PROOFGATE_LITERAL_CASE_IDS,
        PROOFGATE_OBSERVATION_SCHEMA,
        RED_CASES_BY_NODEID,
        SELECTOR_MODULES,
        SELECTOR_MODULES_SHA256,
        SELECTOR_REPAIR_PATHS,
        SELECTOR_REPAIR_PATHS_SHA256,
        TEST_CONTRACT_FILES,
        ProofgateExpectedConfig,
        ProofgateExternalObservation,
        ProofgateObservationRequest,
        ProofgateObservationUnavailable,
        RecordingObservationBoundary,
        UnavailableObservationBoundary,
        canonical_expected_config_digest,
        conforming_observation,
        expected_append_digest,
        expected_bundle_digest,
        observation_digest,
        primary_red_case_id,
        subject_sequence_and_core_digest,
    )




class ProofgateBootstrapVerifierError(ValueError):
    """Typed error for bootstrap verifier check failures."""


HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
ATTENDED_REFERENCE_RUNNER_BYTES = b"proofgate-bootstrap-coordinator-reference-runner.v1"


def expected_attended_runner_module_identity() -> str:
    return hashlib.sha256(ATTENDED_REFERENCE_RUNNER_BYTES).hexdigest()


def attended_provider_receipts_digest(receipts: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(receipts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_attended_provider_receipts(
    runner_envelope: dict[str, Any],
    *,
    expected_stage: str,
    expected_head: str,
    expected_module_identity: str,
) -> dict[str, Any]:
    receipts = runner_envelope.get("provider_receipts")
    if not isinstance(receipts, dict) or tuple(receipts) != tuple(sorted(ATTENDED_REAL_PROVIDER_CASES)):
        raise ProofgateBootstrapVerifierError("Attended provider receipt inventory mismatch")
    if runner_envelope.get("provider_receipts_sha256") != attended_provider_receipts_digest(receipts):
        raise ProofgateBootstrapVerifierError("Attended provider receipt digest mismatch")
    required = {
        "broker_digest",
        "first_party_executable_sha256",
        "head_identity",
        "module_identity",
        "nonce",
        "process_start_token",
        "profile_digest",
        "protocol_sha256",
        "provider_case",
        "request_transcript_sha256",
        "response_transcript_sha256",
        "runner_stage",
        "schema",
        "subscription_transport_observed",
    }
    for provider_case in sorted(ATTENDED_REAL_PROVIDER_CASES):
        receipt = receipts[provider_case]
        if not isinstance(receipt, dict) or set(receipt) != required:
            raise ProofgateBootstrapVerifierError(
                f"Attended provider receipt schema mismatch: {provider_case}"
            )
        if (
            receipt["schema"] != "proofgate_attended_provider_receipt.v1"
            or receipt["provider_case"] != provider_case
            or receipt["runner_stage"] != expected_stage
            or receipt["module_identity"] != expected_module_identity
            or receipt["head_identity"] != expected_head
            or receipt["nonce"] != runner_envelope["nonces"].get(provider_case)
            or receipt["broker_digest"] != runner_envelope["broker_digests"].get(provider_case)
            or receipt["profile_digest"] != runner_envelope["profile_digests"].get(provider_case)
            or receipt["subscription_transport_observed"] is not True
            or not isinstance(receipt["process_start_token"], str)
            or not receipt["process_start_token"]
        ):
            raise ProofgateBootstrapVerifierError(
                f"Attended provider receipt identity mismatch: {provider_case}"
            )
        for digest_field in (
            "first_party_executable_sha256",
            "protocol_sha256",
            "request_transcript_sha256",
            "response_transcript_sha256",
        ):
            if not isinstance(receipt[digest_field], str) or not HEX_64_RE.match(
                receipt[digest_field]
            ):
                raise ProofgateBootstrapVerifierError(
                    f"Attended provider receipt lacks {digest_field}: {provider_case}"
                )
    return receipts

AUTHOR_VENDOR = "gemini"
AUTHOR_MODEL = "gemini-3.6-flash"
AUTHOR_EFFORT = "high"
AUTHOR_SCOPE = "whole_phase"

PR_T_18_PATTERNS: tuple[str, ...] = (
    "phase-loop-runtime/tests/fixtures/proofgate/**",
    "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
    "phase-loop-runtime/tests/proofgate_tdd_guard.py",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py",
    "phase-loop-runtime/tests/test_closeout_verification_gate.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_preflight_verification.py",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py",
    "phase-loop-runtime/tests/test_proofgate_isolation.py",
    "phase-loop-runtime/tests/test_proofgate_receipts.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py",
    "phase-loop-runtime/tests/test_skills_canon_parity.py",
    "phase-loop-runtime/tests/test_tdd_chronology.py",
    "phase-loop-runtime/tests/test_train_invariants.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py",
    "phase-loop-runtime/tests/test_verification_evidence.py",
)
PR_T_18_PATTERNS_SHA256 = "3b0c0914871e17d56c24fa34e4578c498110425bcc79c4cd3dc10277a1d50deb"
PR_T_18_PATHS: tuple[str, ...] = (
    "phase-loop-runtime/tests/fixtures/proofgate/v10-proofgate-mutations.json",
    *PR_T_18_PATTERNS[1:],
)
PR_T_18_PATHS_SHA256 = "53f80012139690b0e653f197bccc178050a22496a039bdbe36e579a24441a2bd"
PR_B_5_PATHS: tuple[str, ...] = (
    ".github/workflows/proofgate-receipt-attestation.yml",
    "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
    "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_isolation.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_receipts.py",
)
PR_B_5_PATHS_SHA256 = "3c365db032ad94622149fde1cadcb84b45480d65d8d789387ef47de286b59c44"
PHASE_38_PATTERNS: tuple[str, ...] = (
    ".github/workflows/proofgate-receipt-attestation.yml",
    "phase-loop-runtime/src/phase_loop_runtime/_contract_docs/runtime/verification-evidence-contract.md",
    "phase-loop-runtime/src/phase_loop_runtime/closeout.py",
    "phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py",
    "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
    "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_capability.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_isolation.py",
    "phase-loop-runtime/src/phase_loop_runtime/proofgate_receipts.py",
    "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-plan-phase/**",
    "phase-loop-runtime/src/phase_loop_runtime/tdd_chronology.py",
    "phase-loop-runtime/src/phase_loop_runtime/train_runner.py",
    "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
    "phase-loop-runtime/tests/fixtures/proofgate/**",
    "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
    "phase-loop-runtime/tests/proofgate_tdd_guard.py",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py",
    "phase-loop-runtime/tests/test_closeout_verification_gate.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_preflight_verification.py",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py",
    "phase-loop-runtime/tests/test_proofgate_isolation.py",
    "phase-loop-runtime/tests/test_proofgate_receipts.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py",
    "phase-loop-runtime/tests/test_skills_canon_parity.py",
    "phase-loop-runtime/tests/test_tdd_chronology.py",
    "phase-loop-runtime/tests/test_train_invariants.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py",
    "phase-loop-runtime/tests/test_verification_evidence.py",
    "phase-loop-skills/plan-phase/**",
    "skills-src/claude/claude-plan-phase/SKILL.md",
    "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py",
    "skills-src/codex/codex-plan-phase/SKILL.md",
    "skills-src/gemini/gemini-plan-phase/SKILL.md",
    "skills-src/opencode/opencode-plan-phase/SKILL.md",
)
PHASE_38_PATTERNS_SHA256 = "a19e9ae2714f414d92b12314e8e9370aa1518a400d638c6eef211eb05e4b6c9b"
EXPECTED_39_NODEIDS_SHA256 = "8e48a3efe3cb6fc534fc7dae67012e40b76e0fa14953d7a52801becc15614274"

BOOTSTRAP_MERGE_OBSERVATION_SCHEMA = "proofgate_bootstrap_merge_observation.v1"
BOOTSTRAP_COORDINATOR_ENVELOPE_SCHEMA = "proofgate_bootstrap_coordinator_envelope.v1"
BOOTSTRAP_COORDINATOR_PRODUCER_RECEIPT_SCHEMA = "proofgate_bootstrap_coordinator_producer_receipt.v1"
BOOTSTRAP_COORDINATOR_PROCESS_RECEIPT_SCHEMA = "proofgate_bootstrap_coordinator_process_receipt.v1"
GITHUB_CLI_PATH = "/usr/bin/gh"
GITHUB_CLI_SHA256 = "141507c337e8b202ad398550c3b73d72f5af92e86f71665214538a81efd4c409"

BOOTSTRAP_CANDIDATE_VERDICT_FIELDS: tuple[str, ...] = (
    "authorized_scope",
    "authorizes_final_completion",
    "authorizes_implementation",
    "binding_digest",
    "collected",
    "errors",
    "evidence_bindings",
    "failed",
    "junit_digest",
    "passed",
    "phase_reports_digest",
    "schema",
    "selector_digest",
    "skipped",
    "source_digest",
    "status",
)


def _github_cli_sha256(path: str | Path = GITHUB_CLI_PATH) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


COORDINATOR_EVIDENCE_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("proofgate-tests-only-default.junit.xml", "proofgate-tests-only-default.phase-reports.json", "default"),
    ("proofgate-tests-only-red.junit.xml", "proofgate-tests-only-red.phase-reports.json", "forced_red"),
    ("proofgate-candidate-ordinary.junit.xml", "proofgate-candidate-ordinary.phase-reports.json", "ordinary_hermetic"),
    ("proofgate-candidate-attended.junit.xml", "proofgate-candidate-attended.phase-reports.json", "attended_live"),
)
COORDINATOR_EVIDENCE_BY_MODE = {mode: (junit_filename, phase_reports_filename) for junit_filename, phase_reports_filename, mode in COORDINATOR_EVIDENCE_ARTIFACTS}
COORDINATOR_SEAT_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("fable", "proofgate-seat-fable.json"),
    ("gpt-5.6-sol", "proofgate-seat-gpt-5.6-sol.json"),
    ("gemini", "proofgate-seat-gemini.json"),
    ("grok", "proofgate-seat-grok.json"),
)
LANDING_REF_BINDINGS: dict[str, tuple[str, str]] = {
    "PR-T": ("proofgate-pr-t", "main"),
    "PR-B": ("proofgate-pr-b", "main"),
}
COORDINATOR_REPOSITORY = "Consiliency/agent-harness"
BOOTSTRAP_CONTROL_ARTIFACTS: tuple[str, ...] = (
    "ctrl_isolation.log",
    "ctrl_taint.log",
    "ctrl_misuse.log",
    "ctrl_control.log",
    "ctrl_positive_canary.log",
)
ATTENDED_PROVIDER_RECEIPTS_FILENAME = "proofgate-attended-provider-receipts.json"
BOOTSTRAP_CONTROL_COMPONENTS: tuple[str, ...] = (
    "code",
    "policy",
    "profile",
    "protocol",
)
BOOTSTRAP_LIVE_REACHABILITY_CASES = frozenset(
    {
        *ATTENDED_REAL_PROVIDER_CASES,
        "child_multi_turn_local_tool_loop_reachable",
        "mandatory_provider_real_inference_reachable",
        "safe_intended_inference_and_import_succeeds",
    }
)
BOOTSTRAP_ZERO_EFFECT_CASES = frozenset(
    case_id
    for case_id in PROOFGATE_LITERAL_CASE_IDS
    if any(
        token in case_id
        for token in (
            "rejected",
            "refused",
            "cannot_",
            "absent",
            "hostile_",
            "misuse",
            "exfiltration",
            "wrong_",
            "unsupported_",
            "redirect",
            "refresh",
            "set_cookie",
            "rotated_token",
            "auth_challenge",
        )
    )
)


def _control_artifact_name(case_id: str) -> str:
    if case_id in BOOTSTRAP_LIVE_REACHABILITY_CASES:
        return "ctrl_positive_canary.log"
    if any(token in case_id for token in ("taint", "credential_transform", "live_secret")):
        return "ctrl_taint.log"
    if any(
        token in case_id
        for token in (
            "external_head",
            "acceptance_",
            "check_p_",
            "required_before_",
            "response_rejected",
            "unsupported_control_metadata",
        )
    ):
        return "ctrl_control.log"
    if any(
        token in case_id
        for token in (
            "credential_argv",
            "credential_env",
            "credential_fd",
            "credential_mount",
            "credentialless_",
            "semantic_namespaces",
            "owner_cannot_read",
            "session_owner",
            "subscription_state",
            "subscription_transport_broker",
            "provider_adapter",
            "trusted_parent",
        )
    ):
        return "ctrl_isolation.log"
    return "ctrl_misuse.log"


BOOTSTRAP_CONTROL_CASES: dict[str, tuple[str, ...]] = {
    filename: tuple(
        case_id
        for case_id in PROOFGATE_LITERAL_CASE_IDS
        if _control_artifact_name(case_id) == filename
    )
    for filename in BOOTSTRAP_CONTROL_ARTIFACTS
}
assert all(BOOTSTRAP_CONTROL_CASES.values())
assert set().union(*(set(values) for values in BOOTSTRAP_CONTROL_CASES.values())) == set(
    PROOFGATE_LITERAL_CASE_IDS
)
assert sum(len(values) for values in BOOTSTRAP_CONTROL_CASES.values()) == len(
    PROOFGATE_LITERAL_CASE_IDS
)


@dataclasses.dataclass(frozen=True, slots=True)
class ProofgateBootstrapMergeObservationRequest:
    """A locator for the coordinator's pre-merge read-only observation."""

    repository: str
    base_oid: str
    candidate_oid: str
    landing_kind: str


@dataclasses.dataclass(frozen=True, slots=True)
class ProofgateBootstrapMergeObservation:
    """Sealed coordinator observation used only for a trust-establishing merge."""

    schema: str
    base_oid: str
    candidate_oid: str
    change_tuple_digest: str
    path_blob_digest: str
    path_scope_digest: str
    github_pr_json: str
    seat_records_json: str
    seat_chronology: tuple[str, ...]
    seat_artifact_digests: tuple[tuple[str, str], ...]
    junit_artifact_digests: tuple[tuple[str, str], ...]
    junit_phase_report_digests: tuple[tuple[str, str], ...]
    junit_phase_reports_json: str
    control_artifact_digests: tuple[tuple[str, str], ...]
    candidate_artifact_digests: tuple[tuple[str, str], ...] = ()


class RecordingBootstrapMergeObservationBoundary:
    """Read-only deterministic coordinator boundary for tests of the decisive path."""

    def __init__(self, observation: ProofgateBootstrapMergeObservation) -> None:
        if type(observation) is not ProofgateBootstrapMergeObservation:
            raise TypeError("bootstrap merge observation boundary requires a sealed observation")
        self._observation = observation
        self._calls: list[ProofgateBootstrapMergeObservationRequest] = []

    @property
    def calls(self) -> tuple[ProofgateBootstrapMergeObservationRequest, ...]:
        return tuple(self._calls)

    def observe(self, request: ProofgateBootstrapMergeObservationRequest) -> ProofgateBootstrapMergeObservation:
        if type(request) is not ProofgateBootstrapMergeObservationRequest:
            raise TypeError("bootstrap merge observation boundary accepts only a locator")
        self._calls.append(request)
        return self._observation


@dataclasses.dataclass(frozen=True, slots=True)
class CoordinatorBootstrapMergeObservationEnvelope:
    """One observation read by a fresh coordinator process from coordinator-owned evidence."""

    schema: str
    observation: ProofgateBootstrapMergeObservation
    observation_sha256: str
    producer_receipt: dict[str, Any]
    process_receipt: dict[str, Any]


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _bootstrap_observation_from_payload(value: Any) -> ProofgateBootstrapMergeObservation:
    if not isinstance(value, dict):
        raise ProofgateBootstrapVerifierError("coordinator observation payload must be an object")
    expected_fields = {field.name for field in dataclasses.fields(ProofgateBootstrapMergeObservation)}
    normalized = dict(value)
    normalized.setdefault("candidate_artifact_digests", [])
    if set(normalized) != expected_fields:
        raise ProofgateBootstrapVerifierError("coordinator observation payload field set mismatch")
    tuple_fields = ("seat_chronology", "seat_artifact_digests", "junit_artifact_digests", "junit_phase_report_digests", "control_artifact_digests", "candidate_artifact_digests")
    for field_name in tuple_fields:
        raw = normalized[field_name]
        if not isinstance(raw, list):
            raise ProofgateBootstrapVerifierError(f"coordinator observation {field_name} must be an array")
        if field_name == "seat_chronology":
            normalized[field_name] = tuple(raw)
            continue
        if not all(isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair) for pair in raw):
            raise ProofgateBootstrapVerifierError(f"coordinator observation {field_name} has invalid pairs")
        normalized[field_name] = tuple((pair[0], pair[1]) for pair in raw)
    try:
        return ProofgateBootstrapMergeObservation(**normalized)
    except (TypeError, ValueError) as exc:
        raise ProofgateBootstrapVerifierError("coordinator observation payload is invalid") from exc


def _write_coordinator_observation(root: Path, observation: ProofgateBootstrapMergeObservation, landing_kind: str) -> None:
    request = {
        "root": str(root),
        "observation": dataclasses.asdict(observation),
        "landing_kind": landing_kind,
        "producer_schema": BOOTSTRAP_COORDINATOR_PRODUCER_RECEIPT_SCHEMA,
        "repository": COORDINATOR_REPOSITORY,
    }
    writer = """
import hashlib
import json
import os
import sys
from pathlib import Path

request = json.loads(sys.stdin.read())
root = Path(request["root"])
observation = request["observation"]
observation_bytes = json.dumps(
    observation, sort_keys=True, separators=(",", ":"), ensure_ascii=True
).encode("utf-8")
(root / "bootstrap-observation.json").write_bytes(observation_bytes)
producer_receipt = {
    "schema": request["producer_schema"],
    "producer": "proofgate-coordinator",
    "writer_pid": os.getpid(),
    "repository": request["repository"],
    "base_oid": observation["base_oid"],
    "candidate_oid": observation["candidate_oid"],
    "landing_kind": request["landing_kind"],
    "observation_filename": "bootstrap-observation.json",
    "observation_sha256": hashlib.sha256(observation_bytes).hexdigest(),
}
(root / "bootstrap-producer-receipt.json").write_text(
    json.dumps(producer_receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8"
)
"""
    subprocess.run(
        [sys.executable, "-c", writer],
        input=json.dumps(request, sort_keys=True, separators=(",", ":")),
        text=True,
        capture_output=True,
        check=True,
    )


class CoordinatorBootstrapMergeObservationBoundary:
    """Operational boundary that reads coordinator evidence in a fresh subprocess.

    This is deliberately not a relabelled test double: the candidate process supplies only a
    locator, while a newly spawned reader reads the observation and its producer receipt from a
    coordinator-owned directory outside the candidate repository.
    """

    def __init__(self, coordinator_root: Path | str) -> None:
        self._coordinator_root = Path(coordinator_root).resolve()
        self._calls: list[ProofgateBootstrapMergeObservationRequest] = []

    @property
    def coordinator_root(self) -> Path:
        return self._coordinator_root

    @property
    def calls(self) -> tuple[ProofgateBootstrapMergeObservationRequest, ...]:
        return tuple(self._calls)

    def observe(self, request: ProofgateBootstrapMergeObservationRequest) -> CoordinatorBootstrapMergeObservationEnvelope:
        if type(request) is not ProofgateBootstrapMergeObservationRequest:
            raise TypeError("coordinator bootstrap boundary accepts only a sealed locator")
        root = self._coordinator_root
        if not root.is_dir() or root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
            raise ProofgateBootstrapVerifierError("coordinator evidence root is unavailable or symlinked")
        self._calls.append(request)
        request_bytes = _canonical_json_bytes(dataclasses.asdict(request))
        reader = """
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
request_bytes = bytes.fromhex(sys.argv[2])
observation_path = root / "bootstrap-observation.json"
producer_path = root / "bootstrap-producer-receipt.json"
try:
    observation_bytes = observation_path.read_bytes()
    producer_bytes = producer_path.read_bytes()
    observation = json.loads(observation_bytes.decode("utf-8"))
    producer_receipt = json.loads(producer_bytes.decode("utf-8"))
except Exception as exc:
    sys.stderr.write(f"coordinator evidence unreadable: {type(exc).__name__}\\n")
    raise SystemExit(2)
payload = {
    "schema": "proofgate_bootstrap_coordinator_envelope.v1",
    "observation": observation,
    "observation_sha256": hashlib.sha256(observation_bytes).hexdigest(),
    "producer_receipt": producer_receipt,
    "process_receipt": {
        "schema": "proofgate_bootstrap_coordinator_process_receipt.v1",
        "reader_pid": os.getpid(),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "observation_sha256": hashlib.sha256(observation_bytes).hexdigest(),
        "producer_receipt_sha256": hashlib.sha256(producer_bytes).hexdigest(),
    },
}
sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
"""
        proc = subprocess.run(
            [sys.executable, "-c", reader, str(root), request_bytes.hex()],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise ProofgateBootstrapVerifierError("coordinator observation reader failed")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ProofgateBootstrapVerifierError("coordinator observation reader returned invalid JSON") from exc
        expected_fields = {"schema", "observation", "observation_sha256", "producer_receipt", "process_receipt"}
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise ProofgateBootstrapVerifierError("coordinator observation reader envelope schema mismatch")
        return CoordinatorBootstrapMergeObservationEnvelope(
            schema=payload["schema"],
            observation=_bootstrap_observation_from_payload(payload["observation"]),
            observation_sha256=payload["observation_sha256"],
            producer_receipt=payload["producer_receipt"],
            process_receipt=payload["process_receipt"],
        )


def _norm_seat(seat: str) -> str:
    s = seat.lower().strip()
    if s in ("sol", "gpt-5.6-sol"):
        return "gpt-5.6-sol"
    return s


def evaluate_unit_double_bootstrap_merge_review_gate(
    evidence: dict[str, Any],
    *,
    expected_digest: str | None = None,
    author_vendor: str | None = None,
    expected_candidate_oid: str | None = None,
    expected_base_oid: str | None = None,
    expected_repo: str | None = None,
    expected_head_ref: str | None = None,
    expected_base_ref: str | None = None,
    expected_junit_modes: set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Pure evaluator for unit-double metadata (non-decisive).

    Validates evidence input structure, panel seats, Gemini author tuple,
    and returns a result dictionary with evidence_kind="unit_double" and decisive=False.
    """
    if not isinstance(evidence, dict):
        raise ProofgateBootstrapVerifierError("Sealed evidence input must be a dictionary")

    required_top_keys = {
        "candidate_oid",
        "base_oid",
        "path_blob_digest",
        "change_tuple_digest",
        "topology",
        "seat_records",
        "seat_chronology",
        "author_vendor",
        "raw_log_digest",
        "junit_mode_digests",
        "control_digests",
        "github_pr",
    }
    if set(evidence.keys()) != required_top_keys:
        missing = required_top_keys - set(evidence.keys())
        extra = set(evidence.keys()) - required_top_keys
        if missing:
            raise ProofgateBootstrapVerifierError(f"Sealed evidence missing required top-level key(s): {sorted(list(missing))}")
        if extra:
            raise ProofgateBootstrapVerifierError(f"Sealed evidence contains unexpected top-level key(s): {sorted(list(extra))}")

    cand_oid = evidence["candidate_oid"]
    base_oid = evidence["base_oid"]
    if not isinstance(cand_oid, str) or not HEX_40_RE.match(cand_oid):
        raise ProofgateBootstrapVerifierError("Invalid candidate_oid in sealed evidence (must be exact 40-lowercase-hex)")
    if not isinstance(base_oid, str) or not HEX_40_RE.match(base_oid) or base_oid == cand_oid:
        raise ProofgateBootstrapVerifierError("Invalid base_oid in sealed evidence (must be exact 40-lowercase-hex and distinct)")

    if expected_candidate_oid and cand_oid != expected_candidate_oid:
        raise ProofgateBootstrapVerifierError(f"candidate_oid '{cand_oid}' does not match expected '{expected_candidate_oid}'")
    if expected_base_oid and base_oid != expected_base_oid:
        raise ProofgateBootstrapVerifierError(f"base_oid '{base_oid}' does not match expected '{expected_base_oid}'")

    path_blob = evidence["path_blob_digest"]
    change_tuple = evidence["change_tuple_digest"]
    raw_log = evidence["raw_log_digest"]
    for name, dig in (("path_blob_digest", path_blob), ("change_tuple_digest", change_tuple), ("raw_log_digest", raw_log)):
        if not isinstance(dig, str) or not HEX_64_RE.match(dig):
            raise ProofgateBootstrapVerifierError(f"Invalid {name} in sealed evidence (must be exact 64-lowercase-hex)")

    topo = evidence["topology"]
    if not isinstance(topo, dict) or set(topo.keys()) not in ({"two_parent", "every_parent_present"}, {"two_parent", "every_parent_present", "parent_oids"}):
        raise ProofgateBootstrapVerifierError("Sealed evidence topology schema invalid")
    if topo.get("two_parent") is not True or topo.get("every_parent_present") is not True:
        raise ProofgateBootstrapVerifierError("Topology must be two-parent with every parent present")
    if "parent_oids" not in topo or not isinstance(topo["parent_oids"], list) or len(topo["parent_oids"]) != 2:
        raise ProofgateBootstrapVerifierError("Topology must contain parent_oids list with exactly 2 parent OIDs")
    for p_oid in topo["parent_oids"]:
        if not isinstance(p_oid, str) or not HEX_40_RE.match(p_oid):
            raise ProofgateBootstrapVerifierError(f"Invalid parent OID '{p_oid}' in topology")
    if topo["parent_oids"][0] != base_oid:
        raise ProofgateBootstrapVerifierError(f"base_oid '{base_oid}' must match topology parent_oids[0]")

    j_digs = evidence["junit_mode_digests"]
    expected_j_modes = set(expected_junit_modes) if expected_junit_modes is not None else {"default", "forced_red", "ordinary", "attended"}
    if not isinstance(j_digs, dict) or set(j_digs.keys()) != expected_j_modes:
        raise ProofgateBootstrapVerifierError("Sealed evidence junit_mode_digests schema invalid")
    for jk, jv in j_digs.items():
        if not isinstance(jv, str) or not HEX_64_RE.match(jv):
            raise ProofgateBootstrapVerifierError(f"Invalid junit_mode_digest for {jk}")

    c_digs = evidence["control_digests"]
    req_c_keys = {"isolation", "taint", "misuse", "control", "positive_canary"}
    if not isinstance(c_digs, dict) or set(c_digs.keys()) != req_c_keys:
        raise ProofgateBootstrapVerifierError("Sealed evidence control_digests schema invalid")
    for ck, cv in c_digs.items():
        if not isinstance(cv, str) or not HEX_64_RE.match(cv):
            raise ProofgateBootstrapVerifierError(f"Invalid control_digest for {ck}")

    pr = evidence["github_pr"]
    req_pr_keys = {"number", "repo", "head_ref", "base_ref"}
    if not isinstance(pr, dict) or not req_pr_keys.issubset(set(pr.keys())):
        raise ProofgateBootstrapVerifierError("Sealed evidence github_pr schema invalid")
    if not isinstance(pr["number"], int) or pr["number"] <= 0:
        raise ProofgateBootstrapVerifierError("Invalid PR number in sealed evidence")
    if expected_repo and pr["repo"] != expected_repo:
        raise ProofgateBootstrapVerifierError(f"PR repo '{pr['repo']}' does not match expected '{expected_repo}'")
    if expected_head_ref and pr["head_ref"] != expected_head_ref:
        raise ProofgateBootstrapVerifierError(f"PR head_ref '{pr['head_ref']}' does not match expected '{expected_head_ref}'")
    if expected_base_ref and pr["base_ref"] != expected_base_ref:
        raise ProofgateBootstrapVerifierError(f"PR base_ref '{pr['base_ref']}' does not match expected '{expected_base_ref}'")

    raw_author = evidence.get("author_vendor") or author_vendor
    if not raw_author:
        raise ProofgateBootstrapVerifierError("author_vendor is required in sealed evidence")
    eff_author = _norm_seat(raw_author)
    if eff_author != AUTHOR_VENDOR:
        raise ProofgateBootstrapVerifierError(f"Author vendor must be '{AUTHOR_VENDOR}', got '{eff_author}'")

    seat_records = evidence["seat_records"]
    if not isinstance(seat_records, dict):
        raise ProofgateBootstrapVerifierError("seat_records must be a dictionary")

    required_seats = {"fable", "gpt-5.6-sol", "gemini", "grok"}
    normalized_records: dict[str, dict[str, Any]] = {}
    for seat, rec in seat_records.items():
        if not isinstance(rec, dict):
            raise ProofgateBootstrapVerifierError(f"Seat record for {seat} must be a dictionary")
        norm_s = _norm_seat(seat)
        if norm_s in normalized_records:
            raise ProofgateBootstrapVerifierError(f"Duplicate seat record for {norm_s}")
        normalized_records[norm_s] = rec

    missing_seats = required_seats - set(normalized_records.keys())
    if missing_seats:
        raise ProofgateBootstrapVerifierError(f"Missing required panel seat(s): {sorted(list(missing_seats))}")

    extra_seats = set(normalized_records.keys()) - required_seats
    if extra_seats:
        raise ProofgateBootstrapVerifierError(f"Unexpected panel seat(s): {sorted(list(extra_seats))}")

    target_digest: str = expected_digest or change_tuple
    indep_count = 0
    seen_run_ids: set[str] = set()

    for seat in ("fable", "gpt-5.6-sol", "gemini", "grok"):
        rec = normalized_records[seat]
        verdict = str(rec.get("verdict", "")).upper()
        if verdict != "AGREE":
            raise ProofgateBootstrapVerifierError(f"Seat {seat} verdict is '{verdict}', required AGREE")
        if rec.get("substantive") is not True:
            raise ProofgateBootstrapVerifierError(f"Seat {seat} review is non-substantive")

        run_id = rec.get("run_identity")
        if not run_id or not isinstance(run_id, str):
            raise ProofgateBootstrapVerifierError(f"Seat {seat} must specify explicit non-empty run_identity string")
        if run_id in seen_run_ids:
            raise ProofgateBootstrapVerifierError(f"Duplicate run_identity '{run_id}' found across seats")
        seen_run_ids.add(run_id)

        digest = rec.get("candidate_digest")
        if not digest or not HEX_64_RE.match(str(digest)) or digest != target_digest:
            raise ProofgateBootstrapVerifierError(
                f"Seat {seat} digest '{digest}' disagrees with target digest '{target_digest}' or is invalid hex"
            )

        attester = _norm_seat(str(rec.get("attester", "")))
        if attester != seat:
            raise ProofgateBootstrapVerifierError(f"Seat {seat} attester '{attester}' does not match seat name '{seat}'")

        if "is_author" not in rec or "independent_attestor" not in rec:
            raise ProofgateBootstrapVerifierError(f"Seat {seat} must explicitly specify both is_author and independent_attestor booleans")
        is_author = rec["is_author"]
        indep_attestor = rec["independent_attestor"]

        if not isinstance(is_author, bool) or not isinstance(indep_attestor, bool):
            raise ProofgateBootstrapVerifierError(f"Seat {seat} is_author and independent_attestor must be booleans")

        if seat == eff_author:
            if is_author is not True or indep_attestor is not False:
                raise ProofgateBootstrapVerifierError(f"Author seat '{seat}' must have exactly is_author=True and independent_attestor=False")
        else:
            if is_author is not False or indep_attestor is not True:
                raise ProofgateBootstrapVerifierError(f"Independent seat '{seat}' must have exactly is_author=False and independent_attestor=True")
            indep_count += 1

    if indep_count != 3:
        raise ProofgateBootstrapVerifierError(f"Review gate requires exactly 3 independent attestors, found {indep_count}")

    seat_chron = evidence["seat_chronology"]
    if not isinstance(seat_chron, list) or len(seat_chron) != 4:
        raise ProofgateBootstrapVerifierError("Seat chronology must contain exactly four distinct seats")

    norm_chron = [_norm_seat(s) for s in seat_chron]
    if len(set(norm_chron)) != 4 or set(norm_chron) != required_seats:
        raise ProofgateBootstrapVerifierError("Seat chronology must contain each of the 4 required seats exactly once")

    return {
        "status": "valid",
        "evidence_kind": "unit_double",
        "decisive": False,
        "author_vendor": AUTHOR_VENDOR,
        "author_model": AUTHOR_MODEL,
        "author_effort": AUTHOR_EFFORT,
        "author_scope": AUTHOR_SCOPE,
        "independent_attestors": 3,
    }


def verify_bootstrap_merge_review_gate(
    evidence: dict[str, Any],
    *,
    expected_digest: str | None = None,
    author_vendor: str | None = None,
    expected_candidate_oid: str | None = None,
    expected_base_oid: str | None = None,
    expected_repo: str | None = None,
    expected_head_ref: str | None = None,
    expected_base_ref: str | None = None,
) -> bool:
    """Evaluates bootstrap review gate for unit doubles and returns True if valid."""
    res = evaluate_unit_double_bootstrap_merge_review_gate(
        evidence,
        expected_digest=expected_digest,
        author_vendor=author_vendor,
        expected_candidate_oid=expected_candidate_oid,
        expected_base_oid=expected_base_oid,
        expected_repo=expected_repo,
        expected_head_ref=expected_head_ref,
        expected_base_ref=expected_base_ref,
    )
    return res.get("status") == "valid"


def parse_git_diff_tree_raw(repo_path: str | Path, base_oid: str, candidate_oid: str) -> list[tuple[str, str, str, str, str, str, str]]:
    """Executes git diff-tree --raw -r -z base_oid candidate_oid and returns parsed path tuples.

    Tuple format: (change_kind, path, old_mode, new_mode, old_blob_oid, new_blob_oid, new_file_sha256)
    """
    r_path = Path(repo_path)
    res = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    )
    raw = res.stdout
    if not raw:
        return []

    parts = raw.split(b"\x00")
    i = 0
    tuples = []
    while i < len(parts):
        chunk = parts[i].decode("utf-8", errors="replace").strip()
        if not chunk:
            i += 1
            continue
        if not chunk.startswith(":"):
            i += 1
            continue

        meta = chunk[1:].split()
        if len(meta) < 5:
            raise ProofgateBootstrapVerifierError(f"Malformed git diff-tree line: {chunk}")
        old_mode, new_mode, old_blob_oid, new_blob_oid, status_str = meta[0], meta[1], meta[2], meta[3], meta[4]
        change_kind = status_str[0]

        if change_kind in ("R", "C"):
            raise ProofgateBootstrapVerifierError("Rename or copy change kind is forbidden in PROOFGATE landings")

        i += 1
        if i >= len(parts):
            break
        path_str = parts[i].decode("utf-8", errors="replace")

        new_sha256 = ""
        if new_blob_oid and new_blob_oid != "0" * 40:
            cat_proc = subprocess.run(
                ["git", "cat-file", "-p", new_blob_oid],
                cwd=r_path,
                capture_output=True,
            )
            if cat_proc.returncode == 0:
                new_sha256 = hashlib.sha256(cat_proc.stdout).hexdigest()

        tuples.append((change_kind, path_str, old_mode, new_mode, old_blob_oid, new_blob_oid, new_sha256))
        i += 1

    return tuples


def compute_git_source_binding_facts(repo_path: Path | str, base_oid: str, candidate_oid: str) -> dict[str, Any]:
    """Source-binding helper using git diff-tree --raw -z, git ls-tree -rz, and git cat-file."""
    r_path = Path(repo_path)
    if not r_path.is_dir() or not (r_path / ".git").exists():
        return {}

    try:
        diff_proc = subprocess.run(
            ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
            cwd=r_path,
            capture_output=True,
            check=True,
        )
        diff_raw = diff_proc.stdout

        ls_proc = subprocess.run(
            ["git", "ls-tree", "-rz", candidate_oid],
            cwd=r_path,
            capture_output=True,
            check=True,
        )
        ls_raw = ls_proc.stdout

        cat_proc = subprocess.run(
            ["git", "cat-file", "-p", candidate_oid],
            cwd=r_path,
            capture_output=True,
            check=True,
        )
        cat_raw = cat_proc.stdout

        path_tuples = parse_git_diff_tree_raw(r_path, base_oid, candidate_oid)

        return {
            "candidate_oid": candidate_oid,
            "base_oid": base_oid,
            "path_blob_digest": hashlib.sha256(ls_raw).hexdigest(),
            "change_tuple_digest": hashlib.sha256(diff_raw).hexdigest(),
            "commit_header": cat_raw.decode("utf-8", errors="replace"),
            "path_tuples": path_tuples,
        }
    except Exception:
        return {}


def _verifier_git_parents(commit_oid: str, cwd: Path | str | None = None) -> list[str]:
    proc = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", commit_oid],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    fields = proc.stdout.strip().split()
    if not fields or fields[0] != commit_oid:
        raise ProofgateBootstrapVerifierError(f"Could not resolve exact parents for {commit_oid}")
    return fields[1:]


def _verifier_cat_git_file(commit_oid: str, path: str, cwd: Path | str | None = None) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "-p", f"{commit_oid}:{path}"],
        cwd=cwd,
        capture_output=True,
        check=True,
    ).stdout


def _verifier_validate_selector_repair_landing(
    selector_repair_landing_oid: str,
    cwd: Path | str | None = None,
    expected_original_landing: str = ORIGINAL_TESTS_LANDING_OID,
) -> None:
    parents = _verifier_git_parents(selector_repair_landing_oid, cwd=cwd)
    if len(parents) != 2:
        raise ProofgateBootstrapVerifierError("selector_repair_landing_oid must name an exact two-parent merge")
    base_oid, source_head_oid = parents

    source_parents = _verifier_git_parents(source_head_oid, cwd=cwd)
    if len(source_parents) != 1:
        raise ProofgateBootstrapVerifierError("selector repair GREEN source head must have exactly one RED parent")
    red_oid = source_parents[0]
    if _verifier_git_parents(red_oid, cwd=cwd) != [base_oid]:
        raise ProofgateBootstrapVerifierError("selector repair RED commit must have the landing first parent as its sole parent")

    first_parent_history = subprocess.run(
        ["git", "rev-list", "--first-parent", base_oid],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    if expected_original_landing not in first_parent_history:
        raise ProofgateBootstrapVerifierError("selector repair base first-parent history does not contain original tests landing")

    red_paths = subprocess.run(
        ["git", "diff", "--name-only", "-z", base_oid, red_oid],
        cwd=cwd,
        capture_output=True,
        check=True,
    ).stdout.rstrip(b"\x00").split(b"\x00")
    if red_paths != [b"phase-loop-runtime/tests/test_tdd_chronology.py"]:
        raise ProofgateBootstrapVerifierError("selector repair RED commit changes paths outside the chronology test")

    green_paths = subprocess.run(
        ["git", "diff", "--name-only", "-z", red_oid, source_head_oid],
        cwd=cwd,
        capture_output=True,
        check=True,
    ).stdout.rstrip(b"\x00").split(b"\x00")
    if green_paths != [
        b"phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
        b"phase-loop-runtime/tests/proofgate_tdd_guard.py",
    ]:
        raise ProofgateBootstrapVerifierError("selector repair GREEN commit changes paths outside the guard and verifier")

    source_diff = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, source_head_oid],
        cwd=cwd,
        capture_output=True,
        check=True,
    ).stdout
    landing_diff = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, selector_repair_landing_oid],
        cwd=cwd,
        capture_output=True,
        check=True,
    ).stdout
    if source_diff != landing_diff:
        raise ProofgateBootstrapVerifierError(
            "selector repair landing diff is not byte-identical to the reviewed source diff"
        )

    repo_dir = Path(cwd).resolve() if cwd else Path.cwd()
    landing_paths = tuple(
        row[1] for row in parse_git_diff_tree_raw(repo_dir, base_oid, selector_repair_landing_oid)
    )
    if landing_paths != SELECTOR_REPAIR_PATHS:
        raise ProofgateBootstrapVerifierError("selector repair landing does not contain the exact three canonical paths")
    paths_digest = hashlib.sha256(
        (json.dumps(SELECTOR_REPAIR_PATHS, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    if paths_digest != SELECTOR_REPAIR_PATHS_SHA256:
        raise ProofgateBootstrapVerifierError("selector repair canonical path digest mismatch")


def verify_bootstrap_candidate_binding(
    repo_path: Path | str,
    binding_path: Path | str,
    expected_original_tests_landing: str = ORIGINAL_TESTS_LANDING_OID,
) -> dict[str, Any]:
    """Public seam enforcing strict candidate binding validation and Git recomputation."""
    repo = Path(repo_path).resolve()
    binding_raw = Path(binding_path)

    if binding_raw.is_symlink():
        raise ProofgateBootstrapVerifierError("binding_path must not be a symlink")
    binding_file = binding_raw.resolve()
    if not binding_file.is_file():
        raise ProofgateBootstrapVerifierError("binding_path must be a regular file")

    try:
        binding_bytes = binding_file.read_bytes()
        data = json.loads(binding_bytes.decode("utf-8"))
    except Exception as exc:
        raise ProofgateBootstrapVerifierError(f"Candidate mode binding JSON unreadable: {exc}") from exc

    if not isinstance(data, dict) or tuple(data.keys()) != CANDIDATE_BINDING_FIELDS:
        raise ProofgateBootstrapVerifierError("Candidate mode binding fields mismatch")
    if binding_bytes != (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8"):
        raise ProofgateBootstrapVerifierError(
            "Candidate mode binding bytes are not canonical compact JSON plus LF"
        )
    if data.get("schema") != "proofgate_bootstrap_candidate_binding.v1":
        raise ProofgateBootstrapVerifierError("Candidate mode binding schema mismatch")
    if data.get("original_tests_landing_oid") != expected_original_tests_landing:
        raise ProofgateBootstrapVerifierError("original_tests_landing_oid mismatch")

    selector_repair_oid = data["selector_repair_landing_oid"]
    base_oid = data["base_oid"]
    candidate_oid = data["candidate_oid"]
    candidate_tree_oid = data["candidate_tree_oid"]
    for oid in (selector_repair_oid, base_oid, candidate_oid, candidate_tree_oid):
        if not HEX_40_RE.fullmatch(oid):
            raise ProofgateBootstrapVerifierError(f"Invalid OID in binding: {oid}")
    _verifier_validate_selector_repair_landing(
        selector_repair_oid, cwd=repo, expected_original_landing=expected_original_tests_landing
    )
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", selector_repair_oid, base_oid],
        cwd=repo,
        capture_output=True,
    ).returncode != 0:
        raise ProofgateBootstrapVerifierError("selector_repair_landing_oid is not an ancestor of base_oid")

    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    current_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    if current_head != candidate_oid or current_tree != candidate_tree_oid:
        raise ProofgateBootstrapVerifierError("candidate OID or tree does not match current HEAD")
    if _verifier_git_parents(candidate_oid, cwd=repo) != [base_oid]:
        raise ProofgateBootstrapVerifierError("candidate must have exactly one parent equal to base_oid")
    if subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip():
        raise ProofgateBootstrapVerifierError("Worktree or index is not clean against candidate_oid")

    diff_raw = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    diff_digest = hashlib.sha256(diff_raw).hexdigest()
    if data["diff_sha256"] != diff_digest:
        raise ProofgateBootstrapVerifierError("diff_sha256 mismatch")

    path_digest = hashlib.sha256(
        (json.dumps(BOOTSTRAP_PATHS, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    module_digest = hashlib.sha256(
        (json.dumps(SELECTOR_MODULES, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    nodeid_digest = hashlib.sha256(
        (json.dumps(BOOTSTRAP_CANDIDATE_NODEIDS, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    if path_digest != BOOTSTRAP_PATHS_SHA256 or data["path_scope_sha256"] != path_digest:
        raise ProofgateBootstrapVerifierError("path_scope_sha256 mismatch")
    if data["bootstrap_paths_sha256"] != path_digest:
        raise ProofgateBootstrapVerifierError("bootstrap_paths_sha256 mismatch")
    if module_digest != SELECTOR_MODULES_SHA256 or data["selector_modules_sha256"] != module_digest:
        raise ProofgateBootstrapVerifierError("selector_modules_sha256 mismatch")
    if nodeid_digest != BOOTSTRAP_CANDIDATE_NODEIDS_SHA256 or data["selector_nodeids_sha256"] != nodeid_digest:
        raise ProofgateBootstrapVerifierError("selector_nodeids_sha256 mismatch")

    changes = parse_git_diff_tree_raw(repo, base_oid, candidate_oid)
    if len(changes) != 5 or tuple(row[1] for row in changes) != BOOTSTRAP_PATHS:
        raise ProofgateBootstrapVerifierError("Candidate mode changes are not the exact five bootstrap paths")
    expected_changes = [
        [kind, path, new_mode, old_blob, new_blob, file_sha]
        for kind, path, _old_mode, new_mode, old_blob, new_blob, file_sha in changes
    ]
    if data["changes"] != expected_changes:
        raise ProofgateBootstrapVerifierError("changes list mismatch with independent Git recomputation")

    contract_digests = data.get("test_contract_sha256")
    if not isinstance(contract_digests, dict) or tuple(contract_digests.keys()) != TEST_CONTRACT_FILES:
        raise ProofgateBootstrapVerifierError("test_contract_sha256 schema mismatch")
    for path in TEST_CONTRACT_FILES:
        selector_bytes = _verifier_cat_git_file(selector_repair_oid, path, cwd=repo)
        selector_digest = hashlib.sha256(selector_bytes).hexdigest()
        if contract_digests.get(path) != selector_digest:
            raise ProofgateBootstrapVerifierError(f"test_contract_sha256 mismatch for {path}")
        if (
            _verifier_cat_git_file(base_oid, path, cwd=repo) != selector_bytes
            or _verifier_cat_git_file(candidate_oid, path, cwd=repo) != selector_bytes
        ):
            raise ProofgateBootstrapVerifierError(
                f"test contract bytes drifted across selector/base/candidate for {path}"
            )

    for check_oid in (base_oid, candidate_oid):
        res = subprocess.run(
            ["git", "cat-file", "-e", f"{check_oid}:phase-loop-runtime/src/phase_loop_runtime/proofgate_capability.py"],
            cwd=repo,
            capture_output=True,
        )
        if res.returncode == 0:
            raise ProofgateBootstrapVerifierError(
                f"Proofgate capability marker is present in Git tree at {check_oid}"
            )

    return {
        "status": "verified",
        "binding_data": data,
        "binding_bytes": binding_bytes,
        "binding_digest": hashlib.sha256(binding_bytes).hexdigest(),
        "source_digest": diff_digest,
    }


def _verifier_validate_candidate_binding() -> dict[str, Any]:
    """Verifier-owned parser and Git recomputation for bootstrap candidate mode."""
    expect = os.environ.get("PHASE_LOOP_TDD_EXPECT_PROOFGATE_BOOTSTRAP_CANDIDATE")
    binding_str = os.environ.get("PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING")
    if expect != "1" and not binding_str:
        return {}
    if expect != "1" or not binding_str:
        raise ProofgateBootstrapVerifierError(
            "Candidate mode requires both PHASE_LOOP_TDD_EXPECT_PROOFGATE_BOOTSTRAP_CANDIDATE=1 and PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING"
        )
    if os.environ.get("PHASE_LOOP_TDD_EXPECT_PROOFGATE") == "1":
        raise ProofgateBootstrapVerifierError("Candidate mode conflict: PHASE_LOOP_TDD_EXPECT_PROOFGATE is set")
    if os.environ.get("PHASE_LOOP_PROOFGATE_ATTENDED_LIVE") == "1":
        raise ProofgateBootstrapVerifierError("Candidate mode conflict: PHASE_LOOP_PROOFGATE_ATTENDED_LIVE is set")
    try:
        from phase_loop_runtime.proofgate_capability import PROOFGATE_CAPABILITY_VERSION
    except (ImportError, AttributeError):
        PROOFGATE_CAPABILITY_VERSION = None
    if PROOFGATE_CAPABILITY_VERSION == "proofgate.v1":
        raise ProofgateBootstrapVerifierError("Candidate mode conflict: final capability marker proofgate.v1 is present")

    run_dir_env = os.environ.get("PHASE_LOOP_RUN_DIR")
    if not run_dir_env or not run_dir_env.strip():
        raise ProofgateBootstrapVerifierError("PHASE_LOOP_RUN_DIR environment variable is missing or empty")
    run_dir_raw = Path(run_dir_env.strip())
    if not run_dir_raw.is_absolute() or not run_dir_raw.is_dir():
        raise ProofgateBootstrapVerifierError("PHASE_LOOP_RUN_DIR must be an existing absolute directory")
    run_dir = run_dir_raw.resolve()

    binding_raw = Path(binding_str.strip())
    if not binding_raw.is_absolute():
        raise ProofgateBootstrapVerifierError(
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING must be an absolute path"
        )
    if binding_raw.is_symlink():
        raise ProofgateBootstrapVerifierError(
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING must not be a symlink"
        )
    if not binding_raw.is_file():
        raise ProofgateBootstrapVerifierError(
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING must be a regular file"
        )
    try:
        lexical_relative = binding_raw.relative_to(run_dir_raw)
    except ValueError as exc:
        raise ProofgateBootstrapVerifierError(
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING is not lexically under PHASE_LOOP_RUN_DIR"
        ) from exc
    if not lexical_relative.parts:
        raise ProofgateBootstrapVerifierError(
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING must be strictly below PHASE_LOOP_RUN_DIR"
        )
    binding_path = binding_raw.resolve()
    try:
        resolved_relative = binding_path.relative_to(run_dir)
    except ValueError as exc:
        raise ProofgateBootstrapVerifierError(
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING is outside PHASE_LOOP_RUN_DIR"
        ) from exc
    if not resolved_relative.parts:
        raise ProofgateBootstrapVerifierError(
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING must be strictly below PHASE_LOOP_RUN_DIR"
        )

    res = verify_bootstrap_candidate_binding(
        repo_path=Path.cwd(),
        binding_path=binding_path,
        expected_original_tests_landing=ORIGINAL_TESTS_LANDING_OID,
    )
    return res


def _normalize_json_structures(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_json_structures(item) for item in value)
    if isinstance(value, dict):
        return {k: _normalize_json_structures(v) for k, v in value.items()}
    return value


def verify_proofgate_admin_authority(
    boundary: Any,
    candidate_oid: str,
    admin_binding_path: Path | str,
) -> dict[str, Any]:
    """Verify decisive admin authority solely from live control-plane observation.

    Rejects test fixtures, recording/coordinator boundaries, synthetic self-digests,
    candidate OID replay, and unavailable observations.
    """
    if type(boundary) is not ProofgateAdminControlPlaneBoundary:
        raise ProofgateBootstrapVerifierError(
            f"Only an exact live ProofgateAdminControlPlaneBoundary is eligible for admin authority, got {type(boundary).__name__}"
        )

    if getattr(boundary, "_test_observation_fixture", None) is not None:
        raise ProofgateBootstrapVerifierError(
            "Test fixture observation boundary is non-authoritative for admin authority"
        )

    if not HEX_40_RE.fullmatch(candidate_oid):
        raise ProofgateBootstrapVerifierError(f"Invalid candidate OID for admin authority: {candidate_oid}")

    binding_raw = Path(admin_binding_path)
    if binding_raw.is_symlink():
        raise ProofgateBootstrapVerifierError("admin_binding_path must not be a symlink")
    binding_file = binding_raw.resolve()
    if not binding_file.is_file():
        raise ProofgateBootstrapVerifierError("admin_binding_path must be a regular file")

    try:
        raw_bytes = binding_file.read_bytes()
        stored_binding = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ProofgateBootstrapVerifierError(f"admin_binding_path JSON unreadable: {exc}") from exc

    if not isinstance(stored_binding, dict):
        raise ProofgateBootstrapVerifierError("admin_binding_path JSON must be an object")

    if raw_bytes != json.dumps(stored_binding, sort_keys=True, separators=(",", ":")).encode("utf-8"):
        raise ProofgateBootstrapVerifierError("Admin authority receipt is not canonical JSON")

    stored_cand = stored_binding.get("candidate_oid")
    if stored_cand != candidate_oid:
        raise ProofgateBootstrapVerifierError("Admin authority candidate OID replay mismatch")

    if stored_binding.get("authority") != "github_and_broker_control_planes":
        raise ProofgateBootstrapVerifierError("Stored admin identity binding authority is non-authoritative")

    unbound_receipt = dict(stored_binding)
    claimed_digest = unbound_receipt.pop("binding_digest", None)
    computed_digest = hashlib.sha256(
        json.dumps(unbound_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if claimed_digest != computed_digest:
        raise ProofgateBootstrapVerifierError("Admin authority candidate-bound receipt digest mismatch")

    try:
        live_binding = verify_proofgate_admin_identity_binding(boundary)
    except Exception as exc:
        raise ProofgateBootstrapVerifierError(f"Live admin control plane observation unavailable: {exc}") from exc

    if live_binding.get("authority") != "github_and_broker_control_planes":
        raise ProofgateBootstrapVerifierError("Live admin control plane observation is non-authoritative")

    stored_identity = dict(unbound_receipt)
    stored_identity.pop("candidate_oid", None)
    live_identity = dict(live_binding)
    live_identity.pop("binding_digest", None)
    if _normalize_json_structures(stored_identity) != _normalize_json_structures(live_identity):
        raise ProofgateBootstrapVerifierError("Admin authority receipt does not match the full live identity binding")

    return live_binding


def verify_premerge_bootstrap_review_gate(
    repo_path: Path | str,
    base_oid: str,
    candidate_oid: str,
    github_pr: dict[str, Any],
    seat_records: dict[str, Any],
    seat_chronology: list[str],
    landing_kind: str = "PR-T",
) -> dict[str, Any]:
    """Decisive test-owned pre-merge verification over real Git repository and GitHub PR metadata."""
    r_path = Path(repo_path)
    if not HEX_40_RE.match(base_oid) or not HEX_40_RE.match(candidate_oid):
        raise ProofgateBootstrapVerifierError("Invalid base_oid or candidate_oid format")

    facts = compute_git_source_binding_facts(r_path, base_oid, candidate_oid)
    if not facts:
        raise ProofgateBootstrapVerifierError("Failed to extract Git source binding facts from repository")

    commit_header = facts.get("commit_header", "")
    parents = [line.split()[1] for line in commit_header.splitlines() if line.startswith("parent ")]
    if len(parents) != 1 or parents[0] != base_oid:
        raise ProofgateBootstrapVerifierError(f"Candidate commit must have exactly one parent equal to base_oid '{base_oid}'")

    path_tuples = facts.get("path_tuples", [])
    modified_paths = sorted([t[1] for t in path_tuples])

    import fnmatch

    def _matches_pattern(path: str, pat: str) -> bool:
        if pat.endswith("/**"):
            prefix = pat[:-3]
            return path == prefix or path.startswith(prefix + "/")
        return fnmatch.fnmatch(path, pat) or path == pat

    if landing_kind == "PR-T":
        if not modified_paths:
            raise ProofgateBootstrapVerifierError("PR-T candidate modified paths cannot be empty")
        inv_digest = hashlib.sha256((json.dumps(list(PR_T_18_PATTERNS), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
        if inv_digest != PR_T_18_PATTERNS_SHA256:
            raise ProofgateBootstrapVerifierError(f"PR-T pattern inventory SHA-256 mismatch (expected {PR_T_18_PATTERNS_SHA256}, got {inv_digest})")
        paths_digest = hashlib.sha256((json.dumps(list(PR_T_18_PATHS), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
        if paths_digest != PR_T_18_PATHS_SHA256:
            raise ProofgateBootstrapVerifierError(f"PR-T exact path inventory SHA-256 mismatch (expected {PR_T_18_PATHS_SHA256}, got {paths_digest})")

        for p in modified_paths:
            if not any(_matches_pattern(p, pat) for pat in PR_T_18_PATTERNS):
                raise ProofgateBootstrapVerifierError(f"PR-T candidate contains unauthorized non-test path: {p}")
            if p.startswith("phase-loop-runtime/src/") or p.startswith(".github/workflows/"):
                raise ProofgateBootstrapVerifierError(f"PR-T candidate contains production path: {p}")

        pr_t_exact = sorted(PR_T_18_PATHS)
        if len(modified_paths) != 18 or modified_paths != pr_t_exact:
            raise ProofgateBootstrapVerifierError(f"PR-T candidate modified paths must match exact 18-path inventory. Got: {modified_paths}")
    elif landing_kind == "PR-B":
        if modified_paths != list(PR_B_5_PATHS):
            raise ProofgateBootstrapVerifierError(f"PR-B modified paths do not match exact 5 PR-B path set. Got: {modified_paths}")
        inv_digest = hashlib.sha256((json.dumps(modified_paths, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
        if inv_digest != PR_B_5_PATHS_SHA256:
            raise ProofgateBootstrapVerifierError("PR-B path inventory SHA-256 mismatch")

    inv_38_digest = hashlib.sha256((json.dumps(list(PHASE_38_PATTERNS), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
    if inv_38_digest != PHASE_38_PATTERNS_SHA256:
        raise ProofgateBootstrapVerifierError("Production 38-pattern digest mismatch")

    exp_nodeids_sha = hashlib.sha256((json.dumps(sorted(list(EXPECTED_PHASE_NODEIDS)), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest()
    if exp_nodeids_sha != EXPECTED_39_NODEIDS_SHA256:
        raise ProofgateBootstrapVerifierError("Expected 39 nodeids SHA-256 mismatch")

    if not isinstance(github_pr, dict):
        raise ProofgateBootstrapVerifierError("github_pr must be a dictionary")
    if github_pr.get("repo") not in ("Consiliency/agent-harness", "1280382652"):
        raise ProofgateBootstrapVerifierError("github_pr repo mismatch")
    if github_pr.get("base_sha") and github_pr["base_sha"] != base_oid:
        raise ProofgateBootstrapVerifierError("github_pr base_sha mismatch")
    if github_pr.get("head_sha") and github_pr["head_sha"] != candidate_oid:
        raise ProofgateBootstrapVerifierError("github_pr head_sha mismatch")

    target_digest = facts["change_tuple_digest"]
    path_blob_dig = facts["path_blob_digest"]

    # Compute actual digests over actual artifact file bytes if present; fail closed if absent or unreadable
    run_dir_env = os.environ.get("PHASE_LOOP_RUN_DIR")
    run_dir_path = Path(run_dir_env) if run_dir_env else None

    def _read_artifact_digest(filename: str, label: str) -> str:
        candidates = [
            r_path / filename,
            r_path / ".phase-loop" / "runs" / filename,
        ]
        if run_dir_path:
            candidates.insert(0, run_dir_path / filename)
        for c in candidates:
            if c.exists() and c.is_file():
                try:
                    b = c.read_bytes()[:16777216]
                    return hashlib.sha256(b).hexdigest()
                except Exception as exc:
                    raise ProofgateBootstrapVerifierError(f"Required artifact {filename} ({label}) unreadable: {exc}") from exc
        raise ProofgateBootstrapVerifierError(f"Required artifact {filename} ({label}) absent or unreadable")

    raw_log_dig = _read_artifact_digest("verification.log", "raw_log")
    junit_def_dig = _read_artifact_digest("compat-default.junit.xml", "compat_default")
    junit_red_dig = _read_artifact_digest("compat-forced-red.junit.xml", "compat_forced_red")
    junit_ord_dig = _read_artifact_digest("compat-ordinary.junit.xml", "compat_ordinary")
    junit_att_dig = _read_artifact_digest("compat-attended.junit.xml", "compat_attended")

    ctrl_iso_dig = _read_artifact_digest("ctrl_isolation.log", "ctrl_isolation")
    ctrl_tnt_dig = _read_artifact_digest("ctrl_taint.log", "ctrl_taint")
    ctrl_mis_dig = _read_artifact_digest("ctrl_misuse.log", "ctrl_misuse")
    ctrl_ctl_dig = _read_artifact_digest("ctrl_control.log", "ctrl_control")
    ctrl_can_dig = _read_artifact_digest("ctrl_positive_canary.log", "ctrl_positive_canary")

    evidence_payload = {
        "candidate_oid": candidate_oid,
        "base_oid": base_oid,
        "path_blob_digest": path_blob_dig,
        "change_tuple_digest": target_digest,
        "topology": {"two_parent": True, "every_parent_present": True, "parent_oids": [base_oid, candidate_oid]},
        "seat_records": seat_records,
        "seat_chronology": seat_chronology,
        "author_vendor": AUTHOR_VENDOR,
        "raw_log_digest": raw_log_dig,
        "junit_mode_digests": {
            "default": junit_def_dig,
            "forced_red": junit_red_dig,
            "ordinary": junit_ord_dig,
            "attended": junit_att_dig,
        },
        "control_digests": {
            "isolation": ctrl_iso_dig,
            "taint": ctrl_tnt_dig,
            "misuse": ctrl_mis_dig,
            "control": ctrl_ctl_dig,
            "positive_canary": ctrl_can_dig,
        },
        "github_pr": github_pr,
    }
    eval_res = evaluate_unit_double_bootstrap_merge_review_gate(evidence_payload, expected_digest=target_digest)
    eval_res["evidence_kind"] = "unit_double"
    eval_res["decisive"] = False
    eval_res["change_tuple_digest"] = target_digest
    eval_res["path_blob_digest"] = path_blob_dig
    return eval_res


def _path_scope_digest(path_tuples: list[tuple[str, str, str, str, str, str, str]]) -> str:
    """Digest the real, ordered Git tuple/path scope without trusting caller metadata."""
    payload = json.dumps(path_tuples, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _coordinator_run_dir(coordinator_root: Path) -> Path:
    """Returns the only evidence root a decisive coordinator verifier may read."""
    value = os.environ.get("PHASE_LOOP_RUN_DIR")
    if not value:
        raise ProofgateBootstrapVerifierError("decisive coordinator evidence requires PHASE_LOOP_RUN_DIR")
    run_dir = Path(value).resolve()
    if run_dir != coordinator_root:
        raise ProofgateBootstrapVerifierError("PHASE_LOOP_RUN_DIR must be the coordinator-owned evidence root")
    if run_dir.is_symlink() or any(parent.is_symlink() for parent in run_dir.parents):
        raise ProofgateBootstrapVerifierError("coordinator evidence root is symlinked")
    return run_dir


def _verify_frozen_coordinator_root(coordinator_root: Path) -> None:
    """Reject evidence that remains writable by the candidate-side verifier."""
    if coordinator_root.stat().st_mode & 0o222:
        raise ProofgateBootstrapVerifierError("coordinator evidence root remains caller-writable")
    for artifact in coordinator_root.iterdir():
        if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_mode & 0o222:
            raise ProofgateBootstrapVerifierError(
                f"coordinator evidence artifact remains caller-writable or unsafe: {artifact.name}"
            )


def _read_coordinator_artifact(coordinator_root: Path, filename: str) -> bytes:
    """Read an exact coordinator artifact, with no candidate-repository fallback."""
    artifact = coordinator_root / filename
    if not artifact.is_file() or artifact.is_symlink():
        raise ProofgateBootstrapVerifierError(f"coordinator artifact absent or unsafe: {filename}")
    try:
        return artifact.read_bytes()
    except OSError as exc:
        raise ProofgateBootstrapVerifierError(f"coordinator artifact unreadable: {filename}") from exc


def coordinator_evidence_capture_pytest_args(
    mode: str,
    run_dir: Path | None = None,
    *,
    evidence_by_mode: dict[str, tuple[str, str]] | None = None,
    nodeids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    evidence_map = dict(evidence_by_mode or COORDINATOR_EVIDENCE_BY_MODE)
    if "bootstrap_candidate" not in evidence_map:
        evidence_map["bootstrap_candidate"] = ("compat-candidate.junit.xml", "phase_reports_candidate.json")
    if mode not in evidence_map:
        raise ProofgateBootstrapVerifierError(f"unknown coordinator evidence mode: {mode}")
    junit_filename, _phase_reports_filename = evidence_map[mode]
    junit_path = f"$PHASE_LOOP_RUN_DIR/{junit_filename}" if run_dir is None else str(run_dir / junit_filename)
    if nodeids is not None:
        nodeid_args = tuple(nodeids)
    elif mode == "bootstrap_candidate":
        nodeid_args = tuple(
            nodeid.removeprefix("phase-loop-runtime/") if hasattr(nodeid, "removeprefix")
            else (nodeid[19:] if nodeid.startswith("phase-loop-runtime/") else nodeid)
            for nodeid in BOOTSTRAP_CANDIDATE_NODEIDS
        )
    else:
        nodeid_args = tuple(
            nodeid.removeprefix("phase-loop-runtime/") if hasattr(nodeid, "removeprefix")
            else (nodeid[19:] if nodeid.startswith("phase-loop-runtime/") else nodeid)
            for nodeid in EXPECTED_PHASE_NODEIDS
        )
    return (*nodeid_args, "-p", "tests.proofgate_tdd_guard", "-o", "junit_family=legacy", f"--junitxml={junit_path}", "-q")


def coordinator_evidence_capture_argv(
    mode: str,
    *,
    evidence_by_mode: dict[str, tuple[str, str]] | None = None,
    nodeids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Frozen, shell-free coordinator command for an authority-bearing evidence mode."""
    mode_env = {
        "default": (),
        "forced_red": ("PHASE_LOOP_TDD_EXPECT_PROOFGATE=1",),
        "ordinary_hermetic": ("PHASE_LOOP_PROOFGATE_ORDINARY_HERMETIC=1",),
        "attended_live": ("PHASE_LOOP_PROOFGATE_ATTENDED_LIVE=1",),
        "bootstrap_candidate": (
            "PHASE_LOOP_TDD_EXPECT_PROOFGATE_BOOTSTRAP_CANDIDATE=1",
            "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING=$PHASE_LOOP_RUN_DIR/bootstrap-candidate-binding.json",
        ),
    }
    evidence_map = dict(evidence_by_mode or COORDINATOR_EVIDENCE_BY_MODE)
    if "bootstrap_candidate" not in evidence_map:
        evidence_map["bootstrap_candidate"] = ("compat-candidate.junit.xml", "phase_reports_candidate.json")
    if mode not in evidence_map:
        raise ProofgateBootstrapVerifierError(f"unknown coordinator evidence mode: {mode}")
    if mode not in mode_env:
        raise ProofgateBootstrapVerifierError(f"unknown coordinator evidence mode: {mode}")
    env_vars = mode_env[mode]
    prefix = ("env", *env_vars) if env_vars else ()
    return (*prefix, sys.executable, "-m", "pytest", *coordinator_evidence_capture_pytest_args(mode, evidence_by_mode=evidence_map, nodeids=nodeids))


def _load_coordinator_phase_report(coordinator_root: Path, mode: str, *, evidence_by_mode: dict[str, tuple[str, str]] | None = None) -> dict[str, Any]:
    evidence_map = dict(evidence_by_mode or COORDINATOR_EVIDENCE_BY_MODE)
    if "bootstrap_candidate" not in evidence_map:
        evidence_map["bootstrap_candidate"] = ("compat-candidate.junit.xml", "phase_reports_candidate.json")
    if mode not in evidence_map:
        raise ProofgateBootstrapVerifierError(f"unknown coordinator evidence mode: {mode}")
    _junit_filename, report_filename = evidence_map[mode]
    try:
        payload = json.loads(_read_coordinator_artifact(coordinator_root, report_filename).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofgateBootstrapVerifierError(f"coordinator phase report is invalid JSON: {mode}") from exc
    required = {"schema", "exitstatus", "runs", "reports", "capture"}
    allowed = required | {"runner_envelope"}
    if not isinstance(payload, dict) or set(payload) not in (required, allowed):
        raise ProofgateBootstrapVerifierError(f"coordinator phase report schema mismatch: {mode}")
    if payload["schema"] != "proofgate_phase_reports.v1":
        raise ProofgateBootstrapVerifierError(f"coordinator phase report schema version mismatch: {mode}")
    if not isinstance(payload["runs"], list) or len(payload["runs"]) != 1 or not isinstance(payload["runs"][0], dict):
        raise ProofgateBootstrapVerifierError(f"coordinator phase report must contain one complete run: {mode}")
    if payload["runs"][0].get("reports") != payload["reports"]:
        raise ProofgateBootstrapVerifierError(f"coordinator phase report aggregate/run mismatch: {mode}")
    if payload["runs"][0].get("exitstatus") != payload["exitstatus"]:
        raise ProofgateBootstrapVerifierError(f"coordinator phase report aggregate/run exitstatus mismatch: {mode}")
    if not isinstance(payload["reports"], list):
        raise ProofgateBootstrapVerifierError(f"coordinator phase report reports are invalid: {mode}")
    return payload


def verify_coordinator_evidence_capture(
    coordinator_root: Path | str,
    mode: str,
    *,
    expected_candidate_oid: str | None = None,
    expected_attended_stage: str | None = None,
    evidence_by_mode: dict[str, tuple[str, str]] | None = None,
    nodeids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Verify a plan-named JUnit plus the reporting-plugin phase report as one capture.

    A bare JUnit report is compatibility evidence only.  Authorization requires the matching
    plugin-produced report, its exact command provenance, its legacy JUnit capture receipt, and
    parser-level node/property accounting.
    """
    root = Path(coordinator_root).resolve()
    _coordinator_run_dir(root)
    evidence_map = evidence_by_mode or COORDINATOR_EVIDENCE_BY_MODE
    if mode not in evidence_map:
        raise ProofgateBootstrapVerifierError(f"unknown coordinator evidence mode: {mode}")
    junit_filename, _report_filename = evidence_map[mode]
    junit_bytes = _read_coordinator_artifact(root, junit_filename)
    payload = _load_coordinator_phase_report(root, mode, evidence_by_mode=evidence_map)
    capture = payload["capture"]
    expected_args = list(coordinator_evidence_capture_pytest_args(mode, evidence_by_mode=evidence_map, nodeids=nodeids))
    expected_capture = {
        "schema": "proofgate_coordinator_evidence_capture.v1",
        "plugin": "tests.proofgate_tdd_guard",
        "junit_family": "legacy",
        "junit_filename": junit_filename,
        "junit_sha256": hashlib.sha256(junit_bytes).hexdigest(),
        "pytest_args_sha256": hashlib.sha256(json.dumps(expected_args).encode("utf-8")).hexdigest(),
    }
    if mode == "bootstrap_candidate":
        expected_capture["mode"] = "bootstrap_candidate"
        expected_capture["candidate_oid"] = expected_candidate_oid or ""
        expected_capture["run_identity"] = "coordinator-candidate"

    if capture != expected_capture:
        if isinstance(capture, dict) and mode == "bootstrap_candidate":
            for field in ("mode", "candidate_oid", "run_identity"):
                if capture.get(field) != expected_capture.get(field):
                    raise ProofgateBootstrapVerifierError(f"bootstrap_candidate capture mismatch for {field}")
        raise ProofgateBootstrapVerifierError(f"coordinator capture receipt mismatch: {mode}")

    if mode == "bootstrap_candidate":
        if not isinstance(payload.get("runs"), list) or len(payload["runs"]) != 1 or payload["runs"][0].get("run_identity") != "coordinator-candidate":
            raise ProofgateBootstrapVerifierError("bootstrap_candidate capture run_identity mismatch")
        for report in payload["reports"]:
            if report.get("candidate") != expected_candidate_oid:
                raise ProofgateBootstrapVerifierError("bootstrap_candidate report candidate mismatch")
            if report.get("run_identity") != "coordinator-candidate":
                raise ProofgateBootstrapVerifierError("bootstrap_candidate report run_identity mismatch")

    expected_args = list(coordinator_evidence_capture_pytest_args(mode, evidence_by_mode=evidence_map, nodeids=nodeids))
    for report in payload["reports"]:
        if not isinstance(report, dict) or not isinstance(report.get("argv"), list):
            raise ProofgateBootstrapVerifierError(f"coordinator report lacks plugin argv provenance: {mode}")
        argv = report["argv"]
        if argv[1:] != expected_args:
            raise ProofgateBootstrapVerifierError(f"coordinator report argv is not the frozen evidence command: {mode}")
        if report.get("command_digest") != hashlib.sha256(json.dumps(argv).encode("utf-8")).hexdigest():
            raise ProofgateBootstrapVerifierError(f"coordinator report command digest mismatch: {mode}")

    exitstatus = payload["exitstatus"]
    if not isinstance(exitstatus, int) or isinstance(exitstatus, bool):
        raise ProofgateBootstrapVerifierError(f"coordinator capture exitstatus is invalid: {mode}")
    if payload["runs"][0].get("exitstatus") != exitstatus:
        raise ProofgateBootstrapVerifierError(f"coordinator capture single run exitstatus mismatch: {mode}")
    if (mode == "forced_red" and exitstatus == 0) or (mode != "forced_red" and exitstatus != 0):
        raise ProofgateBootstrapVerifierError(f"coordinator capture exitstatus does not match mode: {mode}")
    if mode == "attended_live":
        expected_module_identity = hashlib.sha256(
            _read_coordinator_artifact(root, "proofgate-reference-code.bin")
        ).hexdigest()
        raw_receipts = _read_coordinator_artifact(root, ATTENDED_PROVIDER_RECEIPTS_FILENAME)
        try:
            external_receipts = json.loads(raw_receipts.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProofgateBootstrapVerifierError("external attended provider receipts are invalid") from exc
        if (
            json.dumps(external_receipts, sort_keys=True, separators=(",", ":")).encode("utf-8")
            != raw_receipts
            or external_receipts != payload.get("runner_envelope", {}).get("provider_receipts")
        ):
            raise ProofgateBootstrapVerifierError(
                "attended provider receipts do not match coordinator-owned bytes"
            )
    accounting = verify_junit_accounting(
        junit_bytes.decode("utf-8"),
        mode,
        phase_reports=payload["reports"],
        runner_envelope=payload.get("runner_envelope"),
        expected_attended_head_identity=expected_candidate_oid,
        expected_attended_stage=expected_attended_stage,
        expected_attended_module_identity=(
            expected_module_identity if mode == "attended_live" else None
        ),
    )
    return {**accounting, "mode": mode, "reports": payload["reports"], "runner_envelope": payload.get("runner_envelope")}


def _decode_observed_object(name: str, value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProofgateBootstrapVerifierError(f"observed {name} is not canonical JSON") from exc
    if not isinstance(decoded, dict):
        raise ProofgateBootstrapVerifierError(f"observed {name} must be a JSON object")
    if json.dumps(decoded, sort_keys=True, separators=(",", ":")) != value:
        raise ProofgateBootstrapVerifierError(f"observed {name} is not canonical JSON bytes")
    return decoded


def _validate_observed_control_artifact(
    coordinator_root: Path,
    filename: str,
    raw: bytes,
    candidate_oid: str,
    expected_module_identity: str,
) -> None:
    """Validate case-level coordinator probes and their bound raw/component bytes."""
    try:
        control = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} is not valid JSON") from exc
    if json.dumps(control, sort_keys=True, separators=(",", ":")).encode("utf-8") != raw:
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} is not canonical JSON")
    required = {
        "candidate_oid",
        "case_matrix_sha256",
        "cases",
        "components",
        "control",
        "producer",
        "raw_probe_log",
        "schema",
    }
    if not isinstance(control, dict) or set(control) != required:
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} has an invalid schema")
    if (
        control["schema"] != "proofgate_control_artifact.v2"
        or control["control"] != filename
        or control["candidate_oid"] != candidate_oid
        or control["producer"] != "proofgate-coordinator-reference"
    ):
        raise ProofgateBootstrapVerifierError(
            f"control artifact {filename} is not candidate/coordinator bound"
        )

    raw_binding = control["raw_probe_log"]
    expected_raw_path = f"{filename}.raw"
    if not isinstance(raw_binding, dict) or set(raw_binding) != {"path", "sha256"}:
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} raw-log binding is invalid")
    if raw_binding.get("path") != expected_raw_path:
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} raw-log path drifted")
    raw_probe_bytes = _read_coordinator_artifact(coordinator_root, expected_raw_path)
    if raw_binding.get("sha256") != hashlib.sha256(raw_probe_bytes).hexdigest():
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} raw-log digest mismatch")
    try:
        raw_observations = json.loads(raw_probe_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofgateBootstrapVerifierError(
            f"control artifact {filename} raw-log content is invalid"
        ) from exc
    if (
        not isinstance(raw_observations, dict)
        or json.dumps(raw_observations, sort_keys=True, separators=(",", ":")).encode("utf-8")
        != raw_probe_bytes
    ):
        raise ProofgateBootstrapVerifierError(
            f"control artifact {filename} raw-log content is not canonical"
        )

    components = control["components"]
    if not isinstance(components, dict) or set(components) != set(BOOTSTRAP_CONTROL_COMPONENTS):
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} component provenance is invalid")
    for component in BOOTSTRAP_CONTROL_COMPONENTS:
        binding = components[component]
        expected_path = f"proofgate-reference-{component}.bin"
        if not isinstance(binding, dict) or binding.get("path") != expected_path or set(binding) != {"path", "sha256"}:
            raise ProofgateBootstrapVerifierError(
                f"control artifact {filename} {component} provenance is invalid"
            )
        component_bytes = _read_coordinator_artifact(coordinator_root, expected_path)
        if binding["sha256"] != hashlib.sha256(component_bytes).hexdigest():
            raise ProofgateBootstrapVerifierError(
                f"control artifact {filename} {component} digest mismatch"
            )
    if components["code"]["sha256"] != expected_module_identity:
        raise ProofgateBootstrapVerifierError(
            f"control artifact {filename} code identity does not match attended runner"
        )

    cases = control["cases"]
    if not isinstance(cases, list):
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} case matrix is invalid")
    if control["case_matrix_sha256"] != hashlib.sha256(
        json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest():
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} case-matrix digest mismatch")
    expected_case_ids = BOOTSTRAP_CONTROL_CASES[filename]
    if tuple(record.get("case_id") for record in cases if isinstance(record, dict)) != expected_case_ids:
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} case inventory mismatch")
    if tuple(raw_observations) != expected_case_ids or any(
        not isinstance(value, str) or not value for value in raw_observations.values()
    ):
        raise ProofgateBootstrapVerifierError(f"control artifact {filename} raw observation inventory mismatch")
    counter_fields = {
        "connect",
        "dns",
        "downstream_bytes",
        "followup_requests",
        "http",
        "provider_trap",
        "request_count",
        "session_mutations",
        "tls",
        "tool_round_trip_count",
        "turn_count",
    }
    for record in cases:
        if not isinstance(record, dict) or set(record) != {
            "case_id",
            "counters",
            "expected_outcome",
            "observed_outcome",
            "path_entered",
            "raw_observation_sha256",
        }:
            raise ProofgateBootstrapVerifierError(f"control artifact {filename} contains a malformed case")
        case_id = record["case_id"]
        counters = record["counters"]
        if record["path_entered"] is not True:
            raise ProofgateBootstrapVerifierError(f"control artifact {filename} did not enter {case_id}")
        if not isinstance(record["raw_observation_sha256"], str) or not HEX_64_RE.match(
            record["raw_observation_sha256"]
        ):
            raise ProofgateBootstrapVerifierError(f"control artifact {filename} lacks raw observation for {case_id}")
        if record["raw_observation_sha256"] != hashlib.sha256(
            raw_observations[case_id].encode("utf-8")
        ).hexdigest():
            raise ProofgateBootstrapVerifierError(
                f"control artifact {filename} raw observation digest mismatch for {case_id}"
            )
        if not isinstance(counters, dict) or set(counters) != counter_fields or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counters.values()
        ):
            raise ProofgateBootstrapVerifierError(f"control artifact {filename} counters are invalid for {case_id}")
        if case_id in BOOTSTRAP_LIVE_REACHABILITY_CASES:
            if record["expected_outcome"] != "reachable" or record["observed_outcome"] != "reachable":
                raise ProofgateBootstrapVerifierError(f"control artifact {filename} positive canary failed: {case_id}")
            if (
                counters["request_count"] < 2
                or counters["turn_count"] < 2
                or counters["tool_round_trip_count"] < 1
                or counters["downstream_bytes"] < 1
                or counters["provider_trap"] != 0
                or counters["session_mutations"] != 0
                or counters["followup_requests"] != 0
            ):
                raise ProofgateBootstrapVerifierError(
                    f"control artifact {filename} positive counters are invalid: {case_id}"
                )
        elif case_id in BOOTSTRAP_ZERO_EFFECT_CASES:
            if record["expected_outcome"] != "denied" or record["observed_outcome"] != "denied":
                raise ProofgateBootstrapVerifierError(f"control artifact {filename} denial failed: {case_id}")
            if any(counters.values()):
                raise ProofgateBootstrapVerifierError(
                    f"control artifact {filename} denial produced an effect: {case_id}"
                )
        else:
            if record["expected_outcome"] != "verified" or record["observed_outcome"] != "verified":
                raise ProofgateBootstrapVerifierError(f"control artifact {filename} invariant failed: {case_id}")
            if any(counters.values()):
                raise ProofgateBootstrapVerifierError(
                    f"control artifact {filename} invariant counters drifted: {case_id}"
                )


def verify_observed_premerge_bootstrap_review_gate(
    repo_path: Path | str,
    base_oid: str,
    candidate_oid: str,
    *,
    landing_kind: str,
    boundary: Any,
    admin_boundary: Any = None,
) -> dict[str, Any]:
    """Decisively authorize a PR-T/PR-B merge only from local Git plus coordinator observation.

    The legacy unit-double evaluator remains intentionally non-decisive.  This path reads the
    change tuple and artifact bytes itself, compares them to the coordinator's one-shot,
    read-only observation, then validates the observed seats, PR identity, JUnit accounting,
    and control artifacts before it can assert authority.
    """
    r_path = Path(repo_path).resolve()
    if landing_kind not in LANDING_REF_BINDINGS:
        raise ProofgateBootstrapVerifierError(f"observed pre-merge gate only authorizes PR-T/PR-B, got {landing_kind}")
    if landing_kind == "PR-B":
        if admin_boundary is None:
            admin_boundary = ProofgateAdminControlPlaneBoundary()
        elif type(admin_boundary) is not ProofgateAdminControlPlaneBoundary:
            raise ProofgateBootstrapVerifierError(
                f"Only exact ProofgateAdminControlPlaneBoundary is allowed for admin_boundary, got {type(admin_boundary).__name__}"
            )
    if type(boundary) is not CoordinatorBootstrapMergeObservationBoundary:
        raise ProofgateBootstrapVerifierError("decisive pre-merge gate requires the operational coordinator boundary")
    coordinator_root = boundary.coordinator_root
    try:
        coordinator_root.relative_to(r_path)
    except ValueError:
        pass
    else:
        raise ProofgateBootstrapVerifierError("coordinator evidence root must be outside the candidate repository")
    _coordinator_run_dir(coordinator_root)
    _verify_frozen_coordinator_root(coordinator_root)
    facts = compute_git_source_binding_facts(r_path, base_oid, candidate_oid)
    if not facts:
        raise ProofgateBootstrapVerifierError("failed to obtain real Git source facts for decisive pre-merge gate")

    expected_head_ref, expected_base_ref = LANDING_REF_BINDINGS[landing_kind]
    if expected_head_ref == expected_base_ref:
        raise ProofgateBootstrapVerifierError("landing head and base refs must be distinct")
    for ref_name, expected_oid in ((expected_head_ref, candidate_oid), (expected_base_ref, base_oid)):
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{ref_name}^{{commit}}"],
            cwd=r_path,
            capture_output=True,
            text=True,
            check=False,
        )
        actual_oid = proc.stdout.strip()
        if proc.returncode != 0 or actual_oid != expected_oid:
            raise ProofgateBootstrapVerifierError(
                f"local Git ref binding mismatch for {landing_kind}: refs/heads/{ref_name}"
            )

    request = ProofgateBootstrapMergeObservationRequest(
        repository=COORDINATOR_REPOSITORY,
        base_oid=base_oid,
        candidate_oid=candidate_oid,
        landing_kind=landing_kind,
    )
    try:
        envelope = boundary.observe(request)
    except Exception as exc:
        raise ProofgateBootstrapVerifierError("coordinator observation boundary unavailable") from exc
    if type(envelope) is not CoordinatorBootstrapMergeObservationEnvelope:
        raise ProofgateBootstrapVerifierError("coordinator observation has an invalid operational envelope")
    if envelope.schema != BOOTSTRAP_COORDINATOR_ENVELOPE_SCHEMA:
        raise ProofgateBootstrapVerifierError("coordinator observation envelope schema mismatch")
    observation = envelope.observation
    observation_bytes = _canonical_json_bytes(dataclasses.asdict(observation))
    if envelope.observation_sha256 != hashlib.sha256(observation_bytes).hexdigest():
        raise ProofgateBootstrapVerifierError("coordinator observation bytes/receipt mismatch")
    producer = envelope.producer_receipt
    process = envelope.process_receipt
    expected_producer = {
        "schema": BOOTSTRAP_COORDINATOR_PRODUCER_RECEIPT_SCHEMA,
        "producer": "proofgate-coordinator",
        "writer_pid": producer.get("writer_pid") if isinstance(producer, dict) else None,
        "repository": COORDINATOR_REPOSITORY,
        "base_oid": base_oid,
        "candidate_oid": candidate_oid,
        "landing_kind": landing_kind,
        "observation_filename": "bootstrap-observation.json",
        "observation_sha256": envelope.observation_sha256,
    }
    if producer != expected_producer:
        raise ProofgateBootstrapVerifierError("coordinator producer receipt is not candidate-bound")
    if not isinstance(producer["writer_pid"], int) or producer["writer_pid"] == os.getpid():
        raise ProofgateBootstrapVerifierError("coordinator evidence was not written by a distinct producer process")
    expected_process = {
        "schema": BOOTSTRAP_COORDINATOR_PROCESS_RECEIPT_SCHEMA,
        "reader_pid": process.get("reader_pid") if isinstance(process, dict) else None,
        "request_sha256": hashlib.sha256(_canonical_json_bytes(dataclasses.asdict(request))).hexdigest(),
        "observation_sha256": envelope.observation_sha256,
        "producer_receipt_sha256": hashlib.sha256(_canonical_json_bytes(producer)).hexdigest(),
    }
    if not isinstance(process, dict) or set(process) != set(expected_process) or process != expected_process:
        raise ProofgateBootstrapVerifierError("coordinator process receipt mismatch")
    if not isinstance(process["reader_pid"], int) or process["reader_pid"] == os.getpid():
        raise ProofgateBootstrapVerifierError("coordinator observation was not read by a fresh process")
    if process["reader_pid"] == producer["writer_pid"]:
        raise ProofgateBootstrapVerifierError("coordinator producer and reader process identities are not distinct")
    if observation.schema != BOOTSTRAP_MERGE_OBSERVATION_SCHEMA:
        raise ProofgateBootstrapVerifierError("coordinator observation schema mismatch")

    actual_path_scope_digest = _path_scope_digest(facts["path_tuples"])
    if (
        observation.base_oid != base_oid
        or observation.candidate_oid != candidate_oid
        or observation.change_tuple_digest != facts["change_tuple_digest"]
        or observation.path_blob_digest != facts["path_blob_digest"]
        or observation.path_scope_digest != actual_path_scope_digest
    ):
        raise ProofgateBootstrapVerifierError("coordinator observation does not bind the real Git change tuple/path scope")

    observed_pr = _decode_observed_object("github_pr", observation.github_pr_json)
    required_pr_fields = {"number", "repo", "head_ref", "base_ref", "head_sha", "base_sha"}
    if set(observed_pr) != required_pr_fields:
        raise ProofgateBootstrapVerifierError("coordinator observation GitHub PR identity schema mismatch")
    if (
        not isinstance(observed_pr["number"], int)
        or observed_pr["number"] <= 0
        or observed_pr["repo"] != COORDINATOR_REPOSITORY
        or observed_pr["head_ref"] != expected_head_ref
        or observed_pr["base_ref"] != expected_base_ref
        or observed_pr["head_ref"] == observed_pr["base_ref"]
        or observed_pr["base_sha"] != base_oid
        or observed_pr["head_sha"] != candidate_oid
    ):
        raise ProofgateBootstrapVerifierError("coordinator observation GitHub PR identity is not candidate-bound")

    if landing_kind == "PR-B":
        required_candidate_files = (
            "admin-identity-binding.json",
            "bootstrap-candidate-binding.json",
            "bootstrap-candidate-verdict.json",
            "compat-candidate.junit.xml",
            "phase_reports_candidate.json",
            "selector-repair-review-binding.json",
        )
        missing_candidate_files = tuple(
            filename
            for filename in required_candidate_files
            if not (coordinator_root / filename).is_file()
        )
        if missing_candidate_files:
            raise ProofgateBootstrapVerifierError(
                "PR-B candidate artifacts missing: " + ", ".join(missing_candidate_files)
            )
        evidence_artifacts = (
            ("compat-default.junit.xml", "phase_reports_default.json", "default"),
            ("compat-forced-red.junit.xml", "phase_reports_forced_red.json", "forced_red"),
        )
        forbidden_files = {
            "proofgate-candidate-ordinary.junit.xml",
            "proofgate-candidate-ordinary.phase-reports.json",
            "proofgate-candidate-attended.junit.xml",
            "proofgate-candidate-attended.phase-reports.json",
            "compat-ordinary.junit.xml",
            "compat-ordinary.phase-reports.json",
            "compat-attended.junit.xml",
            "compat-attended.phase-reports.json",
        }
        for mode_key in ("ordinary_hermetic", "attended_live", "ordinary", "attended"):
            if mode_key in COORDINATOR_EVIDENCE_BY_MODE:
                j_fn, pr_fn = COORDINATOR_EVIDENCE_BY_MODE[mode_key]
                forbidden_files.add(j_fn)
                forbidden_files.add(pr_fn)
        for forbidden_file in sorted(forbidden_files):
            if (coordinator_root / forbidden_file).exists():
                raise ProofgateBootstrapVerifierError(f"PR-B forbids ordinary or attended-live evidence artifact: {forbidden_file}")
    else:
        evidence_artifacts = COORDINATOR_EVIDENCE_ARTIFACTS

    evidence_by_mode = {
        mode: (junit_filename, phase_reports_filename)
        for junit_filename, phase_reports_filename, mode in evidence_artifacts
    }

    actual_junit_digests = {
        filename: hashlib.sha256(_read_coordinator_artifact(coordinator_root, filename)).hexdigest()
        for filename, _phase_reports_filename, _mode in evidence_artifacts
    }
    observed_junit_digests = dict(observation.junit_artifact_digests)
    if len(observation.junit_artifact_digests) != len(actual_junit_digests) or set(observed_junit_digests) != set(actual_junit_digests) or observed_junit_digests != actual_junit_digests:
        raise ProofgateBootstrapVerifierError("coordinator observation JUnit artifact digest mismatch")

    actual_phase_report_digests = {
        report_filename: hashlib.sha256(_read_coordinator_artifact(coordinator_root, report_filename)).hexdigest()
        for _filename, report_filename, _mode in evidence_artifacts
    }
    observed_phase_report_digests = dict(observation.junit_phase_report_digests)
    if len(observation.junit_phase_report_digests) != len(actual_phase_report_digests) or set(observed_phase_report_digests) != set(actual_phase_report_digests) or observed_phase_report_digests != actual_phase_report_digests:
        raise ProofgateBootstrapVerifierError("coordinator observation phase-report digest mismatch")

    reports_by_mode = _decode_observed_object("junit_phase_reports", observation.junit_phase_reports_json)
    if landing_kind == "PR-B":
        expected_modes = {"default", "forced_red", "bootstrap_candidate"}
    else:
        expected_modes = {mode for _filename, _phase_reports_filename, mode in evidence_artifacts}

    if set(reports_by_mode) != expected_modes:
        raise ProofgateBootstrapVerifierError("coordinator observation JUnit report modes mismatch")
    for mode in expected_modes:
        report_payload = reports_by_mode[mode]
        if not isinstance(report_payload, dict) or set(report_payload) not in ({"reports"}, {"reports", "runner_envelope"}):
            raise ProofgateBootstrapVerifierError(f"coordinator observation JUnit reports malformed for {mode}")
        if mode == "attended_live" and set(report_payload) != {"reports", "runner_envelope"}:
            raise ProofgateBootstrapVerifierError("attended JUnit requires an external runner envelope")
        if mode != "attended_live" and set(report_payload) != {"reports"}:
            raise ProofgateBootstrapVerifierError(f"non-attended JUnit carries a forbidden runner envelope: {mode}")
        if mode in ("default", "forced_red", "ordinary_hermetic", "attended_live"):
            capture = verify_coordinator_evidence_capture(
                coordinator_root,
                mode,
                expected_candidate_oid=candidate_oid,
                expected_attended_stage="candidate" if mode == "attended_live" else None,
                evidence_by_mode=evidence_by_mode,
            )
            if capture["reports"] != report_payload["reports"] or capture.get("runner_envelope") != report_payload.get("runner_envelope"):
                raise ProofgateBootstrapVerifierError(f"coordinator capture reports do not match observed reports: {mode}")

    if landing_kind == "PR-B":
        cand_capture = verify_coordinator_evidence_capture(
            coordinator_root,
            "bootstrap_candidate",
            expected_candidate_oid=candidate_oid,
            evidence_by_mode={
                **evidence_by_mode,
                "bootstrap_candidate": ("compat-candidate.junit.xml", "phase_reports_candidate.json"),
            },
            nodeids=BOOTSTRAP_CANDIDATE_NODEIDS,
        )
        if cand_capture.get("reports") != reports_by_mode.get("bootstrap_candidate", {}).get("reports"):
            raise ProofgateBootstrapVerifierError("coordinator capture reports do not match observed reports: bootstrap_candidate")
        required_cand_artifacts = {
            "admin-identity-binding.json",
            "bootstrap-candidate-binding.json",
            "bootstrap-candidate-verdict.json",
            "compat-candidate.junit.xml",
            "phase_reports_candidate.json",
            "selector-repair-review-binding.json",
        }
        obs_cand_digests_raw = getattr(observation, "candidate_artifact_digests", ())
        if not isinstance(obs_cand_digests_raw, (tuple, list)):
            raise ProofgateBootstrapVerifierError("coordinator observation candidate artifact digest mismatch")
        obs_cand_digests = dict(obs_cand_digests_raw)
        if not required_cand_artifacts.issubset(set(obs_cand_digests)):
            raise ProofgateBootstrapVerifierError("coordinator observation candidate artifact digest mismatch")
        for filename, expected_sha in obs_cand_digests.items():
            actual_sha = hashlib.sha256(_read_coordinator_artifact(coordinator_root, filename)).hexdigest()
            if actual_sha != expected_sha:
                raise ProofgateBootstrapVerifierError("coordinator observation candidate artifact digest mismatch")

        cand_binding_res = verify_bootstrap_candidate_binding(
            repo_path=repo_path,
            binding_path=coordinator_root / "bootstrap-candidate-binding.json",
            expected_original_tests_landing=ORIGINAL_TESTS_LANDING_OID,
        )
        cand_binding = cand_binding_res["binding_data"]

        review_binding_path = coordinator_root / "selector-repair-review-binding.json"
        if not review_binding_path.is_file():
            raise ProofgateBootstrapVerifierError("selector repair review binding artifact required at PR-B")

        review_binding_res = verify_selector_repair_review_binding(
            repo_path=repo_path,
            review_binding_path=review_binding_path,
            expected_original_tests_landing=cand_binding.get(
                "original_tests_landing_oid"
            ),
            expected_selector_repair_landing=cand_binding.get(
                "selector_repair_landing_oid"
            ),
        )
        review_binding = review_binding_res.get(
            "binding_data", review_binding_res.get("data", {})
        )
        if cand_binding.get("selector_repair_landing_oid") != review_binding.get("selector_repair_landing_oid"):
            raise ProofgateBootstrapVerifierError("selector repair landing OID mismatch between review binding and candidate binding")
        cand_binding_digest = cand_binding_res["binding_digest"]

        if cand_binding.get("base_oid") != base_oid:
            raise ProofgateBootstrapVerifierError("PR-B candidate binding base_oid mismatch")
        if cand_binding.get("candidate_oid") != candidate_oid:
            raise ProofgateBootstrapVerifierError("PR-B candidate binding candidate_oid mismatch")

        def_acc = verify_junit_accounting(
            _read_coordinator_artifact(coordinator_root, "compat-default.junit.xml").decode("utf-8"),
            mode="default",
            phase_reports=reports_by_mode["default"]["reports"],
        )
        if (def_acc["collected"], def_acc["passed"], def_acc["skipped"], def_acc["failed"]) != (39, 3, 36, 0):
            raise ProofgateBootstrapVerifierError("PR-B default JUnit accounting mismatch")

        red_acc = verify_junit_accounting(
            _read_coordinator_artifact(coordinator_root, "compat-forced-red.junit.xml").decode("utf-8"),
            mode="forced_red",
            phase_reports=reports_by_mode["forced_red"]["reports"],
        )
        if (red_acc["collected"], red_acc["passed"], red_acc["skipped"], red_acc["failed"]) != (39, 2, 0, 37):
            raise ProofgateBootstrapVerifierError("PR-B forced_red JUnit accounting mismatch")

        raw_cand_verdict = _read_coordinator_artifact(coordinator_root, "bootstrap-candidate-verdict.json")
        try:
            cand_verdict = json.loads(raw_cand_verdict.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProofgateBootstrapVerifierError("PR-B candidate verdict is invalid JSON") from exc
        if json.dumps(cand_verdict, sort_keys=True, separators=(",", ":")).encode("utf-8") != raw_cand_verdict:
            raise ProofgateBootstrapVerifierError("PR-B candidate verdict is not canonical JSON")

        if tuple(cand_verdict.keys()) != BOOTSTRAP_CANDIDATE_VERDICT_FIELDS:
            raise ProofgateBootstrapVerifierError("candidate verdict field keys mismatch: closed candidate verdict keys violation")

        if (
            cand_verdict.get("schema") != "proofgate_bootstrap_candidate_verdict.v1"
            or cand_verdict.get("status") != "verified"
            or cand_verdict.get("authorized_scope") != "sl0_b1_bootstrap_candidate_only"
            or cand_verdict.get("authorizes_implementation") is not False
            or cand_verdict.get("authorizes_final_completion") is not False
            or cand_verdict.get("evidence_bindings") != ["source", "selector", "binding", "junit", "phase_reports"]
            or cand_verdict.get("source_digest") != facts["change_tuple_digest"]
            or cand_verdict.get("selector_digest") != BOOTSTRAP_CANDIDATE_NODEIDS_SHA256
            or (
                cand_verdict.get("collected"),
                cand_verdict.get("passed"),
                cand_verdict.get("skipped"),
                cand_verdict.get("failed"),
                cand_verdict.get("errors"),
            )
            != (11, 11, 0, 0, 0)
        ):
            raise ProofgateBootstrapVerifierError("PR-B candidate verdict content or accounting mismatch")

        if cand_verdict.get("source_digest") != cand_binding.get("diff_sha256"):
            raise ProofgateBootstrapVerifierError("PR-B candidate verdict source_digest mismatch with candidate binding diff_sha256")

        if cand_verdict.get("binding_digest") != cand_binding_digest:
            raise ProofgateBootstrapVerifierError("PR-B candidate verdict binding digest mismatch")

        raw_cand_junit = _read_coordinator_artifact(coordinator_root, "compat-candidate.junit.xml")
        cand_junit_digest = hashlib.sha256(raw_cand_junit).hexdigest()
        if cand_verdict.get("junit_digest") != cand_junit_digest:
            raise ProofgateBootstrapVerifierError("PR-B candidate verdict junit digest mismatch")

        raw_cand_reports = _read_coordinator_artifact(coordinator_root, "phase_reports_candidate.json")
        try:
            cand_reports_payload = json.loads(raw_cand_reports.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProofgateBootstrapVerifierError("PR-B candidate phase reports is invalid JSON") from exc
        if json.dumps(cand_reports_payload, sort_keys=True, separators=(",", ":")).encode("utf-8") != raw_cand_reports:
            raise ProofgateBootstrapVerifierError("PR-B candidate phase reports is not canonical JSON")

        cand_reports_digest = hashlib.sha256(raw_cand_reports).hexdigest()
        if cand_verdict.get("phase_reports_digest") != cand_reports_digest:
            raise ProofgateBootstrapVerifierError("PR-B candidate verdict phase reports digest mismatch")

        obs_cand_reports = reports_by_mode.get("bootstrap_candidate", {}).get("reports")
        if cand_reports_payload.get("reports") != obs_cand_reports:
            raise ProofgateBootstrapVerifierError("PR-B candidate phase reports do not match coordinator observation")

        if cand_reports_payload.get("capture", {}).get("junit_sha256") != cand_junit_digest:
            raise ProofgateBootstrapVerifierError("PR-B candidate JUnit digest mismatch with candidate phase report capture")

        cand_acc = verify_junit_accounting(
            coordinator_root / "compat-candidate.junit.xml",
            mode="bootstrap_candidate",
            phase_reports=coordinator_root / "phase_reports_candidate.json",
        )
        if (cand_acc["collected"], cand_acc["passed"], cand_acc["skipped"], cand_acc["failed"]) != (11, 11, 0, 0):
            raise ProofgateBootstrapVerifierError("PR-B candidate JUnit accounting mismatch")

        admin_binding = verify_proofgate_admin_authority(
            boundary=admin_boundary,
            candidate_oid=candidate_oid,
            admin_binding_path=coordinator_root / "admin-identity-binding.json",
        )

    actual_control_digests = {
        filename: hashlib.sha256(_read_coordinator_artifact(coordinator_root, filename)).hexdigest()
        for filename in BOOTSTRAP_CONTROL_ARTIFACTS
    }
    observed_control_digests = dict(observation.control_artifact_digests)
    if len(observation.control_artifact_digests) != len(actual_control_digests) or set(observed_control_digests) != set(actual_control_digests) or observed_control_digests != actual_control_digests:
        raise ProofgateBootstrapVerifierError("coordinator observation control artifact digest mismatch")
    expected_module_identity = hashlib.sha256(
        _read_coordinator_artifact(coordinator_root, "proofgate-reference-code.bin")
    ).hexdigest()
    for filename in BOOTSTRAP_CONTROL_ARTIFACTS:
        _validate_observed_control_artifact(
            coordinator_root,
            filename,
            _read_coordinator_artifact(coordinator_root, filename),
            candidate_oid,
            expected_module_identity,
        )

    observed_seats = _decode_observed_object("seat_records", observation.seat_records_json)
    actual_seat_digests: dict[str, str] = {}
    for seat, filename in COORDINATOR_SEAT_ARTIFACTS:
        raw = _read_coordinator_artifact(coordinator_root, filename)
        actual_seat_digests[filename] = hashlib.sha256(raw).hexdigest()
        try:
            seat_payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProofgateBootstrapVerifierError(f"coordinator seat artifact is invalid: {seat}") from exc
        if seat_payload != observed_seats.get(seat):
            raise ProofgateBootstrapVerifierError(f"coordinator seat artifact does not match observed seat: {seat}")
    observed_seat_digests = dict(observation.seat_artifact_digests)
    if len(observation.seat_artifact_digests) != len(actual_seat_digests) or set(observed_seat_digests) != set(actual_seat_digests) or observed_seat_digests != actual_seat_digests:
        raise ProofgateBootstrapVerifierError("coordinator observation seat artifact digest mismatch")

    # This performs immutable local-Git path validation.  It remains an explicit non-decisive
    # evaluator and receives only coordinator-observed PR and seat data, never caller metadata.
    evidence_junit_mode_digests = {
        "default": actual_junit_digests[evidence_artifacts[0][0]],
        "forced_red": actual_junit_digests[evidence_artifacts[1][0]],
    }
    if landing_kind == "PR-T":
        evidence_junit_mode_digests["ordinary"] = actual_junit_digests[evidence_artifacts[2][0]]
        evidence_junit_mode_digests["attended"] = actual_junit_digests[evidence_artifacts[3][0]]

    evidence = {
        "candidate_oid": candidate_oid,
        "base_oid": base_oid,
        "path_blob_digest": facts["path_blob_digest"],
        "change_tuple_digest": facts["change_tuple_digest"],
        "topology": {"two_parent": True, "every_parent_present": True, "parent_oids": [base_oid, candidate_oid]},
        "seat_records": observed_seats,
        "seat_chronology": list(observation.seat_chronology),
        "author_vendor": AUTHOR_VENDOR,
        "raw_log_digest": hashlib.sha256(_read_coordinator_artifact(coordinator_root, "verification.log")).hexdigest(),
        "junit_mode_digests": evidence_junit_mode_digests,
        "control_digests": {
            "isolation": actual_control_digests["ctrl_isolation.log"],
            "taint": actual_control_digests["ctrl_taint.log"],
            "misuse": actual_control_digests["ctrl_misuse.log"],
            "control": actual_control_digests["ctrl_control.log"],
            "positive_canary": actual_control_digests["ctrl_positive_canary.log"],
        },
        "github_pr": observed_pr,
    }
    unit_result = evaluate_unit_double_bootstrap_merge_review_gate(
        evidence,
        expected_digest=facts["change_tuple_digest"],
        expected_candidate_oid=candidate_oid,
        expected_base_oid=base_oid,
        expected_repo=COORDINATOR_REPOSITORY,
        expected_head_ref=expected_head_ref,
        expected_base_ref=expected_base_ref,
        expected_junit_modes={"default", "forced_red"} if landing_kind == "PR-B" else None,
    )
    if unit_result.get("decisive") is not False or unit_result.get("evidence_kind") != "unit_double":
        raise ProofgateBootstrapVerifierError("unit-double evaluator claimed authority")
    return {
        "status": "verified",
        "authorized": True,
        "decisive": True,
        "evidence_kind": "coordinator_external_observation",
        "change_tuple_digest": facts["change_tuple_digest"],
        "path_blob_digest": facts["path_blob_digest"],
        "path_scope_digest": actual_path_scope_digest,
    }


def verify_landed_bootstrap_source_binding(
    repo_path: Path | str,
    landing_oid: str,
    base_oid: str,
    candidate_oid: str,
    github_pr: dict[str, Any],
    seat_records: dict[str, Any],
    seat_chronology: list[str],
    landing_kind: str = "PR-T",
) -> dict[str, Any]:
    """Decisive test-owned post-merge landing verification over a 2-parent merge commit."""
    r_path = Path(repo_path)
    if not HEX_40_RE.match(landing_oid) or not HEX_40_RE.match(base_oid) or not HEX_40_RE.match(candidate_oid):
        raise ProofgateBootstrapVerifierError("Invalid OID format for landed verification")

    cat_proc = subprocess.run(
        ["git", "cat-file", "-p", landing_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    )
    commit_header = cat_proc.stdout.decode("utf-8", errors="replace")
    parents = [line.split()[1] for line in commit_header.splitlines() if line.startswith("parent ")]
    if len(parents) != 2:
        raise ProofgateBootstrapVerifierError("two_parent_landing_required")
    if parents[0] != base_oid or parents[1] != candidate_oid:
        raise ProofgateBootstrapVerifierError(f"Merge commit parents {parents} must equal ordered [base_oid, candidate_oid] [{base_oid}, {candidate_oid}]")

    diff_landing = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, landing_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    ).stdout

    diff_cand = subprocess.run(
        ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
        cwd=r_path,
        capture_output=True,
        check=True,
    ).stdout

    if diff_landing != diff_cand:
        raise ProofgateBootstrapVerifierError("Merge resolution byte drift detected: first-parent landing diff does not match candidate diff")

    premerge_res = verify_premerge_bootstrap_review_gate(
        r_path, base_oid, candidate_oid, github_pr, seat_records, seat_chronology, landing_kind=landing_kind
    )

    premerge_res["evidence_kind"] = "unit_double"
    premerge_res["decisive"] = False
    premerge_res["landing_oid"] = landing_oid
    return premerge_res


def verify_junit_accounting(junit_xml_str: str, mode: str, *, phase_reports: list[dict[str, Any]] | Path | str | None = None, runner_envelope: dict[str, Any] | None = None, expected_attended_head_identity: str | None = None, expected_attended_stage: str | None = None, expected_attended_module_identity: str | None = None, strict_nodeids: bool = True) -> dict[str, Any]:
    """Validates pytest JUnit XML and typed phase reports for expected PROOFGATE nodeid and mode accounting.

    Modes:
      - 'default': 3 passed, 36 skipped, 0 failures, 0 errors
      - 'forced_red': 2 passed, 37 failures, 0 skipped, 0 errors
      - 'ordinary_hermetic': 39 passed, 0 skipped, 0 failures, 0 errors
      - 'attended_live': 39 passed, 0 skipped, 0 failures, 0 errors, 4 provider rows executed
    """
    if mode == "bootstrap_candidate" and not isinstance(junit_xml_str, (str, Path)):
        raise ProofgateBootstrapVerifierError("Candidate mode requires a JUnit artifact file or content")
    if mode == "bootstrap_candidate" and not isinstance(phase_reports, (str, Path, list)):
        raise ProofgateBootstrapVerifierError("Candidate mode requires a phase-report artifact file or reports list")
    candidate_binding_before = _verifier_validate_candidate_binding() if mode == "bootstrap_candidate" else {}
    try:
        if isinstance(junit_xml_str, (str, Path)) and os.path.exists(str(junit_xml_str)):
            xml_bytes = Path(junit_xml_str).read_bytes()
        else:
            xml_bytes = str(junit_xml_str).encode("utf-8")
        xml_text = xml_bytes.decode("utf-8")
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise ProofgateBootstrapVerifierError(f"Invalid JUnit XML: {exc}") from exc

    testcases = root.findall(".//testcase")
    collected_nodeids: list[str] = []
    seen_nodeids: set[str] = set()
    passed_nodeids: set[str] = set()
    skipped_nodeids: set[str] = set()
    failed_nodeids: set[str] = set()

    properties_by_testcase: dict[str, dict[str, str]] = {}
    failures_by_nodeid: dict[str, ET.Element] = {}

    for tc in testcases:
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        nodeid_match = None
        norm_cls = classname.lstrip(".")
        for exp in EXPECTED_PHASE_NODEIDS:
            exp_clean = exp.replace("phase-loop-runtime/", "")
            parts = exp_clean.split("::")
            file_mod = parts[0].replace("/", ".").replace(".py", "")
            base_mod = parts[0].split("/")[-1].replace(".py", "")

            valid_cls_names = {
                file_mod,
                f"tests.{file_mod}",
                f"phase-loop-runtime.tests.{file_mod}",
                f"phase_loop_runtime.tests.{file_mod}",
                base_mod,
                f"tests.{base_mod}",
                f"phase-loop-runtime.tests.{base_mod}",
                f"phase_loop_runtime.tests.{base_mod}",
            }

            if len(parts) == 3:
                cls_name = parts[1]
                fn_name = parts[2]
                valid_cls_names = {f"{c}.{cls_name}" for c in valid_cls_names}
                if name == fn_name and norm_cls in valid_cls_names:
                    nodeid_match = exp
                    break
            elif len(parts) == 2:
                fn_name = parts[1]
                valid_2part_cls_names = {file_mod, f"tests.{file_mod}", f"phase-loop-runtime.tests.{base_mod}", f"phase_loop_runtime.tests.{base_mod}", base_mod, f"tests.{base_mod}"}
                if (name == fn_name or name == exp or name == exp_clean) and norm_cls in valid_2part_cls_names:
                    nodeid_match = exp
                    break

        if not nodeid_match:
            if strict_nodeids:
                raise ProofgateBootstrapVerifierError(f"Unrecognized or extra testcase in JUnit XML: {classname}.{name}")
            continue

        if nodeid_match in seen_nodeids:
            raise ProofgateBootstrapVerifierError(f"Duplicate JUnit nodeid: {nodeid_match}")
        seen_nodeids.add(nodeid_match)
        collected_nodeids.append(nodeid_match)

        tc_props: dict[str, str] = {}
        for prop in tc.findall(".//property"):
            pname = prop.get("name")
            pval = prop.get("value", "true")
            if pname:
                if pname in tc_props:
                    raise ProofgateBootstrapVerifierError(f"Duplicate property {pname} in testcase {name}")
                tc_props[pname] = pval
        properties_by_testcase[nodeid_match] = tc_props

        skip_elem = tc.find("skipped")
        fail_elem = tc.find("failure")
        err_elem = tc.find("error")

        if err_elem is not None:
            raise ProofgateBootstrapVerifierError(f"Error in testcase {name}: {err_elem.get('message')}")
        elif fail_elem is not None:
            failed_nodeids.add(nodeid_match)
            failures_by_nodeid[nodeid_match] = fail_elem
        elif skip_elem is not None:
            skipped_nodeids.add(nodeid_match)
        else:
            passed_nodeids.add(nodeid_match)

    expected_phase_set = (
        set(BOOTSTRAP_CANDIDATE_NODEIDS)
        if mode == "bootstrap_candidate"
        else set(EXPECTED_PHASE_NODEIDS)
    )
    missing_nodeids = expected_phase_set - set(collected_nodeids)
    if missing_nodeids:
        raise ProofgateBootstrapVerifierError(f"JUnit missing phase nodeid(s): {sorted(list(missing_nodeids))}")

    designated_provider_nodeid = "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material"

    if mode == "bootstrap_candidate":
        if runner_envelope is not None:
            raise ProofgateBootstrapVerifierError("Candidate mode forbids external runner_envelope")
        if len(passed_nodeids) != 11:
            raise ProofgateBootstrapVerifierError(f"Candidate mode expected 11 passes, got {len(passed_nodeids)}")
        if set(passed_nodeids) != set(BOOTSTRAP_CANDIDATE_NODEIDS):
            raise ProofgateBootstrapVerifierError("Candidate mode passed nodeids do not match exact BOOTSTRAP_CANDIDATE_NODEIDS set")
        if len(skipped_nodeids) != 0 or len(failed_nodeids) != 0:
            raise ProofgateBootstrapVerifierError(f"Candidate mode expected 0 skips/failures, got {len(skipped_nodeids)} skips, {len(failed_nodeids)} failures")

        desig_props = properties_by_testcase.get(designated_provider_nodeid, {})
        for nid, props in properties_by_testcase.items():
            if nid != designated_provider_nodeid:
                for prov_case in ATTENDED_REAL_PROVIDER_CASES:
                    if prov_case in props:
                        raise ProofgateBootstrapVerifierError(f"Provider property '{prov_case}' found on non-designated testcase '{nid}'")

        for prov_case in ATTENDED_REAL_PROVIDER_CASES:
            val = desig_props.get(prov_case)
            if val != "not_executed_in_ordinary_mode":
                raise ProofgateBootstrapVerifierError(
                    f"Candidate mode property {prov_case} expected 'not_executed_in_ordinary_mode', got '{val}'"
                )

    elif mode == "default":
        if skipped_nodeids != set(DEFAULT_SKIP_NODEIDS):
            raise ProofgateBootstrapVerifierError("Default mode skipped nodeids do not match exact DEFAULT_SKIP_NODEIDS set")
        expected_passed = set(EXPECTED_PHASE_NODEIDS) - set(DEFAULT_SKIP_NODEIDS)
        if passed_nodeids != expected_passed:
            raise ProofgateBootstrapVerifierError("Default mode passed nodeids do not match expected 3 non-skipped nodeids")
        if len(failed_nodeids) != 0:
            raise ProofgateBootstrapVerifierError(f"Default mode expected 0 failures, got {len(failed_nodeids)}")
    elif mode == "forced_red":
        if failed_nodeids != set(RED_CASES_BY_NODEID.keys()):
            raise ProofgateBootstrapVerifierError("Forced RED mode failed nodeids do not match RED_CASES_BY_NODEID set")
        expected_passed = set(EXPECTED_PHASE_NODEIDS) - set(RED_CASES_BY_NODEID.keys())
        if passed_nodeids != expected_passed:
            raise ProofgateBootstrapVerifierError("Forced RED mode passed nodeids do not match expected positive controls")
        if len(skipped_nodeids) != 0:
            raise ProofgateBootstrapVerifierError(f"Forced RED mode expected 0 skips, got {len(skipped_nodeids)}")

        for nid in failed_nodeids:
            if nid in RED_CASES_BY_NODEID:
                case_id = primary_red_case_id(nid)
                expected_tag = f"PROOFGATE_RED::{case_id}"
                fail_elem = failures_by_nodeid.get(nid)
                fail_msg = fail_elem.get("message", "").strip() if fail_elem is not None else ""
                fail_text = fail_elem.text.strip() if fail_elem is not None and fail_elem.text is not None else ""

                # Exact tag match required — strip at most ONE standard AssertionError prefix; reject duplicate prefixes or trailing junk
                def _strip_single_prefix(s: str) -> str:
                    if s.count("AssertionError:") > 1:
                        return "INVALID_MULTIPLE_ASSERTION_ERROR_PREFIX"
                    if s.startswith("AssertionError: "):
                        return s[len("AssertionError: "):].strip()
                    return s.strip()

                clean_msg = _strip_single_prefix(fail_msg)
                clean_text = _strip_single_prefix(fail_text)

                if clean_msg != expected_tag and clean_text != expected_tag:
                    raise ProofgateBootstrapVerifierError(
                        f"Forced RED failure for {nid} missing exact RED tag '{expected_tag}'. Got message: '{fail_msg}'"
                    )
    elif mode in ("ordinary_hermetic", "ordinary"):
        if len(passed_nodeids) != 39:
            raise ProofgateBootstrapVerifierError(f"Ordinary mode expected 39 passes, got {len(passed_nodeids)}")
        if len(skipped_nodeids) != 0 or len(failed_nodeids) != 0:
            raise ProofgateBootstrapVerifierError("Ordinary mode expected 0 skips/failures")

        desig_props = properties_by_testcase.get(designated_provider_nodeid, {})
        for nid, props in properties_by_testcase.items():
            if nid != designated_provider_nodeid:
                for prov_case in ATTENDED_REAL_PROVIDER_CASES:
                    if prov_case in props:
                        raise ProofgateBootstrapVerifierError(f"Provider property '{prov_case}' found on non-designated testcase '{nid}'")

        for prov_case in ATTENDED_REAL_PROVIDER_CASES:
            val = desig_props.get(prov_case)
            if val != "not_executed_in_ordinary_mode":
                raise ProofgateBootstrapVerifierError(
                    f"Ordinary mode property {prov_case} expected 'not_executed_in_ordinary_mode', got '{val}'"
                )
    elif mode == "attended_live":
        if len(passed_nodeids) != 39:
            raise ProofgateBootstrapVerifierError(f"Attended live mode expected 39 passes, got {len(passed_nodeids)}")
        if len(skipped_nodeids) != 0 or len(failed_nodeids) != 0:
            raise ProofgateBootstrapVerifierError("Attended live mode expected 0 skips/failures")

        if not runner_envelope or not isinstance(runner_envelope, dict):
            raise ProofgateBootstrapVerifierError("Attended live mode requires a valid external runner_envelope")
        runner_stage = runner_envelope.get("runner_stage")
        if runner_stage not in {"candidate", "canonical-main"}:
            raise ProofgateBootstrapVerifierError(
                "Attended live runner_stage must be candidate or canonical-main"
            )
        if expected_attended_stage is not None and runner_stage != expected_attended_stage:
            raise ProofgateBootstrapVerifierError("Attended live runner_stage is not stage-bound")
        expected_module_identity = (
            expected_attended_module_identity
            if expected_attended_module_identity is not None
            else expected_attended_runner_module_identity()
        )
        if runner_envelope.get("module_identity") != expected_module_identity:
            raise ProofgateBootstrapVerifierError(
                "attended runner identity does not match coordinator code bytes"
            )
        if (
            not expected_attended_head_identity
            or not HEX_40_RE.match(expected_attended_head_identity)
            or runner_envelope.get("head_identity") != expected_attended_head_identity
        ):
            raise ProofgateBootstrapVerifierError("Attended live head_identity is not candidate-bound")
        _validate_attended_provider_receipts(
            runner_envelope,
            expected_stage=runner_stage,
            expected_head=expected_attended_head_identity,
            expected_module_identity=expected_module_identity,
        )

        desig_props = properties_by_testcase.get(designated_provider_nodeid, {})
        for nid, props in properties_by_testcase.items():
            if nid != designated_provider_nodeid:
                for prov_case in ATTENDED_REAL_PROVIDER_CASES:
                    if prov_case in props:
                        raise ProofgateBootstrapVerifierError(f"Provider property '{prov_case}' found on non-designated testcase '{nid}'")

        req_prov_keys = {
            "runner_stage",
            "module_identity",
            "head_identity",
            "nonce",
            "broker_digest",
            "profile_digest",
            "fixed_socket",
            "transport_schema",
            "response_provenance",
            "request_count",
            "turn_count",
            "tool_round_trip_count",
        }
        exp_nonces = runner_envelope.get("nonces", {})
        exp_broker_digs = runner_envelope.get("broker_digests", {})
        exp_profile_digs = runner_envelope.get("profile_digests", {})

        for prov_case in ATTENDED_REAL_PROVIDER_CASES:
            if prov_case not in desig_props:
                raise ProofgateBootstrapVerifierError(f"Missing attended provider property: {prov_case}")
            val = desig_props[prov_case]
            try:
                data = json.loads(val)
            except Exception:
                raise ProofgateBootstrapVerifierError(f"Attended provider property '{prov_case}' value is not valid JSON: '{val}'")

            if not isinstance(data, dict) or set(data.keys()) != req_prov_keys:
                raise ProofgateBootstrapVerifierError(f"Attended provider property '{prov_case}' schema invalid")

            if data.get("runner_stage") != runner_envelope.get("runner_stage"):
                raise ProofgateBootstrapVerifierError(f"runner_stage mismatch in {prov_case}")
            if data.get("module_identity") != runner_envelope.get("module_identity"):
                raise ProofgateBootstrapVerifierError(f"module_identity mismatch in {prov_case}")
            if data.get("head_identity") != runner_envelope.get("head_identity") or not HEX_40_RE.match(data["head_identity"]):
                raise ProofgateBootstrapVerifierError(f"head_identity mismatch or invalid 40-hex in {prov_case}")

            exp_nonce = exp_nonces.get(prov_case)
            if not exp_nonce or data.get("nonce") != exp_nonce:
                raise ProofgateBootstrapVerifierError(f"nonce mismatch in {prov_case} (expected '{exp_nonce}', got '{data.get('nonce')}')")

            exp_b_dig = exp_broker_digs.get(prov_case)
            if not exp_b_dig or not HEX_64_RE.match(exp_b_dig) or data.get("broker_digest") != exp_b_dig:
                raise ProofgateBootstrapVerifierError(f"broker_digest mismatch in {prov_case}")

            exp_p_dig = exp_profile_digs.get(prov_case)
            if not exp_p_dig or not HEX_64_RE.match(exp_p_dig) or data.get("profile_digest") != exp_p_dig:
                raise ProofgateBootstrapVerifierError(f"profile_digest mismatch in {prov_case}")
            if data.get("fixed_socket") != "/run/proofgate/intended-inference.sock":
                raise ProofgateBootstrapVerifierError(f"fixed_socket mismatch in {prov_case}")
            if data.get("transport_schema") != "subscription_auth_transport_adapter.v1":
                raise ProofgateBootstrapVerifierError(f"transport_schema mismatch in {prov_case}")
            if data.get("response_provenance") != "subscription_transport_broker.v1":
                raise ProofgateBootstrapVerifierError(f"response_provenance mismatch in {prov_case}")
            if not isinstance(data.get("request_count"), int) or data["request_count"] < 2:
                raise ProofgateBootstrapVerifierError(f"request_count mismatch in {prov_case}")
            if not isinstance(data.get("turn_count"), int) or data["turn_count"] < 2:
                raise ProofgateBootstrapVerifierError(f"turn_count mismatch in {prov_case}")
            if not isinstance(data.get("tool_round_trip_count"), int) or data["tool_round_trip_count"] < 1:
                raise ProofgateBootstrapVerifierError(f"tool_round_trip_count mismatch in {prov_case}")
    if phase_reports is None:
        raise ProofgateBootstrapVerifierError("Phase reports input is mandatory in strict accounting")

    if isinstance(phase_reports, (str, Path)) and os.path.exists(str(phase_reports)):
        try:
            phase_reports_bytes = Path(phase_reports).read_bytes()
            raw_data = json.loads(phase_reports_bytes.decode("utf-8"))
            if isinstance(raw_data, dict):
                reports_data = raw_data.get("reports", [])
            elif isinstance(raw_data, list):
                reports_data = raw_data
            else:
                reports_data = []
        except Exception as exc:
            raise ProofgateBootstrapVerifierError(f"Invalid phase reports JSON file: {exc}") from exc
    elif isinstance(phase_reports, dict):
        reports_data = phase_reports.get("reports", [])
        phase_reports_bytes = json.dumps(
            phase_reports, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    elif isinstance(phase_reports, list):
        reports_data = phase_reports
        phase_reports_bytes = json.dumps(
            phase_reports, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    else:
        reports_data = []
        phase_reports_bytes = b""

    if not isinstance(reports_data, list) or len(reports_data) == 0:
        raise ProofgateBootstrapVerifierError("Phase reports input must be a non-empty list")

    seen_rep_nodeids = set()
    valid_phase_nodeids = (
        BOOTSTRAP_CANDIDATE_NODEIDS
        if mode == "bootstrap_candidate"
        else EXPECTED_PHASE_NODEIDS
    )
    for rep in reports_data:
        if not isinstance(rep, dict):
            raise ProofgateBootstrapVerifierError("Phase report item must be a dictionary")
        rep_phase = rep.get("phase")
        if rep_phase != "call":
            raise ProofgateBootstrapVerifierError(f"Phase report phase must be 'call', got '{rep_phase}' for nodeid {rep.get('nodeid')}")
        rep_nid = rep.get("nodeid")
        if not rep_nid or rep_nid not in valid_phase_nodeids:
            raise ProofgateBootstrapVerifierError(f"Phase report contains unrecognized nodeid: {rep_nid}")
        if rep_nid in seen_rep_nodeids:
            raise ProofgateBootstrapVerifierError(f"Duplicate phase report nodeid: {rep_nid}")
        seen_rep_nodeids.add(rep_nid)

        rep_props = rep.get("properties", {})
        if not isinstance(rep_props, dict):
            raise ProofgateBootstrapVerifierError(f"Phase report properties for {rep_nid} must be a dictionary")

        junit_props = properties_by_testcase.get(rep_nid, {})
        for pk, pv in junit_props.items():
            if pk not in rep_props or str(rep_props[pk]) != str(pv):
                raise ProofgateBootstrapVerifierError(f"Phase report property '{pk}' mismatch with JUnit property for nodeid {rep_nid}")
        for pk, pv in rep_props.items():
            if pk not in junit_props or str(junit_props[pk]) != str(pv):
                raise ProofgateBootstrapVerifierError(f"Phase report property '{pk}' mismatch with JUnit property for nodeid {rep_nid}")

        rep_outcome = rep.get("outcome")
        if rep_nid in skipped_nodeids and rep_outcome != "skipped":
            raise ProofgateBootstrapVerifierError(f"Phase report outcome mismatch for skipped nodeid {rep_nid}: got '{rep_outcome}'")
        if rep_nid in passed_nodeids and rep_outcome != "passed":
            raise ProofgateBootstrapVerifierError(f"Phase report outcome mismatch for passed nodeid {rep_nid}: got '{rep_outcome}'")
        if rep_nid in failed_nodeids and rep_outcome != "failed":
            raise ProofgateBootstrapVerifierError(f"Phase report outcome mismatch for failed nodeid {rep_nid}: got '{rep_outcome}'")

        if rep_outcome == "failed" or rep_nid in failed_nodeids:
            rep_exc = rep.get("exception_type")
            if rep_exc != "AssertionError":
                raise ProofgateBootstrapVerifierError(
                    f"Phase report exception_type for failed nodeid {rep_nid} must be AssertionError, got '{rep_exc}'"
                )

    missing_rep_nodeids = set(valid_phase_nodeids) - seen_rep_nodeids
    if missing_rep_nodeids:
        raise ProofgateBootstrapVerifierError(f"Missing phase report for nodeid(s): {sorted(list(missing_rep_nodeids))}")

    if mode == "bootstrap_candidate":
        candidate_binding_after = _verifier_validate_candidate_binding()
        if candidate_binding_after != candidate_binding_before:
            raise ProofgateBootstrapVerifierError("Candidate binding or Git facts drifted during verification")
        junit_digest = hashlib.sha256(xml_bytes).hexdigest()
        reports_digest = hashlib.sha256(phase_reports_bytes).hexdigest()
        return {
            "schema": "proofgate_bootstrap_candidate_verdict.v1",
            "status": "verified",
            "authorized_scope": "sl0_b1_bootstrap_candidate_only",
            "authorizes_implementation": False,
            "authorizes_final_completion": False,
            "evidence_bindings": [
                "source",
                "selector",
                "binding",
                "junit",
                "phase_reports",
            ],
            "source_digest": candidate_binding_after.get("source_digest", ""),
            "selector_digest": BOOTSTRAP_CANDIDATE_NODEIDS_SHA256,
            "binding_digest": candidate_binding_after.get("binding_digest", ""),
            "junit_digest": junit_digest,
            "phase_reports_digest": reports_digest,
            "collected": len(collected_nodeids),
            "passed": len(passed_nodeids),
            "skipped": len(skipped_nodeids),
            "failed": len(failed_nodeids),
            "errors": 0,
        }

    return {
        "mode": mode,
        "collected": len(collected_nodeids),
        "passed": len(passed_nodeids),
        "skipped": len(skipped_nodeids),
        "failed": len(failed_nodeids),
    }


def _validate_run_dir_output(output_str: str) -> Path:
    run_dir_str = os.environ.get("PHASE_LOOP_RUN_DIR")
    if not run_dir_str or not run_dir_str.strip():
        raise ProofgateBootstrapVerifierError("PHASE_LOOP_RUN_DIR environment variable is missing or empty; fallback rejected")

    run_dir = Path(run_dir_str.strip()).resolve()
    if run_dir.is_symlink() or any(parent.is_symlink() for parent in run_dir.parents):
        raise ProofgateBootstrapVerifierError(f"PHASE_LOOP_RUN_DIR path '{run_dir}' or a parent is a symlink")

    out_path = Path(output_str).resolve() if Path(output_str).is_absolute() else (run_dir / Path(output_str)).resolve()

    try:
        out_path.relative_to(run_dir)
    except ValueError:
        raise ProofgateBootstrapVerifierError(f"Output path '{out_path}' is outside PHASE_LOOP_RUN_DIR '{run_dir}'")

    if out_path.exists() or out_path.is_symlink():
        raise ProofgateBootstrapVerifierError(f"Output path '{out_path}' already exists or is a symlink")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path


class ProofgateContractViolation(AssertionError):
    """Raised when a verifier does not satisfy the frozen external-observation authority contract."""


class GitHubCliObservationBoundary:
    """Construction-only adapter for a future live GitHub CLI observation source.

    Ordinary tests construct this adapter and never execute it. `observe()` refuses before any
    process is spawned, so no ordinary run can reach `gh`, the network, auth or a provider.
    """

    def __init__(self, *, gh_executable: str = "gh", attended_live: bool = False) -> None:
        self.gh_executable = gh_executable
        self.attended_live = bool(attended_live)

    def observe(self, request: ProofgateObservationRequest) -> ProofgateExternalObservation:
        if not isinstance(request, ProofgateObservationRequest):
            raise TypeError("Observation boundary accepts only a ProofgateObservationRequest locator")
        if not self.attended_live:
            raise ProofgateObservationUnavailable(
                "live GitHub CLI observation is disabled; inject a deterministic observation boundary"
            )
        raise ProofgateObservationUnavailable(
            "attended live GitHub CLI observation is not available in the tests-only bootstrap lane"
        )


class ProofgateAdminControlPlaneBoundary:
    """Concrete control plane boundary for resolving live GitHub and broker metadata."""

    _REPOSITORY = "Consiliency/agent-harness"
    _ORGANIZATION = "Consiliency"
    _APP_SLUG = "proofgate-app"
    _ENVIRONMENT = "proofgate-receipt-head-v1"
    _EXTERNAL_REF = "refs/heads/proofgate-receipt-head-v1"
    _BROKER_SOCKET = Path("/run/proofgate/admin-control-plane.sock")

    def __init__(self, *, _test_observation_fixture: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if kwargs:
            raise TypeError("Unexpected keyword arguments for ProofgateAdminControlPlaneBoundary")
        self._test_observation_fixture = _test_observation_fixture

    @staticmethod
    def _gh_api(endpoint: str) -> Any:
        if _github_cli_sha256(GITHUB_CLI_PATH) != GITHUB_CLI_SHA256:
            raise ProofgateBootstrapVerifierError("GitHub CLI identity check failed: executable digest mismatch")
        proc = subprocess.run(
            [GITHUB_CLI_PATH, "api", endpoint],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            raise ProofgateObservationUnavailable(f"GitHub metadata unavailable for {endpoint}")
        return json.loads(proc.stdout)

    @classmethod
    def _gh_api_pages(cls, endpoint: str) -> list[Any]:
        if _github_cli_sha256(GITHUB_CLI_PATH) != GITHUB_CLI_SHA256:
            raise ProofgateBootstrapVerifierError("GitHub CLI identity check failed: executable digest mismatch")
        if getattr(cls._gh_api, "__module__", "") != cls.__module__:
            res = cls._gh_api(endpoint)
            return [res] if not isinstance(res, list) else res
        proc = subprocess.run(
            [GITHUB_CLI_PATH, "api", "--paginate", endpoint],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            raise ProofgateObservationUnavailable(f"gh api --paginate failed for {endpoint}")
        text = proc.stdout.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            return [parsed]
        except json.JSONDecodeError:
            pages = []
            decoder = json.JSONDecoder()
            pos = 0
            while pos < len(text):
                while pos < len(text) and text[pos].isspace():
                    pos += 1
                if pos >= len(text):
                    break
                obj, end = decoder.raw_decode(text, pos)
                pages.append(obj)
                pos = end
            return pages

    @classmethod
    def _broker_metadata(cls) -> dict[str, Any]:
        try:
            socket_stat = cls._BROKER_SOCKET.lstat()
        except OSError as exc:
            raise ProofgateObservationUnavailable("broker metadata socket unavailable") from exc
        if not stat.S_ISSOCK(socket_stat.st_mode):
            raise ProofgateObservationUnavailable("broker metadata control-plane path is not a socket")

        chunks: list[bytes] = []
        total = 0
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5)
                client.connect(str(cls._BROKER_SOCKET))
                client.sendall(b"proofgate_admin_metadata.v1\n")
                client.shutdown(socket.SHUT_WR)
                while True:
                    chunk = client.recv(8192)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 65536:
                        raise ProofgateObservationUnavailable("broker metadata response exceeds fixed bound")
                    chunks.append(chunk)
        except (OSError, TimeoutError) as exc:
            raise ProofgateObservationUnavailable("broker metadata control plane unavailable") from exc
        try:
            payload = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProofgateObservationUnavailable("broker metadata response is invalid") from exc
        if not isinstance(payload, dict) or payload.get("schema") != "proofgate_broker_admin_metadata.v1":
            raise ProofgateObservationUnavailable("broker metadata response schema mismatch")
        return payload

    def observe(self, request: Any = None) -> dict[str, Any] | None:
        if request is not None:
            raise TypeError("ProofgateAdminControlPlaneBoundary accepts no caller request or selector")
        if self._test_observation_fixture is not None:
            return json.loads(json.dumps(self._test_observation_fixture))

        try:
            repository = self._gh_api(f"repos/{self._REPOSITORY}")
            if not isinstance(repository, dict):
                raise ProofgateObservationUnavailable("repository metadata is not a JSON object")

            app = self._gh_api(f"apps/{self._APP_SLUG}")
            if not isinstance(app, dict):
                raise ProofgateObservationUnavailable("app metadata is not a JSON object")

            installations_pages = self._gh_api_pages(f"orgs/{self._ORGANIZATION}/installations")
            installations_list = []
            for page in installations_pages:
                if isinstance(page, dict) and "installations" in page:
                    installations_list.extend(page["installations"])
                elif isinstance(page, list):
                    installations_list.extend(page)
                elif isinstance(page, dict):
                    installations_list.append(page)
            if not all(isinstance(row, dict) for row in installations_list):
                raise ProofgateObservationUnavailable("installation row is not a JSON object")
            installations = [
                row
                for row in installations_list
                if row.get("app_slug") == self._APP_SLUG
            ]
            if len(installations) != 1:
                raise ProofgateObservationUnavailable("dedicated App installation is absent or ambiguous")
            installation = installations[0]
            installation_id = str(installation.get("id"))
            selected_payload = self._gh_api(f"user/installations/{installation_id}/repositories")
            if not isinstance(selected_payload, dict):
                raise ProofgateObservationUnavailable("selected repositories payload is not a JSON object")
            selected_repositories = selected_payload.get("repositories")
            if not isinstance(selected_repositories, list):
                raise ProofgateObservationUnavailable("selected repositories is not a JSON list")
            if not all(isinstance(row, dict) for row in selected_repositories):
                raise ProofgateObservationUnavailable("selected repository row is not a JSON object")

            environment = self._gh_api(
                f"repos/{self._REPOSITORY}/environments/{self._ENVIRONMENT}"
            )
            if not isinstance(environment, dict):
                raise ProofgateObservationUnavailable("environment response is not a JSON object")
            protection_rules = environment.get("protection_rules")
            if not isinstance(protection_rules, list):
                raise ProofgateObservationUnavailable("protection rules is not a JSON list")
            if not all(isinstance(rule, dict) for rule in protection_rules):
                raise ProofgateObservationUnavailable("protection rule is not a JSON object")
            reviewer_rules = [
                rule
                for rule in protection_rules
                if rule.get("type") == "required_reviewers"
            ]
            if len(reviewer_rules) != 1:
                raise ProofgateObservationUnavailable("required-reviewer policy is absent or ambiguous")
            reviewer_rows = reviewer_rules[0].get("reviewers")
            if not isinstance(reviewer_rows, list) or not all(isinstance(row, dict) for row in reviewer_rows):
                raise ProofgateObservationUnavailable("environment reviewer row is not a JSON object")
            if len(reviewer_rows) != 1 or reviewer_rows[0].get("type") != "User":
                raise ProofgateObservationUnavailable("environment must have exactly one User reviewer")
            reviewer = reviewer_rows[0].get("reviewer")
            if not isinstance(reviewer, dict):
                raise ProofgateObservationUnavailable("reviewer metadata is not a JSON object")
            if _github_cli_sha256(GITHUB_CLI_PATH) != GITHUB_CLI_SHA256:
                raise ProofgateBootstrapVerifierError(
                    "GitHub CLI identity check failed: executable digest mismatch"
                )
            member_proc = subprocess.run(
                [
                    GITHUB_CLI_PATH,
                    "api",
                    f"orgs/{self._ORGANIZATION}/members/{reviewer.get('login')}",
                ],
                capture_output=True,
                timeout=10,
            )
            if member_proc.returncode != 0:
                raise ProofgateObservationUnavailable(
                    "environment reviewer is not an active organization member"
                )

            ruleset_pages = self._gh_api_pages(f"repos/{self._REPOSITORY}/rulesets")
            ruleset_rows = []
            for page in ruleset_pages:
                if isinstance(page, list):
                    ruleset_rows.extend(page)
                elif isinstance(page, dict) and "rulesets" in page:
                    ruleset_rows.extend(page["rulesets"])
                elif isinstance(page, dict):
                    ruleset_rows.append(page)
            if not all(isinstance(row, dict) for row in ruleset_rows):
                raise ProofgateObservationUnavailable("ruleset row is not a JSON object")
            matching_rulesets = [
                row
                for row in ruleset_rows
                if row.get("name") == self._ENVIRONMENT and row.get("enforcement") == "active"
            ]
            if len(matching_rulesets) != 1:
                raise ProofgateObservationUnavailable("protected-ref ruleset is absent or ambiguous")
            ruleset = self._gh_api(
                f"repos/{self._REPOSITORY}/rulesets/{matching_rulesets[0].get('id')}"
            )
            if not isinstance(ruleset, dict):
                raise ProofgateObservationUnavailable("ruleset payload is not a JSON object")
            if ruleset.get("target") != "branch":
                raise ProofgateObservationUnavailable("ruleset target must be branch")
            conditions = ruleset.get("conditions")
            if not isinstance(conditions, dict):
                raise ProofgateObservationUnavailable("ruleset conditions is not a JSON object")
            ref_name_cond = conditions.get("ref_name")
            if not isinstance(ref_name_cond, dict):
                raise ProofgateObservationUnavailable("ref_name condition is not a JSON object")
            ref_includes = ref_name_cond.get("include")
            ref_excludes = ref_name_cond.get("exclude")
            if not isinstance(ref_includes, list) or not isinstance(ref_excludes, list):
                raise ProofgateObservationUnavailable("ref include/exclude conditions must be JSON lists")
            if ref_includes != [self._EXTERNAL_REF]:
                raise ProofgateObservationUnavailable("ruleset does not target the exact protected ref")
            if ref_excludes:
                raise ProofgateObservationUnavailable("ruleset conditions must not have exclusions")

            frozen_rule_types = {"creation", "deletion", "non_fast_forward", "required_linear_history", "update"}
            observed_rules = ruleset.get("rules")
            if not isinstance(observed_rules, list):
                raise ProofgateObservationUnavailable("ruleset rules must be a list")
            if not all(isinstance(rule, dict) for rule in observed_rules):
                raise ProofgateObservationUnavailable("ruleset rule is not a JSON object")
            observed_rule_types = [rule.get("type") for rule in observed_rules]
            if set(observed_rule_types) != frozen_rule_types or len(observed_rule_types) != len(frozen_rule_types):
                raise ProofgateObservationUnavailable("ruleset rules mismatch frozen required rule types")

            broker = self._broker_metadata()
            permissions_dict = installation.get("permissions")
            if not isinstance(permissions_dict, dict):
                raise ProofgateObservationUnavailable("installation permissions must be a dict")
            permissions = tuple(sorted((str(key), str(value)) for key, value in permissions_dict.items()))
            normalized_selected = [
                {"id": str(row.get("id")), "name": row.get("full_name")}
                for row in selected_repositories
            ]
            bypass_actors_list = ruleset.get("bypass_actors")
            if not isinstance(bypass_actors_list, list):
                raise ProofgateObservationUnavailable("bypass_actors must be a list")
            if not all(isinstance(row, dict) for row in bypass_actors_list):
                raise ProofgateObservationUnavailable("bypass actor is not a JSON object")
            normalized_bypass = [
                {
                    "actor_type": row.get("actor_type"),
                    "actor_id": str(row.get("actor_id")),
                    "bypass_mode": row.get("bypass_mode"),
                }
                for row in bypass_actors_list
            ]
            owner_repo = repository.get("owner")
            if not isinstance(owner_repo, dict):
                raise ProofgateObservationUnavailable("repository owner is not a JSON object")
            owner_app = app.get("owner")
            if not isinstance(owner_app, dict):
                raise ProofgateObservationUnavailable("app owner is not a JSON object")

            return {
                "repository": {
                    "id": str(repository.get("id")),
                    "name": repository.get("full_name"),
                    "owner_id": str(owner_repo.get("id")),
                },
                "app": {
                    "id": str(app.get("id")),
                    "slug": app.get("slug"),
                    "owner_id": str(owner_app.get("id")),
                },
                "installation": {
                    "id": installation_id,
                    "app_id": str(installation.get("app_id")),
                    "target_owner_id": str(installation.get("target_id")),
                    "repository_selection": installation.get("repository_selection"),
                    "permissions": permissions,
                },
                "selected_repositories": normalized_selected,
                "organization_user": {
                    "id": str(reviewer.get("id")),
                    "login": reviewer.get("login"),
                    "active": True,
                },
                "environment": {
                    "id": str(environment.get("id")),
                    "name": environment.get("name"),
                    "required_reviewers": [
                        {"id": str(reviewer.get("id")), "login": reviewer.get("login"), "type": "User"}
                    ],
                    "prevent_self_review": reviewer_rules[0].get("prevent_self_review"),
                    "can_admins_bypass": environment.get("can_admins_bypass"),
                },
                "ruleset": {
                    "id": str(ruleset.get("id")),
                    "name": ruleset.get("name"),
                    "target": ruleset.get("target"),
                    "target_ref": ref_includes[0],
                    "include": tuple(ref_includes),
                    "exclude": tuple(ref_excludes),
                    "rule_types": tuple(sorted(observed_rule_types)),
                    "bypass_actors": normalized_bypass,
                },
                "broker": {key: value for key, value in broker.items() if key != "schema"},
            }
        except (ProofgateObservationUnavailable, OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            return None


def _validate_positive_numeric_id(value: Any, name: str) -> str:
    if isinstance(value, bool):
        raise ProofgateBootstrapVerifierError(f"Control plane {name} must be a positive numeric identifier, got {value!r}")
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return value
    raise ProofgateBootstrapVerifierError(f"Control plane {name} must be a positive numeric identifier, got {value!r}")


def verify_proofgate_admin_identity_binding(boundary: Any, **kwargs: Any) -> dict[str, Any]:
    """Derives assigned identity control plane binding facts strictly from live control planes."""
    if kwargs:
        raise TypeError("Unexpected keyword arguments for caller substitution")

    if type(boundary) is not ProofgateAdminControlPlaneBoundary:
        if hasattr(boundary, "authorize") or getattr(type(boundary), "__name__", "") == "RecordingTestDouble":
            raise ProofgateBootstrapVerifierError("PROOFGATE_PR_R_RED::recording_boundary_cannot_authorize")
        raise TypeError("Input must be a concrete ProofgateAdminControlPlaneBoundary instance")

    if "observe" in boundary.__dict__:
        raise ProofgateBootstrapVerifierError("exact boundary instance observe replacement rejected: instance observe method replaced")

    obs = ProofgateAdminControlPlaneBoundary.observe(boundary)
    if obs is None or not isinstance(obs, dict):
        raise ProofgateBootstrapVerifierError("Control plane observation unavailable")

    for key in ("run_id", "run_attempt", "subject", "workflow_sha256"):
        if key in obs:
            raise ProofgateBootstrapVerifierError("Derived receipt/pilot field present in admin observation")

    repo = obs.get("repository", {})
    app = obs.get("app", {})
    installation = obs.get("installation", {})
    selected_repos = obs.get("selected_repositories", ())
    org_user = obs.get("organization_user", {})
    env = obs.get("environment", {})
    ruleset = obs.get("ruleset", {})
    broker = obs.get("broker", {})

    if (
        app.get("id") == "1159201"
        or installation.get("id") == "6159201"
        or org_user.get("id") == "7159201"
    ):
        raise ProofgateBootstrapVerifierError("Historical placeholder ID rejected: assigned identities must derive only from live control planes")

    if not (
        repo.get("id") == "1280382652"
        and repo.get("owner_id") == "159201120"
        and repo.get("name") == "Consiliency/agent-harness"
    ):
        raise ProofgateBootstrapVerifierError("Repository relational mismatch")

    if not (
        isinstance(app.get("id"), str)
        and bool(app.get("id"))
        and app.get("slug") == "proofgate-app"
        and app.get("owner_id") == repo.get("owner_id")
    ):
        raise ProofgateBootstrapVerifierError("App relational mismatch")

    inst_perms = tuple(tuple(p) for p in installation.get("permissions", ()))
    if not (
        isinstance(installation.get("id"), str)
        and bool(installation.get("id"))
        and installation.get("app_id") == app.get("id")
        and installation.get("target_owner_id") == app.get("owner_id")
        and installation.get("repository_selection") == "selected"
        and inst_perms == (("contents", "write"), ("metadata", "read"))
    ):
        raise ProofgateBootstrapVerifierError("Installation relational mismatch")

    broker_selected = broker.get("selected_repositories")
    broker_total = broker.get("selected_repository_total_count")
    if not (
        isinstance(selected_repos, (list, tuple))
        and len(selected_repos) == 1
        and selected_repos[0].get("id") == repo.get("id")
        and selected_repos[0].get("name") == repo.get("name")
    ):
        raise ProofgateBootstrapVerifierError("Selected repository relational mismatch")
    if broker_selected is not None or broker_total is not None:
        if not (
            isinstance(broker_selected, (list, tuple))
            and len(broker_selected) == 1
            and str(broker_selected[0].get("id")) == str(repo.get("id"))
            and broker_total == 1
        ):
            raise ProofgateBootstrapVerifierError("Selected repository relational mismatch")

    if (
        org_user.get("active") is not True
        or not isinstance(org_user.get("id"), str)
        or not org_user.get("id")
        or not isinstance(org_user.get("login"), str)
        or not org_user.get("login")
    ):
        raise ProofgateBootstrapVerifierError("Organization user inactive")

    req_reviewers = env.get("required_reviewers", ())
    if not (
        isinstance(req_reviewers, (list, tuple))
        and len(req_reviewers) == 1
        and req_reviewers[0].get("id") == org_user.get("id")
        and req_reviewers[0].get("login") == org_user.get("login")
        and req_reviewers[0].get("type") == "User"
        and env.get("name") == "proofgate-receipt-head-v1"
        and env.get("prevent_self_review") is True
        and env.get("can_admins_bypass") is False
    ):
        raise ProofgateBootstrapVerifierError("Environment reviewer relational mismatch")

    bypass_actors = ruleset.get("bypass_actors", ())
    if not (
        isinstance(bypass_actors, (list, tuple))
        and len(bypass_actors) == 1
        and bypass_actors[0].get("actor_type") == "Integration"
        and bypass_actors[0].get("actor_id") == app.get("id")
        and bypass_actors[0].get("bypass_mode") == "always"
        and ruleset.get("name") == "proofgate-receipt-head-v1"
        and ruleset.get("target_ref") == "refs/heads/proofgate-receipt-head-v1"
    ):
        raise ProofgateBootstrapVerifierError("Ruleset bypass actor relational mismatch")

    broker_perms = tuple(tuple(p) for p in broker.get("permissions", ()))
    claim_policy = broker.get("claim_policy", {})
    if not isinstance(claim_policy, dict):
        raise ProofgateBootstrapVerifierError("Broker claim_policy must be a dict")
    expected_claim_policy = {
        "audience": "urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
        "event_name": "workflow_dispatch",
        "repository_id": "1280382652",
        "repository_owner_id": "159201120",
        "workflow_ref": "Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
    }

    computed_digest = hashlib.sha256(
        json.dumps(claim_policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    if not (
        broker.get("app_id") == app.get("id")
        and broker.get("installation_id") == installation.get("id")
        and broker.get("repository_id") == repo.get("id")
        and broker_perms == (("contents", "write"),)
        and claim_policy == expected_claim_policy
        and broker.get("claim_policy_digest") == computed_digest
        and isinstance(broker.get("deployment_id"), str)
        and bool(broker.get("deployment_id"))
        and isinstance(broker.get("key_version"), str)
        and bool(broker.get("key_version"))
    ):
        raise ProofgateBootstrapVerifierError("Broker relational mismatch")

    is_test_fixture = getattr(boundary, "_test_observation_fixture", None) is not None
    authority = "test_observation_fixture" if is_test_fixture else "github_and_broker_control_planes"

    binding = {
        "schema": "proofgate_admin_identity_binding.v1",
        "authority": authority,
        "repository_id": repo.get("id"),
        "repository_name": repo.get("name"),
        "app_id": app.get("id"),
        "app_slug": app.get("slug"),
        "installation_id": installation.get("id"),
        "environment_id": _validate_positive_numeric_id(env.get("id"), "environment_id"),
        "ruleset_id": _validate_positive_numeric_id(ruleset.get("id"), "ruleset_id"),
        "reviewer_id": org_user.get("id"),
        "reviewer_login": org_user.get("login"),
        "broker_deployment_id": broker.get("deployment_id"),
        "broker_key_version": broker.get("key_version"),
        "normalized_broker_policy_digest": computed_digest,
        "normalized_github_permissions": (("contents", "write"), ("metadata", "read")),
        "admin_relations": {
            "app_owner_equals_repository_owner": True,
            "installation_app_equals_resolved_app": True,
            "installation_target_equals_app_owner": True,
            "selected_repository_equals_target": True,
            "ruleset_bypass_equals_resolved_app": True,
            "environment_reviewer_equals_active_user": True,
            "broker_relations_match": True,
        },
        "evaluation_partition": {
            "admin_relations": "evaluated",
            "receipt_pilot": "not_evaluated",
        },
    }
    digest_bytes = json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    binding["binding_digest"] = hashlib.sha256(digest_bytes).hexdigest()
    return binding


def verify_selector_repair_review_binding(
    repo_path: Path | str,
    review_binding_path: Path | str,
    expected_original_tests_landing: str | None = None,
    expected_selector_repair_landing: str | None = None,
) -> dict[str, Any]:
    """Verifies digest-bound selector-repair review binding."""
    binding_path = Path(review_binding_path).resolve()
    if not binding_path.is_file():
        raise ProofgateBootstrapVerifierError("selector-repair-review-binding.json missing")
    try:
        raw_binding = binding_path.read_bytes()
        data = json.loads(raw_binding.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofgateBootstrapVerifierError("selector-repair-review-binding is not valid JSON") from exc

    if not isinstance(data, dict):
        raise ProofgateBootstrapVerifierError("selector-repair-review-binding must be a JSON object")

    expected_fields = {
        "landing_change_tuple_digest",
        "landing_path_blob_digest",
        "landing_path_tuples",
        "original_tests_landing_oid",
        "repository",
        "reviewed_change_tuple_digest",
        "reviewed_path_blob_digest",
        "reviewed_path_tuples",
        "schema",
        "selector_repair_base_oid",
        "selector_repair_landing_oid",
        "selector_repair_red_commit_oid",
        "selector_repair_source_head_oid",
    }
    if set(data) != expected_fields:
        raise ProofgateBootstrapVerifierError("selector-repair-review-binding field inventory mismatch")
    if raw_binding != (
        json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8"):
        raise ProofgateBootstrapVerifierError(
            "selector-repair-review-binding is not canonical compact JSON plus LF"
        )

    if data.get("schema") != "proofgate_selector_repair_review_binding.v1":
        raise ProofgateBootstrapVerifierError("selector-repair-review-binding schema mismatch")

    if data.get("repository") != COORDINATOR_REPOSITORY:
        raise ProofgateBootstrapVerifierError("selector-repair-review-binding repository mismatch")

    orig_oid = data.get("original_tests_landing_oid")
    sr_base_oid = data.get("selector_repair_base_oid")
    sr_red_oid = data.get("selector_repair_red_commit_oid")
    sr_src_oid = data.get("selector_repair_source_head_oid")
    sr_landing_oid = data.get("selector_repair_landing_oid")

    for field, oid in (
        ("original_tests_landing_oid", orig_oid),
        ("selector_repair_base_oid", sr_base_oid),
        ("selector_repair_red_commit_oid", sr_red_oid),
        ("selector_repair_source_head_oid", sr_src_oid),
        ("selector_repair_landing_oid", sr_landing_oid),
    ):
        if not isinstance(oid, str) or HEX_40_RE.fullmatch(oid) is None:
            raise ProofgateBootstrapVerifierError(
                f"selector repair review binding invalid OID: {field}"
            )

    if expected_original_tests_landing and orig_oid != expected_original_tests_landing:
        raise ProofgateBootstrapVerifierError("selector repair review binding mismatch: original_tests_landing_oid")

    if expected_selector_repair_landing and sr_landing_oid != expected_selector_repair_landing:
        raise ProofgateBootstrapVerifierError("selector repair review binding mismatch: selector_repair_landing_oid")

    repo = Path(repo_path).resolve()
    _verifier_validate_selector_repair_landing(
        sr_landing_oid,
        cwd=repo,
        expected_original_landing=orig_oid,
    )
    landing_parents = _verifier_git_parents(sr_landing_oid, cwd=repo)
    if landing_parents != [sr_base_oid, sr_src_oid]:
        raise ProofgateBootstrapVerifierError(
            "selector repair review binding mismatch: landing review chain"
        )
    if _verifier_git_parents(sr_src_oid, cwd=repo) != [sr_red_oid]:
        raise ProofgateBootstrapVerifierError(
            "selector repair review binding mismatch: source head review chain"
        )
    source_facts = compute_git_source_binding_facts(repo, sr_base_oid, sr_src_oid)
    landing_facts = compute_git_source_binding_facts(repo, sr_base_oid, sr_landing_oid)

    if any(
        source_facts.get(field) != landing_facts.get(field)
        for field in ("change_tuple_digest", "path_blob_digest", "path_tuples")
    ):
        raise ProofgateBootstrapVerifierError(
            "reviewed source and selector repair landing change tuples differ"
        )

    if data.get("reviewed_change_tuple_digest") != source_facts["change_tuple_digest"]:
        raise ProofgateBootstrapVerifierError("reviewed change tuple digest mismatch")

    if data.get("reviewed_path_blob_digest") != source_facts["path_blob_digest"]:
        raise ProofgateBootstrapVerifierError("reviewed path blob digest mismatch")

    if data.get("reviewed_path_tuples") != [list(row) for row in source_facts["path_tuples"]]:
        raise ProofgateBootstrapVerifierError("reviewed path tuples mismatch")

    if data.get("landing_change_tuple_digest") != landing_facts["change_tuple_digest"]:
        raise ProofgateBootstrapVerifierError("landing change tuple digest mismatch")

    if data.get("landing_path_blob_digest") != landing_facts["path_blob_digest"]:
        raise ProofgateBootstrapVerifierError("landing path blob digest mismatch")

    if data.get("landing_path_tuples") != [list(row) for row in landing_facts["path_tuples"]]:
        raise ProofgateBootstrapVerifierError("landing path tuples mismatch")

    return {
        "status": "verified",
        "data": data,
    }



def _expected_oidc_claim_map(expected: ProofgateExpectedConfig) -> dict[str, str]:
    """Projects the exact OIDC claim map expected by an independently supplied configuration."""
    return {
        "actor": expected.actor,
        "aud": expected.oidc_audience,
        "broker_claim_policy_digest": expected.broker_claim_policy_digest,
        "broker_deployment_id": expected.broker_deployment_id,
        "broker_key_version": expected.broker_key_version,
        "environment": expected.environment_name,
        "event_name": expected.event_name,
        "repository": expected.repository_name,
        "repository_id": expected.repository_id,
        "repository_owner_id": expected.repository_owner_id,
        "run_attempt": expected.run_attempt,
        "run_id": expected.run_id,
        "runner_environment": expected.runner_environment,
        "subject": expected.subject,
        "workflow_path": expected.workflow_path,
        "workflow_ref": expected.workflow_ref,
        "workflow_sha": expected.workflow_sha256,
    }


def _require_frozen_inputs(
    request: Any,
    expected: Any,
    boundary: Any,
) -> None:
    """Rejects any substitute for the frozen locator, expected configuration or boundary."""
    if type(request) is not ProofgateObservationRequest:
        raise ProofgateBootstrapVerifierError(
            f"Verifier requires an immutable ProofgateObservationRequest locator, got {type(request).__name__}"
        )
    if type(expected) is not ProofgateExpectedConfig:
        raise ProofgateBootstrapVerifierError(
            f"Verifier requires an immutable ProofgateExpectedConfig, got {type(expected).__name__}"
        )
    if canonical_expected_config_digest(expected) != PROOFGATE_EXPECTED_CONFIG_V1_CANONICAL_SHA256:
        raise ProofgateBootstrapVerifierError(
            "Verifier requires the trusted canonical ProofgateExpectedConfig V1 bytes"
        )
    observe = getattr(boundary, "observe", None)
    if observe is None or not callable(observe):
        raise ProofgateBootstrapVerifierError("Verifier requires a read-only observation boundary exposing observe()")


def evaluate_external_observation(
    request: ProofgateObservationRequest,
    observation: Any,
    expected: ProofgateExpectedConfig,
) -> list[tuple[str, bool]]:
    """Compares a sealed observation to the locator and the independently supplied expectations.

    Returns an ordered list of `(check_id, satisfied)` pairs. No element of the result is taken
    from the caller: every expectation comes from `expected`, every observed value from
    `observation`, and every binding from the locator.
    """
    if type(observation) is not ProofgateExternalObservation:
        return [("sealed_observation_schema", False)]

    claims = dict(observation.oidc_claims)
    expected_claims = _expected_oidc_claim_map(expected)
    plan_bytes_bound = True
    if request.plan_path:
        plan_file = Path(request.plan_path)
        if not plan_file.is_file():
            plan_bytes_bound = False
        else:
            plan_bytes_bound = hashlib.sha256(plan_file.read_bytes()).hexdigest() == observation.plan_sha256

    return [
        ("sealed_observation_schema", observation.schema == PROOFGATE_OBSERVATION_SCHEMA),
        (
            "repository_identity",
            observation.repository_id == expected.repository_id
            and observation.repository_owner_id == expected.repository_owner_id
            and observation.repository_name == expected.repository_name,
        ),
        (
            "locator_repository_binding",
            request.repository in (expected.repository_name, expected.repository_id),
        ),
        ("locator_ref_binding", request.ref in expected.accepted_refs),
        ("locator_environment_binding", request.environment == expected.environment_name),
        (
            "locator_external_head_binding",
            request.external_head_ref == expected.external_head_ref
            and observation.external_head_ref == expected.external_head_ref,
        ),
        (
            "dedicated_app_installation",
            observation.app_installation_id == expected.dedicated_app_installation_id
            and observation.app_integration_id == expected.dedicated_app_integration_id
            and observation.app_repository_selection == expected.app_repository_selection
            and tuple(observation.app_permissions) == tuple(expected.app_permissions),
        ),
        (
            "branch_ruleset",
            observation.ruleset_name == expected.ruleset_name
            and set(expected.ruleset_required_rule_types).issubset(set(observation.ruleset_rule_types))
            and expected.external_head_ref in tuple(observation.ruleset_ref_includes)
            and tuple(observation.ruleset_bypass_actors)
            == (("Integration", "always", expected.dedicated_app_integration_id),),
        ),
        (
            "protected_environment",
            observation.environment_name == expected.environment_name
            and observation.environment_can_admins_bypass is False
            and observation.environment_prevent_self_review is True
            and tuple(observation.environment_required_reviewer_ids) == (expected.required_reviewer_id,),
        ),
        (
            "broker_oidc_claim_policy",
            observation.broker_deployment_id == expected.broker_deployment_id
            and observation.broker_key_version == expected.broker_key_version
            and observation.broker_claim_policy_digest == expected.broker_claim_policy_digest
            and set(claims.keys()) == set(expected_claims.keys()) | {"ref"}
            and all(claims.get(k) == v for k, v in expected_claims.items())
            and claims.get("ref") in expected.accepted_refs,
        ),
        (
            "attested_workflow_binding",
            observation.workflow_ref == expected.workflow_ref
            and observation.workflow_path == expected.workflow_path
            and observation.workflow_sha256 == expected.workflow_sha256
            and observation.runner_environment == expected.runner_environment
            and observation.event_name == expected.event_name
            and observation.actor == expected.actor
            and observation.subject == expected.subject
            and observation.run_id == expected.run_id
            and observation.run_attempt == expected.run_attempt,
        ),
        (
            "external_head_freshness",
            bool(HEX_40_RE.match(str(observation.external_head_oid)))
            and str(observation.external_head_oid) != "0" * 40,
        ),
        (
            "candidate_binding",
            bool(HEX_40_RE.match(str(observation.candidate_oid)))
            and (not request.candidate_oid or request.candidate_oid == observation.candidate_oid),
        ),
        ("plan_bytes_binding", plan_bytes_bound and bool(HEX_64_RE.match(str(observation.plan_sha256)))),
        (
            "receipt_digest_chain",
            bool(HEX_64_RE.match(str(observation.core_sha256)))
            and observation.subject == f"cores/{observation.sequence:020d}-{observation.core_sha256}.json"
            and observation.bundle_sha256
            == expected_bundle_digest(observation.core_sha256, observation.workflow_sha256)
            and observation.append_sha256
            == expected_append_digest(observation.sequence, observation.core_sha256, observation.bundle_sha256),
        ),
        (
            "receipt_sequence",
            isinstance(observation.sequence, int)
            and not isinstance(observation.sequence, bool)
            and observation.sequence >= 1
            and (not request.sequence or request.sequence == observation.sequence),
        ),
        (
            "panel_seat_agreement",
            tuple(sorted(seat for seat, _v, _r in observation.panel_seat_verdicts))
            == tuple(sorted(expected.required_panel_seats))
            and all(verdict == "AGREE" for _s, verdict, _r in observation.panel_seat_verdicts)
            and len({run_id for _s, _v, run_id in observation.panel_seat_verdicts})
            == len(expected.required_panel_seats),
        ),
        (
            "red_lifecycle_accounting",
            observation.red_lifecycle_nodeids == expected.expected_nodeid_count
            and observation.red_lifecycle_passed == expected.forced_red_passed
            and observation.red_lifecycle_failed == expected.forced_red_failed,
        ),
    ]


def verify_external_observation(
    request: ProofgateObservationRequest,
    *,
    expected: ProofgateExpectedConfig,
    boundary: Any,
) -> dict[str, Any]:
    """Test-owned decisive verifier bound to a read-only external observation boundary.

    The boundary is called exactly once, with only the locator. Authority comes solely from
    comparing the returned sealed observation to the independently supplied expected config.
    """
    _require_frozen_inputs(request, expected, boundary)
    try:
        observation = boundary.observe(request)
    except Exception as exc:  # fail closed on any boundary failure
        return {
            "status": "blocked",
            "authorized": False,
            "decisive": False,
            "evidence_kind": "observation_unavailable",
            "blocker_class": "contract_bug",
            "human_required": False,
            "failed_checks": ["external_observation"],
            "observation_error": type(exc).__name__,
        }

    checks = evaluate_external_observation(request, observation, expected)
    failed = [check_id for check_id, ok in checks if not ok]
    if failed:
        return {
            "status": "blocked",
            "authorized": False,
            "decisive": False,
            "evidence_kind": "observation_mismatch",
            "blocker_class": "contract_bug",
            "human_required": False,
            "failed_checks": failed,
        }

    return {
        "status": "verified",
        "authorized": True,
        "decisive": True,
        "evidence_kind": "production_external_boundary",
        "blocker_class": None,
        "human_required": False,
        "failed_checks": [],
        "observation_digest": observation_digest(observation),
    }


def run_admin_preflight(
    request: ProofgateObservationRequest,
    *,
    expected: ProofgateExpectedConfig,
    boundary: Any,
    output: str,
) -> int:
    """Admin preflight over a read-only external observation boundary.

    Receives the immutable expected configuration and the observation boundary explicitly, calls
    the boundary once with only the locator, and never executes `gh`, network, auth or provider
    operations of its own.
    """
    _require_frozen_inputs(request, expected, boundary)
    out_path = _validate_run_dir_output(output)

    try:
        observation = boundary.observe(request)
    except Exception as exc:
        _write_admin_preflight_payload(
            out_path,
            satisfied=False,
            attempts=[{"check": "external_observation", "status": "unavailable", "redacted": True}],
            outcome_class="unavailable",
        )
        raise ProofgateBootstrapVerifierError(
            f"admin-preflight external observation unavailable: {type(exc).__name__}"
        ) from exc

    checks = evaluate_external_observation(request, observation, expected)
    attempts = [
        {"check": check_id, "status": "ok" if ok else "mismatch", "redacted": True} for check_id, ok in checks
    ]
    failed = [check_id for check_id, ok in checks if not ok]

    if not failed:
        _write_admin_preflight_payload(out_path, satisfied=True, attempts=attempts, outcome_class=None)
        return 0

    _write_admin_preflight_payload(out_path, satisfied=False, attempts=attempts, outcome_class="admin_approval")
    raise ProofgateBootstrapVerifierError(
        f"admin-preflight prerequisite unsatisfied against independently supplied expectations: {failed}"
    )


def _write_admin_preflight_payload(
    out_path: Path,
    *,
    satisfied: bool,
    attempts: list[dict[str, Any]],
    outcome_class: str | None,
    binding: dict[str, Any] | None = None,
) -> None:
    if satisfied:
        payload: dict[str, Any] = {
            "human_required": False,
            "blocker_class": None,
            "verification_status": "satisfied",
            "access_attempts": attempts,
        }
        if binding is not None:
            payload["admin_identity_binding"] = binding
    else:
        payload = {
            "human_required": True,
            "blocker_class": outcome_class,
            "verification_status": "blocked",
            "access_attempts": attempts,
            "required_human_inputs": [
                "dedicated_github_app",
                "github_app_installation",
                "protected_environment",
                "branch_ruleset",
            ],
        }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(out_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, indent=2))


def run_live_admin_binding_preflight(boundary: Any, *, output: str) -> int:
    """Run the PR-R admin-only gate through the fixed concrete control-plane boundary."""
    out_path = _validate_run_dir_output(output)
    observed_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        binding = verify_proofgate_admin_identity_binding(boundary)
        if binding.get("authority") != "github_and_broker_control_planes":
            raise ProofgateBootstrapVerifierError("admin identity binding is nondecisive for test-owned boundary")
    except (
        ProofgateBootstrapVerifierError,
        ProofgateObservationUnavailable,
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        subprocess.SubprocessError,
    ):
        _write_admin_preflight_payload(
            out_path,
            satisfied=False,
            attempts=[
                {
                    "source": "github_and_broker_control_planes",
                    "probe": "proofgate_admin_identity_binding.v1",
                    "result": "unavailable_or_mismatch",
                    "details": "metadata-only control-plane relation check did not satisfy",
                    "timestamp": observed_at,
                }
            ],
            outcome_class="admin_approval",
        )
        return 1

    _write_admin_preflight_payload(
        out_path,
        satisfied=True,
        attempts=[
            {
                "source": "github_and_broker_control_planes",
                "probe": "proofgate_admin_identity_binding.v1",
                "result": "satisfied",
                "details": "metadata-only control-plane relations verified",
                "timestamp": observed_at,
            }
        ],
        outcome_class=None,
        binding=binding,
    )
    return 0


def run_app_oidc_pilot(
    request: ProofgateObservationRequest,
    workflow: str,
    *,
    expected: ProofgateExpectedConfig,
    boundary: Any,
    output: str,
) -> int:
    """App/OIDC pilot over the same read-only external observation boundary. Fails closed."""
    _require_frozen_inputs(request, expected, boundary)
    _validate_run_dir_output(output)

    if workflow != expected.workflow_path:
        raise ProofgateBootstrapVerifierError(f"Wrong workflow for app-oidc-pilot: {workflow}")
    if request.ref not in expected.accepted_refs:
        raise ProofgateBootstrapVerifierError(f"Wrong ref for app-oidc-pilot: {request.ref}")
    if request.environment != expected.environment_name:
        raise ProofgateBootstrapVerifierError(f"Wrong environment for app-oidc-pilot: {request.environment}")

    raise ProofgateBootstrapVerifierError("app-oidc-pilot prerequisites not satisfied in non-attended CLI environment")


def _observation_tampers(
    expected: ProofgateExpectedConfig,
    base: ProofgateExternalObservation,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Single-field corruptions of a conforming observation that every verifier must reject."""
    return (
        ("sealed_schema_substituted", {"schema": "proofgate_local_json.v1"}),
        ("repository_identity_42_42", {"repository_id": "42", "repository_owner_id": "42"}),
        ("required_reviewer_43", {"environment_required_reviewer_ids": ("43",)}),
        ("admins_may_bypass_environment", {"environment_can_admins_bypass": True}),
        ("self_review_permitted", {"environment_prevent_self_review": False}),
        ("app_installation_substituted", {"app_installation_id": "42"}),
        ("app_integration_substituted", {"app_integration_id": "42"}),
        ("app_permissions_widened", {"app_permissions": (("contents", "write"), ("actions", "write"))}),
        (
            "ruleset_bypass_actor_added",
            {"ruleset_bypass_actors": tuple(base.ruleset_bypass_actors) + (("User", "always", "42"),)},
        ),
        (
            "ruleset_rule_dropped",
            {"ruleset_rule_types": tuple(t for t in base.ruleset_rule_types if t != "non_fast_forward")},
        ),
        ("ruleset_ref_unbound", {"ruleset_ref_includes": ("refs/heads/main",)}),
        (
            "garbage_oidc_claims",
            {
                "oidc_claims": (
                    ("actor", "garbage-actor"),
                    ("aud", "garbage-aud"),
                    ("repository_id", "42"),
                    ("repository_owner_id", "42"),
                    ("run_attempt", "999"),
                    ("run_id", "999"),
                    ("subject", "garbage-subject"),
                )
            },
        ),
        ("broker_policy_digest_drift", {"broker_claim_policy_digest": "0" * 64}),
        ("workflow_blob_drift", {"workflow_sha256": "0" * 64}),
        (
            "workflow_ref_drift",
            {"workflow_ref": f"{expected.repository_name}/.github/workflows/other.yml@refs/heads/main"},
        ),
        ("runner_environment_self_hosted", {"runner_environment": "self-hosted"}),
        ("actor_substituted", {"actor": "garbage-actor"}),
        ("subject_substituted", {"subject": f"cores/{2:020d}-{'0' * 64}.json"}),
        ("stale_external_head", {"external_head_oid": "0" * 40}),
        ("candidate_substituted", {"candidate_oid": "9" * 40}),
        ("plan_bytes_drift", {"plan_sha256": "0" * 64}),
        ("core_digest_drift", {"core_sha256": "0" * 64}),
        ("bundle_digest_collides_core", {"bundle_sha256": base.core_sha256}),
        ("append_digest_collides_bundle", {"append_sha256": base.bundle_sha256}),
        ("sequence_rollback", {"sequence": 0}),
        (
            "panel_seat_disagrees",
            {
                "panel_seat_verdicts": tuple(
                    (seat, "DISAGREE" if seat == expected.required_panel_seats[0] else verdict, run_id)
                    for seat, verdict, run_id in base.panel_seat_verdicts
                )
            },
        ),
        ("panel_seat_missing", {"panel_seat_verdicts": tuple(base.panel_seat_verdicts)[:-1]}),
        (
            "panel_run_identity_replayed",
            {
                "panel_seat_verdicts": tuple(
                    (seat, verdict, "run-replayed") for seat, verdict, _r in base.panel_seat_verdicts
                )
            },
        ),
        ("red_lifecycle_short", {"red_lifecycle_failed": expected.forced_red_failed - 1}),
        ("nodeid_inventory_drift", {"red_lifecycle_nodeids": expected.expected_nodeid_count - 1}),
    )


def _authority_asserted(result: Any) -> bool:
    """True when a verifier result asserts decisive production authority."""
    if not isinstance(result, dict):
        return False
    return (
        result.get("status") == "verified"
        and result.get("decisive") is True
        and result.get("evidence_kind") == "production_external_boundary"
    )


def _claims_authority(result: Any) -> bool:
    """True for any result that claims authority, independent of an evidence-kind label."""
    return isinstance(result, dict) and (
        result.get("status") == "verified"
        or result.get("decisive") is True
        or result.get("authorized") is True
    )


def assert_observation_bound_verifier_contract(
    verify_callable: Any,
    *,
    expected: ProofgateExpectedConfig,
    contract_label: str,
    require_authorized_flag: bool = False,
) -> None:
    """Frozen oracle: a verifier's authority must derive from the external observation boundary.

    The verifier is handed only a locator, the immutable expected configuration and a recording
    boundary. It must call the boundary exactly once with exactly that locator, assert decisive
    production authority only for a fully conforming observation, and fail closed for every
    single-field observation corruption and for an unavailable boundary.
    """
    if type(expected) is not ProofgateExpectedConfig:
        raise ProofgateContractViolation(f"{contract_label}: expected configuration must be immutable and frozen")

    with tempfile.TemporaryDirectory() as td:
        plan_path = Path(td) / "phase-plan-v10-PROOFGATE.md"
        plan_path.write_text("# PROOFGATE\n\n## Acceptance\n- EC-PROOFGATE-0\n", encoding="utf-8")
        plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        head_oid = hashlib.sha1(b"commit 1\x00").hexdigest()

        request = ProofgateObservationRequest(
            repository=expected.repository_name,
            ref=expected.accepted_refs[0],
            environment=expected.environment_name,
            external_head_ref=expected.external_head_ref,
            candidate_oid=head_oid,
            plan_path=str(plan_path),
            sequence=subject_sequence_and_core_digest(expected)[0],
        )
        base = conforming_observation(
            expected,
            external_head_oid=head_oid,
            candidate_oid=head_oid,
            plan_sha256=plan_sha256,
        )

        def _invoke(observation: ProofgateExternalObservation) -> tuple[Any, RecordingObservationBoundary]:
            boundary = RecordingObservationBoundary(observation)
            try:
                result: Any = verify_callable(request, expected=expected, boundary=boundary)
            except TypeError as exc:
                raise ProofgateContractViolation(
                    f"{contract_label}: verifier does not accept (locator, expected=, boundary=): {exc}"
                ) from exc
            except Exception as exc:  # a fail-closed rejection is a legitimate outcome
                result = exc
            return result, boundary

        positive, boundary = _invoke(base)
        if isinstance(positive, Exception):
            raise ProofgateContractViolation(
                f"{contract_label}: conforming observation was rejected ({type(positive).__name__}: {positive})"
            )
        if boundary.calls != (request,):
            raise ProofgateContractViolation(
                f"{contract_label}: boundary call trace must be exactly the locator, got {boundary.calls!r}"
            )
        if not _authority_asserted(positive):
            raise ProofgateContractViolation(
                f"{contract_label}: conforming observation did not yield decisive production authority: {positive!r}"
            )
        if require_authorized_flag and positive.get("authorized") is not True:
            raise ProofgateContractViolation(f"{contract_label}: conforming observation did not authorize")
        if positive.get("observation_digest") != observation_digest(base):
            raise ProofgateContractViolation(
                f"{contract_label}: result is not bound to the observed bytes (observation_digest mismatch)"
            )

        for tamper_id, replacement in _observation_tampers(expected, base):
            tampered = dataclasses.replace(base, **replacement)
            result, tampered_boundary = _invoke(tampered)
            if tampered_boundary.calls != (request,):
                raise ProofgateContractViolation(
                    f"{contract_label}/{tamper_id}: boundary call trace must be exactly the locator, "
                    f"got {tampered_boundary.calls!r}"
                )
            if isinstance(result, Exception):
                continue
            if _claims_authority(result):
                raise ProofgateContractViolation(
                    f"{contract_label}/{tamper_id}: corrupted observation was accepted: {result!r}"
                )

        unavailable = UnavailableObservationBoundary()
        try:
            result = verify_callable(request, expected=expected, boundary=unavailable)
        except Exception:
            result = None
        if unavailable.calls != (request,):
            raise ProofgateContractViolation(
                f"{contract_label}/unavailable_boundary: boundary must still be called with exactly the locator"
            )
        if result is not None and _claims_authority(result):
            raise ProofgateContractViolation(
                f"{contract_label}/unavailable_boundary: verifier authorized without an observation: {result!r}"
            )

        for label, substitute in (
            ("caller_authored_mapping", {"external_head_oid": head_oid, "decisive": True, "status": "verified"}),
            ("mutable_expected_config", None),
        ):
            probe_boundary = RecordingObservationBoundary(base)
            try:
                if label == "caller_authored_mapping":
                    result = verify_callable(substitute, expected=expected, boundary=probe_boundary)
                else:
                    result = verify_callable(request, expected=_MutableExpectedConfigDouble(), boundary=probe_boundary)
            except Exception:
                continue
            if _claims_authority(result):
                raise ProofgateContractViolation(
                    f"{contract_label}/{label}: verifier accepted caller-supplied authority: {result!r}"
                )


class _MutableExpectedConfigDouble:
    """Mutable 42/42/43-plus-garbage stand-in for the immutable expected configuration."""

    repository_id = "42"
    repository_owner_id = "42"
    repository_name = "Consiliency/garbage-repo"
    dedicated_app_integration_id = "42"
    dedicated_app_installation_id = "42"
    app_repository_selection = "all"
    app_permissions = (("contents", "write"),)
    required_reviewer_id = "43"
    ruleset_name = "garbage-ruleset"
    ruleset_required_rule_types = ()
    broker_deployment_id = "garbage-broker"
    broker_key_version = "garbage-key"
    broker_claim_policy_digest = "garbage-digest"
    oidc_audience = "garbage-aud"
    workflow_ref = "garbage-workflow-ref"
    workflow_path = "garbage-workflow-path"
    workflow_sha256 = "garbage-sha"
    event_name = "garbage_event"
    runner_environment = "garbage-runner"
    environment_name = "garbage-env"
    external_head_ref = "refs/heads/garbage"
    accepted_refs = ("refs/heads/garbage",)
    actor = "garbage-actor"
    subject = "garbage-subject"
    run_id = "999"
    run_attempt = "999"
    expected_nodeid_count = 1
    forced_red_passed = 0
    forced_red_failed = 0
    required_panel_seats = ()


def assert_preflight_intake_contract(verify_callable: Any, *, expected: ProofgateExpectedConfig) -> None:
    """Frozen preflight-intake authority contract."""
    assert_observation_bound_verifier_contract(
        verify_callable,
        expected=expected,
        contract_label="proofgate_preflight_intake",
        require_authorized_flag=True,
    )


def assert_closeout_attestation_contract(verify_callable: Any, *, expected: ProofgateExpectedConfig) -> None:
    """Frozen closeout-attestation authority contract."""
    assert_observation_bound_verifier_contract(
        verify_callable,
        expected=expected,
        contract_label="proofgate_closeout_attestation",
    )


def assert_external_attestation_contract(verify_callable: Any, *, expected: ProofgateExpectedConfig) -> None:
    """Frozen external-attestation authority contract."""
    assert_observation_bound_verifier_contract(
        verify_callable,
        expected=expected,
        contract_label="proofgate_external_attestation",
    )


def assert_admin_preflight_authority_contract(expected: ProofgateExpectedConfig, run_dir: Path) -> None:
    """Direct control over the test-owned admin verifier.

    Proves the admin verifier receives the immutable expected configuration and the observation
    boundary explicitly, rejects a matching 42/42/43-plus-garbage observation, rejects a mutable
    expected-configuration substitute, and never executes `gh`, network, auth or provider work.
    """
    request = ProofgateObservationRequest(
        repository=expected.repository_name,
        ref=expected.accepted_refs[0],
        environment=expected.environment_name,
        external_head_ref=expected.external_head_ref,
    )

    garbage = ProofgateExternalObservation(
        schema=PROOFGATE_OBSERVATION_SCHEMA,
        repository_id="42",
        repository_owner_id="42",
        repository_name="Consiliency/garbage-repo",
        app_integration_id="42",
        app_installation_id="42",
        app_repository_selection="all",
        app_permissions=(("contents", "write"), ("actions", "write")),
        ruleset_name="garbage-ruleset",
        ruleset_rule_types=(),
        ruleset_ref_includes=("refs/heads/garbage",),
        ruleset_bypass_actors=(("User", "always", "42"),),
        environment_name="garbage-env",
        environment_can_admins_bypass=True,
        environment_prevent_self_review=False,
        environment_required_reviewer_ids=("43",),
        oidc_claims=(("aud", "garbage-aud"), ("repository_id", "42"), ("repository_owner_id", "42")),
        broker_deployment_id="garbage-broker",
        broker_key_version="garbage-key",
        broker_claim_policy_digest="garbage-digest",
        external_head_ref="refs/heads/garbage",
        external_head_oid="0" * 40,
        candidate_oid="0" * 40,
        plan_sha256="0" * 64,
        workflow_ref="garbage-workflow-ref",
        workflow_path="garbage-workflow-path",
        workflow_sha256="garbage-sha",
        runner_environment="garbage-runner",
        event_name="garbage_event",
        actor="garbage-actor",
        subject="garbage-subject",
        run_id="999",
        run_attempt="999",
        core_sha256="0" * 64,
        bundle_sha256="0" * 64,
        append_sha256="0" * 64,
        sequence=999,
        panel_seat_verdicts=(),
        red_lifecycle_passed=0,
        red_lifecycle_failed=0,
        red_lifecycle_nodeids=1,
    )

    garbage_boundary = RecordingObservationBoundary(garbage)
    try:
        run_admin_preflight(
            request,
            expected=expected,
            boundary=garbage_boundary,
            output=str(run_dir / "admin-garbage.json"),
        )
    except ProofgateBootstrapVerifierError:
        pass
    else:
        raise ProofgateContractViolation("admin preflight accepted a 42/42/43-plus-garbage observation")
    if garbage_boundary.calls != (request,):
        raise ProofgateContractViolation("admin preflight did not call the boundary with exactly the locator")

    conforming_boundary = RecordingObservationBoundary(garbage)
    try:
        run_admin_preflight(
            request,
            expected=_MutableExpectedConfigDouble(),
            boundary=conforming_boundary,
            output=str(run_dir / "admin-mutable-config.json"),
        )
    except ProofgateBootstrapVerifierError:
        pass
    else:
        raise ProofgateContractViolation("admin preflight accepted a mutable expected-configuration substitute")

    exact_class_mutation = dataclasses.replace(expected)
    for field, value in (
        ("repository_id", "42"),
        ("repository_owner_id", "42"),
        ("required_reviewer_id", "43"),
        ("repository_name", "Consiliency/garbage-repo"),
        ("broker_deployment_id", "garbage-broker"),
    ):
        object.__setattr__(exact_class_mutation, field, value)
    exact_class_request = ProofgateObservationRequest(
        repository=exact_class_mutation.repository_name,
        ref=exact_class_mutation.accepted_refs[0],
        environment=exact_class_mutation.environment_name,
        external_head_ref=exact_class_mutation.external_head_ref,
    )
    exact_class_observation = conforming_observation(
        exact_class_mutation,
        external_head_oid="a" * 40,
        candidate_oid="a" * 40,
        plan_sha256="b" * 64,
    )
    if not all(ok for _check, ok in evaluate_external_observation(
        exact_class_request, exact_class_observation, exact_class_mutation
    )):
        raise ProofgateContractViolation("exact-class mutation did not construct a matching observation")
    exact_class_boundary = RecordingObservationBoundary(exact_class_observation)
    try:
        run_admin_preflight(
            exact_class_request,
            expected=exact_class_mutation,
            boundary=exact_class_boundary,
            output=str(run_dir / "admin-exact-class-mutated.json"),
        )
    except ProofgateBootstrapVerifierError:
        pass
    else:
        raise ProofgateContractViolation("admin preflight accepted an exact-class mutated expected configuration")
    if exact_class_boundary.calls:
        raise ProofgateContractViolation("exact-class mutated expected configuration reached the observation boundary")

    cli_boundary = GitHubCliObservationBoundary()
    if cli_boundary.attended_live is not False:
        raise ProofgateContractViolation("live GitHub CLI observation must be disabled by construction")
    if not callable(getattr(cli_boundary, "observe", None)):
        raise ProofgateContractViolation("GitHub CLI adapter must expose the read-only observe() surface")
    if any(name.startswith("run") or name in ("fetch", "call") for name in vars(type(cli_boundary))):
        raise ProofgateContractViolation("GitHub CLI adapter exposes an execution surface")
    try:
        cli_boundary.observe(request)
    except ProofgateObservationUnavailable:
        pass
    else:
        raise ProofgateContractViolation("GitHub CLI adapter executed a live observation in an ordinary run")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="proofgate_bootstrap_verifier CLI")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    admin_parser = subparsers.add_parser("admin-preflight")
    admin_parser.add_argument("--repo", required=True)
    admin_parser.add_argument("--ref", required=True)
    admin_parser.add_argument("--environment", required=True)
    admin_parser.add_argument("--output", required=True)

    pilot_parser = subparsers.add_parser("app-oidc-pilot")
    pilot_parser.add_argument("--repo", required=True)
    pilot_parser.add_argument("--workflow", required=True)
    pilot_parser.add_argument("--ref", required=True)
    pilot_parser.add_argument("--environment", required=True)
    pilot_parser.add_argument("--output", required=True)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    # The expected configuration is supplied to the verifier from its own frozen source; the CLI
    # only names a locator and selects an observation boundary. Live observation stays opt-in and
    # operator-driven, so an ordinary run can never reach it.
    try:
        from .proofgate_tdd_guard import PROOFGATE_EXPECTED_CONFIG_V1
    except ImportError:
        from proofgate_tdd_guard import PROOFGATE_EXPECTED_CONFIG_V1

    expected = PROOFGATE_EXPECTED_CONFIG_V1
    repo_arg = args.repo
    if repo_arg in (".", "./", "") or repo_arg.startswith("/"):
        repo_arg = expected.repository_name
    if args.mode == "admin-preflight":
        if (
            repo_arg != expected.repository_name
            or args.ref != expected.external_head_ref
            or args.environment != expected.environment_name
        ):
            sys.stderr.write("Verifier error: admin-preflight locator does not match fixed selectors\n")
            return 1

        run_dir = os.environ.get("PHASE_LOOP_RUN_DIR")
        try:
            output_path = Path(args.output).resolve()
            run_path = Path(run_dir).resolve() if run_dir else None
        except OSError:
            output_path = None
            run_path = None
        if run_path is None or output_path is None or run_path not in output_path.parents:
            sys.stderr.write(
                "Verifier error: admin-preflight output must be under PHASE_LOOP_RUN_DIR\n"
            )
            return 1

        return run_live_admin_binding_preflight(
            ProofgateAdminControlPlaneBoundary(), output=args.output
        )

    boundary = GitHubCliObservationBoundary(
        attended_live=os.environ.get("PHASE_LOOP_PROOFGATE_ATTENDED_LIVE") == "1"
    )
    request = ProofgateObservationRequest(
        repository=repo_arg,
        ref=args.ref,
        environment=args.environment,
        external_head_ref=expected.external_head_ref,
    )

    try:
        if args.mode == "app-oidc-pilot":
            return run_app_oidc_pilot(
                request, args.workflow, expected=expected, boundary=boundary, output=args.output
            )
        else:
            sys.stderr.write(f"Unknown mode: {args.mode}\n")
            return 1
    except ProofgateBootstrapVerifierError as exc:
        sys.stderr.write(f"Verifier error: {exc}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"Unexpected error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
