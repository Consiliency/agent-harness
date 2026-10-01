"""RATIFY's tests-first receipt; missing capabilities are not landing evidence."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import importlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import subprocess
from xml.etree import ElementTree

from phase_loop_runtime.tdd_receipts import (
    RED_ANCHOR_MARKER, record_content_tdd_receipt, verify_content_tdd_receipt,
)

PHASE_CASES = (
    "receipt_partition", "receipt_partition_scope_item_requires_ruling",
    "receipt_partition_missing_or_stale_ruling", "receipt_partition_native_deferral",
    "receipt_partition_foreign_attachment", "ruling_classes",
    "receipt_partition_bound_findings_excluded", "ruling_classes_binding",
    "ruling_classes_legacy_compatibility", "ruling_classes_changing_without_row",
    "ruling_classes_real_consumers", "human_tiers", "human_tiers_universal_triggers",
    "human_tiers_invalid_overrides", "skill_reconciliation",
)
LEDGER_CASES = (
    "closed_vocabulary", "empty_ledger", "ancestor_prefix", "second_parent_prefix",
    "reviewed_sha_ancestry", "duplicate_and_foreign_rows", "pending_and_resolved_fold",
    "unguarded_same_class", "same_class_multirow", "guard_provenance",
    "unavailable_history",
)
CONTROL_CASES = (
    "legacy_grammar_control", "old_policy_constructor_control",
    "unknown_capability_strict_failure", "unexpected_pass_refused",
    "unrelated_exception_propagates", "importerror_not_capability_absence",
    "red_inventory_exact", "red_marker_exact", "red_skips_refused",
    "red_xpass_refused", "landing_junit_zero_skips", "touch_shape_owner_serialization",
    "rejected_recording_no_receipt", "verify_rescans_red_log",
    "receipt_binding_control",
)
TEST_DIR = "phase-loop-runtime/tests"
FROZEN_TEST_FILES = tuple(f"{TEST_DIR}/{name}" for name in (
    "test_ratify_phase.py", "test_ruling_ledger.py", "test_ratify_landed.py",
))
FROZEN_FILES = frozenset((*FROZEN_TEST_FILES, f"{TEST_DIR}/ratify_content_tdd_adapter.py"))
EXPECTED_RED_NODES = frozenset(
    [f"{FROZEN_TEST_FILES[0]}::test_{case}" for case in PHASE_CASES]
    + [f"{FROZEN_TEST_FILES[1]}::test_{case}" for case in LEDGER_CASES]
    + [f"{FROZEN_TEST_FILES[2]}::test_no_ratify_contract_skips_as_unimplemented"]
)
EXPECTED_GREEN_NODES = frozenset(
    f"{FROZEN_TEST_FILES[0]}::test_{case}" for case in CONTROL_CASES
)
EXPECTED_MARKERS = frozenset((*PHASE_CASES, *LEDGER_CASES, "landed_no_skips"))
RECEIPT_PATH = ".phase-loop/evidence/RATIFY/content-tdd-receipt.json"
LANDING_JUNIT = ".phase-loop/evidence/RATIFY/landing-green.xml"
RED_COMMAND = (
    "env PHASE_LOOP_TDD_EXPECT_RATIFY=1 "
    "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests "
    "python3 -m pytest -q -rA --tb=line --color=no -p no:cacheprovider "
    + " ".join(FROZEN_TEST_FILES)
)


class MissingCapability(AssertionError):
    pass


def require_module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            raise MissingCapability(f"module {name} absent") from exc
        raise


def require_attr(obj, name):
    if not hasattr(obj, name):
        raise MissingCapability(f"{name} absent")
    return getattr(obj, name)


def capability(lane):
    if lane == "ledger":
        module = require_module("phase_loop_runtime.ruling_ledger")
        marker = "RATIFY_LEDGER_CAPABILITY_VERSION"
    elif lane == "resolution":
        module = require_module("phase_loop_runtime.panel_invoker")
        marker = "RATIFY_RESOLUTION_CAPABILITY_VERSION"
    else:
        raise ValueError(f"unknown RATIFY lane {lane}")
    value = require_attr(module, marker)
    if type(value) is not int or value != 1:
        raise MissingCapability(f"{marker} does not implement version 1")
    return module


def run_contract(case, lane, check):
    if case not in EXPECTED_MARKERS:
        raise ValueError(f"undeclared RATIFY case {case}")
    activated = os.environ.get("PHASE_LOOP_TDD_EXPECT_RATIFY") == "1"
    strict = any(os.environ.get(key) == "1" for key in (
        "PHASE_LOOP_TDD_REQUIRE_RATIFY_GREEN",
        f"PHASE_LOOP_TDD_REQUIRE_RATIFY_{lane.upper()}_GREEN",
    ))
    try:
        capability(lane)
        check()
    except MissingCapability as exc:
        if activated:
            raise AssertionError(f"{RED_ANCHOR_MARKER} RATIFY_RED::{case}") from exc
        if strict:
            raise
        import pytest
        pytest.skip(f"RATIFY capability unimplemented for {case}: {exc}")
    if activated:
        raise AssertionError(f"RATIFY_RECORD_UNSOUND::{case}: contract unexpectedly passed")


def normalize_node(node):
    return f"phase-loop-runtime/{node}" if node.startswith("tests/") else node


def scan_inventory(receipt):
    files = [path for path, _digest in receipt.test_files]
    nodes = [normalize_node(node) for node in receipt.red_nodeids]
    if len(files) != len(FROZEN_FILES) or set(files) != FROZEN_FILES:
        return "frozen file inventory differs"
    if len(nodes) != len(EXPECTED_RED_NODES | EXPECTED_GREEN_NODES) or set(nodes) != EXPECTED_RED_NODES | EXPECTED_GREEN_NODES:
        return "frozen node inventory differs"
    return None


def scan_red_output(output):
    if "RATIFY_RECORD_UNSOUND" in output or re.search(r"\b(?:XPASS|XFAIL|SKIPPED|ERROR)\b", output):
        return "unexpected pass, skip or error in RED evidence"
    tokens = re.findall(r"RATIFY_RED::([A-Za-z0-9_]+)\s*$", output, re.M)
    anchored = re.findall(re.escape(RED_ANCHOR_MARKER) + r" RATIFY_RED::([A-Za-z0-9_]+)\s*$", output, re.M)
    if Counter(tokens) != Counter(anchored) or Counter(tokens) != Counter(EXPECTED_MARKERS):
        return "missing, duplicate or malformed RED marker"
    failed = [normalize_node(node) for node in re.findall(r"(?m)^FAILED\s+(\S+::\S+)", output)]
    passed = [normalize_node(node) for node in re.findall(r"(?m)^PASSED\s+(\S+::\S+)", output)]
    if len(failed) != len(EXPECTED_RED_NODES) or set(failed) != EXPECTED_RED_NODES:
        return "failing node inventory differs"
    if len(passed) != len(EXPECTED_GREEN_NODES) or set(passed) != EXPECTED_GREEN_NODES:
        return "restored control inventory differs"
    return None


def scan_landing_junit(path):
    try:
        cases = list(ElementTree.parse(path).getroot().iter("testcase"))
    except (OSError, ElementTree.ParseError) as exc:
        return f"landing JUnit unavailable: {exc}"
    # Only this corpus is measured; unrelated tests may legitimately skip.
    ratify = [case for case in cases if any(
        Path(file).stem in case.get("classname", "") for file in FROZEN_TEST_FILES
    )]
    names = [case.get("name") for case in ratify]
    expected = {node.rsplit("::", 1)[1] for node in EXPECTED_RED_NODES | EXPECTED_GREEN_NODES}
    if len(names) != len(expected) or set(names) != expected:
        return "landing JUnit does not cover the frozen corpus exactly"
    if any(any(case.find(tag) is not None for tag in ("skipped", "failure", "error")) for case in ratify):
        return "landing RATIFY node failed, errored or skipped"
    return None


def check_touch_shape(repo, before, after, allowed_seams, unresolved_owners):
    """Measure actual Git line rewrites; this never grants writer ownership."""
    if unresolved_owners:
        return "unresolved owner landing"
    for path, names in allowed_seams.items():
        def source(ref):
            return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo,
                                  check=True, capture_output=True, text=True).stdout
        old, new = source(before), source(after)
        spans = set()
        for node in ast.parse(old).body:
            if getattr(node, "name", None) in names:
                start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", ())])
                spans.update(range(start - 1, node.end_lineno))
        for action, start, end, _new_start, _new_end in SequenceMatcher(
            None, old.splitlines(), new.splitlines(), autojunk=False
        ).get_opcodes():
            if action in ("delete", "replace") and not set(range(start, end)).issubset(spans):
                return f"rewrite outside named additive seam: {path}"
    return None


def verify(repo, landing_ref, receipt_path, *, strict=False):
    receipt = verify_content_tdd_receipt(receipt_path=receipt_path, repo=repo)
    error = scan_inventory(receipt)
    output = "".join((receipt_path.parent / rel).read_text(encoding="utf-8")
                     for rel in (receipt.red_stdout_path, receipt.red_stderr_path))
    error = error or scan_red_output(output)
    if error:
        raise ValueError(error)
    for path, digest in receipt.test_files:
        shown = subprocess.run(["git", "show", f"{landing_ref}:{path}"], cwd=repo,
                               check=True, capture_output=True).stdout
        if hashlib.sha256(shown).hexdigest() != digest:
            raise ValueError(f"landing changes frozen blob: {path}")
    if strict:
        for lane in ("ledger", "resolution"):
            capability(lane)
        error = scan_landing_junit(repo / LANDING_JUNIT)
        if error:
            raise ValueError(error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("record-red", "verify"):
        command = sub.add_parser(action)
        command.add_argument("--repo", type=Path, default=Path.cwd())
        command.add_argument("--landing-ref", default="HEAD")
        command.add_argument("--receipt", type=Path, default=Path(RECEIPT_PATH))
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    receipt_path = args.receipt if args.receipt.is_absolute() else repo / args.receipt
    try:
        if args.action == "verify":
            verify(repo, args.landing_ref, receipt_path,
                   strict=os.environ.get("PHASE_LOOP_TDD_REQUIRE_RATIFY_GREEN") == "1")
        else:
            # Do not publish even a temporary-looking receipt in the evidence directory
            # until every expected RED and restored control has been observed.
            with tempfile.TemporaryDirectory(prefix="ratify-red-") as temp:
                staged = Path(temp) / receipt_path.name
                receipt = record_content_tdd_receipt(
                    repo=repo, test_glob=FROZEN_TEST_FILES[0], red_command=RED_COMMAND,
                    landing_ref=args.landing_ref, out=staged,
                    support_paths=tuple(sorted(FROZEN_FILES - {FROZEN_TEST_FILES[0]})),
                )
                output = "".join((staged.parent / rel).read_text(encoding="utf-8")
                                 for rel in (receipt.red_stdout_path, receipt.red_stderr_path))
                error = scan_inventory(receipt) or scan_red_output(output)
                if error:
                    raise ValueError(error)
                receipt_path.parent.mkdir(parents=True, exist_ok=True)
                for name in (staged.name, receipt.red_stdout_path, receipt.red_stderr_path):
                    shutil.copyfile(staged.parent / name, receipt_path.parent / name)
    except (ValueError, AssertionError, OSError, subprocess.SubprocessError) as exc:
        print(f"ratify {args.action} refused: {exc}", file=sys.stderr)
        return 1
    print(f"ratify {args.action}: ok {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
