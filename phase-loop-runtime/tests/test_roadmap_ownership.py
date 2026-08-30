"""Tests for the roadmap-ownership preflight (ah#633)."""
from __future__ import annotations

import json
import io
import subprocess
from contextlib import redirect_stdout
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


ACTIVE_BANNER = ("> **Status (2026-01-03): ACTIVE — created this date, "
                 "nothing executed yet.**")
ROADMAP_ACTIVE = ROADMAP.replace("# Roadmap", "# Roadmap\n\n" + ACTIVE_BANNER, 1)


def _registry(selected: str, entries) -> str:
    """A canonical `roadmap_status_manifest.v1` document.

    The fixtures previously wrote a bare `{"roadmaps": [...]}`, which the repo's
    own parser rejects -- so they were exercising a registry shape this codebase
    never produces.
    """

    return json.dumps({
        "schema": "roadmap_status_manifest.v1",
        "selected_roadmap": selected,
        "roadmaps": sorted(
            ({"path": p, "status": st} for p, st in entries),
            key=lambda e: e["path"],
        ),
    })


def _own(path: str, alias: str, name: str = "First Thing", note: str = "") -> ro.Ownership:
    """An Ownership for renderer tests, which take the structure not the repo."""
    return ro.Ownership(
        path=path, phase_alias=alias, phase_name=name, is_current=False, note=note
    )


def _repo_with_two_phases(tmp: str, roadmap: str = ROADMAP) -> Path:
    """A repo carrying the shared ROADMAP fixture.

    ALPHA claims ``src/alpha.py`` and ``src/shared.py``; BETA claims ``src/beta/``
    and ``src/shared.py``.

    The docstring used to promise a roadmap this function built, via a
    ``ROADMAP.replace("- `src/alpha.py`", "- `src/alpha.py`")`` that replaced a
    string with itself. The tests passed because the shared fixture already said
    what was needed, so the no-op was invisible -- but any test trusting the
    docstring's "BETA owns src/beta.py" was reading a claim nothing established.
    ``roadmap`` is a real parameter now, for cases needing a variant.
    """
    repo = Path(tmp)
    (repo / "specs").mkdir(parents=True, exist_ok=True)
    (repo / "specs" / "phase-plans-v10.md").write_text(roadmap)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "alpha.py").write_text("x = 1\n")
    return repo


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


