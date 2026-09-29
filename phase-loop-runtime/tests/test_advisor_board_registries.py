"""ABDFREEZE — registry interfaces + matrix API are importable stubs
(IF-0-ABDFREEZE-2).

INTERFACES ONLY: the return types + method surface are frozen; the six-harness
data is ABDREG. A phase that leans on real data before ABDREG must fail loudly,
so the stubs raise ``NotImplementedError``.
"""
from __future__ import annotations

import unittest

from phase_loop_runtime.advisor_board import (
    AuthAvailability,
    CompatibilityMatrix,
    HarnessRegistry,
    HarnessSpec,
    ModelRegistry,
    ModelSpec,
    StubCompatibilityMatrix,
    StubHarnessRegistry,
    StubModelRegistry,
)


class ReturnTypeTests(unittest.TestCase):
    def test_auth_availability_is_concrete_and_defaults_fail_closed(self) -> None:
        aa = AuthAvailability()
        self.assertFalse(aa.subscription)
        self.assertFalse(aa.api_key)
        self.assertFalse(aa.any_available)
        self.assertTrue(AuthAvailability(subscription=True).any_available)

    def test_specs_are_frozen_records(self) -> None:
        hs = HarnessSpec(name="codex", cli="codex")
        ms = ModelSpec(model="gpt-5.6-sol", vendor_family="codex", default_lane="codex")
        with self.assertRaises(Exception):
            hs.name = "x"  # frozen
        with self.assertRaises(Exception):
            ms.model = "y"  # frozen
        self.assertEqual(hs.auth_lanes, ("subscription",))
        self.assertEqual(hs.backing, "homebrew")
        self.assertIsNone(hs.available)  # probe result, not frozen data


class StubTests(unittest.TestCase):
    def test_stubs_structurally_satisfy_protocols(self) -> None:
        self.assertIsInstance(StubHarnessRegistry(), HarnessRegistry)
        self.assertIsInstance(StubModelRegistry(), ModelRegistry)
        self.assertIsInstance(StubCompatibilityMatrix(), CompatibilityMatrix)

    def test_stub_accessors_raise_until_abdreg(self) -> None:
        with self.assertRaises(NotImplementedError):
            StubHarnessRegistry().list_harnesses()
        with self.assertRaises(NotImplementedError):
            StubModelRegistry().default_lane("gpt-5.6-sol")
        with self.assertRaises(NotImplementedError):
            StubCompatibilityMatrix().is_valid("gpt-5.6-sol", "codex")

    def test_matrix_is_valid_return_shape(self) -> None:
        # Freeze the tuple[bool, AuthAvailability] shape via a hand-built verdict —
        # this is what ABDREG's matrix must return and ABDRESOLVE's validation reads.
        verdict: tuple[bool, AuthAvailability] = (True, AuthAvailability(subscription=True))
        ok, avail = verdict
        self.assertTrue(ok)
        self.assertTrue(avail.subscription)


