"""Retractable teeth -- posture resolution (floors, clamps, caps, retraction visibility)."""
from __future__ import annotations

import unittest

from phase_loop_runtime import gate_posture as gp


class GatePostureResolveTest(unittest.TestCase):
    def test_registry_available_on_0_6_2(self):
        self.assertTrue(gp.available())

    def test_invariant_default_is_its_floor_and_cannot_be_retracted(self):
        # never_delete_human_refs: default enforce, floor enforce -> non-retractable.
        base = gp.resolve_posture("never_delete_human_refs")
        self.assertEqual(base["posture"], "enforce")
        self.assertEqual(base["floor"], "enforce")
        # a repo tries to silence it -> denied, clamped back to the floor
        m = {gp.MANIFEST_OVERRIDE_KEY: {"never_delete_human_refs": "observe"}}
        r = gp.resolve_posture("never_delete_human_refs", manifest=m)
        self.assertEqual(r["posture"], "enforce")
        self.assertTrue(r["clamped_to_floor"])

    def test_write_footprint_floored_at_warn(self):
        m = {gp.MANIFEST_OVERRIDE_KEY: {"write_footprint_violation": "observe"}}
        r = gp.resolve_posture("write_footprint_violation", manifest=m)
        self.assertEqual(r["posture"], "warn")  # cannot drop below the warn floor
        self.assertTrue(r["clamped_to_floor"])

    def test_advisory_retracts_freely_and_is_flagged_retracted(self):
        # spec_nonconforming: advisory, default warn, floor observe.
        m = {gp.MANIFEST_OVERRIDE_KEY: {"spec_nonconforming": "observe"}}
        r = gp.resolve_posture("spec_nonconforming", manifest=m)
        self.assertEqual(r["posture"], "observe")   # retract honored
        self.assertTrue(r["retracted"])             # ...but recorded as a downward move
        self.assertFalse(r["clamped_to_floor"])

    def test_repo_may_raise_freely(self):
        m = {gp.MANIFEST_OVERRIDE_KEY: {"pipeline_branch_naming_drift": "enforce"}}
        r = gp.resolve_posture("pipeline_branch_naming_drift", manifest=m)
        self.assertEqual(r["posture"], "enforce")
        self.assertFalse(r["retracted"])

    def test_version_skew_capped_at_warn(self):
        # even an explicit raise to enforce is capped by max_posture.
        m = {gp.MANIFEST_OVERRIDE_KEY: {"version_skew": "enforce"}}
        r = gp.resolve_posture("version_skew", manifest=m)
        self.assertEqual(r["posture"], "warn")
        self.assertEqual(r["cap"], "warn")

    def test_unlisted_code_uses_advisory_default(self):
        r = gp.resolve_posture("some_brand_new_finding")
        self.assertEqual(r["posture"], "warn")
        self.assertEqual(r["category"], "advisory")

    def test_clamped_invariant_is_not_flagged_retracted(self):
        # CR fix: a floor-clamped attempt (effective unchanged) is clamped_to_floor, NOT retracted.
        m = {gp.MANIFEST_OVERRIDE_KEY: {"never_delete_human_refs": "observe"}}
        r = gp.resolve_posture("never_delete_human_refs", manifest=m)
        self.assertEqual(r["posture"], "enforce")
        self.assertFalse(r["retracted"])
        self.assertTrue(r["clamped_to_floor"])

    def test_retracting_overrides_lists_only_real_downward_moves(self):
        # CR fix: de-fanging visible on clean scans -- retracting_overrides scans the manifest,
        # counting only overrides that ACTUALLY lower a class (clamped invariants excluded).
        m = {gp.MANIFEST_OVERRIDE_KEY: {
            "spec_nonconforming": "observe",          # real down-move (advisory)
            "never_delete_human_refs": "observe",     # clamped -> not counted
            "pipeline_branch_naming_drift": "enforce"}}  # a raise -> not counted
        self.assertEqual(gp.retracting_overrides(m), ["spec_nonconforming"])

    def test_max_posture_never_undercuts_the_floor(self):
        # CR fix: floor wins even over a (hypothetical) mis-set max<min; version_skew has
        # floor observe + cap warn, so a raise-to-enforce lands at the warn cap, not below.
        m = {gp.MANIFEST_OVERRIDE_KEY: {"version_skew": "enforce"}}
        self.assertEqual(gp.resolve_posture("version_skew", manifest=m)["posture"], "warn")

    def test_posture_status_mapping(self):
        self.assertEqual(gp.posture_status("observe", mode="warn"), "note")
        self.assertEqual(gp.posture_status("observe", mode="hard"), "note")
        self.assertEqual(gp.posture_status("warn", mode="warn"), "warn")
        self.assertEqual(gp.posture_status("warn", mode="hard"), "warn")
        self.assertEqual(gp.posture_status("enforce", mode="warn"), "warn")   # master switch not thrown
        self.assertEqual(gp.posture_status("enforce", mode="hard"), "blocked")  # opted into hard


class ApplyPostureFallbackTest(unittest.TestCase):
    """CR regression guard: on a contract < 0.6.2 (registry absent) the fallback must
    preserve each gate's PRIOR severity, not uniformly block under hard."""

    def _apply(self, findings, *, mode, **kw):
        from unittest import mock
        from phase_loop_runtime import consiliency_gates as cg
        with mock.patch.object(gp, "available", return_value=False):
            return cg._apply_posture(findings, manifest=None, mode=mode, **kw)

    def test_version_skew_fallback_stays_warn_under_hard(self):
        r = self._apply([{"code": "version_skew"}], mode="hard", legacy_capped_all=True)
        self.assertEqual(r["status"], "warn")  # NOT blocked -- normative phase0 const

    def test_spec_info_fallback_stays_warn_under_hard(self):
        r = self._apply([{"code": "spec_below_conformance_bar"}], mode="hard",
                        legacy_capped_codes=frozenset({"spec_below_conformance_bar"}))
        self.assertEqual(r["status"], "warn")  # info tier never blocks, even in fallback

    def test_uncapped_finding_still_blocks_under_hard_in_fallback(self):
        r = self._apply([{"code": "some_finding"}], mode="hard")
        self.assertEqual(r["status"], "blocked")  # legacy uniform behavior preserved


if __name__ == "__main__":
    unittest.main()
