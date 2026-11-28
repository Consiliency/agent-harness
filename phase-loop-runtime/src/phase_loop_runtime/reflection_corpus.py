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
        (writes DIR/bundle.md, DIR/manifest.json and DIR/rule_enforcement.md)
    python3 -m phase_loop_runtime.reflection_corpus archive --manifest DIR/manifest.json [--root R ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .credential_redaction import redact_text
from .rule_enforcement import Rule, load_registry
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
# agent-harness#1661 (carried from agent-harness#1622 r3): bound each manifest
# boilerplate_lines_stripped item to 500 characters plus an ellipsis.
MAX_MANIFEST_BOILERPLATE_LINE_CHARS = 500

# Deliberately broad: bare `repo#N` refs are how this fleet names issues, so an
# occasional false hit (`step#3`) is the cheaper error than leaking a real ref.
_ORG_REF = re.compile(r"\b[\w.-]+/[\w.-]+#\d+\b|\b[a-z][\w.-]*#\d+\b")
_ABS_PATH = re.compile(r"(?<![\w.])(?:~|/(?:home|mnt|tmp|Users|var|opt|srv|workspace))/[^\s,;)\]`'\"<]+(?![^\s]*<)")
_URL = re.compile(r"https?://\S+")
_SHA = re.compile(r"\b[0-9a-f]{40}\b")
_JSON_BLOB = re.compile(r"\{\".*\}")
_LEDGER_PREFIXES = ("publication result:", "hosted ci:", "lifecycle warning:")
_NONE_LEAD = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])?\s*(?:none(?: required| proposed| needed)?|no (?:skill )?(?:edits?|changes?|improvements?)(?: (?:are |is )?(?:proposed|required|needed))?|n/?a)\b[.:;,]?\s*",
    re.IGNORECASE,
)
_LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>(?:[-*+]|\d+[.)]))(?:\s+|$)")
_FENCE_OPEN_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_THEMATIC_BREAK_RE = re.compile(r"^[ \t]*(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}(?:\s|$)")
_SETEXT_UNDERLINE_RE = re.compile(r"^[ \t]{0,3}(?:=+|-+)[ \t]*$")
_ANY_SETEXT_UNDERLINE_RE = re.compile(r"^[ \t]*(?:=+|-+)[ \t]*$")
_PLACEHOLDER_ONLY_RE = re.compile(r"^(?:<(?:sha|json|url|path|ref)>|[\s.,;:!?()\[\]{}`\"'/-])*$")


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

    def ready_skills(self) -> list[str]:
        return [skill for skill, items in self.admitted_by_skill().items() if len(items) >= self.min_reflections]

    @property
    def due(self) -> bool:
        return bool(self.ready_skills())


def _configured_default_roots() -> list[Path]:
    roots = [root.expanduser() for root in HARNESS_DEFAULT_SKILL_ROOTS.values()]
    if os.environ.get("PHASE_LOOP_SKILL_BUNDLE"):
        override = resolve_skill_bundle_root()
        if override not in roots:
            roots.append(override)
    return roots


def _root_key(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(path))


def _dedup_roots(roots: Iterable[Path]) -> list[Path]:
    """Deduplicate scan roots by resolved canonical path, preserving first-seen order.

    When two paths collide on the same resolved key (for example
    ``parent/missing/../skills`` followed by ``parent/skills``), prefer a
    traversable directory over an unusable path so a non-existent alias cannot
    suppress a valid scan root.
    """
    deduped: list[Path] = []
    index_by_key: dict[Path, int] = {}
    for raw in roots:
        expanded = Path(raw).expanduser()
        key = _root_key(expanded)
        existing = index_by_key.get(key)
        if existing is not None:
            if not deduped[existing].is_dir() and expanded.is_dir():
                deduped[existing] = expanded
            continue
        index_by_key[key] = len(deduped)
        deduped.append(expanded)
    return deduped


def default_roots() -> list[Path]:
    """Every harness's installed skill root; reflections land in more than one.

    A ``PHASE_LOOP_SKILL_BUNDLE`` override is where writers put reflections, so it
    is scanned too. Roots that resolve to the same directory are deduplicated so an
    aliased root is never scanned twice (agent-harness#1657).
    """
    return _dedup_roots(_configured_default_roots())


def split_skill(skill: str) -> tuple[str, str] | None:
    for prefix in HARNESS_PREFIXES:
        if skill.startswith(prefix + "-"):
            bare = skill[len(prefix) + 1:]
            return prefix, SKILL_ALIASES.get(bare, bare)
    return None


