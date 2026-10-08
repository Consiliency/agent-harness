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
    python3 -m phase_loop_runtime.reflection_corpus archive --manifest DIR/manifest.json [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .skill_paths import HARNESS_DEFAULT_SKILL_ROOTS

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
DEFAULT_BOILERPLATE_MIN = 3
BOILERPLATE_MIN_CHARS = 40

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

    def ready_skills(self) -> list[str]:
        return [skill for skill, items in self.admitted_by_skill().items() if len(items) >= self.min_reflections]

    @property
    def due(self) -> bool:
        return bool(self.ready_skills())


def default_roots() -> list[Path]:
    """Every harness's installed skill root; reflections land in more than one."""
    return [root.expanduser() for root in HARNESS_DEFAULT_SKILL_ROOTS.values()]


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


def iter_reflection_paths(root: Path) -> Iterable[tuple[str, Path]]:
    if not root.is_dir():
        return
    for reflections in sorted(root.glob("*/reflections")):
        for path in sorted(reflections.rglob("*.md")):
            if path.is_file() and "archive" not in path.relative_to(reflections).parts:
                yield reflections.parent.name, path


def read_reflection(root: Path, skill: str, path: Path) -> Reflection | None:
    split = split_skill(skill)
    if split is None:
        return None
    harness, bare = split
    rel = path.relative_to(root / skill / "reflections").parts
    repo_hash = rel[0] if len(rel) >= 3 else ""
    branch_slug = "/".join(rel[1:-1]) if len(rel) >= 3 else ""
    raw = path.read_text(encoding="utf-8", errors="replace")
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
    )


def redact(text: str) -> str:
    """Strip closeout-ledger detail that belongs in the handoff, not a reflection."""
    kept = []
    for line in text.splitlines():
        if line.strip().lower().startswith(_LEDGER_PREFIXES):
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


def _norm_line(line: str) -> str:
    return " ".join(line.strip().lstrip("-*").split())


def _content_lines(reflection: Reflection) -> set[str]:
    if not reflection.structured:
        lines = reflection.raw.splitlines()
    else:
        lines = [line for key in CONTENT_KEYS for line in reflection.sections.get(key, "").splitlines()]
    return {norm for norm in map(_norm_line, lines) if norm}


def _mark_duplicates(reflections: list[Reflection]) -> None:
    """Collapse exact copies corpus-wide and near-copies within one repo/branch.

    A near-copy is a re-emitted reflection (same run re-closed) whose content lines
    are at least ``NEAR_DUPLICATE_OVERLAP`` contained in an earlier kept one.
    """
    exact: dict[str, str] = {}
    kept_by_group: dict[tuple[str, str, str], list[tuple[str, set[str]]]] = defaultdict(list)
    for reflection in reflections:
        lines = _content_lines(reflection)
        key = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()
        if key in exact:
            reflection.excluded = f"duplicate_of:{exact[key]}"
            continue
        for kept_id, kept_lines in kept_by_group[reflection.group]:
            smaller = min(len(lines), len(kept_lines))
            if smaller and len(lines & kept_lines) / smaller >= NEAR_DUPLICATE_OVERLAP:
                reflection.excluded = f"duplicate_of:{kept_id}"
                break
        if reflection.excluded:
            continue
        exact[key] = reflection.id
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
    """
    _mark_duplicates(reflections)

    line_counts: Counter[str] = Counter()
    for reflection in reflections:
        if not reflection.excluded:
            line_counts.update(line for line in _content_lines(reflection) if len(line) >= BOILERPLATE_MIN_CHARS)
    boilerplate = {line for line, count in line_counts.items() if count >= boilerplate_min}

    for reflection in reflections:
        if reflection.excluded:
            continue
        for key in CONTENT_KEYS:
            if key not in reflection.sections:
                continue
            original = reflection.sections[key].splitlines()
            kept = [line for line in original if _norm_line(line) not in boilerplate]
            if len(kept) != len(original):
                reflection.notes.append(f"boilerplate_stripped:{key}:{len(original) - len(kept)}")
            reflection.sections[key] = "\n".join(kept).strip()
        reflection.improvements_class = classify_improvements(reflection.sections.get("improvements", ""))
        if reflection.improvements_class == "repo_specific":
            reflection.excluded = "improvements_repo_specific"
            continue
        for key in CONTENT_KEYS:
            if key in reflection.sections:
                reflection.sections[key] = redact(reflection.sections[key])
        if reflection.structured and not reflection.sections.get("didnt") and reflection.improvements_class in {"none", "missing"}:
            reflection.excluded = "no_friction_or_proposal"

    groups: dict[tuple[str, str, str], list[Reflection]] = defaultdict(list)
    for reflection in reflections:
        if not reflection.excluded:
            groups[reflection.group].append(reflection)
    for members in groups.values():
        members.sort(key=lambda r: (r.timestamp, r.run_id), reverse=True)
        for reflection in members[per_branch_cap:]:
            reflection.excluded = f"per_branch_cap:{per_branch_cap}"
    return sorted(boilerplate)


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
        for skill, path in iter_reflection_paths(root):
            reflection = read_reflection(root, skill, path)
            if reflection is None or reflection.bare_skill not in IN_SCOPE_SKILLS:
                out_of_scope.append(path)
                continue
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


def render_bundle(corpus: Corpus) -> str:
    """The aggregator's input: admitted reflections grouped by bare skill."""
    lines = ["# Reflections to aggregate", "", f"min_reflections: {corpus.min_reflections}", ""]
    labels = (("worked", "What worked"), ("didnt", "What didn't"), ("improvements", "Improvements to SKILL.md"))
    for skill, items in corpus.admitted_by_skill().items():
        lines += [f"## {skill} ({len(items)} reflections)", ""]
        for reflection in items:
            lines.append(f"### {reflection.id} — {reflection.skill} — {reflection.timestamp}")
            if reflection.structured:
                for key, label in labels:
                    body = reflection.sections.get(key, "")
                    if body:
                        lines += [f"**{label}**", body, ""]
            else:
                # Demote the raw body's own headings so they cannot open a bundle section.
                body = re.sub(r"^#+\s+(.*)$", r"**\1**", redact(reflection.raw), flags=re.MULTILINE)
                lines += ["**unstructured**", body, ""]
    return "\n".join(lines).rstrip() + "\n"


def manifest(corpus: Corpus, boilerplate: list[str]) -> dict[str, object]:
    return {
        "inventory": inventory(corpus),
        "boilerplate_lines_stripped": boilerplate,
        # Every scanned reflection is consumed: admitted ones feed the plan, excluded
        # ones would be excluded again next pass, so leaving them would never drain.
        "reflections_consumed": [str(r.path) for r in corpus.scanned],
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


def archive(paths: Iterable[Path], *, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """Move consumed reflections to a sibling ``archive/`` (same repo/branch subtree)."""
    moves = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        target = archive_target(path)
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
    archive_cmd.add_argument("--exclude", type=Path, action="append", default=[], help="Leave this path in place (its recommendation failed).")
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
    skip = {str(path) for path in args.exclude}
    paths = [Path(p) for p in data.get("reflections_consumed", []) if p not in skip]
    moves = archive(paths, dry_run=args.dry_run)
    print(json.dumps({"dry_run": args.dry_run, "archived": len(moves), "left_in_place": len(skip)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
