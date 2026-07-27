"""Mechanically verify source citations in prose documents.

WHY THIS EXISTS
---------------
Plans, designs, ADRs and review notes cite source locations — ``foo.py:412``,
``src/db.rs::commit`` — and those citations rot silently.  A rebase, an import removal, a
formatter run: the prose still reads fine and the number now points at an unrelated line.

WHAT THIS DETECTS, AND WHAT IT CANNOT
-------------------------------------
Detects:
  * a cited path that does not resolve, or resolves ambiguously;
  * a cited line PAST end-of-file;
  * a cited SYMBOL that is not defined in the target — i.e. FABRICATED or renamed.
    Comments and string literals are stripped first, so a name merely *mentioned*
    in prose-within-code does not satisfy the search.

Cannot detect, and does not claim to:
  * IN-RANGE line drift.  A bare ``path:412`` carries no expectation of what line 412
    should contain, so after a drift the line still exists and there is nothing to compare
    against.  Detecting that would require the citation to carry an expectation, or an
    external baseline of content digests.  It is NOT implemented, and an earlier version
    of this module wrongly implied otherwise.

That gap is the whole argument for ``path::symbol``: a symbol anchor is self-describing
and drift-proof by construction, because the name is the expectation.  Line anchors are
therefore reported as a distinct advisory category, and ``--require-symbols`` promotes
that to an error once a repo has migrated.

DESIGN CONSTRAINTS (deliberately portable)
------------------------------------------
No assumption about language, project layout, or where documents live:

* **Language-agnostic.** Symbol resolution is a textual definition-ish search, not an AST
  parse, so it works for Python, TypeScript, Go, Rust, Ruby, shell — anything where a
  definition mentions its own name.  There is no import of any language tooling.
* **Layout-agnostic.** Paths resolve relative to the repo root first, then against
  caller-supplied search roots.  Nothing is hardcoded.
* **Location-agnostic.** Documents are selected by glob; the default is every tracked
  markdown file.
* **Vendorable.** Pure stdlib. No config file is required for the common case.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

#: `path:LINE`, `path:LINE-LINE`, or `path::symbol`, inside backticks or bare.
#: The path must contain a dot or a slash so prose like "step 3:4" is not a citation.
_CITATION = re.compile(
    r"`?(?P<path>[A-Za-z0-9_./\-]+[./][A-Za-z0-9_./\-]*)"
    r"(?::(?P<line>\d+)(?:-(?P<end>\d+))?|::(?P<symbol>[A-Za-z_][A-Za-z0-9_]*))`?"
)

#: Extensions treated as prose rather than source, so a doc citing another doc is skipped.
_PROSE_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt"})

#: Directory names that hold GENERATED or VENDORED copies of source. A citation means the
#: real file, not a build artefact, so these are excluded before disambiguating. These are
#: cross-ecosystem conventions (Python, JS, Rust, Go, Java) rather than repo-specific.
_DERIVED_DIRS = frozenset({
    "build", "dist", "target", "out", "bin", "obj",
    "node_modules", "vendor", "third_party", "site-packages",
    ".venv", "venv", ".tox", "__pycache__", ".mypy_cache", ".git",
})


class _Ambiguous(Exception):
    """A basename resolved to several real files. Reported as its own finding kind — NEVER
    as "no file matches", which would be a false diagnostic about the repo's contents."""

    def __init__(self, candidates: list[str]) -> None:
        super().__init__(", ".join(candidates))
        self.candidates = candidates


@dataclass(frozen=True)
class Citation:
    document: str
    path: str
    line: int | None
    end_line: int | None
    symbol: str | None
    raw: str

    @property
    def is_symbol_anchored(self) -> bool:
        return self.symbol is not None


@dataclass(frozen=True)
class Finding:
    citation: Citation
    kind: str  # unresolved_path | line_out_of_range | symbol_absent | line_only
    detail: str

    @property
    def fatal(self) -> bool:
        return self.kind != "line_only"

    def to_json(self) -> dict:
        return {
            "document": self.citation.document,
            "citation": self.citation.raw,
            "path": self.citation.path,
            "line": self.citation.line,
            "symbol": self.citation.symbol,
            "kind": self.kind,
            "detail": self.detail,
            "fatal": self.fatal,
        }


@dataclass
class AuditReport:
    repo: str = "."
    documents: int = 0
    citations: int = 0
    symbol_anchored: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def fatal_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.fatal]

    @property
    def ok(self) -> bool:
        return not self.fatal_findings

    def to_json(self) -> dict:
        return {
            "repo": self.repo,
            "documents": self.documents,
            "citations": self.citations,
            "symbol_anchored": self.symbol_anchored,
            "ok": self.ok,
            "findings": [f.to_json() for f in self.findings],
        }