def _strip_blank_edges(lines: Sequence[str]) -> str:
    """Drop leading/trailing blank lines while preserving first-line indentation."""
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = len(lines)
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end]).rstrip()


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    # (fence_char, fence_len, min_indent_or_None): track fences across the entire
    # document (including preamble and unknown `##` sections) so fenced examples
    # cannot inject fake headings, while bounding list-contained fences to their
    # enclosing list item's content column so unclosed list fences close on dedent.
    open_fence: tuple[str, int, int | None] | None = None
    list_indents: list[int] = []
    saw_blank = False
    for line in text.splitlines():
        if open_fence is not None:
            char, length, min_indent = open_fence
            if min_indent is not None and line.strip() and _indent_width(line) < min_indent:
                open_fence = None
                cur_indent = _indent_width(line)
                while list_indents and cur_indent < list_indents[-1]:
                    list_indents.pop()
            else:
                if current is not None:
                    sections[current].append(line)
                close_min = min_indent or 0
                if _fence_close(line, char, length, min_indent=close_min, max_indent=close_min + 3):
                    open_fence = None
                continue
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            key = SECTION_KEYS.get(heading.group(1).strip().lower())
            # An unknown second-level heading ends the current section; trailing
            # ledger/successor sections are not reflection content.
            current = key
            list_indents.clear()
            saw_blank = False
            if key is not None:
                sections.setdefault(key, [])
            continue
        if current is not None:
            sections[current].append(line)
        if not line.strip():
            saw_blank = True
            continue
        cur_indent = _indent_width(line)
        if saw_blank:
            while list_indents and cur_indent < list_indents[-1]:
                list_indents.pop()
        saw_blank = False
        item_indent = _list_item_content_indent(line)
        if item_indent is not None:
            while list_indents and cur_indent < list_indents[-1]:
                list_indents.pop()
            list_indents.append(item_indent)
            inline_fence = _fence_open_after_list_marker(line)
            if inline_fence is not None:
                open_fence = (inline_fence[0], inline_fence[1], list_indents[-1])
            continue
        active_indent = list_indents[-1] if list_indents else None
        if active_indent is not None and cur_indent >= active_indent:
            opener = _fence_open(line, min_indent=active_indent, max_indent=active_indent + 3)
            if opener is not None:
                open_fence = (opener[0], opener[1], active_indent)
        else:
            opener = _fence_open(line, min_indent=0, max_indent=3)
            if opener is not None:
                open_fence = (opener[0], opener[1], None)
    return {key: _strip_blank_edges(lines) for key, lines in sections.items()}


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


def redact(text: str, *, drop_ledger: bool = True, bulleted_ledger: bool = False) -> str:
    """Redact ledger detail; friction keeps ledger-labelled observations."""
    kept = []
    for line in text.splitlines():
        head = line.strip()
        if bulleted_ledger:
            head = re.sub(r"^[-*+]\s+", "", head)
        if drop_ledger and head.lower().startswith(_LEDGER_PREFIXES):
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


