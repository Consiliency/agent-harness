"""Private synthetic state and fault boundaries; no transport or native reader."""
from dataclasses import replace
import json
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from phase_loop_runtime import vendor_access_publication_journal as journal
from phase_loop_runtime.vendor_access_writer import private_directory_writer


class JournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fd = os.open(temp.name, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.digest = 'a' * 64
        self.a = '00000000-0000-0000-0000-000000000001'
        self.b = '00000000-0000-0000-0000-000000000002'
        self.prepared = journal.PublicationRecord(1, self.digest, self.a, self.a, 'prepared')
        self.ack = replace(self.prepared, phase='acknowledged')
        self.name = journal._record_name(self.fd, self.digest)

    def put(self, raw):
        fd = os.open(self.name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600, dir_fd=self.fd)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)

    def load(self, **kw):
        return journal.load_publication(self.fd, self.digest, **kw)

    def move(self, old, new, **kw):
        with private_directory_writer(self.fd):
            return journal.transition_publication(self.fd, self.digest, old, new, **kw)

    def first(self):
        return self.move(None, self.prepared, barrier_created=True)

    def test_closed_transition_table_and_stale_ack(self):
        self.assertIsNone(self.load())
        with self.assertRaises(ValueError):
            self.move(None, self.prepared)
        self.first()
        for old, new in ((self.prepared, self.prepared), (None, self.prepared),
                         (self.prepared, replace(self.ack, attempt_id=self.b)),
                         (self.prepared, replace(self.ack, barrier_id=self.b))):
            with self.assertRaises(ValueError):
                self.move(old, new, barrier_created=True)
        self.move(self.prepared, self.ack)
        with self.assertRaises(ValueError):
            self.move(self.ack, self.ack)
        newer = replace(self.prepared, attempt_id=self.b)
        self.move(self.ack, newer)
        with self.assertRaises(ValueError):
            self.move(self.prepared, self.ack)
        self.assertEqual(self.load(), newer)
        self.move(newer, replace(newer, phase='acknowledged'))
        self.assertEqual(set(os.listdir(self.fd)), {self.name})

    def test_canonical_bounded_minimal_schema(self):
        good = journal.canonical(self.prepared)
        obj = json.loads(good)
        self.assertEqual(set(obj), {'version', 'binding_sha256', 'barrier_id', 'attempt_id', 'phase'})
        bad = [b'', good[:-2], b'x'*1025, b'CANARY',
               good.replace(b'"version":1', b'"version":true'),
               good.replace(b'"version":1', b'"version":2'),
               good.replace(b'"version":1', b'"version":1,"version":1'),
               good.replace(b'"version":1', b'"extra":0,"version":1'),
               good.replace(b'"version":1', b'"version":1.0'),
               good.replace(b'prepared', b'unknown'),
               good.replace(self.digest.encode(), b'b'*64),
               json.dumps(obj, indent=2).encode()]
        for raw in bad:
            with self.subTest(raw=raw):
                self.put(raw)
                with self.assertRaises(ValueError):
                    self.load()
        self.put(good)
        self.assertEqual(self.load(), self.prepared)

    def test_unsafe_types_ownership_and_changed_read(self):
        self.first()
        os.chmod(self.name, 0o644, dir_fd=self.fd)
        with self.assertRaises(ValueError):
            self.load()
        os.chmod(self.name, 0o600, dir_fd=self.fd)
        real_stat = os.fstat
        def foreign_file(fd):
            result = real_stat(fd)
            if stat.S_ISREG(result.st_mode):
                fields = list(result)
                fields[4] = os.geteuid() + 1
                return os.stat_result(fields)
            return result
        with patch.object(journal.os, 'fstat', side_effect=foreign_file):
            with self.assertRaisesRegex(ValueError, '^unsafe_publication_record$'):
                self.load()
        real_read = os.read
        def changed(fd, size):
            raw = real_read(fd, size)
            os.utime(self.name, ns=(1, 1), dir_fd=self.fd)
            return raw
        with patch.object(journal.os, 'read', side_effect=changed):
            with self.assertRaises(ValueError):
                self.load()
        os.link(self.name, 'orphan', src_dir_fd=self.fd, dst_dir_fd=self.fd)
        with self.assertRaises(ValueError):
            self.load()
        os.unlink(self.name, dir_fd=self.fd)
        os.symlink('orphan', self.name, dir_fd=self.fd)
        with self.assertRaises(OSError):
            self.load()
        os.unlink(self.name, dir_fd=self.fd)
        os.mkfifo(self.name, 0o600, dir_fd=self.fd)
        with self.assertRaises(ValueError):
            self.load()  # O_NONBLOCK prevents holding the lock indefinitely

    def test_first_link_never_overwrites_racing_destination(self):
        real_link = os.link
        def race(*args, **kw):
            self.put(b'preserve')
            return real_link(*args, **kw)
        with patch.object(journal.os, 'link', side_effect=race):
            with self.assertRaises(FileExistsError):
                self.first()
        self.assertEqual(os.listdir(self.fd), [self.name])
        with self.assertRaises(ValueError):
            self.load()

    def test_owned_temporary_cleanup_on_baseexception_and_fsync_failure(self):
        for failure in (OSError, KeyboardInterrupt):
            with patch.object(journal.os, 'fsync', side_effect=failure):
                with self.assertRaises(failure):
                    self.first()
            self.assertEqual(os.listdir(self.fd), [])
            with private_directory_writer(self.fd):
                pass

    def test_replace_failure_preserves_previous_state_and_inert_orphan(self):
        self.first()
        orphan = '.publication-' + 'f'*32
        fd = os.open(orphan, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=self.fd)
        os.close(fd)
        with patch.object(journal.os, 'replace', side_effect=OSError):
            with self.assertRaises(OSError):
                self.move(self.prepared, self.ack)
        self.assertEqual(self.load(), self.prepared)
        self.assertEqual(set(os.listdir(self.fd)), {self.name, orphan})

    def test_ack_directory_sync_failure_visible_ack_can_be_resynced(self):
        self.first()
        real_sync = os.fsync
        def fail_dir(fd):
            if fd == self.fd:
                raise OSError('directory')
            real_sync(fd)
        with patch.object(journal.os, 'fsync', side_effect=fail_dir):
            with self.assertRaises(OSError):
                journal.transition_publication(self.fd, self.digest, self.prepared, self.ack)
        self.assertEqual(self.load(), self.ack)
        calls = []
        with patch.object(journal.os, 'fsync', side_effect=lambda fd: calls.append(fd)):
            self.assertEqual(self.load(durable=True), self.ack)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1], self.fd)
