from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime.cli import main
from phase_loop_runtime.evidence_audit import (
    detect_boilerplate_text,
    detect_loose_uniform,
    detect_size_distribution,
    run_evidence_audit,
)


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)


class LooseUniformTier2Test(unittest.TestCase):
    def test_flags_near_uniform_numeric_array(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scores.json"
            path.write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")

            findings = detect_loose_uniform(path)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].json_pointer, "$.scores")
            self.assertLess(findings[0].coefficient_of_variation, 1e-3)

    def test_flags_near_uniform_object_array_field(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "routes.json"
            path.write_text(
                json.dumps({"routes": [{"similarity": value} for value in (0.9998, 0.9999, 1.0, 1.0001)]}),
                encoding="utf-8",
            )

            findings = detect_loose_uniform(path)

            self.assertEqual([finding.json_pointer for finding in findings], ["$.routes[*].similarity"])

    def test_exact_uniform_numeric_array_is_tier1_not_loose_uniform(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scores.json"
            path.write_text(json.dumps({"scores": [0.99, 0.99, 0.99, 0.99]}), encoding="utf-8")

            self.assertEqual(detect_loose_uniform(path), [])

    def test_varied_numeric_array_is_not_loose_uniform(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scores.json"
            path.write_text(json.dumps({"scores": [0.72, 0.81, 0.95, 0.99]}), encoding="utf-8")

            self.assertEqual(detect_loose_uniform(path), [])


class BoilerplateTier2Test(unittest.TestCase):
    def test_flags_boilerplate_text_after_stripping_path_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shared = (
                "Operator verdict accepted generated evidence requires manual review "
                "before reconcile because findings must be provenance backed."
            )
            files = []
            for index in range(3):
                path = root / f"verdict-{index}.md"
                path.write_text(f"{shared} See /tmp/run-{index}/artifact-{index}.json", encoding="utf-8")
                files.append(path)

            findings = detect_boilerplate_text(files)

            self.assertEqual(len(findings), 1)
            self.assertEqual(len(findings[0].paths), 3)
            self.assertNotIn("/tmp/run-0/artifact-0.json", findings[0].sample_tokens)

    def test_skips_binary_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binary = root / "image.bin"
            binary.write_bytes(b"\xff\xfe\x00\x00")
            text = root / "report.md"
            text.write_text("short but readable", encoding="utf-8")

            self.assertEqual(detect_boilerplate_text([binary, text]), [])

    def test_distinct_text_is_not_boilerplate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = []
            for index, content in enumerate(("alpha beta gamma", "delta epsilon zeta", "eta theta iota")):
                path = root / f"report-{index}.md"
                path.write_text(content, encoding="utf-8")
                files.append(path)

            self.assertEqual(detect_boilerplate_text(files), [])


class SizeDistributionTier2Test(unittest.TestCase):
    def test_flags_low_variance_sibling_file_sizes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "screens"
            root.mkdir()
            files = []
            for index, size in enumerate((1000, 1002, 998, 1001)):
                path = root / f"shot-{index}.png"
                path.write_bytes(b"x" * size)
                files.append(path)

            findings = detect_size_distribution(files)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].sibling_directory, str(root))

    def test_groups_by_sibling_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = []
            for dirname, size in (("a", 100), ("b", 200)):
                directory = root / dirname
                directory.mkdir()
                for index in range(2):
                    path = directory / f"file-{index}.txt"
                    path.write_bytes(b"x" * size)
                    files.append(path)

            self.assertEqual(detect_size_distribution(files, min_group_size=3), [])

    def test_varied_sibling_file_sizes_are_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = []
            for index, size in enumerate((100, 500, 900)):
                path = root / f"file-{index}.txt"
                path.write_bytes(b"x" * size)
                files.append(path)

            self.assertEqual(detect_size_distribution(files), [])


class Tier2CliIntegrationTest(unittest.TestCase):
    def test_default_json_output_omits_tier2_findings(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_git_repo(repo)
            (repo / "scores.json").write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")

            result = run_evidence_audit(repo, dirty_only=True)

            self.assertTrue(result.is_clean())
            self.assertNotIn("tier2_findings", result.to_json())

    def test_tier2_json_output_includes_findings_and_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_git_repo(repo)
            (repo / "scores.json").write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["evidence-audit", "--repo", str(repo), "--tier-2", "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 5)
            self.assertIn("tier2_findings", payload)
            self.assertEqual(len(payload["tier2_findings"]["loose_uniform"]), 1)

    def test_tier2_text_output_uses_tier2_prefixes(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_git_repo(repo)
            (repo / "scores.json").write_text(json.dumps({"scores": [1.0, 1.0001, 0.9999, 1.00005]}), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["evidence-audit", "--repo", str(repo), "--tier-2"])

            self.assertEqual(code, 5)
            self.assertIn("tier2: loose-uniform", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
