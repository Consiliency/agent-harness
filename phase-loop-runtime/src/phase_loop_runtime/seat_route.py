"""JAILCORE's one pre-launch route resolver and private policy loader."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from types import SimpleNamespace

from . import claude_seat_transport, seat_jail
from .seat_route_contract import (
    CODES,
    DESCEND_CODES,
    OD10_CLASSES,
    REMOTE_DESCEND_CODES,
    CapacityGrant,
    NamedException,
    NativeFillRung,
    RemoteAdmission,
    RemoteRequest,
    RemoteRung,
    RouteDecision,
    RoutePolicy,
    RouteRequest,
    RouteStep,
    SeatCapacity,
    validate_route_policy,
)


MODE_REMOTE = "remote"
_POLICY_NAME = "seat-route-policy.json"
_POLICY_CAP = 256 * 1024
_RECEIPT_CAP = 256 * 1024
_IGNORED_POLICIES: dict[int, RoutePolicy] = {}


def mode_line_codes() -> frozenset[str]:
    """The closed set which may appear on a seat mode line."""
    return frozenset({
        *seat_jail.NOTICE_CODES,
        *claude_seat_transport.CODES,
        *CODES,
        "panel_claude_route_invalid",
        "panel_claude_transport_not_admitted",
    })


if set(mode_line_codes()) != set(OD10_CLASSES):
    missing = set(mode_line_codes()) - set(OD10_CLASSES)
    extra = set(OD10_CLASSES) - set(mode_line_codes())
    raise RuntimeError(
        f"seat route OD-10 closure mismatch: missing={sorted(missing)} extra={sorted(extra)}"
    )


class _InactiveRemoteRung:
    def admit(self, _request: RemoteRequest) -> RemoteAdmission:
        return RemoteAdmission(False, "seat_remote_rung_inactive", None)


INACTIVE_REMOTE_RUNG: RemoteRung = _InactiveRemoteRung()


class _NoNativeFill:
    def offer(self, _seat_key: str, _leg: str) -> bool:
        return False


NO_NATIVE_FILL: NativeFillRung = _NoNativeFill()


def _utc(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _matrix_policy() -> RoutePolicy:
    from . import seat_window
    from .seat_profiles import profile_for, registered_legs

    vendor_rows: dict[str, list[Mapping[str, object]]] = {}
    for row in seat_window.readiness_rows():
        if row.get("kind") == "vendor" and isinstance(row.get("vendor"), str):
            vendor_rows.setdefault(str(row["vendor"]), []).append(row)
    exceptions: dict[str, NamedException] = {}
    routed: set[tuple[str, str]] = set()
    for vendor, rows in vendor_rows.items():
        if len(rows) != 1:
            continue
        row = rows[0]
        profile = next((profile_for(leg) for leg in registered_legs() if profile_for(leg) is not None
                        and profile_for(leg).vendor == vendor), None)
        kind = row.get("exception")
        expiry = _utc(row.get("expiry"))
        # Registered profiles never retain the filesystem-unconfined exception, and a
        # profile with an allowlist never retains open egress.
        exception_allowed = not (
            profile is not None and (
                kind == "unconfined"
                or kind == "open egress" and profile.allowlist_id is not None
            )
        )
        if kind in {"unconfined", "open egress"} and expiry is not None and exception_allowed:
            exceptions[vendor] = NamedException(
                vendor=vendor,
                kind=kind,
                expiry=expiry,
                end_condition=str(row.get("end_condition") or "row window or owning phase exit"),
            )
        if row.get("status") == "remote-pending":
            classes = row.get("host_classes")
            if isinstance(classes, list):
                routed.update((vendor, item) for item in classes if isinstance(item, str))
    return RoutePolicy(
        schema="seat_route_policy.v1",
        routed_remote=frozenset(routed),
        exceptions=MappingProxyType(exceptions),
        capacity_offload=(),
    )


def _policy_path() -> Path:
    return seat_jail.state_home() / "phase-loop" / _POLICY_NAME


def load_route_policy(path: Path | None = None) -> RoutePolicy:
    """Load packaged matrix policy plus the capacity-only private host overlay.

    The overlay JSON itself has no ``schema`` field: the only accepted key is
    ``capacity_offload``.  Missing input means the shipped disabled state.
    """
    base = _matrix_policy()
    target = path or _policy_path()
    if not target.exists():
        return base
    ignored = False
    try:
        directory = target.parent
        if seat_jail.pass_store_dir_problem(directory) is not None:
            raise ValueError("unsafe route-policy directory")
        raw = seat_jail._read_private_file(directory, target.name, _POLICY_CAP)
        if raw is None:
            raise ValueError("unsafe route-policy file")
        overlay = json.loads(raw)
        grants = validate_route_policy(overlay)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        grants = ()
        ignored = True
    result = RoutePolicy(
        schema=base.schema,
        routed_remote=base.routed_remote,
        exceptions=base.exceptions,
        capacity_offload=grants,
    )
    if ignored:
        # Keep the object alive as well as its id: CPython may otherwise reuse an id and
        # attach the sibling notice to a later valid policy.
        _IGNORED_POLICIES[id(result)] = result
    return result


def _step(rung: str, name: str, outcome: str, code: str | None) -> RouteStep:
    return RouteStep(
        rung=rung,  # type: ignore[arg-type]
        step=name,
        outcome=outcome,  # type: ignore[arg-type]
        code=code,
        od10_class=None if code is None else OD10_CLASSES[code],
    )


def _decision(
    request: RouteRequest,
    vendor: str,
    mode: str,
    code: str | None,
    steps: list[RouteStep],
    *,
    exception: NamedException | None = None,
    variant: str | None = None,
    qualification_key=None,
    also: tuple[str, ...] = (),
    lease=None,
) -> RouteDecision:
    return RouteDecision(
        leg=request.leg,
        vendor=vendor,
        mode=mode,  # type: ignore[arg-type]
        code=code,
        steps=tuple(steps),
        exception=exception,
        variant=variant,
        qualification_key=qualification_key,
        also=also,
        lease=lease,
    )


def _vendor_identity(leg: str) -> tuple[str | None, str | None]:
    from . import seat_window
    from .seat_profiles import profile_for

    profile = profile_for(leg)
    rows = [row for row in seat_window.readiness_rows()
            if row.get("kind") == "vendor" and row.get("vendor") == (
                profile.vendor if profile is not None else leg
            )]
    if profile is None and not rows:
        return None, "seat_profile_unregistered"
    if profile is not None and (
        len(rows) != 1 or rows[0].get("vendor") != profile.vendor
    ):
        return profile.vendor, "seat_route_identity_invalid"
    if len(rows) != 1:
        return None, "seat_route_identity_invalid"
    return str(rows[0]["vendor"]), None


def _local_failure(
    request: RouteRequest,
    vendor: str,
    code: str,
    step_name: str,
    *,
    exception: NamedException | None = None,
    variant: str | None = None,
    qualification_key=None,
    also: tuple[str, ...] = (),
) -> RouteDecision:
    return _decision(
        request,
        vendor,
        "degraded",
        code,
        [_step("local", step_name, "failed", code)],
        exception=exception,
        variant=variant,
        qualification_key=qualification_key,
        also=also,
    )


def _walk_later_rungs(
    request: RouteRequest,
    vendor: str,
    trigger: str,
    trigger_code: str,
    *,
    remote: RemoteRung,
    native: NativeFillRung,
    initial: list[RouteStep],
    also: tuple[str, ...],
) -> RouteDecision:
    admission = remote.admit(RemoteRequest(
        leg=request.leg,
        vendor=vendor,
        host_class=request.host_class,
        trigger=trigger,  # type: ignore[arg-type]
        trigger_code=trigger_code,
    ))
    if admission.placed:
        return _decision(
            request, vendor, MODE_REMOTE, admission.code,
            [*initial, _step("remote", "R", "selected", admission.code)],
            also=also,
        )
    steps = [*initial, _step("remote", "R", "skipped", admission.code)]
    if admission.code not in REMOTE_DESCEND_CODES and admission.code != "seat_remote_rung_inactive":
        return _decision(request, vendor, "degraded", admission.code,
                         [*steps, _step("degraded", "D", "selected", admission.code)],
                         also=also)
    if native.offer(request.seat_key, request.leg):
        return _decision(
            request, vendor, "native", trigger_code,
            [*steps, _step("native_fill", "N", "selected", trigger_code)],
            also=also,
        )
    steps.append(_step("native_fill", "N", "skipped", "seat_native_fill_unavailable"))
    code = trigger_code if trigger != "routed" else admission.code
    return _decision(
        request, vendor, "degraded", code,
        [*steps, _step("degraded", "D", "selected", code)],
        also=also,
    )


def _receipt_root() -> Path:
    return seat_jail.state_home() / "phase-loop" / "seat-remote-probes"


def _grant_current(grant: CapacityGrant, vendor: str, *, now: dt.datetime) -> bool:
    if grant.target_class == "third_party" and not grant.activation_refs.get(vendor):
        return False
    root = _receipt_root()
    if seat_jail.pass_store_dir_problem(root) is not None:
        return False
    name = grant.probe_receipt
    if Path(name).name != name:
        return False
    receipt = seat_jail._parse_json(seat_jail._read_private_file(root, f"{name}.json", _RECEIPT_CAP))
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema", "target", "target_class", "probe_set_digest", "result",
        "observed_at", "expires_at", "evidence_sha256",
    }:
        return False
    if (
        receipt.get("schema") != "seat_remote_probe_receipt.v1"
        or receipt.get("target") != grant.target
        or receipt.get("target_class") != grant.target_class
        or receipt.get("probe_set_digest") != grant.probe_set_digest
        or receipt.get("result") != "pass"
    ):
        return False
    observed = _utc(receipt.get("observed_at"))
    expires = _utc(receipt.get("expires_at"))
    if observed is None or expires is None or not observed <= now < expires:
        return False
    evidence = seat_jail._read_private_file(root, f"{name}.evidence.json", _RECEIPT_CAP)
    digest = receipt.get("evidence_sha256")
    return (isinstance(digest, str) and evidence is not None
            and hashlib.sha256(evidence).hexdigest() == digest)


def _capacity_grant(
    policy: RoutePolicy, vendor: str, host_class: str, *, now: dt.datetime,
) -> CapacityGrant | None:
    matches = [grant for grant in policy.capacity_offload
               if vendor in grant.vendors and host_class in grant.host_classes
               and _grant_current(grant, vendor, now=now)]
    return matches[0] if len(matches) == 1 else None


def _projection_for_launch(profile, env: Mapping[str, str]):
    """Resolve TEAMHOST's selected subject and return only its key-bound projection."""
    from .executable_dependency_startup import current_dependency_for_provider
    from .seat_qualification_key import admit_profile_projection
    from .seat_subject import open_managed_authority, resolve_seat_subject

    subject = resolve_seat_subject(profile.leg, env)
    current = current_dependency_for_provider(profile.leg)
    if current is not None:
        return admit_profile_projection(profile, current)
    if subject.source != "managed_release":
        return admit_profile_projection(profile, None)
    descriptor, expected = open_managed_authority(subject)
    admitted = None
    try:
        admitted = admit_profile_projection(profile, SimpleNamespace(
            requirement=subject.requirement,
            borrowed_authority_fd=descriptor,
            expected_authority_sha256=expected,
        ))
        if admitted is None:
            return None
        return SimpleNamespace(projection_digest=admitted.projection_digest)
    finally:
        if admitted is not None:
            admitted.close()
        os.close(descriptor)


