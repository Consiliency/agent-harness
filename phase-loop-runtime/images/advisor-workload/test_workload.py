"""Small offline tests, run with unittest discovery in this directory."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import check
import prepare


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'release'
        self.source.mkdir()
        (self.source / 'cli').write_bytes(b'fixture')
        self.lock = {'platform': 'linux/amd64', 'files': [{
            'root': 'tooling', 'source': 'cli', 'target': 'bin/cli',
            'sha256': hashlib.sha256(b'fixture').hexdigest(), 'executable': True}]}
        self.output = self.root / 'output'

    def export(self):
        prepare.prepare(self.lock, {'tooling': self.source}, self.output)

    def test_exact_export_excludes_unlisted_files(self):
        (self.source / 'unlisted').write_text('not payload')
        self.export()
        self.assertEqual((self.output / 'bin/cli').read_bytes(), b'fixture')
        self.assertFalse((self.output / 'unlisted').exists())
        self.assertEqual((self.output / 'bin/cli').stat().st_mode & 0o777, 0o755)

    def test_digest_mismatch_does_not_create_context(self):
        (self.source / 'cli').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.export()
        self.assertFalse(self.output.exists())

    def test_symlink_source_rejected(self):
        (self.source / 'link').symlink_to('cli')
        self.lock['files'][0]['source'] = 'link'
        with self.assertRaises(ValueError):
            self.export()

    def test_parent_symlink_escape_rejected(self):
        (self.source / 'escape').symlink_to(self.root)
        self.lock['files'][0]['source'] = 'escape/release/cli'
        # A symlink that resolves back inside is harmless; outside is not.
        (self.root / 'other').write_bytes(b'fixture')
        self.lock['files'][0]['source'] = 'escape/other'
        with self.assertRaises(ValueError):
            self.export()

    def test_path_traversal_rejected(self):
        for field in ('source', 'target'):
            for value in ('../cli', '/absolute', ''):
                with self.subTest(field=field, value=value):
                    old = self.lock['files'][0][field]
                    self.lock['files'][0][field] = value
                    with self.assertRaises(ValueError):
                        self.export()
                    self.lock['files'][0][field] = old

    def test_duplicate_target_rejected(self):
        self.lock['files'].append(copy.deepcopy(self.lock['files'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.export()

    def test_existing_destination_rejected(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            self.export()

    def test_wrong_platform_rejected(self):
        self.lock['platform'] = 'linux/arm64'
        with self.assertRaisesRegex(ValueError, 'platform'):
            self.export()

    def test_lock_covers_four_advisors_and_node(self):
        lock = json.loads(Path(__file__).with_name('payload.lock.json').read_text())
        self.assertEqual(set(lock['artifacts']), {'claude', 'codex', 'agy', 'grok'})
        targets = {f['target'] for f in lock['files']}
        self.assertTrue({'bin/claude', 'bin/agy', 'bin/grok', 'bin/node',
                         'codex/bin/codex', 'codex/codex-path/rg'} <= targets)
        self.assertIn('@sha256:', lock['base'])
        self.assertEqual(len(targets), len(lock['files']))
        for entry in lock['files']:
            self.assertRegex(entry['sha256'], r'^[a-f0-9]{64}$')


class ClosureTests(unittest.TestCase):
    def test_missing_library_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            check.dependencies('libmissing.so => not found', 0)

    def test_failed_inspection_rejected(self):
        with self.assertRaisesRegex(ValueError, 'failed'):
            check.dependencies('ldd: failed', 1)

    def test_static_binary_accepted(self):
        self.assertEqual(check.dependencies('not a dynamic executable\n', 1), set())

    def test_loader_extracted(self):
        blob = bytearray(160)
        blob[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', blob, 18, 62)
        struct.pack_into('<Q', blob, 32, 64)
        struct.pack_into('<HH', blob, 54, 56, 1)
        struct.pack_into('<I', blob, 64, 3)
        struct.pack_into('<Q', blob, 72, 120)
        loader = b'/lib64/ld-linux-x86-64.so.2\0'
        struct.pack_into('<Q', blob, 96, len(loader))
        blob[120:120 + len(loader)] = loader
        self.assertEqual(check.elf_interpreter(blob), loader[:-1].decode())
        blob[4] = 1
        with self.assertRaises(ValueError):
            check.elf_interpreter(blob)


if __name__ == '__main__':
    unittest.main()
