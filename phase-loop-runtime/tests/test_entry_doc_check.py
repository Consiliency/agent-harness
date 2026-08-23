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


def _is_canonical_checkout() -> bool:
    """True when ``REPO_ROOT`` is the full monorepo.

    Gate A (``scripts/gate_a_cleanroom.sh``) runs this suite from a copied tree
    containing only ``phase-loop-runtime/`` and ``specs/``, so ``REPO_ROOT``
    points at a **partial** tree in which `phase-loop-skills/` and
    `.consiliency/` genuinely do not exist. Assertions about the live entry docs
    are meaningless there -- not because the check misbehaves, but because it
    behaves correctly against a different tree.

    Keyed on sibling packages rather than git-ness: the standalone copy's lack
    of a `.git` is incidental to how Gate A stages the tree and could change,
    whereas "are the other packages here" is the property that actually decides
    whether the live entry docs can be resolved.
    """
    return (REPO_ROOT / "phase-loop-skills").is_dir() and (
        REPO_ROOT / "consiliency-harness"
    ).is_dir()


#: Skip marker for assertions that are only meaningful in the full checkout.
#:
#: This is NOT a hole in the positive control. `.github/workflows/entry-doc-check.yml`
#: runs `entry_doc_check --repo .` against the real checkout on every pull request,
#: push to main, and release tag, and nothing about tree posture can disable it --
#: that workflow is the load-bearing control. The assertions below are a
#: convenience duplicate that happens to run inside the test suite, so skipping
#: them where they cannot be evaluated costs no coverage. Do not "fix" a red
#: standalone run by widening this marker to the arms themselves: every arm's
#: behaviour is proven by constructed fixtures, which are posture-independent
#: and must keep running everywhere.
CANONICAL_ONLY = unittest.skipUnless(
    _is_canonical_checkout(),
    "requires the canonical monorepo checkout (sibling packages absent); the "
    "entry-doc-check workflow is the load-bearing positive control",
)

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

    @CANONICAL_ONLY
    def test_current_repo_is_clean(self):
        raw = edc.check_repo(REPO_ROOT)
        self.assertEqual(
            [f.render() for f in raw],
            [],
            "the live entry docs must produce ZERO RAW findings — a positive control "
            "bought by suppression is not a positive control",
        )

    @CANONICAL_ONLY
    def test_suppression_budget_is_zero_at_landing(self):
        # The mechanism exists for future drift, not to buy today's green.
        #
        # Canonical-only because an ABSENT suppression file also loads as [], so
        # in a partial tree this passes without the checked-in file existing --
        # it would assert nothing about the budget.
        self.assertTrue((REPO_ROOT / edc.SUPPRESSIONS).is_file())
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

    def test_nested_fence_is_not_closed_by_a_shorter_run(self):
        """A ``` line must not close a ```` fence (CommonMark).

        This one fixture distinguishes both failure directions at once. With
        the length check, the only finding is the token AFTER the block. Losing
        it inverts the mask: the inner token is reported (a false positive on
        fenced content) and the outer one is missed (a quiet miss), so the
        assertion below fails on the token identity either way.

        Asserted on a constructed nested fence rather than "the live docs still
        pass" -- no entry doc has a nested fence, so that input cannot
        distinguish the two behaviours at all.
        """
        doc = "\n".join(
            [
                "````",
                "```",
                "`docs/inside/absent.md`",
                "````",
                "",
                "Then `docs/outside/absent.md` here.",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": doc}, packages=self.PATHS_ONLY)
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])
            self.assertEqual(found[0].token, "docs/outside/absent.md")

    def test_file_line_citation_resolves_to_the_path(self):
        # This repo's own convention: `src/.../cli.py:42`. Kept a CHECK, not a
        # skip -- only the line suffix is stripped, so a citation of a file that
        # does not exist is still reported.
        doc = (
            "See `src/pkg/cli.py:42` and `src/pkg/cli.py:42:7`, "
            "but `src/pkg/ghost.py:42` does not exist.\n"
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": doc}, packages=self.PATHS_ONLY)
            (repo / "src" / "pkg").mkdir(parents=True)
            (repo / "src" / "pkg" / "cli.py").write_text("x", encoding="utf-8")
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])
            self.assertEqual(found[0].token, "src/pkg/ghost.py:42")

    def test_absolute_system_paths_are_not_repo_claims(self):
        """`/tmp`, `/run`, `/proc` are host runtime locations, not repo paths.

        Verbatim from `phase-loop-runtime/README.md:57,61` as it stands on
        `main` after Consiliency/agent-harness#545, which turned the merged
        check red in production. The live regression, not a paraphrase.
        """
        doc = (
            "it requires a direct, mode-0700 child of `/tmp`, a quiescent settings tree.\n"
            "That probe uses `/usr/bin/bwrap`, a fresh `/tmp`, `/run`, and `/proc`, "
            "the fixed `/run/phase-loop-review` stage mapping.\n"
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": doc}, packages=self.PATHS_ONLY)
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=("README.md",))), [])

    def test_absolute_root_relative_paths_are_still_checked(self):
        """A leading slash is not a blanket skip.

        `/README.md` is a repo-ROOT-relative reference -- a real way to write a
        path from a doc in a subdirectory -- so it must still resolve, and must
        resolve from the root rather than the document's own directory.
        """
        doc = "Root readme: `/README.md`. Ghost: `/docs/absent.md`.\n"
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"README.md": "root\n", "phase-loop-runtime/README.md": doc},
                packages=self.PATHS_ONLY,
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])
            self.assertEqual(found[0].token, "/docs/absent.md")

    def test_absolute_system_root_skip_self_disables(self):
        # Same self-disabling property as the install-layout class: a repo that
        # genuinely contains the directory resolves it normally.
        doc = "See `/var/config.yml`.\n"
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": doc}, packages=self.PATHS_ONLY)
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=("README.md",))), [])
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": doc, "var/keep.txt": "x"}, packages=self.PATHS_ONLY
            )
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])

    def test_a_colon_in_a_real_filename_is_not_stripped(self):
        # Stripping the citation suffix unconditionally turns a real file whose
        # NAME contains a colon into a phantom missing path. The literal token
        # is tried first, so the citation rule only ever adds a fallback.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": "See `data/log:2024`.\n"}, packages=self.PATHS_ONLY
            )
            (repo / "data").mkdir()
            (repo / "data" / "log:2024").write_text("x", encoding="utf-8")
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=("README.md",))), [])

    def test_a_citation_must_point_at_a_file(self):
        # `src/pkg:42` where src/pkg is a DIRECTORY is nonsense. Accepting any
        # resolvable stripped target would silently drop a finding the
        # unstripped check used to make -- trading a false positive for a
        # quiet miss rather than fixing it.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": "See `src/pkg:42`.\n"}, packages=self.PATHS_ONLY
            )
            (repo / "src" / "pkg").mkdir(parents=True)
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])
            self.assertEqual(found[0].token, "src/pkg:42")

    def test_remaining_false_positive_constructs_are_silent(self):
        """Four shapes that fired on correct documentation.

        Each is skipped by a *self-disabling* rule keyed on repository facts
        rather than a hardcoded string, so none can launder a real defect --
        asserted by the counter-cases below.
        """
        doc = "\n".join(
            [
                "State lives at `.phase-loop/state.json`.",
                "Cite as `Consiliency/agent-harness#<N>`, never a bare number.",
                "The repo is `Consiliency/agent-harness`.",
                "See `github.com/Consiliency/agent-harness`.",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"README.md": doc}, packages=self.PATHS_ONLY)
            (repo / ".gitignore").write_text(".phase-loop/state.json\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "gitignore the runtime artifact")
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=("README.md",))), [])

    def test_those_skips_cannot_launder_a_real_defect(self):
        # Counter-case for each: the rule is keyed on a repository fact, so it
        # stops applying the moment that fact changes.
        cases = {
            # not gitignored -> not a declared artifact -> still reported
            "State lives at `.phase-loop/state.json`.\n": ".phase-loop/state.json",
            # a slug for some OTHER repo is not this repo's identity
            "See `someone/else`.\n": "someone/else",
        }
        for doc, token in cases.items():
            with self.subTest(token=token), TemporaryDirectory() as tmp:
                repo = build_repo(tmp, {"README.md": doc}, packages=self.PATHS_ONLY)
                found = edc.check_repo(repo, entry_docs=("README.md",))
                self.assertEqual(codes(found), [("paths", "missing_path")])
                self.assertEqual(found[0].token, token)

        # host-shaped first segment that DOES exist resolves normally again
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": "See `example.com/x.md`.\n"}, packages=self.PATHS_ONLY
            )
            (repo / "example.com").mkdir()
            found = edc.check_repo(repo, entry_docs=("README.md",))
            self.assertEqual(codes(found), [("paths", "missing_path")])

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


