"""v13 LANEEXEC SL-3: release, reap and cancel at the ``PlacementLifecycle`` hook.

C11 cleanup and races, and the C7 state transitions on journaled records: release of a
prepared, never-launched reservation; release cancelling a live attempt through the
verified owner and then ``cleanup_pending``; reap settling only a verifiably gone owner;
caller-scoped reap with the other inventory invisible. Every case enters through
:func:`build_launch_service` and the production ``release``/``reap`` of a real lifecycle.
The local end-to-end supervisor and capped-parent evidence belong to SL-8.
"""

from __future__ import annotations

from contextlib import contextmanager
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


GEN = "f" * 32


def _generation_claim(prepared):
    life, _, reservation, response, _, _ = prepared
    key = (reservation["reservation_id"], "launch-1", GEN)
    with life.launch_lock(key[0], timeout_s=1) as lock:
        assert lock.claim(key[1], response.paths.run_id, generation=GEN) is None
    return life, key


def test_generation_start_fence_and_rollback_cas(prepared):
    life, key = _generation_claim(prepared)
    deadline = time.monotonic() + 2
    assert not life.fence_launch(key[0], key[1], "0" * 32, cause="release", deadline=deadline)
    assert not life.renew_launch(key[0], key[1], "0" * 32, deadline=deadline)
    with life.launch_lock(key[0], timeout_s=1):
        with pytest.raises(sp.LifecycleError, match="placement_lock_order"):
            with life.launch_operation_lock(key[0], GEN, timeout_s=.1):
                pytest.fail("operation lock acquired under the journal")
    with life.launch_operation_lock(key[0], GEN, timeout_s=1) as held:
        assert held and life.mark_start_intent(*key, deadline=deadline)
        assert not life.mark_start_intent(*key, deadline=deadline)
    with life.launch_lock(key[0], timeout_s=1) as lock:
        assert not lock.rollback(key[1])
        assert not lock.record_rollback_intent(key[1], GEN, cause="snapshot_expired")
    assert life.fence_launch(*key, cause="release", deadline=deadline)
    assert life.read_cleanup_debt(*key).cause == "release"
    with life.launch_operation_lock(key[0], GEN, timeout_s=.2) as held:
        assert held and not life.mark_start_intent(*key, deadline=deadline)
    assert not life.renew_launch(*key, deadline=deadline)
    with life.launch_lock(key[0], timeout_s=1) as lock:
        code, active = lock.window(None)
        assert code is not None
        assert life._flags(active).fenced
        # An unreadable disposition is still a closed window even with the claim intact.
        (life.launch_root / "dispositions" / (GEN + ".json")).unlink()
        assert lock.window(None)[0] is not None and life._flags(active).fenced
    with pytest.raises(sp.LifecycleError):
        life.read_cleanup_debt(*key)


def test_generation_rollback_records_completion(prepared):
    life, key = _generation_claim(prepared)
    with life.launch_lock(key[0], timeout_s=1) as lock:
        assert not lock.rollback(key[1], generation=GEN)
        assert lock.record_rollback_intent(key[1], GEN, cause="snapshot_expired")
        assert lock.rollback(key[1], generation=GEN)
    claim = life.launch_claim_record(key[0])
    assert claim["completed_rollback"] == dict(request_id=key[1], generation=GEN, cause="snapshot_expired")
    assert not claim["claimed"] and claim["rolled_back"] == [key[1]]


def test_generation_reap_dead_before_expiry_keeps_unresolved_debt(env, prepared):
    life, key = _generation_claim(prepared)
    env.owner = "gone"
    result, _ = env.reap()
    assert result.inventory.pending == 1 and prepared[-1].exists()
    assert life.read_cleanup_debt(*key).cause == "owner_gone"


@pytest.mark.parametrize("kind", ["stage", "scratch"])
def test_generation_allocation_requires_observed_inode(env, prepared, kind):
    life, _, reservation, response, _, run = prepared
    key = (reservation["reservation_id"], "launch-1", GEN)
    path = (run if kind == "scratch" else life.launch_root / "stages") / GEN
    args = dict(kind=kind, run_id=response.paths.run_id, owner=sp._own_identity(),
                basename=GEN, deadline=time.monotonic()+2)
    with life.launch_lock(key[0], timeout_s=1):
        assert life.record_allocation(*key, **args, file_id=None)
        path.mkdir(mode=0o700)
        ident = path.stat()
        assert life.record_allocation(*key, **args, file_id=(ident.st_dev, ident.st_ino))
        path.rename(path.with_suffix(".saved"))
        path.mkdir(mode=0o700)
        assert not life.collect_allocation(*key, kind=kind, deadline=args["deadline"])
        path.rmdir()
        path.with_suffix(".saved").rename(path)
        assert life.collect_allocation(*key, kind=kind, deadline=args["deadline"])
        assert not path.exists()


def test_generation_implicit_prepare_replay(env):
    from types import SimpleNamespace
    life = env.lifecycle("agent-harness")
    reservation = env.reserve("agent-harness")
    rid = reservation["reservation_id"]
    request = SimpleNamespace(request_id="launch-1", reservation=contract.Reservation.from_json(reservation),
                              reservation_json=reservation, workload="implementation", paths=None,
                              snapshot=launch.Snapshot("/src", "copy", (), (), "."))
    life.write_launch_record(request.request_id, dict(reservation_id=rid, generation=GEN))
    env.caps_error = True
    with life.launch_request_lock(request.request_id, timeout_s=1):
        with pytest.raises(sp.LifecycleError, match="placement_lock_order"):
            with life.launch_lock(rid, timeout_s=.1):
                pytest.fail("journal acquired under the request lock")
    with life.launch_lock(rid, timeout_s=1) as lock:
        paths = lock.ensure_prepare(request)
        assert isinstance(paths, launch.PreparedPaths)
        assert lock.ensure_prepare(request) == paths
        request.workload = "pi-runner"
        assert lock.ensure_prepare(request) == "sandbox_launch_input_mismatch"
    assert life.launch_prepare_record(rid)["request_id"] == request.request_id
    assert not list((life.launch_root / "prepare-requests").glob("*.json"))


