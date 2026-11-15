from dataclasses import replace
import unittest
import test_vendor_access_requests as fixtures
from phase_loop_runtime.vendor_access_revocation_wire import serialize_expiry_revocation


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def field(number, payload):
    return varint(number*8+2)+varint(len(payload))+payload


class RevocationWireTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.RequestTests()
        f.setUp()
        self.binding, self.identifier = f.binding, f.identifier

    def expected(self, version):
        # Independent upstream field numbers, including Timestamp value presence.
        metadata = field(2, self.binding.provider.encode())+varint(5*8)+varint(version)
        expiry_entry = field(1, self.binding.credential_key.encode())+field(2, b'')
        return (field(1, field(1, metadata))
                +field(3, field(1, self.binding.workspace.encode()))
                +field(4, self.identifier.encode())+field(102, expiry_entry))

    def test_exact_pinned_wire_and_determinism(self):
        for version in (1, 7, 2**64-1):
            result = serialize_expiry_revocation(self.binding, self.identifier, version)
            self.assertEqual(result, self.expected(version))
            self.assertEqual(result, serialize_expiry_revocation(self.binding, self.identifier, version))

    def test_unicode_selectors_use_byte_lengths(self):
        self.binding = replace(self.binding, provider='provider-é')
        self.assertEqual(serialize_expiry_revocation(self.binding, self.identifier, 7), self.expected(7))

    def test_invalid_cas_and_id_refuse_before_encoding(self):
        for version in (0, True, -1, 2**64):
            with self.assertRaises(ValueError):
                serialize_expiry_revocation(self.binding, self.identifier, version)
        with self.assertRaises(ValueError):
            serialize_expiry_revocation(self.binding, 'not-a-uuid', 1)

    def test_oversized_and_padded_selectors_refuse(self):
        for name in ('workspace', 'provider', 'credential_key'):
            for value in ('x'*4097, ' padded', 'é'*2049):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    serialize_expiry_revocation(replace(self.binding, **{name: value}), self.identifier, 1)
