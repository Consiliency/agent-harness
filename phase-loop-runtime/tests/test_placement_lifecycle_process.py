"""v13 PLACECLI SL-1: the production placement lifecycle behind ``agent-harness-placement``.

Every case enters through :class:`PlacementLifecycle` built at its own construction site.
Effects are counted on the injected collaborators: ``observe`` (a capacity probe), the fake
coordinator's calls, lease files in the client inventory, the bridge, ``reconcile`` and the
caps loader and readiness callables (the landed ``seat_resource_caps`` functions are the
defaults; nothing patches that module).
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import math
import os
from importlib import resources
from pathlib import Path
import threading
import time

import pytest
import rfc8785

from phase_loop_runtime import placement_process_contract as contract
from phase_loop_runtime import sandbox_placement as sp
from phase_loop_runtime import sandbox_policy, seat_resource_caps
from phase_loop_runtime.placement_bridge import BridgeHandle

DIGEST = "sha256:" + "c" * 64
TIMEOUT = "sandbox_placement_operation_timeout"
UNCONFIRMED = "sandbox_placement_release_unconfirmed"
END = "sandbox_placement_end_reached"
NOW = 1_800_000_000.0
POLICY_DIGESTS = {
    "minimal-with-app": "sha256:075b63f281bb7ec6c9bd2c1c5c3fb529240d2be7766dc93ed89f5fcd7ed4577e",
    "minimal-without-app": "sha256:974189cb8fa035f9273eda1db2d5002a712a6953f8d92c519b4a8f381e80b43d",
    "full-remote-pi-runner": "sha256:767400727c35828c350a7adaa01a8eed40e14bdc86fd934812910872a935ec2c",
}
ANTHROPIC = [{"host": "api.anthropic.com", "port": 443}]
OPENAI = [{"host": "api.openai.com", "port": 443}, {"host": "auth.openai.com", "port": 443}]


class Coordinator:
    """A fake OpenShell coordinator backend: holds by owner and lease, counts every call."""

    name = "openshell-fake"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.held: dict[str, str] = {}
        self.behave: dict[str, object] = {}
        self.upstream = "/nonexistent/upstream"

    def _call(self, method, *args):
        self.calls.append(method)
        hook = self.behave.get(method)
        return hook(*args) if hook is not None else None

    def capabilities(self):
        self.calls.append("capabilities")
        return frozenset()

    def declaration(self):
        self.calls.append("declaration")
        return sp.Declaration()

    def available(self, request):
        self.calls.append("available")
        return True

    def endpoint(self, root):
        self.calls.append("endpoint")
        return None

    def admit(self, request, bound):
        self._call("admit", request, bound)
        self.held[request.lease_id] = request.owner_id

    def kill(self, lease_id, bound):
        self._call("kill", lease_id, bound)
        self.held.pop(lease_id, None)

    def list_owned(self, owner_id, bound):
        out = self._call("list_owned", owner_id, bound)
        if out is not None:
            return out
        return [(f"sbx-{lease[:8]}", lease) for lease, owner in self.held.items() if owner == owner_id]

    def forward_exposure(self, lease_id, bound):
        self._call("forward_exposure", lease_id, bound)
        return {"service_name": "pi-link", "upstream": self.upstream}

    def commit(self, *args):
        self.calls.append("commit")
        raise AssertionError("reserve never commits")

    def execute(self, *args):
        self.calls.append("execute")
        raise AssertionError("reserve never executes")

    def wait(self, *args):
        self.calls.append("wait")

    def cancel(self, *args):
        self.calls.append("cancel")

    def renew(self, *args):
        self.calls.append("renew")

    def release(self, *args):
        self.calls.append("release")

    @property
    def effects(self) -> list[str]:
        return [c for c in self.calls if c not in ("capabilities", "declaration", "available", "endpoint")]


class Bridge:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.fail = False

    def open(self, reservation, exposure, *, cancelled):
        if self.fail:
            from phase_loop_runtime.placement_bridge import BridgeUnavailable

            raise BridgeUnavailable("bridge_start_failed")
        self.opened.append(reservation.reservation_id)
        descriptor = contract.BridgeDescriptor(exposure.service_name,
                                               f"/run/fake/{reservation.reservation_id}/s")
        return BridgeHandle(descriptor, reservation.reservation_id, f"/run/fake/{reservation.reservation_id}",
                            0, None)

    def close(self, handle, *, cancelled):
        self.closed.append(handle.reservation_id)
        return contract.LeaseFlags(fenced=True, destruction_observed=True, barrier_confirmed=True)

    def directory_for(self, reservation):
        return Path(f"/run/fake/{reservation.reservation_id}")

    def reclaim(self, directory, *, cancelled):
        self.reclaimed = [*getattr(self, "reclaimed", []), str(directory)]
        return contract.LeaseFlags(fenced=True, destruction_observed=True, barrier_confirmed=True)


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.config = tmp_path / "config"
        self.config.mkdir(mode=0o700)
        self.state = tmp_path / "state"
        self.coordinator = Coordinator()
        self.bridge = Bridge()
        self.clock = Clock()
        self.counts = {"observe": 0, "caps": 0, "readiness": 0, "reconcile": 0}
        self.reading = {"memory_available_bytes": 64 << 30, "memory_total_bytes": 128 << 30,
                        "load_per_cpu_percent": 10.0, "io_full_avg10": 0.0, "memory_some_avg10": 0.0}
        self.caps_error = False
        self.readiness = None
        self.verdict = "indeterminate"
        self.ids = iter(f"{n:032x}" for n in range(1, 10_000))

    def write(self, name: str, body: dict) -> None:
        path = self.config / name
        path.write_text(json.dumps(body))
        os.chmod(path, 0o600)

    def toolkit(self, **changes) -> None:
        body = {
            "schema": "placement.client-config.v1", "client": "agent-toolkit",
            "providers": {
                "anthropic": {"endpoints": ANTHROPIC, "workloads": ["pi-runner"],
                              "policy_vectors": ["full-remote-pi-runner", "minimal-without-app"]},
                "openai": {"endpoints": OPENAI, "workloads": ["pi-runner"],
                           "policy_vectors": ["full-remote-pi-runner", "minimal-without-app"]},
            },
            "targets": [
                {"name": "ai", "kind": "openshell", "rank": 0, "transport_id": "ai-openshell",
                 "root": "openshell://ai/placement", "probe_receipt_providers": ["anthropic", "openai"]},
                {"name": "local", "kind": "local", "rank": 1, "transport_id": "local"},
                {"name": "e2b", "kind": "e2b", "rank": 2, "transport_id": "e2b",
                 "od7_providers": ["anthropic", "openai"]},
            ],
        }
        body.update(changes)
        self.write("agent-toolkit.json", body)

    def harness(self, **changes) -> None:
        body = {
            "schema": "placement.client-config.v1", "client": "agent-harness",
            "providers": {"anthropic": {"endpoints": ANTHROPIC,
                                        "workloads": ["leg", "qualification", "implementation"],
                                        "policy_vectors": ["minimal-with-app", "minimal-without-app"]}},
            "targets": [
                {"name": "ai", "kind": "openshell", "rank": 0, "transport_id": "ai-openshell",
                 "root": "openshell://ai/placement", "probe_receipt_providers": ["anthropic"]},
                {"name": "local", "kind": "local", "rank": 1, "transport_id": "local"},
            ],
            "seat_route": {"leg": "ai", "qualification": "local", "implementation": "local"},
        }
        body.update(changes)
        self.write("agent-harness.json", body)

    def observe(self):
        self.counts["observe"] += 1
        return dict(self.reading)

    def caps(self):
        self.counts["caps"] += 1
        if self.caps_error:
            raise seat_resource_caps.CapsUnavailable("seat_resource_caps_unavailable")
        return seat_resource_caps.DEFAULT_CAPS

    def ready(self):
        self.counts["readiness"] += 1
        return self.readiness

    def reconcile(self, record, timeout_s):
        self.counts["reconcile"] += 1
        assert timeout_s >= 0
        return self.verdict

    def backend_for(self, root):
        return self.coordinator if getattr(root, "scheme", "") == "openshell" else None

    def lifecycle(self, client="agent-toolkit", **overrides) -> sp.PlacementLifecycle:
        kwargs = dict(state_root=self.state, config_root=self.config, caps_loader=self.caps,
                      caps_readiness=self.ready, observe=self.observe, backend_for=self.backend_for,
                      reconcile=self.reconcile, bridge=self.bridge, clock=self.clock,
                      new_id=lambda: next(self.ids))
        kwargs.update(overrides)
        return sp.PlacementLifecycle(client, **kwargs)

    def leases(self, client="agent-toolkit") -> list[Path]:
        directory = self.state / client / "placement-leases"
        return sorted(directory.glob("*.json")) if directory.is_dir() else []

    def slots(self) -> list[Path]:
        directory = self.state / "local-slots"
        return sorted(directory.glob("*.json")) if directory.is_dir() else []

    def reservations(self, client="agent-toolkit") -> list[Path]:
        directory = self.state / client / "reservations"
        return sorted(directory.glob("*.json")) if directory.is_dir() else []


@pytest.fixture
def env(tmp_path):
    built = Env(tmp_path)
    built.toolkit()
    built.harness()
    return built


def reserve_body(request_id="req-1", *, workload="pi-runner", providers=("anthropic",),
                 policy_vector=None, deadline_ms=60000, ttl_s=600, context=None):
    return {"schema": "placement.reserve.request.v1", "request_id": request_id, "workload": workload,
            "ttl_s": ttl_s, "image_digest": DIGEST,
            "policy_vector": policy_vector or ("full-remote-pi-runner" if workload == "pi-runner"
                                               else "minimal-with-app"),
            "providers": list(providers), "deadline_ms": deadline_ms,
            "caller_context": context if context is not None else {"run": "r1"}}


def reserve(lifecycle, *args, **kwargs):
    request = contract.decode_request("reserve", json.dumps(reserve_body(*args, **kwargs)).encode())
    response = lifecycle.reserve(request, cancelled=threading.Event())
    return response, contract.encode_response(response), contract.exit_class(response)


def release(lifecycle, reservation, request_id="rel-1", deadline_ms=5000):
    body = {"schema": "placement.release.request.v1", "request_id": request_id,
            "reservation": reservation, "deadline_ms": deadline_ms, "caller_context": {}}
    response = lifecycle.release(contract.decode_request("release", json.dumps(body).encode()),
                                 cancelled=threading.Event())
    return response, contract.exit_class(response)


def reap(lifecycle, max_items=100, deadline_ms=5000):
    body = {"schema": "placement.reap.request.v1", "request_id": "reap-1", "scope": "caller_inventory",
            "deadline_ms": deadline_ms, "max_items": max_items, "caller_context": {}}
    response = lifecycle.reap(contract.decode_request("reap", json.dumps(body).encode()),
                              cancelled=threading.Event())
    return response, contract.exit_class(response)


def trail(response):
    return [(e.target, e.outcome, e.code) for e in response.trail]


def expected_egress(providers, endpoints):
    rules = sorted({(e["host"], e["port"]) for name in providers for e in endpoints[name]})
    grant = {"providers": sorted(set(providers)),
             "rules": [{"host": h, "port": p} for h, p in rules]}
    return "sha256:" + sha256(rfc8785.dumps(grant)).hexdigest()


# -- the ranked pi-runner walk --------------------------------------------------------------

def test_pi_runner_takes_ai_by_authoritative_capacity_and_never_launches(env):
    lifecycle = env.lifecycle()
    response, _raw, code = reserve(lifecycle)
    assert code == 0 and response.outcome == "admitted"
    r = response.reservation
    assert (r.target.name, r.target.kind, r.policy_vector, r.rank_policy) == (
        "ai", "openshell", "full-remote-pi-runner", "agent_executor")
    assert r.policy_digest == POLICY_DIGESTS["full-remote-pi-runner"]
    assert (r.client, r.inventory, r.transport_id) == ("agent-toolkit", "agent-toolkit", "ai-openshell")
    assert r.lease_id is not None and r.bridge is not None and r.bridge.service_name == "pi-link"
    assert r.config_sha256 == lifecycle.config().config_sha256
    assert trail(response) == [("ai", "admitted", None)]
    assert "commit" not in env.coordinator.calls and "execute" not in env.coordinator.calls
    assert env.coordinator.calls.count("admit") == 1 and env.counts["observe"] == 0
    assert env.bridge.opened == [r.reservation_id]
    # The lease stays recorded (not abandoned) and the coordinator still holds it.
    [lease] = env.leases()
    assert json.loads(lease.read_text().splitlines()[0])["abandoned"] is False
    assert r.lease_id in env.coordinator.held


def test_ai_at_capacity_then_an_actually_reserved_local_slot(env):
    env.coordinator.behave["admit"] = lambda request, bound: (_ for _ in ()).throw(
        sp.PlacementUnavailable("sandbox_placement_at_capacity"))
    settings = replace(sp.sandbox_policy.placement_driver_settings(env={}), admit_wait_s=0)
    response, _raw, code = reserve(env.lifecycle(settings=settings))
    assert code == 0
    r = response.reservation
    assert (r.target.name, r.policy_vector, r.bridge, r.lease_id) == (
        "local", "minimal-without-app", None, None)
    assert r.policy_digest == POLICY_DIGESTS["minimal-without-app"]
    assert trail(response) == [("ai", "at_capacity", "sandbox_placement_at_capacity"),
                               ("local", "admitted", None)]
    assert len(env.slots()) == 1 and env.bridge.opened == []


def test_disabled_e2b_is_recorded_and_never_decides(env):
    env.coordinator.behave["admit"] = lambda request, bound: (_ for _ in ()).throw(
        sp.PlacementUnavailable("sandbox_placement_not_enrolled"))
    env.reading["memory_available_bytes"] = 1
    response, _raw, code = reserve(env.lifecycle())
    assert code == 10 and response.outcome == "at_capacity"
    assert trail(response) == [("ai", "refused", "sandbox_placement_not_enrolled"),
                               ("local", "at_capacity", "sandbox_placement_at_capacity"),
                               ("e2b", "refused", "sandbox_placement_driver_unavailable")]
    assert response.trail[1].reason == "pressure"


def test_a_local_pi_reservation_holds_one_shared_live_sandbox_slot(env):
    env.write("host.json", {"schema": "placement.host-config.v1",
                            "local_headroom": {"live_sandboxes_maximum_exclusive": 1}})
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    first, _raw, code = reserve(env.lifecycle(), "req-a")
    assert code == 0 and first.reservation.bridge is None
    assert first.reservation.policy_vector == "minimal-without-app"
    # The other client's local seat counts against the same host-wide gate.
    second, _raw, code = reserve(env.lifecycle("agent-harness"), "req-b", workload="qualification")
    assert code == 10 and second.outcome == "at_capacity"
    release(env.lifecycle(), first.reservation.to_json())
    third, _raw, code = reserve(env.lifecycle("agent-harness"), "req-c", workload="qualification")
    assert code == 0 and third.reservation.target.kind == "local"


# -- seats: single trusted target -----------------------------------------------------------

@pytest.mark.parametrize("workload,target", [("leg", "ai"), ("qualification", "local"),
                                             ("implementation", "local")])
def test_seat_workloads_admit_only_the_trusted_route_target(env, workload, target):
    response, _raw, code = reserve(env.lifecycle("agent-harness"), workload=workload)
    assert code == 0
    r = response.reservation
    assert r.target.name == target and r.rank_policy == "seats_single_target"
    assert [entry.target for entry in response.trail] == [target]
    assert (r.bridge is not None) == (workload == "leg")


def test_a_missing_seat_route_refuses_before_any_probe(env):
    env.harness(seat_route={"leg": "ai"})
    response, _raw, code = reserve(env.lifecycle("agent-harness"), workload="implementation")
    assert code == 10 and response.code == "sandbox_placement_workload_unsupported"
    assert env.counts["observe"] == 0 and env.coordinator.calls == [] and env.leases("agent-harness") == []


@pytest.mark.parametrize("client,workload", [("agent-toolkit", "leg"), ("agent-harness", "pi-runner")])
def test_a_client_workload_mismatch_refuses_before_effects(env, client, workload):
    response, _raw, code = reserve(env.lifecycle(client), workload=workload)
    assert code == 10 and response.code == "sandbox_placement_workload_unsupported"
    assert trail(response) == [("preflight", "refused", "sandbox_placement_workload_unsupported")]
    assert env.counts["observe"] == 0 and env.coordinator.calls == []


# -- providers and egress -------------------------------------------------------------------

@pytest.mark.parametrize("providers", [("unknown",), ("anthropic", "unknown")])
def test_an_unknown_provider_refuses_with_zero_effects(env, providers):
    response, _raw, code = reserve(env.lifecycle(), providers=providers)
    assert code == 10 and response.code == "sandbox_placement_provider_refused"
    assert env.counts["observe"] == 0 and env.coordinator.calls == [] and env.leases() == []
    assert env.slots() == [] and env.bridge.opened == []


def test_a_provider_not_permitted_for_the_workload_refuses(env):
    env.harness(providers={"anthropic": {"endpoints": ANTHROPIC, "workloads": ["leg"],
                                         "policy_vectors": ["minimal-with-app"]}})
    response, _raw, code = reserve(env.lifecycle("agent-harness"), workload="qualification")
    assert code == 10 and response.code == "sandbox_placement_provider_refused"
    assert env.counts["observe"] == 0


def test_a_provider_not_permitted_by_the_resolved_vector_refuses_that_target(env):
    env.toolkit(providers={"anthropic": {"endpoints": ANTHROPIC, "workloads": ["pi-runner"],
                                         "policy_vectors": ["minimal-without-app"]}})
    response, _raw, code = reserve(env.lifecycle())
    assert code == 0 and response.reservation.target.name == "local"
    assert trail(response)[0] == ("ai", "refused", "sandbox_placement_provider_refused")
    assert "admit" not in env.coordinator.calls and env.leases() == []


def test_an_owned_host_needs_the_generic_probe_receipt(env):
    targets = json.loads((env.config / "agent-toolkit.json").read_text())["targets"]
    targets[0]["probe_receipt_providers"] = ["anthropic"]
    env.toolkit(targets=targets)
    response, _raw, _code = reserve(env.lifecycle(), providers=("anthropic", "openai"))
    assert trail(response)[0] == ("ai", "refused", "sandbox_placement_provider_refused")
    assert "admit" not in env.coordinator.calls


def test_a_third_party_target_needs_od7_for_every_provider(env):
    env.toolkit(targets=[{"name": "e2b", "kind": "e2b", "rank": 2, "transport_id": "e2b",
                          "od7_providers": ["anthropic"]}])
    response, _raw, _code = reserve(env.lifecycle(), "a", providers=("anthropic", "openai"))
    assert trail(response) == [("e2b", "refused", "sandbox_placement_provider_refused")]
    response, _raw, _code = reserve(env.lifecycle(), "b", providers=("anthropic",))
    assert trail(response) == [("e2b", "refused", "sandbox_placement_driver_unavailable")]


def test_effective_egress_is_exactly_baseline_plus_declared_endpoints(env):
    endpoints = {"anthropic": ANTHROPIC, "openai": OPENAI}
    response, _raw, _code = reserve(env.lifecycle(), providers=("openai", "anthropic"))
    assert response.reservation.providers == ("openai", "anthropic")
    assert response.reservation.egress_sha256 == expected_egress(["anthropic", "openai"], endpoints)
    grant, digest = sp.effective_egress(["openai", "anthropic"], (), {
        "anthropic": [("api.anthropic.com", 443)],
        "openai": [("api.openai.com", 443), ("auth.openai.com", 443)]})
    assert digest == response.reservation.egress_sha256
    assert grant["rules"] == [{"host": "api.anthropic.com", "port": 443},
                              {"host": "api.openai.com", "port": 443},
                              {"host": "auth.openai.com", "port": 443}]
    # Order and duplicates do not move the digest; an undeclared endpoint is never added.
    same = sp.effective_egress(["anthropic", "openai", "openai"], [("api.openai.com", 443)], {
        "anthropic": [("api.anthropic.com", 443)],
        "openai": [("auth.openai.com", 443), ("api.openai.com", 443)]})[1]
    assert same == digest
    only = sp.effective_egress(["anthropic"], (), {"anthropic": [("api.anthropic.com", 443)],
                                                   "openai": [("api.openai.com", 443)]})[1]
    assert only == expected_egress(["anthropic"], endpoints)


@pytest.mark.parametrize("mutation", ["extra-endpoint", "changed-port", "remapped"])
def test_an_egress_mapping_mutation_changes_the_digest(env, mutation):
    baseline, _raw, _code = reserve(env.lifecycle(), "base")
    providers = json.loads((env.config / "agent-toolkit.json").read_text())["providers"]
    if mutation == "extra-endpoint":
        providers["anthropic"]["endpoints"].append({"host": "evil.example", "port": 443})
    elif mutation == "changed-port":
        providers["anthropic"]["endpoints"][0]["port"] = 8443
    else:
        providers["anthropic"]["endpoints"] = OPENAI
    env.toolkit(providers=providers)
    changed, _raw, _code = reserve(env.lifecycle(), "changed")
    assert changed.reservation.egress_sha256 != baseline.reservation.egress_sha256
    assert changed.reservation.config_sha256 != baseline.reservation.config_sha256


# -- caps readiness (P-S1, coordinator ruling 1) --------------------------------------------

def test_an_unreadable_caps_record_refuses_every_reservation_with_zero_effects(env):
    env.caps_error = True
    for client, workload in (("agent-toolkit", "pi-runner"), ("agent-harness", "leg"),
                             ("agent-harness", "qualification")):
        response, _raw, code = reserve(env.lifecycle(client), f"req-{workload}", workload=workload)
        assert code == 10 and response.code == "sandbox_placement_capability_unmet"
        assert trail(response) == [("preflight", "refused", "sandbox_placement_capability_unmet")]
    assert env.counts["observe"] == 0 and env.coordinator.calls == []
    assert env.leases() == [] and env.leases("agent-harness") == [] and env.slots() == []
    assert env.bridge.opened == []


def test_release_and_reap_keep_working_while_caps_are_unreadable(env):
    held, _raw, _code = reserve(env.lifecycle(), "held")
    env.caps_error = True
    lifecycle = env.lifecycle()
    response, code = release(lifecycle, held.reservation.to_json())
    assert code == 0 and response.state == "released"
    response, code = reap(lifecycle)
    assert code == 0 and response.state == "complete"
    version = lifecycle.version_response()
    assert lifecycle.config().seat_caps_sha256 == sha256(b"seat_resource_caps_unavailable").hexdigest()
    assert contract.exit_class(version) == 0


def test_a_readiness_code_refuses_local_only(env):
    env.readiness = seat_resource_caps.CODE
    response, _raw, code = reserve(env.lifecycle(), "remote")
    assert code == 0 and response.reservation.target.name == "ai"
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    response, _raw, code = reserve(env.lifecycle(), "local")
    assert code == 10 and trail(response) == [("local", "refused", "sandbox_placement_capability_unmet")]
    assert env.counts["observe"] == 0 and env.slots() == []


def test_config_sha256_binds_thresholds_providers_caps_and_launch(env):
    lifecycle = env.lifecycle()
    base = lifecycle.config().config_sha256
    env.write("host.json", {"schema": "placement.host-config.v1",
                            "local_headroom": {"load_per_cpu_percent_maximum_exclusive": 50}})
    thresholds = lifecycle.config().config_sha256
    assert thresholds != base
    assert lifecycle.version_response().local_headroom.load_per_cpu_percent_maximum_exclusive == 50
    env.toolkit(launch={"template_registry": {"path": "x", "sha256": "d" * 64}})
    launched = lifecycle.config().config_sha256
    assert launched not in (base, thresholds)
    env.toolkit(launch={"template_registry": {"path": "x", "sha256": "e" * 64}})
    assert lifecycle.config().config_sha256 != launched
    caps = lifecycle.config().config_sha256
    other = replace(seat_resource_caps.DEFAULT_CAPS, pids_max=seat_resource_caps.DEFAULT_CAPS.pids_max + 1)
    assert env.lifecycle(caps_loader=lambda: other).config().config_sha256 != caps
    env.caps_error = True
    assert lifecycle.config().config_sha256 != caps


@pytest.mark.parametrize("document", [
    {"schema": "placement.client-config.v1", "client": "agent-toolkit", "unknown": 1},
    {"schema": "placement.client-config.v1", "client": "agent-harness"},
    {"schema": "placement.client-config.v1", "client": "agent-toolkit", "launch": []},
    {"schema": "placement.client-config.v1", "client": "agent-toolkit", "launch": None},
    {"schema": "placement.client-config.v1", "client": "agent-toolkit",
     "providers": {"anthropic": {"endpoints": [{"host": "https://x", "port": 443}],
                                 "workloads": ["pi-runner"], "policy_vectors": ["minimal-without-app"]}}},
    {"schema": "placement.client-config.v1", "client": "agent-toolkit",
     "targets": [{"name": "local", "kind": "local", "rank": 0, "transport_id": "local"},
                 {"name": "ai", "kind": "openshell", "rank": 1, "transport_id": "ai",
                  "root": "openshell://ai/p"}]},
])
def test_an_invalid_configuration_is_an_internal_failure(env, document):
    env.write("agent-toolkit.json", document)
    with pytest.raises(sp.LifecycleError) as caught:
        reserve(env.lifecycle())
    assert caught.value.code == "placement_config_invalid"


def test_a_group_writable_configuration_is_refused(env):
    os.chmod(env.config / "agent-toolkit.json", 0o620)
    with pytest.raises(sp.LifecycleError):
        env.lifecycle().config()


# -- headroom ------------------------------------------------------------------------------

def _reading(**changes):
    values = dict(memory_available_bytes=8 << 30, load_per_cpu_percent=10.0, live_sandboxes=0,
                  observed_monotonic=sp._monotonic(), memory_total_bytes=16 << 30,
                  io_full_avg10=0.0, memory_some_avg10=0.0)
    values.update(changes)
    return sp.LocalHeadroom(**values)


DEFAULTS = contract.LocalHeadroomConfig.from_json(sandbox_policy.placement_headroom_defaults())


@pytest.mark.parametrize("changes,admits", [
    ({}, True),
    ({"memory_available_bytes": 4 << 30}, True),                       # floor inclusive
    ({"memory_available_bytes": (4 << 30) - 1}, False),
    ({"memory_total_bytes": 100 << 30, "memory_available_bytes": math.ceil((100 << 30) * 0.1)}, True),
    ({"memory_total_bytes": 100 << 30, "memory_available_bytes": math.ceil((100 << 30) * 0.1) - 1}, False),
    ({"load_per_cpu_percent": 69.999}, True),
    ({"load_per_cpu_percent": 70.0}, False),                           # exclusive
    ({"io_full_avg10": 9.99}, True),
    ({"io_full_avg10": 10.0}, False),
    ({"memory_some_avg10": 10.0}, False),
    ({"live_sandboxes": 3}, True),
    ({"live_sandboxes": 4}, False),
    ({"io_full_avg10": None}, False),                                  # missing PSI
    ({"memory_some_avg10": float("nan")}, False),                      # malformed PSI
    ({"memory_total_bytes": None}, False),                             # unknown dimension
    ({"load_per_cpu_percent": None}, False),
    ({"observed_monotonic": sp._monotonic() - 6}, False),              # stale
])
def test_every_default_threshold_boundary(changes, admits):
    assert _reading(**changes).admits(DEFAULTS) is admits


def test_the_defaults_are_the_published_protocol_defaults():
    document = json.loads(contract.schema_bytes())["x-local-headroom-defaults"]
    assert DEFAULTS.to_json() == {key: document[key] for key in DEFAULTS.to_json()}


def test_psi_parsing_is_fail_closed(tmp_path, monkeypatch):
    io, memory = tmp_path / "io", tmp_path / "memory"
    monkeypatch.setattr(sandbox_policy, "_PRESSURE_IO", io)
    monkeypatch.setattr(sandbox_policy, "_PRESSURE_MEMORY", memory)
    assert sandbox_policy.observe_local_pressure()["io_full_avg10"] is None
    io.write_text("some avg10=1.00 avg60=0 avg300=0 total=1\nfull avg10=2.50 avg60=0 avg300=0 total=1\n")
    memory.write_text("some avg10=bogus avg60=0\n")
    observed = sandbox_policy.observe_local_pressure()
    assert observed["io_full_avg10"] == 2.5 and observed["memory_some_avg10"] is None
    memory.write_text("full avg10=1.0\n")
    assert sandbox_policy.observe_local_pressure()["memory_some_avg10"] is None


def test_an_overridden_threshold_is_the_one_applied(env):
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    env.reading["load_per_cpu_percent"] = 60.0
    response, _raw, code = reserve(env.lifecycle(), "under-default")
    assert code == 0
    env.write("host.json", {"schema": "placement.host-config.v1",
                            "local_headroom": {"load_per_cpu_percent_maximum_exclusive": 60}})
    response, _raw, code = reserve(env.lifecycle(), "at-override")
    assert code == 10 and trail(response) == [("local", "at_capacity", "sandbox_placement_at_capacity")]


# -- idempotency, lost replies and restart --------------------------------------------------

def test_a_lost_reply_is_answered_byte_for_byte_after_restart(env):
    _first, raw, _code = reserve(env.lifecycle())
    calls = list(env.coordinator.calls)
    again = reserve(env.lifecycle())[1]
    assert again == raw and env.coordinator.calls == calls


def test_the_same_request_id_with_another_body_refuses_and_creates_nothing(env):
    reserve(env.lifecycle())
    leases, calls = env.leases(), list(env.coordinator.calls)
    response, _raw, code = reserve(env.lifecycle(), providers=("openai",))
    assert code == 10 and response.code == "sandbox_placement_refused" and response.reservation is None
    assert env.leases() == leases and env.coordinator.calls == calls


def test_a_remote_reservation_survives_restart_with_its_lease_held(env):
    response, _raw, _code = reserve(env.lifecycle())
    lease_id = response.reservation.lease_id
    env.clock.now += 60
    restarted = env.lifecycle()
    assert reap(restarted)[0].inventory.examined == 0          # not eligible: alive
    assert lease_id in env.coordinator.held and len(env.leases()) == 1
    released, code = release(restarted, response.reservation.to_json())
    assert code == 0 and released.state == "released"
    assert lease_id not in env.coordinator.held and env.leases() == []
    assert env.bridge.closed == [response.reservation.reservation_id]


def test_the_reserve_budget_bounds_the_walk(env):
    gate = threading.Event()
    env.coordinator.behave["admit"] = lambda request, bound: gate.wait(5)
    env.coordinator.behave["kill"] = lambda lease_id, bound: (_ for _ in ()).throw(OSError())
    try:
        response, _raw, code = reserve(env.lifecycle(), deadline_ms=200)
    finally:
        gate.set()
    assert code == 20 and response.outcome == "timeout" and response.reservation is None


# -- errata-1 replay R1-R3 -------------------------------------------------------------------

def _lose_the_create_reply(env):
    """The coordinator holds the slot but the reply is lost, and the kill goes unanswered."""
    def admit(request, bound):
        env.coordinator.held[request.lease_id] = request.owner_id
        raise sp.PlacementUnavailable(TIMEOUT, uncertain=True)
    env.coordinator.behave["admit"] = admit
    env.coordinator.behave["kill"] = lambda lease_id, bound: (_ for _ in ()).throw(OSError())
    response, raw, code = reserve(env.lifecycle())
    assert code == 20 and response.outcome == "timeout" and response.reservation is None
    env.coordinator.behave.clear()
    return response


def _effects(env):
    return (list(env.coordinator.calls), env.leases(), env.reservations(), list(env.bridge.opened),
            env.slots())


def test_r1_an_indeterminate_replay_journals_nothing(env):
    _lose_the_create_reply(env)
    before = _effects(env)
    for step in range(3):
        env.clock.now += 10
        response, _raw, code = reserve(env.lifecycle())
        assert (code, response.outcome, response.code, response.reservation) == (20, "timeout", TIMEOUT, None)
        assert env.counts["reconcile"] == step + 1
        assert _effects(env) == before


@pytest.mark.parametrize("verdict,code,outcome", [("held_ready", 0, "admitted"),
                                                  ("nothing_held", 10, "unreachable")])
def test_r2_the_reconciling_replay_settles_and_later_replays_repeat_it(env, monkeypatch, verdict, code,
                                                                       outcome):
    if verdict == "held_ready":
        # A complete, durable admission whose settlement was interrupted.
        commit = _interrupt_reserve(env, monkeypatch, "after-publish")
    else:
        _lose_the_create_reply(env)
    env.verdict = verdict
    calls, opened = list(env.coordinator.calls), list(env.bridge.opened)
    response, raw, exit_code = reserve(env.lifecycle())
    assert exit_code == code and response.outcome == outcome
    if verdict == "nothing_held":
        assert response.code == TIMEOUT
    else:
        assert response.reservation.to_json() == commit["reservation"]
    # The settling replay itself made no exposure, bridge or create call.
    assert env.coordinator.calls == calls and env.bridge.opened == opened
    reconciled = env.counts["reconcile"]
    for _ in range(2):
        again = reserve(env.lifecycle())
        assert again[1] == raw and again[2] == code
    assert env.counts["reconcile"] == reconciled
    assert env.coordinator.calls == calls and env.bridge.opened == opened


@pytest.mark.parametrize("case", ["at-bound", "past-bound", "before-start", "unreadable-start"])
def test_r3_the_settle_bound_settles_terminally_without_reconciling(env, case):
    _lose_the_create_reply(env)
    attempt = env.state / "agent-toolkit" / "attempts" / "req-1.json"
    record = json.loads(attempt.read_text())
    bound = record["started_at"] + (record["deadline_ms"] + sp.REPLAY_SETTLE_ALLOWANCE_MS) / 1000
    if case == "at-bound":
        env.clock.now = bound
    elif case == "past-bound":
        env.clock.now = bound + 1
    elif case == "before-start":
        env.clock.now = record["started_at"] - 1
    else:
        record["started_at"] = "garbled"
        attempt.write_text(json.dumps(record))
        env.clock.now = NOW + 1
    calls = list(env.coordinator.calls)
    response, raw, code = reserve(env.lifecycle())
    assert (code, response.outcome, response.code, response.reservation) == (20, "timeout", END, None)
    assert env.counts["reconcile"] == 0
    assert json.loads(attempt.read_text())["barrier"] == "armed"
    # The uncertain effect became a cleanup entry; reap cleans it and returns only its result.
    reaped, _code = reap(env.lifecycle())
    assert reaped.inventory.examined == 1 and reaped.inventory.destroyed == 1
    assert reserve(env.lifecycle())[1] == raw
    assert [c for c in env.coordinator.calls[len(calls):] if c == "admit"] == []
    # An independent request_id is never blocked by this walk's barrier.
    independent, _raw, independent_code = reserve(env.lifecycle(), "req-2")
    assert independent_code == 0 and independent.outcome == "admitted"


@pytest.mark.parametrize("entry", ["release", "reap", "startup"])
def test_r3_release_reap_and_startup_settle_at_the_bound(env, entry):
    _lose_the_create_reply(env)
    env.clock.now = NOW + 10_000
    lifecycle = env.lifecycle()
    if entry == "release":
        assert release(lifecycle, _any_reservation())[0].state == "unknown_reservation"
    elif entry == "reap":
        reap(lifecycle)
    else:
        lifecycle._startup()
    record = json.loads((env.state / "agent-toolkit" / "attempts" / "req-1.json").read_text())
    assert record["settled"] is True and json.loads(record["response"])["code"] == END
    assert env.counts["reconcile"] == 0


def _any_reservation():
    return {"schema": "placement.reservation.v1", "reservation_id": "rsv-unknown", "workload": "pi-runner",
            "target": {"name": "local", "kind": "local", "rank": 1}, "transport_id": "local",
            "image_digest": DIGEST, "policy_vector": "minimal-without-app", "policy_digest": DIGEST,
            "providers": ["anthropic"], "egress_sha256": DIGEST, "client": "agent-toolkit",
            "inventory": "agent-toolkit", "rank_policy": "agent_executor", "lease_id": None,
            "expires_at": None, "config_sha256": "a" * 64, "bridge": None}


# -- durable admission: interruption between the admission's journal steps -----------------

class Interrupted(BaseException):
    """A process interruption injected at one step of an admission."""


def _interrupt_reserve(env, monkeypatch, point, *, lifecycle=None, **reserve_kwargs):
    """Run one reserve that is interrupted at ``point``; return the attempt's commit."""
    lifecycle = lifecycle if lifecycle is not None else env.lifecycle()
    if point == "after-bridge":
        bridge = lifecycle.bridge
        original_open = bridge.open

        def opened_then_interrupted(*args, **kwargs):
            original_open(*args, **kwargs)
            raise Interrupted(point)
        monkeypatch.setattr(bridge, "open", opened_then_interrupted)
    elif point == "before-publish":
        def interrupted(self, commit, request_id):
            raise Interrupted(point)
        monkeypatch.setattr(sp.PlacementLifecycle, "_publish_reservation", interrupted)
    elif point == "after-publish":
        original_settle = sp.PlacementLifecycle._settle

        def settle(self, record, response):
            if getattr(response, "outcome", None) == "admitted":
                raise Interrupted(point)
            return original_settle(self, record, response)
        monkeypatch.setattr(sp.PlacementLifecycle, "_settle", settle)
    with pytest.raises(Interrupted):
        reserve(lifecycle, **reserve_kwargs)
    monkeypatch.undo()
    record = json.loads((env.state / lifecycle.client / "attempts" / "req-1.json").read_text())
    assert record["settled"] is False and record["pending"] == []
    return record["commit"]


