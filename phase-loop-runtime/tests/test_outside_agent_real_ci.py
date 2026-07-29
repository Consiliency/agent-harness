"""CI proof (OAREAL-2): the ACTUAL canonical corpus runs through our validator.

Unlike the synthetic fixtures this replaces, every submission here is a vendored
Consiliency/spec vector, driven through the real ``outside-agent-validate`` CLI and
the pinned vector runner.
"""
import json
import subprocess
import sys

import pytest
from _outside_agent_canonical import CONTRACT_ROOT, VECTOR_DIR

from phase_loop_runtime.conformance.outside_agent_vectors import run_outside_agent_vectors

MANIFEST = json.loads(
    (VECTOR_DIR / "manifest.json").read_text(encoding="utf-8")
)
_SUBMISSION_ENTRIES = [
    entry
    for entry in MANIFEST["vectors"]
    if entry["schema_target"] == "outside_agent_submission.v0.1"
]

# schema failures collapse to MALFORMED_INPUT (2); the schema-valid-but-inconsistent
# bundle-digest case is the lone CONFORMANCE_BLOCKED (6).
_EXPECTED_EXIT = {
    "positive-work-request": 0,
    "positive-implementation-submission": 0,
    "positive-ambiguity-report": 0,
    "negative-raw-payload": 2,
    "negative-missing-digest": 2,
    "negative-unknown-producer-identity-posture": 2,
    "negative-path-traversal": 2,
    "negative-empty-evidence-refs": 2,
    "negative-git-object-id-length": 2,
    "negative-source-bundle-mismatch": 6,
}


def test_expected_exit_map_covers_every_canonical_submission_vector():
    """A re-vendor that adds a vector must extend this map, not skip it."""
    assert {entry["case_id"] for entry in _SUBMISSION_ENTRIES} == set(_EXPECTED_EXIT)


def _run_validate(vector_path, tmp_path):
    output_path = tmp_path / "verdict.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.cli",
            "outside-agent-validate",
            str(vector_path),
            "--output",
            str(output_path),
            "--submitted-ref",
            "src/agent.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, json.loads(output_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "entry",
    _SUBMISSION_ENTRIES,
    ids=[entry["case_id"] for entry in _SUBMISSION_ENTRIES],
)
def test_cli_validates_canonical_vectors_with_pinned_exit_codes(entry, tmp_path):
    vector_path = CONTRACT_ROOT / entry["path"]
    result, payload = _run_validate(vector_path, tmp_path)

    assert result.returncode == _EXPECTED_EXIT[entry["case_id"]], (
        f"{entry['case_id']}: blockers={[b['code'] for b in payload['blockers']]}"
    )
    assert (payload["status"] == "pass") == entry["expected_valid"]
    assert payload["vectors_executed"] is False
    assert payload["authority"] == "governed_pipeline_validator"


def test_ci_canonical_vector_runner_matches_every_expected_outcome():
    results = run_outside_agent_vectors()

    assert len(results) == len(MANIFEST["vectors"])
    assert all(result.matched for result in results), {
        result.vector_name: (result.status.value, [b.code for b in result.blockers])
        for result in results
        if not result.matched
    }
