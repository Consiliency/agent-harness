"""rigor-v1 P5 — verification-evidence validator (generic-phase hole)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.closeout import build_phase_loop_closeout
from phase_loop_runtime.closeout_validators import (
    CloseoutContext,
    clear_closeout_validators,
    register_closeout_validator,
)
from phase_loop_runtime.verification_evidence_validator import verification_evidence_validator


def _ctx(plan, phase="P5", terminal=None):
    return CloseoutContext(
        phase_alias=phase,
        plan_path=str(plan),
        terminal=terminal or {"verification_status": "passed"},
        automation={"verification_status": "passed"},
        changed_paths=(),
    )


class VerificationEvidenceValidatorTest(unittest.TestCase):
    def setUp(self):
        clear_closeout_validators()
        register_closeout_validator(verification_evidence_validator)
        self._td = tempfile.TemporaryDirectory()
        self.plan = Path(self._td.name) / "plan.md"
        self.plan.write_text("# plan\n", encoding="utf-8")
        self._review = os.environ.pop("PHASE_LOOP_REVIEW", None)

    def tearDown(self):
        clear_closeout_validators()
        if self._review is not None:
            os.environ["PHASE_LOOP_REVIEW"] = self._review
        self._td.cleanup()

    # --- unit: the validator function directly ---
    def test_generic_passed_without_artifact_finds(self):
        findings = verification_evidence_validator(_ctx(self.plan))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, "verification_evidence_missing_generic")

    def test_artifact_present_is_clean(self):
        ctx = _ctx(self.plan, terminal={"verification_status": "passed", "verification_artifact_path": "x.json"})
        self.assertEqual(verification_evidence_validator(ctx), [])

    def test_typed_opt_out_is_clean(self):
        ctx = _ctx(self.plan, terminal={"verification_status": "passed",
                                        "verification_evidence_opt_out": "no_executable_verification"})
        self.assertEqual(verification_evidence_validator(ctx), [])

    def test_not_passed_is_clean(self):
        self.assertEqual(verification_evidence_validator(_ctx(self.plan, terminal={"verification_status": "not_run"})), [])

    def test_rg_phase_owned_by_legacy_gate(self):
        self.assertEqual(verification_evidence_validator(_ctx(self.plan, phase="RG")), [])

    # --- end-to-end through closeout ---
    def test_generic_passed_warns_but_completes_by_default(self):
        c = build_phase_loop_closeout(
            phase_alias="P5", plan_path=self.plan,
            terminal_summary={"terminal_status": "complete", "verification_status": "passed"},
            automation={"status": "complete", "verification_status": "passed", "human_required": False},
        )
        self.assertEqual(c["terminal_status"], "complete")  # warn default never stalls
        codes = [r.get("code") for r in c["verification"]["results"]]
        self.assertIn("verification_evidence_missing_generic", codes)

    def test_generic_passed_blocks_on_opt_in(self):
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "block"}):
            c = build_phase_loop_closeout(
                phase_alias="P5", plan_path=self.plan,
                terminal_summary={"terminal_status": "complete", "verification_status": "passed"},
                automation={"status": "complete", "verification_status": "passed", "human_required": False},
            )
        self.assertEqual(c["terminal_status"], "blocked")
        self.assertFalse(c["blocker"].get("human_required", True))


if __name__ == "__main__":
    unittest.main()