def _attempt(env, client="agent-toolkit"):
    return json.loads((env.state / client / "attempts" / "req-1.json").read_text())


def _bound_of(record):
    return record["started_at"] + (record["deadline_ms"] + sp.REPLAY_SETTLE_ALLOWANCE_MS) / 1000


def _cleanup_entries(env, client="agent-toolkit"):
    return sorted((env.state / client / "cleanup").glob("*.json"))


@pytest.mark.parametrize("point", ["after-bridge", "before-publish", "after-publish"])
def test_an_interrupted_admission_is_recovered_from_its_commit_before_the_bound(env, monkeypatch, point):
    commit = _interrupt_reserve(env, monkeypatch, point)
    assert commit["complete"] is (point != "after-bridge")
    env.verdict = "held_ready"
    calls, opened = list(env.coordinator.calls), list(env.bridge.opened)
    env.clock.now += 30
    response, raw, code = reserve(env.lifecycle())
    # Recovery allocates nothing: no target, lease, exposure or bridge call.
    assert env.coordinator.calls == calls and env.bridge.opened == opened
    if point == "after-bridge":
        # The bridge handle never reached the journal: not a complete reservation.
        assert (code, response.outcome, response.reservation) == (20, "timeout", None)
        assert env.reservations() == [] and _attempt(env)["settled"] is False
        return
    assert code == 0 and response.reservation.to_json() == commit["reservation"]
    assert response.reservation.expires_at == commit["reservation"]["expires_at"]
    [active] = env.reservations()
    stored = json.loads(active.read_text())
    assert stored["reservation"] == commit["reservation"] and stored["effect"] == commit["effect"]
    assert reserve(env.lifecycle())[1] == raw
    assert env.coordinator.calls == calls and env.bridge.opened == opened


