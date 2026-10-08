"""agent-harness#1302: check (S) warns when the execution plan exceeds its word budget.

The plan-size rule used to contradict itself: the skills set a 3000-word budget while
AGENTS.md and the convergence doc said there was no fixed cap. The owner chose a split:
the execution plan is capped, the frozen artifacts it references are not. Check (S) is
the enforcer. It is a WARN, consistent with the validator's other advisory checks.

The negative control is `plans/phase-plan-v10-PANEL.md`, a post-rule plan that landed at
roughly five times the budget. (S) must fire on it and stay silent on a short plan.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "skills_bundle"
PLAN_VALIDATOR = BUNDLE / "claude-plan-phase" / "scripts" / "validate_plan_doc.py"
PANEL_PLAN = REPO / "plans" / "phase-plan-v10-PANEL.md"


def _load():
    name = "validate_plan_doc_word_budget_1302"
    spec = importlib.util.spec_from_file_location(name, PLAN_VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


V = _load()


def test_over_budget_post_rule_plan_warns() -> None:
    if not PANEL_PLAN.is_file():
        pytest.skip("plans/ absent (from-wheel layout)")
    findings = V._check_s_plan_word_budget(PANEL_PLAN.read_text(encoding="utf-8"))
    assert len(findings) == 1
    assert findings[0].startswith("(S) WARN:")
    words = int(findings[0].split(" is ", 1)[1].split(" words", 1)[0])
    assert words > V.PLAN_WORD_BUDGET


def test_short_plan_is_silent() -> None:
    assert V._check_s_plan_word_budget("# Plan\n\n## Context\n\nShort.\n") == []


def test_budget_boundary_and_frontmatter_excluded() -> None:
    at_budget = " ".join(["w"] * V.PLAN_WORD_BUDGET)
    assert V._check_s_plan_word_budget(at_budget) == []
    assert V._check_s_plan_word_budget(at_budget + " over")
    frontmatter = "---\n" + "\n".join(f"k{i}: v" for i in range(50)) + "\n---\n"
    assert V._check_s_plan_word_budget(frontmatter + at_budget) == []


def test_warning_is_non_fatal() -> None:
    # main() partitions on the "WARN" substring; (S) must never become an error.
    finding = V._check_s_plan_word_budget(" ".join(["w"] * (V.PLAN_WORD_BUDGET + 1)))[0]
    assert "WARN" in finding
