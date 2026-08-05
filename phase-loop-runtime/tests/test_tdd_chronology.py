"""test_tdd_chronology.py — PROOFGATE TDD chronology tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
import pytest

from .proofgate_bootstrap_verifier import (
    BOOTSTRAP_CONTROL_CASES,
    BOOTSTRAP_CONTROL_COMPONENTS,
    BOOTSTRAP_LIVE_REACHABILITY_CASES,
    BOOTSTRAP_MERGE_OBSERVATION_SCHEMA,
    BOOTSTRAP_COORDINATOR_PRODUCER_RECEIPT_SCHEMA,
    BOOTSTRAP_ZERO_EFFECT_CASES,
    ATTENDED_PROVIDER_RECEIPTS_FILENAME,
    ATTENDED_REFERENCE_RUNNER_BYTES,
    COORDINATOR_EVIDENCE_ARTIFACTS,
    COORDINATOR_REPOSITORY,
    COORDINATOR_SEAT_ARTIFACTS,
    CoordinatorBootstrapMergeObservationBoundary,
    PR_B_5_PATHS,
    PR_T_18_PATHS,
    ProofgateBootstrapMergeObservation,
    ProofgateBootstrapVerifierError,
    RecordingBootstrapMergeObservationBoundary,
    coordinator_evidence_capture_argv,
    coordinator_evidence_capture_pytest_args,
    compute_git_source_binding_facts,
    evaluate_unit_double_bootstrap_merge_review_gate,
    expected_attended_runner_module_identity,
    attended_provider_receipts_digest,
    verify_coordinator_evidence_capture,
    verify_observed_premerge_bootstrap_review_gate,
    verify_junit_accounting,
    verify_landed_bootstrap_source_binding,
    verify_premerge_bootstrap_review_gate,
)
from .proofgate_tdd_guard import (
    ATTENDED_REAL_PROVIDER_CASES,
    DEFAULT_SKIP_NODEIDS,
    EXPECTED_PHASE_NODEIDS,
    RED_CASES_BY_NODEID,
    ProofgateMissingCapabilityError,
    guard_proofgate_nodeid,
    primary_red_case_id,
    run_proofgate_contract,
)


PR_B_BOOTSTRAP_PATHS_SHA256 = "3c365db032ad94622149fde1cadcb84b45480d65d8d789387ef47de286b59c44"
PR_B_SELECTOR_MODULES_SHA256 = "6d72046058d5b186bc50817c298f919806a09bd3826b10dec51cd000600cfe2d"
PR_B_BOOTSTRAP_CANDIDATE_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_bootstrap_records_are_single_use_and_server_bound",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_rewrite_truncation_fork_or_backfill",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_receipt_chain_rejects_wrong_workflow_signer_source_blob_subject_or_timestamp",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_implementation_authorization_requires_activation_preflight_panel_and_red_order",
    "phase-loop-runtime/tests/test_proofgate_receipts.py::test_runner_routes_reject_child_claims_and_missing_latest_external_head",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_isolation_preflight_masks_host_sibling_receipt_logs_fds_and_credentials",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_provider_projection_allows_only_selected_vendor_subscription_material",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_capability_socket_rejects_privileged_unknown_replayed_or_wrong_peer_requests",
    "phase-loop-runtime/tests/test_proofgate_isolation.py::test_execute_and_panel_routes_use_remote_less_assigned_clone_or_refuse",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py::test_attestation_workflow_is_github_hosted_exact_subject_and_blob_bound",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py::test_codex_execute_command_is_danger_full_access_and_live_repo",
)
PR_B_BOOTSTRAP_CANDIDATE_NODEIDS_SHA256 = "9f5ccd2d7d101f7681e1f93c5c6248502f76859f9c74df9289ecf312497c1bb7"
PR_B_TEST_CONTRACT_FILES: tuple[str, ...] = (
    "phase-loop-runtime/tests/proofgate_tdd_guard.py",
    "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
    "phase-loop-runtime/tests/test_tdd_chronology.py",
    "phase-loop-runtime/tests/test_proofgate_receipts.py",
    "phase-loop-runtime/tests/test_proofgate_isolation.py",
    "phase-loop-runtime/tests/test_proofgate_attestation_workflow.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
)
PR_B_CANDIDATE_ARTIFACTS: tuple[str, ...] = (
    "admin-identity-binding.json",
    "bootstrap-candidate-binding.json",
    "bootstrap-candidate-verdict.json",
    "compat-candidate.junit.xml",
    "phase_reports_candidate.json",
)


def _pr_b_candidate_artifact_names(root: Path) -> tuple[str, ...]:
    review_binding = "selector-repair-review-binding.json"
    return (
        (*PR_B_CANDIDATE_ARTIFACTS, review_binding)
        if (root / review_binding).is_file()
        else PR_B_CANDIDATE_ARTIFACTS
    )


_BOOTSTRAP_ARTIFACTS = (
    "verification.log",
    "compat-default.junit.xml",
    "compat-forced-red.junit.xml",
    "compat-ordinary.junit.xml",
    "compat-attended.junit.xml",
    "ctrl_isolation.log",
    "ctrl_taint.log",
    "ctrl_misuse.log",
    "ctrl_control.log",
    "ctrl_positive_canary.log",
)


def _write_bootstrap_artifacts(repo: Path) -> None:
    exclude = repo / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.writelines(f"/{name}\n" for name in _BOOTSTRAP_ARTIFACTS)
    for name in _BOOTSTRAP_ARTIFACTS:
        (repo / name).write_text(f"unit-double:{name}\n", encoding="utf-8")


@contextmanager
def _coordinator_run_dir(root: Path):
    old_value = os.environ.get("PHASE_LOOP_RUN_DIR")
    os.environ["PHASE_LOOP_RUN_DIR"] = str(root)
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop("PHASE_LOOP_RUN_DIR", None)
        else:
            os.environ["PHASE_LOOP_RUN_DIR"] = old_value


def _setup_git_repo():
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, check=True)
    _write_bootstrap_artifacts(repo)

    readme = repo / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Genesis commit"], cwd=repo, capture_output=True, check=True)
    base_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()
    return tmp, repo, base_oid


def _valid_pr_metadata(head_oid: str, base_oid: str, landing_kind: str) -> dict:
    head_ref = "proofgate-pr-t" if landing_kind == "PR-T" else "proofgate-pr-b"
    return {
        "number": 101,
        "repo": COORDINATOR_REPOSITORY,
        "head_ref": head_ref,
        "base_ref": "main",
        "head_sha": head_oid,
        "base_sha": base_oid,
    }


def _valid_seats(target_digest: str) -> tuple[dict, list]:
    records = {
        "fable": {
            "verdict": "AGREE",
            "substantive": True,
            "candidate_digest": target_digest,
            "attester": "fable",
            "run_identity": "run_fable_101",
            "is_author": False,
            "independent_attestor": True,
        },
        "gpt-5.6-sol": {
            "verdict": "AGREE",
            "substantive": True,
            "candidate_digest": target_digest,
            "attester": "gpt-5.6-sol",
            "run_identity": "run_sol_102",
            "is_author": False,
            "independent_attestor": True,
        },
        "gemini": {
            "verdict": "AGREE",
            "substantive": True,
            "candidate_digest": target_digest,
            "attester": "gemini",
            "run_identity": "run_gemini_103",
            "is_author": True,
            "independent_attestor": False,
        },
        "grok": {
            "verdict": "AGREE",
            "substantive": True,
            "candidate_digest": target_digest,
            "attester": "grok",
            "run_identity": "run_grok_104",
            "is_author": False,
            "independent_attestor": True,
        },
    }
    chronology = ["sol", "grok", "gemini", "fable"]
    return records, chronology


def _chronology_error_type(tdd_chronology):
    error_type = getattr(tdd_chronology, "TddChronologyError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing TddChronologyError")
    return error_type


def _assert_chronology_accepted(tdd_chronology, **kwargs):
    result = tdd_chronology.verify_test_lane_chronology(**kwargs)
    assert isinstance(result, dict), f"verify_test_lane_chronology must return a typed result, got {result!r}"
    assert result.get("schema") == "test_lane_chronology.v1"
    assert result.get("accepted") is True
    assert result.get("decisive") is True
    return result


def _assert_chronology_rejected(tdd_chronology, rejection_code: str, **kwargs):
    """Require the real chronology entrypoint to refuse a named invalid lifecycle."""
    error_type = _chronology_error_type(tdd_chronology)
    try:
        result = tdd_chronology.verify_test_lane_chronology(**kwargs)
    except error_type as exc:
        code = getattr(exc, "code", str(exc))
        assert rejection_code in str(code), f"expected chronology rejection {rejection_code!r}, got {code!r}"
        return
    assert isinstance(result, dict), f"chronology rejection must be typed, not {result!r}"
    assert result.get("schema") == "test_lane_chronology.v1"
    assert result.get("accepted") is False
    assert result.get("rejection_code") == rejection_code
    assert result.get("decisive") is True


def _phase_reports_and_junit(
    mode: str, *, candidate_oid: str = "a" * 40
) -> tuple[str, list[dict], dict | None]:
    """Build canonical, complete artifacts for the decisive bootstrap boundary test."""
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", name="pytest")
    reports: list[dict] = []
    runner_envelope: dict | None = None
    provider_values: dict[str, str] = {}
    if mode == "ordinary_hermetic":
        provider_values = {case: "not_executed_in_ordinary_mode" for case in (
            "fable_subscription_transport_reachable",
            "sol_terra_subscription_transport_reachable",
            "gemini_subscription_transport_reachable",
            "grok_subscription_transport_reachable",
        )}
    elif mode == "attended_live":
        cases = (
            "fable_subscription_transport_reachable",
            "sol_terra_subscription_transport_reachable",
            "gemini_subscription_transport_reachable",
            "grok_subscription_transport_reachable",
        )
        runner_envelope = {
            "runner_stage": "candidate",
            "module_identity": expected_attended_runner_module_identity(),
            "head_identity": candidate_oid,
            "nonces": {case: f"nonce-{index}" for index, case in enumerate(cases)},
            "broker_digests": {case: (str(index) * 64) for index, case in enumerate(cases, 1)},
            "profile_digests": {case: (str(index + 4) * 64) for index, case in enumerate(cases, 1)},
        }
        provider_receipts = {
            case: {
                "schema": "proofgate_attended_provider_receipt.v1",
                "provider_case": case,
                "runner_stage": runner_envelope["runner_stage"],
                "module_identity": runner_envelope["module_identity"],
                "head_identity": runner_envelope["head_identity"],
                "nonce": runner_envelope["nonces"][case],
                "broker_digest": runner_envelope["broker_digests"][case],
                "profile_digest": runner_envelope["profile_digests"][case],
                "first_party_executable_sha256": hashlib.sha256(
                    f"first-party-executable:{case}".encode("utf-8")
                ).hexdigest(),
                "protocol_sha256": hashlib.sha256(
                    f"subscription-protocol:{case}".encode("utf-8")
                ).hexdigest(),
                "process_start_token": f"fresh-process:{case}",
                "request_transcript_sha256": hashlib.sha256(
                    f"request-transcript:{case}".encode("utf-8")
                ).hexdigest(),
                "response_transcript_sha256": hashlib.sha256(
                    f"response-transcript:{case}".encode("utf-8")
                ).hexdigest(),
                "subscription_transport_observed": True,
            }
            for case in sorted(cases)
        }
        runner_envelope["provider_receipts"] = provider_receipts
        runner_envelope["provider_receipts_sha256"] = attended_provider_receipts_digest(
            provider_receipts
        )
        provider_values = {
            case: json.dumps({
                "runner_stage": runner_envelope["runner_stage"],
                "module_identity": runner_envelope["module_identity"],
                "head_identity": runner_envelope["head_identity"],
                "nonce": runner_envelope["nonces"][case],
                "broker_digest": runner_envelope["broker_digests"][case],
                "profile_digest": runner_envelope["profile_digests"][case],
                "fixed_socket": "/run/proofgate/intended-inference.sock",
                "transport_schema": "subscription_auth_transport_adapter.v1",
                "response_provenance": "subscription_transport_broker.v1",
                "request_count": 2,
                "turn_count": 2,
                "tool_round_trip_count": 1,
            }, sort_keys=True)
            for case in cases
        }

    for nodeid in EXPECTED_PHASE_NODEIDS:
        parts = nodeid.replace("phase-loop-runtime/", "").split("::")
        file_mod = parts[0].replace("/", ".").replace(".py", "")
        classname = f"{file_mod}.{parts[1]}" if len(parts) == 3 else file_mod
        testcase = ET.SubElement(suite, "testcase", classname=classname, name=parts[-1])
        properties: dict[str, str] = {}
        if nodeid.endswith("test_provider_projection_allows_only_selected_vendor_subscription_material"):
            properties = provider_values
            if properties:
                props = ET.SubElement(testcase, "properties")
                for name, value in properties.items():
                    ET.SubElement(props, "property", name=name, value=value)

        if mode == "default" and nodeid in DEFAULT_SKIP_NODEIDS:
            ET.SubElement(testcase, "skipped", message="default_skip")
            outcome, exception_type = "skipped", None
        elif mode == "forced_red" and nodeid in RED_CASES_BY_NODEID:
            tag = f"PROOFGATE_RED::{primary_red_case_id(nodeid)}"
            ET.SubElement(testcase, "failure", message=tag).text = tag
            outcome, exception_type = "failed", "AssertionError"
        else:
            outcome, exception_type = "passed", None
        report = {"nodeid": nodeid, "phase": "call", "outcome": outcome, "properties": properties}
        if exception_type is not None:
            report["exception_type"] = exception_type
        reports.append(report)
    return ET.tostring(root, encoding="unicode"), reports, runner_envelope


def _forge_attended_identity(
    junit_xml: str,
    reports: list[dict],
    runner_envelope: dict,
    field: str,
    value: str,
) -> tuple[str, list[dict], dict]:
    forged_reports = json.loads(json.dumps(reports))
    forged_envelope = json.loads(json.dumps(runner_envelope))
    forged_envelope[field] = value
    for receipt in forged_envelope["provider_receipts"].values():
        receipt[field] = value
    forged_envelope["provider_receipts_sha256"] = attended_provider_receipts_digest(
        forged_envelope["provider_receipts"]
    )
    root = ET.fromstring(junit_xml)
    designated = next(
        report
        for report in forged_reports
        if report["nodeid"].endswith(
            "test_provider_projection_allows_only_selected_vendor_subscription_material"
        )
    )
    for prop in root.findall(".//property"):
        if prop.get("name") not in ATTENDED_REAL_PROVIDER_CASES:
            continue
        payload = json.loads(prop.get("value", ""))
        payload[field] = value
        rendered = json.dumps(payload, sort_keys=True)
        prop.set("value", rendered)
        designated["properties"][prop.get("name")] = rendered
    return ET.tostring(root, encoding="unicode"), forged_reports, forged_envelope


def _write_decisive_bootstrap_artifacts(run_dir: Path, candidate_oid: str) -> dict[str, dict]:
    reports_by_mode: dict[str, dict] = {}
    for filename, phase_reports_filename, mode in COORDINATOR_EVIDENCE_ARTIFACTS:
        junit, reports, runner_envelope = _phase_reports_and_junit(
            mode,
            candidate_oid=candidate_oid,
        )
        argv = ["pytest", *coordinator_evidence_capture_pytest_args(mode)]
        for report in reports:
            report["argv"] = argv
            report["command_digest"] = hashlib.sha256(json.dumps(argv).encode("utf-8")).hexdigest()
        (run_dir / filename).write_text(junit, encoding="utf-8")
        reports_by_mode[mode] = {"reports": reports}
        if runner_envelope is not None:
            reports_by_mode[mode]["runner_envelope"] = runner_envelope
        phase_payload = {
            "schema": "proofgate_phase_reports.v1",
            "exitstatus": 1 if mode == "forced_red" else 0,
            "runs": [{"run_identity": f"coordinator-{mode}", "exitstatus": 1 if mode == "forced_red" else 0, "reports": reports}],
            "reports": reports,
            "capture": {
                "schema": "proofgate_coordinator_evidence_capture.v1",
                "plugin": "tests.proofgate_tdd_guard",
                "junit_family": "legacy",
                "junit_filename": filename,
                "junit_sha256": hashlib.sha256((run_dir / filename).read_bytes()).hexdigest(),
                "pytest_args_sha256": hashlib.sha256(
                    json.dumps(list(coordinator_evidence_capture_pytest_args(mode))).encode("utf-8")
                ).hexdigest(),
            },
        }
        if runner_envelope is not None:
            phase_payload["runner_envelope"] = runner_envelope
            (run_dir / ATTENDED_PROVIDER_RECEIPTS_FILENAME).write_text(
                json.dumps(
                    runner_envelope["provider_receipts"],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        (run_dir / phase_reports_filename).write_text(
            json.dumps(phase_payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
    (run_dir / "verification.log").write_text(
        json.dumps({"schema": "proofgate_coordinator_verification_log.v1", "candidate_oid": candidate_oid}, sort_keys=True),
        encoding="utf-8",
    )
    component_bindings = {}
    for component in BOOTSTRAP_CONTROL_COMPONENTS:
        component_path = f"proofgate-reference-{component}.bin"
        component_bytes = (
            ATTENDED_REFERENCE_RUNNER_BYTES
            if component == "code"
            else f"coordinator-reference:{component}:{candidate_oid}".encode("utf-8")
        )
        (run_dir / component_path).write_bytes(component_bytes)
        component_bindings[component] = {
            "path": component_path,
            "sha256": hashlib.sha256(component_bytes).hexdigest(),
        }
    for filename in (
        "ctrl_isolation.log",
        "ctrl_taint.log",
        "ctrl_misuse.log",
        "ctrl_control.log",
        "ctrl_positive_canary.log",
    ):
        raw_observations = {
            case_id: f"coordinator-observed:{case_id}:{candidate_oid}"
            for case_id in BOOTSTRAP_CONTROL_CASES[filename]
        }
        raw_bytes = json.dumps(
            raw_observations,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        raw_path = f"{filename}.raw"
        (run_dir / raw_path).write_bytes(raw_bytes)
        cases = []
        for case_id in BOOTSTRAP_CONTROL_CASES[filename]:
            counters = {
                "connect": 0,
                "dns": 0,
                "downstream_bytes": 0,
                "followup_requests": 0,
                "http": 0,
                "provider_trap": 0,
                "request_count": 0,
                "session_mutations": 0,
                "tls": 0,
                "tool_round_trip_count": 0,
                "turn_count": 0,
            }
            if case_id in BOOTSTRAP_LIVE_REACHABILITY_CASES:
                outcome = "reachable"
                counters.update(
                    {
                        "connect": 1,
                        "dns": 1,
                        "downstream_bytes": 1,
                        "http": 2,
                        "request_count": 2,
                        "tls": 1,
                        "tool_round_trip_count": 1,
                        "turn_count": 2,
                    }
                )
            elif case_id in BOOTSTRAP_ZERO_EFFECT_CASES:
                outcome = "denied"
            else:
                outcome = "verified"
            cases.append(
                {
                    "case_id": case_id,
                    "counters": counters,
                    "expected_outcome": outcome,
                    "observed_outcome": outcome,
                    "path_entered": True,
                    "raw_observation_sha256": hashlib.sha256(
                        raw_observations[case_id].encode("utf-8")
                    ).hexdigest(),
                }
            )
        artifact = {
            "schema": "proofgate_control_artifact.v2",
            "control": filename,
            "candidate_oid": candidate_oid,
            "producer": "proofgate-coordinator-reference",
            "raw_probe_log": {
                "path": raw_path,
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            },
            "components": component_bindings,
            "cases": cases,
            "case_matrix_sha256": hashlib.sha256(
                json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        (run_dir / filename).write_text(
            json.dumps(artifact, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    return reports_by_mode


def _write_coordinator_observation(root: Path, observation: ProofgateBootstrapMergeObservation, landing_kind: str) -> None:
    request = {
        "root": str(root),
        "observation": dataclasses.asdict(observation),
        "landing_kind": landing_kind,
        "producer_schema": BOOTSTRAP_COORDINATOR_PRODUCER_RECEIPT_SCHEMA,
        "repository": COORDINATOR_REPOSITORY,
    }
    writer = """
import hashlib
import json
import os
import sys
from pathlib import Path

