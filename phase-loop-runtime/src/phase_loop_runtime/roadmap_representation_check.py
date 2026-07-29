"""Cross-representation consistency check for phase-plan roadmaps (agent-harness#375).

``roadmap_lint`` validates only the STRUCTURED field (``**Depends on**``) — which is
exactly why four rounds of review on ``phase-plans-v10.md`` each shipped a green lint
over a document whose human-facing representations contradicted the structured graph
(a freeze vs its criteria, a dependency vs its DAG, a count vs the list beneath it, a
critical path vs the structured edges). A validator that cannot see the representations
humans read is not validating the document.

This module treats each phase's ``**Depends on**`` block as the AUTHORITY and diffs it
against the representations a human actually reads inside the ``## Phase Dependency DAG``
fence and the ``## Execution Notes`` root count:

  * the ASCII DAG arrows,
  * the ``Parallel roots`` list,
  * the ``Serial edges`` list (and its self-declared count),
  * the ``Critical path`` chain(s),
  * the "N phases are independent roots" sentence in Execution Notes.

Design for ZERO false positives by construction (not an allowlist — an allowlist would
blind the tool in the absorbed sub-graph, which is exactly where a future real
inconsistency would hide):

  * arrows are read ONLY inside the fenced DAG block, never from surrounding prose;
  * an edge is emitted only when BOTH operands are known phase aliases and differ, so
    box-drawing glyphs, comments, and continuation lines never manufacture an edge;
  * the primary direction is "every edge a representation CLAIMS must be backed by the
    structured field" — the reverse ("a structured edge missing from a list") is noisy
    (continuation lines, absorbed-chain scoping) and is intentionally NOT asserted.

It is ADVISORY: standalone, not wired into the fatal ``lint_roadmap_text`` gate, because
every superseded roadmap (v1..v9, convergence-v1) also carries a DAG section that no one
will reconcile, and ``roadmap_lint`` feeds the skill bundle and CI. Wiring it in after
the corpus is reconciled is tracked as agent-harness#395. Output is meant to be REVIEWED,
not auto-applied.

Zero external deps (stdlib only). Reuses ``roadmap_lint._extract_phases`` for the
authority parse so the structured graph has a single source of truth.
"""

from __future__ import annotations

import functools
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .roadmap_lint import _extract_phases

ARROW = "→"  # →

_WORD_TO_INT = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_INT_TO_WORD = {v: k for k, v in _WORD_TO_INT.items()}


@dataclass(frozen=True)
class Finding:
    representation: str  # "ascii-dag" | "serial-edges" | "parallel-roots" | "critical-path" | "root-count"
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.representation}] {self.message}"


# ---------------------------------------------------------------------------
# Structured authority (from **Depends on**)

def _authority(text: str) -> Tuple[Set[Tuple[str, str]], Set[str], Set[str], List[Tuple[str, ...]]]:
    """Return (edges parent->child, all aliases, roots, maximal root->sink chains)."""
    phases = _extract_phases(text)
    aliases = {p.alias for p in phases}
    edges: Set[Tuple[str, str]] = set()
    succ: Dict[str, List[str]] = {p.alias: [] for p in phases}
    for p in phases:
        for dep in p.depends_on:
            if dep in aliases:
                edges.add((dep, p.alias))
                succ[dep].append(p.alias)
    roots = {p.alias for p in phases if not any(d in aliases for d in p.depends_on)}

    @functools.lru_cache(maxsize=None)
    def longest_from(a: str) -> Tuple[str, ...]:
        best: Tuple[str, ...] = (a,)
        for c in succ[a]:
            cand = (a,) + longest_from(c)
            if len(cand) > len(best):
                best = cand
        return best

    if aliases:
        chains = [longest_from(r) for r in roots] or [longest_from(a) for a in aliases]
        maxlen = max((len(c) for c in chains), default=0)
        maximal = sorted({longest_from(r) for r in roots if len(longest_from(r)) == maxlen})
    else:
        maximal = []
    return edges, aliases, roots, maximal


# ---------------------------------------------------------------------------
# Representation parsing (inside the DAG fence only)

def _dag_fence(text: str) -> str:
    """The content of the first ``` fenced block after '## Phase Dependency DAG'."""
    m = re.search(r"^##\s+Phase Dependency DAG\s*$", text, re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end():]
    fm = re.search(r"```[^\n]*\n(?P<body>.*?)\n```", rest, re.DOTALL)
    return fm.group("body") if fm else ""


def _edges_on_line(line: str, aliases: Set[str]) -> List[Tuple[str, str]]:
    """Edges from a single line: for each arrow, the nearest known-alias token to its
    left and right. Both operands must be known aliases and differ — box-drawing,
    comments, and continuation lines (no left alias) yield nothing."""
    # positions of known-alias tokens
    toks = [(mt.start(), mt.group(0)) for mt in re.finditer(r"[A-Za-z][A-Za-z0-9]*", line)
            if mt.group(0) in aliases]
    out: List[Tuple[str, str]] = []
    for am in re.finditer(re.escape(ARROW), line):
        pos = am.start()
        left = [t for p, t in toks if p < pos]
        right = [t for p, t in toks if p > pos]
        if left and right and left[-1] != right[0]:
            out.append((left[-1], right[0]))
    return out


def _chain_on_line(line: str, aliases: Set[str]) -> Tuple[str, ...]:
    """The ordered sequence of known-alias tokens on a line that contains arrows."""
    if ARROW not in line:
        return ()
    return tuple(mt.group(0) for mt in re.finditer(r"[A-Za-z][A-Za-z0-9]*", line)
                 if mt.group(0) in aliases)


