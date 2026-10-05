"""agent-harness#1132, board round 12 (codex F001): the Claude login wait keeps its board's
cancellation and timeout context.

- ``test_login_wait_preserves_board_context`` is codex's falsifier. It is changed in three
  ways. It has a new name, because ``tests/test_finding_F001.py`` already holds an unrelated
  test. It uses the package-relative import. And its pointer-preflight call passes the
  board's per-leg timeouts, ``timeouts_by_leg={"claude": 300}``, exactly as ``invoke_board``
  does for both the mode and the preflight. As written, it called the preflight with no
  timeout, and a call with no timeout checks the default deadline's margin.
  ``test_the_board_pointer_preflight_uses_the_legs_timeout`` checks the same join through
  ``invoke_board`` itself. Both board-level tests also stub ``_claude_code_support_status``
  to supported, as the other board suites do, so they do not depend on a ``claude`` CLI
  being installed. Without that stub, an all-Claude board on a host without the CLI returns
  before any seat runs.
- The other tests pin the rest of the class: a quiescence-latch cancel or trip wakes the wait,
  and the board's cancel context does not leak outside the board.
"""

import threading
import time
import types

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_credentials as sc
from phase_loop_runtime import seat_jail, seat_jail_autoqualify as aq
from phase_loop_runtime.advisor_board.fixtures import DEFAULT_SEATS
from phase_loop_runtime.advisor_board.matrix import default_matrix
from phase_loop_runtime.advisor_board.schema import Board
from .harden_tdd_guard import invoke_sanctioned_board_control


@pytest.mark.parametrize("case", ["bounded_cancel", "pointer_timeout"])
def test_login_wait_preserves_board_context(monkeypatch, tmp_path, case):
    monkeypatch.setenv(sc.WAIT_ENV, "0" if case == "pointer_timeout" else "2")
    monkeypatch.setenv(sc.POLL_ENV, "2")
    monkeypatch.delenv(sc.MARGIN_ENV, raising=False)
    monkeypatch.setattr(sc, "override_present", lambda: False)
    monkeypatch.setattr(sc, "time", types.SimpleNamespace(
        time=lambda: 1000.0, monotonic=time.monotonic))
    monkeypatch.setattr(sc, "read_login_token",
                        lambda: sc.LoginToken(b"fake-access-token", 1600.0))
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    monkeypatch.setattr(seat_jail, "decide_seat_route",
                        lambda *a, **k: seat_jail.SeatRoute(True))
    monkeypatch.setattr(aq, "ensure_qualified", lambda *a: aq.Outcome(aq.QUALIFIED))
    claude = next(s for s in DEFAULT_SEATS if s.harness == "claude")
    board = Board(name="claude-only", purpose="premerge-review", seats=(claude,))
    if case == "pointer_timeout":
        auth = types.SimpleNamespace(staged_tree_sha256="a" * 64)
        modes = pi._seat_launch_modes(board, mode="review", review_authorization=auth,
                                      base_env={}, timeouts_by_leg={"claude": 300})
        assert modes[0].mode == "jailed" and modes[0].code is None
        assert pi._await_claude_login(300, None).outcome == sc.LOGIN_READY
        assert sc.resolve_claude_seat_credential(pi._claude_seat_login_margin_s(300))
        notices = pi._publish_seat_preflight(
            board, pointer_brief=True, mode="review", review_authorization=auth,
            base_env={}, stream_dir=None, on_seat_preflight=None,
            timeouts_by_leg={"claude": 300})
        assert notices == (), "a launchable jailed reviewer is marked ungrounded"
        return
    cancelled = threading.Event()
    seen = []

    def provider(leg, artifact, **kwargs):
        seen.append(kwargs)
        timer = threading.Timer(0.1, cancelled.set)
        timer.start()
        try:
            pi._await_claude_login(kwargs.get("timeout_s"), kwargs.get("review_monitor"),
                                   kwargs.get("quiescence_latch"))
            return "DEGRADED", "", "claude_seat_login_token_expiring"
        except (sc.LoginWaitCancelled, pi._ReviewOperationCancelled):
            return "UNAVAILABLE", "", "review_operation_cancelled"
        finally:
            timer.cancel()
            timer.join()

    monkeypatch.setattr(pi, "_default_spawn_via_provider", provider)
    started = time.monotonic()
    result = invoke_sanctioned_board_control(
        board, "artifact", matrix=default_matrix(env={}, probe=lambda *a: True),
        base_env={}, cancel_event=cancelled, repo_dir=tmp_path,
        stream_dir=tmp_path / "stream")
    elapsed = time.monotonic() - started
    assert len(seen) == 1, result
    assert result.legs[0].detail == "review_operation_cancelled", (elapsed, result)
    assert elapsed < 1.0, "bounded cancellation did not wake the login wait"