def resolve(
    request: RouteRequest,
    *,
    policy: RoutePolicy,
    remote: RemoteRung,
    native: NativeFillRung,
    capacity: SeatCapacity,
) -> RouteDecision:
    """Walk L0-L9 once, then only the explicitly admitted later rungs."""
    from . import sandbox_egress, seat_egress_proxy, seat_jail_autoqualify
    from .seat_profiles import profile_for
    from .seat_qualification_key import key_for_launch

    also = (("seat_route_policy_ignored",)
            if _IGNORED_POLICIES.get(id(policy)) is policy else ())
    vendor, identity_code = _vendor_identity(request.leg)
    if identity_code is not None:
        return _local_failure(request, vendor or request.leg, identity_code, "L1", also=also)
    assert vendor is not None
    profile = profile_for(request.leg)

    if request.run_kind == "advisory_document":
        return _decision(request, vendor, "unconfined", "seat_sandbox_not_staged", [], also=also)
    if request.run_kind == "qualification_candidate":
        return _decision(request, vendor, "native", "gemini_seat_qualification_candidate", [],
                         also=also)

    if (vendor, request.host_class) in policy.routed_remote:
        return _walk_later_rungs(
            request, vendor, "routed", "seat_route_row_remote",
            remote=remote, native=native,
            initial=[_step("local", "L", "skipped", "seat_route_row_remote")],
            also=also,
        )

    if not request.staged_tree_approved:
        return _local_failure(request, vendor, "seat_sandbox_not_staged", "L0", also=also)
    exception = policy.exceptions.get(vendor)
    now = dt.datetime.now(dt.timezone.utc)
    if profile is None:
        if exception is not None and exception.kind == "unconfined":
            if now < exception.expiry:
                return _decision(
                    request, vendor, "unconfined", "seat_filesystem_unconfined",
                    [_step("local", "L1", "selected", "seat_filesystem_unconfined")],
                    exception=exception, also=also,
                )
            return _local_failure(
                request, vendor, "seat_route_exception_expired", "L1",
                exception=exception, also=also,
            )
        return _local_failure(request, vendor, "seat_profile_unregistered", "L1", also=also)
    if profile.recorded_stop is not None:
        return _local_failure(request, vendor, profile.recorded_stop, "L2", also=also)
    code = seat_jail.seat_sandbox_capable()
    if code is not None:
        if code in DESCEND_CODES:
            return _walk_later_rungs(
                request, vendor, "descend", code,
                remote=remote, native=native,
                initial=[_step("local", "L3", "failed", code)], also=also,
            )
        return _local_failure(request, vendor, code, "L3", also=also)
    variant = None
    if profile.variant is not None:
        variant, code = profile.variant(request.env)
        if code is not None:
            return _local_failure(request, vendor, code, "L4", also=also)
    if not profile.credential_present():
        return _local_failure(
            request, vendor, profile.credential_missing_code, "L5",
            variant=variant, also=also,
        )
    for precondition in profile.preconditions:
        code = precondition.check()
        if code is not None:
            return _local_failure(
                request, vendor, code, "L6", variant=variant, also=also,
            )

    allowlist_digest = None
    if profile.allowlist_id is None:
        if exception is None or exception.kind != "open egress":
            return _local_failure(
                request, vendor, "seat_egress_allowlist_missing", "L7",
                variant=variant, also=also,
            )
        if now >= exception.expiry:
            return _local_failure(
                request, vendor, "seat_route_exception_expired", "L7",
                exception=exception, variant=variant, also=also,
            )
    else:
        if not sandbox_egress.egress_required():
            return _local_failure(
                request, vendor, "seat_sandbox_egress_opt_out", "L7",
                variant=variant, also=also,
            )
        code = seat_egress_proxy.unavailable_code()
        if code is not None:
            if code in DESCEND_CODES:
                return _walk_later_rungs(
                    request, vendor, "descend", code,
                    remote=remote, native=native,
                    initial=[_step("local", "L7", "failed", code)], also=also,
                )
            return _local_failure(
                request, vendor, code, "L7", variant=variant, also=also,
            )
        try:
            allowlist_digest = seat_egress_proxy.allowlist_ref(
                profile.allowlist_id
            ).content_digest
        except seat_egress_proxy.EgressLayerUnavailable as exc:
            return _local_failure(
                request, vendor, exc.code, "L7", variant=variant, also=also,
            )

    try:
        projection = _projection_for_launch(profile, request.env)
    except FileNotFoundError:
        return _local_failure(
            request, vendor, "seat_provider_unavailable", "L6",
            variant=variant, also=also,
        )
    except Exception:
        return _local_failure(
            request, vendor, "seat_route_identity_invalid", "L6",
            variant=variant, also=also,
        )
    qualification_key = key_for_launch(
        profile,
        variant=variant,
        allowlist_digest=allowlist_digest,
        projection=projection,
    )
    outcome = seat_jail_autoqualify.ensure_qualified(
        profile.leg,
        qualification_key=qualification_key,
    )
    if not outcome.qualified:
        reason = seat_jail.pass_record_verdict(qualification_key)[1]
        code = ("seat_sandbox_refused:pass_store_unsafe"
                if reason.startswith("store_unsafe:")
                else "seat_jail_qualification_failed"
                if outcome.reason is not None
                else "seat_sandbox_refused:jail_unqualified")
        return _local_failure(
            request, vendor, code, "L8", variant=variant,
            qualification_key=qualification_key, also=also,
        )

    lease = capacity.try_lease()
    if lease is None:
        code = "seat_local_capacity_exhausted"
        initial = [_step("local", "L9", "failed", code)]
        grant = _capacity_grant(policy, vendor, request.host_class, now=now)
        if grant is not None:
            admission = remote.admit(RemoteRequest(
                request.leg, vendor, request.host_class, "capacity", code,
            ))
            if admission.placed:
                return _decision(
                    request, vendor, MODE_REMOTE, "seat_capacity_offloaded",
                    [*initial, _step("remote", "R", "selected", admission.code)],
                    variant=variant, qualification_key=qualification_key,
                    also=also,
                )
        return _decision(
            request, vendor, "degraded", code,
            [*initial, _step("degraded", "D", "selected", code)],
            variant=variant, qualification_key=qualification_key, also=also,
        )
    return _decision(
        request, vendor, "jailed", None,
        [_step("local", "L9", "selected", None)],
        variant=variant, qualification_key=qualification_key, also=also, lease=lease,
    )


__all__ = [
    "INACTIVE_REMOTE_RUNG", "MODE_REMOTE", "NO_NATIVE_FILL", "load_route_policy",
    "mode_line_codes", "resolve",
]
