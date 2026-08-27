"""model-routing-v1 P1 — model_class layer, shipped model_policy, effort clamp.

Two axes, kept separate: the *empty-policy* path (no model_policy) is byte-for-byte
unchanged (back-compat for downstream repos); the *shipped* model_policy is THIS
repo's default (planning at max, implementation at the implementer model).
"""
import unittest

from phase_loop_runtime.models import ExecutionPolicyRule
from phase_loop_runtime.governed_premerge import next_escalation
from phase_loop_runtime.profiles import (
    apply_model_class_escalation,
    resolve_execution_policy,
    resolve_model_class,
    resolve_profile_for_executor,
    shipped_model_policy_rule,
)


def _resolved(action, executor, *, model_policy=False, plan_policy=None,
              operator_model=None, operator_effort=None):
    selection = resolve_profile_for_executor(action=action, executor=executor)
    rule = shipped_model_policy_rule(action) if model_policy else None
    return resolve_execution_policy(
        action=action, executor=executor, model_selection=selection,
        plan_policy=plan_policy, model_policy_rule=rule,
        operator_model=operator_model, operator_effort=operator_effort,
    )


def _resolve(action, executor, **kwargs):
    rp = _resolved(action, executor, **kwargs)
    return rp.model, rp.effort


class ModelClassResolutionTest(unittest.TestCase):
    def test_class_to_model_per_executor(self):
        self.assertEqual(resolve_model_class("claude", "planner"), "claude-opus-5")
        self.assertEqual(resolve_model_class("claude", "reviewer"), "claude-fable-5")
        self.assertEqual(resolve_model_class("claude", "implementer"), "claude-sonnet-5")
        # design-model-tier-taxonomy.md: worker class → the lite tier's DATED pin
        # (was the undated claude-haiku-4-5, a floating-alias shape).
        self.assertEqual(resolve_model_class("claude", "worker"), "claude-haiku-4-5-20251001")
        self.assertEqual(resolve_model_class("codex", "implementer"), "gpt-5.6-terra")
        # Gemini keeps `pro` for planning; implementer uses the canonical agy 3.7 Flash id
        # (newest GA, CR round-5 finding B), worker the agy 3.5 Flash id (agy has no flash-lite
        # → the matrix's gemini-3.5-flash-lite lite cell is aspirational).
        self.assertEqual(resolve_model_class("gemini", "planner"), "pro")
        self.assertEqual(resolve_model_class("gemini", "reviewer"), "pro")
        self.assertEqual(resolve_model_class("gemini", "implementer"), "gemini-3.7-flash")
        self.assertEqual(resolve_model_class("gemini", "worker"), "gemini-3.5-flash-high")
        self.assertIsNone(resolve_model_class("claude", "bogus"))

    def test_model_class_field_validates(self):
        ExecutionPolicyRule(model_class="planner")  # ok
        ExecutionPolicyRule(model_class="reviewer")  # ok
        with self.assertRaises(ValueError):
            ExecutionPolicyRule(model_class="not_a_class")


class EmptyPolicyBackCompatTest(unittest.TestCase):
    def test_plan_codex_unchanged(self):
        self.assertEqual(_resolve("plan", "codex", model_policy=False), ("gpt-5.6-sol", "high"))

    def test_execute_claude_unchanged(self):
        # design-model-tier-taxonomy.md (operator-ratified): claude execute uses the
        # regular tier (sonnet-5) on the empty-policy path too — the executor-default
        # and tier/class paths agree (opus-4-8 → sonnet-5).
        self.assertEqual(_resolve("execute", "claude", model_policy=False), ("claude-sonnet-5", "high"))


class ShippedPolicyTest(unittest.TestCase):
    def test_plan_codex_becomes_max(self):
        self.assertEqual(_resolve("plan", "codex", model_policy=True), ("gpt-5.6-sol", "max"))

    def test_roadmap_is_max(self):
        self.assertEqual(_resolve("roadmap", "codex", model_policy=True)[1], "max")

    def test_execute_claude_becomes_sonnet_high(self):
        self.assertEqual(_resolve("execute", "claude", model_policy=True), ("claude-sonnet-5", "high"))

    def test_review_claude_uses_reviewer_fable(self):
        resolved = _resolved("review", "claude", model_policy=True)
        self.assertEqual(resolved.model_class, "reviewer")
        self.assertEqual((resolved.model, resolved.effort), ("claude-fable-5", "max"))


class EffortClampTest(unittest.TestCase):
    def test_gemini_plan_max_clamps_to_high_with_shipped_policy(self):
        # The shipped policy sets fallback so gemini's effort_map maps max->high.
        self.assertEqual(_resolve("plan", "gemini", model_policy=True), ("pro", "high"))

    def test_gemini_clamp_records_requested_and_policy_effort(self):
        resolved = _resolved("plan", "gemini", model_policy=True)
        self.assertEqual(resolved.requested_effort, "max")
        self.assertEqual(resolved.policy_effort, "high")
        self.assertEqual(resolved.effort, "high")
        self.assertTrue(resolved.fallback_applied)

    def test_gemini_max_raises_without_clamp(self):
        # Documenting the verified runtime behavior: a max request for a sub-max
        # provider RAISES unless the rule opts into fallback/inherit_default.
        no_clamp = ExecutionPolicyRule(
            selector="plan", action="plan", effort="max",
            unsupported_policy_behavior="block", source="test",
        )
        selection = resolve_profile_for_executor(action="plan", executor="gemini")
        with self.assertRaises(ValueError):
            resolve_execution_policy(
                action="plan", executor="gemini",
                model_selection=selection, model_policy_rule=no_clamp,
            )


