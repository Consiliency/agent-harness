"""The quarantine marker stays small, cited, and pull-request-only (agent-harness#1029).

A test marked `@pytest.mark.quarantine(reason="agent-harness#N")` is a known flake:
pull-request CI deselects it so an unrelated red does not force a rerun, while push,
nightly and Gate A still run it. The marker is a debt register, not an off switch:

- every mark names the issue that tracks the flake, qualified with the repo;
- the register is capped, so it cannot quietly become where failing tests go;
- the workflow deselects marked nodes ONLY under the pull_request guard.

Whether each cited issue is still OPEN is a network fact; the reviewer checks it when
a mark is added, and the cap bounds how much can hide here meanwhile.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"

MAX_QUARANTINED = 5
# `mark.quarantine` covers both `pytest.mark.quarantine` and `from pytest import mark`.
_MARK = re.compile(r"\bmark\.quarantine\b(?P<call>\([^)]*\))?")
_MODULE_MARK = re.compile(r"(?m)^\s*pytestmark\s*=.*\bquarantine\b")
_REASON = re.compile(r'^\(reason="agent-harness#\d+"\)$')


def quarantine_marks() -> list[tuple[str, str]]:
    """(file, the mark's call text) for every quarantine mark under tests/."""
    found = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for match in _MARK.finditer(path.read_text(encoding="utf-8")):
            found.append((path.name, match.group("call") or ""))
    return found


def test_no_module_level_quarantine() -> None:
    """A module-level mark quarantines every node in the file for one textual mark;
    the workflow's per-node cap would catch it, but only on a PR run -- refuse it here."""
    offenders = [p.name for p in sorted(TESTS_DIR.rglob("*.py"))
                 if p.name != Path(__file__).name and _MODULE_MARK.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"quarantine one test at a time, not a module: {offenders}"


def test_every_quarantine_mark_cites_its_tracking_issue() -> None:
    bad = [(name, call) for name, call in quarantine_marks() if not _REASON.match(call)]
    assert not bad, f'quarantine marks must be quarantine(reason="agent-harness#N"): {bad}'


def test_the_quarantine_register_is_capped() -> None:
    marks = quarantine_marks()
    assert len(marks) <= MAX_QUARANTINED, (
        f"{len(marks)} quarantined tests (cap {MAX_QUARANTINED}): fix one before adding another"
    )


@pytest.mark.skipif(not WORKFLOW_PATH.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_the_workflow_deselects_quarantine_on_pull_requests_only() -> None:
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    uses = [i for i, line in enumerate(lines) if "-m quarantine" in line]
    assert len(uses) == 1, f"expected exactly one quarantine collection, found lines {uses}"
    # The collection closes a `while read` loop opened directly under the PR guard.
    guard = [i for i in range(uses[0] - 1, max(uses[0] - 25, -1), -1)
             if lines[i].strip() == 'if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then']
    assert guard, "the quarantine deselect is no longer inside the pull_request guard"
    assert lines[uses[0] + 1].strip() == "fi", "the pull_request guard must close right after the loop"
    block = "\n".join(lines[guard[0]:uses[0] + 1])
    assert "prefix collision" in block and f'-gt {MAX_QUARANTINED} ]' in block, (
        "the PR block must keep its prefix-collision and per-node cap checks"
    )


def test_the_checks_see_a_mark_they_should_reject(tmp_path, monkeypatch) -> None:
    """Falsifier: an uncited mark and an over-cap register are both caught."""
    for i in range(MAX_QUARANTINED + 1):
        (tmp_path / f"test_fake_{i}.py").write_text(
            f'@pytest.mark.quarantine(reason="flaky {i}")\ndef test_x(): pass\n'
        )
    monkeypatch.setattr(sys.modules[__name__], "TESTS_DIR", tmp_path)
    with pytest.raises(AssertionError, match="must be quarantine"):
        test_every_quarantine_mark_cites_its_tracking_issue()
    with pytest.raises(AssertionError, match="cap"):
        test_the_quarantine_register_is_capped()


def _pr_quarantine_snippet() -> str:
    """The workflow's PR-only quarantine block, verbatim (the `if` through its `fi`)."""
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.strip() == 'if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then'
                 and any("-m quarantine" in later for later in lines[i:i + 20]))
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == indent + "fi")
    return textwrap.dedent("\n".join(lines[start:end + 1]))


def _run_snippet(tree: Path, event: str) -> subprocess.CompletedProcess:
    bindir = tree / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "python").symlink_to(sys.executable)
    script = "set -euo pipefail\nsuite_args=()\n" + _pr_quarantine_snippet() + \
        '\nprintf "ARG %s\\n" "${suite_args[@]+"${suite_args[@]}"}"\n'
    env = {**os.environ, "GITHUB_EVENT_NAME": event, "PATH": f"{bindir}:{os.environ['PATH']}"}
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(["bash", "-c", script], cwd=tree, env=env, capture_output=True, text=True)


def _tree(tmp_path: Path, tests: str) -> Path:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nmarkers = ["quarantine(reason): x", "dotfiles_integration: x"]\n'
    )
    (tmp_path / "tests" / "test_example.py").write_text("import pytest\n" + tests)
    return tmp_path


@pytest.mark.skipif(not WORKFLOW_PATH.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_the_real_snippet_deselects_exactly_the_marked_node(tmp_path) -> None:
    tree = _tree(tmp_path, textwrap.dedent("""
        @pytest.mark.quarantine(reason="agent-harness#1")
        def test_flaky(): pass
        def test_other(): pass
    """))
    result = _run_snippet(tree, "pull_request")
    assert result.returncode == 0, result.stderr
    assert "ARG --deselect=tests/test_example.py::test_flaky" in result.stdout.splitlines()
    assert result.stdout.count("ARG --deselect") == 1
    push = _run_snippet(_tree(tmp_path / "push", "def test_a(): pass\n"), "push")
    assert push.returncode == 0 and "--deselect" not in push.stdout


@pytest.mark.skipif(not WORKFLOW_PATH.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_a_prefix_collision_fails_closed(tmp_path) -> None:
    """agent-harness#1030 r1 (codex): --deselect is a PREFIX match, so a quarantined
    `test_check` would silently drop an unmarked `test_check_regression`."""
    tree = _tree(tmp_path, textwrap.dedent("""
        @pytest.mark.quarantine(reason="agent-harness#1")
        def test_check(): pass
        def test_check_regression(): assert False
    """))
    result = _run_snippet(tree, "pull_request")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "prefix collision" in result.stderr
    assert "--deselect" not in result.stdout


@pytest.mark.skipif(not WORKFLOW_PATH.is_file(), reason="CI plumbing is absent from the standalone layout")
def test_the_per_node_cap_fails_closed(tmp_path) -> None:
    """A class-level mark counts once textually but quarantines every method."""
    methods = "".join(f"    def test_{i}(self): pass\n" for i in range(MAX_QUARANTINED + 1))
    tree = _tree(tmp_path, '@pytest.mark.quarantine(reason="agent-harness#1")\nclass TestMany:\n' + methods)
    result = _run_snippet(tree, "pull_request")
    assert result.returncode == 1 and "more than 5" in result.stderr, result.stdout + result.stderr
