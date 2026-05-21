import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from phase_loop_runtime.cli import main


class PhaseLoopInitTest(unittest.TestCase):
    def test_init_creates_gitignore_entry_and_handoffs_dir(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))

            self.assertEqual(self._main(["init", "--repo", str(repo)]), 0)

            self.assertIn("/.dev-skills/", (repo / ".gitignore").read_text(encoding="utf-8").splitlines())
            self.assertTrue((repo / ".dev-skills" / "handoffs").is_dir())

    def test_init_is_idempotent_and_deduplicates_gitignore(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))

            self._main(["init", "--repo", str(repo)])
            self._main(["init", "--repo", str(repo)])

            lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines.count("/.dev-skills/"), 1)

    def test_init_preserves_existing_gitignore(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")

            self._main(["init", "--repo", str(repo)])

            self.assertEqual((repo / ".gitignore").read_text(encoding="utf-8").splitlines(), ["node_modules/", "/.dev-skills/"])

    def test_init_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            output = StringIO()

            with redirect_stdout(output):
                self.assertEqual(main(["init", "--repo", str(repo), "--dry-run", "--json"]), 0)

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["dry_run"])
            self.assertTrue(payload["gitignore_changed"])
            self.assertFalse((repo / ".gitignore").exists())
            self.assertFalse((repo / ".dev-skills").exists())

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        return repo

    def _main(self, argv: list[str]) -> int:
        with redirect_stdout(StringIO()):
            return main(argv)


if __name__ == "__main__":
    unittest.main()
