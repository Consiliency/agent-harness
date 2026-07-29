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
    """Validate an outside-agent submission against the packaged contract.

    Mirrors Consiliency/spec's reference checker for STRUCTURE: JSON-Schema
    validation against the packaged ``outside_agent_submission.v0.1`` schema, plus
    one cross-field semantic check (source-bundle digest agreement) the schema
    cannot express.

    Redaction is a SEPARATE, independent safety pass run after schema validation
    — not a dialect concern. The JSON Schema constrains *shape* (unknown fields,
    path patterns, digest presence), but it cannot see a secret-shaped value
    sitting inside a schema-valid free-text field such as ``summary``. The
    metadata-only guarantee this repo publishes (``redaction_posture`` and
    docs/outside-agent-conformance.md) is backed by ``assert_outside_agent_metadata_only``
    here; without it, ``redaction_posture="metadata_only"`` would assert a property
    nothing checks (agent-harness#371 round 2).
    """
    from .outside_agent_redaction import assert_outside_agent_metadata_only
    from .outside_agent_schema import validate_outside_agent_submission_schema

    input_digest = _digest_mapping(submission)
    schema_result = validate_outside_agent_submission_schema(
        submission, contract_pin=contract_pin
    )
    semantic_blockers = _semantic_blockers(submission)
    # Independent metadata-only enforcement over the RAW submission (not a verdict
    # projection): reaches free-text fields (summary, goal, change_summary,
    # ambiguity_summary, questions[]) the schema treats as opaque strings.
    redaction_blockers = assert_outside_agent_metadata_only(submission)

    blockers = schema_result.blockers + semantic_blockers + redaction_blockers
    status = (
        OutsideAgentVerdictStatus.BLOCKED
        if blockers
        else OutsideAgentVerdictStatus.PASS
    )

    evidence_refs = _extract_evidence_refs(submission)
    provenance_refs = tuple(ref.ref for ref in evidence_refs)
    return OutsideAgentConformanceVerdict(
        verdict_schema_version=contract_pin.verdict_schema_version,
        submission_kind=schema_result.submission_kind,
        status=status,
        blockers=blockers,
        contract_pin=contract_pin,
        input_digest=input_digest,
        provenance_refs=provenance_refs,
        # Honest only because `redaction_blockers` above actually ran: a secret in a
        # schema-valid field flips this verdict to BLOCKED rather than passing while
        # still claiming `metadata_only`.
        evidence_refs=evidence_refs,
        redaction_posture=contract_pin.redaction_posture,
        metadata={"source_owner": contract_pin.source_owner},
    )


def _semantic_blockers(
    submission: Mapping[str, Any],
) -> tuple[OutsideAgentBlocker, ...]:
    """Cross-field checks the JSON Schema cannot express.

    ``source_bundle_mismatch``: an evidence ref's top-level
    ``bundle_manifest_sha256`` must agree with every one of its
    ``source_bundle_refs[].bundle_manifest_sha256``. Both sides are valid sha256
    hex (so the schema accepts them); their DISAGREEMENT is a semantic defect.
    """
    if not isinstance(submission, Mapping):
        return ()
    blockers: list[OutsideAgentBlocker] = []
    for index, evidence_ref in enumerate(submission.get("evidence_refs", []) or []):
        if not isinstance(evidence_ref, Mapping):
            continue
        top_digest = evidence_ref.get("bundle_manifest_sha256")
        for bundle_index, source_bundle in enumerate(
            evidence_ref.get("source_bundle_refs", []) or []
        ):
            if not isinstance(source_bundle, Mapping):
                continue
            if source_bundle.get("bundle_manifest_sha256") != top_digest:
                blockers.append(
                    OutsideAgentBlocker(
                        "source_bundle_mismatch",
                        "evidence ref bundle manifest digest disagrees with its "
                        "source bundle reference",
                        ref=(
                            f"evidence_refs.{index}.source_bundle_refs."
                            f"{bundle_index}.bundle_manifest_sha256"
                        ),
                    )
                )
    return tuple(blockers)


def _extract_evidence_refs(
    submission: Mapping[str, Any],
) -> tuple[OutsideAgentEvidenceRef, ...]:
    """Surface canonical evidence refs as verdict metadata (best-effort).

    Paths are re-normalized through ``normalize_outside_agent_ref`` and any that do
    not resolve to a safe repo-relative path (absolute, ``..`` traversal, scheme)
    are OMITTED rather than echoed. On a schema-valid submission the schema's
    ``repo_relative_path`` pattern already guarantees safety so nothing is dropped;
    this only matters on a BLOCKED submission, where we refuse to reflect an unsafe
    path back into output (grok, agent-harness#371 round 2).
    """
    from .outside_agent_provenance import normalize_outside_agent_ref

    if not isinstance(submission, Mapping):
        return ()
    refs: list[OutsideAgentEvidenceRef] = []
    for evidence_ref in submission.get("evidence_refs", []) or []:
        if not isinstance(evidence_ref, Mapping):
            continue
        path = evidence_ref.get("repo_relative_path")
        digest = evidence_ref.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            continue
        try:
            safe_path = normalize_outside_agent_ref(path)
        except ValueError:
            continue
        refs.append(
            OutsideAgentEvidenceRef(
                ref=safe_path,
                digest=digest,
                kind=str(evidence_ref.get("source_role", "metadata")),
            )
        )
    return tuple(refs)


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
