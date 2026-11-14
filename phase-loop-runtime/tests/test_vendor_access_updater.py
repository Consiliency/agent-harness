from dataclasses import replace
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
import test_vendor_access_preflight as fixtures
from test_vendor_access_wire_response import field
from phase_loop_runtime.vendor_access_contract import AccessSnapshot
from phase_loop_runtime.vendor_access_pending import record_pending, load_pending
from phase_loop_runtime.vendor_access_updater import VendorAccessUpdater
from phase_loop_runtime.vendor_access_writer import private_directory_writer


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.PreflightTests()
        f.setUp()
        self.f = f
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fd = os.open(temp.name, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.snapshot = AccessSnapshot(f.binding.identity_digest, b'CANARY', 2000)
        self.read = Mock(return_value=self.snapshot)
        self.publish = Mock(return_value=field(3, 'mutation'))
        self.updater = VendorAccessUpdater(f.binding, clock=lambda: 1000)

    def tick(self, activation=True):
        return self.updater.tick(self.f.activation if activation else None,
                                 self.fd, self.f.inspect, self.read, self.publish)

    def pending(self):
        record_pending(self.fd, self.f.activation.binding_sha256,
                       '00000000-0000-0000-0000-000000000001')

    def test_held_or_pending_has_no_source_or_gateway_io(self):
        self.assertEqual(self.tick(False).code, 'held')
        self.pending()
        self.assertEqual(self.tick().code, 'revocation_pending')
        self.f.inspect.assert_not_called()
        self.read.assert_not_called()
        self.publish.assert_not_called()

    def test_ack_only_suppresses_same_value_and_changed_expiry_publishes(self):
        first = self.tick()
        self.assertEqual(first.code, 'persisted_pending_application')
        self.assertEqual(first.desired_mutation.targets, ())
        self.assertEqual(self.tick().code, 'acknowledged_value_unchanged')
        self.publish.assert_called_once()
        self.read.return_value = replace(self.snapshot, expires_at=2100)
        self.assertEqual(self.tick().code, 'persisted_pending_application')
        self.assertEqual(self.publish.call_count, 2)
        self.assertNotEqual(self.publish.call_args_list[0].args[2], self.publish.call_args_list[1].args[2])
        self.assertNotIn('CANARY', repr(first))

    def test_changed_source_or_new_pending_never_publishes(self):
        self.read.side_effect = [self.snapshot, replace(self.snapshot, access=b'changed')]
        self.assertEqual(self.tick().code, 'source_change_unverified')
        def discovered(binding):
            self.pending()
            return self.snapshot
        self.read.side_effect = discovered
        self.assertEqual(self.tick().code, 'revocation_pending')
        self.publish.assert_not_called()
        self.assertIsNotNone(load_pending(self.fd, self.f.activation.binding_sha256))

    def test_ambiguous_write_blocks_subsequent_tick_without_retry(self):
        self.publish.side_effect = RuntimeError('CANARY')
        result = self.tick()
        self.assertEqual(result.code, 'publication_reconciliation_required')
        self.assertNotIn('CANARY', repr(result))
        self.assertEqual(self.tick().code, result.code)
        self.publish.assert_called_once()
        self.assertEqual(self.read.call_count, 2)

    def test_bad_metadata_source_or_busy_writer_prevents_publish(self):
        with private_directory_writer(self.fd):
            self.assertEqual(self.tick().code, 'writer_busy')
        self.f.inspect.return_value = replace(self.f.metadata, gateway_refresh_enabled=True)
        self.assertEqual(self.tick().code, 'gateway_refresh_not_disabled')
        self.read.assert_not_called()
        self.f.inspect.return_value = self.f.metadata
        self.read.side_effect = RuntimeError('CANARY')
        self.assertEqual(self.tick().code, 'source_unverified')
        self.publish.assert_not_called()

    def test_publish_holds_lock_and_malformed_ack_never_counts(self):
        def publish(*args):
            with self.assertRaises(BlockingIOError):
                with private_directory_writer(self.fd):
                    self.fail('writer overlapped')
            return b'\xff'
        self.publish.side_effect = publish
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.publish.assert_called_once()

    def test_interruption_retains_uncertainty_and_releases_lock(self):
        self.publish.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.tick()
        with private_directory_writer(self.fd):
            pass
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.publish.assert_called_once()

    def restart(self):
        self.updater = VendorAccessUpdater(self.f.binding, clock=lambda: 1000)
        self.f.inspect.reset_mock()
        self.read.reset_mock()
        self.publish.reset_mock()

    def test_restart_after_success_or_ambiguity_never_replays(self):
        self.assertEqual(self.tick().code, 'persisted_pending_application')
        self.publish.side_effect = RuntimeError('ambiguous')
        self.read.return_value = replace(self.snapshot, access=b'rotated')
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.restart()
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.f.inspect.assert_not_called()
        self.read.assert_not_called()
        self.publish.assert_not_called()

    def test_restart_after_ack_revalidates_current_source_and_cas(self):
        from phase_loop_runtime.vendor_access_publication_journal import load_publication
        def publish(binding, snapshot, request_id, version):
            record = load_publication(self.fd, self.updater._digest)
            self.assertEqual(record.phase, 'prepared')
            self.assertEqual(record.attempt_id, request_id)
            self.assertEqual(record.barrier_id, load_pending(self.fd, self.updater._publication_digest))
            return field(3, 'mutation')
        self.publish.side_effect = publish
        self.tick()
        previous = self.publish.call_args.args[2]
        for version in (8, 9):
            self.restart()
            self.f.inspect.return_value = replace(self.f.metadata, resource_version=version)
            self.read.return_value = replace(self.snapshot, access=b'current', expires_at=1900)
            self.assertEqual(self.tick().code, 'persisted_pending_application')
            self.f.inspect.assert_called_once()
            self.assertEqual(self.read.call_count, 2)
            self.publish.assert_called_once()
            args = self.publish.call_args.args
            self.assertEqual(args[1], self.read.return_value)
            self.assertEqual(args[3], version)
            self.assertNotEqual(args[2], previous)
            previous = args[2]

    def test_durable_barrier_exists_before_publish_and_contains_no_access(self):
        def publish(binding, snapshot, request_id, version):
            self.assertEqual(load_pending(self.fd, self.updater._publication_digest), request_id)
            self.assertIsNone(load_pending(self.fd, self.f.activation.binding_sha256))
            return field(3, 'mutation')
        self.publish.side_effect = publish
        self.assertEqual(self.tick().code, 'persisted_pending_application')

    def test_failed_barrier_sync_never_publishes_or_retries(self):
        with patch('phase_loop_runtime.vendor_access_updater.record_pending', side_effect=OSError):
            self.assertEqual(self.tick().code, 'journal_unavailable')
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.publish.assert_not_called()

    def test_revocation_still_dominates_existing_publication_barrier(self):
        self.tick()
        self.pending()
        self.restart()
        self.assertEqual(self.tick().code, 'revocation_pending')
        self.read.assert_not_called()
        self.publish.assert_not_called()

    def assert_restart_blocked_without_io(self, code):
        self.restart()
        self.assertEqual(self.tick().code, code)
        self.f.inspect.assert_not_called()
        self.read.assert_not_called()
        self.publish.assert_not_called()
        with private_directory_writer(self.fd):
            pass

    def test_interrupted_publication_restart_keeps_durable_barrier(self):
        self.publish.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.tick()
        marker = load_pending(self.fd, self.updater._publication_digest)
        self.assertIsNotNone(marker)
        self.assert_restart_blocked_without_io('publication_reconciliation_required')
        self.assertEqual(load_pending(self.fd, self.updater._publication_digest), marker)

    def test_truncated_publication_barrier_refuses_without_repair(self):
        self.tick()
        name = self.updater._publication_digest + '.pending'
        fd = os.open(name, os.O_WRONLY | os.O_TRUNC, dir_fd=self.fd)
        try:
            os.write(fd, b'broken\n')
        finally:
            os.close(fd)
        self.assert_restart_blocked_without_io('journal_unavailable')
        self.assertEqual(os.stat(name, dir_fd=self.fd).st_size, 7)

    def test_crash_left_hardlink_refuses_without_cleanup(self):
        self.tick()
        name = self.updater._publication_digest + '.pending'
        orphan = '.pending-' + 'a' * 32
        os.link(name, orphan, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        self.assert_restart_blocked_without_io('journal_unavailable')
        self.assertEqual(os.stat(name, dir_fd=self.fd).st_nlink, 2)
        self.assertEqual(os.stat(orphan, dir_fd=self.fd).st_ino,
                         os.stat(name, dir_fd=self.fd).st_ino)

    def test_symlink_barrier_refused_without_following_or_deleting(self):
        self.tick()
        name = self.updater._publication_digest + '.pending'
        os.rename(name, 'saved-record', src_dir_fd=self.fd, dst_dir_fd=self.fd)
        os.symlink('saved-record', name, dir_fd=self.fd)
        self.assert_restart_blocked_without_io('journal_unavailable')
        self.assertEqual(os.readlink(name, dir_fd=self.fd), 'saved-record')

    def test_directory_sync_failure_leaves_restart_blocked_without_publication(self):
        real_fsync = os.fsync
        calls = []
        def fsync(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('synthetic directory sync failure')
            return real_fsync(fd)
        with patch('phase_loop_runtime.vendor_access_pending.os.fsync', side_effect=fsync):
            self.assertEqual(self.tick().code, 'journal_unavailable')
        self.assertEqual(len(calls), 2)
        self.publish.assert_not_called()
        self.assertIsNotNone(load_pending(self.fd, self.updater._publication_digest))
        self.assert_restart_blocked_without_io('publication_reconciliation_required')

    def test_older_alternating_instance_is_retired_before_suppression(self):
        self.tick()
        older = self.updater
        self.restart()
        self.read.return_value = replace(self.snapshot, access=b'newer')
        self.assertEqual(self.tick().code, 'persisted_pending_application')
        self.read.return_value = self.snapshot
        self.updater = older
        self.f.inspect.reset_mock()
        self.read.reset_mock()
        self.publish.reset_mock()
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')
        self.f.inspect.assert_not_called()
        self.read.assert_not_called()
        self.publish.assert_not_called()

    def test_ack_restart_durability_precedes_preflight_and_failure_retires(self):
        self.tick()
        self.restart()
        with patch('phase_loop_runtime.vendor_access_publication_journal.os.fsync', side_effect=OSError):
            self.assertEqual(self.tick().code, 'journal_unavailable')
        self.f.inspect.assert_not_called()
        self.read.assert_not_called()
        self.publish.assert_not_called()
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')

    def test_barrier_and_prepared_pre_call_crashes_block_restart(self):
        from phase_loop_runtime.vendor_access_publication_journal import transition_publication
        for after_write in (False, True):
            f = UpdaterTests()
            f.setUp()
            try:
                def crash(*args, **kw):
                    if after_write:
                        transition_publication(*args, **kw)
                    raise KeyboardInterrupt
                with patch('phase_loop_runtime.vendor_access_updater.transition_publication', side_effect=crash):
                    with self.assertRaises(KeyboardInterrupt):
                        f.tick()
                f.publish.assert_not_called()
                f.assert_restart_blocked_without_io('publication_reconciliation_required')
            finally:
                f.doCleanups()

    def test_ack_write_fault_boundaries_and_order(self):
        from phase_loop_runtime import vendor_access_publication_journal as journal
        for fail_at in range(1, 7):
            f = UpdaterTests()
            f.setUp()
            events = []
            real_sync = os.fsync
            def sync(fd):
                events.append('sync')
                if events.count('sync') == fail_at:
                    raise OSError('synthetic durability fault')
                real_sync(fd)
            def publish(*args):
                events.append('send')
                record = journal.load_publication(f.fd, f.updater._digest)
                self.assertEqual(record.phase, 'prepared')
                self.assertEqual(record.attempt_id, args[2])
                return field(3, 'mutation')
            f.publish.side_effect = publish
            try:
                with patch.object(journal.os, 'fsync', side_effect=sync):
                    self.assertEqual(f.tick().code, 'journal_unavailable')
                self.assertIsNone(f.updater._acknowledged)
                self.assertEqual(f.tick().code, 'publication_reconciliation_required')
                if fail_at <= 4:
                    self.assertNotIn('send', events)
                else:
                    self.assertEqual(events.index('send'), 4)
                f.restart()
                # Only ACK rename followed by failed directory sync exposes ACK.
                code = 'persisted_pending_application' if fail_at == 6 else 'publication_reconciliation_required'
                if fail_at == 1:  # barrier temp never became visible: virgin
                    code = 'persisted_pending_application'
                self.assertEqual(f.tick().code, code)
                if code == 'publication_reconciliation_required':
                    f.f.inspect.assert_not_called()
                    f.read.assert_not_called()
                    f.publish.assert_not_called()
            finally:
                f.doCleanups()

    def test_final_revocation_after_prepared_blocks_without_send(self):
        from phase_loop_runtime.vendor_access_publication_journal import transition_publication, load_publication
        def prepare(*args, **kw):
            result = transition_publication(*args, **kw)
            self.pending()
            return result
        with patch('phase_loop_runtime.vendor_access_updater.transition_publication', side_effect=prepare):
            self.assertEqual(self.tick().code, 'revocation_pending')
        self.publish.assert_not_called()
        marker = load_pending(self.fd, self.f.activation.binding_sha256)
        record = load_publication(self.fd, self.updater._digest)
        self.assertEqual(record.phase, 'prepared')
        self.assertEqual(record.attempt_id, record.barrier_id)
        self.assert_restart_blocked_without_io('revocation_pending')
        self.assertEqual(load_publication(self.fd, self.updater._digest), record)
        self.assertEqual(load_pending(self.fd, self.f.activation.binding_sha256), marker)

    def test_legacy_or_journal_only_or_wrong_barrier_refuses(self):
        from phase_loop_runtime import vendor_access_publication_journal as journal
        for state in ('legacy', 'journal_only', 'wrong_barrier'):
            f = UpdaterTests()
            f.setUp()
            try:
                f.tick()
                digest = f.updater._publication_digest
                if state == 'legacy':
                    os.unlink(digest + '.publication.json', dir_fd=f.fd)
                elif state == 'journal_only':
                    os.unlink(digest + '.pending', dir_fd=f.fd)
                else:
                    record = journal.load_publication(f.fd, f.updater._digest)
                    fd = os.open(digest + '.publication.json', os.O_WRONLY | os.O_TRUNC, dir_fd=f.fd)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(journal.canonical(replace(record, barrier_id='00000000-0000-0000-0000-000000000001')))
                f.assert_restart_blocked_without_io('publication_reconciliation_required')
            finally:
                f.doCleanups()

    def test_restart_negative_preflight_and_source_controls(self):
        from phase_loop_runtime.vendor_access_publication_journal import load_publication
        self.assertEqual(self.tick().code, 'persisted_pending_application')
        saved = load_publication(self.fd, self.updater._digest)
        barrier = load_pending(self.fd, self.updater._publication_digest)
        self.restart()
        def unchanged():
            self.publish.assert_not_called()
            self.assertEqual(load_publication(self.fd, self.updater._digest), saved)
            self.assertEqual(load_pending(self.fd, self.updater._publication_digest), barrier)
        for metadata in (replace(self.f.metadata, resource_version=0),
                         replace(self.f.metadata, workspace='wrong'),
                         replace(self.f.metadata, profile_sha256='c' * 64),
                         replace(self.f.metadata, gateway_refresh_enabled=True)):
            self.f.inspect.return_value = metadata
            self.assertNotEqual(self.tick().code, 'persisted_pending_application')
            unchanged()
        self.publish.assert_not_called()
        self.f.inspect.return_value = self.f.metadata
        for source in (None, replace(self.snapshot, identity_digest='wrong'),
                       replace(self.snapshot, expires_at=900)):
            self.read.return_value = source
            self.assertEqual(self.tick().code, 'source_unverified')
            unchanged()
        self.publish.assert_not_called()

    def test_restart_ack_sync_then_preflight_reads_prepared_send_ack_order(self):
        from phase_loop_runtime import vendor_access_publication_journal as journal
        self.tick()
        self.restart()
        events = []
        real_sync = os.fsync
        def sync(fd):
            events.append('dir' if os.path.isdir('/proc/self/fd/' + str(fd)) else 'file')
            real_sync(fd)
        def inspect(binding):
            events.append('inspect')
            return self.f.metadata
        def read(binding):
            events.append('read')
            return self.snapshot
        def publish(*args):
            events.append('send')
            return field(3, 'mutation')
        self.f.inspect.side_effect = inspect
        self.read.side_effect = read
        self.publish.side_effect = publish
        with patch.object(journal.os, 'fsync', side_effect=sync):
            self.assertEqual(self.tick().code, 'persisted_pending_application')
        self.assertEqual(events, ['file', 'dir', 'inspect', 'read', 'read',
                                  'file', 'dir', 'file', 'dir', 'send', 'file', 'dir'])

    def test_prepared_revocation_dominates_and_preserves_both_records(self):
        self.publish.side_effect = RuntimeError('receiver stored but response lost')
        self.tick()
        self.pending()
        from phase_loop_runtime.vendor_access_publication_journal import load_publication
        record = load_publication(self.fd, self.updater._digest)
        self.assertEqual(record.phase, 'prepared')
        self.assert_restart_blocked_without_io('revocation_pending')
        self.assertEqual(load_publication(self.fd, self.updater._digest), record)

    def test_later_prepared_failure_before_replace_retains_ack_without_send(self):
        self.tick()
        self.read.return_value = replace(self.snapshot, access=b'changed')
        self.publish.reset_mock()
        with patch('phase_loop_runtime.vendor_access_publication_journal.os.replace', side_effect=OSError):
            self.assertEqual(self.tick().code, 'journal_unavailable')
        self.publish.assert_not_called()
        self.restart()
        self.assertEqual(self.tick().code, 'persisted_pending_application')
        self.publish.assert_called_once()

    def test_journal_blocking_io_error_is_not_writer_contention(self):
        self.tick()
        self.restart()
        with patch('phase_loop_runtime.vendor_access_publication_journal.os.fsync',
                   side_effect=BlockingIOError):
            self.assertEqual(self.tick().code, 'journal_unavailable')
        self.f.inspect.assert_not_called()
        self.assertEqual(self.tick().code, 'publication_reconciliation_required')

    def test_forbidden_sinks_exclude_access_encodings(self):
        import base64
        import json
        from urllib.parse import quote_from_bytes
        self.snapshot = replace(self.snapshot, access=b'CANARY+/sink')
        self.read.return_value = self.snapshot
        results = [self.tick(), self.tick()]
        self.read.return_value = replace(self.snapshot, expires_at=1900)
        results.append(self.tick())
        self.restart()
        results.append(self.tick())
        raw = self.snapshot.access
        forbidden = (raw, base64.b64encode(raw), base64.urlsafe_b64encode(raw),
                     json.dumps(raw.decode())[1:-1].encode(), quote_from_bytes(raw, safe='').encode())
        sinks = [repr(results).encode()]
        for name in os.listdir(self.fd):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
            with os.fdopen(fd, 'rb') as stream:
                sinks.append(stream.read(1025))
        for sink in sinks:
            for secret in forbidden:
                self.assertNotIn(secret, sink)

    def test_recovered_ack_revocation_during_reads_and_after_prepared(self):
        from phase_loop_runtime.vendor_access_publication_journal import transition_publication, load_publication
        for boundary in ('reads', 'prepared'):
            with self.subTest(boundary=boundary):
                f = UpdaterTests()
                f.setUp()
                try:
                    self.assertEqual(f.tick().code, 'persisted_pending_application')
                    acknowledged = load_publication(f.fd, f.updater._digest)
                    barrier = load_pending(f.fd, f.updater._publication_digest)
                    self.assertEqual(acknowledged.phase, 'acknowledged')
                    f.restart()
                    def read(binding):
                        f.pending()
                        return f.snapshot
                    def prepare(*args, **kw):
                        result = transition_publication(*args, **kw)
                        f.pending()
                        return result
                    if boundary == 'reads':
                        f.read.side_effect = read
                        self.assertEqual(f.tick().code, 'revocation_pending')
                    else:
                        with patch('phase_loop_runtime.vendor_access_updater.transition_publication', side_effect=prepare):
                            self.assertEqual(f.tick().code, 'revocation_pending')
                    record = load_publication(f.fd, f.updater._digest)
                    if boundary == 'reads':
                        self.assertEqual(record, acknowledged)
                    else:
                        self.assertEqual(record.phase, 'prepared')
                        self.assertNotEqual(record.attempt_id, acknowledged.attempt_id)
                        self.assertEqual(record.barrier_id, barrier)
                    self.assertEqual(load_pending(f.fd, f.updater._publication_digest), barrier)
                    f.publish.assert_not_called()
                    marker = load_pending(f.fd, f.f.activation.binding_sha256)
                    self.assertIsNotNone(marker)
                    f.assert_restart_blocked_without_io('revocation_pending')
                    self.assertEqual(load_pending(f.fd, f.f.activation.binding_sha256), marker)
                    self.assertEqual(load_publication(f.fd, f.updater._digest), record)
                    self.assertEqual(load_pending(f.fd, f.updater._publication_digest), barrier)
                finally:
                    f.doCleanups()
