"""proofgate_content_tdd_adapter.py — TG-PROOFGATE-0 bounded content TDD adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

from phase_loop_runtime.declared_identity import select_declared_commit
from phase_loop_runtime.fab_delta import _translate_glob_to_regex
from phase_loop_runtime.tdd_receipts import (
    RED_ANCHOR_MARKER,
    record_content_tdd_receipt,
    verify_content_tdd_receipt,
)


class ProofgateMissingCapabilityError(Exception):
    """Raised by a PROOFGATE test contract when an expected capability is absent."""


def proofgate_active() -> bool:
    """True if PROOFGATE RED mode is active via environment."""
    return os.environ.get("PHASE_LOOP_TDD_EXPECT_PROOFGATE") == "1"


def verify_proofgate_content_tdd_junit(
    junit_xml_str_or_path: str | Path,
    expected_nodeids: tuple[str, ...] = (),
    group_name: str = "",
    pytest_output: str = "",
    returncode: int = 0,
) -> dict[str, Any]:
    """Executable accounting function called by _run_and_assert and adapter tests."""
    if returncode != 0:
        return {
            "ok": False,
            "error": f"Pytest process failed with exit code {returncode}",
            "passed": 0,
            "failed": 1,
            "skipped": 0,
            "errored": 0,
            "xfailed": 0,
            "xpassed": 0,
            "collected": [],
        }

    if pytest_output:
        if re.search(r"\bXPASS\b|\bunexpected pass\b", pytest_output, re.IGNORECASE):
            return {
                "ok": False,
                "error": f"Non-strict XPASS detected in pytest report output for group '{group_name}'",
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errored": 0,
                "xfailed": 0,
                "xpassed": 1,
                "collected": [],
            }
        deselected_match = re.search(r"(\d+)\s+deselected", pytest_output)
        if deselected_match:
            deselected_cnt = int(deselected_match.group(1))
            if deselected_cnt > 0:
                return {
                    "ok": False,
                    "error": f"Deselected tests detected in pytest report output for group '{group_name}': {deselected_cnt}",
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errored": 0,
                    "xfailed": 0,
                    "xpassed": 0,
                    "collected": [],
                }

    if isinstance(junit_xml_str_or_path, Path):
        if not junit_xml_str_or_path.exists():
            return {
                "ok": False,
                "error": f"JUnit XML file not found: {junit_xml_str_or_path}",
                "passed": 0,
                "failed": 1,
                "skipped": 0,
                "errored": 0,
                "xfailed": 0,
                "xpassed": 0,
                "collected": [],
            }
        xml_str = junit_xml_str_or_path.read_text(encoding="utf-8")
    else:
        xml_str = str(junit_xml_str_or_path)

    if not xml_str.strip():
        return {
            "ok": False,
            "error": "Empty JUnit XML input",
            "passed": 0,
            "failed": 1,
            "skipped": 0,
            "errored": 0,
            "xfailed": 0,
            "xpassed": 0,
            "collected": [],
        }

    try:
        root = ET.fromstring(xml_str)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to parse JUnit XML: {exc}",
            "passed": 0,
            "failed": 1,
            "skipped": 0,
            "errored": 0,
            "xfailed": 0,
            "xpassed": 0,
            "collected": [],
        }

    testcases = root.findall(".//testcase")
    collected_nodeids = []
    passed_count = 0
    skipped_count = 0
    failed_count = 0
    errored_count = 0
    xfailed_count = 0
    xpassed_count = 0

    for tc in testcases:
        classname = tc.attrib.get("classname", "")
        name = tc.attrib.get("name", "")
        file_attr = tc.attrib.get("file", "")

        if file_attr:
            if "::" in classname:
                parts = classname.split("::")
                nodeid = f"{file_attr}::{parts[-1]}::{name}"
            elif classname and not classname.endswith(Path(file_attr).stem):
                class_short = classname.split(".")[-1]
                nodeid = f"{file_attr}::{class_short}::{name}"
            else:
                nodeid = f"{file_attr}::{name}"
        else:
            nodeid = f"{classname}::{name}"

        if not nodeid.startswith("phase-loop-runtime/") and nodeid.startswith("tests/"):
            nodeid = f"phase-loop-runtime/{nodeid}"

        collected_nodeids.append(nodeid)

        skipped_elem = tc.find("skipped")
        if tc.find("failure") is not None:
            failed_count += 1
        elif tc.find("error") is not None:
            errored_count += 1
        elif skipped_elem is not None:
            skipped_type = skipped_elem.attrib.get("type", "")
            if "xfail" in skipped_type.lower():
                xfailed_count += 1
            else:
                skipped_count += 1
        else:
            msg = tc.attrib.get("message", "")
            if "xpass" in msg.lower() or "unexpected pass" in msg.lower():
                xpassed_count += 1
            else:
                passed_count += 1

    if expected_nodeids:
        norm_expected = [
            n if n.startswith("phase-loop-runtime/") else f"phase-loop-runtime/{n}"
            for n in expected_nodeids
        ]
        norm_collected = [
            n if n.startswith("phase-loop-runtime/") else f"phase-loop-runtime/{n}"
            for n in collected_nodeids
        ]

        if len(norm_collected) != len(set(norm_collected)):
            return {
                "ok": False,
                "error": f"Duplicate collected node IDs found for group '{group_name}'",
                "passed": passed_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "errored": errored_count,
                "xfailed": xfailed_count,
                "xpassed": xpassed_count,
                "collected": collected_nodeids,
            }

        if sorted(norm_expected) != sorted(norm_collected):
            return {
                "ok": False,
                "error": (
                    f"Collected node IDs do not match declared set for group '{group_name}'\n"
                    f"Expected: {norm_expected}\nCollected: {norm_collected}"
                ),
                "passed": passed_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "errored": errored_count,
                "xfailed": xfailed_count,
                "xpassed": xpassed_count,
                "collected": collected_nodeids,
            }

    if passed_count == 0:
        return {
            "ok": False,
            "error": f"Expected at least 1 passing test in group '{group_name}', got 0",
            "passed": 0,
            "failed": failed_count,
            "skipped": skipped_count,
            "errored": errored_count,
            "xfailed": xfailed_count,
            "xpassed": xpassed_count,
            "collected": collected_nodeids,
        }

    if failed_count > 0 or errored_count > 0 or skipped_count > 0 or xfailed_count > 0 or xpassed_count > 0:
        return {
            "ok": False,
            "error": (
                f"Non-zero invalid counts for group '{group_name}': "
                f"failed={failed_count}, errored={errored_count}, skipped={skipped_count}, "
                f"xfailed={xfailed_count}, xpassed={xpassed_count}"
            ),
            "passed": passed_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "errored": errored_count,
            "xfailed": xfailed_count,
            "xpassed": xpassed_count,
            "collected": collected_nodeids,
        }

    return {
        "ok": True,
        "error": None,
        "passed": passed_count,
        "failed": 0,
        "skipped": 0,
                "collected": collected_nodeids,
            }


# Closed exact-node-ID groups for SL1, SL0, SL2
SL1_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_chronology_guard_unmatched_anchor_is_mutation_not_applied",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_unmatched_anchor_is_mutation_not_applied",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_candidate_or_command_digest_drift",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation",
)

SL0_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_preflight_gates_enforce_acceptance_falsifiers_on_all_routes",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_closeout_recheck_blocks_invalid_falsifiers_on_delegated_reduction",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_final_closeout_boundary_enforces_path_entered_and_advisory_check_p",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_ec4_helper_only_mutation_cannot_be_credited_as_kill",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage",
    "phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageTest::test_acceptance_contracts_classify_valid_invalid_and_grandfathered",
)

SL2_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_288_ac1_and_ac4_are_rejected",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence",
    "phase-loop-runtime/tests/test_skills_canon_parity.py::SkillsCanonParityTest::test_plan_phase_skills_publish_falsifier_grammar",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py::SkillsBundleDriftTest::test_proofgate_validator_and_guidance_are_generated_without_drift",
)

EC0_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_chronology_guard_unmatched_anchor_is_mutation_not_applied",
)

EC1_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_preflight_gates_enforce_acceptance_falsifiers_on_all_routes",
)

EC2_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_unmatched_anchor_is_mutation_not_applied",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline",
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_candidate_or_command_digest_drift",
)

EC3_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_closeout_recheck_blocks_invalid_falsifiers_on_delegated_reduction",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_288_ac1_and_ac4_are_rejected",
    "phase-loop-runtime/tests/test_skills_canon_parity.py::SkillsCanonParityTest::test_plan_phase_skills_publish_falsifier_grammar",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py::SkillsBundleDriftTest::test_proofgate_validator_and_guidance_are_generated_without_drift",
)

EC4_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_ec4_helper_only_mutation_cannot_be_credited_as_kill",
)

EC5_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage",
)

EC6_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_final_closeout_boundary_enforces_path_entered_and_advisory_check_p",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control",
)

EC7_NODEIDS: tuple[str, ...] = (
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence",
    "phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageTest::test_acceptance_contracts_classify_valid_invalid_and_grandfathered",
)

GROUPS: dict[str, tuple[str, ...]] = {
    "sl1": SL1_NODEIDS,
    "sl0": SL0_NODEIDS,
    "sl2": SL2_NODEIDS,
    "ec-0": EC0_NODEIDS,
    "ec-1": EC1_NODEIDS,
    "ec-2": EC2_NODEIDS,
    "ec-3": EC3_NODEIDS,
    "ec-4": EC4_NODEIDS,
    "ec-5": EC5_NODEIDS,
    "ec-6": EC6_NODEIDS,
    "ec-7": EC7_NODEIDS,
}

_LANE_UNION = set(SL1_NODEIDS) | set(SL0_NODEIDS) | set(SL2_NODEIDS)
_CRITERIA_UNION = (
    set(EC0_NODEIDS)
    | set(EC1_NODEIDS)
    | set(EC2_NODEIDS)
    | set(EC3_NODEIDS)
    | set(EC4_NODEIDS)
    | set(EC5_NODEIDS)
    | set(EC6_NODEIDS)
    | set(EC7_NODEIDS)
)


def _validate_exact_partition(groups: tuple[tuple[str, ...], ...], expected: set[str]) -> str | None:
    flattened = [nodeid for group in groups for nodeid in group]
    duplicates = sorted({nodeid for nodeid in flattened if flattened.count(nodeid) > 1})
    if duplicates:
        return f"duplicate node IDs across groups: {duplicates}"
    observed = set(flattened)
    if observed != expected:
        return f"partition differs from expected node set: {sorted(observed ^ expected)}"
    return None

assert len(SL1_NODEIDS) == 7
assert len(SL0_NODEIDS) == 9
assert len(SL2_NODEIDS) == 6
assert len(_LANE_UNION) == 22
assert len(set(SL1_NODEIDS) & set(SL0_NODEIDS)) == 0
assert len(set(SL1_NODEIDS) & set(SL2_NODEIDS)) == 0
assert len(set(SL0_NODEIDS) & set(SL2_NODEIDS)) == 0
_criteria_partition_error = _validate_exact_partition(
    (EC0_NODEIDS, EC1_NODEIDS, EC2_NODEIDS, EC3_NODEIDS, EC4_NODEIDS, EC5_NODEIDS, EC6_NODEIDS, EC7_NODEIDS),
    _LANE_UNION,
)
assert _criteria_partition_error is None, _criteria_partition_error
assert _LANE_UNION == _CRITERIA_UNION

RED_CASES_BY_NODEID: dict[str, tuple[str, str]] = {
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_chronology_guard_unmatched_anchor_is_mutation_not_applied": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_chronology_guard_unmatched_anchor_is_mutation_not_applied",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_unmatched_anchor_is_mutation_not_applied": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_unmatched_anchor_is_mutation_not_applied",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
    ),
    "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_candidate_or_command_digest_drift": (
        "PG-A-VERIFY-V3",
        "proofgate_v3_rejects_candidate_or_command_digest_drift",
    ),
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation": (
        "PG-A-BROKER-GITHUB",
        "github_builder_epoch_blocked_unwired",
    ),
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation": (
        "PG-A-BROKER-ROUTING",
        "routing_builder_epoch_blocked_unwired",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid": (
        "PG-A-GOAL",
        "missing_falsifier_is_invalid",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_preflight_gates_enforce_acceptance_falsifiers_on_all_routes": (
        "PG-A-GOAL",
        "runner_preflight_gates_enforce_acceptance_falsifiers_on_all_routes",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_closeout_recheck_blocks_invalid_falsifiers_on_delegated_reduction": (
        "PG-A-GOAL",
        "runner_closeout_recheck_blocks_invalid_falsifiers_on_delegated_reduction",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_runner_final_closeout_boundary_enforces_path_entered_and_advisory_check_p": (
        "PG-A-GOAL",
        "runner_final_closeout_boundary_enforces_path_entered_and_advisory_check_p",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control": (
        "PG-A-GOAL",
        "negative_assertion_requires_path_entered_control",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_guard_requires_production_construction_site": (
        "PG-A-GOAL",
        "guard_requires_production_construction_site",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_ec4_helper_only_mutation_cannot_be_credited_as_kill": (
        "PG-A-GOAL",
        "ec4_helper_only_mutation_cannot_be_credited_as_kill",
    ),
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage": (
        "PG-A-GOAL",
        "mutation_manifest_requires_exact_criterion_parameter_and_command_coverage",
    ),
    "phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageTest::test_acceptance_contracts_classify_valid_invalid_and_grandfathered": (
        "PG-A-GOAL",
        "acceptance_contracts_classify_valid_invalid_and_grandfathered",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected": (
        "PG-A-VALIDATOR",
        "agent_harness_358_original_is_rejected",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_288_ac1_and_ac4_are_rejected": (
        "PG-A-VALIDATOR",
        "agent_harness_288_ac1_and_ac4_are_rejected",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns": (
        "PG-A-VALIDATOR",
        "grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
    ),
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_changed_or_new_criterion_requires_v3_evidence": (
        "PG-A-VALIDATOR",
        "changed_or_new_criterion_requires_v3_evidence",
    ),
    "phase-loop-runtime/tests/test_skills_canon_parity.py::SkillsCanonParityTest::test_plan_phase_skills_publish_falsifier_grammar": (
        "PG-A-VALIDATOR",
        "plan_phase_skills_publish_falsifier_grammar",
    ),
    "phase-loop-runtime/tests/test_skills_bundle_drift.py::SkillsBundleDriftTest::test_proofgate_validator_and_guidance_are_generated_without_drift": (
        "PG-A-VALIDATOR",
        "proofgate_validator_and_guidance_are_generated_without_drift",
    ),
}

assert len(set(v[1] for v in RED_CASES_BY_NODEID.values())) == len(RED_CASES_BY_NODEID), "Duplicate RED case IDs found in RED_CASES_BY_NODEID"


def _repo_root() -> Path:
    cmd = ["git", "rev-parse", "--show-toplevel"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return Path(proc.stdout.strip()).resolve()


def assert_source_anchor(anchor_id: str) -> None:
    root = _repo_root()
    if anchor_id == "PG-A-LOCK":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/runner.py"
        content = path.read_text(encoding="utf-8")
        assert "from .dispatch_lock import DispatchLock, DispatchLockContention" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-GOAL":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py"
        content = path.read_text(encoding="utf-8")
        assert "_ACCEPTANCE_SECTION_RE = re.compile(" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-VERIFY-V3":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py"
        content = path.read_text(encoding="utf-8")
        assert "EXTENSION_NAMESPACE_REGISTRY" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-VALIDATOR":
        path = root / "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py"
        content = path.read_text(encoding="utf-8")
        assert "def _check_p_goal_id_coverage(" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-BROKER-GITHUB":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py"
        content = path.read_text(encoding="utf-8")
        assert "epoch_blocked=lambda: evidence_store.epoch_blocked" in content, f"Anchor {anchor_id} missing in {path}"
    elif anchor_id == "PG-A-BROKER-ROUTING":
        path = root / "phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py"
        content = path.read_text(encoding="utf-8")
        assert "epoch_blocked=lambda: evidence_store.epoch_blocked" in content, f"Anchor {anchor_id} missing in {path}"


def guard_proofgate_nodeid(nodeid: str) -> bool:
    if nodeid not in _LANE_UNION:
        raise ValueError(f"Nodeid {nodeid} is not in scoped TDD adapter union")
    anchor_id, _ = RED_CASES_BY_NODEID[nodeid]
    assert_source_anchor(anchor_id)
    return True


def proofgate_red_message(nodeid: str) -> str:
    if nodeid in RED_CASES_BY_NODEID:
        return f"PROOFGATE_RED::{RED_CASES_BY_NODEID[nodeid][1]}"
    return f"PROOFGATE_RED::{nodeid}"


def run_proofgate_contract(nodeid: str, contract_fn) -> None:
    anchor_id, _ = RED_CASES_BY_NODEID[nodeid]
    assert_source_anchor(anchor_id)

    if proofgate_active():
        try:
            contract_fn()
        except ProofgateMissingCapabilityError as exc:
            msg = f"{RED_ANCHOR_MARKER} {proofgate_red_message(nodeid)}"
            raise AssertionError(msg) from exc

        # Unrelated exceptions propagate unchanged!
        # If contract completed cleanly without raising ProofgateMissingCapabilityError:
        raise AssertionError(
            f"Expected ProofgateMissingCapabilityError for {nodeid}, but contract completed without raising expected exception."
        )
    else:
        try:
            contract_fn()
        except ProofgateMissingCapabilityError:
            import pytest
            pytest.skip(f"Capability unimplemented for {nodeid}")


# Constants and fixtures
MUTATION_RULES_BY_PARAMETER: dict[str, tuple[str, str, str, str, str, str]] = {
    "ec-proofgate-0.chronology-guard": (
        "EC-PROOFGATE-0",
        "1c6230d9b116fc9fb758df530f4319d2570c4500fc0f793e960bfffea0beb4b1",
        "ec-proofgate-0.chronology-guard",
        "tdd_chronology_rejection",
        "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_chronology_guard_unmatched_anchor_is_mutation_not_applied",
        "chronology_guard_unwired",
    ),
    "ec-proofgate-1.missing-falsifier": (
        "EC-PROOFGATE-1",
        "2eb6215c889f5db9d6c5559819a4374be8a89e2a426833c565636c967634b62f",
        "ec-proofgate-1.missing-falsifier",
        "missing_falsifier_rejection",
        "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_missing_falsifier_is_invalid",
        "missing_falsifier_unwired",
    ),
    "ec-proofgate-2.mutation-application": (
        "EC-PROOFGATE-2",
        "f379956954c1096e75b3b81635e171827be747eef7c565a8e6f68e6db4039e7d",
        "ec-proofgate-2.mutation-application",
        "mutation_application_rejection",
        "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_unmatched_anchor_is_mutation_not_applied",
        "mutation_not_applied_guard_unwired",
    ),
    "ec-proofgate-3.vacuous-falsifier": (
        "EC-PROOFGATE-3",
        "c33f5018894552d5af14a0ed4097838d61936f46b4a486186c1a8dd8e0cd03c9",
        "ec-proofgate-3.vacuous-falsifier",
        "vacuous_falsifier_rejection",
        "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_agent_harness_358_original_is_rejected",
        "vacuous_falsifier_unwired",
    ),
    "ec-proofgate-4.github-builder-epoch-blocked": (
        "EC-PROOFGATE-4",
        "2b1d58a75fabc43e45c908b4e44d616778a29cf5011612e09d9bffa0689d4e7b",
        "ec-proofgate-4.github-builder-epoch-blocked",
        "production_construction_site_rejection",
        "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_github_broker_admission_store_is_wired_to_evidence_revocation",
        "github_builder_epoch_blocked_unwired",
    ),
    "ec-proofgate-4.routing-builder-epoch-blocked": (
        "EC-PROOFGATE-4",
        "2b1d58a75fabc43e45c908b4e44d616778a29cf5011612e09d9bffa0689d4e7b",
        "ec-proofgate-4.routing-builder-epoch-blocked",
        "production_construction_site_rejection",
        "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py::test_routing_broker_admission_store_is_wired_to_evidence_revocation",
        "routing_builder_epoch_blocked_unwired",
    ),
    "ec-proofgate-5.parameter-coverage": (
        "EC-PROOFGATE-5",
        "cdd99cae0696b659640cc3481195e93e54af35198f76fd1ae727f9720b4de4c0",
        "ec-proofgate-5.parameter-coverage",
        "parameter_coverage_rejection",
        "phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_rejects_missing_duplicate_extra_substituted_or_surviving_parameter",
        "parameter_coverage_unwired",
    ),
    "ec-proofgate-6.missing-path-entered": (
        "EC-PROOFGATE-6",
        "397cd8f421b1149d64b9039eb87e6da17114cdb7842f64e28937548dd0169526",
        "ec-proofgate-6.missing-path-entered",
        "missing_path_entered_control_rejection",
        "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_negative_assertion_requires_path_entered_control",
        "missing_path_entered_control_unwired",
    ),
    "ec-proofgate-7.grandfathering": (
        "EC-PROOFGATE-7",
        "84456823b1ff6fac271929a429b5b0acaf6af47884ef59a5dda011f65f6f3f0a",
        "ec-proofgate-7.grandfathering",
        "grandfathering_rejection",
        "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py::ProofgatePlanValidatorTest::test_grandfathering_uses_exact_cutoff_criterion_bytes_and_warns",
        "grandfathering_unwired",
    ),
}

EC_PROOFGATE_4_ASSERTION_IDS: dict[str, str] = {
    "ec-proofgate-4.github-builder-epoch-blocked": "github_builder_epoch_blocked_wiring",
    "ec-proofgate-4.routing-builder-epoch-blocked": "routing_builder_epoch_blocked_wiring",
}

PROOFGATE_INVALID_ACCEPTANCE_ROUTE_BYTES = (
    "# PROOFGATE route rejection\n\n"
    "## Acceptance Criteria\n"
    "- [ ] EC-PROOFGATE-ROUTE-1 — proven by `python3 -c \"print('ok')\"`, "
    "falsified by `fails if invalid key is accepted`\n"
)
PROOFGATE_MISSING_FALSIFIER_ROUTE_BYTES = (
    "# PROOFGATE missing falsifier\n\n"
    "## Acceptance Criteria\n"
    "- [ ] EC-PROOFGATE-ROUTE-2 — proven by `python3 -c \"print('ok')\"`\n"
)
PROOFGATE_VACUOUS_CORPUS_SPEC = (
    "0196f19c7e9fd90e9a707de076271057b521e1d1:"
    "plans/detailed-board-silent-degradation-358-20260728.md"
)
PROOFGATE_GRANDFATHER_PLAN_PATH = (
    "plans/detailed-goal-id-single-source-of-truth-211-redesign-20260719.md"
)
PROOFGATE_GRANDFATHER_RAW_ITEM = (
    "- [ ] EC-P1-1 — proven by `pytest tests/test_closeout.py -k register_validator`"
)
PROOFGATE_GRANDFATHER_CUTOFF_OID = "5328694ae31b4f13f091903d96ed89395d74f3b2"
PROOFGATE_GRANDFATHER_SUCCESSOR_OID = "a3fbb196b3b57d75e403bcea3bad972e9491f675"
PROOFGATE_GRANDFATHER_SERVER_DATE = "2026-07-29T22:09:58Z"


def proofgate_grandfather_plan_bytes() -> str:
    root = _repo_root()
    for revision in (PROOFGATE_GRANDFATHER_CUTOFF_OID, "HEAD"):
        observed = subprocess.run(
            ["git", "show", f"{revision}:{PROOFGATE_GRANDFATHER_PLAN_PATH}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if observed.returncode != 0 or observed.stdout.count(PROOFGATE_GRANDFATHER_RAW_ITEM) != 1:
            raise AssertionError(
                f"grandfather raw item is not unique at {revision}:{PROOFGATE_GRANDFATHER_PLAN_PATH}"
            )
    base_plan = (root / "plans" / "phase-plan-v10-PROOFGATE.md").read_text(encoding="utf-8")
    new_acc = f"## Acceptance Criteria\n\n{PROOFGATE_GRANDFATHER_RAW_ITEM}\n"
    return re.sub(r"## Acceptance Criteria\n.*", new_acc, base_plan, flags=re.DOTALL)


def proofgate_changed_grandfather_plan_bytes() -> str:
    changed = proofgate_grandfather_plan_bytes().replace(
        "register_validator`",
        "register_validator_changed`",
    )
    if changed == proofgate_grandfather_plan_bytes():
        raise AssertionError("PROOFGATE changed-grandfather fixture did not change")
    return changed


def emit_mutation_observable(param_id: str, record_property: Any) -> None:
    if record_property is None or param_id not in MUTATION_RULES_BY_PARAMETER:
        return
    crit_id, crit_sha, rule_id, fail_class, nodeid, res_code = MUTATION_RULES_BY_PARAMETER[param_id]
    observable = {
        "roadmap_criterion_id": crit_id,
        "roadmap_criterion_sha256": crit_sha,
        "rule_id": rule_id,
        "channel": "pytest_junit_call_property",
        "target_nodeid": nodeid,
        "result_code": res_code,
    }
    if param_id in EC_PROOFGATE_4_ASSERTION_IDS:
        observable["assertion_id"] = EC_PROOFGATE_4_ASSERTION_IDS[param_id]
    record_property("proofgate_mutation_observable", json.dumps(observable, sort_keys=True))


def assert_exact_mutation_observable(param_id: str, properties: list[tuple[str, str]]) -> None:
    if param_id not in MUTATION_RULES_BY_PARAMETER:
        raise AssertionError(f"unknown mutation parameter: {param_id}")
    if len(properties) != 1 or properties[0][0] != "proofgate_mutation_observable":
        raise AssertionError("mutation observable must contain exactly one canonical property")
    try:
        actual = json.loads(properties[0][1])
    except (TypeError, json.JSONDecodeError) as exc:
        raise AssertionError("mutation observable property must contain canonical JSON") from exc
    if not isinstance(actual, dict):
        raise AssertionError("mutation observable JSON must be an object")

    crit_id, crit_sha, rule_id, fail_class, nodeid, res_code = MUTATION_RULES_BY_PARAMETER[param_id]
    expected = {
        "roadmap_criterion_id": crit_id,
        "roadmap_criterion_sha256": crit_sha,
        "rule_id": rule_id,
        "channel": "pytest_junit_call_property",
        "target_nodeid": nodeid,
        "result_code": res_code,
    }
    if param_id in EC_PROOFGATE_4_ASSERTION_IDS:
        expected["assertion_id"] = EC_PROOFGATE_4_ASSERTION_IDS[param_id]
    if actual != expected:
        raise AssertionError(f"mutation observable mismatch: expected {expected}, got {actual}")


def validate_mutation_manifest_structure(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists() or not manifest_path.is_file():
        return {"is_valid": False, "status": "invalid", "error": f"Manifest file missing: {manifest_path}"}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"is_valid": False, "status": "invalid", "error": f"Malformed JSON: {exc}"}

    if raw.get("schema") != "mutation_manifest.v1" or raw.get("phase") != "PROOFGATE":
        return {"is_valid": False, "status": "invalid", "error": "Invalid schema or phase"}

    declarations = raw.get("declarations", [])
    if len(declarations) != 8:
        return {"is_valid": False, "status": "invalid", "error": f"Expected 8 criteria, got {len(declarations)}"}

    expected_criteria = [f"EC-PROOFGATE-{i}" for i in range(8)]
    observed_criteria = []
    for dec in declarations:
        cid = dec.get("criterion_id")
        if not cid:
            return {"is_valid": False, "status": "invalid", "error": "Missing criterion_id"}
        observed_criteria.append(cid)

    if observed_criteria != expected_criteria:
        return {"is_valid": False, "status": "invalid", "error": f"Criteria mismatch: expected {expected_criteria}, got {observed_criteria}"}

    root = _repo_root()

    expected_parameters_by_criterion = {
        "EC-PROOFGATE-0": ["ec-proofgate-0.chronology-guard"],
        "EC-PROOFGATE-1": ["ec-proofgate-1.missing-falsifier"],
        "EC-PROOFGATE-2": ["ec-proofgate-2.mutation-application"],
        "EC-PROOFGATE-3": ["ec-proofgate-3.vacuous-falsifier"],
        "EC-PROOFGATE-4": ["ec-proofgate-4.github-builder-epoch-blocked", "ec-proofgate-4.routing-builder-epoch-blocked"],
        "EC-PROOFGATE-5": ["ec-proofgate-5.parameter-coverage"],
        "EC-PROOFGATE-6": ["ec-proofgate-6.missing-path-entered"],
        "EC-PROOFGATE-7": ["ec-proofgate-7.grandfathering"],
    }

    all_observed_parameters = set()

    for dec in declarations:
        crit_id = dec["criterion_id"]
        expected_params = expected_parameters_by_criterion[crit_id]
        params = dec.get("parameters", [])
        observed_param_ids = [p.get("parameter_id") for p in params]

        if observed_param_ids != expected_params:
            return {
                "is_valid": False,
                "status": "invalid",
                "error": f"Parameter list mismatch for criterion {crit_id}: expected {expected_params}, got {observed_param_ids}",
            }

        for param in params:
            pid = param.get("parameter_id")
            if pid in all_observed_parameters:
                return {"is_valid": False, "status": "invalid", "error": f"Duplicate parameter_id {pid}"}
            all_observed_parameters.add(pid)

            rule = MUTATION_RULES_BY_PARAMETER.get(pid)
            if not rule:
                return {"is_valid": False, "status": "invalid", "error": f"Unknown parameter_id {pid}"}

            expected_crit, expected_sha, expected_pid, expected_fail_class, expected_nodeid, expected_res_code = rule

            target_kind = param.get("target_kind") or dec.get("target_kind")
            if not target_kind or not isinstance(target_kind, str):
                return {"is_valid": False, "status": "invalid", "error": f"Missing or invalid target_kind for {pid}"}

            target_rel_path = param.get("target_path", "")
            target_abs_path = root / target_rel_path
            if not target_abs_path.exists() or not target_abs_path.is_file():
                return {"is_valid": False, "status": "invalid", "error": f"Target path missing: {target_rel_path}"}

            anchor = param.get("injection_anchor", "")
            if not anchor:
                return {"is_valid": False, "status": "invalid", "error": f"Missing injection_anchor for {pid}"}

            target_content = target_abs_path.read_text(encoding="utf-8")
            anchor_count = target_content.count(anchor)
            if anchor_count != 1:
                return {
                    "is_valid": False,
                    "status": "invalid",
                    "error": f"Injection anchor for {pid} is not unique in {target_rel_path} (found {anchor_count})",
                }

            replacement = param.get("replacement_bytes", "")
            if not replacement or replacement == anchor:
                return {
                    "is_valid": False,
                    "status": "invalid",
                    "error": f"Invalid or non-different replacement_bytes for {pid}",
                }

            tnode = param.get("target_nodeid", "")
            if tnode != expected_nodeid:
                return {
                    "is_valid": False,
                    "status": "invalid",
                    "error": f"target_nodeid mismatch for {pid}: expected {expected_nodeid}, got {tnode}",
                }
            if tnode not in _LANE_UNION:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in scoped lane union"}

            if crit_id == "EC-PROOFGATE-0" and tnode not in EC0_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC0 group"}
            elif crit_id == "EC-PROOFGATE-1" and tnode not in EC1_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC1 group"}
            elif crit_id == "EC-PROOFGATE-2" and tnode not in EC2_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC2 group"}
            elif crit_id == "EC-PROOFGATE-3" and tnode not in EC3_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC3 group"}
            elif crit_id == "EC-PROOFGATE-4" and tnode not in EC4_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC4 group"}
            elif crit_id == "EC-PROOFGATE-5" and tnode not in EC5_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC5 group"}
            elif crit_id == "EC-PROOFGATE-6" and tnode not in EC6_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC6 group"}
            elif crit_id == "EC-PROOFGATE-7" and tnode not in EC7_NODEIDS:
                return {"is_valid": False, "status": "invalid", "error": f"target_nodeid {tnode} not in EC7 group"}

            pcmd = param.get("proof_command", [])
            if not isinstance(pcmd, list) or not pcmd:
                return {"is_valid": False, "status": "invalid", "error": f"Missing or invalid proof_command for {pid}"}
            if len(pcmd) < 4 or pcmd[0] != "python3" or pcmd[1] != "-m" or pcmd[2] != "pytest" or pcmd[3] != tnode:
                return {
                    "is_valid": False,
                    "status": "invalid",
                    "error": f"proof_command structure mismatch for {pid}: expected pytest command with {tnode}",
                }

            efail = param.get("expected_failure_class", "")
            if efail != expected_fail_class:
                return {
                    "is_valid": False,
                    "status": "invalid",
                    "error": f"expected_failure_class mismatch for {pid}: expected {expected_fail_class}, got {efail}",
                }

            eobs = param.get("expected_observable")
            if not isinstance(eobs, dict):
                return {"is_valid": False, "status": "invalid", "error": f"Missing or invalid expected_observable for {pid}"}

            required_obs = {
                "roadmap_criterion_id": crit_id,
                "roadmap_criterion_sha256": expected_sha,
                "rule_id": pid,
                "channel": "pytest_junit_call_property",
                "target_nodeid": tnode,
                "result_code": expected_res_code,
            }
            if eobs != required_obs:
                return {
                    "is_valid": False,
                    "status": "invalid",
                    "error": f"expected_observable mismatch for {pid}: expected {required_obs}, got {eobs}",
                }

    if len(all_observed_parameters) != 9:
        return {"is_valid": False, "status": "invalid", "error": f"Expected 9 total parameters, got {len(all_observed_parameters)}"}

    return {
        "is_valid": True,
        "status": "valid",
        "criteria_count": 8,
        "parameters_count": 9,
    }


def _run_and_assert(group_name: str) -> int:
    if group_name not in GROUPS:
        print(f"Error: Unknown group '{group_name}'", file=sys.stderr)
        return 1
    expected_nodeids = GROUPS[group_name]
    repo = _repo_root()

    xml_path = repo / f".phase-loop/evidence/PROOFGATE/junit_{group_name}.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "pytest",
        *expected_nodeids,
        "-o",
        "junit_family=legacy",
        f"--junitxml={xml_path}",
        "-rxX",
        "-q",
    ]
    env = {
        **os.environ,
        "PYTHONPATH": f"{repo}/phase-loop-runtime/src:{repo}/phase-loop-runtime/tests",
    }
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env)

    pytest_output = proc.stdout + proc.stderr

    res = verify_proofgate_content_tdd_junit(
        xml_path,
        expected_nodeids=expected_nodeids,
        group_name=group_name,
        pytest_output=pytest_output,
        returncode=proc.returncode,
    )
    if not res["ok"]:
        print(f"Error: {res['error']}", file=sys.stderr)
        return 1

    print(f"run-and-assert passed for group '{group_name}': {res['passed']} passed, 0 skipped, 0 failed.")
    return 0


def _record_red(group_name: str, landing_ref: str = "HEAD") -> int:
    if group_name not in GROUPS:
        print(f"Error: Unknown group '{group_name}'", file=sys.stderr)
        return 1
    expected_nodeids = GROUPS[group_name]
    repo = _repo_root()

    evidence_dir = repo / ".phase-loop/evidence/PROOFGATE"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    group_cmd = ["pytest", *expected_nodeids, "-q"]
    env = {
        **os.environ,
        "PHASE_LOOP_TDD_EXPECT_PROOFGATE": "1",
        "PYTHONPATH": f"{repo}/phase-loop-runtime/src:{repo}/phase-loop-runtime/tests",
    }
    proc_group = subprocess.run(group_cmd, cwd=repo, capture_output=True, text=True, env=env)
    if proc_group.returncode != 1:
        print(f"Error: Expected group RED pytest command to exit with 1, got {proc_group.returncode}", file=sys.stderr)
        return 1

    group_output = proc_group.stdout + proc_group.stderr
    if RED_ANCHOR_MARKER not in group_output:
        print("Error: Group RED output missing required RED_ANCHOR_MARKER", file=sys.stderr)
        return 1

    for nodeid in expected_nodeids:
        case_id = RED_CASES_BY_NODEID[nodeid][1]
        expected_marker = f"PROOFGATE_RED::{case_id}"
        cnt = group_output.count(expected_marker)
        if cnt != 1:
            print(f"Error: Group RED output for {nodeid} expected marker {expected_marker} exactly once, got {cnt}", file=sys.stderr)
            return 1

    canonical_nodes, canonical_cmd, all_freeze_support_paths = _canonical_red_inputs()
    proc_canonical = subprocess.run(canonical_cmd, cwd=repo, capture_output=True, text=True, env=env)
    if proc_canonical.returncode != 1:
        print(f"Error: Expected canonical whole-freeze RED pytest command to exit with 1, got {proc_canonical.returncode}", file=sys.stderr)
        return 1

    canonical_output = proc_canonical.stdout + proc_canonical.stderr
    if RED_ANCHOR_MARKER not in canonical_output:
        print("Error: Canonical RED output missing required RED_ANCHOR_MARKER", file=sys.stderr)
        return 1

    for nodeid in canonical_nodes:
        case_id = RED_CASES_BY_NODEID[nodeid][1]
        expected_marker = f"PROOFGATE_RED::{case_id}"
        cnt = canonical_output.count(expected_marker)
        if cnt != 1:
            print(f"Error: Canonical RED output for {nodeid} expected marker {expected_marker} exactly once, got {cnt}", file=sys.stderr)
            return 1

    stdout_path = evidence_dir / "content-tdd-receipt.red.stdout.log"
    stderr_path = evidence_dir / "content-tdd-receipt.red.stderr.log"
    stdout_path.write_text(proc_canonical.stdout, encoding="utf-8")
    stderr_path.write_text(proc_canonical.stderr, encoding="utf-8")

    receipt_path = evidence_dir / "content-tdd-receipt.json"
    prior_activation = os.environ.get("PHASE_LOOP_TDD_EXPECT_PROOFGATE")
    os.environ["PHASE_LOOP_TDD_EXPECT_PROOFGATE"] = "1"
    try:
        record_content_tdd_receipt(
            repo=repo,
            test_glob="phase-loop-runtime/tests/test_skills_bundle_drift.py",
            red_command=" ".join(canonical_cmd),
            landing_ref=landing_ref,
            out=receipt_path,
            support_paths=all_freeze_support_paths,
        )
    except Exception as exc:
        print(f"Error recording content TDD receipt: {exc}", file=sys.stderr)
        return 1
    finally:
        if prior_activation is None:
            os.environ.pop("PHASE_LOOP_TDD_EXPECT_PROOFGATE", None)
        else:
            os.environ["PHASE_LOOP_TDD_EXPECT_PROOFGATE"] = prior_activation

    print(f"record-red passed for group '{group_name}': exit code 1, markers verified, canonical receipt recorded.")
    return 0


EXPECTED_FREEZE_FILES: tuple[str, ...] = (
    "phase-loop-runtime/tests/fixtures/proofgate/v10-proofgate-mutations.json",
    "phase-loop-runtime/tests/proofgate_content_tdd_adapter.py",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py",
    "phase-loop-runtime/tests/test_skills_canon_parity.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_goal_coverage.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py",
    "phase-loop-runtime/tests/test_verification_evidence.py",
)


def _canonical_red_inputs() -> tuple[tuple[str, ...], list[str], list[str]]:
    canonical_nodes = tuple(sorted(_LANE_UNION))
    return canonical_nodes, ["pytest", *canonical_nodes, "-q"], list(EXPECTED_FREEZE_FILES)


def _validate_red_marker_output(output: str, canonical_nodes: tuple[str, ...]) -> str | None:
    if output.count(RED_ANCHOR_MARKER) != len(canonical_nodes):
        return f"expected {len(canonical_nodes)} RED anchor markers"
    for nodeid in canonical_nodes:
        marker = f"PROOFGATE_RED::{RED_CASES_BY_NODEID[nodeid][1]}"
        if output.count(marker) != 1:
            return f"expected typed marker {marker} exactly once"
    return None


def _verify_cmd(repo_path: Path, landing_ref: str, identity: str, receipt_path: Path) -> int:
    repo = repo_path.resolve()
    if not receipt_path.is_absolute():
        receipt_path = repo / receipt_path
    if not receipt_path.exists():
        print(f"Error: Receipt file not found: {receipt_path}", file=sys.stderr)
        return 1

    try:
        declared_commit = select_declared_commit(repo, landing_ref, identity)
    except Exception as exc:
        print(f"Error: declared identity '{identity}' not found on '{landing_ref}': {exc}", file=sys.stderr)
        return 1

    try:
        receipt = verify_content_tdd_receipt(receipt_path=receipt_path, repo=repo)
    except Exception as exc:
        print(f"Error verifying content TDD receipt: {exc}", file=sys.stderr)
        return 1

    if receipt.landing_commit != declared_commit:
        print(
            f"Error: Receipt landing commit '{receipt.landing_commit}' does not match declared commit '{declared_commit}'",
            file=sys.stderr,
        )
        return 1

    canonical_nodes = tuple(sorted(_LANE_UNION))
    try:
        red_output = (
            (receipt_path.parent / receipt.red_stdout_path).read_text(encoding="utf-8")
            + (receipt_path.parent / receipt.red_stderr_path).read_text(encoding="utf-8")
        )
    except OSError as exc:
        print(f"Error reading retained RED logs: {exc}", file=sys.stderr)
        return 1
    marker_error = _validate_red_marker_output(red_output, canonical_nodes)
    if marker_error is not None:
        print(f"Error: Retained RED marker verification failed: {marker_error}", file=sys.stderr)
        return 1

    norm_receipt_nodeids = {
        n if n.startswith("phase-loop-runtime/") else f"phase-loop-runtime/{n}"
        for n in receipt.red_nodeids
    }
    for nodeid in canonical_nodes:
        norm_nodeid = nodeid if nodeid.startswith("phase-loop-runtime/") else f"phase-loop-runtime/{nodeid}"
        if norm_nodeid not in norm_receipt_nodeids:
            print(f"Error: Receipt missing canonical node {nodeid}", file=sys.stderr)
            return 1

    receipt_paths = tuple(sorted(path for path, _sha in receipt.test_files))
    if receipt_paths != EXPECTED_FREEZE_FILES:
        print(
            f"Error: Receipt test_files inventory mismatch!\nExpected: {EXPECTED_FREEZE_FILES}\nGot: {receipt_paths}",
            file=sys.stderr,
        )
        return 1

    for rel_path, sha256_in_receipt in receipt.test_files:
        proc = subprocess.run(
            ["git", "show", f"{declared_commit}:{rel_path}"],
            cwd=repo,
            capture_output=True,
        )
        if proc.returncode != 0:
            print(f"Error: File {rel_path} not found in landing commit {declared_commit}", file=sys.stderr)
            return 1
        git_sha256 = hashlib.sha256(proc.stdout).hexdigest()
        if git_sha256 != sha256_in_receipt:
            print(
                f"Error: File {rel_path} sha256 mismatch between receipt ({sha256_in_receipt}) and landing commit ({git_sha256})",
                file=sys.stderr,
            )
            return 1

    print(json.dumps({"ok": receipt.ok, "landing_commit": receipt.landing_commit}, sort_keys=True))
    return 0


EXPECTED_OWNED_UNION: set[str] = {
    "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
    "phase-loop-runtime/tests/proofgate_content_tdd_adapter.py",
    "phase-loop-runtime/tests/test_verification_evidence.py",
    "phase-loop-runtime/tests/test_convergence_broker_revocation_race.py",
    "phase-loop-runtime/tests/fixtures/proofgate/v10-proofgate-mutations.json",
    ".phase-loop/evidence/PROOFGATE/content-tdd-receipt.json",
    ".phase-loop/evidence/PROOFGATE/content-tdd-receipt.red.stdout.log",
    ".phase-loop/evidence/PROOFGATE/content-tdd-receipt.red.stderr.log",
    "phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py",
    "phase-loop-runtime/src/phase_loop_runtime/runner.py",
    "skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py",
    "phase-loop-runtime/tests/test_acceptance_falsifier_contract.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_goal_coverage.py",
    "phase-loop-runtime/tests/test_validate_plan_doc_proofgate.py",
    "phase-loop-runtime/tests/test_skills_canon_parity.py",
    "phase-loop-runtime/tests/test_skills_bundle_drift.py",
    "skills-src/claude/claude-plan-phase/SKILL.md",
    "skills-src/codex/codex-plan-phase/SKILL.md",
    "skills-src/gemini/gemini-plan-phase/SKILL.md",
    "skills-src/opencode/opencode-plan-phase/SKILL.md",
    "phase-loop-skills/plan-phase/**",
    "phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-plan-phase/**",
    ".phase-loop/evidence/PROOFGATE/spec-delta-closeout.json",
}


def _is_path_allowed_by_owned_union(file_path: str, owned_union: set[str]) -> bool:
    if file_path in owned_union:
        return True
    for pattern in owned_union:
        if "*" in pattern or "?" in pattern or "[" in pattern:
            if _translate_glob_to_regex(pattern).fullmatch(file_path):
                return True
    return False


def _committed_paths_in_range(repo: Path, start_ref: str, end_ref: str) -> set[str]:
    proc = subprocess.run(
        ["git", "log", "--format=", "--name-only", "--no-renames", f"{start_ref}..{end_ref}"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def _verify_scope(
    repo_path: Path,
    landing_remote: str,
    landing_branch: str,
    identity: str,
    head_ref: str,
    plan_path: Path,
) -> int:
    repo = repo_path.resolve()
    plan_full_path = repo / plan_path
    if not plan_full_path.exists() or not plan_full_path.is_file():
        print(f"Error: Phase plan path does not exist: {plan_path}", file=sys.stderr)
        return 1

    try:
        from phase_loop_runtime.plan_ir import parse_phase_plan_ir
        plan_ir = parse_phase_plan_ir(plan_full_path)
    except Exception as exc:
        print(f"Error: Failed to parse plan IR from {plan_path}: {exc}", file=sys.stderr)
        return 1

    if plan_ir.diagnostics:
        print(f"Error: Plan IR diagnostics found in {plan_path}: {plan_ir.diagnostics}", file=sys.stderr)
        return 1

    parsed_owned = set()
    for lane in plan_ir.lanes:
        for owned in getattr(lane, "owned_files", ()):
            parsed_owned.add(owned)

    if parsed_owned != EXPECTED_OWNED_UNION:
        print(
            f"Error: Plan owned-file union mismatch!\nExpected: {sorted(EXPECTED_OWNED_UNION)}\nGot: {sorted(parsed_owned)}",
            file=sys.stderr,
        )
        return 1

    if not landing_remote or not landing_branch or ".." in landing_remote or ".." in landing_branch:
        print(f"Error: Invalid remote or branch name: {landing_remote}/{landing_branch}", file=sys.stderr)
        return 1

    remote_branch = f"{landing_remote}/{landing_branch}"
    try:
        landing_commit = select_declared_commit(repo, head_ref, identity)
    except Exception as exc:
        print(f"Error: declared identity '{identity}' not found on '{head_ref}': {exc}", file=sys.stderr)
        return 1

    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", landing_commit, head_ref],
        cwd=repo,
        capture_output=True,
    )
    if ancestry.returncode != 0:
        print(f"Error: landing_commit {landing_commit} is not an ancestor of {head_ref}", file=sys.stderr)
        return 1

    try:
        all_changed = _committed_paths_in_range(repo, landing_commit, head_ref)
        all_changed.update(_committed_paths_in_range(repo, remote_branch, head_ref))
    except RuntimeError as exc:
        print(f"Error: git history scan failed: {exc}", file=sys.stderr)
        return 1

    out_of_scope = [f for f in sorted(all_changed) if not _is_path_allowed_by_owned_union(f, parsed_owned)]
    if out_of_scope:
        print(f"Error: Scope verification failed! Changed files outside allowed set: {out_of_scope}", file=sys.stderr)
        return 1

    print(f"verify-scope passed: {len(all_changed)} changed files, all within parsed plan owned-file union.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PROOFGATE Content TDD Adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_assert = subparsers.add_parser("run-and-assert")
    run_assert.add_argument("--group", required=True, help="Group name: sl1, sl0, sl2, ec-1..ec-7, ec-0")

    rec_red = subparsers.add_parser("record-red")
    rec_red.add_argument("--group", required=True, help="Group name")
    rec_red.add_argument("--landing-ref", default="HEAD", help="Landing ref for content TDD receipt")

    ver = subparsers.add_parser("verify")
    ver.add_argument("--repo", type=Path, default=Path("."))
    ver.add_argument("--landing-ref", default="HEAD")
    ver.add_argument("--identity", default="proofgate-tests-freeze-amendment-1")
    ver.add_argument("--receipt", type=Path, default=Path(".phase-loop/evidence/PROOFGATE/content-tdd-receipt.json"))

    ver_scope = subparsers.add_parser("verify-scope")
    ver_scope.add_argument("--repo", type=Path, default=Path("."))
    ver_scope.add_argument("--landing-remote", default="origin")
    ver_scope.add_argument("--landing-branch", default="main")
    ver_scope.add_argument("--identity", default="proofgate-tests-freeze-amendment-1")
    ver_scope.add_argument("--head", default="HEAD")
    ver_scope.add_argument("--plan", type=Path, default=Path("plans/phase-plan-v10-PROOFGATE.md"))

    args = parser.parse_args(argv)

    if args.command == "run-and-assert":
        return _run_and_assert(args.group)
    elif args.command == "record-red":
        return _record_red(args.group, args.landing_ref)
    elif args.command == "verify":
        return _verify_cmd(args.repo, args.landing_ref, args.identity, args.receipt)
    elif args.command == "verify-scope":
        return _verify_scope(args.repo, args.landing_remote, args.landing_branch, args.identity, args.head, args.plan)

    return 0


if __name__ == "__main__":
    sys.exit(main())
