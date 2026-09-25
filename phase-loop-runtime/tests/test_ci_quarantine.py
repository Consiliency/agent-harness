"""The quarantine marker stays small, cited, exact and pull-request-only (agent-harness#1029).

A test marked `@pytest.mark.quarantine(reason="agent-harness#N")` is a known flake. test.yml
sets `PHASE_LOOP_DESELECT_QUARANTINE=1` on pull_request only, and the conftest hook
(`tests/_quarantine.py`) then drops exactly the marked items -- by MARKER, never by node-ID
prefix (pytest's `--deselect` is a prefix match: agent-harness#1030 r1/r2). Push, nightly and
Gate A run them. The register is debt, not an off switch:

- every mark names the issue that tracks the flake, qualified with the repo;
- more than 5 marked NODES aborts collection (a class/module mark counts per node);
- module-level quarantine is refused outright.

Whether each cited issue is still OPEN is a network fact; the reviewer checks it when a mark
is added, and the cap bounds how much can hide here meanwhile.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from _quarantine import QUARANTINE_CAP, QUARANTINE_ENV

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"
PUBLISH_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "publish-pypi.yml"

# `mark.quarantine` covers both `pytest.mark.quarantine` and `from pytest import mark`.
_MARK = re.compile(r"\bmark\.quarantine\b(?P<call>\([^)]*\))?")
_REASON = re.compile(r'^\(reason="agent-harness#\d+"\)$')


def _sources():
    return [p for p in sorted(TESTS_DIR.rglob("*.py"))
            if p.name not in (Path(__file__).name, "_quarantine.py")]


def quarantine_marks() -> list[tuple[str, str]]:
    """(file, the mark's call text) for every quarantine mark under tests/."""
    return [(path.name, match.group("call") or "")
            for path in _sources()
            for match in _MARK.finditer(path.read_text(encoding="utf-8"))]


def test_every_quarantine_mark_cites_its_tracking_issue() -> None:
    bad = [(name, call) for name, call in quarantine_marks() if not _REASON.match(call)]
    assert not bad, f'quarantine marks must be quarantine(reason="agent-harness#N"): {bad}'


def test_the_textual_register_is_capped() -> None:
    marks = quarantine_marks()
    assert len(marks) <= QUARANTINE_CAP, f"{len(marks)} quarantine marks (cap {QUARANTINE_CAP})"


def _module_level_quarantine(text: str) -> bool:
    """Does a module- or class-level `pytestmark` assignment -- or a class DECORATOR --
    mention quarantine? Either quarantines many tests with one mark.

    Parsed, not regexed: a list entry containing `]` hid a later mark from the old regex
    (agent-harness#1036, F012). Unparsable files fall back to a plain text search."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return "pytestmark" in text and "quarantine" in text

    def module_scope(nodes):
        # Module and class scope, through if/try/with/for/while/match blocks; not function
        # bodies (#1037 r1: `if True:\n    pytestmark = ...` is module-level, and a class
        # body's pytestmark quarantines the whole class -- both were caught by the regex).
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            yield node
            yield from module_scope(ast.iter_child_nodes(node))

    for node in module_scope(tree.body):
        # `@pytest.mark.quarantine(...)` on a class marks every method (agent-harness#1038).
        if isinstance(node, ast.ClassDef) and any(
                "quarantine" in ast.unparse(d) for d in node.decorator_list):
            return True
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            if node.value is not None and "quarantine" in ast.unparse(node.value):
                return True
    return False


def test_no_module_level_quarantine() -> None:
    offenders = [p.name for p in _sources()
                 if _module_level_quarantine(p.read_text(encoding="utf-8"))]
    assert not offenders, f"quarantine one test at a time, not a module or class: {offenders}"


def test_the_static_checks_can_fail(tmp_path, monkeypatch) -> None:
    for i in range(QUARANTINE_CAP + 1):
        (tmp_path / f"test_fake_{i}.py").write_text(
            f'@pytest.mark.quarantine(reason="flaky {i}")\ndef test_x(): pass\n'
        )
    (tmp_path / "test_module.py").write_text(
        'pytestmark = [\n    pytest.mark.parametrize("x", [1]),\n    pytest.mark.quarantine,\n]\n'
    )
    monkeypatch.setattr(sys.modules[__name__], "TESTS_DIR", tmp_path)
    with pytest.raises(AssertionError, match="must be quarantine"):
        test_every_quarantine_mark_cites_its_tracking_issue()
    with pytest.raises(AssertionError, match="cap"):
        test_the_textual_register_is_capped()
    with pytest.raises(AssertionError, match="not a module"):
        test_no_module_level_quarantine()


@pytest.mark.skipif(not WORKFLOW_PATH.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_only_the_hosted_suite_step_enables_it_and_only_on_pull_requests() -> None:
    jobs = yaml.safe_load(WORKFLOW_PATH.read_text())["jobs"]
    enabled = [(job, step.get("name")) for job, spec in jobs.items()
               for step in spec.get("steps", []) if QUARANTINE_ENV in (step.get("env") or {})]
    assert enabled == [("pytest", "Run standalone test suite")], enabled
    step = next(s for s in jobs["pytest"]["steps"] if s.get("name") == "Run standalone test suite")
    assert step["env"][QUARANTINE_ENV] == "${{ github.event_name == 'pull_request' && '1' || '0' }}"
    # Exactly one mention anywhere: no job-level env, no `>> $GITHUB_ENV` export (r3 claude).
    assert WORKFLOW_PATH.read_text().count(QUARANTINE_ENV) == 1
    # Unconditional: a renamed publish workflow must red this, not silently skip it (F026).
    assert PUBLISH_WORKFLOW_PATH.is_file(), f"{PUBLISH_WORKFLOW_PATH} moved; update this guard"
    assert QUARANTINE_ENV not in PUBLISH_WORKFLOW_PATH.read_text()


def _run(tmp_path: Path, body: str, enabled: bool) -> subprocess.CompletedProcess:
    """Run pytest on a synthetic tree whose conftest uses the REAL hook module."""
    (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(TESTS_DIR)!r})
        from _quarantine import deselect_quarantined
        def pytest_collection_modifyitems(config, items):
            deselect_quarantined(config, items)
    """))
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    quarantine(reason): x\n    dotfiles_integration: x\n"
    )
    (tmp_path / "test_example.py").write_text("import pytest\n" + textwrap.dedent(body))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_") and k not in ("FORCE_COLOR", "PY_COLORS")}
    env[QUARANTINE_ENV] = "1" if enabled else "0"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--color=no", "-p", "no:cacheprovider", "-rA", str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )


