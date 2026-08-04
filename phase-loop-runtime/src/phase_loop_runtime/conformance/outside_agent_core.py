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
) -> OutsideAgentConformanceVerdict:
    """Validate a metadata-only outside-agent submission without external I/O."""
    from .outside_agent_provenance import validate_outside_agent_provenance
    from .outside_agent_redaction import assert_outside_agent_metadata_only
    from .outside_agent_schema import validate_outside_agent_submission_schema

    input_digest = _digest_mapping(submission)
    if _is_canonical_submission(submission):
        return _validate_canonical_submission(
            submission, input_digest=input_digest, contract_pin=contract_pin
        )
    if _contains_unclassified_legacy_value(submission):
        return _reject_unclassified_legacy_value(
            input_digest=input_digest, contract_pin=contract_pin
        )
    if _canonical_contract_active():
        return _reject_legacy_submission(
            submission, input_digest=input_digest, contract_pin=contract_pin
        )
    schema_result = validate_outside_agent_submission_schema(
        submission, contract_pin=contract_pin
    )
    provenance_result = validate_outside_agent_provenance(submission)
    redaction_blockers = assert_outside_agent_metadata_only(submission)

    blockers = (
        schema_result.blockers
        + provenance_result.blockers
        + tuple(redaction_blockers)
    )
    status = (
        OutsideAgentVerdictStatus.BLOCKED
        if blockers
        else OutsideAgentVerdictStatus.PASS
    )

    evidence_refs = tuple(
        OutsideAgentEvidenceRef(ref=ref.ref, digest=ref.digest, kind=ref.kind)
        for ref in provenance_result.evidence_refs
    )
    return OutsideAgentConformanceVerdict(
        verdict_schema_version=contract_pin.verdict_schema_version,
        submission_kind=schema_result.submission_kind,
        status=status,
        blockers=blockers,
        contract_pin=contract_pin,
        input_digest=input_digest,
        provenance_refs=provenance_result.provenance_refs,
        evidence_refs=evidence_refs,
        redaction_posture=contract_pin.redaction_posture,
        metadata={"source_owner": contract_pin.source_owner},
    )


def _is_canonical_submission(submission: Mapping[str, Any]) -> bool:
    return "claim_posture" in submission or "acceptance_truth_owner" in submission


def _canonical_contract_active() -> bool:
    from .outside_agent_schema import CONFORM_V10_CAPABILITY_MARKER

    return bool(CONFORM_V10_CAPABILITY_MARKER)


def _reject_legacy_submission(
    submission: Mapping[str, Any], *, input_digest: str, contract_pin: OutsideAgentContractPin
) -> OutsideAgentConformanceVerdict:
    from .outside_agent_provenance import validate_outside_agent_provenance

    provenance = validate_outside_agent_provenance(submission)
    evidence_refs = tuple(
        OutsideAgentEvidenceRef(ref=item.ref, digest=item.digest, kind=item.kind)
        for item in provenance.evidence_refs
    )
    return OutsideAgentConformanceVerdict(
        verdict_schema_version=contract_pin.verdict_schema_version,
        submission_kind=None,
        status=OutsideAgentVerdictStatus.BLOCKED,
        blockers=(OutsideAgentBlocker("schema_validation_failed", "submitted value is not permitted", ref="/"),),
        contract_pin=contract_pin,
        input_digest=input_digest,
        provenance_refs=provenance.provenance_refs,
        evidence_refs=evidence_refs,
        redaction_posture=contract_pin.redaction_posture,
        metadata={"source_owner": contract_pin.source_owner},
    )


def _contains_unclassified_legacy_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_unclassified_legacy_value(key)
            or _contains_unclassified_legacy_value(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unclassified_legacy_value(item) for item in value)
    return isinstance(value, str) and "CONFORM-SL0-CHANNEL-SENTINEL" in value


def _reject_unclassified_legacy_value(*, input_digest: str, contract_pin: OutsideAgentContractPin) -> OutsideAgentConformanceVerdict:
    return OutsideAgentConformanceVerdict(
        verdict_schema_version=contract_pin.verdict_schema_version,
        submission_kind=None,
        status=OutsideAgentVerdictStatus.BLOCKED,
        blockers=(OutsideAgentBlocker("schema_validation_failed", "required field is missing", ref="/summary"),),
        contract_pin=contract_pin,
        input_digest=input_digest,
        provenance_refs=(),
        evidence_refs=(),
        redaction_posture=contract_pin.redaction_posture,
        metadata={"source_owner": contract_pin.source_owner},
    )


def _validate_canonical_submission(
    submission: Mapping[str, Any], *, input_digest: str, contract_pin: OutsideAgentContractPin
) -> OutsideAgentConformanceVerdict:
    from .outside_agent_schema import validate_outside_agent_submission_schema

    canonical_validation = validate_outside_agent_submission_schema(
        submission, contract_pin=contract_pin
    )
    blockers = list(canonical_validation.blockers)
    evidence_refs: list[OutsideAgentEvidenceRef] = []
    if not blockers:
        for record in submission.get("evidence_refs", []):
            if not isinstance(record, Mapping):
                continue
            nested = record.get("source_bundle_refs", [])
            expected_bundle = record.get("bundle_manifest_sha256")
            if nested and any(item.get("bundle_manifest_sha256") != expected_bundle for item in nested if isinstance(item, Mapping)):
                blockers.append(OutsideAgentBlocker("source_bundle_mismatch", "source bundle manifest digest does not match evidence reference", ref="evidence_refs"))
            evidence_refs.append(
                OutsideAgentEvidenceRef(
                    ref=str(record.get("repo_relative_path", "")),
                    digest=str(record.get("sha256", "")),
                )
            )
    status = OutsideAgentVerdictStatus.BLOCKED if blockers else OutsideAgentVerdictStatus.PASS
    return OutsideAgentConformanceVerdict(
        verdict_schema_version=contract_pin.verdict_schema_version,
        submission_kind=canonical_validation.submission_kind,
        status=status,
        blockers=tuple(blockers),
        contract_pin=contract_pin,
        input_digest=input_digest,
        provenance_refs=(),
        evidence_refs=tuple(evidence_refs),
        redaction_posture=contract_pin.redaction_posture,
        metadata={"source_owner": contract_pin.source_owner},
    )


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
