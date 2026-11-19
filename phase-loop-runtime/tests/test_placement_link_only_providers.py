"""PLACECLI link-only placement providers: providers reached only through the link.

The operator configuration (``placement.client-config.v1``) accepts a second provider shape,
``{"reach": "link", "workloads": [...], "policy_vectors": [...]}``, with no endpoints. Such a
provider is a valid request name, is bound into ``config_sha256`` and ``Reservation.providers``,
and adds its name and no rule to the effective egress grant. The PLACECLI protocol bytes are
unchanged.

The file also covers ``sandbox_placement.openshell_route_state`` (the one implementation of
the three openshell route conditions), ``sandbox_placement.openshell_launch_refusal`` (the
launch-boundary check) and the dormant reserve-time gate.

Every case enters through a production construction site: the loader, ``PlacementLifecycle``,
``openshell_launch_refusal`` or ``placement_cli`` in a subprocess. New symbols are fetched
inside each test (``_new``), so on a tree without them a node fails alone instead of the file
failing to collect.
"""

from __future__ import annotations

import copy
from hashlib import sha256
from importlib import resources
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest
import rfc8785

from phase_loop_runtime import placement_process_contract as contract
from phase_loop_runtime import sandbox_placement as sp
from phase_loop_runtime import sandbox_policy
from test_placement_lifecycle_process import (
    ANTHROPIC, POLICY_DIGESTS, Env, expected_egress, reserve, trail,
)

# -- goldens recorded with the unchanged loader -----------------------------------------
# Recorded once from agent-harness origin/main db98d5532 (v0.7.35), before any source
# change in this PR. They are outputs of the code before the change and inputs to it: an
# endpoint-form configuration must keep these exact digests.
GOLDEN_ENDPOINT_FORM = "f1e16413b5c4d299d781531b72b4896e79cfb5d45659f20ecfcde54034a33172"
GOLDEN_PRODUCER_TOOLKIT = "143ccc3f144cf6cacc5a620821667f33c919cf1f184adf6015a0c8f5d7083fd1"
GOLDEN_PRODUCER_HARNESS = "ec5dc7ad8d04c9c4ffe7ec980e776457231b569c39751904af9bec33474ac0a5"

#: A fixed ``seat_caps_sha256`` so the witnesses do not depend on this host's caps record.
CAPS = "1" * 64
PROTOCOL_SHA256 = "130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea"
PREP_NAMES = ("baseten", "lithos", "openai", "xai")
PREP_EGRESS = "sha256:ce53c73171f7aefff66008676a16c08c85874274c47388c625d458c4212b97ca"
ROUTE_DISABLED = "sandbox_launch_route_disabled"
INPUT_MISMATCH = "sandbox_launch_input_mismatch"
INPUT_UNBOUND = "launch_input_unbound"
PROVIDER_REFUSED = "sandbox_placement_provider_refused"
DRIVER_UNAVAILABLE = "sandbox_placement_driver_unavailable"
BOTH_VECTORS = ["full-remote-pi-runner", "minimal-without-app"]


def _new(module, name):
    """A symbol this change adds; ``AttributeError`` fails only the calling node."""
    return getattr(module, name)


def _link(vectors=BOTH_VECTORS, workloads=("pi-runner",)):
    return {"reach": "link", "workloads": list(workloads), "policy_vectors": list(vectors)}


def _endpoint_provider(endpoints=ANTHROPIC, vectors=BOTH_VECTORS, workloads=("pi-runner",)):
    return {"endpoints": copy.deepcopy(endpoints), "workloads": list(workloads),
            "policy_vectors": list(vectors)}


def _toolkit_targets(names, *, local=True, e2b=False, od7=()):
    targets = [{"name": "ai", "kind": "openshell", "rank": 0, "transport_id": "ai-openshell",
                "root": "openshell://ai/placement", "probe_receipt_providers": sorted(names)}]
    if local:
        targets.append({"name": "local", "kind": "local", "rank": 1, "transport_id": "local"})
    if e2b:
        targets.append({"name": "e2b", "kind": "e2b", "rank": 2, "transport_id": "e2b",
                        "od7_providers": list(od7)})
    return targets


def _toolkit(providers, *, targets=None):
    return {"schema": "placement.client-config.v1", "client": "agent-toolkit",
            "providers": providers,
            "targets": targets if targets is not None else _toolkit_targets(providers)}


LINK_ONLY = _toolkit({name: _link() for name in PREP_NAMES})

#: W1. A nonempty endpoint-form agent-toolkit configuration: three endpoint providers keyed
#: out of order, unsorted and mixed-case endpoint lists, unsorted policy vectors, an
#: openshell and a local target written out of rank order, and a nested launch object with
#: placeholder values. The toolkit's only workload is ``pi-runner``, so its workload lists
#: are singletons; workload-order coverage is the producer's agent-harness fixture (W3).
ENDPOINT_FORM = {
    "schema": "placement.client-config.v1", "client": "agent-toolkit",
    "providers": {
        "zeta": {"endpoints": [{"host": "auth.zeta.example", "port": 443},
                               {"host": "API.Zeta.Example", "port": 8443}],
                 "workloads": ["pi-runner"],
                 "policy_vectors": ["minimal-without-app", "full-remote-pi-runner"]},
        "alpha": {"endpoints": [{"host": "b.alpha.example", "port": 443},
                                {"host": "a.alpha.example", "port": 443},
                                {"host": "a.alpha.example", "port": 80}],
                  "workloads": ["pi-runner"], "policy_vectors": ["full-remote-pi-runner"]},
        "mid": {"endpoints": [{"host": "api.mid.example", "port": 443}],
                "workloads": ["pi-runner"], "policy_vectors": ["minimal-without-app"]},
    },
    "targets": [
        {"name": "local", "kind": "local", "rank": 1, "transport_id": "local"},
        {"name": "ai", "kind": "openshell", "rank": 0, "transport_id": "ai-openshell",
         "root": "openshell://ai/placement", "probe_receipt_providers": ["zeta", "alpha"]},
    ],
    "launch": {
        "schema": "laneexec.client-launch-config.v1",
        "activation": {"lane_placement": "placeholder", "local_pi_runner_launcher": "placeholder"},
        "seed_limits": {"max_entries": 1, "max_bytes": 1},
        "template_registry": {"templates": [{"name": "placeholder", "sha256": "0" * 64}],
                              "toolkit_pins": {"commit": "0" * 40}},
    },
}
#: One overridden threshold; every other ``local_headroom`` value is the host default.
ENDPOINT_HOST = {"schema": "placement.host-config.v1",
                 "local_headroom": {"load_per_cpu_percent_maximum_exclusive": 50}}