class TestReplayReport(unittest.TestCase):
    """`--report` is the graduation instrument (ah#633)."""

    def _repo_with_history(self, tmp):
        repo = _repo(tmp)
        run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                        capture_output=True)
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        run("add", "-A")
        run("commit", "-qm", "seed")
        run("checkout", "-qb", "feature")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "alpha.py").write_text("x = 1\n")
        run("add", "-A")
        run("commit", "-qm", "touch alpha")
        run("checkout", "-q", "main")
        run("merge", "--no-ff", "-q", "feature", "-m", "Merge feature")
        return repo

    def test_replay_flags_a_historical_merge(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo_with_history(tmp)
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md")
            # First-parent walks the whole mainline, so the root commit is here
            # too -- unscorable, and counted as such.
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].notable, 1)
            self.assertIn("ALPHA", rows[0].phases)
            self.assertIn("root commit", rows[1].skipped_reason)

    def test_unscorable_merges_are_counted_not_dropped(self):
        """A shrinking denominator would flatter the rate.

        The rate is the ONE number this exists to produce honestly, so a commit
        whose roadmap cannot be read is reported with a reason rather than
        silently excluded from `total`.

        Mutation that must kill this: `continue` instead of appending a row with
        a skipped_reason.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo_with_history(tmp)
            # Remove the roadmap so NOTHING resolves at any commit. Passing a
            # bogus relative path is no longer enough: the resolver is
            # authoritative and finds the fixture's real roadmap regardless, so
            # the old form silently stopped testing the unscorable path.
            (repo / "specs" / "phase-plans-v10.md").unlink()
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           capture_output=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "drop roadmap"],
                           check=True, capture_output=True)
            rows = ro.replay(repo, 5, "specs/does-not-exist.md")
            # Every mainline entry is present: the roadmap-less commit and the
            # root are unscorable, the middle one still scores. Nothing is
            # dropped -- that is the property under test.
            self.assertEqual(len(rows), 3, "no row may be silently dropped")
            self.assertTrue(any(r.skipped_reason for r in rows))
            self.assertIn("unscorable", ro.render_report(rows))
            # And an all-unscorable set must read as zero scored rather than
            # quietly reporting a rate over an empty denominator.
            allskipped = [ro.ReplayRow(r.sha, r.subject, 0, 0, (), "x") for r in rows]
            self.assertIn("0 scored", ro.render_report(allskipped))

    def test_rate_is_computed_over_scored_only(self):
        rows = [
            ro.ReplayRow("a" * 40, "one", 1, 0, ("SCHED",)),
            ro.ReplayRow("b" * 40, "two", 0, 1, ()),
            ro.ReplayRow("c" * 40, "three", 0, 0, (), "roadmap absent at commit"),
        ]
        out = ro.render_report(rows)
        self.assertIn("1/2 (50%)", out)

    def test_a_SQUASH_merged_pr_is_sampled_too(self):
        """The sampling bug this file exists to prevent (found pre-merge).

        The first version used `--merges`, which samples ONLY merge commits. This
        repo lands PRs both ways -- the other agent's arrive as merge commits,
        mine arrive squashed -- so my own ah#644 and ah#650 were invisible to my
        own measurement. A biased population silently corrupts the one number
        this tool produces.

        Mutation that must kill this: `--merges` instead of `--first-parent`.
        A squash lands as a plain non-merge commit on the mainline, so under
        `--merges` this row disappears entirely and the count drops.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo_with_history(tmp)
            # A squash-merged PR: one ordinary commit directly on main.
            (repo / "src" / "alpha.py").write_text("x = 2\n")
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           capture_output=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "squashed pr (#99)"],
                           check=True, capture_output=True)
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md")
            squashed = [r for r in rows if "squashed pr" in r.subject]
            self.assertEqual(len(squashed), 1, "a squash-merged PR must be sampled")
            self.assertEqual(squashed[0].notable, 1)

    def test_replay_reads_the_roadmap_AT_each_commit(self):
        """Not today's roadmap. `Key files` lists change over time, so measuring
        history against the current roadmap answers "what would fire now" when the
        question is "what WOULD have fired".

        Mutation that must kill this: read the roadmap from the working tree.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo_with_history(tmp)
            # The roadmap change must be COMMITTED, or `HEAD:` and `{sha}:` return
            # the same bytes and the mutation is invisible. My first version only
            # wrote the working tree, so this test passed under the very mutation
            # it names -- the sixth vacuous assertion of this session, caught by
            # running the mutation rather than trusting the setup.
            (repo / "specs" / "phase-plans-v10.md").write_text(
                ROADMAP.replace("- `src/alpha.py`", "- `src/unrelated.py`")
            )
            subprocess.run(["git", "-C", tmp, "add", "-A"], check=True,
                           capture_output=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "retarget roadmap"],
                           check=True, capture_output=True)
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md")
            # Target the merge by SUBJECT, not by index: the retarget commit is
            # itself on the mainline and is the newest row.
            merge = [r for r in rows if r.subject == "Merge feature"]
            self.assertEqual(len(merge), 1)
            self.assertEqual(merge[0].notable, 1, "must use the roadmap at that commit")


class TestCounterfactual(unittest.TestCase):
    """Leave-one-phase-out: the statistic the graduation decision actually needs.

    The headline rate says "blocking is not viable now". Read alone it invites
    the inference "so narrow the dominant claim and it becomes viable" -- which
    the data does not support. On this repo the real numbers are 82% headline,
    25% with the dominant phase removed.
    """

    def test_rows_claimed_by_another_phase_SURVIVE_removing_the_dominant(self):
        """Mutation that must kill this: treat every row mentioning the dominant
        phase as cleared (e.g. filter on `dominant in r.phases`) instead of
        checking whether any OTHER phase still claims it. That mutation reports
        0% and would license exactly the wrong decision.
        """
        rows = [
            # dominant-only: clears when GOVLEAN claims nothing
            ro.ReplayRow("a" * 40, "one", 1, 0, ("GOVLEAN",)),
            ro.ReplayRow("b" * 40, "two", 1, 0, ("GOVLEAN",)),
            # also claimed by REVIEWTRUTH: survives
            ro.ReplayRow("c" * 40, "three", 2, 0, ("GOVLEAN", "REVIEWTRUTH")),
        ]
        out = ro.render_report(rows)
        self.assertIn("if GOVLEAN claimed nothing", out)
        self.assertIn("would STILL flag: 1/3", out)
        self.assertIn("NOT SUFFICIENT", out)

    def test_a_sole_cause_is_reported_as_a_sole_cause(self):
        """The opposite verdict must also be reachable, or the message is a
        constant rather than a finding.
        """
        rows = [
            ro.ReplayRow("a" * 40, "one", 1, 0, ("GOVLEAN",)),
            ro.ReplayRow("b" * 40, "two", 1, 0, ("GOVLEAN",)),
        ]
        out = ro.render_report(rows)
        self.assertIn("would STILL flag: 0/2", out)
        self.assertIn("sole cause", out)
        self.assertNotIn("NOT SUFFICIENT", out)


class TestCounterfactualPicksTheRelievablePhase(unittest.TestCase):
    """ah#683: rank by rows a phase claims ALONE, not by how often it appears.

    A phase can appear on more rows than any other while sole-claiming none of
    them -- narrowing it then clears nothing. The counterfactual exists to steer
    remediation, so it must name the phase actually worth narrowing.
    """

    def _rows(self):
        # WIDE appears on 6 rows but NEVER alone -- removing it clears nothing.
        # NARROW appears on 3 and owns all 3 alone -- removing it clears 3.
        # WIDE must out-count every other alias outright, or the frequency
        # ranking breaks the tie alphabetically and the fixture stops
        # demonstrating the divergence it names.
        rows = [ro.ReplayRow(f"{i:040x}", f"co{i}", 1, 0, ("WIDE", "OTHER"))
                for i in range(5)]
        rows += [ro.ReplayRow(f"{80:040x}", "co5", 1, 0, ("WIDE", "THIRD"))]
        rows += [ro.ReplayRow(f"{i+90:040x}", f"solo{i}", 1, 0, ("NARROW",))
                 for i in range(3)]
        return rows

    def test_the_phase_named_is_the_one_whose_removal_clears_the_most(self):
        """Mutation that must kill this: rank by frequency, i.e.
        `sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]`.
        That picks WIDE (6 appearances vs 3) and reports 9/9 still flagged --
        pointing remediation at a phase that cannot relieve a single change.
        """
        out = ro.render_report(self._rows())
        self.assertIn("if NARROW claimed nothing", out)
        self.assertNotIn("if WIDE claimed nothing", out)
        self.assertIn("would STILL flag: 6/9", out)

    def test_frequency_would_have_named_the_useless_phase(self):
        """Pins the divergence itself, so the fixture cannot silently drift into
        a shape where both rankings agree and the test stops discriminating.
        """
        rows = self._rows()
        flagged = [r for r in rows if r.notable]
        counts = {}
        for r in flagged:
            for a in r.phases:
                counts[a] = counts.get(a, 0) + 1
        by_frequency = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        self.assertEqual(by_frequency, "WIDE", "fixture must make the rankings disagree")
        self.assertEqual(ro._most_relievable_phase(flagged, counts), "NARROW")

    def test_with_no_sole_claims_the_tiebreak_is_frequency_not_alphabet(self):
        """With nothing solely claimed, every phase scores 0 and the SECOND key
        decides. It must be frequency, so the report still names the phase a
        reader would expect rather than whichever alias sorts first.

        The fixture deliberately makes the most-frequent alias sort LAST, or the
        two orderings agree and the test cannot tell them apart -- which is
        exactly how my first version of it passed under the mutation it names.

        Mutation that must kill this: drop `-counts[a]`, leaving `(-sole, a)`.
        """
        rows = [ro.ReplayRow(f"{i:040x}", f"r{i}", 1, 0, ("ZETA", "ALPHA"))
                for i in range(4)]
        rows += [ro.ReplayRow(f"{i+90:040x}", f"s{i}", 1, 0, ("ZETA", "BETA"))
                 for i in range(2)]
        flagged = list(rows)
        counts = {}
        for r in flagged:
            for a in r.phases:
                counts[a] = counts.get(a, 0) + 1
        self.assertEqual(counts["ZETA"], 6)
        self.assertEqual(counts["ALPHA"], 4)
        self.assertEqual(ro._most_relievable_phase(flagged, counts), "ZETA",
                         "frequency must break the tie, not alphabetical order")

    def test_the_real_repo_shape_is_unaffected(self):
        """Where one phase dominates -- the current data -- both rankings agree,
        so this refinement must not move the published figure.
        """
        rows = [ro.ReplayRow(f"{i:040x}", f"g{i}", 1, 0, ("GOVLEAN",))
                for i in range(23)]
        rows += [ro.ReplayRow(f"{i+90:040x}", f"m{i}", 2, 0, ("GOVLEAN", "OTHER"))
                 for i in range(10)]
        # The 7 scored-but-unflagged rows matter: the rate's denominator is
        # SCORED rows, not flagged ones. Without them the fixture reports 10/33
        # while the published figure is 10/40, so a test named for the real
        # shape would not have reproduced it.
        rows += [ro.ReplayRow(f"{i+200:040x}", f"clean{i}", 0, 0, ())
                 for i in range(7)]
        out = ro.render_report(rows)
        self.assertIn("if GOVLEAN claimed nothing", out)
        self.assertIn("would STILL flag: 10/40 (25%)", out)
        self.assertIn("would have flagged: 33/40 (82%)", out)


class TestReportCliContract(unittest.TestCase):
    def test_report_zero_does_not_fall_through_to_audit_mode(self):
        """`--report 0` is falsy. `if args.report:` silently ran the ordinary
        audit instead -- answering a question the operator did not ask.

        Mutation that must kill this: `is not None` -> truthiness. Audit mode
        prints the claim report, never the replay header -- so the assertion on
        the header, not the exit code, is what pins the branch.
        """
        with TemporaryDirectory() as tmp:
            repo = _repo(tmp)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ro.main(["prog", "--repo", str(repo), "--report", "0",
                              "--base", "main"])
            # Reaching replay is the point; the exit code is 2 because a report
            # over zero changes produced no measurement, and the fail-closed
            # promise has no exception for the empty case.
            self.assertEqual(rc, 2)
            self.assertIn("0 landed change(s) replayed", buf.getvalue())

    def test_a_report_that_scored_NOTHING_exits_nonzero(self):
        """An instrument that produced no number must not report success.

        Mutation that must kill this: `return 0` unconditionally. The rows all
        carry a skipped_reason, so the report prints "0 scored" -- which under
        exit 0 reads as "measured, and it was fine".
        """
        with TemporaryDirectory() as tmp:
            repo = _repo(tmp)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            # ONE commit: the only mainline entry is the root, which has no
            # parent to diff and is therefore unscorable. Nothing scores.
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ro.main(["prog", "--repo", str(repo), "--report", "5",
                              "--base", "main"])
            self.assertIn("0 scored", buf.getvalue())
            self.assertEqual(rc, 2, "an unmeasured report must not exit 0")


class TestPopulationIsWhatLanded(unittest.TestCase):
    """The instrument must measure the MERGE TARGET, not the current branch.

    Found by the codex seat. With no revision, `git log` walks HEAD: run from a
    feature branch, the PR's own unlanded commits occupy the top of the window
    and displace real landings. Same sampling defect as `--merges`, one level up
    -- and it silently redefines the population the headline rate describes.
    """

    def test_feature_branch_commits_are_NOT_sampled_as_landed(self):
        """Mutation that must kill this: drop `rev` from the git log argv (or
        pass "HEAD"), which is exactly the pre-fix code.
        """
        with TemporaryDirectory() as tmp:
            repo = _repo(tmp)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            (repo / "src").mkdir(exist_ok=True)
            (repo / "src" / "alpha.py").write_text("x = 1\n")
            run("add", "-A")
            run("commit", "-qm", "LANDED on main")
            run("checkout", "-qb", "feature")
            (repo / "src" / "alpha.py").write_text("x = 2\n")
            run("add", "-A")
            run("commit", "-qm", "UNLANDED branch work")

            # Standing on the feature branch, sampling the merge target.
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            subjects = [r.subject for r in rows]
            self.assertIn("LANDED on main", subjects)
            self.assertNotIn("UNLANDED branch work", subjects,
                             "an unlanded commit must never count as a landing")


class TestRoadmapAuthorityIsHistorical(unittest.TestCase):
    """WHICH roadmap governed is itself versioned (codex seat, P1).

    Resolving the path once from HEAD and reading it at every commit is wrong
    across a version flip: pre-flip commits read as "roadmap absent" and get
    ejected from the denominator the rate depends on.
    """

    def test_a_pre_flip_commit_is_scored_against_the_roadmap_that_governed_it(self):
        """Mutation that must kill this: make `_roadmap_rel_at` return the
        fallback unconditionally. The pre-flip commit then looks for v10, which
        does not exist at that sha, and becomes unscorable instead of flagged.
        """
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "specs").mkdir(parents=True, exist_ok=True)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            # Era 1: v9 is the active roadmap and it claims src/alpha.py.
            (repo / "specs" / "phase-plans-v9.md").write_text(ROADMAP_ACTIVE)
            (repo / "specs" / "roadmap-status.json").write_text(
                _registry("specs/phase-plans-v9.md",
                          [("specs/phase-plans-v9.md", "active")])
            )
            run("add", "-A")
            run("commit", "-qm", "seed v9 era")
            (repo / "src").mkdir(exist_ok=True)
            (repo / "src" / "alpha.py").write_text("x = 1\n")
            run("add", "-A")
            run("commit", "-qm", "change under v9")
            # Era 2: flip to v10. v9 is gone; v10 exists only from here on.
            (repo / "specs" / "phase-plans-v9.md").unlink()
            (repo / "specs" / "phase-plans-v10.md").write_text(ROADMAP_ACTIVE)
            (repo / "specs" / "roadmap-status.json").write_text(
                _registry("specs/phase-plans-v10.md",
                          [("specs/phase-plans-v10.md", "active")])
            )
            run("add", "-A")
            run("commit", "-qm", "flip to v10")

            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            under_v9 = [r for r in rows if r.subject == "change under v9"]
            self.assertEqual(len(under_v9), 1)
            self.assertFalse(under_v9[0].skipped_reason,
                             "must resolve v9 at that commit, not today's v10")
            self.assertEqual(under_v9[0].notable, 1)


class TestRegistryIncoherenceIsDisclosed(unittest.TestCase):
    """A present-but-incoherent registry must not fail open (grok seat).

    Everywhere else this module counts what it cannot read and says why. Falling
    back to HEAD's roadmap would score the commit against a roadmap its own
    registry did not name -- a wrong number, silently.
    """

    def _repo_with_registry(self, tmp, registry_text):
        repo = Path(tmp)
        (repo / "specs").mkdir(parents=True, exist_ok=True)
        (repo / "specs" / "phase-plans-v10.md").write_text(ROADMAP)
        (repo / "specs" / "roadmap-status.json").write_text(registry_text)
        run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                        capture_output=True)
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        run("add", "-A")
        run("commit", "-qm", "seed")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "alpha.py").write_text("x = 1\n")
        run("add", "-A")
        run("commit", "-qm", "the change")
        return repo

    def test_two_active_roadmaps_is_unscorable_not_silently_scored(self):
        """Mutation that must kill this: return the fallback instead of a reason.
        The row would then be SCORED (notable=1) against HEAD's roadmap.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo_with_registry(tmp, _registry(
                "specs/phase-plans-v10.md",
                [("specs/phase-plans-v10.md", "active"),
                 ("specs/phase-plans-v9.md", "active")],
            ))
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertIn("authority incoherent", row.skipped_reason)
            self.assertEqual(row.notable, 0)

    def test_unreadable_registry_is_unscorable_not_silently_scored(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo_with_registry(tmp, "{not json")
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertIn("authority incoherent", row.skipped_reason)

    def test_an_ABSENT_registry_still_falls_back_and_scores(self):
        """The fallback must survive: the registry-less fixtures across this
        file depend on it, and a legacy repo is not an error.
        """
        with TemporaryDirectory() as tmp:
            repo = _repo(tmp)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            (repo / "src").mkdir(exist_ok=True)
            (repo / "src" / "alpha.py").write_text("x = 1\n")
            run("add", "-A")
            run("commit", "-qm", "the change")
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertFalse(row.skipped_reason)
            self.assertEqual(row.notable, 1)


class TestDominantIsNotAlwaysTheConstraint(unittest.TestCase):
    def test_when_removing_it_changes_nothing_it_is_not_called_necessary(self):
        """"Necessary but not sufficient" is false when every flagged row has
        another owner: removing the dominant phase changes nothing, so calling
        it necessary would misdirect the remediation.

        Mutation that must kill this: collapse the branch back to the single
        `if remaining:` message.
        """
        rows = [
            ro.ReplayRow("a" * 40, "one", 2, 0, ("GOVLEAN", "SCHED")),
            ro.ReplayRow("b" * 40, "two", 2, 0, ("GOVLEAN", "SCHED")),
        ]
        out = ro.render_report(rows)
        self.assertIn("NOT the binding constraint", out)
        self.assertNotIn("NECESSARY but NOT SUFFICIENT", out)


class TestPreRegistryEraResolution(unittest.TestCase):
    """Before the registry existed, the roadmap was declared by BANNER.

    Codex seat, round 2: falling back to today's roadmap path for pre-registry
    commits both loses them from the denominator and states something false
    ("roadmap absent") about history that plainly contains roadmaps.
    """

    def _era(self, tmp, banners):
        repo = Path(tmp)
        (repo / "specs").mkdir(parents=True, exist_ok=True)
        for name, status in banners:
            body = ROADMAP if status is None else ROADMAP.replace(
                "# Roadmap", f"# Roadmap\n\n{status}", 1)
            (repo / "specs" / name).write_text(body)
        run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                        capture_output=True)
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        run("add", "-A")
        run("commit", "-qm", "seed")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "alpha.py").write_text("x = 1\n")
        run("add", "-A")
        run("commit", "-qm", "the change")
        return repo

    def test_the_banner_declared_roadmap_is_used_when_no_registry_exists(self):
        """Mutation that must kill this: return the fallback instead of
        consulting banners. The fallback path names v10, which does not exist
        here, so the row would read "roadmap absent" instead of scoring.
        """
        with TemporaryDirectory() as tmp:
            repo = self._era(tmp, [
                ("phase-plans-v8.md",
                 "> # DELIVERED — CLOSED (assessed 2026-01-02)"),
                ("phase-plans-v9.md",
                 "> **Status (2026-01-03): ACTIVE — created this date, "
                 "nothing executed yet.**"),
            ])
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertFalse(row.skipped_reason,
                             "v9 declares itself active and must be used")
            self.assertEqual(row.notable, 1)

    def test_no_banner_declares_active_is_disclosed_with_the_real_reason(self):
        """The honest disclosure matters as much as the resolution: this repo's
        own pre-registry commits carry nine roadmaps and NO active banner, and
        reporting that as "roadmap absent" is simply false.
        """
        with TemporaryDirectory() as tmp:
            repo = self._era(tmp, [("phase-plans-v8.md", None),
                                   ("phase-plans-v9.md", None)])
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertIn("no active roadmap declared", row.skipped_reason)
            self.assertNotIn("absent", row.skipped_reason)

    def test_a_registry_selecting_a_roadmap_it_does_not_mark_active_is_rejected(self):
        """A selection contradicting the manifest's own status records is
        rejected, not scored (codex seat).

        This is caught by the repo's canonical parser -- which is exactly the
        argument for reusing it instead of the private JSON reader this had
        before, where such a registry was silently accepted.

        Mutation that must kill this: fall back to the HEAD path when the
        manifest is rejected, which scores the commit anyway.
        """
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "specs").mkdir(parents=True, exist_ok=True)
            (repo / "specs" / "phase-plans-v10.md").write_text(ROADMAP)
            (repo / "specs" / "phase-plans-v9.md").write_text(ROADMAP)
            (repo / "specs" / "roadmap-status.json").write_text(_registry(
                "specs/phase-plans-v10.md",
                [("specs/phase-plans-v10.md", "superseded"),
                 ("specs/phase-plans-v9.md", "active")],
            ))
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            (repo / "src").mkdir(exist_ok=True)
            (repo / "src" / "alpha.py").write_text("x = 1\n")
            run("add", "-A")
            run("commit", "-qm", "the change")
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertIn("authority incoherent", row.skipped_reason)
            self.assertEqual(row.notable, 0)


