"""agent-harness#1302: check (S) warns when the execution plan exceeds its word budget.

The plan-size rule used to contradict itself: the skills set a 3000-word budget while
AGENTS.md and the convergence doc said there was no fixed cap. The owner chose a split:
the execution plan is budgeted, the frozen artifacts it references are not. The budget
scales with lane count (2000 + 500 per lane by default) and is configurable per repo and
per phase in the tracked repo-root `.phase-loop-planning.toml`. Check (S) is the enforcer;
WARN by default.

The negative control is `plans/phase-plan-v10-PANEL.md`, a post-rule plan at 15,241
words against a 4-lane budget of 4,000. (S) must fire on it and stay silent on
`phase-plan-v10-HARDEN.md`, a healthy 7-lane plan that a flat 3000 cap would flag.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

from .proofgate_content_tdd_adapter import (
    PROOFGATE_GRANDFATHER_CUTOFF_OID,
    PROOFGATE_GRANDFATHER_SERVER_DATE,
    PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
    proofgate_grandfather_plan_bytes,
)

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
    config = tmp_path / V.PLANNING_CONFIG
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text, encoding="utf-8")
    return tmp_path


def test_planning_config_is_not_hidden_by_runtime_exclude(tmp_path: Path) -> None:
    # The runtime excludes `.phase-loop/` from git, so a config there could never be
    # committed or reviewed. The config must live where `git add` takes it.
    from phase_loop_runtime.runtime_paths import ensure_phase_loop_excluded

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    ensure_phase_loop_excluded(tmp_path)
    config = tmp_path / V.PLANNING_CONFIG
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('[plan_budget]\nmode = "error"\n', encoding="utf-8")
    git = lambda *a: subprocess.run(  # noqa: E731
        ["git", "-C", str(tmp_path), *a], capture_output=True
    ).returncode
    assert git("check-ignore", "-q", str(V.PLANNING_CONFIG)) == 1
    assert git("add", str(V.PLANNING_CONFIG)) == 0
    assert V._resolve_plan_budget(tmp_path, "X", None)[0].mode == "error"


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
    "[planbudget]\nmode = \"error\"\n",           # typo'd top-level table
])
def test_malformed_config_is_a_visible_error(tmp_path: Path, text: str) -> None:
    budget, findings = V._resolve_plan_budget(_write_config(tmp_path, text), "X", None)
    assert budget == V.PlanBudget()
    assert len(findings) == 1 and findings[0].startswith("(S) invalid")
    assert "WARN" not in findings[0]


def test_malformed_phase_budget_cannot_silently_leave_check_off(tmp_path: Path) -> None:
    config = _write_config(tmp_path, '[plan_budget]\nmode = "off"\n') / V.PLANNING_CONFIG
    budget, findings = V._resolve_plan_budget(tmp_path, "X", None)
    assert findings == [] and budget.mode == "off"

    results = []
    for phase_settings in (
        '[plan_budget.phases.X.phases]\nmode = "error"\n',
        '[plan_budget.phases.OTHER]\nbase_words = true\n',
    ):
        config.write_text(
            '[plan_budget]\nmode = "off"\n' + phase_settings, encoding="utf-8"
        )
        results.append(V._resolve_plan_budget(tmp_path, "X", None))
    for budget, findings in results:
        assert findings and findings[0].startswith("(S) invalid"), results
        assert budget == V.PlanBudget()
        assert V._check_s_plan_word_budget("w " * 5000, 1, budget)


@pytest.mark.parametrize("finding, warning", [
    ("(S) invalid .phase-loop-planning.toml: plan_budget.WARN is not a known setting", False),
    ("(S) execution plan is 9 words, over its 0-word budget (0 + 0 x 0 lanes, from "
     "plan_budget.phases.WARNGATE). Move frozen detail into a referenced artifact.", False),
    ("(S) WARN: execution plan is 9 words, over its 0-word budget.", True),
    ("(P) INFO: goal-coverage not checked here — phase_loop_runtime is not importable.", True),
])
def test_severity_reads_only_the_finding_prefix(finding: str, warning: bool) -> None:
    assert V._is_warning(finding) is warning


def test_warn_in_configuration_text_does_not_demote_budget_errors(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "specs").mkdir()
    roadmap = (REPO / "specs/phase-plans-v10.md").read_bytes()
    (tmp_path / "specs/phase-plans-v10.md").write_bytes(roadmap)
    src = proofgate_grandfather_plan_bytes().replace("phase: PROOFGATE", "phase: WARNINGS")
    src = re.sub(
        r"(?m)^roadmap_sha256:.*$",
        "roadmap_sha256: " + hashlib.sha256(roadmap).hexdigest(), src,
    )
    plan = tmp_path / "phase-plan-v10-WARNINGS.md"
    plan.write_text(src, encoding="utf-8")
    command = [
        sys.executable, str(PLAN_VALIDATOR), str(plan),
        "--grammar-cutoff-commit", PROOFGATE_GRANDFATHER_CUTOFF_OID,
        "--grammar-successor-commit", PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
        "--server-attested-pre-grammar-date", PROOFGATE_GRANDFATHER_SERVER_DATE,
    ]
    baseline = subprocess.run(command, capture_output=True, text=True)
    assert baseline.returncode == 0, baseline.stderr

    config = tmp_path / V.PLANNING_CONFIG
    config.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for config_text in (
        '[plan_budget]\nWARN = 1\n',
        '[plan_budget.phases.WARNINGS]\nmode = "error"\n'
        'base_words = 0\nper_lane_words = 0\n',
        '[plan_budget]\nmode = "error"\nbase_words = 0\nper_lane_words = 0\n',
    ):
        config.write_text(config_text, encoding="utf-8")
        results.append(subprocess.run(command, capture_output=True, text=True))
    assert all("(S)" in checked.stderr for checked in results)
    assert [checked.returncode for checked in results] == [1, 1, 1], "\n".join(
        checked.stdout + checked.stderr for checked in results
    )


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


def test_cli_lane_scaling_is_wired_through_main(tmp_path: Path) -> None:
    # HARDEN is over a flat 2000 but under its 7-lane budget, so (S) stays silent only if
    # main() passes the real lane count. A bare tmp repo keeps any local root config out.
    # Assert on (S) lines only: the bare copy exits 1 on (FM) roadmap resolution.
    src = _plan("phase-plan-v10-HARDEN.md")
    assert len(V._plan_body(src).split()) > V.PLAN_BUDGET_BASE_WORDS
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    plan = tmp_path / "plans" / "phase-plan-v10-HARDEN.md"
    plan.parent.mkdir()
    plan.write_text(src, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(PLAN_VALIDATOR), str(plan)], capture_output=True, text=True
    )
    assert "Traceback" not in proc.stderr, proc.stderr[-2000:]
    assert "(S)" not in proc.stderr, proc.stderr[-2000:]


def test_plan_budget_docs_name_the_tracked_config() -> None:
    roots = [REPO / "skills-src", REPO / "phase-loop-skills", BUNDLE, REPO / "docs"]
    if not all(root.is_dir() for root in roots):
        pytest.skip("source tree absent (from-wheel layout)")
    offenders = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "planning.toml" not in text:
                continue
            if (".phase-loop-planning.toml" not in text
                    or ".phase-loop/planning.toml" in text or "phases.CONFORM" in text):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


# --- agent-harness#1381: entries whose alias no roadmap declares are reported -------------

def _roadmap_repo(tmp_path: Path, config_text: str) -> "tuple[Path, list]":
    """A git repo holding the v10 roadmap, a PROOFGATE plan anchored to it, and the given
    `.phase-loop-planning.toml`. Returns the repo and the validator command."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "specs").mkdir()
    roadmap = (REPO / "specs/phase-plans-v10.md").read_bytes()
    (tmp_path / "specs/phase-plans-v10.md").write_bytes(roadmap)
    src = re.sub(
        r"(?m)^roadmap_sha256:.*$",
        "roadmap_sha256: " + hashlib.sha256(roadmap).hexdigest(),
        proofgate_grandfather_plan_bytes(),
    )
    plan = tmp_path / "phase-plan-v10-PROOFGATE.md"
    plan.write_text(src, encoding="utf-8")
    _write_config(tmp_path, config_text)
    return tmp_path, [
        sys.executable, str(PLAN_VALIDATOR), str(plan),
        "--grammar-cutoff-commit", PROOFGATE_GRANDFATHER_CUTOFF_OID,
        "--grammar-successor-commit", PROOFGATE_GRANDFATHER_SUCCESSOR_OID,
        "--server-attested-pre-grammar-date", PROOFGATE_GRANDFATHER_SERVER_DATE,
    ]


