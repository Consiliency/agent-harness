"""Deterministic vector runner for the canonical outside-agent conformance corpus.

The manifest and vectors are the PACKAGED Consiliency/spec format
(``_contract/test-vectors/outside-agent/manifest.json``): each entry references a
vector FILE by ``path`` (not an inline submission) and declares a ``schema_target``
that selects the submission or route-verdict schema. Each vector is validated
through the same core the ``outside-agent-validate`` CLI uses, and its pass/reject
outcome is compared to the manifest's own ``expected_valid``.
"""
from __future__ import annotations

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
from .outside_agent_schema import validate_outside_agent_route_verdict

_VECTOR_MANIFEST_SCHEMA_VERSION = "outside_agent_vector_manifest.v0.1"
_SUBMISSION_TARGET = "outside_agent_submission.v0.1"
_ROUTE_VERDICT_TARGET = "outside_agent_route_verdict.v0.1"
_ALLOWED_TARGETS = frozenset({_SUBMISSION_TARGET, _ROUTE_VERDICT_TARGET})
_MANIFEST_RELPATH = "test-vectors/outside-agent/manifest.json"


@dataclass(frozen=True)
class OutsideAgentVectorResult:
    vector_name: str
    status: OutsideAgentVerdictStatus
    expected_status: OutsideAgentVerdictStatus | None
    matched: bool
    blockers: tuple[OutsideAgentBlocker, ...]
    evidence_refs: tuple[str, ...]


def _default_contract_root() -> Path:
    return Path(str(resources.files("phase_loop_runtime.conformance") / "_contract"))


def run_outside_agent_vectors(
    root: str | Path | None = None,
    *,
    manifest: Mapping[str, Any] | None = None,
    contract_pin: OutsideAgentContractPin = EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
) -> tuple[OutsideAgentVectorResult, ...]:
    """Run the canonical vector corpus rooted at ``root`` (packaged corpus default).

    ``manifest`` may override the on-disk manifest (used by fail-closed tests);
    vector ``path`` entries always resolve against ``root``.
    """
    contract_root = _default_contract_root() if root is None else Path(root)
    manifest_data = (
        manifest
        if manifest is not None
        else _load_json(contract_root / _MANIFEST_RELPATH)
    )

    manifest_blockers = _validate_manifest(manifest_data)
    if manifest_blockers:
        return (
            OutsideAgentVectorResult(
                vector_name="__manifest__",
                status=OutsideAgentVerdictStatus.BLOCKED,
                expected_status=None,
                matched=False,
                blockers=manifest_blockers,
                evidence_refs=(_MANIFEST_RELPATH,),
            ),
        )

    results: list[OutsideAgentVectorResult] = []
    for entry in manifest_data["vectors"]:
        payload = _load_json(contract_root / entry["path"])
        expected_status = (
            OutsideAgentVerdictStatus.PASS
            if entry["expected_valid"]
            else OutsideAgentVerdictStatus.BLOCKED
        )
        if entry["schema_target"] == _SUBMISSION_TARGET:
            verdict = validate_outside_agent_submission(payload, contract_pin=contract_pin)
            status = verdict.status
            blockers = verdict.blockers
            evidence_refs = tuple(ref.ref for ref in verdict.evidence_refs)
        else:
            blockers = validate_outside_agent_route_verdict(payload)
            status = (
                OutsideAgentVerdictStatus.BLOCKED
                if blockers
                else OutsideAgentVerdictStatus.PASS
            )
            evidence_refs = ()
        results.append(
            OutsideAgentVectorResult(
                vector_name=str(entry["case_id"]),
                status=status,
                expected_status=expected_status,
                matched=status == expected_status,
                blockers=blockers,
                evidence_refs=evidence_refs,
            )
        )
    return tuple(results)


def _validate_manifest(manifest: Mapping[str, Any]) -> tuple[OutsideAgentBlocker, ...]:
    if not isinstance(manifest, Mapping):
        return (
            OutsideAgentBlocker(
                "schema_validation_failed",
                "outside-agent vector manifest must be an object",
                ref="$",
            ),
        )
    blockers: list[OutsideAgentBlocker] = []
    if manifest.get("manifest_schema_version") != _VECTOR_MANIFEST_SCHEMA_VERSION:
        blockers.append(
            OutsideAgentBlocker(
                "unsupported_schema_version",
                "outside-agent vector manifest schema is not supported",
                ref="manifest_schema_version",
            )
        )

    vectors = manifest.get("vectors")
    if not isinstance(vectors, list) or not vectors:
        blockers.append(
            OutsideAgentBlocker(
                "schema_validation_failed",
                "outside-agent vector manifest must contain vectors",
                ref="vectors",
            )
        )
        return tuple(blockers)

    for index, entry in enumerate(vectors):
        if not isinstance(entry, Mapping):
            blockers.append(
                OutsideAgentBlocker(
                    "schema_validation_failed",
                    "outside-agent vector entry must be metadata",
                    ref=f"vectors.{index}",
                )
            )
            continue
        for field in ("case_id", "path", "schema_target", "expected_valid"):
            if field not in entry:
                blockers.append(
                    OutsideAgentBlocker(
                        "schema_validation_failed",
                        "outside-agent vector entry is incomplete",
                        ref=f"vectors.{index}.{field}",
                    )
                )
        if entry.get("schema_target") not in _ALLOWED_TARGETS:
            blockers.append(
                OutsideAgentBlocker(
                    "schema_validation_failed",
                    "outside-agent vector entry schema_target is unsupported",
                    ref=f"vectors.{index}.schema_target",
                )
            )
        if "expected_valid" in entry and not isinstance(entry["expected_valid"], bool):
            blockers.append(
                OutsideAgentBlocker(
                    "schema_validation_failed",
                    "outside-agent vector entry expected_valid must be a bool",
                    ref=f"vectors.{index}.expected_valid",
                )
            )
    return tuple(blockers)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["OutsideAgentVectorResult", "run_outside_agent_vectors"]
