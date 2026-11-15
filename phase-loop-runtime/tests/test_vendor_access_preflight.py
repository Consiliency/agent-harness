"""Offline metadata fixtures; no filesystem credential stores or transports."""
from dataclasses import replace
import unittest
from unittest.mock import Mock

from phase_loop_runtime.vendor_access_contract import VendorBinding
from phase_loop_runtime.vendor_access_preflight import (
    ActivationRecord, ProviderPreflight, binding_digest, preflight,
)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.binding = VendorBinding(
            'binding', 'grok', 'grok', 'subscription_oauth', 'fixture-host',
            'native_store', 'https://auth.x.ai::fixture', 'grok_subscription',
            '/fixture/home', '.grok/auth.json', 'a' * 64, 'workspace', 'provider',
            'GROK_SUBSCRIPTION_ACCESS', 'profile', 'b' * 64, 900, 'owner-ref')
        self.activation = ActivationRecord(binding_digest(self.binding), 'D2', 'D3', 'D5')
        self.metadata = ProviderPreflight('workspace', 'provider', 'profile', 'b' * 64, 7, False)
        self.inspect = Mock(return_value=self.metadata)

    def test_held_performs_no_inspection(self):
        for record in (None, {}, replace(self.activation, d2_ref=''),
                       replace(self.activation, d3_ref=None),
                       replace(self.activation, d5_ref='bad\nref')):
            self.assertEqual(preflight(self.binding, record, self.inspect).state, 'held')
        self.inspect.assert_not_called()

    def test_changed_binding_requires_activation(self):
        for changes in ({'source_host': 'other'}, {'identity_digest': 'c' * 64},
                        {'workspace': 'other'}, {'source_home': '/other'},
                        {'profile_sha256': 'c' * 64}):
            result = preflight(replace(self.binding, **changes), self.activation, self.inspect)
            self.assertEqual(result.state, 'held')
        self.inspect.assert_not_called()

    def test_blank_or_padded_decision_references_hold_before_inspection(self):
        for name in ('d2_ref', 'd3_ref', 'd5_ref'):
            for value in (' ', '   ', '\u00a0', ' decision', 'decision '):
                with self.subTest(name=name, value=repr(value)):
                    record = replace(self.activation, **{name: value})
                    result = preflight(self.binding, record, self.inspect)
                    self.assertEqual(result.state, 'held')
                    self.assertEqual(result.code, 'activation_references_invalid')
        self.inspect.assert_not_called()

    def test_profile_refresh_and_version_refusals(self):
        for changes in ({'workspace': 'other'}, {'provider': 'other'},
                        {'profile_id': 'other'}, {'profile_sha256': 'c' * 64},
                        {'gateway_refresh_enabled': True}, {'gateway_refresh_enabled': 0},
                        {'resource_version': 0}, {'resource_version': True},
                        {'resource_version': -1}, {'resource_version': 2**64}):
            self.inspect.return_value = replace(self.metadata, **changes)
            self.assertEqual(preflight(self.binding, self.activation, self.inspect).state,
                             'gateway_refused')

    def test_transport_failure_is_fixed_status(self):
        self.inspect.side_effect = RuntimeError('synthetic-sensitive-payload')
        result = preflight(self.binding, self.activation, self.inspect)
        self.assertEqual(result.state, 'gateway_unavailable')
        self.assertNotIn('synthetic-sensitive-payload', repr(result))
        self.inspect.assert_called_once_with(self.binding)

    def test_largest_uint64_resource_version_is_eligible(self):
        self.inspect.return_value = replace(self.metadata, resource_version=2**64 - 1)
        result = preflight(self.binding, self.activation, self.inspect)
        self.assertEqual(result.state, 'eligible')
        self.assertEqual(result.resource_version, 2**64 - 1)

    def test_even_matching_activation_cannot_approve_malformed_profile_pin(self):
        for pin in ('', 'not-a-digest', 'a'*63, 'a'*65, 'A'*64, 'g'*64, 'a'*64+'\n', None):
            binding = replace(self.binding, profile_sha256=pin)
            activation = replace(self.activation, binding_sha256=binding_digest(binding))
            result = preflight(binding, activation, self.inspect)
            self.assertEqual((result.state, result.code), ('held', 'profile_pin_invalid'))
        self.inspect.assert_not_called()

    def test_native_diagnostics_cannot_grant_preflight_eligibility(self):
        from phase_loop_runtime.vendor_access_provider_metadata import ProviderMetadata
        from phase_loop_runtime.vendor_access_refresh_metadata import RefreshRecordDiagnostic

        # Even matching CAS/scope and absent or EXTERNAL refresh records do not
        # establish authenticated provenance, profile safety or writer exclusion.
        metadata = ProviderMetadata('provider-id', 'provider', 'workspace', 7,
                                    'profile', 'workspace')
        absent = RefreshRecordDiagnostic('no_matching_refresh_record_returned')
        external = RefreshRecordDiagnostic('refresh_record_present', 'EXTERNAL')
        for observed in (metadata, absent, external, (metadata, absent),
                         (metadata, external)):
            with self.subTest(kind=type(observed).__name__):
                self.inspect.return_value = observed
                result = preflight(self.binding, self.activation, self.inspect)
                self.assertEqual((result.state, result.code, result.resource_version),
                                 ('gateway_refused', 'metadata_invalid', None))

    def test_success_is_preflight_only(self):
        result = preflight(self.binding, self.activation, self.inspect)
        self.assertEqual(result.state, 'eligible')
        self.assertEqual(result.resource_version, 7)
        self.inspect.assert_called_once_with(self.binding)


if __name__ == '__main__':
    unittest.main()
