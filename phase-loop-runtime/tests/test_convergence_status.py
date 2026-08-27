"""SL-3 falsifiers for the transcript-free status projection (EC-RUNTIME-4)."""

from __future__ import annotations

import json

from phase_loop_runtime.convergence.event_log import RecoveredTrainState
from phase_loop_runtime.convergence.status import build_train_status, render_train_status
from phase_loop_runtime.train_ledger import CoordinatorEvent, CoordinatorEventKind

from _runtime_tdd_guard import RuntimeCapabilityMissing
from runtime_content_tdd_adapter import run_mapped_case


def _intent(node_id: str, attempt_id: str, epoch: int = 1) -> CoordinatorEvent:
    return CoordinatorEvent(
        kind=CoordinatorEventKind.INTENT, train_id="t", node_id=node_id, roadmap_path="r",
        roadmap_digest="d", workspace_id="w", branch="b", base_ref="main", base_sha="base",
        head_sha="head", phase="RUNTIME", action="execute", attempt_id=attempt_id, epoch=epoch,
    )


# ---------------------------------------------------------------------------
# Retained skeleton behaviour and the EC-RUNTIME-4 path-entered control


def test_status_projection_is_stable_and_transcript_free():
    snapshot = build_train_status(RecoveredTrainState("t", last_event_offset=2), "events.jsonl")
    assert json.loads(render_train_status(snapshot, as_json=True))["event_log_path"] == "events.jsonl"
    assert "transcript" not in render_train_status(snapshot).lower()


def test_identical_durable_state_renders_identically_across_restarts():
    """EC-RUNTIME-4 path-entered control: same ledger in, same bytes out."""
    state = RecoveredTrainState(
        "t", node_states={"n": _intent("n", "a")}, pending_attempts=(_intent("n", "a"),),
        latest_epoch=1, last_event_offset=0,
    )
    first = build_train_status(state, "events.jsonl")
    second = build_train_status(
        RecoveredTrainState(
            "t", node_states={"n": _intent("n", "a")}, pending_attempts=(_intent("n", "a"),),
            latest_epoch=1, last_event_offset=0,
        ),
        "events.jsonl",
    )
    assert render_train_status(first, as_json=True) == render_train_status(second, as_json=True)
    assert render_train_status(first) == render_train_status(second)


def test_snapshot_projects_only_recovered_state_and_log_identity():
    snapshot = build_train_status(RecoveredTrainState("t"), "events.jsonl")
    payload = json.loads(render_train_status(snapshot, as_json=True))
    assert set(payload) == {
        "train_id", "event_log_path", "last_event_offset", "pending_attempt_ids",
        "node_states", "verification_valid", "approval_valid", "ambiguities", "next_action",
    }


# ---------------------------------------------------------------------------
# SL-3 mapped falsifiers


def test_human_render_labels_validity_as_replay_derived():
    """A reader must not mistake ledger replay for fresh reconciliation authority."""
    snapshot = build_train_status(
        RecoveredTrainState("t", verification_valid=True, approval_valid=True), "events.jsonl"
    )
    human = render_train_status(snapshot)

    def probe():
        lowered = human.lower()
        if "replay" not in lowered or "verification" not in lowered:
            raise RuntimeCapabilityMissing("human status never labels replay-derived validity")

    def assertion():
        lowered = human.lower()
        assert "replay" in lowered
        assert "verification" in lowered and "approval" in lowered
        payload = json.loads(render_train_status(snapshot, as_json=True))
        assert payload["verification_valid"] is True and payload["approval_valid"] is True

    run_mapped_case("status.replay-derived-validity-is-labelled", probe=probe, assertion=assertion)


def test_pending_attempt_ids_stay_distinguishable_per_node():
    """Two nodes sharing an attempt id must not collapse into one opaque entry."""
    state = RecoveredTrainState(
        "t",
        node_states={"n1": _intent("n1", "a"), "n2": _intent("n2", "a")},
        pending_attempts=(_intent("n1", "a"), _intent("n2", "a")),
        latest_epoch=1,
        last_event_offset=1,
    )
    pending = build_train_status(state, "events.jsonl").pending_attempt_ids

    def probe():
        if len(set(pending)) != len(pending):
            raise RuntimeCapabilityMissing("pending attempts collapse to a non-unique projection")

    def assertion():
        assert len(pending) == 2
        assert len(set(pending)) == 2
        assert any("n1" in item for item in pending)
        assert any("n2" in item for item in pending)

    run_mapped_case("status.pending-attempts-stay-distinguishable", probe=probe, assertion=assertion)
