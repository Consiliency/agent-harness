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
            # grok: no dated snapshot published → every cell volatile (blocker 2).
            ("ultra", "grok"): ("grok-4.5", "max", True),
            ("heavy", "grok"): ("grok-4.5", "xhigh", True),
            ("regular", "grok"): ("grok-4.3", "medium", True),
            ("lite", "grok"): ("grok-build-0.1", "low", True),
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
        # claude + codex publish immutable ids → never volatile. (grok is volatile
        # across all cells, asserted separately in PinOnlyInvariantTest.)
        for vendor in ("claude", "codex"):
            for tier in MODEL_TIERS:
                self.assertFalse(resolve(tier, vendor).volatile, (tier, vendor))


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
    def test_pinned_vendors_have_no_floating_alias_shapes(self):
        # claude + codex are pinned: reject the `-latest` alias shape AND the bare
        # OpenAI floating alias `gpt-5.6` (with no -sol/-terra/-luna suffix).
        for vendor in ("claude", "codex"):
            for tier, cell in TIER_MODELS[vendor].items():
                mid = cell.model_id
                self.assertNotIn("latest", mid, (vendor, tier))
                self.assertNotEqual(mid, "gpt-5.6", (vendor, tier))  # the OpenAI floating alias
                if mid.startswith("gpt-5.6"):
                    self.assertRegex(mid, r"^gpt-5\.6-(sol|terra|luna)$", (vendor, tier))
                self.assertTrue(mid.strip(), (vendor, tier))
                self.assertFalse(cell.volatile, (vendor, tier))

    def test_known_floating_shapes_are_marked_volatile(self):
        # A vendor id with no immutable dated snapshot MUST be volatile-marked, so a
        # governed run can see it floats. gemini heavy (preview) + all grok cells.
        self.assertTrue(resolve("heavy", "gemini").volatile)
        for tier in MODEL_TIERS:
            self.assertTrue(resolve(tier, "grok").volatile, tier)


class TierLiveWiringTest(unittest.TestCase):
    """Blocker 1g: the LIVE class path must equal the tier path — no divergence."""

    def test_class_path_is_matrix_sourced_for_claude_and_codex(self):
        from phase_loop_runtime.profiles import resolve_model_class

        bridge = {"planner": "ultra", "implementer": "regular", "worker": "lite"}
        for vendor in ("claude", "codex"):
            for model_class, tier in bridge.items():
                self.assertEqual(
                    resolve_model_class(vendor, model_class),
                    resolve(tier, vendor).model_id,
                    (vendor, model_class),
                )

    def test_claude_executor_default_agrees_with_tier_path(self):
        # The executor-default path (resolve_profile_for_executor) and the tier path
        # must not disagree on claude: plan→fable (ultra), execute→sonnet (regular).
        from phase_loop_runtime.profiles import resolve_profile_for_executor

        self.assertEqual(
            resolve_profile_for_executor(action="plan", executor="claude").model,
            resolve("plan", "claude").model_id,
        )
        self.assertEqual(
            resolve_profile_for_executor(action="execute", executor="claude").model,
            resolve("execute", "claude").model_id,
        )

    def test_gemini_adapter_maps_tier_ids_without_collapsing_flash_to_pro(self):
        # The gemini CLI adapter must map each tier id to the RIGHT agy model — heavy
        # → Pro, but regular/lite must NOT silently collapse to Pro (the CR bug).
        from phase_loop_runtime.launcher import _gemini_cli_model

        self.assertEqual(_gemini_cli_model(resolve("heavy", "gemini").model_id), "Gemini 3.1 Pro (High)")
        regular = _gemini_cli_model(resolve("regular", "gemini").model_id)
        lite = _gemini_cli_model(resolve("lite", "gemini").model_id)
        self.assertNotEqual(regular, "Gemini 3.1 Pro (High)")
        self.assertNotEqual(lite, "Gemini 3.1 Pro (High)")
        self.assertNotEqual(regular, lite)

    def test_gemini_adapter_fails_loud_on_unmapped_gemini_id(self):
        from phase_loop_runtime.launcher import _gemini_cli_model

        with self.assertRaises(ValueError):
            _gemini_cli_model("gemini-9.9-imaginary")

    def test_grok_tier_ids_are_cli_passthrough_safe(self):
        # grok passes -m verbatim; the tier ids must be plain -m-safe tokens. grok's
        # LIVE class routing stays single-model (documented single-model design), so
        # assert that explicitly rather than claiming the matrix ids are live yet.
        from phase_loop_runtime.profiles import resolve_model_class, GROK_DEFAULT_MODEL

        for tier in MODEL_TIERS:
            mid = resolve(tier, "grok").model_id
            self.assertNotIn(" ", mid, tier)
            self.assertTrue(mid.startswith("grok-"), tier)
        for model_class in ("planner", "implementer", "worker"):
            self.assertEqual(resolve_model_class("grok", model_class), GROK_DEFAULT_MODEL)


class SupervisorConsumerTest(unittest.TestCase):
    def test_supervise_selection_binds_heavy(self):
        from phase_loop_runtime.profiles import supervise_selection

        sel = supervise_selection("claude")
        self.assertEqual(sel.tier, "heavy")
        self.assertEqual(sel.model_id, "claude-opus-5")
        # Non-claude supervise = that vendor's heavy model.
        self.assertEqual(supervise_selection("codex").model_id, "gpt-5.6-sol")

    def test_coordinator_review_bundle_records_supervise_binding(self):
        # The train coordinator's authored review artifact is the production consumer.
        from phase_loop_runtime.train_runner import _build_train_review_bundle
        from phase_loop_runtime.train_roadmap import TrainRoadmap

        roadmap = TrainRoadmap(title="t", nodes=(), edges=())
        bundle = _build_train_review_bundle(roadmap, {}, [])
        self.assertIn("Coordinator supervise tier", bundle)
        self.assertIn("claude-opus-5", bundle)


if __name__ == "__main__":
    unittest.main()