request = json.loads(sys.stdin.read())
root = Path(request["root"])
observation = request["observation"]
observation_bytes = json.dumps(
    observation, sort_keys=True, separators=(",", ":"), ensure_ascii=True
).encode("utf-8")
(root / "bootstrap-observation.json").write_bytes(observation_bytes)
producer_receipt = {
    "schema": request["producer_schema"],
    "producer": "proofgate-coordinator",
    "writer_pid": os.getpid(),
    "repository": request["repository"],
    "base_oid": observation["base_oid"],
    "candidate_oid": observation["candidate_oid"],
    "landing_kind": request["landing_kind"],
    "observation_filename": "bootstrap-observation.json",
    "observation_sha256": hashlib.sha256(observation_bytes).hexdigest(),
}
(root / "bootstrap-producer-receipt.json").write_text(
    json.dumps(producer_receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8"
)
"""
    subprocess.run(
        [sys.executable, "-c", writer],
        input=json.dumps(request, sort_keys=True, separators=(",", ":")),
        text=True,
        capture_output=True,
        check=True,
    )


def _freeze_coordinator_root(root: Path) -> None:
    for artifact in root.iterdir():
        if artifact.is_file() and not artifact.is_symlink():
            artifact.chmod(0o444)
    root.chmod(0o555)


def _thaw_coordinator_root(root: Path) -> None:
    root.chmod(0o755)
    for artifact in root.iterdir():
        if artifact.is_file() and not artifact.is_symlink():
            artifact.chmod(0o644)


def _observed_bootstrap_boundary(repo: Path, base_oid: str, candidate_oid: str, github_pr: dict, seats: dict, chronology: list, landing_kind: str):
    coordinator_tmp = tempfile.TemporaryDirectory()
    coordinator_root = Path(coordinator_tmp.name)
    reports_by_mode = _write_decisive_bootstrap_artifacts(coordinator_root, candidate_oid)
    facts = compute_git_source_binding_facts(repo, base_oid, candidate_oid)
    assert facts
    path_scope_digest = hashlib.sha256(
        json.dumps(facts["path_tuples"], separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    junit_digests = tuple(
        (filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest())
        for filename, _phase_reports_filename, _mode in COORDINATOR_EVIDENCE_ARTIFACTS
    )
    phase_report_digests = tuple(
        (filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest())
        for _junit_filename, filename, _mode in COORDINATOR_EVIDENCE_ARTIFACTS
    )
    control_digests = tuple(
        (filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest())
        for filename in ("ctrl_isolation.log", "ctrl_taint.log", "ctrl_misuse.log", "ctrl_control.log", "ctrl_positive_canary.log")
    )
    seat_digests = []
    for seat, filename in COORDINATOR_SEAT_ARTIFACTS:
        (coordinator_root / filename).write_text(
            json.dumps(seats[seat], sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        seat_digests.append((filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest()))
    observation = ProofgateBootstrapMergeObservation(
        schema=BOOTSTRAP_MERGE_OBSERVATION_SCHEMA,
        base_oid=base_oid,
        candidate_oid=candidate_oid,
        change_tuple_digest=facts["change_tuple_digest"],
        path_blob_digest=facts["path_blob_digest"],
        path_scope_digest=path_scope_digest,
        github_pr_json=json.dumps(github_pr, sort_keys=True, separators=(",", ":")),
        seat_records_json=json.dumps(seats, sort_keys=True, separators=(",", ":")),
        seat_chronology=tuple(chronology),
        seat_artifact_digests=tuple(seat_digests),
        junit_artifact_digests=junit_digests,
        junit_phase_report_digests=phase_report_digests,
        junit_phase_reports_json=json.dumps(reports_by_mode, sort_keys=True, separators=(",", ":")),
        control_artifact_digests=control_digests,
    )
    _write_coordinator_observation(coordinator_root, observation, landing_kind)
    _freeze_coordinator_root(coordinator_root)
    return observation, CoordinatorBootstrapMergeObservationBoundary(coordinator_root), coordinator_root, coordinator_tmp


def _candidate_phase_reports_and_junit() -> tuple[str, list[dict]]:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", name="pytest", tests="11", failures="0", errors="0", skipped="0")
    reports: list[dict] = []
    provider_values = {
        case: "not_executed_in_ordinary_mode"
        for case in ATTENDED_REAL_PROVIDER_CASES
    }
    for nodeid in PR_B_BOOTSTRAP_CANDIDATE_NODEIDS:
        parts = nodeid.replace("phase-loop-runtime/", "").split("::")
        file_mod = parts[0].replace("/", ".").replace(".py", "")
        classname = f"{file_mod}.{parts[1]}" if len(parts) == 3 else file_mod
        testcase = ET.SubElement(suite, "testcase", classname=classname, name=parts[-1])
        properties: dict[str, str] = {}
        if nodeid.endswith("test_provider_projection_allows_only_selected_vendor_subscription_material"):
            properties = provider_values
            props = ET.SubElement(testcase, "properties")
            for name, value in properties.items():
                ET.SubElement(props, "property", name=name, value=value)
        report = {"nodeid": nodeid, "phase": "call", "outcome": "passed", "properties": properties}
        reports.append(report)
    return ET.tostring(root, encoding="unicode"), reports


def _pr_b_write_decisive_bootstrap_artifacts(
    run_dir: Path,
    candidate_oid: str,
    repo: Path | None = None,
    base_oid: str | None = None,
    *,
    original_tests_landing_oid: str | None = None,
) -> tuple[dict[str, dict], dict, dict]:
    reports_by_mode: dict[str, dict] = {}
    pr_b_artifacts = (
        ("compat-default.junit.xml", "phase_reports_default.json", "default"),
        ("compat-forced-red.junit.xml", "phase_reports_forced_red.json", "forced_red"),
    )
    nodeids = tuple(nodeid.replace("phase-loop-runtime/", "") for nodeid in EXPECTED_PHASE_NODEIDS)
    for filename, phase_reports_filename, mode in pr_b_artifacts:
        junit, reports, runner_envelope = _phase_reports_and_junit(
            mode,
            candidate_oid=candidate_oid,
        )
        pytest_args = (
            *nodeids,
            "-p",
            "tests.proofgate_tdd_guard",
            "-o",
            "junit_family=legacy",
            f"--junitxml=$PHASE_LOOP_RUN_DIR/{filename}",
            "-q",
        )
        argv = ["pytest", *pytest_args]
        for report in reports:
            report["argv"] = list(argv)
            report["command_digest"] = hashlib.sha256(json.dumps(list(argv)).encode("utf-8")).hexdigest()
        (run_dir / filename).write_text(junit, encoding="utf-8")
        reports_by_mode[mode] = {"reports": reports}
        phase_payload = {
            "schema": "proofgate_phase_reports.v1",
            "exitstatus": 1 if mode == "forced_red" else 0,
            "runs": [{"run_identity": f"coordinator-{mode}", "exitstatus": 1 if mode == "forced_red" else 0, "reports": reports}],
            "reports": reports,
            "capture": {
                "schema": "proofgate_coordinator_evidence_capture.v1",
                "plugin": "tests.proofgate_tdd_guard",
                "junit_family": "legacy",
                "junit_filename": filename,
                "junit_sha256": hashlib.sha256((run_dir / filename).read_bytes()).hexdigest(),
                "pytest_args_sha256": hashlib.sha256(
                    json.dumps(list(pytest_args)).encode("utf-8")
                ).hexdigest(),
            },
        }
        (run_dir / phase_reports_filename).write_text(
            json.dumps(phase_payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )

    cand_junit_xml, cand_reports = _candidate_phase_reports_and_junit()
    cand_junit_filename = "compat-candidate.junit.xml"
    cand_reports_filename = "phase_reports_candidate.json"
    (run_dir / cand_junit_filename).write_text(cand_junit_xml, encoding="utf-8")
    cand_junit_bytes = (run_dir / cand_junit_filename).read_bytes()
    cand_junit_digest = hashlib.sha256(cand_junit_bytes).hexdigest()

    cand_pytest_args = (
        *PR_B_BOOTSTRAP_CANDIDATE_NODEIDS,
        "-p",
        "tests.proofgate_tdd_guard",
        "-o",
        "junit_family=legacy",
        f"--junitxml={run_dir.resolve()}/{cand_junit_filename}",
        "-q",
    )
    cand_argv = ["pytest", *cand_pytest_args]
    cand_cmd_digest = hashlib.sha256(json.dumps(cand_argv).encode("utf-8")).hexdigest()
    for report in cand_reports:
        report["argv"] = list(cand_argv)
        report["command_digest"] = cand_cmd_digest
        report["candidate"] = candidate_oid
        report["run_identity"] = "coordinator-candidate"

    cand_phase_payload = {
        "schema": "proofgate_phase_reports.v1",
        "exitstatus": 0,
        "runs": [{"run_identity": "coordinator-candidate", "exitstatus": 0, "reports": cand_reports}],
        "reports": cand_reports,
        "capture": {
            "schema": "proofgate_coordinator_evidence_capture.v1",
            "plugin": "tests.proofgate_tdd_guard",
            "mode": "bootstrap_candidate",
            "candidate_oid": candidate_oid,
            "run_identity": "coordinator-candidate",
            "junit_family": "legacy",
            "junit_filename": cand_junit_filename,
            "junit_sha256": cand_junit_digest,
            "pytest_args_sha256": hashlib.sha256(
                json.dumps(list(cand_pytest_args)).encode("utf-8")
            ).hexdigest(),
        },
    }
    cand_reports_bytes = json.dumps(cand_phase_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (run_dir / cand_reports_filename).write_bytes(cand_reports_bytes)
    cand_reports_digest = hashlib.sha256(cand_reports_bytes).hexdigest()
    reports_by_mode["bootstrap_candidate"] = {"reports": cand_reports}

    if repo is not None and base_oid is not None:
        diff_raw = subprocess.run(
            ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
        source_digest = hashlib.sha256(diff_raw).hexdigest()
        facts = compute_git_source_binding_facts(repo, base_oid, candidate_oid)
        changes = [
            [kind, path, new_mode, old_blob, new_blob, file_sha]
            for kind, path, _old_mode, new_mode, old_blob, new_blob, file_sha in facts.get("path_tuples", [])
        ]
        contract_digests = {}
        for path in PR_B_TEST_CONTRACT_FILES:
            try:
                content = subprocess.run(
                    ["git", "show", f"{base_oid}:{path}"],
                    cwd=repo,
                    capture_output=True,
                    check=True,
                ).stdout
            except Exception:
                content = f"# contract {path}\n".encode("utf-8")
            contract_digests[path] = hashlib.sha256(content).hexdigest()
        candidate_tree_oid = subprocess.run(
            ["git", "rev-parse", f"{candidate_oid}^{{tree}}"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    else:
        source_digest = hashlib.sha256(f"source:{candidate_oid}".encode("utf-8")).hexdigest()
        changes = []
        contract_digests = {}
        candidate_tree_oid = "0" * 40

    if original_tests_landing_oid is None:
        candidate_binding = {
            "schema": "proofgate_bootstrap_candidate_binding.v1",
            "base_oid": base_oid if base_oid else "0" * 40,
            "candidate_oid": candidate_oid,
            "selector_repair_landing_oid": base_oid if base_oid else "0" * 40,
            "diff_sha256": source_digest,
            "path_scope_sha256": PR_B_BOOTSTRAP_PATHS_SHA256,
            "bootstrap_paths_sha256": PR_B_BOOTSTRAP_PATHS_SHA256,
            "selector_modules_sha256": PR_B_SELECTOR_MODULES_SHA256,
            "selector_nodeids_sha256": PR_B_BOOTSTRAP_CANDIDATE_NODEIDS_SHA256,
            "changes": changes,
            "test_contract_sha256": contract_digests,
        }
        binding_bytes = json.dumps(candidate_binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    else:
        candidate_binding = {
            "schema": "proofgate_bootstrap_candidate_binding.v1",
            "original_tests_landing_oid": original_tests_landing_oid,
            "selector_repair_landing_oid": base_oid if base_oid else "0" * 40,
            "base_oid": base_oid if base_oid else "0" * 40,
            "candidate_oid": candidate_oid,
            "candidate_tree_oid": candidate_tree_oid,
            "diff_sha256": source_digest,
            "path_scope_sha256": PR_B_BOOTSTRAP_PATHS_SHA256,
            "bootstrap_paths_sha256": PR_B_BOOTSTRAP_PATHS_SHA256,
            "selector_modules_sha256": PR_B_SELECTOR_MODULES_SHA256,
            "selector_nodeids_sha256": PR_B_BOOTSTRAP_CANDIDATE_NODEIDS_SHA256,
            "changes": changes,
            "test_contract_sha256": contract_digests,
        }
        binding_bytes = (json.dumps(candidate_binding, separators=(",", ":")) + "\n").encode("utf-8")
    (run_dir / "bootstrap-candidate-binding.json").write_bytes(binding_bytes)
    binding_digest = hashlib.sha256(binding_bytes).hexdigest()
    if repo is not None and original_tests_landing_oid is not None:
        _write_selector_repair_review_binding(
            repo,
            original_tests_landing_oid,
            base_oid,
            run_dir / "selector-repair-review-binding.json",
        )

    candidate_verdict = {
        "schema": "proofgate_bootstrap_candidate_verdict.v1",
        "status": "verified",
        "authorized_scope": "sl0_b1_bootstrap_candidate_only",
        "authorizes_implementation": False,
        "authorizes_final_completion": False,
        "evidence_bindings": ["source", "selector", "binding", "junit", "phase_reports"],
        "source_digest": source_digest,
        "selector_digest": PR_B_BOOTSTRAP_CANDIDATE_NODEIDS_SHA256,
        "binding_digest": binding_digest,
        "junit_digest": cand_junit_digest,
        "phase_reports_digest": cand_reports_digest,
        "collected": 11,
        "passed": 11,
        "skipped": 0,
        "failed": 0,
        "errors": 0,
    }
    (run_dir / "bootstrap-candidate-verdict.json").write_text(
        json.dumps(candidate_verdict, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    claim_policy = {
        "audience": "urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
        "event_name": "workflow_dispatch",
        "repository_id": "1280382652",
        "repository_owner_id": "159201120",
        "workflow_ref": "Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
    }
    claim_policy_digest = hashlib.sha256(json.dumps(claim_policy, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    admin_binding = {
        "schema": "proofgate_admin_identity_binding.v1",
        "authority": "github_and_broker_control_planes",
        "repository_id": "1280382652",
        "repository_name": "Consiliency/agent-harness",
        "app_id": "990001",
        "app_slug": "proofgate-app",
        "installation_id": "880001",
        "reviewer_id": "770001",
        "reviewer_login": "proofgate-reviewer",
        "broker_deployment_id": "proofgate-broker-v1",
        "broker_key_version": "v1",
        "normalized_broker_policy_digest": claim_policy_digest,
        "normalized_github_permissions": (("contents", "write"), ("metadata", "read")),
        "admin_relations": {
            "app_owner_equals_repository_owner": True,
            "installation_app_equals_resolved_app": True,
            "installation_target_equals_app_owner": True,
            "selected_repository_equals_target": True,
            "ruleset_bypass_equals_resolved_app": True,
            "environment_reviewer_equals_active_user": True,
            "broker_relations_match": True,
        },
        "evaluation_partition": {
            "admin_relations": "evaluated",
            "receipt_pilot": "not_evaluated",
        },
    }
    admin_binding["binding_digest"] = hashlib.sha256(json.dumps(admin_binding, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    (run_dir / "admin-identity-binding.json").write_text(
        json.dumps(admin_binding, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    (run_dir / "verification.log").write_text(
        json.dumps({"schema": "proofgate_coordinator_verification_log.v1", "candidate_oid": candidate_oid}, sort_keys=True),
        encoding="utf-8",
    )
    component_bindings = {}
    for component in BOOTSTRAP_CONTROL_COMPONENTS:
        component_path = f"proofgate-reference-{component}.bin"
        component_bytes = (
            ATTENDED_REFERENCE_RUNNER_BYTES
            if component == "code"
            else f"coordinator-reference:{component}:{candidate_oid}".encode("utf-8")
        )
        (run_dir / component_path).write_bytes(component_bytes)
        component_bindings[component] = {
            "path": component_path,
            "sha256": hashlib.sha256(component_bytes).hexdigest(),
        }
    for filename in (
        "ctrl_isolation.log",
        "ctrl_taint.log",
        "ctrl_misuse.log",
        "ctrl_control.log",
        "ctrl_positive_canary.log",
    ):
        raw_observations = {
            case_id: f"coordinator-observed:{case_id}:{candidate_oid}"
            for case_id in BOOTSTRAP_CONTROL_CASES[filename]
        }
        raw_bytes = json.dumps(
            raw_observations,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        raw_path = f"{filename}.raw"
        (run_dir / raw_path).write_bytes(raw_bytes)
        cases = []
        for case_id in BOOTSTRAP_CONTROL_CASES[filename]:
            counters = {
                "connect": 0, "dns": 0, "downstream_bytes": 0, "followup_requests": 0,
                "http": 0, "provider_trap": 0, "request_count": 0, "session_mutations": 0,
                "tls": 0, "tool_round_trip_count": 0, "turn_count": 0,
            }
            if case_id in BOOTSTRAP_LIVE_REACHABILITY_CASES:
                outcome = "reachable"
                counters.update({"connect": 1, "dns": 1, "downstream_bytes": 1, "http": 2, "request_count": 2, "tls": 1, "tool_round_trip_count": 1, "turn_count": 2})
            elif case_id in BOOTSTRAP_ZERO_EFFECT_CASES:
                outcome = "denied"
            else:
                outcome = "verified"
            cases.append({
                "case_id": case_id, "counters": counters, "expected_outcome": outcome, "observed_outcome": outcome, "path_entered": True,
                "raw_observation_sha256": hashlib.sha256(raw_observations[case_id].encode("utf-8")).hexdigest(),
            })
        artifact = {
            "schema": "proofgate_control_artifact.v2", "control": filename, "candidate_oid": candidate_oid, "producer": "proofgate-coordinator-reference",
            "raw_probe_log": {"path": raw_path, "sha256": hashlib.sha256(raw_bytes).hexdigest()}, "components": component_bindings, "cases": cases,
            "case_matrix_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        }
        (run_dir / filename).write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return reports_by_mode, candidate_verdict, admin_binding


def _pr_b_observed_bootstrap_boundary(
    repo: Path,
    base_oid: str,
    candidate_oid: str,
    github_pr: dict,
    seats: dict,
    chronology: list,
    *,
    original_tests_landing_oid: str | None = None,
):
    coordinator_tmp = tempfile.TemporaryDirectory()
    coordinator_root = Path(coordinator_tmp.name)
    reports_by_mode, _candidate_verdict, _admin_binding = _pr_b_write_decisive_bootstrap_artifacts(
        coordinator_root,
        candidate_oid,
        repo=repo,
        base_oid=base_oid,
        original_tests_landing_oid=original_tests_landing_oid,
    )
    facts = compute_git_source_binding_facts(repo, base_oid, candidate_oid)
    assert facts
    path_scope_digest = hashlib.sha256(
        json.dumps(facts["path_tuples"], separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    pr_b_artifacts = (
        ("compat-default.junit.xml", "phase_reports_default.json", "default"),
        ("compat-forced-red.junit.xml", "phase_reports_forced_red.json", "forced_red"),
    )
    junit_digests = tuple(
        (filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest())
        for filename, _phase_reports_filename, _mode in pr_b_artifacts
    )
    phase_report_digests = tuple(
        (filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest())
        for _junit_filename, filename, _mode in pr_b_artifacts
    )
    candidate_artifact_digests = tuple(
        (filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest())
        for filename in _pr_b_candidate_artifact_names(coordinator_root)
    )
    control_digests = tuple(
        (filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest())
        for filename in ("ctrl_isolation.log", "ctrl_taint.log", "ctrl_misuse.log", "ctrl_control.log", "ctrl_positive_canary.log")
    )
    seat_digests = []
    for seat, filename in COORDINATOR_SEAT_ARTIFACTS:
        (coordinator_root / filename).write_text(
            json.dumps(seats[seat], sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        seat_digests.append((filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest()))
    observation = ProofgateBootstrapMergeObservation(
        schema=BOOTSTRAP_MERGE_OBSERVATION_SCHEMA,
        base_oid=base_oid,
        candidate_oid=candidate_oid,
        change_tuple_digest=facts["change_tuple_digest"],
        path_blob_digest=facts["path_blob_digest"],
        path_scope_digest=path_scope_digest,
        github_pr_json=json.dumps(github_pr, sort_keys=True, separators=(",", ":")),
        seat_records_json=json.dumps(seats, sort_keys=True, separators=(",", ":")),
        seat_chronology=tuple(chronology),
        seat_artifact_digests=tuple(seat_digests),
        junit_artifact_digests=junit_digests,
        junit_phase_report_digests=phase_report_digests,
        junit_phase_reports_json=json.dumps(reports_by_mode, sort_keys=True, separators=(",", ":")),
        control_artifact_digests=control_digests,
        candidate_artifact_digests=candidate_artifact_digests,
    )
    _write_coordinator_observation(coordinator_root, observation, "PR-B")
    _freeze_coordinator_root(coordinator_root)
    return observation, CoordinatorBootstrapMergeObservationBoundary(coordinator_root), coordinator_root, coordinator_tmp


def test_chronology_requires_two_parent_tests_bootstrap_and_implementation_landings(
    monkeypatch,
):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_requires_two_parent_tests_bootstrap_and_implementation_landings"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        tmp, repo, base_oid = _setup_git_repo()

        # Build real PR-T branch with exact 18 files
        assert len(PR_T_18_PATHS) == 18
        assert all("*" not in path for path in PR_T_18_PATHS)
        assert "phase-loop-runtime/tests/fixtures/proofgate/v10-proofgate-mutations.json" in PR_T_18_PATHS
        subprocess.run(["git", "checkout", "-b", "proofgate-pr-t"], cwd=repo, capture_output=True, check=True)
        for rel_path in PR_T_18_PATHS:
            full_p = repo / rel_path
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(f"# {rel_path}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-T test landing"], cwd=repo, capture_output=True, check=True)
        cand_t_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_t_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest = hashlib.sha256(diff_raw).hexdigest()
        pr_meta = _valid_pr_metadata(cand_t_oid, base_oid, "PR-T")
        seats, chron = _valid_seats(target_digest)

        # The real Git tuple/path scope, exact PR identity, four seat digests, four
        # JUnits and five control artifacts jointly authorize the pre-merge boundary.
        observation, boundary, coordinator_root, _coordinator_tmp = _observed_bootstrap_boundary(
            repo, base_oid, cand_t_oid, pr_meta, seats, chron, "PR-T"
        )
        with _coordinator_run_dir(coordinator_root):
            decisive = verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, cand_t_oid, landing_kind="PR-T", boundary=boundary
            )
            assert decisive["decisive"] is True
            assert decisive["evidence_kind"] == "coordinator_external_observation"
            assert decisive["authorized"] is True
            assert len(boundary.calls) == 1

            # A recording in-process object cannot become external authority by changing its
            # label, and a coordinator root inside the candidate repository is caller-local.
            with pytest.raises(ProofgateBootstrapVerifierError, match="operational coordinator boundary"):
                verify_observed_premerge_bootstrap_review_gate(
                    repo,
                    base_oid,
                    cand_t_oid,
                    landing_kind="PR-T",
                    boundary=RecordingBootstrapMergeObservationBoundary(observation),
                )
            caller_local_root = repo / ".candidate-local-coordinator"
            caller_local_root.mkdir()
            with pytest.raises(ProofgateBootstrapVerifierError, match="outside the candidate repository"):
                verify_observed_premerge_bootstrap_review_gate(
                    repo,
                    base_oid,
                    cand_t_oid,
                    landing_kind="PR-T",
                    boundary=CoordinatorBootstrapMergeObservationBoundary(caller_local_root),
                )

            _thaw_coordinator_root(coordinator_root)
            with pytest.raises(ProofgateBootstrapVerifierError, match="caller-writable"):
                verify_observed_premerge_bootstrap_review_gate(
                    repo, base_oid, cand_t_oid, landing_kind="PR-T", boundary=boundary
                )
            _freeze_coordinator_root(coordinator_root)

            # The direct same-branch metadata attack has matching caller and observation bytes,
            # but still fails the independent landing-kind ref policy.
            same_branch_pr = dict(pr_meta)
            same_branch_pr["head_ref"] = "main"
            same_branch_pr["base_ref"] = "main"
            _same_observation, same_boundary, same_root, _same_tmp = _observed_bootstrap_boundary(
                repo, base_oid, cand_t_oid, same_branch_pr, seats, chron, "PR-T"
            )
            with _coordinator_run_dir(same_root), pytest.raises(
                ProofgateBootstrapVerifierError, match="GitHub PR identity is not candidate-bound"
            ):
                verify_observed_premerge_bootstrap_review_gate(
                    repo, base_oid, cand_t_oid, landing_kind="PR-T", boundary=same_boundary
                )

            altered_seats = json.loads(observation.seat_records_json)
            altered_seats["fable"]["candidate_digest"] = "0" * 64
            invalid_observations = (
                dataclasses.replace(observation, change_tuple_digest="0" * 64),
                dataclasses.replace(observation, path_scope_digest="0" * 64),
                dataclasses.replace(
                    observation,
                    seat_records_json=json.dumps(altered_seats, sort_keys=True, separators=(",", ":")),
                ),
                dataclasses.replace(
                    observation,
                    junit_phase_reports_json=json.dumps({"default": {"reports": []}}, sort_keys=True, separators=(",", ":")),
                ),
            )
            for invalid_observation in invalid_observations:
                _invalid_tmp = tempfile.TemporaryDirectory()
                invalid_root = Path(_invalid_tmp.name)
                shutil.copytree(coordinator_root, invalid_root, dirs_exist_ok=True)
                _thaw_coordinator_root(invalid_root)
                _write_coordinator_observation(invalid_root, invalid_observation, "PR-T")
                _freeze_coordinator_root(invalid_root)
                with _coordinator_run_dir(invalid_root), pytest.raises(ProofgateBootstrapVerifierError):
                    verify_observed_premerge_bootstrap_review_gate(
                        repo,
                        base_oid,
                        cand_t_oid,
                        landing_kind="PR-T",
                        boundary=CoordinatorBootstrapMergeObservationBoundary(invalid_root),
                    )

            # A caller cannot replace the probe matrix with a clean label, omit a case,
            # or make a positive transport row effect-free even after recomputing every
            # caller-visible artifact and observation digest.
            for label, mutate_control in (
                (
                    "clean-label",
                    lambda _payload: {
                        "schema": "proofgate_control_artifact.v1",
                        "control": "ctrl_isolation.log",
                        "candidate_oid": cand_t_oid,
                        "status": "passed",
                    },
                ),
                (
                    "missing-case",
                    lambda payload: {**payload, "cases": payload["cases"][:-1]},
                ),
                (
                    "vacuous-positive",
                    lambda payload: {
                        **payload,
                        "cases": [
                            {
                                **record,
                                "counters": {key: 0 for key in record["counters"]},
                            }
                            if record["case_id"] in BOOTSTRAP_LIVE_REACHABILITY_CASES
                            else record
                            for record in payload["cases"]
                        ],
                    },
                ),
            ):
                _control_tmp = tempfile.TemporaryDirectory()
                control_root = Path(_control_tmp.name)
                shutil.copytree(coordinator_root, control_root, dirs_exist_ok=True)
                _thaw_coordinator_root(control_root)
                control_filename = (
                    "ctrl_positive_canary.log"
                    if label == "vacuous-positive"
                    else "ctrl_isolation.log"
                )
                control_path = control_root / control_filename
                original_control = json.loads(control_path.read_text(encoding="utf-8"))
                changed_control = mutate_control(original_control)
                if changed_control.get("schema") == "proofgate_control_artifact.v2":
                    changed_control["case_matrix_sha256"] = hashlib.sha256(
                        json.dumps(
                            changed_control["cases"],
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                control_path.write_text(
                    json.dumps(changed_control, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                changed_digests = tuple(
                    (
                        artifact_name,
                        hashlib.sha256((control_root / artifact_name).read_bytes()).hexdigest(),
                    )
                    for artifact_name, _digest in observation.control_artifact_digests
                )
                changed_observation = dataclasses.replace(
                    observation,
                    control_artifact_digests=changed_digests,
                )
                _write_coordinator_observation(control_root, changed_observation, "PR-T")
                _freeze_coordinator_root(control_root)
                with _coordinator_run_dir(control_root), pytest.raises(
                    ProofgateBootstrapVerifierError
                ):
                    verify_observed_premerge_bootstrap_review_gate(
                        repo,
                        base_oid,
                        cand_t_oid,
                        landing_kind="PR-T",
                        boundary=CoordinatorBootstrapMergeObservationBoundary(control_root),
                    )

            # Recomputing every component/control/observation digest cannot make
            # different coordinator reference code match the attended runner identity.
            _code_tmp = tempfile.TemporaryDirectory()
            code_root = Path(_code_tmp.name)
            shutil.copytree(coordinator_root, code_root, dirs_exist_ok=True)
            _thaw_coordinator_root(code_root)
            changed_code = b"attacker-controlled-proofgate-reference-runner"
            (code_root / "proofgate-reference-code.bin").write_bytes(changed_code)
            changed_code_digest = hashlib.sha256(changed_code).hexdigest()
            for control_filename, _digest in observation.control_artifact_digests:
                control_path = code_root / control_filename
                control_payload = json.loads(control_path.read_text(encoding="utf-8"))
                control_payload["components"]["code"]["sha256"] = changed_code_digest
                control_path.write_text(
                    json.dumps(control_payload, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
            changed_control_digests = tuple(
                (
                    artifact_name,
                    hashlib.sha256((code_root / artifact_name).read_bytes()).hexdigest(),
                )
                for artifact_name, _digest in observation.control_artifact_digests
            )
            changed_observation = dataclasses.replace(
                observation,
                control_artifact_digests=changed_control_digests,
            )
            _write_coordinator_observation(code_root, changed_observation, "PR-T")
            _freeze_coordinator_root(code_root)
            with _coordinator_run_dir(code_root), pytest.raises(
                ProofgateBootstrapVerifierError,
                match="attended runner identity does not match coordinator code bytes",
            ):
                verify_observed_premerge_bootstrap_review_gate(
                    repo,
                    base_oid,
                    cand_t_oid,
                    landing_kind="PR-T",
                    boundary=CoordinatorBootstrapMergeObservationBoundary(code_root),
                )

        # Land PR-T via a real two-parent merge only after its pre-merge gate succeeds.
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "merge", "--no-ff", "proofgate-pr-t", "-m", "Merge PR-T"], cwd=repo, capture_output=True, check=True)
        landing_t_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        # The same decisive boundary must be usable before the separately reviewed,
        # production-only PR-B five-path landing.
        subprocess.run(["git", "checkout", "-b", "proofgate-pr-b", landing_t_oid], cwd=repo, capture_output=True, check=True)
        for rel_path in PR_B_5_PATHS:
            full_p = repo / rel_path
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(f"# bootstrap {rel_path}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-B bootstrap landing"], cwd=repo, capture_output=True, check=True)
        cand_b_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()
        pr_b_meta = _valid_pr_metadata(cand_b_oid, landing_t_oid, "PR-B")
        pr_b_digest = hashlib.sha256(
            subprocess.run(
                ["git", "diff-tree", "--raw", "-r", "-z", landing_t_oid, cand_b_oid],
                cwd=repo,
                capture_output=True,
                check=True,
            ).stdout
        ).hexdigest()
        pr_b_seats, pr_b_chronology = _valid_seats(pr_b_digest)
        _observation_b, boundary_b, coordinator_root_b, _coordinator_tmp_b = _pr_b_observed_bootstrap_boundary(
            repo,
            landing_t_oid,
            cand_b_oid,
            pr_b_meta,
            pr_b_seats,
            pr_b_chronology,
            original_tests_landing_oid=base_oid,
        )

        # Explicitly assert pre-marker accounting/default topology: default 3/36, forced RED 2/37, candidate 11/11/0/0/0;
        # ordinary and attended-live artifacts are absent and must not be required or accepted.
        assert not (coordinator_root_b / "proofgate-candidate-ordinary.junit.xml").exists()
        assert not (coordinator_root_b / "proofgate-candidate-attended.junit.xml").exists()
        assert not (coordinator_root_b / "compat-ordinary.junit.xml").exists()
        assert not (coordinator_root_b / "compat-attended.junit.xml").exists()

        reports_by_mode_b = json.loads(
            (coordinator_root_b / "bootstrap-observation.json").read_text(encoding="utf-8")
        ).get("junit_phase_reports_json", "{}")
        reports_by_mode_b_dict = json.loads(reports_by_mode_b) if isinstance(reports_by_mode_b, str) else reports_by_mode_b

        def_acc = verify_junit_accounting(
            (coordinator_root_b / "compat-default.junit.xml").read_text(encoding="utf-8"),
            mode="default",
            phase_reports=reports_by_mode_b_dict["default"]["reports"],
        )
        assert (def_acc["collected"], def_acc["passed"], def_acc["skipped"], def_acc["failed"]) == (39, 3, 36, 0)

        red_acc = verify_junit_accounting(
            (coordinator_root_b / "compat-forced-red.junit.xml").read_text(encoding="utf-8"),
            mode="forced_red",
            phase_reports=reports_by_mode_b_dict["forced_red"]["reports"],
        )
        assert (red_acc["collected"], red_acc["passed"], red_acc["skipped"], red_acc["failed"]) == (39, 2, 0, 37)

        cand_acc = verify_junit_accounting(
            coordinator_root_b / "compat-candidate.junit.xml",
            mode="bootstrap_candidate",
            phase_reports=coordinator_root_b / "phase_reports_candidate.json",
        )
        assert (cand_acc["collected"], cand_acc["passed"], cand_acc["skipped"], cand_acc["failed"]) == (11, 11, 0, 0)

        # Use a valid PR-R-bound PR-B fixture so this assertion reaches the live
        # admin authority seam instead of passing on an earlier binding defect.
        from . import proofgate_bootstrap_verifier

        (
            _pr_r_tmp,
            pr_r_repo,
            pr_r_original_oid,
            pr_r_base_oid,
            pr_r_candidate_oid,
            pr_r_boundary,
            pr_r_coordinator_root,
            _pr_r_coordinator_tmp,
        ) = _setup_pr_r_candidate_history()
        real_verify_binding = proofgate_bootstrap_verifier.verify_bootstrap_candidate_binding

        def verify_binding_from_frozen_original(
            repo_path, binding_path, expected_original_tests_landing=None
        ):
            return real_verify_binding(
                repo_path=repo_path,
                binding_path=binding_path,
                expected_original_tests_landing=pr_r_original_oid,
            )

        monkeypatch.setattr(
            proofgate_bootstrap_verifier,
            "verify_bootstrap_candidate_binding",
            verify_binding_from_frozen_original,
        )
        monkeypatch.setattr(
            proofgate_bootstrap_verifier,
            "verify_proofgate_admin_authority",
            lambda **_kwargs: (_ for _ in ()).throw(
                ProofgateBootstrapVerifierError(
                    "PANEL-R2::live_admin_authority_seam_reached"
                )
            ),
        )
        with _coordinator_run_dir(pr_r_coordinator_root), pytest.raises(
            ProofgateBootstrapVerifierError,
            match="PANEL-R2::live_admin_authority_seam_reached",
        ):
            verify_observed_premerge_bootstrap_review_gate(
                pr_r_repo,
                pr_r_base_oid,
                pr_r_candidate_oid,
                landing_kind="PR-B",
                boundary=pr_r_boundary,
            )

        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "merge", "--no-ff", "proofgate-pr-b", "-m", "Merge PR-B"], cwd=repo, capture_output=True, check=True)

        with pytest.raises(ProofgateBootstrapVerifierError, match="operational coordinator boundary"):
            verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, cand_t_oid, landing_kind="PR-T", boundary=object()
            )

        # Landed verification on 2-parent merge must succeed
        res = verify_landed_bootstrap_source_binding(repo, landing_t_oid, base_oid, cand_t_oid, pr_meta, seats, chron, landing_kind="PR-T")
        assert res["decisive"] is False
        assert res["evidence_kind"] == "unit_double"

        # Rejection test: single-parent (squash) merge must fail
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        readme = repo / "README.md"
        readme.write_text("# Test Repo Updated\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "Squash direct commit"], cwd=repo, capture_output=True, check=True)
        squash_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        with pytest.raises(ProofgateBootstrapVerifierError, match="two_parent_landing_required"):
            verify_landed_bootstrap_source_binding(repo, squash_oid, base_oid, cand_t_oid, pr_meta, seats, chron, landing_kind="PR-T")

        _assert_chronology_accepted(
            tdd_chronology,
            repo_path=repo,
            landing_oid=landing_t_oid,
            base_oid=base_oid,
            candidate_oid=cand_t_oid,
            github_pr=pr_meta,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-T",
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "two_parent_landing_required",
            repo_path=repo,
            landing_oid=squash_oid,
            base_oid=base_oid,
            candidate_oid=cand_t_oid,
            github_pr=pr_meta,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-T",
        )

    run_proofgate_contract(nodeid, _contract)


def test_chronology_rejects_tests_only_range_with_non_test_bytes():
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_tests_only_range_with_non_test_bytes"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        tmp, repo, base_oid = _setup_git_repo()

        subprocess.run(["git", "checkout", "-b", "pr-t-bad"], cwd=repo, capture_output=True, check=True)
        for rel_path in PR_T_18_PATHS:
            full_p = repo / rel_path
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(f"# {rel_path}\n", encoding="utf-8")

        # Inject non-test file (production file)
        prod_file = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "runner.py"
        prod_file.parent.mkdir(parents=True, exist_ok=True)
        prod_file.write_text("# prod file edit\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-T with prod file"], cwd=repo, capture_output=True, check=True)
        cand_bad_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_bad_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest = hashlib.sha256(diff_raw).hexdigest()
        pr_meta = _valid_pr_metadata(cand_bad_oid, base_oid, "PR-T")
        seats, chron = _valid_seats(target_digest)

        with pytest.raises(ProofgateBootstrapVerifierError, match="PR-T candidate contains unauthorized non-test path"):
            verify_premerge_bootstrap_review_gate(repo, base_oid, cand_bad_oid, pr_meta, seats, chron, landing_kind="PR-T")

        _assert_chronology_rejected(
            tdd_chronology,
            "pr_t_tests_only_path_scope",
            repo_path=repo,
            base_oid=base_oid,
            candidate_oid=cand_bad_oid,
            github_pr=pr_meta,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-T",
        )

    run_proofgate_contract(nodeid, _contract)


def test_chronology_rejects_bootstrap_range_outside_frozen_set_or_test_edit():
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_bootstrap_range_outside_frozen_set_or_test_edit"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        tmp, repo, base_oid = _setup_git_repo()

        # Case A: Edit test file inside bootstrap PR
        subprocess.run(["git", "checkout", "-b", "pr-b-bad-test"], cwd=repo, capture_output=True, check=True)
        test_file = repo / "phase-loop-runtime" / "tests" / "test_proofgate_receipts.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("# bad edit\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-B edit test"], cwd=repo, capture_output=True, check=True)
        cand_b_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_b_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest = hashlib.sha256(diff_raw).hexdigest()
        pr_meta = _valid_pr_metadata(cand_b_oid, base_oid, "PR-B")
        seats, chron = _valid_seats(target_digest)

        # Bootstrap range verification must reject test file edit or paths outside frozen bootstrap set
        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_premerge_bootstrap_review_gate(repo, base_oid, cand_b_oid, pr_meta, seats, chron, landing_kind="PR-B")

        # Case B: Edit non-bootstrap production file
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "checkout", "-b", "pr-b-bad-prod"], cwd=repo, capture_output=True, check=True)
        prod_file = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "goal_coverage.py"
        prod_file.parent.mkdir(parents=True, exist_ok=True)
        prod_file.write_text("# bad edit\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-B edit non-bootstrap prod file"], cwd=repo, capture_output=True, check=True)
        cand_b_prod_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw2 = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_b_prod_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest2 = hashlib.sha256(diff_raw2).hexdigest()
        pr_meta2 = _valid_pr_metadata(cand_b_prod_oid, base_oid, "PR-B")
        seats2, chron2 = _valid_seats(target_digest2)

        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_premerge_bootstrap_review_gate(repo, base_oid, cand_b_prod_oid, pr_meta2, seats2, chron2, landing_kind="PR-B")

        _assert_chronology_rejected(
            tdd_chronology,
            "pr_b_bootstrap_path_scope",
            repo_path=repo,
            base_oid=base_oid,
            candidate_oid=cand_b_oid,
            github_pr=pr_meta,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-B",
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "pr_b_bootstrap_path_scope",
            repo_path=repo,
            base_oid=base_oid,
            candidate_oid=cand_b_prod_oid,
            github_pr=pr_meta2,
            seat_records=seats2,
            seat_chronology=chron2,
            landing_kind="PR-B",
        )

    run_proofgate_contract(nodeid, _contract)


def test_chronology_rejects_implementation_range_test_guard_selector_nodeid_count_or_anchor_edit():
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_implementation_range_test_guard_selector_nodeid_count_or_anchor_edit"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        tmp, repo, base_oid = _setup_git_repo()

        # Case A: Guard file edit in PR-I
        subprocess.run(["git", "checkout", "-b", "pr-i-bad"], cwd=repo, capture_output=True, check=True)
        guard_file = repo / "phase-loop-runtime" / "tests" / "proofgate_tdd_guard.py"
        guard_file.parent.mkdir(parents=True, exist_ok=True)
        guard_file.write_text(
            "EXPECTED_PHASE_NODEIDS = ()\n"
            "DEFAULT_SKIP_NODEIDS = ()\n"
            "RED_CASES_BY_NODEID = {}\n"
            "PROOFGATE_SOURCE_ANCHOR_ROWS_V1 = ()\n"
            "def proofgate_test_selection(): return ()\n",
            encoding="utf-8",
        )

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-I edit guard"], cwd=repo, capture_output=True, check=True)
        cand_i_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_i_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest = hashlib.sha256(diff_raw).hexdigest()
        pr_meta = _valid_pr_metadata(cand_i_oid, base_oid, "PR-T")
        seats, chron = _valid_seats(target_digest)

        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_premerge_bootstrap_review_gate(repo, base_oid, cand_i_oid, pr_meta, seats, chron, landing_kind="PR-T")

        # Case B: Test file edit in PR-I
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "checkout", "-b", "pr-i-bad-test"], cwd=repo, capture_output=True, check=True)
        test_file = repo / "phase-loop-runtime" / "tests" / "test_tdd_chronology.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("# edit test\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-I edit test"], cwd=repo, capture_output=True, check=True)
        cand_i_test_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw2 = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_i_test_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest2 = hashlib.sha256(diff_raw2).hexdigest()
        pr_meta2 = _valid_pr_metadata(cand_i_test_oid, base_oid, "PR-T")
        seats2, chron2 = _valid_seats(target_digest2)

        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_premerge_bootstrap_review_gate(repo, base_oid, cand_i_test_oid, pr_meta2, seats2, chron2, landing_kind="PR-T")

        _assert_chronology_rejected(
            tdd_chronology,
            "pr_i_immutable_test_surface",
            repo_path=repo,
            base_oid=base_oid,
            candidate_oid=cand_i_oid,
            github_pr=pr_meta,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-I",
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "pr_i_immutable_test_surface",
            repo_path=repo,
            base_oid=base_oid,
            candidate_oid=cand_i_test_oid,
            github_pr=pr_meta2,
            seat_records=seats2,
            seat_chronology=chron2,
            landing_kind="PR-I",
        )

    run_proofgate_contract(nodeid, _contract)


def test_chronology_rejects_same_branch_squash_rebase_direct_push_copy_or_hidden_parent():
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_chronology_rejects_same_branch_squash_rebase_direct_push_copy_or_hidden_parent"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        tmp, repo, base_oid = _setup_git_repo()

        subprocess.run(["git", "checkout", "-b", "pr-t-branch"], cwd=repo, capture_output=True, check=True)
        for rel_path in PR_T_18_PATHS:
            full_p = repo / rel_path
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(f"# {rel_path}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-T test landing"], cwd=repo, capture_output=True, check=True)
        cand_t_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_t_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest = hashlib.sha256(diff_raw).hexdigest()
        pr_meta = _valid_pr_metadata(cand_t_oid, base_oid, "PR-T")
        seats, chron = _valid_seats(target_digest)

        # Case 1: Single parent commit on main (squash) fails
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "merge", "--squash", "pr-t-branch"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Squashed commit"], cwd=repo, capture_output=True, check=True)
        squash_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        with pytest.raises(ProofgateBootstrapVerifierError, match="two_parent_landing_required"):
            verify_landed_bootstrap_source_binding(repo, squash_oid, base_oid, cand_t_oid, pr_meta, seats, chron, landing_kind="PR-T")

        # Case 2: Direct commit on main fails
        readme = repo / "README.md"
        readme.write_text("# Direct push update\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "Direct commit on main"], cwd=repo, capture_output=True, check=True)
        direct_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_landed_bootstrap_source_binding(repo, direct_oid, base_oid, cand_t_oid, pr_meta, seats, chron, landing_kind="PR-T")

        # Case 3: Same branch PR metadata fails
        same_branch_pr = dict(pr_meta)
        same_branch_pr["head_ref"] = "main"
        same_branch_pr["base_ref"] = "main"
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(
                {
                    "candidate_oid": cand_t_oid,
                    "base_oid": base_oid,
                    "path_blob_digest": "1" * 64,
                    "change_tuple_digest": target_digest,
                    "topology": {"two_parent": True, "every_parent_present": True, "parent_oids": [base_oid, cand_t_oid]},
                    "seat_records": seats,
                    "seat_chronology": chron,
                    "author_vendor": "gemini",
                    "raw_log_digest": "0" * 64,
                    "junit_mode_digests": {"default": "0" * 64, "forced_red": "0" * 64, "ordinary": "0" * 64, "attended": "0" * 64},
                    "control_digests": {"isolation": "0" * 64, "taint": "0" * 64, "misuse": "0" * 64, "control": "0" * 64, "positive_canary": "0" * 64},
                    "github_pr": same_branch_pr,
                },
                expected_head_ref="proofgate-pr-t",
            )

        # Case 4: Wrong parent order fails
        with pytest.raises(ProofgateBootstrapVerifierError, match="base_oid"):
            evaluate_unit_double_bootstrap_merge_review_gate({
                "candidate_oid": cand_t_oid,
                "base_oid": base_oid,
                "path_blob_digest": "1" * 64,
                "change_tuple_digest": target_digest,
                "topology": {"two_parent": True, "every_parent_present": True, "parent_oids": [cand_t_oid, base_oid]},
                "seat_records": seats,
                "seat_chronology": chron,
                "author_vendor": "gemini",
                "raw_log_digest": "0" * 64,
                "junit_mode_digests": {"default": "0" * 64, "forced_red": "0" * 64, "ordinary": "0" * 64, "attended": "0" * 64},
                "control_digests": {"isolation": "0" * 64, "taint": "0" * 64, "misuse": "0" * 64, "control": "0" * 64, "positive_canary": "0" * 64},
                "github_pr": pr_meta,
            })

        # Case 5: Landing resolution byte drift fails
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "reset", "--hard", base_oid], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "merge", "--no-ff", "pr-t-branch", "-m", "Merge PR-T drift"], cwd=repo, capture_output=True, check=True)
        drift_file = repo / "README.md"
        drift_file.write_text("# Drifted landing\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "Drift commit"], cwd=repo, capture_output=True, check=True)
        drift_landing_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_landed_bootstrap_source_binding(repo, drift_landing_oid, base_oid, cand_t_oid, pr_meta, seats, chron, landing_kind="PR-T")

        _assert_chronology_rejected(
            tdd_chronology,
            "two_parent_landing_required",
            repo_path=repo,
            landing_oid=squash_oid,
            base_oid=base_oid,
            candidate_oid=cand_t_oid,
            github_pr=pr_meta,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-T",
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "direct_landing_required",
            repo_path=repo,
            landing_oid=direct_oid,
            base_oid=base_oid,
            candidate_oid=cand_t_oid,
            github_pr=pr_meta,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-T",
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "same_branch_landing",
            repo_path=repo,
            base_oid=base_oid,
            candidate_oid=cand_t_oid,
            github_pr=same_branch_pr,
            seat_records=seats,
            seat_chronology=chron,
            landing_kind="PR-T",
        )

    run_proofgate_contract(nodeid, _contract)


def test_candidate_snapshot_is_source_head_parented_and_rematerializes_byte_identically():
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_candidate_snapshot_is_source_head_parented_and_rematerializes_byte_identically"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        tmp, repo, base_oid = _setup_git_repo()

        subprocess.run(["git", "checkout", "-b", "candidate-snapshot"], cwd=repo, capture_output=True, check=True)
        test_file = repo / "phase-loop-runtime" / "tests" / "proofgate_bootstrap_verifier.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        content = b"# candidate snapshot content\n"
        test_file.write_bytes(content)
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Candidate snapshot"], cwd=repo, capture_output=True, check=True)
        cand_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        # Check commit parent equals base_oid
        cat_proc = subprocess.run(["git", "cat-file", "-p", cand_oid], cwd=repo, capture_output=True, check=True)
        commit_header = cat_proc.stdout.decode()
        parents = [line.split()[1] for line in commit_header.splitlines() if line.startswith("parent ")]
        assert len(parents) == 1
        assert parents[0] == base_oid

        # Check rematerialized bytes match
        ls_proc = subprocess.run(["git", "ls-tree", "-r", cand_oid], cwd=repo, capture_output=True, check=True)
        lines = ls_proc.stdout.decode().splitlines()
        found_blob = None
        for line in lines:
            if "proofgate_bootstrap_verifier.py" in line:
                found_blob = line.split()[2]
                break
        assert found_blob is not None
        cat_blob = subprocess.run(["git", "cat-file", "-p", found_blob], cwd=repo, capture_output=True, check=True).stdout
        assert cat_blob == content

        _assert_chronology_accepted(
            tdd_chronology,
            repo_path=repo,
            base_oid=base_oid,
            candidate_oid=cand_oid,
            lifecycle_stage="candidate_snapshot",
        )

    run_proofgate_contract(nodeid, _contract)


def test_fresh_process_lifecycle_rejects_builder_stale_head_loaded_parent_or_same_process():
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_fresh_process_lifecycle_rejects_builder_stale_head_loaded_parent_or_same_process"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        parent_pid = os.getpid()
        repo_dir = str(Path(__file__).resolve().parents[2])

        # Subprocess probe script
        subproc_script = """
import sys, os, subprocess, hashlib, json
from pathlib import Path

repo_dir = sys.argv[1]
mode = sys.argv[2]
parent_pid = int(sys.argv[3])

if mode == "stale_head":
    sys.stderr.write("fresh_process_required: stale head\\n")
    sys.exit(1)
if mode == "valid":
    head_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True)
    head_sha = head_proc.stdout.strip()
    if not head_sha:
        sys.stderr.write("fresh_process_required: empty HEAD\\n")
        sys.exit(1)

    import phase_loop_runtime
    src_dir = (Path(repo_dir) / "phase-loop-runtime" / "src" / "phase_loop_runtime").resolve()
    mod_digests = {}
    for mod_name, mod_obj in sorted(list(sys.modules.items())):
        mod_file = getattr(mod_obj, "__file__", None)
        if mod_file and isinstance(mod_file, str):
            f_path = Path(mod_file).resolve()
            if src_dir in f_path.parents or f_path.parent == src_dir:
                try:
                    mod_digests[f_path.name] = hashlib.sha256(f_path.read_bytes()).hexdigest()
                except Exception:
                    pass

    if not mod_digests and hasattr(phase_loop_runtime, "__file__") and phase_loop_runtime.__file__:
        p = Path(phase_loop_runtime.__file__).resolve()
        if p.exists():
            mod_digests[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()

    combined_mod_bytes = json.dumps(mod_digests, sort_keys=True).encode("utf-8")
    loaded_modules_digest = hashlib.sha256(combined_mod_bytes).hexdigest()

    mod_path = Path(phase_loop_runtime.__file__).resolve()
    result = {
        "status": "valid",
        "fresh_process": True,
        "pid": os.getpid(),
        "head_sha": head_sha,
        "module_path": str(mod_path),
        "module_digest": loaded_modules_digest,
        "loaded_modules_digests": mod_digests,
        "repository": "Consiliency/agent-harness",
    }
    print(json.dumps(result))
    sys.exit(0)
"""

        # Probe 1: Same process PID check simulation fails
        same_pid_code = f"""
import os, sys
parent_pid = {parent_pid}
curr_pid = parent_pid
if curr_pid == parent_pid:
    sys.stderr.write("fresh_process_required: same process PID\\n")
    sys.exit(1)
"""
        proc_same = subprocess.run(
            [sys.executable, "-c", same_pid_code],
            capture_output=True,
            text=True,
        )
        assert proc_same.returncode == 1
        assert "fresh_process_required: same process PID" in proc_same.stderr

        # Probe 2: Stale head in fresh process fails
        proc_stale = subprocess.run(
            [sys.executable, "-c", subproc_script, repo_dir, "stale_head", str(parent_pid)],
            capture_output=True,
            text=True,
        )
        assert proc_stale.returncode == 1
        assert "fresh_process_required: stale head" in proc_stale.stderr

        # Probe 3: Valid fresh process boundary succeeds
        proc_valid = subprocess.run(
            [sys.executable, "-c", subproc_script, repo_dir, "valid", str(parent_pid)],
            capture_output=True,
            text=True,
        )
        assert proc_valid.returncode == 0, f"Fresh process valid failed: {proc_valid.stderr}"
        res_data = json.loads(proc_valid.stdout)
        assert res_data["status"] == "valid"
        assert res_data["fresh_process"] is True
        assert res_data["pid"] != parent_pid
        assert res_data["repository"] == "Consiliency/agent-harness"
        assert "loaded_modules_digests" in res_data and len(res_data["loaded_modules_digests"]) > 0

        _assert_chronology_rejected(
            tdd_chronology,
            "fresh_process_required",
            repo_path=repo_dir,
            fresh_process_boundary=True,
            parent_pid=parent_pid,
            process_pid=parent_pid,
            head_sha=res_data["head_sha"],
            module_digests=res_data["loaded_modules_digests"],
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "stale_head",
            repo_path=repo_dir,
            fresh_process_boundary=True,
            parent_pid=parent_pid,
            process_pid=res_data["pid"],
            head_sha="0" * 40,
            module_digests=res_data["loaded_modules_digests"],
        )
        _assert_chronology_accepted(
            tdd_chronology,
            repo_path=repo_dir,
            fresh_process_boundary=True,
            parent_pid=parent_pid,
            process_pid=res_data["pid"],
            head_sha=res_data["head_sha"],
            module_digests=res_data["loaded_modules_digests"],
        )

    run_proofgate_contract(nodeid, _contract)


def test_junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips(record_property):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_junit_lifecycle_requires_exact_nodeids_default_skip_red_failures_and_final_zero_skips"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        try:
            from phase_loop_runtime import tdd_chronology
        except ImportError as err:
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology module missing") from err

        if not hasattr(tdd_chronology, "verify_test_lane_chronology"):
            raise ProofgateMissingCapabilityError("phase_loop_runtime.tdd_chronology missing verify_test_lane_chronology capability")

        # Probe 1: Empty JUnit XML must fail
        from .proofgate_tdd_guard import emit_mutation_observable
        try:
            verify_junit_accounting("<testsuite></testsuite>", mode="default")
            emit_mutation_observable("ec-proofgate-0.chronology-guard", record_property)
            raise AssertionError("EC-PROOFGATE-0 chronology guard unwired")
        except ProofgateBootstrapVerifierError:
            pass

        # Probe 2: Phase reports controls (no-report, all-setup, duplicate, mismatch must fail)
        import xml.etree.ElementTree as ET
        root_elem = ET.Element("testsuites")
        ts = ET.SubElement(root_elem, "testsuite", name="pytest", tests="39", failures="0", errors="0", skipped="36")
        for nid in EXPECTED_PHASE_NODEIDS:
            parts = nid.replace("phase-loop-runtime/", "").split("::")
            file_mod = parts[0].replace("/", ".").replace(".py", "")
            classname = f"{file_mod}.{parts[1]}" if len(parts) == 3 else file_mod
            tc = ET.SubElement(ts, "testcase", classname=classname, name=parts[-1])
            if nid in DEFAULT_SKIP_NODEIDS:
                ET.SubElement(tc, "skipped", message="default_skip")
        xml_str = ET.tostring(root_elem, encoding="utf-8").decode("utf-8")

        # 2a: No phase reports supplied must fail
        with pytest.raises(ProofgateBootstrapVerifierError, match="mandatory"):
            verify_junit_accounting(xml_str, mode="default")

        # 2b: All-setup phase reports (phase="setup") must fail
        all_setup_reports = [{"nodeid": nid, "phase": "setup", "outcome": "passed", "properties": {}} for nid in EXPECTED_PHASE_NODEIDS]
        with pytest.raises(ProofgateBootstrapVerifierError, match="phase must be 'call'"):
            verify_junit_accounting(xml_str, mode="default", phase_reports=all_setup_reports)

        # 2c: Duplicate phase report nodeid must fail
        duplicate_nodeid = EXPECTED_PHASE_NODEIDS[0]
        duplicate_outcome = "skipped" if duplicate_nodeid in DEFAULT_SKIP_NODEIDS else "passed"
        dup_reports = [{"nodeid": duplicate_nodeid, "phase": "call", "outcome": duplicate_outcome, "properties": {}}] * 2
        with pytest.raises(ProofgateBootstrapVerifierError, match="Duplicate phase report"):
            verify_junit_accounting(xml_str, mode="default", phase_reports=dup_reports)

        # 2d: Mismatched reports outcome or exception type must fail (repair-24 counterexample 1)
        bad_reports = [
            {"nodeid": nid, "phase": "call", "outcome": "failed", "exception_type": "ValueError", "properties": {}}
            for nid in EXPECTED_PHASE_NODEIDS
        ]
        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_junit_accounting(xml_str, mode="default", phase_reports=bad_reports)


        # Probe 3: Swapped skip set in default mode must fail
        swapped_xml = """<testsuite>
            <testcase classname="phase-loop-runtime.tests.test_proofgate_receipts" name="test_bootstrap_records_are_single_use_and_server_bound"><skipped/></testcase>
        </testsuite>"""
        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_junit_accounting(swapped_xml, mode="default", phase_reports=[{"nodeid": nid, "phase": "call", "outcome": "skipped" if nid in DEFAULT_SKIP_NODEIDS else "passed", "properties": {}} for nid in EXPECTED_PHASE_NODEIDS])

        # Probe 4: Substring-only RED case ID must fail
        substring_red_xml = """<testsuite>
            <testcase classname="phase-loop-runtime.tests.test_proofgate_receipts" name="test_bootstrap_records_are_single_use_and_server_bound">
                <failure message="bootstrap_records_are_single_use_and_server_bound"/>
            </testcase>
        </testsuite>"""
        with pytest.raises(ProofgateBootstrapVerifierError):
            verify_junit_accounting(substring_red_xml, mode="forced_red", phase_reports=[{"nodeid": nid, "phase": "call", "outcome": "failed" if nid in RED_CASES_BY_NODEID else "passed", "exception_type": "AssertionError" if nid in RED_CASES_BY_NODEID else None, "properties": {}} for nid in EXPECTED_PHASE_NODEIDS])

        # Probe 4: Sealed evidence probes for 4-seat merge gate
        valid_evidence = {
            "candidate_oid": "a" * 40,
            "base_oid": "b" * 40,
            "path_blob_digest": "1" * 64,
            "change_tuple_digest": "2" * 64,
            "topology": {"two_parent": True, "every_parent_present": True, "parent_oids": ["b" * 40, "c" * 40]},
            "seat_records": {
                "fable": {"verdict": "AGREE", "substantive": True, "candidate_digest": "2" * 64, "attester": "fable", "run_identity": "run_id_fable_101", "is_author": False, "independent_attestor": True},
                "gpt-5.6-sol": {"verdict": "AGREE", "substantive": True, "candidate_digest": "2" * 64, "attester": "gpt-5.6-sol", "run_identity": "run_id_sol_102", "is_author": False, "independent_attestor": True},
                "gemini": {"verdict": "AGREE", "substantive": True, "candidate_digest": "2" * 64, "attester": "gemini", "run_identity": "run_id_gemini_103", "is_author": True, "independent_attestor": False},
                "grok": {"verdict": "AGREE", "substantive": True, "candidate_digest": "2" * 64, "attester": "grok", "run_identity": "run_id_grok_104", "is_author": False, "independent_attestor": True},
            },
            "seat_chronology": ["sol", "grok", "gemini", "fable"],
            "author_vendor": "gemini",
            "raw_log_digest": "3" * 64,
            "junit_mode_digests": {
                "default": "4" * 64,
                "forced_red": "5" * 64,
                "ordinary": "6" * 64,
                "attended": "7" * 64,
            },
            "control_digests": {
                "isolation": "8" * 64,
                "taint": "9" * 64,
                "misuse": "a" * 64,
                "control": "b" * 64,
                "positive_canary": "c" * 64,
            },
            "github_pr": {
                "number": 123,
                "repo": "Consiliency/agent-harness",
                "head_ref": "proofgate-head",
                "base_ref": "main",
            },
        }

        eval_res = evaluate_unit_double_bootstrap_merge_review_gate(valid_evidence)
        assert eval_res["status"] == "valid"
        assert eval_res["evidence_kind"] == "unit_double"
        assert eval_res["decisive"] is False

        # 4a: Author seat marked as is_author=False fails
        bad_author_attest = json.loads(json.dumps(valid_evidence))
        bad_author_attest["seat_records"]["gemini"]["is_author"] = False
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_author_attest)

        # 4b: Independent seat marked as is_author=True fails
        bad_author_flag = json.loads(json.dumps(valid_evidence))
        bad_author_flag["seat_records"]["fable"]["is_author"] = True
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_author_flag)

        # 4c: Omitted independent_attestor boolean fails
        bad_omit_indep = json.loads(json.dumps(valid_evidence))
        del bad_omit_indep["seat_records"]["fable"]["independent_attestor"]
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_omit_indep)

        # 4d: Duplicate run_identity across seats fails
        bad_dup_run_id = json.loads(json.dumps(valid_evidence))
        bad_dup_run_id["seat_records"]["fable"]["run_identity"] = "run_id_gemini_103"
        with pytest.raises(ProofgateBootstrapVerifierError, match="Duplicate run_identity"):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_dup_run_id)

        # 4e: Swapped parent OIDs fails
        bad_swapped_parents = json.loads(json.dumps(valid_evidence))
        bad_swapped_parents["topology"]["parent_oids"] = ["c" * 40, "b" * 40]
        with pytest.raises(ProofgateBootstrapVerifierError, match="base_oid"):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_swapped_parents)

        # 4f: Duplicate chronology seats fails
        bad_dup_chron = json.loads(json.dumps(valid_evidence))
        bad_dup_chron["seat_chronology"] = ["sol", "sol", "gemini", "fable"]
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_dup_chron)

        # 4g: Omitted chronology seats fails
        bad_omit_chron = json.loads(json.dumps(valid_evidence))
        bad_omit_chron["seat_chronology"] = ["sol", "gemini", "fable"]
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_omit_chron)

        # 4h: Non-hex candidate_oid fails
        bad_nonhex_oid = json.loads(json.dumps(valid_evidence))
        bad_nonhex_oid["candidate_oid"] = "a" * 39 + "Z"
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(bad_nonhex_oid)

        # 4i: PR repo mismatch fails
        with pytest.raises(ProofgateBootstrapVerifierError):
            evaluate_unit_double_bootstrap_merge_review_gate(valid_evidence, expected_repo="Consiliency/other-repo")

        valid_junit, valid_reports, _runner_envelope = _phase_reports_and_junit("default")
        # Decisive coordinator evidence is a separately frozen command/path, not a generic
        # automation JUnit.  Its parser requires the explicit plugin, legacy family and
        # plan-named JUnit/phase-report pair under PHASE_LOOP_RUN_DIR.
        default_command = coordinator_evidence_capture_argv("default")
        assert "-p" in default_command and default_command[default_command.index("-p") + 1] == "tests.proofgate_tdd_guard"
        assert "junit_family=legacy" in default_command
        assert "--junitxml=$PHASE_LOOP_RUN_DIR/proofgate-tests-only-default.junit.xml" in default_command
        assert all("junit_default.xml" not in argument for argument in default_command)
        forced_red_command = coordinator_evidence_capture_argv("forced_red")
        ordinary_command = coordinator_evidence_capture_argv("ordinary_hermetic")
        attended_command = coordinator_evidence_capture_argv("attended_live")
        assert "PHASE_LOOP_TDD_EXPECT_PROOFGATE=1" in forced_red_command
        assert "PHASE_LOOP_TDD_EXPECT_PROOFGATE=1" not in ordinary_command
        assert "PHASE_LOOP_TDD_EXPECT_PROOFGATE=1" not in attended_command
        assert "PHASE_LOOP_PROOFGATE_ORDINARY_HERMETIC=1" in ordinary_command
        assert "PHASE_LOOP_PROOFGATE_ATTENDED_LIVE=1" in attended_command
        attended_junit, attended_reports, attended_envelope = _phase_reports_and_junit(
            "attended_live",
            candidate_oid="a" * 40,
        )
        assert verify_junit_accounting(
            attended_junit,
            "attended_live",
            phase_reports=attended_reports,
            runner_envelope=attended_envelope,
            expected_attended_head_identity="a" * 40,
            expected_attended_stage="candidate",
        )["passed"] == 39
        main_junit, main_reports, main_envelope = _forge_attended_identity(
            attended_junit,
            attended_reports,
            attended_envelope,
            "runner_stage",
            "canonical-main",
        )
        main_junit, main_reports, main_envelope = _forge_attended_identity(
            main_junit,
            main_reports,
            main_envelope,
            "head_identity",
            "b" * 40,
        )
        assert verify_junit_accounting(
            main_junit,
            "attended_live",
            phase_reports=main_reports,
            runner_envelope=main_envelope,
            expected_attended_head_identity="b" * 40,
            expected_attended_stage="canonical-main",
        )["passed"] == 39
        fabricated_transport = json.loads(json.dumps(attended_envelope))
        provider_case = ATTENDED_REAL_PROVIDER_CASES[0]
        fabricated_transport["provider_receipts"][provider_case][
            "subscription_transport_observed"
        ] = False
        fabricated_transport["provider_receipts_sha256"] = attended_provider_receipts_digest(
            fabricated_transport["provider_receipts"]
        )
        with pytest.raises(ProofgateBootstrapVerifierError, match="receipt identity mismatch"):
            verify_junit_accounting(
                attended_junit,
                "attended_live",
                phase_reports=attended_reports,
                runner_envelope=fabricated_transport,
                expected_attended_head_identity="a" * 40,
                expected_attended_stage="candidate",
            )
        for field, forged_value, rejection in (
            ("runner_stage", "forged-stage", "runner_stage"),
            ("module_identity", "0" * 64, "module_identity"),
            ("head_identity", "b" * 40, "head_identity"),
        ):
            forged_junit, forged_reports, forged_envelope = _forge_attended_identity(
                attended_junit,
                attended_reports,
                attended_envelope,
                field,
                forged_value,
            )
            with pytest.raises(ProofgateBootstrapVerifierError, match=rejection):
                verify_junit_accounting(
                    forged_junit,
                    "attended_live",
                    phase_reports=forged_reports,
                    runner_envelope=forged_envelope,
                    expected_attended_head_identity="a" * 40,
                )
        _coordinator_tmp = tempfile.TemporaryDirectory()
        coordinator_root = Path(_coordinator_tmp.name)
        _write_decisive_bootstrap_artifacts(coordinator_root, "a" * 40)
        with _coordinator_run_dir(coordinator_root):
            captured_default = verify_coordinator_evidence_capture(coordinator_root, "default")
            assert captured_default["mode"] == "default"
            assert (captured_default["collected"], captured_default["passed"], captured_default["skipped"], captured_default["failed"]) == (39, 3, 36, 0)
            external_receipts_path = coordinator_root / ATTENDED_PROVIDER_RECEIPTS_FILENAME
            external_receipts_bytes = external_receipts_path.read_bytes()
            external_receipts_path.write_text("{}", encoding="utf-8")
            with pytest.raises(
                ProofgateBootstrapVerifierError,
                match="do not match coordinator-owned bytes",
            ):
                verify_coordinator_evidence_capture(
                    coordinator_root,
                    "attended_live",
                    expected_candidate_oid="a" * 40,
                    expected_attended_stage="candidate",
                )
            external_receipts_path.write_bytes(external_receipts_bytes)

            # A copied default/xunit2 report cannot become authority: the plan-named artifact
            # requires a plugin capture receipt bound to legacy bytes and command provenance.
            default_junit = coordinator_root / "proofgate-tests-only-default.junit.xml"
            (coordinator_root / "junit_default.xml").write_bytes(default_junit.read_bytes())
            phase_report = coordinator_root / "proofgate-tests-only-default.phase-reports.json"
            phase_payload = json.loads(phase_report.read_text(encoding="utf-8"))
            phase_payload["capture"]["junit_family"] = "xunit2"
            phase_report.write_text(json.dumps(phase_payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            with pytest.raises(ProofgateBootstrapVerifierError, match="capture receipt mismatch"):
                verify_coordinator_evidence_capture(coordinator_root, "default")
        _assert_chronology_accepted(
            tdd_chronology,
            lifecycle_stage="junit_lifecycle",
            junit_xml=valid_junit,
            phase_reports=valid_reports,
            junit_evidence=valid_evidence,
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "junit_lifecycle_invalid",
            lifecycle_stage="junit_lifecycle",
            junit_xml="<testsuite><testcase>",
            phase_reports=valid_reports,
            junit_evidence=valid_evidence,
        )

    run_proofgate_contract(nodeid, _contract)


def test_pr_r_admin_binding_derives_assigned_ids_only_from_live_control_planes():
    """Verify agent-harness#454/#456 admin binding derives assigned IDs only from live control planes."""
    try:
        from .proofgate_bootstrap_verifier import (
            ProofgateAdminControlPlaneBoundary,
            ProofgateBootstrapVerifierError,
            run_live_admin_binding_preflight,
            verify_proofgate_admin_identity_binding,
        )
    except (ImportError, AttributeError):
        raise AssertionError(
            "PROOFGATE_PR_R_RED::assigned_identity_control_plane_binding_unimplemented"
        )

    claim_policy_1 = {
        "audience": "urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
        "event_name": "workflow_dispatch",
        "repository_id": "1280382652",
        "repository_owner_id": "159201120",
        "workflow_ref": "Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
    }
    claim_policy_digest_1 = hashlib.sha256(
        json.dumps(claim_policy_1, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    claim_policy_2 = {
        "audience": "urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
        "event_name": "workflow_dispatch",
        "repository_id": "1280382652",
        "repository_owner_id": "159201120",
        "workflow_ref": "Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
    }
    claim_policy_digest_2 = hashlib.sha256(
        json.dumps(claim_policy_2, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    synthetic_observation_1 = {
        "repository": {
            "id": "1280382652",
            "owner_id": "159201120",
            "name": "Consiliency/agent-harness",
        },
        "app": {
            "id": "990001",
            "slug": "proofgate-app",
            "owner_id": "159201120",
        },
        "installation": {
            "id": "880001",
            "app_id": "990001",
            "target_owner_id": "159201120",
            "repository_selection": "selected",
            "permissions": (("contents", "write"), ("metadata", "read")),
        },
        "selected_repositories": (
            {"id": "1280382652", "name": "Consiliency/agent-harness"},
        ),
        "organization_user": {
            "id": "770001",
            "login": "proofgate-reviewer",
            "active": True,
        },
        "environment": {
            "id": "440001",
            "name": "proofgate-receipt-head-v1",
            "required_reviewers": (
                {"id": "770001", "type": "User", "login": "proofgate-reviewer"},
            ),
            "prevent_self_review": True,
            "can_admins_bypass": False,
        },
        "ruleset": {
            "id": "550001",
            "name": "proofgate-receipt-head-v1",
            "target_ref": "refs/heads/proofgate-receipt-head-v1",
            "bypass_actors": (
                {"actor_type": "Integration", "actor_id": "990001", "bypass_mode": "always"},
            ),
        },
        "broker": {
            "deployment_id": "proofgate-broker-v1",
            "key_version": "v1",
            "app_id": "990001",
            "installation_id": "880001",
            "repository_id": "1280382652",
            "permissions": (("contents", "write"),),
            "claim_policy": claim_policy_1,
            "claim_policy_digest": claim_policy_digest_1,
        },
    }

    synthetic_observation_2 = {
        "repository": {
            "id": "1280382652",
            "owner_id": "159201120",
            "name": "Consiliency/agent-harness",
        },
        "app": {
            "id": "990002",
            "slug": "proofgate-app",
            "owner_id": "159201120",
        },
        "installation": {
            "id": "880002",
            "app_id": "990002",
            "target_owner_id": "159201120",
            "repository_selection": "selected",
            "permissions": (("contents", "write"), ("metadata", "read")),
        },
        "selected_repositories": (
            {"id": "1280382652", "name": "Consiliency/agent-harness"},
        ),
        "organization_user": {
            "id": "770002",
            "login": "proofgate-reviewer-2",
            "active": True,
        },
        "environment": {
            "id": "440002",
            "name": "proofgate-receipt-head-v1",
            "required_reviewers": (
                {"id": "770002", "type": "User", "login": "proofgate-reviewer-2"},
            ),
            "prevent_self_review": True,
            "can_admins_bypass": False,
        },
        "ruleset": {
            "id": "550002",
            "name": "proofgate-receipt-head-v1",
            "target_ref": "refs/heads/proofgate-receipt-head-v1",
            "bypass_actors": (
                {"actor_type": "Integration", "actor_id": "990002", "bypass_mode": "always"},
            ),
        },
        "broker": {
            "deployment_id": "proofgate-broker-v1",
            "key_version": "v2",
            "app_id": "990002",
            "installation_id": "880002",
            "repository_id": "1280382652",
            "permissions": (("contents", "write"),),
            "claim_policy": claim_policy_2,
            "claim_policy_digest": claim_policy_digest_2,
        },
    }

    # 1. Concrete boundary instances created via explicit test-owned nondecisive seam
    boundary_1 = ProofgateAdminControlPlaneBoundary(_test_observation_fixture=synthetic_observation_1)
    boundary_2 = ProofgateAdminControlPlaneBoundary(_test_observation_fixture=synthetic_observation_2)

    # Enforce type(boundary) exactness
    assert type(boundary_1) is ProofgateAdminControlPlaneBoundary
    assert type(boundary_2) is ProofgateAdminControlPlaneBoundary

    # 2. Reject non-concrete inputs: dict mappings, files, signatures, process runners,
    #    executable overrides, public requests, flags, environment dicts, replayed payloads
    unauthorized_inputs = [
        synthetic_observation_1,
        "/path/to/admin_config.json",
        "signature_bytes_or_string",
        subprocess.Popen,
        "/usr/bin/custom_gh_override",
        {"public_request": "authorize_app_1159201"},
        "--override-admin-ids",
        {"PHASE_LOOP_ADMIN_APP_ID": "990001"},
        b"replayed_payload_bytes",
    ]
    for invalid_input in unauthorized_inputs:
        with pytest.raises((TypeError, ProofgateBootstrapVerifierError)):
            verify_proofgate_admin_identity_binding(invalid_input)

    # 3. Reject subclasses and wrappers of ProofgateAdminControlPlaneBoundary
    class SubclassedAdminBoundary(ProofgateAdminControlPlaneBoundary):
        pass

    class WrappedAdminBoundary:
        def __init__(self, inner):
            self._inner = inner

    subclassed = SubclassedAdminBoundary(_test_observation_fixture=synthetic_observation_1)
    wrapped = WrappedAdminBoundary(boundary_1)
    for bad_boundary in (subclassed, wrapped):
        with pytest.raises((TypeError, ProofgateBootstrapVerifierError)):
            verify_proofgate_admin_identity_binding(bad_boundary)

    # 4. Prove a recording observer can record but cannot authorize
    class RecordingTestDouble:
        def __init__(self):
            self.recorded_requests = []
            self.authorize_called = False

        def observe(self, request):
            self.recorded_requests.append(request)
            return None

        def authorize(self, *args, **kwargs):
            self.authorize_called = True
            return True

    recording_double = RecordingTestDouble()
    with pytest.raises(
        (TypeError, ProofgateBootstrapVerifierError),
        match="PROOFGATE_PR_R_RED::recording_boundary_cannot_authorize",
    ):
        verify_proofgate_admin_identity_binding(recording_double)
    assert recording_double.authorize_called is False

    # 5. Reject unexpected keyword arguments for caller substitution
    with pytest.raises(TypeError):
        verify_proofgate_admin_identity_binding(boundary_1, caller_app_integration_id="990001")
    with pytest.raises(TypeError):
        verify_proofgate_admin_identity_binding(boundary_1, caller_app_installation_id="880001")
    with pytest.raises(TypeError):
        verify_proofgate_admin_identity_binding(boundary_1, caller_reviewer_id="770001")
    with pytest.raises(TypeError):
        verify_proofgate_admin_identity_binding(boundary_1, allow_caller_override=True)

    # 6. Verify historical placeholder IDs 1159201, 6159201, 7159201 are rejected
    for ph_obs in (
        # Historical App ID 1159201
        {
            **synthetic_observation_1,
            "app": {**synthetic_observation_1["app"], "id": "1159201"},
            "installation": {**synthetic_observation_1["installation"], "app_id": "1159201"},
            "ruleset": {
                **synthetic_observation_1["ruleset"],
                "bypass_actors": ({"actor_type": "Integration", "actor_id": "1159201", "bypass_mode": "always"},),
            },
            "broker": {**synthetic_observation_1["broker"], "app_id": "1159201"},
        },
        # Historical Installation ID 6159201
        {
            **synthetic_observation_1,
            "installation": {**synthetic_observation_1["installation"], "id": "6159201"},
            "broker": {**synthetic_observation_1["broker"], "installation_id": "6159201"},
        },
        # Historical Reviewer ID 7159201
        {
            **synthetic_observation_1,
            "organization_user": {**synthetic_observation_1["organization_user"], "id": "7159201"},
            "environment": {
                **synthetic_observation_1["environment"],
                "required_reviewers": ({"id": "7159201", "type": "User", "login": "placeholder-reviewer"},),
            },
        },
    ):
        bad_b = ProofgateAdminControlPlaneBoundary(_test_observation_fixture=ph_obs)
        with pytest.raises((ValueError, ProofgateBootstrapVerifierError), match="(?i)placeholder|assigned|invalid"):
            verify_proofgate_admin_identity_binding(bad_b)

    # 7. Verify relational mismatches are rejected (modifying one operand while leaving counterpart unchanged)
    for mm_obs in (
        # App owner_id ("999000") vs repo owner_id ("159201120") mismatch
        {
            **synthetic_observation_1,
            "app": {**synthetic_observation_1["app"], "owner_id": "999000"},
        },
        # Installation app_id ("999999") vs App id ("990001") mismatch
        {
            **synthetic_observation_1,
            "installation": {**synthetic_observation_1["installation"], "app_id": "999999"},
        },
        # Installation target_owner_id ("999000") vs App owner_id ("159201120") mismatch
        {
            **synthetic_observation_1,
            "installation": {**synthetic_observation_1["installation"], "target_owner_id": "999000"},
        },
        # Selected repository ID ("999999") vs repo ID ("1280382652") mismatch
        {
            **synthetic_observation_1,
            "selected_repositories": ({"id": "999999", "name": "Consiliency/other-repo"},),
        },
        # Ruleset bypass actor_id ("999999") vs App id ("990001") mismatch
        {
            **synthetic_observation_1,
            "ruleset": {
                **synthetic_observation_1["ruleset"],
                "bypass_actors": ({"actor_type": "Integration", "actor_id": "999999", "bypass_mode": "always"},),
            },
        },
        # Environment reviewer mismatch changing only environment reviewer
        {
            **synthetic_observation_1,
            "environment": {
                **synthetic_observation_1["environment"],
                "required_reviewers": ({"id": "999999", "type": "User", "login": "other-user"},),
            },
        },
        # Inactive organization user rejection
        {
            **synthetic_observation_1,
            "organization_user": {**synthetic_observation_1["organization_user"], "active": False},
        },
        # Extra GitHub permission
        {
            **synthetic_observation_1,
            "installation": {
                **synthetic_observation_1["installation"],
                "permissions": (("contents", "write"), ("metadata", "read"), ("actions", "write")),
            },
        },
        # Extra broker permission
        {
            **synthetic_observation_1,
            "broker": {
                **synthetic_observation_1["broker"],
                "permissions": (("contents", "write"), ("actions", "write")),
            },
        },
        # Broker app_id ("999999") vs App id ("990001") mismatch
        {
            **synthetic_observation_1,
            "broker": {**synthetic_observation_1["broker"], "app_id": "999999"},
        },
        # Claim policy digest mismatch (digest changed while policy object remains unchanged)
        {**synthetic_observation_1, "broker": {**synthetic_observation_1["broker"], "claim_policy_digest": "0" * 64}},
    ):
        bad_b = ProofgateAdminControlPlaneBoundary(_test_observation_fixture=mm_obs)
        with pytest.raises((ValueError, ProofgateBootstrapVerifierError)):
            verify_proofgate_admin_identity_binding(bad_b)

    # 8. Derived receipt/pilot fields (run_id, run_attempt, subject, workflow_sha256) must be absent from input/output
    obs_with_derived_fields = {
        **synthetic_observation_1,
        "run_id": "1000000001",
        "run_attempt": "1",
        "subject": "cores/00000000000000000001-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.json",
        "workflow_sha256": "3c365db032ad94622149fde1cadcb84b45480d65d8d789387ef47de286b59c44",
    }
    b_derived = ProofgateAdminControlPlaneBoundary(_test_observation_fixture=obs_with_derived_fields)
    with pytest.raises((ValueError, ProofgateBootstrapVerifierError), match="(?i)derived|receipt|pilot|constant"):
        verify_proofgate_admin_identity_binding(b_derived)

    # Derive valid binding results for coherent sets 1 and 2
    binding_result_1 = verify_proofgate_admin_identity_binding(boundary_1)
    binding_result_2 = verify_proofgate_admin_identity_binding(boundary_2)

    assert binding_result_1["schema"] == "proofgate_admin_identity_binding.v1"
    assert binding_result_2["schema"] == "proofgate_admin_identity_binding.v1"
    assert binding_result_1["authority"] != "github_and_broker_control_planes"
    assert binding_result_1["normalized_broker_policy_digest"] == claim_policy_digest_1
    assert binding_result_1["normalized_github_permissions"] == (("contents", "write"), ("metadata", "read"))

    with tempfile.TemporaryDirectory() as preflight_tmp:
        preflight_out = Path(preflight_tmp) / "admin_preflight.json"
        with _coordinator_run_dir(Path(preflight_tmp)):
            preflight_code = run_live_admin_binding_preflight(boundary_1, output=str(preflight_out))
        assert preflight_code == 1, "run_live_admin_binding_preflight must fail closed for test-owned nondecisive boundary"
        preflight_payload = json.loads(preflight_out.read_text(encoding="utf-8"))
        assert preflight_payload["verification_status"] == "blocked"
        assert preflight_payload["human_required"] is True
        assert preflight_payload["blocker_class"] == "admin_approval"
        assert preflight_payload["access_attempts"]

    # Reject replaying the first binding result back as authority
    with pytest.raises((TypeError, ProofgateBootstrapVerifierError)):
        verify_proofgate_admin_identity_binding(binding_result_1)

    # Both coherent sets pass but produce different binding digests!
    assert binding_result_1["binding_digest"] != binding_result_2["binding_digest"]

    # Explicit evaluation partition
    assert binding_result_1["evaluation_partition"] == {
        "admin_relations": "evaluated",
        "receipt_pilot": "not_evaluated",
    }

    # Verify admin_relations is present and derived receipt/pilot fields are absent from binding output
    assert "admin_relations" in binding_result_1
    assert "receipt_pilot" not in binding_result_1
    for derived_key in ("run_id", "run_attempt", "subject", "workflow_sha256"):
        assert derived_key not in binding_result_1
        assert derived_key not in binding_result_1["admin_relations"]

    # Assert _test_observation_fixture does NOT appear in resulting evidence
    assert "_test_observation_fixture" not in binding_result_1
    assert "_test_observation_fixture" not in binding_result_1["admin_relations"]


def _setup_pr_r_candidate_history(*, selector_suffix: str = ""):
    tmp, repo, original_tests_landing_oid = _setup_git_repo()
    for rel_path in PR_B_TEST_CONTRACT_FILES:
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# contract {rel_path}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Seed test contracts"], cwd=repo, capture_output=True, check=True)
    selector_base_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    subprocess.run(["git", "checkout", "-b", "selector-repair-red"], cwd=repo, capture_output=True, check=True)
    chronology_path = repo / "phase-loop-runtime/tests/test_tdd_chronology.py"
    chronology_path.write_text(
        chronology_path.read_text(encoding="utf-8") + f"# RED{selector_suffix}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Selector repair RED"], cwd=repo, capture_output=True, check=True)

    subprocess.run(["git", "checkout", "-b", "selector-repair-green"], cwd=repo, capture_output=True, check=True)
    for rel_path in (
        "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
        "phase-loop-runtime/tests/proofgate_tdd_guard.py",
    ):
        path = repo / rel_path
        path.write_text(
            path.read_text(encoding="utf-8") + f"# GREEN{selector_suffix}\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Selector repair GREEN"], cwd=repo, capture_output=True, check=True)

    subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "selector-repair-green", "-m", "Merge selector repair"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    selector_repair_landing_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", original_tests_landing_oid, selector_base_oid],
        cwd=repo,
        capture_output=True,
    ).returncode == 0

    subprocess.run(["git", "checkout", "-b", "proofgate-pr-b"], cwd=repo, capture_output=True, check=True)
    for rel_path in PR_B_5_PATHS:
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# candidate {rel_path}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "PR-B candidate"], cwd=repo, capture_output=True, check=True)
    candidate_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    pr_metadata = _valid_pr_metadata(candidate_oid, selector_repair_landing_oid, "PR-B")
    digest = hashlib.sha256(
        subprocess.run(
            ["git", "diff-tree", "--raw", "-r", "-z", selector_repair_landing_oid, candidate_oid],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    ).hexdigest()
    seats, chronology = _valid_seats(digest)
    _observation, boundary, coordinator_root, coordinator_tmp = _pr_b_observed_bootstrap_boundary(
        repo,
        selector_repair_landing_oid,
        candidate_oid,
        pr_metadata,
        seats,
        chronology,
        original_tests_landing_oid=original_tests_landing_oid,
    )
    return (
        tmp,
        repo,
        original_tests_landing_oid,
        selector_repair_landing_oid,
        candidate_oid,
        boundary,
        coordinator_root,
        coordinator_tmp,
    )


def _write_selector_repair_review_binding(
    repo: Path,
    original_tests_landing_oid: str,
    selector_repair_landing_oid: str,
    output_path: Path,
) -> dict:
    landing_parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", selector_repair_landing_oid],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    selector_repair_base_oid, selector_repair_source_head_oid = landing_parents[1:]
    source_parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", selector_repair_source_head_oid],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    selector_repair_red_commit_oid = source_parents[1]
    source_facts = compute_git_source_binding_facts(
        repo, selector_repair_base_oid, selector_repair_source_head_oid
    )
    landing_facts = compute_git_source_binding_facts(
        repo, selector_repair_base_oid, selector_repair_landing_oid
    )
    payload = {
        "schema": "proofgate_selector_repair_review_binding.v1",
        "repository": COORDINATOR_REPOSITORY,
        "original_tests_landing_oid": original_tests_landing_oid,
        "selector_repair_base_oid": selector_repair_base_oid,
        "selector_repair_red_commit_oid": selector_repair_red_commit_oid,
        "selector_repair_source_head_oid": selector_repair_source_head_oid,
        "selector_repair_landing_oid": selector_repair_landing_oid,
        "reviewed_change_tuple_digest": source_facts["change_tuple_digest"],
        "reviewed_path_blob_digest": source_facts["path_blob_digest"],
        "reviewed_path_tuples": [list(row) for row in source_facts["path_tuples"]],
        "landing_change_tuple_digest": landing_facts["change_tuple_digest"],
        "landing_path_blob_digest": landing_facts["path_blob_digest"],
        "landing_path_tuples": [list(row) for row in landing_facts["path_tuples"]],
    }
    output_path.write_bytes(
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    return payload


def _sync_pr_b_candidate_artifact_digests(
    proofgate_bootstrap_verifier,
    coordinator_root: Path,
    filenames: tuple[str, ...],
) -> None:
    observation_path = coordinator_root / "bootstrap-observation.json"
    observation_payload = json.loads(observation_path.read_text(encoding="utf-8"))
    observation_payload["candidate_artifact_digests"] = [
        [filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest()]
        for filename in filenames
    ]
    observation = proofgate_bootstrap_verifier._bootstrap_observation_from_payload(
        observation_payload
    )
    proofgate_bootstrap_verifier._write_coordinator_observation(
        coordinator_root, observation, "PR-B"
    )


def test_pr_r_terra_001_gh_timeout_fails_closed(monkeypatch):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            ProofgateAdminControlPlaneBoundary,
            run_live_admin_binding_preflight,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "PRR-TERRA-001::live_admin_preflight_timeout_handling_unimplemented"
        ) from exc

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "admin-preflight.json"

        def timeout(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=["gh", "api"], timeout=10)

        monkeypatch.setattr(proofgate_bootstrap_verifier.subprocess, "run", timeout)
        try:
            with _coordinator_run_dir(Path(tmp_dir)):
                exit_code = run_live_admin_binding_preflight(
                    ProofgateAdminControlPlaneBoundary(), output=str(out_path)
                )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(f"PRR-TERRA-001::live_admin_preflight_timeout_escapes_uncaught: {exc}")

        assert exit_code == 1
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["human_required"] is True
        assert payload["blocker_class"] == "admin_approval"
        assert payload["verification_status"] == "blocked"
        assert payload["access_attempts"][0]["result"] == "unavailable_or_mismatch"
        assert payload["access_attempts"][0]["timestamp"]


def test_pr_r_terra_001_gh_structurally_wrong_json_payload_fails_closed(monkeypatch):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            ProofgateAdminControlPlaneBoundary,
            run_live_admin_binding_preflight,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "PRR-TERRA-001::live_admin_preflight_structurally_wrong_payload_unimplemented"
        ) from exc

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "admin-preflight.json"

        def mock_run(cmd, *_args, **_kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='[{"id": 880001}]\n', stderr=""
            )

        monkeypatch.setattr(proofgate_bootstrap_verifier.subprocess, "run", mock_run)
        with _coordinator_run_dir(Path(tmp_dir)):
            exit_code = run_live_admin_binding_preflight(
                ProofgateAdminControlPlaneBoundary(), output=str(out_path)
            )

        assert exit_code == 1
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["human_required"] is True
        assert payload["blocker_class"] == "admin_approval"
        assert payload["verification_status"] == "blocked"
        assert payload["access_attempts"][0]["result"] == "unavailable_or_mismatch"
        assert payload["access_attempts"][0]["timestamp"]


def test_pr_r_terra_002_pr_b_strict_candidate_binding(monkeypatch):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_pr_r_terra_002_pr_b_strict_candidate_binding"

    def contract():
        try:
            from . import proofgate_bootstrap_verifier
            from .proofgate_bootstrap_verifier import verify_bootstrap_candidate_binding
            from .proofgate_tdd_guard import CANDIDATE_BINDING_FIELDS
        except (ImportError, AttributeError) as exc:
            raise ProofgateMissingCapabilityError(
                "PRR-TERRA-002::verify_bootstrap_candidate_binding_unimplemented"
            ) from exc

        (
            _tmp,
            repo,
            original_oid,
            base_oid,
            candidate_oid,
            boundary,
            coordinator_root,
            _coordinator_tmp,
        ) = _setup_pr_r_candidate_history()
        binding_path = coordinator_root / "bootstrap-candidate-binding.json"
        binding_bytes = binding_path.read_bytes()
        binding = json.loads(binding_bytes)
        assert tuple(binding) == CANDIDATE_BINDING_FIELDS
        assert binding_bytes == (json.dumps(binding, separators=(",", ":")) + "\n").encode()
        assert verify_bootstrap_candidate_binding(
            repo_path=repo,
            binding_path=binding_path,
            expected_original_tests_landing=original_oid,
        )["status"] == "verified"

        mutations = {
            "missing-fields": {key: value for key, value in binding.items() if key != "changes"},
            "wrong-order": {key: binding[key] for key in reversed(binding)},
            "candidate-tree": {**binding, "candidate_tree_oid": "0" * 40},
            "selector-topology": {**binding, "selector_repair_landing_oid": candidate_oid},
            "change-tuple": {**binding, "changes": []},
            "test-contract": {**binding, "test_contract_sha256": {**binding["test_contract_sha256"], PR_B_TEST_CONTRACT_FILES[0]: "0" * 64}},
        }
        with tempfile.TemporaryDirectory() as mutation_dir:
            mutation_root = Path(mutation_dir)
            for label, mutated in mutations.items():
                path = mutation_root / f"mutated-{label}.json"
                path.write_bytes((json.dumps(mutated, separators=(",", ":")) + "\n").encode())
                with pytest.raises(ProofgateBootstrapVerifierError, match="(?i)field|tree|selector|change|contract|mismatch"):
                    verify_bootstrap_candidate_binding(
                        repo_path=repo,
                        binding_path=path,
                        expected_original_tests_landing=original_oid,
                    )
            missing_lf = mutation_root / "mutated-missing-lf.json"
            missing_lf.write_bytes(json.dumps(binding, separators=(",", ":")).encode())
            with pytest.raises(ProofgateBootstrapVerifierError, match="(?i)canonical|compact|LF"):
                verify_bootstrap_candidate_binding(
                    repo_path=repo,
                    binding_path=missing_lf,
                    expected_original_tests_landing=original_oid,
                )

        def strict_activation(**_kwargs):
            raise ProofgateBootstrapVerifierError("PRR-TERRA-002::strict_binding_activated")

        monkeypatch.setattr(proofgate_bootstrap_verifier, "verify_bootstrap_candidate_binding", strict_activation)
        with _coordinator_run_dir(coordinator_root), pytest.raises(
            ProofgateBootstrapVerifierError, match="PRR-TERRA-002::strict_binding_activated"
        ):
            verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary
            )

    run_proofgate_contract(nodeid, contract)


def test_pr_r_admin_003_decisive_pr_b_rejects_synthetic_or_replayed_admin_binding(monkeypatch):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_pr_r_admin_003_decisive_pr_b_rejects_synthetic_or_replayed_admin_binding"

    def contract():
        try:
            from . import proofgate_bootstrap_verifier
            from .proofgate_bootstrap_verifier import (
                ProofgateAdminControlPlaneBoundary,
                verify_proofgate_admin_authority,
            )
        except (ImportError, AttributeError) as exc:
            raise ProofgateMissingCapabilityError(
                "PRR-ADMIN-003::verify_proofgate_admin_authority_unimplemented"
            ) from exc

        with tempfile.TemporaryDirectory() as tmp_dir:
            binding_path = Path(tmp_dir) / "admin-binding.json"
            synthetic = {
                "schema": "proofgate_admin_identity_binding.v1",
                "authority": "github_and_broker_control_planes",
                "candidate_oid": "a" * 40,
            }
            synthetic["binding_digest"] = hashlib.sha256(
                json.dumps(synthetic, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            binding_path.write_text(json.dumps(synthetic, sort_keys=True, separators=(",", ":")), encoding="utf-8")

            for _label, boundary, candidate_oid in (
                ("caller-authored", object(), "a" * 40),
                ("fixture", ProofgateAdminControlPlaneBoundary(_test_observation_fixture={}), "a" * 40),
                ("replay", ProofgateAdminControlPlaneBoundary(), "b" * 40),
            ):
                with pytest.raises(ProofgateBootstrapVerifierError, match="(?i)admin|authority|candidate|control plane|live|replay"):
                    verify_proofgate_admin_authority(
                        boundary=boundary,
                        candidate_oid=candidate_oid,
                        admin_binding_path=binding_path,
                    )

            monkeypatch.setattr(ProofgateAdminControlPlaneBoundary, "observe", lambda _self: None)
            with pytest.raises(ProofgateBootstrapVerifierError, match="(?i)unavailable|admin|authority|control plane"):
                verify_proofgate_admin_authority(
                    boundary=ProofgateAdminControlPlaneBoundary(),
                    candidate_oid="a" * 40,
                    admin_binding_path=binding_path,
                )

        called = False

        def admin_activation(**_kwargs):
            nonlocal called
            called = True
            raise ProofgateBootstrapVerifierError("PRR-ADMIN-003::live_admin_authority_required")

        def strict_binding_already_verified(*, binding_path, **_kwargs):
            binding_bytes = Path(binding_path).read_bytes()
            return {
                "status": "verified",
                "binding_data": json.loads(binding_bytes),
                "binding_bytes": binding_bytes,
                "binding_digest": hashlib.sha256(binding_bytes).hexdigest(),
            }

        monkeypatch.setattr(
            proofgate_bootstrap_verifier,
            "verify_bootstrap_candidate_binding",
            strict_binding_already_verified,
        )
        monkeypatch.setattr(proofgate_bootstrap_verifier, "verify_proofgate_admin_authority", admin_activation)
        (
            _tmp,
            repo,
            _original_oid,
            base_oid,
            candidate_oid,
            boundary,
            coordinator_root,
            _coordinator_tmp,
        ) = _setup_pr_r_candidate_history()
        with _coordinator_run_dir(coordinator_root), pytest.raises(
            ProofgateBootstrapVerifierError, match="PRR-ADMIN-003::live_admin_authority_required"
        ):
            verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary
            )
        assert called is True

    run_proofgate_contract(nodeid, contract)


def test_pr_r_admin_001_omitted_admin_boundary_selects_concrete_control_plane(monkeypatch):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_pr_r_admin_001_omitted_admin_boundary_selects_concrete_control_plane"

    def contract():
        try:
            from . import proofgate_bootstrap_verifier
            from .proofgate_bootstrap_verifier import (
                ProofgateAdminControlPlaneBoundary,
                verify_observed_premerge_bootstrap_review_gate,
            )
        except (ImportError, AttributeError) as exc:
            raise ProofgateMissingCapabilityError(
                "PRR-TERRA-001::verify_observed_premerge_bootstrap_review_gate_unimplemented"
            ) from exc

        (
            _tmp,
            repo,
            original_oid,
            base_oid,
            candidate_oid,
            boundary,
            coordinator_root,
            _coordinator_tmp,
        ) = _setup_pr_r_candidate_history()

        real_verify_binding = proofgate_bootstrap_verifier.verify_bootstrap_candidate_binding

        def patched_verify_binding(repo_path, binding_path, expected_original_tests_landing=None):
            return real_verify_binding(
                repo_path=repo_path,
                binding_path=binding_path,
                expected_original_tests_landing=original_oid,
            )

        monkeypatch.setattr(
            proofgate_bootstrap_verifier, "verify_bootstrap_candidate_binding", patched_verify_binding
        )

        captured_boundary = None

        def fake_admin_authority(boundary=None, candidate_oid=None, admin_binding_path=None, **_kwargs):
            nonlocal captured_boundary
            captured_boundary = boundary
            return {
                "schema": "proofgate_admin_identity_binding.v1",
                "authority": "github_and_broker_control_planes",
                "binding_digest": "a" * 64,
            }

        monkeypatch.setattr(
            proofgate_bootstrap_verifier, "verify_proofgate_admin_authority", fake_admin_authority
        )

        with _coordinator_run_dir(coordinator_root):
            verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary
            )

        assert type(captured_boundary) is ProofgateAdminControlPlaneBoundary, (
            f"PRR-ADMIN-001: Expected omitted admin_boundary to pass exact concrete "
            f"ProofgateAdminControlPlaneBoundary to authority seam, got {type(captured_boundary)}"
        )

    run_proofgate_contract(nodeid, contract)


def test_pr_r_admin_001_structural_normalization_and_rejection_rules(monkeypatch):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_pr_r_admin_001_structural_normalization_and_rejection_rules"

    def contract():
        try:
            from . import proofgate_bootstrap_verifier
            from .proofgate_bootstrap_verifier import (
                ProofgateAdminControlPlaneBoundary,
                verify_proofgate_admin_authority,
            )
        except (ImportError, AttributeError) as exc:
            raise ProofgateMissingCapabilityError(
                "PRR-B1::verify_proofgate_admin_authority_unimplemented"
            ) from exc

        claim_policy = {
            "audience": "urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
            "event_name": "workflow_dispatch",
            "repository_id": "1280382652",
            "repository_owner_id": "159201120",
            "workflow_ref": "Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
        }
        claim_policy_digest = hashlib.sha256(
            json.dumps(claim_policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        expected_live_binding = {
            "schema": "proofgate_admin_identity_binding.v1",
            "authority": "github_and_broker_control_planes",
            "repository_id": "1280382652",
            "repository_name": "Consiliency/agent-harness",
            "app_id": "990001",
            "app_slug": "proofgate-app",
            "installation_id": "880001",
            "reviewer_id": "770001",
            "reviewer_login": "proofgate-reviewer",
            "broker_deployment_id": "proofgate-broker-v1",
            "broker_key_version": "v1",
            "normalized_broker_policy_digest": claim_policy_digest,
            "normalized_github_permissions": (("contents", "write"), ("metadata", "read")),
            "admin_relations": {
                "app_owner_equals_repository_owner": True,
                "installation_app_equals_resolved_app": True,
                "installation_target_equals_app_owner": True,
                "selected_repository_equals_target": True,
                "ruleset_bypass_equals_resolved_app": True,
                "environment_reviewer_equals_active_user": True,
                "broker_relations_match": True,
            },
            "evaluation_partition": {
                "admin_relations": "evaluated",
                "receipt_pilot": "not_evaluated",
            },
        }
        digest_bytes = json.dumps(expected_live_binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected_live_binding["binding_digest"] = hashlib.sha256(digest_bytes).hexdigest()

        monkeypatch.setattr(
            proofgate_bootstrap_verifier,
            "verify_proofgate_admin_identity_binding",
            lambda _boundary: expected_live_binding,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            binding_path = Path(tmp_dir) / "admin-binding.json"

            stored = {
                "schema": "proofgate_admin_identity_binding.v1",
                "authority": "github_and_broker_control_planes",
                "repository_id": "1280382652",
                "repository_name": "Consiliency/agent-harness",
                "app_id": "990001",
                "app_slug": "proofgate-app",
                "installation_id": "880001",
                "reviewer_id": "770001",
                "reviewer_login": "proofgate-reviewer",
                "broker_deployment_id": "proofgate-broker-v1",
                "broker_key_version": "v1",
                "normalized_broker_policy_digest": claim_policy_digest,
                "normalized_github_permissions": [["contents", "write"], ["metadata", "read"]],
                "candidate_oid": "a" * 40,
                "admin_relations": {
                    "app_owner_equals_repository_owner": True,
                    "installation_app_equals_resolved_app": True,
                    "installation_target_equals_app_owner": True,
                    "selected_repository_equals_target": True,
                    "ruleset_bypass_equals_resolved_app": True,
                    "environment_reviewer_equals_active_user": True,
                    "broker_relations_match": True,
                },
                "evaluation_partition": {
                    "admin_relations": "evaluated",
                    "receipt_pilot": "not_evaluated",
                },
            }
            unbound = dict(stored)
            unbound.pop("binding_digest", None)
            stored["binding_digest"] = hashlib.sha256(
                json.dumps(unbound, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            binding_path.write_text(json.dumps(stored, sort_keys=True, separators=(",", ":")), encoding="utf-8")

            result = verify_proofgate_admin_authority(
                boundary=ProofgateAdminControlPlaneBoundary(),
                candidate_oid="a" * 40,
                admin_binding_path=binding_path,
            )
            assert result == expected_live_binding, (
                "PRR-ADMIN-001: Structural normalization failed to normalize stored JSON lists to tuples"
            )

            partial = dict(stored)
            partial.pop("candidate_oid")
            partial_unbound = dict(partial)
            partial_unbound.pop("binding_digest", None)
            partial["binding_digest"] = hashlib.sha256(
                json.dumps(partial_unbound, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            partial_path = Path(tmp_dir) / "partial-binding.json"
            partial_path.write_text(json.dumps(partial, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            with pytest.raises(ProofgateBootstrapVerifierError):
                verify_proofgate_admin_authority(
                    boundary=ProofgateAdminControlPlaneBoundary(),
                    candidate_oid="a" * 40,
                    admin_binding_path=partial_path,
                )

            wrong_dig = dict(stored)
            wrong_dig["binding_digest"] = "0" * 64
            wrong_path = Path(tmp_dir) / "wrong-digest.json"
            wrong_path.write_text(json.dumps(wrong_dig, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            with pytest.raises(ProofgateBootstrapVerifierError, match="(?i)digest"):
                verify_proofgate_admin_authority(
                    boundary=ProofgateAdminControlPlaneBoundary(),
                    candidate_oid="a" * 40,
                    admin_binding_path=wrong_path,
                )

            with pytest.raises(ProofgateBootstrapVerifierError, match="(?i)replay"):
                verify_proofgate_admin_authority(
                    boundary=ProofgateAdminControlPlaneBoundary(),
                    candidate_oid="b" * 40,
                    admin_binding_path=binding_path,
                )

            non_auth = dict(stored)
            non_auth["authority"] = "test_observation_fixture"
            non_auth_unbound = dict(non_auth)
            non_auth_unbound.pop("binding_digest", None)
            non_auth["binding_digest"] = hashlib.sha256(
                json.dumps(non_auth_unbound, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            non_auth_path = Path(tmp_dir) / "non-auth-binding.json"
            non_auth_path.write_text(json.dumps(non_auth, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            with pytest.raises(ProofgateBootstrapVerifierError, match="(?i)authoritative"):
                verify_proofgate_admin_authority(
                    boundary=ProofgateAdminControlPlaneBoundary(),
                    candidate_oid="a" * 40,
                    admin_binding_path=non_auth_path,
                )

    run_proofgate_contract(nodeid, contract)


def test_pr_r_admin_002_live_ruleset_parser_contract(monkeypatch):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_pr_r_admin_002_live_ruleset_parser_contract"

    def contract():
        try:
            from . import proofgate_bootstrap_verifier
            from .proofgate_bootstrap_verifier import (
                ProofgateAdminControlPlaneBoundary,
                verify_proofgate_admin_identity_binding,
            )
        except (ImportError, AttributeError) as exc:
            raise ProofgateMissingCapabilityError(
                "PRR-ADMIN-002::verify_proofgate_admin_identity_binding_unimplemented"
            ) from exc

        monkeypatch.setattr(
            proofgate_bootstrap_verifier,
            "_github_cli_sha256",
            lambda path: proofgate_bootstrap_verifier.GITHUB_CLI_SHA256,
        )

        claim_policy = {
            "audience": "urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
            "event_name": "workflow_dispatch",
            "repository_id": "1280382652",
            "repository_owner_id": "159201120",
            "workflow_ref": "Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
        }
        claim_policy_digest = hashlib.sha256(
            json.dumps(claim_policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        broker_payload = {
            "schema": "proofgate_broker_admin_metadata.v1",
            "deployment_id": "proofgate-broker-v1",
            "key_version": "v1",
            "app_id": "990001",
            "installation_id": "880001",
            "repository_id": "1280382652",
            "permissions": [["contents", "write"]],
            "claim_policy": claim_policy,
            "claim_policy_digest": claim_policy_digest,
        }

        current_ruleset_response = {
            "id": 550001,
            "name": "proofgate-receipt-head-v1",
            "target": "branch",
            "enforcement": "active",
            "conditions": {
                "ref_name": {
                    "include": ["refs/heads/proofgate-receipt-head-v1"],
                    "exclude": [],
                }
            },
            "rules": [
                {"type": "creation"},
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {"type": "required_linear_history"},
                {"type": "update"},
            ],
            "bypass_actors": [
                {
                    "actor_type": "Integration",
                    "actor_id": 990001,
                    "bypass_mode": "always",
                }
            ],
        }

        def fake_gh_api(endpoint: str):
            if endpoint == "repos/Consiliency/agent-harness":
                return {"id": 1280382652, "full_name": "Consiliency/agent-harness", "owner": {"id": 159201120}}
            if endpoint == "apps/proofgate-app":
                return {"id": 990001, "slug": "proofgate-app", "owner": {"id": 159201120}}
            if endpoint == "orgs/Consiliency/installations":
                return {
                    "installations": [
                        {
                            "id": 880001,
                            "app_slug": "proofgate-app",
                            "app_id": 990001,
                            "target_id": 159201120,
                            "repository_selection": "selected",
                            "permissions": {"contents": "write", "metadata": "read"},
                        }
                    ]
                }
            if endpoint == "user/installations/880001/repositories":
                return {"repositories": [{"id": 1280382652, "full_name": "Consiliency/agent-harness"}]}
            if endpoint == "repos/Consiliency/agent-harness/environments/proofgate-receipt-head-v1":
                return {
                    "id": 440001,
                    "name": "proofgate-receipt-head-v1",
                    "can_admins_bypass": False,
                    "protection_rules": [
                        {
                            "type": "required_reviewers",
                            "prevent_self_review": True,
                            "reviewers": [{"type": "User", "reviewer": {"id": 770001, "login": "proofgate-reviewer"}}],
                        }
                    ],
                }
            if endpoint == "repos/Consiliency/agent-harness/rulesets":
                return [{"id": 550001, "name": "proofgate-receipt-head-v1", "enforcement": "active"}]
            if endpoint == "repos/Consiliency/agent-harness/rulesets/550001":
                return current_ruleset_response
            raise ValueError(f"Unexpected endpoint: {endpoint}")

        monkeypatch.setattr(ProofgateAdminControlPlaneBoundary, "_gh_api", staticmethod(fake_gh_api))
        monkeypatch.setattr(
            ProofgateAdminControlPlaneBoundary, "_broker_metadata", classmethod(lambda cls: broker_payload)
        )

        real_subprocess_run = subprocess.run

        def fake_subprocess_run(cmd, **kwargs):
            if isinstance(cmd, list) and "orgs/Consiliency/members/proofgate-reviewer" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
            return real_subprocess_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

        boundary = ProofgateAdminControlPlaneBoundary()

        obs = boundary.observe()
        assert obs is not None, "PRR-ADMIN-002: Observation should be available for valid ruleset"
        assert "ruleset" in obs and "rule_types" in obs["ruleset"], (
            "PRR-ADMIN-002: Observed ruleset must include parsed rule_types, not hard-coded values"
        )
        assert tuple(sorted(obs["ruleset"]["rule_types"])) == (
            "creation",
            "deletion",
            "non_fast_forward",
            "required_linear_history",
            "update",
        )
        binding = verify_proofgate_admin_identity_binding(boundary)
        assert binding.get("authority") == "github_and_broker_control_planes"

        mutations = [
            (
                "wrong-target-ref",
                {
                    **current_ruleset_response,
                    "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
                },
            ),
            ("wrong-target-kind", {**current_ruleset_response, "target": "tag"}),
            (
                "exclusions-present",
                {
                    **current_ruleset_response,
                    "conditions": {
                        "ref_name": {
                            "include": ["refs/heads/proofgate-receipt-head-v1"],
                            "exclude": ["refs/heads/proofgate-receipt-head-v1"],
                        }
                    },
                },
            ),
            (
                "missing-creation",
                {
                    **current_ruleset_response,
                    "rules": [
                        {"type": "deletion"},
                        {"type": "non_fast_forward"},
                        {"type": "required_linear_history"},
                        {"type": "update"},
                    ],
                },
            ),
            (
                "missing-deletion",
                {
                    **current_ruleset_response,
                    "rules": [
                        {"type": "creation"},
                        {"type": "non_fast_forward"},
                        {"type": "required_linear_history"},
                        {"type": "update"},
                    ],
                },
            ),
            (
                "missing-non-fast-forward",
                {
                    **current_ruleset_response,
                    "rules": [
                        {"type": "creation"},
                        {"type": "deletion"},
                        {"type": "required_linear_history"},
                        {"type": "update"},
                    ],
                },
            ),
            (
                "missing-required-linear-history",
                {
                    **current_ruleset_response,
                    "rules": [
                        {"type": "creation"},
                        {"type": "deletion"},
                        {"type": "non_fast_forward"},
                        {"type": "update"},
                    ],
                },
            ),
            (
                "missing-update",
                {
                    **current_ruleset_response,
                    "rules": [
                        {"type": "creation"},
                        {"type": "deletion"},
                        {"type": "non_fast_forward"},
                        {"type": "required_linear_history"},
                    ],
                },
            ),
            (
                "extra-rule-type",
                {
                    **current_ruleset_response,
                    "rules": [
                        {"type": "creation"},
                        {"type": "deletion"},
                        {"type": "non_fast_forward"},
                        {"type": "pull_request"},
                        {"type": "required_linear_history"},
                        {"type": "update"},
                    ],
                },
            ),
        ]

        for label, mutated_ruleset in mutations:
            current_ruleset_response = mutated_ruleset
            with pytest.raises(ProofgateBootstrapVerifierError, match=r"(?i)ruleset|observation|rule|target|ref"):
                mutated_obs = boundary.observe()
                if mutated_obs is None:
                    raise ProofgateBootstrapVerifierError(f"PRR-ADMIN-002::{label} observation rejected")
                verify_proofgate_admin_identity_binding(boundary)

    run_proofgate_contract(nodeid, contract)


def test_pr_r_evid_003_pr_b_candidate_digests_bound_to_observation(monkeypatch):
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_pr_r_evid_003_pr_b_candidate_digests_bound_to_observation"

    def contract():
        try:
            from . import proofgate_bootstrap_verifier
            from .proofgate_bootstrap_verifier import (
                ProofgateAdminControlPlaneBoundary,
                verify_observed_premerge_bootstrap_review_gate,
            )
        except (ImportError, AttributeError) as exc:
            raise ProofgateMissingCapabilityError(
                "PRR-EVID-003::verify_observed_premerge_bootstrap_review_gate_unimplemented"
            ) from exc

        (
            _tmp,
            repo,
            original_oid,
            base_oid,
            candidate_oid,
            boundary,
            coordinator_root,
            _coordinator_tmp,
        ) = _setup_pr_r_candidate_history()

        real_verify_binding = proofgate_bootstrap_verifier.verify_bootstrap_candidate_binding

        def patched_verify_binding(repo_path, binding_path, expected_original_tests_landing=None):
            return real_verify_binding(
                repo_path=repo_path,
                binding_path=binding_path,
                expected_original_tests_landing=original_oid,
            )

        monkeypatch.setattr(
            proofgate_bootstrap_verifier, "verify_bootstrap_candidate_binding", patched_verify_binding
        )

        def fake_admin_authority(**_kwargs):
            return {
                "schema": "proofgate_admin_identity_binding.v1",
                "authority": "github_and_broker_control_planes",
                "binding_digest": "a" * 64,
            }

        monkeypatch.setattr(
            proofgate_bootstrap_verifier, "verify_proofgate_admin_authority", fake_admin_authority
        )

        admin_boundary = ProofgateAdminControlPlaneBoundary()

        with _coordinator_run_dir(coordinator_root):
            pos_res = verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
            )
        assert pos_res["decisive"] is True
        assert pos_res["evidence_kind"] == "coordinator_external_observation"

        _thaw_coordinator_root(coordinator_root)
        omission_payload = json.loads(
            (coordinator_root / "bootstrap-observation.json").read_text(encoding="utf-8")
        )
        omission_payload["candidate_artifact_digests"] = []
        omission_observation = proofgate_bootstrap_verifier._bootstrap_observation_from_payload(
            omission_payload
        )
        _write_coordinator_observation(coordinator_root, omission_observation, "PR-B")
        _freeze_coordinator_root(coordinator_root)

        with _coordinator_run_dir(coordinator_root), pytest.raises(
            ProofgateBootstrapVerifierError,
            match=r"(?i)candidate artifact digest",
        ):
            verify_observed_premerge_bootstrap_review_gate(
                repo,
                base_oid,
                candidate_oid,
                landing_kind="PR-B",
                boundary=boundary,
                admin_boundary=admin_boundary,
            )

        # Co-substitute candidate bytes on disk and internally recompute verdict/binding digests
        _thaw_coordinator_root(coordinator_root)
        cand_junit = coordinator_root / "compat-candidate.junit.xml"
        cand_reports = coordinator_root / "phase_reports_candidate.json"
        verdict_file = coordinator_root / "bootstrap-candidate-verdict.json"
        binding_file = coordinator_root / "bootstrap-candidate-binding.json"
        original_cand_junit = cand_junit.read_bytes()
        original_verdict = verdict_file.read_bytes()

        cand_junit.write_text(cand_junit.read_text(encoding="utf-8") + "<!-- modified -->\n", encoding="utf-8")
        cand_junit_sha = hashlib.sha256(cand_junit.read_bytes()).hexdigest()
        cand_reports_sha = hashlib.sha256(cand_reports.read_bytes()).hexdigest()
        cand_binding_sha = hashlib.sha256(binding_file.read_bytes()).hexdigest()

        verdict_data = json.loads(verdict_file.read_text(encoding="utf-8"))
        verdict_data["junit_digest"] = cand_junit_sha
        verdict_data["phase_reports_digest"] = cand_reports_sha
        verdict_data["binding_digest"] = cand_binding_sha
        verdict_bytes = json.dumps(verdict_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        verdict_file.write_bytes(verdict_bytes)
        _freeze_coordinator_root(coordinator_root)

        # First assert unchanged observation fails because its schema/digests omit candidate bytes
        with _coordinator_run_dir(coordinator_root), pytest.raises(
            ProofgateBootstrapVerifierError, match=r"(?i)candidate|digest|observation"
        ):
            verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
            )

        # A fresh observation that binds every candidate artifact must remain
        # authorizable; fail-closed-only behavior is not a repair.
        _thaw_coordinator_root(coordinator_root)
        cand_junit.write_bytes(original_cand_junit)
        verdict_file.write_bytes(original_verdict)
        candidate_artifacts = _pr_b_candidate_artifact_names(coordinator_root)
        observation_payload = json.loads(
            (coordinator_root / "bootstrap-observation.json").read_text(encoding="utf-8")
        )
        observation_payload["candidate_artifact_digests"] = [
            [filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest()]
            for filename in candidate_artifacts
        ]
        bound_observation = proofgate_bootstrap_verifier._bootstrap_observation_from_payload(
            observation_payload
        )
        _write_coordinator_observation(coordinator_root, bound_observation, "PR-B")
        _freeze_coordinator_root(coordinator_root)

        with _coordinator_run_dir(coordinator_root):
            result = verify_observed_premerge_bootstrap_review_gate(
                repo,
                base_oid,
                candidate_oid,
                landing_kind="PR-B",
                boundary=boundary,
                admin_boundary=admin_boundary,
            )
        assert result["decisive"] is True
        assert result["evidence_kind"] == "coordinator_external_observation"

    run_proofgate_contract(nodeid, contract)


def test_pr_r_bind_004_strict_candidate_binding_rejects_capability_marker():
    nodeid = "phase-loop-runtime/tests/test_tdd_chronology.py::test_pr_r_bind_004_strict_candidate_binding_rejects_capability_marker"

    def contract():
        try:
            from .proofgate_bootstrap_verifier import (
                _verifier_cat_git_file,
                parse_git_diff_tree_raw,
                verify_bootstrap_candidate_binding,
            )
        except (ImportError, AttributeError) as exc:
            raise ProofgateMissingCapabilityError(
                "PRR-BIND-004::verify_bootstrap_candidate_binding_unimplemented"
            ) from exc

        # Case 1: Capability marker present unchanged in base and candidate
        (
            _tmp1,
            repo1,
            original_oid1,
            base_oid1,
            _candidate_oid1,
            _boundary1,
            coordinator_root1,
            _coordinator_tmp1,
        ) = _setup_pr_r_candidate_history()

        subprocess.run(["git", "checkout", "-b", "cap-base1", base_oid1], cwd=repo1, capture_output=True, check=True)
        cap_file1 = repo1 / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "proofgate_capability.py"
        cap_file1.parent.mkdir(parents=True, exist_ok=True)
        cap_file1.write_text('PROOFGATE_CAPABILITY_VERSION = "proofgate.v1"\n', encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo1, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Base with capability marker"], cwd=repo1, capture_output=True, check=True)
        new_base_oid1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo1, capture_output=True, text=True, check=True).stdout.strip()

        subprocess.run(["git", "checkout", "-b", "cap-cand1", new_base_oid1], cwd=repo1, capture_output=True, check=True)
        for rel_path in PR_B_5_PATHS:
            path = repo1 / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# bootstrap candidate {rel_path}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo1, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-B 5 bootstrap paths"], cwd=repo1, capture_output=True, check=True)
        new_cand_oid1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo1, capture_output=True, text=True, check=True).stdout.strip()
        new_cand_tree_oid1 = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo1, capture_output=True, text=True, check=True).stdout.strip()

        diff_raw1 = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", new_base_oid1, new_cand_oid1], cwd=repo1, capture_output=True, check=True).stdout
        diff_digest1 = hashlib.sha256(diff_raw1).hexdigest()

        changes1 = parse_git_diff_tree_raw(repo1, new_base_oid1, new_cand_oid1)
        expected_changes1 = [
            [kind, path, new_mode, old_blob, new_blob, file_sha]
            for kind, path, _old_mode, new_mode, old_blob, new_blob, file_sha in changes1
        ]

        test_contract_digests1 = {}
        for path in PR_B_TEST_CONTRACT_FILES:
            selector_bytes = _verifier_cat_git_file(base_oid1, path, cwd=repo1)
            test_contract_digests1[path] = hashlib.sha256(selector_bytes).hexdigest()

        binding_path1 = coordinator_root1 / "bootstrap-candidate-binding.json"
        _thaw_coordinator_root(coordinator_root1)
        binding_data1 = json.loads(binding_path1.read_text(encoding="utf-8"))
        binding_data1["selector_repair_landing_oid"] = base_oid1
        binding_data1["base_oid"] = new_base_oid1
        binding_data1["candidate_oid"] = new_cand_oid1
        binding_data1["candidate_tree_oid"] = new_cand_tree_oid1
        binding_data1["diff_sha256"] = diff_digest1
        binding_data1["changes"] = expected_changes1
        binding_data1["test_contract_sha256"] = test_contract_digests1
        binding_path1.write_bytes((json.dumps(binding_data1, separators=(",", ":")) + "\n").encode("utf-8"))
        _freeze_coordinator_root(coordinator_root1)

        with pytest.raises(
            ProofgateBootstrapVerifierError,
            match=r"(?i)capability|marker",
        ):
            verify_bootstrap_candidate_binding(
                repo_path=repo1,
                binding_path=binding_path1,
                expected_original_tests_landing=original_oid1,
            )

        # Case 2: Capability marker introduced in candidate commit
        (
            _tmp2,
            repo2,
            original_oid2,
            base_oid2,
            _candidate_oid2,
            _boundary2,
            coordinator_root2,
            _coordinator_tmp2,
        ) = _setup_pr_r_candidate_history()

        subprocess.run(["git", "checkout", "-b", "cap-cand2", base_oid2], cwd=repo2, capture_output=True, check=True)
        for rel_path in PR_B_5_PATHS:
            path = repo2 / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# bootstrap candidate {rel_path}\n", encoding="utf-8")
        cap_file2 = repo2 / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "proofgate_capability.py"
        cap_file2.parent.mkdir(parents=True, exist_ok=True)
        cap_file2.write_text('PROOFGATE_CAPABILITY_VERSION = "proofgate.v1"\n', encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo2, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-B 5 bootstrap paths + capability marker"], cwd=repo2, capture_output=True, check=True)
        new_cand_oid2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo2, capture_output=True, text=True, check=True).stdout.strip()
        new_cand_tree_oid2 = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo2, capture_output=True, text=True, check=True).stdout.strip()

        diff_raw2 = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid2, new_cand_oid2], cwd=repo2, capture_output=True, check=True).stdout
        diff_digest2 = hashlib.sha256(diff_raw2).hexdigest()

        changes2 = parse_git_diff_tree_raw(repo2, base_oid2, new_cand_oid2)
        expected_changes2 = [
            [kind, path, new_mode, old_blob, new_blob, file_sha]
            for kind, path, _old_mode, new_mode, old_blob, new_blob, file_sha in changes2
        ]

        test_contract_digests2 = {}
        for path in PR_B_TEST_CONTRACT_FILES:
            selector_bytes = _verifier_cat_git_file(base_oid2, path, cwd=repo2)
            test_contract_digests2[path] = hashlib.sha256(selector_bytes).hexdigest()

        binding_path2 = coordinator_root2 / "bootstrap-candidate-binding.json"
        _thaw_coordinator_root(coordinator_root2)
        binding_data2 = json.loads(binding_path2.read_text(encoding="utf-8"))
        binding_data2["selector_repair_landing_oid"] = base_oid2
        binding_data2["base_oid"] = base_oid2
        binding_data2["candidate_oid"] = new_cand_oid2
        binding_data2["candidate_tree_oid"] = new_cand_tree_oid2
        binding_data2["diff_sha256"] = diff_digest2
        binding_data2["changes"] = expected_changes2
        binding_data2["test_contract_sha256"] = test_contract_digests2
        binding_path2.write_bytes((json.dumps(binding_data2, separators=(",", ":")) + "\n").encode("utf-8"))
        _freeze_coordinator_root(coordinator_root2)

        with pytest.raises(
            ProofgateBootstrapVerifierError,
            match=r"(?i)capability|marker|five bootstrap paths|changes",
        ):
            verify_bootstrap_candidate_binding(
                repo_path=repo2,
                binding_path=binding_path2,
                expected_original_tests_landing=original_oid2,
            )

    run_proofgate_contract(nodeid, contract)


def test_pr_r_evid_004_decisive_pr_b_candidate_and_compat_capture_provenance(monkeypatch):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            ProofgateAdminControlPlaneBoundary,
            verify_observed_premerge_bootstrap_review_gate,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "PRR-EVID-004::candidate_capture_provenance_unimplemented"
        ) from exc

    (
        _tmp,
        repo,
        original_oid,
        base_oid,
        candidate_oid,
        boundary,
        coordinator_root,
        _coordinator_tmp,
    ) = _setup_pr_r_candidate_history()

    real_verify_binding = proofgate_bootstrap_verifier.verify_bootstrap_candidate_binding

    def patched_verify_binding(repo_path, binding_path, expected_original_tests_landing=None):
        return real_verify_binding(
            repo_path=repo_path,
            binding_path=binding_path,
            expected_original_tests_landing=original_oid,
        )

    monkeypatch.setattr(
        proofgate_bootstrap_verifier, "verify_bootstrap_candidate_binding", patched_verify_binding
    )

    def fake_admin_authority(**_kwargs):
        return {
            "schema": "proofgate_admin_identity_binding.v1",
            "authority": "github_and_broker_control_planes",
            "binding_digest": "a" * 64,
        }

    monkeypatch.setattr(
        proofgate_bootstrap_verifier, "verify_proofgate_admin_authority", fake_admin_authority
    )

    admin_boundary = ProofgateAdminControlPlaneBoundary()

    with _coordinator_run_dir(coordinator_root):
        pos_res = verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )
    assert pos_res["decisive"] is True
    assert pos_res["evidence_kind"] == "coordinator_external_observation"

    def _sync_observation_and_digests():
        cand_reports_file = coordinator_root / "phase_reports_candidate.json"
        cand_junit_file = coordinator_root / "compat-candidate.junit.xml"
        binding_file = coordinator_root / "bootstrap-candidate-binding.json"
        verdict_file = coordinator_root / "bootstrap-candidate-verdict.json"
        def_reports_file = coordinator_root / "phase_reports_default.json"
        red_reports_file = coordinator_root / "phase_reports_forced_red.json"

        cand_reports_digest = hashlib.sha256(cand_reports_file.read_bytes()).hexdigest()
        cand_junit_digest = hashlib.sha256(cand_junit_file.read_bytes()).hexdigest()
        binding_digest = hashlib.sha256(binding_file.read_bytes()).hexdigest()

        verdict_payload = json.loads(verdict_file.read_text(encoding="utf-8"))
        verdict_payload["phase_reports_digest"] = cand_reports_digest
        verdict_payload["junit_digest"] = cand_junit_digest
        verdict_payload["binding_digest"] = binding_digest
        verdict_file.write_bytes(json.dumps(verdict_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))

        cand_payload = json.loads(cand_reports_file.read_text(encoding="utf-8"))
        def_payload = json.loads(def_reports_file.read_text(encoding="utf-8"))
        red_payload = json.loads(red_reports_file.read_text(encoding="utf-8"))

        reports_by_mode = {
            "default": {"reports": def_payload["reports"]},
            "forced_red": {"reports": red_payload["reports"]},
            "bootstrap_candidate": {"reports": cand_payload["reports"]},
        }

        obs_payload = json.loads(
            (coordinator_root / "bootstrap-observation.json").read_text(encoding="utf-8")
        )
        obs_payload["junit_phase_reports_json"] = json.dumps(reports_by_mode, sort_keys=True, separators=(",", ":"))
        obs_payload["junit_phase_report_digests"] = [
            ["phase_reports_default.json", hashlib.sha256(def_reports_file.read_bytes()).hexdigest()],
            ["phase_reports_forced_red.json", hashlib.sha256(red_reports_file.read_bytes()).hexdigest()],
        ]
        candidate_artifacts = _pr_b_candidate_artifact_names(coordinator_root)
        obs_payload["candidate_artifact_digests"] = [
            [filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest()]
            for filename in candidate_artifacts
        ]
        obs = proofgate_bootstrap_verifier._bootstrap_observation_from_payload(obs_payload)
        _write_coordinator_observation(coordinator_root, obs, "PR-B")

    cand_reports_file = coordinator_root / "phase_reports_candidate.json"
    def_reports_file = coordinator_root / "phase_reports_default.json"
    orig_cand_reports_bytes = cand_reports_file.read_bytes()

    # Independent mutation 1: Wrong candidate argv and command digest
    _thaw_coordinator_root(coordinator_root)
    payload1 = json.loads(cand_reports_file.read_text(encoding="utf-8"))
    payload1["reports"][0]["argv"] = ["pytest", "wrong_nodeid"]
    payload1["reports"][0]["command_digest"] = hashlib.sha256(json.dumps(payload1["reports"][0]["argv"]).encode("utf-8")).hexdigest()
    payload1["runs"][0]["reports"] = payload1["reports"]
    cand_reports_file.write_bytes(json.dumps(payload1, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)candidate|capture|argv|command digest",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )

    # Restore fixture state
    _thaw_coordinator_root(coordinator_root)
    cand_reports_file.write_bytes(orig_cand_reports_bytes)
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    # Independent mutation 2: Wrong candidate exitstatus
    _thaw_coordinator_root(coordinator_root)
    payload2 = json.loads(cand_reports_file.read_text(encoding="utf-8"))
    payload2["exitstatus"] = 1
    payload2["runs"][0]["exitstatus"] = 1
    cand_reports_file.write_bytes(json.dumps(payload2, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)candidate|capture|exitstatus",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )

    # Restore fixture state
    _thaw_coordinator_root(coordinator_root)
    cand_reports_file.write_bytes(orig_cand_reports_bytes)
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    # Independent mutation 3: Wrong candidate pytest_args_sha256 in capture
    _thaw_coordinator_root(coordinator_root)
    payload3 = json.loads(cand_reports_file.read_text(encoding="utf-8"))
    payload3["capture"]["pytest_args_sha256"] = "0" * 64
    cand_reports_file.write_bytes(json.dumps(payload3, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)candidate|capture|pytest_args",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )

    # Restore fixture state
    _thaw_coordinator_root(coordinator_root)
    cand_reports_file.write_bytes(orig_cand_reports_bytes)
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    # Independent mutation 4: Wrong candidate junit_filename in capture
    _thaw_coordinator_root(coordinator_root)
    payload4 = json.loads(cand_reports_file.read_text(encoding="utf-8"))
    payload4["capture"]["junit_filename"] = "wrong-candidate.junit.xml"
    cand_reports_file.write_bytes(json.dumps(payload4, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)candidate|capture|junit_filename",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )

    # Restore fixture state
    _thaw_coordinator_root(coordinator_root)
    cand_reports_file.write_bytes(orig_cand_reports_bytes)
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    # Independent mutation 5: Default mode phase report uses legacy proofgate-tests-only-default.junit.xml in argv and capture pytest_args_sha256 instead of compat-default.junit.xml
    _thaw_coordinator_root(coordinator_root)
    def_payload = json.loads(def_reports_file.read_text(encoding="utf-8"))

    legacy_pytest_args = coordinator_evidence_capture_pytest_args("default")
    legacy_argv = ["pytest", *legacy_pytest_args]
    legacy_cmd_digest = hashlib.sha256(json.dumps(legacy_argv).encode("utf-8")).hexdigest()

    for report in def_payload["reports"]:
        report["argv"] = legacy_argv
        report["command_digest"] = legacy_cmd_digest
    def_payload["runs"][0]["reports"] = def_payload["reports"]
    def_payload["capture"]["pytest_args_sha256"] = hashlib.sha256(
        json.dumps(list(legacy_pytest_args)).encode("utf-8")
    ).hexdigest()

    def_reports_file.write_bytes(json.dumps(def_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    _sync_observation_and_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)default|proofgate-tests-only|argv|pytest_args|command digest",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )


def test_pr_r_bind_005_decisive_pr_b_candidate_binding_base_cand_and_diff_digest(monkeypatch):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            ProofgateAdminControlPlaneBoundary,
            verify_observed_premerge_bootstrap_review_gate,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "PRR-BIND-005::candidate_binding_pair_matching_unimplemented"
        ) from exc

    (
        _tmp,
        repo,
        original_oid,
        base_oid,
        candidate_oid,
        boundary,
        coordinator_root,
        _coordinator_tmp,
    ) = _setup_pr_r_candidate_history()

    def patched_verify_binding(repo_path, binding_path, expected_original_tests_landing=None):
        binding_bytes = Path(binding_path).read_bytes()
        binding_data = json.loads(binding_bytes.decode("utf-8"))
        return {
            "status": "verified",
            "binding_data": binding_data,
            "binding_bytes": binding_bytes,
            "binding_digest": hashlib.sha256(binding_bytes).hexdigest(),
        }

    monkeypatch.setattr(
        proofgate_bootstrap_verifier, "verify_bootstrap_candidate_binding", patched_verify_binding
    )

    def verified_capture_for_binding_test(coordinator_root, mode, **_kwargs):
        report_filenames = {
            "default": "phase_reports_default.json",
            "forced_red": "phase_reports_forced_red.json",
            "bootstrap_candidate": "phase_reports_candidate.json",
        }
        payload = json.loads(
            (Path(coordinator_root) / report_filenames[mode]).read_text(encoding="utf-8")
        )
        return {"reports": payload["reports"]}

    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "verify_coordinator_evidence_capture",
        verified_capture_for_binding_test,
    )

    def fake_admin_authority(**_kwargs):
        return {
            "schema": "proofgate_admin_identity_binding.v1",
            "authority": "github_and_broker_control_planes",
            "binding_digest": "a" * 64,
        }

    monkeypatch.setattr(
        proofgate_bootstrap_verifier, "verify_proofgate_admin_authority", fake_admin_authority
    )

    admin_boundary = ProofgateAdminControlPlaneBoundary()

    with _coordinator_run_dir(coordinator_root):
        pos_res = verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )
    assert pos_res["decisive"] is True
    assert pos_res["evidence_kind"] == "coordinator_external_observation"

    def _sync_candidate_digests():
        binding_path = coordinator_root / "bootstrap-candidate-binding.json"
        binding_bytes = binding_path.read_bytes()
        binding_sha = hashlib.sha256(binding_bytes).hexdigest()

        verdict_path = coordinator_root / "bootstrap-candidate-verdict.json"
        verdict_payload = json.loads(verdict_path.read_text(encoding="utf-8"))
        verdict_payload["binding_digest"] = binding_sha
        verdict_bytes = json.dumps(verdict_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        verdict_path.write_bytes(verdict_bytes)

        candidate_artifacts = _pr_b_candidate_artifact_names(coordinator_root)
        obs_payload = json.loads(
            (coordinator_root / "bootstrap-observation.json").read_text(encoding="utf-8")
        )
        obs_payload["candidate_artifact_digests"] = [
            [filename, hashlib.sha256((coordinator_root / filename).read_bytes()).hexdigest()]
            for filename in candidate_artifacts
        ]
        obs = proofgate_bootstrap_verifier._bootstrap_observation_from_payload(obs_payload)
        _write_coordinator_observation(coordinator_root, obs, "PR-B")

    binding_file = coordinator_root / "bootstrap-candidate-binding.json"
    orig_binding_bytes = binding_file.read_bytes()

    # Independent Mutation 1: Stale base OID in candidate binding
    _thaw_coordinator_root(coordinator_root)
    binding_data1 = json.loads(binding_file.read_bytes())
    binding_data1["base_oid"] = original_oid
    binding_file.write_bytes((json.dumps(binding_data1, separators=(",", ":")) + "\n").encode("utf-8"))
    _sync_candidate_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)base_oid|base|stale|binding",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )

    # Restore fixture state
    _thaw_coordinator_root(coordinator_root)
    binding_file.write_bytes(orig_binding_bytes)
    _sync_candidate_digests()
    _freeze_coordinator_root(coordinator_root)

    # Independent Mutation 2: Stale candidate OID in candidate binding
    _thaw_coordinator_root(coordinator_root)
    binding_data2 = json.loads(binding_file.read_bytes())
    binding_data2["base_oid"] = base_oid
    binding_data2["candidate_oid"] = original_oid
    binding_file.write_bytes((json.dumps(binding_data2, separators=(",", ":")) + "\n").encode("utf-8"))
    _sync_candidate_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)candidate_oid|candidate|stale|binding",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )

    # Restore fixture state
    _thaw_coordinator_root(coordinator_root)
    binding_file.write_bytes(orig_binding_bytes)
    _sync_candidate_digests()
    _freeze_coordinator_root(coordinator_root)

    # Independent Mutation 3: Mismatched binding diff_sha256 vs candidate verdict source_digest
    _thaw_coordinator_root(coordinator_root)
    binding_data3 = json.loads(binding_file.read_bytes())
    binding_data3["candidate_oid"] = candidate_oid
    binding_data3["diff_sha256"] = "3" * 64
    binding_file.write_bytes((json.dumps(binding_data3, separators=(",", ":")) + "\n").encode("utf-8"))
    _sync_candidate_digests()
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)diff_sha256|source_digest|mismatch|binding",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, candidate_oid, landing_kind="PR-B", boundary=boundary, admin_boundary=admin_boundary
        )


def _install_pr_r_admin_control_plane_fakes(monkeypatch, proofgate_bootstrap_verifier):
    from .proofgate_bootstrap_verifier import ProofgateAdminControlPlaneBoundary

    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "_github_cli_sha256",
        lambda path: proofgate_bootstrap_verifier.GITHUB_CLI_SHA256,
    )

    state = {
        "environment_id": 440001,
        "ruleset_id": 550001,
        "extra_repository": False,
        "extra_ruleset": False,
    }
    paginated_calls: list[str] = []
    claim_policy = {
        "audience": "urn:consiliency:proofgate:github-app-installation-token:repository:1280382652",
        "event_name": "workflow_dispatch",
        "repository_id": "1280382652",
        "repository_owner_id": "159201120",
        "workflow_ref": "Consiliency/agent-harness/.github/workflows/proofgate-receipt-attestation.yml@refs/heads/main",
    }
    claim_policy_digest = hashlib.sha256(
        json.dumps(claim_policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    def installation() -> dict:
        return {
            "id": 880001,
            "app_slug": "proofgate-app",
            "app_id": 990001,
            "target_id": 159201120,
            "repository_selection": "selected",
            "permissions": {"contents": "write", "metadata": "read"},
        }

    def ruleset_row() -> dict:
        return {
            "id": state["ruleset_id"],
            "name": "proofgate-receipt-head-v1",
            "enforcement": "active",
        }

    def broker_payload() -> dict:
        repositories = [{"id": 1280382652, "full_name": "Consiliency/agent-harness"}]
        if state["extra_repository"]:
            repositories.append({"id": 1280382653, "full_name": "Consiliency/other"})
        return {
            "schema": "proofgate_broker_admin_metadata.v1",
            "deployment_id": "proofgate-broker-v1",
            "key_version": "v1",
            "app_id": "990001",
            "installation_id": "880001",
            "repository_id": "1280382652",
            "selected_repository_total_count": len(repositories),
            "selected_repositories": repositories,
            "permissions": [["contents", "write"]],
            "claim_policy": claim_policy,
            "claim_policy_digest": claim_policy_digest,
        }

    def fake_gh_api(endpoint: str):
        endpoint = endpoint.split("?", 1)[0]
        if endpoint == "repos/Consiliency/agent-harness":
            return {
                "id": 1280382652,
                "full_name": "Consiliency/agent-harness",
                "owner": {"id": 159201120},
            }
        if endpoint == "apps/proofgate-app":
            return {"id": 990001, "slug": "proofgate-app", "owner": {"id": 159201120}}
        if endpoint == "orgs/Consiliency/installations":
            return {"total_count": 1, "installations": [installation()]}
        if endpoint == "user/installations/880001/repositories":
            return {
                "total_count": 1,
                "repositories": [
                    {"id": 1280382652, "full_name": "Consiliency/agent-harness"}
                ],
            }
        if endpoint == "orgs/Consiliency/members/proofgate-reviewer":
            return {}
        if endpoint == "repos/Consiliency/agent-harness/environments/proofgate-receipt-head-v1":
            return {
                "id": state["environment_id"],
                "name": "proofgate-receipt-head-v1",
                "can_admins_bypass": False,
                "protection_rules": [
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": True,
                        "reviewers": [
                            {
                                "type": "User",
                                "reviewer": {"id": 770001, "login": "proofgate-reviewer"},
                            }
                        ],
                    }
                ],
            }
        if endpoint == "repos/Consiliency/agent-harness/rulesets":
            return [ruleset_row()]
        if endpoint == f"repos/Consiliency/agent-harness/rulesets/{state['ruleset_id']}":
            return {
                **ruleset_row(),
                "target": "branch",
                "conditions": {
                    "ref_name": {
                        "include": ["refs/heads/proofgate-receipt-head-v1"],
                        "exclude": [],
                    }
                },
                "rules": [
                    {"type": "creation"},
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                    {"type": "required_linear_history"},
                    {"type": "update"},
                ],
                "bypass_actors": [
                    {
                        "actor_type": "Integration",
                        "actor_id": 990001,
                        "bypass_mode": "always",
                    }
                ],
            }
        raise AssertionError(f"unexpected GitHub endpoint: {endpoint}")

    def fake_gh_api_pages(endpoint: str):
        paginated_calls.append(endpoint)
        if endpoint == "orgs/Consiliency/installations":
            return [[installation()]]
        if endpoint == "repos/Consiliency/agent-harness/rulesets":
            rows = [ruleset_row()]
            if state["extra_ruleset"]:
                rows.append({**ruleset_row(), "id": state["ruleset_id"] + 1})
            return [rows]
        raise AssertionError(f"unexpected paginated GitHub endpoint: {endpoint}")

    monkeypatch.setattr(ProofgateAdminControlPlaneBoundary, "_gh_api", staticmethod(fake_gh_api))
    monkeypatch.setattr(
        ProofgateAdminControlPlaneBoundary,
        "_gh_api_pages",
        staticmethod(fake_gh_api_pages),
        raising=False,
    )
    monkeypatch.setattr(
        ProofgateAdminControlPlaneBoundary,
        "_broker_metadata",
        classmethod(lambda cls: broker_payload()),
    )

    real_subprocess_run = subprocess.run

    def fake_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "orgs/Consiliency/members/proofgate-reviewer" in " ".join(cmd):
            return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
        return real_subprocess_run(cmd, **kwargs)

    monkeypatch.setattr(proofgate_bootstrap_verifier.subprocess, "run", fake_subprocess_run)
    return ProofgateAdminControlPlaneBoundary(), state, paginated_calls


def test_pr_r_blocker_fable_f001_requires_review_artifact_and_candidate_cross_binding(monkeypatch):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            ProofgateAdminControlPlaneBoundary,
            verify_selector_repair_review_binding,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "FABLE-F001::selector_repair_review_binding_unimplemented"
        ) from exc

    history_a = _setup_pr_r_candidate_history(selector_suffix="-reviewed")
    _, repo_a, original_a, landing_a, candidate_a, boundary_a, root_a, _ = history_a
    _thaw_coordinator_root(root_a)
    review_path = root_a / "selector-repair-review-binding.json"
    _write_selector_repair_review_binding(repo_a, original_a, landing_a, review_path)
    verified = verify_selector_repair_review_binding(
        repo_path=repo_a,
        review_binding_path=review_path,
        expected_original_tests_landing=original_a,
        expected_selector_repair_landing=landing_a,
    )
    assert verified["status"] == "verified"

    history_b = _setup_pr_r_candidate_history(selector_suffix="-substituted")
    _, repo_b, original_b, landing_b, *_ = history_b
    with pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)reviewed.*(change tuple|source head|landing)|selector repair review binding mismatch",
    ):
        verify_selector_repair_review_binding(
            repo_path=repo_b,
            review_binding_path=review_path,
            expected_original_tests_landing=original_b,
            expected_selector_repair_landing=landing_b,
        )

    review_bytes = review_path.read_bytes()
    _sync_pr_b_candidate_artifact_digests(
        proofgate_bootstrap_verifier,
        root_a,
        (*PR_B_CANDIDATE_ARTIFACTS, "selector-repair-review-binding.json"),
    )
    _freeze_coordinator_root(root_a)
    real_verify_binding = proofgate_bootstrap_verifier.verify_bootstrap_candidate_binding
    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "verify_bootstrap_candidate_binding",
        lambda repo_path, binding_path, expected_original_tests_landing=None: real_verify_binding(
            repo_path=repo_path,
            binding_path=binding_path,
            expected_original_tests_landing=original_a,
        ),
    )
    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "verify_proofgate_admin_authority",
        lambda **_kwargs: {"authority": "github_and_broker_control_planes", "binding_digest": "a" * 64},
    )
    with _coordinator_run_dir(root_a):
        assert verify_observed_premerge_bootstrap_review_gate(
            repo_a,
            landing_a,
            candidate_a,
            landing_kind="PR-B",
            boundary=boundary_a,
            admin_boundary=ProofgateAdminControlPlaneBoundary(),
        )["decisive"] is True

    _thaw_coordinator_root(root_a)
    review_path.unlink()
    _sync_pr_b_candidate_artifact_digests(
        proofgate_bootstrap_verifier, root_a, PR_B_CANDIDATE_ARTIFACTS
    )
    _freeze_coordinator_root(root_a)
    with _coordinator_run_dir(root_a), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)selector.*repair.*review|review.*binding|required.*artifact",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo_a,
            landing_a,
            candidate_a,
            landing_kind="PR-B",
            boundary=boundary_a,
            admin_boundary=ProofgateAdminControlPlaneBoundary(),
        )

    _thaw_coordinator_root(root_a)
    review_path.write_bytes(review_bytes)
    _sync_pr_b_candidate_artifact_digests(
        proofgate_bootstrap_verifier,
        root_a,
        (*PR_B_CANDIDATE_ARTIFACTS, "selector-repair-review-binding.json"),
    )
    _freeze_coordinator_root(root_a)
    candidate_binding = json.loads(
        (root_a / "bootstrap-candidate-binding.json").read_text(encoding="utf-8")
    )
    candidate_binding["selector_repair_landing_oid"] = original_a
    review_binding = json.loads(review_bytes)
    with monkeypatch.context() as mismatch:
        mismatch.setattr(
            proofgate_bootstrap_verifier,
            "verify_bootstrap_candidate_binding",
            lambda **_kwargs: {"status": "verified", "binding_data": candidate_binding},
        )
        mismatch.setattr(
            proofgate_bootstrap_verifier,
            "verify_selector_repair_review_binding",
            lambda **_kwargs: {"status": "verified", "binding_data": review_binding},
        )
        with _coordinator_run_dir(root_a), pytest.raises(
            ProofgateBootstrapVerifierError,
            match=r"(?i)selector.*repair.*landing|review.*binding|candidate.*binding",
        ):
            verify_observed_premerge_bootstrap_review_gate(
                repo_a,
                landing_a,
                candidate_a,
                landing_kind="PR-B",
                boundary=boundary_a,
                admin_boundary=ProofgateAdminControlPlaneBoundary(),
            )


def test_pr_r_blocker_fable_f002_rejects_instance_observe_replacement(monkeypatch):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            verify_proofgate_admin_identity_binding,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "FABLE-F002::exact_admin_boundary_instance_check_unimplemented"
        ) from exc

    boundary, _state, _calls = _install_pr_r_admin_control_plane_fakes(
        monkeypatch, proofgate_bootstrap_verifier
    )
    assert verify_proofgate_admin_identity_binding(boundary)["authority"] == (
        "github_and_broker_control_planes"
    )

    monkeypatch.setattr(boundary, "observe", lambda: {"fixture": "replaced"})
    with pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)exact.*boundary|instance.*observe|replaced.*observe|control plane",
    ):
        verify_proofgate_admin_identity_binding(boundary)


