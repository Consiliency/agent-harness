"""Diff-independent verification of entry-point documentation (agent-harness#568).

``docs_audit`` is change-coupled by contract: it classifies *changed paths* and
enforces that a changed public surface carries a doc decision. It answers "did
the docs change when the code changed?" and structurally cannot answer "are the
docs still true?". Every defect this module targets arose with **no diff
touching the doc** -- a ``v0.1.5`` install pin that rotted through six releases
untouched, a relative link that renders on GitHub but breaks on PyPI.

Three arms, each fully decidable offline:

  (1) ``paths``              -- backtick tokens that look like repo paths resolve.
  (2) ``pins``               -- version pins are *fresh*, not merely resolvable.
  (3) ``published_rendering`` -- a README shipped as a package long-description
                                carries no relative link destinations.

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
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Surfaces

#: Explicit allowlist. Globs cannot express "package roots only", and the tree
#: carries dozens of generated override READMEs under ``phase-loop-skills/**``
#: that are not entry points. Reconciled against every package's
#: ``[project].readme`` by :func:`check_entry_doc_coverage` -- a long-description
#: path missing from this tuple is itself a finding, otherwise a new package
#: README is silently uncovered by the very check meant to cover it.
ENTRY_DOCS: Tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "phase-loop-runtime/README.md",
    "phase-loop-skills/README.md",
    "consiliency-harness/README.md",
)

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
    """
    inside = [False] * len(lines)
    opener: Optional[str] = None
    for idx, line in enumerate(lines):
        match = _FENCE_RE.match(line)
        if opener is None:
            if match:
                opener = match.group(2)[0] * 3
                inside[idx] = True
            continue
        inside[idx] = True
        if match and match.group(2).startswith(opener) and not match.group(3).strip():
            opener = None
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


def _parse_pyproject(text: str) -> Dict[str, str]:
    """Extract the ``[project]`` scalars this check needs.

    ``tomllib`` is 3.11+ and ``requires-python`` is 3.10, so fall back to a
    narrow scan of the ``[project]`` table. Only ``name``/``version``/``readme``
    are read, all of which are plain quoted strings in every pyproject here.
    """
    try:
        import tomllib  # Python 3.11+

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
    except ModuleNotFoundError:
        pass
    except Exception:
        return {}

    out: Dict[str, str] = {"name": "", "version": "", "readme": ""}
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped.split("#", 1)[0].strip() == "[project]"
            continue
        if not in_project:
            continue
        match = re.match(r"(name|version|readme)\s*=\s*[\"']([^\"']*)[\"']", stripped)
        if match:
            out[match.group(1)] = match.group(2)
    return out


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
_ISSUE_CITATION_RE = re.compile(r"^[\w.-]+/[\w.-]+#\d+$")
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_METAVAR_RE = re.compile(r"<[^<>]*>")


def _concrete_prefix(token: str) -> str:
    """The leading segments of ``token`` that contain no metavariable."""
    segments = token.strip("/").split("/")
    concrete: List[str] = []
    for segment in segments:
        if _METAVAR_RE.search(segment):
            break
        concrete.append(segment)
    return "/".join(concrete)


def _resolves(ctx: RepoContext, doc_dir: str, rel: str) -> bool:
    """Repo-root first, then the document's own directory.

    A trailing extension-less basename also resolves against a same-stem
    sibling: the live docs write ``.consiliency/manifest`` for the artifact the
    runtime creates as ``.consiliency/manifest.json``.
    """
    cleaned = rel.strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.rstrip("/")
    if not cleaned:
        return False
    bases = [""] if not doc_dir else ["", doc_dir]
    for base in bases:
        candidate = f"{base}/{cleaned}" if base else cleaned
        if ctx.exists(candidate):
            return True
        if "." not in Path(cleaned).name:
            parent = (ctx.repo / candidate).parent
            stem = Path(candidate).name
            try:
                if parent.is_dir() and any(parent.glob(stem + ".*")):
                    return True
            except OSError:
                pass
    return False


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
            if root in INSTALL_LAYOUT_ROOTS and not ctx.exists(root):
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
            if _resolves(ctx, doc_dir, token):
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


