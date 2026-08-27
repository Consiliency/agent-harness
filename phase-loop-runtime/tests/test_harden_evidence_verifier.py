"""SL-0 guard controls that remain GREEN in both default and activated modes."""

from __future__ import annotations

import ast
from pathlib import Path

from harden_tdd_guard import HARDEN_CASES, HARDEN_RED_ANCHORS, HARDEN_TEST_PATHS


def test_harden_guard_inventory_and_case_bindings_are_frozen():
    root = Path(__file__).resolve().parents[2]
    assert len(HARDEN_TEST_PATHS) == 26
    assert len(set(HARDEN_TEST_PATHS)) == 26
    assert set(HARDEN_RED_ANCHORS) == set(HARDEN_CASES)
    assert set(HARDEN_RED_ANCHORS.values()) == {
        "HARDEN-RED-ANCHOR::staged-tree-containment",
        "HARDEN-RED-ANCHOR::cwd-independent-reconcile",
        "HARDEN-RED-ANCHOR::non-vacuous-goal-coverage",
        "HARDEN-RED-ANCHOR::login-shell-interpreter",
        "HARDEN-RED-ANCHOR::review-leg-isolation",
    }
    for case_id, case in HARDEN_CASES.items():
        test_path, _, test_name = case.nodeid.partition("::")
        path = root / test_path
        assert path.is_file(), f"{case_id}: missing owned test path {test_path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == test_name]
        assert len(matches) == 1, f"{case_id}: missing or duplicate {test_name}"
        source = ast.unparse(matches[0])
        assert f"harden_require('{case_id}')" in source or f'harden_require("{case_id}")' in source
