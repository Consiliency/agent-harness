from dataclasses import replace
import unittest
from phase_loop_runtime.vendor_access_contract import VendorBinding
from phase_loop_runtime.vendor_access_requests import expiry_revocation_request


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.binding = VendorBinding('binding', 'grok', 'grok', 'subscription_oauth',
            'host', 'native_store', 'source', 'grok_subscription', '/home/fixture',
            '.grok/auth.json', 'a'*64, 'workspace', 'provider', 'GROK_SUBSCRIPTION_ACCESS',
            'profile', 'b'*64, 900, 'owner-ref')
        self.identifier = '00000000-0000-0000-0000-000000000001'

    def test_expiry_only_request_shape(self):
        result = expiry_revocation_request(self.binding, self.identifier, 7)
        self.assertEqual(result, {
            'workspace_scope': {'workspace': 'workspace'},
            'provider': {'metadata': {'name': 'provider', 'resource_version': '7'}},
            'credential_expiration_times': {'GROK_SUBSCRIPTION_ACCESS': '1970-01-01T00:00:00Z'},
            'request_id': self.identifier})

    def test_zero_bool_and_out_of_range_cas_refused(self):
        for version in (0, True, -1, 2**64, '7'):
            with self.assertRaisesRegex(ValueError, 'invalid_resource_version'):
                expiry_revocation_request(self.binding, self.identifier, version)

    def test_request_identity_and_binding_refused(self):
        for identifier in ('00000000-0000-0000-0000-000000000000', 'secret', None):
            with self.assertRaisesRegex(ValueError, 'invalid_request_id'):
                expiry_revocation_request(self.binding, identifier, 1)
        for field in ('workspace', 'provider', 'credential_key'):
            with self.assertRaisesRegex(ValueError, 'invalid_binding'):
                expiry_revocation_request(replace(self.binding, **{field: ''}), self.identifier, 1)


if __name__ == '__main__':
    unittest.main()
