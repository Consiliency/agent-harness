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
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

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
commit: {commit}
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
                # Overlaps baml's `.cache/baml/**`: attribution follows whoever WROTE the file.
                "outputs": ["dist/**", ".cache/**"],
            },
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def _poisoned_phase_environment(monkeypatch):
    """The audit's phase identity is ONLY an explicit alias. Both environment keys name
    a phase no test uses, so any resolver that consulted them would bind the wrong
    phase and turn these tests red (agent-harness#1189 round 5)."""
    monkeypatch.setenv("PHASE_LOOP_PHASE_ALIAS", "ENV-NOT-AN-IDENTITY")
    monkeypatch.setenv("PHASE_ALIAS", "ENV-NOT-AN-IDENTITY")


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
        # A STALE state file naming another phase: phase identity must never be read
        # from it (the runner writes it only after a loop ends; agent-harness#1189 r3).
        state = self.repo / ".phase-loop" / "state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"current_phase": "STALE"}))
        # The phase this executor was dispatched for; tests pass it explicitly.
        self.phase = "STATE"

    def set_phase(self, alias: str) -> None:
        """The alias the runner's prompt names on the audit command (`--phase`)."""
        self.phase = alias

    def verify(self) -> dict:
        run_dir = self.repo / ".phase-loop" / "runs" / "exec-state"
        run_dir.mkdir(parents=True, exist_ok=True)
        result = runner._run_execute_verification(
            repo=self.repo, roadmap=self.roadmap, plan=self.plan,
            artifacts={"root": run_dir}, phase_alias="STATE",
        )
        return result

    def handoff_text(self) -> str:
        commit = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        return HANDOFF.format(repo=self.repo, commit=commit)

    def write_handoff(self, text: str | None = None, skill: str = "codex-execute-phase") -> Path:
        path = self.repo / ".dev-skills" / "handoffs" / skill / "latest.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.handoff_text() if text is None else text)
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

            result = audit_ignored_outputs(fx.repo, fx.phase)
            self.assertFalse(result["blocks"], result)
            self.assertEqual(result[UNKNOWN_IGNORED], [])
            self.assertIn(".dev-skills/handoffs/codex-execute-phase/latest.md", result[RUNNER_OWNED])
            self.assertEqual(
                sorted(result[DECLARED_OUTPUT]),
                sorted([".baml/state.json", ".cache/baml/fingerprint", ".cache/tsbuildinfo",
                        "baml_sdk/index.js", "dist/index.js", "dist/index.js.map",
                        "generated/baml/types.ts"]),
            )
            self.assertEqual(main(["--repo", str(fx.repo), "--phase", fx.phase]), 0)

    def test_the_cli_records_for_a_skill_driven_phase(self):
        """No runner: `--record-outputs` runs the declared producers itself."""

        with tempfile.TemporaryDirectory() as td:
            fx = NodeBamlPhaseFixture(Path(td))
            # The executor ran the producers by hand: outputs exist, evidence does not.
            for script in ("scripts/gen_baml.py", "scripts/build.py"):
                subprocess.run([sys.executable, script], cwd=fx.repo, check=True)
            self.assertEqual(main(["--repo", str(fx.repo), "--phase", fx.phase]), 1)
            self.assertEqual(main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]), 0)
            record = generated_outputs.load_record(fx.repo)
            self.assertEqual({i["source"] for i in record["invocations"]}, {"closeout-audit"})


