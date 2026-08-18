"""Tests for the diff-independent entry-doc check (agent-harness#568).

Fixtures are **constructed repositories**, not loose ``.md`` files: arms 2 and 3
need a git repo with tags and package metadata, and a loose ``/tmp/old.md`` has
no owning package and therefore no suppression identity.

Every arm carries two fixtures. A negative proves the arm fires, asserted by
``arm`` *and* ``code`` rather than merely non-empty output. An **adversarial
positive** -- correct-but-tricky documentation -- proves it does not fire on the
things that make naive versions of this check unusable.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase_loop_runtime import entry_doc_check as edc

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "entry_docs"

#: Tag namespace of the constructed fixtures. Encodes both halves of the
#: resolution rule the plan calls load-bearing: ``v0.7.9`` is the *lexical*
#: maximum where ``v0.7.13`` is the *version* maximum, and
#: ``consiliency-harness-v9.9.9`` is a different package's release tag that a
#: missing ``v[0-9]*`` filter would mistake for this repository's latest.
FIXTURE_TAGS = (
    "v0.1.5",
    "v0.7.9",
    "v0.7.13",
    "consiliency-harness-v9.9.9",
    "fleet-pin-20260815",
    "backup/something-abc123",
)
FIXTURE_LATEST_TAG = "v0.7.13"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
    )


def build_repo(
    tmp: str,
    docs: dict,
    *,
    packages: dict = None,
    tags: tuple = FIXTURE_TAGS,
    suppressions=None,
) -> Path:
    """Construct a repo with package metadata, git history and a tag namespace.

    ``packages`` maps a directory (``""`` for the root) to ``(name, version,
    readme)``; a ``readme`` of ``None`` declares no long-description, which is
    how arm-1 fixtures opt out of arms 2 and 3. Defaults to a single
    ``phase-loop-runtime`` package mirroring the live layout, so fixture logical
    paths match production ones.
    """
    repo = Path(tmp)
    if packages is None:
        packages = {"phase-loop-runtime": ("phase-loop-runtime", "0.7.13", "README.md")}
    for directory, (name, version, readme) in packages.items():
        target = repo / directory if directory else repo
        target.mkdir(parents=True, exist_ok=True)
        (target / "pyproject.toml").write_text(
            "[project]\n"
            f'name = "{name}"\n'
            f'version = "{version}"\n'
            + (f'readme = "{readme}"\n' if readme is not None else "")
            + "\n"
            "[project.urls]\n"
            'Repository = "https://github.com/Consiliency/agent-harness"\n',
            encoding="utf-8",
        )
    for logical, text in docs.items():
        path = repo / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if suppressions is not None:
        path = repo / edc.SUPPRESSIONS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"suppressions": suppressions}, indent=2), encoding="utf-8")

    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    for tag in tags:
        # update-ref, not `git tag`: a global `tag.gpgsign = true` forces an
        # annotated, signed tag and fails the fixture build. Writing the ref
        # directly makes the tag namespace independent of ambient git config.
        _git(repo, "update-ref", f"refs/tags/{tag}", "HEAD")
    return repo


def codes(findings) -> list:
    return [(f.arm, f.code) for f in findings]


# ---------------------------------------------------------------------------
# The positive control


class TestPositiveControl(unittest.TestCase):
    """The check must be usable against the docs it ships with."""

    def test_current_repo_is_clean(self):
        raw = edc.check_repo(REPO_ROOT)
        self.assertEqual(
            [f.render() for f in raw],
            [],
            "the live entry docs must produce ZERO RAW findings — a positive control "
            "bought by suppression is not a positive control",
        )

    def test_suppression_budget_is_zero_at_landing(self):
        # The mechanism exists for future drift, not to buy today's green.
        self.assertEqual(edc.load_suppressions(REPO_ROOT), [])

    def test_every_package_long_description_is_an_entry_doc(self):
        ctx = edc.RepoContext(REPO_ROOT)
        declared = {p.readme_logical_path for p in ctx.packages.values() if p.readme}
        self.assertTrue(declared, "expected at least one package to declare a readme")
        self.assertLessEqual(declared, set(edc.ENTRY_DOCS))
        self.assertEqual(edc.check_entry_doc_coverage(ctx, edc.ENTRY_DOCS), [])

    def test_docs_surfaces_taxonomy_is_untouched(self):
        # Revision 2 proposed widening DOC_SURFACE_GLOBS. Removed deliberately:
        # docs_audit.evaluate satisfies a general public-surface obligation with
        # ANY recognised doc change, so the widening would let an agent-instruction
        # edit stand in for a cli.py documentation obligation.
        from phase_loop_runtime import docs_surfaces

        self.assertNotIn("AGENTS.md", docs_surfaces.DOC_SURFACE_GLOBS)
        self.assertNotIn("CLAUDE.md", docs_surfaces.DOC_SURFACE_GLOBS)


# ---------------------------------------------------------------------------
# Arm 1 -- paths


class TestArmPaths(unittest.TestCase):
    #: Arm 1 fixtures declare no long-description, isolating the paths arm from
    #: arms 2 and 3 and from coverage reconciliation.
    PATHS_ONLY = {"": ("demo", "1.0.0", None)}

    def test_unresolvable_path_is_reported(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"README.md": "See `docs/nope/missing.md` for details.\n"},
                packages=self.PATHS_ONLY,
            )
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])
            self.assertEqual(found[0].token, "docs/nope/missing.md")
            self.assertEqual(found[0].line, 1)

    def test_metavariable_with_unresolvable_prefix_is_reported(self):
        # Metavariables are NOT blanket-skipped: the concrete parent prefix is
        # still validated, so a typo'd directory is caught.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"README.md": "It runs `spces/<NAME>.md` roadmaps.\n"},
                packages=self.PATHS_ONLY,
            )
            (repo / "specs").mkdir()
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path_prefix")])
            self.assertIn("spces/", found[0].message)

    def test_adversarial_positives_are_silent(self):
        """Correct-but-tricky path documentation must produce zero findings."""
        doc = "\n".join(
            [
                "Skill roots: `~/.claude/skills`, `~/.config/opencode/skills`.",
                "Cite issues as `Consiliency/agent-harness#130`, never a bare `#130`.",
                "It executes `specs/phase-plans-v<N>.md`.",
                "Overlays live at `_overrides/<harness>/`.",
                "Bundled skills resolve from `skills_bundle/**`.",
                "Secrets (`secrets/**`) are never break-glassable.",
                "Installed to `share/phase-loop-runtime/protocol/protocol.md`.",
                "Un-adopted repos have no `.consiliency/manifest`.",
                "Source: `https://github.com/Consiliency/agent-harness`.",
                "A repo without one exits with `no specs/phase-plans-v*.md roadmap found`.",
                "",
                "```sh",
                "phase-loop install --source <path-to>/phase-loop-skills --apply",
                "cat docs/definitely/not/here.md",
                "```",
                "",
                "See `docs/real.md` and `nested/deep/file.txt`.",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": doc}, packages=self.PATHS_ONLY)
            # The concrete things the doc claims, made true.
            (repo / "specs").mkdir()
            (repo / "docs").mkdir()
            (repo / "docs" / "real.md").write_text("x", encoding="utf-8")
            (repo / "nested" / "deep").mkdir(parents=True)
            (repo / "nested" / "deep" / "file.txt").write_text("x", encoding="utf-8")
            (repo / "skills" / "advisor" / "_overrides" / "claude").mkdir(parents=True)
            (repo / "skills" / "advisor" / "_overrides" / "claude" / "SKILL.md").write_text(
                "x", encoding="utf-8"
            )
            (repo / ".consiliency").mkdir()
            (repo / ".consiliency" / "manifest.json").write_text("{}", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "content")
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=("README.md",))), [])

    def test_install_layout_skip_self_disables(self):
        # The class is a class, not an allowlist: a repo that really has a
        # `share/` directory resolves `share/...` paths normally.
        text = "Installed to `share/protocol/protocol.md`.\n"
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": text}, packages=self.PATHS_ONLY)
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=("README.md",))), [])
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": text, "share/keep.txt": "x"}, packages=self.PATHS_ONLY
            )
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])


# ---------------------------------------------------------------------------
# Arm 2 -- pin freshness


class TestArmPinFreshness(unittest.TestCase):
    def test_stale_distribution_pin_is_reported(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"phase-loop-runtime/README.md": "```sh\npip install phase-loop-runtime==0.7.12\n```\n"},
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "stale_pin")])
            self.assertIn("0.7.13", found[0].message)

    def test_stale_git_ref_pin_is_reported(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {
                    "phase-loop-runtime/README.md": (
                        "```sh\n"
                        'uv tool install "git+https://github.com/Consiliency/agent-harness'
                        '@v0.7.9#subdirectory=phase-loop-runtime"\n'
                        "```\n"
                    )
                },
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "stale_pin")])
            # Version sort, not lexical: v0.7.9 is the lexical max here.
            self.assertIn(FIXTURE_LATEST_TAG, found[0].message)

    def test_release_tag_namespace_excludes_foreign_and_non_release_tags(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": "x\n"})
            ctx = edc.RepoContext(repo)
            self.assertEqual(ctx.latest_release_tag, FIXTURE_LATEST_TAG)

    def test_the_two_clocks_are_never_crossed(self):
        # A distribution pin equal to the repository's latest RELEASE TAG but
        # unequal to that distribution's own source version is still stale.
        # Crossing the clocks would pass it.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"pkg/README.md": "pip install shim==0.7.13\n"},
                packages={"pkg": ("shim", "0.6.1", "README.md")},
            )
            found = edc.check_repo(repo, entry_docs=("pkg/README.md",))
            self.assertEqual(codes(found), [("pins", "stale_pin")])
            self.assertIn("0.6.1", found[0].message)

    def test_adversarial_positives_are_silent(self):
        doc = "\n".join(
            [
                "```sh",
                "pip install phase-loop-runtime               # latest compatible",
                "pip install phase-loop-runtime==0.7.13       # exact version",
                "pip install phase-loop-runtime==X.Y.Z        # version metavariable",
                "pip install consiliency-harness==<VERSION>   # version metavariable",
                'uv tool install "git+https://github.com/Consiliency/agent-harness'
                '@<TAG>#subdirectory=phase-loop-runtime"',
                "pip install git+https://github.com/Consiliency/agent-harness@main",
                "pip install git+https://github.com/other/project@v0.1.5",
                "pip install some-third-party==1.2.3",
                "```",
                "",
                "Sole dependency: `phase-loop-runtime>=0.6.1`.",
                "Pin one explicitly with `--ref vX.Y.Z`.",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"phase-loop-runtime/README.md": doc},
                packages={
                    "phase-loop-runtime": ("phase-loop-runtime", "0.7.13", "README.md"),
                    "consiliency-harness": ("consiliency-harness", "0.6.1", "README.md"),
                },
            )
            (repo / "consiliency-harness" / "README.md").write_text("shim\n", encoding="utf-8")
            found = edc.check_repo(
                repo,
                entry_docs=("phase-loop-runtime/README.md", "consiliency-harness/README.md"),
            )
            self.assertEqual(codes(found), [])

    def test_unresolvable_release_namespace_fails_closed(self):
        """A pin the check could not evaluate is reported, not skipped.

        `latest_release_tag is None` means "I could not do my job", not
        "nothing to compare against". Skipping made arm 2 silently inert under
        a shallow clone, a fork PR, or a relaxed `fetch-depth`, hiding every
        stale git pin behind a green check -- fail-open on the exact defect
        this arm exists to catch.
        """
        pin = (
            'uv tool install "git+https://github.com/Consiliency/agent-harness'
            '@v0.1.5#subdirectory=phase-loop-runtime"\n'
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": pin}, tags=())
            self.assertIsNone(edc.RepoContext(repo).latest_release_tag)
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "release_namespace_unresolved")])
            self.assertIn("v[0-9]*", found[0].message)

        # The same pin in a repo WITH tags is evaluated normally -- the
        # fail-closed path must not mask the staleness verdict.
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": pin})
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "stale_pin")])

    def test_unresolvable_namespace_is_silent_when_nothing_pins_this_repo(self):
        # Fail-closed on an unevaluable claim, NOT a blanket failure whenever a
        # repo has no tags: a document that makes no self-repo release pin has
        # nothing for the namespace to answer.
        doc = "\n".join(
            [
                "pip install phase-loop-runtime==0.7.13",
                "pip install git+https://github.com/Consiliency/agent-harness@main",
                "pip install git+https://github.com/Consiliency/agent-harness@<TAG>",
                "pip install git+https://github.com/other/project@v0.1.5",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": doc}, tags=())
            self.assertEqual(
                codes(edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))), []
            )

    def test_wrong_placeholder_in_ref_position_is_reported(self):
        # The grammar is position-sensitive: a ref position names a tag, so
        # <VERSION> is not meaningful there even though it is in a pin.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {
                    "phase-loop-runtime/README.md": (
                        "pip install git+https://github.com/Consiliency/agent-harness@<VERSION>\n"
                    )
                },
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "invalid_placeholder")])


class TestHistoricalPin(unittest.TestCase):
    """Mutation coupling: the defects that motivated the arms must be caught.

    The fixture is the **whole** file as it stood at ``8f191d99``. An earlier
    revision carried only its first 32 lines, which silently dropped the
    ``../phase-loop-skills`` relative link on line 49 -- the second of the two
    Consiliency/agent-harness#568 defects living in that same file. The
    single-arm assertion below then passed only because the truncation had
    removed the line that would have produced the other arm: the test asserted
    its own truncation rather than the behaviour.
    """

    #: Sibling content the historical README's path claims refer to. Without it
    #: arm 1 reports four findings that are artefacts of an empty fixture repo,
    #: not properties of the document under test.
    SCAFFOLD = {
        "phase-loop-skills/README.md": "skills\n",
        "phase-loop-skills/advisor-board/_overrides/claude/SKILL.md": "override\n",
        ".consiliency/manifest.json": "{}\n",
    }

    def test_v015_historical_pin_is_stale(self):
        historical = (FIXTURES / "historical_8f191d99_README.md").read_text(encoding="utf-8")

        with TemporaryDirectory() as tmp:
            # A constructed repo preserving the LOGICAL path, so the doc has an
            # owning package and a suppression identity.
            repo = build_repo(
                tmp,
                {"phase-loop-runtime/README.md": historical, **self.SCAFFOLD},
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))

            # Exactly the two historical defects, across TWO arms. An equality
            # assertion, so a fixture that loses a defect fails here rather than
            # quietly narrowing what the test covers.
            self.assertEqual(
                codes(found),
                [
                    ("pins", "stale_pin"),
                    ("pins", "stale_pin"),
                    ("published_rendering", "relative_link_in_published_readme"),
                ],
            )

            pins = [f for f in found if f.arm == "pins"]
            for finding in pins:
                # Staleness, NOT nonexistence: v0.1.5 IS a real tag in the
                # namespace, so an existence rule would pass this defect.
                self.assertIn("@v0.1.5", finding.token)
                self.assertIn(FIXTURE_LATEST_TAG, finding.message)
                self.assertIn(edc._RELEASE_TAG_GLOB, finding.message)
            self.assertEqual([f.line for f in pins], [22, 24])

            link = [f for f in found if f.arm == "published_rendering"][0]
            self.assertEqual(link.token, "../phase-loop-skills")
            self.assertEqual(link.line, 49)

            # The pinned tag really does exist -- that is the whole point.
            tags = subprocess.run(
                ["git", "-C", str(repo), "tag", "--list", "v0.1.5"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
            self.assertEqual(tags, ["v0.1.5"])

    def test_fixture_matches_the_commit_it_claims(self):
        """The fixture must be the commit's file, byte for byte.

        Equality, not containment: ``assertIn`` accepts any prefix, so it
        cannot fail on the truncation it exists to catch.
        """
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", "8f191d99:phase-loop-runtime/README.md"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            self.skipTest("commit 8f191d99 not present (shallow clone)")
        fixture = (FIXTURES / "historical_8f191d99_README.md").read_text(encoding="utf-8")
        self.assertEqual(fixture, proc.stdout)


# ---------------------------------------------------------------------------
# Arm 3 -- published-README rendering


class TestArmPublishedRendering(unittest.TestCase):
    def test_relative_link_in_package_readme_is_reported(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"phase-loop-runtime/README.md": "See [the skills](../phase-loop-skills).\n"},
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("published_rendering", "relative_link_in_published_readme")])
            self.assertEqual(found[0].token, "../phase-loop-skills")

    def test_same_link_in_root_readme_is_not_reported(self):
        """The identical link is a defect in one file and correct in the other.

        The root README is not published as any package's long-description, so
        GitHub's relative-link rewriting is the only rendering context it has.
        Both docs are checked in the same run, so this isolates the *published*
        property rather than a difference in coverage.
        """
        link = "See [the skills](phase-loop-skills/README.md).\n"
        docs = ("README.md", "phase-loop-runtime/README.md")
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {
                    "README.md": link,
                    "phase-loop-runtime/README.md": "No relative links here.\n",
                    "phase-loop-skills/README.md": "skills\n",
                },
            )
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=docs)), [])

        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {
                    "README.md": "No relative links here.\n",
                    "phase-loop-runtime/README.md": link,
                    "phase-loop-skills/README.md": "skills\n",
                },
            )
            found = edc.check_repo(repo, entry_docs=docs)
            self.assertEqual(
                codes(found), [("published_rendering", "relative_link_in_published_readme")]
            )
            self.assertEqual(found[0].file, "phase-loop-runtime/README.md")

    def test_grammar_covers_images_and_reference_definitions(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {
                    "phase-loop-runtime/README.md": (
                        "![badge](img/build.svg)\n\n[skills]: ../phase-loop-skills\n"
                    )
                },
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(
                codes(found),
                [
                    ("published_rendering", "relative_link_in_published_readme"),
                    ("published_rendering", "relative_link_in_published_readme"),
                ],
            )
            self.assertEqual(
                sorted(f.token for f in found), ["../phase-loop-skills", "img/build.svg"]
            )

    def test_adversarial_positives_are_silent(self):
        doc = "\n".join(
            [
                "Part of the [agent-harness](https://github.com/Consiliency/agent-harness) monorepo.",
                "Jump to [Install](#install) or [Roadmap validation](#roadmap-validation).",
                "Sources live in the [`phase-loop-skills/`](https://github.com/Consiliency/"
                "agent-harness/tree/main/phase-loop-skills) directory.",
                "Autolink: <https://pypi.org/project/phase-loop-runtime/>.",
                "Mail: <mailto:nobody@example.com>.",
                "Protocol-relative: [cdn](//example.com/x.png).",
                "",
                "[pypi]: https://pypi.org/project/phase-loop-runtime/",
                "",
                "```markdown",
                "[a sample relative link](../not-rendered)",
                "```",
                "",
                "Inline code is not a link: `[x](../also-not-rendered)`.",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"phase-loop-runtime/README.md": doc, "phase-loop-skills/README.md": "skills\n"},
            )
            self.assertEqual(
                codes(edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))), []
            )


# ---------------------------------------------------------------------------
# Coverage reconciliation


class TestCoverageReconciliation(unittest.TestCase):
    def test_uncovered_package_readme_is_a_finding(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"README.md": "root\n", "newpkg/README.md": "new\n"},
                packages={
                    "": ("root-pkg", "1.0.0", "README.md"),
                    "newpkg": ("newpkg", "1.0.0", "README.md"),
                },
            )
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("coverage", "uncovered_package_readme")])
            self.assertEqual(found[0].file, "newpkg/README.md")


# ---------------------------------------------------------------------------
# Suppressions


class TestSuppressions(unittest.TestCase):
    def _stale_pin_repo(self, tmp, suppressions=None):
        return build_repo(
            tmp,
            {"phase-loop-runtime/README.md": "pip install phase-loop-runtime==0.7.12\n"},
            suppressions=suppressions,
        )

    def test_suppression_requires_reason_and_respects_budget(self):
        docs = ("phase-loop-runtime/README.md",)
        with TemporaryDirectory() as tmp:
            repo = self._stale_pin_repo(tmp)
            raw = edc.check_repo(repo, entry_docs=docs)
            self.assertEqual(codes(raw), [("pins", "stale_pin")])
            offender = raw[0]

        entry = {"file": offender.file, "code": offender.code, "token": offender.token}

        # A suppression with a reason silences exactly its own finding.
        with TemporaryDirectory() as tmp:
            repo = self._stale_pin_repo(tmp, [dict(entry, reason="release in flight")])
            raw = edc.check_repo(repo, entry_docs=docs)
            self.assertEqual(
                edc.apply_suppressions(raw, edc.load_suppressions(repo)),
                [],
            )

        # A suppression WITHOUT a reason is undocumented drift: it neither
        # silences the finding nor passes silently itself.
        with TemporaryDirectory() as tmp:
            repo = self._stale_pin_repo(tmp, [dict(entry, reason="   ")])
            raw = edc.check_repo(repo, entry_docs=docs)
            result = edc.apply_suppressions(raw, edc.load_suppressions(repo))
            self.assertEqual(
                codes(result),
                [("pins", "stale_pin"), ("suppressions", "suppression_missing_reason")],
            )

    def test_suppression_matching_nothing_is_itself_a_finding(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"phase-loop-runtime/README.md": "pip install phase-loop-runtime==0.7.13\n"},
                suppressions=[
                    {
                        "file": "phase-loop-runtime/README.md",
                        "code": "stale_pin",
                        "token": "phase-loop-runtime==0.0.1",
                        "reason": "long since fixed",
                    }
                ],
            )
            raw = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(raw, [])
            result = edc.apply_suppressions(raw, edc.load_suppressions(repo))
            self.assertEqual(codes(result), [("suppressions", "unused_suppression")])

    def test_fingerprint_is_line_independent(self):
        a = edc.Finding("README.md", 7, "pins", "m", "stale_pin", "x==1")
        b = edc.Finding("README.md", 99, "pins", "different message", "stale_pin", "x==1")
        self.assertEqual(a.fingerprint, b.fingerprint)
        c = edc.Finding("README.md", 7, "pins", "m", "stale_pin", "x==2")
        self.assertNotEqual(a.fingerprint, c.fingerprint)


# ---------------------------------------------------------------------------
# CLI


class TestCli(unittest.TestCase):
    def test_exit_codes(self):
        self.assertEqual(edc.main(["entry_doc_check", "--repo", str(REPO_ROOT)]), 0)
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"phase-loop-runtime/README.md": "pip install phase-loop-runtime==0.7.12\n"}
            )
            self.assertEqual(edc.main(["entry_doc_check", "--repo", str(repo)]), 1)
        self.assertEqual(edc.main(["entry_doc_check", "--repo", "/nonexistent/xyz"]), 2)

    def test_file_narrowing_is_a_logical_path(self):
        # There is no loose-file mode: /tmp/old.md has no owning package and no
        # suppression identity.
        self.assertEqual(
            edc.main(["entry_doc_check", "--repo", str(REPO_ROOT), "--file", "README.md"]), 0
        )
        self.assertEqual(
            edc.main(["entry_doc_check", "--repo", str(REPO_ROOT), "--file", "/tmp/old.md"]), 2
        )


if __name__ == "__main__":
    unittest.main()
