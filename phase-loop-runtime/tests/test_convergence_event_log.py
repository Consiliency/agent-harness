"""SL-1 falsifiers for the durable convergence event log (EC-RUNTIME-1)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from phase_loop_runtime.convergence import event_log as event_log_module
from phase_loop_runtime.convergence.event_log import (
    default_convergence_event_log_path, read_convergence_events, record_intent,
    record_outcome, recover_train_state,
)
from phase_loop_runtime.train_ledger import CoordinatorEvent, CoordinatorEventKind

from _runtime_tdd_guard import RuntimeCapabilityMissing, require_source_capability
from runtime_content_tdd_adapter import RUNTIME_CASES, run_mapped_case


def _event(kind, **overrides):
    value = dict(kind=kind, train_id="train", node_id="node", roadmap_path="plan.md", roadmap_digest="d", workspace_id="w", branch="b", base_ref="main", base_sha="base", head_sha="head", phase="RUNTIME", action="execute", attempt_id="a", epoch=1)
    value.update(overrides)
    return CoordinatorEvent(**value)


# ---------------------------------------------------------------------------
# Retained skeleton behaviour


def test_durable_intent_then_outcome_and_recovery(tmp_path: Path):
    path = default_convergence_event_log_path(tmp_path, "train")
    intent = _event(CoordinatorEventKind.INTENT)
    outcome = _event(CoordinatorEventKind.OUTCOME, verification_digest="digest", seat_outcomes=("seat",))
    record_intent(path, intent)
    record_outcome(path, outcome)
    record_outcome(path, outcome)
    assert read_convergence_events(path) == (intent, outcome)
    assert not recover_train_state(read_convergence_events(path)).pending_attempts


def test_rejects_phase_loop_and_outcome_without_intent(tmp_path: Path):
    with pytest.raises(ValueError):
        default_convergence_event_log_path(tmp_path / ".phase-loop", "train")
    with pytest.raises(ValueError):
        record_outcome(tmp_path / "events.jsonl", _event(CoordinatorEventKind.OUTCOME))


def test_tolerates_only_malformed_final_record(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    record_intent(path, _event(CoordinatorEventKind.INTENT))
    path.write_text(path.read_text() + "{", encoding="utf-8")
    assert len(read_convergence_events(path)) == 1
    path.write_text("{\n" + path.read_text(), encoding="utf-8")
    with pytest.raises(ValueError):
        read_convergence_events(path)


def test_complete_pair_survives_restart_and_folds(tmp_path: Path):
    """EC-RUNTIME-1 path-entered control: the happy path must stay green."""
    path = tmp_path / "events.jsonl"
    intent = _event(CoordinatorEventKind.INTENT)
    outcome = _event(CoordinatorEventKind.OUTCOME, verification_digest="digest", seat_outcomes=("seat",))
    record_intent(path, intent)
    record_outcome(path, outcome)
    state = recover_train_state(read_convergence_events(path))
    assert state.train_id == "train"
    assert state.node_states["node"] == outcome
    assert state.pending_attempts == ()
    assert state.last_event_offset == 1
    assert state.ambiguities == ()
    assert state.verification_valid and state.approval_valid


def test_zero_based_offset_is_minus_one_when_empty():
    assert recover_train_state(()).last_event_offset == -1


# ---------------------------------------------------------------------------
# SL-1 mapped falsifiers


def test_append_drains_partial_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A short ``os.write`` must not silently truncate a committed record."""
    path = tmp_path / "events.jsonl"
    intent = _event(CoordinatorEventKind.INTENT, train_id="drain")
    real_write = os.write
    marker = b'"train_id":"drain"'

    def short_write(fd, data):
        if marker in data and len(data) > 8:
            return real_write(fd, data[:8])
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", short_write)
    record_intent(path, intent)
    monkeypatch.undo()
    raw = path.read_bytes()

    def probe():
        if not raw.endswith(b"\n") or marker not in raw:
            raise RuntimeCapabilityMissing("_append does not drain short writes")

    def assertion():
        assert read_convergence_events(path) == (intent,)

    run_mapped_case("event-log.full-drain-append", probe=probe, assertion=assertion)


def test_append_fsyncs_the_created_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Creating the log's parent directory must itself be made durable."""
    path = tmp_path / "fresh" / "events.jsonl"
    real_fsync = os.fsync
    synced_dirs: list[bool] = []

    def recording_fsync(fd):
        try:
            synced_dirs.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        except OSError:  # pragma: no cover - defensive
            synced_dirs.append(False)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    record_intent(path, _event(CoordinatorEventKind.INTENT))
    monkeypatch.undo()

    def probe():
        if not any(synced_dirs):
            raise RuntimeCapabilityMissing("_append never fsyncs the created parent directory")

    def assertion():
        assert any(synced_dirs), "the newly created parent directory must be fsynced"
        assert read_convergence_events(path)

    run_mapped_case("event-log.parent-directory-durability", probe=probe, assertion=assertion)


