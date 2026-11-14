"""Bounded metadata projection of pinned OpenShell v0.1.7 status replies.

Pin: 5d25211b25a8fc887e8d5c606d57d6ab22f1d76c openshell.proto.
Hand-built subset, not full generated bindings. Excludes session observations
and free-text errors: decoded metadata cannot establish admission
or revocation completion. Transport must enforce this size limit before buffering.
"""
from functools import lru_cache

from .vendor_access_contract import VendorBinding
from .vendor_access_response import DecodedMutation, decode_update_response

MAX_STATUS_BYTES = 65536


@lru_cache(maxsize=2)
def _response_type(message_name='GetSandboxProviderStatusResponse'):
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    file = descriptor_pb2.FileDescriptorProto(
        name='vendor_status_response_projection.proto', package='openshell.v1', syntax='proto3')
    desired = file.message_type.add(name='ProviderDesiredIdentity')
    for name, number, kind in (
        ('sandbox_id', 1, 9), ('sandbox', 2, 9), ('attachment_epoch', 3, 9),
        ('provider_id', 4, 9), ('provider_resource_version', 5, 4),
        ('provider_env_revision', 6, 4), ('config_revision', 7, 4), ('policy_hash', 8, 9),
    ):
        desired.field.add(name=name, number=number, type=kind, label=1)
    kinds = file.enum_type.add(name='ProviderMutationKind')
    for number, name in enumerate(('UNSPECIFIED', 'ATTACH', 'DETACH', 'UPDATE', 'OBSERVE')):
        kinds.value.add(name='PROVIDER_MUTATION_KIND_' + name, number=number)
    receipt = file.message_type.add(name='ProviderMutationReceipt')
    for number, name in enumerate(('receipt_id', 'mutation_id', 'provider', 'workspace'), 1):
        receipt.field.add(name=name, number=number, type=9, label=1)
    receipt.field.add(name='kind', number=5, type=14, label=1,
                      type_name='.openshell.v1.ProviderMutationKind')
    receipt.field.add(name='desired', number=6, type=11, label=1,
                      type_name='.openshell.v1.ProviderDesiredIdentity')
    enum = file.enum_type.add(name='ProviderReadinessState')
    for name, number in (
        ('PROVIDER_READINESS_STATE_UNSPECIFIED', 0),
        ('PROVIDER_READINESS_STATE_PERSISTED', 1),
        ('PROVIDER_READINESS_STATE_PENDING', 2),
        ('PROVIDER_READINESS_STATE_READY', 3),
        ('PROVIDER_READINESS_STATE_WITHHELD', 4),
        ('PROVIDER_READINESS_STATE_REVOKED', 5),
        ('PROVIDER_READINESS_STATE_FAILED', 6),
        ('PROVIDER_READINESS_STATE_SUPERSEDED', 7),
    ):
        enum.value.add(name=name, number=number)
    enum = file.enum_type.add(name='ProviderReadinessReason')
    for name, number in (
        ('PROVIDER_READINESS_REASON_UNSPECIFIED', 0),
        ('PROVIDER_READINESS_REASON_WAITING_FOR_SUPERVISOR', 1),
        ('PROVIDER_READINESS_REASON_WAITING_FOR_CREDENTIALS', 2),
        ('PROVIDER_READINESS_REASON_WAITING_FOR_POLICY', 3),
        ('PROVIDER_READINESS_REASON_WAITING_FOR_PROCESS', 4),
        ('PROVIDER_READINESS_REASON_UNSUPPORTED_SUPERVISOR', 5),
        ('PROVIDER_READINESS_REASON_CREDENTIALS_WITHHELD', 6),
        ('PROVIDER_READINESS_REASON_CREDENTIAL_INSTALL_FAILED', 7),
        ('PROVIDER_READINESS_REASON_POLICY_ACTIVATION_FAILED', 8),
        ('PROVIDER_READINESS_REASON_PROCESS_INSTALL_FAILED', 9),
        ('PROVIDER_READINESS_REASON_SUPERVISOR_DISCONNECTED', 10),
        ('PROVIDER_READINESS_REASON_SUPERVISOR_LEASE_EXPIRED', 11),
        ('PROVIDER_READINESS_REASON_DESIRED_STATE_CHANGED', 12),
        ('PROVIDER_READINESS_REASON_CREDENTIAL_EXPIRED', 13),
        ('PROVIDER_READINESS_REASON_LOCAL_POLICY', 14),
        ('PROVIDER_READINESS_REASON_SNAPSHOT_MISMATCH', 15),
    ):
        enum.value.add(name=name, number=number)
    enum = file.enum_type.add(name='ConfigUpdateOperationState')
    for name, number in (
        ('CONFIG_UPDATE_OPERATION_STATE_UNSPECIFIED', 0),
        ('CONFIG_UPDATE_OPERATION_STATE_PENDING', 1),
        ('CONFIG_UPDATE_OPERATION_STATE_APPLIED', 2),
        ('CONFIG_UPDATE_OPERATION_STATE_INACTIVE', 3),
        ('CONFIG_UPDATE_OPERATION_STATE_FAILED', 4),
        ('CONFIG_UPDATE_OPERATION_STATE_SUPERSEDED', 5),
        ('CONFIG_UPDATE_OPERATION_STATE_CANCELLED', 6),
    ):
        enum.value.add(name=name, number=number)
    enum = file.enum_type.add(name='ConfigApplyOutcome')
    for name, number in (
        ('CONFIG_APPLY_OUTCOME_UNSPECIFIED', 0),
        ('CONFIG_APPLY_OUTCOME_APPLIED', 1),
        ('CONFIG_APPLY_OUTCOME_IGNORED_DUPLICATE', 2),
        ('CONFIG_APPLY_OUTCOME_IGNORED_STALE', 3),
        ('CONFIG_APPLY_OUTCOME_RETAINED_LOCAL_OVERRIDE', 4),
        ('CONFIG_APPLY_OUTCOME_DEGRADED', 5),
        ('CONFIG_APPLY_OUTCOME_FAILED_RETAINED_LAST_KNOWN_GOOD', 6),
        ('CONFIG_APPLY_OUTCOME_FAILED_CLOSED', 7),
        ('CONFIG_APPLY_OUTCOME_UNSUPPORTED', 8),
    ):
        enum.value.add(name=name, number=number)
    enum = file.enum_type.add(name='ConfigComponent')
    for name, number in (
        ('CONFIG_COMPONENT_UNSPECIFIED', 0),
        ('CONFIG_COMPONENT_SANDBOX_CONFIG', 1),
        ('CONFIG_COMPONENT_PROVIDER_ENVIRONMENT', 2),
    ):
        enum.value.add(name=name, number=number)
    file.message_type.add(name='SandboxConfigRevision')
    revision = file.message_type.add(name='ConfigSnapshotRevision')
    revision.oneof_decl.add(name='component')
    for name, number, kind, type_name in (
        ('sandbox_config', 1, 11, '.openshell.v1.SandboxConfigRevision'),
        ('provider_environment', 2, 4, None),
        ('provider_target', 3, 11, '.openshell.v1.ProviderDesiredIdentity'),
    ):
        field = revision.field.add(name=name, number=number, type=kind, label=1, oneof_index=0)
        if type_name:
            field.type_name = type_name
    operation = file.message_type.add(name='ConfigUpdateOperation')
    for name, number, kind, type_name in (
        ('operation_id', 1, 9, None), ('sandbox_id', 2, 9, None),
        ('component', 3, 14, '.openshell.v1.ConfigComponent'),
        ('target_revision', 4, 11, '.openshell.v1.ConfigSnapshotRevision'),
        ('state', 5, 14, '.openshell.v1.ConfigUpdateOperationState'),
        ('outcome', 6, 14, '.openshell.v1.ConfigApplyOutcome'),
    ):
        field = operation.field.add(name=name, number=number, type=kind, label=1)
        if type_name:
            field.type_name = type_name
    status = file.message_type.add(name='ProviderReadinessStatus')
    status.field.add(name='receipt', number=1, type=11, label=1,
                     type_name='.openshell.v1.ProviderMutationReceipt')
    for name, number, kind, type_name in (
        ('state', 2, 14, '.openshell.v1.ProviderReadinessState'),
        ('reason', 3, 14, '.openshell.v1.ProviderReadinessReason'),
        ('operation', 8, 11, '.openshell.v1.ConfigUpdateOperation'),
    ):
        status.field.add(name=name, number=number, type=kind, label=1, type_name=type_name)
    response = file.message_type.add(name='GetSandboxProviderStatusResponse')
    response.field.add(name='status', number=1, type=11, label=1,
                       type_name='.openshell.v1.ProviderReadinessStatus')
    mutation = file.message_type.add(name='ProviderResponse')
    mutation.field.add(name='target_receipts', number=2, type=11, label=3,
                       type_name='.openshell.v1.ProviderMutationReceipt')
    mutation.field.add(name='mutation_id', number=3, type=9, label=1)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName(
        'openshell.v1.' + message_name))