class TestRegistryIsNotAuthorityByItself(unittest.TestCase):
    """Schema-valid registry != authority (codex seat, round 3).

    `parse_roadmap_status_manifest` deliberately does NOT check banner
    coherence; `read_roadmap_status` is the authority reader and does both legs.
    A registry naming a roadmap whose own banner says otherwise is not authority,
    and scoring under it is a fail-open.
    """

    def _repo(self, tmp, v10_body):
        repo = Path(tmp)
        (repo / "specs").mkdir(parents=True, exist_ok=True)
        (repo / "specs" / "phase-plans-v10.md").write_text(v10_body)
        (repo / "specs" / "roadmap-status.json").write_text(_registry(
            "specs/phase-plans-v10.md",
            [("specs/phase-plans-v10.md", "active")],
        ))
        run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                        capture_output=True)
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        run("add", "-A")
        run("commit", "-qm", "seed")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "alpha.py").write_text("x = 1\n")
        run("add", "-A")
        run("commit", "-qm", "the change")
        return repo

    def _row(self, repo):
        rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
        return [r for r in rows if r.subject == "the change"][0]

    def test_a_selected_roadmap_with_NO_banner_is_not_scored(self):
        """Mutation that must kill this: drop the banner-coherence leg and score
        on the manifest alone. The old fixtures used a banner-less ROADMAP with
        a registry and expected scoring -- pinning the fail-open rather than
        catching it.
        """
        with TemporaryDirectory() as tmp:
            row = self._row(self._repo(tmp, ROADMAP))
            self.assertIn("authority incoherent", row.skipped_reason)
            self.assertEqual(row.notable, 0)

    def test_a_selected_roadmap_whose_banner_says_DELIVERED_is_not_scored(self):
        with TemporaryDirectory() as tmp:
            body = ROADMAP.replace(
                "# Roadmap",
                "# Roadmap\n\n> # DELIVERED — CLOSED (assessed 2026-01-02)", 1)
            row = self._row(self._repo(tmp, body))
            self.assertIn("authority incoherent", row.skipped_reason)

    def test_a_coherent_registry_plus_active_banner_DOES_score(self):
        """The positive case must stay reachable, or the checks above would be
        satisfied by a resolver that simply never scores anything.
        """
        with TemporaryDirectory() as tmp:
            row = self._row(self._repo(tmp, ROADMAP_ACTIVE))
            self.assertFalse(row.skipped_reason)
            self.assertEqual(row.notable, 1)


