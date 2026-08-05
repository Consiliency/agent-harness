"""Pinned Draft 2020-12 validation for outside-agent contract inputs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping

from .outside_agent_core import (
    OutsideAgentBlocker,
    OutsideAgentSubmissionKind,
    OutsideAgentVerdictStatus,
)
from .outside_agent_pin import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    OutsideAgentContractPin,
)


CONFORM_V10_CAPABILITY_MARKER = "spec@v0.2.1:b862f977897a7b87c4419680a3e83735d4ff07b0"

_SUBMISSION_TARGET = "outside_agent_submission.v0.1"
_ROUTE_TARGET = "outside_agent_route_verdict.v0.1"
_SCHEMA_PATHS = {
    _SUBMISSION_TARGET: "schemas/outside-agent-submission.schema.json",
    _ROUTE_TARGET: "schemas/outside-agent-route-verdict.schema.json",
}


@dataclass(frozen=True)
class OutsideAgentSchemaValidation:
    submission_kind: OutsideAgentSubmissionKind | None
    blockers: tuple[OutsideAgentBlocker, ...]
    dispatch_observation: Mapping[str, object] | None = None


@dataclass(frozen=True)
class OutsideAgentRouteVerdictValidation:
    status: OutsideAgentVerdictStatus
    blockers: tuple[OutsideAgentBlocker, ...]
    dispatch_observation: Mapping[str, object]


def validate_outside_agent_submission_schema(
    submission: Mapping[str, Any],
    *,
    contract_pin: OutsideAgentContractPin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
) -> OutsideAgentSchemaValidation:
    """Validate only the pinned submission schema, never a hand-written dialect."""
    del contract_pin
    blockers, observation = _validate_pinned_schema(submission, _SUBMISSION_TARGET)
    return OutsideAgentSchemaValidation(
        submission_kind=_parse_submission_kind(submission.get("submission_kind")),
        blockers=blockers,
        dispatch_observation=observation,
    )


def validate_outside_agent_route_verdict_schema(
    payload: Mapping[str, Any],
    *,
    schema_target: str,
) -> OutsideAgentRouteVerdictValidation:
    """Validate a route-verdict only after explicit manifest-target dispatch."""
    blockers, observation = _validate_pinned_schema(payload, schema_target)
    return OutsideAgentRouteVerdictValidation(
        status=(
            OutsideAgentVerdictStatus.BLOCKED
            if blockers
            else OutsideAgentVerdictStatus.PASS
        ),
        blockers=blockers,
        dispatch_observation=observation,
    )


def _validate_pinned_schema(
    payload: Mapping[str, Any], schema_target: str
) -> tuple[tuple[OutsideAgentBlocker, ...], Mapping[str, object]]:
    from jsonschema.validators import Draft202012Validator

    schema_path = _SCHEMA_PATHS.get(schema_target)
    if schema_path is None:
        return (
            (
                OutsideAgentBlocker(
                    "schema_validation_failed",
                    "submitted value is not permitted",
                    ref="/",
                ),
            ),
            {
                "entered": True,
                "schema_target": schema_target,
                "selected_schema_id": None,
                "selected_schema_sha256": None,
                "validation_error_pointer": "/",
                "validation_error_keyword": "schema_target",
            },
        )

    schema_bytes = (
        resources.files("phase_loop_runtime.conformance")
        .joinpath("_contract")
        .joinpath(schema_path)
        .read_bytes()
    )
    schema = json.loads(schema_bytes)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: (list(error.absolute_path), str(error.validator)),
    )
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
    pointer = _pointer(error.absolute_path)
    keyword = str(error.validator)
    observation["validation_error_pointer"] = pointer
    observation["validation_error_keyword"] = keyword
    return (_bounded_blocker(error, pointer, schema_target),), observation


def _bounded_blocker(
    error: Any, pointer: str, schema_target: str
) -> OutsideAgentBlocker:
    keyword = str(error.validator)
    value = error.instance
    if (
        pointer == "/submission_schema_version"
        and value == "outside_agent_submission.v9"
    ):
        return OutsideAgentBlocker(
            "unsupported_schema_version",
            "outside-agent submission schema version is not pinned",
            ref=pointer,
        )
    if pointer == "/submission_kind" and value in {
        "freeform_patch",
        "unsupported_kind",
    }:
        return OutsideAgentBlocker(
            "unsupported_submission_kind",
            "outside-agent submission kind is not supported",
            ref=pointer,
        )
    if keyword == "additionalProperties":
        if (
            schema_target == _SUBMISSION_TARGET
            and pointer == "/"
            and isinstance(value, Mapping)
            and "summary" not in value
        ):
            return OutsideAgentBlocker(
                "schema_validation_failed",
                "required field is missing",
                ref="/summary",
            )
        code = (
            "unknown_field"
            if "unexpected_field" in str(error.message)
            else "schema_validation_failed"
        )
        return OutsideAgentBlocker(code, "unknown field is not permitted", ref="/<unknown>")
    if keyword == "required":
        required = next(
            (
                field
                for field in error.validator_value
                if isinstance(field, str) and field not in value
            ),
            "<required>",
        )
        return OutsideAgentBlocker(
            "schema_validation_failed",
            "required field is missing",
            ref=f"{pointer.rstrip('/')}/{required}",
        )
    if pointer.endswith("/repo_relative_path"):
        return OutsideAgentBlocker(
            "schema_validation_failed",
            "repository-relative path is invalid",
            ref=pointer,
        )
    return OutsideAgentBlocker(
        "schema_validation_failed", "submitted value is not permitted", ref="/"
    )


def _pointer(parts: object) -> str:
    values = tuple(str(part) for part in parts)
    return "/" + "/".join(values) if values else "/"


def _parse_submission_kind(value: Any) -> OutsideAgentSubmissionKind | None:
    try:
        return OutsideAgentSubmissionKind(value)
    except ValueError:
        return None


__all__ = [
    "CONFORM_V10_CAPABILITY_MARKER",
    "OutsideAgentRouteVerdictValidation",
    "OutsideAgentSchemaValidation",
    "validate_outside_agent_route_verdict_schema",
    "validate_outside_agent_submission_schema",
]
