from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase_loop_runtime.baml_modular import BamlRequest, export_function_schema, parse_baml_response
from phase_loop_runtime.cli import main
from phase_loop_runtime.evidence_audit import (
    EvidenceJudgment,
    LooseUniformFinding,
    evaluate_suspected_fake_evidence,
    run_evidence_audit,
)


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)


def _loose_finding(path: Path) -> LooseUniformFinding:
    return LooseUniformFinding(
        json_artifact=str(path),
        json_pointer="$.scores",
        array_length=4,
        mean=1.0,
        stdev=0.00005,
        coefficient_of_variation=0.00005,
    )


class Tier3BamlSchemaTest(unittest.TestCase):
    def test_evaluate_suspected_fake_evidence_schema_exports_openai_clean_object(self):
        schema = export_function_schema("EvaluateSuspectedFakeEvidence")

        self.assertEqual(schema["title"], "EvidenceJudgment")
        self.assertEqual(set(schema["required"]), {"verdict", "confidence", "reasoning", "specific_concerns"})
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        forbidden = {"allOf", "anyOf", "oneOf", "not", "uniqueItems", "minItems", "maxItems"}

        def walk(value):
            if isinstance(value, dict):
                yield value
                for child in value.values():
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)

        self.assertTrue(all(forbidden.isdisjoint(node) for node in walk(schema)))

    def test_evidence_judgment_accepts_verdict_variants(self):
        for verdict in ("real", "fake", "uncertain"):
            parsed = parse_baml_response(
                "EvidenceJudgment",
                json.dumps(
                    {
                        "verdict": verdict,
                        "confidence": 0.75,
                        "reasoning": f"{verdict} fixture",
                        "specific_concerns": ["fixture concern"],
                    }
                ),
            )
            self.assertEqual(parsed.payload["verdict"], verdict)


class Tier3WrapperTest(unittest.TestCase):
    def test_wrapper_builds_prompt_payload_and_truncates_sample(self):
        with tempfile.TemporaryDirectory() as td:
            sample = Path(td) / "artifact.json"
            sample.write_text("a" * 9000, encoding="utf-8")
            captured = {}

            def build_request(function_name, payload):
                captured["function_name"] = function_name
                captured["payload"] = payload
                return BamlRequest(None, "https://example.invalid", "POST", {}, {"messages": []}, "prompt")

            with patch("phase_loop_runtime.evidence_audit.build_baml_request", side_effect=build_request), patch(
                "phase_loop_runtime.evidence_audit._execute_baml_request",
                return_value=json.dumps(
                    {
                        "verdict": "uncertain",
                        "confidence": 0.5,
                        "reasoning": "needs review",
                        "specific_concerns": ["near uniform"],
                    }
                ),
            ):
                judgment = evaluate_suspected_fake_evidence(_loose_finding(sample), sample, "varied scores")

            self.assertEqual(captured["function_name"], "EvaluateSuspectedFakeEvidence")
            self.assertEqual(len(captured["payload"]["sample_artifact_content"]), 8192)
            self.assertIn("tier2_uncertain_loose_uniform", captured["payload"]["tier2_signal_summary"])
            self.assertEqual(judgment.verdict, "uncertain")

    def test_wrapper_returns_uncertain_on_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            sample = Path(td) / "artifact.json"
            sample.write_text("{}", encoding="utf-8")

            with patch(
                "phase_loop_runtime.evidence_audit.build_baml_request",
                return_value=BamlRequest(None, "https://example.invalid", "POST", {}, {}, "prompt"),
            ), patch("phase_loop_runtime.evidence_audit._execute_baml_request", side_effect=TimeoutError("slow")):
                judgment = evaluate_suspected_fake_evidence(_loose_finding(sample), sample, "varied scores")

            self.assertEqual(judgment.verdict, "uncertain")
            self.assertEqual(judgment.confidence, 0.0)
            self.assertIn("tier3_call_error", judgment.reasoning)

    def test_wrapper_returns_uncertain_on_parse_error(self):
        with tempfile.TemporaryDirectory() as td:
            sample = Path(td) / "artifact.json"
            sample.write_text("{}", encoding="utf-8")

            with patch(
                "phase_loop_runtime.evidence_audit.build_baml_request",
                return_value=BamlRequest(None, "https://example.invalid", "POST", {}, {}, "prompt"),
            ), patch("phase_loop_runtime.evidence_audit._execute_baml_request", return_value="not json"), patch(
                "phase_loop_runtime.evidence_audit.parse_baml_response", side_effect=ValueError("bad payload")
            ):
                judgment = evaluate_suspected_fake_evidence(_loose_finding(sample), sample, "varied scores")

            self.assertEqual(judgment.verdict, "uncertain")
            self.assertEqual(judgment.specific_concerns, ("bad payload",))


class Tier3AuditIntegrationTest(unittest.TestCase):
    def test_default_flag_off_skips_tier3_for_uncertain_tier2_finding(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_git_repo(repo)
            (repo / "scores.json").write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")

            with patch("phase_loop_runtime.evidence_audit.evaluate_suspected_fake_evidence") as tier3:
                result = run_evidence_audit(repo, tier2_enabled=True, enable_tier_3=False)

            tier3.assert_not_called()
            self.assertFalse(result.tier3_enabled)

    def test_enabled_flag_invokes_tier3_for_uncertain_tier2_finding(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_git_repo(repo)
            (repo / "scores.json").write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")

            with patch(
                "phase_loop_runtime.evidence_audit.evaluate_suspected_fake_evidence",
                return_value=EvidenceJudgment("uncertain", 0.25, "review", ("near uniform",)),
            ) as tier3:
                result = run_evidence_audit(repo, tier2_enabled=True, enable_tier_3=True)

            tier3.assert_called_once()
            self.assertEqual(result.tier3_judgments[0].specific_concerns, ("near uniform",))

    def test_enabled_flag_bypasses_clean_and_tier1_suspect_outcomes(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_git_repo(repo)
            (repo / "clean.json").write_text(json.dumps({"scores": [0.72, 0.81, 0.95, 0.99]}), encoding="utf-8")

            with patch("phase_loop_runtime.evidence_audit.evaluate_suspected_fake_evidence") as tier3:
                clean = run_evidence_audit(repo, tier2_enabled=True, enable_tier_3=True)

            tier3.assert_not_called()
            self.assertTrue(clean.is_clean())

            (repo / "suspect.json").write_text(json.dumps({"scores": [0.999999] * 4}), encoding="utf-8")
            with patch("phase_loop_runtime.evidence_audit.evaluate_suspected_fake_evidence") as tier3:
                suspect = run_evidence_audit(repo, tier2_enabled=True, enable_tier_3=True)

            tier3.assert_not_called()
            self.assertTrue(suspect.uniform_numeric)

    def test_cli_help_exposes_enable_tier3(self):
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(stdout):
            main(["evidence-audit", "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--enable-tier-3", stdout.getvalue())

    def test_cli_enabled_invokes_uncertain_tier2_without_live_llm(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_git_repo(repo)
            (repo / "scores.json").write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")
            stdout = io.StringIO()

            with patch(
                "phase_loop_runtime.evidence_audit.evaluate_suspected_fake_evidence",
                return_value=EvidenceJudgment("uncertain", 0.25, "review", ("near uniform",)),
            ) as tier3, contextlib.redirect_stdout(stdout):
                code = main(["evidence-audit", "--repo", str(repo), "--enable-tier-3", "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 5)
            tier3.assert_called_once()
            self.assertIn("tier3_judgments", payload)


if __name__ == "__main__":
    unittest.main()
