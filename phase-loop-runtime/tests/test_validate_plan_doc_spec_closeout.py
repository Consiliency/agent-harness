"""validate_plan_doc.py check (I): the Spec Closeout Plan section is refused when malformed.

This is the runnable negative control for registry row
``plan-phase.spec-closeout-plan-valid`` (agent-harness#1321). The older
contract test that covered it skips everywhere outside the dotfiles tree.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

import pytest

from _dotfiles_tree import skills_bundle_present

if not skills_bundle_present():
    pytest.skip(
        "requires the sibling phase-loop-skills bundle (absent in the standalone-from-wheel clean-room)",
        allow_module_level=True,
    )

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "phase-loop-skills" / "plan-phase" / "scripts" / "validate_plan_doc.py"

VALID = """## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: none
- evidence paths: none
- redaction posture: `metadata_only`

## Execution Notes
"""


def _load():
    spec = importlib.util.spec_from_file_location("validate_plan_doc_spec_closeout", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class SpecCloseoutCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def test_accepts_valid_section(self):
        self.assertEqual(self.mod._check_i_spec_closeout_plan(VALID), [])

    def test_refuses_missing_section(self):
        findings = self.mod._check_i_spec_closeout_plan("## Execution Notes\n")
        self.assertEqual(findings, ["(I) missing required `## Spec Closeout Plan` section"])

    def test_refuses_out_of_vocabulary_decision(self):
        src = VALID.replace("`no_spec_delta`", "`ship_it`")
        findings = self.mod._check_i_spec_closeout_plan(src)
        self.assertTrue(any("invalid Spec Closeout Plan decision `ship_it`" in f for f in findings), findings)

    def test_refuses_non_metadata_only_redaction(self):
        src = VALID.replace("`metadata_only`", "`full`")
        findings = self.mod._check_i_spec_closeout_plan(src)
        self.assertIn("(I) Spec Closeout Plan missing `metadata_only`", findings)