def _write(directory: Path, name: str, body: dict) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(body))
    os.chmod(path, 0o600)


def _env_at(path: Path) -> Env:
    path.mkdir(parents=True)
    return Env(path)


def _load(root: Path, document: dict, *, host: dict | None = None, client="agent-toolkit"):
    _write(root, f"{client}.json", document)
    if host is not None:
        _write(root, "host.json", host)
    return sandbox_policy.load_placement_client_config(client, config_root=root, seat_caps_sha256=CAPS)


def _oracle(document: dict, *, host_overrides: dict | None = None) -> bytes:
    """The expected effective configuration, built without the loader's provider code."""
    headroom = contract.LocalHeadroomConfig.from_json(
        {**sandbox_policy.placement_headroom_defaults(), **(host_overrides or {})}).to_json()
    providers = {}
    for name, body in document.get("providers", {}).items():
        if "reach" in body:
            providers[name] = {"reach": "link", "workloads": sorted(body["workloads"]),
                               "policy_vectors": sorted(body["policy_vectors"])}
        else:
            endpoints = sorted({(e["host"].lower(), e["port"]) for e in body["endpoints"]})
            providers[name] = {"endpoints": [{"host": h, "port": p} for h, p in endpoints],
                               "workloads": sorted(body["workloads"]),
                               "policy_vectors": sorted(body["policy_vectors"])}
    targets = [{"name": t["name"], "kind": t["kind"], "rank": t["rank"],
                "transport_id": t["transport_id"], "root": t.get("root"),
                "probe_receipt_providers": sorted(t.get("probe_receipt_providers", [])),
                "od7_providers": sorted(t.get("od7_providers", []))}
               for t in sorted(document.get("targets", []), key=lambda t: t["rank"])]
    effective = {"schema": "placement.client-config.v1", "client": document["client"],
                 "local_headroom": headroom, "providers": providers, "targets": targets,
                 "seat_route": dict(sorted(document.get("seat_route", {}).items())),
                 "policy_vectors": POLICY_DIGESTS, "seat_caps_sha256": CAPS}
    if "launch" in document:
        effective["launch"] = document["launch"]
    return rfc8785.dumps(effective)


@pytest.fixture
def env(tmp_path):
    built = Env(tmp_path)
    built.toolkit()
    built.harness()
    return built


def _state(value):
    return lambda: value


def _lifecycle(env, state="disabled", client="agent-toolkit"):
    return env.lifecycle(client, route_state=_state(state))


def _launch(config, reservation=None, *, state="enabled", workload="pi-runner", target_kind="openshell",
            providers=None, config_sha256=None, egress_sha256=None):
    check = _new(sp, "openshell_launch_refusal")
    return check(
        config, workload=workload, target_kind=target_kind,
        providers=tuple(providers if providers is not None else reservation.providers),
        config_sha256=config_sha256 if config_sha256 is not None else reservation.config_sha256,
        egress_sha256=egress_sha256 if egress_sha256 is not None else reservation.egress_sha256,
        route_state=_state(state))


# -- loader -----------------------------------------------------------------------------------

def test_l1_a_link_only_provider_loads_with_no_endpoints(tmp_path):
    config = _load(tmp_path / "c", LINK_ONLY)
    for name in PREP_NAMES:
        provider = config.providers[name]
        assert provider.endpoints == ()
        assert _new(provider, "link_only") is True
    assert config.canonical == _oracle(LINK_ONLY)
    effective = json.loads(config.canonical)
    assert effective["providers"]["openai"] == {
        "policy_vectors": BOTH_VECTORS, "reach": "link", "workloads": ["pi-runner"]}
    assert all("endpoints" not in body for body in effective["providers"].values())
    assert config.config_sha256 == sha256(_oracle(LINK_ONLY)).hexdigest()


L2_INVALID = {
    "reach-with-endpoints": {**_link(), "endpoints": ANTHROPIC},
    "reach-with-empty-endpoints": {**_link(), "endpoints": []},
    "reach-endpoints": {**_link(), "reach": "endpoints"},
    "reach-upper": {**_link(), "reach": "LINK"},
    "reach-true": {**_link(), "reach": True},
    "empty-endpoints-without-reach": _endpoint_provider(endpoints=[]),
    "link-without-workloads": {"reach": "link", "policy_vectors": BOTH_VECTORS},
    "link-without-vectors": {"reach": "link", "workloads": ["pi-runner"]},
    "link-unknown-member": {**_link(), "note": "x"},
}


@pytest.mark.parametrize("case", sorted(L2_INVALID))
def test_l2_every_other_provider_shape_is_invalid(tmp_path, case):
    with pytest.raises(sandbox_policy.PlacementConfigError) as caught:
        _load(tmp_path / "c", _toolkit({"openai": L2_INVALID[case]}))
    assert str(caught.value) == "placement_config_invalid"


