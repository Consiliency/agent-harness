import copy

from phase_loop_runtime.conformance.outside_agent_core import OutsideAgentVerdictStatus
from phase_loop_runtime.conformance.outside_agent_vectors import run_outside_agent_vectors


def _canonical_manifest():
    """A minimal well-formed canonical manifest (path entries resolved vs corpus)."""
    return {
        "manifest_schema_version": "outside_agent_vector_manifest.v0.1",
        "vectors": [
            {
                "case_id": "positive-work-request",
                "path": "test-vectors/outside-agent/valid-work-request.json",
                "submission_kind": "work_request",
                "schema_target": "outside_agent_submission.v0.1",
                "expected_valid": True,
            },
        ],
    }


def test_runner_matches_canonical_corpus_expected_outcomes():
    results = run_outside_agent_vectors()

    by_case = {result.vector_name: result for result in results}
    # Every canonical vector's pass/reject outcome matches the manifest's own
    # expected_valid — including the semantic-only and route-verdict cases.
    assert all(result.matched for result in results), {
        name: (r.status.value, [b.code for b in r.blockers])
        for name, r in by_case.items()
        if not r.matched
    }
    assert by_case["positive-work-request"].status == OutsideAgentVerdictStatus.PASS
    assert by_case["negative-source-bundle-mismatch"].status == OutsideAgentVerdictStatus.BLOCKED
    assert {b.code for b in by_case["negative-source-bundle-mismatch"].blockers} == {
        "source_bundle_mismatch"
    }
    # The route-verdict target vector is validated against the verdict schema.
    assert by_case["negative-unsupported-verdict"].status == OutsideAgentVerdictStatus.BLOCKED


def test_unknown_vector_manifest_schema_version_fails_closed():
    manifest = _canonical_manifest()
    manifest["manifest_schema_version"] = "outside_agent_vector_manifest.v9"

    result = run_outside_agent_vectors(manifest=manifest)[0]

    assert result.vector_name == "__manifest__"
    assert result.status == OutsideAgentVerdictStatus.BLOCKED
    assert any(blocker.code == "unsupported_schema_version" for blocker in result.blockers)


def test_missing_required_entry_field_fails_closed():
    manifest = copy.deepcopy(_canonical_manifest())
    del manifest["vectors"][0]["expected_valid"]

    result = run_outside_agent_vectors(manifest=manifest)[0]

    assert result.vector_name == "__manifest__"
    assert any(
        blocker.ref == "vectors.0.expected_valid" and blocker.code == "schema_validation_failed"
        for blocker in result.blockers
    )


def test_unsupported_schema_target_fails_closed():
    manifest = copy.deepcopy(_canonical_manifest())
    manifest["vectors"][0]["schema_target"] = "outside_agent_submission.v9"

    result = run_outside_agent_vectors(manifest=manifest)[0]

    assert result.vector_name == "__manifest__"
    assert any(
        blocker.ref == "vectors.0.schema_target" for blocker in result.blockers
    )
