"""Passive shared-contract constants and mappings; does not activate placement.

A timeout after dispatch is uncertain: release and confirm before overflow.
Unknown leases require kill-to-tombstone recovery; they are never proof of release.
"""
from importlib.resources import files
import json
from types import MappingProxyType

_DEFS = json.loads((files('phase_loop_runtime') / 'contracts/placement/coordinator-v1.schema.json').read_text())['$defs']
ADMISSION_OUTCOMES = tuple(_DEFS['AdmissionOutcome']['enum'])
ERROR_CODES = tuple(_DEFS['ErrorCode']['enum'])
ADMISSION_REASONS = tuple(_DEFS['AdmissionReason']['enum'])
OUTCOME_CODES = MappingProxyType({
    'admitted': None,
    'at_capacity': 'sandbox_placement_at_capacity',
    'refused': 'sandbox_placement_refused',
    'unreachable': 'sandbox_placement_unreachable',
    'timeout': 'sandbox_placement_operation_timeout',
})
COORDINATOR_CODES = MappingProxyType({
    'at_capacity': 'sandbox_placement_at_capacity',
    'owner_mismatch': 'sandbox_placement_identity_mismatch',
    'not_enrolled': 'sandbox_placement_not_enrolled',
    'workload_unsupported': 'sandbox_placement_workload_unsupported',
    'fenced': 'sandbox_placement_lost_after_launch',
    'expired': 'sandbox_placement_lost_after_launch',
    'deadline_exceeded': 'sandbox_placement_operation_timeout',
    'unknown_lease': None,
    # Renew-only, after launch: the lease runs to its current expiry and the run must
    # end before then. Not a placement refusal, so no ladder code.
    'lifetime_exceeded': None,
    # Create-only: the reserved lease still holds capacity, so this is NOT
    # "nothing held". The caller enters releasing (kill to tombstone, confirm).
    'digest_mismatch': None,
    'duplicate_binding': 'sandbox_placement_release_unconfirmed',
    # Listing-only: restart the inventory from page 1. Only a listing that still
    # cannot complete leaves release unconfirmed (decided by the caller).
    'snapshot_expired': None,
    # Phase-dependent: on reserve nothing is held (refused); on create the
    # reservation holds capacity and must be released. The caller decides.
    'invalid_request': None,
    # Revision 7: a typed pre-reservation refusal (nothing reserved or dispatched),
    # so nothing is held and the walk moves on, like an unreachable far end.
    'unavailable': 'sandbox_placement_unreachable',
})


def outcome_code(outcome: str) -> str | None:
    return OUTCOME_CODES[outcome]


def coordinator_code(code: str) -> str | None:
    """Map a code only; callers retain operation context and recovery obligations.

    fenced/expired map to lost-after-launch for an already launched lease.
    unknown_lease, lifetime_exceeded, snapshot_expired, digest_mismatch and
    invalid_request map to None: they are
    handled by operation context, never as a placement outcome. unknown_lease has
    no successful/empty interpretation. An incomplete kill or
    listing always retains release_unconfirmed, irrespective of HTTP status.
    """
    return COORDINATOR_CODES[code]