def test_append_takes_a_cross_process_exclusive_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A process-local ``threading.Lock`` cannot serialize concurrent writers."""
    case = RUNTIME_CASES["event-log.cross-process-single-writer"]
    exclusive: list[str] = []

    def probe():
        source_missing = True
        for needle in ("flock", "lockf"):
            try:
                require_source_capability(case.production_path, case.symbol, needle)
            except RuntimeCapabilityMissing:
                continue
            source_missing = False
            break
        if source_missing:
            raise RuntimeCapabilityMissing("_append takes no cross-process lock")

    def assertion():
        import fcntl

        for name in ("flock", "lockf"):
            real = getattr(fcntl, name)

            def recorder(fd, operation, *rest, _real=real, _name=name):
                if operation & fcntl.LOCK_EX:
                    exclusive.append(_name)
                return _real(fd, operation, *rest)

            monkeypatch.setattr(fcntl, name, recorder)
        record_intent(tmp_path / "events.jsonl", _event(CoordinatorEventKind.INTENT))
        monkeypatch.undo()
        assert exclusive, "the append must hold an exclusive cross-process lock"

    run_mapped_case("event-log.cross-process-single-writer", probe=probe, assertion=assertion)


def test_torn_tail_is_repaired_so_the_next_append_is_readable(tmp_path: Path):
    """A torn final record must be truncated, not concatenated with the next append."""
    path = tmp_path / "events.jsonl"
    first = _event(CoordinatorEventKind.INTENT)
    second = _event(CoordinatorEventKind.INTENT, node_id="node-2", attempt_id="b")
    record_intent(path, first)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind":"intent","train_id":"tr')
    read_convergence_events(path)
    record_intent(path, second)
    recovered = read_convergence_events(path)

    def probe():
        if second not in recovered:
            raise RuntimeCapabilityMissing("a torn tail is never repaired before the next append")

    def assertion():
        assert recovered == (first, second)

    run_mapped_case("event-log.torn-tail-repair-allows-clean-append", probe=probe, assertion=assertion)


def test_conflicting_duplicate_intent_fails_closed(tmp_path: Path):
    """Two intents sharing an exact key but differing in payload must be rejected."""
    path = tmp_path / "events.jsonl"
    first = _event(CoordinatorEventKind.INTENT)
    conflicting = _event(CoordinatorEventKind.INTENT, head_sha="other-head")
    record_intent(path, first)
    raised = False
    try:
        record_intent(path, conflicting)
    except ValueError:
        raised = True

    def probe():
        if not raised:
            raise RuntimeCapabilityMissing("record_intent accepts a conflicting duplicate key")

    def assertion():
        assert raised
        assert read_convergence_events(path) == (first,)

    run_mapped_case("event-log.conflicting-duplicate-intent-fails-closed", probe=probe, assertion=assertion)


def test_mixed_versions_and_mixed_trains_are_distinct_ambiguities():
    """A caller must be able to tell a version mismatch from a train mismatch."""
    versions = recover_train_state((
        _event(CoordinatorEventKind.INTENT),
        _event(CoordinatorEventKind.INTENT, node_id="n2", attempt_id="b", event_schema_version="2"),
    )).ambiguities
    trains = recover_train_state((
        _event(CoordinatorEventKind.INTENT),
        _event(CoordinatorEventKind.INTENT, train_id="other", node_id="n2", attempt_id="b"),
    )).ambiguities

    def probe():
        if set(versions) == set(trains):
            raise RuntimeCapabilityMissing("version and train ambiguities share one merged string")

    def assertion():
        assert versions and trains and set(versions) != set(trains)
        assert not any("train" in item for item in versions)
        assert not recover_train_state((
            _event(CoordinatorEventKind.INTENT),
            _event(CoordinatorEventKind.INTENT, node_id="n2", attempt_id="b", event_schema_version="2"),
        )).verification_valid

    run_mapped_case("event-log.mixed-version-is-distinct-ambiguity", probe=probe, assertion=assertion)


def test_event_log_module_is_transcript_free():
    source = Path(event_log_module.__file__).read_text(encoding="utf-8")
    assert "transcript" not in source.lower()
    assert ".phase-loop" in source  # the guard that refuses to write beneath it