class PrecedenceTest(unittest.TestCase):
    def test_operator_effort_beats_model_policy(self):
        # CLI > model_policy: operator --effort low overrides shipped max.
        self.assertEqual(_resolve("plan", "codex", model_policy=True, operator_effort="low")[1], "low")

    def test_operator_model_beats_model_policy(self):
        self.assertEqual(
            _resolve("plan", "codex", model_policy=True, operator_model="gpt-5.6-terra")[0], "gpt-5.6-terra"
        )

    def test_plan_policy_beats_model_policy(self):
        # plan ## Execution Policy > model_policy: explicit effort xhigh wins.
        plan_rule = ExecutionPolicyRule(selector="plan", action="plan", effort="xhigh", source="phase-plan policy")
        self.assertEqual(_resolve("plan", "codex", model_policy=True, plan_policy=plan_rule)[1], "xhigh")

    def test_plan_policy_effort_only_inherits_shipped_model_class(self):
        # CR fix: a plan Execution Policy pinning ONLY effort must still inherit
        # the shipped model_policy's implementer class (layered merge), not revert
        # to the registry heavy model.
        plan = ExecutionPolicyRule(selector="execute", action="execute", effort="low", source="phase-plan policy")
        model, effort = _resolve("execute", "claude", model_policy=True, plan_policy=plan)
        self.assertEqual(model, "claude-sonnet-5")  # implementer, from model_policy
        self.assertEqual(effort, "low")               # plan's effort wins

    def test_plan_policy_executor_only_inherits_shipped_model_class(self):
        plan = ExecutionPolicyRule(selector="execute", action="execute", executor="claude", source="phase-plan policy")
        model, _effort = _resolve("execute", "claude", model_policy=True, plan_policy=plan)
        self.assertEqual(model, "claude-sonnet-5")  # implementer still applied


class MaxEffortPlannerGuardTest(unittest.TestCase):
    def test_gemini_planner_max_clamps_via_guard_without_explicit_clamp(self):
        # CR fix: planner@max on gemini (no explicit clamp policy) must not RAISE —
        # the wired max-effort-planner guard forces the clamp to the ceiling.
        plan = ExecutionPolicyRule(
            selector="plan", action="plan", model_class="planner", effort="max", source="phase-plan policy"
        )
        model, effort = _resolve("plan", "gemini", plan_policy=plan)
        self.assertEqual(effort, "high")  # clamped via the guard, not raised
        self.assertEqual(model, "pro")    # gemini planner alias

    def test_codex_planner_max_stays_max(self):
        # codex IS max-eligible — the guard does not touch it.
        plan = ExecutionPolicyRule(
            selector="plan", action="plan", model_class="planner", effort="max", source="phase-plan policy"
        )
        self.assertEqual(_resolve("plan", "codex", plan_policy=plan)[1], "max")


class AppliedModelClassEscalationTest(unittest.TestCase):
    def _apply(self, executor, *, operator_model_present=False):
        policy = _resolved("repair", executor, model_policy=True)
        decision = next_escalation(model_class="implementer", failed_tests=2, run_mode="governed")
        return policy, apply_model_class_escalation(
            policy,
            executor=executor,
            decision=decision,
            from_model_class="implementer",
            operator_model_present=operator_model_present,
        )

    def test_claude_escalates_to_opus_and_preserves_other_policy_fields(self):
        policy, result = self._apply("claude")
        self.assertTrue(result.applied)
        self.assertEqual(result.policy.model, "claude-opus-5")
        self.assertEqual(result.policy.model_class, "planner")
        self.assertEqual(result.policy.model_source, "runtime model-class escalation")
        self.assertEqual(result.policy.effort, policy.effort)
        self.assertEqual(result.policy.fallback, policy.fallback)
        self.assertEqual(result.policy.fallback_applied, policy.fallback_applied)

    def test_codex_and_manual_map_provider_resolve_their_planner_models(self):
        self.assertEqual(self._apply("codex")[1].effective_model, "gpt-5.6-sol")
        self.assertEqual(self._apply("gemini")[1].effective_model, "pro")

    def test_explicit_operator_model_is_not_overridden(self):
        policy, result = self._apply("claude", operator_model_present=True)
        self.assertFalse(result.applied)
        self.assertEqual(result.policy, policy)
        self.assertEqual(result.not_applied_reason, "explicit_operator_model")

    def test_unmapped_target_class_fails_closed(self):
        policy = _resolved("repair", "command", model_policy=False)
        decision = next_escalation(model_class="implementer", failed_tests=2, run_mode="governed")
        with self.assertRaisesRegex(ValueError, "no model mapping"):
            apply_model_class_escalation(
                policy,
                executor="command",
                decision=decision,
                from_model_class="implementer",
                operator_model_present=False,
            )


if __name__ == "__main__":
    unittest.main()