@pytest.mark.parametrize("mode", ["warn", "error"])
def test_cli_reports_entry_for_undeclared_alias(tmp_path: Path, mode: str) -> None:
    # Red-first: a mistyped alias used to be silently ignored. It is a WARN in every mode;
    # under `mode = "error"` the plan still exits 0, because the finding is about the
    # config and a renamed phase would otherwise fail every plan in the repo.
    _, command = _roadmap_repo(tmp_path, (
        f'[plan_budget]\nmode = "{mode}"\n\n[plan_budget.phases.CONFROM]\nbase_words = 8000\n'
    ))
    proc = subprocess.run(command, capture_output=True, text=True)
    flagged = [line for line in proc.stderr.splitlines() if "CONFROM" in line]
    assert len(flagged) == 1, proc.stderr[-2000:]
    assert flagged[0].startswith("(S) WARN: [plan_budget.phases.CONFROM]")
    assert V._is_warning(flagged[0])
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_cli_declared_aliases_are_not_reported(tmp_path: Path) -> None:
    # Green guard: declared aliases, in any case, and the plan's own phase raise nothing.
    _, command = _roadmap_repo(tmp_path, (
        '[plan_budget]\nmode = "error"\n\n'
        "[plan_budget.phases.conform]\nbase_words = 8000\n\n"
        "[plan_budget.phases.PANEL]\nbase_words = 8000\n\n"
        "[plan_budget.phases.ProofGate]\nbase_words = 8000\n"
    ))
    proc = subprocess.run(command, capture_output=True, text=True)
    assert "(S)" not in proc.stderr, proc.stderr[-2000:]
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_undeclared_alias_findings_name_each_entry(tmp_path: Path) -> None:
    repo, _ = _roadmap_repo(tmp_path, (
        '[plan_budget]\nmode = "off"\n\n'
        "[plan_budget.phases.CONFROM]\nbase_words = 1\n\n"
        "[plan_budget.phases.CONFORM]\nbase_words = 1\n\n"
        "[plan_budget.phases.WARN]\nbase_words = 1\n"
    ))
    findings = V._check_s_undeclared_phase_aliases(repo)
    assert [f.split("]")[0] for f in findings] == [
        "(S) WARN: [plan_budget.phases.CONFROM", "(S) WARN: [plan_budget.phases.WARN",
    ]


