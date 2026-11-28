"""Skill-text invariants for agent-harness#1699 (follow-up from agent-harness#1687).

1. Pin the ``claude-execute-phase`` merge-target safety gate in ``SKILL.md``
   inside ``## Workflow`` at its pre-dispatch position (and its back-pointer in
   ``references/interactive-steps.md``) so mutations that weaken, hide, indent
   as code, or relocate the gate cannot survive.
2. Assert that every shipped ``references/**/*.md`` file is linked by relative
   path from its owning ``SKILL.md`` as visible CommonMark prose (excluding
   fenced code blocks at any container nesting depth, indented code blocks,
   HTML comments, images, and escaped brackets). Under the adapter bundle
   manifest read exception, an unlinked reference cannot be read.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from phase_loop_runtime import injection

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_SRC = REPO_ROOT / "skills-src"
PHASE_LOOP_SKILLS = REPO_ROOT / "phase-loop-skills"
PACKAGED_SKILLS = Path(injection.__file__).resolve().parent / "skills_bundle"

_LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")
_BLOCKQUOTE_RE = re.compile(r"^ {0,3}>(.*)$")
_LIST_ITEM_RE = re.compile(r"^([-*+]|(?:\d{1,9})[.)])([ \t]+|$)(.*)$")
_OPEN_FENCE_RE = re.compile(r"^(`{3,}|~{3,})([^\r\n]*)$")
_CLOSE_FENCE_RE = re.compile(r"^(`{3,}|~{3,})[ \t]*$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(\*[ \t]*){3,}|(-[ \t]*){3,}|(_[ \t]*){3,})$")
_TRAILING_HASHES_RE = re.compile(r"(?:^|[ \t]+)#+$")
_LINK_DEF_RE = re.compile(
    r"^ {0,3}\[([^\]]+)\]:[ \t]*(?:\n[ \t]*)?(?:<([^>\r\n]+)>|([^\s<>]+))(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$",
    re.MULTILINE,
)
_INLINE_DEST_RE = re.compile(
    r"^[ \t]*(?:\n[ \t]*)?(?:<([^>\r\n]+)>|([^\s()<>]+))(?:[ \t\n]+(?:\"[^\"]*\"|'[^']*'))?[ \t]*(?:\n[ \t]*)?\)"
)
_ASCII_PUNCT = set(r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~""")


@dataclass
class _Container:
    kind: str  # "blockquote" | "list"
    indent: int  # required content columns for "list"; 0 for "blockquote"


@dataclass
class _FenceState:
    char: str
    length: int
    owner_depth: int


@dataclass
class _CommentState:
    owner_depth: int


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = _LINE_SPLIT_RE.split(text)
    if text.endswith(("\r\n", "\n", "\r")) and lines and lines[-1] == "":
        lines.pop()
    return lines


def _leading_indent_cols(line: str, start_col: int = 0) -> tuple[int, int]:
    """Return ``(indent_cols, char_index)`` of leading spaces/tabs from ``start_col``."""
    col = start_col
    idx = 0
    while idx < len(line):
        ch = line[idx]
        if ch == " ":
            col += 1
            idx += 1
        elif ch == "\t":
            col += 4 - (col % 4)
            idx += 1
        else:
            break
    return col - start_col, idx


def _consume_cols(line: str, cols: int, start_col: int = 0) -> tuple[bool, str, int]:
    """Consume exactly ``cols`` columns of leading whitespace (expanding tabs)."""
    consumed = 0
    idx = 0
    cur_col = start_col
    while consumed < cols and idx < len(line):
        ch = line[idx]
        if ch == " ":
            consumed += 1
            cur_col += 1
            idx += 1
        elif ch == "\t":
            tab_w = 4 - (cur_col % 4)
            if consumed + tab_w > cols:
                # Partial tab expansion: emit leftover spaces.
                leftover = (consumed + tab_w) - cols
                return True, (" " * leftover) + line[idx + 1 :], start_col + cols
            consumed += tab_w
            cur_col += tab_w
            idx += 1
        else:
            return False, line, start_col
    if consumed < cols:
        return False, line, start_col
    return True, line[idx:], start_col + cols


def _strip_one_blockquote(line: str, start_col: int) -> tuple[bool, str, int]:
    indent, idx = _leading_indent_cols(line, start_col)
    if indent > 3 or idx >= len(line) or line[idx] != ">":
        return False, line, start_col
    col_after_gt = start_col + indent + 1
    rest = line[idx + 1 :]
    if rest.startswith(" "):
        return True, rest[1:], col_after_gt + 1
    if rest.startswith("\t"):
        tab_w = 4 - (col_after_gt % 4)
        return True, (" " * (tab_w - 1)) + rest[1:], col_after_gt + 1
    return True, rest, col_after_gt


