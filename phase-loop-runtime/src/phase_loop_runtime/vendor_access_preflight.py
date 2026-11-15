"""Unregistered updater preflight, exercised only with synthetic inputs.

A future trusted loader must authenticate the owner-written activation record.
This module neither loads that record nor overrides deployment holds. Passing
preflight is not seat readiness, permission to activate, or a publication receipt.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Callable, Literal

from .vendor_access_contract import VendorBinding


@dataclass(frozen=True)
class ActivationRecord:
    binding_sha256: str
    d2_ref: str
    d3_ref: str
    d5_ref: str


@dataclass(frozen=True)
class ProviderPreflight:
    workspace: str
    provider: str
    profile_id: str
    profile_sha256: str
    resource_version: int
    gateway_refresh_enabled: bool


@dataclass(frozen=True)
class PreflightResult:
    state: Literal["held", "gateway_refused", "gateway_unavailable", "eligible"]
    code: str
    resource_version: int | None = None


def binding_digest(binding: VendorBinding) -> str:
    """Bind activation to the whole non-secret binding, not just its display ID."""
    if type(binding) is not VendorBinding:
        raise ValueError("invalid_binding")
    encoded = json.dumps(asdict(binding), sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reference(value: str) -> bool:
    return (type(value) is str and 0 < len(value) <= 4096
            and value.strip() == value
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def activation_refusal(binding: VendorBinding, activation: ActivationRecord | None) -> str | None:
    """Shared no-I/O hold gate; does not authenticate an activation record."""
    if type(activation) is not ActivationRecord:
        return "activation_absent_or_invalid"
    if not all(_reference(ref) for ref in
               (activation.d2_ref, activation.d3_ref, activation.d5_ref)):
        return "activation_references_invalid"
    if (type(binding) is not VendorBinding
            or type(binding.profile_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', binding.profile_sha256) is None):
        return "profile_pin_invalid"
    try:
        digest = binding_digest(binding)
    except (TypeError, ValueError, UnicodeError):
        return "binding_invalid"
    if type(activation.binding_sha256) is not str or activation.binding_sha256 != digest:
        return "activation_binding_mismatch"
    return None


def preflight(
    binding: VendorBinding,
    activation: ActivationRecord | None,
    inspect_provider: Callable[[VendorBinding], ProviderPreflight],
) -> PreflightResult:
    """One metadata inspection at most; absent/invalid activation performs no I/O.

    inspect_provider must be a bounded, metadata-only transport operation. The
    source adapter and credential mutation are intentionally not accepted here.
    Every later push must repeat profile/refresh checks and use fresh nonzero CAS.
    """
    refusal = activation_refusal(binding, activation)
    if refusal is not None:
        return PreflightResult("held", refusal)
    try:
        observed = inspect_provider(binding)
    except Exception:
        # Do not retain transport exceptions or their potentially sensitive payloads.
        return PreflightResult("gateway_unavailable", "metadata_unavailable")
    if type(observed) is not ProviderPreflight:
        return PreflightResult("gateway_refused", "metadata_invalid")
    if (not all(type(value) is str for value in
                (observed.workspace, observed.provider, observed.profile_id,
                 observed.profile_sha256))
            or (observed.workspace, observed.provider, observed.profile_id,
                observed.profile_sha256) !=
               (binding.workspace, binding.provider, binding.profile_id,
                binding.profile_sha256)):
        return PreflightResult("gateway_refused", "profile_binding_mismatch")
    if observed.gateway_refresh_enabled is not False:
        return PreflightResult("gateway_refused", "gateway_refresh_not_disabled")
    if (type(observed.resource_version) is not int
            or not 0 < observed.resource_version < 2**64):
        return PreflightResult("gateway_refused", "resource_version_invalid")
    return PreflightResult("eligible", "metadata_checked", observed.resource_version)
