"""agent-harness#552: the plan validators fail closed when a check cannot run.

`_check_govlean_plan_pins` used to return no findings when the GOVLEAN plan-pin lint could not
be imported, and `_check_d_owned_files_disjoint` silently skipped owned-file expansion when
`git ls-files` failed inside a repository. Both now report a `contract_bug` finding, matching
Check Q's existing fail-closed behaviour.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from .phase_loop_test_utils import make_repo

ROOT = Path(__file__).resolve().parents[2]
PLAN_VALIDATOR = ROOT / "skills-src" / "claude" / "claude-plan-phase" / "scripts" / "validate_plan_doc.py"
EXECUTE_VALIDATOR = ROOT / "skills-src" / "claude" / "claude-execute-phase" / "scripts" / "validate_plan_doc.py"
LANES = {"SL-1": {"owned_globs": ["pkg/a.py"]}, "SL-2": {"owned_globs": ["pkg/b.py"]}}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def _contract_bugs(findings, prefix: str) -> list[str]:
    return [f for f in findings if f.startswith(prefix) and "contract_bug" in f]


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


@pytest.mark.parametrize("path", [PLAN_VALIDATOR, EXECUTE_VALIDATOR], ids=["plan-phase", "execute-phase"])
def test_failed_git_ls_files_inside_a_repo_is_a_contract_bug_finding(tmp_path, path):
    validator = _load(path, f"validate_plan_doc_{path.parent.parent.name}_552_d")
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    assert validator._git_ls_files(not_a_repo) is None  # the real gathering fails, nothing is stubbed

    findings = validator._check_d_owned_files_disjoint(LANES, not_a_repo)

    assert _contract_bugs(findings, "(D)") == [
        "(D) contract_bug: `git ls-files` failed; owned-file overlap could not be checked"
    ]


@pytest.mark.parametrize("path", [PLAN_VALIDATOR, EXECUTE_VALIDATOR], ids=["plan-phase", "execute-phase"])
def test_working_git_ls_files_reports_no_contract_bug(tmp_path, path):
    validator = _load(path, f"validate_plan_doc_{path.parent.parent.name}_552_e")
    repo = make_repo(tmp_path)
    assert validator._git_ls_files(repo) is not None

    findings = validator._check_d_owned_files_disjoint(LANES, repo)

    assert _contract_bugs(findings, "(D)") == []


@pytest.mark.parametrize("path", [PLAN_VALIDATOR, EXECUTE_VALIDATOR], ids=["plan-phase", "execute-phase"])
def test_no_repo_context_reports_no_contract_bug(path):
    validator = _load(path, f"validate_plan_doc_{path.parent.parent.name}_552_f")

    findings = validator._check_d_owned_files_disjoint(LANES, None)

    assert _contract_bugs(findings, "(D)") == []
