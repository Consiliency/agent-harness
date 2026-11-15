from dataclasses import replace
import unittest
import test_vendor_access_preflight as fixtures
from test_vendor_access_wire_response import field
from phase_loop_runtime.vendor_access_provider_metadata import decode_provider_metadata
from phase_loop_runtime.vendor_access_preflight import preflight


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PreflightTests()
        self.f.setUp()
        self.meta = field(1, 'provider-id') + field(2, 'provider') + field(5, 7) + field(7, 'workspace')

    def payload(self, meta=None, scope='workspace', extra=b''):
        return field(1, field(1, self.meta if meta is None else meta)
                     + field(2, 'profile') + field(6, scope) + extra)

    def decode(self, payload):
        return decode_provider_metadata(self.f.binding, payload)

    def test_exact_identity_scope_and_no_preflight_authority(self):
        result = self.decode(self.payload())
        self.assertEqual((result.provider_id, result.provider, result.workspace,
                          result.resource_version, result.profile_id, result.profile_workspace),
                         ('provider-id', 'provider', 'workspace', 7, 'profile', 'workspace'))
        self.assertEqual(self.decode(self.payload(scope='')).profile_workspace, '')
        self.assertEqual(preflight(self.f.binding, self.f.activation, lambda _: result).code, 'metadata_invalid')

    def test_secrets_handles_and_config_are_not_retained(self):
        entry = field(1, 'key') + field(2, 'CANARY')
        result = self.decode(self.payload(extra=field(3, entry) + field(4, entry) + field(7, entry)))
        self.assertNotIn('CANARY', repr(result))
        self.assertEqual(len(vars(result)), 6)

    def test_zero_version_deletion_and_invalid_scope_refused(self):
        for payload in (self.payload(meta=self.meta + field(5, 0)),
                        self.payload(meta=self.meta + field(108, b'')),
                        self.payload(meta=self.meta + field(108, field(1, 1))),
                        self.payload(scope='other'), self.payload(meta=b'')):
            with self.assertRaises(ValueError):
                self.decode(payload)
        self.assertEqual(self.decode(self.payload(meta=self.meta + field(5, 2**64-1))).resource_version, 2**64-1)

    def test_foreign_or_padded_identities_refused(self):
        for name in ('provider', 'workspace', 'profile_id'):
            with self.assertRaises(ValueError):
                decode_provider_metadata(replace(self.f.binding, **{name: 'other'}), self.payload())
        for value in ('', ' padded', 'x'*4097, 'bad\n'):
            with self.assertRaises(ValueError):
                self.decode(self.payload(meta=self.meta + field(1, value)))

    def test_missing_truncated_oversized_and_wrong_type_refused(self):
        for payload in (b'', field(1, b''), b'\xff', self.payload()[:-1], b'x'*65537,
                        bytearray(self.payload())):
            with self.assertRaisesRegex(ValueError, '^invalid_provider_metadata$'):
                self.decode(payload)