@pytest.mark.parametrize("point", ["after-bridge", "before-publish", "after-publish"])
def test_an_interrupted_admission_at_the_bound_has_one_cleanup_owner(env, monkeypatch, point):
    commit = _interrupt_reserve(env, monkeypatch, point)
    env.clock.now = _bound_of(_attempt(env))
    env.lifecycle()._startup()
    record = _attempt(env)
    assert record["settled"] is True and json.loads(record["response"])["code"] == END
    [entry] = _cleanup_entries(env)
    assert json.loads(entry.read_text())["effect"] == commit["effect"]
    assert env.reservations() == []                      # no active record advertises it
    reaped, code = reap(env.lifecycle())
    assert (code, reaped.inventory.destroyed, reaped.inventory.pending) == (0, 1, 0)
    assert commit["effect"]["lease_id"] not in env.coordinator.held
    if point == "after-bridge":
        assert env.bridge.reclaimed == [commit["effect"]["bridge_directory"]]
    else:
        assert env.bridge.closed == [commit["reservation"]["reservation_id"]]
    # The consumed owner is kept as a completion record until the attempt journals it.
    [entry] = _cleanup_entries(env)
    assert json.loads(entry.read_text())["state"] == "destroyed"
    env.lifecycle()._startup()
    assert env.reservations() == [] and _cleanup_entries(env) == []
    assert _attempt(env)["transfer"]["entries"][0]["state"] == "completed"