@pytest.mark.parametrize(
    ("field", "substituted"),
    (
        ("mode", "default"),
        ("candidate_oid", "0" * 40),
        ("run_identity", "replayed-run"),
    ),
)
def test_pr_r_blocker_prr_evidence_provenance_003_candidate_identity(
    monkeypatch, field, substituted
):
    from . import proofgate_bootstrap_verifier
    from .proofgate_bootstrap_verifier import ProofgateAdminControlPlaneBoundary

    (
        _tmp,
        repo,
        original_oid,
        base_oid,
        candidate_oid,
        boundary,
        coordinator_root,
        _coordinator_tmp,
    ) = _setup_pr_r_candidate_history()
    real_verify_binding = proofgate_bootstrap_verifier.verify_bootstrap_candidate_binding
    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "verify_bootstrap_candidate_binding",
        lambda repo_path, binding_path, expected_original_tests_landing=None: real_verify_binding(
            repo_path=repo_path,
            binding_path=binding_path,
            expected_original_tests_landing=original_oid,
        ),
    )
    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "verify_proofgate_admin_authority",
        lambda **_kwargs: {"authority": "github_and_broker_control_planes", "binding_digest": "a" * 64},
    )
    admin_boundary = ProofgateAdminControlPlaneBoundary()
    with _coordinator_run_dir(coordinator_root):
        assert verify_observed_premerge_bootstrap_review_gate(
            repo,
            base_oid,
            candidate_oid,
            landing_kind="PR-B",
            boundary=boundary,
            admin_boundary=admin_boundary,
        )["decisive"] is True

    reports_path = coordinator_root / "phase_reports_candidate.json"
    _thaw_coordinator_root(coordinator_root)
    reports_payload = json.loads(reports_path.read_text(encoding="utf-8"))
    assert reports_payload["capture"] == {
        **reports_payload["capture"],
        "mode": "bootstrap_candidate",
        "candidate_oid": candidate_oid,
        "run_identity": "coordinator-candidate",
    }
    assert reports_payload["runs"][0]["run_identity"] == "coordinator-candidate"
    assert all(report["candidate"] == candidate_oid for report in reports_payload["reports"])
    assert all(
        report["run_identity"] == "coordinator-candidate"
        for report in reports_payload["reports"]
    )
    reports_payload["capture"][field] = substituted
    reports_path.write_bytes(
        json.dumps(reports_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    verdict_path = coordinator_root / "bootstrap-candidate-verdict.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["phase_reports_digest"] = hashlib.sha256(reports_path.read_bytes()).hexdigest()
    verdict_path.write_bytes(
        json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    _sync_pr_b_candidate_artifact_digests(
        proofgate_bootstrap_verifier,
        coordinator_root,
        (*PR_B_CANDIDATE_ARTIFACTS, "selector-repair-review-binding.json"),
    )
    _freeze_coordinator_root(coordinator_root)

    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=rf"(?i)bootstrap_candidate.*{field}|candidate capture.*{field}|capture receipt mismatch",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo,
            base_oid,
            candidate_oid,
            landing_kind="PR-B",
            boundary=boundary,
            admin_boundary=admin_boundary,
        )


def test_pr_r_blocker_prr_verdict_001_closed_keys(monkeypatch):
    from . import proofgate_bootstrap_verifier
    from .proofgate_bootstrap_verifier import (
        BOOTSTRAP_CANDIDATE_VERDICT_FIELDS,
        ProofgateAdminControlPlaneBoundary,
    )

    (
        _tmp,
        repo,
        original_oid,
        base_oid,
        candidate_oid,
        boundary,
        coordinator_root,
        _coordinator_tmp,
    ) = _setup_pr_r_candidate_history()
    real_verify_binding = proofgate_bootstrap_verifier.verify_bootstrap_candidate_binding
    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "verify_bootstrap_candidate_binding",
        lambda repo_path, binding_path, expected_original_tests_landing=None: real_verify_binding(
            repo_path=repo_path,
            binding_path=binding_path,
            expected_original_tests_landing=original_oid,
        ),
    )
    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "verify_proofgate_admin_authority",
        lambda **_kwargs: {"authority": "github_and_broker_control_planes", "binding_digest": "a" * 64},
    )
    verdict_path = coordinator_root / "bootstrap-candidate-verdict.json"
    _thaw_coordinator_root(coordinator_root)
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert tuple(verdict) == BOOTSTRAP_CANDIDATE_VERDICT_FIELDS
    verdict["authorized"] = True
    verdict_path.write_bytes(
        json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    _sync_pr_b_candidate_artifact_digests(
        proofgate_bootstrap_verifier,
        coordinator_root,
        (*PR_B_CANDIDATE_ARTIFACTS, "selector-repair-review-binding.json"),
    )
    _freeze_coordinator_root(coordinator_root)
    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)candidate verdict.*(field|key)|authorized.*forbidden",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo,
            base_oid,
            candidate_oid,
            landing_kind="PR-B",
            boundary=boundary,
            admin_boundary=ProofgateAdminControlPlaneBoundary(),
        )


