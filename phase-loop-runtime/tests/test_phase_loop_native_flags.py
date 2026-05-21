import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.launcher import (
    LaunchResult,
    build_claude_command,
    build_codex_command,
    build_launch_request,
    build_launch_spec,
    launch_with_spec,
)
from phase_loop_runtime.models import CLOSEOUT_SCHEMA
from phase_loop_runtime.profiles import resolve_profile, resolve_profile_for_executor
from phase_loop_runtime.prompts import build_prompt


JSON_CLOSEOUT_SCHEMA = json.loads(json.dumps(CLOSEOUT_SCHEMA))


class PhaseLoopNativeFlagsTest(unittest.TestCase):
    def test_codex_command_writes_output_schema_temp_file(self):
        selection = resolve_profile("execute")
        command = build_codex_command(Path("/repo"), selection, "prompt", closeout_schema=CLOSEOUT_SCHEMA)
        schema_path = Path(command[command.index("--output-schema") + 1])
        try:
            self.assertEqual(json.loads(schema_path.read_text(encoding="utf-8")), JSON_CLOSEOUT_SCHEMA)
        finally:
            schema_path.unlink(missing_ok=True)

    def test_claude_command_uses_compact_inline_json_schema(self):
        selection = resolve_profile_for_executor(action="execute", executor="claude")
        command = build_claude_command(
            Path("/repo"),
            selection,
            "prompt",
            permission_mode="bypassPermissions",
            closeout_schema=CLOSEOUT_SCHEMA,
        )
        schema_text = command[command.index("--json-schema") + 1]

        self.assertEqual(json.loads(schema_text), JSON_CLOSEOUT_SCHEMA)
        self.assertNotIn("\n", schema_text)

    def test_build_launch_spec_limits_native_flags_to_codex_and_claude(self):
        codex_request = build_launch_request(
            executor="codex",
            action="execute",
            repo=Path("/repo"),
            roadmap=Path("/repo/specs/phase-plans-v1.md"),
            phase="RUNNER",
            plan=Path("/repo/plans/phase-plan-v1-RUNNER.md"),
            model_selection=resolve_profile("execute"),
            prompt_bundle=build_prompt(
                "execute",
                Path("/repo/specs/phase-plans-v1.md"),
                phase="RUNNER",
                plan=Path("/repo/plans/phase-plan-v1-RUNNER.md"),
            ),
            json_output=True,
            bypass_approvals=False,
        )
        codex_spec = build_launch_spec(codex_request)
        self.assertIn("--output-schema", codex_spec.command)
        self.assertEqual(len(codex_spec.cleanup_paths), 1)
        Path(codex_spec.cleanup_paths[0]).unlink(missing_ok=True)

        gemini_request = build_launch_request(
            executor="gemini",
            action="execute",
            repo=Path("/repo"),
            roadmap=Path("/repo/specs/phase-plans-v1.md"),
            phase="RUNNER",
            plan=Path("/repo/plans/phase-plan-v1-RUNNER.md"),
            model_selection=resolve_profile_for_executor(action="execute", executor="gemini"),
            prompt_bundle=build_prompt(
                "execute",
                Path("/repo/specs/phase-plans-v1.md"),
                phase="RUNNER",
                plan=Path("/repo/plans/phase-plan-v1-RUNNER.md"),
                harness_target="gemini",
            ),
            json_output=True,
            bypass_approvals=False,
        )
        gemini_spec = build_launch_spec(gemini_request)
        self.assertNotIn("--output-schema", gemini_spec.command)
        self.assertEqual(gemini_spec.cleanup_paths, ())

    def test_launch_with_spec_removes_codex_schema_temp_file(self):
        request = build_launch_request(
            executor="codex",
            action="execute",
            repo=Path("/repo"),
            roadmap=Path("/repo/specs/phase-plans-v1.md"),
            phase="RUNNER",
            plan=Path("/repo/plans/phase-plan-v1-RUNNER.md"),
            model_selection=resolve_profile("execute"),
            prompt_bundle=build_prompt(
                "execute",
                Path("/repo/specs/phase-plans-v1.md"),
                phase="RUNNER",
                plan=Path("/repo/plans/phase-plan-v1-RUNNER.md"),
            ),
            json_output=True,
            bypass_approvals=False,
        )
        spec = build_launch_spec(request)
        schema_path = Path(spec.cleanup_paths[0])
        self.assertTrue(schema_path.exists())

        with tempfile.TemporaryDirectory() as td, patch(
            "phase_loop_runtime.launcher.launch",
            return_value=LaunchResult(command=spec.command, returncode=0, output="{}"),
        ):
            result = launch_with_spec(spec, log_path=Path(td) / "run.log")

        self.assertFalse(schema_path.exists())
        self.assertIn(str(schema_path), result.cleanup_evidence["schema_cleanup"]["removed"])


if __name__ == "__main__":
    unittest.main()