@pytest.mark.parametrize("restart", ["before-bound", "at-bound"])
def test_an_interrupted_local_admission_keeps_its_slot_binding_and_expiry(env, monkeypatch, restart):
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    commit = _interrupt_reserve(env, monkeypatch, "after-publish")
    assert len(env.slots()) == 1
    if restart == "before-bound":
        env.clock.now += 60
        observed = env.counts["observe"]
        recovered, _raw, code = reserve(env.lifecycle(reconcile=None))   # the default check
        assert code == 0 and recovered.reservation.to_json() == commit["reservation"]
        assert len(env.slots()) == 1 and env.counts["observe"] == observed
        return
    env.clock.now = _bound_of(_attempt(env))
    reaped, code = reap(env.lifecycle())
    assert (code, reaped.inventory.destroyed) == (0, 1)
    env.lifecycle()._startup()
    assert env.slots() == [] and env.reservations() == [] and _cleanup_entries(env) == []


def test_a_reservation_reaped_before_settlement_is_not_republished(env, monkeypatch):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _attempt(env)["started_at"] + 10       # expired, still before the settle bound
    assert reap(env.lifecycle())[0].inventory.destroyed == 1
    assert env.reservations() == []
    env.verdict = "held_ready"
    response, _raw, code = reserve(env.lifecycle(), ttl_s=1)
    assert code == 10 and response.outcome == "unreachable" and env.reservations() == []
    assert (env.state / "agent-toolkit" / "tombstones" / f"{rid}.json").exists()


