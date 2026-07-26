"""Model-tier taxonomy (design-model-tier-taxonomy.md) — resolve() matrix lock.

Pins `resolve(role, vendor)` across every tier × vendor: the four Claude tier
ids, the non-claude ultra→heavy@max fallback, the per-tier ADVISORY efforts, the
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
        self.assertEqual(tier_for_role("roadmap"), "heavy")
        self.assertEqual(tier_for_role("plan"), "heavy")
        self.assertEqual(tier_for_role("review"), "ultra")
        self.assertEqual(tier_for_role("advise"), "ultra")
        self.assertEqual(tier_for_role("security"), "ultra")
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

    def test_authoring_and_review_resolve_separately_on_claude(self):
        for role in ("roadmap", "plan"):
            self.assertEqual(resolve(role, "claude").model_id, "claude-opus-5")
        for role in ("review", "advise", "security"):
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

    def test_claude_lite_uses_dated_snapshot_not_bare_alias(self):
        # CR nit E: Haiku uses the alias→dated form, so the matrix must pin the DATED
        # snapshot, never the bare undated `claude-haiku-4-5` (the floating-alias shape
        # blocker C reintroduced in skill prose). Reject the bare id in every claude cell.
        import re

        lite = resolve("lite", "claude").model_id
        self.assertNotEqual(lite, "claude-haiku-4-5")
        self.assertRegex(lite, r"^claude-haiku-4-5-\d{8}$")
        for tier in MODEL_TIERS:
            self.assertNotEqual(resolve(tier, "claude").model_id, "claude-haiku-4-5", tier)

    def test_advisor_registry_registers_dated_lite_not_bare_alias(self):
        # CR item H: the advisor-board CompatibilityMatrix only accepts REGISTERED ids,
        # so the lite tier's DATED pin must be registerable there, and the bare undated
        # alias must NOT be the registered form (else the lite tier's own id is rejected
        # by the board while the floating alias is accepted). Scan the registry surface,
        # not just TIER_MODELS.
        from phase_loop_runtime.advisor_board.registries import DEFAULT_MODEL_REGISTRY

        ids = {m.model for m in DEFAULT_MODEL_REGISTRY.list_models()}
        self.assertNotIn("claude-haiku-4-5", ids)  # bare undated alias not registered
        self.assertIn(resolve("lite", "claude").model_id, ids)  # dated lite pin IS registered


class TierLiveWiringTest(unittest.TestCase):
    """Blocker 1g: the LIVE class path must equal the tier path — no divergence."""

    def test_class_path_is_matrix_sourced_for_claude_and_codex(self):
        from phase_loop_runtime.profiles import resolve_model_class

        bridge = {
            "planner": "heavy",
            "reviewer": "ultra",
            "implementer": "regular",
            "worker": "lite",
        }
        for vendor in ("claude", "codex"):
            for model_class, tier in bridge.items():
                self.assertEqual(
                    resolve_model_class(vendor, model_class),
                    resolve(tier, vendor).model_id,
                    (vendor, model_class),
                )

    def test_executor_default_agrees_with_tier_path_for_converged_vendors(self):
        # The executor-default path (resolve_profile_for_executor) and the tier path
        # must not disagree on the CONVERGED vendors (claude + codex) for ANY action.
        # This is the invariant the bridge comment claims — enforced, not just prose.
        # (Regression guard for CR round 3: codex execute/repair previously fell
        # through to DEFAULT_PROFILES=heavy while resolve() said regular.)
        from phase_loop_runtime.profiles import resolve_profile_for_executor

        for vendor in ("claude", "codex"):
            for action in ("execute", "repair", "roadmap", "plan", "review"):
                self.assertEqual(
                    resolve_profile_for_executor(action=action, executor=vendor).model,
                    resolve(action, vendor).model_id,
                    (vendor, action),
                )

    def test_opencode_executor_path_agrees_with_class_path(self):
        # opencode is launch-live but NOT a tier vendor (provider-qualified ids), so its
        # executor path must agree with its CLASS map instead of resolve() (CR round-4
        # regression guard: opencode execute/repair previously launched on heavy sol
        # while the class path resolved terra).
        from phase_loop_runtime.profiles import (
            CLASS_MODEL_OVERRIDES,
            resolve_profile_for_executor,
        )

        bridge = {
            "execute": "implementer",
            "repair": "implementer",
            "roadmap": "planner",
            "plan": "planner",
            "review": "reviewer",
        }
        for action, model_class in bridge.items():
            self.assertEqual(
                resolve_profile_for_executor(action=action, executor="opencode").model,
                CLASS_MODEL_OVERRIDES["opencode"][model_class],
                action,
            )

    def test_gemini_executor_path_agrees_with_class_path(self):
        # gemini IS a tier vendor (in TIER_VENDORS) but its LIVE routing is not matrix-
        # DERIVED (agy aliases / canonical agy ids, mapped by _gemini_cli_model), so
        # compare its executor path to its CLASS map (CR round-4 regression guard: gemini
        # execute/repair previously used the `auto` alias, which _gemini_cli_model
        # COLLAPSES to the Pro/heavy argv, while the class path resolved Flash).
        from phase_loop_runtime.profiles import (
            CLASS_MODEL_OVERRIDES,
            resolve_profile_for_executor,
        )
        from phase_loop_runtime.launcher import _gemini_cli_model

        bridge = {
            "execute": "implementer",
            "repair": "implementer",
            "roadmap": "planner",
            "plan": "planner",
            "review": "reviewer",
        }
        for action, model_class in bridge.items():
            self.assertEqual(
                resolve_profile_for_executor(action=action, executor="gemini").model,
                CLASS_MODEL_OVERRIDES["gemini"][model_class],
                action,
            )
        # Anti-collapse guard (the sneaky adapter defect): implementation's argv must NOT
        # resolve to the Pro/heavy agy model.
        for action in ("execute", "repair"):
            selection = resolve_profile_for_executor(action=action, executor="gemini")
            argv = _gemini_cli_model(selection.model, selection.effort)
            self.assertNotEqual(argv, "Gemini 3.1 Pro (High)", action)

    def test_gemini_adapter_maps_tier_ids_without_collapsing_flash_to_pro(self):
        # The gemini CLI adapter must map each tier id to the RIGHT agy model — heavy
        # → Pro, but regular/lite must NOT silently collapse to Pro (the CR bug).
        from phase_loop_runtime.launcher import _gemini_cli_model

        self.assertEqual(_gemini_cli_model(resolve("heavy", "gemini").model_id), "Gemini 3.1 Pro (High)")
        regular = _gemini_cli_model(resolve("regular", "gemini").model_id, "medium")
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
        for model_class in ("planner", "reviewer", "implementer", "worker"):
            self.assertEqual(resolve_model_class("grok", model_class), GROK_DEFAULT_MODEL)


class SupervisorProvenanceTest(unittest.TestCase):
    def test_supervise_selection_resolves_heavy(self):
        from phase_loop_runtime.profiles import supervise_selection

        sel = supervise_selection("claude")
        self.assertEqual(sel.tier, "heavy")
        self.assertEqual(sel.model_id, "claude-opus-5")
        # Non-claude supervise = that vendor's heavy model.
        self.assertEqual(supervise_selection("codex").model_id, "gpt-5.6-sol")

    def test_coordinator_review_bundle_records_supervise_provenance(self):
        # ADVISORY PROVENANCE (not a launch binding): the train coordinator's authored
        # review artifact records the supervise tier. This checks the recorded text
        # only — no launch request consumes it (the coordinator is the ambient session).
        from phase_loop_runtime.train_runner import _build_train_review_bundle
        from phase_loop_runtime.train_roadmap import TrainRoadmap

        roadmap = TrainRoadmap(title="t", nodes=(), edges=())
        bundle = _build_train_review_bundle(roadmap, {}, [])
        self.assertIn("Coordinator supervise tier", bundle)
        self.assertIn("claude-opus-5", bundle)


class ChannelRouteModelBindingTest(unittest.TestCase):
    """CR round-5 finding 3(d): exercise the PRODUCTION-DEFAULT claude CHANNEL route (not
    print — the suite conftest pins print, which is exactly why this defect hid). The
    channel `send` binds no --model; assert that and the session_model_unbound provenance."""

    def test_channel_route_execute_binds_no_model_and_stamps_unbound(self):
        import os
        from phase_loop_runtime.launcher import (
            build_launch_spec,
            _CHANNEL_SESSION_MODEL_UNBOUND_WARNING,
        )
        from _launchspec_golden_cases import _base_request, _pinned_claude_eligibility

        env = {
            "PHASE_LOOP_CLAUDE_ROUTE": "channel",
            "PHASE_LOOP_CLAUDE_CHANNEL_SESSION_ID": "regression-session-id",
        }
        saved = {k: os.environ.get(k) for k in env}
        try:
            for k, v in env.items():
                os.environ[k] = v
            spec = build_launch_spec(
                _base_request(
                    "claude",
                    claude_execution_mode="solo",
                    phase_team_eligibility=_pinned_claude_eligibility(),
                )
            )
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        # Production-default channel route resolved for an execute action.
        self.assertEqual(spec.claude_route, "claude_channel")
        # The `send` transport binds NO --model (print/agent_view routes DO).
        self.assertNotIn("--model", spec.command)
        # Provenance: selected_model is the INTENDED tier model, explicitly stamped unbound.
        self.assertEqual(spec.selected_model, "claude-sonnet-5")
        self.assertIn(_CHANNEL_SESSION_MODEL_UNBOUND_WARNING, spec.claude_route_warnings)

        # CR round-6 blocker C: the stamp must reach the DURABLE record (LaunchResult
        # .event_metadata — the EVENT layer), not only the spec. Route through the PRODUCTION
        # spec→result copy (_result_with_spec, launcher.py) rather than hand-threading the
        # field, so this bites if that threading is deleted (CR round-7 de-tautologization).
        # RESIDUE (named): this calls _result_with_spec directly, so deleting the CALL SITE in
        # _launch_claude_channel would not be caught here; the persisted-artifact test below (via
        # run_artifacts) exercises a separate production path.
        from phase_loop_runtime.launcher import LaunchResult, _result_with_spec

        base = LaunchResult(command=spec.command, returncode=0, executor="claude", claude_route_result={})
        result = _result_with_spec(base, spec)
        md = result.event_metadata()
        self.assertEqual(md.get("selected_model"), "claude-sonnet-5")
        self.assertIn(_CHANNEL_SESSION_MODEL_UNBOUND_WARNING, md.get("claude_route_warnings", []))

    def test_channel_run_persisted_launch_json_carries_the_stamp(self):
        # CR round-8: launch.json is the DURABLE artifact an auditor reads. It records
        # selected_model — so it must ALSO carry claude_route + the session_model_unbound
        # warning, or it misreads a channel run as sonnet-bound. Inspect the PERSISTED file
        # written by run_artifacts (the production launch.json writer), not just event_metadata.
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from phase_loop_runtime import observability
        from phase_loop_runtime.launcher import build_launch_spec, _CHANNEL_SESSION_MODEL_UNBOUND_WARNING
        from phase_loop_runtime.observability import run_artifacts
        from _launchspec_golden_cases import _base_request, _pinned_claude_eligibility

        env = {
            "PHASE_LOOP_CLAUDE_ROUTE": "channel",
            "PHASE_LOOP_CLAUDE_CHANNEL_SESSION_ID": "artifact-session-id",
        }
        saved = {k: os.environ.get(k) for k in env}
        try:
            for k, v in env.items():
                os.environ[k] = v
            spec = build_launch_spec(
                _base_request("claude", claude_execution_mode="solo", phase_team_eligibility=_pinned_claude_eligibility())
            )
            with tempfile.TemporaryDirectory() as td:
                # Stub the dotfiles-dependent skill-bundle materialization (orthogonal to the
                # launch.json ROUTE fields under test); run_artifacts still writes the real
                # launch.json metadata dict.
                with mock.patch.object(observability, "_materialize_launch_bundle", return_value=None), \
                        mock.patch.object(observability, "_materialize_task_ledger", return_value=None):
                    artifacts = run_artifacts(Path(td), "PHASE", "execute", 0, spec)
                launch_json = json.loads(Path(artifacts["metadata"]).read_text(encoding="utf-8"))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        # The persisted artifact records selected_model AND the route + unbound caveat.
        self.assertEqual(launch_json.get("selected_model"), "claude-sonnet-5")
        self.assertEqual(launch_json.get("claude_route"), "claude_channel")
        self.assertIn(_CHANNEL_SESSION_MODEL_UNBOUND_WARNING, launch_json.get("claude_route_warnings", []))


if __name__ == "__main__":
    unittest.main()
