"""The shipped rule→enforcer registry stays truthful (agent-harness#1321, REPORT 1.13)."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from _dotfiles_tree import skills_bundle_present
from phase_loop_runtime import rule_enforcement as re_mod
from phase_loop_runtime.rule_enforcement import Enforcer, Rule, check_registry, load_registry

RUNTIME_ROOT = Path(__file__).resolve().parents[1]


def test_shipped_registry_is_sound():
    assert check_registry(load_registry(), tests_root=RUNTIME_ROOT) == []


PROBE_DIR = Path(__file__).resolve().parent


def _run_controls(node_ids, tmp_path, kill=""):
    """Run node_ids in a child pytest; return it, its call-phase-passed node ids, and its other records."""
    assert node_ids, "no negative control to run"
    log = tmp_path / f"reports{len(list(tmp_path.glob('reports*')))}.jsonl"
    # The child reads no configuration from outside the gate: no PYTEST_* variable, no
    # entry-point plugin, no ini file but this empty one, no conftest above RUNTIME_ROOT.
    inifile = tmp_path / "negative-control.ini"
    inifile.write_text("[pytest]\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PROBE_DIR), env.get("PYTHONPATH", "")]))
    env["NEGATIVE_CONTROL_REPORT_LOG"] = str(log)
    env["NEGATIVE_CONTROL_KILL"] = kill
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-c", str(inifile), f"--rootdir={RUNTIME_ROOT}",
         f"--confcutdir={RUNTIME_ROOT}", "-p", "no:cacheprovider", "-p", "_negative_control_probe", *node_ids],
        cwd=RUNTIME_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    # The log is written by the child above into tmp_path; it is not external input.
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    # Proof is a passed call-phase report for the exact node id, and no report of any phase
    # (subtests included) for it that skipped or failed.
    spoiled = {e["nodeid"] for e in events if "outcome" in e and e["outcome"] != "passed"}
    passed = {e["nodeid"] for e in events if e.get("when") == "call" and e.get("outcome") == "passed"} - spoiled
    return proc, passed, [e for e in events if "outcome" not in e]


@pytest.mark.skipif(not skills_bundle_present(), reason="negative controls load the sibling phase-loop-skills bundle")
def test_every_negative_control_runs_and_passes(tmp_path):
    # Existence is not proof: a control that skips here never shows its enforcer refuse.
    node_ids = [rule.negative_control for rule in load_registry() if rule.negative_control]
    proc, passed, _ = _run_controls(node_ids, tmp_path)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    for node_id in node_ids:
        assert node_id in passed, f"{node_id} did not run and pass"


def _enforcer_kill(rule, enforcer):
    if enforcer.kind == "module":
        return f"module|{rule.skill}|{enforcer.module}|{enforcer.symbol}"
    return f"skill_script|{rule.skill}|{enforcer.path}|{enforcer.symbol}"


_KILL_CASES = [
    pytest.param(rule, enforcer, id=f"{rule.id}-{enforcer.symbol}")
    for rule in load_registry()
    for enforcer in rule.enforcers
]


@pytest.mark.skipif(not skills_bundle_present(), reason="negative controls load the sibling phase-loop-skills bundle")
@pytest.mark.parametrize(("rule", "enforcer"), _KILL_CASES)
def test_disabling_a_named_enforcer_turns_its_rows_control_red(rule, enforcer, tmp_path):
    # A control that passes without one of its row's enforcers does not show that enforcer refusing.
    control = rule.negative_control
    proc, passed, records = _run_controls([control], tmp_path, kill=_enforcer_kill(rule, enforcer))
    killed = [r for r in records if r.get("killed_call")]
    assert killed, f"{control} never reached {enforcer.symbol}"
    assert control not in passed, f"{control} stays green with {enforcer.symbol} disabled"
    assert any(r.get("assertion_failed") for r in records if r.get("nodeid") == control), (
        f"{control} crashed rather than failing its assertion with {enforcer.symbol} disabled\n" + proc.stdout[-2000:]
    )
    if enforcer.kind == "skill_script":
        assert any(k["via_main"] for k in killed), f"{control} calls {enforcer.symbol} without main()"


_DEMOTE_CASES = [case for case in _KILL_CASES if case.values[1].kind == "skill_script"]


@pytest.mark.skipif(not skills_bundle_present(), reason="negative controls load the sibling phase-loop-skills bundle")
@pytest.mark.parametrize(("rule", "enforcer"), _DEMOTE_CASES)
def test_demoting_a_named_check_to_a_warning_turns_its_rows_control_red(rule, enforcer, tmp_path):
    # `enforced` means the check refuses. A control that stays green when the check only warns
    # does not show it refusing.
    control = rule.negative_control
    kill = f"demote|{rule.skill}|{enforcer.path}|{enforcer.symbol}"
    proc, passed, records = _run_controls([control], tmp_path, kill=kill)
    assert any(r.get("via_main") for r in records if r.get("killed_call")), f"{control} never reached {enforcer.symbol}"
    assert control not in passed, f"{control} stays green with {enforcer.symbol} demoted to a warning"
    assert any(r.get("assertion_failed") for r in records if r.get("nodeid") == control), proc.stdout[-2000:]


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


# Negative controls for the run-and-pass gate itself, against synthetic control files.


def _gate_against(tmp_path, monkeypatch, files, node_ids):
    tests = tmp_path / "tests"
    tests.mkdir()
    for name, source in files.items():
        (tests / name).write_text(source, encoding="utf-8")
    template = load_registry()[0]
    rows = [dataclasses.replace(template, id=f"demo.c{i}", negative_control=n) for i, n in enumerate(node_ids)]
    monkeypatch.setattr(sys.modules[__name__], "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "load_registry", lambda: rows)
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    return lambda: test_every_negative_control_runs_and_passes(report_dir)


_PASSING = "import unittest\nclass ControlTest(unittest.TestCase):\n    def test_refuses(self):\n        pass\n"
_BORROWED = ["tests/test_first.py::ControlTest::test_refuses", "tests/test_second.py::ControlTest::test_refuses"]


def test_a_skipped_control_cannot_borrow_a_same_named_pass_from_another_module(tmp_path, monkeypatch):
    skipping = _PASSING.replace("pass", "self.skipTest('never shows its enforcer refuse')")
    gate = _gate_against(tmp_path, monkeypatch, {"test_first.py": _PASSING, "test_second.py": skipping}, _BORROWED)
    with pytest.raises(AssertionError, match="test_second.py::ControlTest::test_refuses did not run and pass"):
        gate()


def test_an_outside_ini_cannot_deselect_a_control(tmp_path, monkeypatch):
    # The child reads only the gate's own ini, so this --deselect never reaches it.
    gate = _gate_against(tmp_path, monkeypatch, {"test_first.py": _PASSING, "test_second.py": _PASSING}, _BORROWED)
    (tmp_path / "pytest.ini").write_text(f"[pytest]\naddopts = --deselect={_BORROWED[1]}\n", encoding="utf-8")
    gate()


@pytest.mark.parametrize(
    "body",
    [
        "import unittest\nclass ControlTest(unittest.TestCase):\n    def test_refuses(self):\n        self.skipTest('x')\n",
        "import unittest\nclass ControlTest(unittest.TestCase):\n    @unittest.skipIf(True, 'x')\n    def test_refuses(self):\n        pass\n",
        "import unittest\nclass ControlTest(unittest.TestCase):\n    @unittest.expectedFailure\n    def test_refuses(self):\n        assert False\n",
        "import unittest\nclass ControlTest(unittest.TestCase):\n    def test_refuses(self):\n        with self.subTest(case=1):\n            self.skipTest('x')\n",
        "import pytest\nclass TestControl:\n    @pytest.mark.xfail(reason='x')\n    def test_refuses(self):\n        assert False\n",
        "import pytest\nclass TestControl:\n    @pytest.mark.parametrize('x', [])\n    def test_refuses(self, x):\n        pass\n",
        "class Helper:\n    def test_refuses(self):\n        pass\n",
    ],
    ids=["skipTest", "skipIf", "expectedFailure", "subTest-skip", "xfail", "empty-parametrize", "not-collected"],
)
def test_a_control_that_does_not_run_and_pass_fails_the_gate(tmp_path, monkeypatch, body):
    cls = "TestControl" if "class TestControl" in body else ("Helper" if "Helper" in body else "ControlTest")
    gate = _gate_against(tmp_path, monkeypatch, {"test_c.py": body}, [f"tests/test_c.py::{cls}::test_refuses"])
    with pytest.raises(AssertionError):
        gate()


def test_a_module_level_control_function_is_matched_by_its_node_id(tmp_path, monkeypatch):
    gate = _gate_against(
        tmp_path, monkeypatch, {"test_fn.py": "def test_refuses():\n    pass\n"}, ["tests/test_fn.py::test_refuses"]
    )
    gate()


def test_an_empty_registry_refuses_instead_of_running_the_whole_suite(tmp_path, monkeypatch):
    gate = _gate_against(tmp_path, monkeypatch, {}, [])
    with pytest.raises(AssertionError, match="no negative control"):
        gate()


@pytest.mark.parametrize("via", ["PYTEST_ADDOPTS", "ini addopts", "conftest setuponly"])
def test_a_control_whose_body_never_ran_is_not_execution_proof(tmp_path, monkeypatch, via):
    body = (
        "import unittest\nfrom pathlib import Path\nclass ControlTest(unittest.TestCase):\n"
        "    def test_refuses(self):\n        Path(__file__).with_name('called').touch()\n"
    )
    gate = _gate_against(tmp_path, monkeypatch, {"test_c.py": body}, ["tests/test_c.py::ControlTest::test_refuses"])
    if via == "PYTEST_ADDOPTS":
        monkeypatch.setenv("PYTEST_ADDOPTS", "--setup-only")
    elif via == "ini addopts":
        (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --setup-only\n", encoding="utf-8")
    else:
        # In-tree code is trusted to load, so this is what still needs call-phase proof.
        (tmp_path / "tests" / "conftest.py").write_text(
            "def pytest_configure(config):\n    config.option.setuponly = True\n", encoding="utf-8"
        )
    try:
        gate()
    except AssertionError:
        return
    assert (tmp_path / "tests" / "called").is_file(), "the gate accepted a control whose body never ran"


_SKIP_BODY = "def pytest_pyfunc_call(pyfuncitem):\n    return True\n"
_FORGE_SKIPPED = (
    "import pytest\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_makereport(item, call):\n"
    "    out = yield\n    r = out.get_result()\n    if r.outcome == 'skipped':\n        r.outcome = 'passed'\n        r.longrepr = None\n"
)
_FN_SENTINEL = "from pathlib import Path\ndef test_refuses():\n    Path(__file__).with_name('called').touch()\n"
_SKIPPING = "import unittest\nclass ControlTest(unittest.TestCase):\n    def test_refuses(self):\n        self.skipTest('x')\n"


@pytest.mark.parametrize("channel", ["ini addopts", "PYTEST_PLUGINS", "entry point"])
@pytest.mark.parametrize("plugin", ["skip-body", "forge-report"])
def test_an_outside_plugin_cannot_fake_a_run(tmp_path, monkeypatch, channel, plugin):
    body, node_id, source = (
        (_FN_SENTINEL, "tests/test_c.py::test_refuses", _SKIP_BODY) if plugin == "skip-body"
        else (_SKIPPING, "tests/test_c.py::ControlTest::test_refuses", _FORGE_SKIPPED)
    )
    gate = _gate_against(tmp_path, monkeypatch, {"test_c.py": body}, [node_id])
    site = tmp_path / "site"
    site.mkdir()
    (site / "outside_plugin.py").write_text(source, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(site), os.environ.get("PYTHONPATH", "")])))
    if channel == "ini addopts":
        (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -p outside_plugin\n", encoding="utf-8")
    elif channel == "PYTEST_PLUGINS":
        monkeypatch.setenv("PYTEST_PLUGINS", "outside_plugin")
    else:
        dist = site / "outside_plugin-0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: outside-plugin\nVersion: 0\n", encoding="utf-8")
        (dist / "entry_points.txt").write_text("[pytest11]\noutside = outside_plugin\n", encoding="utf-8")
    if plugin == "skip-body":
        gate()  # the plugin never loaded, so the body ran and the gate's proof is genuine
        assert (tmp_path / "tests" / "called").is_file(), "the gate accepted a control whose body never ran"
    else:
        with pytest.raises(AssertionError, match="did not run and pass"):
            gate()


def test_a_conftest_above_the_runtime_root_is_not_loaded(tmp_path, monkeypatch):
    runtime = tmp_path / "checkout" / "runtime"
    (runtime / "tests").mkdir(parents=True)
    (runtime / "tests" / "test_c.py").write_text(_SKIPPING, encoding="utf-8")
    (tmp_path / "checkout" / "conftest.py").write_text(_FORGE_SKIPPED, encoding="utf-8")
    rows = [dataclasses.replace(load_registry()[0], id="demo.c0",
                                negative_control="tests/test_c.py::ControlTest::test_refuses")]
    monkeypatch.setattr(sys.modules[__name__], "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(sys.modules[__name__], "load_registry", lambda: rows)
    report = tmp_path / "report"
    report.mkdir()
    with pytest.raises(AssertionError, match="did not run and pass"):
        test_every_negative_control_runs_and_passes(report)