# -- the hand-over to cleanup: one durable, restartable owner ---------------------------------

def _hold(path):
    """Hold an flock on ``path`` from a separate descriptor, as another process would."""
    import fcntl

    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _owners(env, rid):
    """The logical owners of one committed effect. Its cleanup entry, once written, is the
    owner (an active record beside it is stale and is never consumed on its own); a
    destroyed entry owns nothing and no active record may still advertise the effect.
    Cleanup entries are only ever named by the effect's stable key."""
    active = any(p.stem == rid for p in env.reservations())
    states = []
    for entry in _cleanup_entries(env):
        assert entry.stem == rid, "a cleanup entry under any other key duplicates the owner"
        states.append(json.loads(entry.read_text())["state"])
    assert len(states) <= 1
    if states == ["destroyed"]:
        assert not active, "an active record still advertises a removed effect"
        return 0
    return 1 if (states == ["owned"] or active) else 0


def _interrupt_after(monkeypatch, name, *, when=lambda *a, **k: True):
    original = getattr(sp.PlacementLifecycle, name)
    fired = []

    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if not fired and when(*args, **kwargs):
            fired.append(True)
            raise Interrupted(name)
        return result
    monkeypatch.setattr(sp.PlacementLifecycle, name, wrapped)


HANDOVER_STEPS = ["after-plan", "after-owner-write", "after-active-removal", "after-transfer-journal",
                  "before-terminal-settlement"]