_COLLIDING = r'''
    @pytest.mark.dotfiles_integration
    @pytest.mark.quarantine(reason="agent-harness#1")
    def test_check(): pass

    def test_check_regression(): assert False

    @pytest.mark.quarantine(reason="agent-harness#1")
    @pytest.mark.parametrize("value", [0], ids=[r"a\b"])
    def test_flaky(value): pass

    @pytest.mark.parametrize("value", [0], ids=[r"a\b_more"])
    def test_flaky_sibling(value): assert False
'''


def test_marked_items_are_deselected_exactly_never_a_prefix_sibling(tmp_path) -> None:
    """agent-harness#1030 r1/r2: prefix siblings, a double mark, and a backslash id."""
    result = _run(tmp_path, _COLLIDING, enabled=True)
    assert "2 failed" in result.stdout and "2 deselected" in result.stdout, result.stdout
    assert "FAILED test_example.py::test_check_regression" in result.stdout
    assert "test_flaky_sibling" in result.stdout.split("short test summary", 1)[1]


def test_disabled_runs_everything(tmp_path) -> None:
    result = _run(tmp_path, "@pytest.mark.quarantine(reason='x')\ndef test_q(): assert False\n", enabled=False)
    assert "1 failed" in result.stdout and "deselected" not in result.stdout, result.stdout


@pytest.mark.parametrize("marked,aborts", [(QUARANTINE_CAP, False), (QUARANTINE_CAP + 1, True)])
def test_the_node_cap_aborts_collection(tmp_path, marked, aborts) -> None:
    """One over the cap is a usage error (exit 4), at the cap
    it is not -- an unmarked test keeps a non-aborting run from exiting 5 (r3 claude)."""
    # Each test marked on itself (a class-wide mark is refused outright, agent-harness#1044).
    body = "".join(f'@pytest.mark.quarantine(reason="x")\ndef test_{i}(): pass\n' for i in range(marked))
    body += "def test_unmarked(): pass\n"
    result = _run(tmp_path, body, enabled=True)
    output = result.stdout + result.stderr
    if aborts:
        assert result.returncode == 4 and "cap 5" in output, output
    else:
        assert result.returncode == 0 and f"{marked} deselected" in output, output


