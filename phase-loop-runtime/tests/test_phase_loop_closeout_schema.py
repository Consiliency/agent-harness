import unittest

from phase_loop_runtime.models import BLOCKER_CLASSES, CLOSEOUT_SCHEMA, PHASE_STATUSES


class PhaseLoopCloseoutSchemaTest(unittest.TestCase):
    def test_closeout_schema_requires_native_fields(self):
        self.assertEqual(CLOSEOUT_SCHEMA["type"], "object")
        self.assertEqual(
            tuple(CLOSEOUT_SCHEMA["required"]),
            ("terminal_status", "verification_status", "dirty_paths", "produced_if_gates"),
        )
        properties = CLOSEOUT_SCHEMA["properties"]
        for field in CLOSEOUT_SCHEMA["required"]:
            self.assertIn(field, properties)
        self.assertEqual(tuple(properties["terminal_status"]["enum"]), PHASE_STATUSES)
        self.assertEqual(tuple(properties["blocker_class"]["enum"]), (*BLOCKER_CLASSES, "none"))

    def test_complete_closeout_requires_at_least_one_produced_gate(self):
        complete_rule = CLOSEOUT_SCHEMA["allOf"][0]

        self.assertEqual(complete_rule["if"]["properties"]["terminal_status"]["const"], "complete")
        self.assertEqual(complete_rule["then"]["properties"]["produced_if_gates"]["minItems"], 1)


if __name__ == "__main__":
    unittest.main()