class StillFailClosedTest(unittest.TestCase):
    def _verified(self, td: str, **kwargs) -> NodeBamlPhaseFixture:
        fx = NodeBamlPhaseFixture(Path(td), **kwargs)
        self.assertTrue(fx.verify().get("ok"))
        return fx

    def _unknown(self, fx: NodeBamlPhaseFixture) -> dict:
        result = audit_ignored_outputs(fx.repo, fx.phase)
        self.assertTrue(result["blocks"], result)
        self.assertEqual(main(["--repo", str(fx.repo), "--phase", fx.phase]), 1)
        return result

    def test_a_hand_placed_file_inside_a_declared_directory_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            (fx.repo / "dist" / "stray.js").write_text("not produced\n")
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], ["dist/stray.js"])
            self.assertIn("no recorded producer invocation wrote", result["unknown_reasons"]["dist/stray.js"])

    def test_a_file_placed_under_a_declared_glob_BEFORE_the_run_blocks(self):
        """A declaration is not a licence for whatever already sits in `dist/`: only
        what the run itself created or rewrote is attributed to the producer."""

        with tempfile.TemporaryDirectory() as td:
            fx = NodeBamlPhaseFixture(Path(td))
            (fx.repo / "dist").mkdir()
            (fx.repo / "dist" / "planted.js").write_text("placed before the producer ran\n")
            self.assertTrue(fx.verify().get("ok"))
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], ["dist/planted.js"])

    def test_an_untouched_output_carries_forward_from_the_previous_record(self):
        """Incremental producers skip unchanged outputs; an output the previous record
        (same declaration) attributed, still at its digest, stays attributed."""

        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            incremental = BUILD.replace("(root / 'dist' / 'index.js.map').write_text('{}\\n')\n", "")
            self.assertNotIn("index.js.map", incremental)
            (fx.repo / "scripts" / "build.py").write_text(incremental)
            self.assertTrue(fx.verify().get("ok"))
            result = audit_ignored_outputs(fx.repo, fx.phase)
            self.assertFalse(result["blocks"], result)
            self.assertIn("dist/index.js.map", result[DECLARED_OUTPUT])

    def test_a_generated_file_edited_after_the_producer_ran_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            (fx.repo / "baml_sdk" / "index.js").write_text("tampered\n")
            result = self._unknown(fx)
            self.assertEqual(result[UNKNOWN_IGNORED], ["baml_sdk/index.js"])
            self.assertIn("changed after", result["unknown_reasons"]["baml_sdk/index.js"])
            # Actionable: re-recording re-runs the producer, which regenerates the file
            # rather than laundering the edit.
            self.assertIn("--record-outputs", result["unknown_reasons"]["baml_sdk/index.js"])

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
                result = audit_ignored_outputs(fx.repo, fx.phase)
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
            fx.write_handoff(fx.handoff_text().replace(
                "from: codex-execute-phase", "from: codex-plan-phase"))
            result = self._unknown(fx)
            self.assertIn("does not match", next(iter(result["unknown_reasons"].values())))

    def test_a_marked_handoff_for_a_skill_the_harness_does_not_ship_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            fx = self._verified(td)
            fx.write_handoff(fx.handoff_text().replace(
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
            result = audit_ignored_outputs(fx.repo, fx.phase)
            self.assertTrue(result["probe_failed"] and result["blocks"])
            self.assertEqual(main(["--repo", str(fx.repo), "--phase", fx.phase]), 2)

    def test_glob_matching_is_segment_wise(self):
        self.assertTrue(generated_outputs.glob_matches("dist/**", "dist/a/b.js"))
        self.assertTrue(generated_outputs.glob_matches("dist/*.js", "dist/a.js"))
        self.assertFalse(generated_outputs.glob_matches("dist/*.js", "dist/a/b.js"))
        self.assertFalse(generated_outputs.glob_matches("dist/**", "distx/a.js"))


if __name__ == "__main__":
    unittest.main()


# --- round-1 board falsifiers (agent-harness#1189), kept verbatim in substance -------


def _audit_blocks_on(fx, path):
    result = audit_ignored_outputs(fx.repo, fx.phase)
    assert result["blocks"], result
    assert path in result[UNKNOWN_IGNORED], result
    assert main(["--repo", str(fx.repo), "--phase", fx.phase]) == 1
    return result


def test_declared_output_symlink_blocks(tmp_path):
    """codex F001 / grok F1: a producer-created symlink under a declared glob."""

    fx = NodeBamlPhaseFixture(tmp_path)
    target = tmp_path / "input.txt"
    target.write_text("before the producer\n")
    script = fx.repo / "scripts/build.py"
    script.write_text(BUILD + "(root / 'dist' / 'borrowed.js').symlink_to('../../input.txt')\n")
    commit_fixture_paths(fx.repo, "producer creates a symlink", script)
    assert fx.verify()["ok"]
    assert (fx.repo / "dist/borrowed.js").is_symlink()
    target.write_text("changed after the producer\n")
    _audit_blocks_on(fx, "dist/borrowed.js")
    assert "dist/borrowed.js" not in generated_outputs.load_record(fx.repo)["files"]


def test_a_file_reached_through_a_symlinked_directory_blocks(tmp_path):
    """The containment check covers every path component, not just the leaf."""

    fx = NodeBamlPhaseFixture(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    script = fx.repo / "scripts/build.py"
    script.write_text(
        BUILD + "import os\nos.symlink(%r, str(root / 'dist' / 'linked'))\n"
        "(root / 'dist' / 'linked' / 'x.js').write_text('x')\n" % str(outside)
    )
    commit_fixture_paths(fx.repo, "producer links a directory", script)
    assert fx.verify()["ok"]
    assert generated_outputs.file_identity(fx.repo, "dist/linked/x.js") is None
    _audit_blocks_on(fx, "dist/linked")


def test_undeclared_process_cannot_borrow_producer_provenance(tmp_path):
    """codex F002: an undeclared verification command writes under a declared glob."""

    fx = NodeBamlPhaseFixture(tmp_path)
    script = fx.repo / "scripts/unrelated.py"
    script.write_text(
        "from pathlib import Path\n"
        "Path('dist').mkdir(exist_ok=True)\n"
        "Path('dist/stray.js').write_text('unrelated output\\n')\n"
    )
    fx.plan.write_text(fx.plan.read_text().replace(
        "## Verification\n",
        f"## Verification\n- `{sys.executable} scripts/unrelated.py`\n",
    ))
    commit_fixture_paths(fx.repo, "add an undeclared verification command", script, fx.plan)
    assert fx.verify()["ok"]
    _audit_blocks_on(fx, "dist/stray.js")


def test_previous_phase_record_cannot_satisfy_current_phase(tmp_path):
    """codex F003: CORE never runs the producers; STATE's record must not count."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    previous = generated_outputs.load_record(fx.repo)
    assert {i["run_id"] for i in previous["invocations"]} == {"exec-state"}
    fx.roadmap.write_text(fx.roadmap.read_text() + "\n### Phase 1 - Core (CORE)\n")
    script = fx.repo / "scripts/core.py"
    script.write_text("print('CORE passed without running the declared producers')\n")
    plan = write_phase_plan(
        fx.repo, "CORE", fx.roadmap,
        body=f"# CORE\n\n## Verification\n- `{sys.executable} scripts/core.py`\n",
    )
    commit_fixture_paths(fx.repo, "next phase", script, plan, fx.roadmap)
    run_dir = fx.repo / ".phase-loop/runs/exec-core"
    run_dir.mkdir(parents=True)
    verification = runner._run_execute_verification(
        repo=fx.repo, roadmap=fx.roadmap, plan=plan,
        artifacts={"root": run_dir}, phase_alias="CORE",
    )
    assert verification["ok"], verification
    result = _audit_blocks_on(fx, "dist/index.js")
    assert "different commit" in result["unknown_reasons"]["dist/index.js"]


def test_the_next_phase_passes_once_it_reruns_the_deterministic_producers(tmp_path):
    """The positive half of F003 and the consumer flow C1 prescribes. A new commit
    and byte-identical regeneration still pass, because the producers ran in THIS
    phase (`--record-outputs`)."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    marker = fx.repo / "CORE.md"
    marker.write_text("next phase\n")
    commit_fixture_paths(fx.repo, "next phase", marker)
    fx.write_handoff()
    assert main(["--repo", str(fx.repo), "--phase", fx.phase]) == 1          # stale evidence alone blocks
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]) == 0


def test_metadata_only_touch_launders_a_planted_file(tmp_path):
    """Claude C2: a producer that only chmods a planted file has not written it."""

    fx = NodeBamlPhaseFixture(tmp_path)
    (fx.repo / "dist").mkdir()
    (fx.repo / "dist" / "planted.js").write_text("placed before the producer ran\n")
    script = fx.repo / "scripts/build.py"
    script.write_text(BUILD + "import os\nfor p in (root / 'dist').iterdir():\n    os.chmod(p, 0o644)\n")
    commit_fixture_paths(fx.repo, "build normalises modes", script)
    assert fx.verify()["ok"]
    _audit_blocks_on(fx, "dist/planted.js")


def test_a_partial_rerun_keeps_the_other_producers_evidence(tmp_path):
    """Claude C3: a repair turn re-running only `build` keeps `baml`'s evidence at
    the same commit."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    recorder = generated_outputs.ProducerRecorder.for_repo(fx.repo)
    build = next(p for p in recorder.declaration.producers if p.name == "build")
    assert recorder.run(build) == 0
    recorder.write(source="closeout-audit", run_id=None, phase_alias=fx.phase)
    result = audit_ignored_outputs(fx.repo, fx.phase)
    assert not result["blocks"], result
    assert "baml_sdk/index.js" in result[DECLARED_OUTPUT]


def test_overlapping_globs_attribute_to_the_writer_not_declaration_order(tmp_path):
    """grok F2: `.cache/baml/fingerprint` is covered by both producers; `build`
    rewrote it last, so it is build's, whatever the declaration order."""

    for order in (None, "reversed"):
        with tempfile.TemporaryDirectory() as td:
            decl = _declaration()
            if order:
                decl["producers"].reverse()
            fx = NodeBamlPhaseFixture(Path(td), declaration=decl)
            assert fx.verify()["ok"]
            files = generated_outputs.load_record(fx.repo)["files"]
            assert files[".cache/baml/fingerprint"]["producer"] == "build", order


def test_declaration_rejects_unknown_keys_and_shell_syntax():
    """Claude C4: v1 is closed; `command` is an argv, not a shell line."""

    base = _declaration()
    for mutate in (
        lambda d: d.update(extra=1),
        lambda d: d["producers"][0].update(cwd="pkg"),
        lambda d: d["producers"][0].update(command="npm ci && npm run build"),
        lambda d: d["producers"][0].update(command="npm run build; rm -rf x"),
        lambda d: d["producers"][0].update(command=["npm", "run", "build", "|", "tee"]),
    ):
        data = json.loads(json.dumps(base))
        mutate(data)
        try:
            generated_outputs.parse_declaration(json.dumps(data))
        except generated_outputs.DeclarationError:
            continue
        raise AssertionError(f"accepted: {data}")


def test_reserved_roots_are_matched_case_insensitively():
    """grok F3."""

    for glob in (".GIT/**", ".Phase-Loop/**", ".DEV-SKILLS/x"):
        try:
            generated_outputs.parse_declaration(json.dumps(_declaration(producers=[
                {"name": "p", "command": "make", "outputs": [glob]}])))
        except generated_outputs.DeclarationError:
            continue
        raise AssertionError(glob)


def test_a_handoff_for_another_repo_or_commit_blocks(tmp_path):
    """Claude C5: the handoff contract is bound to THIS repo and a commit in it."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    good = fx.handoff_text()
    for bad, why in (
        (good.replace(f"repo_root: {fx.repo}", "repo_root: /somewhere/else"), "repo_root"),
        (good.replace(good.split("commit: ")[1].split("\n")[0], "deadbeefdeadbeef"), "commit"),
    ):
        fx.write_handoff(bad)
        result = _audit_blocks_on(fx, ".dev-skills/handoffs/codex-execute-phase/latest.md")
        assert why in next(iter(result["unknown_reasons"].values()))
    fx.write_handoff(good)
    assert main(["--repo", str(fx.repo), "--phase", fx.phase]) == 0


def test_a_recording_failure_is_surfaced_not_swallowed(tmp_path):
    """Claude C6: the runner reports a recording failure in its summary."""

    from unittest.mock import patch

    fx = NodeBamlPhaseFixture(tmp_path)
    with patch.object(generated_outputs.ProducerRecorder, "write", side_effect=OSError("disk full")):
        summary = fx.verify()
    assert summary["ok"], summary                      # evidence never changes the outcome
    assert "disk full" in summary["generated_outputs_record_error"]
    _audit_blocks_on(fx, "dist/index.js")


def test_record_outputs_is_a_no_op_without_a_declaration(tmp_path):
    """C1: executors pass `--record-outputs` in EVERY repo, so it must not fail
    where nothing is declared."""

    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text(".phase-loop/\n")
    commit_fixture_paths(repo, "seed", repo / ".gitignore")
    assert main(["--repo", str(repo), "--record-outputs"]) == 0


def test_a_partial_rerun_after_a_commit_does_not_inherit_the_old_phase(tmp_path):
    """F003 through the merge path: at a NEW commit, re-running only `build` must not
    carry `baml`'s earlier-phase entries into the fresh record."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    marker = fx.repo / "CORE.md"
    marker.write_text("next phase\n")
    commit_fixture_paths(fx.repo, "next phase", marker)
    recorder = generated_outputs.ProducerRecorder.for_repo(fx.repo)
    build = next(p for p in recorder.declaration.producers if p.name == "build")
    assert recorder.run(build) == 0
    recorder.write(source="closeout-audit", run_id=None, phase_alias=fx.phase)
    _audit_blocks_on(fx, "baml_sdk/index.js")


# --- round-2 board falsifiers (agent-harness#1189 at 68c5abf8) ------------------------


def test_touch_only_does_not_credit_a_planted_file(tmp_path):
    """codex r2 F001 (verbatim): a producer that only moves a planted file's mtime
    has not written it."""

    fx = NodeBamlPhaseFixture(tmp_path)
    planted = fx.repo / "dist/planted.js"
    planted.parent.mkdir()
    planted.write_text("never written by the producer\n")
    before = planted.read_bytes()
    script = fx.repo / "scripts/build.py"
    script.write_text(
        BUILD + "import os\n"
        "p = root / 'dist/planted.js'\n"
        "s = p.stat()\n"
        "os.utime(p, ns=(s.st_atime_ns, s.st_mtime_ns + 1000000000))\n"
    )
    commit_fixture_paths(fx.repo, "producer normalizes output timestamps", script)
    assert fx.verify()["ok"]
    assert planted.read_bytes() == before
    _audit_blocks_on(fx, "dist/planted.js")


def test_next_phase_at_same_head_requires_its_own_producer_invocation(tmp_path):
    """codex r2 F002, plus Claude N1, at the identity level: the CORE executor runs the
    audit with `--phase CORE`, as its prompt prescribes (see
    `test_child_audit_uses_the_live_runner_phase` for the real run_loop path)."""

    fx = NodeBamlPhaseFixture(tmp_path)
    fx.roadmap.write_text(fx.roadmap.read_text() + "\n### Phase 1 - Core (CORE)\n")
    core = fx.repo / "scripts/core.py"
    core.write_text("print('CORE checks passed')\n")
    plan = write_phase_plan(
        fx.repo, "CORE", fx.roadmap,
        body=f"# CORE\n\n## Verification\n- `{sys.executable} scripts/core.py`\n",
    )
    commit_fixture_paths(fx.repo, "plan both phases in advance", core, plan, fx.roadmap)
    assert fx.verify()["ok"]
    head = generated_outputs.head_commit(fx.repo)
    fx.set_phase("CORE")
    run_dir = fx.repo / ".phase-loop/runs/exec-core"
    run_dir.mkdir(parents=True)
    summary = runner._run_execute_verification(
        repo=fx.repo, roadmap=fx.roadmap, plan=plan,
        artifacts={"root": run_dir}, phase_alias="CORE",
    )
    assert summary["ok"], summary
    assert generated_outputs.head_commit(fx.repo) == head
    result = _audit_blocks_on(fx, "dist/index.js")
    assert "phase 'STATE', not 'CORE'" in result["unknown_reasons"]["dist/index.js"]
    # ...and an explicit `--phase` is honoured the same way.
    fx.set_phase("STATE")
    assert main(["--repo", str(fx.repo), "--phase", "CORE"]) == 1
    assert main(["--repo", str(fx.repo), "--phase", "STATE"]) == 0


def test_record_cannot_rebind_old_invocations_to_a_new_head(tmp_path):
    """codex r2 F003 (verbatim): a commit between observation and persistence."""

    fx = NodeBamlPhaseFixture(tmp_path)
    recorder = generated_outputs.ProducerRecorder.for_repo(fx.repo)
    old_head = generated_outputs.head_commit(fx.repo)
    for producer in recorder.declaration.producers:
        assert recorder.run(producer) == 0
    schema = fx.repo / "baml_src/main.baml"
    schema.write_text("class Extract { changed string }\n")
    commit_fixture_paths(fx.repo, "change producer input before evidence is persisted", schema)
    assert generated_outputs.head_commit(fx.repo) != old_head
    recorder.write(source="runner-verification", run_id="exec-state", phase_alias="STATE")
    result = audit_ignored_outputs(fx.repo, fx.phase)
    assert "dist/index.js" in result["unknown_ignored"], result
    assert main(["--repo", str(fx.repo), "--phase", fx.phase]) == 1
    assert any("HEAD moved" in error for error in recorder.errors)


def test_record_outputs_rebuild_moves_planted_and_orphaned_files_aside(tmp_path):
    """Claude N2 and the CLI half of F001: `--record-outputs` is a CLEAN observed
    rebuild. Byte-identical regeneration earns provenance; a planted or orphaned file
    is moved aside (never deleted) instead of riding along."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]) == 0
    orphan = fx.repo / "dist" / "old.js"           # a file the build no longer emits
    orphan.write_text("left over from an earlier build\n")
    assert main(["--repo", str(fx.repo), "--phase", fx.phase]) == 1
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]) == 0
    assert not orphan.exists()
    displaced = sorted((fx.repo / generated_outputs.DISPLACED_RELDIR).glob("*/dist/old.js"))
    assert displaced and displaced[-1].read_text() == "left over from an earlier build\n"


def test_a_runner_rerun_of_byte_identical_outputs_is_not_credited_unless_recorded(tmp_path):
    """The flip side of F001 on the runner path: deterministic regeneration over files
    no record attributes earns nothing (only a record carries forward)."""

    fx = NodeBamlPhaseFixture(tmp_path)
    for script in ("scripts/gen_baml.py", "scripts/build.py"):
        subprocess.run([sys.executable, script], cwd=fx.repo, check=True)   # by hand
    assert fx.verify()["ok"]
    _audit_blocks_on(fx, "dist/index.js")


def test_same_producer_twice_in_one_recording_keeps_first_write(tmp_path):
    """Claude N4: a second, incremental invocation keeps the first one's writes."""

    fx = NodeBamlPhaseFixture(tmp_path)
    recorder = generated_outputs.ProducerRecorder.for_repo(fx.repo)
    baml, build = recorder.declaration.producers
    assert recorder.run(baml) == 0
    assert recorder.run(build) == 0
    assert recorder.run(build) == 0                 # rewrites identical bytes: no new write
    recorder.write(source="closeout-audit", run_id=None, phase_alias=fx.phase)
    result = audit_ignored_outputs(fx.repo, fx.phase)
    assert not result["blocks"], result
    assert "dist/index.js" in result[DECLARED_OUTPUT]


def test_shell_syntax_is_rejected_inside_tokens_too():
    """Claude N5: `a&&b`, `2>/dev/null` and a leading `NAME=` assignment."""

    for command in ("npm run build&&rm -rf x", "npm run build 2>/dev/null", "FOO=1 npm run build",
                    "npm run build;x", "echo `id`", "echo $(id)"):
        try:
            generated_outputs.parse_declaration(json.dumps(_declaration(producers=[
                {"name": "p", "command": command, "outputs": ["dist/**"]}])))
        except generated_outputs.DeclarationError:
            continue
        raise AssertionError(command)


def test_record_outputs_bounds_a_hanging_producer(tmp_path, monkeypatch):
    """Claude N6 / grok N4: a producer that hangs is killed and counts as failed."""

    decl = _declaration()
    decl["producers"][1]["command"] = [sys.executable, "-c", "import time; time.sleep(30)"]
    fx = NodeBamlPhaseFixture(tmp_path, declaration=decl)
    monkeypatch.setenv("PHASE_LOOP_VERIFY_TIMEOUT_SECONDS", "1")
    record = generated_outputs.run_declared_producers(fx.repo, phase=fx.phase)
    codes = {i["producer"]: i["exit_code"] for i in record["invocations"]}
    assert codes == {"baml": 0, "build": 124}


def test_the_handoff_commit_is_read_from_the_frontmatter_only(tmp_path):
    """Claude N7 / grok N5: a valid `commit:` in the BODY cannot rescue a bad one."""

    fx = NodeBamlPhaseFixture(tmp_path)
    good = fx.handoff_text()
    sha = good.split("commit: ")[1].split("\n")[0]
    fx.write_handoff(good.replace(f"commit: {sha}", "commit: not-a-sha") + f"\ncommit: {sha}\n")
    result = _audit_blocks_on(fx, ".dev-skills/handoffs/codex-execute-phase/latest.md")
    assert "commit" in next(iter(result["unknown_reasons"].values()))


def test_a_corrupt_record_entry_is_a_typed_refusal_not_a_crash(tmp_path):
    """grok r2: a non-dict `files` entry is treated as absent (blocks), and
    `--record-outputs` over it does not raise."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    record_path = fx.repo / generated_outputs.RECORD_RELPATH
    record = json.loads(record_path.read_text())
    record["files"]["dist/index.js"] = "garbage"
    record_path.write_text(json.dumps(record))
    result = _audit_blocks_on(fx, "dist/index.js")
    assert "no recorded producer invocation wrote" in result["unknown_reasons"]["dist/index.js"]
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]) == 0


def test_the_clean_rebuild_never_moves_tracked_or_unignored_files(tmp_path):
    """Displacement is limited to IGNORED untracked entries: a tracked file, or an
    untracked file the ownership contract grades, under a declared glob stays put."""

    fx = NodeBamlPhaseFixture(tmp_path)
    (fx.repo / ".gitignore").write_text(GITIGNORE.replace("dist/\n", "dist/*.js\n"))
    tracked = fx.repo / "dist" / "README.txt"
    tracked.parent.mkdir()
    tracked.write_text("tracked\n")
    commit_fixture_paths(fx.repo, "track a file under dist", fx.repo / ".gitignore", tracked)
    untracked = fx.repo / "dist" / "notes.md"
    untracked.write_text("untracked, not ignored\n")
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]) == 0
    assert tracked.read_text() == "tracked\n" and untracked.exists()


def test_a_partial_rerun_in_another_phase_at_the_same_head_starts_fresh(tmp_path):
    """F002 through the merge path: CORE re-running only `build` at STATE's commit
    must not inherit STATE's `baml` entries."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    fx.set_phase("CORE")
    recorder = generated_outputs.ProducerRecorder.for_repo(fx.repo)
    build = next(p for p in recorder.declaration.producers if p.name == "build")
    assert recorder.run(build) == 0
    record = recorder.write(source="closeout-audit", run_id=None, phase_alias=fx.phase)
    assert record["phase"] == "CORE"
    assert "baml_sdk/index.js" not in record["files"]
    _audit_blocks_on(fx, "baml_sdk/index.js")


def test_an_invocation_that_straddles_a_commit_is_not_recorded(tmp_path):
    """F003, the other half: HEAD must be the same before and after the invocation."""

    fx = NodeBamlPhaseFixture(tmp_path)
    recorder = generated_outputs.ProducerRecorder.for_repo(fx.repo)
    baml, _build = recorder.declaration.producers
    # Only ONE invocation, so nothing but its own straddle can refuse the write.
    token = recorder.before(baml.command)
    subprocess.run([sys.executable, "scripts/gen_baml.py"], cwd=fx.repo, check=True)
    marker = fx.repo / "MID.md"
    marker.write_text("landed mid-invocation\n")
    commit_fixture_paths(fx.repo, "commit during the build", marker)
    recorder.after(token, 0)
    assert recorder.write(source="closeout-audit", run_id=None, phase_alias=fx.phase) is None
    assert any("HEAD moved" in error for error in recorder.errors)


# --- rounds 3-5: the phase identity is EXPLICIT (agent-harness#1189) -------------------
#
# Round 5 replaced the launcher's environment stamp: every runner prompt that closes out
# writes `--phase <alias>` literally (prompts.closeout_audit_instruction), and the audit
# resolves its identity from that argument alone.


def test_next_phase_at_same_head_verbatim_with_no_phase_identity(tmp_path):
    """codex r2 F002, verbatim body. The audit is given no `--phase`, the persisted state
    still names the previous phase (as it does mid-loop) and the environment names
    another, so it must not borrow STATE's record from any of them: it fails closed."""

    fx = NodeBamlPhaseFixture(tmp_path)
    fx.roadmap.write_text(fx.roadmap.read_text() + "\n### Phase 1 - Core (CORE)\n")
    core = fx.repo / "scripts/core.py"
    core.write_text("print('CORE checks passed')\n")
    plan = write_phase_plan(
        fx.repo, "CORE", fx.roadmap,
        body=f"# CORE\n\n## Verification\n- `{sys.executable} scripts/core.py`\n",
    )
    commit_fixture_paths(fx.repo, "plan both phases in advance", core, plan, fx.roadmap)
    assert fx.verify()["ok"]
    head = generated_outputs.head_commit(fx.repo)
    (fx.repo / ".phase-loop/state.json").write_text(json.dumps({"current_phase": "STATE"}))
    os.environ["PHASE_LOOP_PHASE_ALIAS"] = "STATE"     # restored by the autouse fixture
    os.environ["PHASE_ALIAS"] = "STATE"
    run_dir = fx.repo / ".phase-loop/runs/exec-core"
    run_dir.mkdir(parents=True)
    summary = runner._run_execute_verification(
        repo=fx.repo, roadmap=fx.roadmap, plan=plan,
        artifacts={"root": run_dir}, phase_alias="CORE",
    )
    assert summary["ok"], summary
    assert generated_outputs.head_commit(fx.repo) == head
    result = audit_ignored_outputs(fx.repo)
    assert "dist/index.js" in result["unknown_ignored"], result
    assert result["unknown_reasons"]["dist/index.js"] == generated_outputs.NO_PHASE_IDENTITY
    assert main(["--repo", str(fx.repo)]) == 1


def test_child_audit_uses_the_live_runner_phase(tmp_path, monkeypatch):
    """codex r3 F001 (verbatim body): a real `run_loop(phase="CORE")` launches a command
    executor. Its phase-less audit must not credit STATE's record from the stale
    persisted `current_phase` (or anything else); it refuses. The same child running
    the audit with the `--phase` it was dispatched with binds to CORE."""

    from phase_loop_runtime.launcher import AuthPreflightResult
    from phase_loop_runtime.models import StateSnapshot
    from phase_loop_runtime.state import write_state
    from phase_loop_test_utils import build_fake_automation_output

    fx = NodeBamlPhaseFixture(tmp_path)
    fx.roadmap.write_text(fx.roadmap.read_text() + "\n### Phase 1 - Core (CORE)\n")
    core = fx.repo / "scripts/core.py"
    core.write_text("print('CORE checks passed')\n")
    plan = write_phase_plan(
        fx.repo, "CORE", fx.roadmap,
        body=f"# CORE\n\n## Verification\n- `{sys.executable} scripts/core.py`\n",
    )
    probe = fx.repo / "scripts/probe.py"
    output = build_fake_automation_output(
        status="complete", verification_status="passed", artifact=str(plan), artifact_state="tracked",
    )
    probe.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "from phase_loop_runtime.closeout_classifier import audit_ignored_outputs\n"
        "result = {'phase': sys.argv[1], 'audit': audit_ignored_outputs(Path.cwd()),\n"
        "          'explicit': audit_ignored_outputs(Path.cwd(), sys.argv[1])}\n"
        "Path('.phase-loop/child-audit.json').write_text(json.dumps(result))\n"
        f"print({output!r})\n"
    )
    commit_fixture_paths(fx.repo, "plan both phases", core, probe, plan, fx.roadmap)
    assert fx.verify()["ok"]
    write_state(fx.repo, StateSnapshot(
        timestamp="2026-10-01T00:00:00Z", repo=str(fx.repo), roadmap=str(fx.roadmap),
        phases={"STATE": "planned", "CORE": "planned"}, current_phase="STATE",
    ))
    monkeypatch.setenv("PHASE_LOOP_PHASE_ALIAS", "STATE")   # an inherited stale value
    monkeypatch.setenv("PYTHONPATH", str(Path(generated_outputs.__file__).parents[1]))
    monkeypatch.setattr(runner, "run_auth_preflight", lambda *a, **k: AuthPreflightResult(ok=True, metadata={}))
    monkeypatch.setattr("phase_loop_runtime.injection._resolve_pack_skill_dirs", lambda *a, **k: {})
    runner.run_loop(
        fx.repo, fx.roadmap, phase="CORE", executor="command", observe=True,
        command_adapter_name="probe",
        command_template=f"{sys.executable} scripts/probe.py {{phase}} {{context_file}}",
    )
    observed = json.loads((fx.repo / ".phase-loop/child-audit.json").read_text())
    assert observed["phase"] == "CORE"
    assert "dist/index.js" in observed["audit"]["unknown_ignored"], observed
    assert observed["audit"]["unknown_reasons"]["dist/index.js"] == generated_outputs.NO_PHASE_IDENTITY
    assert "phase 'STATE', not 'CORE'" in observed["explicit"]["unknown_reasons"]["dist/index.js"], observed


