"""Mechanical TOC lint for canonical skill references (agent-harness#1688).

Enforces the agent-harness#1358 reference-index rule across all
``skills-src/<harness>/<skill>/references/*.md`` files:

1. Every reference over ``MAX_UNINDEXED_LINES`` (100) lines MUST carry a
   top-level ``## Contents`` section with at least one bullet.
2. Every bullet inside ``## Contents`` (plain heading text or Markdown anchor
   link ``[label](#slug)``) MUST match an existing non-``Contents`` heading in
   that file (ignoring commented ``# ...`` lines inside non-markdown fenced
   code blocks).
"""

from __future__ import annotations

import re
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS_SRC = REPO / "skills-src"
MAX_UNINDEXED_LINES = 100

_COMMONMARK_LINE_RE = re.compile(r"\r\n|\r|\n")
_OPEN_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)$")
_CLOSE_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_TRAILING_HASHES_RE = re.compile(r"(?:^|[ \t]+)#+$")
_BULLET_RE = re.compile(r"^[ \t]*[-*+][ \t]+(.+?)[ \t]*$")
_ANCHOR_LINK_RE = re.compile(r"^\[([^\]]+)\]\(#([^)]+)\)$")


@dataclass(frozen=True)
class TocFinding:
    path: str
    message: str
    line: int | None = None

    def describe(self) -> str:
        where = f":{self.line}" if self.line is not None else ""
        return f"{self.path}{where}: {self.message}"


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
    # Strip inline code backticks while keeping their text.
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


@dataclass(frozen=True)
class _Fence:
    char: str
    length: int
    is_markdown: bool


def _parse_reference(text: str) -> tuple[int, list[int], list[tuple[int, str]], list[tuple[int, str]]]:
    """Parse one reference markdown file using CommonMark 0.31.2 fenced-block rules.

    Returns ``(line_count, contents_lines, headings, toc_bullets)`` where:
    - ``contents_lines``: 1-based line numbers of top-level ``## Contents`` headings.
    - ``headings``: ``(line_no, heading_text)`` for every non-``Contents`` ATX heading
      outside non-markdown code fences (headings inside ``markdown``/``md`` fenced
      template blocks are included, while nested non-markdown blocks inside them
      such as ``bash`` remain ignored).
    - ``toc_bullets``: ``(line_no, bullet_text)`` for bullets directly inside the
      top-level ``## Contents`` section (ending at the next heading or fenced block).
    """
    lines = _commonmark_lines(text)
    fence_stack: list[_Fence] = []
    contents_lines: list[int] = []
    headings: list[tuple[int, str]] = []
    toc_bullets: list[tuple[int, str]] = []
    in_contents = False

    for lineno, line in enumerate(lines, start=1):
        # Check whether this line closes an open fence.
        close_match = _CLOSE_FENCE_RE.match(line)
        if fence_stack and close_match:
            run = close_match.group(1)
            char, length = run[0], len(run)
            top = fence_stack[-1]
            if top.char == char and length >= top.length:
                # Pop innermost matching fence (and any outer markdown fence if a
                # longer closing fence closes the enclosing block per CommonMark).
                while fence_stack and fence_stack[-1].char == char and length >= fence_stack[-1].length:
                    fence_stack.pop()
                    if not fence_stack or not fence_stack[-1].is_markdown:
                        break
                continue
            if not top.is_markdown:
                continue

        # Check whether this line opens a new fence (outside all fences, or nested
        # inside a markdown template fence).
        if not fence_stack or fence_stack[-1].is_markdown:
            open_match = _OPEN_FENCE_RE.match(line)
            if open_match:
                run, info = open_match.group(1), open_match.group(2)
                char, length = run[0], len(run)
                if char == "`" and "`" in info:
                    open_match = None
                elif fence_stack and fence_stack[-1].char == char and length >= fence_stack[-1].length:
                    open_match = None
                if open_match is not None:
                    lang = info.strip(" \t").split()[0].lower() if info.strip(" \t") else ""
                    if not fence_stack:
                        in_contents = False
                    fence_stack.append(_Fence(char=char, length=length, is_markdown=lang in {"markdown", "md"}))
                    continue

        if fence_stack and not fence_stack[-1].is_markdown:
            continue

        heading_match = _ATX_HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = _strip_atx_heading(heading_match.group(2) or "")
            if not fence_stack:
                if level == 2 and title == "Contents":
                    contents_lines.append(lineno)
                    in_contents = len(contents_lines) == 1
                    continue
                in_contents = False
            if title:
                headings.append((lineno, title))
            continue

        if in_contents and not fence_stack:
            bullet_match = _BULLET_RE.match(line)
            if bullet_match:
                toc_bullets.append((lineno, bullet_match.group(1).strip(" \t")))

    return len(lines), contents_lines, headings, toc_bullets


