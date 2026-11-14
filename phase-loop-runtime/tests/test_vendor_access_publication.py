from dataclasses import replace
import unittest
import test_vendor_access_preflight as fixtures
from phase_loop_runtime.vendor_access_contract import AccessSnapshot
from phase_loop_runtime.vendor_access_publication import publication_decision


class PublicationTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.PreflightTests()
        f.setUp()
        self.binding = f.binding
        self.snapshot = AccessSnapshot(self.binding.identity_digest, b'ACCESS_CANARY', 2000.0)
        self.key = b'k' * 32

    def decide(self, captured=None, current=None, **kwargs):
        options = dict(key=self.key, now=1000, revocation_pending=False)
        options.update(kwargs)
        return publication_decision(self.binding, captured or self.snapshot,
                                    current or self.snapshot, **options)

    def test_only_acknowledged_value_suppresses_publication(self):
        first = self.decide()
        self.assertEqual(first.action, 'publish')
        self.assertEqual(self.decide().action, 'publish')  # Failed attempt is not ACK.
        self.assertEqual(self.decide(acknowledged_fingerprint=first.fingerprint).action, 'unchanged')
        self.assertNotIn('CANARY', repr(first))
        self.assertNotIn(repr(first.fingerprint), repr(first))

    def test_changed_access_or_expiry_requires_new_ack(self):
        ack = self.decide().fingerprint
        for changes in ({'access': b'ROTATED'}, {'expires_at': 2100.0}):
            fresh = replace(self.snapshot, **changes)
            self.assertEqual(self.decide(fresh, fresh, acknowledged_fingerprint=ack).action, 'publish')
            self.assertEqual(self.decide(current=fresh).code, 'source_change_unverified')

    def test_revocation_dominates_even_missing_source_and_bad_comparison_state(self):
        result = publication_decision(None, None, None, key=None, now=None,
                                     revocation_pending=True, acknowledged_fingerprint='bad')
        self.assertEqual(result.action, 'revoke')
        self.assertIsNone(result.fingerprint)
        self.assertEqual(self.decide(revocation_pending=1).action, 'hold')

    def test_invalid_expired_wrong_identity_and_ambiguous_snapshots_hold(self):
        for changes in ({'access': b''}, {'access': b'x' * 16385}, {'access': b'bad\n'},
                        {'identity_digest': 'other'}, {'expires_at': 1000},
                        {'expires_at': 1899}, {'expires_at': float('nan')},
                        {'expires_at': True}, {'source_generation': 'unknown'},
                        {'claims': (('secret', 'CANARY'),)}):
            invalid = replace(self.snapshot, **changes)
            result = self.decide(invalid, invalid)
            self.assertEqual(result.action, 'hold', changes.keys())
            self.assertIsNone(result.fingerprint)
            self.assertNotIn('CANARY', repr(result))

    def test_binding_and_process_key_scope_fingerprints(self):
        ack = self.decide().fingerprint
        self.assertEqual(self.decide(key=b'z' * 32, acknowledged_fingerprint=ack).action, 'publish')
        self.binding = replace(self.binding, provider='other')
        self.assertEqual(self.decide(acknowledged_fingerprint=ack).action, 'publish')

    def test_invalid_key_clock_and_ack_refused(self):
        for kwargs in ({'key': b''}, {'now': float('inf')}, {'now': True},
                       {'acknowledged_fingerprint': b''}):
            self.assertEqual(self.decide(**kwargs).action, 'hold')
