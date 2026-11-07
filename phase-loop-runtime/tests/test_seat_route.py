from __future__ import annotations

import dataclasses
import datetime as dt
import gc
import hashlib
import importlib
import inspect
import json
from types import MappingProxyType, SimpleNamespace
import weakref

import pytest

from phase_loop_runtime import seat_egress_proxy, seat_jail, seat_profiles, seat_route
from phase_loop_runtime import panel_invoker, seat_jail_autoqualify, seat_uid, seat_window
from phase_loop_runtime.seat_route_contract import (
    CapacityGrant,
    NamedException,
    Precondition,
    RemoteAdmission,
    RouteDecision,
    RoutePolicy,
    RouteRequest,
    RouteStep,
)


class Lease:
    def __init__(self, seat_id=7):
        self.seat_id = seat_id
        self.released = False

    def release(self):
        self.released = True


class Capacity:
    def __init__(self, lease=True):
        self.calls = 0
        self.value = Lease() if lease else None

    def try_lease(self):
        self.calls += 1
        return self.value


class Remote:
    def __init__(self, admission=None):
        self.calls = []
        self.admission = admission or RemoteAdmission(
            False, "seat_remote_rung_inactive", None
        )

    def admit(self, request):
        self.calls.append(request)
        return self.admission


class Native:
    def __init__(self, offered=False):
        self.calls = []
        self.offered = offered

    def offer(self, seat_key, leg):
        self.calls.append((seat_key, leg))
        return self.offered


def policy(*, routed=(), exceptions=None, grants=()):
    return RoutePolicy(
        schema="seat_route_policy.v1",
        routed_remote=frozenset(routed),
        exceptions=MappingProxyType(dict(exceptions or {})),
        capacity_offload=tuple(grants),
    )


def request(leg="gemini", **changes):
    values = dict(
        leg=leg,
        seat_key="seat-a",
        host_class="standard",
        run_kind="review",
        staged_tree_approved=True,
        env={},
    )
    values.update(changes)
    return RouteRequest(**values)


@pytest.fixture
def ready_gemini(monkeypatch):
    profile = dataclasses.replace(
        seat_profiles.profile_for("gemini"),
        credential_present=lambda: True,
        preconditions=(),
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "gemini", profile)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    from phase_loop_runtime import sandbox_egress
    monkeypatch.setattr(sandbox_egress, "egress_required", lambda: True)
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: None)
    monkeypatch.setattr(seat_route, "_projection_for_launch", lambda *_: None)
    monkeypatch.setattr(
        seat_jail_autoqualify,
        "ensure_qualified",
        lambda *a, **k: seat_jail_autoqualify.Outcome(
            seat_jail_autoqualify.QUALIFIED
        ),
    )
    return profile


def test_local_route_holds_one_lease_and_keys_the_real_allowlist(ready_gemini):
    capacity = Capacity()
    decision = seat_route.resolve(
        request(), policy=policy(), remote=Remote(), native=Native(), capacity=capacity
    )
    assert decision.mode == "jailed"
    assert decision.code is None
    assert decision.lease is capacity.value
    assert capacity.calls == 1
    assert decision.qualification_key.allowlist_digest == (
        seat_egress_proxy.allowlist_ref("gemini").content_digest
    )


def test_dependency_admission_failure_is_a_typed_identity_refusal(
    monkeypatch, ready_gemini,
):
    from phase_loop_runtime.executable_dependency import ExecutableDependencyError

    monkeypatch.setattr(
        seat_route, "_projection_for_launch",
        lambda *_a, **_k: (_ for _ in ()).throw(ExecutableDependencyError("authority_missing")),
    )
    decision = seat_route.resolve(
        request(), policy=policy(), remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (decision.mode, decision.code) == (
        "degraded", "seat_sandbox_refused:identity",
    )


@pytest.mark.parametrize("code", [
    "seat_sandbox_unavailable_host",
    "seat_sandbox_unavailable_tiocsti",
    "seat_sandbox_unavailable_seat_uid",
    "seat_egress_not_installed",
])
def test_closed_descend_codes_walk_remote_then_native(monkeypatch, ready_gemini, code):
    if code.startswith("seat_sandbox_unavailable"):
        monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: code)
    else:
        monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: code)
    remote, native, capacity = Remote(), Native(), Capacity()
    decision = seat_route.resolve(
        request(), policy=policy(), remote=remote, native=native, capacity=capacity
    )
    assert decision.mode == "degraded"
    assert decision.code == code
    assert [step.rung for step in decision.steps] == [
        "local", "remote", "native_fill", "degraded"
    ]
    assert len(remote.calls) == 1 and len(native.calls) == 1
    assert capacity.calls == 0


def test_terminal_precondition_enters_no_later_rung(monkeypatch, ready_gemini):
    stopped = dataclasses.replace(
        ready_gemini,
        preconditions=(Precondition("fixture", lambda: "gemini_seat_profile_unqualified"),),
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "gemini", stopped)
    remote, native, capacity = Remote(), Native(), Capacity()
    decision = seat_route.resolve(
        request(), policy=policy(), remote=remote, native=native, capacity=capacity
    )
    assert (decision.mode, decision.code) == (
        "degraded", "gemini_seat_profile_unqualified"
    )
    assert not remote.calls and not native.calls and capacity.calls == 0