def test_generation_late_lane_entry(env, monkeypatch):
    from types import SimpleNamespace
    import phase_loop_runtime
    units = launch_service.LaneUnits(("target",), (), HEX, HEX)
    context = launch_service.LaneContext(HEX, units, ("src",), (HEX,))
    with pytest.raises(ValueError):
        launch_service.LaneContext("bad", units, ("src",), ())
    runner = lambda handoff: None
    service = env.service(supervisor_runner=runner)
    observed = {}
    def attempt(service, request, **kwargs):
        observed.update(kwargs)
        return request
    monkeypatch.setattr(phase_loop_runtime, "launch_exec", SimpleNamespace(launch_attempt=attempt),
                        raising=False)
    event = threading.Event()
    assert service.launch_lane("req", lane_context=context, cancelled=event) == "req"
    assert observed == dict(origin="lane", lane_context=context, cancelled=event, pre_exec=None, withhold=None)
    assert service.supervisor_runner is runner
    # The factory forwards its keyword directly. The service constructor stores
    # that same parameter, and no other service method assigns the runner.
    import ast
    import inspect
    factory = ast.parse(inspect.getsource(launch_service.build_launch_service))
    service_class = ast.parse(inspect.getsource(launch_service.LaunchService))
    args = factory.body[0].args
    defaults = dict(zip((arg.arg for arg in args.kwonlyargs), args.kw_defaults))
    assert ast.unparse(defaults["supervisor_runner"]) == "None"
    forwarded = [node.value for node in ast.walk(factory)
                 if isinstance(node, ast.keyword) and node.arg == "supervisor_runner"]
    stored = [node.value for node in ast.walk(service_class) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Attribute) and t.attr == "supervisor_runner" for t in node.targets)]
    assert [ast.unparse(value) for value in forwarded + stored] == ["supervisor_runner"] * 2
    for tree in (factory, service_class):
        assert not any(isinstance(n, ast.Name) and n.id == "supervisor_runner" and
                       isinstance(n.ctx, ast.Store) for n in ast.walk(tree))
    default = env.service()
    request = SimpleNamespace(supervisor_runner=runner, caller_context={"supervisor_runner": "fixture"})
    assert default.launch_lane(request, lane_context=context, cancelled=event) is request
    assert default.supervisor_runner is None


@pytest.mark.parametrize("fault", ["none", "duplicate", "oversize", "surplus", "utf8", "stale_start", "wrong_pid", "enametoolong"])
def test_generation_cancel_long_path(env, fault, monkeypatch):
    import socket
    import struct
    env.state /= "long-root-" + "x" * 108
    life = env.lifecycle()
    reservation = env.reserve()
    response, _, _ = prepare(env.service(lifecycle=life), reservation)
    key = (reservation["reservation_id"], "launch-1", GEN)
    with life.launch_lock(key[0], timeout_s=1) as journal:
        assert journal.claim(key[1], response.paths.run_id, generation=GEN) is None
    ctl = life.launch_root / "ctl"
    assert len(os.fsencode(life.launch_root)) > 107
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    for component in ctl.parts[1:]:
        child = os.open(component, flags, dir_fd=fd)
        os.close(fd)
        fd = child
    received = []
    def serve(listener):
        conn, _ = listener.accept()
        with conn, conn.makefile("rb") as reader:
            peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, _ = struct.unpack("3i", peer)
            assert uid == os.geteuid()
            header = reader.read(4)
            if fault in ("stale_start", "wrong_pid") and not header:
                return
            length, = struct.unpack(">I", header)
            request = json.loads(reader.read(length))
            assert request["sender_pid"] == pid
            assert request["sender_start"] == run_status.process_start_identity(pid)
            received.append(request)
            reply = json.dumps(dict(version=1, generation=GEN, outcome="cancel_pending")).encode()
            if fault == "duplicate":
                reply = reply.replace(b'"version": 1', b'"version": 1, "version": 1')
            if fault == "utf8":
                reply = b"\xff"
            frame = struct.pack(">I", 4097 if fault == "oversize" else len(reply)) + reply
            conn.sendall(frame * (2 if fault == "surplus" else 1))
    try:
        with socket.socket(socket.AF_UNIX) as listener:
            listener.settimeout(2)
            address = f"/proc/self/fd/{fd}/{GEN}.sock"
            listener.bind(address)
            os.chmod(address, 0o600)
            listener.listen()
            if fault == "enametoolong":
                import errno
                def too_long(*args):
                    raise OSError(errno.ENAMETOOLONG, "injected connect failure")
                monkeypatch.setattr(socket.socket, "connect", too_long)
                with pytest.raises(sp.LifecycleError, match="placement_control_socket_invariant"):
                    life.cancel_launch_owner(*key, deadline=time.monotonic()+2)
                return
            if fault == "wrong_pid":
                claim = life.launch_claim_record(key[0])
                claim["owner"]["pid"] += 1
                life._launch_write("claims", key[0], claim)
            thread = threading.Thread(target=serve, args=(listener,))
            thread.start()
            if fault == "stale_start":
                monkeypatch.setattr(run_status, "process_start_identity", lambda pid: "different")
            assert life.cancel_launch_owner(*key, deadline=time.monotonic()+2) == (
                "cancel_pending" if fault == "none" else "owner_unverified")
            thread.join(2)
    finally:
        os.close(fd)
    if fault in ("stale_start", "wrong_pid"):
        assert not received
        return
    assert received == [dict(version=1, op="cancel", reservation_id=key[0], request_id=key[1],
                             generation=GEN, sender_pid=os.getpid(), sender_start=sp._own_identity()["start"])]


