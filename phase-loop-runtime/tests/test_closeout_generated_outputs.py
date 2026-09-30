"""agent-harness#1139 — the closeout audit attributes ignored outputs by PROVENANCE.

Regression for the reported scenario: a passing Node/BAML-shaped phase
verification leaves ignored generated-SDK, dist and cache outputs plus the
harness's own handoff, all under collapsed ignore entries (`!! dist/`,
`!! .dev-skills/`), and the audit must pass. Everything the evidence does not
cover must still block.

The producers are real processes run by the runner's own verification
(`runner._run_execute_verification`). They are Python stand-ins for
`npm run bootstrap:baml` and `npm test`, so the suite needs no Node toolchain.
Each writes the same output shapes, and the second rewrites a file the first
produced (a shared `.cache/`), which is the cross-write join the design has to
tolerate.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime import generated_outputs, runner
from phase_loop_runtime.closeout_classifier import (
    DECLARED_OUTPUT,
    RUNNER_OWNED,
    UNKNOWN_IGNORED,
    audit_ignored_outputs,
    main,
)
from phase_loop_test_utils import commit_fixture_paths, make_repo, write_phase_plan

GITIGNORE = "/.dev-skills/\n.phase-loop/\n.baml/\n.cache/\nbaml_sdk/\ndist/\ngenerated/baml/\nnode_modules/\n"

GEN_BAML = """\
import json, pathlib
root = pathlib.Path('.')
schema = (root / 'baml_src' / 'main.baml').read_text()
for rel, text in {
    '.baml/state.json': json.dumps({'schema': len(schema)}),
    'baml_sdk/index.js': 'export const schema = ' + json.dumps(schema) + ';\\n',
    'generated/baml/types.ts': 'export type Extract = { name: string };\\n',
    '.cache/baml/fingerprint': 'baml:' + str(len(schema)) + '\\n',
}.items():
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
"""

BUILD = """\
import pathlib
root = pathlib.Path('.')
types = (root / 'generated' / 'baml' / 'types.ts').read_text()
(root / 'dist').mkdir(exist_ok=True)
(root / 'dist' / 'index.js').write_text('// built\\n' + types)
(root / 'dist' / 'index.js.map').write_text('{}\\n')
# The later producer rewrites an output of the earlier one.
(root / '.cache' / 'baml' / 'fingerprint').write_text('rebuilt\\n')
(root / '.cache' / 'tsbuildinfo').write_text('{}\\n')
"""

HANDOFF = """\
---
from: codex-execute-phase
timestamp: 2026-09-30T12:00:00Z
repo: example/app
repo_root: {repo}
branch: main
branch_slug: main
commit: 0000000
run_id: run-1
artifact: plans/phase-plan-v1-STATE.md
artifact_state: tracked
next_skill: codex-plan-phase
next_command: codex-plan-phase specs/phase-plans-v1.md
next_phase: CORE
---