def _visible_prose(text: str) -> str:
    """Extract visible CommonMark prose lines, removing fences, indented code, and HTML comments.

    Tracks nested blockquote and list containers so fences opened inside nested containers
    (e.g. ``- > ~~~``) blank their body, unclosed container fences close when their owning
    container closes (e.g. ``- ~~~`` followed by top-level text), indented code blocks
    (>= 4 spaces outside a paragraph) are blanked, and HTML comments cannot open fences.
    """
    out: list[str] = []
    containers: list[_Container] = []
    fence: _FenceState | None = None
    comment: _CommentState | None = None
    in_paragraph = False

    for raw_line in _split_lines(text):
        rest = raw_line
        col = 0
        matched = 0
        is_blank = False

        # Step 1: Match existing open containers from outermost to innermost.
        for container in containers:
            if not rest.strip():
                is_blank = True
                break
            if container.kind == "blockquote":
                ok, next_rest, next_col = _strip_one_blockquote(rest, col)
                if not ok:
                    break
                rest, col = next_rest, next_col
                matched += 1
            else:
                ok, next_rest, next_col = _consume_cols(rest, container.indent, col)
                if not ok:
                    break
                rest, col = next_rest, next_col
                matched += 1

        if is_blank or not rest.strip():
            # Blank line closes any unclosed paragraph; stays inside open fence/comment.
            in_paragraph = False
            if fence is not None or comment is not None:
                out.append("")
            else:
                out.append("")
            continue

        # Close containers that did not match this non-blank line.
        if matched < len(containers):
            containers = containers[:matched]
            if fence is not None and fence.owner_depth > matched:
                fence = None
            if comment is not None and comment.owner_depth > matched:
                comment = None
            in_paragraph = False

        # Step 2: If still inside a multi-line HTML comment, consume until `-->`.
        if comment is not None:
            end_idx = rest.find("-->")
            if end_idx == -1:
                out.append("")
                continue
            comment = None
            after = rest[end_idx + 3 :]
            if not after.strip():
                in_paragraph = False
                out.append("")
                continue
            rest = after
            in_paragraph = False

        # Step 3: If still inside a fenced code block, check for closing fence at owner depth.
        if fence is not None:
            indent, idx = _leading_indent_cols(rest, col)
            close_match = _CLOSE_FENCE_RE.match(rest[idx:]) if indent <= 3 else None
            if (
                close_match is not None
                and close_match.group(1)[0] == fence.char
                and len(close_match.group(1)) >= fence.length
            ):
                fence = None
            out.append("")
            continue

        # Step 4: Open any new nested containers on this line (blockquote / list item).
        opened_container = False
        while True:
            indent, idx = _leading_indent_cols(rest, col)
            if indent > 3:
                break
            body = rest[idx:]
            if body.startswith(">"):
                ok, next_rest, next_col = _strip_one_blockquote(rest, col)
                if ok:
                    containers.append(_Container("blockquote", 0))
                    rest, col = next_rest, next_col
                    opened_container = True
                    in_paragraph = False
                    continue
            list_match = _LIST_ITEM_RE.match(body)
            if list_match is not None:
                marker = list_match.group(1)
                gap = list_match.group(2)
                after_item = list_match.group(3)
                # Empty list item or non-empty list item content column.
                marker_cols = len(marker)
                gap_cols, _ = _leading_indent_cols(gap, col + indent + marker_cols)
                if not after_item.strip():
                    content_indent = indent + marker_cols + 1
                    containers.append(_Container("list", content_indent))
                    rest = ""
                    col += content_indent
                    opened_container = True
                    in_paragraph = False
                    break
                # CommonMark §5.2: if >= 5 spaces follow marker, content starts at marker+1 (rest is indented code).
                if gap_cols >= 5:
                    content_indent = indent + marker_cols + 1
                    _, rest, col = _consume_cols(
                        body[marker_cols:], 1, col + indent + marker_cols
                    )
                else:
                    content_indent = indent + marker_cols + max(gap_cols, 1)
                    rest = after_item
                    col += content_indent
                containers.append(_Container("list", content_indent))
                opened_container = True
                in_paragraph = False
                continue
            break

        if not rest.strip():
            in_paragraph = False
            out.append("")
            continue

        # Step 5: Indented code block (>= 4 columns outside a paragraph).
        indent, idx = _leading_indent_cols(rest, col)
        if indent >= 4 and not in_paragraph:
            out.append("")
            continue

        # Step 6: HTML comment handling before fence detection so `<!-- ``` -->` cannot open a fence.
        stripped_line = _strip_line_html_comments(rest, owner_depth=len(containers))
        if isinstance(stripped_line, tuple):
            visible_part, comment = stripped_line
            if not visible_part.strip():
                in_paragraph = False
                out.append("")
                continue
            rest = visible_part
        else:
            rest = stripped_line
            if not rest.strip():
                in_paragraph = False
                out.append("")
                continue

        # Step 7: Fenced code block opener (<= 3 columns after containers).
        indent, idx = _leading_indent_cols(rest, col)
        if indent <= 3:
            open_match = _OPEN_FENCE_RE.match(rest[idx:])
            if open_match is not None:
                marker = open_match.group(1)
                info = open_match.group(2)
                if not (marker[0] == "`" and "`" in info):
                    fence = _FenceState(marker[0], len(marker), owner_depth=len(containers))
                    in_paragraph = False
                    out.append("")
                    continue

        # Step 8: ATX heading, Setext heading underline, or thematic break ends paragraph state.
        if (
            _ATX_HEADING_RE.match(rest)
            or _THEMATIC_BREAK_RE.match(rest)
            or (in_paragraph and not opened_container and _SETEXT_UNDERLINE_RE.match(rest))
        ):
            in_paragraph = False
        else:
            in_paragraph = True if (not opened_container or bool(rest.strip())) else False
        out.append(rest)

    return "\n".join(out)


