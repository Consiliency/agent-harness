"""Acceptance-criterion evidence: the agent-harness side of spec's E(C)
``acceptance_evidence`` channel (agent-harness#1321, REPORT 3.2 Slice B).

A run binds human-asserted criterion->command links into ``verification.json``
(extension namespace ``phase_loop_runtime.acceptance_evidence``). The exporter
reads a sealed artifact and emits one seven-field record per linked criterion,
in the shape spec's ``validate_ec`` accepts (Consiliency/spec#250):

    criterion_logical_id, argv, exit_code, log_sha256,
    pipeline_mode, pipeline_engaged, authority

``log_sha256`` digests only the linked command's own bytes in
``verification.log``, so the record names the evidence for that command and
not the whole run.

Honest limit: exit 0 shows the command passed, not that it tests the
criterion. The link is a human assertion; this module records it and never
infers it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import verification_evidence

EXTENSION_NAMESPACE = "phase_loop_runtime.acceptance_evidence"
RECORD_SCHEMA = "acceptance_evidence_links.v1"

AUTHORITY_PRODUCER = "producer"
AUTHORITY_PIPELINE = "pipeline"


class AcceptanceEvidenceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def acceptance_authority(pipeline_mode: str, pipeline_engaged: bool) -> str:
    """Owner decision on agent-harness#1321 (2026-10-08): the pipeline owns
    acceptance truth under ``pipeline_required`` (even if engagement failed) or an
    engaged ``pipeline_optional`` run; otherwise the producer owns it, for that
    run only."""
    if pipeline_mode == "pipeline_required" or pipeline_engaged:
        return AUTHORITY_PIPELINE
    return AUTHORITY_PRODUCER


def bind_acceptance_evidence(
    artifact_path: Path,
    *,
    links: Sequence[Mapping[str, Any]],
    pipeline_mode: str,
    pipeline_engaged: bool,
) -> None:
    """Bind criterion->command links into a sealed ``verification.json``.

    ``links`` items are ``{"criterion_logical_id": <engine_join_id>,
    "command_index": <index into commands[]>}``. ``criterion_logical_id`` must be
    spec's ``engine_join_id`` for the criterion (``projection.desired_logical_id``),
    not the graph node's level-bearing logical_id."""
    artifact_path = Path(artifact_path)
    record = {
        "schema": RECORD_SCHEMA,
        "pipeline_mode": pipeline_mode,
        "pipeline_engaged": pipeline_engaged,
        "links": [dict(link) for link in links],
    }
    try:
        result = verification_evidence.load_verification_artifact(artifact_path)
        verification_evidence._validate_v3_extensions({EXTENSION_NAMESPACE: record})
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceEvidenceError(getattr(exc, "code", "malformed_artifact"), str(exc)) from exc
    _require_command_indexes(record["links"], len(result.commands))
    try:
        verification_evidence._bind_additional_extension(
            artifact_path, namespace=EXTENSION_NAMESPACE, record=record
        )
    except verification_evidence.VerificationArtifactContractError as exc:
        raise AcceptanceEvidenceError(exc.code, str(exc)) from exc


def export_acceptance_evidence(artifact_path: Path) -> list[dict[str, Any]]:
    """Return spec E(C) ``acceptance_evidence`` records for a sealed artifact.

    An artifact with no acceptance links yields ``[]``, which spec reads as
    ``unknown`` for every criterion. A failing linked command is exported as
    evidence (spec grades it; an unengaged required pipeline remains unknown).
    An artifact that fails integrity
    validation is refused."""
    artifact_path = Path(artifact_path)
    validation = verification_evidence.validate_verification_artifact(artifact_path)
    if not validation.ok and validation.code != "nonzero_exit":
        raise AcceptanceEvidenceError(
            validation.code, "; ".join(validation.findings) or f"artifact failed validation: {validation.code}"
        )
    result = verification_evidence.load_verification_artifact(artifact_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    record = (payload.get("extensions") or {}).get(EXTENSION_NAMESPACE)
    if record is None:
        return []
    links = record["links"]
    _require_command_indexes(links, len(result.commands))
    log_bytes = (artifact_path.parent / verification_evidence.LOG_NAME).read_bytes()
    mode = record["pipeline_mode"]
    engaged = record["pipeline_engaged"]
    authority = acceptance_authority(mode, engaged)
    exported = []
    for link in links:
        command = result.commands[link["command_index"]]
        if command.log_end_offset is None:
            raise AcceptanceEvidenceError(
                "missing_command_log_bounds",
                f"command {link['command_index']} has no log_end_offset; per-command log digests need schema v2+",
            )
        command_bytes = log_bytes[command.log_offset:command.log_end_offset]
        exported.append(
            {
                "criterion_logical_id": link["criterion_logical_id"],
                "argv": list(command.argv),
                "exit_code": command.exit_code,
                "log_sha256": hashlib.sha256(command_bytes).hexdigest(),
                "pipeline_mode": mode,
                "pipeline_engaged": engaged,
                "authority": authority,
            }
        )
    return exported


def _require_command_indexes(links: Sequence[Mapping[str, Any]], command_count: int) -> None:
    for index, link in enumerate(links):
        if link["command_index"] >= command_count:
            raise AcceptanceEvidenceError(
                "unknown_command_index",
                f"links[{index}].command_index {link['command_index']} is outside commands[0:{command_count}]",
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m phase_loop_runtime.acceptance_evidence",
        description="Export spec E(C) acceptance_evidence records from a sealed verification.json.",
    )
    parser.add_argument("artifact", type=Path, help="path to verification.json")
    args = parser.parse_args(argv)
    try:
        records = export_acceptance_evidence(args.artifact)
    except (AcceptanceEvidenceError, OSError) as exc:
        print(f"acceptance evidence export failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(records, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