def _tracked_documents(repo: Path, globs: Sequence[str]) -> list[Path]:
    """Documents to audit.  Prefers git (respects ignores); falls back to a walk so the
    audit still runs in an exported tarball or a non-git checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", *globs],
            capture_output=True, text=True, check=True,
        ).stdout
        names = [n for n in out.split("\0") if n]
        if names:
            return [repo / n for n in names]
    except Exception:
        pass
    found: list[Path] = []
    for pattern in globs:
        found.extend(p for p in repo.glob(pattern) if p.is_file())
    return sorted(set(found))


def _resolve(repo: Path, rel: str, search_roots: Sequence[Path]) -> Path | None:
    """Repo-root first, then caller-supplied roots, then a basename match anywhere.

    The basename fallback is what makes this work on layouts the caller never described —
    a doc citing ``verbs.py:25`` in a deep package resolves without configuration. It is
    only accepted when unambiguous."""
    direct = repo / rel
    if direct.is_file():
        return direct
    for root in search_roots:
        candidate = (root / rel) if not root.is_absolute() else (root / rel)
        if candidate.is_file():
            return candidate
    name = Path(rel).name
    matches = [
        p for p in repo.rglob(name)
        if p.is_file()
        and not _DERIVED_DIRS.intersection(p.parts)
        and str(p).endswith(rel)
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise _Ambiguous(sorted(str(m.relative_to(repo)) for m in matches))
    return None


#: Line/inline comment openers across the ecosystems this audit targets, plus the string
#: delimiters a symbol name could otherwise hide inside.  Stripped before matching: a
#: FABRICATED symbol mentioned in a comment ("// interface NeverExisted {}") or in a string
#: literal previously satisfied the search, which defeated the audit's primary purpose.
_COMMENT_OPENERS = ("#", "//", "--", ";")
_BLOCK_COMMENTS = (
    (r"/\*", r"\*/"),
    (r'"""', r'"""'),
    (r"'''", r"'''"),
    (r"<!--", r"-->"),
)


def _strip_noncode(text: str) -> str:
    """Remove block comments, line comments and string literals.

    Deliberately crude and language-agnostic: it over-strips rather than under-strips,
    because a false NEGATIVE here (missing a real definition) surfaces as a loud
    `symbol_absent` a human corrects, while a false POSITIVE (accepting a fabricated
    symbol) is silent and is exactly the defect this audit exists to catch.
    """
    for opener, closer in _BLOCK_COMMENTS:
        text = re.sub(rf"{opener}.*?{closer}", " ", text, flags=re.DOTALL)
    out = []
    for line in text.splitlines():
        for opener in _COMMENT_OPENERS:
            idx = line.find(opener)
            if idx != -1:
                line = line[:idx]
        line = re.sub(r'"[^"]*"', '""', line)
        line = re.sub(r"'[^']*'", "''", line)
        out.append(line)
    return "\n".join(out)


def _symbol_defined(text: str, symbol: str) -> bool:
    """Language-agnostic 'is this symbol defined here'.

    Operates on CODE ONLY — comments and string literals are stripped first.

    Matches the shapes definitions take across common languages without importing any
    language tooling: a definition keyword before the name, or the name bound/declared at
    the start of a line.  Deliberately permissive — the goal is catching a FABRICATED
    symbol, not grading style."""
    text = _strip_noncode(text)
    escaped = re.escape(symbol)
    patterns = (
        rf"\b(?:def|class|func|fn|function|struct|interface|type|impl|trait|enum|module)\s+{escaped}\b",
        rf"^\s*(?:export\s+)?(?:public\s+|private\s+|static\s+|async\s+)*[A-Za-z_<>\[\]:*&\s]*\b{escaped}\s*\(",
        # Receiver / method forms whose prefix contains parens, so the generic
        # `name(` pattern cannot reach them: Go `func (s *Store) Name(`,
        # C++/PHP `Type::Name(`. Found by a portability test that initially passed
        # WITHOUT this and therefore proved nothing.
        rf"\b(?:func|fn)\s*\([^)]*\)\s*(?:[A-Za-z_<>\[\]:*&\s]*\s)?{escaped}\s*\(",
        rf"\b{escaped}\s*\(\s*\)\s*(?:->|:|\{{)",
        rf"^\s*(?:const|let|var|val)\s+{escaped}\b",
        rf"^\s*{escaped}\s*[:=]",
        rf"^\s*{escaped}\s*\(",
    )
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def extract_citations(document: Path, repo: Path) -> list[Citation]:
    rel_doc = str(document.relative_to(repo)) if document.is_absolute() else str(document)
    citations: list[Citation] = []
    for m in _CITATION.finditer(document.read_text(encoding="utf-8", errors="replace")):
        path = m.group("path")
        if Path(path).suffix.lower() in _PROSE_SUFFIXES:
            continue  # a doc citing a doc is not a source citation
        if "." not in Path(path).name:
            continue  # e.g. a bare directory reference
        citations.append(
            Citation(
                document=rel_doc,
                path=path,
                line=int(m.group("line")) if m.group("line") else None,
                end_line=int(m.group("end")) if m.group("end") else None,
                symbol=m.group("symbol"),
                raw=m.group(0).strip("`"),
            )
        )
    return citations


def audit(
    repo: Path,
    *,
    globs: Sequence[str] = ("**/*.md",),
    search_roots: Iterable[Path | str] = (),
    require_symbols: bool = False,
) -> AuditReport:
    """Verify every source citation in the selected documents."""
    repo = Path(repo).resolve()
    roots = [repo / r if not Path(r).is_absolute() else Path(r) for r in search_roots]
    report = AuditReport(repo=str(repo))

    for doc in _tracked_documents(repo, list(globs)):
        report.documents += 1
        for cite in extract_citations(doc, repo):
            report.citations += 1
            if cite.is_symbol_anchored:
                report.symbol_anchored += 1

            try:
                target = _resolve(repo, cite.path, roots)
            except _Ambiguous as exc:
                report.findings.append(
                    Finding(cite, "ambiguous_path",
                            f"{cite.path!r} matches {len(exc.candidates)} files "
                            f"({', '.join(exc.candidates[:3])}) — qualify the path")
                )
                continue
            if target is None:
                report.findings.append(Finding(cite, "unresolved_path", f"no file matches {cite.path!r}"))
                continue

            text = target.read_text(encoding="utf-8", errors="replace")

            if cite.symbol is not None:
                if not _symbol_defined(text, cite.symbol):
                    report.findings.append(
                        Finding(cite, "symbol_absent",
                                f"{cite.symbol!r} is not defined in {cite.path} — fabricated or renamed")
                    )
                continue

            lines = text.splitlines()
            upper = cite.end_line or cite.line or 0
            if upper > len(lines):
                report.findings.append(
                    Finding(cite, "line_out_of_range",
                            f"{cite.path} has {len(lines)} lines; citation points at {upper}")
                )
                continue

            report.findings.append(
                Finding(cite, "line_only",
                        "line-anchored: existence checked, but IN-RANGE DRIFT IS NOT DETECTABLE "
                        "from a bare line number — prefer `path::symbol`, which is self-describing")
            )

    if require_symbols:
        report.findings = [
            Finding(f.citation, "unresolved_path" if f.kind == "line_only" else f.kind, f.detail)
            if f.kind == "line_only" else f
            for f in report.findings
        ]
    return report


def audit_many(
    repos: Sequence[Path | str],
    **kwargs,
) -> list[AuditReport]:
    """Audit several repos in one invocation.

    Mirrors the fleet's established cross-repo audit shape (`closeout-drift-audit --repo .
    --repo ../governed-pipeline`), so a single run can cover agent-harness, the governed
    pipeline and the spec repo together. Each repo resolves independently — no shared
    search roots, so one repo's layout cannot mask another's broken citation."""
    return [audit(Path(r), **kwargs) for r in repos]


def render(report: AuditReport) -> str:
    lines = [
        f"citation-audit [{report.repo}]: {report.citations} citations across "
        f"{report.documents} documents ({report.symbol_anchored} symbol-anchored)"
    ]
    fatal = report.fatal_findings
    advisory = [f for f in report.findings if not f.fatal]
    for f in fatal:
        lines.append(f"  FAIL  {f.citation.document}: `{f.citation.raw}` — {f.detail}")
    if advisory:
        lines.append(f"  note: {len(advisory)} line-anchored citation(s); prefer `path::symbol`")
    lines.append("  OK" if report.ok else f"  {len(fatal)} unverifiable citation(s)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="citation-audit",
        description="Verify that source citations in prose documents still resolve.",
    )
    parser.add_argument("--repo", action="append", default=None,
                        help="Repository root; REPEATABLE to audit several repos in one run "
                             "(e.g. --repo . --repo ../governed-pipeline --repo ../spec). "
                             "Default: cwd.")
    parser.add_argument("--glob", action="append", default=None,
                        help="Document glob; repeatable (default: **/*.md).")
    parser.add_argument("--search-root", action="append", default=[],
                        help="Extra root to resolve cited paths against; repeatable.")
    parser.add_argument("--require-symbols", action="store_true",
                        help="Treat line-only citations as failures (migrate to `path::symbol`).")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)

    reports = audit_many(
        args.repo or ["."],
        globs=tuple(args.glob or ("**/*.md",)),
        search_roots=args.search_root,
        require_symbols=args.require_symbols,
    )
    if args.json:
        print(json.dumps({"repos": [r.to_json() for r in reports],
                          "ok": all(r.ok for r in reports)}, indent=2))
    else:
        print("\n".join(render(r) for r in reports))
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