def test_pr_r_blocker_prr_admin_004_uses_complete_authoritative_collections(monkeypatch):
    from . import proofgate_bootstrap_verifier
    from .proofgate_bootstrap_verifier import verify_proofgate_admin_identity_binding

    boundary, state, paginated_calls = _install_pr_r_admin_control_plane_fakes(
        monkeypatch, proofgate_bootstrap_verifier
    )
    assert verify_proofgate_admin_identity_binding(boundary)["authority"] == (
        "github_and_broker_control_planes"
    )
    assert paginated_calls == [
        "orgs/Consiliency/installations",
        "repos/Consiliency/agent-harness/rulesets",
    ]

    state["extra_repository"] = True
    with pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)selected repositor|authoritative.*repository|control plane observation unavailable",
    ):
        verify_proofgate_admin_identity_binding(boundary)

    state["extra_repository"] = False
    state["extra_ruleset"] = True
    with pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)ruleset.*ambiguous|control plane observation unavailable",
    ):
        verify_proofgate_admin_identity_binding(boundary)


def test_pr_r_blocker_fable_f003_requires_positive_numeric_environment_and_ruleset_ids(
    monkeypatch,
):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            ProofgateAdminControlPlaneBoundary,
            verify_proofgate_admin_identity_binding,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "FABLE-F003::positive_numeric_admin_identifiers_unimplemented"
        ) from exc

    boundary, state, _ = _install_pr_r_admin_control_plane_fakes(
        monkeypatch, proofgate_bootstrap_verifier
    )
    assert type(boundary) is ProofgateAdminControlPlaneBoundary
    first = verify_proofgate_admin_identity_binding(boundary)
    assert first["environment_id"] == "440001"
    assert first["ruleset_id"] == "550001"

    state["environment_id"] = 440002
    state["ruleset_id"] = 550002
    recreated = verify_proofgate_admin_identity_binding(boundary)
    assert recreated["environment_id"] == "440002"
    assert recreated["ruleset_id"] == "550002"
    assert recreated["binding_digest"] != first["binding_digest"]

    for field, invalid_values in (
        ("environment_id", (None, 0, -1, "not-a-number")),
        ("ruleset_id", (None, 0, -1, "not-a-number")),
    ):
        original_value = state[field]
        for invalid_value in invalid_values:
            state[field] = invalid_value
            with pytest.raises(
                ProofgateBootstrapVerifierError,
                match=r"(?i)environment|ruleset|identifier|id|control plane",
            ):
                verify_proofgate_admin_identity_binding(boundary)
        state[field] = original_value


