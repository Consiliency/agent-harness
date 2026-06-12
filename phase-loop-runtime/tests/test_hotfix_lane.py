import json
import sys
import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime.cli import main
from phase_loop_runtime.events import read_events
from phase_loop_test_utils import commit_fixture_paths, make_repo


class HotfixLaneTest(unittest.TestCase):
    def test_init_stub_writes_stub_without_run_directory(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            stub = repo / "hotfixes" / "prod-fix.md"

            code = main(["hotfix", "--repo", str(repo), "--init-stub", "hotfixes/prod-fix.md", "--json"])

            self.assertEqual(code, 0)
            self.assertIn("objective:", stub.read_text(encoding="utf-8"))
            self.assertIn("verification_command:", stub.read_text(encoding="utf-8"))
            self.assertFalse((repo / ".phase-loop" / "runs").exists())

    def test_execute_requires_reason_and_plan(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))

            self.assertEqual(main(["hotfix", "--repo", str(repo), "--plan", "stub.md"]), 2)
            self.assertEqual(main(["hotfix", "--repo", str(repo), "--reason", "bounded fix"]), 2)

    def test_hotfix_execution_records_artifact_paths_and_event_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "---\n"
                "automation:\n"
                f"  suite_command: [{sys.executable!r}, -c, 'print(\"suite\")']\n"
                "---\n"
                "# Roadmap\n\n"
                "### Phase 0 - Hotfix (HL)\n",
                encoding="utf-8",
            )
            stub = repo / "hotfix.md"
            stub.write_text(
                "objective: bounded incident fix\n"
                f"verification_command: {sys.executable} -c \"print('hotfix')\"\n",
                encoding="utf-8",
            )
            commit_fixture_paths(repo, "add hotfix inputs", roadmap, stub)

            code = main(
                [
                    "hotfix",
                    "--repo",
                    str(repo),
                    "--roadmap",
                    str(roadmap),
                    "--reason",
                    "bounded production fix",
                    "--plan",
                    str(stub),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            run_dirs = sorted((repo / ".phase-loop" / "runs").glob("*-hotfix-hotfix"))
            self.assertEqual(len(run_dirs), 1)
            self.assertTrue((run_dirs[0] / "launch.json").exists())
            self.assertTrue((run_dirs[0] / "verification.json").exists())
            self.assertTrue((run_dirs[0] / "verification.log").exists())
            launch = json.loads((run_dirs[0] / "launch.json").read_text(encoding="utf-8"))
            self.assertEqual(launch["work_unit"], "hotfix")
            self.assertEqual(launch["plan_stub"], str(stub))

            event = read_events(repo)[-1]
            hotfix = event["metadata"]["hotfix_closeout"]
            self.assertEqual(event["action"], "hotfix.closeout")
            self.assertEqual(event["status"], "complete")
            self.assertEqual(event["metadata"]["work_unit"], "hotfix")
            self.assertEqual(hotfix["work_unit"], "hotfix")
            self.assertEqual(hotfix["verification_exit_summary"]["commands"], [0])
            self.assertEqual(hotfix["verification_exit_summary"]["suite"], 0)
            self.assertEqual(hotfix["artifact_validation"]["code"], "ok")

    def test_hotfix_verification_failure_blocks_event(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text("# Roadmap\n\n### Phase 0 - Hotfix (HL)\n", encoding="utf-8")
            stub = repo / "hotfix.md"
            stub.write_text(
                "objective: bounded incident fix\n"
                f"verification_command: {sys.executable} -c \"raise SystemExit(7)\"\n",
                encoding="utf-8",
            )
            commit_fixture_paths(repo, "add hotfix inputs", roadmap, stub)

            code = main(
                [
                    "hotfix",
                    "--repo",
                    str(repo),
                    "--roadmap",
                    str(roadmap),
                    "--reason",
                    "bounded production fix",
                    "--plan",
                    str(stub),
                    "--json",
                ]
            )

            self.assertEqual(code, 1)
            event = read_events(repo)[-1]
            self.assertEqual(event["status"], "blocked")
            self.assertEqual(event["blocker"]["blocker_class"], "verification_evidence_missing")
            self.assertEqual(event["metadata"]["terminal_summary"]["verification_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