class TestCandidateSetMirrorsCanonicalGlob(unittest.TestCase):
    def test_a_non_digit_roadmap_name_counts_as_a_candidate(self):
        """`phase-plans-v1-task-message-sourcebroker.md` is a real file in this
        repo's history. A digits-only pattern drops it, so the resolver would see
        a singleton where the canonical selector sees two and refuses.

        Mutation that must kill this: narrow the glob back to digits-only, which
        makes v9 look like the sole candidate and scores the row.
        """
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "specs").mkdir(parents=True, exist_ok=True)
            (repo / "specs" / "phase-plans-v9.md").write_text(ROADMAP)
            (repo / "specs" / "phase-plans-v1-task-message-sourcebroker.md"
             ).write_text(ROADMAP)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            (repo / "src").mkdir(exist_ok=True)
            (repo / "src" / "alpha.py").write_text("x = 1\n")
            run("add", "-A")
            run("commit", "-qm", "the change")
            rows = ro.replay(repo, 5, "specs/phase-plans-v10.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertIn("no active roadmap declared", row.skipped_reason)


class TestNoAnachronisticAuthority(unittest.TestCase):
    """History is judged by what it declared, not by today's rules.

    The versioned LEGIBLE marker predates the roadmap registry in this repo, so
    demanding a registry wherever the marker exists ejects a whole legitimate
    era. Measured: 19 such commits in a 150-window.
    """

    def test_marker_without_registry_is_SCORED_via_the_banner_of_its_era(self):
        """Mutation that must kill this: `required=True`, which raises
        MalformedRegistryError("required roadmap-status registry is absent") and
        turns a scored row into an unscorable one.
        """
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "specs").mkdir(parents=True, exist_ok=True)
            (repo / "plans").mkdir(parents=True, exist_ok=True)
            # The marker exists; the registry does not -- the real historical era.
            (repo / "plans" / "phase-plan-v10-LEGIBLE.md").write_text("x\n")
            (repo / "specs" / "phase-plans-v9.md").write_text(ROADMAP_ACTIVE)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            (repo / "src").mkdir(exist_ok=True)
            (repo / "src" / "alpha.py").write_text("x = 1\n")
            run("add", "-A")
            run("commit", "-qm", "the change")
            rows = ro.replay(repo, 5, "specs/phase-plans-v9.md", "main")
            row = [r for r in rows if r.subject == "the change"][0]
            self.assertFalse(row.skipped_reason,
                             "a pre-registry-era commit must not be ejected")
            self.assertEqual(row.notable, 1)


