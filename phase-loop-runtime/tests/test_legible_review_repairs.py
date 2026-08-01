from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from phase_loop_runtime import legible_evidence
from phase_loop_runtime.plan_manifest import check
from phase_loop_test_utils import make_repo


def _commit_plan(repo: Path, name: str = "phase-plan-v1-RUNNER.md") -> str:
    rel = f"plans/{name}"
    (repo / rel).write_text("---\nphase: RUNNER\n---\n# Runner\n", encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add plan"], cwd=repo, check=True, capture_output=True)
    return rel


def test_legacy_fable_observation_without_external_status_remains_pending(tmp_path, monkeypatch):
    raw = {
        "issue": {"number": 396, "state": "OPEN", "stateReason": None},
        "route": {"provider": "first-party-claude", "capability": "ok"},
        "leg": {
            "status": "UNAVAILABLE",
            "final_verdict_token": "tui_adapter_required",
            "elapsed_ms": 1,
        },
        "response": {},
    }
    monkeypatch.setattr(legible_evidence, "_invoke_reviewtruth_fable_adapter", lambda *args, **kwargs: raw)

    record = legible_evidence.run_reviewtruth_fable_probe(
        tmp_path, repository="Consiliency/agent-harness", issue=396, model="claude-fable-5"
    )

    assert record.state == "pending"


def test_manifest_check_rejects_extra_registered_plan(tmp_path):
    repo = make_repo(tmp_path)
    canonical = _commit_plan(repo)
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps({"plans": [{"file": canonical}, {"file": "plans/phase-plan-v1-GHOST.md"}]}),
        encoding="utf-8",
    )

    result = check(repo)

    assert result.exit_code == 1
    assert [(item.path, item.kind) for item in result.malformed] == [
        ("plans/phase-plan-v1-GHOST.md", "extra")
    ]


def test_manifest_check_rejects_duplicate_registered_plan_path(tmp_path):
    repo = make_repo(tmp_path)
    canonical = _commit_plan(repo)
    manifest = repo / "plans" / "manifest.json"
    manifest.write_text(
        json.dumps({"plans": [{"file": canonical}, {"file": canonical}]}),
        encoding="utf-8",
    )

    result = check(repo)

    assert result.exit_code == 1
    assert [(item.path, item.kind) for item in result.malformed] == [(canonical, "duplicate")]


def test_legible_verify_rejects_head_that_does_not_resolve(tmp_path):
    repo = make_repo(tmp_path)
    args = SimpleNamespace(repo=str(repo), stage="candidate", head="0" * 40)
    status_record = {"roadmaps": []}

    with (
        patch.object(legible_evidence, "collect_roadmap_status", return_value=status_record),
        patch.object(legible_evidence, "validate_roadmap_status_evidence"),
    ):
        assert legible_evidence._cmd_verify(args) == 1