def _arm_handover_interruption(monkeypatch, step):
    if step == "after-plan":
        _interrupt_after(monkeypatch, "_plan_transfer")
    elif step == "after-owner-write":
        _interrupt_after(monkeypatch, "_write_cleanup_owner")
    elif step == "after-active-removal":
        _interrupt_after(monkeypatch, "_retire_active")
    elif step == "after-transfer-journal":
        _interrupt_after(monkeypatch, "_resume_transfer")
    else:
        original = sp.PlacementLifecycle._settle

        def settle(self, record, response):
            if getattr(response, "code", None) == END:
                raise Interrupted(step)
            return original(self, record, response)
        monkeypatch.setattr(sp.PlacementLifecycle, "_settle", settle)


@pytest.mark.parametrize("step", HANDOVER_STEPS)
def test_an_interrupted_handover_keeps_one_owner_across_reap_and_restarts(env, monkeypatch, step):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    _arm_handover_interruption(monkeypatch, step)
    with pytest.raises(Interrupted):
        env.lifecycle()._startup()
    monkeypatch.undo()
    assert _owners(env, rid) <= 1
    reap(env.lifecycle())                                  # a reap interleaved before the restarts
    assert _owners(env, rid) <= 1
    for _ in range(2):                                     # restart twice
        env.lifecycle()._startup()
        assert _owners(env, rid) <= 1
    reaped, _code = reap(env.lifecycle())
    env.lifecycle()._startup()
    assert _owners(env, rid) == 0 and env.reservations() == [] and _cleanup_entries(env) == []
    assert env.bridge.closed == [rid]                      # cleaned exactly once
    assert commit["effect"]["lease_id"] not in env.coordinator.held
    record = _attempt(env)
    assert record["settled"] and json.loads(record["response"])["code"] == END
    assert [entry["state"] for entry in record["transfer"]["entries"]] == ["completed"]
    reap(env.lifecycle())
    env.lifecycle()._startup()
    assert _cleanup_entries(env) == [] and env.bridge.closed == [rid]   # never resurrected


def test_a_consumer_finishes_a_planned_handover_while_the_attempt_is_still_held(env, monkeypatch):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    _arm_handover_interruption(monkeypatch, "after-plan")
    with pytest.raises(Interrupted):
        env.lifecycle()._startup()
    monkeypatch.undo()
    fd = _hold(env.state / "agent-toolkit" / "attempts" / "req-1.lock")   # the attempt is in progress
    try:
        reaped, code = reap(env.lifecycle())
        # The expired active record is planned for hand-over: it is not cleaned on its own.
        assert (code, reaped.inventory.destroyed) == (0, 1)
        assert env.reservations() == [] and env.bridge.closed == [rid]
        [entry] = _cleanup_entries(env)
        assert entry.stem == rid and json.loads(entry.read_text())["state"] == "destroyed"
    finally:
        os.close(fd)
    env.lifecycle()._startup()
    assert _cleanup_entries(env) == [] and env.bridge.closed == [rid]
    assert _attempt(env)["transfer"]["entries"][0]["state"] == "completed"


def test_replay_rechecks_under_the_reservation_lock_after_a_concurrent_reap(env, monkeypatch):
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _attempt(env)["started_at"] + 10       # expired, before the settle bound
    env.verdict = "held_ready"
    original = sp._FileLock.__enter__
    fired = []

    def gated(self):
        if self.path.name == f"{rid}.lock" and not fired:
            fired.append(True)
            assert reap(env.lifecycle())[0].inventory.destroyed == 1   # tombstones it first
        return original(self)
    monkeypatch.setattr(sp._FileLock, "__enter__", gated)
    response, _raw, code = reserve(env.lifecycle(), ttl_s=1)
    monkeypatch.undo()
    assert fired and (code, response.outcome) == (10, "unreachable")
    assert env.reservations() == []                        # never republished
    assert (env.state / "agent-toolkit" / "tombstones" / f"{rid}.json").exists()
    assert env.bridge.closed == [rid]


# -- deadlines reach start-up, hand-over, recovery and slot locking ----------------------------

@pytest.mark.parametrize("operation", ["reserve", "release", "reap"])
def test_a_held_lock_of_an_expired_commit_never_blocks_a_public_operation(env, monkeypatch, operation):
    other, _raw, _code = reserve(env.lifecycle(), "other")
    commit = _interrupt_reserve(env, monkeypatch, "after-publish", ttl_s=1)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now = _bound_of(_attempt(env))
    fd = _hold(env.state / "agent-toolkit" / "reservations" / f"{rid}.lock")
    try:
        started = time.monotonic()
        if operation == "reserve":
            response, _raw, code = reserve(env.lifecycle(), "unrelated", deadline_ms=400)
            assert code == 0 and response.outcome == "admitted"
        elif operation == "release":
            response, code = release(env.lifecycle(), other.reservation.to_json(), deadline_ms=400)
            assert code == 0 and response.state == "released"
        else:
            response, code = reap(env.lifecycle(), deadline_ms=400)
            assert code == 20 and response.inventory.pending >= 1
        assert time.monotonic() - started < 0.4 + 0.4
        # Ownership is kept: the hand-over is planned, the active record is untouched.
        record = _attempt(env)
        assert record["settled"] and record["transfer"]["entries"][0]["state"] == "planned"
        assert (env.state / "agent-toolkit" / "reservations" / f"{rid}.json").exists()
        assert env.bridge.closed.count(rid) == 0
    finally:
        os.close(fd)
    reap(env.lifecycle())
    env.lifecycle()._startup()
    assert _owners(env, rid) == 0 and env.bridge.closed.count(rid) == 1


def _replay_request(cancelled=None, deadline_ms=300):
    request = contract.decode_request("reserve", json.dumps(reserve_body(deadline_ms=deadline_ms)).encode())
    return request, (cancelled or threading.Event())


@pytest.mark.parametrize("case", ["lock-held", "slow-reconciliation", "cancelled", "bound-reached"])
def test_a_replay_that_runs_out_of_time_or_is_cancelled_publishes_nothing(env, monkeypatch, case):
    commit = _interrupt_reserve(env, monkeypatch, "before-publish", deadline_ms=300)
    rid = commit["reservation"]["reservation_id"]
    env.clock.now += 5
    request, cancelled = _replay_request()
    fd = None

    def reconcile(record, timeout_s):
        if case == "slow-reconciliation":
            time.sleep(timeout_s + 0.1)
        elif case == "cancelled":
            cancelled.set()
        elif case == "bound-reached":
            env.clock.now = _bound_of(record)
        return "held_ready"
    if case == "lock-held":
        fd = _hold(env.state / "agent-toolkit" / "reservations" / f"{rid}.lock")
    try:
        started = time.monotonic()
        response = env.lifecycle(reconcile=reconcile).reserve(request, cancelled=cancelled)
        assert time.monotonic() - started < 0.3 + 0.4
    finally:
        if fd is not None:
            os.close(fd)
    assert response.outcome == "timeout" and response.reservation is None
    assert env.reservations() == []                        # no admitted publication
    record = _attempt(env)
    if case == "bound-reached":
        assert response.code == END and record["settled"]
    else:
        assert response.code == TIMEOUT and not record["settled"] and record["commit"]["complete"]


def test_file_lock_checks_budget_after_retry_sleep(tmp_path, monkeypatch):
    import fcntl

    now = [0.0]
    calls = []
    monkeypatch.setattr(sp, "_monotonic", lambda: now[0])

    def flock(_fd, flags):
        calls.append(flags)
        assert flags & fcntl.LOCK_NB
        if len(calls) == 1:
            raise BlockingIOError()

    def sleep(_seconds):
        now[0] = 1.0

    monkeypatch.setattr(fcntl, "flock", flock)
    monkeypatch.setattr(sp.time, "sleep", sleep)
    lock = sp._FileLock(tmp_path / "budget.lock", blocking=True, deadline=sp._Deadline.after(1.0))
    with lock as held:
        assert not held
    assert len(calls) == 1
    assert lock.fd is None


