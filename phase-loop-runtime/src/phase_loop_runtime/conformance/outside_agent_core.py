"""Deterministic outside-agent conformance verdict core."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .outside_agent_pin import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    OutsideAgentContractPin,
)


class OutsideAgentSubmissionKind(str, Enum):
    WORK_REQUEST = "work_request"
    IMPLEMENTATION_SUBMISSION = "implementation_submission"
    AMBIGUITY_REPORT = "ambiguity_report"


class OutsideAgentVerdictStatus(str, Enum):
    PASS = "pass"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class OutsideAgentBlocker:
    code: str
    message: str
    ref: str | None = None


@dataclass(frozen=True)
class OutsideAgentEvidenceRef:
    ref: str
    digest: str
    kind: str = "metadata"


@dataclass(frozen=True)
class OutsideAgentConformanceVerdict:
    verdict_schema_version: str
    submission_kind: OutsideAgentSubmissionKind | None
    status: OutsideAgentVerdictStatus
    blockers: tuple[OutsideAgentBlocker, ...]
    contract_pin: OutsideAgentContractPin
    input_digest: str
    provenance_refs: tuple[str, ...]
    evidence_refs: tuple[OutsideAgentEvidenceRef, ...]
    redaction_posture: str = "metadata_only"
    metadata: Mapping[str, str] = field(default_factory=dict)


def validate_outside_agent_submission(
    submission: Mapping[str, Any],
    *,
    contract_pin: OutsideAgentContractPin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    input_digest: str | None = None,
) -> OutsideAgentConformanceVerdict:
    """Validate a canonical submission with a schema-only structural boundary."""
    from .outside_agent_schema import validate_outside_agent_submission_schema

    captured_digest = input_digest or _digest_mapping(submission)
    schema_result = validate_outside_agent_submission_schema(
        submission, contract_pin=contract_pin
    )
    blockers = list(schema_result.blockers)
    evidence_refs = _project_evidence_refs(submission)
    if not blockers:
        blockers.extend(_source_bundle_blockers(submission))

    return OutsideAgentConformanceVerdict(
        verdict_schema_version=contract_pin.verdict_schema_version,
        submission_kind=schema_result.submission_kind,
        status=(
            OutsideAgentVerdictStatus.BLOCKED
            if blockers
            else OutsideAgentVerdictStatus.PASS
        ),
        blockers=tuple(blockers),
        contract_pin=contract_pin,
        input_digest=captured_digest,
        provenance_refs=tuple(ref.ref for ref in evidence_refs),
        evidence_refs=evidence_refs,
        redaction_posture=contract_pin.redaction_posture,
        metadata={"source_owner": contract_pin.source_owner},
    )


def _source_bundle_blockers(
    submission: Mapping[str, Any],
) -> tuple[OutsideAgentBlocker, ...]:
    for record in submission.get("evidence_refs", ()):
        if not isinstance(record, Mapping):
            continue
        expected = record.get("bundle_manifest_sha256")
        for source_bundle in record.get("source_bundle_refs", ()):
            if isinstance(source_bundle, Mapping) and source_bundle.get(
                "bundle_manifest_sha256"
            ) != expected:
                return (
                    OutsideAgentBlocker(
                        "source_bundle_mismatch",
                        "source bundle manifest digest does not match evidence reference",
                        ref="/evidence_refs",
                    ),
                )
    return ()


def _project_evidence_refs(
    submission: Mapping[str, Any],
) -> tuple[OutsideAgentEvidenceRef, ...]:
    from .outside_agent_provenance import normalize_outside_agent_ref

    projected: list[OutsideAgentEvidenceRef] = []
    records = submission.get("evidence_refs", ())
    if not isinstance(records, list):
        return ()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        raw_ref = record.get("repo_relative_path", record.get("ref"))
        raw_digest = record.get("sha256", record.get("digest"))
        try:
            ref = normalize_outside_agent_ref(raw_ref)
        except ValueError:
            continue
        digest = _normalized_digest(raw_digest)
        if digest is not None:
            projected.append(OutsideAgentEvidenceRef(ref=ref, digest=digest))
    provenance = submission.get("provenance_refs", ())
    if isinstance(provenance, list):
        for record in provenance:
            if not isinstance(record, Mapping):
                continue
            try:
                ref = normalize_outside_agent_ref(record.get("ref"))
            except ValueError:
                continue
            digest = _normalized_digest(record.get("digest"))
            if digest is not None:
                projected.append(OutsideAgentEvidenceRef(ref=ref, digest=digest))
    return tuple(projected)


def _normalized_digest(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    digest = value.removeprefix("sha256:").lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    return digest


def _digest_mapping(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "OutsideAgentBlocker",
    "OutsideAgentConformanceVerdict",
    "OutsideAgentEvidenceRef",
    "OutsideAgentSubmissionKind",
    "OutsideAgentVerdictStatus",
    "validate_outside_agent_submission",
]