def test_unregistered_named_exception_expires(monkeypatch):
    expiry = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    exception = NamedException("codex", "unconfined", expiry, "fixture")
    decision = seat_route.resolve(
        request("codex"),
        policy=policy(exceptions={"codex": exception}),
        remote=Remote(),
        native=Native(),
        capacity=Capacity(),
    )
    assert (decision.mode, decision.code) == (
        "degraded", "seat_route_exception_expired"
    )


def test_registered_profile_never_uses_unconfined_exception(
    monkeypatch, ready_gemini,
):
    stopped = dataclasses.replace(ready_gemini, credential_present=lambda: False)
    monkeypatch.setitem(seat_profiles._REGISTRY, "gemini", stopped)
    exception = NamedException(
        "gemini", "unconfined",
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1), "fixture",
    )
    decision = seat_route.resolve(
        request(), policy=policy(exceptions={"gemini": exception}),
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (decision.mode, decision.code) == (
        "degraded", "gemini_seat_credential_missing"
    )


def test_capacity_offload_ships_disabled(ready_gemini):
    remote = Remote(RemoteAdmission(True, "seat_capacity_offloaded", "fixture"))
    decision = seat_route.resolve(
        request(), policy=policy(), remote=remote, native=Native(), capacity=Capacity(False)
    )
    assert (decision.mode, decision.code) == (
        "degraded", "seat_local_capacity_exhausted"
    )
    assert not remote.calls


def test_routed_vendor_row_skips_local_and_uses_derived_vendor(monkeypatch):
    remote = Remote(RemoteAdmission(True, "seat_remote_rung_inactive", None))
    decision = seat_route.resolve(
        request("codex"),
        policy=policy(routed={"codex", "standard"}),
        remote=remote,
        native=Native(),
        capacity=Capacity(),
    )
    # A malformed tuple is not a routed pair and cannot accidentally route.
    assert decision.code == "seat_profile_unregistered"
    assert not remote.calls
    decision = seat_route.resolve(
        request("codex"),
        policy=policy(routed={("codex", "standard")}),
        remote=remote,
        native=Native(),
        capacity=Capacity(),
    )
    assert decision.mode == "remote"
    assert remote.calls[-1].vendor == "codex"


def test_matrix_reduction_routes_one_host_class_and_keeps_another_local(monkeypatch):
    profile = dataclasses.replace(
        seat_profiles.profile_for("gemini"),
        leg="fixture",
        vendor="fixture",
        recorded_stop="gemini_seat_profile_unqualified",
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "fixture", profile)
    monkeypatch.setattr(
        seat_window,
        "readiness_rows",
        lambda: [{
            "kind": "vendor",
            "vendor": "fixture",
            "status": "remote-pending",
            "host_classes": ["team"],
            "exception": None,
            "expiry": None,
        }],
    )
    matrix = seat_route._matrix_policy()
    assert matrix.routed_remote == frozenset({("fixture", "team")})

    team = seat_route.resolve(
        request("fixture", host_class="team"), policy=matrix,
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    standard = seat_route.resolve(
        request("fixture", host_class="standard"), policy=matrix,
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (team.mode, team.steps[0].step, team.steps[0].outcome) == (
        "degraded", "L", "skipped",
    )
    assert (standard.mode, standard.code, standard.steps[0].step) == (
        "degraded", "gemini_seat_profile_unqualified", "L2",
    )


def test_policy_overlay_is_capacity_only_without_schema(tmp_path, monkeypatch):
    root = tmp_path / "state"
    route_dir = root / "phase-loop"
    route_dir.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    route_dir.chmod(0o700)
    target = route_dir / "seat-route-policy.json"
    target.write_text('{"schema":"seat_route_policy.v1","capacity_offload":[]}')
    target.chmod(0o600)
    loaded = seat_route.load_route_policy(target)
    assert loaded.capacity_offload == ()
    assert id(loaded) in seat_route._IGNORED_POLICIES
    target.write_text('{"capacity_offload":[]}')
    target.chmod(0o600)
    loaded = seat_route.load_route_policy(target)
    assert loaded.capacity_offload == ()
    assert id(loaded) not in seat_route._IGNORED_POLICIES


def test_ignored_policy_registry_is_weak(tmp_path):
    route_dir = tmp_path / "private"
    route_dir.mkdir(mode=0o700)
    target = route_dir / "seat-route-policy.json"
    target.write_text('{"schema":"not-allowed"}', encoding="utf-8")
    target.chmod(0o600)
    loaded = seat_route.load_route_policy(target)
    identity = id(loaded)
    reference = weakref.ref(loaded)
    assert identity in seat_route._IGNORED_POLICIES
    del loaded
    gc.collect()
    assert reference() is None and identity not in seat_route._IGNORED_POLICIES


def test_policy_and_receipt_check_the_private_state_ancestor_chain(tmp_path, monkeypatch):
    state = tmp_path / "state"
    phase = state / "phase-loop"
    receipts = phase / "seat-remote-probes"
    receipts.mkdir(parents=True, mode=0o700)
    state.chmod(0o777)
    phase.chmod(0o700)
    receipts.chmod(0o700)
    overlay = phase / "seat-route-policy.json"
    overlay.write_text('{"capacity_offload":[]}', encoding="utf-8")
    overlay.chmod(0o600)
    monkeypatch.setattr(seat_jail, "state_home", lambda: state)
    loaded = seat_route.load_route_policy()
    assert id(loaded) in seat_route._IGNORED_POLICIES
    assert not seat_route._grant_current(
        _grant(), "gemini", now=dt.datetime.now(dt.timezone.utc),
    )


def test_dangling_policy_link_is_ignored_not_treated_as_absent(tmp_path):
    route_dir = tmp_path / "private"
    route_dir.mkdir(mode=0o700)
    target = route_dir / "seat-route-policy.json"
    target.symlink_to(route_dir / "missing")
    loaded = seat_route.load_route_policy(target)
    assert id(loaded) in seat_route._IGNORED_POLICIES


def test_mode_line_codes_close_the_od10_table():
    from phase_loop_runtime.seat_route_contract import OD10_CLASSES

    assert seat_route.mode_line_codes() == frozenset(OD10_CLASSES)


def test_import_refuses_an_od10_table_outside_the_mode_line_closure(monkeypatch):
    from phase_loop_runtime import seat_route_contract

    original = seat_route_contract.OD10_CLASSES
    widened = MappingProxyType({**dict(original), "fixture_unreachable_code": "ordinary"})
    monkeypatch.setattr(seat_route_contract, "OD10_CLASSES", widened)
    with pytest.raises(RuntimeError, match="OD-10 closure mismatch"):
        importlib.reload(seat_route)
    monkeypatch.setattr(seat_route_contract, "OD10_CLASSES", original)
    importlib.reload(seat_route)


@pytest.mark.parametrize("leg", ["codex", "grok"])
def test_unregistered_vendor_uses_only_its_unconfined_window(leg):
    now = dt.datetime.now(dt.timezone.utc)
    exception = NamedException(
        leg, "unconfined", now + dt.timedelta(minutes=1), "fixture",
    )
    decision = seat_route.resolve(
        request(leg), policy=policy(exceptions={leg: exception}),
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (decision.mode, decision.code, decision.exception) == (
        "unconfined", "seat_filesystem_unconfined", exception,
    )

    expired = dataclasses.replace(exception, expiry=now - dt.timedelta(seconds=1))
    decision = seat_route.resolve(
        request(leg), policy=policy(exceptions={leg: expired}),
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (decision.mode, decision.code) == (
        "degraded", "seat_route_exception_expired",
    )


@pytest.mark.parametrize("leg", ["pi", "opencode", "cursor"])
def test_unregistered_vendor_without_named_window_is_terminal(leg):
    remote, native, capacity = Remote(), Native(), Capacity()
    decision = seat_route.resolve(
        request(leg), policy=policy(), remote=remote, native=native, capacity=capacity,
    )
    assert (decision.mode, decision.code) == (
        "degraded", "seat_profile_unregistered",
    )
    assert not remote.calls and not native.calls and capacity.calls == 0


def test_claude_open_egress_window_and_expiry(monkeypatch):
    profile = dataclasses.replace(
        seat_profiles.profile_for("claude"),
        credential_present=lambda: True,
        variant=lambda _env: ("print", None),
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "claude", profile)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    monkeypatch.setattr(seat_route, "_projection_for_launch", lambda *_: None)
    monkeypatch.setattr(
        seat_jail_autoqualify, "ensure_qualified",
        lambda *a, **k: seat_jail_autoqualify.Outcome(seat_jail_autoqualify.QUALIFIED),
    )
    now = dt.datetime.now(dt.timezone.utc)
    exception = NamedException(
        "claude", "open egress", now + dt.timedelta(minutes=1), "fixture",
    )
    decision = seat_route.resolve(
        request("claude"), policy=policy(exceptions={"claude": exception}),
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert decision.mode == "jailed"
    assert decision.qualification_key.allowlist_digest is None
    assert decision.variant == "print"

    expired = dataclasses.replace(exception, expiry=now - dt.timedelta(seconds=1))
    decision = seat_route.resolve(
        request("claude"), policy=policy(exceptions={"claude": expired}),
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (decision.mode, decision.code) == (
        "degraded", "seat_route_exception_expired",
    )


def _grant(*, target_class="owner_controlled", activation_refs=None):
    return CapacityGrant(
        target="fixture-target",
        target_class=target_class,
        host_classes=frozenset({"standard"}),
        vendors=frozenset({"gemini"}),
        probe_set_digest="probe-set-v1",
        probe_receipt="fixture-receipt",
        activation_refs=MappingProxyType(dict(activation_refs or {})),
    )


def _write_probe_receipt(root, grant, *, expired=False):
    root.mkdir(mode=0o700)
    evidence = b'{"probe":"pass"}\n'
    (root / "fixture-receipt.evidence.json").write_bytes(evidence)
    (root / "fixture-receipt.evidence.json").chmod(0o600)
    now = dt.datetime.now(dt.timezone.utc)
    record = {
        "schema": "seat_remote_probe_receipt.v1",
        "target": grant.target,
        "target_class": grant.target_class,
        "probe_set_digest": grant.probe_set_digest,
        "result": "pass",
        "observed_at": (now - dt.timedelta(minutes=2)).isoformat(),
        "expires_at": (now - dt.timedelta(minutes=1) if expired
                       else now + dt.timedelta(minutes=2)).isoformat(),
        "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
    }
    target = root / "fixture-receipt.json"
    target.write_text(json.dumps(record), encoding="utf-8")
    target.chmod(0o600)


@pytest.mark.parametrize(
    "target_class,activation_refs,expired,admitted",
    [
        ("owner_controlled", {}, False, True),
        ("third_party", {}, False, False),
        ("third_party", {"gemini": "OD-7-fixture"}, False, True),
        ("owner_controlled", {}, True, False),
    ],
)
def test_capacity_offload_requires_current_receipt_and_vendor_od7(
    tmp_path, monkeypatch, ready_gemini,
    target_class, activation_refs, expired, admitted,
):
    grant = _grant(target_class=target_class, activation_refs=activation_refs)
    root = tmp_path / "receipts"
    _write_probe_receipt(root, grant, expired=expired)
    monkeypatch.setattr(seat_route, "_receipt_root", lambda: root)
    remote = Remote(RemoteAdmission(True, "seat_capacity_offloaded", "fixture"))
    decision = seat_route.resolve(
        request(), policy=policy(grants=(grant,)), remote=remote,
        native=Native(), capacity=Capacity(False),
    )
    if admitted:
        assert (decision.mode, decision.code) == ("remote", "seat_capacity_offloaded")
        assert len(remote.calls) == 1
        assert remote.calls[0].trigger == "capacity"
    else:
        assert (decision.mode, decision.code) == (
            "degraded", "seat_local_capacity_exhausted",
        )
        assert not remote.calls


def test_seat_capacity_holds_every_lease_until_explicit_release(tmp_path):
    capacity = seat_uid.SeatIdCapacity(count=2, directory=tmp_path / "leases")
    first = capacity.try_lease()
    second = capacity.try_lease()
    assert (first.seat_id, second.seat_id) == (1, 2)
    assert capacity.try_lease() is None
    first.release()
    first.release()
    replacement = capacity.try_lease()
    assert replacement.seat_id == 1
    replacement.release()
    second.release()


def test_capacity_gate_then_released_lease_is_held_until_route_teardown(
    tmp_path, monkeypatch, ready_gemini,
):
    capacity_type = seat_uid.SeatIdCapacity
    capacity = capacity_type(count=2, directory=tmp_path)
    monkeypatch.setattr(
        panel_invoker._seat_uid,
        "SeatIdCapacity",
        lambda: capacity_type(count=2, directory=tmp_path),
    )
    remote = Remote()
    monkeypatch.setattr(seat_route, "INACTIVE_REMOTE_RUNG", remote)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    first = capacity.try_lease()
    second = capacity.try_lease()
    assert first is not None and second is not None
    route = None
    replacement = None
    try:
        route, notices, refusal = panel_invoker._seat_route_for_spawn(
            "gemini", auth, eligible=True, seat_key="g:a", env={},
        )
        assert not route.jailed and notices == []
        assert refusal == "seat_local_capacity_exhausted"
        assert remote.calls == []

        first.release()
        route, notices, refusal = panel_invoker._seat_route_for_spawn(
            "gemini", auth, eligible=True, seat_key="g:a", env={},
        )
        assert route.jailed and route.decision.lease.seat_id == 1
        assert notices == [] and refusal is None and remote.calls == []
        assert capacity.try_lease() is None

        panel_invoker._release_seat_route(route)
        route = None
        replacement = capacity.try_lease()
        assert replacement is not None and replacement.seat_id == 1
    finally:
        panel_invoker._release_seat_route(route)
        if replacement is not None:
            replacement.release()
        first.release()
        second.release()


def test_registered_profile_readiness_mismatch_is_terminal(
    monkeypatch, ready_gemini,
):
    monkeypatch.setattr(
        seat_window, "readiness_rows",
        lambda: [{"kind": "vendor", "vendor": "not-gemini"}],
    )
    remote, native, capacity = Remote(), Native(), Capacity()
    decision = seat_route.resolve(
        request(), policy=policy(), remote=remote, native=native, capacity=capacity,
    )
    assert (decision.mode, decision.code) == (
        "degraded", "seat_route_identity_invalid",
    )
    assert not remote.calls and not native.calls and capacity.calls == 0


@pytest.mark.parametrize(
    "run_kind,mode,code",
    [
        ("advisory_document", "unconfined", "seat_sandbox_not_staged"),
        ("qualification_candidate", "native", "gemini_seat_qualification_candidate"),
    ],
)
def test_non_review_run_kinds_keep_their_existing_route(
    run_kind, mode, code,
):
    remote, native, capacity = Remote(), Native(), Capacity()
    decision = seat_route.resolve(
        request(run_kind=run_kind, staged_tree_approved=False), policy=policy(),
        remote=remote, native=native, capacity=capacity,
    )
    assert (decision.mode, decision.code) == (mode, code)
    assert not remote.calls and not native.calls and capacity.calls == 0


def test_advisory_unknown_leg_precedes_route_identity():
    decision = seat_route.resolve(
        request("opencode", run_kind="advisory_document", staged_tree_approved=False),
        policy=policy(), remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (decision.mode, decision.code) == ("unconfined", "seat_sandbox_not_staged")


def test_qualification_candidate_is_scoped_to_its_registered_vendor_data(monkeypatch):
    profile = dataclasses.replace(
        seat_profiles.profile_for("claude"), recorded_stop="seat_sandbox_not_staged",
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "claude", profile)
    decision = seat_route.resolve(
        request("claude", run_kind="qualification_candidate"), policy=policy(),
        remote=Remote(), native=Native(), capacity=Capacity(),
    )
    assert (decision.mode, decision.code) == ("degraded", "seat_sandbox_not_staged")


@pytest.mark.parametrize(
    "code",
    [
        "seat_egress_not_installed",
        "seat_egress_integrity_failed",
        "seat_egress_tls_unterminated",
        "seat_egress_start_failed",
    ],
)
def test_egress_split_reaches_adapter_and_mode_line(monkeypatch, code):
    decision = RouteDecision(
        leg="gemini", vendor="gemini", mode="degraded", code=code,
        steps=(RouteStep("local", "L7", "failed", code,
                         seat_route.OD10_CLASSES[code]),),
        exception=None, variant=None, qualification_key=None, also=(), lease=None,
    )
    calls = []

    def resolve(*args, **kwargs):
        calls.append((args, kwargs))
        return decision

    monkeypatch.setattr(seat_route, "resolve", resolve)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    monkeypatch.setattr(panel_invoker, "_has_injected_review_execution_seam", lambda **k: False)
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    board = SimpleNamespace(seats=[
        SimpleNamespace(harness="gemini", seat_key="gemini:a", model="m"),
    ])
    (mode_line,) = panel_invoker._seat_launch_modes(
        board, mode="review", review_authorization=auth, base_env={},
    )
    assert (mode_line.mode, mode_line.code) == ("degraded", code)
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "gemini", auth, eligible=True, seat_key="gemini:a", env={},
    )
    assert (route.decision, notices, refusal) == (decision, [], code)
    assert len(calls) == 1, "the launch must consume the mode line's cached decision"


def test_live_jail_proxy_refuses_another_vendor_and_unlisted_host(monkeypatch):
    """VL: the real fail-closed front binds one process to one provider allowlist."""
    import os

    if os.environ.get("PHASE_LOOP_REQUIRE_LIVE_JAIL") != "1":
        pytest.skip("set PHASE_LOOP_REQUIRE_LIVE_JAIL=1 on a jail-capable host")
    from .test_seat_egress_allowlists_jailcore import _connect_status, _fixture_ref

    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None:
        pytest.fail(f"live jail egress layer unavailable: {reason}")
    refs = {name: _fixture_ref(name) for name in ("fixture-a", "fixture-b")}
    monkeypatch.setattr(
        seat_egress_proxy, "allowlist_ref", lambda allowlist_id: refs[allowlist_id],
    )
    with seat_egress_proxy.start_proxy(allowlist_id="fixture-a") as proxy:
        assert _connect_status(proxy, "fixture-a.invalid").startswith(b"HTTP/1.1 200")
        assert _connect_status(proxy, "fixture-b.invalid").startswith(b"HTTP/1.1 403")
        assert _connect_status(proxy, "not-listed.invalid").startswith(b"HTTP/1.1 403")


def _store_key(**changes):
    from phase_loop_runtime.seat_route_contract import QualificationKey

    values = dict(
        profile_digest="a" * 64,
        allowlist_digest="b" * 64,
        falsifier_layout=seat_jail.falsifier_layout_identity(),
        projection_digest=None,
        variant=None,
        host_identity=seat_jail.host_identity(),
    )
    values.update(changes)
    return QualificationKey(**values)


def _record_keyed_pass(key):
    from phase_loop_runtime import seat_jail_qualification

    evidence = {
        "result": "pass",
        "profile_digest": key.profile_digest,
        "host_identity": key.host_identity,
        "falsifier_layout": key.falsifier_layout,
    }
    return seat_jail_qualification._record_pass(evidence, key)


@pytest.mark.parametrize("part,value", [
    ("profile_digest", "c" * 64),
    ("allowlist_digest", "d" * 64),
    ("allowlist_digest", None),
    ("falsifier_layout", "execfind-falsifier-layout.v1:" + "e" * 64),
    ("projection_digest", "f" * 64),
    ("variant", "print"),
    ("host_identity", "other-host"),
])
def test_v2_pass_is_refused_under_every_changed_key_part(part, value):
    key = _store_key()
    path = _record_keyed_pass(key)
    from phase_loop_runtime.seat_route_contract import key_digest

    assert path.name == f"{key_digest(key)}.json"
    assert seat_jail.pass_record_verdict(key) == (True, "pass")
    assert seat_jail.pass_record_verdict(dataclasses.replace(key, **{part: value}))[0] is False


def test_v1_record_under_the_key_name_is_not_honoured():
    from phase_loop_runtime.seat_route_contract import key_digest

    key = _store_key()
    path = _record_keyed_pass(key)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["schema"] = "seat_jail_pass.v1"
    path.write_text(json.dumps(record), encoding="utf-8")
    path.chmod(0o600)
    assert path.name == f"{key_digest(key)}.json"
    assert seat_jail.pass_record_verdict(key) == (False, "binding_mismatch")


def test_keyed_pass_does_not_satisfy_the_profile_digest_read():
    key = _store_key()
    _record_keyed_pass(key)
    assert seat_jail.pass_record_verdict(key.profile_digest) == (False, "no_record")


def test_record_pass_refuses_evidence_that_disagrees_with_the_key():
    from phase_loop_runtime import seat_jail_qualification

    key = _store_key()
    evidence = {
        "result": "pass",
        "profile_digest": "c" * 64,
        "host_identity": key.host_identity,
        "falsifier_layout": key.falsifier_layout,
    }
    with pytest.raises(seat_jail_qualification.QualificationError):
        seat_jail_qualification._record_pass(evidence, key)
    assert seat_jail.pass_record_verdict(key)[0] is False


def test_launch_gate_honours_the_route_key_it_was_built_under(monkeypatch):
    key = _store_key()
    _record_keyed_pass(key)
    monkeypatch.setattr(panel_invoker, "_require_canonical_jail", lambda _jail: None)
    monkeypatch.setattr(
        panel_invoker._seat_jail, "actual_profile_digest", lambda _jail: key.profile_digest,
    )
    # The route admitted K: the launch re-establishes exactly K's v2 pass.
    panel_invoker._require_qualified_jail(SimpleNamespace(leg="gemini", qualification_key=key))
    # A built jail whose digest is not K's profile is refused before any store read.
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        panel_invoker._require_qualified_jail(SimpleNamespace(
            leg="gemini", qualification_key=_store_key(profile_digest="c" * 64),
        ))
    assert caught.value.code == seat_jail.refused("identity")
    # A key the store has no pass for is refused typed.
    with pytest.raises(seat_jail.SeatSandboxRefused) as caught:
        panel_invoker._require_qualified_jail(SimpleNamespace(
            leg="gemini", qualification_key=_store_key(allowlist_digest="d" * 64),
        ))
    assert caught.value.code == seat_jail.refused("jail_unqualified")


def test_spawn_binds_the_route_key_onto_both_jails(tmp_path):
    key = _store_key()

    def jail():
        return seat_jail.SeatJail(
            leg="gemini", process_owner=(), path_map={}, env={}, pass_fds=(),
            seccomp_fd=-1, profile_id="fixture", profile_digest=key.profile_digest,
            filter_digest="",
        )

    seat = panel_invoker._JailedSeat(
        jail=jail(), probe_jail=jail(), holder_pid=1, token=b"", review_dir=tmp_path,
        seat_dir=tmp_path,
    )
    decision = SimpleNamespace(qualification_key=key)
    bound = panel_invoker._bind_route_qualification(
        seat, seat_jail.SeatRoute(True, None, decision=decision),
    )
    assert bound.jail.qualification_key is key
    assert bound.probe_jail.qualification_key is key
    unbound = panel_invoker._bind_route_qualification(
        panel_invoker._JailedSeat(
            jail=jail(), probe_jail=jail(), holder_pid=1, token=b"",
            review_dir=tmp_path, seat_dir=tmp_path,
        ),
        seat_jail.SeatRoute(True, None),
    )
    assert unbound.jail.qualification_key is None


def _production_adapter(monkeypatch):
    # Production has no function-identity fallback; clearing the decision cache is the only
    # test setup required to enter the resolver path.
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()


@pytest.mark.parametrize("code", sorted(seat_route.mode_line_codes()))
def test_every_typed_degraded_code_reaches_the_launch_tuple(monkeypatch, code):
    # A profile's recorded terminal is the exhaustive L2 injection point.  Keep the real
    # resolver live so this matrix detects a broken production call site, then consume the
    # same cached decision at the launch tuple boundary.
    stopped = dataclasses.replace(seat_profiles.GEMINI, recorded_stop=code)
    monkeypatch.setitem(seat_profiles._REGISTRY, "gemini", stopped)
    calls = []
    real_resolve = seat_route.resolve

    def resolve(route_request, **kwargs):
        calls.append(route_request)
        return real_resolve(route_request, **kwargs)

    monkeypatch.setattr(seat_route, "resolve", resolve)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    remote = Remote()
    native = Native()
    monkeypatch.setattr(seat_route, "INACTIVE_REMOTE_RUNG", remote)
    monkeypatch.setattr(panel_invoker, "_NativeFillAdapter", lambda *_a: native)
    _production_adapter(monkeypatch)
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    board = SimpleNamespace(seats=[
        SimpleNamespace(harness="gemini", seat_key="gemini:a", model="m"),
    ])
    (rendered,) = panel_invoker._seat_launch_modes(
        board, mode="review", review_authorization=auth, base_env={},
    )
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "gemini", auth, eligible=True,
        seat_key="gemini:a", env={"PATH": "/nonexistent"},
    )
    assert (rendered.mode, rendered.code) == ("degraded", code)
    assert not route.jailed and route.decision.mode == "degraded"
    assert route.decision.code == code and notices == [] and refusal == code
    assert remote.calls == [] and native.calls == []
    assert route.decision.steps[-1].step == "L2"
    assert len(calls) == 1


@pytest.mark.parametrize("leg", ["codex", "grok"])
def test_unconfined_exception_reaches_spawn_through_the_real_resolver(monkeypatch, leg):
    exception = NamedException(
        leg, "unconfined", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1), "fixture",
    )
    monkeypatch.setattr(
        seat_route, "load_route_policy", lambda: policy(exceptions={leg: exception}),
    )
    _production_adapter(monkeypatch)
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        leg, SimpleNamespace(staged_tree_sha256="a" * 64), eligible=True,
        seat_key=f"{leg}:a", env={"PATH": "/nonexistent"},
    )
    assert (route, notices, refusal) == (None, ["seat_filesystem_unconfined"], None)


@pytest.mark.parametrize("leg", ["codex", "grok"])
def test_unconfined_exception_expiry_is_path_entered_with_an_injected_clock(
    monkeypatch, tmp_path, leg,
):
    now = dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc)
    exception = NamedException(
        leg, "unconfined", now + dt.timedelta(minutes=1), "fixture",
    )
    monkeypatch.setattr(
        seat_route, "load_route_policy", lambda: policy(exceptions={leg: exception}),
    )
    monkeypatch.setattr(seat_route, "_now", lambda: now)
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        leg, auth, eligible=True, seat_key=f"{leg}:a", env={},
    )
    assert (route, notices, refusal) == (None, ["seat_filesystem_unconfined"], None)
    monkeypatch.setattr(seat_route, "_now", lambda: now + dt.timedelta(minutes=2))
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        leg, auth, eligible=True, seat_key=f"{leg}:a", env={},
    )
    assert not route.jailed and notices == [] and refusal == "seat_route_exception_expired"
    monkeypatch.setattr(
        panel_invoker, "revalidate_review_isolation_authorization", lambda *a, **k: None,
    )
    monkeypatch.setattr(panel_invoker._sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr(panel_invoker, "_canonical_review_repo_authority", lambda _p: tmp_path)

    class NeverBroker:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("an expired exception launched a provider")

    monkeypatch.setattr(panel_invoker, "ParentUnixBroker", NeverBroker)
    spawned = panel_invoker._default_spawn(
        leg,
        "artifact",
        mode="review",
        model="fixture",
        review_authorization=auth,
        canonical_repo_authority=tmp_path,
        seat_key=f"{leg}:a",
    )
    assert tuple(spawned) == ("DEGRADED", "", "seat_route_exception_expired")


def test_open_egress_exception_expiry_is_path_entered_with_an_injected_clock(monkeypatch):
    profile = dataclasses.replace(
        seat_profiles.profile_for("claude"), credential_present=lambda: True,
        preconditions=(), variant=lambda _env: ("print", None),
    )
    monkeypatch.setitem(seat_profiles._REGISTRY, "claude", profile)
    monkeypatch.setattr(seat_jail, "seat_sandbox_capable", lambda: None)
    monkeypatch.setattr(seat_route, "_projection_for_launch", lambda *_a, **_k: None)
    monkeypatch.setattr(
        seat_jail_autoqualify, "ensure_qualified",
        lambda *a, **k: seat_jail_autoqualify.Outcome(seat_jail_autoqualify.QUALIFIED),
    )
    capacity = Capacity(True)
    monkeypatch.setattr(panel_invoker._seat_uid, "SeatIdCapacity", lambda: capacity)
    now = dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc)
    exception = NamedException(
        "claude", "open egress", now + dt.timedelta(minutes=1), "fixture",
    )
    monkeypatch.setattr(
        seat_route, "load_route_policy", lambda: policy(exceptions={"claude": exception}),
    )
    monkeypatch.setattr(seat_route, "_now", lambda: now)
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "claude", auth, eligible=True, seat_key="claude:a", env={},
    )
    assert route.jailed and notices == [] and refusal is None
    panel_invoker._release_seat_route(route)
    monkeypatch.setattr(seat_route, "_now", lambda: now + dt.timedelta(minutes=2))
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "claude", auth, eligible=True, seat_key="claude:a", env={},
    )
    assert not route.jailed and notices == [] and refusal == "seat_route_exception_expired"


