import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.launcher import AuthPreflightResult, LaunchResult
from phase_loop_runtime.runner import run_loop
from phase_loop_test_utils import make_repo, write_phase_plan


class PhaseLoopRunnerCloseoutValidationTest(unittest.TestCase):
    def test_complete_with_zero_produced_gates_blocks_as_contract_bug(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = self._native_fixture(Path(td))

            def fake_launch(spec, **_kwargs):
                payload = {
                    "terminal_status": "complete",
                    "verification_status": "passed",
                    "dirty_paths": [],
                    "produced_if_gates": [],
                }
                return LaunchResult(command=spec.command, returncode=0, output=json.dumps(payload), executor=spec.executor)

            with patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})), patch(
                "phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch
            ):
                snapshot, _results = run_loop(repo, roadmap, phase="RUNNER", executor="codex")

            self.assertEqual(snapshot.phases["RUNNER"], "blocked")
            self.assertEqual(snapshot.blocker_class, "contract_bug")
            self.assertIn("zero produced_if_gates", snapshot.blocker_summary)

    def test_complete_with_matching_produced_gates_advances(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = self._native_fixture(Path(td))

            def fake_launch(spec, **_kwargs):
                payload = {
                    "terminal_status": "complete",
                    "verification_status": "passed",
                    "dirty_paths": [],
                    "produced_if_gates": ["IF-0-NATIVE-1"],
                }
                return LaunchResult(command=spec.command, returncode=0, output=json.dumps(payload), executor=spec.executor)

            with patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})), patch(
                "phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch
            ):
                snapshot, _results = run_loop(repo, roadmap, phase="RUNNER", executor="codex")

            self.assertIn(snapshot.phases["RUNNER"], {"complete", "awaiting_phase_closeout"})

    def test_legacy_complete_missing_produced_gates_warns_without_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            repo, roadmap = self._native_fixture(Path(td))

            def fake_launch(spec, **_kwargs):
                output = (
                    "automation:\n"
                    "  status: complete\n"
                    "  next_skill: none\n"
                    "  next_command: none\n"
                    "  human_required: false\n"
                    "  blocker_class: none\n"
                    "  blocker_summary: none\n"
                    "  required_human_inputs: []\n"
                    "  verification_status: passed\n"
                )
                return LaunchResult(command=spec.command, returncode=0, output=output, executor=spec.executor)

            with patch("phase_loop_runtime.runner.run_auth_preflight", return_value=AuthPreflightResult(ok=True, metadata={})), patch(
                "phase_loop_runtime.runner.launch_with_spec", side_effect=fake_launch
            ):
                snapshot, _results = run_loop(repo, roadmap, phase="RUNNER", executor="codex")

            self.assertIn(snapshot.phases["RUNNER"], {"complete", "awaiting_phase_closeout"})
            event = json.loads((repo / ".phase-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertIn("produced_gates_warning", event["metadata"]["child_automation"])

    def _native_fixture(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = make_repo(tmp_path)
        roadmap = repo / "specs" / "phase-plans-v1.md"
        write_phase_plan(
            repo,
            "RUNNER",
            roadmap,
            body=(
                "# RUNNER\n\n"
                "**Produces**: `IF-0-NATIVE-1`\n\n"
                "## Lanes\n\n"
                "### SL-0 - Contract\n"
                "- **Owned files**: `contract.py`\n"
                "- **Interfaces provided**: `IF-0-NATIVE-1`\n"
            ),
        )
        return repo, roadmap


if __name__ == "__main__":
    unittest.main()
