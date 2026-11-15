from copy import deepcopy
from dataclasses import fields
import unittest
from dataclasses import replace

from phase_loop_runtime.vendor_access_response import (
    decode_update_response, provider_status_request, status_receipt_matches,
)
import test_vendor_access_requests as request_fixtures


class ResponseTests(unittest.TestCase):
    def setUp(self):
        fixture = request_fixtures.RequestTests()
        fixture.setUp()
        self.binding = fixture.binding
        self.response = {'mutation_id': 'server-mutation', 'provider': {'credentials': {'key': 'CANARY'}},
            'target_receipts': [{'receipt_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'mutation_id': 'server-mutation',
                'provider': 'provider', 'workspace': 'workspace',
                'kind': 'PROVIDER_MUTATION_KIND_UPDATE', 'desired': {
                    'sandbox_id': 'sandbox-id', 'sandbox': 'sandbox-name',
                    'attachment_epoch': 'epoch', 'provider_id': 'provider-id',
                    'provider_resource_version': '7', 'provider_env_revision': '8',
                    'config_revision': '9', 'policy_hash': 'hash'}}]}

    def test_preserves_desired_identity_without_secret_or_session(self):
        result = decode_update_response(self.binding, self.response)
        self.assertEqual(result.mutation_id, 'server-mutation')
        self.assertEqual(result.targets[0].provider_resource_version, 7)
        self.assertEqual(result.targets[0].attachment_epoch, 'epoch')
        self.assertNotIn('CANARY', repr(result))
        self.assertNotIn('supervisor_session_id', {f.name for f in fields(result.targets[0])})

    def test_receipt_binding_and_kind_mismatch_refused(self):
        for key in ('mutation_id', 'provider', 'workspace', 'kind'):
            response = deepcopy(self.response)
            response['target_receipts'][0][key] = 'other'
            with self.assertRaisesRegex(ValueError, '^invalid_mutation_response$'):
                decode_update_response(self.binding, response)

    def test_duplicate_receipt_or_sandbox_refused(self):
        for changed_key in (None, 'receipt_id'):
            response = deepcopy(self.response)
            second = deepcopy(response['target_receipts'][0])
            if changed_key:
                second[changed_key] = 'second'
            response['target_receipts'].append(second)
            with self.assertRaises(ValueError):
                decode_update_response(self.binding, response)

    def test_invalid_revision_refused(self):
        for value in (True, 7, '-1', '01', str(2**64), '９', 'secret'):
            response = deepcopy(self.response)
            response['target_receipts'][0]['desired']['config_revision'] = value
            with self.assertRaisesRegex(ValueError, '^invalid_mutation_response$'):
                decode_update_response(self.binding, response)

    def test_protobuf_defaults_and_empty_targets(self):
        self.assertEqual(decode_update_response(self.binding, {'mutation_id': 'm'}).targets, ())
        del self.response['target_receipts'][0]['desired']['config_revision']
        self.assertEqual(decode_update_response(self.binding, self.response).targets[0].config_revision, 0)

    def test_missing_and_malformed_identities_refused(self):
        for key in ('sandbox_id', 'sandbox', 'attachment_epoch', 'provider_id', 'policy_hash'):
            response = deepcopy(self.response)
            del response['target_receipts'][0]['desired'][key]
            with self.assertRaises(ValueError):
                decode_update_response(self.binding, response)
        for response in ({}, {'mutation_id': 'm', 'target_receipts': {}}, {'mutation_id': '\n'}):
            with self.assertRaises(ValueError):
                decode_update_response(self.binding, response)


    def test_status_request_pins_receipt_and_named_scope(self):
        target = decode_update_response(self.binding, self.response).targets[0]
        self.assertEqual(provider_status_request(self.binding, target), {
            'workspace_scope': {'workspace': 'workspace'}, 'sandbox': 'sandbox-name',
            'provider': 'provider', 'receipt_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'})
        with self.assertRaises(ValueError):
            provider_status_request(self.binding, replace(target, receipt_id=''))

    def test_matching_receipt_does_not_require_or_trust_ready_claim(self):
        mutation = decode_update_response(self.binding, self.response)
        response = {'status': {'receipt': self.response['target_receipts'][0]}}
        self.assertTrue(status_receipt_matches(self.binding, mutation, mutation.targets[0], response))
        response['status']['state'] = 'PROVIDER_READINESS_STATE_FAILED'
        self.assertTrue(status_receipt_matches(self.binding, mutation, mutation.targets[0], response))

    def test_every_desired_identity_change_refused_despite_ready_claim(self):
        mutation = decode_update_response(self.binding, self.response)
        for key in self.response['target_receipts'][0]['desired']:
            receipt = deepcopy(self.response['target_receipts'][0])
            receipt['desired'][key] = '999' if 'revision' in key or key == 'provider_resource_version' else 'replacement'
            response = {'status': {'receipt': receipt, 'state': 'PROVIDER_READINESS_STATE_READY'}}
            self.assertFalse(status_receipt_matches(self.binding, mutation, mutation.targets[0], response), key)

    def test_foreign_mutation_receipt_and_unfrozen_target_refused(self):
        mutation = decode_update_response(self.binding, self.response)
        target = mutation.targets[0]
        for key in ('mutation_id', 'receipt_id', 'workspace', 'provider'):
            receipt = deepcopy(self.response['target_receipts'][0])
            receipt[key] = 'other'
            self.assertFalse(status_receipt_matches(self.binding, mutation, target, {'status': {'receipt': receipt}}))
        self.assertFalse(status_receipt_matches(self.binding, mutation, replace(target, sandbox_id='other'), {}))
        for response in ({}, {'status': {}}, {'status': None}):
            self.assertFalse(status_receipt_matches(self.binding, mutation, target, response))


if __name__ == '__main__':
    unittest.main()
