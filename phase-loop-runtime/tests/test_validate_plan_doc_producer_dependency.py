"""agent-harness#182 — validate_plan_doc.py (O) producer-dependency check == runtime.

The runtime lane IR (`phase_loop_runtime.plan_ir`) fails closed with
`missing_producer_dependency` at execute time when a lane consumes an interface provided
by another in-plan lane it does not depend on directly. The plan validator's `(O)` check
must enforce the SAME contract at plan time. To guarantee that — and to avoid re-creating
the very validator-vs-runtime divergence #182 is about — `(O)` DELEGATES to `plan_ir`.
These tests pin the behaviour AND the parity, including the exact-string interface
identity (so `IFoo` vs `IFoo (v2)` does NOT false-positive the way a normalized
reimplementation would).
"""
import importlib.util
import sys
import textwrap
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


def _load():
    spec = importlib.util.spec_from_file_location("validate_plan_doc_prod_dep_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


def _plan(consumed: str, sl2_depends: str) -> str:
    """A 3-lane plan: SL-0 provides `IFoo`; SL-2 consumes `consumed` and depends on
    `sl2_depends`. Empty interface lists are OMITTED (the runtime parses a literal
    `(none)` as an interface token). The runtime tolerates the ASCII hyphen in the
    SL heading."""
    return textwrap.dedent(
        f"""\
        ## Lane Index

        - SL-0 — Provider; Depends on: (none)
        - SL-1 — Middle; Depends on: SL-0
        - SL-2 — Consumer; Depends on: {sl2_depends}

        ## Lanes

        ### SL-0 - Provider

        - **Owned files**: `src/foo.py`
        - **Interfaces provided**: `IFoo`

        ### SL-1 - Middle

        - **Owned files**: `src/mid.py`

        ### SL-2 - Consumer

        - **Owned files**: `src/consumer.py`
        - **Interfaces consumed**: {consumed}
        """
    )


def _runtime_missing(path: Path):
    return [d for d in parse_phase_plan_ir(path).diagnostics if d.kind == "missing_producer_dependency"]


class ProducerDependencyParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def _write(self, tmp: Path, text: str) -> Path:
        p = tmp / "plan.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_flags_missing_direct_producer_edge_matching_runtime(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), _plan(consumed="`IFoo`", sl2_depends="SL-1"))
            runtime = _runtime_missing(path)
            self.assertTrue(runtime, "fixture must trigger the runtime diagnostic (self-check)")
            findings = self.mod._check_o_producer_dependency(path)
            self.assertEqual(len(findings), len(runtime), findings)
            self.assertTrue(any("SL-2" in f for f in findings), findings)
            self.assertTrue(all("WARN" not in f for f in findings))  # ERROR, not advice

    def test_clean_when_direct_edge_present_matching_runtime(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), _plan(consumed="`IFoo`", sl2_depends="SL-0"))
            self.assertEqual(_runtime_missing(path), [], "runtime should accept the direct edge")
            self.assertEqual(self.mod._check_o_producer_dependency(path), [])

    def test_annotated_interface_is_exact_string_not_normalized(self):
        # The CR's false-positive case: provide `IFoo`, consume `IFoo (v2)` with NO direct
        # edge. The runtime matches interfaces by EXACT string, so `IFoo` != `IFoo (v2)` →
        # no in-plan producer → runtime ACCEPTS. A normalized reimplementation would strip
        # `(v2)` and wrongly ERROR. (O) must match the runtime: no finding.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), _plan(consumed="`IFoo (v2)`", sl2_depends="SL-1"))
            self.assertEqual(_runtime_missing(path), [], "runtime treats IFoo and IFoo (v2) as distinct")
            self.assertEqual(
                self.mod._check_o_producer_dependency(path), [],
                "(O) must not false-positive on an annotated interface (exact-string identity)",
            )

    def test_skips_gracefully_when_plan_unparseable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), "not a plan\n")
            # No lanes → no producer edges → no (O) findings (A/B own the parse errors).
            self.assertEqual(self.mod._check_o_producer_dependency(path), [])


if __name__ == "__main__":
    unittest.main()
