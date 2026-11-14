"""Pure offline publication decisions; no source reads, writes or registration.

The caller supplies a process-private HMAC key and the last *acknowledged*
fingerprint, never a last-attempt fingerprint. Restart loses that comparison
state and requires reconciliation. A publish decision is not permission or a
request: fresh preflight, writer authority, durable pending-state checks and
source revalidation at the publication boundary remain caller obligations.
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import math

from .vendor_access_contract import AccessSnapshot, VendorBinding
from .vendor_access_preflight import binding_digest


@dataclass(frozen=True)
class PublicationDecision:
    action: str
    code: str
    fingerprint: bytes | None = field(default=None, repr=False)


def _fingerprint(binding, snapshot, key, now):
    if (type(binding) is not VendorBinding or type(snapshot) is not AccessSnapshot
            or type(key) is not bytes or len(key) != 32
            or type(now) not in (int, float) or not math.isfinite(now)
            or type(binding.floor_s) is not int or binding.floor_s < 0
            or snapshot.identity_digest != binding.identity_digest
            or type(snapshot.access) is not bytes or not 1 <= len(snapshot.access) <= 16384
            or any(c < 33 or c > 126 for c in snapshot.access)
            or type(snapshot.expires_at) not in (int, float)
            or not math.isfinite(snapshot.expires_at)
            or snapshot.expires_at <= now or snapshot.expires_at < now + binding.floor_s
            or snapshot.source_generation is not None or snapshot.claims != ()):
        raise ValueError('source_unverified')
    # This first slice supports the consistent, single-source subscription
    # snapshot only. An optional native generation is not an ordering clock.
    if binding.auth_kind != 'subscription_oauth':
        raise ValueError('source_unverified')
    header = json.dumps([binding_digest(binding), float(snapshot.expires_at)],
                        separators=(',', ':'), allow_nan=False).encode()
    return hmac.digest(key, header + b'\0' + snapshot.access, hashlib.sha256)


def publication_decision(binding, captured, current, *, key, now,
                         revocation_pending, acknowledged_fingerprint=None):
    """Compare freshly re-read source with captured source, then acknowledged state.

    Pending revocation dominates even missing/invalid source. No result changes
    the acknowledged state or clears a tombstone. Fingerprints include binding,
    expiry and access; equal credentials with changed expiry require publication.
    Failures expose only fixed codes. No source token is returned or retained.
    """
    if type(revocation_pending) is not bool:
        return PublicationDecision('hold', 'pending_state_unverified')
    if revocation_pending:
        return PublicationDecision('revoke', 'revocation_pending')
    if acknowledged_fingerprint is not None and (
            type(acknowledged_fingerprint) is not bytes or len(acknowledged_fingerprint) != 32):
        return PublicationDecision('hold', 'acknowledged_state_invalid')
    try:
        before = _fingerprint(binding, captured, key, now)
        after = _fingerprint(binding, current, key, now)
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return PublicationDecision('hold', 'source_unverified')
    if not hmac.compare_digest(before, after):
        return PublicationDecision('hold', 'source_change_unverified')
    if acknowledged_fingerprint is not None and hmac.compare_digest(after, acknowledged_fingerprint):
        return PublicationDecision('unchanged', 'acknowledged_value_unchanged')
    return PublicationDecision('publish', 'source_revalidated', after)
