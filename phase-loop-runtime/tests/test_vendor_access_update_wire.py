from dataclasses import replace
import unittest
import test_vendor_access_revocation_wire as fixtures
from phase_loop_runtime.vendor_access_contract import AccessSnapshot
from phase_loop_runtime.vendor_access_update_wire import serialize_access_update, MAX_UPDATE_BYTES
from phase_loop_runtime.vendor_access_revocation_wire import serialize_expiry_revocation


class UpdateWireTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.RevocationWireTests()
        f.setUp()
        self.binding, self.identifier = f.binding, f.identifier
        self.snapshot = AccessSnapshot(self.binding.identity_digest, b'SYNTHETIC_ACCESS', 2000.75)

    def encode(self, **kwargs):
        return serialize_access_update(self.binding, self.snapshot, self.identifier,
                                       kwargs.pop('version', 7), now=kwargs.pop('now', 1000), **kwargs)

    def test_exact_independent_pinned_wire_with_rounded_down_expiry(self):
        field, varint = fixtures.field, fixtures.varint
        meta = field(2, self.binding.provider.encode()) + varint(40) + varint(7)
        credentials = field(1, self.binding.credential_key.encode()) + field(2, b'SYNTHETIC_ACCESS')
        timestamp = varint(8) + varint(2000)
        expiry = field(1, self.binding.credential_key.encode()) + field(2, timestamp)
        expected = (field(1, field(1, meta) + field(3, credentials))
            + field(3, field(1, self.binding.workspace.encode()))
            + field(4, self.identifier.encode()) + field(102, expiry))
        self.assertEqual(self.encode(), expected)
        self.assertEqual(self.encode(), self.encode())
        # Private descriptor extension must not contaminate expiry-only requests.
        self.assertNotIn(b'SYNTHETIC_ACCESS', serialize_expiry_revocation(self.binding, self.identifier, 7))

    def test_invalid_or_empty_access_never_encodes_deletion(self):
        for value in (b'', b'x' * 16385, b'bad\n', b'\xff', 'text'):
            self.snapshot = replace(self.snapshot, access=value)
            with self.assertRaisesRegex(ValueError, '^invalid_update_snapshot$'):
                self.encode()

    def test_expiry_identity_generation_and_claims_refused(self):
        original = self.snapshot
        for changes in ({'identity_digest': 'wrong'}, {'source_generation': 'unverified'},
                        {'claims': (('refresh_token', 'CANARY'),)}, {'expires_at': None},
                        {'expires_at': float('inf')}, {'expires_at': True},
                        {'expires_at': 253402300800}, {'expires_at': 1000}):
            self.snapshot = replace(original, **changes)
            with self.assertRaises(ValueError) as error:
                self.encode()
            self.assertNotIn('CANARY', str(error.exception))

    def test_rounding_never_shortens_below_required_floor(self):
        self.snapshot = replace(self.snapshot, expires_at=1900.75)
        with self.assertRaisesRegex(ValueError, 'update_expiry_insufficient'):
            self.encode(now=1000.5)

    def test_max_access_fits_cap_and_bad_cas_or_request_id_refused(self):
        self.snapshot = replace(self.snapshot, access=b'x' * 16384)
        self.assertLessEqual(len(self.encode()), MAX_UPDATE_BYTES)
        for version in (0, True, 2**64):
            with self.assertRaises(ValueError):
                self.encode(version=version)
        self.identifier = 'bad'
        with self.assertRaises(ValueError):
            self.encode()