# Every prompt route, ENUMERATED from the runtime's own tables (not hand-picked): each
# route that can lead to an audit writes it with ITS alias (codex r4 F001, r5 F001).

from phase_loop_runtime.injection import HARNESS_ACTION_SKILLS  # noqa: E402
from phase_loop_runtime.models import HARNESS_WORK_UNIT_PROMPT_KINDS, PRODUCT_LOOP_ACTIONS  # noqa: E402

AUDIT_FORMS = (
    "phase-loop-closeout-audit --repo . --record-outputs --phase {alias}`",
    "python -m phase_loop_runtime.closeout_classifier --repo . --record-outputs --phase {alias}`",
)
# Work that closes out a phase, so runs the audit whatever skills it is given.
CLOSING_OUT = {"execute", "repair", "review"}
DELEGATABLE = {"execute", "repair", "review"}
PROMPT_ACTIONS = tuple(PRODUCT_LOOP_ACTIONS) + ("skill-maintenance",)
UNBOUND_ACTIONS = {"roadmap", "maintain-skills", "skill-maintenance"}


def _shipped_audit_skills() -> set[str]:
    """Scan, not a list: every packaged skill whose text prescribes the audit."""
    root = Path(generated_outputs.__file__).parent / "skills_bundle"
    return {
        skill.parent.name for skill in root.glob("*/SKILL.md")
        if "phase-loop-closeout-audit --repo" in skill.read_text()
    }


