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

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"

MAX_QUARANTINED = 5
_MARK = re.compile(r"pytest\.mark\.quarantine\b(?P<call>\([^)]*\))?")
_REASON = re.compile(r'^\(reason="agent-harness#\d+"\)$')


def quarantine_marks() -> list[tuple[str, str]]:
    """(file, the mark's call text) for every quarantine mark under tests/."""
    found = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for match in _MARK.finditer(path.read_text(encoding="utf-8")):
            found.append((path.name, match.group("call") or ""))
    return found


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
    guard = [i for i in range(uses[0] - 1, max(uses[0] - 6, -1), -1)
             if lines[i].strip() == 'if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then']
    assert guard, "the quarantine deselect is no longer inside the pull_request guard"
    assert lines[uses[0] + 1].strip() == "fi", "the pull_request guard must close right after the loop"


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