def _indent_width(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _list_item_content_indent(line: str) -> int | None:
    """CommonMark content column for a list item, or ``None`` if not a list item."""
    if _THEMATIC_BREAK_RE.match(line):
        return None
    expanded = line.expandtabs(4)
    match = _LIST_ITEM_RE.match(expanded)
    if match is None:
        return None
    marker_end = len(match.group("indent")) + len(match.group("marker"))
    rest = expanded[marker_end:]
    if not rest.strip():
        return marker_end + 1
    spaces = len(rest) - len(rest.lstrip(" "))
    return marker_end + (1 if spaces >= 5 else spaces)


def _fence_open(
    line: str, *, min_indent: int = 0, max_indent: int = 3
) -> tuple[str, int] | None:
    indent = _indent_width(line)
    if indent < min_indent or indent > max_indent:
        return None
    match = _FENCE_OPEN_RE.match(line)
    if not match:
        return None
    fence = match.group("fence")
    info = match.group("info")
    # CommonMark: backtick fence info strings cannot contain backticks.
    if fence[0] == "`" and "`" in info:
        return None
    return fence[0], len(fence)


def _fence_open_after_list_marker(line: str) -> tuple[str, int] | None:
    """Detect a fence opener directly after a list marker (``- ```sh``), respecting CommonMark's 4-space code rule."""
    if _THEMATIC_BREAK_RE.match(line):
        return None
    expanded = line.expandtabs(4)
    match = _LIST_ITEM_RE.match(expanded)
    if match is None:
        return None
    marker_end = len(match.group("indent")) + len(match.group("marker"))
    rest = expanded[marker_end:]
    if not rest.strip():
        return None
    spaces = len(rest) - len(rest.lstrip(" "))
    # 1 space separates the marker from item content; up to 3 more spaces are
    # allowed before a fence opener (5+ spaces is an indented code block).
    if spaces > 4:
        return None
    return _fence_open(rest.lstrip(" "), min_indent=0, max_indent=0)


def _fence_open_or_list_fence(
    line: str, *, min_indent: int = 0, max_indent: int = 3
) -> tuple[str, int] | None:
    """Detect a fence opener on ``line`` itself or right after a list marker (``- ```sh``)."""
    opener = _fence_open(line, min_indent=min_indent, max_indent=max_indent)
    if opener is not None:
        return opener
    return _fence_open_after_list_marker(line)


def _fence_close(
    line: str, char: str, length: int, *, min_indent: int = 0, max_indent: int = 3
) -> bool:
    indent = _indent_width(line)
    if indent < min_indent or indent > max_indent:
        return False
    stripped = line.strip()
    return len(stripped) >= length and set(stripped) == {char}


def _consume_fence(
    lines: Sequence[str],
    start: int,
    opener: tuple[str, int] | None = None,
    *,
    min_indent: int | None = None,
) -> tuple[list[str], int]:
    resolved = opener if opener is not None else _fence_open_or_list_fence(lines[start])
    assert resolved is not None
    char, length = resolved
    close_min = min_indent or 0
    block = [lines[start]]
    idx = start + 1
    while idx < len(lines):
        cur = lines[idx]
        if min_indent is not None and cur.strip() and _indent_width(cur) < min_indent:
            return block, idx
        block.append(cur)
        if _fence_close(cur, char, length, min_indent=close_min, max_indent=close_min + 3):
            return block, idx + 1
        idx += 1
    return block, idx


def _split_improvement_units(text: str) -> list[list[str]]:
    """Group ``Improvements`` lines into atomic Markdown proposal units.

    List items use CommonMark content indentation (not marker indentation) to
    distinguish sibling items from nested sub-items and continuation paragraphs,
    and keep lazy continuations and fenced blocks (including ``- ```...``)
    atomic and bounded to their containing list item so dropping a repo-specific
    entry never leaks fragments or swallows a generic sibling (agent-harness#1654).
    """
    lines = text.splitlines()
    units: list[list[str]] = []
    idx = 0
    no_setext_before = 0
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            units.append([line])
            idx += 1
            continue
        top_fence = _fence_open(line, min_indent=0, max_indent=3)
        if top_fence is not None:
            block, idx = _consume_fence(lines, idx, top_fence)
            units.append(block)
            continue
        content_indent = _list_item_content_indent(line)
        if content_indent is not None:
            inline_fence = _fence_open_after_list_marker(line)
            if inline_fence is not None:
                item, idx = _consume_fence(lines, idx, inline_fence, min_indent=content_indent)
            else:
                item = [line]
                idx += 1
            while idx < len(lines):
                cur = lines[idx]
                if not cur.strip():
                    # Look ahead past blank lines: a line indented to at least
                    # the item's content column continues this list item.
                    look = idx
                    while look < len(lines) and not lines[look].strip():
                        look += 1
                    if look < len(lines) and _indent_width(lines[look]) >= content_indent:
                        item.extend(lines[idx:look])
                        idx = look
                        continue
                    break
                cur_indent = _indent_width(cur)
                if cur_indent >= content_indent:
                    cur_fence = _fence_open(cur, min_indent=content_indent, max_indent=content_indent + 3)
                    if cur_fence is not None:
                        block, idx = _consume_fence(lines, idx, cur_fence, min_indent=content_indent)
                        item.extend(block)
                        continue
                else:
                    if _fence_open(cur, min_indent=0, max_indent=3) is not None:
                        break
                    if _HEADING_RE.match(cur) or _THEMATIC_BREAK_RE.match(cur):
                        break
                if _list_item_content_indent(cur) is not None:
                    if cur_indent < content_indent:
                        break
                    nested_fence = _fence_open_after_list_marker(cur)
                    if nested_fence is not None:
                        block, idx = _consume_fence(lines, idx, nested_fence, min_indent=content_indent)
                        item.extend(block)
                        continue
                # Either indented content (>= content_indent) or a CommonMark lazy
                # continuation line directly following the item with no blank line.
                item.append(cur)
                idx += 1
            units.append(item)
            continue
        # Plain (non-bullet, non-fence) line: recognize a single- or multi-line
        # Setext heading (contiguous plain paragraph immediately followed by
        # `===` / `---`), otherwise keep strictly more-indented continuations
        # attached while keeping same-indent sibling lines separate.
        base_indent = _indent_width(line)
        if (
            idx >= no_setext_before
            and base_indent <= 3
            and not _THEMATIC_BREAK_RE.match(line)
            and not _HEADING_RE.match(line)
            and not _SETEXT_UNDERLINE_RE.match(line)
        ):
            look = idx + 1
            while look < len(lines) and lines[look].strip():
                cand = lines[look]
                if _SETEXT_UNDERLINE_RE.match(cand):
                    units.append(list(lines[idx : look + 1]))
                    idx = look + 1
                    break
                if (
                    _fence_open(cand, min_indent=0, max_indent=3) is not None
                    or _HEADING_RE.match(cand)
                    or _THEMATIC_BREAK_RE.match(cand)
                    or _list_item_content_indent(cand) is not None
                ):
                    break
                look += 1
            if idx == look + 1:
                continue
            no_setext_before = look
        item = [line]
        idx += 1
        while idx < len(lines) and lines[idx].strip():
            cur = lines[idx]
            if _indent_width(cur) > base_indent:
                cur_fence = _fence_open_or_list_fence(cur, min_indent=base_indent + 1, max_indent=base_indent + 4)
                if cur_fence is not None:
                    block, idx = _consume_fence(lines, idx, cur_fence, min_indent=base_indent + 1)
                    item.extend(block)
                else:
                    item.append(cur)
                    idx += 1
            else:
                break
        units.append(item)
    return units


def _strip_list_marker(line: str) -> str:
    stripped = line.strip()
    match = _LIST_ITEM_RE.match(stripped)
    if match is not None and not _THEMATIC_BREAK_RE.match(stripped):
        return stripped[match.end():].strip()
    return stripped


def _line_is_ledger(line: str) -> bool:
    return bool(line.strip()) and _strip_list_marker(line).lower().startswith(_LEDGER_PREFIXES)


def _unit_is_ledger(unit: Sequence[str]) -> bool:
    for line in unit:
        if line.strip():
            return _line_is_ledger(line)
    return False


def _strip_nested_ledger_lines(unit: Sequence[str]) -> tuple[list[str], list[str]]:
    """Remove ledger sub-lines (and their wrapped/multi-paragraph continuations) inside a unit.

    Returns ``(kept_lines, removed_ledger_lines)``.
    """
    kept: list[str] = []
    removed: list[str] = []
    idx = 0
    while idx < len(unit):
        line = unit[idx]
        if _line_is_ledger(line):
            base_indent = _indent_width(line)
            content_indent = _list_item_content_indent(line)
            removed.append(line)
            idx += 1
            while idx < len(unit):
                cur = unit[idx]
                if not cur.strip():
                    if content_indent is None:
                        break
                    look = idx
                    while look < len(unit) and not unit[look].strip():
                        look += 1
                    if look < len(unit) and _indent_width(unit[look]) >= content_indent:
                        removed.extend(unit[idx:look])
                        idx = look
                        continue
                    break
                cur_indent = _indent_width(cur)
                if content_indent is not None and cur_indent >= content_indent:
                    cur_fence = _fence_open(cur, min_indent=content_indent, max_indent=content_indent + 3)
                    if cur_fence is not None:
                        block, idx = _consume_fence(unit, idx, cur_fence, min_indent=content_indent)
                        removed.extend(block)
                        continue
                elif _fence_open(cur, min_indent=0, max_indent=3) is not None:
                    break
                if content_indent is not None:
                    if cur_indent < content_indent and (_HEADING_RE.match(cur) or _THEMATIC_BREAK_RE.match(cur)):
                        break
                    if _list_item_content_indent(cur) is not None and cur_indent < content_indent:
                        break
                else:
                    if _HEADING_RE.match(cur) or _THEMATIC_BREAK_RE.match(cur):
                        break
                    if _list_item_content_indent(cur) is not None and cur_indent <= base_indent:
                        break
                    if cur_indent < base_indent:
                        break
                removed.append(cur)
                idx += 1
            if kept and kept[-1].strip():
                kept.append("")
            continue
        kept.append(line)
        idx += 1
    return kept, removed


def _unit_is_empty_fence(unit: Sequence[str]) -> bool:
    non_blank = [line for line in unit if line.strip()]
    if not non_blank:
        return False
    opener = _fence_open(non_blank[0], min_indent=0, max_indent=3)
    if opener is None:
        return False
    char, length = opener
    body = non_blank[1:]
    if body and _fence_close(body[-1], char, length, min_indent=0, max_indent=3):
        body = body[:-1]
    return not body


def _line_is_non_proposal_marker(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _THEMATIC_BREAK_RE.match(line) or re.match(r"^[ \t]*#{1,6}(?:\s|$)", line):
        return True
    if _list_item_content_indent(line) is not None and not _strip_list_marker(line):
        return True
    if classify_improvements(line) in {"none", "missing"}:
        return True
    redacted = redact(line, drop_ledger=True, bulleted_ledger=True)
    if not redacted:
        return True
    body = _strip_list_marker(redacted)
    return not body or bool(_PLACEHOLDER_ONLY_RE.fullmatch(body))


def _unit_is_non_proposal(unit: Sequence[str]) -> bool:
    """True when ``unit`` carries no substantive proposal content."""
    if not any(line.strip() for line in unit) or _unit_is_empty_fence(unit):
        return True
    # Walk original lines preserving blank-line boundaries so a paragraph
    # followed by a blank line and `---` is never misread as a Setext heading,
    # while using the same list-relative fence bounds as `_split_improvement_units`.
    idx = 0
    residual: list[str] = []
    list_indents: list[int] = []
    saw_blank = False
    while idx < len(unit):
        line = unit[idx]
        if not line.strip():
            saw_blank = True
            residual.append(line)
            idx += 1
            continue
        cur_indent = _indent_width(line)
        if saw_blank:
            while list_indents and cur_indent < list_indents[-1]:
                list_indents.pop()
        saw_blank = False
        item_indent = _list_item_content_indent(line)
        if item_indent is not None:
            while list_indents and cur_indent < list_indents[-1]:
                list_indents.pop()
            list_indents.append(item_indent)
            opener = _fence_open_after_list_marker(line)
            if opener is not None:
                min_ind = list_indents[-1]
                block, next_idx = _consume_fence(unit, idx, opener, min_indent=min_ind)
                char, length = opener
                body = [b for b in block[1:] if b.strip()]
                if body and _fence_close(body[-1], char, length, min_indent=min_ind, max_indent=min_ind + 3):
                    body = body[:-1]
                if body:
                    return False
                residual.append("")
                idx = next_idx
                continue
        else:
            active_indent = list_indents[-1] if list_indents else None
            if active_indent is not None and cur_indent >= active_indent:
                fence_min = active_indent
                bound: int | None = active_indent
            else:
                fence_min = 0
                bound = None
            opener = _fence_open(line, min_indent=fence_min, max_indent=fence_min + 3)
            if opener is not None:
                block, next_idx = _consume_fence(unit, idx, opener, min_indent=bound)
                char, length = opener
                body = [b for b in block[1:] if b.strip()]
                if body and _fence_close(body[-1], char, length, min_indent=fence_min, max_indent=fence_min + 3):
                    body = body[:-1]
                if body:
                    return False
                residual.append("")
                idx = next_idx
                continue
        residual.append(line)
        idx += 1
    # Drop single- or multi-line Setext headings (contiguous non-blank plain
    # paragraph lines immediately underlined by `===` / `---` with no blank line).
    filtered_residual: list[str] = []
    r_idx = 0
    no_setext_before = 0
    while r_idx < len(residual):
        line = residual[r_idx]
        if (
            r_idx >= no_setext_before
            and line.strip()
            and _list_item_content_indent(line) is None
            and not _THEMATIC_BREAK_RE.match(line)
            and not re.match(r"^[ \t]*#{1,6}(?:\s|$)", line)
            and not _ANY_SETEXT_UNDERLINE_RE.match(line)
        ):
            look = r_idx + 1
            while look < len(residual) and residual[look].strip():
                cand = residual[look]
                if _ANY_SETEXT_UNDERLINE_RE.match(cand):
                    r_idx = look + 1
                    break
                if (
                    _list_item_content_indent(cand) is not None
                    or _THEMATIC_BREAK_RE.match(cand)
                    or re.match(r"^[ \t]*#{1,6}(?:\s|$)", cand)
                ):
                    break
                look += 1
            if r_idx == look + 1:
                continue
            no_setext_before = look
        filtered_residual.append(line)
        r_idx += 1
    return all(_line_is_non_proposal_marker(line) for line in filtered_residual)


CONTENT_KEYS = ("worked", "didnt", "improvements")
NEAR_DUPLICATE_OVERLAP = 0.8


def _norm_line(line: str) -> str:
    return " ".join(re.sub(r"^[-*+]\s+", "", line.strip()).split())


def _content_lines(reflection: Reflection) -> set[str]:
    if not reflection.structured:
        lines = reflection.raw.splitlines()
    else:
        lines = [line for key in CONTENT_KEYS for line in reflection.sections.get(key, "").splitlines()]
    return {norm for norm in map(_norm_line, lines) if norm}


def _mark_duplicates(reflections: list[Reflection]) -> None:
    """Collapse exact and near copies of the same skill/repo/branch/run.

    A near-copy is a re-emitted reflection (same run re-closed) whose own content
    lines are at least ``NEAR_DUPLICATE_OVERLAP`` contained in an earlier kept one, so
    a newer reflection that adds friction to an older one is kept. Copies are never
    collapsed across runs: identical reports from independent runs are
    recurring evidence, not duplicates.

    Because the grouping key is ``(bare_skill, repo_hash, branch_slug, run_id)``
    without the scan root, deduplication is effectively cross-root across different
    harness roots. Legacy flat reflections that lack ``repo_hash`` or ``branch_slug``
    are skipped so unidentifiable legacy copies are never falsely collapsed.
    """
    kept_by_group: dict[tuple[str, str, str, str], list[tuple[str, set[str]]]] = defaultdict(list)
    for reflection in reflections:
        if reflection.excluded or not reflection.repo_hash or not reflection.branch_slug:
            continue
        group = (*reflection.group, reflection.run_id)
        lines = _content_lines(reflection)
        for kept_id, kept_lines in kept_by_group[group]:
            if lines and len(lines & kept_lines) / len(lines) >= NEAR_DUPLICATE_OVERLAP:
                reflection.excluded = f"duplicate_of:{kept_id}"
                break
        if reflection.excluded:
            continue
        kept_by_group[group].append((reflection.id, lines))


def apply_quality_filter(
    reflections: list[Reflection],
    *,
    per_branch_cap: int = DEFAULT_PER_BRANCH_CAP,
    boilerplate_min: int = DEFAULT_BOILERPLATE_MIN,
) -> list[str]:
    """Mark exclusions in place and strip boilerplate; returns the boilerplate lines removed.

    Order matters. Duplicates collapse first so one copied reflection cannot make
    its own lines look like cross-run boilerplate. Repeated one-repo ledger lines
    and repeated one-repo lines carrying a ref, path or URL within the same skill
    are stripped from What worked and Improvements before classification.
    Repo-specific proposal lines are dropped at line granularity so generic
    sibling proposals still reach the aggregator; when no agnostic proposal
    survives, the Improvements section is dropped while usable friction stays
    intact, and the per-branch cap keeps the newest usable reflections.
    """
    _mark_duplicates(reflections)

    line_counts: Counter[tuple[str, str]] = Counter()
    line_repos: dict[tuple[str, str], set[str]] = defaultdict(set)
    for reflection in reflections:
        if not reflection.excluded:
            ledger_lines = {
                _norm_line(line)
                for key in ("worked", "improvements")
                for line in reflection.sections.get(key, "").splitlines()
            }
            for line in ledger_lines:
                if len(line) >= BOILERPLATE_MIN_CHARS and (
                    line.lower().startswith(_LEDGER_PREFIXES) or classify_improvements(line) == "repo_specific"
                ):
                    skill_line = (reflection.bare_skill, line)
                    line_counts[skill_line] += 1
                    line_repos[skill_line].add(reflection.repo_hash)
    boilerplate_by_skill: dict[str, set[str]] = defaultdict(set)
    for (bare_skill, line), count in line_counts.items():
        if count >= boilerplate_min and len(line_repos[(bare_skill, line)]) == 1:
            boilerplate_by_skill[bare_skill].add(line)

    for reflection in reflections:
        if reflection.excluded:
            continue
        skill_boilerplate = boilerplate_by_skill.get(reflection.bare_skill, ())
        if "worked" in reflection.sections:
            original = reflection.sections["worked"].splitlines()
            kept = [line for line in original if _norm_line(line) not in skill_boilerplate]
            if len(kept) != len(original):
                reflection.notes.append(f"boilerplate_stripped:worked:{len(original) - len(kept)}")
            reflection.sections["worked"] = _strip_blank_edges(kept)

        stripped_repo_specific = False
        dropped_repo_specific = 0
        stripped_ledger = False
        if "improvements" in reflection.sections:
            # Group into Markdown proposal units BEFORE stripping boilerplate lines so
            # boilerplate removal cannot split a wrapped repo-specific bullet and leave
            # its continuation behind as a false generic proposal (agent-harness#1654).
            units = _split_improvement_units(reflection.sections["improvements"])
            bp_stripped_count = 0
            surviving_units: list[list[str]] = []
            for unit in units:
                bp_lines = [line for line in unit if _norm_line(line) in skill_boilerplate]
                bp_stripped_count += len(bp_lines)
                if any(classify_improvements(line) == "repo_specific" for line in bp_lines):
                    stripped_repo_specific = True
                if _unit_is_ledger(unit):
                    stripped_ledger = True
                    if any(classify_improvements(line) == "repo_specific" for line in unit):
                        stripped_repo_specific = True
                    continue
                # Strip nested/wrapped ledger entries BEFORE classifying proposal content
                # or stripping boilerplate so a nested ledger ref cannot discard a generic
                # proposal and boilerplate removal cannot orphan a ledger continuation.
                without_ledger, removed_ledger = _strip_nested_ledger_lines(unit)
                if removed_ledger:
                    stripped_ledger = True
                if any(classify_improvements(line) == "repo_specific" for line in removed_ledger):
                    stripped_repo_specific = True
                if any(classify_improvements(line) == "repo_specific" for line in without_ledger):
                    bp_in_non_ledger = sum(
                        1 for line in without_ledger if _norm_line(line) in skill_boilerplate
                    )
                    dropped_repo_specific += len(without_ledger) - bp_in_non_ledger
                    continue
                kept_unit = [line for line in without_ledger if _norm_line(line) not in skill_boilerplate]
                if _unit_is_empty_fence(kept_unit):
                    continue
                if kept_unit:
                    surviving_units.append(kept_unit)
            if bp_stripped_count:
                reflection.notes.append(f"boilerplate_stripped:improvements:{bp_stripped_count}")
            # Decide substantive survival AFTER ledger/boilerplate removal so a
            # non-proposal marker paired with an indented ledger line cannot be
            # classified as agnostic and archived (agent-harness#1654).
            substantive_units = [unit for unit in surviving_units if not _unit_is_non_proposal(unit)]
            if substantive_units:
                reflection.sections["improvements"] = _strip_blank_edges(
                    [line for unit in surviving_units for line in unit]
                )
                reflection.improvements_class = "agnostic"
                if dropped_repo_specific:
                    reflection.notes.append(
                        f"lines_dropped:improvements:repo_specific:{dropped_repo_specific}"
                    )
            elif dropped_repo_specific or stripped_repo_specific:
                reflection.sections["improvements"] = ""
                reflection.improvements_class = "repo_specific"
                reflection.notes.append("improvements_repo_specific")
                reflection.notes.append("section_dropped:improvements:repo_specific")
            else:
                non_blank_remaining = [
                    line for unit in surviving_units for line in unit if line.strip()
                ]
                has_none_marker = any(
                    classify_improvements(line) == "none" for line in non_blank_remaining
                )
                if stripped_ledger and not has_none_marker:
                    reflection.sections["improvements"] = ""
                    reflection.improvements_class = "ledger_only"
                    reflection.notes.append("improvements_ledger_only")
                else:
                    reflection.sections["improvements"] = _strip_blank_edges(
                        [line for unit in surviving_units for line in unit]
                    ) if has_none_marker else ""
                    reflection.improvements_class = "none" if has_none_marker else "missing"
        else:
            reflection.improvements_class = "missing"
        for key in CONTENT_KEYS:
            if key in reflection.sections:
                reflection.sections[key] = redact(
                    reflection.sections[key], drop_ledger=key != "didnt", bulleted_ledger=key == "improvements",
                )
        eligible_proposal = reflection.improvements_class == "agnostic" and bool(reflection.sections.get("improvements"))
        if reflection.structured and not reflection.sections.get("didnt") and not eligible_proposal:
            if reflection.improvements_class == "repo_specific":
                reflection.excluded = "improvements_repo_specific"
            elif reflection.improvements_class == "ledger_only":
                reflection.excluded = "improvements_ledger_only"
            else:
                reflection.excluded = "no_friction_or_proposal"

    groups: dict[tuple[str, str, str], list[Reflection]] = defaultdict(list)
    for reflection in reflections:
        if not reflection.excluded:
            groups[reflection.group].append(reflection)
    for members in groups.values():
        members.sort(key=lambda r: (r.timestamp, r.run_id), reverse=True)
        for reflection in members[per_branch_cap:]:
            reflection.excluded = f"per_branch_cap:{per_branch_cap}"
    return sorted({line for lines in boilerplate_by_skill.values() for line in lines})


def collect(
    roots: Sequence[Path] | None = None,
    *,
    min_reflections: int = 2,
    per_branch_cap: int = DEFAULT_PER_BRANCH_CAP,
    boilerplate_min: int = DEFAULT_BOILERPLATE_MIN,
) -> tuple[Corpus, list[str]]:
    roots = _dedup_roots(roots if roots is not None else default_roots())
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


def _source_token(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:16] if all(parts) else "unknown"


def render_bundle(corpus: Corpus) -> str:
    """The aggregator's input: admitted reflections grouped by bare skill.

    Every reflection-derived string passes the shared credential redaction first,
    then ``quote_body``; entry-header fields are also forced onto one line.
    """
    lines = ["# Reflections to aggregate", "", f"min_reflections: {corpus.min_reflections}", ""]
    labels = (("worked", "What worked"), ("didnt", "What didn't"), ("improvements", "Improvements to SKILL.md"))
    for skill, items in corpus.admitted_by_skill().items():
        lines += [f"## {skill} ({len(items)} reflections)", ""]
        for reflection in items:
            lines.append(f"### {reflection.id} — {_header_field(reflection.skill)} — {_header_field(reflection.timestamp)}")
            lines.append(
                f"**Source**: repo {_source_token(reflection.repo_hash)}; "
                f"branch {_source_token(reflection.repo_hash, reflection.branch_slug)}; "
                f"run {_source_token(reflection.repo_hash, reflection.branch_slug, reflection.run_id)}"
            )
            if reflection.structured:
                for key, label in labels:
                    body = reflection.sections.get(key, "")
                    if body:
                        lines += [f"**{label}**", quote_body(redact_text(body)), ""]
            else:
                lines += ["**unstructured**", quote_body(redact_text(redact(reflection.raw))), ""]
    return "\n".join(lines).rstrip() + "\n"


# Exclusions whose reflection carries no evidence a later pass could use.
# ``duplicate_of`` is conditional: a duplicate is consumed only when its kept twin
# is also consumed in this pass (agent-harness#1657).
ARCHIVABLE_EXCLUSIONS = ("duplicate_of", "no_friction_or_proposal")
_UNCONDITIONAL_ARCHIVABLE_EXCLUSIONS = frozenset(ARCHIVABLE_EXCLUSIONS) - {"duplicate_of"}


def _duplicate_target_id(excluded: str | None) -> str | None:
    if not excluded:
        return None
    prefix, sep, target = excluded.partition(":")
    if prefix == "duplicate_of" and sep and target:
        return target
    return None


def consumed(corpus: Corpus) -> list[Reflection]:
    """Reflections this pass uses up, so the editor may archive them.

    That is the admitted reflections of ready skills (they feed the plan),
    reflections excluded as having no friction and no proposal, and duplicates
    (``duplicate_of:<id>``) whose kept twin is also consumed in this pass. Every
    other reflection stays in place: admitted ones of a skill below the threshold
    (and their duplicates) so evidence can accumulate, duplicates of non-consumed
    reflections, and the rest of the excluded ones (a dropped repo-specific or
    ledger-only proposal with no friction, per-branch cap, oversized) because they
    may still be evidence. Repo-specific Improvements are removed without dropping usable
    friction. A reflection whose real location leaves its scan root is never
    consumed, because ``archive`` would refuse it.
    """
    ready = set(corpus.ready_skills())
    consumed_indices: set[int] = set()
    consumed_ids: set[str] = set()
    for idx, reflection in enumerate(corpus.scanned):
        if not reflection.in_root:
            continue
        reason = (reflection.excluded or "").split(":", 1)[0]
        if (reflection.excluded is None and reflection.bare_skill in ready) or (
            reason in _UNCONDITIONAL_ARCHIVABLE_EXCLUSIONS
        ):
            consumed_indices.add(idx)
            if reflection.id:
                consumed_ids.add(reflection.id)
    changed = True
    while changed:
        changed = False
        for idx, reflection in enumerate(corpus.scanned):
            if idx in consumed_indices or not reflection.in_root:
                continue
            target_id = _duplicate_target_id(reflection.excluded)
            if target_id is not None and target_id in consumed_ids:
                consumed_indices.add(idx)
                if reflection.id:
                    consumed_ids.add(reflection.id)
                changed = True
    return [reflection for idx, reflection in enumerate(corpus.scanned) if idx in consumed_indices]


def _cap_manifest_line(text: str) -> str:
    if len(text) <= MAX_MANIFEST_BOILERPLATE_LINE_CHARS:
        return text
    return text[:MAX_MANIFEST_BOILERPLATE_LINE_CHARS].rstrip() + "…"


def manifest(corpus: Corpus, boilerplate: list[str]) -> dict[str, object]:
    return {
        "inventory": inventory(corpus),
        # The planner reads this file too, so stripped lines get the same redaction
        # and are capped at MAX_MANIFEST_BOILERPLATE_LINE_CHARS plus an ellipsis.
        "boilerplate_lines_stripped": [_cap_manifest_line(redact_text(redact(line))) for line in boilerplate],
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


def render_rule_registry(rules: Sequence[Rule]) -> str:
    """agent-harness#1321 (REPORT 1.14/1.15): the shipped rule->enforcer registry as
    the aggregator reads it. Unlike ``bundle.md`` this is trusted package data, so it
    is a separate artifact; the aggregator's structural-mechanism gate and ladder
    level are decided against it."""
    lines = [
        "# Rule enforcement registry",
        "",
        "Shipped skill rules and what refuses a violation of each "
        "(`phase_loop_runtime/rule_enforcement.json`). Statuses: `enforced` (named code "
        "refuses a violation), `unenforced/gap` (a mechanism could exist and does not "
        "yet; `tracking` names its issue), `unenforced/judgment` (prose is the correct, "
        "final level).",
        "",
    ]
    for rule in sorted(rules, key=lambda r: r.id):
        status = rule.status if rule.status == "enforced" else f"{rule.status}/{rule.unenforced_reason}"
        lines.append(f"- `{rule.id}` — skill `{rule.skill}` — **{status}**")
        lines.append(f"  - rule: {json.dumps(rule.quote, ensure_ascii=False)}")
        for enforcer in rule.enforcers:
            where = enforcer.module if enforcer.kind == "module" else enforcer.path
            lines.append(f"  - enforcer: {enforcer.kind} `{where}:{enforcer.symbol}`")
        if rule.tracking:
            lines.append(f"  - tracking: {rule.tracking}")
    return "\n".join(lines) + "\n"


def write_corpus(corpus: Corpus, boilerplate: list[str], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / "bundle.md"
    manifest_path = out_dir / "manifest.json"
    registry = out_dir / "rule_enforcement.md"
    bundle.write_text(render_bundle(corpus), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest(corpus, boilerplate), indent=2) + "\n", encoding="utf-8")
    registry.write_text(render_rule_registry(load_registry()), encoding="utf-8")
    return {"bundle": bundle, "manifest": manifest_path, "rule_registry": registry}


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
    allowed = [Path(os.path.abspath(Path(root).expanduser())) for root in [*_configured_default_roots(), *(roots or [])]]
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
    collect_cmd = sub.add_parser("collect", help="Enumerate, parse and filter reflections; with --out-dir, write bundle.md, manifest.json and rule_enforcement.md.")
    collect_cmd.add_argument("--root", action="append", type=Path, help="Skill root to scan (repeatable). Default: every harness root.")
    collect_cmd.add_argument("--out-dir", type=Path)
    collect_cmd.add_argument("--min-reflections", type=int, default=2)
    collect_cmd.add_argument("--per-branch-cap", type=int, default=DEFAULT_PER_BRANCH_CAP)
    collect_cmd.add_argument("--boilerplate-min", type=int, default=DEFAULT_BOILERPLATE_MIN)
    archive_cmd = sub.add_parser("archive", help="Archive consumed paths from a manifest, except those named with --exclude.")
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
