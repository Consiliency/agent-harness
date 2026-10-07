"""The owned launch's setup does not count against the seat's stall window
(agent-harness#1282, Gate A py3.11).

The seat-launch owner runs a namespace identity probe and the seat profile before the
provider exists. The Claude TUI started its stall clock before that, so under load a
bounded seat with a short stall window ended ``claude_tui_stalled`` before its provider
had started. A provider's silence is measured from the moment it exists, as on main, where
the launch was immediate."""

from __future__ import annotations

import os
import time

import pytest

from phase_loop_runtime import panel_invoker as panel
from test_review_seat_stall_1176 import _fast_tui, _provider, retries_exhausted


@pytest.mark.usefixtures("owned_review_network")
def test_slow_owner_setup_does_not_stall_a_bounded_seat(tmp_path, monkeypatch):
    _fast_tui(monkeypatch)
    real_launch = panel.launch_owned

    def slow_setup(*args, **kwargs):
        time.sleep(.6)  # owner setup longer than the stall window, before the provider starts
        return real_launch(*args, **kwargs)

    monkeypatch.setattr(panel, "launch_owned", slow_setup)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, retries_exhausted(), release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=10, backstop_s=10,
            stall_threshold_s=.4, env=os.environ,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        release.touch()
    assert (rc != 0, text, log) == (True, "", "claude_seat_output_budget_exhausted")


@pytest.mark.usefixtures("owned_review_network")
def test_slow_in_seat_startup_does_not_stall_a_bounded_seat(tmp_path, monkeypatch):
    """Inside the seat, the owner's own links (the keyring and filter link, the descriptor
    closer, the journal collector) run before the provider is executed. Their time is not the
    provider's silence: the clock starts at the collector's handoff, right before the exec."""
    _fast_tui(monkeypatch)
    real_collector = panel._claude_journal_collector_command

    def slow_collector(command, **kwargs):
        collector = real_collector(command, **kwargs)
        return ["/bin/sh", "-c", 'sleep .6; exec "$@"', "sh", *collector]

    monkeypatch.setattr(panel, "_claude_journal_collector_command", slow_collector)
    transcript = tmp_path / "session.jsonl"
    release = tmp_path / "release"
    try:
        rc, text, log, _tail = panel._run_claude_tui_session(
            command=_provider(transcript, retries_exhausted(), release), cwd=tmp_path,
            prompt="input", output_file=tmp_path / "absent", timeout_s=10, backstop_s=10,
            stall_threshold_s=.4, env=os.environ,
            allow_transcript_final=True, broker_transcript_path=transcript,
        )
    finally:
        release.touch()
    assert (rc != 0, text, log) == (True, "", "claude_seat_output_budget_exhausted")


@pytest.mark.usefixtures("owned_review_network")
def test_a_seat_that_never_starts_its_provider_still_ends(tmp_path, monkeypatch):
    """The startup allowance is bounded: an owner that never hands off ends as stalled."""
    _fast_tui(monkeypatch)
    monkeypatch.setattr(panel, "_SEAT_OWNER_STARTUP_S", .5)
    monkeypatch.setattr(panel, "_claude_journal_collector_command",
                        lambda command, **kwargs: ["/bin/sh", "-c", "sleep 30"])
    started = time.monotonic()
    rc, text, log, _tail = panel._run_claude_tui_session(
        command=["/usr/bin/true"], cwd=tmp_path, prompt="input", output_file=tmp_path / "absent",
        timeout_s=20, backstop_s=20, stall_threshold_s=.4, env=os.environ,
        allow_transcript_final=True, broker_transcript_path=tmp_path / "session.jsonl",
    )
    assert (rc != 0, log) == (True, "claude_tui_stalled")
    assert time.monotonic() - started < 10
