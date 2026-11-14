import unittest
import test_vendor_access_response as fixtures
from phase_loop_runtime.vendor_access_response import decode_update_response
from phase_loop_runtime.vendor_access_wire_response import decode_status_receipt, MAX_STATUS_BYTES


# Independent wire construction from pinned field numbers, not the decoder's
# descriptors: catches accidental descriptor renumbering and wire-type changes.
def varint(n):
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128)
        n >>= 7
    return bytes(out) + bytes([n])


def field(n, value):
    if isinstance(value, int):
        return varint(n << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint((n << 3) | 2) + varint(len(value)) + value


class WireResponseTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ResponseTests()
        fixture.setUp()
        self.binding = fixture.binding
        self.expected = decode_update_response(self.binding, fixture.response)
        desired = b''.join(field(n, v) for n, v in enumerate(
            ('sandbox-id', 'sandbox-name', 'epoch', 'provider-id', 7, 8, 9, 'hash'), 1))
        self.receipt = b''.join(field(n, v) for n, v in enumerate((
            'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'server-mutation', 'provider',
            'workspace', 3, desired), 1))
        self.payload = field(1, field(1, self.receipt))

    def test_pinned_receipt_wire_decodes_exact_identity(self):
        self.assertEqual(decode_status_receipt(self.binding, self.payload), self.expected)

    def test_unknown_payload_and_ready_claim_are_not_retained(self):
        payload = field(1, field(1, self.receipt) + field(2, 3) + field(99, 'CANARY'))
        result = decode_status_receipt(self.binding, payload)
        self.assertEqual(result, self.expected)
        self.assertNotIn('CANARY', repr(result))

    def test_empty_missing_truncated_and_oversized_payload_refused(self):
        for payload in (b'', field(1, b''), self.payload[:-1], b'\xff',
                        b'x' * (MAX_STATUS_BYTES + 1), bytearray(self.payload)):
            with self.assertRaises(ValueError):
                decode_status_receipt(self.binding, payload)

    def test_unknown_kind_and_wrong_binding_refused(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):
            decode_status_receipt(replace(self.binding, workspace='other'), self.payload)
        # Singular protobuf enum follows last-value-wins; unknown kind must refuse.
        with self.assertRaises(ValueError):
            decode_status_receipt(self.binding, field(1, field(1, self.receipt + field(5, 99))))


if __name__ == '__main__':
    unittest.main()
