"""The shipped rule→enforcer registry stays truthful (agent-harness#1321, REPORT 1.13)."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from _dotfiles_tree import skills_bundle_present
from phase_loop_runtime import rule_enforcement as re_mod
from phase_loop_runtime.rule_enforcement import Enforcer, check_registry, load_registry

RUNTIME_ROOT = Path(__file__).resolve().parents[1]


def _rules():
    return load_registry()


def _by_id(rule_id: str):
    return next(rule for rule in _rules() if rule.id == rule_id)


def _check(rules):
    return check_registry(rules, tests_root=RUNTIME_ROOT)


def test_shipped_registry_is_sound():
    assert _check(_rules()) == []


@pytest.mark.skipif(not skills_bundle_present(), reason="negative controls load the sibling phase-loop-skills bundle")
def test_every_negative_control_runs_and_passes(tmp_path):
    # Existence is not proof: a control that skips here never shows its enforcer refuse.
    node_ids = [rule.negative_control for rule in _rules() if rule.negative_control]
    report = tmp_path / "junit.xml"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", *node_ids],
        cwd=RUNTIME_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    cases = ET.parse(report).getroot().iter("testcase")
    ran = {(case.get("classname", "").rsplit(".", 1)[-1], case.get("name")) for case in cases if not list(case)}
    for node_id in node_ids:
        parts = node_id.split("::")
        assert (parts[-2] if len(parts) > 2 else "", parts[-1]) in ran, f"{node_id} did not run and pass"


def test_registry_ships_as_package_data():
    pyproject = (RUNTIME_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"rule_enforcement.json"' in pyproject


def test_registry_covers_both_statuses_and_both_unenforced_reasons():
    rules = _rules()
    assert {rule.status for rule in rules} == {"enforced", "unenforced"}
    assert {rule.unenforced_reason for rule in rules if rule.status == "unenforced"} == {"gap", "judgment"}


# Negative controls: each check above must be able to refuse.


def test_refuses_quote_that_drifted_from_the_skill_text():
    rule = dataclasses.replace(_by_id("plan-phase.lane-dag-acyclic"), quote="The lane DAG is optional.")
    problems = _check([rule])
    assert any("quote not found in codex-plan-phase/SKILL.md" in p for p in problems)


def test_refuses_quote_missing_from_one_harness_copy():
    rule = _by_id("plan-phase.owned-files-disjoint")
    rule = dataclasses.replace(rule, harness_quotes={})
    problems = _check([rule])
    assert any("claude-plan-phase/SKILL.md" in p for p in problems)
    assert not any("codex-plan-phase" in p for p in problems)


def test_refuses_enforcer_symbol_that_no_longer_exists():
    rule = dataclasses.replace(
        _by_id("plan-phase.owned-files-disjoint"),
        enforcers=(Enforcer(kind="module", module="phase_loop_runtime.plan_ir", symbol="_gone_diagnostics"),),
    )
    assert any("_gone_diagnostics not defined" in p for p in _check([rule]))


def test_refuses_skill_script_symbol_missing_from_shipped_copies():
    rule = dataclasses.replace(
        _by_id("plan-phase.spec-closeout-plan-valid"),
        enforcers=(Enforcer(kind="skill_script", path="scripts/validate_plan_doc.py", symbol="_check_zz"),),
    )
    problems = _check([rule])
    assert len([p for p in problems if "_check_zz not defined" in p]) == 4


def test_refuses_negative_control_that_no_longer_exists():
    rule = dataclasses.replace(
        _by_id("plan-phase.lane-dag-acyclic"),
        negative_control="tests/test_phase_loop_lane_ir.py::PhaseLoopLaneIRTest::test_deleted",
    )
    assert any("not found" in p for p in _check([rule]))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"enforcers": ()}, "names no enforcer"),
        ({"negative_control": ""}, "names no negative_control"),
        ({"status": "partly"}, "status must be one of"),
    ],
)
def test_refuses_malformed_enforced_row(changes, expected):
    rule = dataclasses.replace(_by_id("plan-phase.lane-dag-acyclic"), **changes)
    assert any(expected in p for p in _check([rule]))


@pytest.mark.parametrize("tracking", ["", "#1304", "1304"])
def test_refuses_gap_without_repo_qualified_tracking(tracking):
    rule = dataclasses.replace(_by_id("plan-phase.owned-files-complete"), tracking=tracking)
    assert any("repo-qualified tracking ref" in p for p in _check([rule]))


def test_refuses_unenforced_row_that_names_an_enforcer():
    rule = dataclasses.replace(
        _by_id("plan-phase.skip-unneeded-reconnaissance"),
        enforcers=(Enforcer(kind="module", module="phase_loop_runtime.plan_ir", symbol="_cycle_diagnostics"),),
    )
    assert any("unenforced rule names an enforcer" in p for p in _check([rule]))


def test_refuses_duplicate_ids():
    rule = _by_id("plan-phase.lane-dag-acyclic")
    assert any("duplicate id" in p for p in _check([rule, rule]))


def test_refuses_wrong_schema(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"schema": "rule_enforcement.v0", "rules": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="rule_enforcement.v1"):
        load_registry(path)


def test_bundle_root_is_the_packaged_skills_bundle():
    assert re_mod._BUNDLE_ROOT.name == "skills_bundle"
    assert (re_mod._BUNDLE_ROOT / "codex-plan-phase" / "SKILL.md").is_file()
