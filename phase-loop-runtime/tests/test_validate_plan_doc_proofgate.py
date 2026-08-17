"""test_validate_plan_doc_proofgate.py — PROOFGATE plan validator contract tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import hashlib
from pathlib import Path
import pytest

from .proofgate_content_tdd_adapter import (
    ProofgateMissingCapabilityError,
    PROOFGATE_GRANDFATHER_CUTOFF_OID,
    PROOFGATE_GRANDFATHER_PLAN_PATH,
    PROOFGATE_GRANDFATHER_RAW_ITEM,
    PROOFGATE_GRANDFATHER_SERVER_DATE,
    PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
    emit_mutation_observable,
    guard_proofgate_nodeid,
    proofgate_changed_grandfather_plan_bytes,
    proofgate_grandfather_plan_bytes,
    run_proofgate_contract,
)



def _get_validator_script() -> Path:
    script = Path.cwd() / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    if not script.exists():
        script = Path(__file__).resolve().parents[2] / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    return script


OBJECT_358_SPEC = "0196f19c7e9fd90e9a707de076271057b521e1d1:plans/detailed-board-silent-degradation-358-20260728.md"
OBJECT_288_SPEC = "4e7dbf419b85ffc5e57b43d424a680b1e92e9461:plans/detailed-288-fab-broker-readmission-20260726.md"


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
            combined_output = proc.stdout + proc.stderr
            cli_rejected_vacuous = (
                proc.returncode != 0
                and "vacuous_falsifier" in combined_output
            )
            if not cli_rejected_vacuous:
                emit_mutation_observable(
                    "ec-proofgate-3.vacuous-falsifier",
                    getattr(self, "record_property", None),
                )
            self.assertTrue(
                cli_rejected_vacuous,
                "validate_plan_doc.py must reject #358 at the vacuous-falsifier assertion",
            )

            contracts = goal_coverage.extract_acceptance_contracts(bytes_358)
            check_res = goal_coverage.check_acceptance_falsifiers(contracts)
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
            self.assertIn("vacuous_falsifier", combined_output)

            check_res = goal_coverage.check_acceptance_falsifiers(contracts)
            self.assertFalse(check_res.get("valid", True))

        run_proofgate_contract(nodeid, _contract)

    def test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns(self):
        nodeid = "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            try:
                from phase_loop_runtime import goal_coverage
            except ImportError as err:
                raise ProofgateMissingCapabilityError(
                    "goal_coverage module missing"
                ) from err

            if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
                raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

            cutoff_plan = _load_git_object_bytes(
                f"{PROOFGATE_GRANDFATHER_CUTOFF_OID}:{PROOFGATE_GRANDFATHER_PLAN_PATH}"
            )
            cutoff_contracts = goal_coverage.extract_acceptance_contracts(cutoff_plan)
            cutoff_result = goal_coverage.check_acceptance_falsifiers(
                cutoff_contracts,
                cutoff_commit_oid=PROOFGATE_GRANDFATHER_CUTOFF_OID,
                successor_commit_oid=PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
                server_attested_date=PROOFGATE_GRANDFATHER_SERVER_DATE,
            )
            if not cutoff_result.get("valid") or cutoff_result.get("disposition") != "grandfathered":
                emit_mutation_observable(
                    "ec-proofgate-7.grandfathering",
                    getattr(self, "record_property", None),
                )
            self.assertTrue(cutoff_result.get("valid"))
            self.assertEqual(cutoff_result.get("disposition"), "grandfathered")
            self.assertEqual(len(cutoff_contracts), 3)
            self.assertEqual(len(cutoff_result.get("grandfather_records", [])), 3)
            self.assertTrue(
                all(
                    row.get("server_attested_pre_grammar_date") == PROOFGATE_GRANDFATHER_SERVER_DATE
                    for row in cutoff_result["grandfather_records"]
                )
            )

            grandfather_plan = proofgate_grandfather_plan_bytes()
            contracts = goal_coverage.extract_acceptance_contracts(grandfather_plan)
            cutoff_bytes_parsed = bool(contracts)
            if not cutoff_bytes_parsed:
                emit_mutation_observable(
                    "ec-proofgate-7.grandfathering",
                    getattr(self, "record_property", None),
                )
            self.assertTrue(cutoff_bytes_parsed, "trusted cutoff criterion bytes must remain parseable")
            check_res = goal_coverage.check_acceptance_falsifiers(
                contracts,
                cutoff_commit_oid=PROOFGATE_GRANDFATHER_CUTOFF_OID,
                successor_commit_oid=PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
                server_attested_date=PROOFGATE_GRANDFATHER_SERVER_DATE,
            )
            raw_item_sha256 = hashlib.sha256(
                PROOFGATE_GRANDFATHER_RAW_ITEM.encode("utf-8")
            ).hexdigest()
            cond = (
                isinstance(check_res, dict)
                and check_res.get("valid", False) is True
                and check_res.get("disposition") == "grandfathered"
                and check_res.get("grandfather_records") == [
                    {
                        "criterion_id": "EC-P1-1",
                        "raw_item_sha256": raw_item_sha256,
                        "server_attested_pre_grammar_date": PROOFGATE_GRANDFATHER_SERVER_DATE,
                    }
                ]
            )
            if not cond:
                emit_mutation_observable("ec-proofgate-7.grandfathering", getattr(self, "record_property", None))
            self.assertTrue(cond, check_res)

            missing_cutoff = goal_coverage.check_acceptance_falsifiers(contracts)
            self.assertFalse(
                missing_cutoff.get("valid", True),
                "Exact historical bytes without cutoff proof must remain invalid",
            )
            self.assertEqual(missing_cutoff.get("disposition"), "invalid")
            self.assertEqual(missing_cutoff.get("reason"), "missing_falsifier")
            self.assertIs(missing_cutoff.get("requires_current_evidence"), True)

            invalid_cutoff = goal_coverage.check_acceptance_falsifiers(
                contracts,
                cutoff_commit_oid="0" * 40,
                successor_commit_oid=PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
                server_attested_date=PROOFGATE_GRANDFATHER_SERVER_DATE,
            )
            self.assertFalse(
                invalid_cutoff.get("valid", True),
                "Exact historical bytes with invalid cutoff proof must remain invalid",
            )
            self.assertEqual(invalid_cutoff.get("disposition"), "invalid")

            validator_script = _get_validator_script()
            with tempfile.TemporaryDirectory() as td:
                tf_path = Path(td) / "phase-plan-v10-PROOFGATE.md"
                tf_path.write_text(grandfather_plan, encoding="utf-8")
                unproved_proc = subprocess.run(
                    [sys.executable, str(validator_script), str(tf_path)],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(unproved_proc.returncode, 0)
                self.assertIn("missing_falsifier", unproved_proc.stdout + unproved_proc.stderr)
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(validator_script),
                        str(tf_path),
                        "--grammar-cutoff-commit",
                        PROOFGATE_GRANDFATHER_CUTOFF_OID,
                        "--grammar-successor-commit",
                        PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
                        "--server-attested-pre-grammar-date",
                        PROOFGATE_GRANDFATHER_SERVER_DATE,
                        "--grandfather-source-path",
                        "plans/detailed-goal-id-single-source-of-truth-211-redesign-20260719.md",
                    ],
                    cwd=Path(__file__).resolve().parents[2],
                    capture_output=True,
                    text=True,
                )
            output = proc.stdout + proc.stderr
            warning_lines = [
                line
                for line in output.splitlines()
                if "WARN" in line and "grandfathered" in line
            ]
            self.assertEqual(proc.returncode, 0, output)
            self.assertEqual(len(warning_lines), 1, output)
            self.assertIn("grandfathered", warning_lines[0])
            self.assertIn(PROOFGATE_GRANDFATHER_SERVER_DATE, warning_lines[0])
            self.assertNotIn("ERROR", output)

        run_proofgate_contract(nodeid, _contract)

    def test_changed_or_new_criterion_requires_v3_evidence(self):
        nodeid = "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            try:
                from phase_loop_runtime import goal_coverage
            except ImportError as err:
                raise ProofgateMissingCapabilityError(
                    "goal_coverage module missing"
                ) from err

            if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
                raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

            grandfather_plan = proofgate_grandfather_plan_bytes()
            new_plan = proofgate_changed_grandfather_plan_bytes()
            self.assertNotEqual(new_plan, grandfather_plan)
            contracts = goal_coverage.extract_acceptance_contracts(new_plan)
            check_res = goal_coverage.check_acceptance_falsifiers(
                contracts,
                cutoff_commit_oid=PROOFGATE_GRANDFATHER_CUTOFF_OID,
                successor_commit_oid=PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
                server_attested_date=PROOFGATE_GRANDFATHER_SERVER_DATE,
            )
            self.assertFalse(check_res.get("valid", True), "Changed or new criterion must hard-fail grandfathering check")
            self.assertEqual(check_res.get("disposition"), "invalid")
            self.assertEqual(check_res.get("reason"), "missing_falsifier")
            self.assertEqual(check_res.get("required_verification_schema_version"), 3)
            self.assertIs(check_res.get("requires_current_evidence"), True)

            validator_script = _get_validator_script()
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
                tf.write(new_plan)
                changed_path = tf.name
            proc = subprocess.run(
                [
                    sys.executable,
                    str(validator_script),
                    changed_path,
                    "--grammar-cutoff-commit",
                    PROOFGATE_GRANDFATHER_CUTOFF_OID,
                    "--grammar-successor-commit",
                    PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
                    "--server-attested-pre-grammar-date",
                    PROOFGATE_GRANDFATHER_SERVER_DATE,
                    "--grandfather-source-path",
                    "plans/detailed-goal-id-single-source-of-truth-211-redesign-20260719.md",
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
            )
            output = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, output)
            self.assertIn("missing_falsifier", output)
            self.assertIn("verification_evidence.v3", output)

        run_proofgate_contract(nodeid, _contract)


if __name__ == "__main__":
    unittest.main()
