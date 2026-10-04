"""agent-harness#1132, plan amendment A3: a short Claude login is waited for, read-only.

The harness never runs the Claude CLI to renew a credential. A jailed Claude seat whose login
is short of the launch margin waits -- before staging, reading the store read-only -- for its
owner to renew it; renewed, it runs jailed; not renewed in time (or no wait allowed), it is
DEGRADED and NOT RUN with ``claude_seat_login_token_expiring`` -- never a toolless (sealed)
substitute (plan amendment A3b). Fakes only.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
import types
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import seat_credentials as sc
from phase_loop_runtime import seat_jail


def _login(expires_at):
    return sc.LoginToken(b"fake-login-access-token", expires_at)


class _Clock:
    """A fake wall and monotonic clock; ``wait`` advances it instead of sleeping."""

    def __init__(self, logins, *, cancel_after=None):
        self.t = 1000.0
        self.waits: list[float] = []
        self._logins = logins
        self._cancel_after = cancel_after

    def now(self):
        return self.t

    def read(self):
        login = self._logins(self.t)
        return login

    def wait(self, seconds):
        self.waits.append(seconds)
        self.t += seconds
        return self._cancel_after is not None and len(self.waits) >= self._cancel_after


@pytest.fixture
def no_override(monkeypatch):
    monkeypatch.setattr(sc, "override_present", lambda: False)


def _await(clock, *, max_wait_s=900.0, poll_s=30.0, margin_s=1800.0):
    return sc.await_login_margin(margin_s, max_wait_s=max_wait_s, poll_s=poll_s,
                                 wait=clock.wait, now=clock.now, monotonic=clock.now,
                                 read_login=clock.read)


# --------------------------------------------------------------------------------------
# The read-only wait itself.
# --------------------------------------------------------------------------------------

def test_a_login_renewed_mid_wait_is_refreshed(no_override):
    clock = _Clock(lambda t: _login(1600.0) if t < 1090 else _login(t + 8 * 3600))
    result = _await(clock)
    assert result.outcome == sc.LOGIN_REFRESHED and result.waited_s == 90.0
    assert clock.waits == [30.0, 30.0, 30.0]


def test_a_login_never_renewed_times_out_at_the_bound(no_override):
    clock = _Clock(lambda t: _login(1600.0))
    result = _await(clock, max_wait_s=100.0)
    assert result.outcome == sc.LOGIN_TIMEOUT and result.waited_s == 100.0
    assert clock.waits == [30.0, 30.0, 30.0, 10.0]


def test_a_wait_of_zero_times_out_without_waiting(no_override):
    clock = _Clock(lambda t: _login(1600.0))
    assert _await(clock, max_wait_s=0.0) == sc.LoginWait(sc.LOGIN_TIMEOUT, 0.0)
    assert clock.waits == []


def test_a_login_that_already_clears_the_margin_is_ready_at_once(no_override):
    clock = _Clock(lambda t: _login(t + 8 * 3600))
    assert _await(clock) == sc.LoginWait(sc.LOGIN_READY, 0.0) and clock.waits == []


def test_a_store_that_becomes_unreadable_mid_wait_is_typed(no_override):
    clock = _Clock(lambda t: _login(1600.0) if t < 1060 else None)
    assert _await(clock).outcome == sc.LOGIN_MISSING


def test_cancellation_interrupts_the_wait(no_override):
    clock = _Clock(lambda t: _login(1600.0), cancel_after=2)
    with pytest.raises(sc.LoginWaitCancelled):
        _await(clock)
    assert len(clock.waits) == 2


def test_an_override_never_waits(monkeypatch):
    monkeypatch.setattr(sc, "override_present", lambda: True)
    clock = _Clock(lambda t: pytest.fail("the login store was read"))
    assert _await(clock) == sc.LoginWait(sc.LOGIN_READY, 0.0)


@pytest.mark.parametrize("value, expected", [(None, 900.0), ("0", 0.0), ("45", 45.0),
                                             ("nonsense", 900.0), ("-1", 900.0)])
def test_the_wait_bound_is_configurable(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(sc.WAIT_ENV, raising=False)
    else:
        monkeypatch.setenv(sc.WAIT_ENV, value)
    assert sc.login_refresh_wait_s() == expected


# --------------------------------------------------------------------------------------
# The production wait (`_await_claude_login`): read-only, monitored, bounded.
# --------------------------------------------------------------------------------------

def _file_login(monkeypatch, tmp_path, expires_in):
    """A real login store file (the CLI's), read by the real read-only reader."""
    store = Path(sc.claude_config_dir()) / ".credentials.json"
    store.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "fake-login-access-token",
        "expiresAt": (time.time() + expires_in) * 1000}}))
    store.chmod(0o600)
    return store