@pytest.mark.parametrize("mode,code", [
    ("native", "seat_native_fill_unavailable"),
    ("native", "gemini_seat_qualification_candidate"),
    ("remote", "seat_capacity_offloaded"),
])
def test_nonlocal_decision_is_published_but_never_runs_locally(
    monkeypatch, tmp_path, mode, code,
):
    from phase_loop_runtime import gemini_heartbeat

    monkeypatch.setattr(gemini_heartbeat, "_CANDIDATE", None)
    decision = RouteDecision(
        leg="gemini", vendor="gemini", mode=mode, code=code, steps=(),
        exception=None, variant=None, qualification_key=None, also=(), lease=None,
    )
    monkeypatch.setattr(seat_route, "resolve", lambda *a, **k: decision)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    board = SimpleNamespace(seats=[
        SimpleNamespace(harness="gemini", seat_key="gemini:a", model="m"),
    ])
    (rendered,) = panel_invoker._seat_launch_modes(
        board, mode="review", review_authorization=auth, base_env={},
    )
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "gemini", auth, eligible=True, seat_key="gemini:a", env={},
    )
    assert (rendered.mode, rendered.code) == (mode, code)
    assert route.decision is decision and notices == []
    assert refusal == seat_jail.refused("identity")

    monkeypatch.setattr(
        panel_invoker, "revalidate_review_isolation_authorization", lambda *a, **k: None,
    )
    monkeypatch.setattr(panel_invoker._sandbox_policy, "staging_root", lambda: tmp_path)
    monkeypatch.setattr(panel_invoker, "_canonical_review_repo_authority", lambda _p: tmp_path)

    class NeverBroker:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("a nonlocal decision entered the local provider branch")

    monkeypatch.setattr(panel_invoker, "ParentUnixBroker", NeverBroker)
    spawned = panel_invoker._default_spawn(
        "gemini",
        "artifact",
        mode="review",
        model="fixture",
        review_authorization=auth,
        canonical_repo_authority=tmp_path,
        seat_key="gemini:a",
    )
    assert tuple(spawned) == ("DEGRADED", "", seat_jail.refused("identity"))
    public = " ".join(seat_jail.NOTICES[seat_jail.refused("identity")]).lower()
    assert all(route_word not in public for route_word in ("remote", "native", "local"))


