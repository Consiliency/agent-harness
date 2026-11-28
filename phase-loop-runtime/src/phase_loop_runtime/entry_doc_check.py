"""Diff-independent verification of entry-point documentation (agent-harness#568).

``docs_audit`` is change-coupled by contract: it classifies *changed paths* and
enforces that a changed public surface carries a doc decision. It answers "did
the docs change when the code changed?" and structurally cannot answer "are the
docs still true?". Every defect this module targets arose with **no diff
touching the doc** -- a ``v0.1.5`` install pin that rotted through six releases
untouched, a relative link that renders on GitHub but breaks on PyPI.

Four arms, each fully decidable offline:

  (1) ``paths``              -- backtick tokens that look like repo paths resolve.
  (2) ``pins``               -- version pins are *fresh*, not merely resolvable.
  (3) ``published_rendering`` -- a README shipped as a package long-description
                                carries no relative link destinations.
  (4) ``cli_flags``          -- ``phase-loop <subcommand> --flag`` spans in
                                ``docs/``, ``skills-src/``, and entry docs match
                                the live ``phase-loop`` CLI parser (``--help``).

Two clocks, never crossed
-------------------------
A distribution pin (``dist==V``) is a claim about *that distribution's* current
version and is compared against its own ``pyproject.toml``. A git ref
(``@vX.Y.Z``) is a claim about *the repository's* latest release and is compared
against the release-tag namespace (``v[0-9]*``, version-sorted). These are
different clocks; comparing one against the other is a defect, not a shortcut.

The rule for a pin is **not** "does this ref exist" -- ``v0.1.5`` is a real tag,
so an existence rule passes the exact historical defect this arm exists to
catch. Pins are checked for staleness.

Zero external deps (stdlib only). Importable API + ``main(argv) -> int`` +
``python3 -m phase_loop_runtime.entry_doc_check``, mirroring ``roadmap_lint``.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import itertools
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .skill_paths import HARNESS_DEFAULT_SKILL_ROOTS


# ---------------------------------------------------------------------------
# Surfaces

#: Explicit allowlist. Globs cannot express "package roots only", and the tree
#: carries dozens of generated override READMEs under ``phase-loop-skills/**``
#: that are not entry points. Reconciled against every package's
#: ``[project].readme`` by :func:`check_entry_doc_coverage` -- a long-description
#: path missing from this tuple is itself a finding, otherwise a new package
#: README is silently uncovered by the very check meant to cover it.
#: The package/repo front doors -- the docs that are some package's declared
#: long-description. Named separately so the tuple's membership rule is legible;
#: previously this list and the onboarding docs were one tuple and nothing said
#: which entries were present for which reason.
#:
#: NOTE ``check_entry_doc_coverage`` deliberately reconciles against the FULL
#: checked set (``ENTRY_DOCS``), not against this narrower tuple. Its assertion is
#: "no package long-description goes UNCHECKED", and the checked set is the union
#: -- so a package README listed under either role satisfies it. Narrowing the
#: reconciliation would flag a README that is in fact being checked.
PACKAGE_LONG_DESCRIPTION_DOCS: Tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "phase-loop-runtime/README.md",
    "phase-loop-skills/README.md",
    "consiliency-harness/README.md",
)

#: Entry points by FUNCTION rather than by packaging -- what a new human or agent
#: is actually pointed at. They carry install instructions, so they are exactly
#: where a stale pin does the most damage, and ah#600 is the proof: a `--ref v0.1.5`
#: six minors behind sat in TEAM-ONBOARDING.md on `main`, uncovered.
#:
#: Deliberately NOT in PACKAGE_LONG_DESCRIPTION_DOCS: these are not any package's
#: long-description, and the coverage arm must keep reconciling against that
#: narrower set or it would stop reporting an unlisted package README.
ONBOARDING_DOCS: Tuple[str, ...] = (
    "CONTRIBUTING.md",
    "docs/TEAM-ONBOARDING.md",
    "docs/outside-worker-quickstart.md",
)

#: Directories scanned by Arm 4 (``cli_flags``) for ``phase-loop <sub> --flag``
#: drift beyond the entry docs (agent-harness#1612).
CLI_FLAG_DOC_ROOTS: Tuple[str, ...] = (
    "docs",
    "skills-src",
)

#: Everything the arms read. The union of two roles that used to be one tuple --
#: the conflation was harmless (the coverage check is a one-directional subset
#: test, so growing it kept both green) but unreadable: nothing said which entries
#: were present because a package declares them and which because someone wanted
#: them checked.
ENTRY_DOCS: Tuple[str, ...] = PACKAGE_LONG_DESCRIPTION_DOCS + ONBOARDING_DOCS

#: Closed, **position-sensitive** placeholder grammar.
#:
#: A ref position names a git tag, so only ``<TAG>`` is meaningful there. A
#: version position names a version, so ``<VERSION>`` and the bare metavariable
#: ``X.Y.Z`` are both correct -- the live root README uses ``X.Y.Z`` twice
#: (``README.md:66``, ``:92``) and rejecting it would make the positive control
#: red on day one. ``<PATH>``/``<HARNESS>`` are path/CLI metavariables and are
#: never valid in a pin position.
REF_PLACEHOLDERS: Tuple[str, ...] = ("<TAG>",)
VERSION_PLACEHOLDERS: Tuple[str, ...] = ("<VERSION>", "X.Y.Z")

#: POSIX install-layout roots. A token rooted at one of these names a
#: *destination on an installed system*, not a path in this repository -- e.g.
#: ``share/phase-loop-runtime/protocol/protocol.md``. The class is
#: self-disabling: it only applies when the segment does not exist in the repo,
#: so a repository that really does have a ``lib/`` resolves its paths normally.
INSTALL_LAYOUT_ROOTS: frozenset = frozenset(
    {"bin", "sbin", "lib", "lib64", "libexec", "share", "include", "etc", "var", "opt", "usr"}
)

#: POSIX system roots. An **absolute** token rooted at one of these names a
#: runtime location on the host -- ``/tmp``, ``/run``, ``/proc`` -- not a path
#: in this repository.
#:
#: Deliberately NOT "skip everything starting with ``/``". A token like
#: ``/README.md`` is a repo-**root**-relative reference, a real way to write a
#: path when a doc lives in a subdirectory, and it should still be checked.
#: So a leading slash changes *where* a path resolves from (repo root only,
#: never the document's own directory) and only a recognised system root makes
#: it a non-repo claim. Self-disabling like :data:`INSTALL_LAYOUT_ROOTS`: a
#: repository that really contains ``tmp/`` resolves ``/tmp`` normally.
ABSOLUTE_SYSTEM_ROOTS: frozenset = frozenset(
    {
        "tmp", "run", "proc", "dev", "sys", "etc", "var", "usr", "opt",
        "boot", "mnt", "media", "srv", "lib", "lib64", "bin", "sbin",
        "home", "root",
    }
)

#: Where suppressions live, relative to ``--repo``.
SUPPRESSIONS = ".github/entry-doc-suppressions.json"

_RELEASE_TAG_GLOB = "v[0-9]*"


# ---------------------------------------------------------------------------
# Data model


@dataclass(frozen=True)
class Finding:
    """One defect.

    ``code`` is the machine-readable reason a suppression must cite; ``token``
    is the offending text, hashed into the suppression fingerprint so that
    suppressions survive line-number churn.
    """

    file: str
    line: int
    arm: str
    message: str
    code: str
    token: str = ""

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.file, self.code, self.token)

    def render(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        return f"{where}: [{self.arm}/{self.code}] {self.message}"

    def to_dict(self) -> Dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "arm": self.arm,
            "code": self.code,
            "message": self.message,
            "token": self.token,
            "fingerprint": self.fingerprint,
        }


def fingerprint(file: str, code: str, token: str) -> str:
    digest = hashlib.sha256("\0".join((file, code, token)).encode("utf-8")).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------
# Markdown structure


_FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def _fence_mask(lines: Sequence[str]) -> List[bool]:
    """Return per-line flags: ``True`` where the line is inside a fenced block.

    The fence markers themselves are flagged too -- nothing on them is prose.

    Per CommonMark a fence closes only on a run of the **same character** that
    is **at least as long** as the opener, so a ``` line does not close a ````
    block. Discarding the opener's length inverts the mask from that point on:
    arm 1 then scans fenced content (a false positive on a token inside a code
    block) while arm 3 stops scanning real link destinations. Nested fences are
    exactly what a README quoting a fenced example contains.
    """
    inside = [False] * len(lines)
    opener_char: Optional[str] = None
    opener_len = 0
    for idx, line in enumerate(lines):
        match = _FENCE_RE.match(line)
        if opener_char is None:
            if match:
                opener_char = match.group(2)[0]
                opener_len = len(match.group(2))
                inside[idx] = True
            continue
        inside[idx] = True
        if (
            match
            and match.group(2)[0] == opener_char
            and len(match.group(2)) >= opener_len
            and not match.group(3).strip()
        ):
            opener_char = None
            opener_len = 0
    return inside


def _mask_inline_code(line: str) -> str:
    """Blank out inline code spans, preserving offsets."""
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)


# ---------------------------------------------------------------------------
# Repo context


class RepoContext:
    """Everything the arms need to resolve a claim, resolved once per run."""

    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self._tracked: Optional[List[str]] = None
        self._dir_components: Optional[Set[str]] = None
        self._latest_tag: Optional[str] = None
        self._latest_tag_resolved = False
        self._packages: Optional[Dict[str, "PackageInfo"]] = None
        self._packages_by_norm: Optional[Dict[str, "PackageInfo"]] = None
        self._identities: Optional[Set[Tuple[str, str]]] = None

    # -- filesystem -----------------------------------------------------
    def exists(self, rel: str) -> bool:
        candidate = (self.repo / rel).resolve()
        try:
            candidate.relative_to(self.repo)
        except ValueError:
            return False
        return candidate.exists()

    # -- git ------------------------------------------------------------
    def _git(self, *args: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.repo), *args],
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, ValueError):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout

    @property
    def tracked_paths(self) -> List[str]:
        if self._tracked is None:
            out = self._git("ls-files")
            if out is None:
                self._tracked = [
                    str(p.relative_to(self.repo))
                    for p in self.repo.rglob("*")
                    if p.is_file() and ".git" not in p.parts
                ]
            else:
                self._tracked = [line for line in out.splitlines() if line]
        return self._tracked

    def is_ignored(self, rel: str) -> bool:
        """True when the repo's own gitignore declares ``rel`` an artifact.

        The discriminator for runtime-created paths (`.phase-loop/state.json`)
        is the repository's own configuration, not a hardcoded list: if git
        says the path is ignored, the repo has already declared it generated
        rather than tracked, so documenting it is correct even though it is
        absent from a clean checkout.
        """
        return self._git("check-ignore", "-q", "--", rel) is not None

    def is_remote_tracking_ref(self, ref: str) -> bool:
        """True when ``ref`` resolves to a real ``refs/remotes/<ref>`` in git.

        Allows entry docs like ``CONTRIBUTING.md`` to cite ``origin/main`` as a
        backticked git ref without blanket-skipping typos like ``origin/mian``.
        """
        if not ref or ref.startswith("/") or ref.startswith("-") or "/" not in ref or ".." in ref:
            return False
        return self._git("show-ref", "--verify", "--quiet", f"refs/remotes/{ref}") is not None

    def has_directory_prefix(self, prefix: str) -> bool:
        """True if ``prefix`` occurs as a directory-path component sequence.

        The third rung of the metavariable prefix ladder. ``_overrides/`` lives
        only at ``phase-loop-skills/<skill>/_overrides/``, so a root-or-docdir
        test alone would flag ``_overrides/<harness>/`` -- correct documentation
        in two live entry docs.
        """
        needle = prefix.strip("/")
        if not needle:
            return False
        for path in self.tracked_paths:
            if path.startswith(needle + "/") or ("/" + needle + "/") in path:
                return True
        return False

    @property
    def latest_release_tag(self) -> Optional[str]:
        """Latest tag in the **release namespace**.

        ``git tag --list 'v[0-9]*' --sort=-v:refname | head -1``. Both halves
        are load-bearing: lexical sort yields ``v0.7.9`` where version sort
        yields ``v0.7.13``, and the filter excludes non-release tags -- one of
        which, ``consiliency-harness-v0.6.1``, is *a different package's*
        release tag.
        """
        if not self._latest_tag_resolved:
            self._latest_tag_resolved = True
            out = self._git("tag", "--list", _RELEASE_TAG_GLOB, "--sort=-v:refname")
            if out:
                tags = [t for t in out.splitlines() if t.strip()]
                self._latest_tag = tags[0].strip() if tags else None
        return self._latest_tag

    # -- packages -------------------------------------------------------
    @property
    def packages(self) -> Dict[str, "PackageInfo"]:
        if self._packages is None:
            self._packages = _discover_packages(self.repo)
        return self._packages

    def package_for_distribution(self, dist: str) -> Optional["PackageInfo"]:
        """Look a distribution up under PEP 503 normalisation, not literally."""
        if self._packages_by_norm is None:
            self._packages_by_norm = {
                normalize_dist_name(name): pkg for name, pkg in self.packages.items()
            }
        return self._packages_by_norm.get(normalize_dist_name(dist))

    @property
    def repo_identities(self) -> Set[Tuple[str, str]]:
        """``(owner, repo)`` pairs that denote *this* repository.

        Sourced from the ``origin`` remote when present and from every
        package's ``[project.urls]``, so a constructed fixture with no remote
        still has an identity.
        """
        if self._identities is None:
            found: Set[Tuple[str, str]] = set()
            remote = self._git("remote", "get-url", "origin")
            for text in [remote or ""] + [pkg.urls_blob for pkg in self.packages.values()]:
                for owner, name in _GITHUB_SLUG_RE.findall(text):
                    found.add((owner.lower(), name.lower().removesuffix(".git")))
            self._identities = found
        return self._identities

    def package_for_doc(self, doc_path: str) -> Optional["PackageInfo"]:
        """The package whose ``[project].readme`` *is* ``doc_path``."""
        for pkg in self.packages.values():
            if pkg.readme_logical_path == doc_path:
                return pkg
        return None


@dataclass(frozen=True)
class PackageInfo:
    name: str
    version: str
    directory: str
    readme: str
    urls_blob: str

    @property
    def readme_logical_path(self) -> str:
        if not self.readme:
            return ""
        return f"{self.directory}/{self.readme}" if self.directory else self.readme


_GITHUB_SLUG_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+)")
_NORMALIZE_DIST_RE = re.compile(r"[-_.]+")


def normalize_dist_name(name: str) -> str:
    """PEP 503 normalisation: runs of ``-_.`` collapse to ``-``, lowercased.

    ``phase-loop-runtime``, ``phase_loop_runtime`` and ``Phase-Loop-Runtime``
    are the same distribution to pip, so a literal match silently skips two of
    the three -- and the underscore form is the module's own spelling, making
    it the one most likely to appear in a doc. A pin that is silently skipped
    is worse than no check: the green implies coverage that does not exist.
    """
    return _NORMALIZE_DIST_RE.sub("-", name).lower()


def _parse_pyproject(text: str) -> Dict[str, str]:
    """Extract the ``[project]`` scalars this check needs (``name``/``version``/``readme``)."""
    try:
        data = tomllib.loads(text)
        project = data.get("project", {}) or {}
        readme = project.get("readme", "")
        if isinstance(readme, dict):
            readme = readme.get("file", "")
        return {
            "name": str(project.get("name", "")),
            "version": str(project.get("version", "")),
            "readme": str(readme or ""),
        }
    except Exception:
        return {}


def _discover_packages(repo: Path) -> Dict[str, PackageInfo]:
    packages: Dict[str, PackageInfo] = {}
    candidates = [repo / "pyproject.toml"] + sorted(repo.glob("*/pyproject.toml"))
    for pyproject in candidates:
        if not pyproject.is_file():
            continue
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        fields = _parse_pyproject(text)
        if not fields.get("name"):
            continue
        directory = str(pyproject.parent.relative_to(repo)).replace("\\", "/")
        if directory == ".":
            directory = ""
        packages[fields["name"]] = PackageInfo(
            name=fields["name"],
            version=fields.get("version", ""),
            directory=directory,
            readme=fields.get("readme", ""),
            urls_blob=text,
        )
    return packages


# ---------------------------------------------------------------------------
# Arm 1 -- paths


#: What a path *claim* may be spelled with. Deliberately a closed character set
#: rather than "anything without whitespace": a backtick span holding markdown
#: syntax (``[x](../y)``) or shell punctuation is not a path claim, and letting
#: it through would report a defect the document never asserted.
_PATH_TOKEN_RE = re.compile(r"^[\w.~<>*?/@:#+%-]+$")
#: ``owner/repo#123`` and the metavariable form ``owner/repo#<N>`` that this
#: repo's own AGENTS.md uses when describing the convention rather than citing.
_ISSUE_CITATION_RE = re.compile(r"^[\w.-]+/[\w.-]+#(?:\d+|<[^<>]+>)$")
#: A dotted hostname as the first segment -- a URL written without its scheme
#: (``github.com/Consiliency/agent-harness``). Self-disabling: only applies when
#: no such directory exists in the repo.
_SCHEMELESS_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+$", re.IGNORECASE)
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_METAVAR_RE = re.compile(r"<[^<>]*>")
#: ``path/to/file.py:42`` and ``path/to/file.py:42:7`` -- this repo's own
#: citation convention, used throughout its docs, issues and reviews.
_FILE_LINE_CITATION_RE = re.compile(r"^(?P<path>.+?):(?P<line>\d+)(?::\d+)?$")


def _strip_line_citation(token: str) -> str:
    """Return the path part of a ``file:line`` citation, else ``token``.

    A *check*, not a skip: the path still has to resolve. Only the line-number
    suffix is removed, so a citation of a file that does not exist is still
    reported -- what changes is that a citation of a file that DOES exist stops
    being a false positive.
    """
    match = _FILE_LINE_CITATION_RE.match(token)
    return match.group("path") if match else token


def _concrete_prefix(token: str) -> str:
    """The leading segments of ``token`` that contain no metavariable."""
    segments = token.strip("/").split("/")
    concrete: List[str] = []
    for segment in segments:
        if _METAVAR_RE.search(segment):
            break
        concrete.append(segment)
    return "/".join(concrete)


def _resolves(ctx: RepoContext, doc_dir: str, rel: str, require_file: bool = False) -> bool:
    """Repo-root first, then the document's own directory.

    A trailing extension-less basename also resolves against a same-stem
    sibling: the live docs write ``.consiliency/manifest`` for the artifact the
    runtime creates as ``.consiliency/manifest.json``.
    """
    cleaned = rel.strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    # A leading slash means repo-ROOT-relative, so the document's own directory
    # is not a candidate base -- `/README.md` in a package README refers to the
    # root README, not a sibling of the file it appears in.
    absolute = cleaned.startswith("/")
    cleaned = cleaned.lstrip("/").rstrip("/")
    if not cleaned:
        return False
    bases = [""] if (absolute or not doc_dir) else ["", doc_dir]
    for base in bases:
        candidate = f"{base}/{cleaned}" if base else cleaned
        if ctx.exists(candidate):
            if not require_file or (ctx.repo / candidate).is_file():
                return True
            continue
        if "." not in Path(cleaned).name:
            parent = (ctx.repo / candidate).parent
            stem = Path(candidate).name
            try:
                if parent.is_dir() and any(parent.glob(stem + ".*")):
                    return True
            except OSError:
                pass
    return False


#: Harness skill invocations: `/claude-plan-phase`, `/codex-advisor-panel`. Docs tell
#: you to RUN these, so they are pervasive in an onboarding doc, but they are not
#: paths. Keyed on this repo's actual skill-naming convention (`<harness>-<name>`)
#: rather than on SHAPE: an earlier version skipped any single-segment extensionless
#: absolute, which laundered `/LICENCE` and `/docs-does-not-exist` -- both reported
#: by the base code, both silent under the shape rule. A skip class must name a KIND
#: of token narrowly enough that a typo cannot wear its costume.
_SLASH_COMMAND_RE = re.compile(
    r"^/(?:" + "|".join(sorted(HARNESS_DEFAULT_SKILL_ROOTS)) + r")-[a-z0-9]+(?:-[a-z0-9]+)*$"
)


def check_paths(text: str, doc_path: str, ctx: RepoContext) -> List[Finding]:
    """Arm 1: backtick tokens that look like repo paths must resolve.

    Skip classes, each of which describes a *kind* of token rather than a
    specific string, so none of them can be used to launder a real defect:
    fenced code blocks, ``~``-prefixed home paths, ``owner/repo#N`` issue
    citations (this repo's own convention), URL schemes, ``*`` globs, and
    install-layout destinations.

    Metavariable tokens are **not** blanket-skipped: the concrete parent prefix
    is still validated, so ``spces/<NAME>.md`` is caught while
    ``specs/phase-plans-v<N>.md`` and ``_overrides/<harness>/`` pass.
    """
    findings: List[Finding] = []
    doc_dir = str(Path(doc_path).parent).replace("\\", "/")
    if doc_dir == ".":
        doc_dir = ""
    lines = text.split("\n")
    inside = _fence_mask(lines)

    for idx, line in enumerate(lines):
        if inside[idx]:
            continue
        for match in _INLINE_CODE_RE.finditer(line):
            token = match.group(1).strip()
            lineno = idx + 1
            if "/" not in token or not _PATH_TOKEN_RE.match(token):
                # Multi-word spans are prose or shell commands, not path claims.
                continue
            if _URL_SCHEME_RE.match(token) or token.startswith("//"):
                continue
            if token.startswith("~"):
                continue
            if _ISSUE_CITATION_RE.match(token):
                continue
            if any(ch in token for ch in "*?"):
                continue
            root = token.strip("/").split("/", 1)[0]
            if _SCHEMELESS_HOST_RE.match(root) and not ctx.exists(root):
                # A URL written without its scheme, not a repo path.
                continue
            if (root.lower(), token.split("/", 1)[-1].lower()) in ctx.repo_identities:
                # A bare `owner/repo` slug naming this repository.
                continue
            if token.startswith("/"):
                if root in ABSOLUTE_SYSTEM_ROOTS and not ctx.exists(root):
                    continue
                if _SLASH_COMMAND_RE.match(token):
                    # A skill invocation, not a path -- see _SLASH_COMMAND_RE.
                    continue
            elif root in INSTALL_LAYOUT_ROOTS and not ctx.exists(root):
                continue
            if _METAVAR_RE.search(token):
                prefix = _concrete_prefix(token)
                if not prefix:
                    continue
                if (
                    _resolves(ctx, doc_dir, prefix)
                    or ctx.has_directory_prefix(prefix)
                ):
                    continue
                findings.append(
                    Finding(
                        file=doc_path,
                        line=lineno,
                        arm="paths",
                        code="missing_path_prefix",
                        token=token,
                        message=(
                            f"`{token}` uses a metavariable, but its concrete prefix "
                            f"`{prefix}/` exists nowhere in the repository."
                        ),
                    )
                )
                continue
            # Literal FIRST: a real file may legitimately have a colon in its
            # name (`data/log:2024`), and stripping unconditionally turns it
            # into a phantom missing path.
            if _resolves(ctx, doc_dir, token):
                continue
            target = _strip_line_citation(token)
            # A citation must point at a FILE. `src/pkg:42` where `src/pkg` is a
            # directory is nonsense, and accepting any resolvable target would
            # silently drop a finding the unstripped check used to make.
            if target != token and _resolves(ctx, doc_dir, target, require_file=True):
                continue
            if ctx.is_ignored(token.lstrip("/")):
                # A generated/runtime artifact by the repo's own declaration.
                continue
            if not token.startswith("/") and ctx.is_remote_tracking_ref(token):
                # A real git remote-tracking ref (for example `origin/main`),
                # not a repository path.
                continue
            findings.append(
                Finding(
                    file=doc_path,
                    line=lineno,
                    arm="paths",
                    code="missing_path",
                    token=token,
                    message=(
                        f"`{token}` looks like a repository path but resolves neither "
                        f"from the repo root nor from {doc_dir or '.'}/."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Arm 2 -- pin freshness


#: ``dist==V``, tolerating PEP 508 extras and whitespace around the operator.
#: Deliberately ``==`` only: ``>=`` and ``~=`` are ranges, not claims about a
#: current version, so they have nothing to be stale against.
#: The right-hand side must be **version-shaped or a placeholder**, not any
#: bare token. Tolerating whitespace around ``==`` is required for unquoted
#: requirements samples, but combined with an unconstrained RHS it reads a
#: fenced Python comparison (``if phase_loop_runtime == other:``) as a pin --
#: and arm 2 scans fences deliberately, so that reaches the output.
_DIST_PIN_RE = re.compile(
    r"(?<![\w.-])(?P<dist>[A-Za-z][A-Za-z0-9._-]*[A-Za-z0-9])"
    r"(?:\[[A-Za-z0-9._,-]+\])?\s*==\s*"
    r"(?P<version>[0-9][^\s\"'`,;)\]]*|X\.Y\.Z|<[^<>\s]+>)"
)
_GIT_REF_PIN_RE = re.compile(
    r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?@(?P<ref>[^\s\"'`#)\]]+)"
)
#: The same claim in URL form. `@ref` is only one way to name a release; a doc
#: pointing at `/releases/tag/vX`, `/tree/vX` or `/archive/refs/tags/vX.tar.gz`
#: asserts exactly the same thing about the repository's current release and
#: rots exactly the same way. A different GRAMMAR for one clock, not a
#: different clock -- so it reuses the release-namespace comparison rather than
#: introducing a second notion of freshness.
_URL_TAG_PIN_RE = re.compile(
    r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/"
    r"(?:releases/tag|tree|archive/refs/tags)/"
    r"(?P<ref>v[0-9][0-9A-Za-z._-]*)"
)

#: The same claim in CLI-flag form. `--ref vX` and `AGENT_HARNESS_REF=vX` are the
#: installer's OWN documented interface (`install-agent-harness.sh --ref vX.Y.Z`),
#: which makes the flag the spelling most likely to appear in an install doc --
#: precisely where a stale pin does the most damage. ah#600: a `--ref v0.1.5`,
#: six minors behind, reached `main` in `docs/TEAM-ONBOARDING.md` and no arm saw it.
#:
#: Unlike the URL forms this names NO owner/repo, so it cannot be identity-gated.
#: An unqualified ref in a doc belonging to this repository is a claim about THIS
#: repository's release namespace -- which is the only reading that makes sense for
#: an install instruction. The tag-shape gate (`^v[0-9]`) and the placeholder
#: grammar keep correct docs silent; a third-party tool's `--ref vX` in one of our
#: entry docs would be a false positive, and is the case for a suppression.
_FLAG_REF_PIN_RE = re.compile(
    r"(?:--ref[=\s]+|\bAGENT_HARNESS_REF=)"
    r"[\"']?(?P<ref>[^\s\"'`#)\],;]+)[\"']?"
)

#: Archive suffixes and sentence punctuation that ride along on a URL-form ref.
_REF_SUFFIX_RE = re.compile(r"(?:\.tar\.gz|\.tgz|\.zip)$", re.IGNORECASE)


def _is_workflow_dispatch_ref(line: str, match_start: int, matched_text: str) -> bool:
    """True when ``--ref`` belongs to ``gh workflow run ... --ref <branch>``.

    GitHub CLI's ``gh workflow run --ref`` selects a branch or ref to dispatch a
    workflow on, not an ``agent-harness`` install release-tag pin. Parses the
    prefix before ``match_start`` with quote- and operator-aware shell
    tokenization (handling ``;``, ``|``, ``||``, ``&``, ``&&``, ``(`` and quoted
    arguments) and requires ``gh workflow run`` in command position.
    """
    if not matched_text.startswith("--ref"):
        return False
    prefix = line[:match_start]
    if "`" in prefix:
        prefix = prefix.rsplit("`", 1)[-1]
    segments = _tokenize_shell_segments([(1, prefix + " __REF__", False)])
    if not segments:
        return False
    last_seg = segments[-1]
    idx = _skip_shell_wrappers(last_seg)
    if idx is None or idx + 2 >= len(last_seg):
        return False
    t0, _l0, q0 = last_seg[idx]
    t1, _l1, q1 = last_seg[idx + 1]
    t2, _l2, q2 = last_seg[idx + 2]
    return (
        not q0
        and not q1
        and not q2
        and (t0 == "gh" or t0.endswith("/gh"))
        and t1 == "workflow"
        and t2 == "run"
    )


def _normalize_url_ref(ref: str) -> str:
    """Strip an archive extension and trailing sentence punctuation.

    `/archive/refs/tags/v0.7.13.tar.gz` names tag `v0.7.13`, and a URL ending a
    sentence picks up the full stop. Neither belongs in the tag compared against
    the release namespace.
    """
    cleaned = _REF_SUFFIX_RE.sub("", ref)
    return cleaned.rstrip(".")


def _evaluate_ref_pin(
    raw_ref: str, token: str, doc_path: str, idx: int, ctx: RepoContext
) -> List[Finding]:
    """Evaluate one ref-shaped pin against the release-tag namespace.

    Shared by all three ref grammars -- `@ref`, the URL forms, and the CLI-flag
    form -- so they stay ONE clock. A second copy of this logic would be a second
    notion of freshness, which is the thing the arm-2 docstring warns against.
    """

    findings: List[Finding] = []
    ref = _normalize_url_ref(raw_ref)
    if ref in REF_PLACEHOLDERS:
        return findings
    if _METAVAR_RE.search(ref):
        findings.append(
            Finding(
                file=doc_path,
                line=idx,
                arm="pins",
                code="invalid_placeholder",
                token=token,
                message=(
                    f"`{ref}` is not an accepted ref placeholder; a ref "
                    f"position accepts only {', '.join(REF_PLACEHOLDERS)}."
                ),
            )
        )
        return findings
    if not re.match(r"^v[0-9]", ref):
        # A branch or SHA selector is not a release pin.
        return findings
    latest = ctx.latest_release_tag
    if latest is None:
        # FAIL CLOSED. An empty release namespace is not "nothing to
        # compare against" -- the document makes a live claim about
        # this repository's latest release and the check could not
        # evaluate it. Staying silent here would make every stale git
        # pin invisible under a shallow clone, a fork PR, or anyone
        # relaxing the workflow's `fetch-depth: 0`, with a green check
        # implying coverage that does not exist.
        findings.append(
            Finding(
                file=doc_path,
                line=idx,
                arm="pins",
                code="release_namespace_unresolved",
                token=token,
                message=(
                    f"`@{ref}` pins this repository, but no tag matches the "
                    f"release namespace `{_RELEASE_TAG_GLOB}`, so its freshness "
                    f"could not be evaluated. Fetch tags (`fetch-depth: 0`) "
                    f"before running this check -- an unevaluated pin is not a "
                    f"fresh one."
                ),
            )
        )
        return findings
    if ref == latest:
        return findings
    findings.append(
        Finding(
            file=doc_path,
            line=idx,
            arm="pins",
            code="stale_pin",
            token=token,
            message=(
                f"`@{ref}` is stale: the latest tag in the release namespace "
                f"`{_RELEASE_TAG_GLOB}` is {latest}. (The pinned tag may well "
                f"exist -- freshness is the property being checked, not "
                f"existence.)"
            ),
        )
    )
    return findings


def check_pin_freshness(text: str, doc_path: str, ctx: RepoContext) -> List[Finding]:
    """Arm 2: a pin is a *claim about a current version*, checked for staleness.

    Scans **raw text including fenced blocks** -- install commands live in
    fences -- so it deliberately does not reuse arm 1's backtick pipeline.

    The two clocks stay separate: ``dist==V`` is compared against that
    distribution's own ``pyproject.toml`` version; ``@vX.Y.Z`` in a git-install
    URL is compared against the repository's release-tag namespace. Refs that
    are not tag-shaped (``@main``) are branch selectors, not pins.

    Fails **closed**: if a document pins this repository but the release-tag
    namespace does not resolve, that is reported rather than skipped. Silence
    there would mean a shallow clone or a fork PR hides every stale git pin
    behind a green check.
    """
    findings: List[Finding] = []

    for idx, line in enumerate(text.split("\n"), start=1):
        for match in _DIST_PIN_RE.finditer(line):
            dist = match.group("dist")
            version = match.group("version")
            package = ctx.package_for_distribution(dist)
            if package is None:
                # A third-party pin is on somebody else's clock. Nothing to
                # evaluate, and nothing claimed about this repository.
                continue
            if not package.version:
                # FAIL CLOSED. The distribution IS ours, so the document makes a
                # live claim about it -- the check simply could not resolve the
                # version to compare against (dynamic versioning, or a
                # pyproject this parser cannot read). Skipping made arm 2
                # silently inert for that distribution, which is fail-open on
                # the class this arm exists to catch.
                findings.append(
                    Finding(
                        file=doc_path,
                        line=idx,
                        arm="pins",
                        code="package_version_unresolved",
                        token=match.group(0),
                        message=(
                            f"`{dist}=={version}` pins a distribution defined in this "
                            f"repository, but no static version could be read from "
                            f"{package.directory or '.'}/pyproject.toml, so its freshness "
                            f"could not be evaluated. An unevaluated pin is not a fresh "
                            f"one."
                        ),
                    )
                )
                continue
            if version in VERSION_PLACEHOLDERS:
                continue
            if _METAVAR_RE.search(version):
                findings.append(
                    Finding(
                        file=doc_path,
                        line=idx,
                        arm="pins",
                        code="invalid_placeholder",
                        token=match.group(0),
                        message=(
                            f"`{version}` is not an accepted version placeholder; use "
                            f"one of {', '.join(VERSION_PLACEHOLDERS)}."
                        ),
                    )
                )
                continue
            if version != package.version:
                findings.append(
                    Finding(
                        file=doc_path,
                        line=idx,
                        arm="pins",
                        code="stale_pin",
                        token=match.group(0),
                        message=(
                            f"`{dist}=={version}` is stale: {package.directory or '.'}"
                            f"/pyproject.toml declares {package.name} "
                            f"{package.version}."
                        ),
                    )
                )

        # Both spellings of the same claim, evaluated by the same rule against
        # the same clock -- a release-URL pin rots identically to an `@ref` one.
        for match in itertools.chain(
            _GIT_REF_PIN_RE.finditer(line), _URL_TAG_PIN_RE.finditer(line)
        ):
            owner = match.group("owner").lower()
            name = match.group("repo").lower().removesuffix(".git")
            if (owner, name) not in ctx.repo_identities:
                # A pin at somebody else's repository is on somebody else's clock.
                continue
            findings.extend(
                _evaluate_ref_pin(
                    match.group("ref"), match.group(0), doc_path, idx, ctx
                )
            )
        for match in _FLAG_REF_PIN_RE.finditer(line):
            # No owner/repo to gate on -- see _FLAG_REF_PIN_RE. An unqualified ref
            # in this repository's own entry doc is a claim about this repository,
            # except GitHub CLI's `gh workflow run ... --ref <branch>`.
            if _is_workflow_dispatch_ref(line, match.start(), match.group(0)):
                continue
            findings.extend(
                _evaluate_ref_pin(
                    match.group("ref"), match.group(0), doc_path, idx, ctx
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Arm 3 -- published-README rendering


_INLINE_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*(?P<dest><[^>\n]*>|[^\s)]+)")
_REF_DEFINITION_RE = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*(?P<dest><[^>\n]*>|\S+)")
_AUTOLINK_RE = re.compile(r"<(?P<dest>[a-zA-Z][a-zA-Z0-9+.\-]*:[^>\s]*)>")
#: Inline HTML destinations. Markdown permits raw HTML, and a badge -- the most
#: common relative-destination in a real README -- is written as `<img src=...>`
#: rather than as a markdown image, so a grammar covering only markdown misses
#: the most likely instance of this arm's own defect class. Tag list is closed,
#: matching the rest of arm 3.
_HTML_DEST_RE = re.compile(
    r"<(?:img|a|source|video|audio|iframe|embed|link|object)\b[^>]*?"
    r"\b(?:src|href|data)\s*=\s*"
    r"(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<bare>[^\s>]+))",
    re.IGNORECASE,
)


def _is_absolute_destination(dest: str) -> bool:
    cleaned = dest.strip().strip("<>").strip()
    if not cleaned:
        return True
    if cleaned.startswith("#"):
        return True  # fragment-only: resolves inside the rendered document
    if cleaned.startswith("//"):
        return True
    return bool(_URL_SCHEME_RE.match(cleaned))


def check_published_rendering(text: str, doc_path: str, ctx: RepoContext) -> List[Finding]:
    """Arm 3: relative link destinations break once a README is published.

    GitHub rewrites relative destinations using repository context; PyPI, which
    renders the same bytes as a package long-description, does not. So for a
    README that a package declares as ``[project].readme``, a non-fragment
    relative destination is a defect -- deterministically, offline, without
    ever fetching a URL.

    Closed grammar: inline links, inline images, reference definitions, and
    autolinks. Destinations inside fenced blocks or inline code are code
    samples, not rendered links.
    """
    package = ctx.package_for_doc(doc_path)
    if package is None:
        return []

    findings: List[Finding] = []
    lines = text.split("\n")
    inside = _fence_mask(lines)
    for idx, line in enumerate(lines):
        if inside[idx]:
            continue
        scannable = _mask_inline_code(line)
        destinations: List[str] = [m.group("dest") for m in _INLINE_LINK_RE.finditer(scannable)]
        ref_def = _REF_DEFINITION_RE.match(scannable)
        if ref_def:
            destinations.append(ref_def.group("dest"))
        destinations.extend(m.group("dest") for m in _AUTOLINK_RE.finditer(scannable))
        for match in _HTML_DEST_RE.finditer(scannable):
            dest = match.group("dq") or match.group("sq") or match.group("bare")
            if dest is not None:
                destinations.append(dest)
        for dest in destinations:
            if _is_absolute_destination(dest):
                continue
            findings.append(
                Finding(
                    file=doc_path,
                    line=idx + 1,
                    arm="published_rendering",
                    code="relative_link_in_published_readme",
                    token=dest.strip().strip("<>"),
                    message=(
                        f"`{dest}` is a relative destination in a README published as "
                        f"the long-description of `{package.name}`. GitHub rewrites it "
                        f"with repository context; PyPI does not. Use an absolute URL."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Arm 4 -- CLI flags (agent-harness#1612)


_CLI_FENCE_RE = re.compile(r"^([ ]*)(`{3,}|~{3,})(.*)$")
_CLI_FLAG_RE = re.compile(r"^--[a-z][a-z0-9-]*$")
_CLI_SUBCOMMAND_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_CLI_BQ_STEP_RE = re.compile(r"^[ ]{0,3}>[ ]?")
_CLI_LIST_ITEM_RE = re.compile(r"^([ \t]*)(?:[-*+]|\d{1,9}[.)])(?:([ \t]+)|$)")
_CLI_THEMATIC_BREAK_RE = re.compile(r"^[ ]{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")


@dataclass(frozen=True)
class _CliCommandSpec:
    options: frozenset
    value_options: Dict[str, object]
    remainder_options: frozenset
    positional_remainder_index: Optional[int]


def _collect_parser_flags(
    parser: argparse.ArgumentParser, prefix: Tuple[str, ...] = ()
) -> Dict[Tuple[str, ...], _CliCommandSpec]:
    """Walk ``parser`` and its subparsers, returning documented ``--flag`` specs."""
    specs: Dict[Tuple[str, ...], _CliCommandSpec] = {}
    own_opts: Set[str] = set()
    own_value_opts: Dict[str, object] = {}
    own_remainder_opts: Set[str] = set()
    positional_count = 0
    positional_remainder_index: Optional[int] = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        if not action.option_strings:
            if action.nargs == argparse.REMAINDER and positional_remainder_index is None:
                positional_remainder_index = positional_count
            elif action.nargs != 0:
                positional_count += 1
            continue
        if action.help is argparse.SUPPRESS:
            continue
        for opt in action.option_strings:
            if opt.startswith("--"):
                own_opts.add(opt)
                if action.nargs == argparse.REMAINDER:
                    own_remainder_opts.add(opt)
                elif action.nargs != 0:
                    own_value_opts[opt] = action.nargs
    specs[prefix] = _CliCommandSpec(
        options=frozenset(own_opts),
        value_options=own_value_opts,
        remainder_options=frozenset(own_remainder_opts),
        positional_remainder_index=positional_remainder_index,
    )
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                specs.update(_collect_parser_flags(subparser, prefix + (name,)))
    return specs


@functools.lru_cache(maxsize=1)
def _load_cli_parser_flags() -> Dict[Tuple[str, ...], _CliCommandSpec]:
    """Lazily inspect ``phase_loop_runtime.cli.build_parser()`` for documented flags."""
    from . import cli as _cli

    return _collect_parser_flags(_cli.build_parser())


def _cli_indent_width(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _strip_blockquote_prefix(line: str) -> Tuple[int, str]:
    depth = 0
    rest = line
    while True:
        match = _CLI_BQ_STEP_RE.match(rest)
        if not match:
            break
        depth += 1
        rest = rest[match.end() :]
    return depth, rest


def _cli_list_item_content_indent(line: str) -> Optional[int]:
    if _CLI_THEMATIC_BREAK_RE.match(line):
        return None
    expanded = line.expandtabs(4)
    match = _CLI_LIST_ITEM_RE.match(expanded)
    if not match:
        return None
    return match.end()


def _iter_multiline_inline_code_spans(
    prose_lines: Sequence[Tuple[int, str]],
) -> List[List[Tuple[int, str, bool]]]:
    """Extract CommonMark single- or multi-line inline code spans with line numbers."""
    if not prose_lines:
        return []
    parts: List[str] = []
    char_lines: List[int] = []
    for idx, (lineno, text) in enumerate(prose_lines):
        if idx > 0:
            parts.append("\n")
            char_lines.append(lineno)
        parts.append(text)
        char_lines.extend([lineno] * len(text))
    para = "".join(parts)
    spans: List[List[Tuple[int, str, bool]]] = []
    pos = 0
    length = len(para)
    while pos < length:
        if para[pos] != "`":
            pos += 1
            continue
        run_end = pos
        while run_end < length and para[run_end] == "`":
            run_end += 1
        ticks = para[pos:run_end]
        close = para.find(ticks, run_end)
        while close != -1 and (
            (close > 0 and para[close - 1] == "`")
            or (close + len(ticks) < length and para[close + len(ticks)] == "`")
        ):
            close = para.find(ticks, close + 1)
        if close == -1:
            pos = run_end
            continue
        span_lines: List[Tuple[int, str, bool]] = []
        chunk_start = run_end
        while chunk_start < close:
            nl = para.find("\n", chunk_start, close)
            chunk_end = close if nl == -1 else nl
            chunk_text = para[chunk_start:chunk_end]
            chunk_lineno = char_lines[chunk_start] if chunk_start < len(char_lines) else prose_lines[-1][0]
            span_lines.append((chunk_lineno, chunk_text, False))
            if nl == -1:
                break
            chunk_start = nl + 1
        if span_lines:
            spans.append(span_lines)
        pos = close + len(ticks)
    return spans


def _scan_command_substitution(text: str, start: int) -> int:
    """Return index of matching ``)`` for ``$(`` whose body starts at ``start``, else ``-1``."""
    stack: List[str] = ["subst"]
    i = start
    n = len(text)
    while i < n and stack:
        ch = text[i]
        top = stack[-1]
        if top == "squote":
            if ch == "'":
                stack.pop()
            i += 1
            continue
        if top == "dquote":
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                stack.pop()
                i += 1
                continue
            if ch == "$" and i + 1 < n and text[i + 1] == "(":
                stack.append("subst")
                i += 2
                continue
            i += 1
            continue
        # Inside command substitution (`subst` or nested `paren`)
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "'":
            stack.append("squote")
            i += 1
            continue
        if ch == '"':
            stack.append("dquote")
            i += 1
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "(":
            stack.append("subst")
            i += 2
            continue
        if ch == "(":
            stack.append("paren")
            i += 1
            continue
        if ch == ")":
            stack.pop()
            if not stack:
                return i
            i += 1
            continue
        i += 1
    return -1


def _tokenize_shell_text(
    text: str, char_lines: Sequence[int]
) -> List[List[Tuple[str, int, bool]]]:
    """Tokenize flattened shell command text into operator-bounded segments."""
    segments: List[List[Tuple[str, int, bool]]] = []
    nested_segments: List[List[Tuple[str, int, bool]]] = []
    cur_seg: List[Tuple[str, int, bool]] = []
    buf: List[str] = []
    buf_line = 0
    buf_quoted = False
    in_quote: Optional[str] = None

    def flush_tok() -> None:
        nonlocal buf_quoted
        if buf:
            cur_seg.append(("".join(buf), buf_line, buf_quoted))
            buf.clear()
            buf_quoted = False

    def flush_seg() -> None:
        flush_tok()
        if cur_seg:
            segments.append(list(cur_seg))
            cur_seg.clear()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        lineno = char_lines[i]
        if in_quote is not None:
            if ch == "\\" and in_quote == '"' and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
                i += 1
                continue
            if in_quote == '"' and ch == "$" and i + 1 < n and text[i + 1] == "(":
                close_idx = _scan_command_substitution(text, i + 2)
                if close_idx != -1:
                    buf.append(text[i : close_idx + 1])
                    nested_segments.extend(
                        _tokenize_shell_text(
                            text[i + 2 : close_idx], char_lines[i + 2 : close_idx]
                        )
                    )
                    i = close_idx + 1
                    continue
            buf.append(ch)
            i += 1
            continue
        if ch == "#" and not buf:
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl + 1
            continue
        if ch in ("'", '"'):
            if not buf:
                buf_line = lineno
                buf_quoted = True
            in_quote = ch
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if not buf:
                buf_line = lineno
            buf.append(text[i + 1])
            i += 2
            continue
        if ch in " \t\r\n":
            flush_tok()
            i += 1
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "(":
            close_idx = _scan_command_substitution(text, i + 2)
            if close_idx != -1:
                if not buf:
                    buf_line = lineno
                buf.append(text[i : close_idx + 1])
                nested_segments.extend(
                    _tokenize_shell_text(
                        text[i + 2 : close_idx], char_lines[i + 2 : close_idx]
                    )
                )
                i = close_idx + 1
                continue
            flush_seg()
            i += 2
            continue
        if ch in ";|&()":
            flush_seg()
            if i + 1 < n and text[i + 1] == ch and ch in "|&":
                i += 2
            else:
                i += 1
            continue
        if not buf:
            buf_line = lineno
        buf.append(ch)
        i += 1
    flush_seg()
    return segments + nested_segments


def _tokenize_shell_segments(
    lines_with_nos: Sequence[Tuple[int, str, bool]],
) -> List[List[Tuple[str, int, bool]]]:
    """Split shell command lines into operator-bounded segments of ``(tok, line, quoted)``."""
    parts: List[str] = []
    char_lines: List[int] = []
    prev_continued = False
    for idx, (lineno, raw, continued) in enumerate(lines_with_nos):
        if idx > 0 and not prev_continued:
            parts.append("\n")
            char_lines.append(lineno)
        parts.append(raw)
        char_lines.extend([lineno] * len(raw))
        prev_continued = continued
    if not parts:
        return []
    return _tokenize_shell_text("".join(parts), char_lines)


def _ends_with_line_continuation(line: str) -> bool:
    stripped = line.rstrip("\r")
    trailing_backslashes = len(stripped) - len(stripped.rstrip("\\"))
    return trailing_backslashes % 2 == 1


def _iter_cli_code_segments(text: str) -> List[List[Tuple[str, int, bool]]]:
    """Yield shell command segments from fenced code blocks and inline code spans.

    Handles blockquote-nested fences (``> ```sh``), list-indented fences within
    CommonMark container bounds (preventing 4-space top-level indented code
    lines containing literal backticks from opening phantom fences), multiline
    inline code spans, and POSIX ``\\`` line continuations without inserting
    spurious whitespace.
    """
    lines = text.split("\n")
    out: List[List[Tuple[str, int, bool]]] = []
    opener_char: Optional[str] = None
    opener_len = 0
    fence_bq = 0
    fence_min = 0
    fence_bound: Optional[int] = None
    fence_group: List[Tuple[int, str, bool]] = []
    prose_lines: List[Tuple[int, str]] = []
    prose_bq = 0
    list_indents: List[int] = []
    last_bq = 0
    saw_blank = False

    def flush_fence_group() -> None:
        if fence_group:
            out.extend(_tokenize_shell_segments(fence_group))
            fence_group.clear()

    def flush_prose() -> None:
        if prose_lines:
            for span_lines in _iter_multiline_inline_code_spans(prose_lines):
                out.extend(_tokenize_shell_segments(span_lines))
            prose_lines.clear()

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        lineno = idx + 1
        bq_depth, body = _strip_blockquote_prefix(line)

        if opener_char is not None:
            left_blockquote = bq_depth < fence_bq
            dedented_list = (
                not left_blockquote
                and fence_bound is not None
                and bool(body.strip())
                and _cli_indent_width(body) < fence_bound
            )
            if left_blockquote or dedented_list:
                flush_fence_group()
                opener_char = None
                opener_len = 0
                fence_bq = 0
                fence_min = 0
                fence_bound = None
                continue  # re-process current line outside the closed fence

            # Strip only the fence's own blockquote depth for fence content/closer.
            content = line
            for _ in range(fence_bq):
                m_bq = _CLI_BQ_STEP_RE.match(content)
                if m_bq:
                    content = content[m_bq.end() :]
            match = _CLI_FENCE_RE.match(content)
            cur_indent = _cli_indent_width(content)
            if (
                match
                and match.group(2)[0] == opener_char
                and len(match.group(2)) >= opener_len
                and not match.group(3).strip()
                and fence_min <= cur_indent <= fence_min + 3
            ):
                flush_fence_group()
                opener_char = None
                opener_len = 0
                fence_bq = 0
                fence_min = 0
                fence_bound = None
                idx += 1
                continue
            if _ends_with_line_continuation(content):
                fence_group.append((lineno, content.rstrip("\r")[:-1], True))
            else:
                fence_group.append((lineno, content, False))
                flush_fence_group()
            idx += 1
            continue

        if not body.strip():
            flush_prose()
            saw_blank = True
            idx += 1
            continue

        if bq_depth != last_bq:
            flush_prose()
            list_indents.clear()
            last_bq = bq_depth
            saw_blank = False

        cur_indent = _cli_indent_width(body)
        if saw_blank:
            while list_indents and cur_indent < list_indents[-1]:
                list_indents.pop()
        saw_blank = False

        item_indent = _cli_list_item_content_indent(body)
        if item_indent is not None:
            while list_indents and cur_indent < list_indents[-1]:
                list_indents.pop()
            list_indents.append(item_indent)
            after_marker = body.expandtabs(4)[item_indent:]
            inline_match = _CLI_FENCE_RE.match(after_marker)
            if inline_match and _cli_indent_width(after_marker) <= 3:
                char = inline_match.group(2)[0]
                info = inline_match.group(3)
                if not (char == "`" and "`" in info):
                    flush_prose()
                    opener_char = char
                    opener_len = len(inline_match.group(2))
                    fence_bq = bq_depth
                    fence_min = item_indent
                    fence_bound = item_indent
                    idx += 1
                    continue
        else:
            active_indent = list_indents[-1] if list_indents else None
            if active_indent is not None and cur_indent >= active_indent:
                cand_min = active_indent
                cand_bound: Optional[int] = active_indent
            else:
                cand_min = 0
                cand_bound = None
            match = _CLI_FENCE_RE.match(body)
            if match and cand_min <= cur_indent <= cand_min + 3:
                char = match.group(2)[0]
                info = match.group(3)
                if not (char == "`" and "`" in info):
                    flush_prose()
                    opener_char = char
                    opener_len = len(match.group(2))
                    fence_bq = bq_depth
                    fence_min = cand_min
                    fence_bound = cand_bound
                    idx += 1
                    continue

        if prose_lines and bq_depth != prose_bq:
            flush_prose()
        prose_bq = bq_depth
        prose_lines.append((lineno, body))
        idx += 1

    flush_fence_group()
    flush_prose()
    return out


def _extract_cli_flag(token: str, *, quoted: bool = False) -> Optional[str]:
    """Return canonical ``--flag`` from ``token`` (handling ``[--flag]`` and ``--flag=val``)."""
    candidate = token if quoted else token.lstrip("[")
    if candidate == "--" or not candidate.startswith("--"):
        return None
    flag = candidate.split("=", 1)[0]
    if not quoted:
        flag = flag.rstrip(".,;:)]}>")
    return flag if _CLI_FLAG_RE.fullmatch(flag) else None


_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_PYTHON_BIN_RE = re.compile(r"^(?:.*/)?python(?:\d+(?:\.\d+)*)?$")
_CLI_WRAPPER_BINS: frozenset = frozenset({"nohup", "time", "exec", "sudo"})


def _skip_shell_wrappers(seg: Sequence[Tuple[str, int, bool]]) -> Optional[int]:
    """Advance past prompts, env assignments, and common command wrappers."""
    idx = 0
    n = len(seg)
    while idx < n:
        tok, _ln, quoted = seg[idx]
        if quoted:
            return None
        if tok in ("$", "%"):
            idx += 1
            continue
        if _ENV_ASSIGN_RE.match(tok):
            idx += 1
            continue
        if tok == "env":
            idx += 1
            while idx < n and not seg[idx][2] and (
                seg[idx][0].startswith("-") or _ENV_ASSIGN_RE.match(seg[idx][0])
            ):
                idx += 1
            continue
        if tok == "timeout":
            idx += 1
            while idx < n and not seg[idx][2] and seg[idx][0].startswith("-"):
                opt = seg[idx][0]
                idx += 1
                if opt in ("-k", "-s", "--kill-after", "--signal") and idx < n:
                    idx += 1
            if idx < n and not seg[idx][2]:
                idx += 1  # duration argument
            continue
        if tok == "uv" and idx + 1 < n and not seg[idx + 1][2] and seg[idx + 1][0] == "run":
            idx += 2
            while idx < n and not seg[idx][2] and seg[idx][0].startswith("-"):
                opt = seg[idx][0]
                idx += 1
                if opt in ("--project", "--python", "--with", "--directory") and idx < n:
                    idx += 1
            continue
        if tok == "command":
            idx += 1
            while idx < n and not seg[idx][2] and seg[idx][0].startswith("-"):
                if seg[idx][0] in ("-v", "-V"):
                    return None
                idx += 1
            continue
        if tok in _CLI_WRAPPER_BINS:
            idx += 1
            continue
        return idx
    return None


def _find_cli_invocation(seg: Sequence[Tuple[str, int, bool]]) -> Optional[int]:
    """Return index of first arg after ``phase-loop`` in command position, else ``None``.

    Skips shell prompts (``$``, ``%``), leading ``KEY=VAL`` assignments, and
    common command wrappers (``env``, ``timeout``, ``uv run``, ``command`` without
    ``-v``/``-V``), and recognizes ``python -m phase_loop_runtime.cli``. Leaves
    non-invocation mentions such as ``git grep phase-loop --include ...`` or
    ``command -v phase-loop`` untouched.
    """
    idx = _skip_shell_wrappers(seg)
    if idx is None or idx >= len(seg):
        return None
    n = len(seg)
    tok, _ln, quoted = seg[idx]
    if quoted:
        return None
    if tok == "phase-loop" or tok.endswith("/phase-loop"):
        return idx + 1
    if _PYTHON_BIN_RE.match(tok):
        p = idx + 1
        while p < n and not seg[p][2] and seg[p][0].startswith("-") and seg[p][0] != "-m":
            p += 1
        if (
            p + 1 < n
            and not seg[p][2]
            and seg[p][0] == "-m"
            and not seg[p + 1][2]
            and seg[p + 1][0] == "phase_loop_runtime.cli"
        ):
            return p + 2
        return None
    return None


def _consume_option_values(
    seg: Sequence[Tuple[str, int, bool]], pos: int, nargs: object
) -> int:
    """Return updated index after consuming argument token(s) for option at ``pos``."""
    n = len(seg)
    if nargs is None or nargs == 1:
        return pos + 1 if pos + 1 < n else pos
    if isinstance(nargs, int) and nargs > 1:
        return min(n - 1, pos + nargs)
    if nargs == "?":
        if pos + 1 < n and _extract_cli_flag(seg[pos + 1][0], quoted=seg[pos + 1][2]) is None:
            return pos + 1
        return pos
    if nargs in ("*", "+"):
        while (
            pos + 1 < n
            and seg[pos + 1][0] != "--"
            and _extract_cli_flag(seg[pos + 1][0], quoted=seg[pos + 1][2]) is None
        ):
            pos += 1
        return pos
    return pos


def check_cli_flags(
    text: str,
    doc_path: str,
    *,
    command_specs: Optional[Dict[Tuple[str, ...], _CliCommandSpec]] = None,
) -> List[Finding]:
    """Arm 4: every ``phase-loop <subcommand> --flag`` span must exist in ``--help``."""
    if command_specs is None:
        command_specs = _load_cli_parser_flags()

    top_spec = command_specs.get(
        (),
        _CliCommandSpec(
            options=frozenset(),
            value_options={},
            remainder_options=frozenset(),
            positional_remainder_index=None,
        ),
    )
    findings: List[Finding] = []

    for seg in _iter_cli_code_segments(text):
        pos = _find_cli_invocation(seg)
        if pos is None:
            continue
        # Validate optional top-level flags preceding the subcommand.
        stop_segment = False
        while pos < len(seg):
            t, ln, q = seg[pos]
            if t == "--":
                stop_segment = True
                break
            flag = _extract_cli_flag(t, quoted=q)
            if flag is None:
                break
            if flag in top_spec.remainder_options:
                stop_segment = True
                break
            if flag not in top_spec.options:
                findings.append(
                    Finding(
                        file=doc_path,
                        line=ln,
                        arm="cli_flags",
                        code="unknown_cli_flag",
                        token=f"phase-loop {flag}",
                        message=(
                            f"`phase-loop {flag}` is not a documented top-level "
                            f"option in `phase-loop --help`."
                        ),
                    )
                )
            elif flag in top_spec.value_options and "=" not in t:
                pos = _consume_option_values(seg, pos, top_spec.value_options[flag])
            pos += 1
        if stop_segment or pos >= len(seg):
            continue
        sub_tok, sub_ln, sub_q = seg[pos]
        if sub_q or not _CLI_SUBCOMMAND_RE.fullmatch(sub_tok):
            continue
        if (sub_tok,) not in command_specs:
            has_concrete_flag = False
            for t, _ln, q in seg[pos + 1 :]:
                if t == "--":
                    break
                if _extract_cli_flag(t, quoted=q) is not None:
                    has_concrete_flag = True
                    break
            if has_concrete_flag:
                findings.append(
                    Finding(
                        file=doc_path,
                        line=sub_ln,
                        arm="cli_flags",
                        code="unknown_cli_subcommand",
                        token=f"phase-loop {sub_tok}",
                        message=(
                            f"`phase-loop {sub_tok}` is not a documented subcommand "
                            f"in `phase-loop --help`."
                        ),
                    )
                )
            continue
        path_key: Tuple[str, ...] = (sub_tok,)
        pos += 1
        while (
            pos < len(seg)
            and not seg[pos][2]
            and (*path_key, seg[pos][0]) in command_specs
        ):
            path_key = (*path_key, seg[pos][0])
            pos += 1
        cmd_spec = command_specs[path_key]
        cmd_label = " ".join(path_key)
        positionals_seen = 0
        while pos < len(seg):
            t, ln, q = seg[pos]
            if t == "--":
                break
            flag = _extract_cli_flag(t, quoted=q)
            if flag is not None:
                if flag in cmd_spec.remainder_options:
                    break
                if flag not in cmd_spec.options:
                    findings.append(
                        Finding(
                            file=doc_path,
                            line=ln,
                            arm="cli_flags",
                            code="unknown_cli_flag",
                            token=f"{cmd_label} {flag}",
                            message=(
                                f"`phase-loop {cmd_label} {flag}` is not a "
                                f"documented option in `phase-loop {cmd_label} --help`."
                            ),
                        )
                    )
                elif flag in cmd_spec.value_options and "=" not in t:
                    pos = _consume_option_values(seg, pos, cmd_spec.value_options[flag])
            elif not t.startswith("-"):
                if (
                    cmd_spec.positional_remainder_index is not None
                    and positionals_seen >= cmd_spec.positional_remainder_index
                ):
                    break
                positionals_seen += 1
            pos += 1
    return findings


def check_cli_flags_in_repo(
    ctx: RepoContext,
    *,
    roots: Sequence[str] = CLI_FLAG_DOC_ROOTS,
    exclude: Set[str] = frozenset(),
    command_specs: Optional[Dict[Tuple[str, ...], _CliCommandSpec]] = None,
) -> List[Finding]:
    """Scan markdown files under ``roots`` for ``phase-loop <sub> --flag`` drift."""
    findings: List[Finding] = []
    seen: Set[str] = set(exclude)
    for root_rel in roots:
        root_dir = ctx.repo / root_rel
        if not root_dir.is_dir():
            continue
        for path in sorted(root_dir.rglob("*.md")):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(ctx.repo)
            except (OSError, ValueError):
                continue
            logical = path.relative_to(ctx.repo).as_posix()
            if logical in seen:
                continue
            seen.add(logical)
            findings.extend(
                check_cli_flags(
                    path.read_text(encoding="utf-8"),
                    logical,
                    command_specs=command_specs,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Coverage reconciliation


def check_entry_doc_coverage(ctx: RepoContext, entry_docs: Sequence[str]) -> List[Finding]:
    """Every package long-description must be among the CHECKED docs.

    Otherwise a newly added package README is silently uncovered -- the same
    drift class this check exists to catch, one level up.

    ``entry_docs`` is the full checked set, deliberately: the property is "no
    package long-description goes unchecked", so a README listed under any role
    satisfies it. Reconciling against only ``PACKAGE_LONG_DESCRIPTION_DOCS``
    would report a README that is demonstrably being read.
    """
    findings: List[Finding] = []
    covered = set(entry_docs)
    for package in sorted(ctx.packages.values(), key=lambda p: p.name):
        logical = package.readme_logical_path
        if not logical or logical in covered:
            continue
        findings.append(
            Finding(
                file=logical,
                line=0,
                arm="coverage",
                code="uncovered_package_readme",
                token=logical,
                message=(
                    f"`{package.name}` declares `{logical}` as its long-description, "
                    f"but it is not in ENTRY_DOCS, so no arm verifies it."
                ),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Suppressions


@dataclass(frozen=True)
class Suppression:
    file: str
    code: str
    token: str
    reason: str

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.file, self.code, self.token)


def load_suppressions(repo: Path) -> List[Suppression]:
    """Read the checked-in suppression file (absent file == no suppressions)."""
    path = Path(repo) / SUPPRESSIONS
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{SUPPRESSIONS}: unreadable ({exc})") from exc
    entries = data.get("suppressions", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError(f"{SUPPRESSIONS}: expected a list under 'suppressions'")
    out: List[Suppression] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{SUPPRESSIONS}: each suppression must be an object")
        out.append(
            Suppression(
                file=str(entry.get("file", "")),
                code=str(entry.get("code", "")),
                token=str(entry.get("token", "")),
                reason=str(entry.get("reason", "") or "").strip(),
            )
        )
    return out


def apply_suppressions(
    findings: Sequence[Finding], suppressions: Sequence[Suppression]
) -> List[Finding]:
    """Drop suppressed findings; report unusable and unused suppressions.

    A suppression that matches nothing is itself a finding, so stale entries
    cannot accumulate silently behind a green check.
    """
    matched: Set[str] = set()
    by_fingerprint: Dict[str, Suppression] = {}
    extra: List[Finding] = []
    for suppression in suppressions:
        if not suppression.reason:
            extra.append(
                Finding(
                    file=SUPPRESSIONS,
                    line=0,
                    arm="suppressions",
                    code="suppression_missing_reason",
                    token=suppression.fingerprint,
                    message=(
                        f"suppression for {suppression.file} [{suppression.code}] has no "
                        f"reason; a suppression without a stated reason is undocumented "
                        f"drift."
                    ),
                )
            )
            continue
        by_fingerprint[suppression.fingerprint] = suppression

    kept: List[Finding] = []
    for finding in findings:
        if finding.fingerprint in by_fingerprint:
            matched.add(finding.fingerprint)
            continue
        kept.append(finding)

    for key, suppression in by_fingerprint.items():
        if key in matched:
            continue
        extra.append(
            Finding(
                file=SUPPRESSIONS,
                line=0,
                arm="suppressions",
                code="unused_suppression",
                token=key,
                message=(
                    f"suppression for {suppression.file} [{suppression.code}] matches no "
                    f"finding; the defect is fixed or the entry is wrong -- remove it."
                ),
            )
        )
    return kept + extra


# ---------------------------------------------------------------------------
# Driver


def check_document(text: str, doc_path: str, ctx: RepoContext) -> List[Finding]:
    findings = list(check_paths(text, doc_path, ctx))
    findings.extend(check_pin_freshness(text, doc_path, ctx))
    findings.extend(check_published_rendering(text, doc_path, ctx))
    findings.extend(check_cli_flags(text, doc_path))
    return findings


def check_repo(
    repo: Path,
    entry_docs: Sequence[str] = ENTRY_DOCS,
    only: Optional[str] = None,
) -> List[Finding]:
    """Raw findings for ``repo`` -- **before** suppression.

    ``only`` narrows to one entry doc, interpreted as a logical path inside
    ``repo`` so package ownership and suppression identity stay well defined.

    A declared entry doc that does not exist is **reported**, not skipped.
    Skipping it meant deleting an entry doc turned the check green -- a check
    whose green survives the deletion of the thing it checks. This is safe to
    require because the inventory arrives as the ``entry_docs`` **parameter**:
    the CLI passes this repository's ``ENTRY_DOCS``, while a consumer or a test
    fixture passes its own list and is never held to docs it does not own. So
    the requirement binds this repository without constraining anyone else, and
    making it green after a real deletion means editing ``ENTRY_DOCS`` -- an
    explicit, reviewable act rather than silence.

    (A git-based "absent from disk but present in HEAD" discriminator was
    tried and rejected: once the deletion is committed -- which is what CI and
    a merge commit see -- the file is absent from both, so it only ever caught
    a dirty working tree.)
    """
    ctx = RepoContext(Path(repo))
    targets = list(entry_docs)
    if only is not None:
        normalised = only.replace("\\", "/").lstrip("./")
        if normalised not in targets:
            raise ValueError(
                f"--file {only!r} is not an entry doc; expected one of: "
                + ", ".join(targets)
            )
        targets = [normalised]

    findings: List[Finding] = []
    for doc in targets:
        path = ctx.repo / doc
        if not path.is_file():
            findings.append(
                Finding(
                    file=doc,
                    line=0,
                    arm="coverage",
                    code="missing_entry_doc",
                    token=doc,
                    message=(
                        f"`{doc}` is declared an entry doc but does not exist. If it was "
                        f"removed on purpose, drop it from ENTRY_DOCS in the same change."
                    ),
                )
            )
            continue
        findings.extend(check_document(path.read_text(encoding="utf-8"), doc, ctx))
    if only is None:
        findings.extend(check_entry_doc_coverage(ctx, entry_docs))
        findings.extend(
            check_cli_flags_in_repo(ctx, roots=CLI_FLAG_DOC_ROOTS, exclude=set(targets))
        )
    return findings


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="entry_doc_check",
        description="Verify entry-point documentation against diff-independent properties.",
    )
    parser.add_argument("--repo", required=True, help="repository root to check")
    parser.add_argument(
        "--file",
        default=None,
        help="narrow to one entry doc, as a logical path inside --repo",
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit as exc:  # argparse already printed usage
        return 2 if exc.code else 0

    repo = Path(args.repo)
    if not (repo / ".git").exists() and not repo.is_dir():
        print(f"entry_doc_check: {args.repo}: not a directory", file=sys.stderr)
        return 2

    try:
        raw = check_repo(repo, only=args.file)
        findings = apply_suppressions(raw, load_suppressions(repo))
    except (ValueError, OSError) as exc:
        print(f"entry_doc_check: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "repo": str(repo),
                    "raw_finding_count": len(raw),
                    "findings": [f.to_dict() for f in findings],
                },
                indent=2,
            )
        )
    else:
        for finding in findings:
            print(f"  • {finding.render()}", file=sys.stderr)

    if findings:
        if not args.json:
            print(
                f"entry_doc_check: {len(findings)} finding(s) across "
                f"{len({f.file for f in findings})} file(s)",
                file=sys.stderr,
            )
        return 1
    if not args.json:
        print(f"entry_doc_check: OK — {len(_docs_checked(repo, args.file))} entry doc(s) clean")
    return 0


def _docs_checked(repo: Path, only: Optional[str]) -> List[str]:
    # No existence filter: a declared doc that is missing is now a finding, so
    # a clean run means every one of these was actually read. Filtering here
    # would let the OK line under-report the inventory it just verified.
    return [only] if only else list(ENTRY_DOCS)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