def test_the_wait_runs_nothing_and_reads_the_store_only(monkeypatch, tmp_path):
    store = _file_login(monkeypatch, tmp_path, 120)
    spawned: list = []
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, lambda *a, **k: spawned.append(a) or pytest.fail(
            "a process was started during the login wait"))
    monkeypatch.setenv(sc.WAIT_ENV, "5")
    monkeypatch.setenv(sc.POLL_ENV, "1")
    renewer = threading.Timer(1.5, lambda: store.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "fake-renewed-token", "expiresAt": (time.time() + 8 * 3600) * 1000}})))
    renewer.start()
    try:
        result = pi._await_claude_login(None, None)
    finally:
        renewer.cancel()
    assert result.outcome == sc.LOGIN_REFRESHED and spawned == []


def _monitor(tmp_path):
    return pi._ReviewMonitor(tmp_path / "monitor.json", "inv", 0, threading.Event())


def test_heartbeat_only_records_a_login_wait_not_a_stall(monkeypatch, tmp_path):
    monitor = _monitor(tmp_path)
    monitor.started -= 10_000                          # long before the wait began
    seen = []
    monkeypatch.setattr(sc, "login_seconds_left", lambda margin_s, **k: 60.0)

    def _fake(margin_s, *, max_wait_s, poll_s, wait, **k):
        seen.append(json.loads((tmp_path / "monitor.json").read_text())["login_wait"])
        return sc.LoginWait(sc.LOGIN_REFRESHED, 42.0)

    monkeypatch.setattr(sc, "await_login_margin", _fake)
    before = time.monotonic()
    assert pi._await_claude_login(None, monitor).outcome == sc.LOGIN_REFRESHED
    assert seen == [{"state": "awaiting_refresh", "max_wait_s": 900.0, "waited_s": 0.0}]
    record = json.loads((tmp_path / "monitor.json").read_text())
    assert record["login_wait"] == {"state": "refreshed", "max_wait_s": 900.0, "waited_s": 42.0}
    assert record["progress_notice"] is None and record["observation_state"] == "progress_unobserved"
    assert monitor.started >= before                   # the stall clock starts after the wait


def test_a_bounded_wait_is_capped_by_the_legs_deadline(monkeypatch):
    monkeypatch.setenv(sc.WAIT_ENV, "900")
    monkeypatch.setattr(sc, "login_seconds_left", lambda margin_s, **k: 60.0)
    caps = []
    monkeypatch.setattr(sc, "await_login_margin",
                        lambda margin_s, *, max_wait_s, **k: caps.append(max_wait_s)
                        or sc.LoginWait(sc.LOGIN_TIMEOUT, max_wait_s))
    pi._await_claude_login(300, None)
    pi._await_claude_login(None, None)
    assert caps == [300.0, 900.0]


def test_the_monitor_cancel_interrupts_the_production_wait(monkeypatch, tmp_path):
    monitor = _monitor(tmp_path)
    monitor.cancel.set()
    monkeypatch.setenv(sc.WAIT_ENV, "30")
    monkeypatch.setattr(sc, "login_seconds_left", lambda margin_s, **k: 60.0)
    monkeypatch.setattr(sc, "read_login_token", lambda **k: _login(time.time() + 60))
    with pytest.raises(sc.LoginWaitCancelled):
        pi._await_claude_login(None, monitor)


# --------------------------------------------------------------------------------------
# Through the production spawn: renewed -> jailed; not renewed -> sealed; cancelled.
# --------------------------------------------------------------------------------------