def test_l3_kind_workload_and_vector_edits_each_move_config_sha256(tmp_path):
    def digest(name, document):
        return _load(tmp_path / name, document).config_sha256

    kind = copy.deepcopy(ENDPOINT_FORM)
    kind["providers"]["mid"] = _link(vectors=["minimal-without-app"])
    vectors = copy.deepcopy(ENDPOINT_FORM)
    vectors["providers"]["mid"]["policy_vectors"] = ["minimal-without-app", "full-remote-pi-runner"]
    workloads = copy.deepcopy(ENDPOINT_FORM)
    workloads["providers"]["mid"]["workloads"] = []  # the toolkit's only other valid value
    digests = [digest("base", ENDPOINT_FORM), digest("kind", kind), digest("vectors", vectors),
               digest("workloads", workloads)]
    assert len(set(digests)) == 4
    # A workload edit on a client with several workloads, from the producer's fixture.
    env = _env_at(tmp_path / "h")
    env.harness()
    base = env.lifecycle("agent-harness").config(CAPS).config_sha256
    env.harness(providers={"anthropic": {"endpoints": ANTHROPIC, "workloads": ["leg", "qualification"],
                                         "policy_vectors": ["minimal-with-app", "minimal-without-app"]}})
    assert env.lifecycle("agent-harness").config(CAPS).config_sha256 not in (base, *digests)


# -- digest witnesses: nonempty endpoint form -------------------------------------------

def test_w1_the_endpoint_form_keeps_its_main_config_sha256(tmp_path):
    config = _load(tmp_path / "c", ENDPOINT_FORM, host=ENDPOINT_HOST)
    assert config.config_sha256 == GOLDEN_ENDPOINT_FORM
    assert config.canonical == _oracle(ENDPOINT_FORM, host_overrides=ENDPOINT_HOST["local_headroom"])
    assert b'"reach"' not in config.canonical
    assert config.providers["zeta"].endpoints == (("api.zeta.example", 8443), ("auth.zeta.example", 443))


def test_w3_the_producer_endpoint_configs_keep_their_main_config_sha256(tmp_path):
    env = Env(tmp_path)
    env.toolkit()
    env.harness()
    toolkit = env.lifecycle().config(CAPS)
    harness = env.lifecycle("agent-harness").config(CAPS)
    assert toolkit.config_sha256 == GOLDEN_PRODUCER_TOOLKIT
    assert harness.config_sha256 == GOLDEN_PRODUCER_HARNESS
    # The harness fixture writes its workloads unsorted; the emission sorts them.
    written = json.loads((env.config / "agent-harness.json").read_text())
    assert written["providers"]["anthropic"]["workloads"] == ["leg", "qualification", "implementation"]
    assert json.loads(harness.canonical)["providers"]["anthropic"] == {
        "endpoints": ANTHROPIC, "policy_vectors": ["minimal-with-app", "minimal-without-app"],
        "workloads": ["implementation", "leg", "qualification"]}
    assert harness.canonical == _oracle(written)


def _cases_provider_bodies():
    raw = (Path(__file__).parent / "fixtures" / "placement-cli" / "cases.json").read_text()
    for case in json.loads(raw)["cases"]:
        config = case.get("config") or {}
        for name, body in sorted(config.get("providers", {}).items()):
            yield case["id"], case["client"], name, body


def test_w4_every_pinned_cli_provider_body_keeps_its_v1_emission():
    parse = _new(sandbox_policy, "_parse_placement_provider")
    emit = _new(sandbox_policy, "_placement_provider_effective")
    seen = 0
    for _case, client, name, body in _cases_provider_bodies():
        provider = parse(name, body, sandbox_policy._PLACEMENT_WORKLOADS[client])
        expected = {"endpoints": [{"host": h, "port": p}
                                  for h, p in sorted({(e["host"].lower(), e["port"]) for e in body["endpoints"]})],
                    "workloads": sorted(body["workloads"]), "policy_vectors": sorted(body["policy_vectors"])}
        assert emit(provider) == expected
        assert rfc8785.dumps(emit(provider)) == rfc8785.dumps(expected)
        seen += 1
    assert seen >= 15


def _check_v1():
    raw = resources.files("phase_loop_runtime").joinpath(
        "contracts/placement/vectors/policies.json").read_bytes()
    rows = {row["name"]: row for row in json.loads(raw)["valid"]}
    return all(rows[name]["policy"].get("network_policies") == {}
               for name in ("minimal-with-app", "minimal-without-app", "full-remote-pi-runner"))


def test_v1_every_packaged_vector_has_an_empty_baseline():
    assert _check_v1() is True


# -- effective egress and binding (route disabled) --------------------------------------

def _check_e1(env) -> bool:
    env.write("agent-toolkit.json", LINK_ONLY)
    order = ("xai", "openai", "baseten", "lithos")
    response, _raw, code = reserve(_lifecycle(env), "e1", providers=order)
    reservation = response.reservation
    expected = expected_egress(PREP_NAMES, {name: [] for name in PREP_NAMES})
    grant, digest = sp.effective_egress(order, (), {name: () for name in PREP_NAMES})
    return (code == 0 and reservation.target.name == "ai" and reservation.providers == order
            and reservation.egress_sha256 == expected == digest == PREP_EGRESS
            and grant == {"providers": sorted(PREP_NAMES), "rules": []})


def test_e1_link_only_providers_bind_their_names_and_no_rule(env):
    assert _check_e1(env) is True


MIXED = _toolkit({"openai": _link(), "anthropic": _endpoint_provider()})


def _check_mixed(env) -> bool:
    env.write("agent-toolkit.json", MIXED)
    response, _raw, code = reserve(_lifecycle(env), "e2", providers=("openai", "anthropic"))
    reservation = response.reservation
    return (code == 0 and reservation.target.name == "ai"
            and reservation.providers == ("openai", "anthropic")
            and reservation.egress_sha256 == expected_egress(["anthropic", "openai"],
                                                             {"anthropic": ANTHROPIC, "openai": []}))


def test_e2_mixed_requests_keep_the_v1_union(env):
    # Compatibility behaviour while the route is disabled, not zero egress.
    assert _check_mixed(env) is True
    grant, _digest = sp.effective_egress(("openai", "anthropic"), (), {
        "openai": (), "anthropic": (("api.anthropic.com", 443),)})
    assert grant == {"providers": ["anthropic", "openai"],
                     "rules": [{"host": "api.anthropic.com", "port": 443}]}


