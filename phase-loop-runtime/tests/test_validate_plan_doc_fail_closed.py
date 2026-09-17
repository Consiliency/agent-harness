"""agent-harness#552: the plan validators fail closed when a check cannot run.

`_check_govlean_plan_pins` used to return no findings when the GOVLEAN plan-pin lint could not
be imported, and `_check_d_owned_files_disjoint` silently skipped owned-file expansion when
`git ls-files` failed inside a repository. Both now report a `contract_bug` finding, matching
Check Q's existing fail-closed behaviour.

The validators are loaded from the packaged `skills_bundle/` copies. Those are present in the
Gate A sparse clean room, and `test_skills_bundle_drift.py` / `test_skills_canon_parity.py` keep
them byte-identical to `skills-src/`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from .phase_loop_test_utils import make_repo

BUNDLE = Path(__file__).resolve().parents[1] / "src" / "phase_loop_runtime" / "skills_bundle"
PLAN_VALIDATOR = BUNDLE / "claude-plan-phase" / "scripts" / "validate_plan_doc.py"
EXECUTE_VALIDATOR = BUNDLE / "claude-execute-phase" / "scripts" / "validate_plan_doc.py"
VALIDATORS = pytest.mark.parametrize("path", [PLAN_VALIDATOR, EXECUTE_VALIDATOR], ids=["plan-phase", "execute-phase"])
LANES = {"SL-1": {"owned_globs": ["pkg/a.py"]}, "SL-2": {"owned_globs": ["pkg/b.py"]}}
D_BUG = "(D) contract_bug: `git ls-files` failed; owned-file overlap could not be checked"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def _contract_bugs(findings, prefix: str) -> list[str]:
    return [f for f in findings if f.startswith(prefix) and "contract_bug" in f]


def _repo_with_corrupt_index(tmp_path: Path) -> Path:
    """A real repository in which `git rev-parse --show-toplevel` works but `git ls-files` fails."""
    repo = make_repo(tmp_path)
    (repo / ".git" / "index").write_bytes(b"garbage")
    assert subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo, capture_output=True).returncode == 0
    assert subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True).returncode != 0
    return repo


def test_govlean_lint_unavailable_is_a_contract_bug_finding(tmp_path, monkeypatch):
    validator = _load(PLAN_VALIDATOR, "validate_plan_doc_plan_552_a")
    repo = make_repo(tmp_path)
    monkeypatch.setitem(sys.modules, "phase_loop_runtime.plan_pin_lint", None)

    findings = validator._check_govlean_plan_pins("# plan\n", repo / "plans" / "p.md", repo)

    assert _contract_bugs(findings, "(GOVLEAN)") == [
        "(GOVLEAN) contract_bug: plan-pin lint runtime is unavailable; run this validator with phase_loop_runtime installed"
    ]


def test_govlean_lint_available_reports_no_contract_bug(tmp_path):
    pytest.importorskip("phase_loop_runtime.plan_pin_lint")
    validator = _load(PLAN_VALIDATOR, "validate_plan_doc_plan_552_b")
    repo = make_repo(tmp_path)

    findings = validator._check_govlean_plan_pins("# plan\n", repo / "plans" / "p.md", repo)

    assert _contract_bugs(findings, "(GOVLEAN)") == []


def test_govlean_lint_without_repo_context_stays_silent(tmp_path, monkeypatch):
    validator = _load(PLAN_VALIDATOR, "validate_plan_doc_plan_552_c")
    monkeypatch.setitem(sys.modules, "phase_loop_runtime.plan_pin_lint", None)

    assert validator._check_govlean_plan_pins("# plan\n", tmp_path / "p.md", None) == []


@VALIDATORS
def test_failed_git_ls_files_inside_a_repo_is_a_contract_bug_finding(tmp_path, path):
    validator = _load(path, f"validate_plan_doc_{path.parent.parent.name}_552_d")
    repo = _repo_with_corrupt_index(tmp_path)
    assert validator._git_ls_files(repo) is None  # the real gathering fails, nothing is stubbed

    findings = validator._check_d_owned_files_disjoint(LANES, repo)

    assert _contract_bugs(findings, "(D)") == [D_BUG]


@VALIDATORS
def test_working_git_ls_files_reports_no_contract_bug(tmp_path, path):
    validator = _load(path, f"validate_plan_doc_{path.parent.parent.name}_552_e")
    repo = make_repo(tmp_path)
    assert validator._git_ls_files(repo) is not None

    findings = validator._check_d_owned_files_disjoint(LANES, repo)

    assert _contract_bugs(findings, "(D)") == []


@VALIDATORS
def test_no_repo_context_reports_no_contract_bug(path):
    validator = _load(path, f"validate_plan_doc_{path.parent.parent.name}_552_f")

    findings = validator._check_d_owned_files_disjoint(LANES, None)

    assert _contract_bugs(findings, "(D)") == []


@VALIDATORS
def test_cli_exits_nonzero_and_names_the_failed_git_ls_files(tmp_path, path):
    repo = _repo_with_corrupt_index(tmp_path)
    plan = repo / "plans" / "phase-plan-v1-X.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(path), str(plan)], cwd=repo, capture_output=True, text=True, check=False
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0, output
    assert D_BUG in output, output