_DIST_PIN_RE = re.compile(
    r"(?<![\w.-])(?P<dist>[A-Za-z][A-Za-z0-9._-]*[A-Za-z0-9])==(?P<version>[^\s\"'`,;)\]]+)"
)
_GIT_REF_PIN_RE = re.compile(
    r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?@(?P<ref>[^\s\"'`#)\]]+)"
)


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
            package = ctx.packages.get(dist)
            if package is None or not package.version:
                # A third-party pin has no clock in this repo to check against.
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

        for match in _GIT_REF_PIN_RE.finditer(line):
            owner = match.group("owner").lower()
            name = match.group("repo").lower().removesuffix(".git")
            if (owner, name) not in ctx.repo_identities:
                # A pin at somebody else's repository is on somebody else's clock.
                continue
            ref = match.group("ref")
            if ref in REF_PLACEHOLDERS:
                continue
            if _METAVAR_RE.search(ref):
                findings.append(
                    Finding(
                        file=doc_path,
                        line=idx,
                        arm="pins",
                        code="invalid_placeholder",
                        token=match.group(0),
                        message=(
                            f"`{ref}` is not an accepted ref placeholder; a ref "
                            f"position accepts only {', '.join(REF_PLACEHOLDERS)}."
                        ),
                    )
                )
                continue
            if not re.match(r"^v[0-9]", ref):
                # A branch or SHA selector is not a release pin.
                continue
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
                        token=match.group(0),
                        message=(
                            f"`@{ref}` pins this repository, but no tag matches the "
                            f"release namespace `{_RELEASE_TAG_GLOB}`, so its freshness "
                            f"could not be evaluated. Fetch tags (`fetch-depth: 0`) "
                            f"before running this check -- an unevaluated pin is not a "
                            f"fresh one."
                        ),
                    )
                )
                continue
            if ref == latest:
                continue
            findings.append(
                Finding(
                    file=doc_path,
                    line=idx,
                    arm="pins",
                    code="stale_pin",
                    token=match.group(0),
                    message=(
                        f"`@{ref}` is stale: the latest tag in the release namespace "
                        f"`{_RELEASE_TAG_GLOB}` is {latest}. (The pinned tag may well "
                        f"exist -- freshness is the property being checked, not "
                        f"existence.)"
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Arm 3 -- published-README rendering


_INLINE_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*(?P<dest><[^>\n]*>|[^\s)]+)")
_REF_DEFINITION_RE = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*(?P<dest><[^>\n]*>|\S+)")
_AUTOLINK_RE = re.compile(r"<(?P<dest>[a-zA-Z][a-zA-Z0-9+.\-]*:[^>\s]*)>")


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
# Coverage reconciliation


def check_entry_doc_coverage(ctx: RepoContext, entry_docs: Sequence[str]) -> List[Finding]:
    """Every package long-description must be an entry doc.

    Otherwise a newly added package README is silently uncovered -- the same
    drift class this check exists to catch, one level up.
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
    return findings


def check_repo(
    repo: Path,
    entry_docs: Sequence[str] = ENTRY_DOCS,
    only: Optional[str] = None,
) -> List[Finding]:
    """Raw findings for ``repo`` -- **before** suppression.

    ``only`` narrows to one entry doc, interpreted as a logical path inside
    ``repo`` so package ownership and suppression identity stay well defined.
    An entry doc that does not exist is skipped: ``ENTRY_DOCS`` is this
    repository's inventory, and package coverage is reconciled separately.
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
            continue
        findings.extend(check_document(path.read_text(encoding="utf-8"), doc, ctx))
    if only is None:
        findings.extend(check_entry_doc_coverage(ctx, entry_docs))
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
    if only:
        return [only]
    return [doc for doc in ENTRY_DOCS if (Path(repo) / doc).is_file()]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
