"""`scripts/local_check.py` picks the tests a diff can reach (agent-harness#1029)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "local_check.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file(), reason="scripts/ is absent from the standalone consumer layout"
)


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("local_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pkg(tmp_path):
    root = tmp_path / "phase-loop-runtime"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_uses_a.py").write_text("from phase_loop_runtime.pkg.a import thing\n")
    (root / "tests" / "test_uses_a_leaf.py").write_text("from phase_loop_runtime.pkg import (\n    a,\n)\n")
    (root / "tests" / "test_uses_ab.py").write_text("import phase_loop_runtime.pkg.ab\n")
    (root / "tests" / "test_ci_x.py").write_text("")
    (root / "tests" / "test_own.py").write_text("")
    return root


def test_module_name(lc):
    assert lc.module_name("phase-loop-runtime/src/phase_loop_runtime/pkg/a.py") == "phase_loop_runtime.pkg.a"
    assert lc.module_name("phase-loop-runtime/src/phase_loop_runtime/pkg/__init__.py") == "phase_loop_runtime.pkg"
    assert lc.module_name("phase-loop-runtime/tests/test_x.py") is None


def test_a_changed_module_selects_its_importers_and_not_a_prefix_namesake(lc, pkg):
    tests, _ = lc.select(pkg, ["phase-loop-runtime/src/phase_loop_runtime/pkg/a.py"])
    # `pkg.ab` shares the prefix `pkg.a` but is a different module: it must not be picked.
    assert tests == ["tests/test_uses_a.py"]


def test_a_changed_test_and_ci_plumbing(lc, pkg):
    tests, reasons = lc.select(pkg, ["phase-loop-runtime/tests/test_own.py", ".github/workflows/test.yml"])
    assert tests == ["tests/test_ci_x.py", "tests/test_own.py"]
    assert any("CI plumbing" in r for r in reasons)


def test_shared_config_runs_the_whole_suite(lc, pkg):
    tests, _ = lc.select(pkg, ["phase-loop-runtime/pyproject.toml"])
    assert tests is None


def test_parenthesised_leaf_import_is_seen(lc, pkg):
    """`from phase_loop_runtime.pkg import (a,)` -- the leaf may sit on the next line."""
    text = (pkg / "tests" / "test_uses_a_leaf.py").read_text()
    assert lc.imports_module("from phase_loop_runtime.pkg import (a, b)", "phase_loop_runtime.pkg.a")
    # Multi-line parenthesised imports are a known limit of the line-oriented match;
    # pin it so a change in behaviour is deliberate.
    assert not lc.imports_module(text, "phase_loop_runtime.pkg.a")
