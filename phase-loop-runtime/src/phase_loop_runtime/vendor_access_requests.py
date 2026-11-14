"""Offline protobuf-JSON intent for OpenShell v0.1.7 UpdateProviderRequest.

Pinned source: NVIDIA/OpenShell 5d25211b25a8fc887e8d5c606d57d6ab22f1d76c,
proto/openshell.proto and proto/datamodel.proto. Not a generated protobuf binding
or transport. Request UUID is NOT the server-generated response mutation_id;
readiness must use the latter with the response's frozen target set.
"""
import uuid

from .vendor_access_contract import VendorBinding


def expiry_revocation_request(binding: VendorBinding, request_id: str, resource_version: int) -> dict:
    """Expire only the bound access key; never send credentials or clear expiry.

    Names are taken from an already-authorized binding; this encoder performs no
    authentication, profile inspection or admission. uint64 uses protobuf JSON's
    decimal-string representation. Unix epoch is an already-expired timestamp.
    """
    if type(binding) is not VendorBinding:
        raise ValueError('invalid_binding')
    for value in (binding.workspace, binding.provider, binding.credential_key):
        if (type(value) is not str or not value
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError('invalid_binding')
    if type(resource_version) is not int or not 0 < resource_version < 2**64:
        raise ValueError('invalid_resource_version')
    valid = False
    if type(request_id) is str:
        try:
            parsed = uuid.UUID(request_id)
            valid = parsed.int != 0 and str(parsed) == request_id
        except ValueError:
            pass
    if not valid:
        raise ValueError('invalid_request_id')
    return {
        'workspace_scope': {'workspace': binding.workspace},
        'provider': {'metadata': {'name': binding.provider,
                                  'resource_version': str(resource_version)}},
        'credential_expiration_times': {binding.credential_key: '1970-01-01T00:00:00Z'},
        'request_id': request_id,
    }