@pytest.mark.parametrize("starts_during_exchange", [False, True])
def test_generation_cancel_keeps_prestart_request_on_supervisor_path(
        env, prepared, monkeypatch, starts_during_exchange):
    life, key = _generation_claim(prepared)
    deadline = time.monotonic() + 2

    def supervisor_cancel(*args):
        if starts_during_exchange:
            with life.launch_operation_lock(key[0], key[2], timeout_s=1) as held:
                assert held and life.mark_start_intent(*key, deadline=deadline)
        return "owner_unverified"

    monkeypatch.setattr(sp, "_supervisor_cancel", supervisor_cancel)
    assert life.cancel_launch_owner(*key, deadline=deadline) == "owner_unverified"
    assert env.cancels == []


def test_generation_cancel_stays_bound_when_prepared_attempt_is_reused(env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    rid, request_id, generation = key
    run_id = prepared[3].paths.run_id
    next_generation = "e" * 32
    launch_lock = life.launch_lock
    supervisor_exchanged = False

    def supervisor_cancel(*args):
        nonlocal supervisor_exchanged
        supervisor_exchanged = True
        return "owner_unverified"

    @contextmanager
    def reuse_after_recheck(reservation_id, *, timeout_s):
        with launch_lock(reservation_id, timeout_s=timeout_s) as lock:
            yield lock
        if supervisor_exchanged:
            # Settle the rollback as soon as cancellation drops the claim journal.
            with launch_lock(rid, timeout_s=1) as lock:
                assert lock.record_rollback_intent(request_id, generation, cause="snapshot_expired")
                assert lock.rollback(request_id, generation=generation)
                assert lock.claim("launch-2", run_id, generation=next_generation) is None

    monkeypatch.setattr(sp, "_supervisor_cancel", supervisor_cancel)
    monkeypatch.setattr(life, "launch_lock", reuse_after_recheck)
    assert life.cancel_launch_owner(*key, deadline=time.monotonic() + 2) == "owner_unverified"
    claim = life.launch_claim_record(rid)
    assert (claim["generation"], claim["run_id"]) == (next_generation, run_id)
    assert env.cancels == []


def test_generation_started_cancel_holds_operation_lock_and_refuses_rollback(env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    rid, request_id, generation = key
    deadline = time.monotonic() + 2
    with life.launch_operation_lock(rid, generation, timeout_s=1) as held:
        assert held and life.mark_start_intent(*key, deadline=deadline)
    with life.launch_lock(rid, timeout_s=1) as lock:
        assert not lock.record_rollback_intent(request_id, generation, cause="snapshot_expired")
        # Even a stale intent in the journal cannot authorize rollback after start.
        claim = life.launch_claim_record(rid)
        claim["rollback_cause"] = "snapshot_expired"
        life._launch_write("claims", rid, claim)
        assert not lock.rollback(request_id, generation=generation)

    held_during_cancel = []
    env.on_cancel = lambda claim: held_during_cancel.append(life._holds_operation(rid, generation))
    env.cancel_outcome = "cancelled"
    monkeypatch.setattr(sp, "_supervisor_cancel", lambda *args: "cancelled")

    assert life.cancel_launch_owner(*key, deadline=deadline) == "cancelled"
    assert env.cancels == [(request_id, prepared[3].paths.run_id)]
    assert held_during_cancel == [True]


def test_generation_renewal_slot_error_requires_explicit_fence(prepared, monkeypatch):
    life, key = _generation_claim(prepared)

    def fail_slot_write(*args):
        raise OSError("injected slot write failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "pwrite", fail_slot_write)
        assert not life.renew_launch(*key, deadline=time.monotonic() + 1)

    assert life.read_cleanup_debt(*key).cause == "renewal_lost"
    assert life._launch_read("dispositions", GEN)["fenced"] is False
    assert life.fence_launch(*key, cause="renewal_lost", deadline=time.monotonic() + 1)
    assert life._launch_read("dispositions", GEN)["fenced"] is True


def test_generation_failed_renewal_keeps_flags_ready(prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    monkeypatch.setattr(life, "_confirm_slot", lambda *args: False)
    assert not life.renew_launch(*key, deadline=time.monotonic() + 1)

    with life.launch_lock(key[0], timeout_s=1) as lock:
        code, active = lock.window(None)
        flags = life._flags(active)
    assert not flags.fenced
    assert flags.ready and flags.exec_claimed and not flags.cleanup_pending
    assert code is None


def test_generation_reap_waits_for_unconfirmed_renewal_boundary(env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    initial = life._launch_read("renewals", f"{GEN}.0")
    heartbeat, ttl = initial["heartbeat_at"], initial["ttl_s"]
    clock = Clock(heartbeat + ttl / 3)
    monkeypatch.setattr(sp, "_monotonic", clock)
    monkeypatch.setattr(life, "_confirm_slot", lambda *args: False)
    assert not life.renew_launch(*key, deadline=clock.now + 1)

    fence_at = heartbeat + ttl * 2 / 3
    for now in (clock.now, fence_at - 1):
        clock.now = now
        result, _ = env.reap()
        assert life._launch_read("dispositions", GEN)["fenced"] is False
        assert result.inventory.examined == 0

    clock.now = fence_at
    result, _ = env.reap()
    assert life._launch_read("dispositions", GEN)["fenced"] is True
    assert result.inventory.pending == 1


def test_generation_mark_start_intent_refuses_after_unconfirmed_renewal_boundary(
        prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    initial = life._launch_read("renewals", f"{GEN}.0")
    heartbeat, ttl = initial["heartbeat_at"], initial["ttl_s"]
    fence_at = heartbeat + ttl * 2 / 3
    clock = Clock(heartbeat + ttl / 3)
    monkeypatch.setattr(sp, "_monotonic", clock)
    monkeypatch.setattr(life, "_confirm_slot", lambda *args: False)
    assert not life.renew_launch(*key, deadline=clock.now + 1)
    assert life._launch_read("dispositions", GEN)["fenced"] is False

    # At or after h + 2T/3, start intent is refused even before fence_launch runs.
    clock.now = fence_at
    with life.launch_operation_lock(key[0], GEN, timeout_s=1) as held:
        assert held and not life.mark_start_intent(*key, deadline=clock.now + 5)
    assert life._launch_read("dispositions", GEN)["start_intent"] is False

    # Before h + 2T/3, an unfenced failed renewal still allows start intent.
    clock.now = fence_at - 1
    with life.launch_operation_lock(key[0], GEN, timeout_s=1) as held:
        assert held and life.mark_start_intent(*key, deadline=clock.now + 5)
    assert life._launch_read("dispositions", GEN)["start_intent"] is True


def test_generation_started_cancel_bounds_worker_wait_to_renewal_fence(
        env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    rid, request_id, generation = key
    initial = life._launch_read("renewals", f"{GEN}.0")
    heartbeat, ttl = initial["heartbeat_at"], initial["ttl_s"]
    fence_at = heartbeat + ttl * 2 / 3
    clock = Clock(heartbeat + 1)
    monkeypatch.setattr(sp, "_monotonic", clock)
    monkeypatch.setattr(sp, "_supervisor_cancel", lambda *args: "cancelled")

    with life.launch_operation_lock(rid, generation, timeout_s=1) as held:
        assert held and life.mark_start_intent(*key, deadline=clock.now + 5)

    waits = []
    def record_cancel(claim, timeout_s):
        waits.append(timeout_s)
        return "cancelled"
    monkeypatch.setattr(life, "launch_cancel", record_cancel)

    # Unfenced and 1.5 s before h + 2T/3: WORKER cancel wait is capped to 1.5 s
    # rather than holding launch_operation_lock for the full CANCEL_WAIT_S (10 s).
    clock.now = fence_at - 1.5
    assert life.cancel_launch_owner(*key, deadline=clock.now + 20) == "cancelled"
    assert waits == [pytest.approx(1.5)]

    # At/after h + 2T/3 while still unfenced: yield immediately so fence_launch is not blocked.
    waits.clear()
    clock.now = fence_at
    assert life.cancel_launch_owner(*key, deadline=clock.now + 20) == "cancel_pending"
    assert waits == []

    # Once fenced, WORKER cancel gets the full CANCEL_WAIT_S budget.
    assert life.fence_launch(*key, cause="renewal_lost", deadline=clock.now + 5)
    assert life.cancel_launch_owner(*key, deadline=clock.now + 20) == "cancelled"
    assert waits == [pytest.approx(sp.CANCEL_WAIT_S)]


def test_generation_unstarted_cancel_past_renewal_fence_returns_supervisor_outcome(
        env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    initial = life._launch_read("renewals", f"{GEN}.0")
    fence_at = initial["heartbeat_at"] + initial["ttl_s"] * 2 / 3
    clock = Clock(fence_at + 1)
    monkeypatch.setattr(sp, "_monotonic", clock)
    monkeypatch.setattr(sp, "_supervisor_cancel", lambda *args: "owner_unverified")

    assert life.cancel_launch_owner(*key, deadline=clock.now + 5) == "owner_unverified"
    assert env.cancels == []


def test_generation_mark_start_intent_checks_caller_deadline_after_renewal_read(
        prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    initial = life._launch_read("renewals", f"{GEN}.0")
    heartbeat, ttl = initial["heartbeat_at"], initial["ttl_s"]
    clock = Clock(heartbeat + 1.0)
    caller_deadline = clock.now + 2.0
    monkeypatch.setattr(sp, "_monotonic", clock)

    orig_confirmed = life._confirmed_renewal
    calls = 0

    def slow_post_write_read(k, disposition):
        nonlocal calls
        calls += 1
        row = orig_confirmed(k, disposition)
        if calls == 2:
            # Post-write renewal read crosses caller_deadline while renewal is still current.
            clock.now = caller_deadline + 0.1
            assert clock.now < heartbeat + ttl * 2 / 3
        return row

    monkeypatch.setattr(life, "_confirmed_renewal", slow_post_write_read)
    with life.launch_operation_lock(key[0], GEN, timeout_s=1) as held:
        assert held and not life.mark_start_intent(*key, deadline=caller_deadline)
    assert calls == 2


@pytest.mark.parametrize("bad_row", [
    {"ttl_s": None},
    {"heartbeat_at": "not-a-number"},
    {"ttl_s": 0},
    {"ttl_s": float("nan")},
    {"heartbeat_at": 10**400},
    {"ttl_s": 1e308},
])
def test_generation_malformed_renewal_fields_fail_closed_without_raw_exception(
        prepared, monkeypatch, bad_row):
    life, key = _generation_claim(prepared)
    rid, request_id, generation = key
    row = life._launch_read("renewals", f"{GEN}.0")
    row.update(bad_row)
    life._launch_write("renewals", f"{GEN}.0", row)
    ident = sp._identity_fields(rid, request_id, generation)
    disp = life._disposition(ident)
    assert life._renewal_fence_at(ident, disp) is None
    assert life._renewal_current(ident, disp) is False
    with life.launch_operation_lock(rid, generation, timeout_s=1) as held:
        assert held and not life.mark_start_intent(*key, deadline=time.monotonic() + 5)

    disp["start_intent"] = True
    life._launch_write("dispositions", generation, disp)
    monkeypatch.setattr(sp, "_supervisor_cancel", lambda *args: "cancelled")
    assert life.cancel_launch_owner(*key, deadline=time.monotonic() + 10) == "cancel_pending"


def test_generation_started_cancel_worker_deadline_bounds_verification_and_polling(
        prepared, monkeypatch, tmp_path):
    """Through the production patch_return.cancel_attempt path, launcher verification and
    post-SIGTERM status polling run outside launch_operation_lock; the lock is acquired
    only to revalidate generation/fence and deliver SIGTERM."""
    from types import SimpleNamespace
    import fcntl
    import hashlib
    import signal
    import struct
    from phase_loop_runtime.convergence.adapters import patch_return

    life, key = _generation_claim(prepared)
    rid, request_id, generation = key
    run_id = prepared[3].paths.run_id
    initial = life._launch_read("renewals", f"{GEN}.0")
    heartbeat, ttl = initial["heartbeat_at"], initial["ttl_s"]
    fence_at = heartbeat + ttl * 2 / 3
    clock = Clock(fence_at - 1.5)
    monkeypatch.setattr(sp, "_monotonic", clock)
    monkeypatch.setattr(patch_return.time, "monotonic", clock)
    monkeypatch.setattr(sp, "_supervisor_cancel", lambda *args: "cancelled")

    with life.launch_operation_lock(rid, generation, timeout_s=1) as held:
        assert held and life.mark_start_intent(*key, deadline=clock.now + 1.0)

    worker_root = tmp_path / "worker-state"
    (worker_root / "launchers").mkdir(parents=True)
    exe = str(Path("/proc/self/exe").resolve())
    cmdline = b"\0".join([b"python", *map(str.encode, patch_return.PRODUCTION_LAUNCHER_COMMANDS[0])]) + b"\0"
    launcher_record = {
        "pid": os.getpid(),
        "process_start_time": "start-1",
        "nonce": "nonce-1",
        "attempt_id": run_id,
        "run_id": run_id,
        "assignment_digest": "a" * 64,
        "exe_realpath": exe,
        "cmdline_sha256": hashlib.sha256(cmdline).hexdigest(),
    }
    rec_path = worker_root / "launchers" / f"{run_id}.json"
    rec_path.write_text(json.dumps(launcher_record), encoding="utf-8")
    rec_path.chmod(0o600)

    monkeypatch.setattr(patch_return, "default_state_root", lambda: worker_root)
    monkeypatch.setattr(patch_return.journal, "open_journal_root", lambda *a, **k: worker_root / "journal")
    monkeypatch.setattr(
        patch_return.journal, "read_attempt",
        lambda *a, **k: SimpleNamespace(
            identity=SimpleNamespace(run_id=run_id, assignment_digest="a" * 64),
            writer=SimpleNamespace(owner_pid=os.getpid(), process_start_time="start-1", writer_instance_id="nonce-1"),
        ),
    )

    lock_during_verify = []
    lock_during_signal = []
    lock_during_poll = []
    signals_sent = []
    sleeps = []
    verification_delay = 1.6
    fence_during_verify = False

    def spy_attempt_status(*a, **k):
        if signals_sent:
            lock_during_poll.append(life._holds_operation(rid, generation))
        else:
            lock_during_verify.append(life._holds_operation(rid, generation))
        return SimpleNamespace(state="running", display="running", termination=None, refusal=None)

    monkeypatch.setattr(patch_return.projection, "attempt_status", spy_attempt_status)

    def slow_start_identity(pid):
        lock_during_verify.append(life._holds_operation(rid, generation))
        clock.now += verification_delay
        if fence_during_verify:
            assert life.fence_launch(*key, cause="renewal_lost", deadline=clock.now + 5)
        return "start-1"

    monkeypatch.setattr(patch_return.journal, "process_start_identity", slow_start_identity)
    monkeypatch.setattr(patch_return.os, "pidfd_open", lambda pid: os.dup(0))
    orig_read_bytes = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes",
        lambda self: cmdline if str(self) == f"/proc/{os.getpid()}/cmdline" else orig_read_bytes(self),
    )
    monkeypatch.setattr(
        patch_return.fcntl, "fcntl",
        lambda fd, op, arg: struct.pack("hhqqi", fcntl.F_WRLCK, os.SEEK_SET, 0, 0, os.getpid())
        if op == fcntl.F_GETLK else fcntl.fcntl(fd, op, arg),
    )

    def spy_signal(pidfd, sig):
        lock_during_signal.append(life._holds_operation(rid, generation))
        signals_sent.append(sig)

    monkeypatch.setattr(patch_return.signal, "pidfd_send_signal", spy_signal)

    def fake_sleep(seconds):
        lock_during_poll.append(life._holds_operation(rid, generation))
        sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(patch_return.time, "sleep", fake_sleep)
    monkeypatch.setattr(life, "launch_cancel", sp._landed_launch_cancel)

    # Case 1: verification crosses fence_at while still unfenced -> lock was not held during
    # verification, signal_guard refuses to signal past fence_at, and zero polling runs.
    assert life.cancel_launch_owner(*key, deadline=clock.now + 20) == "cancel_pending"
    assert lock_during_verify and all(held is False for held in lock_during_verify)
    assert signals_sent == []
    assert sleeps == []

    # Case 2: verification completes before fence_at -> lock held ONLY during SIGTERM,
    # released before status polling begins so polling cannot block fence_launch.
    for lst in (lock_during_verify, lock_during_signal, lock_during_poll, signals_sent, sleeps):
        lst.clear()
    clock.now = fence_at - 1.5
    verification_delay = 1.0
    assert life.cancel_launch_owner(*key, deadline=clock.now + 2.0) == "cancel_pending"
    assert lock_during_verify and all(held is False for held in lock_during_verify)
    assert signals_sent == [signal.SIGTERM]
    assert lock_during_signal == [True]
    assert lock_during_poll and all(held is False for held in lock_during_poll)
    assert sum(sleeps) == pytest.approx(1.0)

    # Case 3: verification exceeds WORKER cancel_deadline (CANCEL_WAIT_S=10 s) while caller
    # deadline and renewal fence are still open -> no SIGTERM delivered past WORKER deadline.
    for lst in (lock_during_verify, lock_during_signal, lock_during_poll, signals_sent, sleeps):
        lst.clear()
    clock.now = heartbeat + 1.0  # plenty of room before fence_at (heartbeat + 2T/3)
    verification_delay = sp.CANCEL_WAIT_S + 1.0
    assert life.cancel_launch_owner(*key, deadline=clock.now + 60.0) == "cancel_pending"
    assert signals_sent == []
    assert sleeps == []

    # Case 4: inside signal_guard under launch_operation_lock, launch_lock timeout is capped
    # at the remaining renewal fence window rather than the outer caller deadline.
    for lst in (lock_during_verify, lock_during_signal, lock_during_poll, signals_sent, sleeps):
        lst.clear()
    clock.now = fence_at - 0.5
    verification_delay = 0.0
    orig_launch_lock = life.launch_lock
    observed_guard_lock_timeouts = []

    def spy_launch_lock(reservation_id, *, timeout_s, **kwargs):
        if life._holds_operation(rid, generation):
            observed_guard_lock_timeouts.append(timeout_s)
        return orig_launch_lock(reservation_id, timeout_s=timeout_s, **kwargs)

    monkeypatch.setattr(life, "launch_lock", spy_launch_lock)
    assert life.cancel_launch_owner(*key, deadline=clock.now + 20.5) == "cancel_pending"
    assert observed_guard_lock_timeouts == [pytest.approx(0.5)]
    monkeypatch.setattr(life, "launch_lock", orig_launch_lock)

    # Case 5: fence_launch runs concurrently during verification (proving the lock is free);
    # once fenced, signal_guard sees fenced=True and delivers SIGTERM even past fence_at.
    for lst in (lock_during_verify, lock_during_signal, lock_during_poll, signals_sent, sleeps):
        lst.clear()
    clock.now = fence_at - 1.5
    verification_delay = 1.6
    fence_during_verify = True
    assert life.cancel_launch_owner(*key, deadline=clock.now + 3.0) == "cancel_pending"
    assert signals_sent == [signal.SIGTERM]
    assert lock_during_signal == [True]
    assert lock_during_poll and all(held is False for held in lock_during_poll)

    # Oversized integer deadline/wait raises ValueError("cancel_wait_invalid"), not OverflowError.
    with pytest.raises(ValueError, match="cancel_wait_invalid"):
        patch_return.cancel_attempt(state_root=worker_root, attempt_id=run_id, deadline=10**400)
    with pytest.raises(ValueError, match="cancel_wait_invalid"):
        patch_return.cancel_attempt(state_root=worker_root, attempt_id=run_id, wait_seconds=10**400)


def test_generation_renewal_retries_within_confirmation_window(env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    initial = life._launch_read("renewals", f"{GEN}.0")
    heartbeat, ttl = initial["heartbeat_at"], initial["ttl_s"]
    clock = Clock(heartbeat + .1 * ttl)
    monkeypatch.setattr(sp, "_monotonic", clock)
    with monkeypatch.context() as patch:
        patch.setattr(life, "_confirm_slot", lambda *args: False)
        assert not life.renew_launch(*key, deadline=clock.now + 1)

    clock.now = heartbeat + .2 * ttl
    env.clock.now += .2 * ttl
    assert life.renew_launch(*key, deadline=clock.now + 1)
    assert life.launch_heartbeat(key[0]) == env.clock.now
    assert life.read_cleanup_debt(*key) is None


def test_generation_renewal_late_writer_cannot_move_confirmed_heartbeat(env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    assert life.renew_launch(*key, deadline=time.monotonic() + 1)
    confirmed = life.launch_heartbeat(key[0])
    env.clock.now += 12
    invoked, resume, finished = threading.Event(), threading.Event(), threading.Event()
    write = life._launch_write
    orphan = []

    def delayed(directory, name, row):
        if directory == "renewals":
            orphan.append((threading.current_thread(), directory, name, row))
            invoked.set()
            assert resume.wait(3)
            try:
                return write(directory, name, row)
            finally:
                finished.set()
        return write(directory, name, row)

    with monkeypatch.context() as patch:
        patch.setattr(life, "_launch_write", delayed)
        try:
            assert not life.renew_launch(*key, deadline=time.monotonic() + .25)
            assert invoked.is_set() and not finished.is_set()
            assert life.read_cleanup_debt(*key).cause == "renewal_lost"
            assert life._launch_read("dispositions", GEN)["fenced"] is False
        finally:
            resume.set()
        assert finished.wait(1)
        writer, *candidate = orphan[0]
        writer.join(1)
        assert not writer.is_alive()
    assert life.launch_heartbeat(key[0]) == confirmed

    env.clock.now += 12
    assert life.renew_launch(*key, deadline=time.monotonic() + 1)
    assert life._launch_read("dispositions", GEN)["confirmed_count"] == 2
    # Replay the orphaned publication after the retry has selected its candidate.
    write(*candidate)
    assert life.launch_heartbeat(key[0]) == env.clock.now


def test_generation_renewal_late_confirmation_restores_previous_heartbeat(env, prepared, monkeypatch):
    life, key = _generation_claim(prepared)
    confirmed = life.launch_heartbeat(key[0])
    env.clock.now += 12
    clock = Clock(time.monotonic())
    deadline = clock.now + 2
    write = life._launch_write

    def late_confirmation(directory, name, row):
        write(directory, name, row)
        if directory == "dispositions" and row["confirmed_count"] == 1:
            clock.now = deadline

    monkeypatch.setattr(sp, "_monotonic", clock)
    monkeypatch.setattr(life, "_launch_write", late_confirmation)
    assert not life.renew_launch(*key, deadline=deadline)
    assert clock.now == deadline
    assert life.launch_heartbeat(key[0]) == confirmed
    assert life.read_cleanup_debt(*key).cause == "renewal_lost"
    assert life._launch_read("dispositions", GEN)["fenced"] is False


def test_generation_release_drops_journal_before_waiting_for_lease(env, prepared):
    life, key = _generation_claim(prepared)
    rid, req, generation = key
    # This simulated zero-start supervisor never provisioned a generation scratch.
    (prepared[-1] / "scratch").rmdir()
    outcome = []
    with life.launch_lease_lock(rid, timeout_s=1) as held:
        assert held
        thread = threading.Thread(target=lambda: outcome.append(env.release(prepared[2], deadline_ms=2000)))
        thread.start()
        end = time.monotonic() + 1
        while life.read_cleanup_debt(*key) is None:
            assert time.monotonic() < end
            time.sleep(.01)
        with life.launch_lock(rid, timeout_s=.25) as journal:
            assert journal.held and not journal.rollback(req, generation=generation)
        assert life.write_cleanup_debt(*key, debt=sp.Debt("release", True, True, "inapplicable", False),
                                       deadline=end)
        life.write_launch_record(req, dict(version=1, reservation_id=rid, request_id=req,
                                           generation=generation))
        life.write_launch_terminal(req, refused_terminal(prepared[2], req))
    thread.join(3)
    assert outcome[0][0].state == "released" and not prepared[-1].exists()
    assert life.read_cleanup_debt(*key).allocations_collected is True


@pytest.mark.parametrize("kind", ["stage", "scratch"])
@pytest.mark.parametrize("crash", ["before_mkdir", "before_identify", "after_remove"])
def test_review_allocation_crash_recovery(prepared, env, monkeypatch, kind, crash):
    life, _, reservation, response, _, run = prepared
    rid, req = reservation["reservation_id"], "interrupted"
    key = (rid, req, GEN)
    args = dict(kind=kind, deadline=time.monotonic() + 2)
    (run / "scratch").rmdir()
    path = (run if kind == "scratch" else life.launch_root / "stages") / GEN
    with life.launch_lock(rid, timeout_s=1):
        intent = dict(**args, run_id=response.paths.run_id, owner=sp._own_identity(), basename=GEN)
        assert life.record_allocation(*key, file_id=None, **intent)
        if crash != "before_mkdir":
            path.mkdir(mode=0o700)
        if crash == "after_remove":
            info = path.stat()
            assert life.record_allocation(*key, file_id=(info.st_dev, info.st_ino), **intent)
            if kind == "scratch":
                path.rename(run / "scratch")
            write = life._launch_write
            def interrupt(name, ident, value):
                if value.get("phase") == "collected":
                    raise OSError("interrupted after unlink")
                write(name, ident, value)
            with monkeypatch.context() as patch:
                patch.setattr(life, "_launch_write", interrupt)
                with pytest.raises(OSError, match="after unlink"):
                    life.collect_allocation(*key, **args)
        env.owner = "gone"
        if crash == "before_identify":
            assert not life.collect_allocation(*key, **args)
            assert path.is_dir()
            path.rmdir()  # independent removal of the unidentified directory
        adopter = dict(pid=1234, start="adopter")
        life.write_launch_record(req, dict(reservation_id=rid, generation=GEN, owner=adopter))
        with monkeypatch.context() as patch:
            patch.setattr(life, "launch_owner", lambda row: "live" if row["owner"] == adopter else "gone")
            assert not life.collect_allocation(*key, **args)
        assert life.collect_allocation(*key, **args)
        assert life._launch_read(kind + "-intents", GEN)["phase"] == "collected"
    assert env.release(reservation)[0].state == "released"


def test_review_slot_failure_allows_retry_and_release(prepared, env, monkeypatch):
    life, _, reservation, response, _, run = prepared
    rid = reservation["reservation_id"]
    (run / "scratch").rmdir()
    with life.launch_lock(rid, timeout_s=1) as lock:
        with monkeypatch.context() as patch:
            patch.setattr(life, "_confirm_slot", lambda *args: False)
            assert lock.claim("first", response.paths.run_id, generation=GEN) == "sandbox_placement_capability_unmet"
        assert life.launch_claim_record(rid) is None
        assert lock.window(None)[0] is None
        gen = "3" * 32
        assert lock.claim("retry", response.paths.run_id, generation=gen) is None
        assert lock.record_rollback_intent("retry", gen, cause="snapshot_expired")
        assert lock.rollback("retry", generation=gen)
    assert env.release(reservation)[0].state == "released"


@pytest.mark.parametrize("corrupt", ["claim", "disposition"])
def test_review_journal_corruption_is_local(env, prepared, corrupt):
    life, key = _generation_claim(prepared)
    other = env.reserve()
    if corrupt == "claim":
        (life.launch_root / "claims" / (key[0] + ".json")).write_text("{")
        env.clock.now += 600
        response, _ = env.reap()
        assert (response.inventory.pending, response.inventory.destroyed) == (1, 1)
    else:
        # A retired generation exercises the reservation index independently
        # of the current-claim disposition check.
        with life.launch_lock(key[0], timeout_s=1) as lock:
            assert lock.record_rollback_intent(key[1], GEN, cause="snapshot_expired")
            assert lock.rollback(key[1], generation=GEN)
        (life.launch_root / "dispositions" / (GEN + ".json")).write_text("{")
        with life.launch_lock(other["reservation_id"], timeout_s=1) as lock:
            assert lock.window(None)[0] is None
        with life.launch_lock(key[0], timeout_s=1) as lock:
            assert lock.window(None)[0] is not None


def test_review_cancel_journal_lock_respects_release_deadline(env, prepared):
    life, key = _generation_claim(prepared)
    result = []
    with sp._FileLock(life.launch_root / "cancels" / (key[1] + ".lock"), blocking=True):
        thread = threading.Thread(target=lambda: result.append(env.release(prepared[2], deadline_ms=250)))
        thread.start()
        thread.join(1.5)
        stuck = thread.is_alive()
    thread.join(2)
    assert not stuck and result[0][0].state == "cleanup_pending"
    assert prepared[-1].is_dir()


def test_review_renewal_checks_caller_lock_order(prepared):
    life, key = _generation_claim(prepared)
    with life.launch_lock(key[0], timeout_s=1):
        with pytest.raises(sp.LifecycleError, match="placement_lock_order"):
            life.renew_launch(*key, deadline=time.monotonic() + .2)


def test_review_cleanup_cause_cas(prepared):
    life, key = _generation_claim(prepared)
    end = time.monotonic() + 2
    assert life.fence_launch(*key, cause="release", deadline=end)
    assert not life.write_cleanup_debt(*key, debt=sp.Debt("owner_gone", True, True, "inapplicable", True),
                                       deadline=end)
    assert life.read_cleanup_debt(*key).cause == "release"


def test_review_heartbeat_reports_wall_time(prepared, env):
    life, key = _generation_claim(prepared)
    assert life.launch_heartbeat(key[0]) == env.clock.now
    env.clock.now += 12
    assert life.renew_launch(*key, deadline=time.monotonic() + 1)
    assert life.launch_heartbeat(key[0]) == env.clock.now
    # Existing records can be projected from the initial claim clock pair.
    initial = life._launch_read("renewals", f"{GEN}.0")
    old = life._launch_read("renewals", f"{GEN}.1")
    del old["wall_heartbeat_at"]
    life._launch_write("renewals", f"{GEN}.1", old)
    elapsed = old["heartbeat_at"] - initial["heartbeat_at"]
    assert life.launch_heartbeat(key[0]) == life.launch_claim_record(key[0])["claimed_at"] + elapsed


@pytest.mark.parametrize("loser", [False, True])
def test_review_implicit_prepare_publication_crash(env, monkeypatch, loser):
    from types import SimpleNamespace
    life = env.lifecycle("agent-harness")
    reservation = env.reserve("agent-harness")
    rid, req = reservation["reservation_id"], "implicit"
    request = SimpleNamespace(request_id=req, reservation=contract.Reservation.from_json(reservation),
                              reservation_json=reservation, workload="implementation", paths=None,
                              snapshot=launch.Snapshot("/src/repo", "copy", (), (), "."))
    life.write_launch_record(req, dict(reservation_id=rid, generation=GEN))
    with life.launch_lock(rid, timeout_s=1) as lock:
        with monkeypatch.context() as patch:
            _interrupt_publication(patch, life)
            with pytest.raises(OSError):
                lock.ensure_prepare(request)
        planned = life._launch_read("implicit", req)["run_id"]
        assert life.launch_run_dir(planned).is_dir()
    if loser:
        winner, _, _ = prepare(env.service("agent-harness", lifecycle=life), reservation)
    with life.launch_lock(rid, timeout_s=1) as lock:
        selected = lock.ensure_prepare(request)
        assert selected.run_id == (winner.paths.run_id if loser else planned)
        assert life._launch_read("implicit", req)["state"] == ("retired" if loser else "published")
    if loser:
        assert life._launch_read("cleanup", planned)["reservation_id"] == rid
    assert env.release(reservation, "agent-harness")[0].state == "released"
    assert not life.launch_run_dir(planned).exists()


@pytest.mark.parametrize("contender", ["start", "rollback"])
def test_review_fence_races_claim_transition(prepared, monkeypatch, contender):
    life, key = _generation_claim(prepared)
    rid, req, generation = key
    if contender == "rollback":
        with life.launch_lock(rid, timeout_s=1) as lock:
            assert lock.record_rollback_intent(req, generation, cause="snapshot_expired")
    entered, proceed, competing = threading.Event(), threading.Event(), threading.Event()
    write = life._launch_write
    def pause(name, ident, row):
        if name == "dispositions" and row.get("fenced"):
            entered.set()
            assert proceed.wait(3)
        write(name, ident, row)
    monkeypatch.setattr(life, "_launch_write", pause)
    end = time.monotonic() + 4
    fenced, results = [], []
    flock = fcntl.flock
    def observed_flock(fd, operation):
        try:
            return flock(fd, operation)
        except BlockingIOError:
            competing.set()
            raise
    monkeypatch.setattr(fcntl, "flock", observed_flock)
    def race():
        if contender == "rollback":
            with life.launch_lock(rid, timeout_s=2) as lock:
                results.append(lock.rollback(req, generation=generation))
        else:
            with life.launch_operation_lock(rid, generation, timeout_s=2) as held:
                assert held
                results.append(life.mark_start_intent(*key, deadline=end))
    fence = threading.Thread(target=lambda: fenced.append(life.fence_launch(*key, cause="release", deadline=end)))
    fence.start()
    assert entered.wait(1)
    rival = threading.Thread(target=race)
    rival.start()
    try:
        assert competing.wait(1)
    finally:
        proceed.set()
    fence.join(3)
    rival.join(3)
    assert fenced == [True] and results == [False]
    assert life.launch_claim_record(rid)["claimed"] is True

def test_review_cancel_journal_write_error_is_pending(prepared, env, monkeypatch):
    life, key = _generation_claim(prepared)
    write = sp.PlacementLifecycle._launch_write
    def interrupted(self, name, ident, row):
        if name == "cancels":
            raise OSError("cancel record unavailable")
        return write(self, name, ident, row)
    monkeypatch.setattr(sp.PlacementLifecycle, "_launch_write", interrupted)
    assert env.release(prepared[2])[0].state == "cleanup_pending"
    assert life.launch_claim_record(key[0])["claimed"] and prepared[-1].is_dir()


def test_renewal_rejects_held_generation_operation_lock(prepared):
    life, key = _generation_claim(prepared)
    with life.launch_operation_lock(key[0], key[2], timeout_s=1) as held:
        assert held
        with pytest.raises(sp.LifecycleError, match="placement_lock_order"):
            life.renew_launch(*key, deadline=time.monotonic() + .2)
    assert life.read_cleanup_debt(*key) is None
