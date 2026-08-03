"""test_validate_plan_doc_proofgate.py — PROOFGATE plan validator contract tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import pytest

from .proofgate_tdd_guard import (
    ProofgateMissingCapabilityError,
    emit_mutation_observable,
    guard_proofgate_nodeid,
    run_proofgate_contract,
)



def _get_validator_script() -> Path:
    script = Path.cwd() / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    if not script.exists():
        script = Path(__file__).resolve().parents[2] / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    return script


PROOFGATE_GRANDFATHER_TIMESTAMP = "2026-07-29T22:09:58Z"

OBJECT_358_SPEC = "0196f19c7e9fd90e9a707de076271057b521e1d1:plans/detailed-board-silent-degradation-358-20260728.md"
OBJECT_288_SPEC = "4e7dbf419b85ffc5e57b43d424a680b1e92e9461:plans/detailed-288-fab-broker-readmission-20260726.md"
CUTOFF_COMMIT_OID = "5328694ae31b4f13f091903d96ed89395d74f3b2"
SUCCESSOR_COMMIT_OID = "a3fbb196b3b57d75e403bcea3bad972e9491f675"


def _load_git_object_bytes(spec: str) -> str:
    proc = subprocess.run(["git", "cat-file", "-p", spec], capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"Failed to read pinned git object {spec}: {proc.stderr}")
    return proc.stdout


class ProofgatePlanValidatorTest(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _inject_record_property(self, record_property):
        self.record_property = record_property

    def test_agent_harness_358_original_is_rejected(self):
        nodeid = "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            from phase_loop_runtime import goal_coverage

            if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
                raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

            bytes_358 = _load_git_object_bytes(OBJECT_358_SPEC)
            validator_script = _get_validator_script()

            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
                tf.write(bytes_358)
                tf_path = tf.name

            proc = subprocess.run([sys.executable, str(validator_script), tf_path], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0, "validate_plan_doc.py CLI must exit non-zero on #358 pinned bytes")
            combined_output = proc.stdout + proc.stderr
            self.assertIn("vacuous_falsifier", combined_output)
            self.assertNotIn("WARN", combined_output)

            contracts = goal_coverage.extract_acceptance_contracts(bytes_358)
            check_res = goal_coverage.check_acceptance_falsifiers(contracts)
            cond = isinstance(check_res, dict) and not check_res.get("valid", True)
            if not cond:
                emit_mutation_observable("ec-proofgate-3.vacuous-falsifier", getattr(self, "record_property", None))
            self.assertFalse(check_res.get("valid", True))

        run_proofgate_contract(nodeid, _contract)

    def test_agent_harness_288_ac1_and_ac4_are_rejected(self):
        nodeid = "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_288_ac1_and_ac4_are_rejected"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            import hashlib
            from phase_loop_runtime import goal_coverage

            if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
                raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

            bytes_288 = _load_git_object_bytes(OBJECT_288_SPEC)
            proc_rev = subprocess.run(["git", "rev-parse", OBJECT_288_SPEC], capture_output=True, text=True, check=True)
            git_blob_sha = proc_rev.stdout.strip()
            self.assertEqual(git_blob_sha, "d1be22ceadd78ba87ac800d1ed0872a8e63698fb", "#288 git blob SHA mismatch")

            file_sha256 = hashlib.sha256(bytes_288.encode("utf-8")).hexdigest()
            self.assertEqual(file_sha256, "77dc3eb21bd0390a13fca2a3ac54258145092a7f98ec246c9ae160a4889351ec", "#288 whole-file SHA-256 mismatch")

            # Extract contracts and verify AC-1 and AC-4 slices specifically
            contracts = goal_coverage.extract_acceptance_contracts(bytes_288)
            ac1_contracts = [c for c in contracts if c.get("id") == "AC-1"]
            ac4_contracts = [c for c in contracts if c.get("id") == "AC-4"]

            self.assertTrue(len(ac1_contracts) > 0, "AC-1 contract missing in #288")
            self.assertTrue(len(ac4_contracts) > 0, "AC-4 contract missing in #288")

            # Verify pinned AC-1 and AC-4 slice SHA-256 hashes
            ac1_slice_raw = ac1_contracts[0].get("raw_item", ac1_contracts[0].get("raw", ""))
            ac1_slice_sha256 = hashlib.sha256(ac1_slice_raw.encode("utf-8")).hexdigest() if isinstance(ac1_slice_raw, str) else ac1_contracts[0].get("sha256", "")
            self.assertEqual(
                ac1_slice_sha256,
                "5bb80a50e6f7942d62bc58839bc6b66efa5b66439b899b9b90ddbbc4fe662329",
                "AC-1 slice SHA-256 mismatch",
            )

            ac4_slice_raw = ac4_contracts[0].get("raw_item", ac4_contracts[0].get("raw", ""))
            ac4_slice_sha256 = hashlib.sha256(ac4_slice_raw.encode("utf-8")).hexdigest() if isinstance(ac4_slice_raw, str) else ac4_contracts[0].get("sha256", "")
            self.assertEqual(
                ac4_slice_sha256,
                "9239214f44821e38eae26820b8d5304d04bf5753a3cb3d6ff7d61eb1e50574d0",
                "AC-4 slice SHA-256 mismatch",
            )

            # Check individual typed slice rejections with reason="vacuous_falsifier"
            check_ac1 = goal_coverage.check_acceptance_falsifiers(ac1_contracts)
            self.assertFalse(check_ac1.get("valid", True), "AC-1 slice must fail acceptance contract validation")
            self.assertEqual(check_ac1.get("reason"), "vacuous_falsifier", "AC-1 slice rejection reason must be vacuous_falsifier")

            check_ac4 = goal_coverage.check_acceptance_falsifiers(ac4_contracts)
            self.assertFalse(check_ac4.get("valid", True), "AC-4 slice must fail acceptance contract validation")
            self.assertEqual(check_ac4.get("reason"), "vacuous_falsifier", "AC-4 slice rejection reason must be vacuous_falsifier")

            validator_script = _get_validator_script()
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
                tf.write(bytes_288)
                tf_path = tf.name

            proc = subprocess.run([sys.executable, str(validator_script), tf_path], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0, "validate_plan_doc.py CLI must exit non-zero on #288 pinned bytes")
            combined_output = proc.stdout + proc.stderr
            self.assertNotIn("WARN", combined_output)

            check_res = goal_coverage.check_acceptance_falsifiers(contracts)
            self.assertFalse(check_res.get("valid", True))

        run_proofgate_contract(nodeid, _contract)

    def test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns(self):
        nodeid = "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            from phase_loop_runtime import goal_coverage

            if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
                raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

            # Explicitly exercise extract_plan_goal_refs for EC-7 reachability
            if hasattr(goal_coverage, "extract_plan_goal_refs"):
                refs = goal_coverage.extract_plan_goal_refs(Path(__file__))
                if not isinstance(refs, set) or len(refs) == 0:
                    emit_mutation_observable("ec-proofgate-7.grandfathering", getattr(self, "record_property", None))
                self.assertTrue(isinstance(refs, set) and len(refs) > 0, "extract_plan_goal_refs must return a non-empty set of refs")

            bytes_358 = _load_git_object_bytes(OBJECT_358_SPEC)
            contracts = goal_coverage.extract_acceptance_contracts(bytes_358)
            check_res = goal_coverage.check_acceptance_falsifiers(
                contracts,
                cutoff_commit_oid=CUTOFF_COMMIT_OID,
                successor_commit_oid=SUCCESSOR_COMMIT_OID,
                grandfather_timestamp=PROOFGATE_GRANDFATHER_TIMESTAMP,
            )
            cond = (
                isinstance(check_res, dict)
                and check_res.get("valid", False) is True
                and ("grandfathered" in check_res.get("warnings", []) or check_res.get("disposition") == "grandfathered")
            )
            if not cond:
                emit_mutation_observable("ec-proofgate-7.grandfathering", getattr(self, "record_property", None))
            self.assertTrue(check_res.get("valid", False))

        run_proofgate_contract(nodeid, _contract)

    def test_changed_or_new_criterion_requires_v3_evidence(self):
        nodeid = "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            from phase_loop_runtime import goal_coverage

            if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
                raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

            bytes_358 = _load_git_object_bytes(OBJECT_358_SPEC)
            new_plan = bytes_358.replace("Acceptance Criteria", "Acceptance Criteria\n- [ ] EC-NEW-1 — proven by t")
            contracts = goal_coverage.extract_acceptance_contracts(new_plan)
            check_res = goal_coverage.check_acceptance_falsifiers(
                contracts,
                cutoff_commit_oid=CUTOFF_COMMIT_OID,
                successor_commit_oid=SUCCESSOR_COMMIT_OID,
                grandfather_timestamp=PROOFGATE_GRANDFATHER_TIMESTAMP,
            )
            self.assertFalse(check_res.get("valid", True), "Changed or new criterion must hard-fail grandfathering check")

        run_proofgate_contract(nodeid, _contract)


if __name__ == "__main__":
    unittest.main()
