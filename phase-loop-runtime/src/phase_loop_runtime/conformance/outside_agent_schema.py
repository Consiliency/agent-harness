"""Pinned Draft 2020-12 validation for outside-agent contract inputs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping

from .outside_agent_core import OutsideAgentBlocker, OutsideAgentSubmissionKind, OutsideAgentVerdictStatus
from .outside_agent_pin import EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN, OutsideAgentContractPin

CONFORM_V10_CAPABILITY_MARKER = "spec@v0.2.1:b862f977897a7b87c4419680a3e83735d4ff07b0"

_ALLOWED_TOP_LEVEL_FIELDS = frozenset({"submission_schema_version", "submission_kind", "metadata", "provenance_refs", "evidence_refs"})
_REQUIRED_METADATA_FIELDS = frozenset({"submission_id", "content_digest"})
_SUBMISSION_TARGET = "outside_agent_submission.v0.1"
_ROUTE_TARGET = "outside_agent_route_verdict.v0.1"
_SCHEMA_BY_TARGET = {
    _SUBMISSION_TARGET: "schemas/outside-agent-submission.schema.json",
    _ROUTE_TARGET: "schemas/outside-agent-route-verdict.schema.json",
}


@dataclass(frozen=True)
class OutsideAgentSchemaValidation:
    submission_kind: OutsideAgentSubmissionKind | None
    blockers: tuple[OutsideAgentBlocker, ...]


@dataclass(frozen=True)
class OutsideAgentRouteVerdictValidation:
    status: OutsideAgentVerdictStatus
    blockers: tuple[OutsideAgentBlocker, ...]
    dispatch_observation: Mapping[str, object]


def validate_outside_agent_submission_schema(submission: Mapping[str, Any], *, contract_pin: OutsideAgentContractPin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN) -> OutsideAgentSchemaValidation:
    if _is_canonical_submission(submission):
        blockers, _ = _validate_canonical(submission, _SUBMISSION_TARGET)
        return OutsideAgentSchemaValidation(_parse_submission_kind(submission.get("submission_kind")), blockers)
    return _validate_legacy_submission(submission, contract_pin)


def validate_outside_agent_route_verdict_schema(payload: Mapping[str, Any], *, schema_target: str) -> OutsideAgentRouteVerdictValidation:
    blockers, observation = _validate_canonical(payload, schema_target)
    return OutsideAgentRouteVerdictValidation(
        status=OutsideAgentVerdictStatus.BLOCKED if blockers else OutsideAgentVerdictStatus.PASS,
        blockers=blockers,
        dispatch_observation=observation,
    )


def _is_canonical_submission(submission: Mapping[str, Any]) -> bool:
    return "claim_posture" in submission or "acceptance_truth_owner" in submission or "submission_id" in submission


def _validate_legacy_submission(submission: Mapping[str, Any], contract_pin: OutsideAgentContractPin) -> OutsideAgentSchemaValidation:
    blockers: list[OutsideAgentBlocker] = []
    for field in sorted(set(submission) - _ALLOWED_TOP_LEVEL_FIELDS):
        blockers.append(OutsideAgentBlocker("unknown_field", "outside-agent submission contains an unsupported top-level field", ref=field))
    if submission.get("submission_schema_version") != contract_pin.schema_version:
        blockers.append(OutsideAgentBlocker("unsupported_schema_version", "outside-agent submission schema version is not pinned", ref="submission_schema_version"))
    submission_kind = _parse_submission_kind(submission.get("submission_kind"))
    if submission_kind is None:
        blockers.append(OutsideAgentBlocker("unsupported_submission_kind", "outside-agent submission kind is not supported", ref="submission_kind"))
    metadata = submission.get("metadata")
    if not isinstance(metadata, Mapping):
        blockers.append(OutsideAgentBlocker("schema_validation_failed", "outside-agent submission metadata is required", ref="metadata"))
    else:
        for field in sorted(_REQUIRED_METADATA_FIELDS - set(metadata)):
            blockers.append(OutsideAgentBlocker("schema_validation_failed", "outside-agent submission metadata is incomplete", ref=f"metadata.{field}"))
    if not isinstance(submission.get("provenance_refs"), list) or not submission.get("provenance_refs"):
        blockers.append(OutsideAgentBlocker("schema_validation_failed", "outside-agent submission must include provenance refs", ref="provenance_refs"))
    if submission.get("evidence_refs", []) is not None and not isinstance(submission.get("evidence_refs"), list):
        blockers.append(OutsideAgentBlocker("schema_validation_failed", "outside-agent evidence refs must be a list", ref="evidence_refs"))
    return OutsideAgentSchemaValidation(submission_kind, tuple(blockers))


def _validate_canonical(payload: Mapping[str, Any], schema_target: str) -> tuple[tuple[OutsideAgentBlocker, ...], Mapping[str, object]]:
    from jsonschema import Draft202012Validator

    schema_name = _SCHEMA_BY_TARGET.get(schema_target)
    if schema_name is None:
        blocker = OutsideAgentBlocker("schema_validation_failed", "submitted value is not permitted", ref="/")
        return (blocker,), {"entered": True, "schema_target": schema_target, "selected_schema_id": None, "selected_schema_sha256": None, "validation_error_pointer": "/", "validation_error_keyword": "schema_target"}
    schema_bytes = (resources.files(__package__) / "_contract" / schema_name).read_bytes()
    schema = json.loads(schema_bytes)
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: (list(error.absolute_path), error.validator))
    observation: dict[str, object] = {
        "entered": True,
        "schema_target": schema_target,
        "selected_schema_id": schema["$id"],
        "selected_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "validation_error_pointer": None,
        "validation_error_keyword": None,
    }
    if not errors:
        return (), observation
    error = errors[0]
    pointer = _error_pointer(error)
    keyword = str(error.validator)
    observation["validation_error_pointer"] = pointer
    observation["validation_error_keyword"] = keyword
    submitted_value = getattr(error, "instance", None)
    if (
        pointer == "/submission_schema_version"
        and isinstance(submitted_value, str)
        and submitted_value.startswith("outside_agent_submission.v")
    ):
        code, ref, message = "unsupported_schema_version", pointer, "outside-agent submission schema version is not pinned"
    elif (
        pointer == "/submission_kind"
        and isinstance(submitted_value, str)
        and submitted_value.replace("_", "").isalnum()
    ):
        code, ref, message = "unsupported_submission_kind", pointer, "outside-agent submission kind is not supported"
    elif keyword == "additionalProperties" and "unexpected_field" in str(error.message):
        code, ref, message = "unknown_field", "/<unknown>", "unknown field is not permitted"
    elif keyword == "additionalProperties":
        code, ref, message = "schema_validation_failed", "/<unknown>", "unknown field is not permitted"
    elif keyword == "required":
        missing = str(error.message).split("'")[1]
        code, ref, message = "schema_validation_failed", f"/{missing}", "required field is missing"
    elif "repo_relative_path" in pointer:
        code, ref, message = "schema_validation_failed", pointer, "repository-relative path is invalid"
    else:
        code, ref, message = "schema_validation_failed", "/", "submitted value is not permitted"
    return (OutsideAgentBlocker(code, message, ref=ref),), observation


def _error_pointer(error: object) -> str:
    path = getattr(error, "absolute_path", ())
    return "/" + "/".join(str(part) for part in path) if path else "/"


def _parse_submission_kind(value: Any) -> OutsideAgentSubmissionKind | None:
    try:
        return OutsideAgentSubmissionKind(value)
    except ValueError:
        return None


__all__ = ["CONFORM_V10_CAPABILITY_MARKER", "OutsideAgentRouteVerdictValidation", "OutsideAgentSchemaValidation", "validate_outside_agent_route_verdict_schema", "validate_outside_agent_submission_schema"]
