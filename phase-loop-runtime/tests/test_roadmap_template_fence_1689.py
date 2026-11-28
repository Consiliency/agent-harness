"""Regression tests for outer markdown fence nesting in roadmap-template.md (agent-harness#1689)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


RUNTIME = Path(__file__).resolve().parents[1]
REPO = RUNTIME.parent

SRC_TEMPLATE = REPO / "skills-src" / "claude" / "claude-phase-roadmap-builder" / "references" / "roadmap-template.md"
SKILLS_TEMPLATE = (
    REPO / "phase-loop-skills" / "phase-roadmap-builder" / "_overrides" / "claude" / "references" / "roadmap-template.md"
)
BUNDLE_TEMPLATE = (
    RUNTIME / "src" / "phase_loop_runtime" / "skills_bundle" / "claude-phase-roadmap-builder" / "references" / "roadmap-template.md"
)

_OPEN_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\n]*)$")


def _extract_top_level_fenced_blocks(text: str) -> list[tuple[str, str, int, int, str]]:
    """Parse CommonMark top-level fenced code blocks.

    Returns ``(fence_token, info_string, start_line, end_line, body)`` tuples
    (1-based line numbers). Raises ``AssertionError`` if an outer fence is unclosed.
    """
    blocks: list[tuple[str, str, int, int, str]] = []
    open_fence: str | None = None
    open_info = ""
    open_line = 0
    body_lines: list[str] = []

    for lineno, line in enumerate(text.splitlines(), 1):
        match = _OPEN_FENCE_RE.match(line)
        if open_fence is None:
            if match:
                fence, rest = match.group(1), match.group(2)
                # Backtick info strings cannot contain backticks in CommonMark.
                if fence[0] == "`" and "`" in rest:
                    continue
                open_fence = fence
                open_info = rest.strip()
                open_line = lineno
                body_lines = []
        else:
            close_char = open_fence[0]
            close_min = len(open_fence)
            if (
                match
                and match.group(1)[0] == close_char
                and len(match.group(1)) >= close_min
                and match.group(2).strip() == ""
            ):
                blocks.append((open_fence, open_info, open_line, lineno, "\n".join(body_lines)))
                open_fence = None
                open_info = ""
                open_line = 0
                body_lines = []
            else:
                body_lines.append(line)

    assert open_fence is None, f"unclosed markdown fence {open_fence!r} opened at line {open_line}"
    return blocks


def _bundled_template_text() -> str:
    if BUNDLE_TEMPLATE.is_file():
        return BUNDLE_TEMPLATE.read_text(encoding="utf-8")
    from importlib import resources

    return (
        resources.files("phase_loop_runtime")
        .joinpath("skills_bundle/claude-phase-roadmap-builder/references/roadmap-template.md")
        .read_text(encoding="utf-8")
    )


def test_roadmap_template_outer_markdown_fence_encloses_inner_code_blocks() -> None:
    text = _bundled_template_text()
    blocks = _extract_top_level_fenced_blocks(text)
    markdown_blocks = [b for b in blocks if b[1] == "markdown"]
    assert len(markdown_blocks) == 1, f"expected one top-level markdown template block, got {len(markdown_blocks)}"

    fence, _info, _start, end_line, body = markdown_blocks[0]
    assert (fence[0] == "`" and len(fence) >= 4) or (fence[0] == "~" and len(fence) >= 3), (
        f"outer markdown fence {fence!r} cannot safely enclose inner triple-backtick fences"
    )

    # The entire roadmap template, including its inner ```bash verification snippet, stays inside the block.
    assert "# <Project Name> — Phase Plan v<N>" in body
    assert "## Verification" in body
    assert "```bash" in body
    assert "## Notes on filling in the template" not in body

    trailing = "\n".join(text.splitlines()[end_line:])
    assert "## Notes on filling in the template" in trailing


@pytest.mark.skipif(
    not SRC_TEMPLATE.is_file() or not SKILLS_TEMPLATE.is_file() or not BUNDLE_TEMPLATE.is_file(),
    reason="repo-only source and generated skill trees absent from standalone-from-wheel layout",
)
def test_roadmap_template_source_and_generated_bundles_are_identical() -> None:
    src = SRC_TEMPLATE.read_text(encoding="utf-8")
    assert SKILLS_TEMPLATE.read_text(encoding="utf-8") == src
    assert BUNDLE_TEMPLATE.read_text(encoding="utf-8") == src


def test_fence_parser_catches_premature_closure_regression() -> None:
    # Inner bare ``` closes an outer ```markdown block early, splitting the template in two.
    broken_paired = "\n".join([
        "```markdown",
        "# Title",
        "```",
        "diagram",
        "```",
        "## Verification",
        "```",
    ])
    blocks = _extract_top_level_fenced_blocks(broken_paired)
    markdown_blocks = [b for b in blocks if b[1] == "markdown"]
    assert len(markdown_blocks) == 1
    assert "## Verification" not in markdown_blocks[0][4]

    # Inner ```bash + ``` inside ```markdown closes early at the inner closing fence, leaving the outer closing fence unclosed.
    broken_unclosed = "\n".join([
        "```markdown",
        "# Title",
        "```bash",
        "echo hi",
        "```",
        "## Verification",
        "```",
    ])
    with pytest.raises(AssertionError, match="unclosed markdown fence"):
        _extract_top_level_fenced_blocks(broken_unclosed)
