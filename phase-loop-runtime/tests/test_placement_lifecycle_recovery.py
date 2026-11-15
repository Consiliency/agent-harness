"""v13 PLACECLI SL-1, supplemental: completion proof retention and caller cancellation.

Two lifecycle properties, each driven through :class:`PlacementLifecycle` with injected
clocks, events, lock holds and interruption hooks (no wall-clock waits decide a result):

* A release tombstone is also the durable proof that a committed effect was destroyed.
  Its public expiry ends only what a repeated release answers; the file is pruned, under
  its reservation's lock, only once no recovery of that reservation is unfinished. A
  destroyed effect is therefore never handed to a second cleanup.
* The caller's deadline and cancellation reach start-up, terminal settlement, the
  cleanup transfer, release and reap. Once either fires, no further reconciliation,
  materialization or remote cleanup call begins, durable ownership is kept, and a later
  uncancelled operation recovers.

The fixtures are the SL-1 producer's own (``test_placement_lifecycle_process``).
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from phase_loop_runtime import placement_process_contract as contract
from phase_loop_runtime import sandbox_placement as sp
from test_placement_lifecycle_process import (
    END,
    TIMEOUT,
    UNCONFIRMED,
    Env,
    Interrupted,
    _any_reservation,
    _attempt,
    _bound_of,
    _cleanup_entries,
    _hold,
    _interrupt_after,
    _interrupt_reserve,
    _lose_the_create_reply,
    _owners,
    release,
    reap,
    reserve,
    reserve_body,
)

REFUSED = "sandbox_placement_refused"


@pytest.fixture
def env(tmp_path):
    built = Env(tmp_path)
    built.toolkit()
    built.harness()
    return built


def _reserve(lifecycle, request_id, cancelled, **kwargs):
    body = reserve_body(request_id, **kwargs)
    response = lifecycle.reserve(contract.decode_request("reserve", json.dumps(body).encode()),
                                 cancelled=cancelled)
    return response, contract.encode_response(response), contract.exit_class(response)


def _release(lifecycle, reservation, cancelled, request_id="rel-c", deadline_ms=5000):
    body = {"schema": "placement.release.request.v1", "request_id": request_id,
            "reservation": reservation, "deadline_ms": deadline_ms, "caller_context": {}}
    response = lifecycle.release(contract.decode_request("release", json.dumps(body).encode()),
                                 cancelled=cancelled)
    return response, contract.exit_class(response)


def _reap(lifecycle, cancelled, max_items=100, deadline_ms=5000):
    body = {"schema": "placement.reap.request.v1", "request_id": "reap-c", "scope": "caller_inventory",
            "deadline_ms": deadline_ms, "max_items": max_items, "caller_context": {}}
    response = lifecycle.reap(contract.decode_request("reap", json.dumps(body).encode()),
                              cancelled=cancelled)
    return response, contract.exit_class(response)


def _record(env, request_id):
    return json.loads((env.state / "agent-toolkit" / "attempts" / f"{request_id}.json").read_text())


def _states(record):
    return [entry["state"] for entry in record["transfer"]["entries"]]


def _tombstone(env, rid):
    return env.state / "agent-toolkit" / "tombstones" / f"{rid}.json"


def _reservation_lock(env, rid):
    return env.state / "agent-toolkit" / "reservations" / f"{rid}.lock"


def _kills(env):
    return env.coordinator.calls.count("kill")


class _Monotonic:
    """The lifecycle's monotonic clock, advanced only by the test."""

    def __init__(self, monkeypatch) -> None:
        self.now = 1_000.0
        monkeypatch.setattr(sp, "_monotonic", self)

    def __call__(self) -> float:
        return self.now

    def expire(self) -> None:
        self.now += 1_000_000.0


def _trigger(kind, cancelled, clock):
    return cancelled.set if kind == "cancelled" else clock.expire


def _gate_lock(monkeypatch, name, hook):
    """Run ``hook`` once, right after the first lock named ``name`` was taken."""
    original = sp._FileLock.__enter__
    fired = []

    def gated(self):
        taken = original(self)
        if self.path.name == name and not fired:
            fired.append(taken)
            hook()
        return taken
    monkeypatch.setattr(sp._FileLock, "__enter__", gated)
    return fired


