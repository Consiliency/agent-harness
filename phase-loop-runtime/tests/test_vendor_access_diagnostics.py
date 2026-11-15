from copy import deepcopy
import unittest

from phase_loop_runtime.vendor_access_diagnostics import decode_status_diagnostics
from phase_loop_runtime.vendor_access_response import decode_update_response
import test_vendor_access_response as fixtures


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ResponseTests()
        fixture.setUp()
        self.binding = fixture.binding
        self.mutation = decode_update_response(self.binding, fixture.response)
        self.target = self.mutation.targets[0]
        self.response = {'status': {'receipt': deepcopy(fixture.response['target_receipts'][0]),
            'state': 'PROVIDER_READINESS_STATE_WITHHELD',
            'reason': 'PROVIDER_READINESS_REASON_CREDENTIAL_EXPIRED'}}

    def decode(self, response=None):
        return decode_status_diagnostics(self.binding, self.mutation, self.target,
                                         self.response if response is None else response)

    def operation(self):
        self.response['status']['operation'] = {
            'operation_id': self.target.receipt_id, 'sandbox_id': self.target.sandbox_id,
            'component': 'CONFIG_COMPONENT_PROVIDER_ENVIRONMENT',
            'target_revision': {'provider_target': deepcopy(self.response['status']['receipt']['desired'])},
            'state': 'CONFIG_UPDATE_OPERATION_STATE_FAILED',
            'outcome': 'CONFIG_APPLY_OUTCOME_FAILED_CLOSED', 'sanitized_error': 'CANARY'}
        return self.response['status']['operation']

    def test_expiry_stays_withheld_and_missing_operation_stays_absent(self):
        result = self.decode()
        self.assertEqual(result.readiness, 'PROVIDER_READINESS_STATE_WITHHELD')
        self.assertEqual(result.reason, 'PROVIDER_READINESS_REASON_CREDENTIAL_EXPIRED')
        self.assertIsNone(result.operation_state)
        self.assertIsNone(result.operation_outcome)
        self.assertEqual(set(vars(result)), {'readiness', 'reason', 'operation_state', 'operation_outcome'})

    def test_ready_does_not_override_terminal_failure_or_copy_error(self):
        self.operation()
        self.response['status']['state'] = 'PROVIDER_READINESS_STATE_READY'
        result = self.decode()
        self.assertEqual(result.operation_state, 'CONFIG_UPDATE_OPERATION_STATE_FAILED')
        self.assertEqual(result.operation_outcome, 'CONFIG_APPLY_OUTCOME_FAILED_CLOSED')
        self.assertEqual(result.readiness, 'PROVIDER_READINESS_STATE_READY')
        self.assertNotIn('CANARY', repr(result))

    def test_foreign_operation_or_target_refused(self):
        self.operation()
        for key in ('operation_id', 'sandbox_id', 'component', 'target_revision'):
            response = deepcopy(self.response)
            response['status']['operation'][key] = 'wrong'
            with self.assertRaisesRegex(ValueError, '^invalid_status_diagnostics$'):
                self.decode(response)
        for key in self.response['status']['receipt']['desired']:
            response = deepcopy(self.response)
            response['status']['operation']['target_revision']['provider_target'][key] = '999'
            with self.assertRaises(ValueError):
                self.decode(response)

    def test_unknown_enums_and_malformed_operation_refused(self):
        self.operation()
        for container, key in (('status', 'state'), ('status', 'reason'),
                               ('operation', 'state'), ('operation', 'outcome')):
            for value in (True, 0, 'CANARY', 'x' * 1000, []):
                response = deepcopy(self.response)
                dest = response['status'] if container == 'status' else response['status']['operation']
                dest[key] = value
                with self.assertRaisesRegex(ValueError, '^invalid_status_diagnostics$'):
                    self.decode(response)
        for value in (None, [], {}, 'CANARY'):
            self.response['status']['operation'] = value
            with self.assertRaises(ValueError):
                self.decode()

    def test_receipt_mismatch_and_conflicting_oneof_refused(self):
        self.operation()
        response = deepcopy(self.response)
        response['status']['receipt']['workspace'] = 'other'
        with self.assertRaises(ValueError):
            self.decode(response)
        self.response['status']['operation']['target_revision']['provider_environment'] = '8'
        with self.assertRaises(ValueError):
            self.decode()

    def test_protobuf_enum_defaults_are_not_completion(self):
        op = self.operation()
        del op['state'], op['outcome']
        del self.response['status']['state'], self.response['status']['reason']
        result = self.decode()
        self.assertTrue(all(value.endswith('_UNSPECIFIED') for value in vars(result).values()))
