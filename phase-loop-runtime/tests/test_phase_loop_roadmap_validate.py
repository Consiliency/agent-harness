import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phase_loop_test_utils import make_repo, provenanced_event, provenanced_state, write_phase_plan
from phase_loop_runtime.cli import main
from phase_loop_runtime.events import append_event
from phase_loop_runtime.provenance import (
    phase_provenance_map,
    phase_sha256,
    validate_roadmap_phase_headings,
)


class PhaseLoopRoadmapValidateTest(unittest.TestCase):
    def test_validator_accepts_integer_and_decimal_phase_headings(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "# Roadmap\n\n"
                "### Phase 0 - Contract (CONTRACT)\n\n"
                "### Phase 2.1 - Runner Follow-up (RUNNER2)\n"
            )

            self.assertEqual(validate_roadmap_phase_headings(roadmap), [])
            self.assertIn("CONTRACT", phase_provenance_map(roadmap))
            self.assertIsNotNone(phase_sha256(roadmap, "RUNNER2"))

    def test_validator_reports_loose_candidates_duplicates_and_invalid_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "# Roadmap\n\n"
                "### Phase NOTANUMBER - Bad Number (BAD)\n"
                "### Phase 1 - Duplicate (DUP)\n"
                "### Phase 2 - Duplicate Again (DUP)\n"
                "### Phase 3 - Bad Alias (bad)\n"
            )

            findings = validate_roadmap_phase_headings(roadmap)
            reasons = [finding.reason for finding in findings]
            self.assertTrue(any("loose-match" in reason for reason in reasons))
            self.assertTrue(any("duplicate-alias" in reason for reason in reasons))
            self.assertTrue(any("invalid-alias" in reason for reason in reasons))
            self.assertTrue(all(finding.line_number > 0 for finding in findings))
            self.assertTrue(all(finding.raw_text.startswith("### Phase") for finding in findings))
            self.assertTrue(all(finding.suggested_fix for finding in findings))

    def test_clean_roadmap_has_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"

            self.assertEqual(validate_roadmap_phase_headings(roadmap), [])

    def test_roadmap_aware_entrypoints_warn_without_blocking_or_corrupting_json(self):
        commands = (
            ("run", ["run", "--phase", "RUNNER", "--dry-run"]),
            ("resume", ["resume"]),
            ("dry-run", ["dry-run"]),
            ("status", ["status", "--json"]),
            ("execute", ["execute", "RUNNER", "--output", "{output}", "--mode", "execute", "--dry-run", "--json"]),
            ("reconcile", ["reconcile", "--phase", "RUNNER", "--repair-summary", "fixture"]),
            ("reopen", ["reopen", "--phase", "RUNNER", "--reason", "fixture", "--allow-dirty"]),
            ("monitor", ["monitor", "--once", "--json"]),
            ("evidence-audit", ["evidence-audit"]),
            ("closeout-drift-audit", ["closeout-drift-audit"]),
        )
        for name, command in commands:
            with self.subTest(command=name), tempfile.TemporaryDirectory() as td:
                repo = make_repo(Path(td))
                roadmap = repo / "specs" / "phase-plans-v1.md"
                roadmap.write_text(
                    roadmap.read_text()
                    + "\n### Phase NOTANUMBER - Bad heading (BAD)\n"
                )
                subprocess.run(["git", "add", str(roadmap.relative_to(repo))], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "bad roadmap fixture"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
                plan = write_phase_plan(repo, "RUNNER", roadmap)
                subprocess.run(["git", "add", str(plan.relative_to(repo))], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "runner plan fixture"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
                if name == "reopen":
                    append_event(repo, provenanced_event(repo, roadmap, "RUNNER", "complete"))

                output = Path(td) / "closeout.json"
                argv = [part.format(output=output) for part in command]
                if name == "closeout-drift-audit":
                    argv.extend(["--repo", str(repo), "--roadmap", str(roadmap)])
                else:
                    argv.extend(["--repo", str(repo), "--roadmap", str(roadmap)])

                stdout = io.StringIO()
                stderr = io.StringIO()
                patches = []
                if name in {"run", "dry-run", "execute"}:
                    patches.append(
                        patch(
                            "phase_loop_runtime.cli.run_loop",
                            return_value=(provenanced_state(repo, roadmap, {"RUNNER": "planned"}), []),
                        )
                    )
                if name == "closeout-drift-audit":
                    class CleanDriftAudit:
                        def to_json(self):
                            return {"findings": []}

                        def render_text(self):
                            return "Closeout drift audit: clean"

                        def has_setup_errors(self):
                            return False

                        def has_drift(self):
                            return False

                    patches.append(patch("phase_loop_runtime.phase_loop_drift_audit.run_drift_audit", return_value=CleanDriftAudit()))
                with contextlib.ExitStack() as stack, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    for active_patch in patches:
                        stack.enter_context(active_patch)
                    code = main(argv)

                self.assertNotEqual(code, 2, stderr.getvalue())
                self.assertIn("phase-loop roadmap warning", stderr.getvalue())
                self.assertIn("line", stderr.getvalue())
                self.assertIn("loose-match", stderr.getvalue())
                self.assertIn("Bad heading", stderr.getvalue())
                self.assertIn("suggested fix", stderr.getvalue())
                if "--json" in argv:
                    json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
