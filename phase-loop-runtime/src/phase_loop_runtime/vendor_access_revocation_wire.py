"""Offline expiry-only UpdateProvider projection at OpenShell 5d25211.

Hand-built subset of the pinned schema, not full generated bindings. Cannot
encode credentials, clear expiry, or change profiles. No transport/activation.
"""
from functools import lru_cache

from .vendor_access_requests import expiry_revocation_request

MAX_REVOCATION_BYTES = 16384


@lru_cache(maxsize=1)
def _request_type():
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, timestamp_pb2
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(timestamp_pb2.DESCRIPTOR.serialized_pb)
    data = descriptor_pb2.FileDescriptorProto(name='vendor_revoke_data.proto',
        package='openshell.datamodel.v1', syntax='proto3')
    selector = data.message_type.add(name='WorkspaceSelector')
    selector.oneof_decl.add(name='selection')
    selector.field.add(name='workspace', number=1, type=9, label=1, oneof_index=0)
    meta = data.message_type.add(name='ObjectMeta')
    meta.field.add(name='name', number=2, type=9, label=1)
    meta.field.add(name='resource_version', number=5, type=4, label=1)
    provider = data.message_type.add(name='Provider')
    provider.field.add(name='metadata', number=1, type=11, label=1,
                       type_name='.openshell.datamodel.v1.ObjectMeta')
    pool.Add(data)
    api = descriptor_pb2.FileDescriptorProto(name='vendor_revoke_api.proto',
        package='openshell.v1', syntax='proto3', dependency=[data.name, 'google/protobuf/timestamp.proto'])
    request = api.message_type.add(name='UpdateProviderRequest')
    request.field.add(name='provider', number=1, type=11, label=1,
                      type_name='.openshell.datamodel.v1.Provider')
    request.field.add(name='workspace_scope', number=3, type=11, label=1,
                      type_name='.openshell.datamodel.v1.WorkspaceSelector')
    request.field.add(name='request_id', number=4, type=9, label=1)
    entry = request.nested_type.add(name='CredentialExpirationTimesEntry')
    entry.options.map_entry = True
    entry.field.add(name='key', number=1, type=9, label=1)
    entry.field.add(name='value', number=2, type=11, label=1,
                    type_name='.google.protobuf.Timestamp')
    request.field.add(name='credential_expiration_times', number=102, type=11, label=3,
        type_name='.openshell.v1.UpdateProviderRequest.CredentialExpirationTimesEntry')
    pool.Add(api)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName('openshell.v1.UpdateProviderRequest'))


def serialize_expiry_revocation(binding, request_id, resource_version):
    """Encode a nonzero-CAS, idempotent expiry request without reading secrets."""
    intent = expiry_revocation_request(binding, request_id, resource_version)
    for value in (binding.workspace, binding.provider, binding.credential_key):
        if value.strip() != value or len(value.encode('utf-8')) > 4096:
            raise ValueError('invalid_revocation_selector')
    message = _request_type()()
    message.workspace_scope.workspace = intent['workspace_scope']['workspace']
    message.provider.metadata.name = binding.provider
    message.provider.metadata.resource_version = resource_version
    message.request_id = request_id
    # Presence of an empty Timestamp message represents Unix epoch, not absence.
    message.credential_expiration_times[binding.credential_key].SetInParent()
    payload = message.SerializeToString(deterministic=True)
    if len(payload) > MAX_REVOCATION_BYTES:
        raise ValueError('revocation_wire_oversize')
    return payload