def test_e2_a_local_pi_runner_with_a_link_only_name_has_no_bridge(env):
    env.write("agent-toolkit.json", _toolkit({"openai": _link()}, targets=[
        {"name": "local", "kind": "local", "rank": 1, "transport_id": "local"}]))
    response, _raw, code = reserve(_lifecycle(env), "e2l", providers=("openai",))
    assert code == 0 and response.reservation.target.name == "local"
    assert response.reservation.bridge is None
    assert response.reservation.egress_sha256 == expected_egress(["openai"], {"openai": []})


def test_e2_a_link_only_name_still_needs_the_probe_receipt(env):
    targets = _toolkit_targets(["openai"])
    targets[0]["probe_receipt_providers"] = []
    env.write("agent-toolkit.json", _toolkit({"openai": _link()}, targets=targets))
    response, _raw, _code = reserve(_lifecycle(env), "e2p", providers=("openai",))
    assert trail(response)[0] == ("ai", "refused", PROVIDER_REFUSED)
    assert env.coordinator.calls == [] and env.leases() == []


def test_e2_a_link_only_name_still_needs_od7_on_a_third_party_target(env):
    env.write("agent-toolkit.json", _toolkit({"openai": _link()}, targets=[
        {"name": "e2b", "kind": "e2b", "rank": 2, "transport_id": "e2b", "od7_providers": []}]))
    response, _raw, _code = reserve(_lifecycle(env), "e2e", providers=("openai",))
    assert trail(response) == [("e2b", "refused", PROVIDER_REFUSED)]


# -- route state -------------------------------------------------------------------------

class _Registered:
    name = "openshell-registered"


def _route(monkeypatch, *, status="qualified", flag=True, backend=_Registered()):
    from phase_loop_runtime import panel_invoker

    if isinstance(status, Exception):
        def raising():
            raise status
        monkeypatch.setattr(sandbox_policy, "placement_policy_status", raising)
    else:
        monkeypatch.setattr(sandbox_policy, "placement_policy_status", lambda: status)
    monkeypatch.setattr(panel_invoker, "_NONLOCAL_EXECUTION_DRIVER", flag)
    if isinstance(backend, Exception):
        def lookup(scheme):
            raise backend
    else:
        def lookup(scheme):
            return backend if scheme == "openshell" else None
    monkeypatch.setattr(sp, "backend_for_scheme", lookup)
    return _new(sp, "openshell_route_state")()


R1_ROWS = {
    "pending-only": ({"status": "pending_qualification"}, "disabled"),
    "flag-only": ({"flag": False}, "disabled"),
    "flag-not-true": ({"flag": 1}, "disabled"),
    "unregistered-only": ({"backend": None}, "disabled"),
    "all-cleared": ({}, "enabled"),
    "status-unavailable": ({"status": sandbox_policy.PlacementConfigError()}, "unknown"),
    "registry-raises": ({"backend": sp.PlacementUnavailable("sandbox_placement_plugin_unavailable")},
                        "unknown"),
}


@pytest.mark.parametrize("row", sorted(R1_ROWS))
def test_r1_route_state_requires_all_three_conditions(monkeypatch, row):
    changes, expected = R1_ROWS[row]
    assert _route(monkeypatch, **changes) == expected


def test_r1_shipped_constants_are_disabled():
    assert _new(sandbox_policy, "placement_policy_status")() == "pending_qualification"
    assert _new(sp, "openshell_route_state")() == "disabled"


R1_STATUS_BYTES = {
    "malformed": b"{",
    "missing": json.dumps({"valid": []}).encode(),
    "non-string": json.dumps({"status": 1, "valid": []}).encode(),
    "not-an-object": b"[]",
}


@pytest.mark.parametrize("row", sorted([*R1_STATUS_BYTES, "unreadable"]))
def test_r1_an_unreadable_or_malformed_status_is_unknown(monkeypatch, row):
    from phase_loop_runtime import panel_invoker

    if row == "unreadable":
        def raw():
            raise OSError("unreadable")
    else:
        def raw():
            return R1_STATUS_BYTES[row]
    monkeypatch.setattr(sandbox_policy, _new_name(sandbox_policy, "_placement_policies_raw"), raw)
    with pytest.raises(sandbox_policy.PlacementConfigError):
        _new(sandbox_policy, "placement_policy_status")()
    monkeypatch.setattr(panel_invoker, "_NONLOCAL_EXECUTION_DRIVER", True)
    monkeypatch.setattr(sp, "backend_for_scheme", lambda scheme: _Registered())
    assert _new(sp, "openshell_route_state")() == "unknown"


def _new_name(module, name):
    _new(module, name)
    return name


def test_r1_an_invoker_import_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(sandbox_policy, "placement_policy_status", lambda: "qualified")
    monkeypatch.setitem(sys.modules, "phase_loop_runtime.panel_invoker", None)
    assert _new(sp, "openshell_route_state")() == "unknown"


def test_r1_a_pending_status_never_imports_the_invoker():
    program = (
        "import sys\n"
        "from phase_loop_runtime import sandbox_placement as sp\n"
        "name = 'phase_loop_runtime.panel_invoker'\n"
        "before = name in sys.modules\n"
        "state = sp.openshell_route_state()\n"
        "print(before, state, name in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-c", program], capture_output=True, timeout=120,
                          env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert done.returncode == 0, done.stderr
    assert done.stdout.decode().split() == ["False", "disabled", "False"]


# -- launch check (the boundary function) -----------------------------------------------

def _k1(tmp_path):
    config = _load(tmp_path / "k", LINK_ONLY)
    return config, dict(providers=PREP_NAMES, config_sha256=config.config_sha256, egress_sha256=PREP_EGRESS)


def _check_k1(tmp_path) -> bool:
    config, terms = _k1(tmp_path)
    return _launch(config, **terms) is None


