import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime.closeout_validation import extract_plan_produces, validate_produced_gates
from phase_loop_test_utils import make_repo, write_phase_plan


class PhaseLoopCloseoutValidationTest(unittest.TestCase):
    def test_matching_produced_gates_pass(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            plan = self._write_native_plan(repo)

            result = validate_produced_gates(
                plan,
                {"terminal_status": "complete", "produced_if_gates": ["IF-0-NATIVE-1", "IF-0-NATIVE-2"]},
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.missing_gates, ())
            self.assertEqual(result.unexpected_gates, ())

    def test_mismatched_produced_gates_reject(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            plan = self._write_native_plan(repo)

            result = validate_produced_gates(
                plan,
                {"terminal_status": "complete", "produced_if_gates": ["IF-0-NATIVE-1", "IF-0-NATIVE-9"]},
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.blocker_class, "contract_bug")
            self.assertEqual(result.missing_gates, ("IF-0-NATIVE-2",))
            self.assertEqual(result.unexpected_gates, ("IF-0-NATIVE-9",))

    def test_missing_produced_gates_soft_warns_during_native(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            plan = self._write_native_plan(repo)

            result = validate_produced_gates(plan, {"terminal_status": "complete"})

            self.assertTrue(result.ok)
            self.assertIn("compatibility window", result.warning)

    def test_present_empty_complete_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            plan = self._write_native_plan(repo)

            result = validate_produced_gates(plan, {"terminal_status": "complete", "produced_if_gates": []})

            self.assertFalse(result.ok)
            self.assertEqual(result.blocker_summary, "completed closeout reported zero produced_if_gates")

    def test_extract_plan_produces_reads_produces_and_lane_interfaces(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            plan = self._write_native_plan(repo)

            self.assertEqual(extract_plan_produces(plan), ("IF-0-NATIVE-1", "IF-0-NATIVE-2"))

    def _write_native_plan(self, repo: Path) -> Path:
        roadmap = repo / "specs" / "phase-plans-v1.md"
        return write_phase_plan(
            repo,
            "RUNNER",
            roadmap,
            body=(
                "# RUNNER\n\n"
                "**Produces**: `IF-0-NATIVE-1`\n\n"
                "## Lanes\n\n"
                "### SL-0 - Contract\n"
                "- **Owned files**: `contract.py`\n"
                "- **Interfaces provided**: `IF-0-NATIVE-2`\n"
            ),
        )


if __name__ == "__main__":
    unittest.main()
