from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _outside_agent_canonical import (
    ALL_OUTSIDE_AGENT_NODE_IDS,
    CONFORMANCE_EXPORT_SNAPSHOT,
    FIXTURE_ROOT,
    LIVE_BLOCKER_CODE_BY_INVALID_CASE,
    REPO_ROOT,
    assert_packaged_contract_mirror,
    assert_evidence_verifier_entrypoint,
    fixture_paths,
    load_oracle,
    manifest,
    node_source_path,
    normalized_nodeid,
    route_verdict_entry,
    submission_entries,
    vector_entries,
    vector_payload,
    verify_fixture_digests,
)


def test_canonical_fixture_provenance_and_digest_inventory() -> None:
    verify_fixture_digests()
    assert fixture_paths() == (
        "consiliency_spec/outside_agent_router.py",
        "schemas/outside-agent-route-verdict.schema.json",
        "schemas/outside-agent-submission.schema.json",
        "test-vectors/outside-agent/invalid-empty-evidence-refs.json",
        "test-vectors/outside-agent/invalid-git-object-id-length.json",
        "test-vectors/outside-agent/invalid-missing-digest.json",
        "test-vectors/outside-agent/invalid-path-traversal.json",
        "test-vectors/outside-agent/invalid-raw-payload.json",
        "test-vectors/outside-agent/invalid-source-bundle-mismatch.json",
        "test-vectors/outside-agent/invalid-unknown-producer-identity-posture.json",
        "test-vectors/outside-agent/invalid-unsupported-verdict.json",
        "test-vectors/outside-agent/manifest.json",
        "test-vectors/outside-agent/valid-ambiguity-report.json",
        "test-vectors/outside-agent/valid-implementation-submission.json",
        "test-vectors/outside-agent/valid-work-request.json",
    )


def test_canonical_manifest_partition_and_oracle_rows() -> None:
    rows = vector_entries()
    assert {(row["case_id"], row["expected_valid"], row["expected_blocker_class"]) for row in rows} == {
        ("positive-work-request", True, "none"),
        ("positive-implementation-submission", True, "none"),
        ("positive-ambiguity-report", True, "none"),
        ("negative-raw-payload", False, "unsafe_evidence_reference"),
        ("negative-missing-digest", False, "missing_information"),
        ("negative-source-bundle-mismatch", False, "unsafe_evidence_reference"),
        ("negative-unsupported-verdict", False, "policy_gap"),
        ("negative-unknown-producer-identity-posture", False, "policy_gap"),
        ("negative-path-traversal", False, "unsafe_evidence_reference"),
        ("negative-empty-evidence-refs", False, "missing_information"),
        ("negative-git-object-id-length", False, "unsafe_evidence_reference"),
    }
    valid = {row["case_id"] for row in rows if row["expected_valid"]}
    invalid = {row["case_id"] for row in rows if not row["expected_valid"]}
    submission_invalid = {
        row["case_id"]
        for row in rows
        if row["schema_target"] == "outside_agent_submission.v0.1" and not row["expected_valid"]
    }
    route_invalid = {
        row["case_id"]
        for row in rows
        if row["schema_target"] == "outside_agent_route_verdict.v0.1" and not row["expected_valid"]
    }
    assert valid == {
        "positive-work-request",
        "positive-implementation-submission",
        "positive-ambiguity-report",
    }
    assert invalid == {
        "negative-raw-payload",
        "negative-missing-digest",
        "negative-source-bundle-mismatch",
        "negative-unsupported-verdict",
        "negative-unknown-producer-identity-posture",
        "negative-path-traversal",
        "negative-empty-evidence-refs",
        "negative-git-object-id-length",
    }
    assert submission_invalid == invalid - {"negative-unsupported-verdict"}
    assert route_invalid == {"negative-unsupported-verdict"}
    assert LIVE_BLOCKER_CODE_BY_INVALID_CASE == {
        "negative-raw-payload": "schema_validation_failed",
        "negative-missing-digest": "schema_validation_failed",
        "negative-source-bundle-mismatch": "source_bundle_mismatch",
        "negative-unsupported-verdict": "schema_validation_failed",
        "negative-unknown-producer-identity-posture": "schema_validation_failed",
        "negative-path-traversal": "schema_validation_failed",
        "negative-empty-evidence-refs": "schema_validation_failed",
        "negative-git-object-id-length": "schema_validation_failed",
    }
    assert set(LIVE_BLOCKER_CODE_BY_INVALID_CASE) == invalid
    assert set(LIVE_BLOCKER_CODE_BY_INVALID_CASE.values()) == {
        "schema_validation_failed",
        "source_bundle_mismatch",
    }
    assert {
        row["schema_target"]
        for row in rows
    } == {
        "outside_agent_submission.v0.1",
        "outside_agent_route_verdict.v0.1",
    }
    assert manifest()["vectors"] == list(rows)