def _strip_line_html_comments(
    line: str, *, owner_depth: int
) -> str | tuple[str, _CommentState]:
    """Strip inline ``<!-- ... -->`` comments on ``line`` (ignoring ones inside inline code spans).

    If an unclosed ``<!--`` opens on ``line``, returns ``(prefix_before_comment, _CommentState)``.
    """
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == "\\" and i + 1 < n and line[i + 1] in _ASCII_PUNCT:
            out.append(line[i : i + 2])
            i += 2
            continue
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            tick_len = j - i
            close_idx = _find_matching_backticks(line, j, tick_len)
            if close_idx != -1:
                out.append(line[i : close_idx + tick_len])
                i = close_idx + tick_len
                continue
            out.append(line[i:j])
            i = j
            continue
        if line.startswith("<!--", i):
            end_idx = line.find("-->", i + 4)
            if end_idx == -1:
                return "".join(out), _CommentState(owner_depth=owner_depth)
            i = end_idx + 3
            continue
        out.append(line[i])
        i += 1
    return "".join(out)


def _find_matching_backticks(text: str, start: int, tick_len: int) -> int:
    """Return index of matching backtick run of exact length ``tick_len``, or ``-1``."""
    k = start
    n = len(text)
    while k < n:
        if text[k] == "`":
            m = k
            while m < n and text[m] == "`":
                m += 1
            if m - k == tick_len:
                return k
            k = m
        else:
            k += 1
    return -1


def _iter_atx_headings(text: str) -> list[tuple[int, int, str]]:
    """Return ``(line_index, level, title)`` for ATX headings in visible prose."""
    headings: list[tuple[int, int, str]] = []
    for idx, line in enumerate(_split_lines(text)):
        match = _ATX_HEADING_RE.match(line)
        if match is not None:
            level = len(match.group(1))
            raw_title = (match.group(2) or "").strip()
            title = _TRAILING_HASHES_RE.sub("", raw_title).strip()
            headings.append((idx, level, title))
    return headings


def _extract_section_from_visible(visible: str, *, level: int, title: str) -> str | None:
    """Extract the body of an ATX section from already-filtered visible prose."""
    lines = _split_lines(visible)
    collecting = False
    collected: list[str] = []
    for line in lines:
        match = _ATX_HEADING_RE.match(line)
        if match is not None:
            heading_level = len(match.group(1))
            raw_title = (match.group(2) or "").strip()
            clean_title = _TRAILING_HASHES_RE.sub("", raw_title).strip()
            if collecting:
                if heading_level <= level:
                    break
                collected.append(line)
                continue
            if heading_level == level and clean_title == title:
                collecting = True
                continue
        elif collecting:
            collected.append(line)
    if not collecting:
        return None
    return "\n".join(collected)


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


_WORKFLOW_HEADING = "Workflow (orchestrator-only main thread)"
_INTERACTIVE_STEPS_HEADING = "Interactive steps"
_SAFETY_GATE_HEADING = "Step 2 — Merge-target safety gate"
_STEP_95_HEADING = "Step 9.5 — After the reflection and handoff are written"

_SAFETY_GATE_REQUIRED_PHRASES: tuple[tuple[str, str], ...] = (
    ("precedes dispatch/merge", "Before any lane dispatch or merge:"),
    (
        "stops on main or protected branch",
        "if the resolved merge target is `main` or a protected branch, STOP",
    ),
    (
        "forbids lane dispatch and git merge",
        "do not dispatch lanes or run any `git merge` onto it.",
    ),
    (
        "interactive feature-branch remediation",
        "Interactive: check out / create a dedicated feature branch first and re-resolve the merge target;",
    ),
    (
        "runner/adapter managed-branch remediation",
        "runner/adapter: the runner resolves a runner-managed branch.",
    ),
    (
        "precedence over Step 7 auto-merge",
        "This gate precedes Step 7's auto-merge, which would otherwise mutate `main` directly.",
    ),
)

_PUBLICATION_MODE_REQUIRED_PHRASES: tuple[tuple[str, str], ...] = (
    ("interactive branch passed safety gate", "passed the merge-target safety gate"),
    (
        "protected target stopped before lane merge",
        "Merge target is `main` or a protected branch. Already STOPPED at the merge-target safety gate before any lane merge",
    ),
    ("never merge lanes onto main/protected", "never merge lanes onto `main`/protected."),
)

_INTERACTIVE_STEPS_BACKPOINTER = (
    "Apply the merge-target safety gate in `SKILL.md` (Step 2) before any lane dispatch or merge."
)


