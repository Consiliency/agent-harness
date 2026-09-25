"""Content-bound RED receipt for the EXECFIND frozen test lane."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, Sequence

from phase_loop_runtime.tdd_receipts import (
    RED_ANCHOR_MARKER,
    record_content_tdd_receipt,
    verify_content_tdd_receipt,
)


ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_EXECFIND"
STRICT_GREEN_ENV = "PHASE_LOOP_TDD_REQUIRE_EXECFIND_GREEN"
UNSOUND = "EXECFIND_RECORD_UNSOUND"
TEST_DIR = "phase-loop-runtime/tests"
FROZEN_TEST_FILES = (
    f"{TEST_DIR}/test_execfind_falsifier.py",
    f"{TEST_DIR}/test_governed_review.py",
    f"{TEST_DIR}/test_advisor_board_golden.py",
)
FROZEN_SUPPORT_FILES = (
    f"{TEST_DIR}/execfind_content_tdd_adapter.py",
    f"{TEST_DIR}/data/execfind_falsifier_attachment_v1.golden.json",
)
FROZEN_FILES = frozenset((*FROZEN_TEST_FILES, *FROZEN_SUPPORT_FILES))
EXECFIND_CASES = (
    "grammar", "parser_reject_outside_tests", "parser_reject_modify_existing",
    "parser_reject_no_nodeid", "parser_reject_foreign_nodeid",
    "parser_reject_double_claim", "attachment_byte_neutral",
    "attachment_matches_frozen_contract", "outcome_vocabulary", "apply_failed",
    "red_on_head", "green_on_head", "node_missing", "reviewed_sha_mismatch_error",
    "bound_expiry_error",
    "no_network_no_credentials", "staged_tree_only", "staged_overlay_drift_error",
    "staged_untracked_extra_error", "staged_ignored_extra_error",
    "staged_symlink_retarget_error", "staged_exec_bit_drift_error",
    "only_named_node_runs",
    "seat_tool_attempt_refused", "authorization_identity", "brief_teaches_form",
    "inline_fixture_artifact_ref", "brokered_text_only", "prompt_over_cap_refused",
)
GOVERNED_CASES = (
    "finding_bound", "finding_reviewed_sha_mismatch", "finding_unbound", "finding_receipt",
    "finding_receipt_digest_unresolved", "falsifier_count_bound", "finding_prose",
    "degraded_leg_whole_code",
    "falsifier_policy_optional", "falsifier_policy_required_refuses_prose",
)
EXPECTED_RED_CASES = (*EXECFIND_CASES, *GOVERNED_CASES)
EXPECTED_RED_NODES = frozenset(
    f"{FROZEN_TEST_FILES[0]}::test_{case}" for case in EXECFIND_CASES
) | frozenset(
    f"{FROZEN_TEST_FILES[1]}::ExecfindFindingTests::test_{case}" for case in GOVERNED_CASES
)
EXPECTED_GREEN_NODES = frozenset({
    "phase-loop-runtime/tests/test_advisor_board_golden.py::ConcurrencyProofTests::test_invoke_board_max_concurrency_1_is_sequential",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::ConcurrencyProofTests::test_invoke_board_runs_seats_concurrently",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::ConcurrencyProofTests::test_invoke_panel_max_concurrency_1_is_sequential",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::ConcurrencyProofTests::test_invoke_panel_runs_legs_concurrently",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::ConcurrencyProofTests::test_max_concurrency_1_preserves_order_and_results",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::ExecfindGoldenBytesTest::test_attached_falsifier_leaves_leg_golden_bytes_unchanged",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenApiStabilityTests::test_default_board_yields_four_legs_in_board_order",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenApiStabilityTests::test_invoke_board_default_matches_invoke_panel_usable_semantics",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenPerLegLaunchTests::test_claude_argv_and_env_equal_legacy",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenPerLegLaunchTests::test_codex_argv_env_and_timeout_equal_legacy",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenPerLegLaunchTests::test_gemini_default_board_and_legacy_panel_share_flash_invocation",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenPerLegLaunchTests::test_per_leg_timeout_is_a_pure_function_of_the_staged_artifact",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenWholeBoardBehaviorTests::test_every_leg_launched_once_and_results_in_order_both_paths",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenWholeBoardBehaviorTests::test_failure_semantics_empty_on_ok_becomes_empty_both_paths",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenWholeBoardBehaviorTests::test_failure_semantics_raise_degrades_both_paths",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenWholeBoardBehaviorTests::test_failure_semantics_unknown_status_degrades_both_paths",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenWholeBoardBehaviorTests::test_mixed_per_leg_outcomes_classify_identically",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenWholeBoardBehaviorTests::test_ok_results_are_byte_identical_except_seat_key",
    "phase-loop-runtime/tests/test_advisor_board_golden.py::GoldenWholeBoardBehaviorTests::test_seat_key_is_the_sole_documented_delta",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_every_expected_case_ran",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_frozen_inventory_exact",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_importerror_not_capability_absence",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_marker_exact_match_only",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_missing_capability_strict_green_fails",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_node_launch_guard_detects_attempt",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_red_output_digest_golden",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_rejected_recording_no_receipt",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_unexpected_pass_refused",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_unrelated_exception_propagates",
    "phase-loop-runtime/tests/test_execfind_falsifier.py::test_verify_rescans_red_log",
    "phase-loop-runtime/tests/test_governed_review.py::AutonomousShortCircuitTest::test_autonomous_makes_zero_panel_calls",
    "phase-loop-runtime/tests/test_governed_review.py::GovernedGateTest::test_block_finding_holds_promotion",
    "phase-loop-runtime/tests/test_governed_review.py::GovernedGateTest::test_deferred_claude_leg_is_a_warn_never_a_block",
    "phase-loop-runtime/tests/test_governed_review.py::GovernedGateTest::test_deferred_leg_does_not_mask_a_real_disagree",
    "phase-loop-runtime/tests/test_governed_review.py::GovernedGateTest::test_no_block_promotes_with_nits_recorded",
    "phase-loop-runtime/tests/test_governed_review.py::GovernedGateTest::test_rejected_reason_as_text_would_block",
    "phase-loop-runtime/tests/test_governed_review.py::GovernedGateTest::test_repo_dir_is_forwarded_to_panel_invoker",
    "phase-loop-runtime/tests/test_governed_review.py::ReviewerPoolTest::test_author_vendor_mapping",
    "phase-loop-runtime/tests/test_governed_review.py::ReviewerPoolTest::test_author_vendor_only_degrades",
    "phase-loop-runtime/tests/test_governed_review.py::ReviewerPoolTest::test_no_disjoint_reviewer_blocks_fail_closed",
    "phase-loop-runtime/tests/test_governed_review.py::ReviewerPoolTest::test_pool_excludes_author_vendor",
    "phase-loop-runtime/tests/test_governed_review.py::ReviewerPoolTest::test_zero_authed_degrades",
    "phase-loop-runtime/tests/test_governed_review.py::RunModeTest::test_closeout_context_run_mode_defaults_autonomous",
    "phase-loop-runtime/tests/test_governed_review.py::RunModeTest::test_default_is_autonomous",
    "phase-loop-runtime/tests/test_governed_review.py::VerdictClassifierTest::test_approving_phrasings_do_not_block",
    "phase-loop-runtime/tests/test_governed_review.py::VerdictClassifierTest::test_real_block_verdicts_block",
})
EXPECTED_FROZEN_NODES = EXPECTED_RED_NODES | EXPECTED_GREEN_NODES
RECEIPT_PATH = ".phase-loop/evidence/EXECFIND/content-tdd-receipt.json"
RED_COMMAND = (
    f"env {ACTIVATION_ENV}=1 "
    f"PYTHONPATH=phase-loop-runtime/src{os.pathsep}phase-loop-runtime/tests "
    "python3 -m pytest -q --tb=line --color=no -p no:cacheprovider "
    + " ".join(FROZEN_TEST_FILES)
)
_FAILED = re.compile(r"(?m)^FAILED\s+(\S+::\S+)")


class MissingCapability(AssertionError):
    """Only an absent pre-implementation EXECFIND interface may become RED."""


def require_module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            raise MissingCapability(f"module {name} absent") from exc
        raise


def require_attr(obj: object, name: str):
    if not hasattr(obj, name):
        raise MissingCapability(f"{name} absent")
    return getattr(obj, name)


def run_execfind_contract(case: str, check: Callable[[], None]) -> None:
    if case not in EXPECTED_RED_CASES:
        raise ValueError(f"undeclared EXECFIND case: {case}")
    if os.environ.get(ACTIVATION_ENV) == "1":
        try:
            check()
        except MissingCapability as exc:
            raise AssertionError(f"{RED_ANCHOR_MARKER} EXECFIND_RED::{case}") from exc
        raise AssertionError(f"{UNSOUND}::{case}: contract unexpectedly passed")
    try:
        check()
    except MissingCapability as exc:
        if os.environ.get(STRICT_GREEN_ENV) == "1":
            raise
        import pytest

        pytest.skip(f"EXECFIND capability unimplemented for {case}: {exc}")


def scan_red_output(output: str) -> str | None:
    if UNSOUND in output or "XPASS" in output or "unexpected pass" in output.lower():
        return "unexpected pass or already-green contract"
    markers = Counter(token for token in output.split() if "EXECFIND_RED::" in token)
    expected_markers = Counter({f"EXECFIND_RED::{case}": 1 for case in EXPECTED_RED_CASES})
    if markers != expected_markers:
        return "RED markers are missing, repeated, or unexpected"
    failed = frozenset(_FAILED.findall(output))
    if failed != EXPECTED_RED_NODES:
        return "executed failing nodes differ from the frozen corpus"
    summary = re.search(r"(?m)^\s*(\d+) failed\b", output)
    if summary is None or int(summary.group(1)) != len(EXPECTED_RED_NODES):
        return "RED failure count differs from the frozen corpus"
    if re.search(r"\b(?:error|errors|skipped|deselected|xfailed|xpassed)\b", output.split("short test summary info")[-1], re.I):
        return "run contains an error, skip, deselection, or xpass"
    return None


def scan_inventory(receipt: object) -> str | None:
    paths = {path for path, _digest in receipt.test_files}
    if paths != FROZEN_FILES or len(receipt.test_files) != len(FROZEN_FILES):
        return "receipt test_files inventory differs from the frozen corpus"
    # pytest --collect-only reports paths relative to its configured rootdir
    # (phase-loop-runtime), while failure summaries use repo-relative paths.
    nodes = [
        f"phase-loop-runtime/{node}" if node.startswith("tests/") else node
        for node in receipt.red_nodeids
    ]
    if len(nodes) != len(EXPECTED_FROZEN_NODES) or set(nodes) != EXPECTED_FROZEN_NODES:
        return "receipt node ids differ from the frozen corpus"
    return None


def _bind_landing(repo: Path, receipt_path: Path, landing_ref: str) -> str | None:
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    for item in payload["test_files"]:
        path = item["path"]
        shown = subprocess.run(
            ["git", "show", f"{landing_ref}:{path}"], cwd=repo, capture_output=True,
        )
        if shown.returncode or hashlib.sha256(shown.stdout).hexdigest() != item["sha256"]:
            return f"requested landing changes frozen file {path}"
    return None


def _read_red_output(parent: Path, receipt: object) -> str:
    return (
        (parent / receipt.red_stdout_path).read_text(encoding="utf-8")
        + (parent / receipt.red_stderr_path).read_text(encoding="utf-8")
    )


def record_red(repo: Path, landing_ref: str, receipt_path: Path) -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="execfind-red-") as scratch:
            staged = Path(scratch) / receipt_path.name
            receipt = record_content_tdd_receipt(
                repo=repo, test_glob=FROZEN_TEST_FILES[0], red_command=RED_COMMAND,
                landing_ref=landing_ref, out=staged,
                support_paths=(*FROZEN_TEST_FILES[1:], *FROZEN_SUPPORT_FILES),
            )
            error = scan_inventory(receipt) or scan_red_output(_read_red_output(staged.parent, receipt))
            if error:
                print(f"execfind record-red refused: {error}", file=sys.stderr)
                return 1
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            for name in (staged.name, receipt.red_stdout_path, receipt.red_stderr_path):
                shutil.copyfile(staged.parent / name, receipt_path.parent / name)
    except Exception as exc:
        print(f"execfind record-red failed: {exc}", file=sys.stderr)
        return 1
    print(f"execfind record-red: {receipt_path}")
    return 0


def verify(repo: Path, landing_ref: str | None, receipt_path: Path) -> int:
    try:
        receipt = verify_content_tdd_receipt(receipt_path=receipt_path, repo=repo)
        error = scan_inventory(receipt) or scan_red_output(_read_red_output(receipt_path.parent, receipt))
        if error is None and landing_ref is not None:
            error = _bind_landing(repo, receipt_path, landing_ref)
    except Exception as exc:
        print(f"execfind verify failed: {exc}", file=sys.stderr)
        return 2
    if error:
        print(f"execfind verify refused: {error}", file=sys.stderr)
        return 2
    print(f"execfind verify: ok landing_ref={landing_ref or receipt.landing_commit}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("record-red", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--landing-ref", default="HEAD" if name == "record-red" else None)
        command.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    receipt = args.receipt if args.receipt.is_absolute() else repo / args.receipt
    if args.command == "record-red":
        return record_red(repo, args.landing_ref, receipt)
    return verify(repo, args.landing_ref, receipt)


if __name__ == "__main__":
    raise SystemExit(main())
