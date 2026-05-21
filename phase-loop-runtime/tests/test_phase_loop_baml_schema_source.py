import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BAML_SOURCE = ROOT / "vendor/phase-loop-runtime/baml_src/emit_phase_closeout.baml"


class PhaseLoopBamlSchemaSourceTest(unittest.TestCase):
    def test_emit_phase_closeout_contract_is_declared(self):
        text = BAML_SOURCE.read_text(encoding="utf-8")
        self.assertIn("function EmitPhaseCloseout(", text)
        for arg in ("phase_alias: string", "plan_produces: string[]", "plan_owned_files: string[]", "closeout_commit_sha: string?"):
            self.assertIn(arg, text)
        self.assertIn("-> PhaseLoopCloseoutV1", text)

    def test_closeout_fields_and_literals_are_present(self):
        text = BAML_SOURCE.read_text(encoding="utf-8")
        for field in (
            "terminal_status",
            "verification_status",
            "dirty_paths",
            "produced_if_gates",
            "next_action",
            "blocker_class",
            "blocker_summary",
            "human_required",
            "required_human_inputs",
        ):
            self.assertIn(field, text)
        for literal in ("complete", "blocked", "not_run", "passed", "contract_bug", "dirty_worktree_conflict"):
            self.assertIn(literal, text)
        self.assertIn("Completed closeouts must include every IF gate", text)
        self.assertIn("must not leave produced_if_gates empty", text)


if __name__ == "__main__":
    unittest.main()
