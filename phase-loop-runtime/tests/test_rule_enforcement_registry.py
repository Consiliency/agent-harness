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
from phase_loop_runtime.rule_enforcement import Enforcer, Rule, check_registry, load_registry

RUNTIME_ROOT = Path(__file__).resolve().parents[1]


def test_shipped_registry_is_sound():
    assert check_registry(load_registry(), tests_root=RUNTIME_ROOT) == []


@pytest.mark.skipif(not skills_bundle_present(), reason="negative controls load the sibling phase-loop-skills bundle")
def test_every_negative_control_runs_and_passes(tmp_path):
    # Existence is not proof: a control that skips here never shows its enforcer refuse.
    node_ids = [rule.negative_control for rule in load_registry() if rule.negative_control]
    report = tmp_path / "junit.xml"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", *node_ids],
        cwd=RUNTIME_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    ran = _ran_keys(report)
    for node_id in node_ids:
        assert _junit_key(node_id) in ran, f"{node_id} did not run and pass"


def _ran_keys(report: Path) -> set[tuple[str, str | None]]:
    """(last classname segment, test name) of every case in ``report`` that neither failed nor skipped."""
    # The report is written by a pytest subprocess into tmp_path; it is not external input.
    cases = ET.parse(report).getroot().iter("testcase")
    return {(case.get("classname", "").rsplit(".", 1)[-1], case.get("name")) for case in cases if not list(case)}


def _junit_key(node_id: str) -> tuple[str, str]:
    """The ``_ran_keys`` entry a control that ran and passed leaves behind.

    JUnit's classname is the dotted module path plus the class, when there is one. A
    control with no class segment (``tests/x.py::test_fn``) therefore reports the module
    stem as its last segment, not an empty string.
    """
    parts = node_id.split("::")
    owner = parts[-2] if len(parts) > 2 else Path(parts[0]).stem
    return (owner, parts[-1])


