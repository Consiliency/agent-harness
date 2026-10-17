"""agent-harness#1358: adapter-mode Claude runs may read linked `references/` files.

Skill bodies keep a short spine in `SKILL.md` and move templates and checklists into
`references/`. Claude Code preloads `SKILL.md` but not the files it links, so the
repo-owned bundle manifest must not forbid reading them, and the materialized plugin
bundle must carry them. Ungated: needs no dotfiles tree.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from phase_loop_runtime import injection

PACKAGED = Path(injection.__file__).resolve().parent / "skills_bundle"


class ClaudeBundleReferenceReadsTest(unittest.TestCase):
    def test_manifest_keeps_the_reread_ban_but_allows_linked_references(self):
        text = injection._claude_bundle_manifest("plan", ("claude-plan-phase",))
        self.assertIn("Do not list or read `claude-bundle/plugin/skills/**`", text)
        self.assertIn("bundled `SKILL.md`, `assets/`, or `reflections/`", text)
        self.assertIn("a `references/` file that the active skill's `SKILL.md` links by relative path", text)
        # Negative control: references/ is no longer in the blanket ban list.
        self.assertNotIn("bundled `SKILL.md`, `references/`", text)

    def test_materialized_plugin_bundle_carries_linked_references(self):
        for action, skill in (("plan", "claude-plan-phase"), ("execute", "claude-execute-phase")):
            with self.subTest(skill=skill):
                source = PACKAGED / skill
                linked = sorted(p.name for p in (source / "references").glob("*.md"))
                self.assertTrue(linked, f"packaged {skill} ships no references/")
                bundle = SimpleNamespace(
                    product_action=action,
                    expected_skill_pack=(skill,),
                    skill_bundle_sha256="0" * 64,
                )
                with tempfile.TemporaryDirectory() as td, patch.object(
                    injection, "_resolve_pack_skill_dirs", return_value={skill: source}
                ):
                    result = injection.materialize_claude_plugin_bundle(
                        repo=Path(td), run_root=Path(td) / "run", prompt_bundle=bundle
                    )
                    copied = Path(result["plugin_dir"]) / "skills" / skill / "references"
                    self.assertEqual(sorted(p.name for p in copied.glob("*.md")), linked)

    def test_bundle_digest_changes_when_a_linked_reference_changes(self):
        def digest(skill_dir):
            with patch.object(
                injection, "_resolve_pack_skill_dirs", return_value={"claude-execute-phase": skill_dir}
            ):
                return injection._bundle_sha256(
                    repo=skill_dir,
                    harness_target="claude",
                    action="execute",
                    workflow_command="claude-execute-phase plan.md",
                    body="body",
                    expected_skill_pack=("claude-execute-phase",),
                )

        with tempfile.TemporaryDirectory() as td:
            skill_dir = Path(td) / "claude-execute-phase"
            shutil.copytree(PACKAGED / "claude-execute-phase", skill_dir)
            before = digest(skill_dir)
            self.assertEqual(digest(skill_dir), before)
            reference = skill_dir / "references" / "merge-and-verify.md"
            reference.write_text(reference.read_text() + "\nedited\n")
            self.assertNotEqual(digest(skill_dir), before)


if __name__ == "__main__":
    unittest.main()
