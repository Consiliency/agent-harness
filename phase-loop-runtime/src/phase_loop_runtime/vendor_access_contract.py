"""Offline vendor-access data contracts. No resolver, transport or registration.

These objects are internal design inputs, not serialized OpenShell profiles or
remote credential rows. AccessSnapshot is sensitive even though repr is redacted;
callers must never serialize it (including dataclasses.asdict).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

AuthKind = Literal["subscription_oauth", "api_key"]
State = Literal[
    "held", "unbound", "source_unavailable", "schema_unknown", "ambiguous_account",
    "identity_mismatch", "awaiting_owner_renewal", "persisted_pending_application",
    "fresh", "expired", "gateway_unavailable", "gateway_refused",
    "revocation_pending", "source_change_unverified", "revoked_at_source",
    "unbound_by_owner",
]


@dataclass(frozen=True)
class VendorBinding:
    binding_id: str
    vendor: str
    harness: str
    auth_kind: AuthKind
    source_host: str
    source_kind: Literal["native_store", "onepassword", "local_key"]
    source_ref: str
    billing_route: str
    source_home: str | None
    source_relpath: str
    identity_digest: str
    workspace: str
    provider: str
    credential_key: str
    profile_id: str
    profile_sha256: str
    floor_s: int
    owner_decision_ref: str


@dataclass(frozen=True)
class AccessSnapshot:
    identity_digest: str
    access: bytes = field(repr=False)
    expires_at: float | None
    source_generation: str | None = None
    claims: tuple[tuple[str, str], ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class TargetReceipt:
    sandbox_id: str
    supervisor_session_id: str
    attachment_epoch: str  # Opaque gateway identity; compare for equality only.
    outcome: Literal["pending", "applied", "refused"]


@dataclass(frozen=True)
class BindingStatus:
    binding_id: str
    vendor: str
    provider: str
    workspace: str
    state: State
    expires_at: float | None
    pushed_at: float | None
    mutation_id: str | None
    sandbox_receipts: tuple[TargetReceipt, ...]
    code: str | None
    observed_at: float


class SourceRefused(Exception):
    """Adapter refusal containing only a fixed diagnostic code."""

    _CODES = frozenset({
        "source_unavailable", "schema_unknown", "ambiguous_account", "expired",
        "awaiting_owner_renewal", "identity_mismatch", "source_change_unverified",
    })

    def __init__(self, code: str):
        self.code = code if type(code) is str and code in self._CODES else "source_unavailable"
        super().__init__(self.code)


class SourceAdapter(Protocol):
    def read(self, binding: VendorBinding) -> AccessSnapshot: ...
