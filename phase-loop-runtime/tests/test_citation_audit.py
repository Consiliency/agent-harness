"""ah#334 follow-up: mechanical verification of source citations in prose.

The audit exists because seven citations drifted or were fabricated in normative plan
documents in a single session, every one caught by a human/agent reviewer rather than by
a check. The tests below pin the two things that make it worth having:

1. it catches a FABRICATED symbol (no line-based check can), and
2. it is genuinely PORTABLE — the portability claim is asserted by building a
   TypeScript/Go/Rust repo with a layout this project does not use, rather than by
   docstring. A portability claim that is only prose is the same class of unverified
   assertion the audit was written to catch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from phase_loop_runtime import citation_audit


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _kinds(report) -> set[str]:
    return {f.kind for f in report.findings}


def test_fabricated_symbol_is_caught(tmp_path: Path):
    """THE case a line-checker cannot catch: the citation resolves to a real file and a
    real line, but names a symbol that never existed. Mutation: delete the `symbol_absent`
    branch -> this passes while a fabricated identifier ships."""
    repo = _repo(tmp_path, {
        "src/store.py": "def admit(request):\n    return request\n",
        "docs/plan.md": "See `src/store.py::admit_atomically` for the guard.\n",
    })
    report = citation_audit.audit(repo)
    assert not report.ok
    assert "symbol_absent" in _kinds(report)


def test_real_symbol_resolves(tmp_path: Path):
    """POSITIVE CONTROL. Without it, hardcoding `symbol_absent` would pass the test above."""
    repo = _repo(tmp_path, {
        "src/store.py": "def admit(request):\n    return request\n",
        "docs/plan.md": "See `src/store.py::admit` for the guard.\n",
    })
    assert citation_audit.audit(repo).ok


def test_line_past_eof_is_caught(tmp_path: Path):
    repo = _repo(tmp_path, {
        "src/store.py": "x = 1\n",
        "docs/plan.md": "See `src/store.py:900`.\n",
    })
    report = citation_audit.audit(repo)
    assert not report.ok and "line_out_of_range" in _kinds(report)


def test_ambiguous_basename_is_not_reported_as_missing(tmp_path: Path):
    """Regression on the audit's OWN first version: when a basename matched several files
    it reported "no file matches", which is a FALSE statement about the repo. Ambiguity is
    its own kind. Mutation: collapse `ambiguous_path` into `unresolved_path` -> fails."""
    repo = _repo(tmp_path, {
        "a/store.py": "def admit(): pass\n",
        "b/store.py": "def admit(): pass\n",
        "docs/plan.md": "See `store.py:1`.\n",
    })
    report = citation_audit.audit(repo)
    assert "ambiguous_path" in _kinds(report)
    assert "unresolved_path" not in _kinds(report), "must not claim the file is missing"


def test_generated_copies_do_not_create_false_ambiguity(tmp_path: Path):
    """A `build/` copy of a source file must not make its citation ambiguous — the
    citation means the real file. Cross-ecosystem convention, not repo-specific."""
    repo = _repo(tmp_path, {
        "src/store.py": "def admit(): pass\n",
        "build/lib/store.py": "def admit(): pass\n",
        "docs/plan.md": "See `store.py:1`.\n",
    })
    assert citation_audit.audit(repo).ok


def test_doc_citing_a_doc_is_not_a_source_citation(tmp_path: Path):
    repo = _repo(tmp_path, {"docs/a.md": "See `docs/b.md:400` for context.\n"})
    assert citation_audit.audit(repo).ok


def test_line_anchored_citations_are_advisory_not_fatal(tmp_path: Path):
    """A repo with existing line citations must not be blocked on day one; the migration to
    `path::symbol` is opt-in via --require-symbols."""
    repo = _repo(tmp_path, {
        "src/store.py": "x = 1\n",
        "docs/plan.md": "See `src/store.py:1`.\n",
    })
    lenient = citation_audit.audit(repo)
    assert lenient.ok and "line_only" in _kinds(lenient)
    strict = citation_audit.audit(repo, require_symbols=True)
    assert not strict.ok


def test_portable_across_languages_and_layouts(tmp_path: Path):
    """THE PORTABILITY CLAIM, ASSERTED RATHER THAN DOCUMENTED.

    A TypeScript/Go/Rust repo with a layout this project does not use, audited with ZERO
    configuration. Mutation: reintroduce any Python-specific or layout-specific assumption
    into `_resolve`/`_symbol_defined` -> the good citations stop resolving and this fails.
    """
    repo = _repo(tmp_path, {
        "src/api/handlers.ts": (
            "export function commitTransaction(id: string): void {}\n"
            "export interface AdmissionTarget {\n  head: string;\n}\n"          # no parens
        ),
        "lib/store.go": (
            "package lib\n\n"
            "func AdmitRecord(id string) error { return nil }\n"
            "type LedgerRecord struct {\n\tHead string\n}\n"                     # no parens
            "func (s *Store) Reconcile() error { return nil }\n"                  # receiver form
        ),
        "lib/engine.rs": (
            "impl Engine {\n    fn resolve_head(&self) -> Option<String> { None }\n}\n"
            "pub struct Generation {\n    pub n: u64,\n}\n"                       # no parens
            "pub trait Fenced {}\n"                                               # no parens
        ),
        "docs/design.md": (
            "- `src/api/handlers.ts::commitTransaction`\n"
            "- `src/api/handlers.ts::AdmissionTarget`\n"
            "- `lib/store.go::AdmitRecord`\n"
            "- `lib/store.go::LedgerRecord`\n"
            "- `lib/store.go::Reconcile`\n"
            "- `lib/engine.rs::resolve_head`\n"
            "- `lib/engine.rs::Generation`\n"
            "- `lib/engine.rs::Fenced`\n"
            "- BROKEN: `lib/store.go::AdmitRecordAtomically`\n"
        ),
    })
    report = citation_audit.audit(repo)

    # Declarations with NO parentheses (interface/struct/trait) and Go's receiver form
    # cannot match a generic `name(` pattern — they REQUIRE the language keyword list, so
    # narrowing it to Python breaks them. That is what makes this test discriminating.
    assert report.symbol_anchored == 9
    fatal = report.fatal_findings
    assert len(fatal) == 1, f"only the fabricated symbol should fail: {[f.detail for f in fatal]}"
    assert fatal[0].citation.symbol == "AdmitRecordAtomically"


def test_cross_repo_audit_keeps_repos_independent(tmp_path: Path):
    """Fleet shape (`--repo . --repo ../governed-pipeline`). One repo's layout must not
    resolve another's citation — otherwise a broken reference could be masked by a
    same-named file in a sibling repo."""
    a = _repo(tmp_path / "a", {
        "src/store.py": "def admit(): pass\n",
        "docs/p.md": "`src/store.py::admit`\n",
    })
    b = _repo(tmp_path / "b", {"docs/p.md": "`src/store.py::admit`\n"})

    reports = citation_audit.audit_many([a, b])
    assert reports[0].ok, "repo A's own citation resolves"
    assert not reports[1].ok, "repo B has no such file — must not borrow repo A's"
    assert "unresolved_path" in _kinds(reports[1])


# --- review round: two claims the module made and did NOT satisfy ------------------

def test_fabricated_symbol_in_a_comment_does_not_satisfy_the_search(tmp_path: Path):
    """The audit's PRIMARY purpose is catching a fabricated symbol. The first version
    searched raw source, so a name merely MENTIONED in a comment satisfied it — verified by
    a reviewer with `// interface NeverExisted {}`. That made the headline claim false.

    Mutation: drop the `_strip_noncode` call from `_symbol_defined` -> these pass and the
    audit silently accepts fabricated citations again."""
    repo = _repo(tmp_path, {
        "src/api.ts": "// interface NeverExisted {}\nexport function real(): void {}\n",
        "src/py.py": '# def AlsoFake(): pass\nmsg = "def StringFake"\ndef real2(): pass\n',
        "docs/plan.md": (
            "- `src/api.ts::NeverExisted`\n"
            "- `src/py.py::AlsoFake`\n"
            "- `src/py.py::StringFake`\n"
        ),
    })
    report = citation_audit.audit(repo)
    absent = [f for f in report.findings if f.kind == "symbol_absent"]
    assert len(absent) == 3, f"all three are fabricated: {[f.citation.symbol for f in absent]}"


def test_real_definitions_still_resolve_after_stripping(tmp_path: Path):
    """POSITIVE CONTROL for the strip. Over-stripping would silently turn real citations
    into `symbol_absent` — a false accusation, which is its own kind of wrong."""
    repo = _repo(tmp_path, {
        "src/api.ts": "// commentary about Target\nexport interface Target {\n  h: string;\n}\n",
        "lib/s.go": "package lib\n// Reconcile does things\nfunc (s *S) Reconcile() error { return nil }\n",
        "docs/plan.md": "- `src/api.ts::Target`\n- `lib/s.go::Reconcile`\n",
    })
    assert citation_audit.audit(repo).ok


def test_in_range_line_drift_is_NOT_claimed_to_be_detected(tmp_path: Path):
    """HONESTY TEST. An earlier version implied it caught drifted line anchors. It does not
    and cannot: a bare `path:N` carries no expectation of what line N should contain, so
    after a drift the line still exists and there is nothing to compare against.

    This test pins the LIMIT rather than a capability, so nobody re-adds the claim without
    also adding the mechanism (a carried expectation or a content-digest baseline). The
    module docstring must keep saying so."""
    repo = _repo(tmp_path, {
        "code.py": "import os\nimport sys\n\ndef target():\n    pass\n",
        "docs/plan.md": "See `code.py:4` for target().\n",
    })
    assert citation_audit.audit(repo).ok

    # Drift it exactly as ah#334's import removal drifted train_runner.py.
    (tmp_path / "code.py").write_text("import os\n\ndef target():\n    pass\n", encoding="utf-8")
    after = citation_audit.audit(repo)
    assert after.ok, "still 'ok' — the audit does not detect in-range drift"
    assert {f.kind for f in after.findings} == {"line_only"}

    doc = citation_audit.__doc__ or ""
    assert "Cannot detect" in doc and "IN-RANGE line drift" in doc, (
        "the module must state this limit; an earlier version implied the opposite"
    )


# --- review round 2: five claims the module made and did NOT satisfy ---------------

def test_symbol_present_but_NOT_DEFINED_is_rejected(tmp_path: Path):
    """THE CASE THAT MADE THE WHOLE SUITE VACUOUS.

    Every earlier negative case was fabricated by ABSENCE — the name appeared nowhere. So a
    degenerate `_symbol_defined = lambda t, s: s in t` passed all 12 tests, and the comment
    claiming the portability test was 'discriminating' was itself false.

    Here the symbol is PRESENT in the file — as a call site, an import, a type reference —
    but never DEFINED. Mutation: replace `_symbol_defined` with a substring check -> fails.
    """
    repo = _repo(tmp_path, {
        "src/app.ts": 'import { Ghost } from "./ghost";\nexport function boot(): void { Ghost(); }\n',
        "src/use.py": "from lib import Phantom\n\ndef run():\n    return Phantom()\n",
        "lib/s.go": "package lib\n\nvar Spectre error\n\nfunc Real() error { return Spectre }\n",
        "docs/plan.md": (
            "- `src/app.ts::Ghost`\n"      # imported + called, never defined here
            "- `src/use.py::Phantom`\n"    # imported + called, never defined here
            "- `src/app.ts::boot`\n"       # genuinely defined -> must pass
            "- `lib/s.go::Real`\n"         # genuinely defined -> must pass
        ),
    })
    report = citation_audit.audit(repo)
    absent = {f.citation.symbol for f in report.findings if f.kind == "symbol_absent"}
    assert absent == {"Ghost", "Phantom"}, (
        f"a call site or import is not a definition; got {absent}"
    )


def test_stripping_does_not_falsely_accuse_real_code(tmp_path: Path):
    """A FALSE ACCUSATION IS ITS OWN KIND OF WRONG. The first stripper guessed one global
    comment syntax and truncated real declarations: `;` (a statement separator in most of
    the languages the module claims to support), `#` (C preprocessor / Rust attributes),
    and `'...'` (Rust lifetimes). Seven legitimate definitions were reported FATAL as
    'fabricated or renamed'. Mutation: put `;` back in the opener set -> this fails."""
    repo = _repo(tmp_path, {
        "src/a.ts": "const a = 1; export function boot(): void {}\n",
        "src/b.c": "#define MAX_RETRIES 10\n",
        "src/c.rs": "impl<'a> Parser<'a> {\n    fn go(&self) {}\n}\n",
        "src/d.py": 'url = "http://x.co"\nimport os;\ndef grab(): pass\n',
        "docs/plan.md": (
            "- `src/a.ts::boot`\n- `src/b.c::MAX_RETRIES`\n"
            "- `src/c.rs::Parser`\n- `src/d.py::grab`\n"
        ),
    })
    report = citation_audit.audit(repo)
    assert report.ok, f"real definitions falsely accused: {[f.detail for f in report.fatal_findings]}"


def test_escaped_quote_cannot_smuggle_a_fabricated_symbol(tmp_path: Path):
    """The first string regex `"[^"]*"` could not span an escaped quote, so a fabricated
    name hid inside one. Mutation: revert to the non-escape-aware pattern -> fails."""
    repo = _repo(tmp_path, {
        "src/s.py": 'x = "he said \\"def Phantom(\\" ok"\ndef real(): pass\n',
        "docs/plan.md": "- `src/s.py::Phantom`\n",
    })
    report = citation_audit.audit(repo)
    assert not report.ok and "symbol_absent" in _kinds(report)


def test_backtick_string_cannot_smuggle_a_fabricated_symbol(tmp_path: Path):
    """Found by a vendor leg: JS/TS template literals and Go raw strings are delimited by
    backticks, which the earlier stripper ignored entirely — so a fabricated symbol inside
    one satisfied the search. They span lines, so they must be stripped before the
    line-by-line pass. Mutation: remove the `_BACKTICK_STRING` substitution -> fails."""
    repo = _repo(tmp_path, {
        "src/a.ts": "const q = `class Ghost {}`;\nexport function real(): void {}\n",
        "lib/b.go": "package lib\n\nconst q = `func Spectre() {}`\n\nfunc Real() {}\n",
        "docs/plan.md": "- `src/a.ts::Ghost`\n- `lib/b.go::Spectre`\n- `src/a.ts::real`\n- `lib/b.go::Real`\n",
    })
    report = citation_audit.audit(repo)
    absent = {f.citation.symbol for f in report.findings if f.kind == "symbol_absent"}
    assert absent == {"Ghost", "Spectre"}, f"backtick strings must not define symbols; got {absent}"


# --- confirmation round: two fail-open paths the earlier tests could not reach ------

def test_socket_addresses_are_not_citations(tmp_path: Path):
    """A reviewer found the repo's OWN docs producing fatal findings: `127.0.0.1:18765`
    parsed as path `127.0.0.1` line `18765` and was reported "no file matches" — a false
    accusation against a socket address. A citation path must end in a FILE EXTENSION.
    Mutation: relax the path pattern back to 'contains a dot or slash' -> this fails."""
    repo = _repo(tmp_path, {
        "src/a.py": "def run(): pass\n",
        "docs/ops.md": (
            "Connect to 127.0.0.1:18765 and also http://127.0.0.1:18765/health.\n"
            "Version 1.2.3 shipped. See `src/a.py::run` for the handler.\n"
        ),
    })
    report = citation_audit.audit(repo)
    assert report.ok, f"non-paths must not be cited: {[f.detail for f in report.fatal_findings]}"
    assert report.citations == 1, "only the real source citation should be recognised"


def test_cli_repeated_repo_after_subcommand_audits_every_repo(tmp_path, capsys):
    """CLI-LEVEL, deliberately. The earlier test called `audit_many()` directly and so could
    not see that the shipped entrypoint dropped repos. Mutation: remove `citation-audit`
    from cli.py's append-allowlist -> only the last repo is audited and this fails."""
    from phase_loop_runtime import cli

    a = _repo(tmp_path / "a", {"src/x.py": "def f(): pass\n", "docs/p.md": "`src/x.py::missing_sym`\n"})
    b = _repo(tmp_path / "b", {"docs/p.md": "clean\n"})

    rc = cli.main(["citation-audit", "--repo", str(a), "--repo", str(b)])
    out = capsys.readouterr().out
    assert out.count("citation-audit [") == 2, f"both repos must be audited:\n{out}"
    assert rc == 1, "a broken citation in ANY audited repo must fail the run"


def test_cli_refuses_the_truncating_top_level_repo_position(tmp_path, capsys):
    """The TOP-LEVEL `--repo` is scalar and shared by every subcommand, so
    `phase-loop --repo a --repo b citation-audit` silently keeps only `b`. Auditing a subset
    while exiting 0 is precisely the fail-open this command exists to avoid, so it must
    REFUSE rather than under-report. Mutation: drop the guard -> it silently audits one."""
    from phase_loop_runtime import cli

    a = _repo(tmp_path / "a", {"docs/p.md": "clean\n"})
    b = _repo(tmp_path / "b", {"docs/p.md": "clean\n"})

    rc = cli.main(["--repo", str(a), "--repo", str(b), "citation-audit"])
    err = capsys.readouterr().err
    assert rc == 2, "must refuse, not silently audit a subset"
    assert "DISCARDED" in err and "after the subcommand" in err, err
