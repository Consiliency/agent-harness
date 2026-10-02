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
def _phase_identity(monkeypatch):
    """Each test runs as the executor child of a dispatched phase (STATE by default),
    and never inherits a phase identity from the developer's or CI's environment."""
    monkeypatch.delenv("PHASE_ALIAS", raising=False)
    monkeypatch.setenv("PHASE_LOOP_PHASE_ALIAS", "STATE")


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
        # The default identity (STATE) comes from the autouse `_phase_identity` fixture,
        # so constructing this from another module never leaks it into the session.

    def set_phase(self, alias: str) -> None:
        """What `launcher.launch(phase_alias=...)` stamps on the executor child. The
        autouse `_phase_identity` fixture restores the environment afterwards."""
        os.environ["PHASE_LOOP_PHASE_ALIAS"] = alias

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
            self.assertEqual({i["source"] for i in record["invocations"]}, {"closeout-audit"})


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
            result = audit_ignored_outputs(fx.repo)
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


# --- round-1 board falsifiers (agent-harness#1189), kept verbatim in substance -------


def _audit_blocks_on(fx, path):
    result = audit_ignored_outputs(fx.repo)
    assert result["blocks"], result
    assert path in result[UNKNOWN_IGNORED], result
    assert main(["--repo", str(fx.repo)]) == 1
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
    assert main(["--repo", str(fx.repo)]) == 1          # stale evidence alone blocks
    assert main(["--repo", str(fx.repo), "--record-outputs"]) == 0


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
    recorder.write(source="closeout-audit", run_id=None)
    result = audit_ignored_outputs(fx.repo)
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
    assert main(["--repo", str(fx.repo)]) == 0


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
    recorder.write(source="closeout-audit", run_id=None)
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
    """codex r2 F002, plus Claude N1, at the identity level: the CORE child carries
    PHASE_LOOP_PHASE_ALIAS=CORE, which `launcher.launch(phase_alias=...)` stamps (see
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
    result = audit_ignored_outputs(fx.repo)
    assert "dist/index.js" in result["unknown_ignored"], result
    assert main(["--repo", str(fx.repo)]) == 1
    assert any("HEAD moved" in error for error in recorder.errors)


def test_record_outputs_rebuild_moves_planted_and_orphaned_files_aside(tmp_path):
    """Claude N2 and the CLI half of F001: `--record-outputs` is a CLEAN observed
    rebuild. Byte-identical regeneration earns provenance; a planted or orphaned file
    is moved aside (never deleted) instead of riding along."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert main(["--repo", str(fx.repo), "--record-outputs"]) == 0
    orphan = fx.repo / "dist" / "old.js"           # a file the build no longer emits
    orphan.write_text("left over from an earlier build\n")
    assert main(["--repo", str(fx.repo)]) == 1
    assert main(["--repo", str(fx.repo), "--record-outputs"]) == 0
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
    recorder.write(source="closeout-audit", run_id=None)
    result = audit_ignored_outputs(fx.repo)
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
    record = generated_outputs.run_declared_producers(fx.repo)
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
    assert main(["--repo", str(fx.repo), "--record-outputs"]) == 0


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
    assert main(["--repo", str(fx.repo), "--record-outputs"]) == 0
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
    record = recorder.write(source="closeout-audit", run_id=None)
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
    assert recorder.write(source="closeout-audit", run_id=None) is None
    assert any("HEAD moved" in error for error in recorder.errors)


# --- round-3 board falsifiers (agent-harness#1189 at e797af15) ------------------------


def test_next_phase_at_same_head_verbatim_with_no_phase_identity(tmp_path, monkeypatch):
    """codex r2 F002, verbatim body. The audit runs with NO phase identity in the
    environment (as before this PR stamped one), so it must not borrow STATE's record.
    With no identity the audit fails closed instead of falling back to state.json."""

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
    monkeypatch.delenv("PHASE_LOOP_PHASE_ALIAS")
    # The persisted state still names the previous phase, as it does mid-loop: a
    # fallback to it would wrongly match STATE's record.
    (fx.repo / ".phase-loop/state.json").write_text(json.dumps({"current_phase": "STATE"}))
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
    assert main(["--repo", str(fx.repo)]) == 1


def test_child_audit_uses_the_live_runner_phase(tmp_path, monkeypatch):
    """codex r3 F001 (verbatim): a real `run_loop(phase="CORE")` launches a command
    executor whose own audit must bind to CORE, not to STATE's record and not to the
    stale persisted `current_phase`."""

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
        "result = {'phase': sys.argv[1], 'audit': audit_ignored_outputs(Path.cwd())}\n"
        "Path('.phase-loop/child-audit.json').write_text(json.dumps(result))\n"
        f"print({output!r})\n"
    )
    commit_fixture_paths(fx.repo, "plan both phases", core, probe, plan, fx.roadmap)
    assert fx.verify()["ok"]
    write_state(fx.repo, StateSnapshot(
        timestamp="2026-10-01T00:00:00Z", repo=str(fx.repo), roadmap=str(fx.roadmap),
        phases={"STATE": "planned", "CORE": "planned"}, current_phase="STATE",
    ))
    monkeypatch.delenv("PHASE_LOOP_PHASE_ALIAS", raising=False)
    monkeypatch.delenv("PHASE_ALIAS", raising=False)
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
    assert "not 'CORE'" in observed["audit"]["unknown_reasons"]["dist/index.js"], observed


