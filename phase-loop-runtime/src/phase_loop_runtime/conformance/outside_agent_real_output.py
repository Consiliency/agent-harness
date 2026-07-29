"""JSON serialization for governed-pipeline outside-agent validation verdicts."""
from __future__ import annotations

import hashlib
from typing import Any

from .outside_agent_pin import OutsideAgentContractPin
from .outside_agent_real import OutsideAgentValidationExitCode, OutsideAgentValidationVerdict
from .outside_agent_redaction import assert_outside_agent_metadata_only


def serialize_outside_agent_validation_verdict(
    validation: OutsideAgentValidationVerdict,
) -> dict[str, Any]:
    verdict = validation.verdict
    payload = {
        "gate_id": "real_conformance_gate.v0.1",
        "authority": validation.authority,
        "validator_version": validation.validator_version,
        "command": "outside-agent-validate",
        "verdict_schema_version": verdict.verdict_schema_version,
        "contract_pin": _contract_pin_fields(verdict.contract_pin),
        "vector_manifest_hash": verdict.contract_pin.vector_manifest_hash,
        "input_digest": verdict.input_digest,
        "submitted_refs": [ref.ref for ref in validation.submitted_refs],
        "submission_kind": verdict.submission_kind.value if verdict.submission_kind else None,
        "status": verdict.status.value,
        "blockers": [
            {"code": blocker.code, "message": blocker.message, "ref": blocker.ref}
            for blocker in verdict.blockers
        ],
        "evidence_refs": [
            {"ref": ref.ref, "digest": ref.digest, "kind": ref.kind}
            for ref in verdict.evidence_refs
        ],
        "redaction_posture": verdict.redaction_posture,
        "vectors_executed": validation.vectors_executed,
        "exit_code": int(validation.exit_code),
    }

    # Serialization-boundary safety invariant (Option C, agent-harness#371 round 3).
    # This function is the SOLE sink for validation output, so "the emitted document
    # carries no submitter-supplied secret-shaped value" is provable HERE as a
    # property of one choke point — independent of how many channels feed it, and not
    # dependent on a channel enumeration ever being complete. It reuses the SAME
    # metadata-only predicate the construction path uses (one detector, two call
    # sites — a second detector that could disagree would itself be a defect). In
    # correct operation the upstream verdict-level scans block first and this never
    # fires; if it does, a gate was bypassed. Fail CLOSED with a minimal blocked
    # document — NOT raise (raising the serializer is an operational fail-open,
    # Blocker 1's lesson), and NOT emit the leaking payload.
    if assert_outside_agent_metadata_only(payload):
        return _secret_free_blocked_document(validation)
    return payload


def _contract_pin_fields(contract_pin: OutsideAgentContractPin) -> dict[str, Any]:
    return {
        "schema_version": contract_pin.schema_version,
        "verdict_schema_version": contract_pin.verdict_schema_version,
        "contract_package": contract_pin.contract_package,
        "contract_version": contract_pin.contract_version,
        "contract_git_sha": contract_pin.contract_git_sha,
        "vector_manifest_name": contract_pin.vector_manifest_name,
        "vector_manifest_hash": contract_pin.vector_manifest_hash,
        "source_owner": contract_pin.source_owner,
        "redaction_posture": contract_pin.redaction_posture,
    }


def _secret_free_blocked_document(
    validation: OutsideAgentValidationVerdict,
) -> dict[str, Any]:
    """Fail-closed replacement emitted when the boundary sweep trips.

    Built ONLY from constants and fields that are provably NOT submitter-derived:
    the frozen contract pin (ours), the validator version (``__version__``), and the
    input_digest (a SHA-256 hex string — its alphabet [0-9a-f] cannot contain any
    secret marker, a submitted ref, or a case id). Every submitter-projection field
    is emptied and the blocker text is constant, so this document cannot itself echo
    the content that tripped the boundary (agent-harness#371 round 3).
    """
    contract_pin = validation.verdict.contract_pin
    return {
        "gate_id": "real_conformance_gate.v0.1",
        "authority": "governed_pipeline_validator",
        "validator_version": validation.validator_version,
        "command": "outside-agent-validate",
        "verdict_schema_version": contract_pin.verdict_schema_version,
        "contract_pin": _contract_pin_fields(contract_pin),
        "vector_manifest_hash": contract_pin.vector_manifest_hash,
        "input_digest": validation.verdict.input_digest,
        "submitted_refs": [],
        "submission_kind": None,
        "status": "blocked",
        "blockers": [
            {
                "code": "secret_like_value_present",
                "message": (
                    "outside-agent validation output tripped the serialization-boundary "
                    "secret sweep; emitting a redacted fail-closed verdict"
                ),
                "ref": "$",
            }
        ],
        "evidence_refs": [],
        "redaction_posture": contract_pin.redaction_posture,
        "vectors_executed": False,
        "exit_code": int(OutsideAgentValidationExitCode.REDACTION_VIOLATION),
    }


def digest_outside_agent_validation_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "digest_outside_agent_validation_bytes",
    "serialize_outside_agent_validation_verdict",
]
