import unittest
from pathlib import Path

from phase_loop_runtime.injection import build_lane_prompt_bundle, build_prompt_bundle
from phase_loop_runtime.models import HarnessLaneAssignment


ROOT = Path(__file__).resolve().parents[3]


class PhaseLoopBamlInjectionTest(unittest.TestCase):
    def test_prompt_bundles_include_baml_closeout_prompt_and_adapter_constraints(self):
        for action in ("plan", "execute", "repair", "review"):
            with self.subTest(action=action):
                bundle = build_prompt_bundle(
                    repo=ROOT,
                    harness_target="claude",
                    action=action,
                    roadmap=ROOT / "specs/phase-plans-v20.md",
                    phase="BAMLBASE",
                    plan=ROOT / "plans/phase-plan-v20-BAMLBASE.md",
                    body="phase-loop launch body",
                )
                context = bundle.render_context()
                self.assertIn("EmitPhaseCloseout", context)
                self.assertIn("vendor/phase-loop-runtime/baml_src/emit_phase_closeout.baml", context)
                self.assertIn("IF-0-BAMLBASE-1", context)
                self.assertIn("Phase-loop adapter constraints", context)

    def test_lane_prompt_uses_baml_reference_instead_of_field_list_source_of_truth(self):
        assignment = HarnessLaneAssignment(
            phase="BAMLBASE",
            lane_id="SL-3",
            work_unit_kind="lane_execute",
            prompt_kind="implementation",
            owned_files=("vendor/phase-loop-runtime/src/phase_loop_runtime/injection.py",),
            consumed_interfaces=("IF-0-BAMLBASE-3",),
        )
        context = build_lane_prompt_bundle(
            repo=ROOT,
            harness_target="codex",
            action="execute",
            roadmap=ROOT / "specs/phase-plans-v20.md",
            plan=ROOT / "plans/phase-plan-v20-BAMLBASE.md",
            assignment=assignment,
        ).render_context()
        self.assertIn("BAML closeout schema instruction:", context)
        self.assertIn("EmitPhaseCloseout", context)
        self.assertIn("Do not spawn peer harnesses directly.", context)
        self.assertNotIn("Required shared automation closeout fields:", context)


if __name__ == "__main__":
    unittest.main()