def _recover(env, rid, commit):
    """A later, uncancelled start-up and reap remove the committed effect exactly once."""
    env.lifecycle()._startup()
    reap(env.lifecycle())
    env.lifecycle()._startup()
    assert _owners(env, rid) == 0 and env.reservations() == [] and _cleanup_entries(env) == []
    assert env.bridge.closed == [rid] and commit["effect"]["lease_id"] not in env.coordinator.held
    record = _attempt(env)
    assert record["settled"] and json.loads(record["response"])["code"] == END
    assert _states(record) == ["completed"]


# -- a tombstone is kept as completion proof until no recovery needs it ------------------------

def _released_before_the_bound(env, monkeypatch):
    """A durable, published admission interrupted before settlement and released by its
    caller before the settle bound: the effect is destroyed, its tombstone is the only
    record of that, and the attempt has planned no transfer yet. The clock then passes
    both the settle bound and the tombstone's public expiry with no operation between."""
    commit = _interrupt_reserve(env, monkeypatch, "after-publish")
    rid = commit["reservation"]["reservation_id"]
    env.clock.now += 10
    released, code = release(env.lifecycle(), commit["reservation"])
    assert (code, released.state) == (0, "released")
    record = _attempt(env)
    assert record["settled"] is False and "transfer" not in record
    assert env.bridge.closed == [rid] and _kills(env) == 1 and _tombstone(env, rid).exists()
    env.clock.now += sp.TOMBSTONE_RETENTION_S + 1
    return commit, rid


def _assert_cleaned_once(env, rid, commit):
    """Two restarts and a reap: the destroyed effect is never cleaned again, the hand-over
    completes, the proof is pruned, and every replay repeats the settled bytes."""
    for _ in range(2):
        env.lifecycle()._startup()
    reap(env.lifecycle())
    assert env.bridge.closed == [rid] and _kills(env) == 1
    assert commit["effect"]["lease_id"] not in env.coordinator.held
    record = _attempt(env)
    assert record["settled"] and json.loads(record["response"])["code"] == END
    assert _states(record) == ["completed"]
    assert _cleanup_entries(env) == [] and env.reservations() == []
    assert not _tombstone(env, rid).exists()
    raw = record["response"].encode("utf-8")
    for _ in range(2):
        assert reserve(env.lifecycle())[1] == raw
    gone, code = release(env.lifecycle(), commit["reservation"], "rel-late")
    assert (code, gone.state) == (10, "unknown_reservation")
    assert env.bridge.closed == [rid] and _kills(env) == 1


def test_a_tombstone_expiring_before_its_hand_over_still_completes_it_without_a_second_cleanup(
        env, monkeypatch):
    commit, rid = _released_before_the_bound(env, monkeypatch)
    fd = _hold(_reservation_lock(env, rid))
    try:
        # This operation's start-up settles the attempt, but cannot hand its effect over.
        reap(env.lifecycle())
    finally:
        os.close(fd)
    record = _attempt(env)
    assert record["settled"] and json.loads(record["response"])["code"] == END
    assert _states(record) == ["planned"]
    assert _tombstone(env, rid).exists()
    _assert_cleaned_once(env, rid, commit)


def test_an_unsettled_commit_keeps_its_tombstone_while_its_attempt_is_held(env, monkeypatch):
    commit, rid = _released_before_the_bound(env, monkeypatch)
    fd = _hold(env.state / "agent-toolkit" / "attempts" / "req-1.lock")
    try:
        reap(env.lifecycle())                              # its start-up skips the held attempt
        record = _attempt(env)
        assert record["settled"] is False and "transfer" not in record
        assert _tombstone(env, rid).exists()
        # Publicly the reservation is gone, while recovery still keeps its proof.
        gone, code = release(env.lifecycle(), commit["reservation"], "rel-2")
        assert (code, gone.state, gone.code) == (10, "unknown_reservation", REFUSED)
        assert gone.flags.barrier_confirmed and not gone.flags.reserved
        assert _tombstone(env, rid).exists()
    finally:
        os.close(fd)
    _assert_cleaned_once(env, rid, commit)


