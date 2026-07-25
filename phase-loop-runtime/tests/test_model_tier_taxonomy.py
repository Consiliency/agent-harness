"""Model-tier taxonomy (design-model-tier-taxonomy.md) — resolve() matrix lock.

Pins `resolve(role, vendor)` across every tier × vendor: the four Claude tier
ids, the non-claude ultra→heavy@max fallback, the per-tier canonical efforts, the
gemini-heavy preview/volatile marker, and the role→tier + supervise bindings.
Also asserts the PIN-ONLY invariant (no floating aliases in the matrix).
"""
import unittest

from phase_loop_runtime.models import MODEL_TIERS
from phase_loop_runtime.profiles import (
    ROLE_TIERS,
    SUPERVISOR_TIER,
    TIER_MODELS,
    TIER_VENDORS,
    resolve,
    tier_for_role,
)


class TierMatrixTest(unittest.TestCase):
    def test_full_tier_by_vendor_matrix(self):
        # (tier, vendor) -> (model_id, effort, volatile). Non-claude ultra is the
        # heavy model @ max (no separate ultra catalog id for codex/gemini/grok).
        expected = {
            ("ultra", "claude"): ("claude-fable-5", "max", False),
            ("heavy", "claude"): ("claude-opus-5", "xhigh", False),
            ("regular", "claude"): ("claude-sonnet-5", "medium", False),
            ("lite", "claude"): ("claude-haiku-4-5-20251001", "low", False),
            ("ultra", "codex"): ("gpt-5.6-sol", "max", False),
            ("heavy", "codex"): ("gpt-5.6-sol", "xhigh", False),
            ("regular", "codex"): ("gpt-5.6-terra", "medium", False),
            ("lite", "codex"): ("gpt-5.6-luna", "low", False),
            ("ultra", "gemini"): ("gemini-3.1-pro-preview", "max", True),
            ("heavy", "gemini"): ("gemini-3.1-pro-preview", "xhigh", True),
            ("regular", "gemini"): ("gemini-3.6-flash", "medium", False),
            ("lite", "gemini"): ("gemini-3.5-flash-lite", "low", False),
            ("ultra", "grok"): ("grok-4.5", "max", False),
            ("heavy", "grok"): ("grok-4.5", "xhigh", False),
            ("regular", "grok"): ("grok-4.3", "medium", False),
            ("lite", "grok"): ("grok-build-0.1", "low", False),
        }
        # Covers all 4 tiers × 4 vendors.
        self.assertEqual(set(TIER_VENDORS), {"claude", "codex", "gemini", "grok"})
        self.assertEqual(len(expected), len(MODEL_TIERS) * len(TIER_VENDORS))
        for (tier, vendor), (model_id, effort, volatile) in expected.items():
            r = resolve(tier, vendor)
            self.assertEqual(r.tier, tier, (tier, vendor))
            self.assertEqual(r.model_id, model_id, (tier, vendor))
            self.assertEqual(r.effort, effort, (tier, vendor))
            self.assertEqual(r.volatile, volatile, (tier, vendor))

    def test_non_claude_ultra_is_heavy_at_max(self):
        for vendor in ("codex", "gemini", "grok"):
            self.assertNotIn("ultra", TIER_MODELS[vendor])
            ultra = resolve("ultra", vendor)
            heavy = resolve("heavy", vendor)
            self.assertEqual(ultra.model_id, heavy.model_id)
            self.assertEqual(ultra.effort, "max")

    def test_only_claude_has_a_distinct_ultra_model(self):
        self.assertIn("ultra", TIER_MODELS["claude"])
        self.assertNotEqual(
            resolve("ultra", "claude").model_id, resolve("heavy", "claude").model_id
        )

    def test_gemini_heavy_carries_preview_volatile_marker(self):
        self.assertTrue(resolve("heavy", "gemini").volatile)
        self.assertTrue(resolve("ultra", "gemini").volatile)
        # No other vendor's heavy tier is volatile.
        for vendor in ("claude", "codex", "grok"):
            self.assertFalse(resolve("heavy", vendor).volatile)


class RoleToTierTest(unittest.TestCase):
    def test_role_to_tier_bindings(self):
        self.assertEqual(tier_for_role("roadmap"), "ultra")
        self.assertEqual(tier_for_role("plan"), "ultra")
        self.assertEqual(tier_for_role("review"), "ultra")
        self.assertEqual(tier_for_role("execute"), "regular")
        self.assertEqual(tier_for_role("repair"), "regular")
        self.assertEqual(tier_for_role("worker"), "lite")

    def test_supervise_binds_to_heavy(self):
        self.assertEqual(SUPERVISOR_TIER, "heavy")
        self.assertEqual(tier_for_role("supervise"), "heavy")
        self.assertEqual(ROLE_TIERS["supervise"], "heavy")
        # supervise on claude → the heavy model (opus-5).
        self.assertEqual(resolve("supervise", "claude").model_id, "claude-opus-5")

    def test_bare_tier_name_passes_through_as_role(self):
        for tier in MODEL_TIERS:
            self.assertEqual(tier_for_role(tier), tier)

    def test_planning_resolves_to_fable_on_claude(self):
        # The headline behavior change: Claude planning/review → fable (ultra).
        for role in ("roadmap", "plan", "review"):
            self.assertEqual(resolve(role, "claude").model_id, "claude-fable-5")

    def test_execute_target_is_regular_sonnet_on_claude(self):
        # resolve() encodes the taxonomy target end-state for implementation.
        self.assertEqual(resolve("execute", "claude").model_id, "claude-sonnet-5")

    def test_unknown_role_and_vendor_raise(self):
        with self.assertRaises(ValueError):
            resolve("not_a_role", "claude")
        with self.assertRaises(ValueError):
            resolve("plan", "not_a_vendor")


class PinOnlyInvariantTest(unittest.TestCase):
    def test_no_floating_aliases_in_matrix(self):
        # Every matrix id is a pinned canonical literal — reject the known floating
        # alias shapes (`-latest`, and the bare `gpt-5.6`/`grok-4.5-latest` forms).
        for vendor, tiers in TIER_MODELS.items():
            for tier, cell in tiers.items():
                self.assertNotIn("-latest", cell.model_id, (vendor, tier))
                self.assertNotIn("latest", cell.model_id, (vendor, tier))
                self.assertTrue(cell.model_id.strip(), (vendor, tier))


if __name__ == "__main__":
    unittest.main()
