from dataclasses import replace
import unittest
import test_vendor_access_preflight as fixtures
from test_vendor_access_wire_response import field
from phase_loop_runtime.vendor_access_provider_metadata import ProviderMetadata
from phase_loop_runtime.vendor_access_refresh_metadata import decode_refresh_record
from phase_loop_runtime.vendor_access_preflight import preflight


class RefreshMetadataTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PreflightTests()
        self.f.setUp()
        self.provider = ProviderMetadata('id', 'provider', 'workspace', 7, 'profile', 'workspace')
        self.record = field(1, 'provider') + field(2, 'id') + field(3, self.f.binding.credential_key)

    def decode(self, payload):
        return decode_refresh_record(self.f.binding, self.provider, payload)

    def test_empty_reply_is_absence_not_refresh_disabled_or_eligible(self):
        result = self.decode(b'')
        self.assertEqual(result.code, 'no_matching_refresh_record_returned')
        self.assertIsNone(result.strategy)
        self.assertEqual(preflight(self.f.binding, self.f.activation, lambda _: result).code, 'metadata_invalid')

    def test_present_external_and_oauth_records_do_not_require_schedule(self):
        for value, expected in ((2, 'EXTERNAL'), (3, 'OAUTH2_REFRESH_TOKEN')):
            result = self.decode(field(1, self.record + field(4, value)))
            self.assertEqual((result.code, result.strategy), ('refresh_record_present', expected))

    def test_free_text_and_timestamp_canaries_not_retained(self):
        payload = field(1, self.record + field(4, 3) + field(5, 'STATUS_CANARY')
                        + field(9, 'ERROR_CANARY') + field(107, field(1, 123)))
        self.assertNotIn('CANARY', repr(self.decode(payload)))
        self.assertEqual(self.decode(payload), self.decode(field(1, self.record + field(4, 3))))

    def test_wrong_identity_duplicate_and_unknown_strategy_refused(self):
        valid = self.record + field(4, 2)
        payloads = [field(1, valid + field(n, 'foreign')) for n in (1, 2, 3)]
        payloads += [field(1, valid)*2, field(1, self.record), field(1, self.record + field(4, 99))]
        for payload in payloads:
            with self.assertRaises(ValueError):
                self.decode(payload)
        with self.assertRaises(ValueError):
            decode_refresh_record(self.f.binding, replace(self.provider, workspace='other'), b'')

    def test_malformed_oversized_wrong_type_refused(self):
        for payload in (b'\xff', b'x'*65537, bytearray(b''), field(1, self.record)[:-1]):
            with self.assertRaisesRegex(ValueError, '^invalid_refresh_metadata$'):
                self.decode(payload)