def test_an_expired_tombstone_is_removed_only_under_its_reservation_lock(env):
    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    rid = response.reservation.reservation_id
    assert release(env.lifecycle(), stored)[0].state == "released"
    env.clock.now += sp.TOMBSTONE_RETENTION_S + 1
    fd = _hold(_reservation_lock(env, rid))
    try:
        env.lifecycle()._startup()
        assert _tombstone(env, rid).exists()               # the lock was refused: left intact
        gone, code = release(env.lifecycle(), stored, "rel-2", deadline_ms=300)
        assert (code, gone.state) == (10, "unknown_reservation")
        assert _tombstone(env, rid).exists()
    finally:
        os.close(fd)
    env.lifecycle()._startup()
    assert not _tombstone(env, rid).exists()               # nothing refers to it any more


@pytest.mark.parametrize("point", ["before-acknowledgment", "after-completion"])
def test_an_interrupted_completion_keeps_the_tombstone_until_the_attempt_records_it(
        env, monkeypatch, point):
    commit, rid = _released_before_the_bound(env, monkeypatch)
    fd = _hold(_reservation_lock(env, rid))
    try:
        reap(env.lifecycle())
    finally:
        os.close(fd)
    if point == "before-acknowledgment":
        # The entry is recognized as completed, but the attempt has not journaled it.
        _interrupt_after(monkeypatch, "_materialize")
    else:
        _interrupt_after(monkeypatch, "_journal_attempt",
                         when=lambda record: _states(record) == ["completed"])
    with pytest.raises(Interrupted):
        env.lifecycle()._startup()
    monkeypatch.undo()
    assert _tombstone(env, rid).exists()
    expected = "planned" if point == "before-acknowledgment" else "completed"
    assert _states(_attempt(env)) == [expected]
    _assert_cleaned_once(env, rid, commit)


# -- the caller's deadline and cancellation reach every lifecycle step -------------------------

@pytest.mark.parametrize("operation", ["reserve", "release", "reap"])
def test_a_pre_cancelled_operation_begins_no_start_up_work(env, monkeypatch, operation):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    effects, opened = list(env.coordinator.effects), list(env.bridge.opened)
    cancelled = threading.Event()
    cancelled.set()
    lifecycle = env.lifecycle()
    if operation == "reserve":
        response, _raw, code = _reserve(lifecycle, "fresh", cancelled)
        assert (code, response.outcome, response.code, response.reservation) == (10, "refused", REFUSED, None)
    elif operation == "release":
        response, code = _release(lifecycle, commit["reservation"], cancelled)
        assert (code, response.state, response.code) == (20, "cleanup_pending", UNCONFIRMED)
        assert response.flags.cleanup_pending and not response.flags.barrier_confirmed
    else:
        response, code = _reap(lifecycle, cancelled)
        assert (code, response.state) == (20, "cleanup_pending")
        assert (response.inventory.examined, response.inventory.destroyed, response.inventory.pending) == (0, 0, 1)
    record = _attempt(env)
    assert record["settled"] is False and "transfer" not in record
    [active] = env.reservations()
    assert active.stem == rid and json.loads(active.read_text())["state"] == "active"
    assert _cleanup_entries(env) == [] and env.counts["reconcile"] == 0
    assert env.coordinator.effects == effects and env.bridge.opened == opened and env.bridge.closed == []
    _recover(env, rid, commit)


def _lost_reply(env, request_id):
    """An attempt whose create reply was lost and whose kill went unanswered: it owns one
    uncertain lease and stays unsettled. Returns that lease id."""
    def admit(request, bound):
        env.coordinator.held[request.lease_id] = request.owner_id
        raise sp.PlacementUnavailable(TIMEOUT, uncertain=True)
    env.coordinator.behave["admit"] = admit
    env.coordinator.behave["kill"] = lambda lease_id, bound: (_ for _ in ()).throw(OSError())
    response, _raw, code = reserve(env.lifecycle(), request_id)
    assert code == 20 and response.reservation is None
    env.coordinator.behave.clear()
    [effect] = _record(env, request_id)["pending"]
    return effect["lease_id"]


