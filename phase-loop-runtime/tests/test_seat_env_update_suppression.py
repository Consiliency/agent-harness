"""Seats suppress CLI self-update (agent-harness#1798 follow-up).

A seat runs the native provider directly (agent-harness#1318 wrappers, #1798 frontdoors),
so the update suppression the team-host launcher applies must come from the seat itself.
"""

from phase_loop_runtime import seat_jail


def test_every_seat_disables_the_autoupdater():
    for leg in ("claude", "codex", "grok", "gemini"):
        assert seat_jail.seat_env(leg, token_fd=None)["DISABLE_AUTOUPDATER"] == "1"


def test_a_claude_seat_also_disables_updates():
    assert seat_jail.seat_env("claude", token_fd=None)["DISABLE_UPDATES"] == "1"


def test_other_seats_do_not_gain_the_claude_flag():
    for leg in ("codex", "grok", "gemini"):
        assert "DISABLE_UPDATES" not in seat_jail.seat_env(leg, token_fd=None)
