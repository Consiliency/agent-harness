"""Offline projection of one credential's pinned OpenShell refresh-status reply.

No record is not proof of disabled refresh. Caller must correlate an authenticated
GetProviderRefreshStatus request selecting the exact workspace/provider/key;
empty replies carry no identity. This helper grants no preflight eligibility.
Free-text status/errors and timestamps are discarded, not logged or retained.
"""
from dataclasses import dataclass
from functools import lru_cache

from .vendor_access_contract import VendorBinding
from .vendor_access_provider_metadata import ProviderMetadata

MAX_REFRESH_BYTES = 65536
STRATEGIES = ('UNSPECIFIED', 'STATIC', 'EXTERNAL', 'OAUTH2_REFRESH_TOKEN',
              'OAUTH2_CLIENT_CREDENTIALS', 'GOOGLE_SERVICE_ACCOUNT_JWT', 'AWS_STS_ASSUME_ROLE')


@dataclass(frozen=True)
class RefreshRecordDiagnostic:
    code: str
    strategy: str | None = None


@lru_cache(maxsize=1)
def _response_type():
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    file = descriptor_pb2.FileDescriptorProto(name='refresh_metadata.proto',
        package='refresh_metadata', syntax='proto3')
    enum = file.enum_type.add(name='Strategy')
    for number, name in enumerate(STRATEGIES):
        enum.value.add(name=name, number=number)
    record = file.message_type.add(name='Record')
    for number, name in enumerate(('provider', 'provider_id', 'credential_key'), 1):
        record.field.add(name=name, number=number, type=9, label=1)
    record.field.add(name='strategy', number=4, type=14, label=1,
                     type_name='.refresh_metadata.Strategy')
    response = file.message_type.add(name='Response')
    response.field.add(name='credentials', number=1, type=11, label=3,
                       type_name='.refresh_metadata.Record')
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName('refresh_metadata.Response'))


def decode_refresh_record(binding, provider, payload):
    """Report only absence/presence for a single-key query; never a disabled flag."""
    if (type(binding) is not VendorBinding or type(provider) is not ProviderMetadata
            or (provider.provider, provider.workspace, provider.profile_id) !=
               (binding.provider, binding.workspace, binding.profile_id)
            or type(provider.provider_id) is not str or not provider.provider_id
            or type(binding.credential_key) is not str or not binding.credential_key
            or type(payload) is not bytes or len(payload) > MAX_REFRESH_BYTES):
        raise ValueError('invalid_refresh_metadata')
    from google.protobuf.message import DecodeError
    message = _response_type()()
    try:
        message.ParseFromString(payload)
    except DecodeError:
        raise ValueError('invalid_refresh_metadata') from None
    message.DiscardUnknownFields()
    if not message.credentials:
        return RefreshRecordDiagnostic('no_matching_refresh_record_returned')
    if len(message.credentials) != 1:
        raise ValueError('invalid_refresh_metadata')
    record = message.credentials[0]
    if ((record.provider, record.provider_id, record.credential_key) !=
            (binding.provider, provider.provider_id, binding.credential_key)
            or not 0 < record.strategy < len(STRATEGIES)):
        raise ValueError('invalid_refresh_metadata')
    return RefreshRecordDiagnostic('refresh_record_present', STRATEGIES[record.strategy])