def test_aliases_come_from_every_roadmap_not_only_the_active_one(tmp_path: Path) -> None:
    # FREEZE is declared only by the superseded convergence-v1 roadmap, whose name is
    # outside `phase-plans-v*`; RUNTIME is declared by both it and v10, so one entry
    # covers both roadmaps.
    repo, _ = _roadmap_repo(tmp_path, (
        "[plan_budget.phases.FREEZE]\nbase_words = 1\n\n"
        "[plan_budget.phases.RUNTIME]\nbase_words = 1\n"
    ))
    findings = V._check_s_undeclared_phase_aliases(repo)
    assert [f.split("]")[0] for f in findings] == ["(S) WARN: [plan_budget.phases.FREEZE"]
    convergence = "specs/phase-plans-convergence-v1.md"
    (repo / convergence).write_bytes((REPO / convergence).read_bytes())
    assert V._check_s_undeclared_phase_aliases(repo) == []


def test_declared_alias_in_registered_nested_roadmap_is_not_reported(tmp_path: Path) -> None:
    # Board finding F001 (agent-harness#1396 hb1): the runtime's roadmap set is the git
    # pathspec `specs/phase-plans-*.md`, whose `*` also matches `/`. A registered roadmap
    # at `specs/phase-plans-archive/convergence-v1.md` declares FREEZE, so an entry for
    # it must not be reported.
    import json

    from phase_loop_runtime import roadmap_lint

    repo, command = _roadmap_repo(tmp_path, (
        '[plan_budget]\nmode = "error"\n[plan_budget.phases.freeze]\nbase_words = 8000\n'
    ))
    nested = "specs/phase-plans-archive/convergence-v1.md"
    (repo / nested).parent.mkdir()
    (repo / nested).write_bytes((REPO / "specs/phase-plans-convergence-v1.md").read_bytes())
    registry = {
        "schema": "roadmap_status_manifest.v1",
        "selected_roadmap": "specs/phase-plans-v10.md",
        "roadmaps": [
            {"path": nested, "status": "superseded"},
            {"path": "specs/phase-plans-v10.md", "status": "active"},
        ],
    }
    (repo / "specs/roadmap-status.json").write_text(json.dumps(registry), encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "specs"], check=True)
    assert roadmap_lint._tracked_roadmap_paths(repo) == [nested, "specs/phase-plans-v10.md"]
    assert roadmap_lint.read_roadmap_status(repo, repo / "specs/roadmap-status.json") == registry
    proc = subprocess.run(command, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "[plan_budget.phases.freeze]" not in proc.stderr, proc.stderr[-2000:]
    assert V._check_s_undeclared_phase_aliases(repo) == []


def test_undeclared_alias_check_is_silent_without_roadmaps_or_readable_config(
    tmp_path: Path,
) -> None:
    # No roadmap to compare against: nothing is reported (the plan already fails (FM)).
    _write_config(tmp_path, "[plan_budget.phases.CONFROM]\nbase_words = 1\n")
    assert V._check_s_undeclared_phase_aliases(tmp_path) == []
    assert V._check_s_undeclared_phase_aliases(None) == []
    # Unparseable TOML is reported once, by `_resolve_plan_budget`, not again here.
    repo, _ = _roadmap_repo(tmp_path / "r", "[plan_budget.phases.CONFROM\n")
    assert V._check_s_undeclared_phase_aliases(repo) == []
    assert V._resolve_plan_budget(repo, "PROOFGATE", None)[1][0].startswith("(S) invalid")


def test_undeclared_alias_check_is_visible_without_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _roadmap_repo(tmp_path, "[plan_budget.phases.CONFROM]\nbase_words = 1\n")
    monkeypatch.setitem(sys.modules, "phase_loop_runtime", None)
    findings = V._check_s_undeclared_phase_aliases(repo)
    assert len(findings) == 1 and findings[0].startswith("(S) INFO:"), findings
