"""Deterministic vector runner for the packaged outside-agent corpus."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from .outside_agent_core import (
    OutsideAgentBlocker,
    OutsideAgentVerdictStatus,
    validate_outside_agent_submission,
)
from .outside_agent_pin import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    OutsideAgentContractPin,
)
from .outside_agent_schema import validate_outside_agent_route_verdict_schema


_VECTOR_MANIFEST_SCHEMA_VERSION = "outside_agent_vector_manifest.v0.1"
_SUBMISSION_TARGET = "outside_agent_submission.v0.1"
_ROUTE_TARGET = "outside_agent_route_verdict.v0.1"


@dataclass(frozen=True)
class OutsideAgentVectorResult:
    vector_name: str
    status: OutsideAgentVerdictStatus
    expected_status: OutsideAgentVerdictStatus | None
    matched: bool
    blockers: tuple[OutsideAgentBlocker, ...]
    evidence_refs: tuple[str, ...]
    dispatch_observation: Mapping[str, object] | None = None


def run_outside_agent_vectors(
    manifest: Mapping[str, Any] | str | Path | None = None,
    *,
    contract_pin: OutsideAgentContractPin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
) -> tuple[OutsideAgentVectorResult, ...]:
    manifest_data, manifest_digest = _load_manifest(manifest)
    blockers = _validate_manifest(manifest_data, manifest_digest)
    if blockers:
        return (
            OutsideAgentVectorResult(
                vector_name="__manifest__",
                status=OutsideAgentVerdictStatus.BLOCKED,
                expected_status=None,
                matched=False,
                blockers=blockers,
                evidence_refs=(contract_pin.vector_manifest_name,),
            ),
        )

    results: list[OutsideAgentVectorResult] = []
    for vector in manifest_data.get("vectors", []):
        if "case_id" not in vector:
            results.append(_run_legacy_vector(vector, contract_pin))
            continue
        results.append(_run_canonical_vector(vector, contract_pin))
    return tuple(results)


def _run_canonical_vector(
    vector: Mapping[str, Any], contract_pin: OutsideAgentContractPin
) -> OutsideAgentVectorResult:
    case_id = str(vector["case_id"])
    schema_target = str(vector["schema_target"])
    payload = json.loads(
        _contract_path(str(vector["path"])).read_text(encoding="utf-8")
    )
    expected_status = (
        OutsideAgentVerdictStatus.PASS
        if vector["expected_valid"]
        else OutsideAgentVerdictStatus.BLOCKED
    )
    if schema_target == _ROUTE_TARGET:
        route = validate_outside_agent_route_verdict_schema(
            payload, schema_target=schema_target
        )
        return OutsideAgentVectorResult(
            vector_name=case_id,
            status=route.status,
            expected_status=expected_status,
            matched=route.status == expected_status,
            blockers=route.blockers,
            evidence_refs=(),
            dispatch_observation=route.dispatch_observation,
        )
    if schema_target != _SUBMISSION_TARGET:
        blocker = OutsideAgentBlocker(
            "schema_validation_failed", "submitted value is not permitted", ref="/"
        )
        return OutsideAgentVectorResult(
            vector_name=case_id,
            status=OutsideAgentVerdictStatus.BLOCKED,
            expected_status=expected_status,
            matched=False,
            blockers=(blocker,),
            evidence_refs=(),
            dispatch_observation={
                "entered": True,
                "schema_target": schema_target,
                "selected_schema_id": None,
                "selected_schema_sha256": None,
                "validation_error_pointer": "/",
                "validation_error_keyword": "schema_target",
            },
        )
    verdict = validate_outside_agent_submission(payload, contract_pin=contract_pin)
    return OutsideAgentVectorResult(
        vector_name=case_id,
        status=verdict.status,
        expected_status=expected_status,
        matched=verdict.status == expected_status,
        blockers=verdict.blockers,
        evidence_refs=tuple(ref.ref for ref in verdict.evidence_refs),
        dispatch_observation=None,
    )


def _run_legacy_vector(
    vector: Mapping[str, Any], contract_pin: OutsideAgentContractPin
) -> OutsideAgentVectorResult:
    expected_status = OutsideAgentVerdictStatus(vector["expected_status"])
    verdict = validate_outside_agent_submission(
        vector["submission"], contract_pin=contract_pin
    )
    expected_blockers = tuple(vector.get("expected_blocker_codes", ()))
    return OutsideAgentVectorResult(
        vector_name=str(vector["name"]),
        status=verdict.status,
        expected_status=expected_status,
        matched=(
            verdict.status == expected_status
            and all(code in {blocker.code for blocker in verdict.blockers} for code in expected_blockers)
        ),
        blockers=verdict.blockers,
        evidence_refs=tuple(ref.ref for ref in verdict.evidence_refs),
    )


def _load_manifest(
    manifest: Mapping[str, Any] | str | Path | None,
) -> tuple[Mapping[str, Any], str]:
    if manifest is None:
        raw = _contract_path("test-vectors/outside-agent/manifest.json").read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    if isinstance(manifest, Mapping):
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return manifest, hashlib.sha256(raw).hexdigest()
    raw = Path(manifest).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _contract_path(relative: str):
    return (
        resources.files("phase_loop_runtime.conformance")
        .joinpath("_contract")
        .joinpath(relative)
    )


def _validate_manifest(
    manifest: Mapping[str, Any], manifest_digest: str
) -> tuple[OutsideAgentBlocker, ...]:
    if manifest.get("manifest_schema_version") != _VECTOR_MANIFEST_SCHEMA_VERSION:
        return (
            OutsideAgentBlocker(
                "unsupported_schema_version",
                "outside-agent vector manifest schema is not supported",
                ref="manifest_schema_version",
            ),
        )
    declared_digest = manifest.get("manifest_digest")
    if declared_digest and str(declared_digest).removeprefix("sha256:").lower() != manifest_digest:
        return (
            OutsideAgentBlocker(
                "digest_mismatch",
                "outside-agent vector manifest digest drifted",
                ref="manifest_digest",
            ),
        )
    vectors = manifest.get("vectors")
    if not isinstance(vectors, list):
        return (
            OutsideAgentBlocker(
                "schema_validation_failed",
                "outside-agent vector manifest must contain vectors",
                ref="vectors",
            ),
        )
    for index, vector in enumerate(vectors):
        if not isinstance(vector, Mapping):
            return (
                OutsideAgentBlocker(
                    "schema_validation_failed",
                    "outside-agent vector must be metadata",
                    ref=f"vectors.{index}",
                ),
            )
        if "case_id" in vector:
            required = ("case_id", "path", "schema_target", "expected_valid", "expected_blocker_class")
        else:
            required = ("name", "submission", "expected_status")
        missing = next((key for key in required if key not in vector), None)
        if missing is not None:
            return (
                OutsideAgentBlocker(
                    "schema_validation_failed",
                    "outside-agent vector is incomplete",
                    ref=f"vectors.{index}.{missing}",
                ),
            )
    return ()


__all__ = ["OutsideAgentVectorResult", "run_outside_agent_vectors"]
