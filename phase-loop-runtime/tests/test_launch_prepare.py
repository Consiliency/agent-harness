"""v13 LANEEXEC SL-3: ``LaunchService.prepare``, ``status`` and ``cancel`` (C11, L-S4).

Every case enters through :func:`build_launch_service` on a real
:class:`~phase_loop_runtime.sandbox_placement.PlacementLifecycle` whose reservations were
made by ``reserve``. The clock, caps loader, worker JOURNAL readers and the verified-owner
cancel are injected at their construction sites; ``launch`` is never entered (it is the
late-bound SL-8 seam).
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from phase_loop_runtime import launch_process_contract as launch
from phase_loop_runtime import launch_service
from phase_loop_runtime import placement_process_contract as contract
from phase_loop_runtime import run_status
from phase_loop_runtime import run_status_projection as projection
from phase_loop_runtime import sandbox_placement as sp
from phase_loop_runtime import seat_resource_caps
from phase_loop_runtime.launch_return import STATUS_UNCERTAIN_CODE, build_launch_evidence

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
END = "sandbox_placement_end_reached"
TIMEOUT = "sandbox_placement_operation_timeout"


def records(env, name, client="agent-toolkit"):
    directory = env.launch_root(client) / name
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def attempt(env, request_id, client="agent-toolkit"):
    return json.loads((env.launch_root(client) / "prepare-requests" / f"{request_id}.json").read_text())


def hold_lock(env, reservation, client="agent-toolkit"):
    """Hold the reservation's journal lock from outside the lifecycle (another process's
    view: a separate open file description)."""
    path = env.state / client / "reservations" / f"{reservation['reservation_id']}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


@pytest.fixture
def short_waits(monkeypatch):
    # The lock wait of a prepare is bounded by what is left of prepare_deadline_ms; these
    # cases shorten that bound so an injected lock holder costs a fraction of a second.
    monkeypatch.setattr(sp, "ANSWER_BOUND_S", 0.2)
    monkeypatch.setattr(sp, "_PREPARE_MIN_WAIT_S", 0.1)


# -- construction -------------------------------------------------------------------------

def test_construction_stores_the_config_and_seams_and_binds_no_launch(env):
    lifecycle = env.lifecycle()
    popen, readiness, route = object(), (lambda: "x"), (lambda: "disabled")
    service = launch_service.build_launch_service(
        "agent-toolkit", config=lifecycle.config(), lifecycle=lifecycle, capped_popen=popen,
        load_caps=env.caps, readiness_code=readiness, route_state=route, clock=env.clock,
        admission_bound_s=12.5, worker_state_root=env.worker)
    assert service.config.config_sha256 == lifecycle.config().config_sha256
    assert (service.capped_popen, service.readiness_code, service.route_state) == (popen, readiness, route)
    assert service.load_caps == env.caps and service.clock is env.clock
    assert service.admission_bound_s == 12.5 and service.worker_state_root == env.worker
    assert service.lifecycle is lifecycle
    reservation = env.reserve()
    prepare(service, reservation)
    assert "phase_loop_runtime.launch_exec" not in sys.modules


def test_the_default_admission_bound_and_landed_seams(env):
    service = launch_service.build_launch_service("agent-toolkit", config=env.lifecycle().config(),
                                                  lifecycle=env.lifecycle())
    assert service.admission_bound_s == launch_service.ADMISSION_BOUND_S == 300.0
    assert service.capped_popen is seat_resource_caps.capped_popen
    assert service.load_caps is seat_resource_caps.load_caps
    assert service.readiness_code is seat_resource_caps.readiness_code


@pytest.mark.parametrize("kwargs,code", [
    ({"client": "agent-harness"}, "launch_config_invalid"),
    ({"client": "other"}, "launch_client_unknown"),
    ({"admission_bound_s": 0}, "launch_admission_bound_invalid"),
    ({"admission_bound_s": 301}, "launch_admission_bound_invalid"),
])
def test_construction_refuses_a_foreign_config_or_an_unbounded_admission(env, kwargs, code):
    lifecycle = env.lifecycle()
    args = {"client": "agent-toolkit", "config": lifecycle.config(), "lifecycle": lifecycle, **kwargs}
    client = args.pop("client")
    with pytest.raises(ValueError) as error:
        launch_service.build_launch_service(client, **args)
    assert str(error.value) == code


# -- C11 values ---------------------------------------------------------------------------

def test_local_prepare_assigns_the_run_scratch_and_tree_before_any_seed_read(env):
    service = env.service()
    reservation = env.reserve()
    response, raw, code = prepare(service, reservation)
    assert code == 0 and response.state == "prepared" and response.code is None
    run_id = response.paths.run_id
    assert run_id.startswith("run-") and len(run_id) == 36
    run_dir = env.launch_root() / "runs" / run_id
    assert response.paths.scratch_path == str(run_dir / "scratch")
    assert response.paths.tree_path == "/src/repo"
    assert run_dir.is_dir() and (run_dir.stat().st_mode & 0o777) == 0o700
    record = json.loads((env.launch_root() / "prepare" / f"{reservation['reservation_id']}.json").read_text())
    assert (record["run_id"], record["scratch_path"], record["tree_path"]) == (
        run_id, response.paths.scratch_path, "/src/repo")
    assert response.caller_context == {"run": "r1"}
    assert launch.decode_launch_response("prepare", raw) == response


@pytest.mark.parametrize("root,tree", [("/src/repo", "/fs/src/repo"), ("/r", "/fs/r")])
def test_openshell_prepare_uses_the_work_tree(env, root, tree):
    service = env.service("agent-harness")
    reservation = env.reserve("agent-harness")
    assert reservation["target"]["kind"] == "openshell"
    response, _raw, code = prepare(service, reservation, snapshot_root=root)
    assert code == 0
    run_id = response.paths.run_id
    assert response.paths.scratch_path == f"/work/{run_id}/scratch"
    assert response.paths.tree_path == f"/work/{run_id}{tree}"


# -- C11 idempotency ----------------------------------------------------------------------

def test_a_repeat_prepare_returns_identical_values_under_any_request_id(env):
    service = env.service()
    reservation = env.reserve()
    first, raw, _ = prepare(service, reservation, "prep-1")
    again, raw_again, code = prepare(service, reservation, "prep-1")
    assert code == 0 and raw_again == raw
    other, raw_other, code = prepare(service, reservation, "prep-2", context={"run": "r2"})
    assert code == 0 and other.paths == first.paths
    assert len(records(env, "runs")) == 1


def test_a_different_snapshot_root_refuses_input_mismatch_and_changes_nothing(env):
    service = env.service()
    reservation = env.reserve()
    first, _raw, _ = prepare(service, reservation, "prep-1")
    before = records(env, "prepare")
    response, _raw, code = prepare(service, reservation, "prep-2", snapshot_root="/elsewhere")
    assert (code, response.state, response.code, response.paths) == (
        10, "refused", "sandbox_launch_input_mismatch", None)
    assert records(env, "prepare") == before and len(records(env, "runs")) == 1
    assert prepare(service, reservation, "prep-3")[0].paths == first.paths
    # The refusal is journaled under its request_id and replays byte for byte.
    assert prepare(service, reservation, "prep-2", snapshot_root="/elsewhere")[2] == 10


def test_the_same_request_id_with_another_body_refuses_and_creates_nothing(env):
    service = env.service()
    reservation, other = env.reserve(), env.reserve()
    prepare(service, reservation, "prep-1")
    journaled = attempt(env, "prep-1")
    response, _raw, code = prepare(service, other, "prep-1")
    assert (code, response.code) == (10, "sandbox_launch_refused")
    assert records(env, "prepare") == [f"{reservation['reservation_id']}.json"]
    assert attempt(env, "prep-1") == journaled
    response, _raw, code = prepare(service, reservation, "prep-1", context={"run": "other"})
    assert (code, response.code) == (10, "sandbox_launch_refused")


# -- C11 replay ---------------------------------------------------------------------------

def test_replay_after_an_injected_timeout_prepares_once(env, short_waits):
    service = env.service()
    reservation = env.reserve()
    fd = hold_lock(env, reservation)
    try:
        response, _raw, code = prepare(service, reservation)
    finally:
        os.close(fd)
    assert (code, response.state, response.code, response.paths) == (20, "timeout", TIMEOUT, None)
    journaled = attempt(env, "prep-1")
    assert journaled["settled"] is False and journaled["run_id"] is None
    assert records(env, "prepare") == [] and records(env, "runs") == []
    response, raw, code = prepare(service, reservation)
    assert code == 0 and response.state == "prepared"
    assert prepare(service, reservation)[1] == raw
    assert len(records(env, "runs")) == 1


def test_an_indeterminate_replay_journals_nothing(env, short_waits):
    service = env.service()
    reservation = env.reserve()
    fd = hold_lock(env, reservation)
    try:
        prepare(service, reservation)
        journaled = attempt(env, "prep-1")
        response, _raw, code = prepare(service, reservation)
    finally:
        os.close(fd)
    assert (code, response.state, response.code) == (20, "timeout", TIMEOUT)
    assert attempt(env, "prep-1") == journaled


def _block_run_dir(env, run_id):
    runs = env.launch_root() / "runs"
    runs.mkdir(parents=True, exist_ok=True, mode=0o700)
    (runs / run_id).write_text("in the way")


def test_replay_after_an_injected_internal_failure_reuses_the_planned_run_id(env):
    reservation = env.reserve()
    fresh = iter(f"{n:032x}" for n in range(0xe00, 0xf00))
    service = env.service(lifecycle=env.lifecycle(new_id=lambda: next(fresh)))
    planned = f"run-{0xe00:032x}"
    _block_run_dir(env, planned)
    with pytest.raises(sp.LifecycleError) as error:
        prepare(service, reservation)
    assert str(error.value) == "placement_internal"
    journaled = attempt(env, "prep-1")
    assert (journaled["settled"], journaled["run_id"]) == (False, planned)
    assert records(env, "prepare") == []
    (env.launch_root() / "runs" / planned).unlink()
    response, _raw, code = prepare(service, reservation)
    # A confirmed absence prepares once, under the run_id the attempt already journaled.
    assert code == 0 and response.paths.run_id == planned
    assert records(env, "runs") == [planned]


def _interrupt_settlement(monkeypatch, lifecycle):
    real = lifecycle._settle_prepare

    def settle(record, response):
        if response.state == "prepared":
            raise sp.LifecycleError("placement_internal")
        return real(record, response)

    monkeypatch.setattr(lifecycle, "_settle_prepare", settle)
    return real


def test_a_replay_that_confirms_the_record_settles_prepared(env, monkeypatch):
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    real = _interrupt_settlement(monkeypatch, lifecycle)
    with pytest.raises(sp.LifecycleError):
        prepare(service, reservation)
    assert attempt(env, "prep-1")["settled"] is False and len(records(env, "prepare")) == 1
    monkeypatch.setattr(lifecycle, "_settle_prepare", real)
    response, raw, code = prepare(service, reservation)
    assert code == 0 and response.paths.run_id == attempt(env, "prep-1")["run_id"]
    assert attempt(env, "prep-1")["settled"] is True and prepare(service, reservation)[1] == raw


def _uncertain_write(env, monkeypatch):
    """An unsettled attempt whose prepare record was written: the uncertain write."""
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    real = _interrupt_settlement(monkeypatch, lifecycle)
    with pytest.raises(sp.LifecycleError):
        prepare(service, reservation)
    monkeypatch.setattr(lifecycle, "_settle_prepare", real)
    return service, reservation, attempt(env, "prep-1")


def _bound(record):
    return record["started_at"] + (record["deadline_ms"] + sp.REPLAY_SETTLE_ALLOWANCE_MS) / 1000.0


@pytest.mark.parametrize("case", ["at_bound", "past_bound", "backward_clock"])
def test_the_clock_is_read_before_the_journal_and_settles_end_reached(env, monkeypatch, case):
    service, reservation, journaled = _uncertain_write(env, monkeypatch)
    env.clock.now = {"at_bound": _bound(journaled), "past_bound": _bound(journaled) + 1,
                     "backward_clock": journaled["started_at"] - 1}[case]
    response, raw, code = prepare(service, reservation)
    # The prepare record is present, yet no journal read confirms it: the bound settles first.
    assert (code, response.state, response.code, response.paths) == (20, "timeout", END, None)
    assert records(env, "cleanup") == [f"{journaled['run_id']}.json"]
    entry = json.loads((env.launch_root() / "cleanup" / f"{journaled['run_id']}.json").read_text())
    assert (entry["reservation_id"], entry["run_id"]) == (reservation["reservation_id"], journaled["run_id"])
    assert prepare(service, reservation)[1] == raw


def test_an_unreadable_start_settles_end_reached(env, monkeypatch):
    service, reservation, journaled = _uncertain_write(env, monkeypatch)
    journaled["started_at"] = "unreadable"
    path = env.launch_root() / "prepare-requests" / "prep-1.json"
    path.write_text(json.dumps(journaled))
    response, _raw, code = prepare(service, reservation)
    assert (code, response.code) == (20, END)


def test_lifecycle_startup_settles_unsettled_prepare_attempts_at_their_bound(env, monkeypatch):
    _service, reservation, journaled = _uncertain_write(env, monkeypatch)
    env.clock.now = _bound(journaled)
    env.reap()  # a restarted lifecycle's start-up
    settled = attempt(env, "prep-1")
    assert settled["settled"] is True and settled["exit"] == 20
    assert json.loads(settled["response"])["code"] == END
    assert records(env, "cleanup") == [f"{journaled['run_id']}.json"]


def test_a_requester_stops_at_end_reached_and_a_new_request_id_prepares(env, monkeypatch):
    service, reservation, journaled = _uncertain_write(env, monkeypatch)
    env.clock.now = _bound(journaled)
    assert prepare(service, reservation)[2] == 20
    # The reservation (ttl 600 s) outlives the prepare settle bound, so a fresh request_id
    # finds the record the uncertain write left and returns its values.
    response, _raw, code = prepare(service, reservation, "prep-2")
    assert code == 0 and response.paths.run_id == journaled["run_id"]


# -- C11 refusals -------------------------------------------------------------------------

def test_after_the_exec_claim_prepare_refuses_exec_claimed(env):
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    first, _raw, _ = prepare(service, reservation)
    assert lifecycle.claim_exec(reservation["reservation_id"], "launch-1", first.paths.run_id,
                                timeout_s=1) is None
    response, raw, code = prepare(service, reservation, "prep-2")
    assert (code, response.state, response.code, response.paths) == (
        10, "refused", "sandbox_launch_exec_claimed", None)
    assert prepare(service, reservation, "prep-2")[1] == raw


def test_a_released_or_expired_reservation_refuses_reservation_unknown(env):
    service = env.service()
    released, expired = env.reserve(), env.reserve()
    assert env.release(released)[1] == 0
    response, _raw, code = prepare(service, released, "prep-r")
    assert (code, response.code) == (10, "sandbox_launch_reservation_unknown")
    env.clock.now += 600
    response, _raw, code = prepare(service, expired, "prep-e")
    assert (code, response.code) == (10, "sandbox_launch_reservation_unknown")
    assert records(env, "prepare") == [] and records(env, "runs") == []


@pytest.mark.parametrize("field,value", [("expires_at", "2030-01-01T00:00:00Z"),
                                         ("config_sha256", "f" * 64),
                                         ("lease_id", "lease-x")])
def test_a_differing_reservation_echo_refuses_mismatch(env, field, value):
    service = env.service()
    reservation = env.reserve()
    echo = {**reservation, field: value}
    response, _raw, code = prepare(service, echo)
    assert (code, response.code) == (10, "sandbox_launch_reservation_mismatch")
    assert records(env, "prepare") == []


def test_another_clients_reservation_is_never_looked_up(env):
    harness_reservation = env.reserve("agent-harness")
    response, _raw, code = prepare(env.service(), harness_reservation)
    assert (code, response.code) == (10, "sandbox_launch_reservation_unknown")
    assert records(env, "prepare", "agent-harness") == []


def test_an_unreadable_caps_record_refuses_prepare_and_status_and_cancel_keep_working(env):
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    first, _raw, _ = prepare(service, reservation)
    journal_launch(lifecycle, reservation, "launch-1", first.paths)
    env.caps_error = True
    response, raw, code = prepare(service, reservation, "prep-2")
    assert (code, response.state, response.paths) == (10, "refused", None)
    assert response.code == sp.PREPARE_CAPS_UNREADABLE_CODE
    assert launch.decode_launch_response("prepare", raw) == response
    assert len(records(env, "runs")) == 1
    env.journal[first.paths.run_id] = journal_status("running", first.paths.run_id)
    assert status(service, reservation, "launch-1").state == "running"
    env.cancel_outcome = "cancelled"
    assert cancel(service, reservation, "launch-1").state == "cancelled"


# -- status echo schema -------------------------------------------------------------------

def _finished(reservation_id, request_id, paths):
    evidence = build_launch_evidence(
        snapshot=None, launch_digest=HEX, template_sha256=HEX, image_digest=DIGEST,
        policy_digest=DIGEST, egress_sha256=DIGEST, transport_id="local", caps_sha256=HEX,
        bridge_attached=False, stdout_sha256=None, stderr_sha256=None, exit_status=0,
        duration_ms=5, renewals=1)
    return launch.LaunchResponse(
        request_id, reservation_id, paths.run_id, "finished", None, None, None, None,
        launch.Termination("completed", None, "worker"), 1, HEX, paths.scratch_path,
        paths.tree_path, None, evidence, {"run": "r1"})


def test_a_finished_status_with_null_or_differing_top_level_values_is_refused():
    paths = launch.PreparedPaths("run-" + "1" * 32, "/s/scratch", "/src/repo")
    nested = _finished("rsv-" + "1" * 32, "launch-1", paths)
    good = launch.StatusResponse("st-1", "rsv-" + "1" * 32, "launch-1", "finished", nested,
                                 paths.run_id, paths.scratch_path, paths.tree_path, {})
    raw = launch.encode_launch_response(good)
    assert launch.decode_launch_response("status", raw) == good
    for field in ("run_id", "scratch_path", "tree_path"):
        value = json.loads(raw)
        value[field] = None
        assert not launch.validate_launch_message("StatusResponse", value)
        with pytest.raises(launch.ProtocolError):
            launch.decode_launch_response("status", json.dumps(value).encode() + b"\n")
    for field, other in (("run_id", "run-" + "2" * 32), ("scratch_path", "/x"), ("tree_path", "/y")):
        value = json.loads(raw)
        value[field] = other
        with pytest.raises(launch.ProtocolError):
            launch.decode_launch_response("status", json.dumps(value).encode() + b"\n")
        with pytest.raises(launch.ProtocolError):
            launch.encode_launch_response(launch.StatusResponse.from_json(value))


# -- L-S4 status --------------------------------------------------------------------------

def journal_launch(lifecycle, reservation, request_id, paths, *, claim=True, terminal=None,
                   invocations=1):
    """What the launch order journals (SL-8), written through the lifecycle hooks."""
    reservation_id = reservation["reservation_id"]
    lifecycle.write_launch_record(request_id, {
        "reservation_id": reservation_id, "request_id": request_id, "run_id": paths.run_id,
        "scratch_path": paths.scratch_path, "tree_path": paths.tree_path,
        "caller_context": {"run": "r1"}, "worker_invocations": invocations,
        "envelope_digest": HEX})
    if claim:
        assert lifecycle.claim_exec(reservation_id, request_id, paths.run_id, timeout_s=1) is None
    if terminal is not None:
        lifecycle.write_launch_terminal(request_id, terminal)


def journal_status(display, attempt_id, *, identity=True):
    state = display if display in ("queued", "running", "cancelling") else (
        None if display == "unknown" else "finished")
    return projection.AttemptStatus(
        attempt_id, state, display, None, None, None, None, (),
        run_status.AttemptIdentity("a" * 64, "b" * 64, attempt_id, attempt_id) if identity else None)


def status(service, reservation, launch_request_id, request_id="st-1"):
    body = {"schema": "placement.launch.status.request.v1", "request_id": request_id,
            "reservation_id": reservation["reservation_id"], "launch_request_id": launch_request_id,
            "caller_context": {"s": 1}}
    response = service.status(launch.decode_launch_request("status", json.dumps(body).encode()))
    launch.encode_launch_response(response)
    return response


def cancel(service, reservation, launch_request_id, deadline_ms=2000, cancelled=None):
    body = {"schema": "placement.launch.cancel.request.v1", "request_id": "cx-1",
            "reservation_id": reservation["reservation_id"], "launch_request_id": launch_request_id,
            "deadline_ms": deadline_ms, "caller_context": {}}
    response = service.cancel(launch.decode_launch_request("cancel", json.dumps(body).encode()),
                              cancelled=cancelled or threading.Event())
    launch.encode_launch_response(response)
    return response


@pytest.fixture
def launched(env):
    lifecycle = env.lifecycle()
    service = env.service(lifecycle=lifecycle)
    reservation = env.reserve()
    paths = prepare(service, reservation)[0].paths
    return lifecycle, service, reservation, paths


def test_status_without_a_launch_record_is_unknown_attempt(env, launched):
    _lifecycle, service, reservation, _paths = launched
    response = status(service, reservation, "launch-none")
    assert (response.state, response.launch, response.run_id, response.scratch_path,
            response.tree_path) == ("unknown_attempt", None, None, None, None)
    assert launch.launch_exit_class(response) == 10 and response.caller_context == {"s": 1}


def test_status_replays_the_terminal_with_the_prepared_values(env, launched):
    lifecycle, service, reservation, paths = launched
    terminal = _finished(reservation["reservation_id"], "launch-1", paths)
    journal_launch(lifecycle, reservation, "launch-1", paths, terminal=terminal)
    env.journal[paths.run_id] = journal_status("running", paths.run_id)
    response = status(service, reservation, "launch-1")
    assert response.state == "finished" and response.launch == terminal
    assert (response.run_id, response.scratch_path, response.tree_path) == (
        paths.run_id, paths.scratch_path, paths.tree_path)
    assert response.launch.attempt_id == paths.run_id


@pytest.mark.parametrize("display", ["queued", "running", "cancelling"])
def test_status_reports_a_live_journal_state_with_the_claim_paths(env, launched, display):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths)
    env.journal[paths.run_id] = journal_status(display, paths.run_id)
    response = status(service, reservation, "launch-1")
    assert (response.state, response.launch) == (display, None)
    assert (response.run_id, response.scratch_path, response.tree_path) == (
        paths.run_id, paths.scratch_path, paths.tree_path)


@pytest.mark.parametrize("journal", ["finished (completed)", "refused", "unknown", "stale_unknown",
                                     "no_identity", None])
def test_status_without_a_laneexec_terminal_is_uncertain(env, launched, journal):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths)
    if journal == "no_identity":
        env.journal[paths.run_id] = journal_status("running", paths.run_id, identity=False)
    elif journal is not None:
        env.journal[paths.run_id] = journal_status(journal, paths.run_id)
    response = status(service, reservation, "launch-1")
    assert response.state == "uncertain" and response.launch.code == STATUS_UNCERTAIN_CODE
    # The claim is held, so the attempt's values are reported.
    assert (response.run_id, response.scratch_path, response.tree_path) == (
        paths.run_id, paths.scratch_path, paths.tree_path)


def test_status_of_an_unclaimed_launch_without_a_terminal_carries_null_paths(env, launched):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths, claim=False)
    response = status(service, reservation, "launch-1")
    assert response.state == "uncertain"
    assert (response.run_id, response.scratch_path, response.tree_path) == (None, None, None)


def test_status_through_the_landed_journal_reader_with_no_journal_is_uncertain(env, launched):
    lifecycle, _service, reservation, paths = launched
    service = env.service(lifecycle=lifecycle, attempt_status=None)
    journal_launch(lifecycle, reservation, "launch-1", paths)
    assert status(service, reservation, "launch-1").state == "uncertain"


def test_status_and_cancel_never_read_the_other_clients_inventory(env, launched):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths)
    harness = env.service("agent-harness")
    assert status(harness, reservation, "launch-1").state == "unknown_attempt"
    assert cancel(harness, reservation, "launch-1").state == "unknown_attempt"
    assert env.cancels == []
    # A record under another reservation id is not this launch either.
    other = {**reservation, "reservation_id": "rsv-" + "9" * 32}
    assert status(service, other, "launch-1").state == "unknown_attempt"


# -- L-S4 cancel --------------------------------------------------------------------------

@pytest.mark.parametrize("outcome,state,journaled", [
    ("cancelled", "cancelled", []), ("already_terminal", "already_terminal", []),
    ("cancel_pending", "cancel_pending", []),
    ("unknown_attempt", "cancel_pending", ["unknown_attempt"]),
    ("owner_unverified", "cancel_pending", ["owner_unverified"]),
    ("owner_not_live", "cancel_pending", ["owner_not_live"]),
    ("something_else", "cancel_pending", ["unmapped"]),
    (RuntimeError("boom"), "cancel_pending", ["unmapped"]),
])
def test_cancel_goes_through_the_verified_owner_and_never_reports_zero_signal_success(
        env, launched, outcome, state, journaled):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths)
    env.cancel_outcome = outcome
    response = cancel(service, reservation, "launch-1")
    assert response.state == state
    assert env.cancels == [("service", paths.run_id)]
    assert lifecycle.launch_local_cancels("launch-1") == journaled
    expected_exit = {"cancelled": 0, "already_terminal": 0, "cancel_pending": 20}[state]
    assert launch.launch_exit_class(response) == expected_exit


def test_cancel_with_no_claim_and_an_unknown_journal_attempt_is_unknown_attempt(env, launched):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths, claim=False)
    env.cancel_outcome = "unknown_attempt"
    response = cancel(service, reservation, "launch-1")
    assert response.state == "unknown_attempt" and launch.launch_exit_class(response) == 10
    assert cancel(service, reservation, "launch-none").state == "unknown_attempt"


def test_cancel_after_the_terminal_is_already_terminal_without_a_signal(env, launched):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths,
                   terminal=_finished(reservation["reservation_id"], "launch-1", paths))
    assert cancel(service, reservation, "launch-1").state == "already_terminal"
    assert env.cancels == []


def test_a_cancelled_caller_sends_nothing_and_answers_cancel_pending(env, launched):
    lifecycle, service, reservation, paths = launched
    journal_launch(lifecycle, reservation, "launch-1", paths)
    stop = threading.Event()
    stop.set()
    assert cancel(service, reservation, "launch-1", cancelled=stop).state == "cancel_pending"
    assert env.cancels == []


def test_cancel_through_the_landed_cancel_attempt_with_no_journal(env, launched):
    lifecycle, _service, reservation, paths = launched
    service = env.service(lifecycle=lifecycle, cancel_attempt=None)
    journal_launch(lifecycle, reservation, "launch-1", paths)
    # The landed cancel_attempt finds no JOURNAL attempt; LaneExec holds the claim.
    assert cancel(service, reservation, "launch-1").state == "cancel_pending"
    assert lifecycle.launch_local_cancels("launch-1") == ["unknown_attempt"]
