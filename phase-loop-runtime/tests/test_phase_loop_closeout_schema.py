import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime.baml_modular import export_function_schema
from phase_loop_runtime.models import BLOCKER_CLASSES, CLOSEOUT_SCHEMA, PHASE_STATUSES


class PhaseLoopCloseoutSchemaTest(unittest.TestCase):
    def test_closeout_schema_requires_native_fields(self):
        self.assertEqual(CLOSEOUT_SCHEMA, export_function_schema("EmitPhaseCloseout"))
        self.assertEqual(CLOSEOUT_SCHEMA["type"], "object")
        properties = CLOSEOUT_SCHEMA["properties"]
        # OpenAI Responses API requires `required` to list EVERY property.
        # "Optional" fields are nullable instead.
        self.assertEqual(
            set(CLOSEOUT_SCHEMA["required"]),
            set(properties.keys()),
            msg="OpenAI Responses API requires every property to be in `required`",
        )
        # Core native fields must be present:
        for field in ("terminal_status", "verification_status", "dirty_paths", "produced_if_gates"):
            self.assertIn(field, properties)
            self.assertIn(field, CLOSEOUT_SCHEMA["required"])
        self.assertEqual(tuple(properties["terminal_status"]["enum"]), PHASE_STATUSES)
        # blocker_class now includes None in its enum (nullable for "no blocker"):
        self.assertIn(None, properties["blocker_class"]["enum"])
        for cls in BLOCKER_CLASSES:
            self.assertIn(cls, properties["blocker_class"]["enum"])

    def test_complete_closeout_requires_at_least_one_produced_gate_via_runner_check(self):
        # The conditional rule "when terminal_status=complete, produced_if_gates
        # must be non-empty" was previously expressed in the schema via allOf +
        # if/then. OpenAI's response_format JSON Schema dialect (used by Codex
        # --output-schema) rejects allOf/anyOf/oneOf/not/if/then — only a strict
        # subset is supported. We moved the conditional enforcement to runner-
        # side IF-gate Tier 1 validation in closeout_validation. The schema
        # therefore should NOT contain allOf.
        self.assertNotIn("allOf", CLOSEOUT_SCHEMA, msg="schema must avoid allOf for Codex --output-schema dialect compatibility")
        # produced_if_gates remains structurally required at the schema layer:
        self.assertIn("produced_if_gates", CLOSEOUT_SCHEMA["required"])
        # The complete-status non-empty enforcement lives in closeout_validation:
        from phase_loop_runtime.closeout_validation import validate_produced_gates
        with tempfile.TemporaryDirectory() as td:
            plan = Path(td) / "phase-plan.md"
            plan.write_text("# X\n\n**Produces**: IF-0-X-1\n", encoding="utf-8")
            result = validate_produced_gates(plan, {"terminal_status": "complete", "produced_if_gates": []})
        self.assertFalse(result.ok, "validator must reject empty produced_if_gates when terminal_status=complete")
        self.assertIsNotNone(result.blocker_class, "rejection must surface a typed blocker_class")


if __name__ == "__main__":
    unittest.main()
