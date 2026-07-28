import json
import subprocess
import sys

from _outside_agent_canonical import (
    clean_submission,
    raw_payload_submission,
    source_bundle_mismatch_submission,
)


def _write(path, submission):
    path.write_text(json.dumps(submission), encoding="utf-8")
    return path


def _run_validate(path, *args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "phase_loop_runtime.cli",
            "outside-agent-validate",
            str(path),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_clean_pass_writes_file_and_stdout(tmp_path):
    submission_path = _write(tmp_path / "submission.json", clean_submission())
    output_path = tmp_path / "verdict.json"

    result = _run_validate(
        submission_path,
        "--output",
        str(output_path),
        "--submitted-ref",
        "src/agent.py",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert payload["gate_id"] == "real_conformance_gate.v0.1"
    assert payload["authority"] == "governed_pipeline_validator"
    assert payload["command"] == "outside-agent-validate"
    assert payload["submitted_refs"] == ["src/agent.py"]
    assert payload["vectors_executed"] is False
    assert "accepted_for_merge" not in payload
    assert "merge_verdict" not in payload
    assert result.stderr == ""


def test_cli_malformed_json_returns_exit_2_and_writes_output(tmp_path):
    submission_path = tmp_path / "submission.json"
    output_path = tmp_path / "verdict.json"
    submission_path.write_text("{not json", encoding="utf-8")

    result = _run_validate(submission_path, "--output", str(output_path))
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["blockers"][0]["code"] == "malformed_input"
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_cli_schema_invalid_submission_returns_exit_2(tmp_path):
    # A forbidden raw payload field is a packaged-schema (additionalProperties) failure.
    submission_path = _write(tmp_path / "submission.json", raw_payload_submission())
    output_path = tmp_path / "verdict.json"

    result = _run_validate(submission_path, "--output", str(output_path))
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert {blocker["code"] for blocker in payload["blockers"]} == {"schema_validation_failed"}


def test_cli_unsafe_submitted_ref_returns_exit_4(tmp_path):
    submission_path = _write(tmp_path / "submission.json", clean_submission())
    output_path = tmp_path / "verdict.json"

    result = _run_validate(
        submission_path,
        "--output",
        str(output_path),
        "--submitted-ref",
        "/tmp/unsafe.json",
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 4
    assert "absolute_path_ref" in {blocker["code"] for blocker in payload["blockers"]}


def test_cli_requires_output(tmp_path):
    submission_path = _write(tmp_path / "submission.json", clean_submission())

    result = _run_validate(submission_path)

    assert result.returncode == 2
    assert "required" in result.stderr
    assert result.stdout == ""


def test_cli_source_bundle_mismatch_returns_exit_6(tmp_path):
    submission_path = _write(
        tmp_path / "submission.json", source_bundle_mismatch_submission()
    )
    output_path = tmp_path / "verdict.json"

    result = _run_validate(submission_path, "--output", str(output_path))
    payload = json.loads(result.stdout)

    assert result.returncode == 6
    assert {blocker["code"] for blocker in payload["blockers"]} == {"source_bundle_mismatch"}