def test_the_real_conftest_deselects_every_marked_node(tmp_path) -> None:
    """Wiring: the real conftest calls the hook (deleting the call reds this)."""
    files = sorted({f"tests/{name}" for name, _ in quarantine_marks()})
    if not files:
        pytest.skip("no quarantined tests to wire-check")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_") and k not in ("FORCE_COLOR", "PY_COLORS")}
    base = [sys.executable, "-m", "pytest", "--collect-only", "-q", "--color=no", "-p", "no:cacheprovider", *files]

    def run(extra, value):
        return subprocess.run(base + extra, cwd=TESTS_DIR.parent, capture_output=True, text=True,
                              env={**env, QUARANTINE_ENV: value, "PYTHONPATH": "src:tests"}).stdout
    marked = [line for line in run(["-m", "quarantine"], "0").splitlines() if "::" in line]
    assert marked
    assert f"({len(marked)} deselected)" in run([], "1"), "the conftest hook is not wired"


@pytest.mark.parametrize("source,flagged", [
    ('pytestmark = [\n    pytest.mark.parametrize("x", [1]),\n    pytest.mark.quarantine,\n]\n', True),
    ("if True:\n    pytestmark = pytest.mark.quarantine(reason='x')\n", True),       # #1037 r1
    ("try:\n    pass\nexcept Exception:\n    pytestmark = [pytest.mark.quarantine]\n", True),
    ("pytestmark: list = [pytest.mark.quarantine]\n", True),
    ("pytestmark += [pytest.mark.quarantine]\n", True),
    ("def f():\n    pytestmark = pytest.mark.quarantine\n", False),                 # not module scope
    ("class T:\n    pytestmark = pytest.mark.quarantine\n", True),                  # whole class
    ("@pytest.mark.quarantine(reason='x')\nclass TestMany:\n    def test_a(self): pass\n", True),
    ("if True:\n    @pytest.mark.quarantine(reason='x')\n    class T:\n        pass\n", True),
    ("@pytest.mark.quarantine(reason='x')\ndef test_one(): pass\n", False),         # one test: allowed
    ("class T:\n    @pytest.mark.quarantine(reason='x')\n    def test_m(self): pass\n", False),
    ("with ctx():\n    pytestmark = [pytest.mark.quarantine]\n", True),
    ("pytestmark = [pytest.mark.slow]\n", False),
])
def test_module_level_quarantine_detection(source, flagged) -> None:
    assert _module_level_quarantine(source) is flagged


@pytest.mark.parametrize("enabled", [False, True])
def test_inherited_quarantine_is_refused_on_every_run(tmp_path, enabled) -> None:
    """agent-harness#1044 r1 (codex): an aliased class decorator evades the text scan, so the
    collection hook refuses any quarantine a test inherits, whether or not deselection is on."""
    body = ("from pytest import mark\n"
            "group_mark = mark.quarantine(reason='agent-harness#1')\n"
            "@group_mark\n"
            "class TestMany:\n"
            "    def test_a(self): pass\n"
            "    def test_b(self): pass\n"
            "def test_unmarked(): pass\n")
    result = _run(tmp_path, body, enabled=enabled)
    output = result.stdout + result.stderr
    assert result.returncode == 4 and "inherited from a class or module" in output, output


def test_own_and_param_marks_are_not_inherited(tmp_path) -> None:
    body = ('@pytest.mark.quarantine(reason="agent-harness#1")\n'
            "def test_own(): pass\n"
            '@pytest.mark.parametrize("v", [pytest.param(1, marks=pytest.mark.quarantine(reason="x")), 2])\n'
            "def test_param(v): pass\n")
    result = _run(tmp_path, body, enabled=True)
    assert result.returncode == 0 and "2 deselected" in result.stdout, result.stdout + result.stderr
