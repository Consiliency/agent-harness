import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan
from phase_loop_runtime.cli import main
from phase_loop_runtime.events import read_events


def _head(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def _run(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class PhaseLoopReconcileRecoveryModeTest(unittest.TestCase):
    def _reconcile_args(self, repo: Path, roadmap: Path, *extra: str) -> list[str]:
        return ["reconcile", "--repo", str(repo), "--roadmap", str(roadmap), "--phase", "RUNNER", *extra]

    def test_recovery_mode_allows_dirty_tree_without_allow_dirty(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

            code, _, stderr = _run(
                self._reconcile_args(
                    repo,
                    roadmap,
                    "--recovery-mode",
                    "--closeout-commit",
                    _head(repo),
                    "--repair-summary",
                    "dirty recovery",
                    "--verification-status",
                    "passed",
                )
            )

            self.assertEqual(code, 0, stderr)
            manual_repair = read_events(repo)[-1]["metadata"]["manual_repair"]
            self.assertTrue(manual_repair["recovery_mode"])
            self.assertEqual(manual_repair["repair_summary"], "dirty recovery")
            self.assertEqual(manual_repair["verification_status"], "passed")

    def test_legacy_reconcile_still_rejects_dirty_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

            code, _, stderr = _run(self._reconcile_args(repo, roadmap))

            self.assertEqual(code, 2)
            self.assertIn("working tree is dirty", stderr)

    def test_allow_dirty_continues_without_recovery_mode(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

            code, _, stderr = _run(self._reconcile_args(repo, roadmap, "--allow-dirty"))

            self.assertEqual(code, 0, stderr)
            manual_repair = read_events(repo)[-1]["metadata"]["manual_repair"]
            self.assertNotIn("recovery_mode", manual_repair)
            self.assertEqual(manual_repair["verification_status"], "not_run")

    def test_recovery_mode_allows_dirty_plan_doc(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            plan = write_phase_plan(repo, "RUNNER", roadmap)
            commit_fixture_paths(repo, "add runner plan", plan)
            plan.write_text(plan.read_text(encoding="utf-8") + "\noperator recovery note\n", encoding="utf-8")

            code, _, stderr = _run(
                self._reconcile_args(
                    repo,
                    roadmap,
                    "--recovery-mode",
                    "--closeout-commit",
                    _head(repo),
                    "--repair-summary",
                    "dirty plan doc recovery",
                    "--verification-status",
                    "passed",
                )
            )

            self.assertEqual(code, 0, stderr)
            self.assertTrue(read_events(repo)[-1]["metadata"]["manual_repair"]["recovery_mode"])

    def test_recovery_mode_requires_closeout_commit(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"

            code, _, stderr = _run(
                self._reconcile_args(
                    repo,
                    roadmap,
                    "--recovery-mode",
                    "--repair-summary",
                    "missing closeout",
                    "--verification-status",
                    "passed",
                )
            )

            self.assertEqual(code, 2)
            self.assertIn("--closeout-commit", stderr)

    def test_recovery_mode_requires_repair_summary(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"

            code, _, stderr = _run(
                self._reconcile_args(
                    repo,
                    roadmap,
                    "--recovery-mode",
                    "--closeout-commit",
                    _head(repo),
                    "--verification-status",
                    "passed",
                )
            )

            self.assertEqual(code, 2)
            self.assertIn("--repair-summary", stderr)

    def test_recovery_mode_requires_verification_status(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"

            code, _, stderr = _run(
                self._reconcile_args(
                    repo,
                    roadmap,
                    "--recovery-mode",
                    "--closeout-commit",
                    _head(repo),
                    "--repair-summary",
                    "missing verification",
                )
            )

            self.assertEqual(code, 2)
            self.assertIn("--verification-status", stderr)


if __name__ == "__main__":
    unittest.main()