def merge_target_safety_gate_findings(
    skill_md_text: str,
    *,
    interactive_steps_text: str | None = None,
    label: str = "claude-execute-phase",
) -> list[str]:
    """Return missing/mutated/misplaced invariants for the claude-execute-phase safety gate."""
    findings: list[str] = []
    visible_skill = _visible_prose(skill_md_text)

    workflow_body = _extract_section_from_visible(visible_skill, level=2, title=_WORKFLOW_HEADING)
    if workflow_body is None:
        findings.append(f"{label}/SKILL.md: missing `## {_WORKFLOW_HEADING}` section")
    else:
        subheadings = [
            (line_no, title)
            for line_no, lvl, title in _iter_atx_headings(workflow_body)
            if lvl == 3
        ]
        by_title = {title: line_no for line_no, title in subheadings}
        gate_body = _extract_section_from_visible(
            workflow_body, level=3, title=_SAFETY_GATE_HEADING
        )
        if gate_body is None:
            findings.append(
                f"{label}/SKILL.md: missing `### {_SAFETY_GATE_HEADING}` inside `## {_WORKFLOW_HEADING}`"
            )
        else:
            gate_pos = by_title[_SAFETY_GATE_HEADING]
            if (
                _INTERACTIVE_STEPS_HEADING not in by_title
                or gate_pos < by_title[_INTERACTIVE_STEPS_HEADING]
            ):
                findings.append(
                    f"{label}/SKILL.md: `### {_SAFETY_GATE_HEADING}` must follow `### {_INTERACTIVE_STEPS_HEADING}` in Workflow"
                )
            if _STEP_95_HEADING not in by_title or gate_pos > by_title[_STEP_95_HEADING]:
                findings.append(
                    f"{label}/SKILL.md: `### {_SAFETY_GATE_HEADING}` must precede `### {_STEP_95_HEADING}` in Workflow"
                )
            normalized_gate = _normalize_ws(gate_body)
            for clause_name, phrase in _SAFETY_GATE_REQUIRED_PHRASES:
                if phrase not in normalized_gate:
                    findings.append(
                        f"{label}/SKILL.md: Step 2 merge-target safety gate missing {clause_name} ({phrase!r})"
                    )

    pub_body = _extract_section_from_visible(visible_skill, level=2, title="Publication mode")
    if pub_body is None:
        findings.append(f"{label}/SKILL.md: missing `## Publication mode` section")
    else:
        normalized_pub = _normalize_ws(pub_body)
        for clause_name, phrase in _PUBLICATION_MODE_REQUIRED_PHRASES:
            if phrase not in normalized_pub:
                findings.append(
                    f"{label}/SKILL.md: Publication mode missing {clause_name} ({phrase!r})"
                )

    if interactive_steps_text is not None:
        visible_steps = _visible_prose(interactive_steps_text)
        preflight_body = _extract_section_from_visible(
            visible_steps, level=2, title="Step 2 — Preflight"
        )
        if preflight_body is None:
            findings.append(
                f"{label}/references/interactive-steps.md: missing `## Step 2 — Preflight` section"
            )
        elif _INTERACTIVE_STEPS_BACKPOINTER not in _normalize_ws(preflight_body):
            findings.append(
                f"{label}/references/interactive-steps.md: Step 2 preflight missing back-pointer "
                f"({_INTERACTIVE_STEPS_BACKPOINTER!r})"
            )

    return findings


def _normalize_ref_label(label: str) -> str:
    return " ".join(label.strip().split()).casefold()


def _normalize_relative_target(raw_target: str) -> str:
    target = raw_target.strip().split("#", 1)[0]
    if target.startswith("./"):
        target = target[2:]
    return target