def _short_login(monkeypatch):
    monkeypatch.setenv(sc.WAIT_ENV, "30")
    monkeypatch.setenv(sc.POLL_ENV, "30")
    monkeypatch.delenv(sc.MARGIN_ENV, raising=False)
    monkeypatch.setattr(sc, "override_present", lambda: False)
    monkeypatch.setattr(sc, "time", types.SimpleNamespace(
        time=lambda: 1000.0, monotonic=time.monotonic))
    # 100 s left: short of any leg's margin, so the wait starts.
    monkeypatch.setattr(sc, "read_login_token",
                        lambda: sc.LoginToken(b"fake-access-token", 1100.0))


@pytest.mark.parametrize("how", ["cancel", "trip"])
def test_a_quiescence_latch_cancel_or_trip_wakes_the_login_wait(monkeypatch, how):
    _short_login(monkeypatch)
    latch = pi._ProviderQuiescenceLatch()

    def _fire():
        if how == "cancel":
            latch.cancel()
        else:
            latch.trip(pi.ProviderProcessGroupQuiescenceError("fake provider group"))

    timer = threading.Timer(0.2, _fire)
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises((pi._ReviewOperationCancelled, pi.ProviderProcessGroupQuiescenceError)):
            pi._await_claude_login(300, None, latch)
    finally:
        timer.cancel()
        timer.join()
    assert time.monotonic() - started < 2.0, "the latch did not wake the login wait"


def test_the_board_cancel_context_does_not_leak_outside_the_board(monkeypatch):
    # Outside a board there is no board cancel: the wait keeps its private event (and ends on
    # its own bound), and a set event from an earlier board is never visible here.
    assert pi._BOARD_CANCEL.get() is None
    stale = threading.Event()
    stale.set()
    token = pi._BOARD_CANCEL.set(stale)
    pi._BOARD_CANCEL.reset(token)
    _short_login(monkeypatch)
    monkeypatch.setenv(sc.WAIT_ENV, "0.3")
    assert pi._await_claude_login(300, None).outcome == sc.LOGIN_TIMEOUT


def test_the_board_pointer_preflight_uses_the_legs_timeout(monkeypatch, tmp_path):
    # Through invoke_board: with waiting disabled, a 300 s Claude leg whose login has 600 s
    # left is launchable and jailed, so the pointer preflight must not mark it ungrounded.
    monkeypatch.setenv(sc.WAIT_ENV, "0")
    monkeypatch.delenv(sc.MARGIN_ENV, raising=False)
    monkeypatch.setattr(sc, "override_present", lambda: False)
    monkeypatch.setattr(sc, "time", types.SimpleNamespace(
        time=lambda: 1000.0, monotonic=time.monotonic))
    monkeypatch.setattr(sc, "read_login_token",
                        lambda: sc.LoginToken(b"fake-access-token", 1600.0))
    monkeypatch.setattr(pi, "_under_claude_code", lambda *a: False)
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a, **k: (True, "supported"))
    monkeypatch.setattr(seat_jail, "decide_seat_route",
                        lambda *a, **k: seat_jail.SeatRoute(True))
    monkeypatch.setattr(aq, "ensure_qualified", lambda *a: aq.Outcome(aq.QUALIFIED))
    claude = next(s for s in DEFAULT_SEATS if s.harness == "claude")
    board = Board(name="claude-only", purpose="premerge-review", seats=(claude,))
    captured = {}
    real = pi._publish_seat_preflight

    def spy(*a, **k):
        captured["notices"] = real(*a, **k)
        return captured["notices"]

    monkeypatch.setattr(pi, "_publish_seat_preflight", spy)
    monkeypatch.setattr(pi, "_default_spawn_via_provider",
                        lambda leg, artifact, **k: ("OK", "fine\n\nAGREE"))
    invoke_sanctioned_board_control(
        board, "artifact", matrix=default_matrix(env={}, probe=lambda *a: True),
        base_env={}, repo_dir=tmp_path, stream_dir=tmp_path / "stream",
        pointer_brief=True, timeouts_by_leg={"claude": 300})
    assert captured["notices"] == (), "a launchable jailed reviewer is marked ungrounded"