def test_a_contended_slot_lock_is_bounded_and_never_mutates_the_attempt_late(env):
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    env.state.mkdir(parents=True, exist_ok=True)
    fd = _hold(env.state / "local-slots.lock")
    try:
        started = time.monotonic()
        response, _raw, code = reserve(env.lifecycle(), deadline_ms=400)
        assert time.monotonic() - started < 0.4 + 0.6
        assert response.reservation is None and code in (10, 20)
    finally:
        os.close(fd)
    time.sleep(0.6)                                        # a timed-out worker never writes later
    assert env.slots() == []
    assert not [effect for effect in _attempt(env).get("pending", []) if effect["kind"] == "local"]


# -- start-up reads each attempt again under its lock ------------------------------------------

def _gate_attempt_lock(monkeypatch, hook):
    original = sp._FileLock.__enter__
    fired = []

    def gated(self):
        if self.path.name == "req-1.lock" and not fired:
            fired.append(True)
            hook()
        return original(self)
    monkeypatch.setattr(sp._FileLock, "__enter__", gated)


def test_startup_never_overwrites_an_attempt_settled_after_enumeration(env, monkeypatch):
    _lose_the_create_reply(env)
    early = env.lifecycle(clock=lambda: NOW + 10)
    env.verdict = "nothing_held"
    env.clock.now = _bound_of(_attempt(env)) + 1
    _gate_attempt_lock(monkeypatch, lambda: reserve(early))
    env.lifecycle()._startup()
    record = _attempt(env)
    assert json.loads(record["response"])["outcome"] == "unreachable"
    assert len(_cleanup_entries(env)) == 1


def test_two_startups_settle_one_expired_attempt_once(env, monkeypatch):
    _lose_the_create_reply(env)
    env.clock.now = _bound_of(_attempt(env)) + 1
    other = env.lifecycle()
    _gate_attempt_lock(monkeypatch, other._startup)
    env.lifecycle()._startup()
    record = _attempt(env)
    first = record["response"]
    assert json.loads(first)["code"] == END and len(_cleanup_entries(env)) == 1
    env.lifecycle()._startup()
    assert _attempt(env)["response"] == first and len(_cleanup_entries(env)) == 1


# -- replay never builds what admission did not durably finish ---------------------------------

def test_a_held_lease_without_a_complete_commit_is_never_made_ready_on_replay(env):
    _lose_the_create_reply(env)
    env.verdict = "held_ready"
    before = _effects(env)
    for _ in range(2):
        response, _raw, code = reserve(env.lifecycle())
        assert (code, response.outcome, response.reservation) == (20, "timeout", None)
    assert _effects(env) == before and "forward_exposure" not in env.coordinator.calls


# -- one deadline per operation ----------------------------------------------------------------

def test_a_slow_exposure_never_turns_into_a_late_admission(env):
    env.coordinator.behave["forward_exposure"] = lambda lease_id, bound: time.sleep(3)
    started = time.monotonic()
    response, _raw, code = reserve(env.lifecycle(), deadline_ms=600)
    assert time.monotonic() - started < 2.0
    assert (code, response.outcome, response.reservation) == (20, "timeout", None)
    assert env.reservations() == []
    record = _attempt(env)
    assert record["commit"]["complete"] is False and record["commit"]["effect"]["lease_id"] in env.coordinator.held


def test_a_cancel_after_admission_is_never_reported_as_admitted(env, monkeypatch):
    cancelled = threading.Event()
    original_open = env.bridge.open

    def open_then_cancel(*args, **kwargs):
        handle = original_open(*args, **kwargs)
        cancelled.set()
        return handle
    monkeypatch.setattr(env.bridge, "open", open_then_cancel)
    request = contract.decode_request("reserve", json.dumps(reserve_body()).encode())
    response = env.lifecycle().reserve(request, cancelled=cancelled)
    assert response.outcome == "timeout" and response.reservation is None
    assert env.reservations() == [] and _attempt(env)["commit"]["complete"] is True