def _find_bracket_close(text: str, open_idx: int) -> int:
    """Find the closing ``]`` matching ``[`` at ``open_idx`` (respecting escapes & code spans)."""
    n = len(text)
    depth = 1
    i = open_idx + 1
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCT:
            i += 2
            continue
        if ch == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            tick_len = j - i
            close_bt = _find_matching_backticks(text, j, tick_len)
            if close_bt != -1:
                i = close_bt + tick_len
                continue
            i = j
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _scan_paragraph_inline_links(
    paragraph: str, definitions: dict[str, str], linked: set[str]
) -> None:
    """Single-pass CommonMark inline scanner for links, images (ignored), escapes, and code spans."""
    i = 0
    n = len(paragraph)
    while i < n:
        ch = paragraph[i]
        # 1. Backslash escape skips escaped ASCII punctuation (e.g. `\[Guide](...)`).
        if ch == "\\" and i + 1 < n and paragraph[i + 1] in _ASCII_PUNCT:
            i += 2
            continue

        # 2. Inline code span: exact `references/...` counts; literal link examples do not.
        if ch == "`":
            j = i
            while j < n and paragraph[j] == "`":
                j += 1
            tick_len = j - i
            close_bt = _find_matching_backticks(paragraph, j, tick_len)
            if close_bt != -1:
                inner = paragraph[j:close_bt]
                if (
                    len(inner) >= 2
                    and inner.startswith(" ")
                    and inner.endswith(" ")
                    and inner.strip()
                ):
                    inner = inner[1:-1]
                candidate = inner[2:] if inner.startswith("./") else inner
                if candidate.startswith("references/") and not any(
                    c.isspace() for c in candidate
                ):
                    linked.add(candidate)
                i = close_bt + tick_len
                continue
            i = j
            continue

        # 3. Image node (`![alt](...)`, `![alt][label]`, `![label][]`, `![label]`): consume & ignore!
        if ch == "!" and i + 1 < n and paragraph[i + 1] == "[":
            close_br = _find_bracket_close(paragraph, i + 1)
            if close_br != -1:
                after = close_br + 1
                if after < n and paragraph[after] == "(":
                    m_dest = _INLINE_DEST_RE.match(paragraph[after + 1 :])
                    if m_dest is not None:
                        i = after + 1 + m_dest.end()
                        continue
                if after < n and paragraph[after] == "[":
                    close_ref = _find_bracket_close(paragraph, after)
                    if close_ref != -1:
                        label_text = paragraph[after + 1 : close_ref]
                        key = _normalize_ref_label(label_text or paragraph[i + 2 : close_br])
                        if key in definitions:
                            i = close_ref + 1
                            continue
                shortcut_key = _normalize_ref_label(paragraph[i + 2 : close_br])
                if shortcut_key in definitions:
                    i = close_br + 1
                    continue
            i += 1
            continue

        # 4. Link node (`[text](dest)`, `[text][label]`, `[label][]`, `[label]`).
        if ch == "[":
            close_br = _find_bracket_close(paragraph, i)
            if close_br != -1:
                link_text = paragraph[i + 1 : close_br]
                after = close_br + 1
                # Inline link: [text](dest) or [text](<dest>)
                if after < n and paragraph[after] == "(":
                    m_dest = _INLINE_DEST_RE.match(paragraph[after + 1 :])
                    if m_dest is not None:
                        dest = m_dest.group(1) if m_dest.group(1) is not None else m_dest.group(2)
                        if dest:
                            linked.add(_normalize_relative_target(dest))
                        i = after + 1 + m_dest.end()
                        continue
                # Full or collapsed reference link: [text][label] or [label][]
                if after < n and paragraph[after] == "[":
                    close_ref = _find_bracket_close(paragraph, after)
                    if close_ref != -1:
                        label_text = paragraph[after + 1 : close_ref]
                        key = _normalize_ref_label(label_text or link_text)
                        target = definitions.get(key)
                        if target:
                            linked.add(target)
                            i = close_ref + 1
                            continue
                # Shortcut reference link: [label] (not followed by `[`)
                elif not (after < n and paragraph[after] == "["):
                    key = _normalize_ref_label(link_text)
                    target = definitions.get(key)
                    if target:
                        linked.add(target)
                        i = close_br + 1
                        continue
            i += 1
            continue

        i += 1


def _extract_linked_relative_paths(skill_md_text: str) -> set[str]:
    """Collect relative reference paths linked via CommonMark links or exact inline code spans."""
    visible = _visible_prose(skill_md_text)
    definitions: dict[str, str] = {}

    def _consume_link_def(match: re.Match[str]) -> str:
        label = _normalize_ref_label(match.group(1))
        dest = match.group(2) if match.group(2) is not None else match.group(3)
        if label and label not in definitions and dest:
            definitions[label] = _normalize_relative_target(dest)
        return ""

    body = _LINK_DEF_RE.sub(_consume_link_def, visible)
    linked: set[str] = set()
    for paragraph in re.split(r"\n[ \t]*\n", body):
        if paragraph.strip():
            _scan_paragraph_inline_links(paragraph, definitions, linked)
    return linked


def is_reference_linked_in_skill_md(skill_md_text: str, rel_ref_path: str) -> bool:
    """True if ``rel_ref_path`` (e.g. ``references/foo.md``) is linked outside code/comments."""
    return rel_ref_path in _extract_linked_relative_paths(skill_md_text)


def unlinked_reference_findings_for_skill(
    skill_dir: Path,
    *,
    skill_md_path: Path | None = None,
    references_dir: Path | None = None,
    label_root: Path | None = None,
) -> tuple[int, list[str]]:
    """Audit all ``references/**/*.md`` files under one skill against its ``SKILL.md``."""
    ref_root = references_dir if references_dir is not None else skill_dir / "references"
    if not ref_root.is_dir():
        return 0, []
    md_files = sorted(p for p in ref_root.rglob("*.md") if p.is_file())
    if not md_files:
        return 0, []
    skill_md = skill_md_path if skill_md_path is not None else skill_dir / "SKILL.md"
    if not skill_md.is_file():
        rel_skill = (
            skill_dir.relative_to(label_root).as_posix()
            if label_root is not None
            else str(skill_dir)
        )
        return len(md_files), [f"{rel_skill}: ships references/ without SKILL.md"]
    linked_paths = _extract_linked_relative_paths(skill_md.read_text(encoding="utf-8"))
    findings: list[str] = []
    for ref_file in md_files:
        rel_ref = f"references/{ref_file.relative_to(ref_root).as_posix()}"
        if rel_ref not in linked_paths:
            owner_label = (
                skill_md.relative_to(label_root).as_posix()
                if label_root is not None
                else str(skill_md)
            )
            findings.append(f"{owner_label}: shipped `{rel_ref}` is not linked from SKILL.md")
    return len(md_files), findings


