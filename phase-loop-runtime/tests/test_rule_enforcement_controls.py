"""Negative controls for the enforced rows of the rule→enforcer registry (agent-harness#1321).

Each control drives every enforcer its row names: the runtime lane IR through
``parse_phase_plan_ir`` and the plan validator through its ``main()``, so a check that
is unwired from the validator turns the control red too.
"""
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

from _dotfiles_tree import skills_bundle_present
from phase_loop_runtime.plan_ir import parse_phase_plan_ir

if not skills_bundle_present():
    pytest.skip(
        "requires the sibling phase-loop-skills bundle (absent in the standalone-from-wheel clean-room)",
        allow_module_level=True,
    )

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "phase-loop-skills" / "plan-phase" / "scripts" / "validate_plan_doc.py"

CLOSEOUT = """
## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `{decision}`
- target surfaces: none
- evidence paths: none
- redaction posture: `metadata_only`
"""


def _load():
    spec = importlib.util.spec_from_file_location("validate_plan_doc_rule_controls", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _plan(sl0_depends="(none)", sl1_depends="SL-0", sl1_owned="`src/b.py`", sl1_consumed="", decision="no_spec_delta"):
    consumed = f"- **Interfaces consumed**: {sl1_consumed}\n" if sl1_consumed else ""
    lanes = (
        "# DEMO\n\n## Lane Index & Dependencies\n\n"
        f"SL-0 — Provider\n  Depends on: {sl0_depends}\n  Parallel-safe: yes\n\n"
        f"SL-1 — Consumer\n  Depends on: {sl1_depends}\n  Parallel-safe: yes\n\n"
        "## Lanes\n\n"
        "### SL-0 — Provider\n\n- **Owned files**: `src/a.py`\n- **Interfaces provided**: `IFoo`\n\n"
        f"### SL-1 — Consumer\n\n- **Owned files**: {sl1_owned}\n"
    )
    return lanes + consumed + CLOSEOUT.format(decision=decision)


class RuleEnforcementControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def _refusals(self, text):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plan.md"
            path.write_text(text, encoding="utf-8")
            kinds = {diagnostic.kind for diagnostic in parse_phase_plan_ir(path).diagnostics}
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                code = self.mod.main(["validate_plan_doc.py", str(path)])
        return kinds, code, stderr.getvalue()

    def test_overlapping_owned_files_are_refused(self):
        kinds, code, stderr = self._refusals(_plan(sl1_owned="`src/a.py`"))
        self.assertIn("overlapping_write_ownership", kinds)
        self.assertEqual(code, 1)
        self.assertIn("(D) duplicate owned glob `src/a.py`", stderr)

    def test_lane_cycle_is_refused(self):
        kinds, code, stderr = self._refusals(_plan(sl0_depends="SL-1"))
        self.assertIn("cycle", kinds)
        self.assertEqual(code, 1)
        self.assertIn("(C) lane DAG has a cycle", stderr)

    def test_missing_producer_edge_is_refused(self):
        kinds, code, stderr = self._refusals(_plan(sl1_depends="(none)", sl1_consumed="`IFoo`"))
        self.assertIn("missing_producer_dependency", kinds)
        self.assertEqual(code, 1)
        self.assertIn("(O)", stderr)

    def test_out_of_vocabulary_closeout_decision_is_refused(self):
        _, code, stderr = self._refusals(_plan(decision="ship_it"))
        self.assertEqual(code, 1)
        self.assertIn("invalid Spec Closeout Plan decision `ship_it`", stderr)

    def test_clean_plan_has_none_of_these_refusals(self):
        kinds, _, stderr = self._refusals(_plan())
        self.assertNotIn("(B)", stderr)  # both lanes parsed, so the absences below mean something
        self.assertFalse(kinds & {"overlapping_write_ownership", "cycle", "missing_producer_dependency"}, kinds)
        for marker in ("(C) lane DAG has a cycle", "(D) duplicate owned glob", "(O)", "invalid Spec Closeout"):
            self.assertNotIn(marker, stderr)


if __name__ == "__main__":
    unittest.main()
