import unittest

from phase_loop_runtime.models import DISPATCH_CAPABILITIES, EXECUTORS, PRODUCT_LOOP_ACTIONS
from phase_loop_runtime.planner_validation import ValidationFinding, validate_plan_dispatch_hints


class PhaseLoopPlannerValidationTest(unittest.TestCase):
    def test_invalid_terminal_status_dry_run_is_flagged(self):
        findings = validate_plan_dispatch_hints('{"terminal_status": "dry_run", "verification_status": "not_run"}')
        self.assertEqual(findings[0].field_path, "closeout.terminal_status")
        self.assertEqual(findings[0].literal, "dry_run")
        self.assertIn("complete", findings[0].allowed_values)
        self.assertIn("Use one of", findings[0].suggested_fix)

    def test_valid_browser_automation_dispatch_capability_passes(self):
        plan = "## Dispatch Hints\n- required capabilities: `browser_automation`, `structured_output`\n"
        self.assertEqual(validate_plan_dispatch_hints(plan), [])

    def test_invalid_dispatch_capability_is_flagged(self):
        plan = "## Dispatch Hints\n- required capabilities: browser_automation, completely_invented\n"
        findings = validate_plan_dispatch_hints(plan)
        self.assertEqual(findings[0].field_path, "dispatch_hints.required_capabilities[1]")
        self.assertEqual(findings[0].literal, "completely_invented")
        self.assertIn("browser_automation", findings[0].allowed_values)

    def test_invalid_executor_literal_is_flagged(self):
        plan = "## Dispatch Hints\n- allowed executors: `codex`, `imaginary_harness`\n"
        findings = validate_plan_dispatch_hints(plan)
        self.assertEqual(findings[0].field_path, "dispatch_hints.allowed_executors[1]")
        self.assertEqual(findings[0].literal, "imaginary_harness")
        self.assertIn("claude", findings[0].allowed_values)

    def test_invalid_dispatch_action_selector_is_flagged(self):
        plan = "## Dispatch Hints\n- summarize preferred executors: `codex`\n"
        findings = validate_plan_dispatch_hints(plan)
        self.assertEqual(findings[0].field_path, "dispatch_hints.selector")
        self.assertEqual(findings[0].literal, "summarize")
        self.assertIn("execute", findings[0].allowed_values)

    def test_invalid_execution_policy_selector_is_flagged(self):
        plan = "## Execution Policy\n- reduce: executor=`codex`, work-unit=`phase_reducer`\n"
        findings = validate_plan_dispatch_hints(plan)
        self.assertEqual(findings[0].field_path, "execution_policy.selector")
        self.assertEqual(findings[0].literal, "reduce")
        self.assertIn("SL-<N>", findings[0].allowed_values)

    def test_lane_execution_policy_selector_is_valid(self):
        plan = "## Execution Policy\n- SL-2: executor=`codex`, work-unit=`phase_reducer`\n"
        self.assertEqual(validate_plan_dispatch_hints(plan), [])

    def test_invalid_execution_policy_executor_is_flagged(self):
        plan = "## Execution Policy\n- execute: executor=`invented_executor`, work-unit=`lane_execute`\n"
        findings = validate_plan_dispatch_hints(plan)
        self.assertEqual(findings[0].field_path, "execution_policy.execute.executor")
        self.assertEqual(findings[0].literal, "invented_executor")

    def test_invalid_verification_status_is_flagged(self):
        findings = validate_plan_dispatch_hints("verification_status: mostly_passed")
        self.assertEqual(findings[0].field_path, "closeout.verification_status")
        self.assertEqual(findings[0].literal, "mostly_passed")
        self.assertIn("blocked", findings[0].allowed_values)

    def test_historical_invented_blocker_classes_are_flagged(self):
        invented = (
            "blocked_by_implementation",
            "needs_operator_review",
            "requires_manual_reconcile",
            "planner_validation_failed",
            "phase_loop_drift",
            "runtime_schema_drift",
        )
        plan = "\n".join(f"blocker_class: {literal}" for literal in invented)
        findings = validate_plan_dispatch_hints(plan)
        self.assertEqual([finding.literal for finding in findings], list(invented))
        self.assertTrue(all(finding.field_path == "closeout.blocker_class" for finding in findings))

    def test_every_valid_dispatch_capability_passes(self):
        plan = "## Dispatch Hints\n- required capabilities: " + ", ".join(f"`{value}`" for value in DISPATCH_CAPABILITIES)
        self.assertEqual(validate_plan_dispatch_hints(plan), [])

    def test_every_valid_executor_passes(self):
        plan = "## Dispatch Hints\n- allowed executors: " + ", ".join(f"`{value}`" for value in EXECUTORS)
        self.assertEqual(validate_plan_dispatch_hints(plan), [])

    def test_every_valid_product_loop_action_selector_passes(self):
        plan = "## Execution Policy\n" + "\n".join(
            f"- {action}: executor=`codex`, work-unit=`lane_execute`" for action in PRODUCT_LOOP_ACTIONS
        )
        self.assertEqual(validate_plan_dispatch_hints(plan), [])

    def test_finding_shape_is_stable_and_metadata_only(self):
        findings = validate_plan_dispatch_hints("## Dispatch Hints\n- required capabilities: secret_token_123\n")
        self.assertIsInstance(findings[0], ValidationFinding)
        self.assertEqual(findings[0].field_path, "dispatch_hints.required_capabilities[0]")
        self.assertEqual(findings[0].literal, "secret_token_123")
        self.assertIsInstance(findings[0].allowed_values, tuple)
        self.assertNotIn("provider_payload", findings[0].suggested_fix)


if __name__ == "__main__":
    unittest.main()
