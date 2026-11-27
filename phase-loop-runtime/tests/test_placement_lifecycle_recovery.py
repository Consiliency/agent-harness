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

Appended for agent-harness#1989: cancellation also ends every retrying lock wait and a
rung release after a failed bridge; start-up collects destroyed cleanup owners once their
attempt has journaled the completion; reap visits and counts one effect once.

Appended for agent-harness#1996: cancellation that arrives during backend resolution, lease
recovery or fencing starts no remote kill or listing, and the lease stays owned.

The fixtures are the SL-1 producer's own (``test_placement_lifecycle_process``).
"""

from __future__ import annotations

import json
import os
import threading
import time

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
    _arm_handover_interruption,
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


# -- agent-harness#1989: shared set-ups ---------------------------------------------------------

def _attempt_lock(env, request_id="req-1"):
    return env.state / "agent-toolkit" / "attempts" / f"{request_id}.lock"


def _owner_state(env, key):
    path = env.state / "agent-toolkit" / "cleanup" / f"{key}.json"
    return json.loads(path.read_text())["state"] if path.exists() else None


def _destroyed_owner_planned(env, monkeypatch):
    """Attempt req-1 unsettled at its bound with a planned transfer; a consumer destroyed the
    owner while the attempt was held, so the entry is still ``planned`` on disk."""
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    _arm_handover_interruption(monkeypatch, "after-plan")
    with pytest.raises(Interrupted):
        env.lifecycle()._startup()
    monkeypatch.undo()
    fd = _hold(_attempt_lock(env))
    try:
        reap(env.lifecycle())
    finally:
        os.close(fd)
    assert _states(_attempt(env)) == ["planned"] and _owner_state(env, rid) == "destroyed"
    return rid


def _settled_with_destroyed_owner(env, monkeypatch):
    """Attempt req-1 settled terminally with a materialized entry; the owner is destroyed."""
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    env.lifecycle()._startup()
    assert _attempt(env)["settled"] and _states(_attempt(env)) == ["materialized"]
    reap(env.lifecycle())
    assert _states(_attempt(env)) == ["materialized"] and _owner_state(env, rid) == "destroyed"
    return rid


def _hold_after_completed_journal(monkeypatch, path_of):
    """Hold ``path_of(record)`` right after the first journal that records a completed entry."""
    original = sp.PlacementLifecycle._journal_attempt
    held = []

    def journal(self, record):
        original(self, record)
        if not held and record.get("transfer") and "completed" in _states(record):
            held.append(_hold(path_of(record)))
    monkeypatch.setattr(sp.PlacementLifecycle, "_journal_attempt", journal)
    return held


@pytest.fixture
def foreign_sleeper():
    """Another thread of the process keeps calling ``time.sleep`` throughout the test, as a
    long-lived daemon left by an earlier test does in a single-process suite run. The
    lock-retry patch must observe only the lock's own pauses."""
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            time.sleep(0.001)
    thread = threading.Thread(target=loop, name="foreign-sleeper", daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(5)


def _sleeps_cancelling(monkeypatch, cancelled, clock=None, then=None):
    """Patch the lock retry sleep: the first call sets ``cancelled`` (then runs ``then``);
    later calls advance ``clock`` (or really sleep when there is none). Setting the event
    inside the first wait, not before the operation, makes the lock wait itself observe it.
    Returns the call list."""
    real_sleep = time.sleep
    calls = []

    def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 1:
            cancelled.set()
            if then is not None:
                then()
        if clock is not None:
            clock.now += seconds
        elif len(calls) > 1:
            real_sleep(seconds)
    monkeypatch.setattr(sp, "_sleep", sleep)
    return calls


def _completed_with_destroyed_owner(env, monkeypatch):
    """Attempt req-1 settled with its entry completed; the destroyed owner stayed because
    its removal lock was refused once."""
    rid = _destroyed_owner_planned(env, monkeypatch)
    held = _hold_after_completed_journal(monkeypatch, lambda record: _reservation_lock(env, rid))
    env.lifecycle()._startup()
    monkeypatch.undo()
    os.close(held[0])
    record = _attempt(env)
    assert record["settled"] and _states(record) == ["completed"] and _owner_state(env, rid) == "destroyed"
    return rid


def _write_malformed_attempt(env):
    """An attempt that parses but is malformed (a commit without a reservation), well before
    its bound, so start-up never touches it."""
    bad = env.state / "agent-toolkit" / "attempts" / "req-bad.json"
    bad.write_text(json.dumps({"request_id": "req-bad", "settled": False, "deadline_ms": 10 ** 12,
                               "started_at": env.clock.now, "commit": {}}))
    os.chmod(bad, 0o600)


def _record_fsyncs_and_removals(monkeypatch):
    events = []
    real_fsync, real_remove = sp._fsync_directory, sp._remove_journal
    monkeypatch.setattr(sp, "_fsync_directory",
                        lambda path: events.append(("fsync", path.name)) or real_fsync(path))
    monkeypatch.setattr(sp, "_remove_journal",
                        lambda path: events.append(("remove", path.parent.name)) or real_remove(path))
    return events


# -- agent-harness#1989 (a): the caller's cancellation reaches a bridge-failure cleanup ---------

def test_a_bridge_failure_after_cancellation_starts_no_remote_kill(env):
    from phase_loop_runtime.placement_bridge import BridgeUnavailable

    cancelled = threading.Event()

    def open_(reservation, exposure, *, cancelled):
        cancelled.set()
        raise BridgeUnavailable("bridge_cancelled")
    env.bridge.open = open_
    response, _raw, code = _reserve(env.lifecycle(), "req-c", cancelled)
    assert "kill" not in env.coordinator.calls, (code, response.outcome, response.code)
    assert (response.outcome, response.code) == ("timeout", UNCONFIRMED)
    assert getattr(env.bridge, "reclaimed", []), "the bridge reclaim still ran"
    assert len(env.coordinator.held) == 1, "the lease stays held for replay or terminal cleanup"
    record = _record(env, "req-c")
    assert record["settled"] is False and record["barrier"] == "armed" and record.get("commit")
    # A later, uncancelled start-up at the bound and a reap remove the lease exactly once.
    env.clock.now = _bound_of(record)
    env.lifecycle()._startup()
    reap(env.lifecycle())
    env.lifecycle()._startup()
    assert _kills(env) == 1 and env.coordinator.held == {}
    assert _record(env, "req-c")["settled"] and _cleanup_entries(env) == []


def test_an_uncancelled_bridge_failure_releases_the_rung_once(env):
    env.bridge.fail = True
    response, _raw, code = reserve(env.lifecycle(), "req-u")
    assert (response.outcome, code) == ("refused", 10)
    assert env.coordinator.calls.count("kill") == 1 and env.coordinator.held == {}


# -- agent-harness#1989 (c): cancellation ends lock waits, at every retrying site ---------------

def test_a_release_lock_wait_stops_on_cancellation(env, monkeypatch, foreign_sleeper):  # release
    response, _raw, _code = reserve(env.lifecycle())
    rid = response.reservation.reservation_id
    clock = _Monotonic(monkeypatch)
    cancelled = threading.Event()
    sleeps = _sleeps_cancelling(monkeypatch, cancelled, clock)
    fd = _hold(_reservation_lock(env, rid))
    try:
        released, _code = _release(env.lifecycle(), response.reservation.to_json(), cancelled)
    finally:
        os.close(fd)
    assert released.state == "cleanup_pending"
    assert len(sleeps) == 1, f"{len(sleeps)} lock-wait polls"
    monkeypatch.undo()
    assert env.bridge.closed == [] and _kills(env) == 0
    released, code = release(env.lifecycle(), response.reservation.to_json(), "rel-2")
    assert (code, released.state) == (0, "released")
    assert env.bridge.closed == [rid] and _kills(env) == 1


def test_an_admit_publish_lock_wait_stops_on_cancellation(env, monkeypatch, foreign_sleeper):  # admission
    original = sp.PlacementLifecycle._journal_commit
    held = []

    def journal_commit(self, record, commit):
        original(self, record, commit)
        if commit.get("complete") and not held:
            held.append(_hold(_reservation_lock(env, commit["reservation"]["reservation_id"])))
    monkeypatch.setattr(sp.PlacementLifecycle, "_journal_commit", journal_commit)
    clock = _Monotonic(monkeypatch)
    cancelled = threading.Event()
    sleeps = _sleeps_cancelling(monkeypatch, cancelled, clock)
    try:
        response, _raw, _code = _reserve(env.lifecycle(), "req-1", cancelled, deadline_ms=5000)
    finally:
        for fd in held:
            os.close(fd)
    assert (response.outcome, response.code) == ("timeout", TIMEOUT)
    assert len(sleeps) == 1, f"{len(sleeps)} lock-wait polls"
    monkeypatch.undo()
    rid = _attempt(env)["commit"]["reservation"]["reservation_id"]
    assert env.reservations() == [] and _kills(env) == 0
    env.clock.now = _bound_of(_attempt(env))
    env.lifecycle()._startup()
    reap(env.lifecycle())
    assert env.bridge.closed == [rid] and _kills(env) == 1 and env.coordinator.held == {}


def test_a_settle_committed_lock_wait_stops_on_cancellation(env, monkeypatch, foreign_sleeper):  # replay settle
    commit = _interrupt_reserve(env, monkeypatch, "before-publish", deadline_ms=5000)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now += 5
    env.verdict = "held_ready"
    clock = _Monotonic(monkeypatch)
    cancelled = threading.Event()
    sleeps = _sleeps_cancelling(monkeypatch, cancelled, clock)
    fd = _hold(_reservation_lock(env, rid))
    try:
        response, _raw, _code = _reserve(env.lifecycle(), "req-1", cancelled, deadline_ms=5000)
    finally:
        os.close(fd)
    assert (response.outcome, response.code) == ("timeout", TIMEOUT)
    assert not _attempt(env)["settled"]
    assert len(sleeps) == 1, f"{len(sleeps)} lock-wait polls"
    monkeypatch.undo()
    assert env.bridge.closed == [] and _kills(env) == 0
    env.clock.now = _bound_of(_attempt(env))
    env.lifecycle()._startup()
    reap(env.lifecycle())
    assert env.bridge.closed == [rid] and _kills(env) == 1 and env.coordinator.held == {}


def test_a_transfer_materialize_lock_wait_stops_on_cancellation(env, monkeypatch, foreign_sleeper):  # transfer
    _lose_the_create_reply(env)
    [effect] = _attempt(env)["pending"]
    key = f"req-1--{effect['lease_id']}"
    env.verdict = "nothing_held"
    clock = _Monotonic(monkeypatch)
    cancelled = threading.Event()
    sleeps = _sleeps_cancelling(monkeypatch, cancelled, clock)
    fd = _hold(env.state / "agent-toolkit" / "cleanup" / f"{key}.lock")
    try:
        response, _raw, _code = _reserve(env.lifecycle(), "req-1", cancelled)
    finally:
        os.close(fd)
    assert response.outcome == "unreachable" and _states(_attempt(env)) == ["planned"]
    assert len(sleeps) == 1, f"{len(sleeps)} lock-wait polls"
    monkeypatch.undo()
    kills = _kills(env)
    assert effect["lease_id"] in env.coordinator.held
    env.lifecycle()._startup()
    reap(env.lifecycle())
    assert _kills(env) == kills + 1 and env.coordinator.held == {}


def test_a_transfer_removal_lock_wait_stops_on_cancellation(env, monkeypatch, foreign_sleeper):  # owner removal
    rid = _destroyed_owner_planned(env, monkeypatch)
    monkeypatch.setattr(sp.PlacementLifecycle, "_startup", lambda self, *a, **k: None)
    held = _hold_after_completed_journal(monkeypatch, lambda record: _reservation_lock(env, rid))
    clock = _Monotonic(monkeypatch)
    cancelled = threading.Event()
    sleeps = _sleeps_cancelling(monkeypatch, cancelled, clock)
    try:
        response, _raw, _code = _reserve(env.lifecycle(), "req-1", cancelled, ttl_s=1)  # replay at bound
    finally:
        for fd in held:
            os.close(fd)
    assert response.outcome == "timeout" and _attempt(env)["settled"]
    assert _owner_state(env, rid) == "destroyed", "removal skipped once cancelled"
    assert len(sleeps) == 1, f"{len(sleeps)} lock-wait polls"
    monkeypatch.undo()
    env.lifecycle()._startup()
    assert _cleanup_entries(env) == [] and env.bridge.closed == [rid] and _kills(env) == 1


def test_a_local_slot_lock_wait_stops_on_cancellation(env, monkeypatch, foreign_sleeper):  # local slot
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    env.state.mkdir(parents=True, exist_ok=True)
    original = sp._ReserveWalk.local_admit
    bounds, done = [], threading.Event()

    def local_admit(self, settings, bound):
        bounds.append(bound)
        try:
            return original(self, settings, bound)
        finally:
            done.set()
    monkeypatch.setattr(sp._ReserveWalk, "local_admit", local_admit)
    cancelled = threading.Event()
    # The first retry sleep cancels the caller, then waits until the walk has cancelled the
    # call's own bound, so the next retry check sees it deterministically.
    sleeps = _sleeps_cancelling(monkeypatch, cancelled, then=lambda: bounds[0].cancelled.wait(5))
    fd = _hold(env.state / "local-slots.lock")
    try:
        response, _raw, _code = _reserve(env.lifecycle(), "req-1", cancelled, deadline_ms=2000)
        assert done.wait(5)
    finally:
        os.close(fd)
    assert response.reservation is None and env.slots() == []
    assert len(sleeps) == 1, f"{len(sleeps)} lock-wait polls after the bound was cancelled"


def test_a_pre_cancelled_uncontended_release_is_still_validated(env):
    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    cancelled = threading.Event()
    cancelled.set()
    rejected, code = _release(env.lifecycle(), {**stored, "transport_id": "elsewhere"}, cancelled, "rel-m")
    assert (code, rejected.state) == (10, "rejected")


def test_file_lock_takes_its_first_try_even_when_already_cancelled(env):
    env.state.mkdir(parents=True, exist_ok=True)
    cancelled = threading.Event()
    cancelled.set()
    lock = sp._FileLock(env.state / "probe.lock", blocking=False, deadline=sp._Deadline.after(5),
                        cancelled=cancelled)
    with lock as held:
        assert held


def test_file_lock_budget_check_ignores_foreign_thread_sleeps(tmp_path, monkeypatch, foreign_sleeper):
    """agent-harness#2207: patching process-wide ``time.sleep`` lets background threads
    advance the fake clock before the first ``flock`` call in single-process Gate A runs."""
    from test_placement_lifecycle_process import test_file_lock_checks_budget_after_retry_sleep

    real_sleep = time.sleep
    original_enter = sp._FileLock.__enter__
    checked = []

    def assert_global_sleep_unpatched(self):
        checked.append(time.sleep is real_sleep)
        return original_enter(self)

    monkeypatch.setattr(sp._FileLock, "__enter__", assert_global_sleep_unpatched)
    with monkeypatch.context() as inner:
        test_file_lock_checks_budget_after_retry_sleep(tmp_path, inner)
    assert checked == [True]


# -- agent-harness#1989 P3a: completed cleanup owners are collected -----------------------------

def test_a_settled_attempt_interrupted_after_its_completion_journal_keeps_no_owner(env, monkeypatch):
    rid = _settled_with_destroyed_owner(env, monkeypatch)
    _interrupt_after(monkeypatch, "_journal_attempt", when=lambda record: _states(record) == ["completed"])
    with pytest.raises(Interrupted):
        env.lifecycle()._startup()
    monkeypatch.undo()
    for _ in range(2):
        env.lifecycle()._startup()
    assert env.bridge.closed == [rid] and env.coordinator.calls.count("kill") == 1
    assert _cleanup_entries(env) == []


def test_a_refused_removal_lock_keeps_no_owner_after_a_later_start_up(env, monkeypatch):
    rid = _destroyed_owner_planned(env, monkeypatch)
    held = _hold_after_completed_journal(monkeypatch, lambda record: _reservation_lock(env, rid))
    env.lifecycle()._startup()
    monkeypatch.undo()
    os.close(held[0])
    for _ in range(2):
        env.lifecycle()._startup()
    assert _cleanup_entries(env) == [] and env.bridge.closed == [rid]
    assert env.coordinator.calls.count("kill") == 1


def test_a_malformed_attempt_keeps_tombstones_but_not_completed_owners(env, monkeypatch):
    # A second reservation, released first: its tombstone expires later in the test.
    other, _raw, _code = reserve(env.lifecycle(), "req-2")
    released, _code = release(env.lifecycle(), other.reservation.to_json(), "rel-2")
    assert released.state == "released"
    other_rid = other.reservation.reservation_id
    rid = _settled_with_destroyed_owner(env, monkeypatch)
    # Complete req-1's entry and refuse its removal (and any sweep) while the lock is held.
    held = _hold_after_completed_journal(monkeypatch, lambda record: _reservation_lock(env, rid))
    env.lifecycle()._startup()
    monkeypatch.undo()
    try:
        assert _states(_attempt(env)) == ["completed"] and _owner_state(env, rid) == "destroyed"
        _write_malformed_attempt(env)
    finally:
        os.close(held[0])
    env.clock.now += sp.TOMBSTONE_RETENTION_S + 1
    env.lifecycle()._startup()
    assert _tombstone(env, other_rid).exists(), "an unreadable attempt keeps every tombstone"
    assert _cleanup_entries(env) == [], "but never another attempt's completed owner"
    assert sorted(env.bridge.closed) == sorted([rid, other_rid]) and _kills(env) == 2


def test_the_attempt_snapshot_is_durable_before_the_first_tombstone_prune(env, monkeypatch):
    response, _raw, _code = reserve(env.lifecycle())
    release(env.lifecycle(), response.reservation.to_json(), "rel-1")
    env.clock.now += sp.TOMBSTONE_RETENTION_S + 1
    events = _record_fsyncs_and_removals(monkeypatch)
    env.lifecycle()._startup()
    monkeypatch.undo()
    assert ("remove", "tombstones") in events
    first = events.index(("remove", "tombstones"))
    assert ("fsync", "attempts") in events[:first], events
    assert env.bridge.closed == [response.reservation.reservation_id] and _kills(env) == 1


def test_the_attempt_snapshot_is_durable_before_the_first_owner_prune(env, monkeypatch):
    rid = _completed_with_destroyed_owner(env, monkeypatch)
    events = _record_fsyncs_and_removals(monkeypatch)
    env.lifecycle()._startup()
    monkeypatch.undo()
    assert ("remove", "cleanup") in events
    first = events.index(("remove", "cleanup"))
    assert ("fsync", "attempts") in events[:first], events
    assert _cleanup_entries(env) == [] and env.bridge.closed == [rid] and _kills(env) == 1


def test_an_unfinished_entry_keeps_its_destroyed_owner(env, monkeypatch):
    """Mutation M1 (drop the completed-evidence check) must turn this red."""
    rid = _destroyed_owner_planned(env, monkeypatch)
    fd = _hold(_attempt_lock(env))
    try:
        for _ in range(2):
            env.lifecycle()._startup()
        assert _owner_state(env, rid) == "destroyed", "removed before its entry completed"
    finally:
        os.close(fd)
    env.lifecycle()._startup()
    reap(env.lifecycle())
    assert _states(_attempt(env)) == ["completed"]
    assert env.bridge.closed == [rid] and env.coordinator.calls.count("kill") == 1


def _completed_entry_of_an_unsettled_attempt(env, monkeypatch):
    rid = _destroyed_owner_planned(env, monkeypatch)
    held = _hold_after_completed_journal(monkeypatch, lambda record: _reservation_lock(env, rid))
    _arm_handover_interruption(monkeypatch, "before-terminal-settlement")
    with pytest.raises(Interrupted):
        env.lifecycle()._startup()
    monkeypatch.undo()
    os.close(held[0])
    record = _attempt(env)
    assert not record["settled"] and _states(record) == ["completed"]
    return rid


@pytest.mark.parametrize("malformed", [False, True], ids=["alone", "beside-a-malformed-attempt"])
def test_a_completed_entry_of_an_unsettled_attempt_keeps_its_owner(env, monkeypatch, malformed):
    """Mutation M2 (ignore the attempt's own references) must turn this red. An unrelated
    malformed attempt does not change the answer."""
    rid = _completed_entry_of_an_unsettled_attempt(env, monkeypatch)
    if malformed:
        _write_malformed_attempt(env)
    fd = _hold(_attempt_lock(env))
    try:
        for _ in range(2):
            env.lifecycle()._startup()
        assert _owner_state(env, rid) == "destroyed", "removed while its attempt is unsettled"
    finally:
        os.close(fd)
    env.lifecycle()._startup()
    assert _attempt(env)["settled"] and _cleanup_entries(env) == []
    assert env.bridge.closed == [rid] and env.coordinator.calls.count("kill") == 1


@pytest.mark.parametrize("where", ["entry-lock-outside-the-two-names", "owner-lock-differs",
                                   "entry-and-owner-name-a-third-lock"])
def test_a_completed_owner_is_kept_unless_entry_and_owner_name_the_same_lock(env, monkeypatch, where):
    """Mutation M9 (trust the entry's lock without the allow-list or the owner cross-check)
    must turn this red."""
    rid = _completed_with_destroyed_owner(env, monkeypatch)
    attempt_path = env.state / "agent-toolkit" / "attempts" / "req-1.json"
    owner_path = env.state / "agent-toolkit" / "cleanup" / f"{rid}.json"
    attempt, owner = json.loads(attempt_path.read_text()), json.loads(owner_path.read_text())
    if where != "owner-lock-differs":
        attempt["transfer"]["entries"][0]["lock"] = "tombstones"
    if where == "owner-lock-differs":
        owner["lock"] = "cleanup"
    elif where == "entry-and-owner-name-a-third-lock":
        owner["lock"] = "tombstones"
    attempt_path.write_text(json.dumps(attempt))
    owner_path.write_text(json.dumps(owner))
    for _ in range(2):
        env.lifecycle()._startup()
    assert _owner_state(env, rid) == "destroyed"
    assert env.bridge.closed == [rid] and _kills(env) == 1


# -- agent-harness#1989 P3c: one logical effect is visited and counted once ---------------------

def _dual_candidate(env, monkeypatch):
    """After-owner-write: active record and cleanup owner of one reservation, attempt unsettled."""
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    _arm_handover_interruption(monkeypatch, "after-owner-write")
    with pytest.raises(Interrupted):
        env.lifecycle()._startup()
    monkeypatch.undo()
    return rid


def _recovered_once(env, rid):
    """An uncancelled start-up settles the attempt and collects the destroyed owner."""
    env.lifecycle()._startup()
    assert _attempt(env)["settled"] and _states(_attempt(env)) == ["completed"]
    assert _cleanup_entries(env) == [] and env.reservations() == []
    assert rid in env.bridge.closed and env.bridge.closed.count(rid) == 1


def test_one_logical_effect_counts_once(env, monkeypatch):
    rid = _dual_candidate(env, monkeypatch)
    fd = _hold(_attempt_lock(env))
    try:
        response, _code = reap(env.lifecycle())
    finally:
        os.close(fd)
    assert env.bridge.closed == [rid]
    assert (response.inventory.examined, response.inventory.destroyed) == (1, 1)
    _recovered_once(env, rid)
    assert _kills(env) == 1


def _dual_candidate_and_a_later_effect(env, monkeypatch):
    rid = _dual_candidate(env, monkeypatch)
    fd = _hold(_attempt_lock(env))
    try:
        env.clock.now += 10                    # the second effect sorts after the first's owner
        later, _raw, _code = reserve(env.lifecycle(), "req-2", ttl_s=1)
        env.clock.now += 100
    except BaseException:
        os.close(fd)
        raise
    return rid, later.reservation.reservation_id, fd


def test_max_items_bounds_distinct_effects(env, monkeypatch):
    """Red on the unfixed module only because req-2's created_at sorts after req-1's owner
    entry. Mutation M4 (merge applied after the slice) must turn this red."""
    rid, later, fd = _dual_candidate_and_a_later_effect(env, monkeypatch)
    try:
        response, _code = reap(env.lifecycle(), max_items=2)
    finally:
        os.close(fd)
    assert sorted(env.bridge.closed) == sorted([rid, later])
    assert (response.inventory.examined, response.inventory.destroyed) == (2, 2)
    _recovered_once(env, rid)
    assert _kills(env) == 2


def test_max_items_one_reaches_only_the_earliest_effect(env, monkeypatch):
    rid, _later, fd = _dual_candidate_and_a_later_effect(env, monkeypatch)
    try:
        response, _code = reap(env.lifecycle(), max_items=1)
    finally:
        os.close(fd)
    assert env.bridge.closed == [rid] and response.inventory.examined == 1


def test_a_reap_owner_lock_wait_stops_on_cancellation(env, monkeypatch, foreign_sleeper):  # reap
    held, _raw, _code = reserve(env.lifecycle(), "held", ttl_s=1)
    rid = held.reservation.reservation_id
    env.clock.now += 100
    clock = _Monotonic(monkeypatch)
    cancelled = threading.Event()
    sleeps = _sleeps_cancelling(monkeypatch, cancelled, clock)
    fd = _hold(_reservation_lock(env, rid))
    try:
        response, _code = _reap(env.lifecycle(), cancelled)
    finally:
        os.close(fd)
    assert len(sleeps) == 1, f"{len(sleeps)} lock-wait polls"
    assert (response.inventory.examined, response.inventory.pending) == (1, 1)
    monkeypatch.undo()
    assert env.bridge.closed == [] and _kills(env) == 0
    response, code = reap(env.lifecycle())
    assert (code, response.inventory.destroyed) == (0, 1)
    assert env.bridge.closed == [rid] and _kills(env) == 1


# -- agent-harness#1996: cancellation is checked again just before the remote kill ---------------

def _assert_kept_then_recovered(env, lease_id, calls):
    """No kill or listing began after the cancellation; the lease stays owned, recorded as
    unconfirmed, with its active record. A later uncancelled reap removes it once."""
    assert env.coordinator.calls[calls:] == [], env.coordinator.calls[calls:]
    assert lease_id in env.coordinator.held
    [entry] = env.leases()
    assert json.loads(entry.read_text()).get("abandoned") is True
    [active] = env.reservations()
    kept = json.loads(active.read_text())
    assert kept["state"] == "cleanup_pending" and kept["effect"]["lease_id"] == lease_id
    response, code = reap(env.lifecycle())
    assert (code, response.inventory.destroyed, response.inventory.pending) == (0, 1, 0)
    assert _kills(env) == 1 and lease_id not in env.coordinator.held
    assert env.leases() == [] and env.reservations() == []


@pytest.mark.parametrize("operation", ["release", "reap"])
def test_cancellation_during_backend_resolution_starts_no_remote_kill(env, operation):
    response, _raw, _code = reserve(env.lifecycle(), ttl_s=1)
    stored = response.reservation.to_json()
    lease_id = response.reservation.lease_id
    cancelled = threading.Event()
    resolved = []

    def backend_for(root):
        resolved.append(root)
        cancelled.set()                                    # the signal arrives during resolution
        return env.backend_for(root)
    lifecycle = env.lifecycle(backend_for=backend_for)
    calls = len(env.coordinator.calls)
    if operation == "release":
        pending, code = _release(lifecycle, stored, cancelled)
        assert (code, pending.state, pending.code) == (20, "cleanup_pending", UNCONFIRMED)
    else:
        env.clock.now += 100
        pending, code = _reap(lifecycle, cancelled)
        assert (code, pending.inventory.destroyed, pending.inventory.pending) == (20, 0, 1)
    assert len(resolved) == 1                              # resolution was reached once, in cleanup
    _assert_kept_then_recovered(env, lease_id, calls)


@pytest.mark.parametrize("step", ["recover", "fence"])
def test_cancellation_during_lease_preparation_starts_no_remote_kill(env, monkeypatch, step):
    from phase_loop_runtime import placement_lease

    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    lease_id = response.reservation.lease_id
    cancelled = threading.Event()
    seen = []
    if step == "recover":
        original_recover = placement_lease.recover_lease

        def recover(lease, **kwargs):
            recovered = original_recover(lease, **kwargs)
            seen.append(lease)
            cancelled.set()                                # the signal arrives during recovery
            return recovered
        monkeypatch.setattr(placement_lease, "recover_lease", recover)
    else:
        original_fence = placement_lease.Lease.fence

        def fence(self):
            original_fence(self)
            seen.append(self.lease_id)
            cancelled.set()                                # the signal arrives during fencing
        monkeypatch.setattr(placement_lease.Lease, "fence", fence)
    calls = len(env.coordinator.calls)
    pending, code = _release(env.lifecycle(), stored, cancelled)
    monkeypatch.undo()
    assert seen == [lease_id]
    assert (code, pending.state, pending.code) == (20, "cleanup_pending", UNCONFIRMED)
    _assert_kept_then_recovered(env, lease_id, calls)
