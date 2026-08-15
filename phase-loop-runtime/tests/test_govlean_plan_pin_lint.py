"""GOVLEAN EC-GOVLEAN-1 falsifiers for content-only phase-plan pins."""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .govlean_freeze_receipt import govlean_api_available
from .phase_loop_test_utils import make_repo


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.plan_pin_lint", "find_plan_pin_violations"),
    reason="GOVLEAN plan-pin lint capability absent",
)


ROOT = Path(__file__).resolve().parents[2]
CONFORM_PLAN = ROOT / "plans" / "phase-plan-v10-CONFORM.md"
GOVLEAN_PLAN = ROOT / "plans" / "phase-plan-v10-GOVLEAN.md"
ROADMAP = ROOT / "specs" / "phase-plans-v10.md"
VALIDATOR = ROOT / "skills-src" / "claude" / "claude-plan-phase" / "scripts" / "validate_plan_doc.py"
CATEGORIES = frozenset(
    {
        "future_commit_identity",
        "mutable_tracked_blob_pin",
        "commit_ordinal",
        "future_topology",
    }
)


def _lint_module():
    return importlib.import_module("phase_loop_runtime.plan_pin_lint")


def _categories(findings) -> set[str]:
    return {finding.category for finding in findings}


def _forbidden_plan_text() -> str:
    return """---
phase_loop_plan_version: 1
phase: SAMPLE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
---

# Sample

- The future implementation must land commit `1111111111111111111111111111111111111111`.
- `phase-loop-runtime/src/phase_loop_runtime/runner.py` must retain blob `sha256:2222222222222222222222222222222222222222222222222222222222222222`.
- The implementation change must be commit number 3 in its branch series.
- The future tests-only landing must be a two-parent merge commit with the implementation as its second parent.
"""


def test_unmodified_conform_plan_supplies_all_four_nonvacuous_positive_controls():
    lint = _lint_module()

    findings = lint.find_plan_pin_violations(
        CONFORM_PLAN.read_text(encoding="utf-8"), ROOT, CONFORM_PLAN
    )

    assert isinstance(findings, tuple)
    assert CATEGORIES <= _categories(findings), findings


def test_clean_govlean_plan_exempts_only_its_verified_current_roadmap_frontmatter_seal():
    lint = _lint_module()

    findings = lint.find_plan_pin_violations(
        GOVLEAN_PLAN.read_text(encoding="utf-8"), ROOT, GOVLEAN_PLAN
    )

    assert findings == ()


def test_each_closed_future_history_category_has_a_distinct_firing_control(tmp_path):
    lint = _lint_module()
    repo = make_repo(tmp_path)
    plan_path = repo / "plans" / "phase-plan-v10-SAMPLE.md"
    tracked = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "runner.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("# tracked fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", tracked.relative_to(repo).as_posix()], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "tracked fixture"], cwd=repo, check=True, capture_output=True)
    plan_path.write_text(_forbidden_plan_text(), encoding="utf-8")

    findings = lint.find_plan_pin_violations(plan_path.read_text(encoding="utf-8"), repo, plan_path)

    assert _categories(findings) == CATEGORIES, findings


def test_pinned_inputs_allows_declared_external_content_but_never_a_tracked_repo_blob(tmp_path):
    lint = _lint_module()
    repo = make_repo(tmp_path)
    tracked = repo / "src" / "owned.py"
    tracked.parent.mkdir()
    tracked.write_text("owned = True\n", encoding="utf-8")
    subprocess.run(["git", "add", tracked.relative_to(repo).as_posix()], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "tracked input"], cwd=repo, check=True, capture_output=True)
    plan_path = repo / "plans" / "phase-plan-v10-SAMPLE.md"
    plan_path.write_text(
        """# Sample

## Pinned inputs

- External release archive: https://example.invalid/release.tar.gz sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
- Repository file: src/owned.py sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
""",
        encoding="utf-8",
    )

    findings = lint.find_plan_pin_violations(plan_path.read_text(encoding="utf-8"), repo, plan_path)

    assert _categories(findings) == {"mutable_tracked_blob_pin"}, findings


def test_validator_reports_every_govlean_pin_finding_instead_of_accepting_or_stopping_early(tmp_path):
    lint = _lint_module()
    repo = make_repo(tmp_path)
    shutil.copyfile(ROADMAP, repo / "specs" / "phase-plans-v10.md")
    tracked = repo / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "runner.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("# tracked fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", tracked.relative_to(repo).as_posix()], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "tracked fixture"], cwd=repo, check=True, capture_output=True)
    plan_path = repo / "plans" / "phase-plan-v10-GOVLEAN.md"
    plan_path.write_text(
        GOVLEAN_PLAN.read_text(encoding="utf-8") + "\n" + _forbidden_plan_text(),
        encoding="utf-8",
    )

    findings = lint.find_plan_pin_violations(plan_path.read_text(encoding="utf-8"), repo, plan_path)
    assert _categories(findings) == CATEGORIES, findings

    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), str(plan_path)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0, output
    for category in sorted(CATEGORIES):
        assert category in output, output