class TestAuthorityResolutionFailsClosed(unittest.TestCase):
    def test_a_commit_that_cannot_be_checked_out_is_disclosed_not_scored(self):
        """A half-materialized commit must never be scored as if it were the
        commit.

        Mutation that must kill this: return a roadmap path instead of a reason
        when `git worktree add` fails.
        """
        with TemporaryDirectory() as tmp, TemporaryDirectory() as tmp_root:
            repo = _repo(tmp)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            rel, reason = ro._roadmap_rel_at(repo, "0" * 40, Path(tmp_root))
            self.assertIsNone(rel)
            self.assertIn("could not check out commit", reason)


class TestShallowCloneBoundary(unittest.TestCase):
    """The shallow branch shipped with no test reaching it (Fable seat).

    A remedy exercised only by a manual probe is unpinned: the next edit can
    silently revert it. Fixture recipe from that seat, which it proved works.
    """

    def test_a_shallow_boundary_is_labelled_as_one_not_as_a_root_commit(self):
        """Mutation that must kill this: make `_is_shallow` return False, which
        is the pre-fix behaviour -- the boundary then reads "root commit".
        """
        with TemporaryDirectory() as src, TemporaryDirectory() as dstdir:
            repo = _repo(src)
            run = lambda *a: subprocess.run(["git", "-C", src, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            (repo / "src").mkdir(exist_ok=True)
            for i, msg in enumerate(("second", "third", "fourth")):
                (repo / "src" / "alpha.py").write_text(f"x = {i}\n")
                run("add", "-A")
                run("commit", "-qm", msg)
            dst = Path(dstdir) / "clone"
            # Depth must NOT reach the root: git un-shallows a clone whose
            # requested depth covers all history, and the branch would not fire.
            subprocess.run(["git", "clone", "-q", "--depth", "2",
                            f"file://{src}", str(dst)], check=True,
                           capture_output=True)
            self.assertTrue(ro._is_shallow(dst), "fixture must be a shallow clone")
            rows = ro.replay(dst, 5, "specs/phase-plans-v10.md", "HEAD")
            boundary = [r for r in rows if r.skipped_reason]
            self.assertEqual(len(boundary), 1)
            self.assertIn("shallow-clone boundary", boundary[0].skipped_reason)
            self.assertNotIn("root commit", boundary[0].skipped_reason)


class TestNegativeReportIsRejected(unittest.TestCase):
    def test_negative_N_does_not_silently_replay_all_history(self):
        """`git log -n -1` is unlimited, not one.

        Mutation that must kill this: drop the guard. The run then succeeds and
        replays every commit, so the exit code flips to 0.
        """
        with TemporaryDirectory() as tmp:
            repo = _repo(tmp)
            run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                            capture_output=True)
            run("init", "-q", "-b", "main")
            run("config", "user.email", "t@t")
            run("config", "user.name", "t")
            run("add", "-A")
            run("commit", "-qm", "seed")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ro.main(["prog", "--repo", str(repo), "--report", "-1",
                              "--base", "main"])
            self.assertEqual(rc, 2)
            self.assertIn("must be >= 0", buf.getvalue())


class TestPreflight(unittest.TestCase):
    """agent-harness#633: answer the pre-EDIT question before the work exists.

    The issue was filed after nine commits of good work were closed as
    superseded for touching a phase's key files. Ownership is machine-readable,
    so that specific miss is mechanically catchable -- which is what this does.
    """

    def _repo(self, tmp):
        repo = _repo_with_two_phases(tmp)
        run = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                        capture_output=True)
        run("init", "-q", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        run("add", "-A")
        run("commit", "-qm", "seed")
        return repo

    def test_a_path_owned_by_ANOTHER_phase_is_reported(self):
        """Mutation that must kill this: return {} unconditionally."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            owned = ro.preflight(repo, ["src/alpha.py"])
            self.assertIn("src/alpha.py", owned)
            self.assertEqual(
                [o.phase_alias for o in owned["src/alpha.py"]], ["ALPHA"]
            )

    def test_your_OWN_phase_is_excluded(self):
        """The question is "does this belong to somebody ELSE?" -- a phase
        editing its own key files is the normal case and must not be flagged.

        Mutation that must kill this: ignore `current_phase`.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            self.assertEqual(ro.preflight(repo, ["src/alpha.py"], "ALPHA"), {})

    def test_an_unclaimed_path_is_not_reported(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            self.assertEqual(ro.preflight(repo, ["src/unclaimed.py"]), {})

    def test_the_exit_code_carries_the_answer(self):
        """1 = a path belongs to another phase, 0 = clear. A caller scripting a
        pre-edit guard reads the code, not the prose.

        Mutation that must kill this: always return 0.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc_owned = ro.main(["prog", "--repo", str(repo),
                                    "--preflight", "src/alpha.py"])
            self.assertEqual(rc_owned, 1)
            self.assertIn("claimed by", buf.getvalue())
            with redirect_stdout(io.StringIO()):
                rc_clear = ro.main(["prog", "--repo", str(repo),
                                    "--preflight", "src/unclaimed.py"])
            self.assertEqual(rc_clear, 0)

    def test_the_report_does_not_claim_to_know_BLOCK_state(self):
        """The honesty property, and the reason this is not the ah#633 gate.

        Scanning phase bodies for a BLOCKED marker matches 6 phases in v10 of
        which one is a real block; a gate on that signal fires falsely on five.
        The output must say ownership only, and say so.
        """
        out = ro.render_preflight({"src/alpha.py": [_own("src/alpha.py", "ALPHA")]})
        self.assertIn("BLOCK STATE IS NOT", out)
        self.assertIn("does not authorize", out)

    def test_the_SAME_file_answers_the_same_however_it_is_spelled(self):
        """The fail-open a cross-vendor panel caught (codex + grok, PR 725).

        `_claims` compares the argument to repo-relative roadmap tokens by exact
        match and `startswith`, so before normalization the same claimed file
        answered three different ways:

            src/alpha.py    -> exit 1, claimed
            ./src/alpha.py  -> exit 0, "no path is claimed"
            <abs>/src/alpha.py -> exit 0, "no path is claimed"

        Both false forms are what people actually type. The failure is
        fail-OPEN -- the wrong answer is the reassuring one -- in the guard whose
        entire purpose is catching an edit into another phase's files.

        Mutation that must kill this: drop the `_normalize_preflight_path` call
        and pass `raw` straight to `owners_for`.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            spellings = [
                "src/alpha.py",
                "./src/alpha.py",
                "src/./alpha.py",
                "src/beta/../alpha.py",
                str(Path(tmp) / "src" / "alpha.py"),
            ]
            for spelling in spellings:
                with self.subTest(spelling=spelling):
                    owned = ro.preflight(repo, [spelling])
                    self.assertEqual(
                        [o.phase_alias for o in owned.get(spelling, [])],
                        ["ALPHA"],
                        f"{spelling!r} must resolve to the same claim as the "
                        f"repo-relative form",
                    )

    def test_a_path_OUTSIDE_the_repo_cannot_evaluate_rather_than_clearing(self):
        """A path this command cannot place in the repo must not be silently
        skipped: skipping empties the result, and an empty result prints "no path
        is claimed" and exits 0 -- a pass produced by not having looked.

        Mutation that must kill this: `continue` instead of raising in
        `_normalize_preflight_path`, which yields exit 0.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            with self.assertRaises(ro.PathNotInRepo):
                ro.preflight(repo, ["/etc/passwd"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ro.main(["prog", "--repo", str(repo),
                              "--preflight", "/etc/passwd"])
            self.assertEqual(rc, 2, "cannot-evaluate is 2, never 0 and never 1")
            self.assertIn("CANNOT EVALUATE", buf.getvalue())

    def test_an_unresolvable_roadmap_exits_2_not_1(self):
        """Both panel seats found this independently.

        `preflight` called `declared_active_roadmap` directly, whose
        `RoadmapStatusError` subclasses no caller catches. The exception escaped,
        Python exited 1, and 1 is the code this command DEFINES as "claimed by
        another phase" -- so "I cannot tell which roadmap is active" was
        indistinguishable from "you are blocked".

        Mutation that must kill this: call `declared_active_roadmap(repo)` in
        `preflight` instead of `resolve_roadmap(repo)`.
        """
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)  # no specs/, no registry -> unresolvable
            (repo / "src").mkdir()
            with self.assertRaises(ro.RoadmapUnreadable):
                ro.preflight(repo, ["src/alpha.py"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = ro.main(["prog", "--repo", str(repo),
                              "--preflight", "src/alpha.py"])
            self.assertEqual(rc, 2)
            self.assertIn("CANNOT EVALUATE", buf.getvalue())

    def test_a_SCOPED_claim_is_not_presented_as_an_unconditional_one(self):
        """The roadmap qualifies some claims -- GOVLEAN's directory entry reads
        "`<dir>/` (new evidence, lint, and governance modules)", scoping it to
        PART of that directory. `audit` already surfaces the parenthetical
        verbatim; `preflight` kept only aliases, so it reported the whole
        directory as owned outright. That over-report is how this module briefly
        had GOVLEAN owning the entire source tree.

        Mutation that must kill this: drop `note=` from the Ownership built in
        `preflight`.
        """
        scoped = ROADMAP.replace(
            "- `src/beta/`", "- `src/beta/` (only the lane-B evidence modules)"
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=scoped)
            owned = ro.preflight(repo, ["src/beta/thing.py"])
            claims = owned["src/beta/thing.py"]
            self.assertEqual([o.phase_alias for o in claims], ["BETA"])
            # Attributed to the token carrying it, so a reader can see the
            # qualification is on the DIRECTORY claim rather than on their file.
            self.assertEqual(
                claims[0].note, "`src/beta/` (only the lane-B evidence modules)"
            )
            self.assertIn("SCOPED", ro.render_preflight(owned))

    def test_a_DIRECTORY_token_is_claimed_in_both_spellings(self):
        """The regression my own round-2 fix introduced, caught by the panel.

        `Path.resolve()` drops a trailing slash, and `_claims` reads that slash as
        the marker of a directory token. So normalizing turned the roadmap's OWN
        spelling of a claim into an unclaimed path: `src/beta/x.py` was flagged
        while `src/beta/` -- the literal text of the bullet -- came back "no path
        is claimed". Closing one fail-open opened another on the most obvious
        input there is.

        Mutations that must kill this: drop the `directoryish` branch in
        `_normalize_preflight_path`, OR drop the `rstrip("/")` arm of `_claims`.
        Each is killed independently -- the path assertion below pins the
        normalizer, and the slash-free spelling of a not-yet-existing directory
        pins the `_claims` arm, because nothing there can tell the normalizer it
        is a directory.

        Exercises `preflight` directly, not the CLI; the exit-code mapping is
        covered by `test_the_exit_code_carries_the_answer`.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            for spelling in ("src/beta/", "src/beta"):
                with self.subTest(spelling=spelling):
                    owned = ro.preflight(repo, [spelling])
                    self.assertEqual(
                        [o.phase_alias for o in owned.get(spelling, [])],
                        ["BETA"],
                        f"{spelling!r} is BETA's claim as the roadmap writes it",
                    )
                    if spelling.endswith("/"):
                        # Observes the NORMALIZER, not just the match. Without it
                        # the two layers are only killable together: `_claims`'
                        # rstrip arm alone satisfies the assertion above, so
                        # deleting the directory-ness preservation killed nothing
                        # and that layer sat unpinned.
                        #
                        # Only asserted for the directory-SHAPED spelling: for
                        # `src/beta` naming a directory that does not exist on
                        # disk yet, nothing in the argument or the filesystem says
                        # "directory", so the normalizer cannot know -- and the
                        # `_claims` arm is what carries that case. That asymmetry
                        # is the reason both layers exist.
                        self.assertEqual(owned[spelling][0].path, "src/beta/")

    def test_a_whole_repository_scope_cannot_evaluate(self):
        """`""`, `.`, and the absolute repo root match no ownership token, so each
        exited 0 -- "the whole repository is unclaimed", the most confidently
        wrong answer available.

        Mutation that must kill this: return `relative` unconditionally instead of
        raising on `"."`.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            for scope in ("", ".", str(Path(tmp))):
                with self.subTest(scope=scope):
                    with self.assertRaises(ro.PathNotInRepo):
                        ro.preflight(repo, [scope])
                    with redirect_stdout(io.StringIO()) as buf:
                        rc = ro.main(["prog", "--repo", str(repo),
                                      "--preflight", scope])
                    self.assertEqual(rc, 2)

    def test_an_unreadable_roadmap_exits_2_not_1(self):
        """`resolve_roadmap` normalizes RESOLUTION failures, but the READ was
        bare: a non-UTF-8 roadmap raised out of `main`, and the interpreter's
        exit 1 is this command's "claimed by another phase".

        Mutation that must kill this: drop the try/except around `read_text`.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "specs" / "phase-plans-v10.md").write_bytes(b"\xff\xfe not utf-8")
            with self.assertRaises(ro.RoadmapUnreadable):
                ro.preflight(repo, ["src/alpha.py"])
            with redirect_stdout(io.StringIO()) as buf:
                rc = ro.main(["prog", "--repo", str(repo),
                              "--preflight", "src/alpha.py"])
            self.assertEqual(rc, 2)
            self.assertIn("CANNOT EVALUATE", buf.getvalue())

    def test_the_note_comes_from_the_most_specific_claim(self):
        """A phase can claim a file AND its parent directory with different
        qualifications -- GOVLEAN does in v10. Returning the first match made the
        answer depend on bullet ORDER, so reordering two equivalent lines could
        swap an exact file's narrow qualification for the broad directory note,
        silently widening the scope a reader believes they have.

        Mutation that must kill this: `max(matches, key=len)` -> `matches[0]`.
        """
        both = ROADMAP.replace(
            "- `src/beta/`",
            "- `src/beta/` (the whole lane-B tree)\n- `src/beta/narrow.py` (only the parser)",
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=both)
            owned = ro.preflight(repo, ["src/beta/narrow.py"])
            self.assertEqual(
                owned["src/beta/narrow.py"][0].note, "(only the parser)"
            )

    def test_a_LONGER_glob_does_not_outrank_the_exact_file(self):
        """Length alone is not specificity once globs exist.

        A glob can be textually longer than the exact file it matches while
        claiming far more, so ranking purely by length hands the broad
        qualification to the narrow path — the same over-report the ordering fix
        was meant to end, reintroduced by its own tie-breaker.

        Mutation that must kill this: `key=specificity` -> `key=len`.
        """
        # `src/beta/[xyz][.]py` is 19 characters and matches the 13-character
        # `src/beta/x.py`, so a length-only ranking prefers the GLOB.
        broad, exact = "src/beta/[xyz][.]py", "src/beta/x.py"
        self.assertGreater(len(broad), len(exact), "the glob must out-length the file")
        globbed = ROADMAP.replace(
            "- `src/beta/`",
            f"- `{broad}` (the whole lane-B tree)\n- `{exact}` (only the parser)",
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=globbed)
            owned = ro.preflight(repo, [exact])
            self.assertEqual(owned[exact][0].note, "(only the parser)")

    def test_MULTIPLE_qualified_claims_are_all_surfaced_not_ranked(self):
        """Three successive rankings each attached a BROADER qualification to a
        narrower path, so the ranking was removed rather than repaired a fourth
        time:

            raw length            a 19-char glob outranked the 13-char exact file
            literal-beats-glob    `src/beta/` outranked `src/beta/parser_*.py`
            longest-prefix        `[a-z]*.py` outranked the narrower `[a]*.py`

        For two globs sharing a literal prefix, breadth is not length -- `[a]*.py`
        is narrower than `[a-z]*.py` and shorter -- so no cheap total order
        exists. When several of a phase's claims are qualified and none is exact,
        every qualification is shown. That matches what this module already says
        it does with prose it cannot interpret: reporting the whole directory as
        owned would overstate, dropping the entry would understate.

        Mutation that must kill this: return only the first qualified note instead
        of joining them.
        """
        roadmap = ROADMAP.replace(
            "- `src/beta/`",
            "- `src/beta/` (the whole lane-B tree)\n"
            "- `src/beta/parser_*.py` (only parser modules)",
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=roadmap)
            note = ro.preflight(repo, ["src/beta/parser_impl.py"])[
                "src/beta/parser_impl.py"
            ][0].note
            self.assertIn("(only parser modules)", note)
            self.assertIn("(the whole lane-B tree)", note)

    def test_an_EXACT_claim_settles_the_qualification_alone(self):
        """An exact token claims this path and nothing else, so its qualification
        is authoritative and the broader ones are not shown alongside it.

        Mutation that must kill this: drop the exact-match short-circuit and fall
        through to joining every qualified claim.
        """
        roadmap = ROADMAP.replace(
            "- `src/beta/`",
            "- `src/beta/` (the whole lane-B tree)\n"
            "- `src/beta/exact.py` (only the parser)",
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=roadmap)
            self.assertEqual(
                ro.preflight(repo, ["src/beta/exact.py"])["src/beta/exact.py"][0].note,
                "(only the parser)",
            )

    def test_the_note_is_scoped_to_the_PHASE_being_reported(self):
        """Both dissenting seats found this, with a worked example on live v10.

        Ranking over every phase's tokens let ANOTHER phase's exact claim win, and
        the note lookup is per-alias — so GOVLEAN's scoped directory note vanished
        from every file some other phase happens to name exactly (`runner.py`,
        `test_reviewtruth_phase.py`, dozens more). A scoped claim presented as
        unconditional is the exact failure `Ownership.note` exists to prevent.

        The earlier same-phase fixture could not catch it: with both tokens on one
        alias, alias-scoped and global ranking coincide.

        Mutation that must kill this: drop the `any(p.alias == alias ...)` filter.
        """
        roadmap = ROADMAP.replace(
            "- `src/beta/`", "- `src/beta/` (only the lane-B evidence modules)"
        ).replace("- `src/alpha.py`", "- `src/beta/shared.py`")
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=roadmap)
            mapping = ro.ownership_map(roadmap)
            # ALPHA claims src/beta/shared.py exactly and unqualified; BETA claims
            # the directory WITH a qualification. BETA's note must survive.
            self.assertEqual(
                ro._note_for("BETA", "src/beta/shared.py", mapping),
                "`src/beta/` (only the lane-B evidence modules)",
            )
            self.assertEqual(ro._note_for("ALPHA", "src/beta/shared.py", mapping), "")

    def test_a_broader_qualification_is_ATTRIBUTED_never_asserted_of_this_path(self):
        """The last form of the recurring defect, caught by codex in round 5.

        Given a qualified `src/beta/` and an UNQUALIFIED narrower claim, the
        directory's "(the whole lane-B tree)" was returned as the qualification
        ON the narrower path -- a broader qualification attached to a narrower,
        unconditional claim, for the fourth time in this PR.

        The bug was never the ORDERING. It was reporting a qualification without
        saying which claim it qualifies. Naming the token makes the
        misattribution unrepresentable, which is why no ranking is attempted.

        Mutation that must kill this: emit the bare note instead of the
        ```token` note`` form.
        """
        roadmap = ROADMAP.replace(
            "- `src/beta/`",
            "- `src/beta/` (the whole lane-B tree)\n- `src/beta/parser_*.py`",
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=roadmap)
            note = ro.preflight(repo, ["src/beta/parser_impl.py"])[
                "src/beta/parser_impl.py"
            ][0].note
            self.assertIn("(the whole lane-B tree)", note)
            self.assertIn(
                "`src/beta/`",
                note,
                "the qualification must name the claim it belongs to, or it "
                "reads as qualifying the narrower unconditional claim",
            )

    def test_an_UNQUALIFIED_exact_claim_does_not_suppress_a_scope_note(self):
        """The exact-match short-circuit fires only when the exact token actually
        carries a qualification.

        A phase can claim a file exactly with no note AND its parent directory
        with a scope note. Short-circuiting on the exact token regardless would
        return "" and hide the directory's scope entirely -- the reader loses the
        one sentence saying how far that claim reaches. Now that qualifications
        are attributed to their token, showing it cannot be misread as a claim
        about this file, so there is no reason to suppress it.

        This is the branch a mutation run found unpinned: flipping the
        short-circuit to `if owned == path:` changed behaviour and killed nothing.

        Mutation that must kill this: drop `and note_of(owned)` from the
        short-circuit condition.
        """
        roadmap = ROADMAP.replace(
            "- `src/beta/`",
            "- `src/beta/` (the whole lane-B tree)\n- `src/beta/bare.py`",
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=roadmap)
            note = ro.preflight(repo, ["src/beta/bare.py"])["src/beta/bare.py"][0].note
            self.assertIn("(the whole lane-B tree)", note)
            self.assertIn("`src/beta/`", note)

    def test_dotdot_across_a_repo_internal_symlink_uses_the_REAL_path(self):
        """Also codex, round 5. `..` is the only construct that makes lexical
        collapsing unsound: it cancels the preceding component without knowing
        whether that component was a symlink.

        With `link -> <repo>/a/b`, `link/../owned.py` collapses lexically to
        `owned.py` while it really names `a/owned.py`. Both are INSIDE the repo,
        so the containment guard passes and ownership is evaluated for a path the
        caller never named -- exit 0 while `a/owned.py` is claimed.

        Mutation that must kill this: drop the `".." in candidate.parts` branch.
        """
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp)
            (repo / "a" / "b").mkdir(parents=True, exist_ok=True)
            (repo / "link").symlink_to(repo / "a" / "b")
            self.assertIn(
                "a/owned.py", ro._preflight_identities(repo, "link/../owned.py")
            )

    def test_a_symlinked_directory_without_dotdot_keeps_its_OWN_name(self):
        """The other half of the same rule, and why `..` is special-cased rather
        than resolving everything: without `..`, the lexical form is what the
        caller named, and a token naming the symlinked directory must still match
        it. Ownership describes the repository's paths, not their targets.

        Mutation that must kill this: always use the resolved form.
        """
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp)
            (repo / "src" / "real").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "link").symlink_to(repo / "src" / "real")
            self.assertIn("src/link/", ro._preflight_identities(repo, "src/link/"))

    def test_BOTH_identities_of_a_symlinked_path_are_evaluated(self):
        """codex, round 6 — the hole in choosing lexical.

        With `link -> real`, ALPHA owning `src/link/` and BETA owning `src/real/`,
        ALPHA preflighting `src/link/owned.py` saw only the lexical name, matched
        its OWN claim, filtered it as current-phase, and exited 0 — while the edit
        mutates BETA's `src/real/owned.py`. Choosing the resolved form instead
        fails the mirror case (a token naming the symlink stops matching), so
        neither is correct alone.

        An edit through a symlink touches both the name typed and the bytes the
        target owns, so both are the caller's business: the union is the answer,
        not a hedge.

        Mutation that must kill this: return only the first identity from
        `_preflight_identities`.
        """
        roadmap = ROADMAP.replace("- `src/alpha.py`", "- `src/link/`").replace(
            "- `src/beta/`", "- `src/real/`"
        )
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=roadmap)
            (repo / "src" / "real").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "link").symlink_to(repo / "src" / "real")
            owned = ro.preflight(repo, ["src/link/owned.py"], "ALPHA")
            self.assertIn(
                "BETA",
                [o.phase_alias for o in owned.get("src/link/owned.py", [])],
                "editing through ALPHA's symlink writes BETA's file; excluding "
                "ALPHA must not clear the path",
            )

    def test_a_repo_INTERNAL_symlink_still_matches_its_own_token(self):
        """Resolving before comparing rewrote a repo-internal symlink to its
        target, so the roadmap's own token normalized to a different path and
        matched nothing -- exit 0, unclaimed.

        Ownership describes the repository's PATHS, not where they point.

        Mutation that must kill this: compute `relative` from `resolved` first
        instead of from the lexical path.
        """
        roadmap = ROADMAP.replace("- `src/alpha.py`", "- `src/link/`")
        with TemporaryDirectory() as tmp:
            repo = _repo_with_two_phases(tmp, roadmap=roadmap)
            (repo / "src" / "real").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "link").symlink_to(repo / "src" / "real")
            owned = ro.preflight(repo, ["src/link/"])
            self.assertEqual(
                [o.phase_alias for o in owned.get("src/link/", [])],
                ["ALPHA"],
                "a symlinked directory must still match the token naming it",
            )

    def test_a_symlink_LOOP_cannot_evaluate_rather_than_exiting_1(self):
        """`Path.resolve()` raises RuntimeError on a symlink loop and OSError on
        assorted filesystem failures. Uncaught, either escaped `main` as the
        interpreter's exit 1 -- the code reserved for "claimed by another phase".

        Mutation that must kill this: drop the `(OSError, RuntimeError)` handler
        around the argument's `resolve()`.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "src" / "loop_a").symlink_to(repo / "src" / "loop_b")
            (repo / "src" / "loop_b").symlink_to(repo / "src" / "loop_a")
            with redirect_stdout(io.StringIO()) as buf:
                rc = ro.main(["prog", "--repo", str(repo),
                              "--preflight", "src/loop_a/x.py"])
            self.assertIn(rc, (0, 2), "must never be 1 -- that means 'claimed'")
            if rc == 2:
                self.assertIn("CANNOT EVALUATE", buf.getvalue())

    def test_a_symlink_ERASED_by_lexical_dotdot_cannot_evaluate(self):
        """Lexical `..` collapsing is not filesystem-truthful: it erases a symlink
        before containment is checked. With `link -> /tmp/outside`, the argument
        `link/../x` reads lexically as `<repo>/x` (inside) while really resolving
        outside the repo — so ownership would be evaluated for a path the caller
        never named.

        Mutation that must kill this: drop the `resolved.relative_to(root)` guard
        and trust the lexical form.
        """
        with TemporaryDirectory() as tmp, TemporaryDirectory() as outside:
            repo = self._repo(tmp)
            (repo / "link").symlink_to(outside)
            with self.assertRaises(ro.PathNotInRepo):
                ro.preflight(repo, ["link/../src/alpha.py"])

    def test_a_non_object_state_file_does_not_exit_1(self):
        """Valid JSON need not be an OBJECT. A state file containing `[]` reached
        `.get` on a list and raised AttributeError, which audit-mode `main` does
        not catch — exiting 1 with no ownership claim at all.

        Mutation that must kill this: drop the `isinstance(loaded, dict)` guard.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / ".phase-loop").mkdir(exist_ok=True)
            (repo / ".phase-loop" / "state.json").write_text("[]")
            self.assertIsNone(ro.current_phase(repo))

    def test_AUDIT_also_normalizes_an_unreadable_roadmap(self):
        """Round 3 wrapped the read in `preflight` and left `audit` bare two
        hundred lines away, so the same non-UTF-8 roadmap still escaped there.
        The fix that lives in one caller is how the other keeps the hole.

        Mutation that must kill this: `read_roadmap(...)` -> `roadmap.read_text(...)`
        in `audit`.
        """
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / "specs" / "phase-plans-v10.md").write_bytes(b"\xff\xfe bad")
            with self.assertRaises(ro.RoadmapUnreadable):
                ro.audit(repo, "HEAD")

    def test_without_current_phase_the_output_does_not_say_another_phase(self):
        """"another phase" implies an exclusion that only happened if one was
        named. Without `--current-phase` the question is "does ANY phase claim
        this?", and the answer must not imply otherwise.
        """
        owned = {"src/alpha.py": [_own("src/alpha.py", "ALPHA")]}
        self.assertNotIn("another phase", ro.render_preflight(owned))
        self.assertIn("another phase", ro.render_preflight(owned, "BETA"))


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
