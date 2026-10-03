"""agent-harness#1132, plan amendment A2: the jail is qualified on first use.

Every case runs on fakes: a fake qualification and a fake pass store. No test here runs the
real falsifier qualification (the suite-wide guard in conftest fails any test that would).
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from phase_loop_runtime import seat_jail, seat_uid
from phase_loop_runtime import seat_jail_autoqualify as aq
from phase_loop_runtime.seat_jail_qualification import QualificationError


@pytest.fixture(autouse=True)
def _state(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    aq._RECENT.clear()


class _Store:
    """A fake pass store and a fake qualification that records into it."""

    def __init__(self, *, passes: bool = True, delay: float = 0.0, raises=None):
        self.passed: set[str] = set()
        self.runs = 0
        self.passes, self.delay, self.raises = passes, delay, raises
        self._lock = threading.Lock()

    def verdict(self, digest):
        return (digest in self.passed, "pass" if digest in self.passed else "no_record")

    def qualify(self, leg):
        with self._lock:
            self.runs += 1
        time.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        if self.passes:
            self.passed.add(seat_jail.jail_profile_digest(leg))
            return {"result": "pass"}
        return {"result": "fail"}


def _ensure(store, **kw):
    return aq.ensure_qualified("claude", verdict=store.verdict, qualify=store.qualify, **kw)


def test_an_existing_pass_skips_the_qualification():
    store = _Store()
    store.passed.add(seat_jail.jail_profile_digest("claude"))
    assert _ensure(store) == aq.Outcome(aq.QUALIFIED) and store.runs == 0


def test_no_record_qualifies_on_first_use_then_reuses_the_pass():
    store = _Store()
    assert _ensure(store) == aq.Outcome(aq.QUALIFIED_NOW)
    assert _ensure(store) == aq.Outcome(aq.QUALIFIED) and store.runs == 1
    assert aq.recent_outcome(seat_jail.jail_profile_digest("claude")).state == aq.QUALIFIED


def test_a_failure_is_typed_cached_and_not_retried_within_its_ttl():
    store = _Store(passes=False)
    clock = [1000.0]
    first = _ensure(store, now=lambda: clock[0], retry_after_s=600)
    assert first == aq.Outcome(aq.FAILED, "falsifiers_failed") and store.runs == 1
    clock[0] += 599
    assert _ensure(store, now=lambda: clock[0], retry_after_s=600) == first
    assert store.runs == 1                                       # not retried on every seat
    clock[0] += 2
    _ensure(store, now=lambda: clock[0], retry_after_s=600)
    assert store.runs == 2                                       # retried after the TTL


@pytest.mark.parametrize("change", ["digest", "layout"])
def test_a_cached_failure_is_retried_as_soon_as_the_digest_or_layout_changes(monkeypatch,
                                                                            change):
    store = _Store(passes=False)
    _ensure(store, now=lambda: 1000.0, retry_after_s=3600)
    if change == "digest":
        real = seat_jail.jail_profile_digest
        monkeypatch.setattr(seat_jail, "jail_profile_digest", lambda leg: "b" * len(real(leg)))
    else:
        monkeypatch.setattr(seat_jail, "falsifier_layout_identity", lambda: "another-layout")
    _ensure(store, now=lambda: 1001.0, retry_after_s=3600)
    assert store.runs == 2


def test_concurrent_first_use_runs_the_qualification_once():
    store = _Store(delay=0.5)
    outcomes: list[aq.Outcome] = []
    threads = [threading.Thread(target=lambda: outcomes.append(_ensure(store)))
               for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert store.runs == 1
    assert len(outcomes) == 4 and all(o.qualified for o in outcomes)
    assert all(o.state == aq.QUALIFIED_NOW for o in outcomes)   # the waiters see it as new


@pytest.mark.parametrize("exc, reason", [
    (QualificationError(seat_uid.PREREQUISITE), "prerequisite_missing"),
    (QualificationError("egress isolation unavailable"), "prerequisite_missing"),
    (QualificationError("no /etc/machine-id: this host has no identity"), "prerequisite_missing"),
    (QualificationError("/x must be a directory you own ...; no pass recorded"), "store_unsafe"),
    (QualificationError("sentinel never became ready: {}"), "falsifiers_failed"),
    (TimeoutError("run"), "timeout"),
    (RuntimeError("boom"), "error"),
])
def test_a_qualification_that_cannot_run_falls_back_with_a_typed_reason(exc, reason):
    outcome = _ensure(_Store(raises=exc))
    assert outcome == aq.Outcome(aq.FAILED, reason)
    assert aq.REASON_FIXES[reason]


def test_a_held_lock_times_out_typed_and_uncached():
    import fcntl

    store = _Store()
    aq._private_dirs(seat_jail.state_home(), aq._state_dir())
    holder = os.open(aq.lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        assert _ensure(store, lock_wait_s=0.3) == aq.Outcome(aq.FAILED, "timeout")
    finally:
        os.close(holder)
    assert store.runs == 0
    assert _ensure(store) == aq.Outcome(aq.QUALIFIED_NOW)       # the timeout was not cached


@pytest.mark.parametrize("value, expected", [
    ("", aq.DEFAULT_RETRY_S), ("60", 60.0), ("0", 0.0), ("-1", aq.DEFAULT_RETRY_S),
    ("soon", aq.DEFAULT_RETRY_S)])
def test_the_retry_ttl_is_configurable(value, expected):
    assert aq.retry_s({aq.RETRY_ENV: value}) == expected


def test_the_suite_never_runs_a_real_first_use_qualification():
    # The conftest guard replaces the real qualification for every test.
    with pytest.raises(pytest.fail.Exception):
        aq._default_qualify("claude")