# Handoff
"""


def _declaration(**overrides) -> dict:
    data = {
        "schema": generated_outputs.DECLARATION_SCHEMA,
        "producers": [
            {
                "name": "baml",
                "command": [sys.executable, "scripts/gen_baml.py"],
                "outputs": [".baml/**", "baml_sdk/**", "generated/baml/**", ".cache/baml/**"],
            },
            {
                "name": "build",
                "command": [sys.executable, "scripts/build.py"],
                "outputs": ["dist/**", ".cache/tsbuildinfo"],
            },
        ],
    }
    data.update(overrides)
    return data


class NodeBamlPhaseFixture:
    def __init__(self, tmp: Path, declaration: dict | None = None, commit_declaration: bool = True):
        self.repo = make_repo(tmp)
        repo = self.repo
        (repo / ".gitignore").write_text(GITIGNORE)
        (repo / "package.json").write_text('{"name": "app", "scripts": {"test": "node dist"}}\n')
        (repo / "baml_src").mkdir()
        (repo / "baml_src" / "main.baml").write_text("class Extract { name string }\n")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "gen_baml.py").write_text(GEN_BAML)
        (repo / "scripts" / "build.py").write_text(BUILD)
        self.roadmap = repo / "specs" / "phase-plans-v1.md"
        self.roadmap.parent.mkdir(exist_ok=True)
        self.roadmap.write_text("# Roadmap\n\n### Phase 0 - State (STATE)\n")
        self.plan = write_phase_plan(
            repo, "STATE", self.roadmap,
            body=(
                "# STATE\n\n## Verification\n"
                f"- `{sys.executable} scripts/gen_baml.py`\n"
                f"- `{sys.executable} scripts/build.py`\n"
            ),
        )
        paths = [repo / ".gitignore", repo / "package.json", repo / "baml_src" / "main.baml",
                 repo / "scripts" / "gen_baml.py", repo / "scripts" / "build.py",
                 self.roadmap, self.plan]
        decl_path = repo / generated_outputs.DECLARATION_PATH
        decl_path.write_text(json.dumps(declaration or _declaration(), indent=2) + "\n")
        if commit_declaration:
            paths.append(decl_path)
        commit_fixture_paths(repo, "seed", *paths)

    def verify(self) -> dict:
        run_dir = self.repo / ".phase-loop" / "runs" / "exec-state"
        run_dir.mkdir(parents=True, exist_ok=True)
        result = runner._run_execute_verification(
            repo=self.repo, roadmap=self.roadmap, plan=self.plan,
            artifacts={"root": run_dir}, phase_alias="STATE",
        )
        return result

    def write_handoff(self, text: str | None = None, skill: str = "codex-execute-phase") -> Path:
        path = self.repo / ".dev-skills" / "handoffs" / skill / "latest.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HANDOFF.format(repo=self.repo) if text is None else text)
        return path


class ReportedScenarioTest(unittest.TestCase):
    def test_passing_node_baml_verification_then_closeout_audit_passes(self):
        """The acceptance regression: verification passes, outputs are left
        behind under collapsed ignore entries, and the audit exits 0."""

        with tempfile.TemporaryDirectory() as td:
            fx = NodeBamlPhaseFixture(Path(td))
            verification = fx.verify()
            self.assertTrue(verification.get("ok"), verification)
            fx.write_handoff()
            porcelain = subprocess.run(
                ["git", "-C", str(fx.repo), "status", "--porcelain", "--ignored=matching",
                 "--untracked-files=all"], capture_output=True, text=True, check=True,
            ).stdout
            # The reported shape: collapsed directory entries, not files.
            for entry in ("!! .dev-skills/", "!! dist/", "!! baml_sdk/", "!! .cache/", "!! .baml/"):
                self.assertIn(entry, porcelain.splitlines())

            result = audit_ignored_outputs(fx.repo)
            self.assertFalse(result["blocks"], result)
            self.assertEqual(result[UNKNOWN_IGNORED], [])
            self.assertIn(".dev-skills/handoffs/codex-execute-phase/latest.md", result[RUNNER_OWNED])
            self.assertEqual(
                sorted(result[DECLARED_OUTPUT]),
                sorted([".baml/state.json", ".cache/baml/fingerprint", ".cache/tsbuildinfo",
                        "baml_sdk/index.js", "dist/index.js", "dist/index.js.map",
                        "generated/baml/types.ts"]),
            )
            self.assertEqual(main(["--repo", str(fx.repo)]), 0)

    def test_the_cli_records_for_a_skill_driven_phase(self):
        """No runner: `--record-outputs` runs the declared producers itself."""

        with tempfile.TemporaryDirectory() as td:
            fx = NodeBamlPhaseFixture(Path(td))
            # The executor ran the producers by hand: outputs exist, evidence does not.
            for script in ("scripts/gen_baml.py", "scripts/build.py"):
                subprocess.run([sys.executable, script], cwd=fx.repo, check=True)
            self.assertEqual(main(["--repo", str(fx.repo)]), 1)
            self.assertEqual(main(["--repo", str(fx.repo), "--record-outputs"]), 0)
            record = generated_outputs.load_record(fx.repo)
            self.assertEqual(record["source"], "closeout-audit")


class StillFailClosedTest(unittest.TestCase):
    def _verified(self, td: str, **kwargs) -> NodeBamlPhaseFixture:
        fx = NodeBamlPhaseFixture(Path(td), **kwargs)
        self.assertTrue(fx.verify().get("ok"))
        return fx

    def _unknown(self, fx: NodeBamlPhaseFixture) -> dict:
        result = audit_ignored_outputs(fx.repo)
        self.assertTrue(result["blocks"], result)
        self.assertEqual(main(["--repo", str(fx.repo)]), 1)
        return result

    def test_a_hand_placed_file_inside_a_declared_directory_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            (fx.repo / "dist" / "stray.js").write_text("not produced\n")
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], ["dist/stray.js"])
            self.assertIn("did not leave behind", result["unknown_reasons"]["dist/stray.js"])

    def test_a_generated_file_edited_after_the_producer_ran_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            (fx.repo / "baml_sdk" / "index.js").write_text("tampered\n")
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], ["baml_sdk/index.js"])
            self.assertIn("changed after", result["unknown_reasons"]["baml_sdk/index.js"])

    def test_an_undeclared_ignored_directory_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            # `.cache/other` is under an ignored dir but outside every declared glob.
            (fx.repo / ".cache" / "other").write_text("x\n")
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], [".cache/other"])

    def test_outputs_of_a_failed_producer_block(self):
        with tempfile.TemporaryDirectory() as td:
            fx = NodeBamlPhaseFixture(Path(td))
            (fx.repo / "scripts" / "build.py").write_text(BUILD + "raise SystemExit(3)\n")
            self.assertFalse(fx.verify().get("ok"))
            result = self._unknown(fx)
            self.assertIn("dist/index.js", result[UNKNOWN_IGNORED])
            self.assertNotIn("baml_sdk/index.js", result[UNKNOWN_IGNORED])

    def test_an_uncommitted_declaration_is_not_honoured(self):
        with tempfile.TemporaryDirectory() as td:
            fx = NodeBamlPhaseFixture(Path(td), commit_declaration=False)
            # Staged is not committed: only HEAD's declaration counts.
            subprocess.run(["git", "add", generated_outputs.DECLARATION_PATH], cwd=fx.repo, check=True)
            self.assertTrue(fx.verify().get("ok"))
            self.assertIsNone(generated_outputs.load_record(fx.repo))
            result = self._unknown(fx)
            self.assertIn("dist/index.js", result[UNKNOWN_IGNORED])

    def test_a_record_for_an_older_declaration_does_not_count(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            decl = fx.repo / generated_outputs.DECLARATION_PATH
            decl.write_text(json.dumps(_declaration(), indent=4) + "\n")
            commit_fixture_paths(fx.repo, "reformat declaration", decl)
            result = self._unknown(fx)
            self.assertIn("predates", result["unknown_reasons"]["dist/index.js"])

    def test_an_unmarked_file_under_the_handoff_root_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            fx.write_handoff("from: codex-execute-phase\n")
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], [".dev-skills/handoffs/codex-execute-phase/latest.md"])

    def test_a_handoff_missing_contract_keys_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            fx.write_handoff("---\nfrom: codex-execute-phase\n---\n")
            result = self._unknown(fx)
            self.assertIn("missing", next(iter(result["unknown_reasons"].values())))

    def test_an_unenumerable_ignored_directory_fails_closed(self):
        from unittest.mock import patch

        from phase_loop_runtime import closeout_classifier

        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            with patch.object(closeout_classifier, "_ignored_members", return_value=None):
                result = audit_ignored_outputs(fx.repo)
            self.assertTrue(result["blocks"])
            self.assertIn("dist/", result[UNKNOWN_IGNORED])

    def test_a_record_attributing_a_file_to_a_non_covering_producer_does_not_count(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            record_path = fx.repo / generated_outputs.RECORD_RELPATH
            record = json.loads(record_path.read_text())
            record["files"]["dist/index.js"]["producer"] = "baml"  # baml's globs do not cover dist/
            record_path.write_text(json.dumps(record))
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], ["dist/index.js"])

    def test_a_handoff_whose_from_disagrees_with_its_directory_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            fx.write_handoff(HANDOFF.format(repo=fx.repo).replace(
                "from: codex-execute-phase", "from: codex-plan-phase"))
            result = self._unknown(fx)
            self.assertIn("does not match", next(iter(result["unknown_reasons"].values())))

    def test_a_marked_handoff_for_a_skill_the_harness_does_not_ship_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            fx.write_handoff(HANDOFF.format(repo=fx.repo).replace(
                "from: codex-execute-phase", "from: codex-exfiltrate"), skill="codex-exfiltrate")
            self._unknown(fx)

    def test_other_files_under_dev_skills_block(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            fx.write_handoff()
            (fx.repo / ".dev-skills" / "notes.txt").write_text("x\n")
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], [".dev-skills/notes.txt"])


class DeclarationBoundsTest(unittest.TestCase):
    def _parse(self, outputs):
        return generated_outputs.parse_declaration(json.dumps(_declaration(producers=[
            {"name": "p", "command": "npm run build", "outputs": outputs}])))

    def test_unbounded_or_reserved_globs_are_rejected(self):
        for glob in ("**", "*", "**/dist/**", "*.js", "/dist/**", "../x/**", "dist/../../x",
                     ".phase-loop/**", ".dev-skills/**", ".git/**", ".codex/phase-loop/**", " dist/**"):
            with self.assertRaises(generated_outputs.DeclarationError, msg=glob):
                self._parse([glob])

    def test_bounded_globs_are_accepted(self):
        decl = self._parse(["dist/**", "generated/baml/**", ".cache/tsbuildinfo"])
        self.assertEqual(decl.producers[0].command, ("npm", "run", "build"))

    def test_an_invalid_committed_declaration_cannot_evaluate(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _declaration()
            bad["producers"][0]["outputs"] = ["**"]
            fx = NodeBamlPhaseFixture(Path(td), declaration=bad)
            result = audit_ignored_outputs(fx.repo)
            self.assertTrue(result["probe_failed"] and result["blocks"])
            self.assertEqual(main(["--repo", str(fx.repo)]), 2)

    def test_glob_matching_is_segment_wise(self):
        self.assertTrue(generated_outputs.glob_matches("dist/**", "dist/a/b.js"))
        self.assertTrue(generated_outputs.glob_matches("dist/*.js", "dist/a.js"))
        self.assertFalse(generated_outputs.glob_matches("dist/*.js", "dist/a/b.js"))
        self.assertFalse(generated_outputs.glob_matches("dist/**", "distx/a.js"))


if __name__ == "__main__":
    unittest.main()
