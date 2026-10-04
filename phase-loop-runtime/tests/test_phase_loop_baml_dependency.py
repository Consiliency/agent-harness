import importlib.metadata
import json
import sys
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


class PhaseLoopBamlDependencyTest(unittest.TestCase):
    # TESTDECOUPLE: integration — reads vendor/phase-loop-runtime/pyproject.toml,
    # which is NEVER package-data (no repoint can make it standalone). This is the
    # source-tree PACKAGING contract; it legitimately runs only in-tree.
    @pytest.mark.dotfiles_integration
    def test_pyproject_declares_baml_runtime_and_packaged_source(self):
        # DECOUPLE SL-0: baml_src now ships as package-data inside the package
        # (resolved via importlib.resources), NOT via [tool.setuptools.data-files]
        # into share/. See test_pkg_layout_freeze.py for the full freeze contract.
        text = (ROOT / "vendor/phase-loop-runtime/pyproject.toml").read_text(encoding="utf-8")
        # agent-harness#1135: BAML v1 (D6 exact pin; D5 protobuf window).
        self.assertIn('"baml-bridge==0.20.1"', text)
        self.assertIn('"protobuf>=6.31.1,<8"', text)
        self.assertNotIn("baml-py", text)
        self.assertIn('"pydantic>=2,<3"', text)
        self.assertIn('"baml_src/*.baml"', text)
        self.assertNotIn('"share/phase-loop-runtime/baml_src"', text)
        pkg_dir = ROOT / "vendor/phase-loop-runtime/src/phase_loop_runtime"
        pkg_baml_dir = pkg_dir / "baml_src"
        for name in (
            "emit_phase_closeout",
            "dotfiles_adoption_manifest",
            "dotfiles_runtime_projection",
            "dotfiles_c4_document",
            "dotfiles_task_catalog",
            "verification_evidence",
            "phase_loop_bridge",
        ):
            self.assertTrue(
                (pkg_baml_dir / f"{name}.baml").is_file(),
                f"missing packaged baml source: {name}.baml",
            )
        self.assertTrue((pkg_dir / "_baml_worker.py").is_file())

    def test_baml_bridge_loads_after_install(self):
        # A real parse through the worker, not an import-only check (release
        # notes (f): the 0.20.0 fingerprint failure hit every Linux wheel).
        from phase_loop_runtime import baml_modular

        self.assertEqual(importlib.metadata.version("baml-bridge"), "0.20.1")
        parsed = baml_modular.parse_baml_response(
            "EmitPhaseCloseout",
            json.dumps(
                {
                    "terminal_status": "complete",
                    "verification_status": "passed",
                    "dirty_paths": [],
                    "produced_if_gates": ["G"],
                    "required_human_inputs": [],
                }
            ),
        )
        self.assertEqual(parsed.payload["terminal_status"], "complete")
        self.assertNotIn("baml_bridge", sys.modules)
        self.assertIsNone(__import__("importlib.util").util.find_spec("baml_py"))


if __name__ == "__main__":
    unittest.main()
