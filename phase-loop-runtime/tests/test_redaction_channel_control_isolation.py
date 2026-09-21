"""Isolation falsifiers for the concurrent CLI channel controls (agent-harness#945).

`_run_channel_controls` overlaps independent per-channel controls. Concurrency is
only safe if no two cases touch the same file and a failure in one case still
reaches the caller, so both are checked here rather than assumed.

The module keeps ``outside_agent`` out of every node id so the CONFORM
``-k outside_agent`` lifecycle corpus is unchanged.
"""
from __future__ import annotations

import collections
import json
import subprocess
import threading
from pathlib import Path

import pytest

import test_outside_agent_redaction_separation as redaction


def _stub_run(recorder, lock, failing_channel=None):
    """Stand in for the CLI child: record the paths, never spawn anything."""

    def run(command, submission_path, output_path, *additional):
        with lock:
            recorder[str(submission_path)] += 1
            recorder[str(output_path)] += 1
        payload = json.loads(Path(submission_path).read_text(encoding="utf-8"))
        rendered = json.dumps({"status": "pass", "echo": sorted(payload)}, sort_keys=True)
        Path(output_path).write_text(rendered, encoding="utf-8")
        if failing_channel is not None and failing_channel in str(submission_path):
            rendered = "SENTINEL-LEAK"
            Path(output_path).write_text(rendered, encoding="utf-8")
        return subprocess.CompletedProcess([command], 0, rendered, "")

    return run


def _cases(count: int) -> list[tuple[str, dict, bool]]:
    return [
        (f"submission.work_request.channel_{index}", {"field": f"value-{index}"}, True)
        for index in range(count)
    ]


def test_concurrent_channels_never_share_a_file(monkeypatch, tmp_path):
    """Every case must touch only paths named for its own channel and command."""
    recorder: collections.Counter[str] = collections.Counter()
    lock = threading.Lock()
    monkeypatch.setattr(redaction, "_run", _stub_run(recorder, lock))
    monkeypatch.setattr(redaction, "clean_canonical_submission", lambda: {"clean": True})
    monkeypatch.setattr(redaction, "_production_capability_marker_present", lambda: False)

    cases = _cases(24)
    redaction._run_channel_controls(cases, sentinel="SENTINEL", tmp_path=tmp_path)

    # Four files per channel (safe input, safe output, negative input, negative
    # output) for each of the two commands, each touched exactly once.
    assert len(recorder) == len(cases) * 8, len(recorder)
    assert set(recorder.values()) == {1}, recorder.most_common(3)

    owners: dict[str, set[str]] = collections.defaultdict(set)
    for path in recorder:
        stem = Path(path).name
        owner = next(
            channel for channel, _, _ in cases if stem.startswith(channel.replace(".", "-"))
        )
        owners[owner].add(path)
    assert sum(len(paths) for paths in owners.values()) == len(recorder)
    assert len({path for paths in owners.values() for path in paths}) == len(recorder)


def test_a_failure_in_one_concurrent_channel_reaches_the_caller(monkeypatch, tmp_path):
    """A worker's assertion must not be swallowed by the pool."""
    recorder: collections.Counter[str] = collections.Counter()
    lock = threading.Lock()
    monkeypatch.setattr(
        redaction, "_run", _stub_run(recorder, lock, failing_channel="channel_7")
    )
    monkeypatch.setattr(redaction, "clean_canonical_submission", lambda: {"clean": True})
    monkeypatch.setattr(redaction, "_production_capability_marker_present", lambda: False)

    with pytest.raises(Exception) as caught:
        redaction._run_channel_controls(
            _cases(16), sentinel="SENTINEL-LEAK", tmp_path=tmp_path
        )
    assert "channel_7" in str(caught.value)


def test_an_empty_case_list_spawns_nothing(monkeypatch, tmp_path):
    recorder: collections.Counter[str] = collections.Counter()
    monkeypatch.setattr(redaction, "_run", _stub_run(recorder, threading.Lock()))
    redaction._run_channel_controls([], sentinel="SENTINEL", tmp_path=tmp_path)
    assert not recorder


def test_every_real_channel_slug_is_unique():
    """Concurrency is only safe while distinct channels cannot share a filename.

    `_assert_cli_channel_control` names its files after `channel.replace('.', '-')`.
    Two channels that differ only where a dot meets a dash would map to the same
    slug; serially that silently overwrote, concurrently it would race.
    """
    from _outside_agent_canonical import (
        CANONICAL_DYNAMIC_INPUTS,
        redaction_channel_assignment,
    )

    channels = set(redaction_channel_assignment()) | set(CANONICAL_DYNAMIC_INPUTS)
    slugs = collections.Counter(channel.replace(".", "-") for channel in channels)
    collisions = {slug: count for slug, count in slugs.items() if count > 1}
    assert not collisions, collisions
    assert len(slugs) == len(channels)
