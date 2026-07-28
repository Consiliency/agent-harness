import os

from _outside_agent_canonical import (
    clean_submission,
    raw_payload_submission,
    source_bundle_mismatch_submission,
)

from phase_loop_runtime.conformance import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    OutsideAgentAdvisoryEvidence,
    OutsideAgentAdvisoryExitCode,
    build_outside_agent_advisory_evidence,
    serialize_outside_agent_advisory_evidence,
)


def test_builds_clean_advisory_evidence_without_external_access(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-test-value")
    monkeypatch.setenv("OUTSIDE_AGENT_SPEC_ROOT", "/not/read/by/advisory")
    calls = []
    monkeypatch.setattr(os, "system", lambda command: calls.append(command) or 1)

    evidence = build_outside_agent_advisory_evidence(clean_submission())
    payload = serialize_outside_agent_advisory_evidence(evidence)

    assert isinstance(evidence, OutsideAgentAdvisoryEvidence)
    assert evidence.exit_code == OutsideAgentAdvisoryExitCode.PASS
    assert payload["authority"] == "advisory"
    assert payload["classification"] == "clean_advisory_pass"
    assert payload["status"] == "pass"
    assert payload["redaction_posture"] == "metadata_only"
    assert payload["contract_pin"]["schema_version"] == "outside_agent_submission.v0.1"
    assert payload["contract_pin"]["source_owner"] == EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN.source_owner
    assert len(payload["input_digest"]) == 64
    assert payload["provenance_refs"] == ["plans/oaspec/FIELD-NAME-FREEZE.md"]
    assert payload["evidence_refs"] == [
        {
            "ref": "plans/oaspec/FIELD-NAME-FREEZE.md",
            "digest": "a" * 64,
            "kind": "documentation",
        },
    ]
    assert "accepted_for_merge" not in payload
    assert "merge_verdict" not in payload
    assert calls == []


def test_serialized_advisory_evidence_is_deterministic_and_metadata_only():
    first = serialize_outside_agent_advisory_evidence(
        build_outside_agent_advisory_evidence(clean_submission())
    )
    second = serialize_outside_agent_advisory_evidence(
        build_outside_agent_advisory_evidence(clean_submission())
    )

    assert first == second
    assert first["metadata"] == {"source": "outside_agent_advisory_preflight"}


def test_malformed_submission_maps_to_exit_code_2():
    evidence = build_outside_agent_advisory_evidence(["not", "an", "object"])
    payload = serialize_outside_agent_advisory_evidence(evidence)

    assert evidence.exit_code == OutsideAgentAdvisoryExitCode.MALFORMED_INPUT
    assert payload["classification"] == "malformed_input"
    assert payload["exit_code"] == 2
    assert payload["blockers"][0]["code"] == "malformed_input"


def test_schema_invalid_submission_maps_to_exit_code_2():
    # Advisory has no conformance-blocked tier: a raw payload (schema failure)
    # surfaces as malformed_input.
    evidence = build_outside_agent_advisory_evidence(raw_payload_submission())
    payload = serialize_outside_agent_advisory_evidence(evidence)

    assert evidence.exit_code == OutsideAgentAdvisoryExitCode.MALFORMED_INPUT
    assert payload["classification"] == "malformed_input"
    assert {blocker["code"] for blocker in payload["blockers"]} == {"schema_validation_failed"}
    assert any("raw_body" in blocker["message"] for blocker in payload["blockers"])


def test_source_bundle_mismatch_maps_to_exit_code_2():
    evidence = build_outside_agent_advisory_evidence(source_bundle_mismatch_submission())
    payload = serialize_outside_agent_advisory_evidence(evidence)

    assert evidence.exit_code == OutsideAgentAdvisoryExitCode.MALFORMED_INPUT
    assert {blocker["code"] for blocker in payload["blockers"]} == {"source_bundle_mismatch"}