class TestSlashCommandTokens(unittest.TestCase):
    """ah#600: harness docs invoke skills as `/claude-plan-phase`, not paths.

    Differential against origin/main before this change: `/claude-plan-phase` WAS
    reported `missing_path`, `/docs/does-not-exist.md` was too. After: only the
    slash-command stops being reported. That is the whole intended delta.
    """

    def test_slash_command_is_not_treated_as_a_path(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {
                    "phase-loop-runtime/README.md": (
                        "Invoke `/claude-phase-roadmap-builder` in your harness.\n"
                    )
                },
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [])

    def test_the_skip_cannot_launder_a_real_broken_path(self):
        """The guard that keeps the skip class honest.

        The skip is deliberately narrow -- ONE segment, NO extension. A
        multi-segment absolute path is still a path claim and must still resolve,
        or the class would be a hole rather than a kind.

        Mutation that must kill this: widen the skip to any leading-slash token.
        """
        for broken in ("/docs/does-not-exist.md", "/specs/missing/"):
            with self.subTest(token=broken):
                with TemporaryDirectory() as tmp:
                    repo = build_repo(
                        tmp,
                        {"phase-loop-runtime/README.md": f"See `{broken}` for details.\n"},
                    )
                    found = edc.check_repo(
                        repo, entry_docs=("phase-loop-runtime/README.md",)
                    )
                    self.assertEqual(codes(found), [("paths", "missing_path")])


