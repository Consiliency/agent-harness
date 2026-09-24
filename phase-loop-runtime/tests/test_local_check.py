"""`scripts/local_check.py` picks the tests a diff can reach (agent-harness#1029)."""
from __future__ import annotations

import importlib.util
import os
import subprocess
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
    assert tests == ["tests/test_uses_a.py", "tests/test_uses_a_leaf.py"]


def test_a_changed_test_and_ci_plumbing(lc, pkg):
    tests, reasons = lc.select(pkg, ["phase-loop-runtime/tests/test_own.py", ".github/workflows/test.yml"])
    assert tests == ["tests/test_ci_x.py", "tests/test_own.py"]
    assert any("CI plumbing" in r for r in reasons)


def test_shared_config_runs_the_whole_suite(lc, pkg):
    tests, _ = lc.select(pkg, ["phase-loop-runtime/pyproject.toml"])
    assert tests is None


def test_parenthesised_multiline_leaf_import_is_seen(lc, pkg):
    """#1031 r1 (codex): `from phase_loop_runtime.pkg import (\n    a,\n)` imports pkg.a."""
    text = (pkg / "tests" / "test_uses_a_leaf.py").read_text()
    assert lc.imports_module(text, "phase_loop_runtime.pkg.a")
    assert lc.imports_module("def f():\n    import phase_loop_runtime.pkg.a\n", "phase_loop_runtime.pkg.a")
    assert not lc.imports_module("import phase_loop_runtime.pkg.ab\n", "phase_loop_runtime.pkg.a")
    tests, _ = lc.select(pkg, ["phase-loop-runtime/src/phase_loop_runtime/pkg/a.py"])
    assert "tests/test_uses_a_leaf.py" in tests


def _git(repo, *args):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t",
                           *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def test_a_rename_reports_both_endpoints(lc, tmp_path):
    """#1031 r1 (codex): importers of the OLD module path must still be selected."""
    _git(tmp_path, "init", "-q", "-b", "main")
    src = tmp_path / "phase-loop-runtime" / "src" / "phase_loop_runtime" / "pkg"
    src.mkdir(parents=True)
    (src / "a.py").write_text("value = 1\n" * 20)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "mv", str(src / "a.py"), str(src / "b.py"))
    files = lc.changed_files(tmp_path, "main")
    assert "phase-loop-runtime/src/phase_loop_runtime/pkg/a.py" in files
    assert "phase-loop-runtime/src/phase_loop_runtime/pkg/b.py" in files


def test_the_venv_cache_key_tracks_project_metadata(lc, tmp_path):
    (tmp_path / "phase-loop-runtime").mkdir()
    pyproject = tmp_path / "phase-loop-runtime" / "pyproject.toml"
    pyproject.write_text('requires-python = ">=3.10"\n')
    before = lc.cache_key(tmp_path)
    pyproject.write_text('requires-python = ">=3.11"\n')
    assert lc.cache_key(tmp_path) != before


def test_no_linter_is_not_a_pass(lc, monkeypatch, capsys):
    monkeypatch.setattr(lc.shutil, "which", lambda name: None if name == "uvx" else name)
    monkeypatch.setattr(lc, "changed_files", lambda repo, base: [])
    monkeypatch.setenv("LOCAL_CHECK_PYTHON", lc.sys.executable)
    assert lc.main([]) == 1
    assert "FAIL" in capsys.readouterr().out


WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml"


@pytest.mark.skipif(not WORKFLOW.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_the_ci_mirrors_match_the_workflow(lc):
    """RUFF_PIN and CI_TEST_DEPS are copied from test.yml by hand; keep them honest."""
    text = WORKFLOW.read_text()
    assert f"'{lc.RUFF_PIN}'" in text
    install = next(line for line in text.splitlines() if "pip install \"./phase-loop-runtime[visual]\"" in line)
    for dep in lc.CI_TEST_DEPS:
        assert (f'"{dep}"' if dep != "pytest" else " pytest ") in install, dep


def test_changed_files_handles_odd_paths(lc, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "keep.txt").write_text("x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / 'we"ird é.py').write_text("x")
    raw = os.fsdecode(b"review-\xff.txt")  # not valid UTF-8 (#1031 r2 codex)
    try:
        (tmp_path / raw).write_text("example\n")
    except OSError:  # macOS: HFS+/APFS reject names that are not valid UTF-8 (#1031 r3)
        raw = None
    assert lc.changed_files(tmp_path, "main") == sorted(p for p in (raw, 'we"ird é.py') if p)


def test_a_changed_script_selects_the_tests_that_name_it(lc, pkg):
    (pkg / "tests" / "test_runs_tool.py").write_text('SCRIPT = ROOT / "scripts" / "tool.py"\n')
    tests, _ = lc.select(pkg, ["phase-loop-runtime/scripts/tool.py"])
    assert tests == ["tests/test_runs_tool.py"]


def test_an_unparsable_importer_fails_open(lc):
    """#1031 r2 (claude): a host Python older than the test's syntax must not drop it."""
    newer = "match x:\n    case 1: pass\nfrom phase_loop_runtime.foo import f\n"
    if lc.imported_modules(newer) is None:  # host cannot parse `match`
        assert lc.imports_module(newer, "phase_loop_runtime.foo")
    assert lc.imports_module("def (:\nimport phase_loop_runtime.foo\n", "phase_loop_runtime.foo")
    assert lc.imports_module("\ufeffimport phase_loop_runtime.foo\n", "phase_loop_runtime.foo")
    assert lc.imports_module("x = '\\0'\0\nimport phase_loop_runtime.foo\n", "phase_loop_runtime.foo")
