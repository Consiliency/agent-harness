"""HARDEN SL-0 tests-only guard: frozen inventory and deterministic RED anchors.

The guard is deliberately test-only.  Before production exposes the exact
``HARDEN_CAPABILITY_VERSION = 1`` marker, mapped capability assertions skip in
the ordinary suite and fail at their one named anchor only when the explicit
HARDEN TDD switch is active.  Each case first resolves the production symbol it
will exercise, so an import or collection problem is never accepted as RED
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import inspect
import os
from pathlib import Path
import subprocess
import sysconfig

import pytest


HARDEN_ACTIVATION_ENV = "PHASE_LOOP_TDD_EXPECT_HARDEN"
HARDEN_MARKER_MODULE = "phase_loop_runtime.capability_registry"
HARDEN_MARKER_ATTRIBUTE = "HARDEN_CAPABILITY_VERSION"
HARDEN_SKIP_REASON = (
    "HARDEN production capability is absent (SL-0 tests-only boundary): "
    "set PHASE_LOOP_TDD_EXPECT_HARDEN=1 to record the deterministic RED anchors"
)

HARDEN_TEST_PATHS = (
    "phase-loop-runtime/tests/harden_tdd_guard.py",
    "phase-loop-runtime/tests/test_advisor_board_advisory_mode.py",
    "phase-loop-runtime/tests/test_advisor_board_backcompat.py",
    "phase-loop-runtime/tests/test_advisor_board_backing_homebrew.py",
    "phase-loop-runtime/tests/test_advisor_board_backing_omnigent.py",
    "phase-loop-runtime/tests/test_advisor_board_cli_legacy.py",
    "phase-loop-runtime/tests/test_advisor_board_composition.py",
    "phase-loop-runtime/tests/test_advisor_board_config.py",
    "phase-loop-runtime/tests/test_advisor_board_golden.py",
    "phase-loop-runtime/tests/test_advisor_board_integration.py",
    "phase-loop-runtime/tests/test_advisor_board_live_research.py",
    "phase-loop-runtime/tests/test_advisor_board_observability.py",
    "phase-loop-runtime/tests/test_advisor_board_presets.py",
    "phase-loop-runtime/tests/test_advisor_board_research.py",
    "phase-loop-runtime/tests/test_advisor_board_resolver.py",
    "phase-loop-runtime/tests/test_goal_coverage.py",
    "phase-loop-runtime/tests/test_harden_evidence_verifier.py",
    "phase-loop-runtime/tests/test_panel_invoker.py",
    "phase-loop-runtime/tests/test_panel_leg_failure_diagnostic.py",
    "phase-loop-runtime/tests/test_panel_native_fill_183.py",
    "phase-loop-runtime/tests/test_panel_streaming_verdicts.py",
    "phase-loop-runtime/tests/test_phase_loop_injection.py",
    "phase-loop-runtime/tests/test_ratification_policy.py",
    "phase-loop-runtime/tests/test_reconcile_portability_85c.py",
    "phase-loop-runtime/tests/test_review_leg_sandbox.py",
    "phase-loop-runtime/tests/test_verification_interpreter_guard_221.py",
)

HARDEN_RED_ANCHORS = {
    "staged-tree-containment": "HARDEN-RED-ANCHOR::staged-tree-containment",
    "cwd-independent-reconcile": "HARDEN-RED-ANCHOR::cwd-independent-reconcile",
    "non-vacuous-goal-coverage": "HARDEN-RED-ANCHOR::non-vacuous-goal-coverage",
    "login-shell-interpreter": "HARDEN-RED-ANCHOR::login-shell-interpreter",
    "review-leg-isolation": "HARDEN-RED-ANCHOR::review-leg-isolation",
}


@dataclass(frozen=True)
class HardenCase:
    nodeid: str
    production_path: str
    symbol: str


HARDEN_CASES = {
    "staged-tree-containment": HardenCase(
        "phase-loop-runtime/tests/test_review_leg_sandbox.py::"
        "test_review_stage_rejects_every_escape_form_before_launch",
        "phase-loop-runtime/src/phase_loop_runtime/launcher.py",
        "_stage_review_tree",
    ),
    "cwd-independent-reconcile": HardenCase(
        "phase-loop-runtime/tests/test_reconcile_portability_85c.py::"
        "test_cwd_independent_reconcile_is_repo_anchored",
        "phase-loop-runtime/src/phase_loop_runtime/reconcile.py",
        "reconcile",
    ),
    "non-vacuous-goal-coverage": HardenCase(
        "phase-loop-runtime/tests/test_goal_coverage.py::"
        "test_enforce_blocks_every_zero_declared_and_all_bare_legacy_is_distinct",
        "phase-loop-runtime/src/phase_loop_runtime/runner.py",
        "_execute_goal_coverage_preflight",
    ),
    "login-shell-interpreter": HardenCase(
        "phase-loop-runtime/tests/test_verification_interpreter_guard_221.py::"
        "test_argument_consuming_bash_options_and_profile_patch_version_fail_closed",
        "phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py",
        "run_verification",
    ),
    "review-leg-isolation": HardenCase(
        "phase-loop-runtime/tests/test_advisor_board_composition.py::"
        "test_review_leg_isolation_refuses_unbound_direct_invocation",
        "phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py",
        "invoke_board",
    ),
}


def _repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent,
    )
    return Path(completed.stdout.strip()).resolve()


def _dotted_module(production_path: str) -> str:
    relative = production_path.split("phase-loop-runtime/src/", 1)[1]
    return relative.removesuffix(".py").replace("/", ".")


def _marker_version() -> int | None:
    try:
        spec = importlib.util.find_spec(HARDEN_MARKER_MODULE)
    except ModuleNotFoundError:
        return None
    if spec is None:
        return None
    module = importlib.import_module(HARDEN_MARKER_MODULE)
    return getattr(module, HARDEN_MARKER_ATTRIBUTE, None)


def harden_capability_active() -> bool:
    """Return true for the exact forced mode or the final production marker."""

    return os.environ.get(HARDEN_ACTIVATION_ENV) == "1" or _marker_version() == 1


def _resolve_production_symbol(case_id: str) -> None:
    case = HARDEN_CASES[case_id]
    module = importlib.import_module(_dotted_module(case.production_path))
    obj: object = module
    for part in case.symbol.split("."):
        obj = getattr(obj, part)
    source_file = inspect.getsourcefile(obj)
    assert source_file is not None, f"{case_id}: {case.symbol} has no source file"
    relative = Path(case.production_path.split("phase-loop-runtime/src/", 1)[1])
    checkout_path = (_repo_root() / case.production_path).resolve()
    expected = {checkout_path}
    for scheme_path in ("purelib", "platlib"):
        root = sysconfig.get_path(scheme_path)
        if root:
            expected.add((Path(root) / relative).resolve())
    resolved = Path(source_file).resolve()
    assert resolved in expected, (
        f"{case_id}: {case.symbol} resolves to {resolved}, not {case.production_path}"
    )
    if resolved != checkout_path:
        assert resolved.read_bytes() == checkout_path.read_bytes(), (
            f"{case_id}: installed {case.symbol} differs from the reviewed checkout"
        )


def harden_require(case_id: str) -> None:
    """Enter a case's production seam, then skip or emit its one RED anchor."""

    assert case_id in HARDEN_CASES, f"unmapped HARDEN case: {case_id}"
    _resolve_production_symbol(case_id)
    marker = _marker_version()
    assert marker in (None, 1), (
        f"{HARDEN_MARKER_MODULE}.{HARDEN_MARKER_ATTRIBUTE} must be absent or equal 1"
    )
    if marker == 1:
        return
    if os.environ.get(HARDEN_ACTIVATION_ENV) == "1":
        raise AssertionError(HARDEN_RED_ANCHORS[case_id])
    pytest.skip(HARDEN_SKIP_REASON)
