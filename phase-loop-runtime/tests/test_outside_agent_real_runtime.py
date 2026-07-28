from _outside_agent_canonical import (
    clean_submission,
    raw_payload_submission,
    source_bundle_mismatch_submission,
)

from phase_loop_runtime.conformance import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    OutsideAgentSubmittedRef,
    OutsideAgentValidationExitCode,
    OutsideAgentValidationVerdict,
    build_outside_agent_validation_verdict,
)
from phase_loop_runtime.conformance.outside_agent_core import (
    OutsideAgentBlocker,
    OutsideAgentConformanceVerdict,
    validate_outside_agent_submission,
)


def test_real_validator_wraps_core_once_with_metadata_only_evidence():
    calls = []

    def core(submission, *, contract_pin):
        calls.append((submission, contract_pin))
        return validate_outside_agent_submission(submission, contract_pin=contract_pin)

    verdict = build_outside_agent_validation_verdict(
        clean_submission(),
        submitted_refs=("src/agent.py",),
        core_validator=core,
    )

    assert isinstance(verdict, OutsideAgentValidationVerdict)
    assert verdict.authority == "governed_pipeline_validator"
    assert verdict.validator_version
    assert verdict.exit_code == OutsideAgentValidationExitCode.PASS
    assert verdict.verdict.contract_pin == EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN
    assert len(verdict.verdict.input_digest) == 64
    assert verdict.submitted_refs == (OutsideAgentSubmittedRef(ref="src/agent.py"),)
    assert verdict.vectors_executed is False
    assert calls == [(clean_submission(), EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN)]


def test_real_validator_malformed_object_maps_to_exit_2_and_calls_core_once():
    calls = []

    def core(submission, *, contract_pin):
        calls.append(submission)
        return validate_outside_agent_submission(submission, contract_pin=contract_pin)

    verdict = build_outside_agent_validation_verdict({"metadata": {}}, core_validator=core)

    assert verdict.exit_code == OutsideAgentValidationExitCode.MALFORMED_INPUT
    assert calls == [{"metadata": {}}]
    assert "schema_validation_failed" in {blocker.code for blocker in verdict.verdict.blockers}


def test_real_validator_schema_invalid_submission_maps_to_exit_2():
    # A forbidden raw payload is a schema (additionalProperties) failure.
    verdict = build_outside_agent_validation_verdict(raw_payload_submission())

    assert verdict.exit_code == OutsideAgentValidationExitCode.MALFORMED_INPUT
    codes = {blocker.code for blocker in verdict.verdict.blockers}
    assert codes == {"schema_validation_failed"}


def test_real_validator_source_bundle_mismatch_maps_to_exit_6():
    # Schema-valid but semantically inconsistent -> conformance blocked, not malformed.
    verdict = build_outside_agent_validation_verdict(source_bundle_mismatch_submission())

    assert verdict.exit_code == OutsideAgentValidationExitCode.CONFORMANCE_BLOCKED
    assert {blocker.code for blocker in verdict.verdict.blockers} == {
        "source_bundle_mismatch"
    }


def test_real_validator_other_conformance_blocker_maps_to_exit_6():
    base = validate_outside_agent_submission(clean_submission())

    def core(submission, *, contract_pin):
        return OutsideAgentConformanceVerdict(
            verdict_schema_version=base.verdict_schema_version,
            submission_kind=base.submission_kind,
            status=base.status,
            blockers=(OutsideAgentBlocker("policy_blocked", "blocked by policy"),),
            contract_pin=base.contract_pin,
            input_digest=base.input_digest,
            provenance_refs=base.provenance_refs,
            evidence_refs=base.evidence_refs,
            redaction_posture=base.redaction_posture,
            metadata=base.metadata,
        )

    verdict = build_outside_agent_validation_verdict(clean_submission(), core_validator=core)

    assert verdict.exit_code == OutsideAgentValidationExitCode.CONFORMANCE_BLOCKED


def test_real_validator_rejects_absolute_submitted_refs_without_raw_paths():
    verdict = build_outside_agent_validation_verdict(
        clean_submission(),
        submitted_refs=("/tmp/agent.py",),
    )

    assert verdict.exit_code == OutsideAgentValidationExitCode.PROVENANCE_FAILURE
    assert verdict.submitted_refs == ()
    assert verdict.verdict.blockers[-1].ref == "submitted_refs.0"
