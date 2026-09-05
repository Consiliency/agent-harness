"""rigor-v1 P1 — closeout validator-hook + severity model + schema seams.

Verifies the autonomy-first contract: validators default to `warn` (record +
continue), block only on opt-in, and never set `human_required`. Back-compat
(zero validators → unchanged) is covered by the existing closeout suites; here
we exercise the hook with registered validators.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.closeout import build_phase_loop_closeout
from phase_loop_runtime.closeout_validators import (
    ReviewFinding,
    clear_closeout_validators,
    register_closeout_validator,
    resolve_review_mode,
)
from phase_loop_runtime.models import (
    DEFINITION_OF_DONE_TERM,
    DOC_DELTA_DECISIONS,
    DocDeltaCloseout,
    VERIFICATION_EVIDENCE_OPT_OUT_REASONS,
    VERIFICATION_EVIDENCE_REQUIRED_DEFAULT,
    VisualEvidence,
    public_surface_touched,
    ui_change_detected,
)


def _passing_closeout(plan: Path, phase: str = "P1") -> dict:
    return build_phase_loop_closeout(
        phase_alias=phase,
        plan_path=plan,
        terminal_summary={"terminal_status": "complete", "verification_status": "passed"},
        automation={"status": "complete", "verification_status": "passed", "human_required": False},
    )


def _warn(ctx):
    return [ReviewFinding(code="demo_warn", reason="just noting", severity="warn")]


def _block(ctx):
    return [ReviewFinding(code="demo_block", reason="must fix", severity="block",
                          blocker_class="dirty_worktree_conflict")]


def _block_no_class(ctx):
    return [ReviewFinding(code="demo_block", reason="must fix", severity="block")]


def _boom(ctx):
    raise RuntimeError("a broken validator must never break closeout")


class CloseoutValidatorHookTest(unittest.TestCase):
    def setUp(self):
        clear_closeout_validators()
        self._td = tempfile.TemporaryDirectory()
        self.plan = Path(self._td.name) / "plan.md"
        self.plan.write_text("# plan\n", encoding="utf-8")
        # Default-warn unless a test overrides PHASE_LOOP_REVIEW.
        self._review = os.environ.pop("PHASE_LOOP_REVIEW", None)

    def tearDown(self):
        clear_closeout_validators()
        if self._review is not None:
            os.environ["PHASE_LOOP_REVIEW"] = self._review
        self._td.cleanup()

    def test_empty_registry_is_noop_complete(self):
        self.assertEqual(_passing_closeout(self.plan)["terminal_status"], "complete")

    def test_warn_finding_records_but_does_not_block(self):
        register_closeout_validator(_warn)
        c = _passing_closeout(self.plan)
        self.assertEqual(c["terminal_status"], "complete")  # warn never blocks
        self.assertFalse(c["blocker"].get("human_required", False))
        codes = [r.get("code") for r in c["verification"]["results"]]
        self.assertIn("demo_warn", codes)  # recorded for audit

    def test_block_finding_does_not_block_in_default_warn(self):
        register_closeout_validator(_block)
        c = _passing_closeout(self.plan)  # default warn downgrades block→warn
        self.assertEqual(c["terminal_status"], "complete")

    def test_block_finding_blocks_in_block_mode(self):
        register_closeout_validator(_block)
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "block"}):
            c = _passing_closeout(self.plan)
        self.assertEqual(c["terminal_status"], "blocked")
        self.assertEqual(c["blocker"]["blocker_class"], "dirty_worktree_conflict")
        # verification_status must flip to blocked too (no passed-on-blocked record).
        self.assertEqual(c["verification"]["status"], "blocked")

    def test_off_mode_skips_validators(self):
        register_closeout_validator(_block)
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "off"}):
            self.assertEqual(_passing_closeout(self.plan)["terminal_status"], "complete")

    def test_blocking_validator_never_sets_human_required(self):
        register_closeout_validator(_block_no_class)
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "block"}):
            c = _passing_closeout(self.plan)
        self.assertEqual(c["terminal_status"], "blocked")
        self.assertFalse(c["blocker"].get("human_required", True))
        self.assertFalse(c["automation"].get("human_required", True))

    def test_raising_validator_does_not_break_closeout(self):
        """A raising validator must not break closeout -- and must not be SILENT.

        G-1 (2026-09-01 codebase review). This test previously asserted
        ``terminal_status == "complete"`` under ``PHASE_LOOP_REVIEW=block``, which
        pinned the fail-open: the crash was swallowed by a bare
        ``except Exception: continue`` with no log line and no finding, so a gate
        that never ran was indistinguishable from a gate that passed.

        The guarantee this test exists for is unchanged: the exception does not
        propagate, closeout runs to completion and produces a payload. What
        changes is the VERDICT under an explicitly requested blocking posture --
        a crashed gate's result is UNKNOWN, and unknown must not read as pass.
        Under the default ``warn`` posture the finding is rewritten to ``warn``
        and closeout still completes (asserted in the next test), so this is
        scoped to runs that opted in. Nothing in the fleet or CI sets
        ``PHASE_LOOP_REVIEW=block``.
        """
        register_closeout_validator(_boom)
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "block"}):
            closeout = _passing_closeout(self.plan)
        self.assertEqual(closeout["terminal_status"], "blocked")
        self.assertIn("gate_crashed", json.dumps(closeout))

    def test_raising_validator_only_warns_under_the_default_posture(self):
        """G-1: the default posture records the crash without blocking."""
        register_closeout_validator(_boom)
        with patch.dict(os.environ, {"PHASE_LOOP_REVIEW": "warn"}):
            closeout = _passing_closeout(self.plan)
        self.assertEqual(closeout["terminal_status"], "complete")
        self.assertIn("gate_crashed", json.dumps(closeout))

    def test_resolve_review_mode_defaults_to_warn(self):
        self.assertEqual(resolve_review_mode({}), "warn")
        self.assertEqual(resolve_review_mode({"PHASE_LOOP_REVIEW": "off"}), "off")
        self.assertEqual(resolve_review_mode({"PHASE_LOOP_REVIEW": "block"}), "block")
        self.assertEqual(resolve_review_mode({"PHASE_LOOP_REVIEW": "nonsense"}), "warn")


class SchemaSeamTest(unittest.TestCase):
    def test_canonical_definition_of_done_term(self):
        self.assertEqual(DEFINITION_OF_DONE_TERM, "acceptance_criteria")

    def test_verification_evidence_default_is_off(self):
        self.assertFalse(VERIFICATION_EVIDENCE_REQUIRED_DEFAULT)
        self.assertIn("no_executable_verification", VERIFICATION_EVIDENCE_OPT_OUT_REASONS)

    def test_doc_delta_closeout_schema(self):
        d = DocDeltaCloseout(decision="docs_updated", target_surfaces=("README.md",))
        self.assertEqual(d.to_json()["schema"], "doc_delta_closeout.v1")
        self.assertIn("no_doc_delta", DOC_DELTA_DECISIONS)
        with self.assertRaises(ValueError):
            DocDeltaCloseout(decision="not_a_real_decision")

    def test_ui_change_detected_heuristic(self):
        self.assertTrue(ui_change_detected(["src/components/Button.tsx"]))
        self.assertTrue(ui_change_detected(["app/page.jsx", "x.py"]))
        self.assertTrue(ui_change_detected(["styles.css"]))
        self.assertFalse(ui_change_detected(["runner.py", "README.md"]))
        self.assertFalse(ui_change_detected([]))

    def test_public_surface_touched_heuristic(self):
        self.assertTrue(public_surface_touched(["phase_loop_runtime/cli.py"]))
        self.assertTrue(public_surface_touched(["README.md"]))
        self.assertTrue(public_surface_touched(["pkg/_contract_docs/protocol.md"]))
        self.assertFalse(public_surface_touched(["src/internal/helper.py"]))

    def test_visual_evidence_field(self):
        v = VisualEvidence(artifact_paths=("shot.png",), observed="button renders blue")
        self.assertEqual(v.to_json()["artifact_paths"], ["shot.png"])


if __name__ == "__main__":
    unittest.main()
