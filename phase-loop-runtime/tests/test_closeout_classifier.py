"""GATE (roadmap v40) — sensitivity classifier (IF-0-GATE-1).

`classify_unowned_path` maps a repo-relative path to a SensitivityVerdict per the
PROTO SENSITIVITY_CLASSES taxonomy. Precedence is load-bearing: UNSAFE-specific
patterns (secrets, lockfile, ci) win over broad SAFE rules; tests are UNSAFE;
config_nonsource is a tight allowlist; unmatched is deny-by-default UNSAFE.
"""

import unittest

import phase_loop_runtime.models as m
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from phase_loop_runtime.closeout_classifier import (
    RUNNER_OWNED,
    TOOL_CACHE,
    UNKNOWN_IGNORED,
    SensitivityVerdict,
    audit_ignored_outputs,
    classify_ignored_output,
    classify_unowned_path,
    main,
)


class CloseoutClassifierTest(unittest.TestCase):
    def _cls(self, path):
        return classify_unowned_path(path).sensitivity_class

    def test_safe_classes(self):
        for path in ("README.md", "docs/guide.md", "docs/sub/x.md", "notes.rst"):
            v = classify_unowned_path(path)
            self.assertEqual(v.sensitivity_class, "docs", path)
            self.assertTrue(v.safe, path)
        self.assertEqual(self._cls("plans/phase-plan-v40-GATE.md"), "plans")
        self.assertTrue(classify_unowned_path("plans/p.md").safe)
        self.assertEqual(self._cls(".dev-skills/handoffs/codex-execute-phase/latest.md"), "handoffs")
        self.assertTrue(classify_unowned_path(".dev-skills/handoffs/x/latest.md").safe)

    def test_config_nonsource_is_a_tight_allowlist(self):
        for path in (".gitignore", ".editorconfig", "setup.cfg", "tox.ini"):
            v = classify_unowned_path(path)
            self.assertEqual(v.sensitivity_class, "config_nonsource", path)
            self.assertTrue(v.safe, path)

    def test_source_is_unsafe(self):
        for path in ("ai_stack/router/models.py", "scripts/run.sh", "src/app.ts", "weird.bin", "unknown.xyz", "Makefile"):
            v = classify_unowned_path(path)
            self.assertFalse(v.safe, path)
            self.assertIn(v.sensitivity_class, m.UNSAFE_SENSITIVITY_CLASSES, path)

    def test_txt_is_docs_only_under_docs_dir(self):
        # A bare .txt is NOT auto-docs (source-adjacent text); only docs are SAFE.
        self.assertFalse(classify_unowned_path("src/foreign.txt").safe)
        self.assertEqual(classify_unowned_path("docs/notes.txt").sensitivity_class, "docs")
        self.assertTrue(classify_unowned_path("docs/notes.txt").safe)

    def test_tests_are_unsafe(self):
        for path in ("tests/test_x.py", "tests/queue/test_db_migrations.py", "pkg/__tests__/a.test.ts", "test_top.py"):
            v = classify_unowned_path(path)
            self.assertFalse(v.safe, path)
            self.assertEqual(v.sensitivity_class, "source", path)

    def test_precedence_unsafe_specific_beats_broad_safe(self):
        # CI config files are not docs/config_nonsource — they are ci (UNSAFE).
        self.assertEqual(self._cls(".github/workflows/release.yml"), "ci")
        self.assertFalse(classify_unowned_path(".github/workflows/release.yml").safe)
        # Secrets win regardless of suffix.
        for path in (".env", ".env.production", "deploy/server.pem", "secrets/token.txt"):
            self.assertEqual(self._cls(path), "secrets", path)
            self.assertFalse(classify_unowned_path(path).safe, path)
        # Lockfiles.
        for path in ("package-lock.json", "uv.lock", "pnpm-lock.yaml", "Cargo.lock", "poetry.lock"):
            self.assertEqual(self._cls(path), "lockfile", path)
            self.assertFalse(classify_unowned_path(path).safe, path)
        # A .toml/.yaml/.json is NOT auto-SAFE config — it is source (UNSAFE).
        for path in ("pyproject.toml", "config/nodes.toml", "settings.yaml", "data.json"):
            self.assertFalse(classify_unowned_path(path).safe, path)

    def test_deny_by_default_unmatched_is_unsafe(self):
        for path in ("", "no_extension", "a/b/c.weirdext", "binaryblob"):
            self.assertFalse(classify_unowned_path(path).safe, path)

    def test_verdict_safe_matches_taxonomy(self):
        for path in ("docs/a.md", "plans/p.md", ".gitignore", "src/a.py", "tests/t.py", ".env", "uv.lock", ".github/x.yml", "weird.bin"):
            v = classify_unowned_path(path)
            self.assertIn(v.sensitivity_class, m.SENSITIVITY_CLASSES, path)
            self.assertEqual(v.safe, v.sensitivity_class in m.SAFE_SENSITIVITY_CLASSES, path)

    def test_verdict_is_frozen_dataclass(self):
        v = SensitivityVerdict(sensitivity_class="docs", safe=True)
        with self.assertRaises(Exception):
            v.safe = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()