def test_the_launcher_stamps_the_live_phase_over_an_inherited_one(tmp_path):
    """The positive half: the child sees exactly the dispatched alias, even when the
    parent environment carries a stale one."""

    from phase_loop_runtime.launcher import launch

    out = tmp_path / "alias.txt"
    script = f"import os; open({str(out)!r}, 'w').write(os.environ.get('PHASE_LOOP_PHASE_ALIAS', ''))"
    launch([sys.executable, "-c", script], env={**os.environ, "PHASE_LOOP_PHASE_ALIAS": "STALE"},
           phase_alias="CORE", timeout_seconds=60)
    assert out.read_text() == "CORE"
    # With no dispatched phase the inherited alias is a guess, so the child gets none.
    launch([sys.executable, "-c", script], env={**os.environ, "PHASE_LOOP_PHASE_ALIAS": "STALE"},
           timeout_seconds=60)
    assert out.read_text() == ""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="lease supervision relies on prctl")
def test_the_lease_supervised_launch_keeps_the_stamped_phase(tmp_path):
    """Production run_loop launches under a lease authority, which re-enters `launch`
    without `phase_alias`; the stamp must survive that re-entry."""

    import fcntl

    from phase_loop_runtime.launcher import launch

    class _Lease:
        generation = "closeout-phase-test"

        def __init__(self, fd: int) -> None:
            self._fd = fd

        def fileno(self) -> int:
            return self._fd

    fd = os.open(tmp_path / "lease.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = tmp_path / "alias.txt"
        script = f"import os; open({str(out)!r}, 'w').write(os.environ.get('PHASE_LOOP_PHASE_ALIAS', ''))"
        result = launch([sys.executable, "-c", script], lease_authority=_Lease(fd),
                        log_path=tmp_path / "executor.log", env={**os.environ, "PHASE_LOOP_PHASE_ALIAS": "STALE"},
                        phase_alias="CORE")
        assert not result.failed, result
        assert out.read_text() == "CORE"
    finally:
        os.close(fd)


def test_the_execute_prompt_passes_the_phase_to_the_audit(tmp_path, monkeypatch):
    """Channel and agent-view sessions get no launcher env, so the prompt itself names
    the phase on every audit command it prescribes."""

    from phase_loop_runtime.prompts import build_prompt

    monkeypatch.setattr("phase_loop_runtime.injection._resolve_pack_skill_dirs", lambda *a, **k: {})
    fx = NodeBamlPhaseFixture(tmp_path)
    bundle = build_prompt("execute", fx.roadmap, phase="STATE", plan=fx.plan)
    text = f"{bundle.body}\n{bundle.context_body or ''}"
    assert "phase-loop-closeout-audit --repo . --record-outputs --phase STATE`" in text
    assert "closeout_classifier --repo . --record-outputs --phase STATE`" in text


def test_record_outputs_without_a_phase_identity_records_nothing(tmp_path, monkeypatch):
    """Claude R3_A: no live alias and no --phase -> no record, so nothing is accepted;
    `--phase` restores the CLI path."""

    fx = NodeBamlPhaseFixture(tmp_path)
    monkeypatch.delenv("PHASE_LOOP_PHASE_ALIAS")
    assert main(["--repo", str(fx.repo), "--record-outputs"]) == 1
    assert not (fx.repo / generated_outputs.RECORD_RELPATH).exists()   # not even a null-phase file
    assert main(["--repo", str(fx.repo), "--record-outputs", "--phase", "STATE"]) == 0
    assert main(["--repo", str(fx.repo)]) == 1                     # still no identity
    reason = audit_ignored_outputs(fx.repo)["unknown_reasons"]["dist/index.js"]
    assert reason.startswith("no phase identity"), reason
    assert main(["--repo", str(fx.repo), "--phase", "STATE"]) == 0


def test_a_corrupt_record_at_top_level_is_typed(tmp_path):
    """Claude R3_B."""

    fx = NodeBamlPhaseFixture(tmp_path)
    assert fx.verify()["ok"]
    path = fx.repo / generated_outputs.RECORD_RELPATH
    for bad in ("[]", '"x"', "null", '{"schema": 1, "files": [], "head": 3}'):
        path.write_text(bad)
        result = audit_ignored_outputs(fx.repo)
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
    """Claude r3 nit: only the newest DISPLACED_KEEP displacements are kept."""

    fx = NodeBamlPhaseFixture(tmp_path)
    for _ in range(generated_outputs.DISPLACED_KEEP + 2):
        assert main(["--repo", str(fx.repo), "--record-outputs"]) == 0
    kept = list((fx.repo / generated_outputs.DISPLACED_RELDIR).iterdir())
    assert len(kept) == generated_outputs.DISPLACED_KEEP
