"""test_acceptance_falsifier_contract.py — Acceptance falsifier contract tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from .proofgate_tdd_guard import (
    ProofgateMissingCapabilityError,
    PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES,
    emit_mutation_observable,
    guard_proofgate_nodeid,
    run_proofgate_contract,
)


def _validator_script_path() -> Path:
    script = Path.cwd() / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    if not script.exists():
        script = Path(__file__).resolve().parents[2] / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
    return script


def test_missing_falsifier_is_invalid(record_property):
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage

        if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
            raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers attribute missing on goal_coverage")

        plan_content_missing = (
            "# Phase Plan — Test\n\n"
            "## Acceptance Criteria\n"
            "- [ ] EC-FEATURE-1 — proven by `pytest phase-loop-runtime/tests/test_foo.py`\n"
        )
        plan_content_valid = (
            "# Phase Plan — Test\n\n"
            "## Acceptance Criteria\n"
            "- [ ] EC-FEATURE-1 — proven by `pytest phase-loop-runtime/tests/test_foo.py`, "
            "falsified by `python3 -c \"assert False\"`\n"
        )

        # 1. Python-level contract check and mutation observable emission first
        contracts_missing = goal_coverage.extract_acceptance_contracts(plan_content_missing)
        check_missing = goal_coverage.check_acceptance_falsifiers(contracts_missing)
        cond1 = isinstance(check_missing, dict) and not check_missing.get("valid", True) and check_missing.get("reason") == "missing_falsifier"
        if not cond1:
            emit_mutation_observable("ec-proofgate-1.missing-falsifier", record_property)

        contracts_valid = goal_coverage.extract_acceptance_contracts(plan_content_valid)
        check_valid = goal_coverage.check_acceptance_falsifiers(contracts_valid)
        cond2 = isinstance(check_valid, dict) and check_valid.get("valid", False) is True

        assert cond1, f"check_missing must return valid=False with reason missing_falsifier, got {check_missing}"
        assert cond2, f"check_valid must return valid=True, got {check_valid}"

        # 2. CLI process validation
        validator_script = _validator_script_path()
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
            tf.write(plan_content_missing)
            tf_path = tf.name

        proc = subprocess.run([sys.executable, str(validator_script), tf_path], capture_output=True, text=True)
        assert proc.returncode != 0, "validate_plan_doc.py CLI must exit non-zero when falsifier is missing"
        combined_output = proc.stdout + proc.stderr
        assert "EC-FEATURE-1" in combined_output
        assert "missing_falsifier" in combined_output
        assert "WARN" not in combined_output

    run_proofgate_contract(nodeid, _contract)


def test_negative_assertion_requires_path_entered_control(record_property):
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage

        if not hasattr(goal_coverage, "extract_acceptance_contracts") or not hasattr(goal_coverage, "check_acceptance_falsifiers"):
            raise ProofgateMissingCapabilityError("extract_acceptance_contracts or check_acceptance_falsifiers missing on goal_coverage")

        validator_script = _validator_script_path()

        # Arm 1: Absence claim without path-entered control
        plan_no_control = PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
            tf.write(plan_no_control)
            tf_path = tf.name

        contracts_no_control = goal_coverage.extract_acceptance_contracts(plan_no_control)
        check_no_control = goal_coverage.check_acceptance_falsifiers(contracts_no_control)
        cond1 = isinstance(check_no_control, dict) and not check_no_control.get("valid", True) and check_no_control.get("reason") == "missing_path_entered_control"
        if not cond1:
            emit_mutation_observable("ec-proofgate-6.missing-path-entered", record_property)

        # Arm 2: Absence claim with path-entered control
        plan_with_control = (
            "# Phase Plan — Test\n\n"
            "## Acceptance Criteria\n"
            "- [ ] EC-FEAT-2 — proven by `pytest tests/test_foo.py`, "
            "falsified by `fails if invalid key is accepted when path-entered control reaches branch B`\n"
        )
        contracts_with_control = goal_coverage.extract_acceptance_contracts(plan_with_control)
        check_with_control = goal_coverage.check_acceptance_falsifiers(contracts_with_control)
        cond2 = isinstance(check_with_control, dict) and check_with_control.get("valid", False) is True

        proc = subprocess.run([sys.executable, str(validator_script), tf_path], capture_output=True, text=True)
        assert proc.returncode != 0, "validate_plan_doc.py CLI must exit non-zero when path-entered control is missing"

        assert cond1
        assert cond2

    run_proofgate_contract(nodeid, _contract)


def test_guard_requires_production_construction_site():
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import goal_coverage

        if not hasattr(goal_coverage, "is_production_construction_site"):
            raise ProofgateMissingCapabilityError("is_production_construction_site attribute missing on goal_coverage")

        checker = goal_coverage.is_production_construction_site
        site_helper = "phase-loop-runtime/tests/proofgate_tdd_guard.py"
        assert not checker(site_helper), "Helper-only declaration must be classified as invalid construction site"

        site_prod = "phase-loop-runtime/src/phase_loop_runtime/runner.py"
        assert checker(site_prod), "Real production path must be classified as valid construction site"

    run_proofgate_contract(nodeid, _contract)


def test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage():
    nodeid = "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage"
    if not guard_proofgate_nodeid(nodeid):
        return

    def _contract():
        from phase_loop_runtime import verification_evidence

        if not hasattr(verification_evidence, "execute_proofgate_mutation_manifest"):
            raise ProofgateMissingCapabilityError("execute_proofgate_mutation_manifest attribute missing on verification_evidence")

        from .proofgate_tdd_guard import validate_mutation_manifest_structure

        manifest_path = Path(__file__).parent / "fixtures" / "proofgate" / "v10-proofgate-mutations.json"
        res_struct = validate_mutation_manifest_structure(manifest_path)
        assert res_struct is not None, "validate_mutation_manifest_structure must not return None"
        assert res_struct.get("is_valid") is True or res_struct.get("status") == "valid"
        assert res_struct["criteria_count"] == 8
        assert res_struct["parameters_count"] == 9

        try:
            cand_oid = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        except Exception:
            cand_oid = "0000000000000000000000000000000000000000"

        exec_fn = verification_evidence.execute_proofgate_mutation_manifest
        exec_res = exec_fn(manifest_path=manifest_path, candidate_oid=cand_oid)
        assert isinstance(exec_res, dict)
        assert exec_res.get("parameters_count") == 9
        assert exec_res.get("killed_count") == 9
        assert exec_res.get("survived_count") == 0
        assert exec_res.get("block_count") == 0
        assert exec_res.get("status") == "killed"
        assert len(exec_res.get("classifications", {})) == 9
        assert all(v == "killed" for v in exec_res["classifications"].values())
        bindings = exec_res.get("bindings", {})
        assert len(bindings) == 9
        for b in bindings.values():
            assert "candidate" in b
            assert "tree" in b
            assert "path" in b
            assert "blob" in b
            assert "argv" in b
            assert "command" in b
            assert "environment" in b
            assert "testcase" in b
            assert "assertion" in b

    run_proofgate_contract(nodeid, _contract)