def test_k1_the_all_clear_launch_has_no_refusal(tmp_path):
    assert _check_k1(tmp_path) is True


def test_k2_route_rows_refuse_route_disabled(tmp_path):
    config, terms = _k1(tmp_path)
    assert _launch(config, state="disabled", **terms) == ROUTE_DISABLED
    assert _launch(config, state="unknown", **terms) == ROUTE_DISABLED


def test_k2_a_nonempty_predicate_refuses_route_disabled(tmp_path):
    # An endpoint pi-runner provider permitted only under the local vector still blocks it.
    document = _toolkit({**{name: _link() for name in PREP_NAMES},
                         "partner": _endpoint_provider(vectors=["minimal-without-app"])},
                        targets=_toolkit_targets(PREP_NAMES))
    config = _load(tmp_path / "k", document)
    assert _launch(config, providers=PREP_NAMES, config_sha256=config.config_sha256,
                   egress_sha256=PREP_EGRESS) == ROUTE_DISABLED


def test_k2_an_injected_baseline_rule_refuses_route_disabled(tmp_path, monkeypatch):
    config, terms = _k1(tmp_path)
    original = sandbox_policy.placement_policy_baseline
    monkeypatch.setattr(sandbox_policy, "placement_policy_baseline", lambda name: (
        (("inject.invalid", 443),) if name == "full-remote-pi-runner" else original(name)))
    assert _launch(config, **terms) == ROUTE_DISABLED


def test_k2_a_config_digest_mismatch_refuses_input_mismatch(tmp_path):
    config, terms = _k1(tmp_path)
    assert _launch(config, **{**terms, "config_sha256": "0" * 64}) == INPUT_MISMATCH


def test_k2_an_unknown_or_endpoint_declared_name_refuses_route_disabled(tmp_path):
    # ``spare`` is an endpoint provider that serves no pi-runner workload, so the predicate
    # stays empty and only the declared-name row can refuse it.
    document = _toolkit({**{name: _link() for name in PREP_NAMES},
                         "spare": _endpoint_provider(workloads=())},
                        targets=_toolkit_targets(PREP_NAMES))
    config = _load(tmp_path / "k", document)
    assert sandbox_policy.placement_sandbox_egress_providers(config) == ()
    common = dict(config_sha256=config.config_sha256, egress_sha256=PREP_EGRESS)
    assert _launch(config, providers=(*PREP_NAMES, "ghost"), **common) == ROUTE_DISABLED
    assert _launch(config, providers=("openai", "spare"), **common) == ROUTE_DISABLED


def _check_k2_grant_digest(tmp_path) -> bool:
    config, terms = _k1(tmp_path)
    other = expected_egress(["openai"], {"openai": []})
    return _launch(config, **{**terms, "egress_sha256": other}) == INPUT_UNBOUND


def test_k2_a_grant_digest_mismatch_refuses_launch_input_unbound(tmp_path):
    assert _check_k2_grant_digest(tmp_path) is True


def _check_k2_grant_rule(tmp_path, monkeypatch) -> bool:
    # The recomputed grant carries a rule and its digest matches: only rules == [] refuses.
    config, terms = _k1(tmp_path)
    original = sp.effective_egress
    monkeypatch.setattr(sp, "effective_egress", lambda providers, baseline, endpoints: original(
        providers, [*baseline, ("rule.invalid", 443)], endpoints))
    digest = original(PREP_NAMES, [("rule.invalid", 443)], {name: () for name in PREP_NAMES})[1]
    return _launch(config, **{**terms, "egress_sha256": digest}) == INPUT_UNBOUND


def test_k2_a_grant_with_a_rule_refuses_launch_input_unbound(tmp_path, monkeypatch):
    assert _check_k2_grant_rule(tmp_path, monkeypatch) is True


def test_k2_a_non_openshell_launch_is_outside_the_check(tmp_path):
    config, terms = _k1(tmp_path)
    for kind in ("local", "e2b"):
        assert _launch(config, state="unknown", target_kind=kind, **terms) is None


# -- every openshell workload keeps the general route gate ------------------------------

def _check_non_pi_route(env) -> bool:
    config = env.lifecycle("agent-harness").config(CAPS)
    terms = dict(workload="leg", providers=("anthropic",), config_sha256=config.config_sha256,
                 egress_sha256=expected_egress(["anthropic"], {"anthropic": ANTHROPIC}))
    return (_launch(config, state="disabled", **terms) == ROUTE_DISABLED
            and _launch(config, state="unknown", **terms) == ROUTE_DISABLED
            and _launch(config, state="enabled", **terms) is None)


def test_a_non_pi_openshell_launch_keeps_the_general_route_gate(env):
    # Provider enforcement stays pi-runner only: an endpoint ``leg`` provider passes once the
    # route is enabled, and every route state other than enabled refuses.
    assert _check_non_pi_route(env) is True


def test_a_non_pi_openshell_launch_with_a_drifted_config_refuses_input_mismatch(env):
    config = env.lifecycle("agent-harness").config(CAPS)
    assert _launch(config, workload="leg", providers=("anthropic",), config_sha256="0" * 64,
                   egress_sha256=expected_egress(["anthropic"], {"anthropic": ANTHROPIC})) == INPUT_MISMATCH


@pytest.mark.parametrize("state", ["enabled", "unknown"])
def test_the_reserve_gate_leaves_non_pi_openshell_workloads_unchanged(env, state):
    response, _raw, code = reserve(_lifecycle(env, state, "agent-harness"), "leg-1", workload="leg")
    assert code == 0 and response.reservation.target.name == "ai"
    assert response.reservation.egress_sha256 == expected_egress(["anthropic"], {"anthropic": ANTHROPIC})


# -- drift and pre-activation reservations ----------------------------------------------
# The helper checks the config digest first, matching LANEEXEC's frozen order (binding,
# including config_binding, before activation): a drifted configuration refuses
# ``sandbox_launch_input_mismatch`` here, as it will at the production binding stage.

