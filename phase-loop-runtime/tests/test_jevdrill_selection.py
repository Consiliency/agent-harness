"""JEVHOST §6 and §7: JEV Drill's test selection, LEARN whole-file rule, names and imports.

Collection runs in a child pytest (``--collect-only``) with a small recording plugin, so
the markers and the ``-m "not dotfiles_integration"`` selection are the real ones.
"""

import ast
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RUNTIME = Path(__file__).resolve().parents[1]
TESTS = RUNTIME / "tests"
NAMES = json.loads((TESTS / "data" / "jevdrill_test_names.json").read_text(encoding="utf-8"))

JEVDRILL_FILES = tuple(f"test_jevdrill_{name}.py" for name in
                       ("adapter", "diagnostics", "discovery", "input", "queue", "usage"))
LEARN_FILES = ("test_windows_locking.py", "test_launcher_liveness.py",
               "test_windows_processes.py", "test_windows_storage.py")
R4_FILES = ("test_jevdrill_discovery.py", "test_jevdrill_adapter.py", "test_jevdrill_queue.py",
            *LEARN_FILES)

#: JEVHOST §1: the eight controls, and whether each carries ``jevdrill_installed``.
CONTROLS = {
    "test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[alpha]": True,
    "test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[beta]": True,
    "test_jevdrill_discovery.py::test_entered_discovery_requires_harness_decomposition": True,
    "test_jevdrill_discovery.py::test_objective_tombstone_survives_restart_and_preserves_reports": True,
    "test_jevdrill_discovery.py::test_native_unsupported_observer_records_unknown_capture": False,
    "test_jevdrill_adapter.py::test_guidance_is_verified_injected_once_and_deactivated": False,
    "test_jevdrill_queue.py::test_objective_guard_reuses_anchored_transaction_and_bounds_admission": False,
    "test_jevdrill_queue.py::test_objective_guard_bounds_other_thread_contention": False,
}

#: JEVHOST §1: nominated earlier, ruled not gating; reported only.
JD084 = ("test_phase_loop_launcher.py::test_launcher_accepts_explicit_nonserialized_lease_authority",
         "test_phase_loop_launcher.py::test_supervised_launch_drains_retained_stdout_before_returning")

RECORDER = '''
import json, os

_rows = {}

def pytest_itemcollected(item):
    _rows[item.nodeid] = {"markers": sorted({m.name for m in item.iter_markers()}),
                          "selected": True}

def pytest_deselected(items):
    for item in items:
        _rows.setdefault(item.nodeid, {"markers": []})["selected"] = False

def pytest_collection_finish(session):
    with open(os.environ["JEVHOST_SELECTION_OUT"], "w", encoding="utf-8") as handle:
        json.dump(_rows, handle)
'''


def _collect(tmp_path_factory, files):
    plugin_dir = tmp_path_factory.mktemp("selection-plugin")
    (plugin_dir / "jevhost_selection_recorder.py").write_text(RECORDER, encoding="utf-8")
    out = plugin_dir / "collected.json"
    env = {key: value for key, value in os.environ.items()
           if key not in {"JEVDRILL_TEST_CLI", "JEVDRILL_TEST_PYTHON", "PYTEST_ADDOPTS",
                          "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"}}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(plugin_dir), str(RUNTIME / "src"), str(TESTS),
         *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
    env["JEVHOST_SELECTION_OUT"] = str(out)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "-p", "no:xdist", "-p", "jevhost_selection_recorder",
         "-m", "not dotfiles_integration", *(f"tests/{name}" for name in files)],
        cwd=RUNTIME, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=300, check=False)
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-4000:]
    rows = json.loads(out.read_text(encoding="utf-8"))
    return {nodeid.removeprefix("tests/"): row for nodeid, row in rows.items()}


@pytest.fixture(scope="module")
def collected(tmp_path_factory):
    return _collect(tmp_path_factory, (*JEVDRILL_FILES, *LEARN_FILES, "test_phase_loop_launcher.py"))


