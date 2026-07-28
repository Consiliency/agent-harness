import json
import subprocess
import sys

from _outside_agent_canonical import clean_submission, raw_payload_submission


def _run_preflight(path, *args):
    return subprocess.run(
        [sys.executable, "-m", "phase_loop_runtime.cli", "outside-agent-preflight", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(path, submission):
    path.write_text(json.dumps(submission), encoding="utf-8")
    return path


def test_cli_clean_pass_outputs_advisory_json(tmp_path):
    submission_path = _write(tmp_path / "submission.json", clean_submission())

    result = _run_preflight(submission_path)
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["authority"] == "advisory"
    assert payload["classification"] == "clean_advisory_pass"
    assert payload["status"] == "pass"
    assert payload["redaction_posture"] == "metadata_only"
    assert "accepted_for_merge" not in payload
    assert "merge_verdict" not in payload
    assert result.stderr == ""


def test_cli_malformed_json_returns_exit_2(tmp_path):
    submission_path = tmp_path / "submission.json"
    submission_path.write_text("{not json", encoding="utf-8")

    result = _run_preflight(submission_path)
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["classification"] == "malformed_input"
    assert payload["blockers"][0]["code"] == "malformed_input"


def test_cli_schema_invalid_submission_returns_exit_2(tmp_path):
    submission_path = _write(tmp_path / "submission.json", raw_payload_submission())

    result = _run_preflight(submission_path)
    payload = json.loads(result.stdout)

    assert result.returncode == 2
    assert payload["classification"] == "malformed_input"
    assert "schema_validation_failed" in {blocker["code"] for blocker in payload["blockers"]}


def test_cli_writes_output_file_with_stdout_payload(tmp_path):
    submission_path = _write(tmp_path / "submission.json", clean_submission())
    output_path = tmp_path / "advisory.json"

    result = _run_preflight(submission_path, "--output", str(output_path))

    assert result.returncode == 0
    assert json.loads(output_path.read_text(encoding="utf-8")) == json.loads(result.stdout)
