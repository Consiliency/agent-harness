import os
import unittest
from unittest.mock import Mock, patch
import test_vendor_access_updater as fixtures
from test_vendor_access_wire_response import field
from phase_loop_runtime.vendor_access_pending import load_pending
from phase_loop_runtime.vendor_access_publication_journal import (
    PublicationRecord, canonical, load_publication)
from phase_loop_runtime.vendor_access_update_wire import serialize_access_update


class EncodedUpdateTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.UpdaterTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.f = f

    def tick(self, invoke, activation=True):
        f = self.f
        return f.updater.tick_encoded(f.f.activation if activation else None,
                                     f.fd, f.f.inspect, f.read, invoke)

    def test_exact_payload_after_durability_without_secret_persistence(self):
        f = self.f
        calls = []
        def invoke(binding, payload):
            marker = load_pending(f.fd, f.updater._publication_digest)
            self.assertIsNotNone(marker)
            self.assertEqual(payload, serialize_access_update(binding, f.snapshot, marker, 7, now=1000))
            calls.append(binding)
            digest = f.updater._publication_digest
            record = PublicationRecord(1, f.updater._digest, marker, marker, 'prepared')
            self.assertEqual(load_publication(f.fd, f.updater._digest), record)
            expected = {digest + '.pending': (marker + '\n').encode(),
                        digest + '.publication.json': canonical(record)}
            self.assertEqual(set(os.listdir(f.fd)), set(expected))
            for name, content in expected.items():
                fd = os.open(name, os.O_RDONLY, dir_fd=f.fd)
                try:
                    raw = os.read(fd, 1025)
                    self.assertEqual(raw, content)
                    self.assertNotIn(b'CANARY', raw)
                finally:
                    os.close(fd)
            return field(3, 'server-mutation')
        result = self.tick(invoke)
        self.assertEqual(result.code, 'persisted_pending_application')
        self.assertEqual(result.desired_mutation.mutation_id, 'server-mutation')
        self.assertNotIn('CANARY', repr(result))
        self.assertEqual(self.tick(invoke).code, 'acknowledged_value_unchanged')
        self.assertEqual(calls, [f.f.binding])

    def test_held_pending_and_failed_durability_never_encode_or_invoke(self):
        invoke = Mock()
        with patch('phase_loop_runtime.vendor_access_update_wire.serialize_access_update') as encode:
            self.assertEqual(self.tick(invoke, False).code, 'held')
            with patch('phase_loop_runtime.vendor_access_updater.record_pending', side_effect=OSError):
                self.assertEqual(self.tick(invoke).code, 'journal_unavailable')
            self.f.pending()
            self.assertEqual(self.tick(invoke).code, 'revocation_pending')
            encode.assert_not_called()
        invoke.assert_not_called()

    def test_encoding_refusal_never_invokes_or_acknowledges(self):
        invoke = Mock()
        with patch('phase_loop_runtime.vendor_access_update_wire.serialize_access_update',
                   side_effect=ValueError('CANARY')):
            result = self.tick(invoke)
        self.assertEqual(result.code, 'publication_reconciliation_required')
        self.assertNotIn('CANARY', repr(result))
        self.assertIsNotNone(load_pending(self.f.fd, self.f.updater._publication_digest))
        self.assertIsNone(self.f.updater._acknowledged)
        self.assertEqual(self.tick(invoke).code, 'publication_reconciliation_required')
        invoke.assert_not_called()
        self.f.assert_restart_blocked_without_io('publication_reconciliation_required')

    def test_elapsed_source_lifetime_refused_at_encoding(self):
        self.f.updater._clock = Mock(side_effect=[1000, 1200])
        invoke = Mock()
        self.assertEqual(self.tick(invoke).code, 'publication_reconciliation_required')
        invoke.assert_not_called()
        self.assertIsNone(self.f.updater._acknowledged)
        self.f.assert_restart_blocked_without_io('publication_reconciliation_required')

    def test_ambiguous_invocation_is_not_retried_or_acknowledged(self):
        invoke = Mock(side_effect=RuntimeError('CANARY'))
        self.assertEqual(self.tick(invoke).code, 'publication_reconciliation_required')
        self.assertEqual(self.tick(invoke).code, 'publication_reconciliation_required')
        invoke.assert_called_once()
        self.assertIsNone(self.f.updater._acknowledged)