def test_canonical_oracle_is_importable_and_matches_manifest() -> None:
    oracle = load_oracle()
    for row in vector_entries():
        verdict = oracle.route(vector_payload(row), row["schema_target"])
        assert oracle.blocker_class_of(verdict) == row["expected_blocker_class"]
    route_row = route_verdict_entry()
    route_verdict = oracle.route(vector_payload(route_row), route_row["schema_target"])
    assert route_verdict["route"] == "reject"


def test_public_exports_and_frontmatter_import_are_preserved() -> None:
    from phase_loop_runtime import conformance
    import _outside_agent_canonical

    assert tuple(conformance.__all__) == CONFORMANCE_EXPORT_SNAPSHOT
    for name in CONFORMANCE_EXPORT_SNAPSHOT:
        assert getattr(conformance, name) is not None
    assert Path(_outside_agent_canonical.__file__).resolve().parent == (
        REPO_ROOT / "phase-loop-runtime" / "tests"
    )
    test_root = node_source_path(ALL_OUTSIDE_AGENT_NODE_IDS[0]).parent
    source_root = REPO_ROOT / "phase-loop-runtime" / "src"
    pythonpath = [str(test_root)]
    if source_root.is_dir():
        pythonpath.insert(0, str(source_root))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "phase-loop-runtime/tests",
            "-q",
            "--collect-only",
            "-k",
            "outside_agent",
        ],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": os.pathsep.join(pythonpath)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    collected = {
        normalized_nodeid(line.strip())
        for line in completed.stdout.splitlines()
        if "test_outside_agent" in line and "::" in line
    }
    assert collected == set(ALL_OUTSIDE_AGENT_NODE_IDS)


def test_canonical_oracle_passes_repo_root_ruff() -> None:
    # Ruff remains runner-owned pre-freeze evidence.  Gate A and ordinary pytest
    # must instead inspect the exact fixture they actually carry, without an
    # ambient executable.
    oracle_path = FIXTURE_ROOT / "consiliency_spec" / "outside_agent_router.py"
    source = oracle_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(oracle_path))
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {"route", "blocker_class_of"} <= functions
    oracle = load_oracle()
    assert callable(oracle.route)
    assert callable(oracle.blocker_class_of)


def test_canonical_submission_api_accepts_three_valid_rows() -> None:
    from phase_loop_runtime.conformance.outside_agent_core import validate_outside_agent_submission

    oracle = load_oracle()
    outcomes = {}
    for row in submission_entries():
        verdict = validate_outside_agent_submission(vector_payload(row))
        oracle_verdict = oracle.route(vector_payload(row), row["schema_target"])
        outcomes[row["case_id"]] = {
            "status": verdict.status.value,
            "blocker_codes": tuple(sorted(blocker.code for blocker in verdict.blockers)),
            "oracle_blocker_class": oracle.blocker_class_of(oracle_verdict),
        }
    expected = {
        row["case_id"]: {
            "status": "pass" if row["expected_valid"] else "blocked",
            "blocker_codes": ()
            if row["expected_valid"]
            else (LIVE_BLOCKER_CODE_BY_INVALID_CASE[row["case_id"]],),
            "oracle_blocker_class": row["expected_blocker_class"],
        }
        for row in submission_entries()
    }
    assert outcomes == expected, "CONFORM_RED::canonical_submission_api_accepts_three_valid_rows"


