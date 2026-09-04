"""Static contract for superseded test-workflow cancellation."""

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"

# The workflow is repository source, not wheel/package data, so Gate A's copied
# standalone tree cannot evaluate this assertion. The full source suites and the
# workflow's own live behavior remain the load-bearing positive controls.
pytestmark = pytest.mark.skipif(
    not WORKFLOW_PATH.is_file(),
    reason="repo-only test workflow absent from standalone-from-wheel layout",
)


def test_test_workflow_cancels_only_the_same_pr_or_ref() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    # A pull_request run supersedes only the earlier runs of the SAME PR. Every
    # other event (the push to main that is the landing proof, the nightly, a
    # manual dispatch) gets a group unique to its own run_id, so it is never
    # cancelled and never replaced while queued (agent-harness#741).
    assert workflow["concurrency"] == {
        "group": (
            "${{ github.event_name == 'pull_request' "
            "&& format('test-pr-{0}', github.event.pull_request.number) "
            "|| format('test-{0}-{1}', github.ref, github.run_id) }}"
        ),
        "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
    }
