from dataclasses import replace
import unittest
import test_vendor_access_wire_response as fixtures
from phase_loop_runtime.vendor_access_response import DecodedMutation
from phase_loop_runtime.vendor_access_wire_response import decode_mutation_wire, MAX_STATUS_BYTES


class MutationWireTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WireResponseTests()
        self.f.setUp()
        self.payload = fixtures.field(2, self.f.receipt)+fixtures.field(3, 'server-mutation')

    def test_independent_wire_matches_desired_targets_only(self):
        result = decode_mutation_wire(self.f.binding, self.payload)
        self.assertEqual(result, self.f.expected)
        self.assertFalse(hasattr(result.targets[0], 'session_id'))

    def test_empty_target_set_retains_mutation_without_application_claim(self):
        self.assertEqual(decode_mutation_wire(self.f.binding, fixtures.field(3, 'server-mutation')),
                         DecodedMutation('server-mutation', ()))

    def test_provider_and_unknown_canary_are_not_retained(self):
        payload = fixtures.field(1, b'CANARY provider')+self.payload+fixtures.field(99, 'CANARY unknown')
        result = decode_mutation_wire(self.f.binding, payload)
        self.assertEqual(result, self.f.expected)
        self.assertNotIn('CANARY', repr(result))

    def test_bad_wire_and_missing_mutation_refuse(self):
        for payload in (b'', b'\xff', self.payload[:-1], b'x'*(MAX_STATUS_BYTES+1),
                        fixtures.field(2, self.f.receipt), bytearray(self.payload)):
            with self.assertRaises(ValueError):
                decode_mutation_wire(self.f.binding, payload)

    def test_binding_duplicate_and_receipt_mutation_mismatch_refuse(self):
        for binding, payload in (
            (replace(self.f.binding, workspace='other'), self.payload),
            (replace(self.f.binding, provider='other'), self.payload),
            (self.f.binding, self.payload+fixtures.field(2, self.f.receipt)),
            (self.f.binding, fixtures.field(2, self.f.receipt)+fixtures.field(3, 'different')),
            (self.f.binding, fixtures.field(2, self.f.receipt+fixtures.field(5, 99))
             +fixtures.field(3, 'server-mutation'))):
            with self.assertRaises(ValueError):
                decode_mutation_wire(binding, payload)