def test_junit_key_matches_class_and_module_level_controls(tmp_path):
    """Both control shapes must be recognised as having run, or a valid control reads as missing."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        "class TestDemo:\n    def test_in_class(self):\n        pass\n\n\ndef test_module_level():\n    pass\n",
        encoding="utf-8",
    )
    node_ids = ["tests/test_demo.py::TestDemo::test_in_class", "tests/test_demo.py::test_module_level"]
    report = tmp_path / "junit.xml"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", *node_ids],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    ran = _ran_keys(report)
    for node_id in node_ids:
        assert _junit_key(node_id) in ran, f"{node_id} ran and passed but was not recognised: {sorted(ran)}"


def test_registry_ships_as_package_data():
    pyproject = (RUNTIME_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"rule_enforcement.json"' in pyproject


def test_bundle_root_is_the_packaged_skills_bundle():
    assert re_mod._BUNDLE_ROOT.name == "skills_bundle"
    assert (re_mod._BUNDLE_ROOT / "codex-plan-phase" / "SKILL.md").is_file()


# Negative controls for check_registry, against a synthetic bundle so they do not
# depend on live rows (which are meant to change as gaps get enforcers).


@pytest.fixture
def fixture_roots(tmp_path):
    bundle = tmp_path / "bundle"
    for harness, text in (("codex", "Lanes MUST be disjoint."), ("claude", "Every lane is disjoint.")):
        skill = bundle / f"{harness}-demo"
        (skill / "scripts").mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"# demo\n\n- {text}\n", encoding="utf-8")
        (skill / "scripts" / "check.py").write_text("def check_disjoint():\n    pass\n", encoding="utf-8")
    tests = tmp_path / "runtime"
    (tests / "tests").mkdir(parents=True)
    (tests / "tests" / "test_demo.py").write_text(
        "class DemoTest:\n    def test_refuses(self):\n        pass\n", encoding="utf-8"
    )
    return bundle, tests


ENFORCED = Rule(
    id="demo.disjoint",
    skill="demo",
    quote="Lanes MUST be disjoint.",
    harness_quotes={"claude": "Every lane is disjoint."},
    status="enforced",
    enforcers=(
        Enforcer(kind="module", module="phase_loop_runtime.rule_enforcement", symbol="check_registry"),
        Enforcer(kind="skill_script", path="scripts/check.py", symbol="check_disjoint"),
    ),
    negative_control="tests/test_demo.py::DemoTest::test_refuses",
)
GAP = Rule(
    id="demo.gap",
    skill="demo",
    quote="Lanes MUST be disjoint.",
    harness_quotes={"claude": "Every lane is disjoint."},
    status="unenforced",
    unenforced_reason="gap",
    tracking="agent-harness#1",
)


def _check(roots, *rules):
    bundle, tests = roots
    return check_registry(list(rules), bundle_root=bundle, tests_root=tests)


def test_synthetic_rows_are_sound(fixture_roots):
    judgment = dataclasses.replace(GAP, id="demo.judgment", unenforced_reason="judgment", tracking="")
    assert _check(fixture_roots, ENFORCED, GAP, judgment) == []


def test_refuses_quote_that_drifted_from_the_skill_text(fixture_roots):
    problems = _check(fixture_roots, dataclasses.replace(ENFORCED, quote="Lanes MAY overlap."))
    assert problems == ["demo.disjoint: quote not found in codex-demo/SKILL.md: 'Lanes MAY overlap.'"]


def test_refuses_quote_missing_from_one_harness_copy(fixture_roots):
    problems = _check(fixture_roots, dataclasses.replace(ENFORCED, harness_quotes={}))
    assert problems == ["demo.disjoint: quote not found in claude-demo/SKILL.md: 'Lanes MUST be disjoint.'"]


def test_refuses_harness_quote_for_a_harness_that_ships_no_copy(fixture_roots):
    rule = dataclasses.replace(ENFORCED, harness_quotes={**ENFORCED.harness_quotes, "gemini": "x"})
    assert any("names 'gemini', which ships no 'demo'" in p for p in _check(fixture_roots, rule))


def test_refuses_unknown_skill(fixture_roots):
    assert any("no shipped copy of skill 'nope'" in p for p in _check(fixture_roots, dataclasses.replace(GAP, skill="nope")))


def test_refuses_module_enforcer_symbol_that_no_longer_exists(fixture_roots):
    rule = dataclasses.replace(
        ENFORCED, enforcers=(Enforcer(kind="module", module="phase_loop_runtime.rule_enforcement", symbol="gone"),)
    )
    assert any("phase_loop_runtime.rule_enforcement:gone not defined" in p for p in _check(fixture_roots, rule))


def test_refuses_skill_script_symbol_missing_from_every_shipped_copy(fixture_roots):
    rule = dataclasses.replace(
        ENFORCED, enforcers=(Enforcer(kind="skill_script", path="scripts/check.py", symbol="gone"),)
    )
    assert len([p for p in _check(fixture_roots, rule) if "check.py:gone not defined" in p]) == 2


def test_refuses_negative_control_that_no_longer_exists(fixture_roots):
    rule = dataclasses.replace(ENFORCED, negative_control="tests/test_demo.py::DemoTest::test_deleted")
    assert any("not found" in p for p in _check(fixture_roots, rule))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"enforcers": ()}, "names no enforcer"),
        ({"negative_control": ""}, "names no negative_control"),
        ({"tracking": "agent-harness#1"}, "carries unenforced_reason/tracking"),
        ({"status": "partly"}, "status must be one of"),
        ({"id": "NoDot"}, "id must look like"),
    ],
)
def test_refuses_malformed_enforced_row(fixture_roots, changes, expected):
    assert any(expected in p for p in _check(fixture_roots, dataclasses.replace(ENFORCED, **changes)))


@pytest.mark.parametrize("tracking", ["", "#1304", "1304"])
def test_refuses_gap_without_repo_qualified_tracking(fixture_roots, tracking):
    rule = dataclasses.replace(GAP, tracking=tracking)
    assert any("repo-qualified tracking ref" in p for p in _check(fixture_roots, rule))


def test_refuses_unenforced_row_that_names_an_enforcer(fixture_roots):
    rule = dataclasses.replace(GAP, enforcers=ENFORCED.enforcers)
    assert any("unenforced rule names an enforcer" in p for p in _check(fixture_roots, rule))


def test_refuses_duplicate_ids(fixture_roots):
    assert any("duplicate id" in p for p in _check(fixture_roots, GAP, GAP))


def test_refuses_wrong_schema(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"schema": "rule_enforcement.v0", "rules": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="rule_enforcement.v1"):
        load_registry(path)
