"""#12 CR #3 — drift guard for the generated `skills_bundle/` package-data.

Mirrors `test_phase_loop_runtime_package_data` for the other generated data: regenerate
the bundle from the canonical `phase-loop-skills/` source and assert the committed copy
is byte-identical, so an edit to the source without re-running `scripts/sync_skills_bundle.py`
cannot ship stale skills with green CI. Skipped standalone (no sibling source to compare).
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]  # phase-loop-runtime/
COMMITTED = PKG / "src" / "phase_loop_runtime" / "skills_bundle"
SRC_SKILLS = PKG.parent / "phase-loop-skills"
SYNC = PKG / "scripts" / "sync_skills_bundle.py"


def _load_sync():
    spec = importlib.util.spec_from_file_location("sync_skills_bundle_under_test", SYNC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SkillsBundleDriftTest(unittest.TestCase):
    def test_committed_bundle_is_byte_identical_to_regen(self):
        if not SRC_SKILLS.is_dir():
            self.skipTest("sibling phase-loop-skills/ source absent (from-wheel layout)")
        sync = _load_sync()

        def _bundle_files(root: Path) -> dict:
            # Exclude bytecode caches: importing a vendored bundle script (e.g. in another
            # test) writes __pycache__/*.pyc into the committed tree, which would falsely
            # read as drift. 0 .pyc are committed; they are never meaningful bundle content.
            return {
                p.relative_to(root): p
                for p in root.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
            }

        with tempfile.TemporaryDirectory() as td:
            regen = sync.assemble_bundle(SRC_SKILLS, Path(td) / "skills_bundle")
            committed = _bundle_files(COMMITTED)
            fresh = _bundle_files(regen)
            self.assertEqual(
                set(committed),
                set(fresh),
                "skills_bundle/ file set drifted from phase-loop-skills/; "
                "run scripts/sync_skills_bundle.py",
            )
            for rel, cpath in committed.items():
                with self.subTest(path=str(rel)):
                    self.assertEqual(
                        cpath.read_bytes(),
                        fresh[rel].read_bytes(),
                        f"skills_bundle/{rel} drifted; run scripts/sync_skills_bundle.py",
                    )

    def test_proofgate_validator_and_guidance_are_generated_without_drift(self):
        from .proofgate_tdd_guard import ProofgateMissingCapabilityError, guard_proofgate_nodeid, run_proofgate_contract
        nodeid = "phase-loop-runtime/tests/test_skills_bundle_drift.py::SkillsBundleDriftTest::test_proofgate_validator_and_guidance_are_generated_without_drift"
        if not guard_proofgate_nodeid(nodeid):
            return

        def _contract():
            sync = _load_sync()
            if not hasattr(sync, "verify_proofgate_validator_and_guidance_drift"):
                raise ProofgateMissingCapabilityError("sync_skills_bundle missing verify_proofgate_validator_and_guidance_drift capability")

            with tempfile.TemporaryDirectory() as td:
                self.assertTrue(SRC_SKILLS.is_dir(), "phase-loop-skills source directory missing")

                regen = sync.assemble_bundle(SRC_SKILLS, Path(td) / "skills_bundle")
                for gen_file in regen.rglob("*"):
                    if gen_file.is_file() and "__pycache__" not in gen_file.parts and not gen_file.name.endswith(".pyc"):
                        rel = gen_file.relative_to(regen)
                        com_file = COMMITTED / rel
                        self.assertTrue(com_file.is_file(), f"Committed file missing for regenerated {rel}")
                        self.assertEqual(
                            gen_file.read_bytes(),
                            com_file.read_bytes(),
                            f"Regenerated and committed {rel} must have byte parity",
                        )

                # Check literals on committed bundle files
                committed_val_file = COMMITTED / "claude-plan-phase" / "scripts" / "validate_plan_doc.py"
                self.assertTrue(committed_val_file.is_file(), "validate_plan_doc.py missing in committed skills_bundle")
                val_txt = committed_val_file.read_text(encoding="utf-8")
                self.assertTrue(
                    "missing_falsifier" in val_txt and "vacuous_falsifier" in val_txt and "missing_path_entered_control" in val_txt,
                    "validate_plan_doc.py missing proofgate reason code literals",
                )

                committed_guidance_file = COMMITTED / "claude-plan-phase" / "SKILL.md"
                self.assertTrue(committed_guidance_file.is_file(), "plan-phase SKILL.md missing in committed skills_bundle")
                guidance_txt = committed_guidance_file.read_text(encoding="utf-8")
                self.assertTrue(
                    "Falsifier:" in guidance_txt or "falsified by" in guidance_txt or "path-entered control" in guidance_txt,
                    "plan-phase SKILL.md missing proofgate grammar literals",
                )

        run_proofgate_contract(nodeid, _contract)



if __name__ == "__main__":
    unittest.main()
