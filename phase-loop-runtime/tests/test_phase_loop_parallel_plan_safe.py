from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime.runner import _classify_dirty_paths, _dirty_paths, is_sibling_phase_plan_doc
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_named_roadmap


def _write_versioned_plan(repo: Path, roadmap: Path, phase: str, *, version: str = "v25") -> Path:
    plan = repo / "plans" / f"phase-plan-{version}-{phase.upper()}.md"
    roadmap_hash = hashlib.sha256(roadmap.read_bytes()).hexdigest()
    plan.write_text(
        "---\n"
        "phase_loop_plan_version: 1\n"
        f"phase: {phase.upper()}\n"
        f"roadmap: {roadmap.relative_to(repo)}\n"
        f"roadmap_sha256: {roadmap_hash}\n"
        "---\n"
        f"# {phase.upper()}\n\n"
        "## Lanes\n\n"
        f"### SL-0 - {phase.upper()}\n"
        "- **Owned files**: `notes.md`\n",
        encoding="utf-8",
    )
    return plan


class ParallelPlanSafeTests(unittest.TestCase):
    def test_four_way_parallel_plan_fixture_marks_siblings_expected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = write_named_roadmap(
                repo,
                (("ALPHA", "Alpha"), ("BETA", "Beta"), ("GAMMA", "Gamma"), ("DELTA", "Delta")),
                version="v25",
            )
            plan = _write_versioned_plan(repo, roadmap, "ALPHA")

            summary = _classify_dirty_paths(
                repo,
                roadmap,
                plan,
                pre_launch_dirty_paths=[],
                post_launch_dirty_paths=[
                    "plans/phase-plan-v25-BETA.md",
                    "plans/phase-plan-v25-GAMMA.md",
                    "plans/phase-plan-v25-DELTA.md",
                ],
                current_phase="ALPHA",
            )

            self.assertTrue(summary["expected_sibling_dirty"])
            self.assertEqual(
                summary["expected_sibling_dirty_paths"],
                ["plans/phase-plan-v25-BETA.md", "plans/phase-plan-v25-GAMMA.md", "plans/phase-plan-v25-DELTA.md"],
            )
            self.assertEqual(summary["unowned_dirty_paths"], [])
            self.assertTrue(summary["phase_owned_dirty"])

    def test_two_way_parallel_fixture_marks_single_sibling_expected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = write_named_roadmap(repo, (("ALPHA", "Alpha"), ("BETA", "Beta")), version="v25")
            plan = _write_versioned_plan(repo, roadmap, "ALPHA")

            summary = _classify_dirty_paths(
                repo,
                roadmap,
                plan,
                pre_launch_dirty_paths=[],
                post_launch_dirty_paths=["plans/phase-plan-v25-BETA.md"],
                current_phase="ALPHA",
            )

            self.assertEqual(summary["expected_sibling_dirty_paths"], ["plans/phase-plan-v25-BETA.md"])
            self.assertEqual(summary["unowned_dirty_paths"], [])

    def test_single_phase_has_no_sibling_false_positive(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = write_named_roadmap(repo, (("ALPHA", "Alpha"),), version="v25")

            self.assertFalse(is_sibling_phase_plan_doc("plans/phase-plan-v25-BETA.md", roadmap, "ALPHA"))

    def test_alternate_directory_and_absolute_paths_are_not_whitelisted(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = write_named_roadmap(repo, (("ALPHA", "Alpha"), ("BETA", "Beta")), version="v25")

            self.assertFalse(is_sibling_phase_plan_doc("tmp/phase-plan-v25-BETA.md", roadmap, "ALPHA"))
            self.assertFalse(is_sibling_phase_plan_doc("../plans/phase-plan-v25-BETA.md", roadmap, "ALPHA"))
            self.assertFalse(is_sibling_phase_plan_doc("/repo/plans/phase-plan-v25-BETA.md", roadmap, "ALPHA"))

    def test_wrong_roadmap_version_is_not_whitelisted(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = write_named_roadmap(repo, (("ALPHA", "Alpha"), ("BETA", "Beta")), version="v25")

            self.assertFalse(is_sibling_phase_plan_doc("plans/phase-plan-v24-BETA.md", roadmap, "ALPHA"))

    def test_current_phase_plan_doc_is_treated_normally(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = write_named_roadmap(repo, (("ALPHA", "Alpha"), ("BETA", "Beta")), version="v25")
            plan = _write_versioned_plan(repo, roadmap, "ALPHA")

            summary = _classify_dirty_paths(
                repo,
                roadmap,
                plan,
                pre_launch_dirty_paths=[],
                post_launch_dirty_paths=["plans/phase-plan-v25-ALPHA.md"],
                current_phase="ALPHA",
            )

            self.assertEqual(summary["expected_sibling_dirty_paths"], [])
            self.assertIn("plans/phase-plan-v25-ALPHA.md", summary["phase_owned_dirty_paths"])

    def test_temp_git_smoke_classifies_four_simulated_sibling_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = write_named_roadmap(
                repo,
                (
                    ("ALPHA", "Alpha"),
                    ("BETA", "Beta"),
                    ("GAMMA", "Gamma"),
                    ("DELTA", "Delta"),
                    ("EPSILON", "Epsilon"),
                ),
                version="v25",
            )
            plan = _write_versioned_plan(repo, roadmap, "ALPHA")
            commit_fixture_paths(repo, "parallel plan fixture", roadmap, plan)
            for phase in ("BETA", "GAMMA", "DELTA", "EPSILON"):
                _write_versioned_plan(repo, roadmap, phase)

            dirty_paths = _dirty_paths(repo)
            summary = _classify_dirty_paths(
                repo,
                roadmap,
                plan,
                pre_launch_dirty_paths=[],
                post_launch_dirty_paths=dirty_paths,
                current_phase="ALPHA",
            )

            self.assertEqual(
                summary["expected_sibling_dirty_paths"],
                [
                    "plans/phase-plan-v25-BETA.md",
                    "plans/phase-plan-v25-DELTA.md",
                    "plans/phase-plan-v25-EPSILON.md",
                    "plans/phase-plan-v25-GAMMA.md",
                ],
            )
            self.assertEqual(summary["unowned_dirty_paths"], [])
            self.assertTrue(summary["phase_owned_dirty"])


if __name__ == "__main__":
    unittest.main()