def _spawn(monkeypatch, tmp_path, outcome, *, review_monitor=None, waited=30.0, jailed_leg=None):
    from test_seat_notices import _FakeBroker

    calls = {"prepare": 0}

    def _prepare(*_a, **_k):
        calls["prepare"] += 1
        if jailed_leg is not None:
            return types.SimpleNamespace(notices=[])
        raise seat_jail.SeatSandboxRefused("seat_sandbox_refused:jail_build")

    def _stage(_repo, review_dir):
        tree = Path(review_dir) / "pl-panel-stage-x"
        (tree / ".git").mkdir(parents=True)
        (tree / ".git" / "phase-loop-source-commit").write_text("c" * 40)
        return tree

    def _wait(timeout_s, monitor, latch=None):
        if isinstance(outcome, BaseException):
            raise outcome
        return sc.LoginWait(outcome, waited)

    monkeypatch.setattr(pi, "_await_claude_login", _wait)
    monkeypatch.setattr(pi._seat_jail, "decide_seat_route", lambda leg, **k: seat_jail.SeatRoute(True))
    monkeypatch.setattr(pi._seat_jail_autoqualify, "ensure_qualified",
                        lambda leg: pi._seat_jail_autoqualify.Outcome("qualified"))
    monkeypatch.setattr(pi._sandbox_policy, "select_sandbox_root",
                        lambda **k: types.SimpleNamespace(fell_back=False, path=tmp_path,
                                                          host=None, reason=""))
    monkeypatch.setattr(pi._sandbox_policy, "ensure_staging_space", lambda *a, **k: None)
    monkeypatch.setattr(pi._sandbox_policy, "staging_root", lambda: tmp_path / "staging")
    (tmp_path / "staging").mkdir(exist_ok=True)
    monkeypatch.setattr(pi._review_stage, "stage_review_tree", _stage)
    monkeypatch.setattr(pi._sandbox_retention, "mark_as_sandbox", lambda *a, **k: None)
    monkeypatch.setattr(pi._seat_uid, "subordinate_range", lambda _f: (100000, 65536))
    monkeypatch.setattr(pi._seat_uid, "seat_id_count", lambda *a: 1)
    monkeypatch.setattr(pi._seat_uid, "lease_seat_id", lambda _n: contextlib.nullcontext(7))
    monkeypatch.setattr(pi._sandbox_egress, "isolated_network",
                        lambda **k: contextlib.nullcontext(
                            ["nsenter", "-t", "4242", "-U", "--net", "setpriv"]))
    monkeypatch.setattr(pi, "_prepare_jailed_claude", _prepare)
    if jailed_leg is not None:
        monkeypatch.setattr(pi, "_exec_jailed_claude_leg", jailed_leg)
    monkeypatch.setattr(pi, "ParentUnixBroker", _FakeBroker)
    monkeypatch.setattr(_FakeBroker, "invoked", 0)
    monkeypatch.setattr(pi, "revalidate_review_isolation_authorization", lambda *a, **k: None)
    monkeypatch.setattr(pi._advisor_board_backing, "_revalidate_staged_tree", lambda *a, **k: None)
    monkeypatch.setattr(pi, "derive_review_leg_authorization",
                        lambda *a, **k: types.SimpleNamespace(expires_monotonic_ns=time.monotonic_ns() + 10**12))
    monkeypatch.setattr(pi, "harden_subscription_model", lambda leg, model, effort=None: model)
    monkeypatch.setattr(pi, "_canonical_review_repo_authority", lambda _p: tmp_path)
    monkeypatch.setattr(pi, "_under_claude_code", lambda env=None: False)
    # The sealed route stops at its support probe (no CLI is run in tests).
    monkeypatch.setattr(pi, "_claude_code_support_status", lambda *a: (False, "missing_claude_cli"))
    monkeypatch.setattr(pi, "_exception_failure", lambda exc: (_ for _ in ()).throw(exc))
    spawned = pi._default_spawn(
        "claude", "ARTIFACT", mode="review", model="m", timeout_s=420,
        review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
        canonical_repo_authority=tmp_path, review_monitor=review_monitor,
    )
    calls["launched"] = _FakeBroker.invoked              # any provider launch, sealed or jailed
    return spawned, calls