class PopulatedRegistryTests(unittest.TestCase):
    """ABDREG: the populated six-harness / model registries (the frozen stubs
    above still raise — that contract is unchanged)."""

    def test_registered_harnesses_with_cli_and_backing(self) -> None:
        from phase_loop_runtime.advisor_board import DefaultHarnessRegistry

        reg = DefaultHarnessRegistry()
        names = tuple(h.name for h in reg.list_harnesses())
        self.assertEqual(names, ("claude", "codex", "gemini", "grok", "opencode", "pi", "cursor"))
        # built-4 are homebrew; breadth (opencode/pi/cursor) default to omnigent.
        by = {h.name: h for h in reg.list_harnesses()}
        for built in ("claude", "codex", "gemini", "grok"):
            self.assertEqual(by[built].backing, "homebrew")
        for breadth in ("opencode", "pi", "cursor"):
            self.assertEqual(by[breadth].backing, "omnigent")
        # probe binaries reflect reality: gemini -> agy, grok -> grok, cursor -> cursor-agent.
        self.assertEqual(by["gemini"].cli, "agy")
        self.assertEqual(by["grok"].cli, "grok")
        self.assertEqual(by["cursor"].cli, "cursor-agent")
        # grok is registered SUBSCRIPTION-ONLY (no vendor api-key var wired for it),
        # while the other homebrew lanes support both credential lanes.
        self.assertEqual(by["grok"].auth_lanes, ("subscription",))
        self.assertEqual(by["codex"].auth_lanes, ("subscription", "api_key"))

    def test_cursor_availability_is_gated_on_cursor_agent_binary(self) -> None:
        from phase_loop_runtime.advisor_board import DefaultHarnessRegistry

        present = DefaultHarnessRegistry(probe=lambda cli: cli == "cursor-agent")
        self.assertTrue(present.is_available("cursor"))
        absent = DefaultHarnessRegistry(probe=lambda cli: False)
        self.assertFalse(absent.is_available("cursor"))

    def test_unknown_harness_raises_with_known_list(self) -> None:
        from phase_loop_runtime.advisor_board import DefaultHarnessRegistry, UnknownHarnessError

        with self.assertRaises(UnknownHarnessError):
            DefaultHarnessRegistry().get("amp")

    def test_model_default_lane_pins_gpt55_to_codex_not_opencode(self) -> None:
        # gpt-5.6-sol is runnable_by both codex and opencode, but a bare seat MUST
        # resolve onto the built-3 codex leg (default-board back-compat).
        from phase_loop_runtime.advisor_board import DEFAULT_MODEL_REGISTRY

        spec = DEFAULT_MODEL_REGISTRY.get("gpt-5.6-sol")
        self.assertEqual(spec.default_lane, "codex")
        self.assertEqual(spec.runnable_by, ("codex", "opencode"))
        self.assertEqual(spec.vendor_family, "codex")  # derived from schema.vendor_family

    def test_grok_model_resolves_to_the_grok_lane(self) -> None:
        # grok-4.6 is a RETAINED legacy xAI-family model: the 4-vendor code-review
        # board moved to grok-4.7 (ah#971), but 4.6 stays registered as an explicit
        # seat, so it must still resolve to the grok lane.
        from phase_loop_runtime.advisor_board import DEFAULT_MODEL_REGISTRY

        spec = DEFAULT_MODEL_REGISTRY.get("grok-4.6")
        self.assertEqual(spec.default_lane, "grok")
        self.assertEqual(spec.vendor_family, "grok")
        self.assertEqual(spec.runnable_by, ("grok",))  # grok-family runs only on the grok lane

    def test_current_default_board_models_resolve_to_their_lanes(self) -> None:
        # The fleet defaults: claude-opus-5-5 (claude lane; claude-fable-5-1 is the
        # retained explicit option) and gemini-3.8-flash (gemini lane) alongside
        # gpt-5.6-sol above. grok's default is grok-4.7
        # (ah#971); grok-4.6 above is the retained legacy seat, not a default.
        from phase_loop_runtime.advisor_board import DEFAULT_MODEL_REGISTRY

        opus = DEFAULT_MODEL_REGISTRY.get("claude-opus-5-5")
        self.assertEqual(opus.default_lane, "claude")
        self.assertEqual(opus.vendor_family, "claude")
        fable = DEFAULT_MODEL_REGISTRY.get("claude-fable-5-1")
        self.assertEqual(fable.default_lane, "claude")
        self.assertEqual(fable.vendor_family, "claude")
        flash = DEFAULT_MODEL_REGISTRY.get("gemini-3.8-flash")
        self.assertEqual(flash.default_lane, "gemini")
        self.assertEqual(flash.effort_ceiling, "high")

    def test_previous_board_models_remain_registered_for_explicit_configs(self) -> None:
        from phase_loop_runtime.advisor_board import DEFAULT_MODEL_REGISTRY

        self.assertEqual(DEFAULT_MODEL_REGISTRY.get("gemini-3.6-flash").default_lane, "gemini")
        self.assertEqual(DEFAULT_MODEL_REGISTRY.get("gemini-3.7-flash").default_lane, "gemini")
        self.assertEqual(DEFAULT_MODEL_REGISTRY.get("grok-4.5").default_lane, "grok")
        self.assertEqual(DEFAULT_MODEL_REGISTRY.get("claude-fable-5").default_lane, "claude")

    def test_gpt_6_sol_is_an_explicit_codex_seat_not_a_default(self) -> None:
        from phase_loop_runtime.advisor_board import DEFAULT_MODEL_REGISTRY
        from phase_loop_runtime.advisor_board.harness_mapping import render_seat_invocation
        from phase_loop_runtime.panel_invoker import DEFAULT_LEG_MODELS, DEFAULT_REVIEW_SEAT_ALIASES

        spec = DEFAULT_MODEL_REGISTRY.get("gpt-6-sol")
        self.assertEqual(spec.default_lane, "codex")
        self.assertEqual(spec.effort_ceiling, "max")
        self.assertEqual(DEFAULT_REVIEW_SEAT_ALIASES["gpt-6-sol"], "sol")
        inv = render_seat_invocation("codex", "gpt-6-sol", "max")
        self.assertEqual((inv.model, inv.effort_args), ("gpt-6-sol", ("-c", "model_reasoning_effort=xhigh")))
        # registration only: gpt-6-sol is not the codex seat default
        self.assertNotEqual(DEFAULT_LEG_MODELS["codex"], "gpt-6-sol")

    def test_gpt_6_1_sol_is_the_codex_review_seat_default(self) -> None:
        # Maintainer, 2026-09-29, "for now": the codex review seat moves to gpt-6.1-sol.
        # The planner/implementer model and the prior review default stay registered.
        from phase_loop_runtime import profiles
        from phase_loop_runtime.advisor_board import DEFAULT_MODEL_REGISTRY
        from phase_loop_runtime.advisor_board.backing import HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES
        from phase_loop_runtime.advisor_board.harness_mapping import render_seat_invocation
        from phase_loop_runtime.advisor_board.presets import CODE_REVIEW_BOARD
        from phase_loop_runtime.panel_invoker import DEFAULT_LEG_MODELS, DEFAULT_REVIEW_SEAT_ALIASES

        spec = DEFAULT_MODEL_REGISTRY.get("gpt-6.1-sol")
        self.assertEqual((spec.default_lane, spec.effort_ceiling), ("codex", "max"))
        self.assertEqual(spec.runnable_by, ("codex", "opencode"))
        self.assertEqual(DEFAULT_REVIEW_SEAT_ALIASES["gpt-6.1-sol"], "sol")
        inv = render_seat_invocation("codex", "gpt-6.1-sol", "max")
        self.assertEqual((inv.model, inv.effort_args), ("gpt-6.1-sol", ("-c", "model_reasoning_effort=xhigh")))
        self.assertEqual(DEFAULT_LEG_MODELS["codex"], "gpt-6.1-sol")
        self.assertEqual(HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["codex"], "gpt-6.1-sol")
        self.assertEqual([s.model for s in CODE_REVIEW_BOARD.seats if s.harness == "codex"], ["gpt-6.1-sol"])
        for kept in ("gpt-6-astra", "gpt-6-sol", "gpt-5.6-sol"):
            self.assertEqual(DEFAULT_REVIEW_SEAT_ALIASES[kept], "sol")
            self.assertEqual(DEFAULT_MODEL_REGISTRY.get(kept).default_lane, "codex")
        self.assertEqual(profiles.OPENAI_HEAVY_MODEL, "gpt-6-astra")

    def test_unknown_model_raises_with_known_list(self) -> None:
        from phase_loop_runtime.advisor_board import DEFAULT_MODEL_REGISTRY, UnknownModelError

        with self.assertRaises(UnknownModelError):
            DEFAULT_MODEL_REGISTRY.default_lane("gpt-9-imaginary")


if __name__ == "__main__":
    unittest.main()
