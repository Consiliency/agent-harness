"""Preserve committed bytes and bind event-log paths (agent-harness#720)."""

from dataclasses import asdict
import io
import json
import os
from pathlib import Path

import pytest

from phase_loop_runtime.convergence import event_log
from phase_loop_runtime.train_ledger import CoordinatorEvent, CoordinatorEventKind


def _event(**overrides):
    value = dict(
        kind=CoordinatorEventKind.INTENT, train_id="train", node_id="node",
        roadmap_path="plan.md", roadmap_digest="digest", workspace_id="workspace",
        branch="branch", base_ref="main", base_sha="base", head_sha="head",
        phase="RUNTIME", action="execute", attempt_id="attempt", epoch=1,
    )
    value.update(overrides)
    return CoordinatorEvent(**value)


def _line(event):
    return (json.dumps(asdict(event), sort_keys=True) + "\n").encode()


@pytest.mark.parametrize("bad", [b"{", b"\xff", b"[]", b"null", b"{}",
    b'{"kind":"invalid"}', b'{"kind":"intent"}'])
@pytest.mark.parametrize("position", ["last", "first"])
@pytest.mark.parametrize("operation", ["read", "append"])
def test_complete_corruption_refuses_without_erasing_bytes(tmp_path, bad, position, operation):
    path = tmp_path / "events.jsonl"
    good = _line(_event())
    raw = good + bad + b"\n" if position == "last" else bad + b"\n" + good
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        if operation == "read":
            event_log.read_convergence_events(path)
        else:
            event_log.record_intent(path, _event(node_id="next", attempt_id="next"))
    assert path.read_bytes() == raw


@pytest.mark.parametrize("operation", ["read", "append"])
def test_invalid_collection_shape_is_committed_corruption(tmp_path, operation):
    path = tmp_path / "events.jsonl"
    value = asdict(_event())
    value["owned_paths"] = 17
    raw = (json.dumps(value) + "\n").encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        if operation == "read":
            event_log.read_convergence_events(path)
        else:
            event_log.record_intent(path, _event(node_id="next"))
    assert path.read_bytes() == raw


@pytest.mark.parametrize("tail", [b"{", b"\xff", b'{"kind":"intent"}', b"\r"])
def test_only_unterminated_tail_is_ignored_then_repaired(tmp_path, tail):
    path = tmp_path / "events.jsonl"
    first, second = _event(), _event(node_id="next", attempt_id="next")
    raw = _line(first) + tail
    path.write_bytes(raw)
    assert event_log.read_convergence_events(path) == (first,)
    assert path.read_bytes() == raw
    event_log.record_intent(path, second)
    assert event_log.read_convergence_events(path) == (first, second)
    assert path.read_bytes().endswith(b"\n")


def test_identical_replay_may_repair_tail_but_conflict_cannot(tmp_path):
    path = tmp_path / "events.jsonl"
    first = _event()
    raw = _line(first) + b"{"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        event_log.record_intent(path, _event(head_sha="conflicting"))
    assert path.read_bytes() == raw
    event_log.record_intent(path, first)
    assert path.read_bytes() == _line(first)
    assert event_log.read_convergence_events(path) == (first,)


@pytest.mark.parametrize("operation", ["read", "append"])
def test_carriage_return_cannot_hide_two_records_in_one_committed_line(tmp_path, operation):
    path = tmp_path / "events.jsonl"
    raw = _line(_event()).rstrip(b"\n") + b"\r" + _line(_event(node_id="other"))
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        if operation == "read":
            event_log.read_convergence_events(path)
        else:
            event_log.record_intent(path, _event(node_id="next"))
    assert path.read_bytes() == raw


def test_blank_lines_and_absent_file_preserve_reader_behavior(tmp_path):
    path = tmp_path / "events.jsonl"
    assert event_log.read_convergence_events(path) == ()
    assert not path.exists()
    raw = b"\n \t\n\r\n" + _line(_event()) + b"\n"
    path.write_bytes(raw)
    assert event_log.read_convergence_events(path) == (_event(),)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("train_id", ["", ".", "..", "a/b", "a\\b", "a\0b", "safe/../../escaped"])
def test_helper_refuses_unsafe_train_components(tmp_path, train_id):
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError):
        event_log.default_convergence_event_log_path(tmp_path, train_id)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("train_id", ["ordinary", ".hidden", "a.b", "a..b", "with space", "é"])
def test_helper_preserves_opaque_component_and_lexical_root_alias(tmp_path, train_id):
    selected = tmp_path / "selected"
    selected.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(selected, target_is_directory=True)
    path = event_log.default_convergence_event_log_path(alias, train_id)
    assert path == alias / "convergence" / f"train-{train_id}.events.jsonl"
    event_log.record_intent(path, _event())
    assert event_log.read_convergence_events(path) == (_event(),)


