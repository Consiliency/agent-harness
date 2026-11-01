"""Every required status check reports on the merge queue's ``merge_group`` event.

The merge queue waits for each required check on the queue commit. A required check
whose workflow does not listen on ``merge_group`` (or whose job never runs there) never
reports, and the queue holds that entry until its timeout. These are the contexts
branch protection on ``main`` requires (CONTRIBUTING.md lists them).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# required context -> (workflow file, job id)
REQUIRED_CHECKS = {
    "suite gate": ("test.yml", "gate"),
    "lint (pyflakes)": ("test.yml", "lint"),
    "chronology retention guard": ("test.yml", "chronology-retention"),
    "docs-freshness audit": ("docs-audit.yml", "docs-audit"),
    "gitleaks": ("scrub.yml", "gitleaks"),
    "check": ("release-consistency.yml", "check"),
}

pytestmark = pytest.mark.skipif(
    not (WORKFLOWS / "test.yml").is_file(),
    reason="repo-only workflows absent from standalone-from-wheel layout",
)


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("context", sorted(REQUIRED_CHECKS))
def test_required_check_runs_on_merge_group(context: str) -> None:
    filename, job_id = REQUIRED_CHECKS[context]
    workflow = _load(filename)
    triggers = workflow.get("on", workflow.get(True))
    # No path or branch filter: a filtered-out queue commit would never report.
    assert triggers["merge_group"] == {"types": ["checks_requested"]}, filename
    job = workflow["jobs"][job_id]
    assert job.get("name", job_id) == context
    # The job itself runs on every event (the gate aggregates with always()).
    assert job.get("if") in (None, "always()"), (context, job.get("if"))


def test_docs_audit_diffs_the_queued_pr_against_the_group_base() -> None:
    step = next(
        s for s in _load("docs-audit.yml")["jobs"]["docs-audit"]["steps"]
        if "docs-audit" in s.get("run", "")
    )
    assert step["env"]["DOCS_AUDIT_PUSH_BEFORE"] == (
        "${{ github.event.before || github.event.merge_group.base_sha }}"
    )
