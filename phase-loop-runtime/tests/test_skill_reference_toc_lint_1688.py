"""Mechanical TOC lint for canonical skill references (agent-harness#1688).

Enforces the agent-harness#1358 reference-index rule across all
``skills-src/<harness>/<skill>/references/*.md`` files:

1. Every reference over ``MAX_UNINDEXED_LINES`` (100) lines MUST carry a
   top-level ``## Contents`` section with at least one bullet.
2. Every bullet inside ``## Contents`` (plain heading text or Markdown anchor
   link ``[label](#slug)``) MUST match an existing non-``Contents`` heading in
   that file (following CommonMark 0.31.2 block/container/fence/HTML/Setext
   rules and GitHub section-link slug allocation).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS_SRC = REPO / "skills-src"
MAX_UNINDEXED_LINES = 100

_COMMONMARK_LINE_RE = re.compile(r"\r\n|\r|\n")
_OPEN_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})([^\r\n]*)$")
_CLOSE_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(\*[ \t]*){3,}|(-[ \t]*){3,}|(_[ \t]*){3,})$")
_TRAILING_HASHES_RE = re.compile(r"(?:^|[ \t]+)#+$")
_LIST_START_RE = re.compile(r"^( {0,3})([-*+]|(?:\d{1,9})[.)])([ \t]+|$)")
_BLOCKQUOTE_RE = re.compile(r"^ {0,3}>(.*)$")
_ANCHOR_LINK_RE = re.compile(r"^\[([^\]]+)\]\(#([^)]+)\)$")
_ASCII_WS_SPLIT_RE = re.compile(r"[ \t]+")

# CommonMark 0.31.2 §4.6 HTML block start/end rules (types 1–6).
_HTML_TYPE1_START = re.compile(r"^ {0,3}<(?:pre|script|style|textarea)(?:[ \t>]|$)", re.IGNORECASE)
_HTML_TYPE1_END = re.compile(r"</(?:pre|script|style|textarea)>", re.IGNORECASE)
_HTML_TYPE2_START = re.compile(r"^ {0,3}<!--")
_HTML_TYPE3_START = re.compile(r"^ {0,3}<\?")
_HTML_TYPE4_START = re.compile(r"^ {0,3}<![A-Za-z]")
_HTML_TYPE5_START = re.compile(r"^ {0,3}<!\[CDATA\[")
_HTML_TYPE6_START = re.compile(
    r"^ {0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|"
    r"colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|"
    r"frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|"
    r"noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|"
    r"thead|title|tr|track|ul)(?:[ \t]|$|/?>)",
    re.IGNORECASE,
)
# CommonMark 0.31.2 §4.6 HTML block type 7 (complete open/close tag alone on a line;
# cannot interrupt a paragraph; terminates on a blank line).
_HTML_TAG_NAME = r"[A-Za-z][A-Za-z0-9-]*"
_HTML_ATTR_NAME = r"[A-Za-z_:][A-Za-z0-9_.:-]*"
_HTML_ATTR_VAL = r"(?:[^ \t\"'=<>`]+|'[^']*'|\"[^\"]*\")"
_HTML_ATTR = rf"[ \t]+{_HTML_ATTR_NAME}(?:[ \t]*=[ \t]*{_HTML_ATTR_VAL})?"
_HTML_TYPE7_START = re.compile(
    rf"^ {{0,3}}(?:<{_HTML_TAG_NAME}(?:{_HTML_ATTR})*[ \t]*/?>|</{_HTML_TAG_NAME}[ \t]*>)[ \t]*$"
)

# Inline Markdown stripping patterns for GitHub heading plain-text slugging.
_INLINE_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_INLINE_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_INLINE_STRIKE_RE = re.compile(r"(?<!\\)~~(.+?)(?<!\\)~~")
_INLINE_STRONG_STAR_RE = re.compile(r"(?<!\\)\*\*(.+?)(?<!\\)\*\*")
_INLINE_EM_STAR_RE = re.compile(r"(?<!\\)\*(.+?)(?<!\\)\*")
_INLINE_STRONG_UNDER_RE = re.compile(r"(?<![\\\w])__(.+?)(?<!\\)__(?!\w)")
_INLINE_EM_UNDER_RE = re.compile(r"(?<![\\\w])_(.+?)(?<!\\)_(?!\w)")
_BACKSLASH_ESCAPE_RE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")


@dataclass(frozen=True)
class TocFinding:
    path: str
    message: str
    line: int | None = None

    def describe(self) -> str:
        where = f":{self.line}" if self.line is not None else ""
        return f"{self.path}{where}: {self.message}"


@dataclass(frozen=True)
class _Fence:
    char: str
    length: int
    indent: int
    is_markdown: bool


@dataclass(frozen=True)
class _Heading:
    line: int
    level: int
    title: str
    is_toc: bool = False


@dataclass(frozen=True)
class _ParsedDoc:
    line_count: int
    contents_lines: list[int]
    rendered_headings: list[_Heading]
    template_titles: set[str]
    toc_bullets: list[tuple[int, str]]


def _commonmark_lines(text: str) -> list[str]:
    """Split text on CommonMark 0.31.2 line endings (CRLF, CR, LF) only."""
    if not text:
        return []
    lines = _COMMONMARK_LINE_RE.split(text)
    if text.endswith(("\r\n", "\n", "\r")) and lines and lines[-1] == "":
        lines.pop()
    return lines


def _find_matching_backticks(text: str, start: int) -> tuple[int, int] | None:
    """CommonMark §6.1 code-span scan starting at a backtick run."""
    n = len(text)
    end_open = start
    while end_open < n and text[end_open] == "`":
        end_open += 1
    tick_len = end_open - start
    pos = end_open
    while pos < n:
        if text[pos] == "`":
            close_end = pos
            while close_end < n and text[close_end] == "`":
                close_end += 1
            if close_end - pos == tick_len:
                return end_open, close_end
            pos = close_end
        else:
            pos += 1
    return None


def _render_non_code_inline(fragment: str) -> str:
    text = _INLINE_LINK_RE.sub(lambda m: _heading_plain_text(m.group(1)), fragment)
    text = _INLINE_HTML_TAG_RE.sub("", text)
    return _strip_emphasis(text)


def _heading_plain_text(heading: str) -> str:
    """Render CommonMark inline spans in a heading to plain text for GitHub slugging.

    Code spans are extracted first into unique NUL-delimited placeholders (non-word,
    non-whitespace) so literal content such as ``<Widget>`` is protected from
    HTML/emphasis stripping while emphasis spanning across or adjacent to a code span
    (e.g. ``_Call `<Widget>`_`` or `` `foo`_bar_ ``) still matches across the whole
    heading.
    """
    salt = 0
    while f"\x00CODE{salt}X" in heading:
        salt += 1
    prefix = f"\x00CODE{salt}X"

    placeholders: dict[str, str] = {}
    out: list[str] = []
    i = 0
    n = len(heading)
    while i < n:
        if heading[i] == "\\" and i + 1 < n:
            out.append(heading[i : i + 2])
            i += 2
            continue
        if heading[i] == "`":
            span = _find_matching_backticks(heading, i)
            if span is not None:
                content_start, span_end = span
                tick_len = content_start - i
                code = heading[content_start : span_end - tick_len]
                if len(code) >= 2 and code.startswith(" ") and code.endswith(" ") and code.strip(" "):
                    code = code[1:-1]
                token = f"{prefix}{len(placeholders)}\x00"
                placeholders[token] = code
                out.append(token)
                i = span_end
                continue
        out.append(heading[i])
        i += 1

    rendered = _render_non_code_inline("".join(out))
    for token, literal in placeholders.items():
        rendered = rendered.replace(token, literal)
    return rendered


def _strip_emphasis(fragment: str) -> str:
    text = _INLINE_STRIKE_RE.sub(r"\1", fragment)
    text = _INLINE_STRONG_STAR_RE.sub(r"\1", text)
    text = _INLINE_EM_STAR_RE.sub(r"\1", text)
    text = _INLINE_STRONG_UNDER_RE.sub(r"\1", text)
    text = _INLINE_EM_UNDER_RE.sub(r"\1", text)
    text = _BACKSLASH_ESCAPE_RE.sub(r"\1", text)
    return text


def _github_heading_slug(heading: str) -> str:
    """Compute GitHub-style Markdown anchor slug for a heading title."""
    cleaned = _heading_plain_text(heading).strip().lower()
    out: list[str] = []
    for ch in cleaned:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        elif ch == " ":
            out.append("-")
    return "".join(out)


def _strip_atx_heading(raw_title: str) -> str:
    title = raw_title.strip(" \t")
    title = _TRAILING_HASHES_RE.sub("", title).strip(" \t")
    return title


def _leading_columns(line: str, start_col: int = 0) -> int:
    """Count leading indentation columns (tabs expand to 4-column stops per CommonMark)."""
    cols = start_col
    for ch in line:
        if ch == " ":
            cols += 1
        elif ch == "\t":
            cols += 4 - (cols % 4)
        else:
            break
    return cols - start_col


def _strip_leading_columns(line: str, max_cols: int, start_col: int = 0) -> str:
    """Strip up to ``max_cols`` leading whitespace columns, expanding partial tabs to spaces."""
    cols = start_col
    idx = 0
    target = start_col + max_cols
    while idx < len(line) and cols < target:
        ch = line[idx]
        if ch == " ":
            cols += 1
            idx += 1
        elif ch == "\t":
            tab_end = cols + (4 - (cols % 4))
            idx += 1
            if tab_end > target:
                return (" " * (tab_end - target)) + line[idx:]
            cols = tab_end
        else:
            break
    return line[idx:]


def _strip_leading_spaces(line: str, max_spaces: int) -> str:
    removed = 0
    while removed < max_spaces and removed < len(line) and line[removed] == " ":
        removed += 1
    return line[removed:]


def _fence_language(info: str) -> str:
    stripped = info.strip(" \t")
    if not stripped:
        return ""
    return _ASCII_WS_SPLIT_RE.split(stripped, maxsplit=1)[0].lower()


def _html_block_end_kind(line: str, *, allow_type7: bool = True) -> str | None:
    if _HTML_TYPE1_START.match(line):
        return "type1"
    if _HTML_TYPE2_START.match(line):
        return "type2"
    if _HTML_TYPE3_START.match(line):
        return "type3"
    if _HTML_TYPE4_START.match(line):
        return "type4"
    if _HTML_TYPE5_START.match(line):
        return "type5"
    if _HTML_TYPE6_START.match(line):
        return "type6"
    if allow_type7 and _HTML_TYPE7_START.match(line):
        return "type6"
    return None


def _starts_non_paragraph_block(line: str) -> bool:
    """Return True if ``line`` begins a non-paragraph block at container/block start."""
    if not line.strip(" \t"):
        return True
    if _leading_columns(line) >= 4:
        return True
    if _ATX_HEADING_RE.match(line) or _THEMATIC_BREAK_RE.match(line) or _BLOCKQUOTE_RE.match(line):
        return True
    open_match = _OPEN_FENCE_RE.match(line)
    if open_match and not (open_match.group(2)[0] == "`" and "`" in open_match.group(3)):
        return True
    if _html_block_end_kind(line, allow_type7=True) is not None:
        return True
    if _LIST_START_RE.match(line):
        return True
    return False


def _line_interrupts_paragraph(line: str) -> bool:
    """Return True if ``line`` can interrupt a CommonMark paragraph (not blank, not lazy continuation)."""
    if not line.strip(" \t"):
        return True
    if _ATX_HEADING_RE.match(line) or _THEMATIC_BREAK_RE.match(line) or _BLOCKQUOTE_RE.match(line):
        return True
    open_match = _OPEN_FENCE_RE.match(line)
    if open_match and not (open_match.group(2)[0] == "`" and "`" in open_match.group(3)):
        return True
    if _html_block_end_kind(line, allow_type7=False) is not None:
        return True
    list_match = _LIST_START_RE.match(line)
    if list_match:
        marker = list_match.group(2)
        after_marker = line[list_match.end() :]
        # Per CommonMark §5.2: an empty list item cannot interrupt a paragraph, and an
        # ordered list item can interrupt a paragraph ONLY when its start number is 1.
        if not after_marker.strip(" \t"):
            return False
        if marker not in {"-", "*", "+"} and int(marker[:-1]) != 1:
            return False
        return True
    return False


def _html_block_closed(kind: str, line: str) -> bool:
    if kind == "type1":
        return bool(_HTML_TYPE1_END.search(line))
    if kind == "type2":
        return "-->" in line
    if kind == "type3":
        return "?>" in line
    if kind == "type4":
        return ">" in line
    if kind == "type5":
        return "]]>" in line
    return False


def _strip_blockquote_marker(line: str) -> str:
    match = _BLOCKQUOTE_RE.match(line)
    assert match is not None
    rest = match.group(1)
    if rest.startswith(" "):
        return rest[1:]
    if rest.startswith("\t"):
        # Per CommonMark §5.1, a tab after '>' expands to column 4; stripping 1 optional space leaves 2 or 3 spaces.
        col_after_gt = line.index(">") + 1
        expanded = 4 - (col_after_gt % 4)
        return (" " * max(expanded - 1, 0)) + rest[1:]
    return rest


def _parse_document(
    text: str,
    *,
    top_level: bool = True,
    collect_templates: bool = True,
    collect_nested_bullets: bool = False,
    line_offset: int = 0,
) -> _ParsedDoc:
    """Parse one CommonMark 0.31.2 document using recursive containers and two-pass fences.

    - Outer fenced code blocks are scanned without interpreting inner fence syntax, so an
      unclosed inner fence inside a Markdown template can never hide outer headings.
    - Outer ``markdown``/``md`` fenced blocks are dedented by the opening fence's leading
      spaces (CommonMark §4.5) and parsed in Pass 2 (``collect_templates=False``) for
      plain template heading titles (never rendered anchor slugs).
    - Blockquotes and list items recursively invoke ``_parse_document(..., top_level=False)``
      so fences, HTML comments, Setext headings, and real headings inside containers all
      follow exact CommonMark rules while never falsely satisfying the top-level
      ``## Contents`` requirement.
    """
    lines = _commonmark_lines(text)
    outer_fence: _Fence | None = None
    fence_lines: list[str] = []
    html_block: str | None = None
    in_contents = False
    para_lines: list[tuple[int, str]] = []

    contents_lines: list[int] = []
    rendered_headings: list[_Heading] = []
    template_titles: set[str] = set()
    toc_bullets: list[tuple[int, str]] = []

    def _flush_markdown_template(fence: _Fence, raw_lines: list[str]) -> None:
        if not collect_templates or not fence.is_markdown:
            return
        dedented = "\n".join(_strip_leading_spaces(item, fence.indent) for item in raw_lines)
        inner = _parse_document(dedented, top_level=False, collect_templates=False)
        for heading in inner.rendered_headings:
            template_titles.add(heading.title)

    def _record_heading(lineno: int, level: int, title: str) -> None:
        nonlocal in_contents
        if top_level and level == 2 and title == "Contents":
            contents_lines.append(lineno)
            rendered_headings.append(_Heading(lineno, level, title, is_toc=True))
            in_contents = len(contents_lines) == 1
            return
        if top_level:
            in_contents = False
        if title:
            rendered_headings.append(_Heading(lineno, level, title, is_toc=False))

    i = 0
    total = len(lines)
    while i < total:
        line = lines[i]
        lineno = line_offset + i + 1

        # 1. Active outer fenced code block (CommonMark §4.5).
        if outer_fence is not None:
            close_match = _CLOSE_FENCE_RE.match(line)
            if close_match:
                run = close_match.group(1)
                if run[0] == outer_fence.char and len(run) >= outer_fence.length:
                    _flush_markdown_template(outer_fence, fence_lines)
                    outer_fence = None
                    fence_lines = []
                    i += 1
                    continue
            fence_lines.append(line)
            i += 1
            continue

        # 2. Active HTML block (CommonMark §4.6).
        if html_block is not None:
            if html_block == "type6":
                if not line.strip(" \t"):
                    html_block = None
                i += 1
                continue
            if _html_block_closed(html_block, line):
                html_block = None
            i += 1
            continue

        # 3. Blank line closes any open paragraph.
        if not line.strip(" \t"):
            para_lines.clear()
            i += 1
            continue

        # 4. Setext heading underline (CommonMark §4.3) when a paragraph is open.
        if para_lines:
            setext_match = _SETEXT_UNDERLINE_RE.match(line)
            if setext_match:
                level = 1 if setext_match.group(1)[0] == "=" else 2
                title = " ".join(part.strip(" \t") for _, part in para_lines)
                start_line = para_lines[0][0]
                para_lines.clear()
                _record_heading(start_line, level, title)
                i += 1
                continue

        indent = _leading_columns(line)

        # 5. Indented code block (CommonMark §4.4): >= 4 columns outside a paragraph.
        if indent >= 4 and not para_lines:
            i += 1
            continue

        # 6. Opening fenced code block (does NOT end ## Contents; bullets after the fence still lint).
        open_match = _OPEN_FENCE_RE.match(line)
        if open_match:
            lead, run, info = open_match.group(1), open_match.group(2), open_match.group(3)
            if not (run[0] == "`" and "`" in info):
                para_lines.clear()
                lang = _fence_language(info)
                outer_fence = _Fence(
                    char=run[0],
                    length=len(run),
                    indent=len(lead),
                    is_markdown=lang in {"markdown", "md"},
                )
                fence_lines = []
                i += 1
                continue

        # 7. HTML block start (CommonMark §4.6; type 7 cannot interrupt a paragraph).
        html_kind = _html_block_end_kind(line, allow_type7=not para_lines)
        if html_kind is not None:
            para_lines.clear()
            if html_kind == "type6" or not _html_block_closed(html_kind, line):
                html_block = html_kind
            i += 1
            continue

        # 8. Blockquote container (CommonMark §5.1): recurse with top_level=False.
        if _BLOCKQUOTE_RE.match(line):
            para_lines.clear()
            quote_start = i
            quote_lines: list[str] = []
            while i < total and _BLOCKQUOTE_RE.match(lines[i]):
                quote_lines.append(_strip_blockquote_marker(lines[i]))
                i += 1
            nested = _parse_document(
                "\n".join(quote_lines),
                top_level=False,
                collect_templates=collect_templates,
                line_offset=line_offset + quote_start,
            )
            rendered_headings.extend(nested.rendered_headings)
            template_titles.update(nested.template_titles)
            continue

        # 9. ATX heading (CommonMark §4.2).
        atx_match = _ATX_HEADING_RE.match(line)
        if atx_match:
            para_lines.clear()
            level = len(atx_match.group(1))
            title = _strip_atx_heading(atx_match.group(2) or "")
            _record_heading(lineno, level, title)
            i += 1
            continue

        # 10. Thematic break (CommonMark §4.1).
        if _THEMATIC_BREAK_RE.match(line):
            para_lines.clear()
            i += 1
            continue

        # 11. List item container (CommonMark §5.2): collect full item body and recurse.
        list_match = _LIST_START_RE.match(line)
        if list_match:
            para_lines.clear()
            item_start = i
            lead, marker, sep = list_match.group(1), list_match.group(2), list_match.group(3)
            marker_end_col = len(lead) + len(marker)
            after_marker = line[marker_end_col:]
            ws_cols = _leading_columns(after_marker, start_col=marker_end_col)
            rest_after_ws = after_marker.lstrip(" \t")
            if not rest_after_ws or ws_cols >= 5:
                content_indent = marker_end_col + 1
                first_body_line = _strip_leading_columns(after_marker, 1, start_col=marker_end_col)
            else:
                content_indent = marker_end_col + ws_cols
                first_body_line = rest_after_ws

            is_bullet_item = marker in {"-", "*", "+"}
            capture_bullet = (in_contents or collect_nested_bullets) and is_bullet_item

            item_lines: list[str] = [first_body_line]
            lazy_indices: set[int] = set()
            first_para_open = bool(rest_after_ws) and not _starts_non_paragraph_block(first_body_line)
            i += 1
            pending_blanks: list[str] = []
            while i < total:
                next_line = lines[i]
                if not next_line.strip(" \t"):
                    pending_blanks.append("")
                    first_para_open = False
                    i += 1
                    continue
                if _leading_columns(next_line) >= content_indent:
                    item_lines.extend(pending_blanks)
                    pending_blanks.clear()
                    stripped_next = _strip_leading_columns(next_line, content_indent)
                    if first_para_open and (
                        _line_interrupts_paragraph(stripped_next) or _SETEXT_UNDERLINE_RE.match(stripped_next)
                    ):
                        first_para_open = False
                    item_lines.append(stripped_next)
                    i += 1
                    continue
                # CommonMark §5.2 lazy paragraph continuation line (only while the first paragraph is still open).
                if first_para_open and not pending_blanks and not _line_interrupts_paragraph(next_line):
                    lazy_indices.add(len(item_lines))
                    item_lines.append(next_line.strip(" \t"))
                    i += 1
                    continue
                break
            # Rewind trailing blank lines that were not followed by indented item content.
            i -= len(pending_blanks)

            if capture_bullet and rest_after_ws:
                if _starts_non_paragraph_block(first_body_line):
                    bullet_text = rest_after_ws.strip(" \t")
                else:
                    para_parts: list[str] = [item_lines[0].strip(" \t")]
                    for idx, cont in enumerate(item_lines[1:], start=1):
                        if idx not in lazy_indices and (
                            not cont.strip(" \t")
                            or _line_interrupts_paragraph(cont)
                            or _SETEXT_UNDERLINE_RE.match(cont)
                        ):
                            break
                        para_parts.append(cont.strip(" \t"))
                    bullet_text = " ".join(part for part in para_parts if part)
                toc_bullets.append((lineno, bullet_text))

            # CommonMark §4.3: a Setext heading underline cannot be a lazy continuation line.
            nested_lines = [
                ("\\" + ln if (idx in lazy_indices and _SETEXT_UNDERLINE_RE.match(ln)) else ln)
                for idx, ln in enumerate(item_lines)
            ]
            nested = _parse_document(
                "\n".join(nested_lines),
                top_level=False,
                collect_templates=collect_templates,
                collect_nested_bullets=capture_bullet,
                line_offset=line_offset + item_start,
            )
            rendered_headings.extend(nested.rendered_headings)
            template_titles.update(nested.template_titles)
            if capture_bullet:
                toc_bullets.extend(nested.toc_bullets)
            continue

        # 12. Ordinary paragraph line (candidate for a following Setext underline).
        para_lines.append((lineno, line))
        i += 1

    # Unclosed trailing markdown fence still parses its inner lines per CommonMark §4.5.
    if outer_fence is not None:
        _flush_markdown_template(outer_fence, fence_lines)

    return _ParsedDoc(
        line_count=len(lines),
        contents_lines=contents_lines,
        rendered_headings=rendered_headings,
        template_titles=template_titles,
        toc_bullets=toc_bullets,
    )


def reference_toc_findings(text: str, label: str) -> list[TocFinding]:
    """Validate TOC presence (>100 lines) and bullet-to-heading agreement for one file."""
    doc = _parse_document(text, top_level=True, collect_templates=True)
    findings: list[TocFinding] = []

    if doc.line_count > MAX_UNINDEXED_LINES and not doc.contents_lines:
        findings.append(
            TocFinding(
                label,
                f"reference has {doc.line_count} lines (> {MAX_UNINDEXED_LINES}) without a top-level '## Contents' section",
            )
        )
        return findings

    if len(doc.contents_lines) > 1:
        findings.append(
            TocFinding(
                label,
                f"duplicate top-level '## Contents' heading (first at line {doc.contents_lines[0]})",
                line=doc.contents_lines[1],
            )
        )

    if doc.contents_lines and not doc.toc_bullets:
        findings.append(
            TocFinding(
                label,
                "'## Contents' section has no bullet items",
                line=doc.contents_lines[0],
            )
        )
        return findings

    # GitHub-style slug allocation across ALL rendered headings in document order
    # (including top-level ## Contents so a later `### Contents` receives `#contents-1`
    # while `#contents` points only to the TOC itself). Template headings from fenced
    # markdown blocks never produce rendered anchors.
    used_slugs: set[str] = set()
    target_titles: set[str] = set(doc.template_titles)
    target_slugs: set[str] = set()
    for heading in doc.rendered_headings:
        base = _github_heading_slug(heading.title)
        slug = base
        suffix = 1
        while slug in used_slugs:
            slug = f"{base}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        if not heading.is_toc:
            target_titles.add(heading.title)
            target_slugs.add(slug)

    for lineno, bullet in doc.toc_bullets:
        link_match = _ANCHOR_LINK_RE.match(bullet)
        if link_match:
            anchor = link_match.group(2).strip().lower()
            if anchor not in target_slugs:
                findings.append(
                    TocFinding(
                        label,
                        f"## Contents anchor '#{anchor}' does not match any rendered heading in this file",
                        line=lineno,
                    )
                )
            continue
        if bullet == "Contents":
            findings.append(
                TocFinding(
                    label,
                    "## Contents plain bullet 'Contents' is self-referential "
                    "(use an explicit '#contents-1' anchor link if targeting a later heading)",
                    line=lineno,
                )
            )
            continue
        if bullet not in target_titles:
            findings.append(
                TocFinding(
                    label,
                    f"## Contents bullet {bullet!r} does not match any heading in this file",
                    line=lineno,
                )
            )

    return findings


def canonical_reference_files(root: Path = SKILLS_SRC) -> list[Path]:
    return sorted(root.glob("*/*/references/*.md"))


def _clean_git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    return env


def _is_sparse_checkout(repo: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "config", "--bool", "core.sparseCheckout"],
            capture_output=True,
            text=True,
            check=False,
            env=_clean_git_env(),
        )
        return proc.returncode == 0 and proc.stdout.strip().lower() == "true"
    except OSError:
        return False


def _has_full_skills_src(repo: Path = REPO) -> bool:
    """True only for a full repository checkout (never Gate A's sparse tree)."""
    root = repo / "skills-src"
    return (
        not _is_sparse_checkout(repo)
        and (repo / "phase-loop-skills").is_dir()
        and all((root / harness).is_dir() for harness in ("claude", "codex", "gemini", "opencode"))
    )


_NEEDS_FULL_SKILLS_SRC = unittest.skipUnless(
    _has_full_skills_src(),
    "lints the full canonical skills-src tree; sparse Gate A and wheel-only trees omit it",
)


class SkillReferenceTocLintTest(unittest.TestCase):
    @_NEEDS_FULL_SKILLS_SRC
    def test_canonical_skill_references_satisfy_toc_lint(self) -> None:
        files = canonical_reference_files()
        self.assertTrue(files, "no skills-src/*/*/references/*.md files found")
        errors: list[str] = []
        for path in files:
            label = path.relative_to(REPO).as_posix()
            text = path.read_bytes().decode("utf-8")
            for finding in reference_toc_findings(text, label):
                errors.append(finding.describe())
        self.assertEqual(errors, [], "\n".join(errors))

    def test_over_100_lines_without_contents_fails(self) -> None:
        text = "# Long Reference\n\n## Alpha\n" + ("body line\n" * 100)
        findings = reference_toc_findings(text, "fixture/long.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("without a top-level '## Contents'", findings[0].message)

    def test_at_or_under_100_lines_without_contents_passes(self) -> None:
        text = "# Short Reference\n\n## Alpha\n" + ("body line\n" * 97)
        self.assertEqual(len(_commonmark_lines(text)), 100)
        self.assertEqual(reference_toc_findings(text, "fixture/short.md"), [])

    def test_drifted_plain_bullet_and_broken_anchor_fail(self) -> None:
        text = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Real heading\n"
            "- Stale bullet\n"
            "- [Real link](#real-heading)\n"
            "- [Broken link](#missing-heading)\n\n"
            "## Real heading\n"
            "Body.\n"
        )
        findings = reference_toc_findings(text, "fixture/drifted.md")
        messages = [f.message for f in findings]
        self.assertEqual(len(findings), 2, messages)
        self.assertTrue(any("Stale bullet" in m for m in messages), messages)
        self.assertTrue(any("#missing-heading" in m for m in messages), messages)

    def test_commonmark_non_rendered_structures_do_not_satisfy_toc(self) -> None:
        # 1. Four-space-indented '- Real' is an indented code block, not a bullet.
        indented_bullet = "# Ref\n\n## Contents\n\n    - Real\n\n## Real\n"
        findings = reference_toc_findings(indented_bullet, "fixture/indented.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("no bullet items", findings[0].message)

        # 2. Heading inside an HTML comment (top-level or inside a list item) does not satisfy TOC.
        html_comment = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Ghost\n"
            "- [Ghost](#ghost)\n\n"
            "<!--\n## Ghost\n-->\n"
        )
        findings = reference_toc_findings(html_comment, "fixture/html-comment.md")
        self.assertEqual(len(findings), 2)

        list_html_comment = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [Ghost](#ghost)\n\n"
            "## Body\n\n"
            "- item\n\n"
            "  <!--\n"
            "  ## Ghost\n"
            "  -->\n"
        )
        findings = reference_toc_findings(list_html_comment, "fixture/list-html-comment.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("#ghost", findings[0].message)

        # 3. Bash fence opening directly on a list marker (`- ```bash`) hides `# Ghost`.
        list_inline_fence = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [Ghost](#ghost)\n\n"
            "## Body\n\n"
            "- ```bash\n"
            "  # Ghost\n"
            "  ```\n"
        )
        findings = reference_toc_findings(list_inline_fence, "fixture/list-inline-fence.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("#ghost", findings[0].message)

        # 4. '## Contents' nested inside a list item or blockquote does not satisfy >100-line requirement.
        list_contents = (
            "# Long Ref\n\n"
            "- item\n\n"
            "  ## Contents\n\n"
            "  - Alpha\n\n"
            "## Alpha\n"
            + ("body line\n" * 100)
        )
        findings = reference_toc_findings(list_contents, "fixture/list-contents.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("without a top-level '## Contents'", findings[0].message)

        quote_contents = (
            "# Long Ref\n\n"
            "> ## Contents\n"
            "> - Alpha\n\n"
            "## Alpha\n"
            + ("body line\n" * 100)
        )
        findings = reference_toc_findings(quote_contents, "fixture/quote-contents.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("without a top-level '## Contents'", findings[0].message)

        # 5. Broken bullet AFTER a fenced block inside ## Contents is still checked.
        after_fence = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Alpha\n\n"
            "```text\nexample\n```\n\n"
            "- Broken after fence\n\n"
            "## Alpha\n"
        )
        findings = reference_toc_findings(after_fence, "fixture/after-fence.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("Broken after fence", findings[0].message)

        # 6. Valid Setext headings (including Setext level-2 Contents) are recognized.
        setext = (
            "Title\n=====\n\n"
            "Contents\n--------\n\n"
            "- Setext Section\n"
            "- [Setext Section](#setext-section)\n\n"
            "Setext Section\n--------------\n"
            "Body.\n"
        )
        self.assertEqual(reference_toc_findings(setext, "fixture/setext.md"), [])

        # 7. Type-7 raw HTML block (`<widget>`) hides `## Ghost` inside it.
        html_type7 = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [Ghost](#ghost)\n\n"
            "<widget>\n"
            "## Ghost\n"
            "</widget>\n"
        )
        findings = reference_toc_findings(html_type7, "fixture/html-type7.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("#ghost", findings[0].message)

        # 8. Wrapped TOC bullets validate the full rendered bullet text (both indented and lazy wrap).
        wrapped_stale = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Real\n"
            "  stale words\n\n"
            "## Real\n"
        )
        findings = reference_toc_findings(wrapped_stale, "fixture/wrapped-stale.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("Real stale words", findings[0].message)

        wrapped_match = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Real\n"
            "  stale words\n\n"
            "## Real stale words\n"
        )
        self.assertEqual(reference_toc_findings(wrapped_match, "fixture/wrapped-match.md"), [])

        lazy_wrapped_match = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Real\n"
            "lazy words\n\n"
            "## Real lazy words\n"
        )
        self.assertEqual(reference_toc_findings(lazy_wrapped_match, "fixture/lazy-wrapped-match.md"), [])

        # 9. Ordered list starting at 2 (`2. extra`) cannot interrupt a bullet's paragraph.
        ordered_wrap_stale = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Real\n"
            "  2. extra\n\n"
            "## Real\n"
        )
        findings = reference_toc_findings(ordered_wrap_stale, "fixture/ordered-wrap-stale.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("Real 2. extra", findings[0].message)

        # 10. Raw HTML type-7 block inside a list item (`- <widget>`) ends with the list item;
        # unindented `Contents\n---` starts a valid top-level Setext TOC.
        after_html_list_item = (
            "# Ref\n\n"
            "- <widget>\n"
            "Contents\n"
            "---\n\n"
            "- Real\n\n"
            "## Real\n"
            + ("body line\n" * 100)
        )
        self.assertEqual(reference_toc_findings(after_html_list_item, "fixture/after-html-list.md"), [])

    def test_anchor_slug_allocation_emphasis_blockquotes_and_template_separation(self) -> None:
        # 1. Heading inside an md template satisfies plain bullet, NEVER #anchor.
        tpl_anchor = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Example\n"
            "- [Example](#example)\n\n"
            "```md\n"
            "## Example\n"
            "```\n"
        )
        findings = reference_toc_findings(tpl_anchor, "fixture/tpl-anchor.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("#example", findings[0].message)

        # 2. Emphasis markers (`_Real_`, `*Star*`, `**Bold**`) strip cleanly while
        # intraword underscores (`foo_bar`) and code-span literals (``Call `<Widget>` ``)
        # are preserved; blockquote headings (`> ## Quoted`) resolve.
        formatted = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [Real](#real)\n"
            "- [Star](#star)\n"
            "- [Bold](#bold)\n"
            "- [Snake](#foo_bar)\n"
            "- [Widget](#call-widget)\n"
            "- [EmphWidget](#emph-widget)\n"
            "- [Adjacent](#foobar)\n"
            "- [Quoted](#quoted)\n\n"
            "## _Real_\n\n"
            "## *Star*\n\n"
            "## **Bold**\n\n"
            "## foo_bar\n\n"
            "## Call `<Widget>`\n\n"
            "## _Emph `<Widget>`_ \n\n"
            "## `foo`_bar_\n\n"
            "> ## Quoted\n"
        )
        self.assertEqual(reference_toc_findings(formatted, "fixture/formatted.md"), [])

        # 3. ## Foo, ## Foo-1, ## Foo allocates #foo, #foo-1, #foo-2 (skipping collision).
        dedup = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [First](#foo)\n"
            "- [Middle](#foo-1)\n"
            "- [Third](#foo-2)\n\n"
            "## Foo\n\n## Foo-1\n\n## Foo\n"
        )
        self.assertEqual(reference_toc_findings(dedup, "fixture/dedup.md"), [])

        # 4. With a later ### Contents, BOTH plain `- Contents` and `#contents` are rejected,
        # while explicit `#contents-1` targets the later ### Contents (accepted).
        later_contents_bad = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Contents\n"
            "- [TOC self](#contents)\n\n"
            "### Contents\n"
        )
        findings = reference_toc_findings(later_contents_bad, "fixture/later-contents-bad.md")
        self.assertEqual(len(findings), 2)

        later_contents_ok = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [Later contents](#contents-1)\n\n"
            "### Contents\n"
        )
        self.assertEqual(reference_toc_findings(later_contents_ok, "fixture/later-contents-ok.md"), [])

    def test_fence_edge_cases_indentation_unclosed_inner_and_unicode_info_strings(self) -> None:
        # 1. Unclosed ~~~bash inside ````markdown does NOT hide headings after ````.
        unclosed_inner = (
            "# Template Ref\n\n"
            "## Contents\n\n"
            "- Context\n"
            "- After Template\n\n"
            "````markdown\n"
            "## Context\n"
            "~~~bash\n"
            "# Shell comment\n"
            "````\n\n"
            "## After Template\n"
        )
        self.assertEqual(reference_toc_findings(unclosed_inner, "fixture/unclosed-inner.md"), [])

        # 2. Indented outer ````markdown (both top-level and list-nested) strips up to
        # opening fence indentation before inner parse.
        top_indented_tpl = (
            "# Template Ref\n\n"
            "## Contents\n\n"
            "- Indented Heading\n\n"
            "Template:\n\n"
            "   ````markdown\n"
            "      ## Indented Heading\n"
            "   ````\n"
        )
        # 6 spaces minus 3 opening spaces = 3 spaces -> valid ATX heading in CommonMark.
        self.assertEqual(reference_toc_findings(top_indented_tpl, "fixture/top-indented-tpl.md"), [])

        list_indented_tpl = (
            "# Template Ref\n\n"
            "## Contents\n\n"
            "- Indented Heading\n\n"
            "   ````markdown\n"
            "      ## Indented Heading\n"
            "   ````\n"
        )
        self.assertEqual(reference_toc_findings(list_indented_tpl, "fixture/list-indented-tpl.md"), [])

        # 3. Info strings with only \v or \u00a0 do not crash with IndexError.
        for info_ws in ("\v", "\u00a0"):
            text = (
                "# Ref\n\n"
                "## Contents\n\n"
                "- Real\n\n"
                f"```{info_ws}\n"
                "# Ignored\n"
                "```\n\n"
                "## Real\n"
            )
            self.assertEqual(reference_toc_findings(text, f"fixture/info-{ord(info_ws)}.md"), [])

        # 4. Closing fences with trailing \u00a0, \v, or \f do not close the fence.
        for bad_suffix in ("\u00a0", "\v", "\f"):
            unclosed = (
                "# Ref\n\n"
                "## Contents\n\n"
                "- Trapped heading\n\n"
                "```bash\n"
                "echo hi\n"
                f"```{bad_suffix}\n"
                "## Trapped heading\n"
            )
            findings = reference_toc_findings(unclosed, f"fixture/unclosed-{ord(bad_suffix)}.md")
            self.assertEqual(len(findings), 1, f"expected unclosed fence for U+{ord(bad_suffix):04X}")

    def test_empty_duplicate_and_self_referential_contents_fail(self) -> None:
        empty = "# Ref\n\n## Contents\n\n## Alpha\n"
        findings = reference_toc_findings(empty, "fixture/empty.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("no bullet items", findings[0].message)

        dup = "# Ref\n\n## Contents\n\n- Alpha\n\n## Contents\n\n- Alpha\n\n## Alpha\n"
        findings = reference_toc_findings(dup, "fixture/dup.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("duplicate", findings[0].message)

        self_ref = "# Ref\n\n## Contents\n\n- Contents\n- [Contents](#contents)\n\n## Alpha\n"
        findings = reference_toc_findings(self_ref, "fixture/self-ref.md")
        self.assertEqual(len(findings), 2)

    def test_full_skills_src_guard_skips_sparse_and_absent_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Sparse-like layout with all 4 provider dirs but no phase-loop-skills/: skipped.
            for harness in ("claude", "codex", "gemini", "opencode"):
                (root / "skills-src" / harness).mkdir(parents=True)
            self.assertFalse(_has_full_skills_src(root))

            # Full non-sparse layout with phase-loop-skills/ and all 4 provider dirs: enabled.
            (root / "phase-loop-skills").mkdir()
            self.assertTrue(_has_full_skills_src(root))

            # Git sparse-checkout layout (even if phase-loop-skills/ exists): skipped.
            git_env = _clean_git_env()
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "init", "-q"],
                cwd=root,
                check=True,
                capture_output=True,
                env=git_env,
            )
            subprocess.run(
                ["git", "config", "core.sparseCheckout", "true"],
                cwd=root,
                check=True,
                capture_output=True,
                env=git_env,
            )
            self.assertFalse(_has_full_skills_src(root))

    def test_canonical_reference_files_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ref = Path(td) / "claude" / "claude-sample" / "references" / "guide.md"
            ref.parent.mkdir(parents=True)
            ref.write_text("# Guide\n", encoding="utf-8")
            self.assertEqual(canonical_reference_files(Path(td)), [ref])
