"""Bounded path controls for the installed Gate A workspace; no builds or clients."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/gate_a_workspace.py"
spec = importlib.util.spec_from_file_location("gate_a_workspace", SCRIPT)
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=Path.home(), prefix="gate-a-test-"))
        self.addCleanup(shutil.rmtree, self.base)

    def test_private_install_tree_and_cleanup(self):
        result = workspace.create_workspace(self.base, ())
        self.assertEqual(result.parent, self.base)
        self.assertEqual(result.stat().st_mode & 0o777, 0o700)
        self.assertNotEqual(result, workspace.create_workspace(self.base, ()))

    def test_private_leaf_below_writable_ancestor_refused(self):
        ancestor = self.base / "shared"
        ancestor.mkdir()
        ancestor.chmod(0o777)
        leaf = ancestor / "private"
        leaf.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            workspace.create_workspace(leaf, ())
        self.assertEqual(list(leaf.iterdir()), [])

    def test_symlink_ancestor_refused(self):
        real = self.base / "real"
        real.mkdir(mode=0o700)
        (real / "home").mkdir(mode=0o700)
        link = self.base / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            workspace.create_workspace(link / "home", ())

    def test_wrong_home_owner_refused(self):
        original = Path.lstat
        victim = self.base
        def changed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return SimpleNamespace(st_uid=os.getuid() + 1, st_mode=info.st_mode) if path == victim else info
        with patch.object(Path, "lstat", changed), self.assertRaises(ValueError):
            workspace.create_workspace(self.base, ())

    def test_checkout_placement_refused(self):
        with self.assertRaises(ValueError):
            workspace.create_workspace(self.base, (self.base,))
        self.assertEqual(list(self.base.iterdir()), [])

    def test_relative_home_refused(self):
        with self.assertRaises(ValueError):
            workspace.create_workspace(Path("relative"), ())


if __name__ == "__main__":
    unittest.main()
