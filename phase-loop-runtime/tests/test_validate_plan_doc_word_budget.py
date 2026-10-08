"""agent-harness#1302: check (S) warns when the execution plan exceeds its word budget.

The plan-size rule used to contradict itself: the skills set a 3000-word budget while
AGENTS.md and the convergence doc said there was no fixed cap. The owner chose a split:
the execution plan is budgeted, the frozen artifacts it references are not. The budget
scales with lane count (2000 + 500 per lane by default) and is configurable per repo and
per phase in `.phase-loop/planning.toml`. Check (S) is the enforcer; WARN by default.

The negative control is `plans/phase-plan-v10-PANEL.md`, a post-rule plan at 15,241
words against a 4-lane budget of 4,000. (S) must fire on it and stay silent on
`phase-plan-v10-HARDEN.md`, a healthy 7-lane plan that a flat 3000 cap would flag.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "skills_bundle"
PLAN_VALIDATOR = BUNDLE / "claude-plan-phase" / "scripts" / "validate_plan_doc.py"
PLANS = REPO / "plans"


def _load():
    name = "validate_plan_doc_word_budget_1302"
    spec = importlib.util.spec_from_file_location(name, PLAN_VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


V = _load()


def _words(n: int) -> str:
    return " ".join(["w"] * n)


def _plan(name: str) -> str:
    path = PLANS / name
    if not path.is_file():
        pytest.skip("plans/ absent (from-wheel layout)")
    return path.read_text(encoding="utf-8")


def _lanes(src: str) -> int:
    return len(V._parse_lane_index(V._extract_section(src, "Lane Index & Dependencies")))


def test_over_budget_post_rule_plan_warns() -> None:
    src = _plan("phase-plan-v10-PANEL.md")
    findings = V._check_s_plan_word_budget(src, _lanes(src))
    assert len(findings) == 1
    assert findings[0].startswith("(S) WARN:")
    assert "4000-word budget" in findings[0]


def test_healthy_many_lane_plan_is_silent() -> None:
    # 3,672 words over 7 lanes: a flat 3000 cap flagged it; the lane-scaled one must not.
    src = _plan("phase-plan-v10-HARDEN.md")
    assert _lanes(src) == 7
    assert V._check_s_plan_word_budget(src, _lanes(src)) == []
    assert V._check_s_plan_word_budget(src, _lanes(src), V.PlanBudget(3000, 0))


def test_budget_scales_with_lanes_and_excludes_frontmatter() -> None:
    limit = V.PLAN_BUDGET_BASE_WORDS + 3 * V.PLAN_BUDGET_PER_LANE_WORDS
    assert V._check_s_plan_word_budget(_words(limit), 3) == []
    assert V._check_s_plan_word_budget(_words(limit + 1), 3)
    assert V._check_s_plan_word_budget(_words(limit + 1), 4) == []
    frontmatter = "---\n" + "\n".join(f"k{i}: v" for i in range(50)) + "\n---\n"
    assert V._check_s_plan_word_budget(frontmatter + _words(limit), 3) == []


def test_modes() -> None:
    over = _words(V.PLAN_BUDGET_BASE_WORDS + 1)
    assert "WARN" in V._check_s_plan_word_budget(over, 0, V.PlanBudget(mode="warn"))[0]
    assert "WARN" not in V._check_s_plan_word_budget(over, 0, V.PlanBudget(mode="error"))[0]
    assert V._check_s_plan_word_budget(over, 0, V.PlanBudget(mode="off")) == []


def _write_config(tmp_path: Path, text: str) -> Path:
    (tmp_path / ".phase-loop").mkdir()
    (tmp_path / ".phase-loop" / "planning.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_config_repo_default_and_phase_override(tmp_path: Path) -> None:
    repo = _write_config(tmp_path, (
        "[plan_budget]\nbase_words = 1000\nper_lane_words = 100\nmode = \"error\"\n\n"
        "[plan_budget.phases.conform]\nbase_words = 8000\n"
    ))
    budget, findings = V._resolve_plan_budget(repo, "PANEL", None)
    assert findings == []
    assert (budget.base_words, budget.per_lane_words, budget.mode) == (1000, 100, "error")
    budget, _ = V._resolve_plan_budget(repo, "CONFORM", None)  # alias match is case-insensitive
    assert (budget.base_words, budget.per_lane_words, budget.mode) == (8000, 100, "error")
    assert budget.source == "plan_budget.phases.conform"


def test_flag_overrides_config(tmp_path: Path) -> None:
    repo = _write_config(tmp_path, "[plan_budget]\nbase_words = 1000\nmode = \"off\"\n")
    budget, _ = V._resolve_plan_budget(repo, "X", 6000)
    assert (budget.limit(5), budget.mode, budget.source) == (6000, "warn", "--word-budget")


@pytest.mark.parametrize("text", [
    "[plan_budget]\nbase_word = 1000\n",          # typo'd key
    "[plan_budget]\nmode = \"loud\"\n",           # unknown mode
    "[plan_budget]\nbase_words = -1\n",           # negative
    "[plan_budget]\nbase_words = true\n",         # bool is not a word count
    "[plan_budget\n",                              # not TOML
])
def test_malformed_config_is_a_visible_error(tmp_path: Path, text: str) -> None:
    budget, findings = V._resolve_plan_budget(_write_config(tmp_path, text), "X", None)
    assert budget == V.PlanBudget()
    assert len(findings) == 1 and findings[0].startswith("(S) invalid")
    assert "WARN" not in findings[0]


def test_cli_end_to_end_flag_and_exit_code(tmp_path: Path) -> None:
    src = _plan("phase-plan-v10-PANEL.md")
    run = lambda *extra: subprocess.run(  # noqa: E731
        [sys.executable, str(PLAN_VALIDATOR), str(PLANS / "phase-plan-v10-PANEL.md"), *extra],
        capture_output=True, text=True, cwd=REPO,
    )
    default = run()
    assert "(S) WARN: execution plan is" in default.stderr, default.stderr[-2000:]
    raised = run("--word-budget", str(len(src.split()) * 2))
    assert "(S)" not in raised.stderr


def test_cli_reads_phase_override_from_repo_config(tmp_path: Path) -> None:
    # Wires frontmatter `phase:` -> [plan_budget.phases.<ALIAS>] through main().
    src = _plan("phase-plan-v10-PANEL.md")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _write_config(tmp_path, f"[plan_budget.phases.panel]\nbase_words = {len(src.split()) * 2}\n")
    plan = tmp_path / "plans" / "phase-plan-v10-PANEL.md"
    plan.parent.mkdir()
    plan.write_text(src, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(PLAN_VALIDATOR), str(plan)], capture_output=True, text=True
    )
    assert "Traceback" not in proc.stderr, proc.stderr[-2000:]
    assert "(S)" not in proc.stderr
