import os

from _outside_agent_canonical import clean_submission

from phase_loop_runtime.conformance import (
    EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN,
    OutsideAgentBlocker,
    OutsideAgentConformanceVerdict,
    OutsideAgentContractError,
    OutsideAgentContractPin,
    OutsideAgentEvidenceRef,
    OutsideAgentSubmissionKind,
    OutsideAgentVerdictStatus,
    load_outside_agent_contract_pin,
    validate_outside_agent_submission,
)


def test_public_core_api_returns_typed_metadata_only_verdict():
    verdict = validate_outside_agent_submission(clean_submission())

    assert isinstance(verdict, OutsideAgentConformanceVerdict)
    assert verdict.verdict_schema_version == "outside_agent_route_verdict.v0.1"
    assert verdict.submission_kind == OutsideAgentSubmissionKind.WORK_REQUEST
    assert verdict.status == OutsideAgentVerdictStatus.PASS
    assert verdict.blockers == ()
    assert verdict.contract_pin == EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN
    assert len(verdict.input_digest) == 64
    # Verdict evidence refs are surfaced from the canonical evidence_refs
    # (repo_relative_path + sha256 + source_role), metadata-only.
    assert verdict.provenance_refs == ("plans/oaspec/FIELD-NAME-FREEZE.md",)
    assert verdict.evidence_refs == (
        OutsideAgentEvidenceRef(
            ref="plans/oaspec/FIELD-NAME-FREEZE.md",
            digest="a" * 64,
            kind="documentation",
        ),
    )
    assert verdict.redaction_posture == "metadata_only"


def test_core_api_is_deterministic_and_does_not_require_secrets(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-test-value")
    monkeypatch.setenv("OUTSIDE_AGENT_SPEC_ROOT", "/not/read/by/core")

    first = validate_outside_agent_submission(clean_submission())
    second = validate_outside_agent_submission(clean_submission())

    assert first == second


def test_public_import_surface_preserves_oacontract_helpers():
    assert isinstance(EXPECTED_OUTSIDE_AGENT_CONTRACT_PIN, OutsideAgentContractPin)
    assert OutsideAgentContractError("code", "message").code == "code"
    assert callable(load_outside_agent_contract_pin)
    assert isinstance(OutsideAgentBlocker("code", "message"), OutsideAgentBlocker)


def test_validation_does_not_use_network_or_provider_credentials(monkeypatch):
    calls = []

    def fake_system(command):
        calls.append(command)
        return 1

    monkeypatch.setattr(os, "system", fake_system)

    verdict = validate_outside_agent_submission(clean_submission("ambiguity_report"))

    assert verdict.status == OutsideAgentVerdictStatus.PASS
    assert calls == []
