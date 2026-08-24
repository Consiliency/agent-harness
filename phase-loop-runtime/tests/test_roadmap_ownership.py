"""Tests for the roadmap-ownership preflight (ah#633)."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase_loop_runtime import roadmap_ownership as ro

REPO_ROOT = Path(__file__).resolve().parents[2]

ROADMAP = """# Roadmap

## Context

x

## Architecture North Star

x

## Assumptions (fail-loud if wrong)

1. x

## Non-Goals

x

## Cross-Cutting Principles

x

## Top Interface-Freeze Gates

- IF-0-ALPHA-1 — a thing

## Phases

### Phase 0 — First Thing (ALPHA)

**Objective**
Do the first thing.

**Exit criteria**
- [ ] EC-ALPHA-1 — proven by `pytest`

**Scope notes**
decompose into 2 lanes; disjoint files.

**Non-goals**
None.

**Key files**
- `src/alpha.py`
- `src/shared.py`

**Depends on**
- (none)

**Produces**
- IF-0-ALPHA-1

### Phase 1 — Second Thing (BETA)

**Objective**
Do the second thing.

**Exit criteria**
- [ ] EC-BETA-1 — proven by `pytest`

**Scope notes**
decompose into 2 lanes; disjoint files.

**Non-goals**
None.

**Key files**
- `src/beta/`
- `src/shared.py`

**Depends on**
- ALPHA

**Produces**
- (none)

## Phase Dependency DAG

ALPHA -> BETA

## Execution Notes

x

## Verification

