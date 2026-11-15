"""Offline decoding of pinned OpenShell v0.1.7 ProviderResponse metadata.

Input is protobuf JSON with preserving_proto_field_name=True. The provider
payload is deliberately ignored, never copied into the result. This is neither
an authenticated transport nor readiness evidence. Desired identities do not
contain supervisor sessions and must not be converted to applied TargetReceipt
objects. Pin: 5d25211b25a8fc887e8d5c606d57d6ab22f1d76c, openshell.proto.
Do not log input or exception traceback locals at this boundary.
"""
from dataclasses import dataclass
import uuid

from .vendor_access_contract import VendorBinding


@dataclass(frozen=True)
class DesiredTarget:
    receipt_id: str
    sandbox_id: str
    sandbox: str
    attachment_epoch: str
    provider_id: str
    provider_resource_version: int
    provider_env_revision: int
    config_revision: int
    policy_hash: str


@dataclass(frozen=True)
class DecodedMutation:
    mutation_id: str
    targets: tuple[DesiredTarget, ...]


def _text(value):
    if (type(value) is not str or not 0 < len(value) <= 1024
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('invalid_mutation_response')
    return value


def _uint64(value):
    # Canonical protobuf JSON emits decimal strings. Refuse bools, signs,
    # Unicode digits, leading zeros and oversized input before conversion.
    if (type(value) is not str or not 1 <= len(value) <= 20
            or any(c not in '0123456789' for c in value)
            or (len(value) > 1 and value[0] == '0')):
        raise ValueError('invalid_mutation_response')
    result = int(value)
    if result >= 2**64:
        raise ValueError('invalid_mutation_response')
    return result


def decode_update_response(binding: VendorBinding, response: dict) -> DecodedMutation:
    """Retain exact UPDATE targets; an empty target set is not application proof.

    Omitted repeated fields and uint64 defaults follow protobuf JSON defaults.
    Receipt mutation/provider/workspace must match the response and binding.
    Receipt IDs and sandbox IDs must each be unique. No session is fabricated.
    """
    if type(binding) is not VendorBinding or type(response) is not dict:
        raise ValueError('invalid_mutation_response')
    mutation = _text(response.get('mutation_id'))
    receipts = response.get('target_receipts', [])
    if type(receipts) is not list or len(receipts) > 4096:
        raise ValueError('invalid_mutation_response')
    targets = []
    receipt_ids, sandbox_ids = set(), set()
    for receipt in receipts:
        if (type(receipt) is not dict
                or receipt.get('mutation_id') != mutation
                or receipt.get('provider') != binding.provider
                or receipt.get('workspace') != binding.workspace
                or receipt.get('kind') != 'PROVIDER_MUTATION_KIND_UPDATE'):
            raise ValueError('invalid_mutation_response')
        desired = receipt.get('desired')
        if type(desired) is not dict:
            raise ValueError('invalid_mutation_response')
        target = DesiredTarget(
            _text(receipt.get('receipt_id')),
            *(_text(desired.get(k)) for k in
              ('sandbox_id', 'sandbox', 'attachment_epoch', 'provider_id')),
            *(_uint64(desired.get(k, '0')) for k in
              ('provider_resource_version', 'provider_env_revision', 'config_revision')),
            _text(desired.get('policy_hash')),
        )
        if target.receipt_id in receipt_ids or target.sandbox_id in sandbox_ids:
            raise ValueError('invalid_mutation_response')
        receipt_ids.add(target.receipt_id)
        sandbox_ids.add(target.sandbox_id)
        targets.append(target)
    return DecodedMutation(mutation, tuple(targets))


def provider_status_request(binding: VendorBinding, target: DesiredTarget) -> dict:
    """Query the immutable receipt, never reconstruct an unpinned current state."""
    if type(binding) is not VendorBinding or type(target) is not DesiredTarget:
        raise ValueError('invalid_status_request')
    receipt = _text(target.receipt_id)
    valid = False
    try:
        parsed = uuid.UUID(receipt)
        valid = parsed.int != 0 and str(parsed) == receipt
    except ValueError:
        pass
    if not valid:
        raise ValueError('invalid_status_request')
    return {
        'workspace_scope': {'workspace': _text(binding.workspace)},
        'sandbox': _text(target.sandbox),
        'provider': _text(binding.provider),
        'receipt_id': _text(target.receipt_id),
    }


def status_receipt_matches(binding: VendorBinding, mutation: DecodedMutation,
                           target: DesiredTarget, response: dict) -> bool:
    """Check receipt correlation only; True does NOT establish readiness.

    Session authority, observation age, operation outcome, and live stream
    revocation still need independent validation. Ignore READY claims here.
    Revisions are compared for equality, never ordered.
    """
    if (type(mutation) is not DecodedMutation or type(target) is not DesiredTarget
            or type(mutation.targets) is not tuple or target not in mutation.targets
            or type(response) is not dict):
        return False
    status = response.get('status')
    if type(status) is not dict:
        return False
    try:
        decoded = decode_update_response(binding, {
            'mutation_id': mutation.mutation_id,
            'target_receipts': [status.get('receipt')],
        })
    except ValueError:
        return False
    return decoded.targets == (target,)