def test_pr_r_blocker_prr_admin_006_pins_github_cli_identity(monkeypatch):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import (
            GITHUB_CLI_PATH,
            GITHUB_CLI_SHA256,
            ProofgateAdminControlPlaneBoundary,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "PRR-ADMIN-006::github_cli_identity_pin_unimplemented"
        ) from exc

    assert GITHUB_CLI_PATH == "/usr/bin/gh"
    assert GITHUB_CLI_SHA256 == "141507c337e8b202ad398550c3b73d72f5af92e86f71665214538a81efd4c409"
    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "_github_cli_sha256",
        lambda path: GITHUB_CLI_SHA256,
    )
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(proofgate_bootstrap_verifier.subprocess, "run", fake_run)
    assert ProofgateAdminControlPlaneBoundary._gh_api("repos/Consiliency/agent-harness") == {}
    assert calls and all(cmd[:2] == [GITHUB_CLI_PATH, "api"] for cmd in calls)

    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "_github_cli_sha256",
        lambda path: "0" * 64,
    )
    call_count = len(calls)
    with pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)GitHub CLI.*identity|executable.*digest",
    ):
        ProofgateAdminControlPlaneBoundary._gh_api("repos/Consiliency/agent-harness")
    assert len(calls) == call_count


def test_pr_r_blocker_fable_f004_explicit_admin_preflight_invokes_live_preflight(
    monkeypatch, tmp_path
):
    try:
        from . import proofgate_bootstrap_verifier
        from .proofgate_bootstrap_verifier import run_live_admin_binding_preflight
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "FABLE-F004::live_admin_preflight_entrypoint_unimplemented"
        ) from exc
    assert callable(run_live_admin_binding_preflight)

    monkeypatch.delenv("PHASE_LOOP_PROOFGATE_ATTENDED_LIVE", raising=False)
    monkeypatch.delenv("PHASE_LOOP_PROOFGATE_OPERATOR_OPT_IN", raising=False)
    calls = []

    def fake_preflight(_boundary, *, output):
        calls.append(output)
        Path(output).write_text("{}", encoding="utf-8")
        return 0

    monkeypatch.setattr(
        proofgate_bootstrap_verifier,
        "run_live_admin_binding_preflight",
        fake_preflight,
    )
    runner_root = tmp_path / "runner-owned"
    runner_root.mkdir()
    output = runner_root / "admin-preflight.json"
    argv = [
        "admin-preflight",
        "--repo",
        "Consiliency/agent-harness",
        "--ref",
        "refs/heads/proofgate-receipt-head-v1",
        "--environment",
        "proofgate-receipt-head-v1",
        "--output",
        str(output),
    ]
    with _coordinator_run_dir(runner_root):
        assert proofgate_bootstrap_verifier.main(argv) == 0
    assert calls == [str(output)]
    assert output.read_text(encoding="utf-8") == "{}"


