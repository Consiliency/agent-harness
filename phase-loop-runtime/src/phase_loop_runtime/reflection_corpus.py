"""Reflection corpus collector for the skill-improvement loop (agent-harness#1301).

Every phase-loop workflow skill writes a reflection at closeout to
``<skill-root>/<skill>/reflections/<repo_hash>/<branch_slug>/<run_id>.md``. This
module is the deterministic front half of the loop that consumes them:

    enumerate -> parse -> quality-filter -> emit (bundle + manifest) -> archive

The planner skill aggregates the emitted bundle; the editor skill applies the
plan and then archives the manifest's consumed paths through ``archive``. Keeping
enumeration, parsing and filtering here (not in skill prose) means the scope and
the filter rules can be tested and cannot silently drift between harnesses.

CLI::

    python3 -m phase_loop_runtime.reflection_corpus collect --out-dir DIR [--root R ...]
    python3 -m phase_loop_runtime.reflection_corpus archive --manifest DIR/manifest.json [--root R ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .credential_redaction import redact_text
from .skill_paths import HARNESS_DEFAULT_SKILL_ROOTS, resolve_skill_bundle_root

HARNESS_PREFIXES = tuple(HARNESS_DEFAULT_SKILL_ROOTS)

# Bare workflow skills whose reflections feed the loop. ``execute-detailed`` is the
# largest producer; ``advisor-panel`` is the legacy alias of ``advisor-board``.
IN_SCOPE_SKILLS = (
    "phase-roadmap-builder",
    "plan-phase",
    "execute-phase",
    "plan-detailed",
    "execute-detailed",
    "task-contextualizer",
    "skill-improvement-planner",
    "skill-editor",
    "advisor-board",
    "phase-loop",
    "run-train",
)
SKILL_ALIASES = {"advisor-panel": "advisor-board"}

SECTION_KEYS = {
    "run context": "run_context",
    "what worked": "worked",
    "what didn't": "didnt",
    "what didn’t": "didnt",
    "what did not": "didnt",
    "improvements to skill.md": "improvements",
    "skill improvements": "improvements",
}

DEFAULT_PER_BRANCH_CAP = 3
# About 4x the largest real reflection. A larger file is excluded without being read,
# so one runaway reflection cannot stall collection or flood the bundle.
MAX_REFLECTION_BYTES = 32 * 1024
DEFAULT_BOILERPLATE_MIN = 3
BOILERPLATE_MIN_CHARS = 40
# A recurring line is rendered once per skill; these bound one bundle/manifest item.
MAX_RECURRING_LINE_CHARS = 500
MAX_RECURRING_IDS = 10

# Deliberately broad: bare `repo#N` refs are how this fleet names issues, so an
# occasional false hit (`step#3`) is the cheaper error than leaking a real ref.
_ORG_REF = re.compile(r"\b[\w.-]+/[\w.-]+#\d+\b|\b[a-z][\w.-]*#\d+\b")
_ABS_PATH = re.compile(r"(?<![\w.])(?:~|/(?:home|mnt|tmp|Users|var|opt|srv|workspace))/[^\s,;)\]`'\"<]+(?![^\s]*<)")
_URL = re.compile(r"https?://\S+")
_SHA = re.compile(r"\b[0-9a-f]{40}\b")
_JSON_BLOB = re.compile(r"\{\".*\}")
_LEDGER_PREFIXES = ("publication result:", "hosted ci:", "lifecycle warning:")
_NONE_LEAD = re.compile(
    r"^\s*[-*]?\s*(?:none(?: required| proposed| needed)?|no (?:skill )?(?:edits?|changes?|improvements?)(?: (?:are |is )?(?:proposed|required|needed))?|n/?a)\b[.:;,]?\s*",
    re.IGNORECASE,
)


@dataclass
class Reflection:
    path: Path
    root: Path
    skill: str
    harness: str
    bare_skill: str
    repo_hash: str
    branch_slug: str
    run_id: str
    timestamp: str
    sections: dict[str, str]
    raw: str
    id: str = ""
    improvements_class: str = ""
    excluded: str | None = None
    notes: list[str] = field(default_factory=list)
    # Normalized lines stripped from this reflection as boilerplate that still carry
    # text once redacted; the bundle renders each once per skill with its admitted
    # carriers (agent-harness#1370).
    boilerplate: list[str] = field(default_factory=list)
    # The subset of ``boilerplate`` that was a repo-agnostic proposal.
    boilerplate_proposals: list[str] = field(default_factory=list)
    # False when the real location leaves the resolved scan root (a symlinked skill or
    # reflections dir): still read, but never consumed, since archive refuses it.
    in_root: bool = True

    @property
    def group(self) -> tuple[str, str, str]:
        return (self.skill, self.repo_hash, self.branch_slug)

    @property
    def structured(self) -> bool:
        return "didnt" in self.sections or "improvements" in self.sections


@dataclass
class Corpus:
    roots: list[Path]
    scanned: list[Reflection]
    out_of_scope: list[Path]
    min_reflections: int

    @property
    def admitted(self) -> list[Reflection]:
        return [r for r in self.scanned if r.excluded is None]

    def admitted_by_skill(self) -> dict[str, list[Reflection]]:
        grouped: dict[str, list[Reflection]] = defaultdict(list)
        for reflection in self.admitted:
            grouped[reflection.bare_skill].append(reflection)
        return dict(sorted(grouped.items()))

    def boilerplate_carriers(self, skill: str | None = None) -> dict[str, list[str]]:
        """Each stripped boilerplate line -> ids of the admitted reflections that carried it.

        With ``skill``, only that bare skill's carriers count. Excluded reflections are
        left out: the aggregator cannot look their ids up in the bundle.
        """
        carriers: dict[str, list[str]] = defaultdict(list)
        for reflection in self.admitted:
            if skill is None or reflection.bare_skill == skill:
                for line in reflection.boilerplate:
                    carriers[line].append(reflection.id)
        return dict(sorted(carriers.items()))

    def ready_skills(self) -> list[str]:
        return [skill for skill, items in self.admitted_by_skill().items() if len(items) >= self.min_reflections]

    @property
    def due(self) -> bool:
        return bool(self.ready_skills())


def default_roots() -> list[Path]:
    """Every harness's installed skill root; reflections land in more than one.

    A ``PHASE_LOOP_SKILL_BUNDLE`` override is where writers put reflections, so it
    is scanned too.
    """
    roots = [root.expanduser() for root in HARNESS_DEFAULT_SKILL_ROOTS.values()]
    if os.environ.get("PHASE_LOOP_SKILL_BUNDLE"):
        override = resolve_skill_bundle_root()
        if override not in roots:
            roots.append(override)
    return roots


def split_skill(skill: str) -> tuple[str, str] | None:
    for prefix in HARNESS_PREFIXES:
        if skill.startswith(prefix + "-"):
            bare = skill[len(prefix) + 1:]
            return prefix, SKILL_ALIASES.get(bare, bare)
    return None


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            key = SECTION_KEYS.get(heading.group(1).strip().lower())
            # An unknown second-level heading ends the current section; trailing
            # ledger/successor sections are not reflection content.
            current = key
            if key is not None:
                sections.setdefault(key, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _run_context_value(run_context: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*:\s*(\S+)", run_context, re.IGNORECASE)
    return match.group(1).rstrip(".") if match else ""


def _within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _contained(path: Path, reflections: Path) -> bool:
    """A regular, non-symlink file whose real location is inside its reflections dir.

    ``is_symlink`` runs first because every later check (and the size ``stat``) follows
    links.
    """
    if path.is_symlink() or not path.is_file():
        return False
    return _within(path.resolve(), reflections.resolve())


def iter_reflection_paths(root: Path, skipped: list[Path] | None = None) -> Iterable[tuple[str, Path]]:
    if not root.is_dir():
        return
    for reflections in sorted(root.glob("*/reflections")):
        for path in sorted(reflections.rglob("*.md")):
            if "archive" in path.relative_to(reflections).parts:
                continue
            if _contained(path, reflections):
                yield reflections.parent.name, path
            elif skipped is not None:
                skipped.append(path)


def read_reflection(root: Path, skill: str, path: Path) -> Reflection | None:
    split = split_skill(skill)
    if split is None:
        return None
    harness, bare = split
    rel = path.relative_to(root / skill / "reflections").parts
    repo_hash = rel[0] if len(rel) >= 3 else ""
    branch_slug = "/".join(rel[1:-1]) if len(rel) >= 3 else ""
    size = path.stat().st_size
    oversized = size > MAX_REFLECTION_BYTES
    raw = "" if oversized else path.read_text(encoding="utf-8", errors="replace")
    sections = parse_sections(raw)
    timestamp = _run_context_value(sections.get("run_context", ""), "Timestamp") or path.stem
    return Reflection(
        path=path,
        root=root,
        skill=skill,
        harness=harness,
        bare_skill=bare,
        repo_hash=repo_hash,
        branch_slug=branch_slug,
        run_id=path.stem,
        timestamp=timestamp,
        sections=sections,
        raw=raw,
        excluded=f"oversized:{size}" if oversized else None,
    )


def redact(text: str, *, bulleted_ledger: bool = False) -> str:
    """Strip closeout-ledger detail that belongs in the handoff, not a reflection.

    ``bulleted_ledger`` also drops a ledger line behind a list marker. Only the
    Improvements section asks for it: in "What didn't" a bulleted ``Hosted CI:`` line
    is usually real friction.
    """
    kept = []
    for line in text.splitlines():
        head = line.strip()
        if bulleted_ledger:
            head = head.lstrip("-*+").strip()
        if head.lower().startswith(_LEDGER_PREFIXES):
            continue
        line = _URL.sub("<url>", line)
        line = _JSON_BLOB.sub("<json>", line)
        line = _ABS_PATH.sub("<path>", line)
        line = _SHA.sub("<sha>", line)
        line = _ORG_REF.sub("<ref>", line)
        kept.append(line)
    return "\n".join(kept).strip()


def classify_improvements(text: str) -> str:
    """``none`` | ``agnostic`` | ``repo_specific`` | ``missing``."""
    if not text.strip():
        return "missing"
    remainder = _NONE_LEAD.sub("", text.strip(), count=1).strip()
    if not remainder:
        return "none"
    if _ORG_REF.search(text) or _ABS_PATH.search(text) or _URL.search(text):
        return "repo_specific"
    return "agnostic"


CONTENT_KEYS = ("worked", "didnt", "improvements")
NEAR_DUPLICATE_OVERLAP = 0.8


def _note(reflection: Reflection, note: str) -> None:
    if note not in reflection.notes:
        reflection.notes.append(note)


def _is_repo_specific(text: str) -> bool:
    return bool(_ORG_REF.search(text) or _ABS_PATH.search(text) or _URL.search(text))


def _settle_boilerplate_only(reflections: list[Reflection], cap_reason: str) -> None:
    """Keep a ``boilerplate_only`` reflection only if one of its proposals recurs across branches.

    Boilerplate is single-repo by construction, so re-runs or copies on one branch are
    template noise; the same proposal from at least two branches' admitted
    reflections is recurring evidence. Repeats until stable, since dropping one
    carrier can leave another proposal on a single branch.

    A reflection that fails is archivable noise (``no_friction_or_proposal``) only
    when the line is single-branch even counting capped carriers and it dropped no
    repo-specific proposal. If the cap removed its other branches' carriers it is
    ``boilerplate_unconfirmed``, and if it dropped a repo-specific proposal it is
    ``improvements_repo_specific``; both stay in place (agent-harness#1371).
    """
    changed = True
    while changed:
        changed = False
        admitted: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        present: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        for reflection in reflections:
            # An unconfirmed copy is still a carrier: it was only displaced by the cap,
            # so it must not make the other branch's copies look single-branch.
            if reflection.excluded in (None, cap_reason, "boilerplate_unconfirmed"):
                for line in reflection.boilerplate:
                    key = (reflection.bare_skill, line)
                    branch = (reflection.repo_hash, reflection.branch_slug)
                    present[key].add(branch)
                    if reflection.excluded is None:
                        admitted[key].add(branch)
        for reflection in reflections:
            if reflection.excluded is not None or "boilerplate_only" not in reflection.notes:
                continue
            keys = [(reflection.bare_skill, line) for line in reflection.boilerplate_proposals]
            if any(len(admitted[key]) >= 2 for key in keys):
                continue
            if any(len(present[key]) >= 2 for key in keys):
                reflection.excluded = "boilerplate_unconfirmed"
            elif "section_dropped:improvements:repo_specific" in reflection.notes:
                reflection.excluded = "improvements_repo_specific"
            else:
                reflection.excluded = "no_friction_or_proposal"
                _note(reflection, "boilerplate_single_branch")
            changed = True


def _norm_line(line: str) -> str:
    return " ".join(line.strip().lstrip("-*+").split())


def _content_lines(reflection: Reflection) -> set[str]:
    if not reflection.structured:
        lines = reflection.raw.splitlines()
    else:
        lines = [line for key in CONTENT_KEYS for line in reflection.sections.get(key, "").splitlines()]
    return {norm for norm in map(_norm_line, lines) if norm}


def _mark_duplicates(reflections: list[Reflection]) -> None:
    """Collapse exact and near copies within one skill/repo/branch.

    A near-copy is a re-emitted reflection (same run re-closed) whose own content
    lines are at least ``NEAR_DUPLICATE_OVERLAP`` contained in an earlier kept one, so
    a newer reflection that adds friction to an older one is kept. Copies are never
    collapsed across repos or branches: identical reports from independent runs are
    recurring evidence, not duplicates.
    """
    kept_by_group: dict[tuple[str, str, str], list[tuple[str, set[str]]]] = defaultdict(list)
    for reflection in reflections:
        if reflection.excluded:
            continue
        lines = _content_lines(reflection)
        for kept_id, kept_lines in kept_by_group[reflection.group]:
            if lines and len(lines & kept_lines) / len(lines) >= NEAR_DUPLICATE_OVERLAP:
                reflection.excluded = f"duplicate_of:{kept_id}"
                break
        if reflection.excluded:
            continue
        kept_by_group[reflection.group].append((reflection.id, lines))


def apply_quality_filter(
    reflections: list[Reflection],
    *,
    per_branch_cap: int = DEFAULT_PER_BRANCH_CAP,
    boilerplate_min: int = DEFAULT_BOILERPLATE_MIN,
) -> list[str]:
    """Mark exclusions in place and strip boilerplate; returns the boilerplate lines removed.

    Order matters. Duplicates collapse first so one copied reflection cannot make
    its own lines look like cross-run boilerplate. Boilerplate is stripped before
    the ``Improvements`` gate so a copied repo-specific line does not reject an
    otherwise repo-agnostic proposal, and the per-branch cap runs last so it keeps
    the newest *usable* reflections.

    A repo-specific ``Improvements`` section, or a repo-specific proposal line
    stripped as boilerplate, is dropped on its own; the reflection's friction is still
    admitted (agent-harness#1371). A reflection whose only proposal is a repo-agnostic
    line stripped as boilerplate is admitted as ``boilerplate_only`` when that line
    recurs on at least two branches, so a proposal independent runs repeat counts
    toward readiness (agent-harness#1370). A copied friction, ledger or single-branch
    template line does not keep a reflection.
    """
    _mark_duplicates(reflections)

    # Boilerplate is a line one repo's runs of one skill keep re-emitting (a copied
    # ledger or template line). The same line from several repos is recurring
    # evidence and stays; one skill's copies never count toward another's.
    line_counts: Counter[tuple[str, str]] = Counter()
    line_repos: dict[tuple[str, str], set[str]] = defaultdict(set)
    for reflection in reflections:
        if not reflection.excluded:
            for line in _content_lines(reflection):
                if len(line) >= BOILERPLATE_MIN_CHARS:
                    line_counts[(reflection.bare_skill, line)] += 1
                    line_repos[(reflection.bare_skill, line)].add(reflection.repo_hash)
    boilerplate_by_skill: dict[str, set[str]] = defaultdict(set)
    for (skill, line), count in line_counts.items():
        if count >= boilerplate_min and len(line_repos[(skill, line)]) == 1:
            boilerplate_by_skill[skill].add(line)

    for reflection in reflections:
        if reflection.excluded:
            continue
        boilerplate = boilerplate_by_skill.get(reflection.bare_skill, set())
        dropped_repo_specific = False
        for key in CONTENT_KEYS:
            if key not in reflection.sections:
                continue
            original = reflection.sections[key].splitlines()
            kept = [line for line in original if _norm_line(line) not in boilerplate]
            if len(kept) != len(original):
                reflection.notes.append(f"boilerplate_stripped:{key}:{len(original) - len(kept)}")
            for line in sorted({_norm_line(line) for line in original} & boilerplate):
                if key == "improvements" and _is_repo_specific(line):
                    dropped_repo_specific = True
                    continue
                # A ledger line redacts to nothing: neither evidence nor a proposal.
                if not redact(line):
                    continue
                if line not in reflection.boilerplate:
                    reflection.boilerplate.append(line)
                if key == "improvements" and classify_improvements(redact(line)) == "agnostic":
                    reflection.boilerplate_proposals.append(line)
            reflection.sections[key] = "\n".join(kept).strip()
        reflection.improvements_class = classify_improvements(reflection.sections.get("improvements", ""))
        if reflection.improvements_class == "repo_specific":
            # Kept as an empty section so the reflection stays structured.
            reflection.sections["improvements"] = ""
            dropped_repo_specific = True
        if dropped_repo_specific:
            _note(reflection, "section_dropped:improvements:repo_specific")
        for key in CONTENT_KEYS:
            if key in reflection.sections:
                reflection.sections[key] = redact(reflection.sections[key], bulleted_ledger=key == "improvements")
        if reflection.structured and not reflection.sections.get("didnt") and reflection.improvements_class != "agnostic":
            if reflection.boilerplate_proposals:
                reflection.notes.append("boilerplate_only")
            elif dropped_repo_specific:
                # Its proposal was dropped, not absent, so it is not consumed.
                reflection.excluded = "improvements_repo_specific"
            else:
                reflection.excluded = "no_friction_or_proposal"

    # The cap and the boilerplate_only settlement depend on each other: the cap can
    # drop a line's other carriers, and a settled exclusion frees a cap slot. Each
    # round re-caps from scratch after settling; settled exclusions only grow, so the
    # rounds stop once a round settles nothing new.
    cap_reason = f"per_branch_cap:{per_branch_cap}"
    while True:
        for reflection in reflections:
            if reflection.excluded == cap_reason:
                reflection.excluded = None
        _settle_boilerplate_only(reflections, cap_reason)
        settled = [r.excluded for r in reflections]
        groups: dict[tuple[str, str, str], list[Reflection]] = defaultdict(list)
        for reflection in reflections:
            if not reflection.excluded:
                groups[reflection.group].append(reflection)
        for members in groups.values():
            members.sort(key=lambda r: (r.timestamp, r.run_id), reverse=True)
            for reflection in members[per_branch_cap:]:
                reflection.excluded = cap_reason
        _settle_boilerplate_only(reflections, cap_reason)
        if all(after == before or after == cap_reason for before, after in zip(settled, (r.excluded for r in reflections))):
            break
    return sorted(set().union(*boilerplate_by_skill.values()))


def collect(
    roots: Sequence[Path] | None = None,
    *,
    min_reflections: int = 2,
    per_branch_cap: int = DEFAULT_PER_BRANCH_CAP,
    boilerplate_min: int = DEFAULT_BOILERPLATE_MIN,
) -> tuple[Corpus, list[str]]:
    roots = [Path(root).expanduser() for root in (roots if roots is not None else default_roots())]
    scanned: list[Reflection] = []
    out_of_scope: list[Path] = []
    for root in roots:
        # A symlinked file, or one whose real location leaves its reflections dir, is
        # never read; it counts as out of scope.
        for skill, path in iter_reflection_paths(root, skipped=out_of_scope):
            reflection = read_reflection(root, skill, path)
            if reflection is None or reflection.bare_skill not in IN_SCOPE_SKILLS:
                out_of_scope.append(path)
                continue
            if not _within(path.resolve(), root.resolve()):
                reflection.in_root = False
                reflection.notes.append("outside_root:not_archivable")
            scanned.append(reflection)
    scanned.sort(key=lambda r: (r.bare_skill, r.skill, r.repo_hash, r.branch_slug, r.timestamp, str(r.path)))
    for index, reflection in enumerate(scanned, start=1):
        reflection.id = f"R{index:04d}"
    boilerplate = apply_quality_filter(scanned, per_branch_cap=per_branch_cap, boilerplate_min=boilerplate_min)
    return Corpus(roots=roots, scanned=scanned, out_of_scope=out_of_scope, min_reflections=min_reflections), boilerplate


def inventory(corpus: Corpus) -> dict[str, object]:
    by_root: list[dict[str, object]] = []
    for root in corpus.roots:
        count = sum(1 for r in corpus.scanned if r.root == root)
        by_root.append({"root": str(root), "count": count})
    exclusions = Counter((r.excluded or "").split(":")[0] for r in corpus.scanned if r.excluded)
    return {
        "total": len(corpus.scanned),
        "admitted": len(corpus.admitted),
        "roots": by_root,
        "by_skill": {skill: len(items) for skill, items in corpus.admitted_by_skill().items()},
        "excluded": dict(sorted(exclusions.items())),
        "out_of_scope": len(corpus.out_of_scope),
        "min_reflections": corpus.min_reflections,
        "ready_skills": corpus.ready_skills(),
        "due": corpus.due,
    }


_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?[ \t]*$")
_FENCE_LINE = re.compile(r"^ {0,3}(?:`{3,}|~{3,})")


def quote_body(text: str) -> str:
    """Reflection text as inert bundle content: it cannot open a heading or a fence.

    A heading line (up to three leading spaces) is demoted to bold text, and a line
    that would open a code fence is indented so it is literal text, so one entry can
    neither forge another entry's header nor swallow the entries after it.
    """
    lines = []
    for line in text.split("\n"):
        heading = _HEADING_LINE.match(line)
        if heading:
            line = f"**{heading.group(1)}**" if heading.group(1) else ""
        elif _FENCE_LINE.match(line):
            line = "    " + line
        lines.append(line)
    return "\n".join(lines)


def _header_field(value: str) -> str:
    """One inert line: a file name can carry any line separator, so collapse all whitespace."""
    return quote_body(" ".join(redact_text(value).split()))


def _cap_line(text: str) -> str:
    return text[:MAX_RECURRING_LINE_CHARS].rstrip() + "…" if len(text) > MAX_RECURRING_LINE_CHARS else text


def _recurring_item(line: str, ids: list[str]) -> dict[str, object]:
    """One recurring line, redacted, on one inert line, with its text and ids capped."""
    return {
        "line": _cap_line(_header_field(redact(line))),
        "count": len(ids),
        "reflections": ids[:MAX_RECURRING_IDS],
        "reflections_omitted": max(0, len(ids) - MAX_RECURRING_IDS),
    }


def _id_list(item: dict[str, object]) -> str:
    listed = ", ".join(item["reflections"])  # type: ignore[arg-type]
    return f"{listed}, +{item['reflections_omitted']} more" if item["reflections_omitted"] else listed


def render_bundle(corpus: Corpus) -> str:
    """The aggregator's input: admitted reflections grouped by bare skill.

    Every reflection-derived string passes the shared credential redaction first,
    then ``quote_body``; entry-header fields are also forced onto one line.
    """
    lines = ["# Reflections to aggregate", "", f"min_reflections: {corpus.min_reflections}", ""]
    note = "_Every line of this entry recurs across runs; see the recurring lines list below._"
    labels = (("worked", "What worked"), ("didnt", "What didn't"), ("improvements", "Improvements to SKILL.md"))
    for skill, items in corpus.admitted_by_skill().items():
        lines += [f"## {skill} ({len(items)} reflections)", ""]
        for reflection in items:
            lines.append(f"### {reflection.id} — {_header_field(reflection.skill)} — {_header_field(reflection.timestamp)}")
            if reflection.structured:
                bodies = [(label, reflection.sections.get(key, "")) for key, label in labels]
                for label, body in bodies:
                    if body:
                        lines += [f"**{label}**", quote_body(redact_text(body)), ""]
                if not any(body for _, body in bodies):
                    lines += [note, ""]
            else:
                lines += ["**unstructured**", quote_body(redact_text(redact(reflection.raw))), ""]
        carriers = corpus.boilerplate_carriers(skill)
        if carriers:
            # Stripped from the entries above; one line each, with how many admitted
            # reflections carried it (agent-harness#1370). A bold label, not a heading:
            # every ``###`` heading in a skill section is a reflection entry.
            lines += ["**Recurring lines** (stripped from the entries above; not a reflection)", ""]
            for line, ids in carriers.items():
                item = _recurring_item(line, ids)
                lines.append(f"- {item['count']} reflections ({_id_list(item)}): {item['line']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# Exclusions whose reflection carries no evidence a later pass could use.
ARCHIVABLE_EXCLUSIONS = ("duplicate_of", "no_friction_or_proposal")


def consumed(corpus: Corpus) -> list[Reflection]:
    """Reflections this pass uses up, so the editor may archive them.

    That is the admitted reflections of ready skills (they feed the plan), plus, for
    any skill, reflections excluded as a duplicate or as having no friction and no
    proposal. Every other reflection stays in place: admitted ones of a skill below
    the threshold so evidence can accumulate, and the rest of the excluded ones
    (a dropped repo-specific proposal with no friction, per-branch cap, a recurring
    proposal the cap left unconfirmed, oversized) because they may still be evidence
    (agent-harness#1371). A reflection whose real location leaves its scan root is
    never consumed, because ``archive`` would refuse it.
    """
    ready = set(corpus.ready_skills())
    return [
        r for r in corpus.scanned
        if r.in_root
        and ((r.excluded is None and r.bare_skill in ready) or (r.excluded or "").split(":")[0] in ARCHIVABLE_EXCLUSIONS)
    ]


def manifest(corpus: Corpus, boilerplate: list[str]) -> dict[str, object]:
    return {
        "inventory": inventory(corpus),
        # The planner reads this file too, so stripped lines get the same redaction.
        "boilerplate_lines_stripped": [_cap_line(redact_text(redact(line))) for line in boilerplate],
        "boilerplate_carriers": [
            {"skill": skill, **_recurring_item(line, ids)}
            for skill in corpus.admitted_by_skill()
            for line, ids in corpus.boilerplate_carriers(skill).items()
        ],
        "reflections_consumed": [str(r.path) for r in consumed(corpus)],
        "reflections": [
            {
                "id": r.id,
                "path": str(r.path),
                "skill": r.skill,
                "bare_skill": r.bare_skill,
                "repo_hash": r.repo_hash,
                "branch_slug": r.branch_slug,
                "improvements": r.improvements_class,
                "excluded": r.excluded,
                "notes": r.notes,
            }
            for r in corpus.scanned
        ],
    }


def write_corpus(corpus: Corpus, boilerplate: list[str], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / "bundle.md"
    manifest_path = out_dir / "manifest.json"
    bundle.write_text(render_bundle(corpus), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest(corpus, boilerplate), indent=2) + "\n", encoding="utf-8")
    return {"bundle": bundle, "manifest": manifest_path}


def archive_target(path: Path) -> Path:
    parts = path.parts
    if "reflections" not in parts or "archive" in parts[parts.index("reflections"):]:
        raise ValueError(f"not an unarchived reflection: {path}")
    return path.parent / "archive" / path.name


def _archivable(path: Path, roots: Sequence[Path]) -> bool:
    """``path`` is an unarchived ``<root>/<harness>-<skill>/reflections/**.md`` for one of ``roots``.

    The skill must be one the loop covers. The path is never a symlink, and its real
    location stays inside both that skill's reflections dir and the resolved root, so
    a symlinked skill or reflections dir cannot carry the move outside the root.
    """
    if path.suffix != ".md" or path.is_symlink():
        return False
    for root in roots:
        try:
            rel = path.relative_to(root).parts
        except ValueError:
            continue
        split = split_skill(rel[0]) if rel else None
        if len(rel) < 3 or split is None or split[1] not in IN_SCOPE_SKILLS or rel[1] != "reflections" or "archive" in rel[2:]:
            continue
        if not path.exists():
            return True
        real = path.resolve()
        if _within(real, (root / rel[0] / "reflections").resolve()) and _within(real, root.resolve()):
            return True
    return False


def archive(
    paths: Iterable[Path], *, roots: Sequence[Path] | None = None, dry_run: bool = False
) -> list[tuple[Path, Path]]:
    """Move consumed reflections to a sibling ``archive/`` (same repo/branch subtree).

    Every path must lie under ``default_roots()`` or one of ``roots`` (never a root
    named by the manifest being archived). All paths are checked before anything
    moves, so one out-of-root path moves nothing and raises ``ValueError``. A path
    that no longer exists (already archived) is skipped.
    """
    allowed = [Path(os.path.abspath(Path(root).expanduser())) for root in [*default_roots(), *(roots or [])]]
    candidates = [Path(os.path.abspath(Path(path).expanduser())) for path in paths]
    refused = [path for path in candidates if not _archivable(path, allowed)]
    if refused:
        raise ValueError(f"refusing to archive {len(refused)} path(s) outside every skill reflections root: {refused[0]}")
    moves = []
    for path in candidates:
        if not path.is_file():
            continue
        target = path.parent / "archive" / path.name
        if target.parent.is_symlink():
            raise ValueError(f"archive directory is a symlink: {target.parent}")
        if target.exists():
            raise FileExistsError(f"archive target already exists: {target}")
        moves.append((path, target))
    if not dry_run:
        for source, target in moves:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    return moves


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m phase_loop_runtime.reflection_corpus")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_cmd = sub.add_parser("collect", help="Enumerate, parse and filter reflections; write bundle.md + manifest.json.")
    collect_cmd.add_argument("--root", action="append", type=Path, help="Skill root to scan (repeatable). Default: every harness root.")
    collect_cmd.add_argument("--out-dir", type=Path)
    collect_cmd.add_argument("--min-reflections", type=int, default=2)
    collect_cmd.add_argument("--per-branch-cap", type=int, default=DEFAULT_PER_BRANCH_CAP)
    collect_cmd.add_argument("--boilerplate-min", type=int, default=DEFAULT_BOILERPLATE_MIN)
    archive_cmd = sub.add_parser("archive", help="Archive every path in a manifest's reflections_consumed.")
    archive_cmd.add_argument("--manifest", type=Path, required=True)
    archive_cmd.add_argument(
        "--root", action="append", type=Path, default=[],
        help="Extra skill root the consumed paths may live under (repeatable). Every harness root and PHASE_LOOP_SKILL_BUNDLE are always allowed.",
    )
    archive_cmd.add_argument("--exclude", type=Path, action="append", default=[], help="Leave this consumed path in place (its recommendation failed).")
    archive_cmd.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "collect":
        corpus, boilerplate = collect(
            args.root,
            min_reflections=args.min_reflections,
            per_branch_cap=args.per_branch_cap,
            boilerplate_min=args.boilerplate_min,
        )
        summary: dict[str, object] = inventory(corpus)
        if args.out_dir:
            summary["artifacts"] = {key: str(path) for key, path in write_corpus(corpus, boilerplate, args.out_dir).items()}
        print(json.dumps(summary, indent=2))
        return 0

    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    consumed_paths = [Path(p) for p in data.get("reflections_consumed", [])]
    excludes = {path.resolve() for path in args.exclude}
    unmatched = excludes - {path.resolve() for path in consumed_paths}
    if unmatched:
        print(json.dumps({"error": "--exclude matches no consumed reflection", "paths": sorted(map(str, unmatched))}), file=sys.stderr)
        return 1
    paths = [path for path in consumed_paths if path.resolve() not in excludes]
    try:
        moves = archive(paths, roots=args.root, dry_run=args.dry_run)
    except (ValueError, FileExistsError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    left = len(consumed_paths) - len(paths)
    print(json.dumps({"dry_run": args.dry_run, "archived": len(moves), "left_in_place": left}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
