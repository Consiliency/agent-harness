"""Tests for sanctioned in-place ``replan`` lifecycle transitions (agent-harness#1968)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import plan_manifest as pm


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64

_UNSET = object()


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _init_repo_with_manifest(
    tmp_path: Path,
    *,
    status: str = "committed",
    existing_frozen: object = _UNSET,
) -> Path:
    repo = tmp_path / "repo"
    (repo / "plans" / "artifacts").mkdir(parents=True)
    (repo / "specs").mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    (repo / "specs" / "phase-plans-v14.md").write_text("# Roadmap\n", encoding="utf-8")
    (repo / "plans" / "phase-plan-v14-REPLAN.md").write_text("# Plan\n", encoding="utf-8")
    (repo / "plans" / "phase-plan-v14-OTHER.md").write_text("# Other\n", encoding="utf-8")

    row: dict[str, object] = {
        "acceptance_criteria_count": None,
        "created_at": "2026-11-09T00:00:00Z",
        "file": "plans/phase-plan-v14-REPLAN.md",
        "handoff_ref": None,
        "if_gates_produced": ["IF-0-REPLAN-1"],
        "lanes": ["SL-0"],
        "lifecycle": [],
        "owner_skill": "claude-plan-phase",
        "phase_alias": "REPLAN",
        "reflection_ref": None,
        "roadmap_ref": {
            "file": "specs/phase-plans-v14.md",
            "slug": "phase-plans-v14",
            "status": "committed",
            "type": "phase",
        },
        "slug": "v14-REPLAN",
        "status": status,
        "task_summary": None,
        "type": "phase",
        "updated_at": "2026-11-09T00:00:00Z",
    }
    if existing_frozen is not _UNSET:
        row["frozen_inputs"] = existing_frozen

    sibling = {
        "acceptance_criteria_count": None,
        "created_at": "2026-11-09T00:00:00Z",
        "file": "plans/phase-plan-v14-OTHER.md",
        "handoff_ref": None,
        "if_gates_produced": [],
        "lanes": ["SL-0"],
        "lifecycle": [],
        "owner_skill": "codex-plan-phase",
        "phase_alias": "OTHER",
        "reflection_ref": None,
        "roadmap_ref": {
            "file": "specs/phase-plans-v14.md",
            "slug": "phase-plans-v14",
            "status": "committed",
            "type": "phase",
        },
        "slug": "v14-OTHER",
        "status": "committed",
        "task_summary": None,
        "type": "phase",
        "updated_at": "2026-11-09T00:00:00Z",
    }

    manifest = {"schema_version": 1, "plans": [row, sibling]}
    (repo / "plans" / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


@pytest.mark.parametrize("initial_status", ["committed", "imported"])
def test_update_lifecycle_replan_keeps_committed_status_merges_frozen_inputs_and_passes_validators(
    tmp_path: Path, initial_status: str
) -> None:
    repo = _init_repo_with_manifest(
        tmp_path,
        status=initial_status,
        existing_frozen={"plans/artifacts/base-input.md": {"sha256": SHA_A}},
    )
    before = json.loads((repo / "plans" / "manifest.json").read_text(encoding="utf-8"))
    sibling_before = before["plans"][1]
    row_keys_before = list(before["plans"][0].keys())

    caller_metadata = {
        "superseded_plan_sha256": SHA_B,
        "frozen_inputs": {
            "plans/artifacts/base-input.md": {"sha256": SHA_A},
            "plans/artifacts/new-binding.md": {"sha256": SHA_C},
        },
        "reason": "owner decision: re-plan against landed code",
        "sweep_input": "Consiliency/agent-harness#1968",
    }
    pm.update_lifecycle(repo, "v14-REPLAN", "replan", "claude-plan-phase", caller_metadata)

    after = json.loads((repo / "plans" / "manifest.json").read_text(encoding="utf-8"))
    row = after["plans"][0]
    assert row["status"] == "committed"
    assert list(row.keys()) == row_keys_before
    assert after["plans"][1] == sibling_before
    assert row["frozen_inputs"] == {
        "plans/artifacts/base-input.md": {"sha256": SHA_A},
        "plans/artifacts/new-binding.md": {"sha256": SHA_C},
    }
    assert len(row["lifecycle"]) == 1
    event = row["lifecycle"][0]
    assert event["transition"] == "replan"
    assert event["by"] == "claude-plan-phase"
    assert event["metadata"]["superseded_plan_sha256"] == SHA_B
    assert event["metadata"]["reason"] == "owner decision: re-plan against landed code"
    assert event["metadata"]["sweep_input"] == "Consiliency/agent-harness#1968"
    assert event["metadata"]["frozen_inputs"] == {
        "plans/artifacts/base-input.md": {"sha256": SHA_A},
        "plans/artifacts/new-binding.md": {"sha256": SHA_C},
    }

    # Repeated replan and subsequent executing transition remain valid.
    pm.update_lifecycle(
        repo,
        "v14-REPLAN",
        "replan",
        "claude-plan-phase",
        {
            "superseded_plan_sha256": SHA_C,
            "frozen_inputs": {},
            "reason": "second replan with no additional frozen inputs",
        },
    )
    assert pm.validate_manifest(repo / "plans" / "manifest.json").valid
    check_result = pm.check(repo)
    assert check_result.exit_code == 0, check_result

    pm.update_lifecycle(repo, "v14-REPLAN", "executing", "claude-execute-phase", {"run_id": "r1"})
    loaded = pm.read_manifest(repo)
    assert loaded.plans[0].status == "executing"
    assert [ev.transition for ev in loaded.plans[0].lifecycle] == ["replan", "replan", "executing"]


def test_update_lifecycle_replan_with_empty_frozen_inputs_does_not_create_empty_row_field(
    tmp_path: Path,
) -> None:
    repo = _init_repo_with_manifest(tmp_path, status="committed")
    pm.update_lifecycle(
        repo,
        "v14-REPLAN",
        "replan",
        "claude-plan-phase",
        {
            "superseded_plan_sha256": SHA_A,
            "frozen_inputs": {},
            "reason": "replan without new frozen inputs",
        },
    )
    after = json.loads((repo / "plans" / "manifest.json").read_text(encoding="utf-8"))
    assert "frozen_inputs" not in after["plans"][0]
    assert pm.validate_manifest(repo / "plans" / "manifest.json").valid
    assert pm.check(repo).exit_code == 0


@pytest.mark.parametrize(
    ("existing_frozen", "incoming_frozen"),
    [
        ({"./plans/artifacts/base-input.md": {"sha256": SHA_A}}, {"plans/artifacts/base-input.md": {"sha256": SHA_D}}),
        ({"./plans/artifacts/base-input.md": {"sha256": SHA_A}}, {}),
        ({"plans/artifacts/base-input.md": {"sha256": "bad"}}, {}),
        (None, {"plans/artifacts/new.md": {"sha256": SHA_C}}),
        (None, {}),
        (["plans/artifacts/base-input.md"], {}),
    ],
)
def test_update_lifecycle_replan_rejects_malformed_or_null_existing_frozen_inputs_without_mutating_manifest(
    tmp_path: Path, existing_frozen: object, incoming_frozen: dict[str, dict[str, str]]
) -> None:
    repo = _init_repo_with_manifest(tmp_path, status="committed", existing_frozen=existing_frozen)
    before_bytes = (repo / "plans" / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="manifest entry frozen_inputs"):
        pm.update_lifecycle(
            repo,
            "v14-REPLAN",
            "replan",
            "claude-plan-phase",
            {
                "superseded_plan_sha256": SHA_B,
                "frozen_inputs": incoming_frozen,
                "reason": "reject malformed existing frozen_inputs",
            },
        )
    assert (repo / "plans" / "manifest.json").read_bytes() == before_bytes


def test_update_lifecycle_replan_refuses_detailed_entries(tmp_path: Path) -> None:
    repo = _init_repo_with_manifest(tmp_path, status="committed")
    (repo / "plans" / "detailed-example.md").write_text("# Detailed\n", encoding="utf-8")
    manifest_path = repo / "plans" / "manifest.json"
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc["plans"].append(
        {
            "acceptance_criteria_count": 1,
            "created_at": "2026-11-09T00:00:00Z",
            "file": "plans/detailed-example.md",
            "handoff_ref": None,
            "if_gates_produced": [],
            "lanes": [],
            "lifecycle": [],
            "owner_skill": "claude-plan-detailed",
            "phase_alias": None,
            "reflection_ref": None,
            "roadmap_ref": None,
            "slug": "detailed-example",
            "status": "committed",
            "task_summary": "Example detailed plan",
            "type": "detailed",
            "updated_at": "2026-11-09T00:00:00Z",
        }
    )
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    before_bytes = manifest_path.read_bytes()

    with pytest.raises(ValueError, match="only supported for phase entries"):
        pm.update_lifecycle(
            repo,
            "detailed-example",
            "replan",
            "claude-plan-detailed",
            {
                "superseded_plan_sha256": SHA_A,
                "frozen_inputs": {},
                "reason": "detailed entries are not phase replans",
            },
        )
    assert manifest_path.read_bytes() == before_bytes

    # A hand-written replan event on a detailed entry is also rejected by validate_manifest.
    doc["plans"][-1]["lifecycle"].append(
        {
            "at": "2026-11-09T15:00:00Z",
            "by": "claude-plan-detailed",
            "metadata": {
                "superseded_plan_sha256": SHA_A,
                "frozen_inputs": {},
                "reason": "hand-written detailed replan",
            },
            "transition": "replan",
        }
    )
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    validation = pm.validate_manifest(manifest_path)
    assert not validation.valid
    assert not validation.entries[-1].valid
    assert any("only valid for phase entries" in err for err in validation.entries[-1].errors)


@pytest.mark.parametrize("disallowed_status", ["executing", "completed", "failed", "orphaned"])
def test_update_lifecycle_replan_refuses_non_prestart_statuses(
    tmp_path: Path, disallowed_status: str
) -> None:
    repo = _init_repo_with_manifest(tmp_path, status=disallowed_status)
    with pytest.raises(ValueError, match="invalid lifecycle transition"):
        pm.update_lifecycle(
            repo,
            "v14-REPLAN",
            "replan",
            "claude-plan-phase",
            {
                "superseded_plan_sha256": SHA_A,
                "frozen_inputs": {},
                "reason": "should be rejected",
            },
        )


def test_update_lifecycle_replan_refuses_conflicting_existing_frozen_input_digest(
    tmp_path: Path,
) -> None:
    repo = _init_repo_with_manifest(
        tmp_path,
        status="committed",
        existing_frozen={"plans/artifacts/base-input.md": {"sha256": SHA_A}},
    )
    before_bytes = (repo / "plans" / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="different digest"):
        pm.update_lifecycle(
            repo,
            "v14-REPLAN",
            "replan",
            "claude-plan-phase",
            {
                "superseded_plan_sha256": SHA_B,
                "frozen_inputs": {"plans/artifacts/base-input.md": {"sha256": SHA_D}},
                "reason": "attempt to overwrite existing seal",
            },
        )
    assert (repo / "plans" / "manifest.json").read_bytes() == before_bytes


@pytest.mark.parametrize(
    "bad_metadata",
    [
        {"frozen_inputs": {}, "reason": "missing sha"},
        {"superseded_plan_sha256": "A" * 64, "frozen_inputs": {}, "reason": "uppercase sha"},
        {"superseded_plan_sha256": "not-a-sha", "frozen_inputs": {}, "reason": "short sha"},
        {"superseded_plan_sha256": SHA_A, "reason": "missing frozen_inputs"},
        {"superseded_plan_sha256": SHA_A, "frozen_inputs": ["plans/a.md"], "reason": "list frozen_inputs"},
        {
            "superseded_plan_sha256": SHA_A,
            "frozen_inputs": {"/abs/path.md": {"sha256": SHA_B}},
            "reason": "absolute frozen_inputs path",
        },
        {
            "superseded_plan_sha256": SHA_A,
            "frozen_inputs": {"../escape.md": {"sha256": SHA_B}},
            "reason": "parent traversal frozen_inputs path",
        },
        {
            "superseded_plan_sha256": SHA_A,
            "frozen_inputs": {"plans/a.md": {"sha256": "bad"}},
            "reason": "bad seal digest",
        },
        {
            "superseded_plan_sha256": SHA_A,
            "frozen_inputs": {"plans/a.md": {"sha256": SHA_B, "extra": "x"}},
            "reason": "extra key in seal",
        },
        {"superseded_plan_sha256": SHA_A, "frozen_inputs": {}},
        {"superseded_plan_sha256": SHA_A, "frozen_inputs": {}, "reason": "   "},
    ],
)
def test_replan_metadata_validation_rejects_malformed_payloads_in_writer_and_validators(
    tmp_path: Path, bad_metadata: dict[str, object]
) -> None:
    repo = _init_repo_with_manifest(tmp_path, status="committed")
    with pytest.raises(ValueError):
        pm.update_lifecycle(repo, "v14-REPLAN", "replan", "claude-plan-phase", bad_metadata)

    # Hand-writing the same malformed replan event fails both validate_manifest and check().
    manifest_path = repo / "plans" / "manifest.json"
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc["plans"][0]["lifecycle"].append(
        {
            "at": "2026-11-09T15:00:00Z",
            "by": "claude-plan-phase",
            "metadata": bad_metadata,
            "transition": "replan",
        }
    )
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    validation = pm.validate_manifest(manifest_path)
    assert not validation.valid
    assert not validation.entries[0].valid
    assert validation.entries[1].valid

    check_result = pm.check(repo)
    assert check_result.exit_code == 1
    assert any(
        finding.path == "plans/phase-plan-v14-REPLAN.md"
        and finding.kind == "replan-lifecycle"
        for finding in check_result.malformed
    )


def test_validators_reject_replan_as_entry_status(tmp_path: Path) -> None:
    repo = _init_repo_with_manifest(tmp_path, status="replan")
    validation = pm.validate_manifest(repo / "plans" / "manifest.json")
    assert not validation.valid
    assert any("status is invalid" in err for err in validation.entries[0].errors)

    check_result = pm.check(repo)
    assert check_result.exit_code == 1
    assert "replan-lifecycle" in pm.MANIFEST_MALFORMED_KINDS
    assert any(
        finding.path == "plans/phase-plan-v14-REPLAN.md"
        and finding.kind == "replan-lifecycle"
        for finding in check_result.malformed
    )


def test_update_lifecycle_replan_rejects_blank_by_without_changing_other_transitions(
    tmp_path: Path,
) -> None:
    repo = _init_repo_with_manifest(tmp_path, status="committed")
    with pytest.raises(ValueError, match="by must be a non-empty string"):
        pm.update_lifecycle(
            repo,
            "v14-REPLAN",
            "replan",
            "   ",
            {"superseded_plan_sha256": SHA_A, "frozen_inputs": {}, "reason": "blank actor"},
        )
    # Existing non-replan transitions keep their previous contract.
    pm.update_lifecycle(repo, "v14-REPLAN", "executing", "   ", {})
    assert pm.read_manifest(repo).plans[0].status == "executing"


@pytest.mark.parametrize("field_name", ["by", "at"])
def test_validators_reject_whitespace_only_replan_actor_or_timestamp(
    tmp_path: Path, field_name: str
) -> None:
    repo = _init_repo_with_manifest(tmp_path, status="committed")
    manifest_path = repo / "plans" / "manifest.json"
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    event = {
        "at": "2026-11-09T15:00:00Z",
        "by": "claude-plan-phase",
        "metadata": {
            "superseded_plan_sha256": SHA_A,
            "frozen_inputs": {},
            "reason": "valid metadata",
        },
        "transition": "replan",
    }
    event[field_name] = "   "
    doc["plans"][0]["lifecycle"].append(event)
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    validation = pm.validate_manifest(manifest_path)
    assert not validation.valid
    assert not validation.entries[0].valid
    assert pm.check(repo).exit_code == 1