def test_pr_r_blocker_fable_f005_bootstrap_candidate_capture_argv_is_bound_to_11_nodeids(monkeypatch, tmp_path):
    run_dir = str(tmp_path.resolve())
    candidate_oid = "a" * 40
    monkeypatch.setenv("PHASE_LOOP_RUN_DIR", run_dir)
    monkeypatch.setenv("PHASE_LOOP_RUN_ID", "coordinator-candidate")
    monkeypatch.setenv("PHASE_LOOP_CANDIDATE_OID", candidate_oid)

    try:
        candidate_args = coordinator_evidence_capture_pytest_args("bootstrap_candidate")
        candidate_argv = coordinator_evidence_capture_argv("bootstrap_candidate")
    except ProofgateBootstrapVerifierError as exc:
        pytest.fail(
            "FABLE-F005::bootstrap_candidate coordinator evidence mode is unavailable: "
            f"{exc}"
        )

    expected_nodeids = tuple(
        nodeid.removeprefix("phase-loop-runtime/")
        for nodeid in PR_B_BOOTSTRAP_CANDIDATE_NODEIDS
    )
    assert len(expected_nodeids) == 11
    assert candidate_args[: len(expected_nodeids)] == expected_nodeids
    assert all(not nodeid.startswith("phase-loop-runtime/") for nodeid in expected_nodeids)
    assert candidate_args[len(expected_nodeids) :] == (
        "-p",
        "tests.proofgate_tdd_guard",
        "-o",
        "junit_family=legacy",
        f"--junitxml={run_dir}/compat-candidate.junit.xml",
        "-q",
    )
    assert candidate_argv == (
        "env",
        f"PHASE_LOOP_RUN_DIR={run_dir}",
        "PHASE_LOOP_RUN_ID=coordinator-candidate",
        f"PHASE_LOOP_CANDIDATE_OID={candidate_oid}",
        "PHASE_LOOP_TDD_EXPECT_PROOFGATE_BOOTSTRAP_CANDIDATE=1",
        f"PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING={run_dir}/bootstrap-candidate-binding.json",
        sys.executable,
        "-m",
        "pytest",
        *candidate_args,
    )
    assert all("$PHASE_LOOP_RUN_DIR" not in arg for arg in candidate_argv)
    assert all("$PHASE_LOOP_RUN_DIR" not in arg for arg in candidate_args)