def reference_toc_findings(text: str, label: str) -> list[TocFinding]:
    """Validate TOC presence (>100 lines) and bullet-to-heading agreement for one file."""
    line_count, contents_lines, headings, toc_bullets = _parse_reference(text)
    findings: list[TocFinding] = []

    if line_count > MAX_UNINDEXED_LINES and not contents_lines:
        findings.append(
            TocFinding(
                label,
                f"reference has {line_count} lines (> {MAX_UNINDEXED_LINES}) without a top-level '## Contents' section",
            )
        )
        return findings

    if len(contents_lines) > 1:
        findings.append(
            TocFinding(
                label,
                f"duplicate top-level '## Contents' heading (first at line {contents_lines[0]})",
                line=contents_lines[1],
            )
        )

    if contents_lines and not toc_bullets:
        findings.append(
            TocFinding(
                label,
                "'## Contents' section has no bullet items",
                line=contents_lines[0],
            )
        )
        return findings

    heading_titles = {title for _, title in headings}
    slug_counts: dict[str, int] = {}
    heading_slugs: set[str] = set()
    for _, title in headings:
        base = _github_heading_slug(title)
        seen = slug_counts.get(base, 0)
        slug_counts[base] = seen + 1
        heading_slugs.add(base if seen == 0 else f"{base}-{seen}")

    for lineno, bullet in toc_bullets:
        link_match = _ANCHOR_LINK_RE.match(bullet)
        if link_match:
            anchor = link_match.group(2).strip().lower()
            if anchor not in heading_slugs:
                findings.append(
                    TocFinding(
                        label,
                        f"## Contents anchor '#{anchor}' does not match any heading in this file",
                        line=lineno,
                    )
                )
            continue
        if bullet not in heading_titles:
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


def _has_canonical_skills_src() -> bool:
    return all((SKILLS_SRC / harness).is_dir() for harness in ("claude", "codex", "gemini", "opencode"))


_NEEDS_SOURCE_TREE = unittest.skipUnless(
    _has_canonical_skills_src(),
    "lints the full skills-src tree; the standalone wheel tree omits canonical skills-src/",
)


class SkillReferenceTocLintTest(unittest.TestCase):
    @_NEEDS_SOURCE_TREE
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

    def test_code_fence_comments_do_not_satisfy_toc_and_invalid_closing_fences_keep_block_open(self) -> None:
        # 1. Bash comment '# Fake heading' inside ```bash is not a heading.
        bash_text = (
            "# Ref\n\n"
            "## Contents\n\n"
            "- Fake heading\n\n"
            "```bash\n"
            "# Fake heading\n"
            "```\n"
        )
        findings = reference_toc_findings(bash_text, "fixture/bash.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("Fake heading", findings[0].message)

        # 2. CommonMark closing fence rejects trailing \u00a0, \v, and \f; a heading
        # after an unclosed bash fence stays inside the code block and does not match.
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

    def test_markdown_template_fence_headings_match_while_nested_bash_comments_stay_ignored(self) -> None:
        text = (
            "# Template Ref\n\n"
            "## Contents\n\n"
            "- Context\n"
            "- Verification\n\n"
            "````markdown\n"
            "## Context\n"
            "## Verification\n"
            "```bash\n"
            "# Shell comment\n"
            "```\n"
            "````\n\n"
            "## Notes\n"
        )
        self.assertEqual(reference_toc_findings(text, "fixture/template.md"), [])

        bad = text.replace("- Verification\n", "- Shell comment\n")
        findings = reference_toc_findings(bad, "fixture/template-bad.md")
        self.assertEqual(len(findings), 1)
        self.assertIn("Shell comment", findings[0].message)

    def test_empty_contents_and_duplicate_contents_fail(self) -> None:
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

    def test_canonical_reference_files_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ref = Path(td) / "claude" / "claude-sample" / "references" / "guide.md"
            ref.parent.mkdir(parents=True)
            ref.write_text("# Guide\n", encoding="utf-8")
            self.assertEqual(canonical_reference_files(Path(td)), [ref])