class TestEntryDocRoles(unittest.TestCase):
    def test_entry_docs_is_the_union_of_both_roles(self):
        self.assertEqual(
            edc.ENTRY_DOCS,
            edc.PACKAGE_LONG_DESCRIPTION_DOCS + edc.ONBOARDING_DOCS,
        )

    def test_onboarding_docs_are_checked(self):
        """The ah#600 coverage gap: these were entry points by function, unchecked."""
        for doc in ("docs/TEAM-ONBOARDING.md", "docs/outside-worker-quickstart.md"):
            self.assertIn(doc, edc.ENTRY_DOCS)

    def test_onboarding_docs_are_not_package_long_descriptions(self):
        """They are checked, but they are not any package's declared README."""
        for doc in edc.ONBOARDING_DOCS:
            self.assertNotIn(doc, edc.PACKAGE_LONG_DESCRIPTION_DOCS)


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

    def test_flag_form_ref_pin_stale_is_reported(self):
        """ah#600 regression: `--ref v0.1.5` is the shipped defect, verbatim.

        `docs/TEAM-ONBOARDING.md` on main told every team to pin `--ref v0.1.5`
        while the latest release was six minors ahead. Arm 2 matched `@ref` and
        the URL forms but not the installer's own documented flag -- the spelling
        most likely to appear in an install doc.

        Mutation that must kill this: drop `_FLAG_REF_PIN_RE` from the scan.
        """
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {
                    "phase-loop-runtime/README.md": (
                        "```sh\nagent-harness/install-agent-harness.sh --ref v0.1.5\n```\n"
                    )
                },
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "stale_pin")])
            self.assertIn(FIXTURE_LATEST_TAG, found[0].message)

    def test_env_form_ref_pin_stale_is_reported(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"phase-loop-runtime/README.md": "```sh\nAGENT_HARNESS_REF=v0.1.5 ./install.sh\n```\n"},
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "stale_pin")])

    def test_flag_form_ref_placeholder_and_branch_are_silent(self):
        """The positive control: correct docs must stay green.

        The live `docs/TEAM-ONBOARDING.md` uses `--ref vX.Y.Z` since ah#602, and
        `--ref main` is a branch selector, not a release claim. Either firing
        would make this arm red on day one.
        """
        for spelling in ("--ref vX.Y.Z", "--ref <TAG>", "--ref main", "--ref HEAD"):
            with self.subTest(spelling=spelling):
                with TemporaryDirectory() as tmp:
                    repo = build_repo(
                        tmp,
                        {"phase-loop-runtime/README.md": f"```sh\n./install.sh {spelling}\n```\n"},
                    )
                    found = edc.check_repo(
                        repo, entry_docs=("phase-loop-runtime/README.md",)
                    )
                    self.assertEqual(codes(found), [])

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

    def _dynamic_version_repo(self, tmp, doc):
        repo = build_repo(tmp, {"phase-loop-runtime/README.md": doc})
        pyproject = repo / "phase-loop-runtime" / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                'version = "0.7.13"\n', 'dynamic = ["version"]\n'
            ),
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "switch to dynamic versioning")
        return repo

    def test_unresolvable_package_version_fails_closed(self):
        """A pin the check could not evaluate is reported, not skipped.

        `package is None` and "package found but version unreadable" were
        conflated. The first is somebody else's clock; the second is OUR
        distribution with a claim the check could not check -- fail-open on
        exactly the class this arm exists to catch, and silent per-distribution
        rather than repo-wide, so nothing else goes red to reveal it.
        """
        with TemporaryDirectory() as tmp:
            repo = self._dynamic_version_repo(tmp, "pip install phase-loop-runtime==0.1.0\n")
            self.assertEqual(
                edc.RepoContext(repo).package_for_distribution("phase-loop-runtime").version,
                "",
            )
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(codes(found), [("pins", "package_version_unresolved")])
            self.assertIn("pyproject.toml", found[0].message)

            # Through the REAL entry point, not just the unit under edit: a
            # finding that never changes the CLI verdict has not been wired in.
            self.assertEqual(edc.main(["entry_doc_check", "--repo", str(repo)]), 1)

    def test_a_third_party_pin_stays_silent(self):
        # The other half of the split: a distribution this repo does not define
        # is on somebody else's clock, so there is genuinely nothing to
        # evaluate. Fail-closed must not become "fail on every pin".
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"phase-loop-runtime/README.md": "pip install some-third-party==1.2.3\n"}
            )
            self.assertEqual(
                codes(edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))), []
            )

    def test_a_resolvable_version_still_reports_staleness(self):
        # The fail-closed path must not mask the verdict it stands in for.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"phase-loop-runtime/README.md": "pip install phase-loop-runtime==0.1.0\n"}
            )
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

    def test_distribution_names_are_matched_under_pep503(self):
        """Every legal spelling of the same distribution is one clock.

        A literal match silently skipped the underscore and mixed-case forms --
        and underscore is the module's own spelling, so it is the one most
        likely to appear in a doc. A silently skipped pin is worse than no
        check: the green implies coverage that does not exist.
        """
        for spelling in (
            "phase-loop-runtime==0.1.0",
            "phase_loop_runtime==0.1.0",
            "Phase-Loop-Runtime==0.1.0",
            "phase.loop.runtime==0.1.0",
            "phase-loop-runtime[extra]==0.1.0",
            "phase-loop-runtime == 0.1.0",
        ):
            with self.subTest(spelling=spelling), TemporaryDirectory() as tmp:
                repo = build_repo(tmp, {"phase-loop-runtime/README.md": f"pip install {spelling}\n"})
                found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
                self.assertEqual(codes(found), [("pins", "stale_pin")])
                self.assertIn("0.7.13", found[0].message)

    def test_a_fenced_comparison_is_not_a_pin(self):
        """`if dist == other:` in a code sample is not a version claim.

        Arm 2 scans fences deliberately, so an unconstrained right-hand side
        combined with whitespace tolerance turns a PEP-8-spaced Python
        comparison into a `stale_pin`. The whitespace tolerance is needed for
        unquoted requirements samples, so the RHS is constrained to
        version-shaped-or-placeholder instead. Both halves asserted in the same
        fence: the comparison is silent, the real pin beside it still reports.
        """
        doc = "\n".join(
            [
                "```python",
                "if phase_loop_runtime == other:",
                "    pass",
                "```",
            ]
        )
        pkgs = {"phase-loop-runtime": ("phase-loop-runtime", "0.7.13", "README.md")}
        docs = ("phase-loop-runtime/README.md",)
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": doc}, packages=pkgs)
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=docs)), [])

        with_pin = (
            "```python\n"
            "if phase_loop_runtime == other:\n"
            "    pass\n"
            "# pip install phase_loop_runtime==0.1.0\n"
            "```\n"
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": with_pin}, packages=pkgs)
            found = edc.check_repo(repo, entry_docs=docs)
            self.assertEqual(codes(found), [("pins", "stale_pin")])
            self.assertEqual(found[0].token, "phase_loop_runtime==0.1.0")

    def test_ranges_are_not_pins_under_any_spelling(self):
        # `>=` and `~=` are ranges, not claims about a current version, so they
        # have nothing to be stale against. Normalisation must not sweep them in.
        doc = "\n".join(
            [
                "Sole dependency: `phase_loop_runtime>=0.6.1`.",
                "Compatible release: `phase_loop_runtime~=0.7.0`.",
                "Correct pin: `phase_loop_runtime==0.7.13`.",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": doc})
            self.assertEqual(
                codes(edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))), []
            )

    def test_release_url_forms_are_pins_too(self):
        """`@ref` is only one spelling of a release claim.

        A doc pointing at `/releases/tag/vX`, `/tree/vX` or an archive tarball
        asserts the same thing about the repository's current release and rots
        the same way. This is a different GRAMMAR for one clock, not a second
        clock -- it reuses the release-namespace comparison rather than
        introducing another notion of freshness.
        """
        docs = ("phase-loop-runtime/README.md",)
        for url in (
            "https://github.com/Consiliency/agent-harness/releases/tag/v0.1.5",
            "https://github.com/Consiliency/agent-harness/tree/v0.1.5",
            "https://github.com/Consiliency/agent-harness/archive/refs/tags/v0.1.5.tar.gz",
            "See https://github.com/Consiliency/agent-harness/releases/tag/v0.1.5.",
        ):
            with self.subTest(url=url), TemporaryDirectory() as tmp:
                repo = build_repo(tmp, {"phase-loop-runtime/README.md": url + "\n"})
                found = edc.check_repo(repo, entry_docs=docs)
                self.assertEqual(codes(found), [("pins", "stale_pin")])
                self.assertIn(FIXTURE_LATEST_TAG, found[0].message)

    def test_release_url_adversarial_positives_are_silent(self):
        # The archive suffix and a trailing full stop are not part of the tag;
        # `latest` names no tag; a branch is not a pin; another repo is another
        # clock. Any of these misread would fire on correct documentation.
        doc = "\n".join(
            [
                "https://github.com/Consiliency/agent-harness/releases/tag/v0.7.13",
                "https://github.com/Consiliency/agent-harness/archive/refs/tags/v0.7.13.tar.gz",
                "https://github.com/Consiliency/agent-harness/releases/latest",
                "https://github.com/Consiliency/agent-harness/tree/main",
                "https://github.com/Consiliency/agent-harness/tree/main/phase-loop-skills",
                "https://github.com/other/project/releases/tag/v0.1.5",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": doc})
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
            # Not only a shallow clone: Gate A's standalone tree is a plain copy
            # with no `.git` at all, so this guard SKIPS there rather than
            # running. Named precisely because "did not fail" is not "ran".
            self.skipTest(
                "commit 8f191d99 unreadable at REPO_ROOT (shallow clone, or a "
                "standalone copy with no git history)"
            )
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

    def test_html_destinations_are_parsed(self):
        """Markdown permits raw HTML, and badges are written as `<img src=...>`.

        A grammar covering only markdown links misses the single most common
        relative destination in a real README -- this arm's own defect class,
        in its most likely form.
        """
        doc = "\n".join(
            [
                '<img src="docs/logo.png" alt="logo">',
                '<a href="../phase-loop-skills">skills</a>',
                "[markdown too](../also-relative)",
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": doc})
            found = edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))
            self.assertEqual(
                sorted(f.token for f in found),
                ["../also-relative", "../phase-loop-skills", "docs/logo.png"],
            )
            self.assertTrue(all(f.arm == "published_rendering" for f in found))
            # Through the real entry point, not only the unit under edit.
            self.assertEqual(edc.main(["entry_doc_check", "--repo", str(repo)]), 1)

    def test_html_adversarial_positives_are_silent(self):
        doc = "\n".join(
            [
                '<img src="https://img.shields.io/badge/build-passing.svg" alt="badge">',
                "<a href='#install'>install</a>",
                '<a href="https://github.com/Consiliency/agent-harness">repo</a>',
                '<img src="//cdn.example.com/x.png">',
                "",
                "```html",
                '<img src="docs/sample.png">',
                "```",
                "",
                'Write it as `<img src="docs/inline.png">` in your README.',
            ]
        )
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": doc})
            self.assertEqual(
                codes(edc.check_repo(repo, entry_docs=("phase-loop-runtime/README.md",))), []
            )

    def test_html_in_the_root_readme_is_not_reported(self):
        # Same destination, both docs checked in one run: only the published
        # one is a defect, exactly as for markdown links.
        docs = ("README.md", "phase-loop-runtime/README.md")
        html = '<img src="docs/logo.png">\n'
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": html, "phase-loop-runtime/README.md": "no links\n"}
            )
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=docs)), [])
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": "no links\n", "phase-loop-runtime/README.md": html}
            )
            found = edc.check_repo(repo, entry_docs=docs)
            self.assertEqual(
                codes(found), [("published_rendering", "relative_link_in_published_readme")]
            )
            self.assertEqual(found[0].file, "phase-loop-runtime/README.md")

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


