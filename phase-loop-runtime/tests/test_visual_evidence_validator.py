"""rigor-v1 P6 — visual-evidence closeout validator."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.closeout import build_phase_loop_closeout
from phase_loop_runtime.closeout_validators import clear_closeout_validators, register_closeout_validator
from phase_loop_runtime.visual_evidence_validator import visual_evidence_validator


def _closeout(plan, changed_paths, terminal_extra=None):
    terminal = {"terminal_status": "complete", "verification_status": "passed"}
    terminal.update(terminal_extra or {})
    return build_phase_loop_closeout(
        phase_alias="P6", plan_path=plan, terminal_summary=terminal,
        automation={"status": "complete", "verification_status": "passed", "human_required": False},
        changed_paths=changed_paths,
    )


class VisualEvidenceValidatorTest(unittest.TestCase):
    def setUp(self):
        clear_closeout_validators()
        register_closeout_validator(visual_evidence_validator)
        self._td = tempfile.TemporaryDirectory()
        self.plan = Path(self._td.name) / "plan.md"
        self.plan.write_text("# plan\n", encoding="utf-8")
        self._review = os.environ.pop("PHASE_LOOP_REVIEW", None)

    def tearDown(self):
        clear_closeout_validators()
        if self._review is not None:
            os.environ["PHASE_LOOP_REVIEW"] = self._review
        self._td.cleanup()

    def test_non_ui_change_no_finding(self):
        c = _closeout(self.plan, ["src/runner.py"])
        self.assertFalse(c["verification"]["results"])

    def test_ui_change_without_evidence_warns(self):
        c = _closeout(self.plan, ["src/components/Button.tsx"])
        self.assertEqual(c["terminal_status"], "complete")  # warn never blocks
        codes = [r.get("code") for r in c["verification"]["results"]]
        self.assertIn("visual_evidence_missing", codes)

    def test_ui_change_with_evidence_is_clean(self):
        c = _closeout(self.plan, ["app/page.tsx"], {"visual_evidence_path": "shots/page.png"})
        self.assertFalse(c["verification"]["results"])

    def test_ui_change_blocks_on_opt_in(self):
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "block"}):
            c = _closeout(self.plan, ["styles/app.css"])
        self.assertEqual(c["terminal_status"], "blocked")
        self.assertEqual(c["blocker"]["blocker_class"], "review_gate_block")
        self.assertFalse(c["blocker"].get("human_required", True))


if __name__ == "__main__":
    unittest.main()