def decode_mutation_wire(binding: VendorBinding, payload: bytes) -> DecodedMutation:
    """Decode ProviderResponse metadata; never convert desired targets to sessions.

    Provider field 1 can contain sensitive data and is discarded as unknown.
    Each returned receipt is checked against the binding. Empty targets provide
    no independent workspace/provider evidence: authenticated request correlation
    remains a transport obligation. This result is not revocation completion.
    """
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_STATUS_BYTES:
        raise ValueError('invalid_mutation_wire')
    from google.protobuf import json_format
    from google.protobuf.message import DecodeError
    message = _response_type('ProviderResponse')()
    try:
        message.ParseFromString(payload)
    except DecodeError:
        raise ValueError('invalid_mutation_wire') from None
    message.DiscardUnknownFields()
    return decode_update_response(binding, json_format.MessageToDict(
        message, preserving_proto_field_name=True))


def decode_status_receipt(binding: VendorBinding, payload: bytes) -> DecodedMutation:
    """Decode a single UPDATE receipt; callers must still match the frozen target.

    Unknown fields follow protobuf compatibility rules and are discarded. No
    response payload, unknown fields or readiness claim is retained in the result.
    """
    from google.protobuf import json_format
    message = _parse_status(payload)
    receipt = json_format.MessageToDict(message.status.receipt, preserving_proto_field_name=True)
    return decode_update_response(binding, {
        'mutation_id': receipt.get('mutation_id'), 'target_receipts': [receipt],
    })


def decode_status_diagnostics_wire(binding, mutation, target, payload):
    """Retain correlated diagnostic enums, without admission or completion claims."""
    from google.protobuf import json_format
    from .vendor_access_diagnostics import decode_status_diagnostics
    message = _parse_status(payload)
    return decode_status_diagnostics(binding, mutation, target,
        json_format.MessageToDict(message, preserving_proto_field_name=True))


def _parse_status(payload):
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_STATUS_BYTES:
        raise ValueError('invalid_status_wire')
    from google.protobuf.message import DecodeError
    message = _response_type()()
    try:
        message.ParseFromString(payload)
    except DecodeError:
        raise ValueError('invalid_status_wire') from None
    if not message.HasField('status') or not message.status.HasField('receipt'):
        raise ValueError('invalid_status_wire')
    message.DiscardUnknownFields()
    return message
