from _outside_agent_canonical import clean_submission

from phase_loop_runtime.conformance.outside_agent_core import OutsideAgentSubmissionKind
from phase_loop_runtime.conformance.outside_agent_schema import (
    validate_outside_agent_submission_schema,
)


def _refs(result):
    return {blocker.ref for blocker in result.blockers}


def _codes(result):
    return {blocker.code for blocker in result.blockers}


def test_accepts_supported_submission_kinds():
    expected = {
        "work_request": OutsideAgentSubmissionKind.WORK_REQUEST,
        "implementation_submission": OutsideAgentSubmissionKind.IMPLEMENTATION_SUBMISSION,
        "ambiguity_report": OutsideAgentSubmissionKind.AMBIGUITY_REPORT,
    }

    for kind, parsed in expected.items():
        result = validate_outside_agent_submission_schema(clean_submission(kind))
        assert result.submission_kind == parsed
        assert result.blockers == ()


def test_unsupported_schema_version_fails_closed():
    submission = clean_submission()
    submission["submission_schema_version"] = "outside_agent_submission.v9"

    result = validate_outside_agent_submission_schema(submission)
    assert _codes(result) == {"schema_validation_failed"}
    assert "submission_schema_version" in _refs(result)


def test_unsupported_submission_kind_fails_closed():
    submission = clean_submission()
    submission["submission_kind"] = "freeform_patch"

    result = validate_outside_agent_submission_schema(submission)
    assert "schema_validation_failed" in _codes(result)
    assert "submission_kind" in _refs(result)
    # An unknown kind is not a supported OutsideAgentSubmissionKind.
    assert result.submission_kind is None


def test_unknown_top_level_field_fails_closed():
    submission = clean_submission()
    submission["raw_result"] = {"anything": True}

    result = validate_outside_agent_submission_schema(submission)
    assert "schema_validation_failed" in _codes(result)
    # The unexpected field is rejected by the schema's additionalProperties gate.
    # The sanitized message names the failing keyword, never the submitted field
    # name or value (agent-harness#371 round 2: schema messages must not echo input).
    assert any("additionalProperties" in blocker.message for blocker in result.blockers)
    assert all("raw_result" not in blocker.message for blocker in result.blockers)


def test_missing_required_top_level_field_fails_closed():
    submission = clean_submission()
    del submission["producer"]

    result = validate_outside_agent_submission_schema(submission)
    assert "schema_validation_failed" in _codes(result)
    assert any("producer" in blocker.message for blocker in result.blockers)
