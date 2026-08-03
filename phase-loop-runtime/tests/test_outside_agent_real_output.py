import json

from _outside_agent_canonical import clean_submission, raw_payload_submission

from phase_loop_runtime.conformance import (
    OutsideAgentValidationExitCode,
    build_outside_agent_validation_verdict,
    serialize_outside_agent_validation_verdict,
)


def test_serializes_clean_governed_pipeline_verdict_shape():
    payload = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(
            clean_submission(),
            submitted_refs=("src/agent.py", "docs/result.md"),
        )
    )

    assert payload["gate_id"] == "real_conformance_gate.v0.1"
    assert payload["authority"] == "governed_pipeline_validator"
    assert payload["validator_version"]
    assert payload["command"] == "outside-agent-validate"
    assert payload["verdict_schema_version"] == "outside_agent_route_verdict.v0.1"
    assert payload["contract_pin"]["contract_package"] == "consiliency-spec"
    assert payload["vector_manifest_hash"] == payload["contract_pin"]["vector_manifest_hash"]
    assert len(payload["input_digest"]) == 64
    assert payload["submitted_refs"] == ["src/agent.py", "docs/result.md"]
    assert payload["status"] == "pass"
    assert payload["blockers"] == []
    assert payload["evidence_refs"] == [
        {
            "ref": "plans/oaspec/FIELD-NAME-FREEZE.md",
            "digest": "a" * 64,
            "kind": "documentation",
        },
    ]
    assert payload["redaction_posture"] == "metadata_only"
    assert payload["vectors_executed"] is False
    assert payload["exit_code"] == 0


def test_serialized_real_verdict_is_deterministic_json():
    first = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(clean_submission())
    )
    second = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(clean_submission())
    )

    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_serialized_blocked_verdict_has_typed_blockers_and_no_advisory_fields():
    # A raw payload field is rejected by the packaged schema (additionalProperties).
    payload = serialize_outside_agent_validation_verdict(
        build_outside_agent_validation_verdict(raw_payload_submission())
    )

    assert payload["status"] == "blocked"
    assert payload["exit_code"] == int(OutsideAgentValidationExitCode.MALFORMED_INPUT)
    codes = {blocker["code"] for blocker in payload["blockers"]}
    assert codes == {"schema_validation_failed"}
    # Sanitized message names the failing keyword; the forbidden field name and its
    # raw value must never ride out into output (agent-harness#371 round 2 anti-leak).
    assert any("additionalProperties" in blocker["message"] for blocker in payload["blockers"])
    _dumped = json.dumps(payload)
    assert "raw_body" not in _dumped
    assert "forbidden raw provider payload" not in _dumped
    assert "classification" not in payload
    assert "accepted_for_merge" not in payload
    assert "merge_verdict" not in payload
    assert "portal_projection" not in payload
