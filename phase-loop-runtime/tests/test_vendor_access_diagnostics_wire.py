import unittest
from phase_loop_runtime.vendor_access_wire_response import (
    decode_status_diagnostics_wire, MAX_STATUS_BYTES,
)
import test_vendor_access_wire_response as wire


class DiagnosticWireTests(unittest.TestCase):
    def setUp(self):
        fixture = wire.WireResponseTests()
        fixture.setUp()
        self.binding, self.mutation = fixture.binding, fixture.expected
        self.target = self.mutation.targets[0]
        self.receipt = fixture.receipt
        f = wire.field
        self.desired = b''.join(f(n, v) for n, v in enumerate(
            ('sandbox-id', 'sandbox-name', 'epoch', 'provider-id', 7, 8, 9, 'hash'), 1))
        self.revision = f(3, self.desired)
        self.operation = (f(1, self.target.receipt_id) + f(2, 'sandbox-id') + f(3, 2)
                          + f(4, self.revision) + f(5, 4) + f(6, 7))

    def payload(self, state=4, reason=13, operation=None):
        f = wire.field
        return f(1, f(1, self.receipt) + f(2, state) + f(3, reason)
                 + (f(8, operation) if operation is not None else b''))

    def decode(self, payload):
        return decode_status_diagnostics_wire(self.binding, self.mutation, self.target, payload)

    def test_expired_withheld_and_independent_terminal_failure(self):
        result = self.decode(self.payload(operation=self.operation))
        self.assertEqual(result.readiness, 'PROVIDER_READINESS_STATE_WITHHELD')
        self.assertEqual(result.reason, 'PROVIDER_READINESS_REASON_CREDENTIAL_EXPIRED')
        self.assertEqual(result.operation_state, 'CONFIG_UPDATE_OPERATION_STATE_FAILED')
        self.assertEqual(result.operation_outcome, 'CONFIG_APPLY_OUTCOME_FAILED_CLOSED')
        ready = self.decode(self.payload(state=3, operation=self.operation))
        self.assertEqual(ready.readiness, 'PROVIDER_READINESS_STATE_READY')
        self.assertEqual(ready.operation_state, result.operation_state)

    def test_missing_operation_and_default_enums(self):
        result = self.decode(self.payload(state=0, reason=0))
        self.assertIsNone(result.operation_state)
        self.assertIsNone(result.operation_outcome)
        self.assertEqual(result.readiness, 'PROVIDER_READINESS_STATE_UNSPECIFIED')

    def test_error_and_observation_canaries_discarded(self):
        f = wire.field
        operation = self.operation + f(7, 'ERROR_CANARY')
        payload = f(1, f(1, self.receipt) + f(4, f(1, 'SESSION_CANARY'))
                    + f(5, 'NETWORK_CANARY') + f(8, operation) + f(99, 'UNKNOWN_CANARY'))
        self.assertNotIn('CANARY', repr(self.decode(payload)))

    def test_unknown_enums_and_foreign_operation_refused(self):
        f = wire.field
        payloads = [self.payload(state=99), self.payload(reason=99)]
        payloads += [self.payload(operation=self.operation + f(n, value))
                     for n, value in ((1, 'other'), (2, 'other'), (3, 99), (5, 99), (6, 99))]
        # Later oneof member must replace provider_target, not be discarded as unknown.
        payloads.append(self.payload(operation=self.operation + f(4, f(2, 8))))
        payloads.append(self.payload(operation=self.operation + f(4, f(1, b''))))
        payloads.append(self.payload(operation=self.operation + f(4, f(3, self.desired + f(7, 999)))))
        for payload in payloads:
            with self.assertRaises(ValueError):
                self.decode(payload)

    def test_size_type_missing_and_truncated_refused(self):
        payload = self.payload(operation=self.operation)
        for bad in (b'', b'\xff', payload[:-1], b'x' * (MAX_STATUS_BYTES + 1),
                    bytearray(payload), wire.field(1, b'')):
            with self.assertRaises(ValueError):
                self.decode(bad)