CONFIG_A = _toolkit({"openai": _link(), "xai": _link()})
CONFIG_B = _toolkit({"openai": _link(), "xai": _link(),
                     "partner": _endpoint_provider(vectors=["minimal-without-app"])},
                    targets=_toolkit_targets(["openai", "xai", "partner"]))
#: A' changes one link-only provider's policy vectors (the toolkit's workloads are a
#: singleton): the predicate stays empty, so only the config digest row can refuse it.
CONFIG_A_PRIME = copy.deepcopy(CONFIG_A)
CONFIG_A_PRIME["providers"]["xai"]["policy_vectors"] = ["full-remote-pi-runner"]


def _reserve_under_a(env):
    env.write("agent-toolkit.json", CONFIG_A)
    response, _raw, code = reserve(_lifecycle(env), "d1", providers=("openai", "xai"))
    assert code == 0 and response.reservation.target.name == "ai"
    return response.reservation


def _check_d1_prime(env) -> bool:
    reservation = _reserve_under_a(env)
    env.write("agent-toolkit.json", CONFIG_A_PRIME)
    config = env.lifecycle().config()
    return (sandbox_policy.placement_sandbox_egress_providers(config) == ()
            and _launch(config, reservation) == INPUT_MISMATCH)


def test_d1_config_drift_refuses_input_mismatch(env):
    reservation = _reserve_under_a(env)
    assert _launch(env.lifecycle().config(), reservation) is None
    env.write("agent-toolkit.json", CONFIG_B)
    config_b = env.lifecycle().config()
    assert sandbox_policy.placement_sandbox_egress_providers(config_b) == ("partner",)
    assert _launch(config_b, reservation) == INPUT_MISMATCH
    env.write("agent-toolkit.json", CONFIG_A_PRIME)
    assert _launch(env.lifecycle().config(), reservation) == INPUT_MISMATCH


def test_d1_the_digest_row_refuses_drift_on_its_own(env):
    assert _check_d1_prime(env) is True


def test_d1_new_requests_under_the_drifted_config_refuse_at_reserve(env):
    env.write("agent-toolkit.json", CONFIG_B)
    env.coordinator.calls.clear()
    response, _raw, _code = reserve(_lifecycle(env, "enabled"), "d1-p", providers=("partner",))
    assert trail(response)[0] == ("ai", "refused", PROVIDER_REFUSED)
    response, _raw, _code = reserve(_lifecycle(env, "enabled"), "d1-l", providers=("openai",))
    assert trail(response)[0] == ("ai", "refused", DRIVER_UNAVAILABLE)
    assert env.coordinator.calls == []


CONFIG_C = _toolkit({"anthropic": _endpoint_provider(), "openai": _link()})


def test_d2_a_dormant_endpoint_reservation_refuses_once_the_route_is_live(env):
    env.write("agent-toolkit.json", CONFIG_C)
    first, raw, code = reserve(_lifecycle(env), "d2", providers=("anthropic",))
    reservation = first.reservation
    assert code == 0 and reservation.target.name == "ai"
    assert reservation.egress_sha256 == expected_egress(["anthropic"], {"anthropic": ANTHROPIC})
    calls = list(env.coordinator.calls)
    replay, replay_raw, _code = reserve(_lifecycle(env, "enabled"), "d2", providers=("anthropic",))
    assert replay_raw == raw and contract.encode_response(replay) == raw
    assert env.coordinator.calls == calls
    config_c = env.lifecycle().config()
    assert config_c.config_sha256 == reservation.config_sha256
    assert _launch(config_c, reservation) == ROUTE_DISABLED
    env.write("agent-toolkit.json", CONFIG_A)
    assert _launch(env.lifecycle().config(), reservation) == INPUT_MISMATCH
    env.write("agent-toolkit.json", CONFIG_C)
    env.coordinator.calls.clear()
    response, _raw, _code = reserve(_lifecycle(env, "enabled"), "d2-new", providers=("anthropic",))
    assert trail(response)[0] == ("ai", "refused", PROVIDER_REFUSED)
    assert env.coordinator.calls == []


# -- reserve gate --------------------------------------------------------------------------

def _check_g1(env) -> bool:
    env.write("agent-toolkit.json", CONFIG_C)
    env.coordinator.calls.clear()
    response, _raw, code = reserve(_lifecycle(env, "enabled"), "g1", providers=("anthropic",))
    return (trail(response)[0] == ("ai", "refused", PROVIDER_REFUSED)
            and env.coordinator.calls == [] and env.leases() == [] and env.bridge.opened == []
            and code == 0 and response.reservation.target.name == "local")


def test_g1_a_live_route_refuses_a_declared_endpoint_provider_before_any_call(env):
    assert _check_g1(env) is True


def _check_g2(env) -> bool:
    env.write("agent-toolkit.json", LINK_ONLY)
    response, _raw, code = reserve(_lifecycle(env, "enabled"), "g2", providers=PREP_NAMES)
    return code == 0 and response.reservation.target.name == "ai" and response.reservation.egress_sha256 == PREP_EGRESS


def test_g2_a_live_route_admits_only_link_only_names(env):
    assert _check_g2(env) is True


G3_ROWS = {
    "all-link-only": (_toolkit({"openai": _link(), "xai": _link()}), "agent-toolkit", ()),
    "full-remote-endpoint": (_toolkit({"openai": _link(), "zeta": _endpoint_provider(vectors=["full-remote-pi-runner"])}),
                             "agent-toolkit", ("zeta",)),
    "local-vector-endpoint": (_toolkit({"openai": _link(), "mid": _endpoint_provider(vectors=["minimal-without-app"]),
                                        "alpha": _endpoint_provider()}),
                              "agent-toolkit", ("alpha", "mid")),
    "no-pi-runner": (None, "agent-harness", ()),
}


