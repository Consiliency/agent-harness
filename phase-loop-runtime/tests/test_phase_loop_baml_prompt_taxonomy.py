import unittest

from phase_loop_runtime.baml_modular import BamlValidationError, build_baml_request, render_baml_prompt
from phase_loop_runtime.models import BLOCKER_CLASSES, CLOSEOUT_SCHEMA, PHASE_STATUSES


class PhaseLoopBamlPromptTaxonomyTest(unittest.TestCase):
    def test_render_baml_prompt_substitutes_single_constant(self):
        rendered = render_baml_prompt("Status: {{ status }}", {"status": "complete"})
        self.assertEqual(rendered, "Status: complete")

    def test_render_baml_prompt_substitutes_join_filter(self):
        rendered = render_baml_prompt("Statuses: {{ statuses | join(', ') }}", {"statuses": ("planned", "complete")})
        self.assertEqual(rendered, "Statuses: planned, complete")

    def test_render_baml_prompt_substitutes_multiple_constants(self):
        rendered = render_baml_prompt(
            "{{ terminal }} / {{ verification | join(' | ') }}",
            {"terminal": "complete", "verification": ("not_run", "passed")},
        )
        self.assertEqual(rendered, "complete / not_run | passed")

    def test_render_baml_prompt_leaves_non_constant_baml_placeholders_unchanged(self):
        template = "{% for gate in plan_produces %}\n- {{ gate }}\n{% endfor %}\n{{ ctx.output_format }}"
        self.assertEqual(render_baml_prompt(template, {}), template)

    def test_missing_taxonomy_constant_raises_validation_error(self):
        with self.assertRaisesRegex(BamlValidationError, "allowed_terminal_statuses"):
            render_baml_prompt("{{ allowed_terminal_statuses | join(', ') }}", {})

    def test_live_phase_statuses_render_from_models_constants(self):
        rendered = render_baml_prompt(
            "{{ allowed_terminal_statuses | join(', ') }}",
            {"allowed_terminal_statuses": PHASE_STATUSES},
        )
        self.assertEqual(rendered, ", ".join(PHASE_STATUSES))

    def test_emit_phase_closeout_request_renders_taxonomy_placeholders(self):
        request = build_baml_request(
            "EmitPhaseCloseout",
            {
                "phase_alias": "CLOSEOUTPROMPTTAXONOMY",
                "plan_produces": ["IF-0-CLOSEOUTPROMPTTAXONOMY-1", "IF-0-CLOSEOUTPROMPTTAXONOMY-2"],
                "plan_owned_files": ["vendor/phase-loop-runtime/src/phase_loop_runtime/baml_modular.py"],
                "closeout_commit_sha": None,
            },
        )

        for status in PHASE_STATUSES:
            self.assertIn(status, request.prompt)
        for blocker_class in (*BLOCKER_CLASSES, "none"):
            self.assertIn(blocker_class, request.prompt)
        self.assertIn("IF-0-CLOSEOUTPROMPTTAXONOMY-1", request.prompt)
        self.assertIn("Answer in JSON using this schema", request.prompt)
        self.assertIn("terminal_status: string", request.prompt)
        self.assertNotIn("allowed_terminal_statuses", request.prompt)
        self.assertNotIn("allowed_verification_statuses", request.prompt)
        self.assertNotIn("allowed_blocker_classes", request.prompt)

    def test_models_closeout_schema_imports_before_building_closeout_request(self):
        self.assertEqual(CLOSEOUT_SCHEMA["title"], "PhaseLoopNativeCloseout")
        request = build_baml_request(
            "EmitPhaseCloseout",
            {
                "phase_alias": "IMPORTSMOKE",
                "plan_produces": [],
                "plan_owned_files": [],
                "closeout_commit_sha": None,
            },
        )
        self.assertIn("IMPORTSMOKE", request.prompt)


if __name__ == "__main__":
    unittest.main()