@pytest.mark.parametrize("operation", ["reserve", "release", "reap"])
def test_cancellation_during_start_up_begins_no_further_attempt(env, monkeypatch, operation):
    other, _raw, _code = reserve(env.lifecycle(), "other")
    lease_a, lease_b = _lost_reply(env, "req-a"), _lost_reply(env, "req-b")
    env.clock.now = _bound_of(_record(env, "req-a"))
    cancelled = threading.Event()
    original = sp.PlacementLifecycle._settle

    def settle(self, record, response):
        settled = original(self, record, response)
        if record["request_id"] == "req-a":
            cancelled.set()                                # the signal arrives mid-scan
        return settled
    monkeypatch.setattr(sp.PlacementLifecycle, "_settle", settle)
    effects = list(env.coordinator.effects)
    lifecycle = env.lifecycle()
    if operation == "reserve":
        response, _raw, code = _reserve(lifecycle, "fresh", cancelled)
        assert (code, response.outcome, response.code, response.reservation) == (10, "refused", REFUSED, None)
    elif operation == "release":
        response, code = _release(lifecycle, other.reservation.to_json(), cancelled)
        assert (code, response.state, response.code) == (20, "cleanup_pending", UNCONFIRMED)
        assert other.reservation.lease_id in env.coordinator.held
    else:
        response, code = _reap(lifecycle, cancelled)
        assert (code, response.state, response.inventory.destroyed) == (20, "cleanup_pending", 0)
    monkeypatch.undo()
    first, second = _record(env, "req-a"), _record(env, "req-b")
    assert first["settled"] and json.loads(first["response"])["code"] == END
    assert second["settled"] is False and "transfer" not in second
    assert [path.stem for path in _cleanup_entries(env)] == [f"req-a--{lease_a}"]
    assert env.coordinator.effects == effects and env.counts["reconcile"] == 0
    assert other.reservation.reservation_id in [path.stem for path in env.reservations()]
    # A later uncancelled operation settles the rest and cleans each effect once.
    env.lifecycle()._startup()
    assert _record(env, "req-b")["settled"]
    reap(env.lifecycle())
    env.lifecycle()._startup()
    assert _cleanup_entries(env) == []
    assert lease_a not in env.coordinator.held and lease_b not in env.coordinator.held


def _two_pending_effects(env):
    """``req-1`` owning two uncertain leases, so that its hand-over has two entries."""
    _lose_the_create_reply(env)
    path = env.state / "agent-toolkit" / "attempts" / "req-1.json"
    record = json.loads(path.read_text())
    [first] = record["pending"]
    second = {**first, "lease_id": "e" * 32}
    env.coordinator.held[second["lease_id"]] = env.coordinator.held[first["lease_id"]]
    record["pending"] = [first, second]
    sp._write_journal(path, record)
    return first, second


@pytest.mark.parametrize("trigger", ["cancelled", "expired"])
def test_no_further_transfer_entry_is_materialized_once_cancelled_or_out_of_time(env, monkeypatch, trigger):
    first, second = _two_pending_effects(env)
    first_key, second_key = f"req-1--{first['lease_id']}", f"req-1--{second['lease_id']}"
    env.clock.now = _bound_of(_attempt(env))
    cancelled = threading.Event()
    fire = _trigger(trigger, cancelled, _Monotonic(monkeypatch))
    original = sp.PlacementLifecycle._materialize
    materialized = []

    def materialize(self, entry):
        state = original(self, entry)
        materialized.append(entry["key"])
        fire()
        return state
    monkeypatch.setattr(sp.PlacementLifecycle, "_materialize", materialize)
    original_enter = sp._FileLock.__enter__
    taken = []

    def enter(self):
        held = original_enter(self)
        if held:
            taken.append(self.path.name)
        return held
    monkeypatch.setattr(sp._FileLock, "__enter__", enter)
    effects = list(env.coordinator.effects)
    response, code = _reap(env.lifecycle(), cancelled)
    monkeypatch.undo()
    assert materialized == [first_key]
    assert f"{first_key}.lock" in taken and f"{second_key}.lock" not in taken
    record = _attempt(env)
    # Touched at its bound: the terminal settlement and the whole plan are durable.
    assert record["settled"] and record["barrier"] == "armed"
    assert json.loads(record["response"])["code"] == END
    assert [(entry["key"], entry["state"]) for entry in record["transfer"]["entries"]] == [
        (first_key, "materialized"), (second_key, "planned")]
    assert [path.stem for path in _cleanup_entries(env)] == [first_key]
    assert (code, response.inventory.examined, response.inventory.pending) == (20, 0, 1)
    assert env.coordinator.effects == effects
    env.lifecycle()._startup()
    assert _states(_attempt(env)) == ["materialized", "materialized"]
    reap(env.lifecycle())
    env.lifecycle()._startup()
    assert _states(_attempt(env)) == ["completed", "completed"] and _cleanup_entries(env) == []
    assert first["lease_id"] not in env.coordinator.held and second["lease_id"] not in env.coordinator.held


