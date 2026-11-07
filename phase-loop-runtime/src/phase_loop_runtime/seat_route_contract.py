"""Pure contracts for jailed-seat profiles and route selection.

This module deliberately contains no filesystem or process access.  Runtime
adapters live in :mod:`seat_profiles`, :mod:`seat_route`, and
:mod:`seat_egress_proxy`; importing the frozen shapes is therefore side-effect
free for downstream vendor phases.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Protocol, Sequence


OD10Class = Literal["security", "ordinary"]
RouteMode = Literal["jailed", "unconfined", "remote", "native", "degraded"]
RunKind = Literal["review", "advisory_document", "qualification_candidate"]


@dataclass(frozen=True)
class CredentialDelivery:
    channel: Literal["token_fd", "home_file", "none"]
    scope_evidence: str | None


@dataclass(frozen=True)
class ConfigSurface:
    closed: bool
    planted_paths: tuple[str, ...]


@dataclass(frozen=True)
class ContainmentEvidence:
    credential_scope: str | None
    refresh_detection: str | None
    unlisted_endpoint_refused: str | None
    deferred_to: str | None


@dataclass(frozen=True)
class Precondition:
    name: str
    check: Callable[[], str | None]


@dataclass(frozen=True)
class WindowRows:
    """Profile-owned inputs to the vendor-neutral seat-window kit.

    ``plant_locations`` rows are ``(name, jail_path, host_backing)`` and
    ``tree_rows`` rows are ``(path, role)``.  Keeping these rows as immutable
    data lets later vendors register a profile without changing kit code.
    """

    canonical_record_field: str
    route_record_field: str
    route_literal: str
    plant_locations: tuple[tuple[str, str, str], ...]
    tree_rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class OwnerPaths:
    tree: str
    home: str
    out: str
    provider: str
    bundle_fd: str
    instructions_fd: str
    token_fd: str | None
    seccomp_fd: str
    provider_bind: bool = True
    provider_config: str | None = None
    egress_ca: str | None = None
    egress_proxy: str | None = None
    transport: str | None = None


@dataclass(frozen=True)
class EnvInputs:
    token_fd: int | str | None
    lang: str = "C.UTF-8"
    term: str = "xterm-256color"
    egress_proxy: str | None = None
    egress_ca: str | None = None
    transport: str | None = None


@dataclass(frozen=True)
class ArgvInputs:
    provider_argv0: str
    model: str | None = None
    effort: str | None = None
    output_path: str | None = None
    transport: str | None = None


@dataclass(frozen=True)
class JailProfile:
    leg: str
    vendor: str
    owner_binds: Callable[[OwnerPaths], Sequence[str]]
    env: Callable[[EnvInputs], Mapping[str, str]]
    home_dirs: tuple[str, ...]
    digest_placeholders: Callable[[OwnerPaths], Mapping[str, str]]
    mount_points: Callable[[OwnerPaths], Sequence[str]]
    new_session: bool
    token_fd: bool
    argv: Callable[[ArgvInputs], Sequence[str]]
    projection: Literal["none", "optional", "required"]
    credential: CredentialDelivery
    credential_present: Callable[[], bool]
    credential_missing_code: str
    preconditions: tuple[Precondition, ...]
    recorded_stop: str | None
    config_surface: ConfigSurface
    auth_probe: Callable[[], Literal["healthy", "signed_out", "unavailable"]]
    output_secret_code: str
    containment: ContainmentEvidence
    allowlist_id: str | None
    variant: Callable[[Mapping[str, str]], tuple[str | None, str | None]] | None
    notice_codes: frozenset[str]
    window: WindowRows | None


class SeatLease(Protocol):
    seat_id: int

    def release(self) -> None: ...


class SeatCapacity(Protocol):
    def try_lease(self) -> SeatLease | None: ...


@dataclass(frozen=True)
class NamedException:
    vendor: str
    kind: Literal["unconfined", "open egress"]
    expiry: datetime
    end_condition: str


@dataclass(frozen=True)
class CapacityGrant:
    target: str
    target_class: Literal["owner_controlled", "third_party"]
    host_classes: frozenset[str]
    vendors: frozenset[str]
    probe_set_digest: str
    probe_receipt: str
    activation_refs: Mapping[str, str]


@dataclass(frozen=True)
class RoutePolicy:
    schema: Literal["seat_route_policy.v1"]
    routed_remote: frozenset[tuple[str, str]]
    exceptions: Mapping[str, NamedException]
    capacity_offload: tuple[CapacityGrant, ...] = ()


@dataclass(frozen=True)
class RouteRequest:
    leg: str
    seat_key: str
    host_class: str
    run_kind: RunKind
    staged_tree_approved: bool
    env: Mapping[str, str]


@dataclass(frozen=True)
class RemoteRequest:
    leg: str
    vendor: str
    host_class: str
    trigger: Literal["routed", "descend", "capacity"]
    trigger_code: str


@dataclass(frozen=True)
class RemoteAdmission:
    placed: bool
    code: str
    activation_ref: str | None


class RemoteRung(Protocol):
    def admit(self, request: RemoteRequest) -> RemoteAdmission: ...


class NativeFillRung(Protocol):
    def offer(self, seat_key: str, leg: str) -> bool: ...


@dataclass(frozen=True)
class QualificationKey:
    profile_digest: str
    allowlist_digest: str | None
    falsifier_layout: str
    projection_digest: str | None
    variant: str | None
    host_identity: str


def record_binding(key: QualificationKey) -> Mapping[str, object]:
    """Return the exact fields a v2 qualification record must bind."""
    return MappingProxyType(asdict(key))


def key_digest(key: QualificationKey) -> str:
    payload = json.dumps(dict(record_binding(key)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RouteStep:
    rung: Literal["local", "remote", "native_fill", "degraded"]
    step: str
    outcome: Literal["selected", "failed", "skipped"]
    code: str | None
    od10_class: OD10Class | None


@dataclass(frozen=True)
class RouteDecision:
    leg: str
    vendor: str
    mode: RouteMode
    code: str | None
    steps: tuple[RouteStep, ...]
    exception: NamedException | None
    variant: str | None
    qualification_key: QualificationKey | None
    also: tuple[str, ...]
    lease: SeatLease | None


@dataclass(frozen=True)
class AllowlistRef:
    id: str
    content_digest: str
    request_set: tuple[Mapping[str, object], ...]
    probe_rows: tuple[Mapping[str, object], ...]


DESCEND_CODES = frozenset({
    "seat_sandbox_unavailable_host",
    "seat_sandbox_unavailable_tiocsti",
    "seat_sandbox_unavailable_seat_uid",
    "seat_egress_not_installed",
})
REMOTE_DESCEND_CODES: frozenset[str] = frozenset()
CAPACITY_CODES = frozenset({"seat_local_capacity_exhausted"})


CODES: Mapping[str, tuple[OD10Class, str, str, str]] = MappingProxyType({
    "seat_egress_not_installed": (
        "ordinary", "seat unavailable", "the host egress layer is not installed",
        "run `phase-loop seat-egress install`, then re-run"),
    "seat_egress_integrity_failed": (
        "security", "seat refused", "the installed egress layer did not verify",
        "reinstall with `phase-loop seat-egress install`; report the outcome privately"),
    "seat_egress_tls_unterminated": (
        "security", "seat refused", "the egress layer did not attest its required mode",
        "reinstall the egress layer; report the outcome privately"),
    "seat_egress_start_failed": (
        "ordinary", "seat unavailable", "the verified egress layer did not start",
        "check the private operator log, then reinstall with `phase-loop seat-egress install` or re-run"),
    "seat_route_identity_invalid": (
        "security", "seat refused", "the route identity inputs do not agree",
        "the leg, its profile and its readiness row must name one vendor; report the outcome privately"),
    "seat_egress_allowlist_missing": (
        "ordinary", "seat unavailable", "the profile has no egress allowlist",
        "the vendor phase registers its allowlist; the seat stays degraded until then"),
    "seat_profile_unregistered": (
        "ordinary", "seat unavailable", "the leg has no registered jail profile",
        "the vendor has no jail profile yet; the seat stays degraded until its phase registers one"),
    "seat_route_exception_expired": (
        "ordinary", "seat unavailable", "the named route exception expired",
        "only an owner record in the readiness matrix renews an exception"),
    "seat_local_capacity_exhausted": (
        "ordinary", "seat unavailable", "no local seat id is free",
        "wait for a running seat to finish, then re-run"),
    "seat_route_row_remote": (
        "ordinary", "route skipped", "the readiness matrix routes this vendor remotely",
        "none: the configured remote rung decides the route"),
    "seat_remote_rung_inactive": (
        "ordinary", "route skipped", "the remote rung is not active",
        "none: no remote route is active for this vendor on this host class"),
    "seat_native_fill_unavailable": (
        "ordinary", "route skipped", "the driving session cannot fill this seat",
        "none: the seat remains degraded"),
    "seat_capacity_offloaded": (
        "ordinary", "seat routed remotely", "a current capacity grant admitted the seat",
        "none"),
    "seat_route_policy_ignored": (
        "ordinary", "route policy ignored", "the private route-policy overlay was unusable",
        "fix the host route-policy file's ownership or shape; capacity offload stays off"),
})


_SECURITY_CODES = frozenset({
    "claude_sdk_provenance_refused",
    "claude_sdk_worker_contract_violation",
    "claude_seat_api_key_source",
    "claude_seat_token_in_output",
    "gemini_seat_credential_unusable",
    "gemini_seat_egress_unconfined",
    "gemini_seat_stream_split_unavailable",
    "gemini_seat_subagent_or_unknown_event",
    "gemini_seat_token_in_output",
    "gemini_seat_token_refreshed_in_jail",
    "gemini_seat_token_scope_excess",
    "seat_egress_integrity_failed",
    "seat_egress_tls_unterminated",
    "seat_output_retained_after_teardown",
    "seat_route_identity_invalid",
    "seat_sandbox_egress_opt_out",
    "seat_sandbox_refused:identity",
    "seat_sandbox_refused:output_unsafe",
    "seat_sandbox_refused:stage_changed",
    "seat_sandbox_refused:stage_not_private",
    "seat_sandbox_refused:token_file_unsafe",
    "seat_sandbox_retained_after_teardown",
})


_ORDINARY_CODES = frozenset({
    "agy_image_unqualified", "claude_agent_view_review_unsupported",
    "claude_sdk_dependency_unavailable", "claude_sdk_worker_unavailable",
    "claude_seat_bypass_ack_blocked", "claude_seat_delivery_refused",
    "claude_seat_login_rate_limited", "claude_seat_login_rejected",
    "claude_seat_login_token_awaiting_refresh", "claude_seat_login_token_expired",
    "claude_seat_login_token_expiring", "claude_seat_login_unproven",
    "claude_seat_override_other_subscription", "claude_seat_result_unproven",
    "claude_seat_stream_unsafe", "claude_seat_token_missing",
    "claude_seat_token_rate_limited", "claude_seat_token_rejected",
    "claude_tui_journal_collection_refused", "claude_tui_workspace_trust_blocked",
    "panel_claude_route_invalid", "panel_claude_transport_not_admitted",
    "executor_review_route_unsupported", "gemini_credential_awaiting_refresh",
    "gemini_credential_near_expiry", "gemini_credential_refresh_timeout",
    "gemini_seat_credential_missing", "gemini_seat_egress_unavailable",
    "gemini_seat_profile_unqualified", "gemini_seat_qualification_candidate",
    "gemini_seat_token_expired", "grok_tool_surface_unverified", "leg_auth_signed_out",
    "leg_auth_unavailable", "leg_exec_record_unavailable", "leg_execution_failed",
    "native_seat_unavailable_heartbeat_only", "sandbox_placement_at_capacity",
    "sandbox_placement_backend_unregistered", "sandbox_placement_budget_spent",
    "sandbox_placement_capability_undeclared", "sandbox_placement_capability_unmet",
    "sandbox_placement_capacity_exhausted", "sandbox_placement_code_invalid",
    "sandbox_placement_driver_unavailable", "sandbox_placement_end_reached",
    "sandbox_placement_identity_mismatch", "sandbox_placement_local_release_unconfirmed",
    "sandbox_placement_lost_after_launch", "sandbox_placement_not_enrolled",
    "sandbox_placement_operation_timeout", "sandbox_placement_plugin_unavailable",
    "sandbox_placement_ref_invalid", "sandbox_placement_refused",
    "sandbox_placement_release_unconfirmed", "sandbox_placement_required_unavailable",
    "sandbox_placement_unreachable", "sandbox_placement_workload_unsupported",
    "seat_bind_source_unavailable", "seat_broker_socket_unavailable",
    "seat_cli_adapter_missing", "seat_cli_platform_unsupported",
    "seat_cli_qualification_failed", "seat_cli_qualification_store_unsafe",
    "seat_cli_qualification_unavailable", "seat_cli_unqualified",
    "seat_filesystem_unconfined", "seat_filtered_egress_unavailable",
    "seat_identity_unverified", "seat_jail_qualification_failed",
    "seat_keyring_unavailable", "seat_launch_owner_required",
    "seat_output_inside_readonly_input", "seat_output_path_unavailable",
    "seat_owner_unavailable", "seat_placement_waiting", "seat_profile_unavailable",
    "seat_resource_caps_unavailable",
    "seat_prompt_over_cap", "seat_provider_unavailable", "seat_sandbox_not_staged",
    "seat_sandbox_refused:gemini_credential_unsafe", "seat_sandbox_refused:jail_build",
    "seat_sandbox_refused:jail_unqualified", "seat_sandbox_refused:namespace",
    "seat_sandbox_refused:pass_store_unsafe", "seat_sandbox_refused:preseed",
    "seat_sandbox_root_fell_back", "seat_sandbox_root_unapplied",
    "seat_sandbox_unavailable_host", "seat_sandbox_unavailable_seat_uid",
    "seat_sandbox_unavailable_tiocsti", "seat_staging_below_floor", "seat_tool_denied",
    "seat_tool_sandbox_unavailable", "under_claude_code",
    *(code for code, entry in CODES.items() if entry[0] == "ordinary"),
})


OD10_CLASSES: Mapping[str, OD10Class] = MappingProxyType({
    **{code: "ordinary" for code in _ORDINARY_CODES},
    **{code: "security" for code in _SECURITY_CODES},
})


def _validate_contract(
    codes: Mapping[str, tuple[OD10Class, str, str, str]] = CODES,
    classes: Mapping[str, OD10Class] = OD10_CLASSES,
) -> None:
    missing = set(codes) - set(classes)
    if missing:
        raise RuntimeError(f"unclassified seat route codes: {sorted(missing)}")
    overlap = _SECURITY_CODES & _ORDINARY_CODES
    if overlap:
        raise RuntimeError(f"multiply classified seat route codes: {sorted(overlap)}")


_validate_contract()


def validate_route_policy(overlay: Mapping[str, object]) -> tuple[CapacityGrant, ...]:
    """Validate the only operator overlay JAILCORE accepts.

    Exceptions, routed rows, and descend sets are packaged inputs and cannot be
    replaced by the host overlay.
    """
    if not isinstance(overlay, Mapping) or set(overlay) != {"capacity_offload"}:
        raise ValueError("route-policy overlay may set capacity_offload only")
    raw_grants = overlay["capacity_offload"]
    if not isinstance(raw_grants, list):
        raise ValueError("capacity_offload must be a list")
    grants: list[CapacityGrant] = []
    required = {
        "target", "target_class", "host_classes", "vendors", "probe_set_digest",
        "probe_receipt", "activation_refs",
    }
    for raw in raw_grants:
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ValueError("capacity grant has an invalid shape")
        target = raw["target"]
        target_class = raw["target_class"]
        host_classes = raw["host_classes"]
        vendors = raw["vendors"]
        probe_set_digest = raw["probe_set_digest"]
        probe_receipt = raw["probe_receipt"]
        activation_refs = raw["activation_refs"]
        if not isinstance(target, str) or not target:
            raise ValueError("capacity grant target is required")
        if target_class not in {"owner_controlled", "third_party"}:
            raise ValueError("capacity grant target_class is invalid")
        if (not isinstance(host_classes, list) or not host_classes
                or any(not isinstance(item, str) or not item for item in host_classes)
                or "*" in host_classes):
            raise ValueError("capacity grant host_classes are invalid")
        if (not isinstance(vendors, list) or not vendors
                or any(not isinstance(item, str) or not item for item in vendors)
                or "*" in vendors):
            raise ValueError("capacity grant vendors are invalid")
        if not isinstance(probe_set_digest, str) or not probe_set_digest:
            raise ValueError("capacity grant probe_set_digest is required")
        if not isinstance(probe_receipt, str) or not probe_receipt:
            raise ValueError("capacity grant probe_receipt is required")
        if (not isinstance(activation_refs, Mapping)
                or any(not isinstance(key, str) or not isinstance(value, str)
                       for key, value in activation_refs.items())):
            raise ValueError("capacity grant activation_refs are invalid")
        grants.append(CapacityGrant(
            target=target,
            target_class=target_class,
            host_classes=frozenset(host_classes),
            vendors=frozenset(vendors),
            probe_set_digest=probe_set_digest,
            probe_receipt=probe_receipt,
            activation_refs=MappingProxyType(dict(activation_refs)),
        ))
    return tuple(grants)