def test_approved_gemini_heartbeat_executor_keeps_its_native_route(monkeypatch):
    from phase_loop_runtime import gemini_heartbeat

    monkeypatch.setattr(gemini_heartbeat, "_CANDIDATE", None)
    code = "seat_sandbox_unavailable_host"
    decision = RouteDecision(
        leg="gemini", vendor="gemini", mode="native", code=code, steps=(),
        exception=None, variant=None, qualification_key=None, also=(), lease=None,
    )
    monkeypatch.setattr(seat_route, "resolve", lambda *a, **k: decision)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "gemini",
        SimpleNamespace(staged_tree_sha256="a" * 64),
        eligible=True,
        approved_local_native_executor=True,
    )
    assert route.decision is decision
    assert notices == [code] and refusal is None


def test_same_leg_mode_cache_is_keyed_per_seat(monkeypatch):
    codes = {"gemini:a": "seat_egress_start_failed",
             "gemini:b": "seat_egress_integrity_failed"}

    def resolve(route_request, **_kwargs):
        code = codes[route_request.seat_key]
        return RouteDecision(
            leg="gemini", vendor="gemini", mode="degraded", code=code,
            steps=(RouteStep("local", "L7", "failed", code,
                             seat_route.OD10_CLASSES[code]),),
            exception=None, variant=None, qualification_key=None, also=(), lease=None,
        )

    monkeypatch.setattr(seat_route, "resolve", resolve)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    board = SimpleNamespace(seats=[
        SimpleNamespace(harness="gemini", seat_key=key, model="m") for key in codes
    ])
    modes = panel_invoker._seat_launch_modes(
        board, mode="review", review_authorization=auth, base_env={},
    )
    assert {item.seat_key: item.code for item in modes} == codes