def _g3(tmp_path, row):
    document, client, _expected = G3_ROWS[row]
    if document is None:
        env = _env_at(tmp_path / row)
        env.harness()
        config = env.lifecycle(client).config(CAPS)
    else:
        config = _load(tmp_path / row, document)
    return _new(sandbox_policy, "placement_sandbox_egress_providers")(config)


@pytest.mark.parametrize("row", sorted(G3_ROWS))
def test_g3_the_predicate_names_every_endpoint_pi_runner_provider(tmp_path, row):
    assert _g3(tmp_path, row) == G3_ROWS[row][2]


def test_g4_an_unknown_route_state_enforces(env):
    env.write("agent-toolkit.json", CONFIG_C)
    response, _raw, _code = reserve(_lifecycle(env, "unknown"), "g4-e", providers=("anthropic",))
    assert trail(response)[0] == ("ai", "refused", PROVIDER_REFUSED)
    response, _raw, _code = reserve(_lifecycle(env, "unknown"), "g4-l", providers=("openai",))
    assert trail(response)[0] == ("ai", "refused", DRIVER_UNAVAILABLE)


def _check_w2(env) -> bool:
    env.toolkit()
    response, _raw, code = reserve(env.lifecycle(), "w2")
    return code == 0 and response.reservation.target.name == "ai"


def test_w2_shipped_constants_keep_the_v1_endpoint_admission(env):
    # The default route_state under shipped constants: the gate is dormant.
    assert _check_w2(env) is True


# -- process boundary ---------------------------------------------------------------------

@pytest.fixture
def home():
    path = Path(tempfile.mkdtemp(prefix="plk", dir="/tmp"))
    os.chmod(path, 0o700)
    (path / ".config" / "agent-harness" / "placement").mkdir(parents=True, mode=0o700)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _cli(home: Path, argv: list[str]):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    done = subprocess.run([sys.executable, "-I", "-m", "phase_loop_runtime.placement_cli", *argv],
                          capture_output=True, env=env, timeout=120, cwd=home)
    return done.returncode, done.stdout, done.stderr


def _cli_loader_digest(home: Path) -> str:
    program = ("from phase_loop_runtime import sandbox_placement as sp\n"
               "print(sp.PlacementLifecycle('agent-toolkit').config().config_sha256)\n")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    done = subprocess.run([sys.executable, "-I", "-c", program], capture_output=True, env=env,
                          timeout=120, cwd=home)
    assert done.returncode == 0, done.stderr
    return done.stdout.decode().strip()


def test_c1_version_accepts_a_link_only_config_and_refuses_reach_with_endpoints(home):
    _write(home / ".config" / "agent-harness" / "placement", "agent-toolkit.json", LINK_ONLY)
    code, out, err = _cli(home, ["--client", "agent-toolkit", "version"])
    assert (code, err) == (0, b""), err
    version = contract.decode_response("version", out)
    assert version.protocol_schema_sha256 == PROTOCOL_SHA256
    assert version.config_sha256 == _cli_loader_digest(home)
    _write(home / ".config" / "agent-harness" / "placement", "agent-toolkit.json",
           _toolkit({"openai": {**_link(), "endpoints": ANTHROPIC}}))
    code, out, err = _cli(home, ["--client", "agent-toolkit", "version"])
    assert (code, out, err) == (70, b"", b"agent-harness-placement: placement_config_invalid\n")


# -- mutation controls --------------------------------------------------------------------

def _mutant(name):
    """``(owner, attribute, replacement)`` for each control, built against the live symbol."""
    if name == "link-load":
        def v1_parse(provider_name, body, workloads):
            sandbox_policy._require(isinstance(body, dict) and set(body) == {"endpoints", "workloads", "policy_vectors"})
            return original(provider_name, body, workloads)
        original = _new(sandbox_policy, "_parse_placement_provider")
        return sandbox_policy, "_parse_placement_provider", v1_parse
    if name == "link-shape":
        original = _new(sandbox_policy, "_parse_placement_provider")

        def lax(provider_name, body, workloads):
            if isinstance(body, dict) and "reach" in body:
                body = {k: v for k, v in body.items() if k != "endpoints"}
            return original(provider_name, body, workloads)
        return sandbox_policy, "_parse_placement_provider", lax
    if name == "canonical":
        original = _new(sandbox_policy, "_placement_provider_effective")
        return sandbox_policy, "_placement_provider_effective", lambda p: {**original(p), "reach": "link"}
    if name in ("link-egress", "link-name-grant"):
        original = sp.effective_egress

        def egress(providers, baseline, endpoints):
            empty = [n for n in providers if not endpoints[n]]
            if name == "link-egress":
                return original(providers, [*baseline, *(("link.invalid", 443) for _ in empty[:1])], endpoints)
            return original([n for n in providers if n not in empty], baseline, endpoints)
        return sp, "effective_egress", egress
    if name == "link-name-reservation":
        original = sp.PlacementLifecycle._binding

        def binding(self, request, record, plan, config_sha256):
            out = original(self, request, record, plan, config_sha256)
            registry = self.config().providers
            out["providers"] = [n for n in out["providers"] if registry[n].endpoints]
            return out
        return sp.PlacementLifecycle, "_binding", binding
    if name == "gate-off":
        _new(sp, "_openshell_pi_runner_refusal")
        return sp, "_openshell_pi_runner_refusal", lambda config, providers: None
    if name == "gate-scope":
        _new(sp, "_openshell_pi_runner_refusal")
        return sp, "_openshell_pi_runner_refusal", lambda config, providers: PROVIDER_REFUSED
    if name in ("predicate-scope", "predicate-link"):
        _new(sandbox_policy, "placement_sandbox_egress_providers")

        def predicate(config):
            return tuple(sorted(
                n for n, p in config.providers.items() if "pi-runner" in p.workloads
                and (name == "predicate-link" or p.endpoints)
                and (name == "predicate-link" or "full-remote-pi-runner" in p.policy_vectors)))
        return sandbox_policy, "placement_sandbox_egress_providers", predicate
    if name == "state-any":
        _new(sp, "openshell_route_state")

        def any_state():
            from phase_loop_runtime import panel_invoker

            try:
                status = sandbox_policy.placement_policy_status()
            except sandbox_policy.PlacementConfigError:
                return "unknown"
            cleared = [status != "pending_qualification", panel_invoker._NONLOCAL_EXECUTION_DRIVER is True,
                       sp.backend_for_scheme("openshell") is not None]
            return "enabled" if any(cleared) else "disabled"
        return sp, "openshell_route_state", any_state
    if name == "state-unknown":
        original = _new(sp, "openshell_route_state")

        def mapped():
            state = original()
            return "disabled" if state == "unknown" else state
        return sp, "openshell_route_state", mapped
    if name == "launch-skip-config":
        _new(sp, "_launch_config_bound")
        return sp, "_launch_config_bound", lambda config, config_sha256: True
    if name == "launch-skip-grant":
        _new(sp, "_launch_grant_refusal")
        return sp, "_launch_grant_refusal", lambda *args: None
    if name == "launch-pi-only":
        original = _new(sp, "openshell_launch_refusal")

        def pi_only(config, *, workload, **kwargs):
            return None if workload != "pi-runner" else original(config, workload=workload, **kwargs)
        return sp, "openshell_launch_refusal", pi_only
    if name == "baseline-inject":
        original = sandbox_policy.placement_policy_baseline
        return sandbox_policy, "placement_policy_baseline", lambda vector: (
            (("inject.invalid", 443),) if vector == "full-remote-pi-runner" else original(vector))
    if name == "live-always":
        _new(sp, "openshell_route_state")
        return sp, "openshell_route_state", lambda: "enabled"
    raise AssertionError(name)


