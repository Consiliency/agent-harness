"""SL-3: the mechanical Gate-A clean-room independence proof (IF-0-DECOUPLE-1).

Drives ``scripts/gate_a_cleanroom.sh``: build a wheel, install it into an isolated
venv with no dotfiles reachable + user-site disabled, and assert (via the in-venv
probe) that no resolved BAML / skill-root / manifest / import / CLI path points
under the dotfiles checkout, while ``version`` / ``status`` / ``dry-run`` /
``execute --bundle`` + the gp bridge smoke all run against that exact wheel.

The DECOUPLE phase PASSES iff this test passes.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import unittest
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = PKG_ROOT / "scripts" / "gate_a_cleanroom.sh"

import pytest

# TESTDECOUPLE SL-1 (overlay-dependent): builds a skill/adoption bundle or runs the
# runtime execute path, which resolves the dotfiles skill-source / profile overlay
# (claude-config/*, codex-config/* …) absent standalone. Run-time integration: the
# conftest hook skips it when no dotfiles tree is reachable.
def _have(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


@pytest.mark.dotfiles_integration
class GateAWheelIsolationTest(unittest.TestCase):
    def test_gate_a_cleanroom_passes(self):
        # Gate A is the IF-0-DECOUPLE-1 success gate. A SKIP would be a silent
        # no-op that lets a regression through, so missing build tooling FAILS by
        # default. CI that genuinely cannot build wheels must opt out LOUDLY via
        # PHASE_LOOP_SKIP_GATE_A=1 (recorded, not silent).
        if os.environ.get("PHASE_LOOP_SKIP_GATE_A") == "1":
            self.skipTest("PHASE_LOOP_SKIP_GATE_A=1 set; Gate A explicitly opted out")
        missing = [
            name
            for name, ok in (
                ("build", _have("build")),
                ("venv", _have("venv")),
                ("bash", shutil.which("bash") is not None),
            )
            if not ok
        ]
        self.assertEqual(
            missing,
            [],
            f"Gate A cannot run -- missing required tooling: {missing}. "
            "Install it, or set PHASE_LOOP_SKIP_GATE_A=1 to opt out loudly.",
        )
        self.assertTrue(GATE_SCRIPT.is_file(), f"missing Gate-A script: {GATE_SCRIPT}")

        result = subprocess.run(
            ["bash", str(GATE_SCRIPT)],
            text=True,
            capture_output=True,
            timeout=900,
        )
        if result.returncode != 0:
            self.fail(
                "Gate A clean-room failed (rc="
                f"{result.returncode}):\n--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}"
            )
        self.assertIn("Gate A PASSED", result.stdout)
        # both configs must have run: fleet-install (present) and the seam (absent)
        self.assertIn("GATE-A PROBE OK (present)", result.stdout)
        self.assertIn("GATE-A PROBE OK (absent)", result.stdout)
        # TESTDECOUPLE: the gate now runs the FULL standalone suite (not just the
        # import/execute/bridge smoke) against the installed wheel with no dotfiles
        # tree reachable. Assert it ran and was green, unless explicitly opted out.
        if os.environ.get("PHASE_LOOP_SKIP_GATE_A_SUITE") == "1":
            self.assertIn("full standalone suite: SKIPPED", result.stdout)
        else:
            self.assertIn("full standalone suite: GREEN", result.stdout)


@unittest.skipUnless(GATE_SCRIPT.is_file(), "source Gate A script unavailable")
class GateAConformEvidenceScopeTest(unittest.TestCase):
    def test_prebuilt_release_wheel_seam_preserves_artifact_identity(self):
        script = GATE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('if [ -n "${GATE_A_WHEEL:-}" ]', script)
        self.assertIn('GATE_A_WHEEL must be an absolute .whl path', script)
        self.assertIn('cp -- "$GATE_A_WHEEL" "$WHEEL"', script)
        self.assertIn('cmp -s "$GATE_A_WHEEL" "$WHEEL"', script)
        self.assertIn('wheel mode   : prebuilt release artifact', script)
        self.assertIn('( cd "$PKG_ROOT" && python3 -m build --wheel --outdir "$DIST" )', script)
        self.assertLess(
            script.index('if [ -n "${GATE_A_WHEEL:-}" ]'),
            script.index('( cd "$PKG_ROOT" && python3 -m build --wheel --outdir "$DIST" )'),
        )

    def test_conform_evidence_scope_is_minimal_and_excludes_final_nodes(self):
        script = GATE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("sparse-checkout init --no-cone", script)
        for required in (
            "/phase-loop-runtime/tests/",
            "/phase-loop-runtime/src/",
            "/phase-loop-runtime/protocol/",
            "/plans/phase-plan-v10-CONFORM.md",
            "/plans/phase-plan-v10-FABPUB.md",
            "/plans/phase-plan-v10-PROOFGATE.md",
            "/skills-src/codex/codex-execute-phase/",
            "/CHANGELOG.md",
        ):
            self.assertIn(required, script)
        self.assertIn('"$SOURCE_HEAD:plans/manifest.json"', script)
        self.assertIn("PHASE_LOOP_LEGIBLE_AUTHORITY_MANIFEST", script)
        self.assertNotIn("      /plans/manifest.json \\", script)
        self.assertLess(
            script.index("LEGIBLE_AUTHORITY_ENV=()"),
            script.index('if [ "$CONFORM_CAPABILITY_STATUS" -eq 0 ]'),
        )
        self.assertLess(
            script.index('if [ "$CONFORM_CAPABILITY_STATUS" -eq 0 ]'),
            script.index('"${LEGIBLE_AUTHORITY_ENV[@]}"'),
        )
        self.assertNotIn("sparse-checkout set \\\n      phase-loop-runtime/tests", script)
        self.assertNotIn("      .claude", script)
        self.assertIn('"--rootdir=$SUITE_TREE"', script)
        self.assertIn("os.chdir(suite.parent)", script)
        self.assertIn('PROOFGATE_358_COMMIT="0196f19c7e9fd90e9a707de076271057b521e1d1"', script)
        self.assertIn('git -C "$SOURCE_REPO" pack-objects --stdout', script)
        self.assertIn('git -C "$STANDALONE_ROOT" unpack-objects -q', script)

        for nodeid in (
            "test_outside_agent_contract_drift.py::test_documented_consumer_mirror_policy_allows_only_pinned_contract_bytes",
            "test_outside_agent_release_surface.py::test_v7_disposition_records_merged_contract_and_final_installed_behavior",
            "test_outside_agent_release_surface.py::test_release_handoff_records_metadata_only_package_contract_and_dispatch_boundary",
            "test_outside_agent_release_surface.py::test_public_docs_point_to_handoff_without_claiming_release_dispatch",
        ):
            self.assertIn(f"--deselect=tests/{nodeid}", script)
            self.assertNotIn(f"--deselect=$SUITE_TREE/tests/{nodeid}", script)


if __name__ == "__main__":
    unittest.main()