@pytest.mark.parametrize("part", ["directory", "leaf"])
@pytest.mark.parametrize("destination", ["inside", "outside", "phase_loop"])
def test_helper_refuses_descendant_symlinks_even_without_escape(tmp_path, part, destination):
    root = tmp_path / "selected"
    root.mkdir()
    target = {"inside": root / "real", "outside": tmp_path / "other",
              "phase_loop": tmp_path / ".phase-loop"}[destination]
    target.mkdir()
    target_file = target / "retained.jsonl"
    raw = _line(_event())
    target_file.write_bytes(raw)
    convergence = root / "convergence"
    if part == "directory":
        convergence.symlink_to(target, target_is_directory=True)
    else:
        convergence.mkdir()
        (convergence / "train-train.events.jsonl").symlink_to(target_file)
    with pytest.raises(ValueError):
        event_log.default_convergence_event_log_path(root, "train")
    assert target_file.read_bytes() == raw
    assert sorted(p.name for p in target.iterdir()) == ["retained.jsonl"]


@pytest.mark.parametrize("operation", ["read", "append"])
@pytest.mark.parametrize("exists", [True, False])
def test_direct_io_refuses_resolved_phase_loop_even_through_alias(tmp_path, operation, exists):
    protected = tmp_path / ".phase-loop"
    protected.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(protected, target_is_directory=True)
    path = alias / "events.jsonl"
    raw = _line(_event())
    if exists:
        path.write_bytes(raw)
    with pytest.raises(ValueError):
        if operation == "read":
            event_log.read_convergence_events(path)
        else:
            event_log.record_intent(path, _event(node_id="next"))
    assert path.read_bytes() == raw if exists else not path.exists()


@pytest.mark.parametrize("operation", ["read", "append"])
def test_leaf_symlink_planted_at_open_cannot_redirect_io(tmp_path, monkeypatch, operation):
    path = tmp_path / "events.jsonl"
    outside = tmp_path / "outside.jsonl"
    path.write_bytes(_line(_event()))
    outside_raw = _line(_event(node_id="outside", attempt_id="outside"))
    outside.write_bytes(outside_raw)
    swapped = []
    real_open, real_io_open = os.open, io.open

    def swap(file):
        if not swapped and isinstance(file, (str, os.PathLike)) and Path(file).name == path.name:
            path.unlink()
            path.symlink_to(outside)
            swapped.append(True)

    def open_fd(file, *args, **kwargs):
        swap(file)
        return real_open(file, *args, **kwargs)

    def open_stream(file, *args, **kwargs):
        swap(file)
        return real_io_open(file, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_fd)
    monkeypatch.setattr(io, "open", open_stream)
    with pytest.raises(ValueError):
        if operation == "read":
            event_log.read_convergence_events(path)
        else:
            event_log.record_intent(path, _event(node_id="next", attempt_id="next"))
    assert swapped, "the operation must reach the injected check-to-open interval"
    assert outside.read_bytes() == outside_raw


def test_alias_retarget_after_parent_binding_does_not_redirect_append(tmp_path, monkeypatch):
    selected = tmp_path / "selected"
    protected = tmp_path / ".phase-loop"
    selected.mkdir()
    protected.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(selected, target_is_directory=True)
    physical = selected / "events.jsonl"
    physical.write_bytes(_line(_event()))
    outside = protected / "events.jsonl"
    outside.write_bytes(b"")
    swapped = []
    real_open = os.open

    def retarget(file, *args, **kwargs):
        if not swapped and isinstance(file, (str, os.PathLike)) and Path(file).name == physical.name:
            alias.unlink()
            alias.symlink_to(protected, target_is_directory=True)
            swapped.append(True)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(os, "open", retarget)
    second = _event(node_id="next", attempt_id="next")
    event_log.record_intent(alias / "events.jsonl", second)
    assert swapped
    assert outside.read_bytes() == b""
    assert event_log.read_convergence_events(physical) == (_event(), second)


@pytest.mark.parametrize("operation", ["read", "append"])
@pytest.mark.parametrize("destination", ["inside", "outside", "phase_loop"])
def test_missing_intermediate_symlink_inserted_after_validation_cannot_redirect_io(tmp_path, monkeypatch, operation, destination):
    root = tmp_path.resolve()
    selected = root / "selected"
    selected.mkdir()
    target = {"inside": selected / "real", "outside": root / "outside",
              "phase_loop": root / ".phase-loop"}[destination]
    (target / "sub").mkdir(parents=True)
    path = selected / "new" / "sub" / "events.jsonl"
    outside = target / "sub" / "events.jsonl"
    outside_raw = _line(_event(node_id="outside", attempt_id="outside"))
    outside.write_bytes(outside_raw)
    entered = []
    real_validate = event_log._reject_phase_loop

    def insert_after_validation(candidate):
        real_validate(candidate)
        if candidate == path and not entered:
            (selected / "new").symlink_to(target, target_is_directory=True)
            entered.append(True)

    monkeypatch.setattr(event_log, "_reject_phase_loop", insert_after_validation)
    with pytest.raises(ValueError):
        try:
            if operation == "read":
                event_log.read_convergence_events(path)
            else:
                event_log.record_intent(path, _event(node_id="next", attempt_id="next"))
        finally:
            assert entered, "the previously missing suffix must change after real path validation"
            assert outside.read_bytes() == outside_raw