class ClaudeExecutePhaseMergeTargetGateTest(unittest.TestCase):
    def test_packaged_claude_execute_phase_pins_merge_target_safety_gate(self) -> None:
        skill_dir = PACKAGED_SKILLS / "claude-execute-phase"
        skill_md = skill_dir / "SKILL.md"
        interactive_steps = skill_dir / "references" / "interactive-steps.md"
        self.assertTrue(skill_md.is_file(), f"missing packaged {skill_md}")
        self.assertTrue(interactive_steps.is_file(), f"missing packaged {interactive_steps}")
        findings = merge_target_safety_gate_findings(
            skill_md.read_text(encoding="utf-8"),
            interactive_steps_text=interactive_steps.read_text(encoding="utf-8"),
            label="skills_bundle/claude-execute-phase",
        )
        self.assertEqual(findings, [], "\n".join(findings))

    def test_canonical_claude_execute_phase_pins_merge_target_safety_gate(self) -> None:
        if not SKILLS_SRC.is_dir():
            self.skipTest("skills-src/ not present (from-wheel install); source-tree check only")
        skill_dir = SKILLS_SRC / "claude" / "claude-execute-phase"
        findings = merge_target_safety_gate_findings(
            (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
            interactive_steps_text=(skill_dir / "references" / "interactive-steps.md").read_text(
                encoding="utf-8"
            ),
            label="skills-src/claude/claude-execute-phase",
        )
        self.assertEqual(findings, [], "\n".join(findings))

    def test_merge_target_safety_gate_rejects_mutations(self) -> None:
        skill_dir = PACKAGED_SKILLS / "claude-execute-phase"
        base_skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        base_steps = (skill_dir / "references" / "interactive-steps.md").read_text(encoding="utf-8")

        gate_start = base_skill.index(f"### {_SAFETY_GATE_HEADING}")
        gate_end = base_skill.index(f"### {_STEP_95_HEADING}", gate_start)
        gate_block = base_skill[gate_start:gate_end]
        gate_heading, gate_rest = gate_block.split("\n", 1)

        def _mutate_gate(old: str, new: str) -> str:
            self.assertIn(old, gate_block)
            return base_skill[:gate_start] + gate_block.replace(old, new, 1) + base_skill[gate_end:]

        closeout_idx = base_skill.index("## Closeout\n")
        moved_to_closeout = (
            base_skill[:gate_start]
            + base_skill[gate_end:closeout_idx]
            + "## Closeout\n\n"
            + gate_block
            + base_skill[closeout_idx + len("## Closeout\n") :]
        )
        after_step_95_end = base_skill.index("## Runner Verification Evidence")
        moved_after_step_95 = (
            base_skill[:gate_start]
            + base_skill[gate_end:after_step_95_end]
            + gate_block
            + base_skill[after_step_95_end:]
        )
        fenced_gate_only = (
            base_skill[:gate_start]
            + "```markdown\n"
            + gate_block
            + "```\n\n"
            + base_skill[gate_end:]
        )
        html_commented_gate = (
            base_skill[:gate_start]
            + f"{gate_heading}\n\n<!--\n"
            + gate_rest
            + "-->\n\n"
            + base_skill[gate_end:]
        )
        indented_code_gate = (
            base_skill[:gate_start]
            + gate_heading
            + "\n"
            + "\n".join(
                ("    " + ln if ln.strip() else ln) for ln in gate_rest.splitlines()
            )
            + "\n\n"
            + base_skill[gate_end:]
        )

        mutations: tuple[tuple[str, str, str, str], ...] = (
            (
                "heading removed",
                _mutate_gate(f"### {_SAFETY_GATE_HEADING}", "### Step 2 — Notes"),
                base_steps,
                f"missing `### {_SAFETY_GATE_HEADING}` inside `## {_WORKFLOW_HEADING}`",
            ),
            (
                "moved under Closeout",
                moved_to_closeout,
                base_steps,
                f"missing `### {_SAFETY_GATE_HEADING}` inside `## {_WORKFLOW_HEADING}`",
            ),
            (
                "moved after Step 9.5 inside Workflow",
                moved_after_step_95,
                base_steps,
                f"`### {_SAFETY_GATE_HEADING}` must precede `### {_STEP_95_HEADING}` in Workflow",
            ),
            (
                "gate body hidden in HTML comment",
                html_commented_gate,
                base_steps,
                "Step 2 merge-target safety gate missing stops on main or protected branch",
            ),
            (
                "gate body indented as 4-space code block",
                indented_code_gate,
                base_steps,
                "Step 2 merge-target safety gate missing stops on main or protected branch",
            ),
            (
                "STOP removed",
                _mutate_gate(", STOP —", ", warn and continue —"),
                base_steps,
                "Step 2 merge-target safety gate missing stops on main or protected branch",
            ),
            (
                "git merge prohibition removed",
                _mutate_gate("or run any\n`git merge` onto it.", "without caution."),
                base_steps,
                "Step 2 merge-target safety gate missing forbids lane dispatch and git merge",
            ),
            (
                "main target removed inside Step 2 only",
                _mutate_gate("target is `main` or a protected branch", "target is `release`"),
                base_steps,
                "Step 2 merge-target safety gate missing stops on main or protected branch",
            ),
            (
                "interactive remedy removed",
                _mutate_gate(
                    "Interactive: check out / create a dedicated feature branch first and\nre-resolve the merge target;",
                    "Interactive: proceed carefully;",
                ),
                base_steps,
                "Step 2 merge-target safety gate missing interactive feature-branch remediation",
            ),
            (
                "runner remedy removed",
                _mutate_gate(
                    "runner/adapter: the runner resolves a runner-managed branch.",
                    "runner/adapter: continue on current branch.",
                ),
                base_steps,
                "Step 2 merge-target safety gate missing runner/adapter managed-branch remediation",
            ),
            (
                "Step 7 precedence removed",
                _mutate_gate(
                    "This gate precedes Step 7's auto-merge, which would otherwise mutate `main` directly.",
                    "",
                ),
                base_steps,
                "Step 2 merge-target safety gate missing precedence over Step 7 auto-merge",
            ),
            (
                "Publication mode (c) weakened",
                base_skill.replace("never merge lanes onto `main`/protected.", "avoid merging to main.", 1),
                base_steps,
                "Publication mode missing never merge lanes onto main/protected",
            ),
            (
                "gate wrapped in closed code fence only",
                fenced_gate_only,
                base_steps,
                f"missing `### {_SAFETY_GATE_HEADING}` inside `## {_WORKFLOW_HEADING}`",
            ),
            (
                "interactive-steps back-pointer dropped",
                base_skill,
                base_steps.replace(_INTERACTIVE_STEPS_BACKPOINTER, "Continue directly to dispatch.", 1),
                "Step 2 preflight missing back-pointer",
            ),
        )
        for name, mutated_skill, mutated_steps, expected_fragment in mutations:
            with self.subTest(mutation=name):
                findings = merge_target_safety_gate_findings(
                    mutated_skill, interactive_steps_text=mutated_steps
                )
                self.assertTrue(
                    any(expected_fragment in item for item in findings),
                    f"mutation {name!r} expected finding containing {expected_fragment!r}, got {findings!r}",
                )


class ShippedReferenceLinksTest(unittest.TestCase):
    def test_every_packaged_reference_is_linked_from_its_skill_md(self) -> None:
        self.assertTrue(PACKAGED_SKILLS.is_dir(), f"missing packaged bundle {PACKAGED_SKILLS}")
        total = 0
        findings: list[str] = []
        for skill_dir in sorted(p for p in PACKAGED_SKILLS.iterdir() if p.is_dir()):
            count, skill_findings = unlinked_reference_findings_for_skill(
                skill_dir, label_root=PACKAGED_SKILLS
            )
            total += count
            findings.extend(skill_findings)
        self.assertGreaterEqual(total, 31, f"expected >= 31 packaged references, found {total}")
        self.assertEqual(findings, [], "\n".join(findings))

    def test_every_canonical_skills_src_reference_is_linked_from_its_skill_md(self) -> None:
        if not SKILLS_SRC.is_dir():
            self.skipTest("skills-src/ not present (from-wheel install); source-tree check only")
        total = 0
        findings: list[str] = []
        for harness_dir in sorted(p for p in SKILLS_SRC.iterdir() if p.is_dir()):
            for skill_dir in sorted(p for p in harness_dir.iterdir() if p.is_dir()):
                count, skill_findings = unlinked_reference_findings_for_skill(
                    skill_dir, label_root=SKILLS_SRC
                )
                total += count
                findings.extend(skill_findings)
        self.assertGreaterEqual(total, 25, f"expected >= 25 canonical references, found {total}")
        self.assertEqual(findings, [], "\n".join(findings))

    def test_every_phase_loop_skills_reference_is_linked_from_its_skill_md(self) -> None:
        if not PHASE_LOOP_SKILLS.is_dir():
            self.skipTest("phase-loop-skills/ not present (from-wheel install); source-tree check only")
        total = 0
        findings: list[str] = []
        for skill_dir in sorted(p for p in PHASE_LOOP_SKILLS.iterdir() if p.is_dir()):
            count, skill_findings = unlinked_reference_findings_for_skill(
                skill_dir, label_root=PHASE_LOOP_SKILLS
            )
            total += count
            findings.extend(skill_findings)
            overrides_dir = skill_dir / "_overrides"
            if overrides_dir.is_dir():
                for harness_override in sorted(p for p in overrides_dir.iterdir() if p.is_dir()):
                    override_skill_md = harness_override / "SKILL.md"
                    owner_md = override_skill_md if override_skill_md.is_file() else skill_dir / "SKILL.md"
                    o_count, o_findings = unlinked_reference_findings_for_skill(
                        harness_override,
                        skill_md_path=owner_md,
                        label_root=PHASE_LOOP_SKILLS,
                    )
                    total += o_count
                    findings.extend(o_findings)
        self.assertGreaterEqual(total, 25, f"expected >= 25 bundle references, found {total}")
        self.assertEqual(findings, [], "\n".join(findings))

    def test_reference_link_checker_accepts_valid_links_and_rejects_orphans_fences_and_malformed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "demo-skill"
            refs = skill / "references"
            (refs / "nested").mkdir(parents=True)
            for rel in (
                "linked.md",
                "anchored.md",
                "angle-dest.md",
                "code-span.md",
                "dot-rel.md",
                "nested/deep.md",
                "ref-full.md",
                "ref-collapsed.md",
                "ref-shortcut.md",
                "after-unclosed-list-fence.md",
                "after-comment-fence.md",
                "multiline-dest.md",
                "orphan.md",
                "fenced-top.md",
                "fenced-list.md",
                "fenced-quote.md",
                "fenced-nested-list-quote.md",
                "indented-code.md",
                "indented-after-setext.md",
                "padded-list-code.md",
                "commented-only.md",
                "prefix-only.md",
                "image-inline.md",
                "image-ref.md",
                "escaped-inline.md",
                "malformed-angle.md",
                "code-link-example.md",
                "unused-def.md",
            ):
                (refs / rel).write_text(f"# {rel}\n", encoding="utf-8")

            (skill / "SKILL.md").write_text(
                "# Demo\n\n"
                "- Read [linked](references/linked.md).\n"
                "- Jump to [section](references/anchored.md#details).\n"
                "- Angle destination [ok](<references/angle-dest.md>).\n"
                "- See `references/code-span.md` for details.\n"
                "- Also [dot](./references/dot-rel.md) and [deep](references/nested/deep.md).\n"
                "- Multiline destination [next-line](\n"
                "  references/multiline-dest.md\n"
                ").\n"
                "- Reference links: [the full guide][full-guide], [ref-collapsed][], and [ref-shortcut].\n"
                "- Wrong prefix: `other/references/prefix-only.md` and `references/prefix-only.md.bak`.\n"
                "- Inline image is not a doc link: ![img](references/image-inline.md).\n"
                "- Reference image is not a doc link: ![preview][img-ref].\n"
                "- Escaped inline link is not a link: \\[Guide](references/escaped-inline.md).\n"
                "- Malformed angle link: [bad](<references/malformed-angle.md).\n"
                "- Literal link inside code span is not a link: `[ex](references/code-link-example.md)`.\n"
                "<!-- [hidden](references/commented-only.md) `references/commented-only.md` -->\n\n"
                "    [indented-code](references/indented-code.md)\n"
                "    `references/indented-code.md`\n\n"
                "Setext Heading\n"
                "--------------\n"
                "    [indented-after-setext](references/indented-after-setext.md)\n\n"
                "-     [padded-list-code](references/padded-list-code.md)\n\n"
                "```markdown\n"
                "[top-fence](references/fenced-top.md)\n"
                "`references/fenced-top.md`\n"
                "```\n\n"
                "1. Ordered list item with an indented fenced example:\n\n"
                "    ```markdown\n"
                "    [list-fence](references/fenced-list.md)\n"
                "    `references/fenced-list.md`\n"
                "    ```\n\n"
                "> Blockquote with a fenced example:\n"
                ">\n"
                "> ~~~markdown\n"
                "> [quote-fence](references/fenced-quote.md)\n"
                "> `references/fenced-quote.md`\n"
                "> ~~~\n\n"
                "- > ~~~markdown\n"
                "  > [nested](references/fenced-nested-list-quote.md)\n"
                "  > ~~~\n\n"
                "- ~~~markdown\n"
                "  [still-inside-list-fence](references/orphan.md)\n\n"
                "Top-level prose after unclosed list fence: [ok](references/after-unclosed-list-fence.md).\n\n"
                "<!--\n"
                "```markdown\n"
                "-->\n\n"
                "Visible after comment with fence marker: [ok](references/after-comment-fence.md).\n\n"
                "[full-guide]: references/ref-full.md\n"
                "[ref-collapsed]: references/ref-collapsed.md#top\n"
                "[ref-shortcut]: <references/ref-shortcut.md>\n"
                "[img-ref]: references/image-ref.md\n"
                "[unused-def]: references/unused-def.md\n",
                encoding="utf-8",
            )

            count, findings = unlinked_reference_findings_for_skill(skill, label_root=root)
            self.assertEqual(count, 28)
            self.assertEqual(
                findings,
                [
                    "demo-skill/SKILL.md: shipped `references/code-link-example.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/commented-only.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/escaped-inline.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/fenced-list.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/fenced-nested-list-quote.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/fenced-quote.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/fenced-top.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/image-inline.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/image-ref.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/indented-after-setext.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/indented-code.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/malformed-angle.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/orphan.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/padded-list-code.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/prefix-only.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/unused-def.md` is not linked from SKILL.md",
                ],
            )


if __name__ == "__main__":
    unittest.main()
