import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phase_loop_runtime.vendor_access_pending import load_pending, record_pending, recover_pending_link

DIGEST = 'a' * 64
FIRST = '00000000-0000-0000-0000-000000000001'
SECOND = '00000000-0000-0000-0000-000000000002'


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.close, self.fd)

    def test_reopen_preserves_pending_and_repeated_record(self):
        self.assertIsNone(load_pending(self.fd, DIGEST))
        record_pending(self.fd, DIGEST, FIRST)
        other = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(load_pending(other, DIGEST), FIRST)
            self.assertEqual(record_pending(other, DIGEST, FIRST), FIRST)
        finally:
            os.close(other)
        self.assertEqual(len(list(self.path.iterdir())), 1)

    def test_conflict_cannot_replace_pending(self):
        record_pending(self.fd, DIGEST, FIRST)
        with self.assertRaisesRegex(ValueError, 'pending_operation_conflict'):
            record_pending(self.fd, DIGEST, SECOND)
        self.assertEqual(load_pending(self.fd, DIGEST), FIRST)

    def test_data_sync_failure_never_publishes(self):
        with patch('phase_loop_runtime.vendor_access_pending.os.fsync', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                record_pending(self.fd, DIGEST, FIRST)
        self.assertIsNone(load_pending(self.fd, DIGEST))
        self.assertEqual(list(self.path.iterdir()), [])

    def test_directory_sync_failure_keeps_recoverable_intent(self):
        sync = os.fsync
        def fail_directory(fd):
            if fd == self.fd:
                raise OSError('directory sync failed')
            sync(fd)
        with patch('phase_loop_runtime.vendor_access_pending.os.fsync', side_effect=fail_directory):
            with self.assertRaises(OSError):
                record_pending(self.fd, DIGEST, FIRST)
        self.assertEqual(load_pending(self.fd, DIGEST), FIRST)
        record_pending(self.fd, DIGEST, FIRST)

    def test_unsafe_files_and_directory_refuse(self):
        target = self.path / (DIGEST + '.pending')
        target.symlink_to(self.path / 'missing')
        with self.assertRaises(OSError):
            load_pending(self.fd, DIGEST)
        target.unlink()
        target.write_text('bad')
        with self.assertRaises(ValueError):
            load_pending(self.fd, DIGEST)
        self.path.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'unsafe_pending_directory'):
            record_pending(self.fd, DIGEST, FIRST)
        self.path.chmod(0o700)

    def test_interrupted_publication_preserves_intent_but_refuses_use(self):
        # Simulate failure after the final link exists but before temp unlink.
        with patch('phase_loop_runtime.vendor_access_pending.os.unlink',
                   side_effect=OSError('interrupted cleanup')):
            with self.assertRaises(OSError):
                record_pending(self.fd, DIGEST, FIRST)
        target = self.path / (DIGEST + '.pending')
        self.assertEqual(target.read_text(), FIRST + '\n')
        self.assertEqual(target.stat().st_nlink, 2)
        with self.assertRaisesRegex(ValueError, 'unsafe_pending_record'):
            load_pending(self.fd, DIGEST)
        with self.assertRaisesRegex(ValueError, 'unsafe_pending_record'):
            record_pending(self.fd, DIGEST, SECOND)
        self.assertEqual(target.read_text(), FIRST + '\n')

    def test_fifo_refuses_without_waiting_for_a_writer(self):
        os.mkfifo(self.path / (DIGEST + '.pending'), 0o600)
        with self.assertRaisesRegex(ValueError, 'unsafe_pending_record'):
            load_pending(self.fd, DIGEST)

    def test_record_permission_change_refuses(self):
        record_pending(self.fd, DIGEST, FIRST)
        target = self.path / (DIGEST + '.pending')
        target.chmod(0o640)
        with self.assertRaisesRegex(ValueError, 'unsafe_pending_record'):
            load_pending(self.fd, DIGEST)
        with self.assertRaisesRegex(ValueError, 'unsafe_pending_record'):
            record_pending(self.fd, DIGEST, FIRST)
        self.assertEqual(target.read_text(), FIRST + '\n')

    def _publication_orphan(self):
        with patch('phase_loop_runtime.vendor_access_pending.os.unlink',
                   side_effect=OSError('interrupted cleanup')):
            with self.assertRaises(OSError):
                record_pending(self.fd, DIGEST, FIRST)
        return next(p.name for p in self.path.iterdir() if p.name.startswith('.pending-'))

    def test_explicit_orphan_recovery_preserves_operation(self):
        temporary = self._publication_orphan()
        self.assertEqual(recover_pending_link(self.fd, DIGEST, temporary), FIRST)
        self.assertEqual(load_pending(self.fd, DIGEST), FIRST)
        self.assertFalse((self.path / temporary).exists())
        self.assertEqual((self.path / (DIGEST + '.pending')).stat().st_nlink, 1)

    def test_recovery_refuses_unrelated_file_and_symlink(self):
        temporary = self._publication_orphan()
        other = self.path / ('.pending-' + 'f' * 32)
        other.write_text(FIRST + '\n')
        other.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'pending_orphan_mismatch'):
            recover_pending_link(self.fd, DIGEST, other.name)
        other.unlink()
        other.symlink_to(self.path / temporary)
        with self.assertRaisesRegex(ValueError, 'pending_orphan_mismatch'):
            recover_pending_link(self.fd, DIGEST, other.name)
        self.assertTrue((self.path / temporary).exists())
        self.assertTrue(other.is_symlink())

    def test_recovery_sync_failure_does_not_remove_orphan(self):
        temporary = self._publication_orphan()
        with patch('phase_loop_runtime.vendor_access_pending.os.fsync', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                recover_pending_link(self.fd, DIGEST, temporary)
        self.assertTrue((self.path / temporary).exists())
        with self.assertRaisesRegex(ValueError, 'unsafe_pending_record'):
            load_pending(self.fd, DIGEST)

    def test_invalid_identifiers_cannot_create_files(self):
        for digest, identifier in (('../escape', FIRST), (DIGEST, 'secret-value')):
            with self.assertRaises(ValueError):
                record_pending(self.fd, digest, identifier)
        self.assertEqual(list(self.path.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