x
"""


def _repo(tmp: str, *, roadmap: str = ROADMAP, current: str | None = "ALPHA") -> Path:
    repo = Path(tmp)
    (repo / "specs").mkdir(parents=True, exist_ok=True)
    (repo / "specs" / "phase-plans-v10.md").write_text(roadmap)
    if current is not None:
        (repo / ".phase-loop").mkdir(exist_ok=True)
        (repo / ".phase-loop" / "state.json").write_text(
            json.dumps({"current_phase": current})
        )
    return repo


class TestOwnershipMap(unittest.TestCase):
    def test_the_motivating_case_would_have_been_caught(self):
        """ah#633's whole reason: this is the file whose edit cost a session.

        `phase_worktree_executor.py` is Phase 5 (SCHED) lane A in the LIVE roadmap.
        Nine commits were built against it and closed as superseded. The ownership
        data was present and machine-readable the entire time.
        """
        mapping = ro.ownership_map(
            (REPO_ROOT / "specs" / "phase-plans-v10.md").read_text()
        )
        owners = ro.owners_for(
            "phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py",
            mapping,
        )
        self.assertIn("SCHED", [p.alias for p in owners])

    def test_a_genuinely_unowned_path_has_no_owner(self):
        """`docs/TEAM-ONBOARDING.md` is claimed by no phase.

        This test previously used `entry_doc_check.py` as the "unowned" example,
        which was WRONG and passed only because the parser could not read
        annotated directory entries. GOVLEAN claims
        `phase-loop-runtime/src/phase_loop_runtime/` wholesale, so every runtime
        module is claimed. I had also concluded by hand that `entry_doc_check.py`
        was unowned -- the same blind spot, made twice, once in prose and once in
        code.
        """
        mapping = ro.ownership_map(
            (REPO_ROOT / "specs" / "phase-plans-v10.md").read_text()
        )
        self.assertEqual(ro.owners_for("docs/TEAM-ONBOARDING.md", mapping), [])

    def test_govlean_directory_claim_covers_every_runtime_module(self):
        """A single phase claiming the whole source tree is the signal/noise problem.

        GOVLEAN's `phase-loop-runtime/src/phase_loop_runtime/` entry means EVERY
        runtime change is "owned". Recorded as a test because it is the fact that
        decides whether this check can ever become blocking -- not a defect in the
        matcher, which is behaving correctly.
        """
        mapping = ro.ownership_map(
            (REPO_ROOT / "specs" / "phase-plans-v10.md").read_text()
        )
        for module in ("entry_doc_check.py", "panel_invoker.py", "runner.py"):
            owners = ro.owners_for(
                f"phase-loop-runtime/src/phase_loop_runtime/{module}", mapping
            )
            self.assertIn("GOVLEAN", [p.alias for p in owners], module)

    def test_a_path_can_have_several_owners(self):
        """Collapsing to one owner would silently drop a claim.

        `src/shared.py` is named by both phases in the fixture, and in the live
        roadmap `runner.py` is named by three. Reporting one would hide the others.
        """
        mapping = ro.ownership_map(ROADMAP)
        self.assertEqual(
            sorted(p.alias for p in ro.owners_for("src/shared.py", mapping)),
            ["ALPHA", "BETA"],
        )

    def test_directory_prefix_claims_files_beneath_it(self):
        """A phase claiming `src/beta/` owns what is under it."""
        mapping = ro.ownership_map(ROADMAP)
        self.assertEqual(
            [p.alias for p in ro.owners_for("src/beta/deep/thing.py", mapping)],
            ["BETA"],
        )

    def test_a_non_directory_owner_does_not_claim_by_string_prefix(self):
        """`src/alpha.py` must not claim `src/alpha.py.bak`.

        The prefix rule is deliberately gated on a trailing slash: a DIRECTORY
        claims what is beneath it, a FILE claims only itself. Without that gate a
        bare string-prefix match sweeps in neighbours.

        Choosing the input matters here. My first version used `src/betamax.py`
        against owner `src/beta/` -- but that startswith() is already False because
        of the slash, so the mutation changed nothing and the test passed either
        way. Caught by running the mutation instead of assuming it.

        Mutation that must kill this: replace the guarded prefix test with a bare
        `path.startswith(owned)`.
        """
        mapping = ro.ownership_map(ROADMAP)
        self.assertEqual(ro.owners_for("src/alpha.py.bak", mapping), [])

    def test_a_sibling_of_a_directory_owner_is_not_claimed(self):
        mapping = ro.ownership_map(ROADMAP)
        self.assertEqual(ro.owners_for("src/betamax.py", mapping), [])


class TestRealBulletShapes(unittest.TestCase):
    """The shapes that actually appear in `Key files`, all found by review.

    My first version handled only `` `path` `` and silently missed the rest. Its
    own dry-run reported "no changed path is claimed" for a PR editing two
    directories GOVLEAN claims -- a false negative from the check whose whole
    purpose is not missing ownership.
    """

    def test_annotated_directory_entry_is_read(self):
        """GOVLEAN writes: - `path/` (new evidence, lint, and governance modules)

        Mutation that must kill this: strip the whole bullet instead of taking
        the first backticked span.
        """
        mapping = ro.ownership_map(
            (REPO_ROOT / "specs" / "phase-plans-v10.md").read_text()
        )
        owners = ro.owners_for(
            "phase-loop-runtime/src/phase_loop_runtime/roadmap_ownership.py", mapping
        )
        self.assertIn("GOVLEAN", [p.alias for p in owners])

    def test_unbackticked_trailing_prose_entry_is_read(self):
        """GOVLEAN also writes: - `skills-src/` planner and roadmap skills ..."""
        self.assertEqual(
            ro._strip_token("`skills-src/` planner and roadmap skills plus outputs"),
            "skills-src/",
        )

    def test_glob_entry_claims_what_it_matches(self):
        """LEGIBLE claims `specs/phase-plans-v*.md`.

        Stored literally a glob matches nothing, so LEGIBLE's claim on every
        roadmap file was silently inert.

        Mutation that must kill this: drop the fnmatch branch from `_claims`.
        """
        mapping = ro.ownership_map(
            (REPO_ROOT / "specs" / "phase-plans-v10.md").read_text()
        )
        self.assertIn(
            "LEGIBLE",
            [p.alias for p in ro.owners_for("specs/phase-plans-v10.md", mapping)],
        )

    def test_glob_does_not_over_claim(self):
        self.assertFalse(ro._claims("specs/phase-plans-v*.md", "specs/other.md"))


class TestScopedClaims(unittest.TestCase):
    def test_a_qualified_claim_reports_its_qualification(self):
        """GOVLEAN's directory claims are SCOPED by a parenthetical.

        Discarding it turns "part of this directory" into "all of it" -- which is
        how this module briefly had GOVLEAN owning the whole source tree. The
        matcher cannot tell which part, so it must surface the prose.

        Mutation that must kill this: drop the note from _split_token.
        """
        path, note = ro._split_token(
            "`phase-loop-runtime/src/phase_loop_runtime/` (new evidence, lint, and "
            "governance modules)"
        )
        self.assertEqual(path, "phase-loop-runtime/src/phase_loop_runtime/")
        self.assertIn("new evidence", note)

    def test_render_surfaces_the_qualification(self):
        out = ro.render(
            [ro.Ownership("a.py", "GOVLEAN", "Lean Governance", False, "(only new modules)")],
            disposition=False,
        )
        self.assertIn("SCOPED", out)
        self.assertIn("only new modules", out)


class TestExpectedClaims(unittest.TestCase):
    """Near-universal claims are DEMOTED, never dropped.

    `CHANGELOG.md` is claimed by RELEASE while docs-audit REQUIRES a CHANGELOG
    entry for public-surface changes, so the two rules together make the flag fire
    on nearly every PR. A warning that always fires is tuned out within a week --
    and then the substantive findings underneath it are tuned out too.
    """

    def _own(self, path, alias="RELEASE"):
        return ro.Ownership(path, alias, "Pilots and Governed Release", False)

    def test_expected_claim_is_moved_below_the_substantive_findings(self):
        out = ro.render(
            [self._own("CHANGELOG.md"), self._own("src/real.py", "SCHED")],
            disposition=False,
        )
        self.assertLess(out.index("src/real.py"), out.index("CHANGELOG.md"))
        self.assertIn("Expected", out)

    def test_expected_claim_is_still_reported_with_its_reason(self):
        """Demoted is not hidden.

        Mutation that must kill this: filter expected claims out entirely instead
        of moving them. A reader deciding whether to add a disposition needs to
        see the claim; suppressing it would be a worse defect than the noise.
        """
        out = ro.render([self._own("CHANGELOG.md")], disposition=False)
        self.assertIn("CHANGELOG.md", out)
        self.assertIn("docs-audit requires an entry", out)

    def test_only_expected_claims_reads_as_OK_not_as_findings(self):
        out = ro.render([self._own("CHANGELOG.md")], disposition=False)
        self.assertIn("no notable claims", out)

    def test_the_count_in_the_headline_excludes_expected(self):
        """The headline number must be the actionable one.

        Mutation that must kill this: count `found` instead of `notable`.
        """
        out = ro.render(
            [self._own("CHANGELOG.md"), self._own("src/real.py", "SCHED")],
            disposition=False,
        )
        self.assertIn("1 claimed path(s)", out)


class TestPartialDrift(unittest.TestCase):
    def test_one_phase_losing_key_files_raises(self):
        """The third mutation, found by review: PARTIAL drift passed silently.

        The all-or-nothing guards only see "every phase gone" or "every entry
        gone". Removing ONE phase's `**Key files**` heading left the map looking
        healthy while that phase's claims vanished -- exactly the silent-wrong
        answer this check must never give.

        Mutation that must kill this: drop the `barren` check.
        """
        lines = ROADMAP.splitlines()
        out, skipping = [], False
        for line in lines:
            if line == "**Key files**" and not skipping:
                skipping = True   # drop ALPHA's heading and its bullets only
                continue
            if skipping:
                if line.startswith("- `"):
                    continue
                skipping = False
            out.append(line)
        with self.assertRaises(ro.RoadmapUnreadable) as caught:
            ro.ownership_map("\n".join(out))
        self.assertIn("ALPHA", str(caught.exception))


class TestUsesCanonicalAuthority(unittest.TestCase):
    def test_resolves_the_declared_active_roadmap(self):
        """Delegates to the repo's own registry rather than guessing.

        Hand-rolling "highest version number" picks a SUPERSEDED roadmap the
        moment a higher-numbered one is delivered, then audits against a map
        nobody works from.
        """
        self.assertEqual(ro.resolve_roadmap(REPO_ROOT).name, "phase-plans-v10.md")

    def test_unreadable_repo_raises_rather_than_guessing(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ro.RoadmapUnreadable):
                ro.resolve_roadmap(Path(tmp))


class TestFailsLoudly(unittest.TestCase):
    """A preflight that silently passes when it cannot read its map is the bug."""

    def test_zero_phases_raises_rather_than_reporting_nothing_owned(self):
        """Mutation that must kill this: return {} instead of raising.

        Reporting "no changed path is claimed" when the parse failed would pass
        EVERY PR — the exact absence-reads-as-success class this repo keeps hitting.
        """
        with self.assertRaises(ro.RoadmapUnreadable) as caught:
            ro.ownership_map("# Not a roadmap\n\nnothing here.\n")
        # Assert WHICH guard fired. The two are redundant for this input -- zero
        # phases also yields an empty mapping -- so without pinning the message,
        # deleting the first guard leaves every test green. Verified by mutation.
        self.assertIn("zero phases", str(caught.exception))

    def test_phases_without_key_files_raises(self):
        stripped = "\n".join(
            line
            for line in ROADMAP.splitlines()
            if not line.startswith("- `src/") and line != "**Key files**"
        )
        with self.assertRaises(ro.RoadmapUnreadable) as caught:
            ro.ownership_map(stripped)
        self.assertIn("no Key files", str(caught.exception))

    def test_unresolvable_base_raises_rather_than_reporting_no_changes(self):
        """The THIRD operand, unpinned until review found it.

        The suite pinned roadmap resolution and parsing, but not `git diff`.
        Replacing that guard with `return []` left all tests green while the CLI
        printed "OK — no changed path is claimed" and exited 0 on an unresolvable
        base. A check that reports "nothing owned" because it could not look is
        the exact failure this module exists to prevent, one operand deeper.

        Mutation that must kill this: swallow the git failure and return [].
        """
        with TemporaryDirectory() as tmp:
            repo = _repo(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "t@t"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "t"], check=True)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "seed"], check=True)
            with self.assertRaises(ro.RoadmapUnreadable):
                ro.changed_paths(repo, "no-such-ref-anywhere")

    def test_cli_exits_two_on_unresolvable_base(self):
        with TemporaryDirectory() as tmp:
            _repo(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "t@t"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "t"], check=True)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "seed"], check=True)
            self.assertEqual(
                ro.main(["roadmap_ownership", "--repo", tmp, "--base", "no-such-ref"]),
                2,
            )

    def test_missing_roadmap_raises(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ro.RoadmapUnreadable):
                ro.resolve_roadmap(Path(tmp))

    def test_cli_returns_nonzero_when_it_cannot_evaluate(self):
        """The check failing must not look like the PR passing."""
        with TemporaryDirectory() as tmp:
            self.assertEqual(ro.main(["roadmap_ownership", "--repo", tmp]), 2)


class TestDisposition(unittest.TestCase):
    def test_trailer_is_detected(self):
        self.assertTrue(
            ro.has_disposition("Some body\n\nRoadmap-Disposition: urgent data-loss fix\n")
        )

    def test_absent_trailer(self):
        self.assertFalse(ro.has_disposition("Some body with no trailer\n"))

    def test_mention_in_prose_does_not_count(self):
        """Only a trailer at line start counts, not the words in a sentence."""
        self.assertFalse(
            ro.has_disposition("I considered adding a Roadmap-Disposition: but did not.")
        )


class TestAuditEndToEnd(unittest.TestCase):
    def test_audit_reports_a_claimed_changed_file(self):
        with TemporaryDirectory() as tmp:
            repo = _repo(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q", "-b", "main"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.email", "t@t"], check=True)
            subprocess.run(["git", "-C", tmp, "config", "user.name", "t"], check=True)
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "seed"], check=True)
            base = subprocess.run(
                ["git", "-C", tmp, "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            (repo / "src").mkdir(exist_ok=True)
            (repo / "src" / "alpha.py").write_text("x = 1\n")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "touch alpha"], check=True)

            found = ro.audit(repo, base)
            self.assertEqual([(o.path, o.phase_alias) for o in found],
                             [("src/alpha.py", "ALPHA")])
            self.assertTrue(found[0].is_current)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