def test_canonical_submission_cli_accepts_three_valid_rows(tmp_path) -> None:
    expected_exit = {
        "positive-work-request": 0,
        "positive-implementation-submission": 0,
        "positive-ambiguity-report": 0,
        "negative-raw-payload": 2,
        "negative-missing-digest": 2,
        "negative-source-bundle-mismatch": 6,
        "negative-unknown-producer-identity-posture": 2,
        "negative-path-traversal": 2,
        "negative-empty-evidence-refs": 2,
        "negative-git-object-id-length": 2,
    }
    assert {row["case_id"] for row in submission_entries()} == set(expected_exit)
    for row in submission_entries():
        submission_path = tmp_path / (row["case_id"] + ".json")
        output_path = tmp_path / (row["case_id"] + ".output.json")
        submission_path.write_text(json.dumps(vector_payload(row)), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "phase_loop_runtime.cli",
                "outside-agent-validate",
                str(submission_path),
                "--output",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(completed.stdout)
        assert completed.returncode == expected_exit[row["case_id"]], "CONFORM_RED::canonical_submission_cli_accepts_three_valid_rows"
        assert payload["status"] == ("pass" if row["expected_valid"] else "blocked")
        assert output_path.read_text(encoding="utf-8") == completed.stdout
        if not row["expected_valid"]:
            assert {blocker["code"] for blocker in payload["blockers"]} == {
                LIVE_BLOCKER_CODE_BY_INVALID_CASE[row["case_id"]]
            }


def test_canonical_vector_runner_consumes_schema_target_partition() -> None:
    from phase_loop_runtime.conformance.outside_agent_vectors import run_outside_agent_vectors

    assert_evidence_verifier_entrypoint(
        "phase-loop-runtime/tests/test_outside_agent_canonical_corpus.py::"
        "test_canonical_vector_runner_consumes_schema_target_partition"
    )
    try:
        results = run_outside_agent_vectors(manifest())
    except Exception as exc:
        pytest.fail(
            "CONFORM_RED::canonical_vector_runner_consumes_schema_target_partition: "
            f"canonical vector dispatch is unavailable ({type(exc).__name__})"
        )
    by_case = {result.vector_name: result for result in results}
    assert set(by_case) == {row["case_id"] for row in vector_entries()}, "CONFORM_RED::canonical_vector_runner_consumes_schema_target_partition"
    oracle = load_oracle()
    for row in vector_entries():
        result = by_case[row["case_id"]]
        assert result.status.value == ("pass" if row["expected_valid"] else "blocked")
        assert oracle.blocker_class_of(oracle.route(vector_payload(row), row["schema_target"])) == row["expected_blocker_class"]
        if not row["expected_valid"]:
            assert {blocker.code for blocker in result.blockers} == {
                LIVE_BLOCKER_CODE_BY_INVALID_CASE[row["case_id"]]
            }


def test_route_verdict_requires_selected_schema_not_submission_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import phase_loop_runtime.cli as phase_loop_cli
    import phase_loop_runtime.conformance.outside_agent_vectors as vector_runner

    route_row = route_verdict_entry()
    assert route_row["case_id"] not in {row["case_id"] for row in submission_entries()}
    route_payload = vector_payload(route_row)
    anchor = "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli"
    submission_validator = vector_runner.validate_outside_agent_submission

    def forbid_route_submission(payload, *args, **kwargs):
        if payload == route_payload:
            pytest.fail(anchor)
        return submission_validator(payload, *args, **kwargs)

    def forbid_submission_cli(*_args, **_kwargs):
        pytest.fail(anchor)

    subprocess_run = subprocess.run
    subprocess_popen = subprocess.Popen

    def guard_subprocess_run(command, *args, **kwargs):
        if "outside-agent-validate" in tuple(str(item) for item in command):
            pytest.fail(anchor)
        return subprocess_run(command, *args, **kwargs)

    def guard_subprocess_popen(command, *args, **kwargs):
        if "outside-agent-validate" in tuple(str(item) for item in command):
            pytest.fail(anchor)
        return subprocess_popen(command, *args, **kwargs)

    monkeypatch.setattr(
        vector_runner, "validate_outside_agent_submission", forbid_route_submission
    )
    monkeypatch.setattr(
        phase_loop_cli, "_outside_agent_validate_command", forbid_submission_cli
    )
    monkeypatch.setattr(subprocess, "run", guard_subprocess_run)
    monkeypatch.setattr(subprocess, "Popen", guard_subprocess_popen)
    # This is the direct route-verdict seam.  It is intentionally independent of
    # the vector runner and never feeds the route row through either submission
    # CLI.  A flattened one-schema implementation cannot satisfy this probe.
    try:
        from phase_loop_runtime.conformance.outside_agent_schema import (
            validate_outside_agent_route_verdict_schema,
        )

        direct = validate_outside_agent_route_verdict_schema(
            route_payload, schema_target=route_row["schema_target"]
        )
    except (AttributeError, ImportError, TypeError) as exc:
        pytest.fail(
            "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli: "
            f"selected route-verdict schema capability is unavailable ({type(exc).__name__})"
        )
    assert direct.status.value == "blocked", (
        "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli"
    )
    assert {blocker.code for blocker in direct.blockers} == {
        LIVE_BLOCKER_CODE_BY_INVALID_CASE[route_row["case_id"]]
    }
    try:
        results = vector_runner.run_outside_agent_vectors(manifest())
    except Exception as exc:
        pytest.fail(
            "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli: "
            f"route dispatch is unavailable ({type(exc).__name__})"
        )
    by_name = {result.vector_name: result for result in results}
    result = by_name.get(route_row["case_id"])
    assert result is not None and result.status.value == "blocked", "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli"
    assert {blocker.code for blocker in result.blockers} == {
        LIVE_BLOCKER_CODE_BY_INVALID_CASE[route_row["case_id"]]
    }
    payload = route_payload
    assert payload["verdict_schema_version"] == "outside_agent_route_verdict.v0.1"
    assert payload["route"] not in {"reject", "needs_clarification", "roadmap_intake", "review_candidate"}
    schema = json.loads(
        (FIXTURE_ROOT / "schemas/outside-agent-route-verdict.schema.json").read_text(
            encoding="utf-8"
        )
    )
    observation = getattr(result, "dispatch_observation", None)
    assert observation == {
        "entered": True,
        "schema_target": route_row["schema_target"],
        "selected_schema_id": schema["$id"],
        "selected_schema_sha256": __import__("hashlib").sha256(
            (FIXTURE_ROOT / "schemas/outside-agent-route-verdict.schema.json").read_bytes()
        ).hexdigest(),
        "validation_error_pointer": "/route",
        "validation_error_keyword": "enum",
    }, "CONFORM_RED::route_verdict_requires_selected_schema_not_submission_cli"


def test_packaged_contract_mirror_matches_fixture_provenance() -> None:
    assert_packaged_contract_mirror()
