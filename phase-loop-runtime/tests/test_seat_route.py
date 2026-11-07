from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from types import MappingProxyType, SimpleNamespace

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


def test_mode_line_codes_close_the_od10_table():
    from phase_loop_runtime.seat_route_contract import OD10_CLASSES

    assert seat_route.mode_line_codes() == frozenset(OD10_CLASSES)


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
    monkeypatch.setattr(
        panel_invoker, "_JAILCORE_LEGACY_DECIDER", panel_invoker._seat_jail.decide_seat_route,
    )
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
