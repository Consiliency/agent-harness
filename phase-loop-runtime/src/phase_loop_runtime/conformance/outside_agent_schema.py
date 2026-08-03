"""Schema validation for outside-agent submissions against the packaged contract.

The authority is the vendored Consiliency/spec JSON Schema
(``_contract/schemas/outside-agent-submission.schema.json`` and the route-verdict
schema), validated with ``jsonschema`` Draft 2020-12 — the SAME model spec's own
reference checker uses. The schema file is the single source of truth: we do not
re-encode ``additionalProperties``/``required``/patterns in Python. Hand-mirroring
the schema is exactly how agent-harness#371's dialect divergence was born.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Mapping

from jsonschema.validators import Draft202012Validator

from .outside_agent_core import OutsideAgentBlocker, OutsideAgentSubmissionKind
from .outside_agent_pin import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    OutsideAgentContractPin,
)

_SUBMISSION_SCHEMA_NAME = "outside-agent-submission.schema.json"
_ROUTE_VERDICT_SCHEMA_NAME = "outside-agent-route-verdict.schema.json"


def _load_schema(name: str) -> dict[str, Any]:
    schema_bytes = (
        resources.files("phase_loop_runtime.conformance")
        / "_contract"
        / "schemas"
        / name
    ).read_bytes()
    return json.loads(schema_bytes)


@lru_cache(maxsize=None)
def _submission_validator() -> Draft202012Validator:
    schema = _load_schema(_SUBMISSION_SCHEMA_NAME)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@lru_cache(maxsize=None)
def _route_verdict_validator() -> Draft202012Validator:
    schema = _load_schema(_ROUTE_VERDICT_SCHEMA_NAME)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@dataclass(frozen=True)
class OutsideAgentSchemaValidation:
    submission_kind: OutsideAgentSubmissionKind | None
    blockers: tuple[OutsideAgentBlocker, ...]


def _ref_for_error(error: Any) -> str:
    """Repo-relative-ish JSON path for a jsonschema error (``$`` -> root)."""
    json_path = getattr(error, "json_path", "$")
    if json_path in ("$", ""):
        return "$"
    return json_path[2:] if json_path.startswith("$.") else json_path


# Keywords whose failing schema value (``error.validator_value``) is a compact,
# SCHEMA-DERIVED expectation safe to echo. It is never instance data — that lives
# in ``error.instance`` / ``error.message``, which we must not serialize because a
# secret-shaped submitted value would ride out verbatim (agent-harness#371 round 2).
_SCHEMA_KEYWORD_EXPECTATION = frozenset(
    {
        "type",
        "enum",
        "const",
        "pattern",
        "format",
        "required",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "uniqueItems",
    }
)


def _compact_schema_value(value: Any, *, limit: int = 160) -> str:
    """Render a schema-derived keyword value compactly and boundedly."""
    try:
        rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        rendered = repr(value)
    if len(rendered) > limit:
        rendered = rendered[:limit] + "..."
    return rendered


def _safe_schema_message(error: Any) -> str:
    """Sanitized blocker message: the failing keyword and its SCHEMA expectation.

    Built only from ``error.validator`` (the keyword) and ``error.validator_value``
    (schema-derived). It NEVER reads ``error.message`` or ``error.instance``, so a
    secret carried in a schema-invalid submitted field cannot echo into output.
    The default branch emits the keyword alone — it must not fall through to
    ``error.message``.
    """
    keyword = getattr(error, "validator", None)
    keyword = str(keyword) if keyword is not None else "schema"
    if keyword in _SCHEMA_KEYWORD_EXPECTATION:
        expectation = _compact_schema_value(getattr(error, "validator_value", None))
        return (
            f"value at this location does not satisfy schema keyword "
            f"'{keyword}' (expected: {expectation})"
        )
    return f"value at this location does not satisfy schema keyword '{keyword}'"


def _schema_blockers(
    validator: Draft202012Validator, document: Any
) -> tuple[OutsideAgentBlocker, ...]:
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    return tuple(
        OutsideAgentBlocker(
            "schema_validation_failed",
            _safe_schema_message(error),
            ref=_ref_for_error(error),
        )
        for error in errors
    )


def validate_outside_agent_submission_schema(
    submission: Mapping[str, Any],
    *,
    contract_pin: OutsideAgentContractPin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
) -> OutsideAgentSchemaValidation:
    del contract_pin  # schema const pins the version; kept for signature stability
    blockers = _schema_blockers(_submission_validator(), submission)
    submission_kind = _parse_submission_kind(
        submission.get("submission_kind") if isinstance(submission, Mapping) else None
    )
    return OutsideAgentSchemaValidation(submission_kind=submission_kind, blockers=blockers)


def validate_outside_agent_route_verdict(
    document: Mapping[str, Any],
) -> tuple[OutsideAgentBlocker, ...]:
    """Validate an outside-agent route-verdict document against the packaged schema."""
    return _schema_blockers(_route_verdict_validator(), document)


def _parse_submission_kind(value: Any) -> OutsideAgentSubmissionKind | None:
    try:
        return OutsideAgentSubmissionKind(value)
    except ValueError:
        return None


__all__ = [
    "OutsideAgentSchemaValidation",
    "validate_outside_agent_route_verdict",
    "validate_outside_agent_submission_schema",
]