@dataclass
class _Regions:
    bracket: List[str]
    parallel: List[str]
    serial: List[str]
    absorbed: List[str]
    critical: List[str]


def _split_regions(fence: str) -> _Regions:
    reg = _Regions([], [], [], [], [])
    cur = reg.bracket
    for line in fence.splitlines():
        low = line.strip().lower()
        if low.startswith("parallel roots"):
            cur = reg.parallel
            continue
        if low.startswith("serial edges"):
            cur = reg.serial
            reg.serial.append(line)  # keep header for count check
            continue
        if low.startswith("absorbed"):
            cur = reg.absorbed
            continue
        if low.startswith("critical path"):
            cur = reg.critical
            reg.critical.append(line)  # keep header (holds the count check)
            continue
        cur.append(line)
    return reg


# ---------------------------------------------------------------------------
# Checks

def check_representation_consistency(text: str) -> List[Finding]:
    edges, aliases, roots, maximal = _authority(text)
    findings: List[Finding] = []
    if not aliases:
        return findings
    fence = _dag_fence(text)
    if not fence:
        findings.append(Finding("ascii-dag", "no fenced '## Phase Dependency DAG' block found"))
        return findings
    reg = _split_regions(fence)

    def _claimed_edges(lines: List[str]) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        for ln in lines:
            out.extend(_edges_on_line(ln, aliases))
        return out

    # (1) Every arrow a representation CLAIMS must be backed by the structured field.
    # Full region lists: a header line carries no alias-joined arrows, but the pre-fix
    # critical path lives ENTIRELY on its header line ("Critical path: A → B → ..."), so
    # dropping the header would blind the check to exactly the defect it must catch.
    for repname, lines in (("ascii-dag", reg.bracket), ("serial-edges", reg.serial),
                           ("absorbed-chain", reg.absorbed), ("critical-path", reg.critical)):
        for a, b in _claimed_edges(lines):
            if (a, b) not in edges:
                findings.append(Finding(
                    repname,
                    f"asserts edge {a} {ARROW} {b}, which no phase's **Depends on** backs"))

    # (2) Parallel-roots list must equal the structured roots.
    par_line = next((ln for ln in reg.parallel if "∥" in ln), " ".join(reg.parallel))
    claimed_roots = {t for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", par_line) if t in aliases}
    if claimed_roots:
        for extra in sorted(claimed_roots - roots):
            findings.append(Finding("parallel-roots",
                                    f"lists {extra} as a root, but it **Depends on** another phase"))
        for missing in sorted(roots - claimed_roots):
            findings.append(Finding("parallel-roots",
                                    f"omits root {missing} (it has no **Depends on**)"))

    # (3) Serial-edges self-declared count must match the number of listed edges.
    serial_edges = _claimed_edges(reg.serial[1:])
    header = reg.serial[0] if reg.serial else ""
    cm = re.search(r"\(\s*(\d+|" + "|".join(_WORD_TO_INT) + r")\b", header, re.IGNORECASE)
    if cm:
        tok = cm.group(1).lower()
        declared = int(tok) if tok.isdigit() else _WORD_TO_INT[tok]
        if declared != len(serial_edges):
            findings.append(Finding("serial-edges",
                                    f"header declares {declared} edge(s) but {len(serial_edges)} are listed"))

    # (4) Critical-path chain(s) must equal the computed set of maximal chains.
    claimed_chains = {c for ln in reg.critical for c in (_chain_on_line(ln, aliases),) if len(c) >= 2}
    if claimed_chains:
        want = set(maximal)
        for extra in sorted(claimed_chains - want):
            findings.append(Finding("critical-path",
                                    f"lists {' '.join(extra)}, not a longest structured chain"))
        for missing in sorted(want - claimed_chains):
            findings.append(Finding("critical-path",
                                    f"omits longest structured chain {' '.join(missing)}"))

    # (5) Execution Notes "N phases are independent roots" must equal len(roots).
    en = re.search(r"^##\s+Execution Notes\s*$", text, re.MULTILINE)
    if en:
        body = text[en.end(): _next_heading(text, en.end())]
        rc = re.search(r"\b(\d+|" + "|".join(_WORD_TO_INT) + r")\s+phases?\s+are\s+independent\s+roots",
                       body, re.IGNORECASE)
        if rc:
            tok = rc.group(1).lower()
            stated = int(tok) if tok.isdigit() else _WORD_TO_INT[tok]
            if stated != len(roots):
                want_word = _INT_TO_WORD.get(len(roots), str(len(roots)))
                findings.append(Finding("root-count",
                                        f"says {tok} phases are independent roots, but the structured "
                                        f"field has {len(roots)} ({want_word})"))
    return findings


def _next_heading(text: str, start: int) -> int:
    m = re.search(r"^##\s+", text[start:], re.MULTILINE)
    return start + m.start() if m else len(text)


# ---------------------------------------------------------------------------
# Public API / CLI

def check_roadmap(path: Path | str) -> List[Finding]:
    return check_representation_consistency(Path(path).read_text(encoding="utf-8"))


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        prog = Path(argv[0]).name if argv else "roadmap_representation_check"
        print(f"usage: {prog} <roadmap-path>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        findings = check_roadmap(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    if findings:
        print(f"roadmap_representation_check: {len(findings)} inconsistency(ies) in {path}", file=sys.stderr)
        for f in findings:
            print(f"  • {f}", file=sys.stderr)
        return 1
    print(f"roadmap_representation_check: OK — representations agree with **Depends on** in {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
