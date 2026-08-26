import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
from phase_loop_runtime.capability_registry import DEFAULT_EXECUTOR_POLICY
from phase_loop_runtime.launcher import (
    _adapter_effective_effort,
    _gemini_cli_model,
    build_codex_command,
    build_grok_command,
)
from phase_loop_runtime.models import ExecutionPolicyRule, ModelSelection
from phase_loop_runtime.profiles import _resolve_policy_model
from phase_loop_runtime.profiles import resolve_execution_policy, resolve_model_selection_from_policy, resolve_profile_for_executor


class PhaseLoopExecutionPolicyTest(unittest.TestCase):
    def test_adapter_effort_provenance_matches_emitted_argv(self):
        codex = ModelSelection(profile="plan", model="gpt-5.6-sol", effort="max")
        codex_command = build_codex_command(Path("/repo"), codex, "prompt")
        self.assertIn('model_reasoning_effort="xhigh"', codex_command)
        self.assertEqual(_adapter_effective_effort("codex", codex.model, codex.effort), "xhigh")

        grok = ModelSelection(profile="plan", model="grok-4.5", effort="max")
        grok_command = build_grok_command(
            Path("/repo"), grok, action="plan", context_file="context.md"
        )
        effort_index = grok_command.index("--reasoning-effort") + 1
        self.assertEqual(grok_command[effort_index], "high")
        self.assertEqual(_adapter_effective_effort("grok", grok.model, grok.effort), "high")

    def test_gemini_base_model_renders_effort_and_conflict_fails(self):
        self.assertEqual(
            _gemini_cli_model("gemini-3.6-flash", "medium"),
            "gemini-3.6-flash-medium",
        )
        with self.assertRaisesRegex(ValueError, "conflicts with requested effort"):
            _gemini_cli_model("gemini-3.6-flash-high", "medium")

    def test_dfparsoak_policy_precedence_keeps_execute_default_and_explicit_fallbacks(self):
        self.assertEqual(DEFAULT_EXECUTOR_POLICY["execute"], "codex")
        self.assertEqual(resolve_profile_for_executor(action="execute", executor="pi").model, "auto")
        self.assertEqual(resolve_profile_for_executor(action="execute", executor="claude").model, "claude-sonnet-5")
        # gemini execute uses the canonical agy 3.6 Flash id (CR round-5 finding B — newest
        # GA), NOT `auto` (which the adapter collapses to Pro/heavy).
        self.assertEqual(resolve_profile_for_executor(action="execute", executor="gemini").model, "gemini-3.6-flash")

        roadmap = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="pi",
            model="gpt-5.6-sol",
            effort="medium",
            work_unit_kind="lane_execute",
            source="roadmap:execute",
        )
        plan = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="codex",
            model="gpt-5.6-sol",
            effort="high",
            work_unit_kind="lane_execute",
            unsupported_policy_behavior="inherit_default",
            inherit_default=True,
            source="plan:execute",
        )

        resolved = resolve_execution_policy(
            action="execute",
            executor=DEFAULT_EXECUTOR_POLICY["execute"],
            model_selection=ModelSelection(profile="execute", model="gpt-5.6-sol", effort="medium"),
            plan_policy=plan,
            roadmap_policy=roadmap,
        )

        self.assertEqual(resolved.executor, "codex")
        self.assertEqual(resolved.executor_source, "phase-plan policy")
        self.assertEqual(resolved.execution_policy_source, "phase-plan policy")
        self.assertFalse(resolved.fallback_applied)

    def test_phase_plan_policy_overrides_roadmap_policy(self):
        roadmap = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="claude",
            model="claude-opus-4-8",
            effort="high",
            work_unit_kind="lane_execute",
            source="roadmap:execute",
        )
        plan = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="codex",
            model="gpt-5.6-sol",
            effort="xhigh",
            work_unit_kind="lane_execute",
            source="plan:execute",
        )

        resolved = resolve_execution_policy(
            action="execute",
            executor="claude",
            model_selection=ModelSelection(profile="execute", model="claude-opus-4-8", effort="high"),
            plan_policy=plan,
            roadmap_policy=roadmap,
        )

        self.assertEqual(resolved.executor, "codex")
        self.assertEqual(resolved.model, "gpt-5.6-sol")
        self.assertEqual(resolved.effort, "xhigh")
        self.assertEqual(resolved.execution_policy_source, "phase-plan policy")

    def test_operator_model_and_effort_override_policy(self):
        plan = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="codex",
            model="gpt-5.6-sol",
            effort="medium",
            work_unit_kind="lane_execute",
            source="plan:execute",
        )

        resolved = resolve_execution_policy(
            action="execute",
            executor="codex",
            model_selection=ModelSelection(profile="execute", model="gpt-5.6-sol", effort="medium"),
            operator_model="gpt-5.6-terra",
            operator_effort="high",
            plan_policy=plan,
        )
        selection = resolve_model_selection_from_policy(profile="execute", resolved_policy=resolved)

        self.assertEqual(selection.model, "gpt-5.6-terra")
        self.assertEqual(selection.effort, "high")
        self.assertEqual(resolved.model_source, "CLI/operator override")
        self.assertEqual(resolved.effort_source, "CLI/operator override")

    def test_operator_gemini_model_survives_inherit_default_end_to_end(self):
        """agent-harness#671, the reported RESIDUAL launch, end to end.

        The precedence test above is codex-only, and codex has NO model_aliases,
        so it never reaches the substitution branch. Gemini does: `allowed` is
        the set of INTERNAL alias values, a canonical id is absent from it, and
        `inherit_default` replaced the operator's explicit `--model` with
        `phase-loop-execute-medium` -- which agy rejects before session creation.

        Asserts the whole chain the operator experiences: resolution keeps the
        pin, the source records the override, and the emitted argv carries the
        canonical id with NO internal token anywhere in it.

        Mutation that must kill this: drop `operator_pinned` from
        `_resolve_policy_model`, or stop threading it at the call site.
        """
        plan = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="gemini",
            model="gemini-3.6-flash",
            effort="medium",
            work_unit_kind="lane_execute",
            source="plan:execute",
            unsupported_policy_behavior="inherit_default",
            inherit_default=True,
        )

        resolved = resolve_execution_policy(
            action="execute",
            executor="gemini",
            model_selection=ModelSelection(
                profile="execute", model="gemini-3.6-flash", effort="medium",
            ),
            operator_model="gemini-3.6-flash",
            operator_effort="high",
            plan_policy=plan,
        )
        selection = resolve_model_selection_from_policy(
            profile="execute", resolved_policy=resolved,
        )

        self.assertEqual(selection.model, "gemini-3.6-flash")
        self.assertEqual(resolved.model_source, "CLI/operator override")
        self.assertNotIn("phase-loop-", resolved.model)

        argv_model = _gemini_cli_model(selection.model, selection.effort)
        self.assertEqual(argv_model, "gemini-3.6-flash-high")
        self.assertNotIn("phase-loop-", argv_model)

    def test_a_blank_operator_model_fails_loudly_instead_of_launching_HEAVY(self):
        """agent-harness#671 round 2 (codex seat), reproduced before fixing.

        A blank or whitespace-only pin passes every `is not None` check, and the
        renderer strips it and falls through to the provider's HEAVY default --
        so `--model "$UNSET_VAR"` silently launched `Gemini 3.1 Pro (High)`
        instead of failing. Verified byte-identical on clean origin/main, so this
        is PRE-EXISTING rather than a regression; it is fixed here because this
        function now promises an operator pin is never substituted, and that
        promise has to cover the blank case.

        Mutation that must kill this: drop the `.strip()` emptiness check.
        """
        for pin in ("", "   ", "\t"):
            with self.assertRaises(ValueError) as caught:
                resolve_execution_policy(
                    action="execute",
                    executor="gemini",
                    model_selection=ModelSelection(
                        profile="execute", model="gemini-3.6-flash", effort="medium",
                    ),
                    operator_model=pin,
                    operator_effort="high",
                )
            self.assertIn("empty --model", str(caught.exception))

    def test_an_internal_alias_typed_as_an_operator_pin_is_REJECTED(self):
        """Rejecting is not substituting (fable seat).

        The operator-pin guard returns before the `phase-loop-` fail-closed
        raise, so a MISSPELLED internal token reached agy verbatim and failed
        there with a vaguer message. The repo knows these names are its own
        vocabulary, so it can refuse precisely — without violating the
        never-substitute invariant, since nothing is swapped in.

        A RECOGNISED alias is deliberately still allowed through: the codex seat
        noted an operator may define these locally as `modelConfigs.customAliases`,
        so refusing them would break a legitimate workflow. Only an
        unrecognised `phase-loop-*` token — a typo by construction — is refused.

        Mutation that must kill this: drop the prefix check inside the
        operator-pin branch.
        """
        with self.assertRaises(ValueError) as caught:
            _resolve_policy_model(
                "gemini", "lane_execute", "phase-loop-execute-mediumX", None,
                "inherit_default", operator_pinned=True,
            )
        self.assertIn("internal phase-loop alias", str(caught.exception))

        # A recognised alias still passes: operators may define it locally.
        self.assertEqual(
            _resolve_policy_model(
                "gemini", "lane_execute", "phase-loop-execute-medium", None,
                "inherit_default", operator_pinned=True,
            ),
            "phase-loop-execute-medium",
        )

    def test_omitting_the_operator_model_is_still_fine(self):
        """The guard must reject BLANK, not absent. `None` means "no override"
        and must keep working, or the fix breaks every non-override launch.

        Mutation that must kill this: reject `operator_model is None` too.
        """
        resolved = resolve_execution_policy(
            action="execute",
            executor="gemini",
            model_selection=ModelSelection(
                profile="execute", model="gemini-3.6-flash", effort="medium",
            ),
            operator_model=None,
            operator_effort=None,
        )
        self.assertNotEqual(resolved.model_source, "CLI/operator override")

    def test_policy_derived_gemini_model_still_inherits_the_default(self):
        """The fix must NOT disable inheritance generally -- only stop it
        outranking an operator pin. Without an operator model the policy path is
        unchanged.

        Mutation that must kill this: make `_resolve_policy_model` return the
        model unconditionally, which would "fix" ah#671 by deleting the feature.
        """
        self.assertEqual(
            _resolve_policy_model(
                "gemini", "lane_execute", "gemini-3.6-flash", None,
                "inherit_default", operator_pinned=False,
            ),
            "phase-loop-execute-medium",
        )

    def test_invalid_gemini_alias_fails_closed_without_explicit_fallback(self):
        policy = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="gemini",
            model="phase-loop-unknown",
            effort="medium",
            work_unit_kind="lane_execute",
            source="plan:execute",
        )

        with self.assertRaisesRegex(ValueError, "unsupported model"):
            resolve_execution_policy(
                action="execute",
                executor="gemini",
                model_selection=ModelSelection(profile="execute", model="phase-loop-execute-medium", effort="medium"),
                plan_policy=policy,
            )

    def test_named_fallback_and_default_inheritance_are_recorded(self):
        fallback_policy = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="gemini",
            model="phase-loop-unknown",
            effort="medium",
            work_unit_kind="lane_execute",
            unsupported_policy_behavior="fallback",
            fallback="phase-loop-execute-medium",
            source="plan:execute",
        )
        inherited_policy = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="gemini",
            model="phase-loop-unknown",
            effort="xhigh",
            work_unit_kind="lane_execute",
            unsupported_policy_behavior="inherit_default",
            inherit_default=True,
            source="roadmap:execute",
        )

        fallback = resolve_execution_policy(
            action="execute",
            executor="gemini",
            model_selection=ModelSelection(profile="execute", model="phase-loop-execute-medium", effort="medium"),
            plan_policy=fallback_policy,
        )
        inherited = resolve_execution_policy(
            action="execute",
            executor="gemini",
            model_selection=ModelSelection(profile="execute", model="phase-loop-execute-medium", effort="medium"),
            roadmap_policy=inherited_policy,
        )

        self.assertEqual(fallback.model, "phase-loop-execute-medium")
        self.assertEqual(fallback.fallback, "phase-loop-execute-medium")
        self.assertEqual(inherited.model, "phase-loop-execute-medium")
        self.assertEqual(inherited.effort, "medium")
        self.assertTrue(inherited.fallback_applied)

    def test_default_executor_profiles_match_high_medium_high_policy(self):
        self.assertEqual(resolve_profile_for_executor(action="roadmap", executor="codex").effort, "high")
        self.assertEqual(resolve_profile_for_executor(action="plan", executor="codex").effort, "high")
        self.assertEqual(resolve_profile_for_executor(action="execute", executor="codex").effort, "medium")
        self.assertEqual(resolve_profile_for_executor(action="repair", executor="codex").effort, "medium")
        self.assertEqual(resolve_profile_for_executor(action="review", executor="codex").effort, "high")
        self.assertEqual(resolve_profile_for_executor(action="maintain-skills", executor="codex").effort, "high")

    def test_pi_policy_fails_closed_for_unsupported_effort_without_fallback(self):
        policy = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="pi",
            model="auto",
            effort="xhigh",
            work_unit_kind="lane_execute",
            source="plan:execute",
        )

        with self.assertRaisesRegex(ValueError, "unsupported effort"):
            resolve_execution_policy(
                action="execute",
                executor="pi",
                model_selection=ModelSelection(profile="execute", model="auto", effort="medium"),
                plan_policy=policy,
            )

    def test_pi_policy_can_inherit_default_effort(self):
        policy = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="pi",
            model="auto",
            effort="xhigh",
            work_unit_kind="lane_execute",
            unsupported_policy_behavior="inherit_default",
            inherit_default=True,
            source="plan:execute",
        )

        resolved = resolve_execution_policy(
            action="execute",
            executor="pi",
            model_selection=ModelSelection(profile="execute", model="auto", effort="medium"),
            plan_policy=policy,
        )
        self.assertEqual(resolved.executor, "pi")
        self.assertEqual(resolved.effort, "medium")
        self.assertTrue(resolved.fallback_applied)

    def test_claude_model_defaults_to_claude_executor_unless_pi_override_is_reasoned(self):
        defaulted = resolve_execution_policy(
            action="execute",
            executor="pi",
            model_selection=ModelSelection(profile="execute", model="claude-opus-4-8", effort="high"),
        )
        self.assertEqual(defaulted.executor, "claude")

        explicit_pi = ExecutionPolicyRule(
            selector="execute",
            action="execute",
            executor="pi",
            model="claude-opus-4-8",
            effort="medium",
            work_unit_kind="lane_execute",
            unsupported_policy_behavior="inherit_default",
            inherit_default=True,
            source="plan:execute",
            override_reason="explicit Pi-wrapped Claude route",
        )
        selected = resolve_execution_policy(
            action="execute",
            executor="pi",
            model_selection=ModelSelection(profile="execute", model="claude-opus-4-8", effort="medium"),
            plan_policy=explicit_pi,
        )
        self.assertEqual(selected.executor, "pi")
        self.assertEqual(selected.execution_policy_override_reason, "explicit Pi-wrapped Claude route")


if __name__ == "__main__":
    unittest.main()
