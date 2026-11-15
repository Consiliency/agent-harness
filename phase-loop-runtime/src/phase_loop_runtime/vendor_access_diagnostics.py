"""Offline, non-authorizing status diagnostics for pinned OpenShell v0.1.7.

Consumes protobuf JSON with preserved field names, not unbounded wire input.
No observation/session evidence, authorization, completion, or pending-state
mutation is produced. Unknown enum values fail closed. Free-text errors and
unrecognized fields are never retained. Pin: 5d25211b25a8fc887e8d5c606d57d6ab22f1d76c.
"""
from dataclasses import dataclass

from .vendor_access_response import status_receipt_matches

PROVIDERREADINESSSTATE = frozenset(('PROVIDER_READINESS_STATE_UNSPECIFIED', 'PROVIDER_READINESS_STATE_PERSISTED', 'PROVIDER_READINESS_STATE_PENDING', 'PROVIDER_READINESS_STATE_READY', 'PROVIDER_READINESS_STATE_WITHHELD', 'PROVIDER_READINESS_STATE_REVOKED', 'PROVIDER_READINESS_STATE_FAILED', 'PROVIDER_READINESS_STATE_SUPERSEDED'))
PROVIDERREADINESSREASON = frozenset(('PROVIDER_READINESS_REASON_UNSPECIFIED', 'PROVIDER_READINESS_REASON_WAITING_FOR_SUPERVISOR', 'PROVIDER_READINESS_REASON_WAITING_FOR_CREDENTIALS', 'PROVIDER_READINESS_REASON_WAITING_FOR_POLICY', 'PROVIDER_READINESS_REASON_WAITING_FOR_PROCESS', 'PROVIDER_READINESS_REASON_UNSUPPORTED_SUPERVISOR', 'PROVIDER_READINESS_REASON_CREDENTIALS_WITHHELD', 'PROVIDER_READINESS_REASON_CREDENTIAL_INSTALL_FAILED', 'PROVIDER_READINESS_REASON_POLICY_ACTIVATION_FAILED', 'PROVIDER_READINESS_REASON_PROCESS_INSTALL_FAILED', 'PROVIDER_READINESS_REASON_SUPERVISOR_DISCONNECTED', 'PROVIDER_READINESS_REASON_SUPERVISOR_LEASE_EXPIRED', 'PROVIDER_READINESS_REASON_DESIRED_STATE_CHANGED', 'PROVIDER_READINESS_REASON_CREDENTIAL_EXPIRED', 'PROVIDER_READINESS_REASON_LOCAL_POLICY', 'PROVIDER_READINESS_REASON_SNAPSHOT_MISMATCH'))
CONFIGUPDATEOPERATIONSTATE = frozenset(('CONFIG_UPDATE_OPERATION_STATE_UNSPECIFIED', 'CONFIG_UPDATE_OPERATION_STATE_PENDING', 'CONFIG_UPDATE_OPERATION_STATE_APPLIED', 'CONFIG_UPDATE_OPERATION_STATE_INACTIVE', 'CONFIG_UPDATE_OPERATION_STATE_FAILED', 'CONFIG_UPDATE_OPERATION_STATE_SUPERSEDED', 'CONFIG_UPDATE_OPERATION_STATE_CANCELLED'))
CONFIGAPPLYOUTCOME = frozenset(('CONFIG_APPLY_OUTCOME_UNSPECIFIED', 'CONFIG_APPLY_OUTCOME_APPLIED', 'CONFIG_APPLY_OUTCOME_IGNORED_DUPLICATE', 'CONFIG_APPLY_OUTCOME_IGNORED_STALE', 'CONFIG_APPLY_OUTCOME_RETAINED_LOCAL_OVERRIDE', 'CONFIG_APPLY_OUTCOME_DEGRADED', 'CONFIG_APPLY_OUTCOME_FAILED_RETAINED_LAST_KNOWN_GOOD', 'CONFIG_APPLY_OUTCOME_FAILED_CLOSED', 'CONFIG_APPLY_OUTCOME_UNSUPPORTED'))

@dataclass(frozen=True)
class StatusDiagnostics:
    readiness: str
    reason: str
    operation_state: str | None
    operation_outcome: str | None


def _enum(data, key, allowed, default):
    value = data.get(key, default)
    if type(value) is not str or len(value) > 96 or value not in allowed:
        raise ValueError('invalid_status_diagnostics')
    return value


def decode_status_diagnostics(binding, mutation, target, response):
    """Correlate receipt and optional operation; keep their claims separate.

    A missing operation stays absent. READY never overwrites FAILED, and
    WITHHELD never becomes REVOKED. This helper is not wired to admission.
    """
    if not status_receipt_matches(binding, mutation, target, response):
        raise ValueError('invalid_status_diagnostics')
    status = response['status']
    state = _enum(status, 'state', PROVIDERREADINESSSTATE,
                  'PROVIDER_READINESS_STATE_UNSPECIFIED')
    reason = _enum(status, 'reason', PROVIDERREADINESSREASON,
                   'PROVIDER_READINESS_REASON_UNSPECIFIED')
    op_state = op_outcome = None
    if 'operation' in status:
        op = status['operation']
        if (type(op) is not dict or op.get('operation_id') != target.receipt_id
                or op.get('sandbox_id') != target.sandbox_id
                or op.get('component') != 'CONFIG_COMPONENT_PROVIDER_ENVIRONMENT'):
            raise ValueError('invalid_status_diagnostics')
        revision = op.get('target_revision')
        if type(revision) is not dict or set(revision) != {'provider_target'}:
            raise ValueError('invalid_status_diagnostics')
        # Reuse canonical uint64/default and exact target comparison.
        receipt = dict(status['receipt'], desired=revision['provider_target'])
        if not status_receipt_matches(binding, mutation, target,
                                      {'status': {'receipt': receipt}}):
            raise ValueError('invalid_status_diagnostics')
        op_state = _enum(op, 'state', CONFIGUPDATEOPERATIONSTATE,
                         'CONFIG_UPDATE_OPERATION_STATE_UNSPECIFIED')
        op_outcome = _enum(op, 'outcome', CONFIGAPPLYOUTCOME,
                           'CONFIG_APPLY_OUTCOME_UNSPECIFIED')
    return StatusDiagnostics(state, reason, op_state, op_outcome)
