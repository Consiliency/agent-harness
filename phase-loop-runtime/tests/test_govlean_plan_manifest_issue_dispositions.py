"""EC-GOVLEAN-6 / IF-0-GOVLEAN-4 — typed phase-closeout issue dispositions.

Freeze the tests-only contract for ``IssueDisposition`` and the ``completed``
gate on ``update_lifecycle``. Enrollment lives outside the ledger: callers
supply the externally enrolled ``issue_inventory`` and matching
``issue_dispositions``. The gate is phase-only. Structured writes must keep
existing per-entry extension fields such as ``lifecycle_events``
(agent-harness#548).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from .govlean_freeze_receipt import govlean_api_available
from phase_loop_runtime import plan_manifest
from phase_loop_runtime.plan_manifest import (
    DotfilesPlanEntry,
    DotfilesPlanLifecycleEvent,
    DotfilesPlanRef,
    append_entry,
    read_manifest,
    update_lifecycle,
    validate_manifest,
)


pytestmark = pytest.mark.skipif(
    not govlean_api_available("phase_loop_runtime.plan_manifest", "IssueDisposition"),
    reason="GOVLEAN issue-disposition capability absent",
)


PHASE = "GOVLEAN"
CLOSED_DISPOSITIONS = frozenset(
    {"closed", "folded_into_successor", "carried_with_owner"}
)
ISSUE_DISPOSITION_FIELDS = frozenset(
    {"issue_id", "phase", "disposition", "owner", "successor_plan"}
)

_CONFORM_LIFECYCLE_EVENTS = [
    {
        "status": "executing",
        "at": "2026-08-13T01:15:00+00:00",
        "by": "claude-coordination-session",
        "note": "retroactive executing record (agent-harness#548 preservation probe)",
    },
    {
        "status": "completed",
        "at": "2026-08-13T01:15:00+00:00",
        "by": "claude-coordination-session",
        "note": "maintainer-ratified closeout retained as an unmodeled extension field",
    },
]
_CONFORM_EXTENSION_NOTE = {
    "source": "agent-harness#548",
    "kind": "per-entry-extension",
    "retained": True,
}


def _issue_disposition_cls() -> Any:
    cls = getattr(plan_manifest, "IssueDisposition", None)
    assert cls is not None, (
        "EC-GOVLEAN-6: phase_loop_runtime.plan_manifest.IssueDisposition is absent"
    )
    return cls


def _closed_record(
    *,
    issue_id: str = "agent-harness#548",
    phase: str = PHASE,
    disposition: str = "closed",
    owner: str = "sl1-owner",
    successor_plan: str | None = None,
    include_successor: bool = False,
) -> Any:
    cls = _issue_disposition_cls()
    kwargs: dict[str, Any] = {
        "issue_id": issue_id,
        "phase": phase,
        "disposition": disposition,
        "owner": owner,
    }
    if include_successor or successor_plan is not None:
        kwargs["successor_plan"] = successor_plan
    return cls(**kwargs)


def _disposition_payload(
    *,
    issue_id: str = "agent-harness#548",
    phase: str = PHASE,
    disposition: str = "closed",
    owner: str | None = "sl1-owner",
    successor_plan: str | None = None,
    include_owner: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "issue_id": issue_id,
        "phase": phase,
        "disposition": disposition,
    }
    if include_owner:
        payload["owner"] = owner
    if successor_plan is not None:
        payload["successor_plan"] = successor_plan
    if extra:
        payload.update(extra)
    return payload


def _phase_entry(
    *,
    slug: str = "v10-GOVLEAN",
    file: str = "plans/phase-plan-v10-GOVLEAN.md",
    phase_alias: str = PHASE,
    status: str = "committed",
) -> DotfilesPlanEntry:
    timestamp = "2026-08-15T00:00:00Z"
    return DotfilesPlanEntry(
        slug=slug,
        file=file,
        type="phase",
        status=status,
        created_at=timestamp,
        updated_at=timestamp,
        owner_skill="codex-plan-phase",
        handoff_ref=".dev-skills/handoffs/codex-plan-phase/run.md",
        roadmap_ref=DotfilesPlanRef(
            slug="phase-plans-v10",
            file="specs/phase-plans-v10.md",
            type="phase",
            status="committed",
        ),
        phase_alias=phase_alias,
        if_gates_produced=("IF-0-GOVLEAN-4",),
        lanes=("SL-0", "SL-1"),
        lifecycle=(
            DotfilesPlanLifecycleEvent(
                transition="committed",
                by="codex-plan-phase",
                at=timestamp,
                metadata={"handoff_ref": ".dev-skills/handoffs/codex-plan-phase/run.md"},
            ),
        ),
    )


def _detailed_entry() -> DotfilesPlanEntry:
    timestamp = "2026-08-15T00:00:00Z"
    return DotfilesPlanEntry(
        slug="detailed-example",
        file="plans/detailed-example.md",
        type="detailed",
        status="committed",
        created_at=timestamp,
        updated_at=timestamp,
        owner_skill="codex-plan-detailed",
        task_summary="Example detailed plan",
        acceptance_criteria_count=1,
        lifecycle=(
            DotfilesPlanLifecycleEvent(
                "committed",
                "codex-plan-detailed",
                timestamp,
                {},
            ),
        ),
    )


def _prepare_phase_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "plans").mkdir(parents=True)
    (repo / "specs").mkdir(parents=True)
    (repo / "plans" / "phase-plan-v10-GOVLEAN.md").write_text("# GOVLEAN\n", encoding="utf-8")
    (repo / "specs" / "phase-plans-v10.md").write_text("# Roadmap\n", encoding="utf-8")
    append_entry(repo, _phase_entry())
    update_lifecycle(
        repo,
        "v10-GOVLEAN",
        "executing",
        "codex-execute-phase",
        {"run_id": "run-1", "phase_alias": PHASE},
    )
    return repo


def _complete(repo: Path, metadata: dict[str, Any]) -> None:
    update_lifecycle(repo, "v10-GOVLEAN", "completed", "codex-execute-phase", metadata)


def _raw_plans(repo: Path) -> list[dict[str, Any]]:
    payload = json.loads((repo / "plans" / "manifest.json").read_text(encoding="utf-8"))
    plans = payload.get("plans")
    assert isinstance(plans, list)
    return plans


def _raw_entry(repo: Path, slug: str) -> dict[str, Any]:
    for entry in _raw_plans(repo):
        if isinstance(entry, dict) and entry.get("slug") == slug:
            return entry
    raise AssertionError(f"manifest is missing slug {slug!r}")


def _seed_extension_entry(repo: Path) -> dict[str, Any]:
    """Seed a modeled phase row plus unmodeled per-entry extension fields."""
    (repo / "plans").mkdir(parents=True, exist_ok=True)
    (repo / "plans" / "phase-plan-v10-CONFORM.md").write_text("# CONFORM\n", encoding="utf-8")
    seeded = {
        "acceptance_criteria_count": None,
        "created_at": "2026-07-30T04:08:05Z",
        "file": "plans/phase-plan-v10-CONFORM.md",
        "handoff_ref": ".dev-skills/handoffs/codex-plan-phase/conform.md",
        "if_gates_produced": ["IF-0-CONFORM-1"],
        "lanes": ["SL-0"],
        "lifecycle": [
            {
                "at": "2026-07-30T04:08:05Z",
                "by": "codex-plan-phase",
                "metadata": {},
                "transition": "committed",
            }
        ],
        "owner_skill": "codex-plan-phase",
        "phase_alias": "CONFORM",
        "reflection_ref": None,
        "roadmap_ref": {
            "file": "specs/phase-plans-v10.md",
            "slug": "phase-plans-v10",
            "status": "imported",
            "type": "phase",
        },
        "slug": "v10-CONFORM",
        "status": "committed",
        "task_summary": None,
        "type": "phase",
        "updated_at": "2026-08-13T01:15:00+00:00",
        "lifecycle_events": json.loads(json.dumps(_CONFORM_LIFECYCLE_EVENTS)),
        "extension_note": json.loads(json.dumps(_CONFORM_EXTENSION_NOTE)),
    }
    (repo / "plans" / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "plans": [seeded]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return seeded


def test_issue_disposition_is_closed_phase_record() -> None:
    cls = _issue_disposition_cls()
    field_names = {field.name for field in dataclasses.fields(cls)}
    assert field_names == ISSUE_DISPOSITION_FIELDS
    record = _closed_record()
    assert record.issue_id == "agent-harness#548"
    assert record.phase == PHASE
    assert record.disposition == "closed"
    assert record.owner == "sl1-owner"
    folded = _closed_record(
        issue_id="Consiliency/agent-harness#442",
        disposition="folded_into_successor",
        successor_plan="plans/phase-plan-v10-PROOFGATE.md",
        include_successor=True,
    )
    assert folded.successor_plan == "plans/phase-plan-v10-PROOFGATE.md"
    carried = _closed_record(
        issue_id="agent-harness#519",
        disposition="carried_with_owner",
        owner="lane-owner",
    )
    assert carried.disposition in CLOSED_DISPOSITIONS
    assert carried.owner == "lane-owner"


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"issue_id": "#548"}, "issue_id"),
        ({"issue_id": "548"}, "issue_id"),
        ({"issue_id": "agent-harness"}, "issue_id"),
        ({"disposition": "wontfix"}, "disposition"),
        ({"disposition": "folded_into_successor"}, "successor_plan"),
        ({"owner": ""}, "owner"),
        ({"owner": "   "}, "owner"),
    ],
    ids=[
        "bare-hash-issue",
        "numeric-issue",
        "unqualified-repo",
        "unknown-disposition",
        "folded-missing-successor",
        "empty-owner",
        "whitespace-owner",
    ],
)
def test_issue_disposition_rejects_invalid_closed_records(
    kwargs: dict[str, Any], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _closed_record(**kwargs)


def test_issue_disposition_rejects_unexpected_constructor_fields() -> None:
    cls = _issue_disposition_cls()
    with pytest.raises(TypeError):
        cls(
            issue_id="agent-harness#548",
            phase=PHASE,
            disposition="closed",
            owner="sl1-owner",
            surprise="not-in-schema",
        )


def test_phase_completed_requires_explicit_empty_enrolled_arrays(tmp_path: Path) -> None:
    repo = _prepare_phase_repo(tmp_path)
    _complete(
        repo,
        {
            "verification_status": "passed",
            "issue_inventory": [],
            "issue_dispositions": [],
        },
    )
    entry = read_manifest(repo).plans[0]
    assert entry.status == "completed"
    assert entry.lifecycle[-1].metadata["issue_inventory"] == []
    assert entry.lifecycle[-1].metadata["issue_dispositions"] == []
    assert validate_manifest(repo / "plans" / "manifest.json").valid


def test_phase_completed_accepts_exact_inventory_disposition_equality(
    tmp_path: Path,
) -> None:
    repo = _prepare_phase_repo(tmp_path)
    records = [
        _disposition_payload(
            issue_id="agent-harness#548",
            disposition="closed",
            owner="sl1-owner",
        ),
        _disposition_payload(
            issue_id="Consiliency/agent-harness#442",
            disposition="folded_into_successor",
            owner="sl1-owner",
            successor_plan="plans/phase-plan-v10-PROOFGATE.md",
        ),
        _disposition_payload(
            issue_id="agent-harness#519",
            disposition="carried_with_owner",
            owner="carry-owner",
        ),
    ]
    inventory = [
        "agent-harness#548",
        "Consiliency/agent-harness#442",
        "agent-harness#519",
    ]
    _complete(
        repo,
        {
            "verification_status": "passed",
            "issue_inventory": inventory,
            "issue_dispositions": records,
        },
    )
    entry = read_manifest(repo).plans[0]
    assert entry.status == "completed"
    stored = entry.lifecycle[-1].metadata
    assert stored["issue_inventory"] == inventory
    assert stored["issue_dispositions"] == records
    cls = _issue_disposition_cls()
    parsed = []
    for row in stored["issue_dispositions"]:
        parsed.append(row if isinstance(row, cls) else cls(**row))
    assert {item.issue_id for item in parsed} == set(inventory)
    assert {item.disposition for item in parsed} == CLOSED_DISPOSITIONS


@pytest.mark.parametrize(
    ("metadata", "match"),
    [
        (
            {"verification_status": "passed"},
            "issue_inventory",
        ),
        (
            {"verification_status": "passed", "issue_dispositions": []},
            "issue_inventory",
        ),
        (
            {"verification_status": "passed", "issue_inventory": []},
            "issue_dispositions",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548", "agent-harness#442"],
                "issue_dispositions": [
                    _disposition_payload(issue_id="agent-harness#548"),
                ],
            },
            "issue",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [
                    _disposition_payload(issue_id="agent-harness#548"),
                    _disposition_payload(issue_id="agent-harness#442"),
                ],
            },
            "issue",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548", "agent-harness#548"],
                "issue_dispositions": [_disposition_payload()],
            },
            "duplicate",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [
                    _disposition_payload(),
                    _disposition_payload(owner="other-owner"),
                ],
            },
            "duplicate",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [
                    _disposition_payload(disposition="wontfix"),
                ],
            },
            "disposition",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [
                    _disposition_payload(include_owner=False),
                ],
            },
            "owner",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [_disposition_payload(owner="")],
            },
            "owner",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [_disposition_payload(phase="PROOFGATE")],
            },
            "phase",
        ),
        (
            {
                "issue_inventory": ["#548"],
                "issue_dispositions": [_disposition_payload(issue_id="#548")],
            },
            "issue_id",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [
                    _disposition_payload(
                        disposition="folded_into_successor",
                    )
                ],
            },
            "successor_plan",
        ),
        (
            {
                "issue_inventory": ["agent-harness#548"],
                "issue_dispositions": [
                    _disposition_payload(extra={"surprise": "closed-schema"})
                ],
            },
            "surprise|unknown|field",
        ),
    ],
    ids=[
        "omitted-both-keys",
        "omitted-inventory-key",
        "omitted-dispositions-key",
        "omitted-inventory-issue",
        "unknown-extra-disposition",
        "duplicate-inventory-id",
        "duplicate-disposition-id",
        "unknown-disposition",
        "missing-owner",
        "empty-owner",
        "phase-mismatch",
        "unqualified-issue-id",
        "folded-missing-successor",
        "unknown-disposition-field",
    ],
)
def test_phase_completed_rejects_inventory_and_schema_negatives(
    tmp_path: Path,
    metadata: dict[str, Any],
    match: str,
) -> None:
    repo = _prepare_phase_repo(tmp_path)
    with pytest.raises(ValueError, match=match):
        _complete(repo, metadata)
    assert read_manifest(repo).plans[0].status == "executing"


def test_detailed_completed_does_not_require_issue_disposition_gate(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "plans").mkdir(parents=True)
    (repo / "plans" / "detailed-example.md").write_text("# Detailed\n", encoding="utf-8")
    append_entry(repo, _detailed_entry())
    update_lifecycle(
        repo,
        "detailed-example",
        "executing",
        "codex-execute-detailed",
        {"run_id": "run-1"},
    )
    update_lifecycle(
        repo,
        "detailed-example",
        "completed",
        "codex-execute-detailed",
        {"verification_status": "passed"},
    )
    entry = read_manifest(repo).plans[0]
    assert entry.type == "detailed"
    assert entry.status == "completed"
    assert "issue_inventory" not in entry.lifecycle[-1].metadata
    assert "issue_dispositions" not in entry.lifecycle[-1].metadata


def test_append_entry_preserves_sibling_lifecycle_events_extension(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    seeded = _seed_extension_entry(repo)
    (repo / "plans" / "phase-plan-v10-GOVLEAN.md").write_text("# GOVLEAN\n", encoding="utf-8")
    append_entry(repo, _phase_entry())
    preserved = _raw_entry(repo, "v10-CONFORM")
    assert "lifecycle_events" in preserved, (
        "agent-harness#548: append_entry dropped sibling lifecycle_events"
    )
    assert "extension_note" in preserved, (
        "agent-harness#548: append_entry dropped sibling extension_note"
    )
    assert preserved["lifecycle_events"] == seeded["lifecycle_events"]
    assert preserved["extension_note"] == seeded["extension_note"]
    assert {entry["slug"] for entry in _raw_plans(repo)} == {
        "v10-CONFORM",
        "v10-GOVLEAN",
    }


def test_update_lifecycle_preserves_same_entry_lifecycle_events_extension(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    seeded = _seed_extension_entry(repo)
    update_lifecycle(
        repo,
        "v10-CONFORM",
        "executing",
        "codex-execute-phase",
        {"run_id": "ah548-probe"},
    )
    preserved = _raw_entry(repo, "v10-CONFORM")
    assert preserved["status"] == "executing"
    assert "lifecycle_events" in preserved, (
        "agent-harness#548: update_lifecycle dropped lifecycle_events"
    )
    assert "extension_note" in preserved, (
        "agent-harness#548: update_lifecycle dropped extension_note"
    )
    assert preserved["lifecycle_events"] == seeded["lifecycle_events"]
    assert preserved["extension_note"] == seeded["extension_note"]
    modeled = read_manifest(repo).plans[0]
    assert [event.transition for event in modeled.lifecycle][-1] == "executing"
    assert modeled.lifecycle[-1].metadata["run_id"] == "ah548-probe"
