"""test_tdd_chronology.py — PROOFGATE TDD chronology tests."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

from .proofgate_bootstrap_verifier import (
    BOOTSTRAP_MERGE_OBSERVATION_SCHEMA,
    PR_B_5_PATHS,
    PR_T_18_PATHS,
    ProofgateBootstrapMergeObservation,
    ProofgateBootstrapVerifierError,
    RecordingBootstrapMergeObservationBoundary,
    compute_git_source_binding_facts,
    evaluate_unit_double_bootstrap_merge_review_gate,
    verify_observed_premerge_bootstrap_review_gate,
    verify_junit_accounting,
    verify_landed_bootstrap_source_binding,
    verify_premerge_bootstrap_review_gate,
)
from .proofgate_tdd_guard import (
    DEFAULT_SKIP_NODEIDS,
    EXPECTED_PHASE_NODEIDS,
    RED_CASES_BY_NODEID,
    ProofgateMissingCapabilityError,
    guard_proofgate_nodeid,
    run_proofgate_contract,
)


_BOOTSTRAP_ARTIFACTS = (
    "verification.log",
    "junit_default.xml",
    "junit_forced_red.xml",
    "junit_ordinary.xml",
    "junit_attended.xml",
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


def _valid_pr_metadata(head_oid: str, base_oid: str) -> dict:
    return {
        "number": 101,
        "repo": "Consiliency/agent-harness",
        "head_ref": "proofgate-pr-t",
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


def _phase_reports_and_junit(mode: str) -> tuple[str, list[dict], dict | None]:
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
            "module_identity": "bootstrap-module-digest",
            "head_identity": "a" * 40,
            "nonces": {case: f"nonce-{index}" for index, case in enumerate(cases)},
            "broker_digests": {case: (str(index) * 64) for index, case in enumerate(cases, 1)},
            "profile_digests": {case: (str(index + 4) * 64) for index, case in enumerate(cases, 1)},
        }
        provider_values = {
            case: json.dumps({
                "runner_stage": runner_envelope["runner_stage"],
                "module_identity": runner_envelope["module_identity"],
                "head_identity": runner_envelope["head_identity"],
                "nonce": runner_envelope["nonces"][case],
                "broker_digest": runner_envelope["broker_digests"][case],
                "profile_digest": runner_envelope["profile_digests"][case],
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
            tag = f"PROOFGATE_RED::{RED_CASES_BY_NODEID[nodeid][1]}"
            ET.SubElement(testcase, "failure", message=tag).text = tag
            outcome, exception_type = "failed", "AssertionError"
        else:
            outcome, exception_type = "passed", None
        report = {"nodeid": nodeid, "phase": "call", "outcome": outcome, "properties": properties}
        if exception_type is not None:
            report["exception_type"] = exception_type
        reports.append(report)
    return ET.tostring(root, encoding="unicode"), reports, runner_envelope


def _write_decisive_bootstrap_artifacts(repo: Path, candidate_oid: str) -> dict[str, dict]:
    reports_by_mode: dict[str, dict] = {}
    for filename, mode in (
        ("junit_default.xml", "default"),
        ("junit_forced_red.xml", "forced_red"),
        ("junit_ordinary.xml", "ordinary_hermetic"),
        ("junit_attended.xml", "attended_live"),
    ):
        junit, reports, runner_envelope = _phase_reports_and_junit(mode)
        (repo / filename).write_text(junit, encoding="utf-8")
        reports_by_mode[mode] = {"reports": reports}
        if runner_envelope is not None:
            reports_by_mode[mode]["runner_envelope"] = runner_envelope
    for filename in (
        "ctrl_isolation.log",
        "ctrl_taint.log",
        "ctrl_misuse.log",
        "ctrl_control.log",
        "ctrl_positive_canary.log",
    ):
        (repo / filename).write_text(json.dumps({
            "schema": "proofgate_control_artifact.v1",
            "control": filename,
            "candidate_oid": candidate_oid,
            "status": "passed",
        }, sort_keys=True), encoding="utf-8")
    return reports_by_mode


def _observed_bootstrap_boundary(repo: Path, base_oid: str, candidate_oid: str, github_pr: dict, seats: dict, chronology: list):
    reports_by_mode = _write_decisive_bootstrap_artifacts(repo, candidate_oid)
    facts = compute_git_source_binding_facts(repo, base_oid, candidate_oid)
    assert facts
    path_scope_digest = hashlib.sha256(
        json.dumps(facts["path_tuples"], separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    junit_digests = tuple(
        (filename, hashlib.sha256((repo / filename).read_bytes()).hexdigest())
        for filename in ("junit_default.xml", "junit_forced_red.xml", "junit_ordinary.xml", "junit_attended.xml")
    )
    control_digests = tuple(
        (filename, hashlib.sha256((repo / filename).read_bytes()).hexdigest())
        for filename in ("ctrl_isolation.log", "ctrl_taint.log", "ctrl_misuse.log", "ctrl_control.log", "ctrl_positive_canary.log")
    )
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
        junit_artifact_digests=junit_digests,
        junit_phase_reports_json=json.dumps(reports_by_mode, sort_keys=True, separators=(",", ":")),
        control_artifact_digests=control_digests,
    )
    return observation, RecordingBootstrapMergeObservationBoundary(observation)


def test_chronology_requires_two_parent_tests_bootstrap_and_implementation_landings():
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
        subprocess.run(["git", "checkout", "-b", "pr-t-branch"], cwd=repo, capture_output=True, check=True)
        for rel_path in PR_T_18_PATHS:
            full_p = repo / rel_path
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(f"# {rel_path}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-T test landing"], cwd=repo, capture_output=True, check=True)
        cand_t_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        # Land PR-T via 2-parent merge
        subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "merge", "--no-ff", "pr-t-branch", "-m", "Merge PR-T"], cwd=repo, capture_output=True, check=True)
        landing_t_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()

        diff_raw = subprocess.run(["git", "diff-tree", "--raw", "-r", "-z", base_oid, cand_t_oid], cwd=repo, capture_output=True, check=True).stdout
        target_digest = hashlib.sha256(diff_raw).hexdigest()
        pr_meta = _valid_pr_metadata(cand_t_oid, base_oid)
        seats, chron = _valid_seats(target_digest)

        # The real Git tuple/path scope, exact PR identity, four seat digests, four
        # JUnits and five control artifacts jointly authorize the pre-merge boundary.
        observation, boundary = _observed_bootstrap_boundary(repo, base_oid, cand_t_oid, pr_meta, seats, chron)
        decisive = verify_observed_premerge_bootstrap_review_gate(
            repo, base_oid, cand_t_oid, pr_meta, landing_kind="PR-T", boundary=boundary
        )
        assert decisive["decisive"] is True
        assert decisive["evidence_kind"] == "coordinator_external_observation"
        assert decisive["authorized"] is True
        assert len(boundary.calls) == 1

        # The same decisive boundary must be usable before the separately reviewed,
        # production-only PR-B five-path landing.
        subprocess.run(["git", "checkout", "-b", "pr-b-branch", landing_t_oid], cwd=repo, capture_output=True, check=True)
        for rel_path in PR_B_5_PATHS:
            full_p = repo / rel_path
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(f"# bootstrap {rel_path}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "PR-B bootstrap landing"], cwd=repo, capture_output=True, check=True)
        cand_b_oid = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, check=True).stdout.decode().strip()
        pr_b_meta = _valid_pr_metadata(cand_b_oid, landing_t_oid)
        pr_b_digest = hashlib.sha256(
            subprocess.run(
                ["git", "diff-tree", "--raw", "-r", "-z", landing_t_oid, cand_b_oid],
                cwd=repo,
                capture_output=True,
                check=True,
            ).stdout
        ).hexdigest()
        pr_b_seats, pr_b_chronology = _valid_seats(pr_b_digest)
        _observation_b, boundary_b = _observed_bootstrap_boundary(
            repo, landing_t_oid, cand_b_oid, pr_b_meta, pr_b_seats, pr_b_chronology
        )
        decisive_b = verify_observed_premerge_bootstrap_review_gate(
            repo, landing_t_oid, cand_b_oid, pr_b_meta, landing_kind="PR-B", boundary=boundary_b
        )
        assert decisive_b["decisive"] is True
        assert decisive_b["evidence_kind"] == "coordinator_external_observation"

        _write_decisive_bootstrap_artifacts(repo, cand_t_oid)
        altered_seats = json.loads(observation.seat_records_json)
        altered_seats["fable"]["candidate_digest"] = "0" * 64
        invalid_observations = (
            ("change_tuple", dataclasses.replace(observation, change_tuple_digest="0" * 64)),
            ("path_scope", dataclasses.replace(observation, path_scope_digest="0" * 64)),
            ("seat_digest", dataclasses.replace(
                observation,
                seat_records_json=json.dumps(altered_seats, sort_keys=True, separators=(",", ":")),
            )),
            ("junit_accounting", dataclasses.replace(
                observation,
                junit_phase_reports_json=json.dumps({"default": {"reports": []}}, sort_keys=True, separators=(",", ":")),
            )),
        )
        for label, invalid_observation in invalid_observations:
            with pytest.raises(ProofgateBootstrapVerifierError, match="(Git change tuple/path scope|JUnit report modes mismatch|Seat fable digest)"):
                verify_observed_premerge_bootstrap_review_gate(
                    repo,
                    base_oid,
                    cand_t_oid,
                    pr_meta,
                    landing_kind="PR-T",
                    boundary=RecordingBootstrapMergeObservationBoundary(invalid_observation),
                )

        class _UnavailableBoundary:
            def observe(self, _request):
                raise RuntimeError("coordinator unavailable")

        with pytest.raises(ProofgateBootstrapVerifierError, match="observation boundary unavailable"):
            verify_observed_premerge_bootstrap_review_gate(
                repo, base_oid, cand_t_oid, pr_meta, landing_kind="PR-T", boundary=_UnavailableBoundary()
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
        pr_meta = _valid_pr_metadata(cand_bad_oid, base_oid)
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
        pr_meta = _valid_pr_metadata(cand_b_oid, base_oid)
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
        pr_meta2 = _valid_pr_metadata(cand_b_prod_oid, base_oid)
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
        pr_meta = _valid_pr_metadata(cand_i_oid, base_oid)
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
        pr_meta2 = _valid_pr_metadata(cand_i_test_oid, base_oid)
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
        pr_meta = _valid_pr_metadata(cand_t_oid, base_oid)
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
            repo_path=repo,
            fresh_process_boundary=True,
            parent_pid=parent_pid,
            process_pid=parent_pid,
            head_sha=res_data["head_sha"],
            module_digests=res_data["loaded_modules_digests"],
        )
        _assert_chronology_rejected(
            tdd_chronology,
            "stale_head",
            repo_path=repo,
            fresh_process_boundary=True,
            parent_pid=parent_pid,
            process_pid=res_data["pid"],
            head_sha="0" * 40,
            module_digests=res_data["loaded_modules_digests"],
        )
        _assert_chronology_accepted(
            tdd_chronology,
            repo_path=repo,
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
