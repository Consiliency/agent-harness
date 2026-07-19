import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phase_loop_runtime.cli import _validate_tracked_closeout_artifact, main
from phase_loop_runtime.events import read_events
from phase_loop_runtime.reconcile import reconcile
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan


def _run(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _fixture(td: Path):
    """Repo with a committed roadmap, RUNNER plan, and RUNNER closeout markdown. Returns
    (repo, roadmap, closeout_relpath, closeout_commit)."""
    repo = make_repo(Path(td))
    roadmap = repo / "specs" / "phase-plans-v1.md"
    plan = write_phase_plan(repo, "RUNNER", roadmap)
    closeout = repo / "planning" / "phase-artifacts" / "RUNNER-closeout.md"
    closeout.parent.mkdir(parents=True, exist_ok=True)
    closeout.write_text("# RUNNER closeout\n\nPhase completed; IF gates satisfied.\n", encoding="utf-8")
    commit_fixture_paths(repo, "add runner plan + closeout", plan, closeout)
    return repo, roadmap, closeout.relative_to(repo).as_posix(), _head(repo)


class ValidateTrackedCloseoutArtifactTest(unittest.TestCase):
    def test_tracked_committed_markdown_is_recovery_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            repo, _roadmap, rel, commit = _fixture(Path(td))
            result = _validate_tracked_closeout_artifact(repo, rel, commit)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["code"], "recovered_from_tracked_closeout")
            self.assertEqual(result["provenance"], "tracked_closeout_artifact")
            self.assertEqual(result["closeout_commit"], commit)

    def test_untracked_markdown_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, _roadmap, _rel, commit = _fixture(Path(td))
            untracked = repo / "planning" / "phase-artifacts" / "GHOST-closeout.md"
            untracked.write_text("# not committed\n", encoding="utf-8")  # on disk, NOT committed
            result = _validate_tracked_closeout_artifact(repo, untracked.relative_to(repo).as_posix(), commit)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "closeout_artifact_not_committed")

    def test_markdown_not_present_at_that_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, _roadmap, rel, _commit = _fixture(Path(td))
            first_commit = subprocess.run(
                ["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            # The closeout was added in a later commit; it does not exist at the initial commit.
            result = _validate_tracked_closeout_artifact(repo, rel, first_commit)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "closeout_artifact_not_committed")

    def test_empty_tracked_markdown_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            empty = repo / "planning" / "EMPTY-closeout.md"
            empty.parent.mkdir(parents=True, exist_ok=True)
            empty.write_text("", encoding="utf-8")
            commit_fixture_paths(repo, "add empty closeout", empty)
            result = _validate_tracked_closeout_artifact(repo, empty.relative_to(repo).as_posix(), _head(repo))
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "empty_closeout_artifact")

    def test_path_outside_repo_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            repo, _roadmap, _rel, commit = _fixture(Path(td))
            stray = Path(outside) / "closeout.md"
            stray.write_text("# outside\n", encoding="utf-8")
            result = _validate_tracked_closeout_artifact(repo, str(stray), commit)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "artifact_outside_repo")


class ReconcileTrackedCloseoutRecoveryTest(unittest.TestCase):
    def _args(self, repo, roadmap, phase, *extra):
        return ["reconcile", "--repo", str(repo), "--roadmap", str(roadmap), "--phase", phase, *extra]

    def test_reconcile_recovers_completed_phase_from_tracked_closeout(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap, rel, commit = _fixture(Path(td))
            code, _out, stderr = _run(
                self._args(
                    repo, roadmap, "RUNNER",
                    "--closeout-artifact", rel,
                    "--closeout-commit", commit,
                    "--repair-summary", "Recovered RUNNER from tracked closeout after interrupted session.",
                    "--verification-status", "passed",
                )
            )
            self.assertEqual(code, 0, stderr)
            repair = read_events(repo)[-1]["metadata"]["manual_repair"]
            self.assertEqual(repair["evidence_provenance"], "tracked_closeout_artifact")
            self.assertEqual(repair["verification_evidence"]["code"], "recovered_from_tracked_closeout")
            # End-to-end: a fresh reconcile now sees RUNNER as complete (not planned/unplanned).
            self.assertEqual(reconcile(repo, roadmap).phases.get("RUNNER"), "complete")

    def test_reconcile_rejects_untracked_closeout_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap, _rel, commit = _fixture(Path(td))
            untracked = repo / "planning" / "phase-artifacts" / "GHOST-closeout.md"
            untracked.write_text("# not committed\n", encoding="utf-8")
            code, _out, stderr = _run(
                self._args(
                    repo, roadmap, "RUNNER",
                    "--closeout-artifact", untracked.relative_to(repo).as_posix(),
                    "--closeout-commit", commit,
                    "--repair-summary", "attempt",
                    "--verification-status", "passed",
                    "--allow-dirty",
                )
            )
            self.assertEqual(code, 2)
            self.assertIn("closeout_artifact_not_committed", stderr)

    def test_closeout_artifact_requires_audit_fields(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap, rel, _commit = _fixture(Path(td))
            code, _out, stderr = _run(
                self._args(repo, roadmap, "RUNNER", "--closeout-artifact", rel, "--verification-status", "passed")
            )
            self.assertEqual(code, 2)
            self.assertIn("--closeout-commit", stderr)

    def test_closeout_artifact_and_verification_log_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap, rel, commit = _fixture(Path(td))
            code, _out, stderr = _run(
                self._args(
                    repo, roadmap, "RUNNER",
                    "--closeout-artifact", rel,
                    "--verification-log", rel,
                    "--closeout-commit", commit,
                    "--repair-summary", "x",
                    "--verification-status", "passed",
                )
            )
            self.assertEqual(code, 2)
            self.assertIn("mutually exclusive", stderr)

    def test_verification_log_path_still_rejects_markdown(self):
        # Regression guard: the runner-verification path is unchanged and still rejects a markdown.
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap, rel, _commit = _fixture(Path(td))
            code, _out, stderr = _run(
                self._args(
                    repo, roadmap, "RUNNER",
                    "--verification-status", "passed",
                    "--verification-log", rel,
                    "--allow-dirty",
                )
            )
            self.assertEqual(code, 2)
            self.assertIn("malformed_artifact", stderr)


if __name__ == "__main__":
    unittest.main()
