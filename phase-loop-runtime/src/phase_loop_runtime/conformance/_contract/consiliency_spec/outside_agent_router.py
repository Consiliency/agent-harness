"""Reference intake router for the outside-agent contract.

This module is the **normative executable oracle** for
`outside_agent_route_verdict.v0.1`. Given an outside-agent submission it returns
the route verdict that a conforming intake implementation MUST produce.

Scope boundary (unchanged from `docs/outside-agent-contract.md`): this is intake
routing only. It never grants merge acceptance, Portal projection state, or any
downstream authority — `acceptance_truth_owner` stays `governed_pipeline`.

It exists because the conformance corpus declares an `expected_verdict` and an
`expected_blocker_class` per vector, and until now nothing derived those values:
the corpus could only be checked for *vocabulary*, so a wrong verdict was
unobservable. A conformance runtime that cannot fail is not a fence.

`jsonschema` is imported lazily, so importing `consiliency_spec` stays
dependency-free; install the `outside-agent` extra to use the router.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUBMISSION_SCHEMA_TARGET = "outside_agent_submission.v0.1"
VERDICT_SCHEMA_TARGET = "outside_agent_route_verdict.v0.1"

#: Valid submissions route by kind. Every entry is a non-accepting intake route.
KIND_ROUTES = {
    "work_request": "roadmap_intake",
    "implementation_submission": "review_candidate",
    "ambiguity_report": "needs_clarification",
}

_REJECT = "reject"


def _schema_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "schemas"


def _load_schema(filename: str) -> dict[str, Any]:
    source = _schema_dir() / filename
    if source.exists():
        return json.loads(source.read_text(encoding="utf-8"))
    from . import load_json  # published-wheel fallback via _data/

    return load_json(f"schemas/{filename}")


def _validator(filename: str):
    from jsonschema.validators import Draft202012Validator

    return Draft202012Validator(_load_schema(filename))


def _classify(error) -> str:
    """Map one schema error to a blocker class. Deterministic, total.

    The split is by *what the failure means*, not by which keyword tripped:
    absence of required evidence is missing information; malformed or
    out-of-bounds evidence content is an unsafe reference; anything the
    contract simply has no rule for is a policy gap.
    """
    path = list(error.absolute_path)
    top = path[0] if path else None

    if top == "evidence_refs":
        # Absent evidence (missing field, or an empty array) is under-specified,
        # not dangerous. Malformed evidence content is dangerous.
        if error.validator in ("required", "minItems"):
            return "missing_information"
        return "unsafe_evidence_reference"

    if top == "submission_kind":
        return "unsupported_submission_kind"

    if error.validator == "required":
        return "missing_information"

    return "policy_gap"


def _semantic_blockers(payload: dict[str, Any]) -> list[str]:
    """Cross-field rules JSON Schema cannot express.

    A source bundle whose manifest digest disagrees with the evidence ref that
    carries it is an unsafe reference: the two disagree about what was hashed.
    """
    blockers: list[str] = []
    for evidence_ref in payload.get("evidence_refs", []) or []:
        if not isinstance(evidence_ref, dict):
            continue
        top_level_digest = evidence_ref.get("bundle_manifest_sha256")
        for source_bundle in evidence_ref.get("source_bundle_refs", []) or []:
            if not isinstance(source_bundle, dict):
                continue
            if source_bundle.get("bundle_manifest_sha256") != top_level_digest:
                blockers.append("bundle manifest digest mismatch")
    return blockers


def _safe_summary(error) -> str:
    """Describe a validation failure WITHOUT echoing the submitted value.

    `jsonschema` messages embed the offending value (`'sk-live-…' does not
    match …`) and, for `additionalProperties`, the offending *property name*.
    Putting that in a verdict would launder submitted content into a document
    that is serialized and passed downstream — the contract is metadata-only
    precisely so that cannot happen.

    Structural validation and safety redaction stay separate mechanisms here:
    the location and the violated keyword are enough to debug a rejection, and
    neither is attacker-controlled content.
    """
    location = "/".join(str(part) for part in error.absolute_path) or "<root>"
    keyword = error.validator or "unknown"
    return f"{location}: failed constraint {keyword}"


def _reject(blocker_class: str, summary: str) -> dict[str, Any]:
    return {
        "verdict_schema_version": VERDICT_SCHEMA_TARGET,
        "route": _REJECT,
        "claim_posture": "claims_only",
        "acceptance_truth_owner": "governed_pipeline",
        "blocker": {
            "class": blocker_class,
            "summary": summary,
            "human_required": blocker_class in ("policy_gap", "ambiguous_request"),
        },
    }


def route_submission(payload: Any) -> dict[str, Any]:
    """Derive the route verdict for an outside-agent submission.

    Returns a document valid against `outside-agent-route-verdict.schema.json`.
    Fails closed: anything not provably routable rejects with a blocker.
    """
    if not isinstance(payload, dict):
        return _reject("missing_information", "submission must be a JSON object")

    errors = sorted(
        _validator("outside-agent-submission.schema.json").iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.validator or ""),
    )
    if errors:
        first = errors[0]
        return _reject(_classify(first), _safe_summary(first))

    semantic = _semantic_blockers(payload)
    if semantic:
        return _reject("unsafe_evidence_reference", semantic[0])

    route = KIND_ROUTES.get(payload.get("submission_kind"))
    if route is None:
        # Unreachable while the schema enum and KIND_ROUTES agree; kept so that
        # widening the enum without widening the router fails closed instead of
        # silently routing to a default.
        return _reject("unsupported_submission_kind", "no route for submission kind")

    return {
        "verdict_schema_version": VERDICT_SCHEMA_TARGET,
        "route": route,
        "claim_posture": "claims_only",
        "acceptance_truth_owner": "governed_pipeline",
    }


def route_verdict_document(payload: Any) -> dict[str, Any]:
    """Verdict for a submitted *route verdict* document.

    Outside agents may propose a verdict; a proposal that is not a
    representable intake route (for example `accepted_for_merge`, which belongs
    to governed-pipeline) is rejected as a policy gap rather than honoured.
    """
    if not isinstance(payload, dict):
        return _reject("missing_information", "verdict must be a JSON object")

    errors = sorted(
        _validator("outside-agent-route-verdict.schema.json").iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.validator or ""),
    )
    if errors:
        return _reject("policy_gap", _safe_summary(errors[0]))
    return payload


def route(payload: Any, schema_target: str = SUBMISSION_SCHEMA_TARGET) -> dict[str, Any]:
    """Route `payload` against the named schema target."""
    if schema_target == VERDICT_SCHEMA_TARGET:
        return route_verdict_document(payload)
    if schema_target != SUBMISSION_SCHEMA_TARGET:
        return _reject("policy_gap", "unknown schema target")
    return route_submission(payload)


def blocker_class_of(verdict: dict[str, Any]) -> str:
    """`none` when the verdict carries no blocker — the corpus's vocabulary."""
    blocker = verdict.get("blocker")
    if not isinstance(blocker, dict):
        return "none"
    return blocker.get("class", "none")


__all__ = [
    "KIND_ROUTES",
    "SUBMISSION_SCHEMA_TARGET",
    "VERDICT_SCHEMA_TARGET",
    "blocker_class_of",
    "route",
    "route_submission",
    "route_verdict_document",
]