def test_native_fill_adapter_uses_the_existing_board_routing(monkeypatch):
    monkeypatch.setattr(panel_invoker, "_under_claude_code", lambda _env=None: True)
    board = SimpleNamespace(seats=[SimpleNamespace(
        harness="claude", seat_key="claude:a", model="m", backing=None,
    )])
    adapter = panel_invoker._NativeFillAdapter(board, {})
    assert adapter.offer("claude:a", "claude")
    assert not adapter.offer("claude:b", "claude")


def test_under_claude_code_keeps_its_current_route_before_the_walk(monkeypatch):
    monkeypatch.setattr(panel_invoker, "_under_claude_code", lambda _env=None: True)
    monkeypatch.setattr(
        seat_route, "resolve",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("resolver entered")),
    )
    board = SimpleNamespace(seats=[SimpleNamespace(
        harness="claude", seat_key="claude:a", model="m", backing=None,
    )])
    (mode,) = panel_invoker._seat_launch_modes(
        board, mode="review",
        review_authorization=SimpleNamespace(staged_tree_sha256="a" * 64),
        base_env={},
    )
    assert (mode.mode, mode.code) == ("native", "under_claude_code")


def test_mode_and_launch_share_one_production_capacity_lease(monkeypatch, ready_gemini):
    capacity = Capacity(True)
    monkeypatch.setattr(panel_invoker._seat_uid, "SeatIdCapacity", lambda: capacity)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    board = SimpleNamespace(seats=[
        SimpleNamespace(harness="gemini", seat_key="gemini:a", model="m"),
    ])
    (rendered,) = panel_invoker._seat_launch_modes(
        board, mode="review", review_authorization=auth, base_env={},
    )
    assert rendered.mode == "jailed" and capacity.calls == 1
    assert capacity.value.released is False
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "gemini", auth, eligible=True, seat_key="gemini:a", env={},
    )
    assert route.decision.lease is capacity.value
    assert notices == [] and refusal is None and capacity.calls == 1
    panel_invoker._release_seat_route(route)
    assert capacity.value.released is True