class TestIgnoredOutputProvenance(unittest.TestCase):
    """ah#670: an executor blocked closeout on the runner's OWN footprint.

    Its 13-file tracked diff was owned and verified; `.phase-loop/**`,
    `.ruff_cache/`, `.pytest_cache/` and `.venv/` were all produced by the
    governed command itself. Blocking there is a loop -- the repair turn re-runs
    the command and recreates them.
    """

    def test_the_exact_paths_from_the_reported_run_do_not_block(self):
        """Every path is taken verbatim from the terminal-summary of the run in
        the issue, so this pins the reported case rather than a paraphrase.

        Mutation that must kill this: drop `.venv`/`__pycache__` from the
        toolchain set, or stop consulting EXCLUDE_ENTRIES.
        """
        reported = [
            ".phase-loop/active-loop.json",
            ".phase-loop/events.jsonl",
            ".phase-loop/metrics.jsonl",
            ".phase-loop/runs/",
            ".phase-loop/state.json",
            ".phase-loop/tui-handoff.md",
            ".ruff_cache/",
            "phase-loop-runtime/.pytest_cache/",
            "phase-loop-runtime/.venv/",
            "phase-loop-runtime/src/phase_loop_runtime.egg-info/",
            "phase-loop-runtime/src/phase_loop_runtime/__pycache__/",
        ]
        for path in reported:
            verdict = classify_ignored_output(path)
            self.assertFalse(verdict.blocks, f"{path} must not block: {verdict}")
            self.assertIn(verdict.provenance, (RUNNER_OWNED, TOOL_CACHE))

    def test_runner_state_is_typed_from_the_runtime_s_own_exclusions(self):
        self.assertEqual(classify_ignored_output(".phase-loop/state.json").provenance,
                         RUNNER_OWNED)
        # The legacy location is in EXCLUDE_ENTRIES too, so reusing that constant
        # covers it without a second list here.
        self.assertEqual(classify_ignored_output(".codex/phase-loop/state.json").provenance,
                         RUNNER_OWNED)

    def test_an_unrecognised_ignored_output_STILL_blocks(self):
        """The point is to stop blocking on the runner's footprint, not to stop
        blocking. Deny-by-default must survive.

        Mutation that must kill this: return a non-blocking verdict as the
        fallback instead of UNKNOWN_IGNORED.
        """
        for path in ("scratch/dump.csv", "secrets.env.bak", "output/report.pdf"):
            verdict = classify_ignored_output(path)
            self.assertEqual(verdict.provenance, UNKNOWN_IGNORED)
            self.assertTrue(verdict.blocks, f"{path} must still block")

    def test_a_cache_NAME_matches_at_any_depth(self):
        """The reported run had caches at the root AND nested two levels down,
        so a root-anchored rule would have missed half of them.
        """
        self.assertEqual(
            classify_ignored_output("a/b/c/__pycache__/x.pyc").provenance, TOOL_CACHE)

    def test_a_path_merely_CONTAINING_a_cache_name_is_not_laundered(self):
        """`my__pycache__notes.txt` is not a cache. Substring matching would
        launder an arbitrary ignored file into the non-blocking bucket.

        Mutation that must kill this: match on substring rather than on a path
        COMPONENT.
        """
        self.assertEqual(
            classify_ignored_output("notes/my__pycache__notes.txt").provenance,
            UNKNOWN_IGNORED)


class TestIgnoredOutputAudit(unittest.TestCase):
    def _repo(self, tmp):
        run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                        capture_output=True)
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        repo = Path(tmp)
        (repo / ".gitignore").write_text(
            ".phase-loop/\n.ruff_cache/\n__pycache__/\n.venv/\nscratch/\n")
        (repo / "src").mkdir()
        (repo / "src" / "owned.py").write_text("x = 1\n")
        run("add", "-A")
        run("commit", "-qm", "seed")
        return repo

    def test_the_reported_scenario_end_to_end_does_not_block(self):
        """Acceptance regression from the issue: an owned tracked diff PLUS
        `.phase-loop/**` plus pytest/Ruff caches must not block.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "src" / "owned.py").write_text("x = 2\n")     # owned tracked diff
            (repo / ".phase-loop" / "runs").mkdir(parents=True)
            (repo / ".phase-loop" / "state.json").write_text("{}")
            (repo / ".ruff_cache").mkdir()
            (repo / ".ruff_cache" / "c").write_text("x")
            (repo / "src" / "__pycache__").mkdir()
            (repo / "src" / "__pycache__" / "owned.pyc").write_text("x")
            result = audit_ignored_outputs(repo)
            self.assertFalse(result["blocks"], result)
            self.assertEqual(result[UNKNOWN_IGNORED], [])
            self.assertTrue(result[RUNNER_OWNED] or result[TOOL_CACHE])

    def test_an_unknown_ignored_output_makes_the_audit_block(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "scratch").mkdir()
            (repo / "scratch" / "dump.csv").write_text("x")
            result = audit_ignored_outputs(repo)
            self.assertTrue(result["blocks"])
            self.assertTrue(result[UNKNOWN_IGNORED])

    def test_a_failed_git_probe_blocks_rather_than_reading_as_clean(self):
        """"Could not read the tree" must never present as "nothing to see".

        Mutation that must kill this: return empty buckets with blocks=False on
        a non-zero git exit.
        """
        with TemporaryDirectory() as tmp:
            result = audit_ignored_outputs(Path(tmp) / "not-a-repo")
            self.assertTrue(result["probe_failed"])
            self.assertTrue(result["blocks"])

    def test_the_cli_exit_codes_carry_the_verdict(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / ".ruff_cache").mkdir()
            (repo / ".ruff_cache" / "c").write_text("x")
            self.assertEqual(main(["--repo", str(repo)]), 0)
            (repo / "scratch").mkdir()
            (repo / "scratch" / "dump.csv").write_text("x")
            self.assertEqual(main(["--repo", str(repo)]), 1)
            self.assertEqual(main(["--repo", str(Path(tmp) / "nope")]), 2)