def test_a_contended_release_lock_is_bounded_by_the_deadline(env):
    import fcntl

    response, _raw, _code = reserve(env.lifecycle())
    rid = response.reservation.reservation_id
    fd = os.open(env.state / "agent-toolkit" / "reservations" / f"{rid}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        pending, code = release(env.lifecycle(), response.reservation.to_json(), deadline_ms=300)
        assert time.monotonic() - started < 1.5
        assert (code, pending.state) == (20, "cleanup_pending")
        assert len(env.reservations()) == 1 and response.reservation.lease_id in env.coordinator.held
    finally:
        os.close(fd)
    assert release(env.lifecycle(), response.reservation.to_json(), "rel-2")[0].state == "released"


# -- release ---------------------------------------------------------------------------------

def test_release_echo_mismatch_is_rejected_and_the_lease_stays_held(env):
    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    for field, value in (("transport_id", "elsewhere"), ("egress_sha256", "sha256:" + "f" * 64),
                         ("providers", ["openai"]), ("expires_at", "2030-01-01T00:00:00Z")):
        rejected, code = release(env.lifecycle(), {**stored, field: value}, f"rel-{field}")
        assert code == 10 and rejected.state == "rejected" and rejected.code == "sandbox_placement_refused"
        assert rejected.flags.reserved and not rejected.flags.cleanup_pending
        assert rejected.flags.barrier_confirmed
    assert response.reservation.lease_id in env.coordinator.held and len(env.reservations()) == 1


@pytest.mark.parametrize("reservation_id", ["rsv-unknown", "x" * 256, "rsv-" + "0" * 32])
def test_an_id_this_lifecycle_never_issued_is_unknown(env, reservation_id):
    response, code = release(env.lifecycle(), {**_any_reservation(), "reservation_id": reservation_id})
    assert code == 10 and response.state == "unknown_reservation"
    assert list((env.state / "agent-toolkit" / "reservations").iterdir()) == []


def test_a_cross_client_release_is_rejected_without_lookup(env):
    response, _raw, _code = reserve(env.lifecycle())
    rejected, code = release(env.lifecycle("agent-harness"), response.reservation.to_json())
    assert code == 10 and rejected.state == "rejected"
    assert response.reservation.lease_id in env.coordinator.held


def test_repeat_release_returns_released_then_unknown_after_tombstone_expiry(env):
    response, _raw, _code = reserve(env.lifecycle())
    stored = response.reservation.to_json()
    assert release(env.lifecycle(), stored)[0].state == "released"
    again, code = release(env.lifecycle(), stored, "rel-2")
    assert code == 0 and again.state == "released"
    env.clock.now += sp.TOMBSTONE_RETENTION_S + 1
    gone, code = release(env.lifecycle(), stored, "rel-3")
    assert code == 10 and gone.state == "unknown_reservation"
    assert gone.flags.barrier_confirmed and not gone.flags.reserved


def test_an_unconfirmed_release_arms_the_barrier_for_that_reservation_only(env):
    held, _raw, _code = reserve(env.lifecycle(), "held")
    other, _raw, _code = reserve(env.lifecycle(), "other")
    env.coordinator.behave["kill"] = lambda lease_id, bound: (_ for _ in ()).throw(OSError())
    pending, code = release(env.lifecycle(), held.reservation.to_json())
    assert code == 20 and pending.state == "cleanup_pending"
    assert pending.flags.cleanup_pending and not pending.flags.barrier_confirmed
    env.coordinator.behave.clear()
    # Other reservations, of this client and the other, stay admissible and releasable.
    third, _raw, code = reserve(env.lifecycle(), "third")
    assert code == 0
    seat, _raw, code = reserve(env.lifecycle("agent-harness"), "seat", workload="qualification")
    assert code == 0
    assert release(env.lifecycle(), other.reservation.to_json(), "rel-o")[0].state == "released"
    retried, code = release(env.lifecycle(), held.reservation.to_json(), "rel-again")
    assert code == 0 and retried.state == "released" and retried.flags.barrier_confirmed


# -- caller-scoped reap ------------------------------------------------------------------------

def test_reap_examines_only_the_callers_inventory_in_created_order(env):
    toolkit, harness = env.lifecycle(), env.lifecycle("agent-harness")
    first, _raw, _code = reserve(toolkit, "t1", ttl_s=1)
    env.clock.now += 1
    second, _raw, _code = reserve(toolkit, "t2", ttl_s=1)
    seat, _raw, _code = reserve(harness, "h1", workload="leg", ttl_s=1)
    env.clock.now += 100
    killed = []
    env.coordinator.behave["kill"] = lambda lease_id, bound: killed.append(lease_id)
    result, code = reap(toolkit, max_items=1)
    assert (code, result.inventory.client, result.inventory.inventory) == (0, "agent-toolkit", "agent-toolkit")
    assert (result.inventory.examined, result.inventory.destroyed) == (1, 1)
    assert killed == [first.reservation.lease_id]
    result, _code = reap(toolkit)
    assert killed == [first.reservation.lease_id, second.reservation.lease_id]
    assert seat.reservation.lease_id in env.coordinator.held       # never touched
    assert len(env.reservations("agent-harness")) == 1


def test_an_uncertain_reap_item_stays_pending_without_a_wider_barrier(env):
    held, _raw, _code = reserve(env.lifecycle(), "held", ttl_s=1)
    env.clock.now += 100
    env.coordinator.behave["kill"] = lambda lease_id, bound: (_ for _ in ()).throw(OSError())
    result, code = reap(env.lifecycle())
    assert code == 20 and result.state == "cleanup_pending" and result.inventory.pending == 1
    assert result.inventory.code == UNCONFIRMED
    env.coordinator.behave.clear()
    assert reserve(env.lifecycle(), "fresh")[2] == 0


def test_the_inventories_and_owner_ids_are_separate(env):
    from phase_loop_runtime import placement_lease

    reserve(env.lifecycle(), "t")
    reserve(env.lifecycle("agent-harness"), "h", workload="leg")
    toolkit = placement_lease.owner_id(env.state / "agent-toolkit")
    harness = placement_lease.owner_id(env.state / "agent-harness")
    assert toolkit != harness
    assert set(env.coordinator.held.values()) == {toolkit, harness}
    assert len(env.leases()) == 1 and len(env.leases("agent-harness")) == 1


# -- the bridge and the no-fallback rule ---------------------------------------------------------

def test_a_bridge_failure_after_admission_releases_and_never_falls_back(env):
    env.bridge.fail = True
    response, _raw, code = reserve(env.lifecycle())
    assert code == 10 and response.outcome == "refused"
    assert trail(response) == [("ai", "refused", "sandbox_placement_refused")]
    assert env.coordinator.held == {} and env.slots() == []


def test_local_and_non_bridged_reservations_have_bridge_null(env):
    response, _raw, _code = reserve(env.lifecycle("agent-harness"), workload="qualification")
    assert response.reservation.bridge is None
    env.harness(seat_route={"qualification": "ai"})
    response, _raw, _code = reserve(env.lifecycle("agent-harness"), "remote-q", workload="qualification")
    assert response.reservation.target.kind == "openshell" and response.reservation.bridge is None
    assert env.bridge.opened == []


def test_shipped_defaults_reach_no_live_adapter(env, monkeypatch):
    for name in ("REMOTE_REQUIRED", "ROOT", "ADMIT_WAIT_S"):
        monkeypatch.setenv(f"PHASE_LOOP_SANDBOX_{name}", "1")
    lifecycle = env.lifecycle(backend_for=None)
    response, _raw, code = reserve(lifecycle)
    assert trail(response)[0] == ("ai", "refused", "sandbox_placement_backend_unregistered")
    assert code == 0 and response.reservation.target.name == "local"
    from phase_loop_runtime import panel_invoker

    assert panel_invoker._NONLOCAL_EXECUTION_DRIVER is False
    policies = json.loads(resources.files("phase_loop_runtime").joinpath(
        "contracts/placement/vectors/policies.json").read_text())
    assert policies["status"] == "pending_qualification"


# -- mutation controls: each named guard, removed, is caught through the production path ----

def _check_provider_guard(env):
    return reserve(env.lifecycle(), "m-p", providers=("unknown",))[2] == 10


def _check_caps_guard(env):
    env.caps_error = True
    try:
        return reserve(env.lifecycle(), "m-c")[0].code == "sandbox_placement_capability_unmet"
    finally:
        env.caps_error = False


def _check_headroom_guard(env):
    env.reading["io_full_avg10"] = None
    env.toolkit(targets=[{"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}])
    return reserve(env.lifecycle(), "m-h")[0].outcome == "at_capacity"


def _check_no_execute(env):
    reserve(env.lifecycle(), "m-x")
    return not {"commit", "execute"} & set(env.coordinator.calls)


def _check_timeout_label(env):
    return _lose_the_create_reply(env).outcome == "timeout"


def _check_od7(env):
    env.toolkit(targets=[{"name": "e2b", "kind": "e2b", "rank": 2, "transport_id": "e2b"}])
    return reserve(env.lifecycle(), "m-o")[0].trail[0].code == "sandbox_placement_provider_refused"


def _check_undeclared_egress(env):
    response = reserve(env.lifecycle(), "m-e")[0]
    return response.reservation.egress_sha256 == expected_egress(["anthropic"], {"anthropic": ANTHROPIC})


def _check_separate_inventories(env):
    reserve(env.lifecycle(), "m-i1")
    return env.lifecycle("agent-harness").inventory != env.lifecycle().inventory and len(env.leases()) == 1


def _check_at_bound(env):
    _lose_the_create_reply(env)
    record = json.loads((env.state / "agent-toolkit" / "attempts" / "req-1.json").read_text())
    env.clock.now = record["started_at"] + (record["deadline_ms"] + sp.REPLAY_SETTLE_ALLOWANCE_MS) / 1000
    return reserve(env.lifecycle())[0].code == END and env.counts["reconcile"] == 0


def _mutant(name):
    original = {
        "provider": sp.PlacementLifecycle._reserve_new,
        "caps": sp.PlacementLifecycle.caps_state,
        "headroom": sp.LocalHeadroom._admits_thresholds,
        "execute": sp._Walk._rung,
        "timeout": sp.PlacementLifecycle._unsettled,
        "od7": sp.PlacementLifecycle._plan,
        "egress": sp.effective_egress,
        "inventory": sp.PlacementLifecycle.__init__,
        "at-bound": sp.PlacementLifecycle._at_bound,
    }[name]

    if name == "provider":
        def mutated(self, request, body, *rest):
            return original(self, replace(request, providers=("anthropic",)), body, *rest)
        return "_reserve_new", mutated, sp.PlacementLifecycle
    if name == "caps":
        return "caps_state", lambda self: (True, "0" * 64), sp.PlacementLifecycle
    if name == "headroom":
        return "_admits_thresholds", lambda self, limits: True, sp.LocalHeadroom
    if name == "execute":
        def rung(self, root):
            self.reserve_only = False
            return original(self, root)
        return "_rung", rung, sp._Walk
    if name == "timeout":
        def unsettled(self, record, request, trail, code):
            return self._settle(record, self._reserve_response(request, "unreachable", TIMEOUT, trail))
        return "_unsettled", unsettled, sp.PlacementLifecycle
    if name == "od7":
        def plan(self, config, request, target, ready):
            planned = original(self, config, request, target, ready)
            if target.kind == "e2b":
                return replace(planned, refusal="sandbox_placement_driver_unavailable")
            return planned
        return "_plan", plan, sp.PlacementLifecycle
    if name == "egress":
        def egress(providers, baseline, endpoints):
            return original(providers, [*baseline, ("evil.example", 443)], endpoints)
        return "effective_egress", egress, sp
    if name == "inventory":
        def init(self, client, **kwargs):
            original(self, client, **kwargs)
            self.inventory = self.state_root / "shared"
        return "__init__", init, sp.PlacementLifecycle
    def at_bound(self, record, now):
        bound = self._settle_bound(record)
        return bound is None or now > bound
    return "_at_bound", at_bound, sp.PlacementLifecycle


MUTATION_CONTROLS = {
    "provider": _check_provider_guard, "caps": _check_caps_guard, "headroom": _check_headroom_guard,
    "execute": _check_no_execute, "timeout": _check_timeout_label, "od7": _check_od7,
    "egress": _check_undeclared_egress, "inventory": _check_separate_inventories,
    "at-bound": _check_at_bound,
}


@pytest.mark.parametrize("kind", ["intact", "killed"])
@pytest.mark.parametrize("control", sorted(MUTATION_CONTROLS))
def test_lifecycle_mutation_controls(env, monkeypatch, control, kind):
    check = MUTATION_CONTROLS[control]
    if kind == "killed":
        attribute, value, owner = _mutant(control)
        monkeypatch.setattr(owner, attribute, value)
        try:
            holds = check(env)
        except (AssertionError, sp.LifecycleError, contract.ProtocolError):
            holds = False
        assert holds is False
    else:
        assert check(env) is True