def _check_l1(ctx) -> bool:
    config = _load(ctx.tmp_path / "m-l1", LINK_ONLY)
    return all(config.providers[n].endpoints == () and config.providers[n].link_only for n in PREP_NAMES)


def _check_l2_first(ctx) -> bool:
    try:
        _load(ctx.tmp_path / "m-l2", _toolkit({"openai": L2_INVALID["reach-with-endpoints"]}))
    except sandbox_policy.PlacementConfigError:
        return True
    return False


def _check_w1(ctx) -> bool:
    config = _load(ctx.tmp_path / "m-w1", ENDPOINT_FORM, host=ENDPOINT_HOST)
    return config.config_sha256 == GOLDEN_ENDPOINT_FORM


def _check_r1(ctx) -> bool:
    rows = {**R1_ROWS}
    holds = True
    for row in sorted(rows):
        changes, expected = rows[row]
        with pytest.MonkeyPatch.context() as patch:
            holds = holds and _route(patch, **changes) == expected
    return holds


def _check_unknown(ctx) -> bool:
    with pytest.MonkeyPatch.context() as patch:
        unknown = _route(patch, status=sandbox_policy.PlacementConfigError()) == "unknown"
    env = ctx.env
    env.write("agent-toolkit.json", CONFIG_C)
    response, _raw, _code = reserve(env.lifecycle(route_state=lambda: sp.openshell_route_state()),
                                    "m-g4", providers=("anthropic",))
    # Under an unreadable status the default state is unknown, and unknown enforces.
    return unknown and trail(response)[0] == ("ai", "refused", PROVIDER_REFUSED)


def _check_unknown_enforces(ctx) -> bool:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sandbox_policy, "placement_policy_status", _raise_config_error)
        return _check_unknown(ctx)


def _raise_config_error():
    raise sandbox_policy.PlacementConfigError()


def _check_g3_row(row):
    return lambda ctx: _g3(ctx.tmp_path / "m-g3", row) == G3_ROWS[row][2]


def _check_baseline(ctx) -> bool:
    return _check_k1(ctx.tmp_path / "m-k1") and _check_e1(ctx.env)


class _Ctx:
    def __init__(self, tmp_path, env, monkeypatch):
        self.tmp_path, self.env, self.monkeypatch = tmp_path, env, monkeypatch


MUTATION_CONTROLS = {
    "link-load": _check_l1,
    "link-shape": _check_l2_first,
    "canonical": _check_w1,
    "link-egress": lambda ctx: _check_e1(ctx.env),
    "link-name-grant": lambda ctx: _check_e1(ctx.env),
    "link-name-reservation": lambda ctx: _check_mixed(ctx.env) and _check_e1(ctx.env),
    "gate-off": lambda ctx: _check_g1(ctx.env),
    "gate-scope": lambda ctx: _check_g2(ctx.env),
    "predicate-scope": _check_g3_row("local-vector-endpoint"),
    "predicate-link": _check_g3_row("all-link-only"),
    "state-any": _check_r1,
    "state-unknown": _check_unknown_enforces,
    "launch-skip-config": lambda ctx: _check_d1_prime(ctx.env),
    "launch-skip-grant": lambda ctx: _check_k2_grant_digest(ctx.tmp_path / "m-k2"),
    "launch-pi-only": lambda ctx: _check_non_pi_route(ctx.env),
    "baseline-inject": _check_baseline,
    "live-always": lambda ctx: _check_w2(ctx.env),
}


@pytest.mark.parametrize("kind", ["intact", "killed"])
@pytest.mark.parametrize("control", sorted(MUTATION_CONTROLS))
def test_link_only_mutation_controls(env, tmp_path, monkeypatch, control, kind):
    check = MUTATION_CONTROLS[control]
    ctx = _Ctx(tmp_path, env, monkeypatch)
    if kind == "intact":
        assert check(ctx) is True
        return
    owner, attribute, replacement = _mutant(control)
    monkeypatch.setattr(owner, attribute, replacement)
    try:
        holds = check(ctx)
    except (AssertionError, sp.LifecycleError, contract.ProtocolError, sandbox_policy.PlacementConfigError):
        holds = False
    assert holds is False
    if control == "baseline-inject":
        assert _check_v1() is True  # the independent raw-byte check stays green
