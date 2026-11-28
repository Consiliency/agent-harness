"""Mechanical TOC lint for canonical skill references (agent-harness#1688).

Enforces the agent-harness#1358 reference-index rule across all
``skills-src/<harness>/<skill>/references/*.md`` files:

1. Every reference over ``MAX_UNINDEXED_LINES`` (100) lines MUST carry a
   top-level ``## Contents`` section with at least one bullet.
2. Every bullet inside ``## Contents`` (plain heading text or Markdown anchor
   link ``[label](#slug)``) MUST match an existing non-``Contents`` heading in
   that file (following CommonMark 0.31.2 block/fence/HTML/Setext rules and
   GitHub section-link slug allocation).
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
_BULLET_ITEM_RE = re.compile(r"^( {0,3})([-*+])([ \t]+)(.+?)[ \t]*$")
_LIST_START_RE = re.compile(r"^( {0,3})(?:[-*+]|(\d{1,9})[.)])([ \t]+|$)")
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
    list_prefix: int = 0


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


def _github_heading_slug(heading: str) -> str:
    """Compute GitHub-style Markdown anchor slug for a heading title."""
    cleaned = heading.replace("`", "").strip().lower()
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


def _leading_columns(line: str) -> int:
    """Count leading indentation columns (tabs expand to 4-column stops per CommonMark)."""
    cols = 0
    for ch in line:
        if ch == " ":
            cols += 1
        elif ch == "\t":
            cols += 4 - (cols % 4)
        else:
            break
    return cols


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


def _html_block_end_kind(line: str) -> str | None:
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
    return None


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


def _parse_document(text: str, *, collect_templates: bool = True) -> _ParsedDoc:
    """Parse one CommonMark 0.31.2 document using a two-pass fence strategy.

    Pass 1 tracks a single outer fenced block so inner fence syntax (even an
    unclosed fence inside a template) can never prevent the outer closing fence
    from closing the block. When an outer ``markdown``/``md`` fenced block ends,
    its lines are dedented by the opening fence's indentation (CommonMark §4.5)
    and parsed in Pass 2 (``collect_templates=False``) for template headings.
    """
    lines = _commonmark_lines(text)
    outer_fence: _Fence | None = None
    fence_lines: list[str] = []
    html_block: str | None = None
    list_indent: int | None = None
    in_contents = False
    contents_list_indent: int | None = None
    para_lines: list[tuple[int, str]] = []

    contents_lines: list[int] = []
    rendered_headings: list[_Heading] = []
    template_titles: set[str] = set()
    toc_bullets: list[tuple[int, str]] = []

    def _flush_markdown_template(fence: _Fence, raw_lines: list[str]) -> None:
        if not collect_templates or not fence.is_markdown:
            return
        dedented = "\n".join(_strip_leading_spaces(item, fence.indent) for item in raw_lines)
        inner = _parse_document(dedented, collect_templates=False)
        for heading in inner.rendered_headings:
            template_titles.add(heading.title)

    def _record_heading(lineno: int, level: int, title: str, *, top_level: bool) -> None:
        nonlocal in_contents, contents_list_indent
        if top_level and level == 2 and title == "Contents":
            contents_lines.append(lineno)
            rendered_headings.append(_Heading(lineno, level, title, is_toc=True))
            in_contents = len(contents_lines) == 1
            contents_list_indent = None
            return
        if top_level:
            in_contents = False
            contents_list_indent = None
        if title:
            rendered_headings.append(_Heading(lineno, level, title, is_toc=False))

    for lineno, line in enumerate(lines, start=1):
        # 1. Active outer fenced code block (CommonMark §4.5).
        if outer_fence is not None:
            if outer_fence.list_prefix > 0 and line.strip(" \t") and _leading_columns(line) < outer_fence.list_prefix:
                _flush_markdown_template(outer_fence, fence_lines)
                outer_fence = None
                fence_lines = []
                list_indent = None
                contents_list_indent = None
            else:
                effective = _strip_leading_spaces(line, outer_fence.list_prefix) if outer_fence.list_prefix else line
                close_match = _CLOSE_FENCE_RE.match(effective)
                if close_match:
                    run = close_match.group(1)
                    if run[0] == outer_fence.char and len(run) >= outer_fence.length:
                        _flush_markdown_template(outer_fence, fence_lines)
                        outer_fence = None
                        fence_lines = []
                        continue
                fence_lines.append(effective)
                continue

        # 2. Active HTML block (CommonMark §4.6).
        if html_block is not None:
            if html_block == "type6":
                if not line.strip(" \t"):
                    html_block = None
                continue
            if _html_block_closed(html_block, line):
                html_block = None
            continue

        # 3. Blank line resets paragraph (and keeps loose list context alive).
        if not line.strip(" \t"):
            para_lines.clear()
            continue

        indent = _leading_columns(line)

        # 4. Setext heading underline (CommonMark §4.3) when a top-level paragraph is open.
        if para_lines and list_indent is None:
            setext_match = _SETEXT_UNDERLINE_RE.match(line)
            if setext_match:
                level = 1 if setext_match.group(1)[0] == "=" else 2
                title = " ".join(part.strip(" \t") for _, part in para_lines)
                start_line = para_lines[0][0]
                para_lines.clear()
                _record_heading(start_line, level, title, top_level=True)
                continue

        # 5. Track list-item nesting so indented content inside a list item is not top-level.
        if list_indent is not None:
            if indent >= list_indent:
                para_lines.clear()
                inner_line = _strip_leading_spaces(line, list_indent)
                # Fenced code block nested inside a list item.
                nested_fence = _OPEN_FENCE_RE.match(inner_line)
                if nested_fence:
                    lead, run, info = nested_fence.group(1), nested_fence.group(2), nested_fence.group(3)
                    if not (run[0] == "`" and "`" in info):
                        lang = _fence_language(info)
                        outer_fence = _Fence(
                            char=run[0],
                            length=len(run),
                            indent=len(lead),
                            is_markdown=lang in {"markdown", "md"},
                            list_prefix=list_indent,
                        )
                        fence_lines = []
                        continue
                # Nested bullet inside ## Contents list is validated too.
                if in_contents and contents_list_indent is not None:
                    nested_bullet = _BULLET_ITEM_RE.match(inner_line)
                    if nested_bullet:
                        toc_bullets.append((lineno, nested_bullet.group(4).strip(" \t")))
                        continue
                # Nested ATX heading inside a list item participates in rendered slugs
                # (but is NOT a top-level ## Contents heading).
                nested_atx = _ATX_HEADING_RE.match(inner_line)
                if nested_atx:
                    title = _strip_atx_heading(nested_atx.group(2) or "")
                    _record_heading(lineno, len(nested_atx.group(1)), title, top_level=False)
                continue
            list_indent = None
            contents_list_indent = None

        # 6. Indented code block (CommonMark §4.4): >= 4 columns outside a paragraph/list.
        if indent >= 4 and not para_lines:
            continue

        # 7. Opening fenced code block (does NOT end ## Contents; bullets after the fence still lint).
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
                continue

        # 8. HTML block start (CommonMark §4.6).
        html_kind = _html_block_end_kind(line)
        if html_kind is not None:
            para_lines.clear()
            if html_kind == "type6" or not _html_block_closed(html_kind, line):
                html_block = html_kind
            continue

        # 9. Blockquote (CommonMark §5.1): not top-level ## Contents.
        if re.match(r"^ {0,3}>", line):
            para_lines.clear()
            continue

        # 10. Top-level ATX heading (CommonMark §4.2).
        atx_match = _ATX_HEADING_RE.match(line)
        if atx_match:
            para_lines.clear()
            level = len(atx_match.group(1))
            title = _strip_atx_heading(atx_match.group(2) or "")
            _record_heading(lineno, level, title, top_level=True)
            continue

        # 11. Thematic break (CommonMark §4.1).
        if _THEMATIC_BREAK_RE.match(line):
            para_lines.clear()
            continue

        # 12. List item start (CommonMark §5.2).
        list_match = _LIST_START_RE.match(line)
        if list_match:
            para_lines.clear()
            marker_end = list_match.end()
            list_indent = marker_end
            bullet_match = _BULLET_ITEM_RE.match(line)
            if in_contents and bullet_match:
                contents_list_indent = marker_end
                toc_bullets.append((lineno, bullet_match.group(4).strip(" \t")))
                continue
            # Handle inline heading on list marker line (e.g. `- ## Contents`):
            # rendered heading for slug allocation, never a top-level ## Contents.
            rest = line[marker_end:]
            inline_atx = _ATX_HEADING_RE.match(rest)
            if inline_atx:
                title = _strip_atx_heading(inline_atx.group(2) or "")
                _record_heading(lineno, len(inline_atx.group(1)), title, top_level=False)
            continue

        # 13. Ordinary paragraph line (candidate for a following Setext underline).
        para_lines.append((lineno, line))

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
    doc = _parse_document(text, collect_templates=True)
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

        # 2. Heading inside an HTML comment does not satisfy a TOC bullet or anchor.
        html_comment = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Ghost\n"
            "- [Ghost](#ghost)\n\n"
            "<!--\n## Ghost\n-->\n"
        )
        findings = reference_toc_findings(html_comment, "fixture/html-comment.md")
        self.assertEqual(len(findings), 2)

        # 3. '## Contents' nested inside a list item does not satisfy the >100-line requirement.
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

        # 4. Broken bullet AFTER a fenced block inside ## Contents is still checked.
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

        # 5. Valid Setext headings (including Setext level-2 Contents) are recognized.
        setext = (
            "Title\n=====\n\n"
            "Contents\n--------\n\n"
            "- Setext Section\n"
            "- [Setext Section](#setext-section)\n\n"
            "Setext Section\n--------------\n"
            "Body.\n"
        )
        self.assertEqual(reference_toc_findings(setext, "fixture/setext.md"), [])

    def test_anchor_slug_allocation_and_template_anchor_separation(self) -> None:
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

        # 2. ## Foo, ## Foo-1, ## Foo allocates #foo, #foo-1, #foo-2 (skipping collision).
        dedup = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [First](#foo)\n"
            "- [Middle](#foo-1)\n"
            "- [Third](#foo-2)\n\n"
            "## Foo\n\n## Foo-1\n\n## Foo\n"
        )
        self.assertEqual(reference_toc_findings(dedup, "fixture/dedup.md"), [])

        # 3. With a later ### Contents, #contents still points to the TOC (rejected),
        # while #contents-1 targets the later ### Contents (accepted).
        later_contents_bad = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- [TOC self](#contents)\n\n"
            "### Contents\n"
        )
        findings = reference_toc_findings(later_contents_bad, "fixture/later-contents-bad.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("#contents", findings[0].message)

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
