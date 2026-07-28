"""Advisory evidence over the canonical corpus, cross-checked against the manifest.

Replaces hand-authored golden fixtures (whose invented shapes concealed
agent-harness#371) with the vendored Consiliency/spec vectors: each submission
vector's advisory summary must agree with the manifest's own ``expected_valid``.
"""
import json

import pytest
from _outside_agent_canonical import VECTOR_DIR, load_vector

from phase_loop_runtime.conformance.outside_agent_advisory import (
    build_outside_agent_advisory_evidence,
    serialize_outside_agent_advisory_evidence,
)

MANIFEST = json.loads((VECTOR_DIR / "manifest.json").read_text(encoding="utf-8"))
_SUBMISSION_ENTRIES = [
    entry
    for entry in MANIFEST["vectors"]
    if entry["schema_target"] == "outside_agent_submission.v0.1"
]


@pytest.mark.parametrize(
    "entry",
    _SUBMISSION_ENTRIES,
    ids=[entry["case_id"] for entry in _SUBMISSION_ENTRIES],
)
def test_advisory_summary_agrees_with_manifest(entry):
    stem = entry["path"].rsplit("/", 1)[-1].removesuffix(".json")
    payload = serialize_outside_agent_advisory_evidence(
        build_outside_agent_advisory_evidence(load_vector(stem))
    )

    if entry["expected_valid"]:
        assert payload["classification"] == "clean_advisory_pass"
        assert payload["exit_code"] == 0
        assert payload["status"] == "pass"
        assert payload["blockers"] == []
    else:
        assert payload["status"] == "blocked"
        # Advisory has no conformance-blocked tier; all rejections read exit 2.
        assert payload["exit_code"] == 2
        assert payload["blockers"]

    # Structural invariants that hold for every canonical submission.
    assert payload["redaction_posture"] == "metadata_only"
    assert payload["contract_pin"]["schema_version"] == "outside_agent_submission.v0.1"
    assert payload["contract_pin"]["redaction_posture"] == "metadata_only"
    assert len(payload["input_digest"]) == 64
    assert "accepted_for_merge" not in payload
    assert "merge_verdict" not in payload