def test_production_capacity_never_probes_before_the_held_acquire(
    monkeypatch, ready_gemini,
):
    events = []
    attempts = 0

    class Manager:
        def __init__(self, attempt):
            self.attempt = attempt

        def __enter__(self):
            events.append(("enter", self.attempt))
            if self.attempt > 1:
                raise seat_uid.SeatIdsExhausted("probe consumed the only opportunity")
            return 7

        def __exit__(self, *_exc):
            events.append(("exit", self.attempt))

    def lease_seat_id(_count, *, directory=None):
        nonlocal attempts
        attempts += 1
        return Manager(attempts)

    monkeypatch.setattr(seat_uid, "lease_seat_id", lease_seat_id)
    capacity = seat_uid.SeatIdCapacity(count=1)
    monkeypatch.setattr(panel_invoker._seat_uid, "SeatIdCapacity", lambda: capacity)
    monkeypatch.setattr(seat_route, "load_route_policy", lambda: policy())
    panel_invoker._JAILCORE_ROUTE_CACHE.clear()
    auth = SimpleNamespace(staged_tree_sha256="a" * 64)
    board = SimpleNamespace(seats=[
        SimpleNamespace(harness="gemini", seat_key="gemini:a", model="m"),
    ])

    (rendered,) = panel_invoker._seat_launch_modes(
        board, mode="review", review_authorization=auth, base_env={},
    )
    assert rendered.mode == "jailed"
    assert events == [("enter", 1)]
    route, notices, refusal = panel_invoker._seat_route_for_spawn(
        "gemini", auth, eligible=True, seat_key="gemini:a", env={},
    )
    assert route.decision.lease.seat_id == 7
    assert notices == [] and refusal is None and events == [("enter", 1)]
    panel_invoker._release_seat_route(route)
    assert events == [("enter", 1), ("exit", 1)]


def test_matrix_policy_does_not_duplicate_window_exception_filtering(monkeypatch):
    from phase_loop_runtime import seat_window

    row = next(row for row in seat_window.readiness_rows()
               if row["id"] == "vendor:codex").copy()
    row.update(exception="unconfined", expiry="2026-12-04T00:00:00+00:00")
    monkeypatch.setattr(seat_window, "readiness_rows", lambda: [row])
    assert seat_route._matrix_policy().exceptions["codex"].kind == "unconfined"
    assert "profile_for" not in inspect.getsource(seat_route._matrix_policy)
