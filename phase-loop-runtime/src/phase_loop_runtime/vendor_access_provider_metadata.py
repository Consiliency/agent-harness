"""Bounded non-secret ProviderResponse projection at OpenShell 5d25211.

Not ProviderPreflight: profile digest, refresh ownership and authenticated
request correlation remain unverified. No transport or credential lookup.
Unknown fields (including credentials/config/handles) are discarded. Transport
must enforce the receive cap before buffering; never log input or parse locals.
"""
from dataclasses import dataclass
from functools import lru_cache

from .vendor_access_contract import VendorBinding

MAX_PROVIDER_BYTES = 65536


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    provider: str
    workspace: str
    resource_version: int
    profile_id: str
    profile_workspace: str


@lru_cache(maxsize=1)
def _response_type():
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    file = descriptor_pb2.FileDescriptorProto(name='vendor_metadata_projection.proto',
                                             package='vendor_metadata', syntax='proto3')
    # Only presence matters; an empty deletion timestamp also refuses.
    file.message_type.add(name='DeletionTimestamp')
    meta = file.message_type.add(name='ObjectMeta')
    for name, number, kind in (('id', 1, 9), ('name', 2, 9),
                               ('resource_version', 5, 4), ('workspace', 7, 9)):
        meta.field.add(name=name, number=number, type=kind, label=1)
    meta.field.add(name='deletion_time', number=108, type=11, label=1,
                   type_name='.vendor_metadata.DeletionTimestamp')
    provider = file.message_type.add(name='Provider')
    provider.field.add(name='metadata', number=1, type=11, label=1,
                       type_name='.vendor_metadata.ObjectMeta')
    provider.field.add(name='type', number=2, type=9, label=1)
    provider.field.add(name='profile_workspace', number=6, type=9, label=1)
    response = file.message_type.add(name='ProviderResponse')
    response.field.add(name='provider', number=1, type=11, label=1,
                       type_name='.vendor_metadata.Provider')
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName('vendor_metadata.ProviderResponse'))


def _text(value):
    return (0 < len(value.encode('utf-8')) <= 4096 and value.strip() == value
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def decode_provider_metadata(binding, payload):
    """Match named provider/workspace/profile, require nonzero CAS and no deletion.

    Platform profile scope is retained as empty, never normalized to workspace.
    No digest or refresh-disabled value is inferred from the response.
    """
    if (type(binding) is not VendorBinding or type(payload) is not bytes
            or not 0 < len(payload) <= MAX_PROVIDER_BYTES):
        raise ValueError('invalid_provider_metadata')
    from google.protobuf.message import DecodeError
    message = _response_type()()
    try:
        message.ParseFromString(payload)
    except DecodeError:
        raise ValueError('invalid_provider_metadata') from None
    if not message.HasField('provider') or not message.provider.HasField('metadata'):
        raise ValueError('invalid_provider_metadata')
    message.DiscardUnknownFields()
    provider = message.provider
    meta = provider.metadata
    if (meta.HasField('deletion_time') or meta.resource_version == 0
            or not all(_text(v) for v in (meta.id, meta.name, meta.workspace, provider.type))
            or (meta.name, meta.workspace, provider.type) !=
               (binding.provider, binding.workspace, binding.profile_id)
            or provider.profile_workspace not in ('', binding.workspace)):
        raise ValueError('invalid_provider_metadata')
    return ProviderMetadata(meta.id, meta.name, meta.workspace, meta.resource_version,
                            provider.type, provider.profile_workspace)