@pytest.mark.parametrize("outcome", [sc.LOGIN_READY, sc.LOGIN_REFRESHED])
def test_a_renewed_login_launches_the_seat_jailed(monkeypatch, tmp_path, outcome):
    _spawned, calls = _spawn(monkeypatch, tmp_path, outcome)
    assert calls == {"prepare": 1, "launched": 1}     # the jailed route is taken


@pytest.mark.parametrize("outcome, code", [
    (sc.LOGIN_TIMEOUT, "claude_seat_login_token_expiring"),
    (sc.LOGIN_MISSING, "claude_seat_token_missing"),
])
def test_a_login_not_renewed_is_degraded_and_not_run(monkeypatch, tmp_path, outcome, code):
    spawned, calls = _spawn(monkeypatch, tmp_path, outcome)
    # Plan amendment A3b: no jail is built and NOTHING is launched -- no sealed substitute.
    assert calls == {"prepare": 0, "launched": 0}
    assert tuple(spawned)[:2] == ("DEGRADED", "")
    assert str(tuple(spawned)[2]) == code
    assert spawned.seat_notices == (code,)
    assert list((tmp_path / "staging").iterdir()) == []


def test_a_seat_with_no_credential_is_degraded_and_not_run(monkeypatch, tmp_path):
    spawned, calls = _spawn(monkeypatch, tmp_path, sc.LOGIN_READY)
    monkeypatch.setattr(pi._seat_jail, "decide_seat_route",
                        lambda leg, **k: seat_jail.SeatRoute(False, "claude_seat_token_missing"))
    from test_seat_notices import _FakeBroker

    monkeypatch.setattr(_FakeBroker, "invoked", 0)
    spawned = pi._default_spawn(
        "claude", "ARTIFACT", mode="review", model="m", timeout_s=420,
        review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
        canonical_repo_authority=tmp_path)
    assert tuple(spawned)[0] == "DEGRADED" and _FakeBroker.invoked == 0
    assert spawned.seat_notices == ("claude_seat_token_missing",)


def test_cancellation_during_the_wait_cancels_the_leg_and_leaves_no_scratch(monkeypatch,
                                                                            tmp_path):
    with pytest.raises(pi._ReviewOperationCancelled):
        _spawn(monkeypatch, tmp_path, sc.LoginWaitCancelled("review_operation_cancelled"))
    assert list((tmp_path / "staging").iterdir()) == []


def test_the_spawn_waits_before_staging_or_holding_a_seat(monkeypatch, tmp_path):
    order: list[str] = []
    real_wait = sc.LoginWait

    def _wait(timeout_s, monitor, latch=None):
        order.append("wait")
        return real_wait(sc.LOGIN_REFRESHED, 1.0)

    _spawned, _calls = _spawn(monkeypatch, tmp_path, sc.LOGIN_REFRESHED)
    monkeypatch.setattr(pi, "_await_claude_login", _wait)
    monkeypatch.setattr(pi._review_stage, "stage_review_tree",
                        lambda *a, **k: order.append("stage") or pytest.fail("stop"))
    monkeypatch.setattr(pi._seat_uid, "lease_seat_id",
                        lambda _n: order.append("lease") or pytest.fail("stop"))
    with contextlib.suppress(BaseException):
        pi._default_spawn(
            "claude", "ARTIFACT", mode="review", model="m", timeout_s=420,
            review_authorization=types.SimpleNamespace(staged_tree_sha256="a" * 64),
            canonical_repo_authority=tmp_path)
    assert order[:1] == ["wait"] and len(order) >= 2


def test_the_suite_never_sleeps_through_a_real_long_login_wait():
    with pytest.raises(pytest.fail.Exception, match="real login wait"):
        sc.await_login_margin(1800.0, max_wait_s=900.0, poll_s=30.0,
                              wait=lambda s: pytest.fail("slept"),
                              read_login=lambda: _login(time.time() + 60))


def test_a_bounded_legs_login_wait_is_charged_to_its_deadline(monkeypatch, tmp_path):
    seen = []

    def _jailed(seat, *, timeout_s, backstop_s, **_k):
        seen.append((timeout_s, backstop_s))
        return "OK", "review\n\nAGREE"

    _spawn(monkeypatch, tmp_path, sc.LOGIN_REFRESHED, waited=30.0, jailed_leg=_jailed)
    assert seen == [(390, 390)]                       # 420 s, less the 30 s waited
