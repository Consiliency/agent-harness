"""Offline access-only UpdateProvider projection at OpenShell 5d25211.

Returned bytes contain credentials: never log, persist or include them in error
messages. No transport or activation. Caller must revalidate source, profile,
writer authority and durable barriers before publication. Expiry is rounded DOWN
to whole seconds, never extended. Refresh tokens/profile edits are not encoded.
"""
from functools import lru_cache
import math

from .vendor_access_contract import AccessSnapshot, VendorBinding
from .vendor_access_revocation_wire import _request_type as _revocation_type
from .vendor_access_revocation_wire import serialize_expiry_revocation

MAX_UPDATE_BYTES = 32768


@lru_cache(maxsize=1)
def _request_type():
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, timestamp_pb2
    # Clone the narrow expiry projection into a private pool, leaving revocation
    # incapable of encoding credentials. Add only pinned Provider.credentials=3.
    original = _revocation_type().DESCRIPTOR.file
    api = descriptor_pb2.FileDescriptorProto()
    original.CopyToProto(api)
    data = descriptor_pb2.FileDescriptorProto()
    original.pool.FindFileByName('vendor_revoke_data.proto').CopyToProto(data)
    provider = next(m for m in data.message_type if m.name == 'Provider')
    entry = provider.nested_type.add(name='CredentialsEntry')
    entry.options.map_entry = True
    entry.field.add(name='key', number=1, type=9, label=1)
    entry.field.add(name='value', number=2, type=9, label=1)
    provider.field.add(name='credentials', number=3, type=11, label=3,
                      type_name='.openshell.datamodel.v1.Provider.CredentialsEntry')
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(timestamp_pb2.DESCRIPTOR.serialized_pb)
    pool.Add(data)
    pool.Add(api)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName('openshell.v1.UpdateProviderRequest'))


def serialize_access_update(binding, snapshot, request_id, resource_version, *, now):
    """Encode exactly one nonempty access key and finite expiry, with nonzero CAS."""
    if (type(binding) is not VendorBinding or type(snapshot) is not AccessSnapshot
            or binding.auth_kind != 'subscription_oauth'
            or snapshot.identity_digest != binding.identity_digest
            or snapshot.source_generation is not None or snapshot.claims != ()
            or type(snapshot.access) is not bytes or not 1 <= len(snapshot.access) <= 16384
            or any(c < 33 or c > 126 for c in snapshot.access)
            or type(now) not in (int, float) or not math.isfinite(now)
            or type(binding.floor_s) is not int or not 0 <= binding.floor_s <= 253402300799
            or type(snapshot.expires_at) not in (int, float)
            or not math.isfinite(snapshot.expires_at)
            or not 0 < snapshot.expires_at < 253402300800):
        raise ValueError('invalid_update_snapshot')
    seconds = math.floor(snapshot.expires_at)
    if seconds <= now or seconds < now + binding.floor_s:
        raise ValueError('update_expiry_insufficient')
    base = serialize_expiry_revocation(binding, request_id, resource_version)
    message = _request_type()()
    message.ParseFromString(base)
    message.provider.credentials[binding.credential_key] = snapshot.access.decode('ascii')
    message.credential_expiration_times[binding.credential_key].seconds = seconds
    payload = message.SerializeToString(deterministic=True)
    if len(payload) > MAX_UPDATE_BYTES:
        raise ValueError('update_wire_oversize')
    return payload
