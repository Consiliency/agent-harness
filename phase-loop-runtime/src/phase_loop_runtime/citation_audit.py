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
#: The path must end in a FILE EXTENSION — a dot followed by an ALPHA-led token. Without
#: that, `127.0.0.1:18765` parses as path `127.0.0.1` line `18765` and is reported FATAL as
#: "no file matches" — a false accusation against a socket address, triggered by this
#: repo's own docs. A reviewer found it; the rule that a path merely "contains a dot or
#: slash" was too weak.
_CITATION = re.compile(
    r"`?(?P<path>[A-Za-z0-9_./\-]*[A-Za-z0-9_\-]\.[A-Za-z][A-Za-z0-9]{0,9})"
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
    kind: str  # unresolved_path | ambiguous_path | line_out_of_range | symbol_absent |
    #            line_only | symbol_required (line_only promoted under --require-symbols)
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


#: Comment syntax BY FILE EXTENSION. An earlier version guessed one global set of openers
#: and was wrong in both directions: `;` (a statement separator in C/C++/Java/JS/TS/Go/Rust/
#: PHP) truncated real declarations, `#` killed C preprocessor lines and Rust attributes,
#: and `'...'` ate Rust lifetimes — each producing a FATAL "fabricated or renamed"
#: accusation against correct code. A false accusation is its own kind of wrong.
_LINE_COMMENTS: dict[str, tuple[str, ...]] = {
    ".py": ("#",), ".rb": ("#",), ".sh": ("#",), ".bash": ("#",), ".zsh": ("#",),
    ".yml": ("#",), ".yaml": ("#",), ".toml": ("#",), ".pl": ("#",), ".r": ("#",),
    ".js": ("//",), ".jsx": ("//",), ".ts": ("//",), ".tsx": ("//",),
    ".go": ("//",), ".rs": ("//",), ".java": ("//",), ".c": ("//",), ".h": ("//",),
    ".cc": ("//",), ".cpp": ("//",), ".hpp": ("//",), ".cs": ("//",), ".swift": ("//",),
    ".kt": ("//",), ".scala": ("//",), ".php": ("//", "#"),
    ".sql": ("--",), ".lua": ("--",), ".hs": ("--",), ".ex": ("#",), ".exs": ("#",),
}
#: Conservative fallback for an unknown extension: only unambiguous openers.  `;` is
#: DELIBERATELY absent — it is a comment opener in Lisp/asm/ini and a statement separator
#: nearly everywhere else, so treating it as a comment breaks far more than it fixes.
_DEFAULT_LINE_COMMENTS: tuple[str, ...] = ("//", "#")

_BLOCK_COMMENTS = (
    (r"/\*", r"\*/"),
    (r'"""', r'"""'),
    ("'''", "'''"),
    (r"<!--", r"-->"),
)

#: A quoted string, honouring BACKSLASH ESCAPES.  The earlier `"[^"]*"` could not span an
#: escaped quote, so `x = "he said \"def Phantom(\" ok"` left `def Phantom(` exposed and a
#: FABRICATED symbol was accepted — the exact defect this stripping exists to prevent.
_DQ_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_SQ_STRING = re.compile(r"'(?:\\.|[^'\\])*'")
#: Rust lifetimes (`'a`, `'static`) are NOT char literals and must survive stripping.
_RUST_LIFETIME = re.compile(r"'[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_'])")
#: Backtick strings — JS/TS template literals and Go raw strings. A reviewer found a
#: fabricated symbol hiding in one (`const q = \`class Ghost {}\``): they span lines, so
#: they are stripped with the BLOCK comments, before line-by-line processing.
_BACKTICK_STRING = re.compile(r"`(?:[^`\\]|\\.)*`", re.DOTALL)


def _strip_noncode(text: str, suffix: str = "") -> str:
    """Remove block comments, line comments and string literals, so a symbol that is only
    MENTIONED in prose-within-code cannot satisfy a definition search.

    Comment syntax is chosen by file extension rather than guessed globally — guessing
    produced false "fabricated" accusations against correct C, Rust, Go and JS.
    """
    for opener, closer in _BLOCK_COMMENTS:
        text = re.sub(rf"{opener}.*?{closer}", " ", text, flags=re.DOTALL)
    text = _BACKTICK_STRING.sub("``", text)  # multi-line, so stripped before line splitting
    openers = _LINE_COMMENTS.get(suffix.lower(), _DEFAULT_LINE_COMMENTS)
    out = []
    for line in text.splitlines():
        # Strings first: a `//` or `#` INSIDE a string (a URL, a fragment) is not a comment.
        line = _DQ_STRING.sub('""', line)
        placeholders: list[str] = []

        def _keep_lifetime(m: "re.Match[str]") -> str:
            placeholders.append(m.group(0))
            return f"\x00LT{len(placeholders) - 1}\x00"

        line = _RUST_LIFETIME.sub(_keep_lifetime, line)
        line = _SQ_STRING.sub("''", line)
        for idx, kept in enumerate(placeholders):
            line = line.replace(f"\x00LT{idx}\x00", kept)
        for opener in openers:
            pos = line.find(opener)
            if pos != -1:
                line = line[:pos]
        out.append(line)
    return "\n".join(out)


#: Keywords that make a line a STATEMENT, not a declaration. `return Phantom()` is a CALL
#: SITE; without this guard the C-style declaration pattern reads it as a definition, and a
#: symbol that is merely imported/called/referenced passes as "defined". Checked in Python
#: rather than by regex lookahead: `^\s*` backtracks, so a lookahead can be evaluated at a
#: position where the keyword is no longer at the start and silently succeeds.
_STATEMENT_LEAD = re.compile(
    r"^\s*(?:return|yield|await|if|elif|while|for|else|throw|new|assert|del|raise|print|"
    r"case|switch|match|with|in|and|or|not)\b"
)


def _line_is_statement(text: str, symbol: str) -> bool:
    """True when EVERY line mentioning `symbol` before a `(` leads with a statement keyword."""
    hits = [ln for ln in text.splitlines() if re.search(rf"\b{re.escape(symbol)}\s*\(", ln)]
    return bool(hits) and all(_STATEMENT_LEAD.match(ln) for ln in hits)


def _symbol_defined(text: str, symbol: str, suffix: str = "") -> bool:
    """Language-agnostic 'is this symbol defined here'.

    Operates on CODE ONLY — comments and string literals are stripped first.

    Matches the shapes definitions take across common languages without importing any
    language tooling: a definition keyword before the name, or the name bound/declared at
    the start of a line.  Deliberately permissive — the goal is catching a FABRICATED
    symbol, not grading style."""
    text = _strip_noncode(text, suffix)
    escaped = re.escape(symbol)
    patterns = (
        # Generic parameters may sit between the keyword and the name — `impl<'a> Parser`,
        # `class Foo<T>`, `func[T any]`. Found by a reviewer: without `(?:<[^>]*>)?` the
        # Rust impl form produced a FATAL "fabricated" accusation against correct code.
        rf"\b(?:def|class|func|fn|function|struct|interface|type|impl|trait|enum|module)"
        rf"\s*(?:<[^>]*>)?\s+{escaped}\b",
        # C/C++ preprocessor definitions. `#` is not a comment opener in these languages,
        # so the macro name is a real declaration the audit must see.
        rf"^\s*#\s*(?:define|undef)\s+{escaped}\b",
        # C-style declaration: optional type/modifier prefix, then the name, then `(`.
        # Guarded separately below — see `_STATEMENT_LEAD`. A regex lookahead does NOT
        # work here: `^\s*` backtracks, so the guard lands mid-whitespace and never fires.
        rf"^\s*(?:export\s+)?(?:public\s+|private\s+|static\s+|async\s+)*"
        # A real declaration has a type/modifier token, then WHITESPACE, then the name. The
        # mandatory `\s+` (not `\b`) is what distinguishes `void foo(` from a bare call
        # `admit_atomically(req)`: a bare call has no token+whitespace before the name, so it
        # cannot match. `[*&]*` after the whitespace admits the pointer/reference return form
        # `char *dupstr(` / `Rec &get(` (K&R/Linux style), which is a real declaration the
        # earlier `\s+{escaped}` form falsely accused. This whole tuple is matched PER LINE
        # (see the `for ln in lines` search below), so `\s+` can never span a newline and
        # borrow the PREVIOUS line's trailing token (`try:`, `pass`, a closing `]`) as the
        # type prefix — that cross-line span silently accepted fabricated called-only symbols.
        rf"[A-Za-z_<>\[\]:*&]+\s+[*&]*\s*{escaped}\s*\(",
        # Receiver / method forms whose prefix contains parens, so the generic
        # `name(` pattern cannot reach them: Go `func (s *Store) Name(`,
        # C++/PHP `Type::Name(`. Found by a portability test that initially passed
        # WITHOUT this and therefore proved nothing.
        rf"\b(?:func|fn)\s*\([^)]*\)\s*(?:[A-Za-z_<>\[\]:*&\s]*\s)?{escaped}\s*\(",
        rf"\b{escaped}\s*\(\s*\)\s*(?:->|:|\{{)",
        # Value/constant declarations. The modifier prefix is REQUIRED: `export const`,
        # `pub const`, `pub static`, `public static final` are idiomatic TS/JS/Rust/Java, and
        # without it every one was falsely accused of being "fabricated or renamed" — a
        # FATAL finding against correct code. Found by a reviewer enumerating real-world
        # declaration forms rather than the ones I happened to write tests for.
        rf"^\s*(?:(?:export|pub(?:\([^)]*\))?|public|private|protected|internal|static|"
        rf"final|readonly|declare|extern|global)\s+)*"
        rf"(?:const|let|var|val|static)\s+{escaped}\b",
        # Typed FIELD declaration with no keyword: `public static final int MAX = 3` (Java,
        # C#, C++). At least one modifier is REQUIRED so a plain assignment or a call site
        # cannot match — `x = 1` is not a declaration of `x` in these languages.
        rf"^\s*(?:(?:public|private|protected|internal|static|final|readonly|const|extern|"
        rf"volatile|synchronized)\s+)+[A-Za-z_][A-Za-z0-9_<>\[\].]*\s+{escaped}\s*[=;]",
        rf"^\s*{escaped}\s*[:=]",
        # NOTE: a bare `name(` at line start is DELIBERATELY not a definition form. It is
        # indistinguishable from a statement-expression call (`admit_atomically(req)` in a
        # function body), which a reviewer showed was being accepted as a definition —
        # a fail-open in the audit's core question. Shell-style `name() {` and
        # `name() -> T:` are still matched by the `name()` + brace/arrow/colon form above.
    )
    # Match every pattern PER LINE, not against the whole text. A definition and its name
    # live on one physical line; searching the joined text with re.MULTILINE let `\s+` (and
    # the leading `^\s*`) span newlines, so the previous line's trailing token could serve as
    # a declaration's "type prefix" — a fabricated symbol merely CALLED as the first
    # statement of a `try:`/`else:`/`finally:` block, or after a `pass`/`return`/`]` line,
    # was silently accepted as defined. That defeated the audit's core purpose. Per-line
    # search confines every whitespace class to a single line and closes the whole class.
    lines = text.splitlines()
    if not any(re.search(p, ln) for p in patterns for ln in lines):
        return False
    # A match whose only evidence is a statement line (`return Foo()`) is a CALL SITE.
    keyword_forms = (
        rf"\b(?:def|class|func|fn|function|struct|interface|type|impl|trait|enum|module)"
        rf"\s*(?:<[^>]*>)?\s+{escaped}\b",
        rf"^\s*#\s*(?:define|undef)\s+{escaped}\b",
        rf"^\s*(?:const|let|var|val)\s+{escaped}\b",
    )
    if any(re.search(p, ln) for p in keyword_forms for ln in lines):
        return True
    return not _line_is_statement(text, symbol)


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
                if not _symbol_defined(text, cite.symbol, target.suffix):
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
        # Promote line-only advisories to FATAL under the opt-in migration gate. The kind
        # is `symbol_required`, NOT `unresolved_path`: the path DID resolve, so reporting it
        # as unresolved would be a false machine-readable diagnostic about the repo's
        # contents (a JSON consumer keying on `unresolved_path` would conclude the file is
        # missing). This is the same "never claim a resolved path is missing" rule the
        # ambiguous-vs-missing split already enforces.
        report.findings = [
            Finding(f.citation, "symbol_required",
                    f"{f.detail} [--require-symbols: line anchor rejected; migrate to `path::symbol`]")
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