@pytest.mark.parametrize("trigger", ["cancelled", "expired"])
@pytest.mark.parametrize("gate", ["attempt-lock", "owner-lock"])
def test_start_up_stops_at_a_lock_gate_once_cancelled_or_out_of_time(env, monkeypatch, gate, trigger):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish")
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    cancelled = threading.Event()
    fire = _trigger(trigger, cancelled, _Monotonic(monkeypatch))
    fired = _gate_lock(monkeypatch, "req-1.lock" if gate == "attempt-lock" else f"{rid}.lock", fire)
    effects = list(env.coordinator.effects)
    response, _code = _reap(env.lifecycle(), cancelled)
    monkeypatch.undo()
    assert fired == [True]                                 # the gate's lock was taken
    record = _attempt(env)
    if gate == "attempt-lock":
        assert record["settled"] is False and "transfer" not in record
    else:
        # The attempt already touched settles terminally with its durable plan only.
        assert record["settled"] and record["barrier"] == "armed"
        assert json.loads(record["response"])["code"] == END
        assert _states(record) == ["planned"]
    assert [path.stem for path in env.reservations()] == [rid] and _cleanup_entries(env) == []
    assert response.inventory.destroyed == 0 and env.bridge.closed == []
    assert env.coordinator.effects == effects
    _recover(env, rid, commit)


def test_a_cancelled_replay_at_its_bound_settles_terminally_with_a_planned_transfer(env, monkeypatch):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish")
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    cancelled = threading.Event()
    cancelled.set()
    response, raw, code = _reserve(env.lifecycle(), "req-1", cancelled)
    assert (code, response.outcome, response.code, response.reservation) == (20, "timeout", END, None)
    record = _attempt(env)
    assert record["settled"] and record["barrier"] == "armed" and _states(record) == ["planned"]
    assert [path.stem for path in env.reservations()] == [rid] and _cleanup_entries(env) == []
    assert env.counts["reconcile"] == 0 and env.bridge.closed == []
    assert reserve(env.lifecycle())[1] == raw              # an uncancelled replay repeats it
    _recover(env, rid, commit)


def test_a_cancelled_replay_before_its_bound_reconciles_nothing(env, monkeypatch):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish")
    env.clock.now += 30
    env.verdict = "held_ready"
    cancelled = threading.Event()
    cancelled.set()
    response, _raw, code = _reserve(env.lifecycle(), "req-1", cancelled)
    assert (code, response.outcome, response.code, response.reservation) == (20, "timeout", TIMEOUT, None)
    assert env.counts["reconcile"] == 0
    record = _attempt(env)
    assert record["settled"] is False and record["commit"]["complete"] and "transfer" not in record
    recovered, _raw, code = reserve(env.lifecycle())
    assert code == 0 and recovered.reservation.to_json() == commit["reservation"]
    assert env.counts["reconcile"] == 1


def test_a_cancelled_release_is_still_validated_and_starts_no_teardown(env):
    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    rid, lease_id = response.reservation.reservation_id, response.reservation.lease_id
    cancelled = threading.Event()
    cancelled.set()
    rejected, code = _release(env.lifecycle(), {**stored, "transport_id": "elsewhere"}, cancelled, "rel-m")
    assert (code, rejected.state) == (10, "rejected")
    rejected, code = _release(env.lifecycle("agent-harness"), stored, cancelled, "rel-x")
    assert (code, rejected.state) == (10, "rejected")
    unknown, code = _release(env.lifecycle(), {**_any_reservation(), "reservation_id": "rsv-" + "0" * 32},
                             cancelled, "rel-u")
    assert (code, unknown.state) == (10, "unknown_reservation")
    pending, code = _release(env.lifecycle(), stored, cancelled)
    assert (code, pending.state, pending.code) == (20, "cleanup_pending", UNCONFIRMED)
    assert pending.flags.cleanup_pending and not pending.flags.barrier_confirmed
    assert env.bridge.closed == [] and "kill" not in env.coordinator.calls
    assert lease_id in env.coordinator.held and len(env.leases()) == 1
    [active] = env.reservations()
    assert json.loads(active.read_text())["state"] == "active"
    released, code = release(env.lifecycle(), stored, "rel-2")
    assert (code, released.state) == (0, "released")
    assert env.bridge.closed == [rid] and lease_id not in env.coordinator.held and env.leases() == []