def test_the_eight_controls_are_collected_selected_and_split_by_install(collected):
    for nodeid, installed in CONTROLS.items():
        assert nodeid in collected, nodeid
        row = collected[nodeid]
        assert row["selected"], nodeid
        assert "dotfiles_integration" not in row["markers"], nodeid
        assert ("jevdrill_installed" in row["markers"]) is installed, nodeid
    assert sum(CONTROLS.values()) == 4 and len(CONTROLS) == 8


def test_the_seven_r4_files_deselect_nothing(collected):
    for nodeid, row in collected.items():
        if nodeid.split("::", 1)[0] in R4_FILES:
            assert row["selected"], nodeid
            assert "dotfiles_integration" not in row["markers"], nodeid
    assert {nodeid.split("::", 1)[0] for nodeid in collected} >= set(R4_FILES)


def _mark_names(decorator):
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return names


SKIP_MARKS = {"skip", "skipif", "xfail", "skipIf", "skipUnless", "expectedFailure"}


def _skips(tree):
    """Every skip-like mark, call or ``pytestmark`` in a module, by kind."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                if SKIP_MARKS & set(_mark_names(decorator)):
                    found.append(("decorator", node.name))
        elif isinstance(node, ast.Call):
            names = _mark_names(node)
            if names and names[0] in {"skip", "xfail", "skipTest", "importorskip"}:
                found.append(("call", ".".join(reversed(names))))
            elif SKIP_MARKS & set(names) and "mark" in names:
                found.append(("mark", ".".join(reversed(names))))
    return found


def test_learn_whole_file_rule_is_static():
    for name in ("test_windows_locking.py", "test_launcher_liveness.py"):
        tree = ast.parse((TESTS / name).read_text(encoding="utf-8"))
        assert _skips(tree) == [], name
    for name, reason in (("test_windows_processes.py", "Native Windows Job Object proof"),
                         ("test_windows_storage.py", "Native NTFS storage proof")):
        source = (TESTS / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(_skips(tree)) == 1, name
        module_marks = [node for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)]
        assert len(module_marks) == 1, name
        assert ast.unparse(module_marks[0].value) == (
            f"pytest.mark.skipif(os.name != 'nt', reason={reason!r})"), name


def test_collected_names_equal_the_recorded_draft_names(collected):
    assert not NAMES["renames"] and not NAMES["removals"]
    actual = {}
    for nodeid in collected:
        path, _, name = nodeid.partition("::")
        if path in (*JEVDRILL_FILES, *LEARN_FILES):
            actual.setdefault(path, set()).add(re.sub(r"\[.*\]$", "", name))
    expected = {path: set(names) for path, names in NAMES["names"].items()}
    assert set(expected) == {*JEVDRILL_FILES, *LEARN_FILES}
    # Windows-only files are collected (then skipped by their module mark) everywhere.
    assert actual == expected
    for addition in NAMES["additions"]:
        assert addition["name"] in expected[addition["file"]]


R5_NAMES = {
    "phase_loop_runtime": ("launcher", "runner", "models"),
    "phase_loop_runtime.jevdrill_adapter": ("JevDrillTransport", "JevDrillUnavailable"),
    "phase_loop_runtime.jevdrill_queue": ("ReportQueue",),
    "test_jevdrill_discovery": ("installed_discovery", "linked_task",
                                "test_installed_discovery_decomposition_two_task_launch"),
    "test_jevdrill_adapter": ("FIXTURES", "adapter_fixture"),
    "test_jevdrill_usage": ("records", "synthetic_spec", "values"),
    "phase_loop_test_utils": ("make_repo", "write_phase_plan"),
}


@pytest.mark.parametrize("module", sorted(R5_NAMES))
def test_every_r5_name_imports(module):
    imported = importlib.import_module(module)
    for name in R5_NAMES[module]:
        if module == "phase_loop_runtime":
            importlib.import_module(f"phase_loop_runtime.{name}")
        else:
            assert hasattr(imported, name), f"{module}.{name}"


def test_jd084_launcher_tests_selection_is_reported_not_gated(collected, record_property):
    # JEVHOST §1/§6: information only; never an acceptance condition.
    report = {nodeid: bool(collected.get(nodeid, {}).get("selected")) for nodeid in JD084}
    record_property("jd084_selected", json.dumps(report, sort_keys=True))
    print("JD-084 launcher tests selected (informational):", report)
