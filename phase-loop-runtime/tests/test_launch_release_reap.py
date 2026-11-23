"""v13 LANEEXEC SL-3: release, reap and cancel at the ``PlacementLifecycle`` hook.

C11 cleanup and races, and the C7 state transitions on journaled records: release of a
prepared, never-launched reservation; release cancelling a live attempt through the
verified owner and then ``cleanup_pending``; reap settling only a verifiably gone owner;
caller-scoped reap with the other inventory invisible. Every case enters through
:func:`build_launch_service` and the production ``release``/``reap`` of a real lifecycle.
The local end-to-end supervisor and capped-parent evidence belong to SL-8.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from phase_loop_runtime import launch_process_contract as launch
from phase_loop_runtime import launch_service
from phase_loop_runtime import openshell_artifacts
from phase_loop_runtime import placement_process_contract as contract
from phase_loop_runtime import run_status
from phase_loop_runtime import sandbox_placement as sp
from phase_loop_runtime import seat_resource_caps
from phase_loop_runtime.launch_return import ReturnAttempt, ReturnPolicy, collect_return

# -- fixture: a real PlacementLifecycle and LaunchService on a temporary inventory ---------
#
# Reservations are made through ``PlacementLifecycle.reserve``; every collaborator with an
# effect is injected at its construction site. Nothing patches ``seat_resource_caps``.

DIGEST = "sha256:" + "c" * 64
NOW = 1_800_000_000.0
ANTHROPIC = [{"host": "api.anthropic.com", "port": 443}]


class Coordinator:
    """A fake OpenShell coordinator: admits and lists leases by owner."""

    def __init__(self) -> None:
        self.held: dict[str, str] = {}

    def capabilities(self):
        return frozenset()

    def declaration(self):
        return sp.Declaration()

    def available(self, request):
        return True

    def endpoint(self, root):
        return None

    def admit(self, request, bound):
        self.held[request.lease_id] = request.owner_id

    def kill(self, lease_id, bound):
        self.held.pop(lease_id, None)

    def list_owned(self, owner_id, bound):
        return [(f"sbx-{lease[:8]}", lease) for lease, owner in self.held.items() if owner == owner_id]


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.config = tmp_path / "config"
        self.config.mkdir(mode=0o700)
        self.state = tmp_path / "state"
        self.worker = tmp_path / "worker"
        self.clock = Clock()
        self.coordinator = Coordinator()
        self.caps_error = False
        self.ids = iter(f"{n:032x}" for n in range(1, 100_000))
        self.cancels: list[tuple[str, str]] = []
        self.cancel_outcome: object = "cancel_pending"
        self.on_cancel = None
        self.owner = "live"
        self.journal: dict[str, object] = {}
        self.write("agent-toolkit.json", {
            "schema": "placement.client-config.v1", "client": "agent-toolkit",
            "providers": {"anthropic": {"endpoints": ANTHROPIC, "workloads": ["pi-runner"],
                                        "policy_vectors": ["full-remote-pi-runner",
                                                           "minimal-without-app"]}},
            "targets": [{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}]})
        self.write("agent-harness.json", {
            "schema": "placement.client-config.v1", "client": "agent-harness",
            "providers": {"anthropic": {"endpoints": ANTHROPIC,
                                        "workloads": ["leg", "qualification", "implementation"],
                                        "policy_vectors": ["minimal-with-app", "minimal-without-app"]}},
            "targets": [{"name": "ai", "kind": "openshell", "rank": 0, "transport_id": "ai-openshell",
                         "root": "openshell://ai/placement", "probe_receipt_providers": ["anthropic"]},
                        {"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}],
            "seat_route": {"leg": "ai", "qualification": "local", "implementation": "ai"}})

    def write(self, name: str, body: dict) -> None:
        path = self.config / name
        path.write_text(json.dumps(body))
        os.chmod(path, 0o600)

    def caps(self):
        if self.caps_error:
            raise seat_resource_caps.CapsUnavailable("seat_resource_caps_unavailable")
        return seat_resource_caps.DEFAULT_CAPS

    def launch_cancel(self, claim, wait_s):
        self.cancels.append((str(claim["request_id"]), str(claim["run_id"])))
        if self.on_cancel is not None:
            self.on_cancel(claim)
        if isinstance(self.cancel_outcome, BaseException):
            raise self.cancel_outcome
        return self.cancel_outcome

    def lifecycle(self, client="agent-toolkit", **overrides) -> sp.PlacementLifecycle:
        kwargs = dict(
            state_root=self.state, config_root=self.config, caps_loader=self.caps,
            caps_readiness=lambda: None,
            observe=lambda: {"memory_available_bytes": 64 << 30, "memory_total_bytes": 128 << 30,
                             "load_per_cpu_percent": 10.0, "io_full_avg10": 0.0,
                             "memory_some_avg10": 0.0},
            backend_for=lambda root: self.coordinator if getattr(root, "scheme", "") == "openshell" else None,
            reconcile=lambda record, timeout_s: "indeterminate", clock=self.clock,
            new_id=lambda: next(self.ids), launch_cancel=self.launch_cancel,
            launch_owner=lambda claim: self.owner)
        kwargs.update(overrides)
        return sp.PlacementLifecycle(client, **kwargs)

    def attempt_status(self, state_root, attempt_id):
        assert state_root == self.worker
        return self.journal.get(attempt_id)

    def cancel_attempt(self, state_root, attempt_id, wait_s):
        assert state_root == self.worker and 0 < wait_s <= 10
        self.cancels.append(("service", attempt_id))
        if isinstance(self.cancel_outcome, BaseException):
            raise self.cancel_outcome
        return self.cancel_outcome

    def service(self, client="agent-toolkit", lifecycle=None, **overrides):
        lifecycle = lifecycle or self.lifecycle(client)
        kwargs = dict(config=lifecycle.config(), lifecycle=lifecycle, load_caps=self.caps,
                      readiness_code=lambda: None, capped_popen=self.no_popen,
                      worker_state_root=self.worker, attempt_status=self.attempt_status,
                      cancel_attempt=self.cancel_attempt)
        kwargs.update(overrides)
        return launch_service.build_launch_service(client, **kwargs)

    @staticmethod
    def no_popen(*args, **kwargs):
        raise AssertionError("no SL-3 path starts a process")

    def reserve(self, client="agent-toolkit", request_id=None, *, ttl_s=600):
        workload = "pi-runner" if client == "agent-toolkit" else "implementation"
        body = {"schema": "placement.reserve.request.v1",
                "request_id": request_id or f"rsv-req-{next(self.ids)[-6:]}",
                "workload": workload, "ttl_s": ttl_s, "image_digest": DIGEST,
                "policy_vector": "full-remote-pi-runner" if client == "agent-toolkit" else "minimal-with-app",
                "providers": ["anthropic"], "deadline_ms": 60000, "caller_context": {}}
        lifecycle = self.lifecycle(client)
        response = lifecycle.reserve(contract.decode_request("reserve", json.dumps(body).encode()),
                                     cancelled=threading.Event())
        assert response.outcome == "admitted", response
        return response.reservation.to_json()

    def release(self, reservation, client="agent-toolkit", deadline_ms=5000):
        body = {"schema": "placement.release.request.v1", "request_id": f"rel-{next(self.ids)[-6:]}",
                "reservation": reservation, "deadline_ms": deadline_ms, "caller_context": {}}
        response = self.lifecycle(client).release(
            contract.decode_request("release", json.dumps(body).encode()), cancelled=threading.Event())
        return response, contract.exit_class(response)

    def reap(self, client="agent-toolkit", deadline_ms=5000):
        body = {"schema": "placement.reap.request.v1", "request_id": f"reap-{next(self.ids)[-6:]}",
                "scope": "caller_inventory", "deadline_ms": deadline_ms, "max_items": 100,
                "caller_context": {}}
        response = self.lifecycle(client).reap(
            contract.decode_request("reap", json.dumps(body).encode()), cancelled=threading.Event())
        return response, contract.exit_class(response)

    def launch_root(self, client="agent-toolkit") -> Path:
        return self.state / client / "laneexec"


def prepare_request(reservation, request_id="prep-1", snapshot_root="/src/repo", context=None):
    body = {"schema": "placement.launch.prepare.request.v1", "request_id": request_id,
            "reservation": reservation, "snapshot_root": snapshot_root,
            "caller_context": context if context is not None else {"run": "r1"}}
    return launch.decode_launch_request("prepare", json.dumps(body).encode())


def prepare(service, reservation, request_id="prep-1", snapshot_root="/src/repo", context=None):
    response = service.prepare(prepare_request(reservation, request_id, snapshot_root, context))
    return response, launch.encode_launch_response(response), launch.launch_exit_class(response)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


HEX = "a" * 64


def records(env, name, client="agent-toolkit"):
    directory = env.launch_root(client) / name
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def hold_lock(env, reservation, client="agent-toolkit"):
    path = env.state / client / "reservations" / f"{reservation['reservation_id']}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def journal_launch(lifecycle, reservation, request_id, paths, *, claim=True):
    reservation_id = reservation["reservation_id"]
    lifecycle.write_launch_record(request_id, {
        "reservation_id": reservation_id, "request_id": request_id, "run_id": paths.run_id,
        "scratch_path": paths.scratch_path, "tree_path": paths.tree_path,
        "caller_context": {}, "worker_invocations": 1, "envelope_digest": HEX})
    if claim:
        assert lifecycle.claim_exec(reservation_id, request_id, paths.run_id, timeout_s=1) is None


def refused_terminal(reservation, request_id):
    """A schema-valid LaneExec terminal (the shape is SL-8's; any terminal settles here)."""
    return launch.LaunchResponse(request_id, reservation["reservation_id"], None, "refused",
                                 "sandbox_launch_pre_exec_refused", None, None, None, None, 0,
                                 None, None, None, None, None, {})


def unrelated_run(env, client="agent-toolkit"):
    run = env.launch_root(client) / "runs" / ("run-" + "7" * 32)
    run.mkdir(mode=0o700)
    (run / "kept").write_text("x")
    return run


@pytest.fixture
def prepared(env):
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    response, raw, _ = prepare(service, reservation)
    run_dir = env.launch_root() / "runs" / response.paths.run_id
    (run_dir / "scratch").mkdir(mode=0o700)
    return lifecycle, service, reservation, response, raw, run_dir


# -- C11 cleanup ----------------------------------------------------------------------------

def test_release_of_a_prepared_never_launched_reservation_removes_only_its_run(env, prepared):
    _lifecycle, service, reservation, _response, raw, run_dir = prepared
    other = unrelated_run(env)
    response, code = env.release(reservation)
    assert (code, response.state) == (0, "released")
    assert records(env, "prepare") == [] and not run_dir.exists()
    assert other.is_dir() and (other / "kept").read_text() == "x"
    # A fresh request finds no reservation; a replay returns its retained settled bytes and
    # recreates nothing.
    fresh, _raw, code = prepare(service, reservation, "prep-2")
    assert (code, fresh.code) == (10, "sandbox_launch_reservation_unknown")
    assert prepare(service, reservation, "prep-1")[1] == raw
    assert not run_dir.exists() and records(env, "prepare") == []


def test_reap_of_a_prepared_never_launched_reservation_removes_only_its_run(env, prepared):
    _lifecycle, service, reservation, _response, raw, run_dir = prepared
    other = unrelated_run(env)
    env.clock.now += 600
    response, code = env.reap()
    assert (code, response.state, response.inventory.destroyed) == (0, "complete", 1)
    assert records(env, "prepare") == [] and not run_dir.exists() and other.is_dir()
    fresh, _raw, code = prepare(service, reservation, "prep-2")
    assert (code, fresh.code) == (10, "sandbox_launch_reservation_unknown")
    assert prepare(service, reservation, "prep-1")[1] == raw
    assert not run_dir.exists()


def test_a_cleanup_entry_left_by_an_uncertain_prepare_is_consumed_by_release(env, monkeypatch):
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    fresh = iter(f"{n:032x}" for n in range(0xd00, 0xe00))
    lifecycle.new_id = lambda: next(fresh)
    planned = f"run-{0xd00:032x}"
    runs = env.launch_root() / "runs"
    runs.mkdir(parents=True, mode=0o700, exist_ok=True)
    (runs / planned).write_text("in the way")
    with pytest.raises(sp.LifecycleError):
        prepare(service, reservation)
    (runs / planned).unlink()
    (runs / planned).mkdir(mode=0o700)  # what a partial allocation leaves
    record = json.loads((env.launch_root() / "prepare-requests" / "prep-1.json").read_text())
    env.clock.now = record["started_at"] + (record["deadline_ms"] + sp.REPLAY_SETTLE_ALLOWANCE_MS) / 1000
    assert prepare(service, reservation)[2] == 20
    assert records(env, "cleanup") == [f"{planned}.json"] and records(env, "prepare") == []
    other = unrelated_run(env)
    assert env.release(reservation)[1] == 0
    assert records(env, "cleanup") == [] and not (runs / planned).exists() and other.is_dir()


def test_reap_sweeps_cleanup_entries_of_reservations_no_longer_held(env):
    lifecycle = env.lifecycle()
    reservation = env.reserve()
    run_id = "run-" + "5" * 32
    lifecycle._launch_write("cleanup", run_id, {"reservation_id": reservation["reservation_id"],
                                                "run_id": run_id})
    (lifecycle.launch_run_dir(run_id)).mkdir(mode=0o700)
    other = unrelated_run(env)
    # Released by PLACECLI first: the entry outlives its reservation until reap.
    os.unlink(env.state / "agent-toolkit" / "reservations" / f"{reservation['reservation_id']}.json")
    env.reap()
    assert records(env, "cleanup") == [] and not lifecycle.launch_run_dir(run_id).exists()
    assert other.is_dir()


# -- C11 races at the reservation lock ------------------------------------------------------

def _waiting(thread):
    time.sleep(0.15)
    assert thread.is_alive()  # it is waiting on the held reservation lock


def test_prepare_then_release_leaves_a_record_that_release_removes(env):
    service = env.service()
    reservation = env.reserve()
    out = {}
    fd = hold_lock(env, reservation)
    thread = threading.Thread(target=lambda: out.setdefault("p", prepare(service, reservation)))
    thread.start()
    _waiting(thread)
    os.close(fd)
    thread.join(5)
    assert out["p"][2] == 0 and len(records(env, "prepare")) == 1
    assert env.release(reservation)[1] == 0
    assert records(env, "prepare") == [] and records(env, "runs") == []


def test_release_then_prepare_refuses_reservation_unknown_with_no_record(env):
    service = env.service()
    reservation = env.reserve()
    out = {}
    fd = hold_lock(env, reservation)
    thread = threading.Thread(target=lambda: out.setdefault("r", env.release(reservation)))
    thread.start()
    _waiting(thread)
    os.close(fd)
    thread.join(5)
    assert out["r"][1] == 0
    response, _raw, code = prepare(service, reservation)
    assert (code, response.code) == (10, "sandbox_launch_reservation_unknown")
    assert records(env, "prepare") == [] and records(env, "runs") == []


def test_prepare_and_release_released_together_leave_one_consistent_outcome(env):
    service = env.service()
    reservation = env.reserve()
    out = {}
    fd = hold_lock(env, reservation)
    threads = [threading.Thread(target=lambda: out.setdefault("p", prepare(service, reservation))),
               threading.Thread(target=lambda: out.setdefault("r", env.release(reservation)))]
    for thread in threads:
        thread.start()
    time.sleep(0.15)
    os.close(fd)
    for thread in threads:
        thread.join(5)
    assert out["r"][1] == 0 and records(env, "prepare") == [] and records(env, "runs") == []
    assert out["p"][0].state in ("prepared", "refused")
    if out["p"][0].state == "refused":
        assert out["p"][0].code == "sandbox_launch_reservation_unknown"


@pytest.mark.parametrize("order", ["prepare_first", "reap_first"])
def test_prepare_against_reap_in_both_orders(env, order):
    service = env.service()
    reservation = env.reserve()
    if order == "prepare_first":
        assert prepare(service, reservation)[2] == 0
        env.clock.now += 600
        env.reap()
    else:
        env.clock.now += 600
        env.reap()
        response, _raw, code = prepare(service, reservation)
        assert (code, response.code) == (10, "sandbox_launch_reservation_unknown")
    assert records(env, "prepare") == [] and records(env, "runs") == []


# -- C7 at the hook: release with a LaneExec claim ------------------------------------------

def test_release_cancels_a_live_attempt_through_the_owner_then_proceeds_on_its_terminal(env, prepared):
    lifecycle, _service, reservation, response, _raw, run_dir = prepared
    journal_launch(lifecycle, reservation, "launch-1", response.paths)
    env.cancel_outcome = "cancelled"
    env.on_cancel = lambda claim: lifecycle.write_launch_terminal(
        "launch-1", refused_terminal(reservation, "launch-1"))
    released, code = env.release(reservation)
    assert (code, released.state) == (0, "released")
    assert env.cancels == [("launch-1", response.paths.run_id)]
    assert not run_dir.exists() and records(env, "prepare") == []
    # The launch and claim records stay for status; reap never replaces a response.
    assert lifecycle.launch_terminal("launch-1") == refused_terminal(reservation, "launch-1")


@pytest.mark.parametrize("outcome,journaled", [("cancel_pending", []),
                                               ("owner_unverified", ["owner_unverified"]),
                                               (RuntimeError("boom"), ["unmapped"])])
def test_release_of_an_attempt_not_terminal_by_the_deadline_is_cleanup_pending(
        env, prepared, outcome, journaled):
    lifecycle, _service, reservation, response, _raw, run_dir = prepared
    journal_launch(lifecycle, reservation, "launch-1", response.paths)
    env.cancel_outcome = outcome
    released, code = env.release(reservation, deadline_ms=300)
    assert (code, released.state, released.code) == (
        20, "cleanup_pending", "sandbox_placement_release_unconfirmed")
    assert released.flags.exec_claimed is True and released.flags.cleanup_pending is True
    # The lease is held: nothing is torn down.
    assert run_dir.is_dir() and len(records(env, "prepare")) == 1
    assert len(list((env.state / "local-slots").glob("*.json"))) == 1
    assert lifecycle.launch_local_cancels("launch-1") == journaled
    assert lifecycle.launch_claim_record(reservation["reservation_id"])["claimed"] is True


def test_release_after_the_terminal_destroys_the_run_without_a_cancel(env, prepared):
    lifecycle, _service, reservation, response, _raw, run_dir = prepared
    journal_launch(lifecycle, reservation, "launch-1", response.paths)
    lifecycle.write_launch_terminal("launch-1", refused_terminal(reservation, "launch-1"))
    released, code = env.release(reservation)
    assert (code, released.state) == (0, "released") and env.cancels == []
    assert not run_dir.exists()


def test_release_after_a_claim_rollback_needs_no_cancel(env, prepared):
    lifecycle, _service, reservation, response, _raw, run_dir = prepared
    journal_launch(lifecycle, reservation, "launch-1", response.paths)
    assert lifecycle.rollback_claim(reservation["reservation_id"], "launch-1", timeout_s=1)
    assert env.release(reservation)[1] == 0 and env.cancels == [] and not run_dir.exists()


# -- C7 at the hook: reap settles only a verifiably gone owner -----------------------------

@pytest.mark.parametrize("owner", ["live", "unverified"])
def test_reap_keeps_a_claimed_attempt_whose_owner_is_not_verifiably_gone(env, prepared, owner):
    lifecycle, _service, reservation, response, _raw, run_dir = prepared
    journal_launch(lifecycle, reservation, "launch-1", response.paths)
    env.owner = owner
    env.clock.now += 600
    reaped, code = env.reap()
    assert (code, reaped.state, reaped.inventory.pending) == (20, "cleanup_pending", 1)
    assert env.cancels == [] and run_dir.is_dir()
    assert lifecycle.launch_claim_record(reservation["reservation_id"]).get("reaped_at") is None


def test_reap_cancels_and_settles_a_gone_owner_and_never_writes_a_response(env, prepared):
    lifecycle, service, reservation, response, _raw, run_dir = prepared
    journal_launch(lifecycle, reservation, "launch-1", response.paths)
    env.owner = "gone"
    env.cancel_outcome = "owner_not_live"
    env.clock.now += 600
    reaped, code = env.reap()
    assert (code, reaped.state, reaped.inventory.destroyed) == (0, "complete", 1)
    assert env.cancels == [("launch-1", response.paths.run_id)]
    claim = lifecycle.launch_claim_record(reservation["reservation_id"])
    assert claim["claimed"] is True and claim["reaped_at"] == env.clock.now
    assert not run_dir.exists() and lifecycle.launch_terminal("launch-1") is None
    assert lifecycle.launch_local_cancels("launch-1") == ["owner_not_live"]
    # A later launch for the reservation still finds the claim; status cannot settle it.
    body = {"schema": "placement.launch.status.request.v1", "request_id": "st-1",
            "reservation_id": reservation["reservation_id"], "launch_request_id": "launch-1",
            "caller_context": {}}
    assert service.status(launch.decode_launch_request("status", json.dumps(body).encode())
                          ).state == "uncertain"


def test_the_landed_owner_check_reads_the_claiming_process(env, prepared):
    lifecycle, _service, reservation, response, _raw, _run_dir = prepared
    landed = env.lifecycle(launch_owner=None)
    journal_launch(lifecycle, reservation, "launch-1", response.paths)
    claim = landed.launch_claim_record(reservation["reservation_id"])
    assert claim["owner"]["pid"] == os.getpid()
    assert landed.launch_owner(claim) == "live"
    assert landed.launch_owner({**claim, "owner": {"pid": claim["owner"]["pid"], "start": "other"}}) == "gone"
    assert landed.launch_owner({**claim, "owner": None}) == "unverified"


# -- caller-scoped reap -----------------------------------------------------------------------

def test_reap_examines_only_the_selected_inventory(env):
    toolkit_service, harness_service = env.service(), env.service("agent-harness")
    toolkit, harness = env.reserve(), env.reserve("agent-harness")
    prepare(toolkit_service, toolkit)
    prepare(harness_service, harness)
    env.clock.now += 600
    env.reap("agent-toolkit")
    assert records(env, "prepare") == []
    assert records(env, "prepare", "agent-harness") == [f"{harness['reservation_id']}.json"]
    assert len(records(env, "runs", "agent-harness")) == 1


# -- an interrupted publication keeps the unused run owned ------------------------------------

def _interrupt_publication(monkeypatch, lifecycle):
    real = lifecycle._launch_write

    def write(name, key, value):
        if name == "prepare":
            raise OSError("injected")
        return real(name, key, value)

    monkeypatch.setattr(lifecycle, "_launch_write", write)
    return real


@pytest.mark.parametrize("end", ["release", "reap"])
def test_an_interrupted_publication_hands_its_run_to_cleanup_when_another_wins(env, monkeypatch, end):
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    real = _interrupt_publication(monkeypatch, lifecycle)
    with pytest.raises(sp.LifecycleError):
        prepare(service, reservation, "prep-a")
    monkeypatch.setattr(lifecycle, "_launch_write", real)
    [loser] = records(env, "runs")
    winner, _raw, code = prepare(service, reservation, "prep-b")
    assert code == 0 and winner.paths.run_id != loser
    replay, _raw, code = prepare(service, reservation, "prep-a")
    assert code == 0 and replay.paths == winner.paths
    assert records(env, "cleanup") == [f"{loser}.json"]
    assert sorted(records(env, "runs")) == sorted([loser, winner.paths.run_id])
    if end == "release":
        assert env.release(reservation)[1] == 0
    else:
        env.clock.now += 600
        env.reap()
    assert records(env, "runs") == [] and records(env, "cleanup") == []


# -- the production owner classifier needs affirmative evidence -----------------------------

def test_an_unreadable_identity_of_a_live_owner_is_unverified_and_reap_keeps_everything(
        env, prepared, monkeypatch):
    _lifecycle, _service, reservation, response, _raw, run_dir = prepared
    landed = env.lifecycle(launch_owner=None)
    journal_launch(landed, reservation, "launch-1", response.paths)
    claim = landed.launch_claim_record(reservation["reservation_id"])
    assert claim["owner"]["pid"] == os.getpid()
    monkeypatch.setattr(run_status, "process_start_identity", lambda pid: None)
    assert landed.launch_owner(claim) == "unverified"
    env.clock.now += 600
    body = {"schema": "placement.reap.request.v1", "request_id": "reap-x", "scope": "caller_inventory",
            "deadline_ms": 2000, "max_items": 100, "caller_context": {}}
    reaped = landed.reap(contract.decode_request("reap", json.dumps(body).encode()),
                         cancelled=threading.Event())
    assert (reaped.state, reaped.inventory.pending) == ("cleanup_pending", 1)
    assert env.cancels == [] and run_dir.is_dir()
    assert len(list((env.state / "local-slots").glob("*.json"))) == 1


def test_a_pid_that_no_longer_exists_is_gone(env, prepared, monkeypatch):
    lifecycle = env.lifecycle(launch_owner=None)
    monkeypatch.setattr(run_status, "process_start_identity", lambda pid: None)
    pid_max = int(Path("/proc/sys/kernel/pid_max").read_text())
    absent = next(pid for pid in range(pid_max - 1, 1, -1) if not Path(f"/proc/{pid}").exists())
    claim = {"owner": {"pid": absent, "start": "linux-proc:x:1"}}
    assert lifecycle.launch_owner(claim) == "gone"


# -- retained returns outlive release -------------------------------------------------------

def test_a_retained_return_outlives_release_and_is_pruned_after_the_tombstone(env, prepared):
    lifecycle, service, reservation, response, _raw, run_dir = prepared
    rid, paths = reservation["reservation_id"], response.paths
    journal_launch(lifecycle, reservation, "launch-1", paths)
    # The out directory is the run's; the return directory comes from the lifecycle on this
    # fresh reservation, with no directory made by the test.
    out = run_dir / "out"
    out.mkdir(mode=0o700)
    data = b'{"ok":true}'
    (out / "result.json").write_bytes(data)
    os.chmod(out / "result.json", 0o600)
    directory = lifecycle.launch_return_dir(rid, paths.run_id)
    assert not directory.exists()
    limits = openshell_artifacts.Limits(source_bytes=1 << 20, file_bytes=1 << 20, files=100,
                                        patch_bytes=1 << 20, output_bytes=1 << 20)
    outcome = collect_return(ReturnAttempt(return_dir=directory, out_dir=out), "result",
                             policy=ReturnPolicy(binary_limits=limits), withhold=None,
                             bound=openshell_artifacts.Bound(time.monotonic() + 30, lambda: False))
    assert (outcome.status, outcome.code) == ("returned", None)
    assert (directory.parent.stat().st_mode & 0o777) == 0o700
    descriptor = outcome.descriptor
    assert Path(descriptor.path).parent == directory
    terminal = launch.LaunchResponse(
        "launch-1", rid, paths.run_id, "finished", None, None, None, None,
        launch.Termination("completed", None, "worker"), 1, HEX, paths.scratch_path,
        paths.tree_path, descriptor, _evidence(), {})
    lifecycle.write_launch_terminal("launch-1", terminal)
    assert env.release(reservation)[1] == 0
    assert not run_dir.exists()
    assert Path(descriptor.path).read_bytes() == data
    body = {"schema": "placement.launch.status.request.v1", "request_id": "st-1",
            "reservation_id": rid, "launch_request_id": "launch-1", "caller_context": {}}
    status = service.status(launch.decode_launch_request("status", json.dumps(body).encode()))
    assert status.launch.return_ == descriptor and Path(status.launch.return_.path).read_bytes() == data
    env.reap()
    assert Path(descriptor.path).exists()  # the tombstone still answers
    env.clock.now += sp.TOMBSTONE_RETENTION_S
    env.reap()
    assert not directory.parent.exists()


def test_no_return_directory_is_provisioned_for_a_reservation_no_longer_held(env, prepared):
    lifecycle, _service, reservation, response, _raw, _run_dir = prepared
    assert env.release(reservation)[1] == 0
    with pytest.raises(sp.LifecycleError):
        lifecycle.launch_return_dir(reservation["reservation_id"], response.paths.run_id)
    assert not (env.launch_root() / "returns" / reservation["reservation_id"]).exists()


# -- a claim needs an owner reap can verify ---------------------------------------------------

def test_a_claim_is_refused_and_never_written_without_a_readable_owner_identity(env, prepared,
                                                                                monkeypatch):
    lifecycle, _service, reservation, response, _raw, _run_dir = prepared
    rid, run_id = reservation["reservation_id"], response.paths.run_id
    assert lifecycle.claim_exec(rid, "launch-1", run_id, timeout_s=1,
                                owner={"pid": os.getpid(), "start": None}) == (
        "sandbox_placement_capability_unmet")
    monkeypatch.setattr(run_status, "process_start_identity", lambda pid: None)
    assert lifecycle.claim_exec(rid, "launch-1", run_id, timeout_s=1) == (
        "sandbox_placement_capability_unmet")
    assert lifecycle.launch_claim_record(rid) is None
    monkeypatch.undo()
    assert lifecycle.claim_exec(rid, "launch-1", run_id, timeout_s=1) is None


def test_a_legacy_claim_with_no_start_identity_is_gone_once_its_pid_is_gone(env):
    lifecycle = env.lifecycle(launch_owner=None)
    pid_max = int(Path("/proc/sys/kernel/pid_max").read_text())
    absent = next(pid for pid in range(pid_max - 1, 1, -1) if not Path(f"/proc/{pid}").exists())
    assert lifecycle.launch_owner({"owner": {"pid": absent, "start": None}}) == "gone"
    # A live pid with no recorded identity stays indeterminate.
    assert lifecycle.launch_owner({"owner": {"pid": os.getpid(), "start": None}}) == "unverified"


def test_a_zombie_owner_is_gone(env):
    lifecycle = env.lifecycle(launch_owner=None)
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(0.2)"])
    try:
        start = run_status.process_start_identity(child.pid)
        assert start is not None
        deadline = time.monotonic() + 10
        while Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert run_status.process_start_identity(child.pid) is None
        assert lifecycle.launch_owner({"owner": {"pid": child.pid, "start": start}}) == "gone"
    finally:
        child.wait(5)


def _evidence():
    from phase_loop_runtime.launch_return import build_launch_evidence

    return build_launch_evidence(
        snapshot=None, launch_digest=HEX, template_sha256=HEX, image_digest=DIGEST,
        policy_digest=DIGEST, egress_sha256=DIGEST, transport_id="local", caps_sha256=HEX,
        bridge_attached=False, stdout_sha256=None, stderr_sha256=None, exit_status=0,
        duration_ms=5, renewals=0)