def test_a_release_cancelled_during_bridge_teardown_starts_no_remote_cleanup(env, monkeypatch):
    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    rid, lease_id = response.reservation.reservation_id, response.reservation.lease_id
    caller = threading.Event()
    original_close = env.bridge.close
    received = []

    def close(handle, *, cancelled):
        received.append(cancelled)
        flags = original_close(handle, cancelled=cancelled)
        caller.set()                                       # the signal arrives during teardown
        return flags
    monkeypatch.setattr(env.bridge, "close", close)
    calls = len(env.coordinator.calls)
    pending, code = _release(env.lifecycle(), stored, caller)
    monkeypatch.undo()
    assert received == [caller]                            # the caller's own event reached the bridge
    assert (code, pending.state, pending.code) == (20, "cleanup_pending", UNCONFIRMED)
    assert env.bridge.closed == [rid] and env.coordinator.calls[calls:] == []
    # The lease is neither killed nor forgotten: it stays with the active record.
    assert lease_id in env.coordinator.held and len(env.leases()) == 1
    [active] = env.reservations()
    kept = json.loads(active.read_text())
    assert kept["state"] == "cleanup_pending" and kept["effect"]["lease_id"] == lease_id
    released, code = release(env.lifecycle(), stored, "rel-2")
    assert (code, released.state) == (0, "released")
    assert lease_id not in env.coordinator.held and env.leases() == [] and env.reservations() == []


def test_a_kill_in_progress_when_cancelled_finishes_and_its_lease_stays_owned(env):
    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    lease_id = response.reservation.lease_id
    caller = threading.Event()
    env.coordinator.behave["kill"] = lambda lease_id, bound: caller.set()
    calls = len(env.coordinator.calls)
    pending, code = _release(env.lifecycle(), stored, caller)
    env.coordinator.behave.clear()
    assert (code, pending.state, pending.code) == (20, "cleanup_pending", UNCONFIRMED)
    # The started kill ran to its end; no owner listing began after the cancellation.
    assert env.coordinator.calls[calls:] == ["kill"] and lease_id not in env.coordinator.held
    assert len(env.leases()) == 1                          # unconfirmed: still recorded
    [active] = env.reservations()
    kept = json.loads(active.read_text())
    assert kept["state"] == "cleanup_pending" and kept["effect"]["lease_id"] == lease_id
    released, code = release(env.lifecycle(), stored, "rel-2")
    assert (code, released.state) == (0, "released")
    assert env.leases() == [] and env.reservations() == []


def test_a_reap_item_cancelled_at_its_lock_is_left_pending(env, monkeypatch):
    held, _raw, _code = reserve(env.lifecycle(), "held", ttl_s=1)
    rid = held.reservation.reservation_id
    env.clock.now += 100
    cancelled = threading.Event()
    fired = _gate_lock(monkeypatch, f"{rid}.lock", cancelled.set)
    response, code = _reap(env.lifecycle(), cancelled)
    monkeypatch.undo()
    assert fired == [True]
    assert (code, response.inventory.examined, response.inventory.destroyed, response.inventory.pending) == (
        20, 1, 0, 1)
    assert env.bridge.closed == [] and "kill" not in env.coordinator.calls
    assert held.reservation.lease_id in env.coordinator.held
    [active] = env.reservations()
    assert json.loads(active.read_text())["state"] == "active"
    response, code = reap(env.lifecycle())
    assert (code, response.inventory.destroyed) == (0, 1) and env.bridge.closed == [rid]
