"""Static contract for superseded test-workflow cancellation."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_test_workflow_cancels_only_the_same_pr_or_ref() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    )

    assert workflow["concurrency"] == {
        "group": "test-${{ github.event.pull_request.number || github.ref }}",
        "cancel-in-progress": True,
    }