def test_pr_r_blocker_fable_f006_pr_b_only_requires_candidate_evidence():
    try:
        from .proofgate_bootstrap_verifier import COORDINATOR_EVIDENCE_ARTIFACTS
    except ImportError as exc:
        raise ProofgateMissingCapabilityError(
            "FABLE-F006::coordinator_evidence_inventory_unimplemented"
        ) from exc

    assert tuple(mode for _junit, _reports, mode in COORDINATOR_EVIDENCE_ARTIFACTS) == (
        "default",
        "forced_red",
        "ordinary_hermetic",
        "attended_live",
    )

    _tmp, repo, base_oid = _setup_git_repo()
    subprocess.run(
        ["git", "checkout", "-b", "proofgate-pr-b"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    for rel_path in PR_B_5_PATHS:
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# candidate {rel_path}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "PR-B candidate without candidate evidence"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    candidate_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    change_digest = hashlib.sha256(
        subprocess.run(
            ["git", "diff-tree", "--raw", "-r", "-z", base_oid, candidate_oid],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    ).hexdigest()
    seats, chronology = _valid_seats(change_digest)
    _observation, boundary, coordinator_root, _coordinator_tmp = _observed_bootstrap_boundary(
        repo,
        base_oid,
        candidate_oid,
        _valid_pr_metadata(candidate_oid, base_oid, "PR-B"),
        seats,
        chronology,
        "PR-B",
    )
    assert not any(
        (coordinator_root / filename).exists()
        for filename in (
            "bootstrap-candidate-binding.json",
            "bootstrap-candidate-verdict.json",
            "phase_reports_candidate.json",
        )
    )
    with _coordinator_run_dir(coordinator_root), pytest.raises(
        ProofgateBootstrapVerifierError,
        match=r"(?i)bootstrap.*candidate|candidate.*(binding|verdict|report)|candidate artifact",
    ):
        verify_observed_premerge_bootstrap_review_gate(
            repo,
            base_oid,
            candidate_oid,
            landing_kind="PR-B",
            boundary=boundary,
        )


def test_pr_r_blocker_fable_f007_producer_output_satisfies_decisive_pr_b_verifier_contract(monkeypatch):
    try:
        from .proofgate_tdd_guard import ProofgateReportingPlugin, EXPECTED_PHASE_NODEIDS
        from .proofgate_bootstrap_verifier import (
            verify_coordinator_evidence_capture,
            coordinator_evidence_capture_pytest_args,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "FABLE-F007::producer_verifier_contract_unimplemented"
        ) from exc

    (
        _tmp,
        repo,
        original_oid,
        base_oid,
        _synth_candidate_oid,
        boundary,
        _old_coordinator_root,
        _coordinator_tmp,
    ) = _setup_pr_r_candidate_history()

    candidate_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    coordinator_root = repo.parent / "coordinator_evidence"
    if coordinator_root.exists():
        shutil.rmtree(coordinator_root)
    coordinator_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PHASE_LOOP_RUN_DIR", str(coordinator_root))
    monkeypatch.setenv("PHASE_LOOP_RUN_ID", "coordinator-candidate")
    monkeypatch.setenv("PHASE_LOOP_CANDIDATE_OID", candidate_oid)

    class DummyItem:
        def __init__(self, nodeid):
            self.nodeid = nodeid
            self.user_properties = []

    class DummyCall:
        def __init__(self, when="call"):
            self.when = when
            self.outcome = "passed"
            self.skipped = False
            self.failed = False

    class DummyReport:
        def __init__(self, nodeid, outcome="passed"):
            self.nodeid = nodeid
            self.when = "call"
            self.outcome = outcome

    class DummyOutcome:
        def __init__(self, result):
            self._result = result

        def get_result(self):
            return self._result

    def _invoke_makereport(plugin, nodeid, outcome="passed"):
        item = DummyItem(nodeid)
        call = DummyCall(when="call")
        rep = DummyReport(nodeid, outcome=outcome)

        def wrapper():
            yield rep

        gen = plugin.pytest_runtest_makereport(item, call)
        next(gen)
        try:
            gen.send(DummyOutcome(rep))
        except StopIteration:
            pass

    # 1. Candidate evidence generated via ProofgateReportingPlugin producer
    cand_args = coordinator_evidence_capture_pytest_args(
        "bootstrap_candidate",
        nodeids=PR_B_BOOTSTRAP_CANDIDATE_NODEIDS,
    )
    cand_argv = ["pytest", *cand_args]
    cand_junit_xml, _ = _candidate_phase_reports_and_junit()
    (coordinator_root / "compat-candidate.junit.xml").write_text(cand_junit_xml, encoding="utf-8")

    plugin_cand = ProofgateReportingPlugin()
    for nodeid in PR_B_BOOTSTRAP_CANDIDATE_NODEIDS:
        _invoke_makereport(plugin_cand, nodeid, "passed")

    old_argv = sys.argv
    sys.argv = list(cand_argv)
    try:
        plugin_cand.pytest_sessionfinish(None, 0)
    finally:
        sys.argv = old_argv

    # 2. Compat-default evidence generated via ProofgateReportingPlugin producer
    def_args = coordinator_evidence_capture_pytest_args(
        "default",
        evidence_by_mode={"default": ("compat-default.junit.xml", "phase_reports_default.json")},
    )
    def_argv = ["pytest", *def_args]
    def_junit_xml, _, _ = _phase_reports_and_junit("default")
    (coordinator_root / "compat-default.junit.xml").write_text(def_junit_xml, encoding="utf-8")

    plugin_def = ProofgateReportingPlugin()
    for nodeid in EXPECTED_PHASE_NODEIDS:
        _invoke_makereport(plugin_def, nodeid, "passed")

    old_argv = sys.argv
    sys.argv = list(def_argv)
    try:
        plugin_def.pytest_sessionfinish(None, 0)
    finally:
        sys.argv = old_argv

    # 3. Compat-forced-red evidence generated via ProofgateReportingPlugin producer
    red_args = coordinator_evidence_capture_pytest_args(
        "forced_red",
        evidence_by_mode={"forced_red": ("compat-forced-red.junit.xml", "phase_reports_forced_red.json")},
    )
    red_argv = ["pytest", *red_args]
    red_junit_xml, _, _ = _phase_reports_and_junit("forced_red")
    (coordinator_root / "compat-forced-red.junit.xml").write_text(red_junit_xml, encoding="utf-8")

    plugin_red = ProofgateReportingPlugin()
    for nodeid in EXPECTED_PHASE_NODEIDS:
        _invoke_makereport(plugin_red, nodeid, "failed" if nodeid == EXPECTED_PHASE_NODEIDS[0] else "skipped")

    old_argv = sys.argv
    sys.argv = list(red_argv)
    try:
        plugin_red.pytest_sessionfinish(None, 1)
    finally:
        sys.argv = old_argv

    # Verify that the real producer output satisfies the decisive verifier contract
    with _coordinator_run_dir(coordinator_root):
        captured_cand = verify_coordinator_evidence_capture(
            coordinator_root,
            "bootstrap_candidate",
            expected_candidate_oid=candidate_oid,
            evidence_by_mode={"bootstrap_candidate": ("compat-candidate.junit.xml", "phase_reports_candidate.json")},
            nodeids=PR_B_BOOTSTRAP_CANDIDATE_NODEIDS,
        )
        assert captured_cand["mode"] == "bootstrap_candidate"

        captured_def = verify_coordinator_evidence_capture(
            coordinator_root,
            "default",
            evidence_by_mode={"default": ("compat-default.junit.xml", "phase_reports_default.json")},
        )
        assert captured_def["mode"] == "default"

        captured_red = verify_coordinator_evidence_capture(
            coordinator_root,
            "forced_red",
            evidence_by_mode={"forced_red": ("compat-forced-red.junit.xml", "phase_reports_forced_red.json")},
        )
        assert captured_red["mode"] == "forced_red"


def _setup_real_repo_candidate_history():
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name) / "repo"
    source_repo = Path(__file__).resolve().parents[2]

    shutil.copytree(
        source_repo,
        repo,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc", ".pytest_cache", ".tox", ".mypy_cache"),
    )
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    gitignore_path = repo / ".gitignore"
    existing_ignore = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    needed_ignores = ["__pycache__/", "*.py[cod]", ".pytest_cache/", ".venv/"]
    missing_ignores = [pat for pat in needed_ignores if pat not in existing_ignore]
    if missing_ignores:
        new_content = (existing_ignore.rstrip() + "\n\n# Runtime cache artifacts\n" + "\n".join(missing_ignores) + "\n").lstrip()
        gitignore_path.write_text(new_content, encoding="utf-8")

    subprocess.run(
        ["git", "add", "."],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    subprocess.run(
        ["git", "checkout", "-b", "selector-repair-base"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    pr_r_files = (
        "phase-loop-runtime/tests/test_tdd_chronology.py",
        "phase-loop-runtime/tests/proofgate_tdd_guard.py",
        "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
    )
    for rel_p in pr_r_files:
        p = repo / rel_p
        p.write_bytes(p.read_bytes() + b"\n# SENTINEL_ORIGINAL_BASE\n")

    subprocess.run(
        ["git", "add", *pr_r_files],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Synthetic original base"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    original_tests_landing_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    subprocess.run(
        ["git", "checkout", "-b", "selector-repair-red"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    chron_src = Path(__file__)
    (repo / "phase-loop-runtime/tests/test_tdd_chronology.py").write_bytes(chron_src.read_bytes())
    subprocess.run(
        ["git", "add", "phase-loop-runtime/tests/test_tdd_chronology.py"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Selector repair RED"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    subprocess.run(
        ["git", "checkout", "-b", "selector-repair-green"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    guard_src = chron_src.parent / "proofgate_tdd_guard.py"
    verifier_src = chron_src.parent / "proofgate_bootstrap_verifier.py"

    guard_content = guard_src.read_text(encoding="utf-8")
    new_guard_content, count = re.subn(
        r'ORIGINAL_TESTS_LANDING_OID = "[0-9a-fA-F]{40}"',
        f'ORIGINAL_TESTS_LANDING_OID = "{original_tests_landing_oid}"',
        guard_content,
    )
    if count != 1:
        raise ValueError(f"Expected exactly 1 replacement for ORIGINAL_TESTS_LANDING_OID assignment, got {count}")

    (repo / "phase-loop-runtime/tests/proofgate_tdd_guard.py").write_text(new_guard_content, encoding="utf-8")
    (repo / "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py").write_bytes(verifier_src.read_bytes())

    subprocess.run(
        [
            "git",
            "add",
            "phase-loop-runtime/tests/proofgate_tdd_guard.py",
            "phase-loop-runtime/tests/proofgate_bootstrap_verifier.py",
        ],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Selector repair GREEN"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    subprocess.run(
        ["git", "checkout", "selector-repair-base"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "merge", "--no-ff", "selector-repair-green", "-m", "Merge selector repair"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    selector_landing_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    subprocess.run(
        ["git", "checkout", "-b", "proofgate-pr-b"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    for rel_path in PR_B_5_PATHS:
        src = source_repo / rel_path
        dst = repo / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        base_content = src.read_bytes() if src.exists() else b""
        dst.write_bytes(base_content + f"# candidate {rel_path}\n".encode("utf-8"))

    subprocess.run(
        ["git", "add", *PR_B_5_PATHS],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "PR-B candidate"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    candidate_oid = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    pr_metadata = _valid_pr_metadata(candidate_oid, selector_landing_oid, "PR-B")
    digest = hashlib.sha256(
        subprocess.run(
            ["git", "diff-tree", "--raw", "-r", "-z", selector_landing_oid, candidate_oid],
            cwd=repo,
            capture_output=True,
            check=True,
        ).stdout
    ).hexdigest()
    seats, chronology = _valid_seats(digest)
    _obs, boundary, coordinator_root, coordinator_tmp = _pr_b_observed_bootstrap_boundary(
        repo,
        selector_landing_oid,
        candidate_oid,
        pr_metadata,
        seats,
        chronology,
        original_tests_landing_oid=original_tests_landing_oid,
    )

    _thaw_coordinator_root(coordinator_root)

    for name in ("phase_reports_candidate.json", "phase_reports_candidate.jsonl"):
        path = coordinator_root / name
        if path.exists():
            path.unlink()

    return (
        tmp,
        repo,
        original_tests_landing_oid,
        selector_landing_oid,
        candidate_oid,
        boundary,
        coordinator_root,
        coordinator_tmp,
    )


def test_pr_r_blocker_fable_f008_real_producer_subprocess_execution_satisfies_verifier_contract(monkeypatch):
    try:
        from .proofgate_bootstrap_verifier import (
            coordinator_evidence_capture_argv,
        )
    except (ImportError, AttributeError) as exc:
        raise ProofgateMissingCapabilityError(
            "FABLE-F008::producer_subprocess_contract_unimplemented"
        ) from exc

    (
        tmp,
        repo,
        _original_oid,
        _selector_landing_oid,
        candidate_oid,
        _boundary,
        coordinator_root,
        coordinator_tmp,
    ) = _setup_real_repo_candidate_history()

    monkeypatch.setenv("PHASE_LOOP_RUN_DIR", str(coordinator_root))
    monkeypatch.setenv("PHASE_LOOP_RUN_ID", "coordinator-candidate")
    monkeypatch.setenv("PHASE_LOOP_CANDIDATE_OID", candidate_oid)

    # Subprocess-level execution of canonical shell-free producer command
    cand_argv = coordinator_evidence_capture_argv("bootstrap_candidate")
    env = dict(os.environ)
    env["PHASE_LOOP_RUN_DIR"] = str(coordinator_root)
    env["PHASE_LOOP_RUN_ID"] = "coordinator-candidate"
    env["PHASE_LOOP_CANDIDATE_OID"] = candidate_oid

    repo_pkg = repo / "phase-loop-runtime"

    proc = subprocess.run(
        list(cand_argv),
        cwd=repo_pkg,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    combined_out = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 1, (
        f"Producer subprocess expected returncode 1 (governed RED tests), got {proc.returncode}:\n"
        f"{combined_out}"
    )

    forbidden_errors = (
        "PHASE_LOOP_TDD_PROOFGATE_BOOTSTRAP_BINDING must",
        "original_tests_landing_oid mismatch",
        "Candidate mode changes count mismatch",
        "No module named",
    )
    for forbidden in forbidden_errors:
        assert forbidden not in combined_out, f"Found setup/path error in output: {forbidden}\n{combined_out}"

    cand_junit = coordinator_root / "compat-candidate.junit.xml"
    cand_reports = coordinator_root / "phase_reports_candidate.json"

    assert cand_junit.is_file(), f"Missing junit artifact: {cand_junit}"
    assert cand_reports.is_file(), f"Missing phase reports artifact: {cand_reports}"

    payload = json.loads(cand_reports.read_text(encoding="utf-8"))
    assert payload.get("schema") == "proofgate_phase_reports.v1"
    assert payload.get("exitstatus") == 1
    assert payload.get("capture", {}).get("run_identity") == "coordinator-candidate"
    assert payload.get("capture", {}).get("mode") == "bootstrap_candidate"

    rep_nodeids = tuple(
        r["nodeid"] for r in payload.get("reports", []) if isinstance(r, dict) and "nodeid" in r
    )
    assert rep_nodeids == PR_B_BOOTSTRAP_CANDIDATE_NODEIDS