class TestDeletedEntryDoc(unittest.TestCase):
    """A check whose green survives deleting the thing it checks is vacuous."""

    def test_declared_but_absent_entry_doc_is_reported(self):
        # The RED direction, asserted directly. "The suite still passes after
        # flipping the behaviour on" shows nothing broke, not that the new
        # finding exists.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": "root\n"}, packages={"": ("demo", "1.0.0", None)}
            )
            found = edc.check_repo(repo, entry_docs=("README.md", "AGENTS.md"))
            self.assertEqual(codes(found), [("coverage", "missing_entry_doc")])
            self.assertEqual(found[0].file, "AGENTS.md")

    def test_deleting_a_doc_flips_the_verdict(self):
        # Same repo, same inventory, one file removed -- the only variable.
        docs = ("README.md", "AGENTS.md")
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp,
                {"README.md": "root\n", "AGENTS.md": "agents\n"},
                packages={"": ("demo", "1.0.0", None)},
            )
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=docs)), [])
            (repo / "AGENTS.md").unlink()
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "delete AGENTS.md")
            # Committed, which is what CI and a merge commit see -- the case a
            # "present in HEAD" discriminator cannot distinguish from a repo
            # that never had the file.
            self.assertEqual(
                codes(edc.check_repo(repo, entry_docs=docs)),
                [("coverage", "missing_entry_doc")],
            )

    def test_a_repo_checked_against_its_own_inventory_stays_silent(self):
        # The parameter IS the discriminator: a consumer or fixture that passes
        # its own list is never held to docs it does not own. This is what makes
        # requiring existence safe without any git probing.
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"README.md": "root\n"}, packages={"": ("demo", "1.0.0", None)}
            )
            self.assertEqual(codes(edc.check_repo(repo, entry_docs=("README.md",))), [])


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
    """Exit codes are split by posture-dependence, not guarded wholesale.

    Only assertions that read the live tree need the canonical checkout. The
    synthetic-repo and usage-error paths are posture-independent and must keep
    running everywhere, including the standalone clean room -- blanket-guarding
    the whole test would silently stop exercising them.
    """

    def test_exit_code_1_on_findings(self):
        with TemporaryDirectory() as tmp:
            repo = build_repo(
                tmp, {"phase-loop-runtime/README.md": "pip install phase-loop-runtime==0.7.12\n"}
            )
            self.assertEqual(edc.main(["entry_doc_check", "--repo", str(repo)]), 1)

    def test_exit_code_2_on_usage_error(self):
        self.assertEqual(edc.main(["entry_doc_check", "--repo", "/nonexistent/xyz"]), 2)

    def test_file_narrowing_rejects_a_non_entry_doc(self):
        # There is no loose-file mode: /tmp/old.md has no owning package and no
        # suppression identity. Independent of tree posture -- the rejection is
        # decided by ENTRY_DOCS membership, not by what is on disk.
        with TemporaryDirectory() as tmp:
            repo = build_repo(tmp, {"phase-loop-runtime/README.md": "x\n"})
            self.assertEqual(
                edc.main(["entry_doc_check", "--repo", str(repo), "--file", "/tmp/old.md"]), 2
            )

    @CANONICAL_ONLY
    def test_exit_code_0_on_the_live_repo(self):
        self.assertEqual(edc.main(["entry_doc_check", "--repo", str(REPO_ROOT)]), 0)

    @CANONICAL_ONLY
    def test_file_narrowing_accepts_a_live_entry_doc(self):
        # Canonical-only because a partial tree has no root README.md, and a
        # declared-but-absent entry doc is now REPORTED (exit 1) rather than
        # skipped -- so this asserts the clean path only where the doc exists.
        self.assertTrue((REPO_ROOT / "README.md").is_file())
        self.assertEqual(
            edc.main(["entry_doc_check", "--repo", str(REPO_ROOT), "--file", "README.md"]), 0
        )


if __name__ == "__main__":
    unittest.main()
