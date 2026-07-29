"""Pinned outside-agent contract metadata consumed from Consiliency/spec."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutsideAgentContractPin:
    schema_version: str
    verdict_schema_version: str
    contract_package: str
    contract_version: str
    # ``contract_git_tag`` is the immutable release anchor (an annotated tag on
    # Consiliency/spec@main); ``contract_git_sha`` is the 40-hex commit it
    # dereferences to. Recording both lets a reader tell an anchor from a bare
    # snapshot — see plans/oapack/RELEASE-ANCHOR.md in Consiliency/spec.
    contract_git_tag: str
    contract_git_sha: str
    # Per-source sha256 over the RAW FILE BYTES of each contract artifact we
    # consume. Manifest-hash-only verification missed byte changes to the two
    # schema files that preserved their version const; these digests close that
    # asymmetry (Consiliency/agent-harness#370) and mirror governed-pipeline's
    # per-schema ``source_sha256`` pin.
    submission_schema_sha256: str
    verdict_schema_sha256: str
    vector_manifest_hash: str
    vector_manifest_name: str
    source_owner: str
    redaction_posture: str


EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN = OutsideAgentContractPin(
    schema_version="outside_agent_submission.v0.1",
    verdict_schema_version="outside_agent_route_verdict.v0.1",
    contract_package="consiliency-spec",
    contract_version="0.2.1",
    contract_git_tag="v0.2.1",
    contract_git_sha="b862f977897a7b87c4419680a3e83735d4ff07b0",
    submission_schema_sha256="5670b5001ced0f25010b153fe602db5761f92d69707cf670b6f530a7d689ef4a",
    verdict_schema_sha256="86169277d3a0823db1a6c9fa4d20a838b0bc2820818ad00ebd53dcdd03c2b1c2",
    vector_manifest_hash="78858828e9eace93eaf31d90717666ddce54ccb3666113df9d033d67c20cfca0",
    vector_manifest_name="test-vectors/outside-agent/manifest.json",
    source_owner="Consiliency/spec",
    redaction_posture="metadata_only",
)


__all__ = ["OutsideAgentContractPin", "EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN"]
