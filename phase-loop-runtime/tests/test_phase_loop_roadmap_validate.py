import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phase_loop_test_utils import make_repo, provenanced_event, provenanced_state, write_phase_plan
from phase_loop_runtime.cli import main
from phase_loop_runtime.events import append_event
from phase_loop_runtime.provenance import (
    phase_provenance_map,
    phase_sha256,
    validate_roadmap_phase_headings,
)

import pytest

# TESTDECOUPLE SL-1 (overlay-dependent): builds a skill/adoption bundle or runs the
# runtime execute path, which resolves the dotfiles skill-source / profile overlay
# (claude-config/*, codex-config/* …) absent standalone. Run-time integration: the
# conftest hook skips this class when no dotfiles tree is reachable. The pure
# roadmap-lint tests below must also run in standalone CI.
@pytest.mark.dotfiles_integration
class PhaseLoopRoadmapValidateTest(unittest.TestCase):
    def test_validator_accepts_integer_and_decimal_phase_headings(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "# Roadmap\n\n"
                "### Phase 0 - Contract (CONTRACT)\n\n"
                "### Phase 2.1 - Runner Follow-up (RUNNER2)\n"
            )

            self.assertEqual(validate_roadmap_phase_headings(roadmap), [])
            self.assertIn("CONTRACT", phase_provenance_map(roadmap))
            self.assertIsNotNone(phase_sha256(roadmap, "RUNNER2"))

    def test_validator_reports_loose_candidates_duplicates_and_invalid_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"
            roadmap.write_text(
                "# Roadmap\n\n"
                "### Phase NOTANUMBER - Bad Number (BAD)\n"
                "### Phase 1 - Duplicate (DUP)\n"
                "### Phase 2 - Duplicate Again (DUP)\n"
                "### Phase 3 - Bad Alias (bad)\n"
            )

            findings = validate_roadmap_phase_headings(roadmap)
            reasons = [finding.reason for finding in findings]
            self.assertTrue(any("loose-match" in reason for reason in reasons))
            self.assertTrue(any("duplicate-alias" in reason for reason in reasons))
            self.assertTrue(any("invalid-alias" in reason for reason in reasons))
            self.assertTrue(all(finding.line_number > 0 for finding in findings))
            self.assertTrue(all(finding.raw_text.startswith("### Phase") for finding in findings))
            self.assertTrue(all(finding.suggested_fix for finding in findings))

    def test_clean_roadmap_has_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            roadmap = repo / "specs" / "phase-plans-v1.md"

            self.assertEqual(validate_roadmap_phase_headings(roadmap), [])

    def test_roadmap_aware_entrypoints_warn_without_blocking_or_corrupting_json(self):
        commands = (
            ("run", ["run", "--phase", "RUNNER", "--dry-run"]),
            ("resume", ["resume"]),
            ("dry-run", ["dry-run"]),
            ("status", ["status", "--json"]),
            ("execute", ["execute", "RUNNER", "--output", "{output}", "--mode", "execute", "--dry-run", "--json"]),
            ("reconcile", ["reconcile", "--phase", "RUNNER", "--repair-summary", "fixture"]),
            ("reopen", ["reopen", "--phase", "RUNNER", "--reason", "fixture", "--allow-dirty"]),
            ("monitor", ["monitor", "--once", "--json"]),
            ("evidence-audit", ["evidence-audit"]),
            ("closeout-drift-audit", ["closeout-drift-audit"]),
        )
        for name, command in commands:
            with self.subTest(command=name), tempfile.TemporaryDirectory() as td:
                repo = make_repo(Path(td))
                roadmap = repo / "specs" / "phase-plans-v1.md"
                roadmap.write_text(
                    roadmap.read_text()
                    + "\n### Phase NOTANUMBER - Bad heading (BAD)\n"
                )
                subprocess.run(["git", "add", str(roadmap.relative_to(repo))], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "bad roadmap fixture"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
                plan = write_phase_plan(repo, "RUNNER", roadmap)
                subprocess.run(["git", "add", str(plan.relative_to(repo))], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "runner plan fixture"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
                if name == "reopen":
                    append_event(repo, provenanced_event(repo, roadmap, "RUNNER", "complete"))

                output = Path(td) / "closeout.json"
                argv = [part.format(output=output) for part in command]
                if name == "closeout-drift-audit":
                    argv.extend(["--repo", str(repo), "--roadmap", str(roadmap)])
                else:
                    argv.extend(["--repo", str(repo), "--roadmap", str(roadmap)])

                stdout = io.StringIO()
                stderr = io.StringIO()
                patches = []
                if name in {"run", "dry-run", "execute"}:
                    patches.append(
                        patch(
                            "phase_loop_runtime.cli.run_loop",
                            return_value=(provenanced_state(repo, roadmap, {"RUNNER": "planned"}), []),
                        )
                    )
                if name == "closeout-drift-audit":
                    class CleanDriftAudit:
                        def to_json(self):
                            return {"findings": []}

                        def render_text(self):
                            return "Closeout drift audit: clean"

                        def has_setup_errors(self):
                            return False

                        def has_drift(self):
                            return False

                    patches.append(patch("phase_loop_runtime.phase_loop_drift_audit.run_drift_audit", return_value=CleanDriftAudit()))
                with contextlib.ExitStack() as stack, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    for active_patch in patches:
                        stack.enter_context(active_patch)
                    code = main(argv)

                self.assertNotEqual(code, 2, stderr.getvalue())
                self.assertIn("phase-loop roadmap warning", stderr.getvalue())
                self.assertIn("line", stderr.getvalue())
                self.assertIn("loose-match", stderr.getvalue())
                self.assertIn("Bad heading", stderr.getvalue())
                self.assertIn("suggested fix", stderr.getvalue())
                if "--json" in argv:
                    json.loads(stdout.getvalue())


_VALID_ROADMAP = """# Test Roadmap

## Context
context.

## Phases

### Phase 1 — Foundation (FOUND)
**Objective**
Do the thing.

**Exit criteria**
- [ ] it works

**Scope notes**
Decompose into 2 lanes.

**Key files**
- src/a.py

**Depends on**
- (none)

**Produces**
- IF-0-FOUND-1

## Top Interface-Freeze Gates
- IF-0-FOUND-1

## Phase Dependency DAG
FOUND

## Execution Notes
notes.

## Verification
verify.
"""


class RoadmapLintModuleTest(unittest.TestCase):
    """The full roadmap lint now lives in the always-installed runtime
    (phase_loop_runtime.roadmap_lint), exposed as `phase-loop validate-roadmap`.
    The skill-bundle script is a thin shim over it (A8)."""

    def test_lint_accepts_a_clean_roadmap(self):
        from phase_loop_runtime.roadmap_lint import lint_roadmap_text

        self.assertEqual(lint_roadmap_text(_VALID_ROADMAP), [])

    def test_lint_flags_missing_alias_headings_gates_and_root(self):
        from phase_loop_runtime.roadmap_lint import lint_roadmap_text

        errors = lint_roadmap_text("# Bad\n\n## Phases\n\n### Phase 1 — No Alias\n")
        codes = " ".join(errors)
        self.assertIn("(A)", codes)  # missing required headings
        self.assertIn("(B)", codes)  # invalid phase heading / no phases
        self.assertIn("(E)", codes)  # no root phases

    def test_lint_detects_dependency_cycle(self):
        from phase_loop_runtime.roadmap_lint import lint_roadmap_text

        cyclic = _VALID_ROADMAP.replace("- (none)", "- LATER") + (
            "\n### Phase 2 — Later (LATER)\n"
            "**Objective**\no\n\n**Exit criteria**\n- [ ] x\n\n**Scope notes**\n2 lanes\n\n"
            "**Key files**\n- src/b.py\n\n**Depends on**\n- FOUND\n\n**Produces**\n- IF-0-LATER-1\n"
        )
        # FOUND now depends on LATER and LATER depends on FOUND → cycle.
        errors = lint_roadmap_text(cyclic)
        self.assertTrue(any(e.startswith("(F)") for e in errors), errors)

    def test_validate_roadmap_cli_subcommand(self):
        # The CLI infers the repository as the roadmap's grandparent. A roadmap written
        # directly into a bare tempdir made that ``/tmp`` itself, whose mtime other xdist
        # workers change mid-validation ("root changed during validation",
        # agent-harness#987). Give it the layout the inference expects: a private
        # repo/specs/ directory nobody else touches.
        with tempfile.TemporaryDirectory() as td:
            specs = Path(td) / "repo" / "specs"
            specs.mkdir(parents=True)
            good = specs / "good.md"
            good.write_text(_VALID_ROADMAP, encoding="utf-8")
            bad = specs / "bad.md"
            bad.write_text("# Bad\n\n## Phases\n\n### Phase 1 — No Alias\n", encoding="utf-8")

            self.assertEqual(main(["validate-roadmap", str(good)]), 0)
            self.assertEqual(main(["validate-roadmap", "--roadmap", str(good)]), 0)
            self.assertEqual(main(["validate-roadmap", str(bad)]), 1)


    def test_validate_roadmap_skips_coherence_outside_a_git_work_tree(self):
        """agent-harness#1053: a roadmap loose in a non-git directory has no canonical
        repository; the inferred grandparent (here a bare tempdir, in the wild ``/tmp``)
        must not be validated as one. A coherence validator that would fail proves the
        check is skipped, not merely passing."""
        import phase_loop_runtime.roadmap_lint as roadmap_lint_module

        calls = []

        def _refuse(repo, required=False):
            calls.append((repo, required))
            raise roadmap_lint_module.RoadmapStatusError("must not run outside git")

        with tempfile.TemporaryDirectory() as td:
            specs = Path(td) / "loose" / "specs"
            specs.mkdir(parents=True)
            good = specs / "good.md"
            good.write_text(_VALID_ROADMAP, encoding="utf-8")
            err = io.StringIO()
            with patch.object(roadmap_lint_module, "validate_roadmap_status_coherence", _refuse), \
                    contextlib.redirect_stderr(err):
                self.assertEqual(main(["validate-roadmap", str(good)]), 0)
        self.assertEqual(calls, [])
        self.assertIn("not inside a git work tree", err.getvalue())

    def test_validate_roadmap_runs_coherence_inside_a_git_work_tree(self):
        """The other half: inside a git work tree the check still runs, required=True."""
        import phase_loop_runtime.roadmap_lint as roadmap_lint_module

        calls = []
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            (repo / "specs").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            good = repo / "specs" / "good.md"
            good.write_text(_VALID_ROADMAP, encoding="utf-8")
            with patch.object(roadmap_lint_module, "validate_roadmap_status_coherence",
                              lambda repo, required=False: calls.append((Path(repo).resolve(), required))):
                self.assertEqual(main(["validate-roadmap", str(good)]), 0)
            self.assertEqual(calls, [(repo.resolve(), True)])


    def _run_with_git(self, roadmap, git_script=None, extra_env=None):
        """validate-roadmap with a spy coherence validator; optionally a fake ``git`` first
        on PATH (``None`` script = git missing entirely). Returns the spy's calls."""
        import os
        import phase_loop_runtime.roadmap_lint as roadmap_lint_module

        calls = []
        env = dict(os.environ)
        with tempfile.TemporaryDirectory() as bindir:
            if git_script is not None:
                fake = Path(bindir) / "git"
                fake.write_text("#!/bin/sh\n" + git_script, encoding="utf-8")
                fake.chmod(0o755)
                env["PATH"] = bindir + os.pathsep + "/usr/bin:/bin"
            elif extra_env is None:
                env["PATH"] = bindir  # no git anywhere
            env.update(extra_env or {})
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(roadmap_lint_module, "validate_roadmap_status_coherence",
                                 lambda repo, required=False: calls.append(required)), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["validate-roadmap", str(roadmap)]), 0)
        return calls

    def _real_repo_roadmap(self, td):
        repo = Path(td) / "repo"
        (repo / "specs").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        roadmap = repo / "specs" / "good.md"
        roadmap.write_text(_VALID_ROADMAP, encoding="utf-8")
        return roadmap

    def test_an_undeterminable_git_answer_keeps_the_coherence_check(self):
        """#1054 r1 (all four seats): git missing, a safe.directory refusal or odd git
        output must keep the check inside a real repository (fail closed). The probe is
        structural now, so these hold without git being consulted at all."""
        with tempfile.TemporaryDirectory() as td:
            roadmap = self._real_repo_roadmap(td)
            self.assertEqual(self._run_with_git(roadmap, git_script=None), [True], "git missing")
            dubious = "echo \"fatal: detected dubious ownership in repository\" >&2; exit 128\n"
            self.assertEqual(self._run_with_git(roadmap, git_script=dubious), [True], "safe.directory")
            self.assertEqual(self._run_with_git(roadmap, git_script="echo false\n"), [True], "odd output")

    def test_structural_cases_from_review_round_2(self):
        """#1054 r2: an unreachable worktree ``.git`` FILE keeps the check; a repository
        whose path contains "not a git repository" keeps the check; a loose roadmap is
        skipped whatever the locale (no git output is parsed)."""
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td) / "wt"
            (wt / "specs").mkdir(parents=True)
            (wt / ".git").write_text("gitdir: /nonexistent/.git/worktrees/wt\n", encoding="utf-8")
            roadmap = wt / "specs" / "good.md"
            roadmap.write_text(_VALID_ROADMAP, encoding="utf-8")
            self.assertEqual(self._run_with_git(roadmap, extra_env={}), [True], "unreachable gitdir file")

            named = Path(td) / "not a git repository"
            (named / "specs").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(named)], check=True)
            roadmap = named / "specs" / "good.md"
            roadmap.write_text(_VALID_ROADMAP, encoding="utf-8")
            self.assertEqual(self._run_with_git(roadmap, extra_env={}), [True], "phrase in path")

            loose = Path(td) / "loose" / "specs"
            loose.mkdir(parents=True)
            roadmap = loose / "good.md"
            roadmap.write_text(_VALID_ROADMAP, encoding="utf-8")
            self.assertEqual(self._run_with_git(roadmap, extra_env={
                "LC_ALL": "de_DE.UTF-8", "LANGUAGE": "de"}), [], "localized")

    def test_an_inherited_git_dir_cannot_answer_for_the_roadmap(self):
        """GIT_DIR/GIT_WORK_TREE exported for ANOTHER repository must not make a loose
        roadmap look like it is inside a work tree (the probe ignores the environment)."""
        with tempfile.TemporaryDirectory() as td:
            other = Path(td) / "other"
            subprocess.run(["git", "init", "-q", str(other)], check=True)
            specs = Path(td) / "loose" / "specs"
            specs.mkdir(parents=True)
            roadmap = specs / "good.md"
            roadmap.write_text(_VALID_ROADMAP, encoding="utf-8")
            calls = self._run_with_git(roadmap, extra_env={
                "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)})
            self.assertEqual(calls, [])


_SECOND_PHASE = """### Phase 2 — Delivery (DELIVERY)
**Objective**
Ship the change.

**Exit criteria**
- [ ] it ships

**Scope notes**
Single lane.

**Key files**
- src/delivery.py

**Depends on**
- FOUND

**Produces**
- (none)

"""


@pytest.mark.parametrize(
    "heading,prefix",
    [
        ("### phase 2 — Delivery (DELIVERY)", ""),
        ("## Phase 2 — Delivery (DELIVERY)", ""),
        ("### Phase2 — Delivery (DELIVERY)", ""),
        ("### Phase 2 — Delivery (DELIVERY)", " "),
        ("### Phase 2 — Delivery (DELIVERY)", "\u00a0"),
        ("### Phase 2 — Delivery (DELIVERY)", "\ufeff"),
    ],
    ids=["case", "level", "spacing", "space-indent", "nbsp-indent", "bom-indent"],
)
def test_malformed_phase_cannot_silently_disappear(heading, prefix):
    from phase_loop_runtime.roadmap_lint import lint_roadmap_text

    clean = _VALID_ROADMAP.replace("## Top Interface-Freeze Gates", _SECOND_PHASE + "## Top Interface-Freeze Gates")
    assert lint_roadmap_text(clean) == []
    altered = _SECOND_PHASE.replace(_SECOND_PHASE.splitlines()[0], heading, 1)
    altered = "".join(prefix + line for line in altered.splitlines(keepends=True))
    text = clean.replace(_SECOND_PHASE, altered)
    line_number = text[:text.index(prefix + heading)].count("\n") + 1
    errors = lint_roadmap_text(text)
    assert any(f"(B) line {line_number}:" in error for error in errors), errors


def test_unrecognized_phase_heading_leaves_an_unclaimed_body_error():
    from phase_loop_runtime.roadmap_lint import lint_roadmap_text

    altered = _SECOND_PHASE.replace("### Phase 2 — Delivery (DELIVERY)", "### Delivery")
    text = _VALID_ROADMAP.replace("## Top Interface-Freeze Gates", altered + "## Top Interface-Freeze Gates")
    body_line = text[:text.index("**Key files**", text.index("### Delivery"))].count("\n") + 1
    errors = lint_roadmap_text(text)
    assert any(f"(B) line {body_line}:" in error for error in errors), errors


@pytest.mark.parametrize(
    "opening,inside,closing",
    [
        ("```markdown", "", "```"),
        ("~~~markdown", "", "~~~"),
        ("   ```markdown", "", "   ```"),
        ("  ~~~~markdown", "~~~\n", "~~~~~"),
        ("````markdown", "```\n", "`````"),
        ("```markdown", "~~~\n", "```"),
        ("~~~markdown", "```\n", "~~~"),
        ("```markdown", "``` not-a-closing-fence\n", "```"),
    ],
)
def test_fenced_phase_examples_are_not_parsed_or_linted(opening, inside, closing):
    from phase_loop_runtime.roadmap_lint import _extract_phases, lint_roadmap_text

    example = f"{opening}\n{inside}{_SECOND_PHASE}### phase 3 — Example (EXAMPLE)\n{closing}\n\n"
    text = _VALID_ROADMAP.replace("## Phases", example + "## Phases")
    assert lint_roadmap_text(text) == []
    assert [phase.alias for phase in _extract_phases(text)] == ["FOUND"]


def test_unclosed_fence_hides_examples_through_end_of_document():
    from phase_loop_runtime.roadmap_lint import _extract_phases, lint_roadmap_text

    text = _VALID_ROADMAP + "\n~~~markdown\n" + _SECOND_PHASE
    assert lint_roadmap_text(text) == []
    assert [phase.alias for phase in _extract_phases(text)] == ["FOUND"]


def test_phase_keeps_raw_fenced_source_immediately_after_heading():
    from phase_loop_runtime.roadmap_lint import _extract_phases, lint_roadmap_text

    example = "```markdown\n### Phase 99 — Example (EXAMPLE)\n```\n"
    text = _VALID_ROADMAP.replace("**Objective**", example + "**Objective**", 1)
    assert lint_roadmap_text(text) == []
    phases = _extract_phases(text)
    assert len(phases) == 1
    assert example in phases[0].raw_body
    assert phases[0].objective == "Do the thing."


def test_heading_error_line_number_survives_fenced_example():
    from phase_loop_runtime.roadmap_lint import lint_roadmap_text

    heading = "### phase 2 — Delivery (DELIVERY)"
    text = _VALID_ROADMAP.replace("## Phases", "```\n### Phase 99 — Example (EXAMPLE)\n```\n\n## Phases")
    text = text.replace("## Top Interface-Freeze Gates", _SECOND_PHASE.replace(_SECOND_PHASE.splitlines()[0], heading) + "## Top Interface-Freeze Gates")
    line_number = text[:text.index(heading)].count("\n") + 1
    assert any(f"(B) line {line_number}:" in error for error in lint_roadmap_text(text))


@pytest.mark.parametrize(
    "heading",
    [
        "### Phase 2 —\n```markdown\nexample\n```\nDelivery (DELIVERY)\n",
        "### Phase 2\n```\n```\n— Delivery (DELIVERY)\n",
        "### Phase 2 — Delivery (DELIVERY,\nannotation)\n",
    ],
    ids=["fence-after-dash", "fence-before-dash", "multiline-annotation"],
)
def test_phase_heading_cannot_span_source_lines(heading):
    from phase_loop_runtime.roadmap_lint import _extract_phases, lint_roadmap_text

    assert _extract_phases(heading) == []
    assert any(error.startswith("(B) line 1:") for error in lint_roadmap_text(heading))


@pytest.mark.parametrize("separator", ["\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
@pytest.mark.parametrize("side", ["before", "after"])
def test_non_lf_separator_cannot_silently_drop_a_phase(separator, side):
    from phase_loop_runtime.roadmap_lint import lint_roadmap_text

    text = _VALID_ROADMAP.replace("## Top Interface-Freeze Gates", _SECOND_PHASE + "## Top Interface-Freeze Gates")
    heading = "### Phase 2 — Delivery (DELIVERY)"
    if side == "before":
        text = text.replace("\n" + heading, separator + heading, 1)
    else:
        text = text.replace(heading + "\n", heading + separator, 1)
    line_number = text[:text.index(heading)].count("\n") + 1
    assert any(f"(B) line {line_number}:" in error for error in lint_roadmap_text(text))


@pytest.mark.parametrize("separator", ["\x85", "\u2028", "\x0c"])
def test_non_lf_separator_cannot_create_a_fence(separator):
    from phase_loop_runtime.roadmap_lint import _extract_phases, lint_roadmap_text

    text = f"Prose{separator}```markdown\n" + _VALID_ROADMAP
    assert [phase.alias for phase in _extract_phases(text)] == ["FOUND"]
    assert lint_roadmap_text(text) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_lf_and_crlf_keep_phase_and_raw_fenced_body(newline):
    from phase_loop_runtime.roadmap_lint import _extract_phases, lint_roadmap_text

    example = "~~~markdown\n### Phase 99 — Example (EXAMPLE)\n~~~\n"
    text = _VALID_ROADMAP.replace("**Objective**", example + "**Objective**", 1)
    text = text.replace("## Top Interface-Freeze Gates", _SECOND_PHASE + "## Top Interface-Freeze Gates")
    text = text.replace("\n", newline)
    phases = _extract_phases(text)
    assert [phase.alias for phase in phases] == ["FOUND", "DELIVERY"]
    assert example.replace("\n", newline) in phases[0].raw_body
    assert lint_roadmap_text(text) == []


@pytest.mark.parametrize(
    "heading",
    [
        "### Phase 2 —\n```markdown\nexample\n```\nDelivery (DELIVERY)",
        "### Phase 2\n```\n```\n— Delivery (DELIVERY)",
        "\u2028### Phase 2 — Delivery (DELIVERY)",
        "### Phase 2 — Delivery (DELIVERY)\u2028",
    ],
    ids=["fence-after-dash", "fence-before-dash", "separator-before", "separator-after"],
)
def test_standalone_validator_reports_heading_errors_without_traceback(tmp_path, heading):
    from phase_loop_runtime import roadmap_lint

    phase = _SECOND_PHASE.replace("### Phase 2 — Delivery (DELIVERY)", heading)
    text = _VALID_ROADMAP.replace("## Top Interface-Freeze Gates", phase + "## Top Interface-Freeze Gates")
    if heading.endswith("\u2028"):
        text = text.replace("\u2028\n", "\u2028", 1)
    path = tmp_path / "roadmap.md"
    path.write_bytes(text.encode("utf-8"))
    result = subprocess.run([sys.executable, roadmap_lint.__file__, str(path)], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "(B) line " in result.stderr
    assert "Traceback" not in result.stderr


def test_standalone_validator_normalizes_bare_cr_file_lines(tmp_path):
    from phase_loop_runtime import roadmap_lint

    text = _VALID_ROADMAP.replace("## Top Interface-Freeze Gates", _SECOND_PHASE + "## Top Interface-Freeze Gates")
    text = text.replace("\n### Phase 2", "\r### Phase 2", 1)
    path = tmp_path / "roadmap.md"
    path.write_bytes(text.encode("utf-8"))
    result = subprocess.run([sys.executable, roadmap_lint.__file__, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "2 phase(s)" in result.stdout


def test_versioned_roadmaps_still_lint_clean():
    from phase_loop_runtime.roadmap_lint import lint_roadmap_text

    repo = Path(__file__).resolve().parents[2]
    paths = sorted((repo / "specs").glob("phase-plans-v*.md"))
    assert paths
    findings = {str(path.relative_to(repo)): lint_roadmap_text(path.read_text(encoding="utf-8")) for path in paths}
    assert not {path: errors for path, errors in findings.items() if errors}


if __name__ == "__main__":
    unittest.main()
