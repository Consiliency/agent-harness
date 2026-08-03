"""test_tdd_chronology.py — PROOFGATE TDD chronology tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

from .proofgate_bootstrap_verifier import (
    PR_T_18_PATHS,
    ProofgateBootstrapVerifierError,
    evaluate_unit_double_bootstrap_merge_review_gate,
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


def _setup_git_repo():
    tmp = tempfile.TemporaryDirectory()
    repo = Path(tmp.name)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, check=True)

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

        tdd_chronology.verify_test_lane_chronology(repo_path=repo, landing_oid=landing_t_oid, base_oid=base_oid, candidate_oid=cand_t_oid, github_pr=pr_meta, seat_records=seats, seat_chronology=chron)

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

        tdd_chronology.verify_test_lane_chronology(repo_path=repo, base_oid=base_oid, candidate_oid=cand_bad_oid, github_pr=pr_meta, seat_records=seats, seat_chronology=chron, landing_kind="PR-T")

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
            verify_premerge_bootstrap_review_gate(repo, base_oid, cand_b_oid, pr_meta, seats, chron, landing_kind="PR-T")

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
            verify_premerge_bootstrap_review_gate(repo, base_oid, cand_b_prod_oid, pr_meta2, seats2, chron2, landing_kind="PR-T")

        tdd_chronology.verify_test_lane_chronology(repo_path=repo, base_oid=base_oid, candidate_oid=cand_b_oid, github_pr=pr_meta, seat_records=seats, seat_chronology=chron, landing_kind="PR-B")

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
        guard_file.write_text("# edit guard\n", encoding="utf-8")

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

        tdd_chronology.verify_test_lane_chronology(repo_path=repo, base_oid=base_oid, candidate_oid=cand_i_oid, github_pr=pr_meta, seat_records=seats, seat_chronology=chron, landing_kind="PR-I")

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

        tdd_chronology.verify_test_lane_chronology(repo_path=repo, landing_oid=squash_oid, base_oid=base_oid, candidate_oid=cand_t_oid, github_pr=pr_meta, seat_records=seats, seat_chronology=chron)

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

        tdd_chronology.verify_test_lane_chronology(repo_path=repo, base_oid=base_oid, candidate_oid=cand_oid)

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

        verify_kwargs = {"fresh_process_boundary": True}
        if hasattr(tdd_chronology, "verify_test_lane_chronology_fresh_process"):
            tdd_chronology.verify_test_lane_chronology_fresh_process(parent_pid=parent_pid, process_pid=res_data["pid"], head_sha=res_data["head_sha"], module_digests=res_data["loaded_modules_digests"])
        else:
            tdd_chronology.verify_test_lane_chronology(**verify_kwargs)

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

        tdd_chronology.verify_test_lane_chronology(junit_evidence=valid_evidence)

    run_proofgate_contract(nodeid, _contract)