def _prompt_text(bundle) -> str:
    return f"{bundle.body}\n{bundle.context_body or ''}\n{bundle.render_context()}"


def _assert_audit_names(bundle, alias: str) -> None:
    text = _prompt_text(bundle)
    for form in AUDIT_FORMS:
        assert form.format(alias=alias) in text, (form, alias)
    # ...and never a phase-less form an executor could follow instead.
    assert "--repo . --record-outputs`" not in text
    assert "--record-outputs --phase <" not in text
    if alias != generated_outputs.ALIAS_PLACEHOLDER:
        assert f"--record-outputs --phase {generated_outputs.ALIAS_PLACEHOLDER}`" not in text


@pytest.fixture(scope="module")
def prompt_fx(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("phase_loop_runtime.injection._resolve_pack_skill_dirs", lambda *a, **k: {})
        yield NodeBamlPhaseFixture(tmp_path_factory.mktemp("prompts"))


def test_the_audit_skill_constant_matches_the_shipped_skills():
    from phase_loop_runtime.prompts import AUDIT_PRESCRIBING_SKILLS

    assert set(AUDIT_PRESCRIBING_SKILLS) == _shipped_audit_skills()


def _routes():
    for harness in sorted(HARNESS_ACTION_SKILLS):
        for action in PROMPT_ACTIONS:
            yield pytest.param(harness, action, None, id=f"{harness}-{action}")
            if action in DELEGATABLE and harness in {"codex", "claude"}:
                yield pytest.param(harness, action, "delegated", id=f"{harness}-{action}-delegated")
        for kind in HARNESS_WORK_UNIT_PROMPT_KINDS:
            yield pytest.param(harness, "execute", f"lane:{kind}", id=f"{harness}-lane-{kind}")


@pytest.mark.parametrize(("harness", "action", "variant"), list(_routes()))
def test_every_prompt_route_that_can_audit_names_its_phase(prompt_fx, harness, action, variant):
    from phase_loop_runtime.models import HarnessLaneAssignment
    from phase_loop_runtime.prompts import build_prompt
    from phase_loop_test_utils import build_fake_delegation_request

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("phase_loop_runtime.injection._resolve_pack_skill_dirs", lambda *a, **k: {})
        kwargs, alias = {}, (generated_outputs.ALIAS_PLACEHOLDER if action in UNBOUND_ACTIONS else "STATE")
        phase = None if action in UNBOUND_ACTIONS else "STATE"
        if variant == "delegated":
            kwargs["delegation_request"] = build_fake_delegation_request(
                request_id="r1", target_executor=harness, product_action=action)
        elif variant and variant.startswith("lane:"):
            kwargs["harness_lane_assignment"] = HarnessLaneAssignment(
                phase="LANEPH", lane_id="SL-0", work_unit_kind="lane_execute",
                prompt_kind=variant.split(":", 1)[1], owned_files=("scripts/build.py",))
            alias, phase = "LANEPH", "OTHER"
        bundle = build_prompt(action, prompt_fx.roadmap, phase=phase, plan=prompt_fx.plan,
                              harness_target=harness, **kwargs)
    closes_out = action in CLOSING_OUT or (variant or "").startswith("lane:")
    if closes_out or _shipped_audit_skills() & set(bundle.expected_skill_pack):
        _assert_audit_names(bundle, alias)
        if alias == generated_outputs.ALIAS_PLACEHOLDER:
            assert "not bound to a phase: replace <ALIAS>" in _prompt_text(bundle)


@pytest.mark.parametrize("route", ["execute", "repair", "review", "lane"])
def test_what_a_codex_prompt_only_child_receives_names_the_phase(prompt_fx, route):
    """Claude N-R5-4 (mutation mC): assert the DELIVERED prompt, not the bundle. A codex
    child gets `render_prompt()` (argv / stdin), which reads the bundle's body."""

    from phase_loop_runtime import launcher
    from phase_loop_runtime.models import HarnessLaneAssignment
    from phase_loop_runtime.profiles import resolve_profile_for_executor
    from phase_loop_runtime.prompts import build_prompt

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("phase_loop_runtime.injection._resolve_pack_skill_dirs", lambda *a, **k: {})
        kwargs, action = {}, route
        if route == "lane":
            kwargs["harness_lane_assignment"] = HarnessLaneAssignment(
                phase="STATE", lane_id="SL-0", work_unit_kind="lane_execute",
                prompt_kind="implementation", owned_files=("scripts/build.py",))
            action = "execute"
        bundle = build_prompt(action, prompt_fx.roadmap, phase="STATE", plan=prompt_fx.plan,
                              harness_target="codex", **kwargs)
        request = launcher.build_launch_request(
            executor="codex", action=action, repo=prompt_fx.repo, roadmap=prompt_fx.roadmap,
            phase="STATE", plan=prompt_fx.plan,
            model_selection=resolve_profile_for_executor(action=action, executor="codex"),
            prompt_bundle=bundle, json_output=False, bypass_approvals=False)
        spec = launcher.build_launch_spec(request)
    delivered = " ".join(spec.command) + "\n" + (spec.delivery_payload() or "")
    for form in AUDIT_FORMS:
        assert form.format(alias="STATE") in delivered, (route, form)
    assert "--record-outputs --phase STATE`" in bundle.render_prompt()


@pytest.mark.parametrize("action", ["lane", "repair"])
def test_channel_closeout_receives_phase_on_every_prompt_route(tmp_path, monkeypatch, action):
    """codex r4 F001 falsifier, verbatim body: a Claude CHANNEL session (no launcher
    environment at all) follows the audit command its prompt gives it."""

    import re
    import shlex

    from phase_loop_runtime import launcher
    from phase_loop_runtime.models import HarnessLaneAssignment

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    (fx.repo / ".phase-loop/state.json").unlink()
    monkeypatch.delenv("PHASE_LOOP_PHASE_ALIAS", raising=False)
    monkeypatch.delenv("PHASE_ALIAS", raising=False)
    monkeypatch.setenv("PHASE_LOOP_CLAUDE_ROUTE", "channel")
    monkeypatch.setenv("PHASE_LOOP_CHANNEL_SESSION_ID", "test-session")
    observed = {}
    skill = Path(launcher.__file__).parent / "skills_bundle/claude-execute-phase/SKILL.md"
    monkeypatch.setattr(
        "phase_loop_runtime.injection._resolve_pack_skill_dirs",
        lambda repo, harness, names: {name: skill.parent.parent / name for name in names},
    )

    class FakeChannel:
        def __init__(self, **kwargs):
            pass

        def send_and_wait(self, text):
            observed["text"] = text
            pattern = r"`(phase-loop-closeout-audit --repo \. --record-outputs[^`]*)`"
            match = re.search(pattern, text) or re.search(pattern, skill.read_text())
            assert match is not None
            args = shlex.split(match.group(1))[1:]
            args[args.index("--repo") + 1] = str(fx.repo)
            observed["exit"] = main(args)
            observed["audit"] = audit_ignored_outputs(fx.repo)
            return launcher.ClaudeRouteResult(
                route="claude_channel", session_id="test-session",
                event_id="test", status="done", text="finished",
            )

    monkeypatch.setattr(launcher, "ChannelSidecarClient", FakeChannel)
    if action == "lane":
        assignment = HarnessLaneAssignment(
            phase="STATE", lane_id="SL-0", work_unit_kind="lane_execute",
            prompt_kind="implementation", owned_files=("scripts/build.py",),
        )
        runner.launch_harness_lane_work_unit(
            repo=fx.repo, roadmap=fx.roadmap, plan=fx.plan,
            assignment=assignment, executor="claude", dry_run=False,
        )
    else:
        from phase_loop_runtime.profiles import resolve_profile_for_executor
        from phase_loop_runtime.prompts import build_prompt

        request = launcher.build_launch_request(
            executor="claude", action="repair", repo=fx.repo, roadmap=fx.roadmap,
            phase="STATE", plan=fx.plan,
            model_selection=resolve_profile_for_executor(action="repair", executor="claude"),
            prompt_bundle=build_prompt("repair", fx.roadmap, phase="STATE",
                                       plan=fx.plan, harness_target="claude"),
            json_output=False, bypass_approvals=False,
        )
        launcher.launch_with_spec(launcher.build_launch_spec(request))
    assert observed["exit"] == 0, observed["audit"]


@pytest.mark.parametrize("action", ["execute", "repair", "review"])
def test_delegated_channel_closeout_receives_its_phase(tmp_path, monkeypatch, action):
    """codex r5 F001 falsifier, verbatim body: a delegated CLAUDE child (execute,
    repair and REVIEW) on the channel route follows the audit its prompt gives it;
    the environment names STATE too, and must not be what makes it pass."""

    import re
    import shlex

    from phase_loop_runtime import launcher
    from phase_loop_test_utils import build_fake_automation_output, build_fake_delegation_request

    fx = NodeBamlPhaseFixture(tmp_path)
    fx.plan.write_text(
        fx.plan.read_text()
        + "\n## Lanes\n\n### SL-0 - Build\n- **Owned files**: `scripts/build.py`\n"
    )
    commit_fixture_paths(fx.repo, "declare delegation ownership", fx.plan)
    assert fx.verify()["ok"]
    assert main(["--repo", str(fx.repo), "--phase", "STATE"]) == 0
    monkeypatch.setenv("PHASE_LOOP_PHASE_ALIAS", "STATE")
    monkeypatch.setenv("PHASE_ALIAS", "STATE")
    monkeypatch.setenv("PHASE_LOOP_CLAUDE_ROUTE", "channel")
    monkeypatch.setenv("PHASE_LOOP_CHANNEL_SESSION_ID", "test-session")
    skill_root = Path(launcher.__file__).parent / "skills_bundle"
    monkeypatch.setattr(
        "phase_loop_runtime.injection._resolve_pack_skill_dirs",
        lambda repo, harness, names: {name: skill_root / name for name in names},
    )
    monkeypatch.setattr(
        runner, "run_auth_preflight",
        lambda *a, **k: launcher.AuthPreflightResult(ok=True, metadata={}),
    )
    observed = {}

    class FakeChannel:
        def __init__(self, **kwargs):
            pass

        def send_and_wait(self, text):
            pattern = r"`(phase-loop-closeout-audit --repo \. --record-outputs[^`]*)`"
            skill = (skill_root / "claude-execute-phase/SKILL.md").read_text()
            match = re.search(pattern, text) or re.search(pattern, skill)
            assert match is not None
            args = shlex.split(match.group(1))[1:]
            args[args.index("--repo") + 1] = str(fx.repo)
            observed["command"] = match.group(1)
            observed["exit"] = main(args)
            return launcher.ClaudeRouteResult(
                route="claude_channel", session_id="test-session", event_id="test",
                status="done", text=build_fake_automation_output(status="executed"),
            )

    monkeypatch.setattr(launcher, "ChannelSidecarClient", FakeChannel)
    request = build_fake_delegation_request(
        request_id="audit-review", target_executor="claude", product_action=action,
        owned_files=("scripts/build.py",),
    )
    outcome = runner.launch_delegated_child(
        repo=fx.repo, roadmap=fx.roadmap, parent_phase="STATE", parent_action="execute",
        plan=fx.plan, request=request, parent_executor="codex", dry_run=False,
    )
    assert outcome["decision"]["status"] == "approved", outcome
    assert observed["exit"] == 0, observed


def test_record_outputs_without_a_phase_refuses_before_touching_anything(tmp_path):
    """Claude R3_A / Grok r4 G-5: with a declaration and no `--phase`, `--record-outputs`
    exits 2 BEFORE moving anything aside or running a producer; nothing is recorded,
    and the environment is never consulted."""

    fx = NodeBamlPhaseFixture(tmp_path)
    for _ in range(2):   # the second run moves the first build aside, so displaced/ exists
        assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", "STATE"]) == 0
    before = {p: p.read_bytes() for p in (fx.repo / "dist").rglob("*") if p.is_file()}
    record_before = (fx.repo / generated_outputs.RECORD_RELPATH).read_bytes()
    displaced = fx.repo / generated_outputs.DISPLACED_RELDIR
    displaced_before = sorted(displaced.iterdir())
    assert main(["--repo", str(fx.repo), "--record-outputs"]) == 2
    assert sorted(displaced.iterdir()) == displaced_before          # nothing moved aside
    assert {p: p.read_bytes() for p in (fx.repo / "dist").rglob("*") if p.is_file()} == before
    assert (fx.repo / generated_outputs.RECORD_RELPATH).read_bytes() == record_before
    with pytest.raises(generated_outputs.PhaseIdentityError):
        generated_outputs.run_declared_producers(fx.repo)
    # The plain audit with no identity blocks, naming the remedy.
    assert main(["--repo", str(fx.repo)]) == 1
    reason = audit_ignored_outputs(fx.repo)["unknown_reasons"]["dist/index.js"]
    assert reason == generated_outputs.NO_PHASE_IDENTITY and "--phase" in reason
    assert main(["--repo", str(fx.repo), "--phase", "STATE"]) == 0


def test_an_unsubstituted_placeholder_is_not_a_phase_identity(tmp_path):
    """The skills, hint and docs print `--phase "<ALIAS>"`. Pasted unchanged, the
    shell passes `<ALIAS>`, which the alias grammar can never match, so it is refused
    exactly like a missing phase (it would otherwise give every phase one identity)."""

    fx = NodeBamlPhaseFixture(tmp_path)
    placeholder = shlex.split(generated_outputs.ALIAS_PLACEHOLDER)
    assert placeholder == ["<ALIAS>"]
    for bad in (*placeholder, generated_outputs.ALIAS_PLACEHOLDER, "<PHASE_ALIAS>", "", "  ",
                "A B", "'CORE'", "-CORE", "state"):
        assert generated_outputs.current_phase(bad) is None, bad
    assert generated_outputs.current_phase(" CORE ") == "CORE"
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", *placeholder]) == 2
    assert not (fx.repo / generated_outputs.RECORD_RELPATH).exists()


def test_every_alias_the_roadmap_grammar_accepts_is_a_phase_identity(tmp_path):
    """codex r6 F001: a word list cannot tell a placeholder from a real alias. Derive
    the accepted set from the roadmap's OWN parser (`discovery.parse_roadmap_phases`)
    over a generated candidate set, and require `current_phase` to agree with it
    exactly: every alias a roadmap can declare is an identity, and nothing else is."""

    import itertools
    import random

    from phase_loop_runtime.discovery import parse_roadmap_phases

    alphabet = "AZQ09._-az<>\"'*"
    candidates = {"".join(chars) for n in (1, 2, 3) for chars in itertools.product(alphabet, repeat=n)}
    rng = random.Random(1139)
    candidates |= {"".join(rng.choice(alphabet) for _ in range(rng.randint(4, 12))) for _ in range(400)}
    candidates |= {"PHASE", "ALIAS", "PHASE_ALIAS", "PHASE-ALIAS", "PHASEALIAS", "CORE", "STATE",
                   "ADAPTER", "V10.1", "<ALIAS>", generated_outputs.ALIAS_PLACEHOLDER}
    ordered = sorted(candidates)
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text("# Roadmap\n\n" + "".join(
        f"### Phase {i} - Candidate ({alias})\n" for i, alias in enumerate(ordered)))
    accepted = set(parse_roadmap_phases(roadmap))
    assert {"PHASE", "ALIAS", "PHASE_ALIAS", "CORE"} <= accepted   # the grammar admits them
    assert "<ALIAS>" not in accepted and generated_outputs.ALIAS_PLACEHOLDER not in accepted
    assert len(accepted) > 100 and len(candidates - accepted) > 1000   # both sides exercised
    for alias in ordered:
        assert (generated_outputs.current_phase(alias) == alias) == (alias in accepted), alias


def test_declared_roadmap_phase_is_not_a_placeholder(tmp_path, monkeypatch):
    """codex r6 F001 falsifier, verbatim body: a roadmap that declares the real alias
    PHASE validates, verifies, and the runner's own literal audit command accepts it."""

    import re

    from phase_loop_runtime.discovery import parse_roadmap_phases, plan_artifact_diagnostic
    from phase_loop_runtime.prompts import build_prompt

    fx = NodeBamlPhaseFixture(tmp_path)
    fx.roadmap.write_text("# Roadmap\n\n### Phase 0 - Implementation (PHASE)\n")
    plan = write_phase_plan(
        fx.repo, "PHASE", fx.roadmap,
        body=("# PHASE\n\n## Verification\n"
              f"- `{sys.executable} scripts/gen_baml.py`\n"
              f"- `{sys.executable} scripts/build.py`\n"),
    )
    commit_fixture_paths(fx.repo, "declare the real PHASE alias", fx.roadmap, plan)
    assert parse_roadmap_phases(fx.roadmap) == ["PHASE"]
    assert plan_artifact_diagnostic(fx.repo, plan, fx.roadmap, "PHASE") is None
    monkeypatch.setattr("phase_loop_runtime.injection._resolve_pack_skill_dirs",
                        lambda *a, **k: {})
    bundle = build_prompt("execute", fx.roadmap, phase="PHASE", plan=plan)
    command = re.search(
        r"`(phase-loop-closeout-audit --repo \. --record-outputs[^`]*)`",
        bundle.render_prompt(),
    ).group(1)
    args = shlex.split(command)[1:]
    args[args.index("--repo") + 1] = str(fx.repo)
    root = fx.repo / ".phase-loop" / "runs" / "phase"
    root.mkdir(parents=True)
    verification = runner._run_execute_verification(
        repo=fx.repo, roadmap=fx.roadmap, plan=plan,
        artifacts={"root": root}, phase_alias="PHASE",
    )
    assert verification["ok"], verification
    assert main(args) == 0, verification
    assert generated_outputs.load_record(fx.repo)["phase"] == "PHASE"


def test_the_mismatch_hint_names_the_phase(tmp_path):
    """Grok r4 G-2: the remedy an operator copies must carry `--phase`."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    reason = audit_ignored_outputs(fx.repo, "CORE")["unknown_reasons"]["dist/index.js"]
    assert "--record-outputs --phase CORE`" in reason, reason
    # Claude N-R5-1: the tool never prints an ACCEPTED placeholder for an operator to copy.
    (fx.repo / generated_outputs.RECORD_RELPATH).unlink()
    reason = audit_ignored_outputs(fx.repo)["unknown_reasons"]["dist/index.js"]
    assert '--record-outputs --phase "<ALIAS>"`' in reason, reason
    assert '--phase "<ALIAS>"' in generated_outputs.NO_PHASE_IDENTITY
    for printed in (generated_outputs.ALIAS_PLACEHOLDER, *shlex.split(generated_outputs.ALIAS_PLACEHOLDER)):
        assert generated_outputs.current_phase(printed) is None


def test_the_execute_phase_skills_prescribe_the_audit_with_a_phase():
    """Grok r4 G-2 / Claude N-R5-2: every shipped skill that prescribes the audit writes
    the quoted placeholder `--phase "<ALIAS>"`, which is shell-safe to paste literally
    (a no-op without a declaration, refused as an identity with one), and says to
    substitute it."""

    root = Path(generated_outputs.__file__).parent / "skills_bundle"
    skills = sorted(root / name / "SKILL.md" for name in _shipped_audit_skills())
    assert skills
    for skill in skills:
        text = skill.read_text()
        assert '--record-outputs --phase "<ALIAS>"`' in text, skill
        assert "replace `<ALIAS>` with the alias of the phase you are executing" in text, skill
        assert "--repo . --record-outputs`" not in text, skill
        assert "--phase <" not in text and "--phase ALIAS" not in text, skill


def test_a_corrupt_record_at_top_level_is_typed(tmp_path):
    """Claude R3_B."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    path = fx.repo / generated_outputs.RECORD_RELPATH
    for bad in ("[]", '"x"', "null", '{"schema": 1, "files": [], "head": 3}'):
        path.write_text(bad)
        result = audit_ignored_outputs(fx.repo, fx.phase)
        assert result["blocks"] and not result["probe_failed"], (bad, result)


def test_invalid_producer_timeouts_fall_back_to_the_bound(capsys):
    """Claude r3 nit: 0, negative, NaN, infinity and garbage never mean "unbounded"."""

    for bad in (0, -5, "nan", "inf", "-inf", "soon"):
        assert generated_outputs.producer_timeout(bad) == generated_outputs.DEFAULT_PRODUCER_TIMEOUT_S, bad
    assert generated_outputs.producer_timeout("7") == 7.0


def test_a_timed_out_producer_takes_its_children_with_it(tmp_path):
    """Claude r3 nit: the whole process group is killed, so a grandchild cannot keep
    writing after the post-run snapshot."""

    marker = tmp_path / "grandchild-wrote"
    grandchild = f"import time; time.sleep(2); open({str(marker)!r}, 'w').write('late')"
    parent = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "time.sleep(30)\n"
    )
    code = generated_outputs._run_bounded([sys.executable, "-c", parent], tmp_path, 0.5, "p")
    assert code == 124
    import time

    time.sleep(3)
    assert not marker.exists()


def test_displacement_directories_are_bounded(tmp_path):
    """Claude r3 nit: only the newest DISPLACED_KEEP displacements are kept. Grok r4 G-1
    (mutation K): pin the DIRECTION too, so the prune can never delete the
    displacement it just made, or keep the oldest."""

    fx = NodeBamlPhaseFixture(tmp_path)
    root = fx.repo / generated_outputs.DISPLACED_RELDIR
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]) == 0  # first build
    made = []
    for _ in range(generated_outputs.DISPLACED_KEEP + 2):
        seen = {entry.name for entry in root.iterdir()} if root.exists() else set()
        assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", fx.phase]) == 0
        (new,) = {entry.name for entry in root.iterdir()} - seen
        made.append(new)
    kept = sorted(entry.name for entry in root.iterdir())
    assert len(kept) == generated_outputs.DISPLACED_KEEP
    assert made[-1] in kept and made[0] not in kept and made[1] not in kept, (made, kept)
