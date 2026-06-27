"""rigor-v1 P2 — doc-delta closeout validator."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.closeout import build_phase_loop_closeout
from phase_loop_runtime.closeout_validators import clear_closeout_validators, register_closeout_validator
from phase_loop_runtime.doc_delta_validator import doc_delta_validator


def _closeout(plan, changed_paths, terminal_extra=None):
    terminal = {"terminal_status": "complete", "verification_status": "passed"}
    terminal.update(terminal_extra or {})
    return build_phase_loop_closeout(
        phase_alias="P2",
        plan_path=plan,
        terminal_summary=terminal,
        automation={"status": "complete", "verification_status": "passed", "human_required": False},
        changed_paths=changed_paths,
    )


class DocDeltaValidatorTest(unittest.TestCase):
    def setUp(self):
        clear_closeout_validators()
        register_closeout_validator(doc_delta_validator)
        self._td = tempfile.TemporaryDirectory()
        self.plan = Path(self._td.name) / "plan.md"
        self.plan.write_text("# plan\n", encoding="utf-8")
        self._review = os.environ.pop("PHASE_LOOP_REVIEW", None)

    def tearDown(self):
        clear_closeout_validators()
        if self._review is not None:
            os.environ["PHASE_LOOP_REVIEW"] = self._review
        self._td.cleanup()

    def test_non_public_change_no_finding(self):
        c = _closeout(self.plan, ["src/internal/helper.py"])
        self.assertEqual(c["terminal_status"], "complete")
        self.assertFalse(c["verification"]["results"])

    def test_public_change_without_decision_records_finding_but_warns(self):
        c = _closeout(self.plan, ["phase_loop_runtime/cli.py"])
        self.assertEqual(c["terminal_status"], "complete")  # warn default never blocks
        codes = [r.get("code") for r in c["verification"]["results"]]
        self.assertIn("doc_delta_undecided", codes)

    def test_public_change_with_recorded_decision_is_clean(self):
        c = _closeout(self.plan, ["README.md"], {"doc_delta_decision": "no_doc_delta"})
        self.assertEqual(c["terminal_status"], "complete")
        self.assertFalse(c["verification"]["results"])

    def test_public_change_blocks_in_block_mode(self):
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "block"}):
            c = _closeout(self.plan, ["phase_loop_runtime/cli.py"])
        self.assertEqual(c["terminal_status"], "blocked")
        self.assertEqual(c["blocker"]["blocker_class"], "review_gate_block")
        self.assertFalse(c["blocker"].get("human_required", True))

    def test_block_mode_with_decision_is_clean(self):
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "block"}):
            c = _closeout(self.plan, ["README.md"], {"doc_delta_decision": "docs_updated"})
        self.assertEqual(c["terminal_status"], "complete")


if __name__ == "__main__":
    unittest.main()
