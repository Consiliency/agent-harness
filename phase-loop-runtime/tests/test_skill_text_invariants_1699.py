"""Skill-text invariants for agent-harness#1699 (follow-up from agent-harness#1687).

1. Pin the ``claude-execute-phase`` merge-target safety gate in ``SKILL.md``
   inside ``## Workflow`` at its pre-dispatch position (and its back-pointer in
   ``references/interactive-steps.md``) so mutations that weaken, hide, or
   relocate the gate cannot survive.
2. Assert that every shipped ``references/**/*.md`` file is linked by relative
   path from its owning ``SKILL.md`` outside CommonMark fenced code blocks
   (including fences inside list items and blockquotes) and HTML comments.
   Under the adapter bundle manifest read exception, an unlinked reference
   cannot be read.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from phase_loop_runtime import injection

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_SRC = REPO_ROOT / "skills-src"
PHASE_LOOP_SKILLS = REPO_ROOT / "phase-loop-skills"
PACKAGED_SKILLS = Path(injection.__file__).resolve().parent / "skills_bundle"

_LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")
_BLOCKQUOTE_RE = re.compile(r"^ {0,3}> ?(.*)$")
_LIST_ITEM_RE = re.compile(r"^( *)(?:[-*+]|(?:\d{1,9})[.)])([ \t]+)(.*)$")
_OPEN_FENCE_RE = re.compile(r"^( *)(`{3,}|~{3,})([^\r\n]*)$")
_CLOSE_FENCE_RE = re.compile(r"^( *)(`{3,}|~{3,})[ \t]*$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_TRAILING_HASHES_RE = re.compile(r"(?:^|[ \t]+)#+$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_LINK_DEF_RE = re.compile(
    r"^ {0,3}\[([^\]]+)\]:[ \t]*(?:<([^>\r\n]+)>|([^\s<>]+))(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$",
    re.MULTILINE,
)
_INLINE_LINK_RE = re.compile(
    r"(?<!\!)\[[^\]]+\]\([ \t]*(?:<([^>\r\n]+)>|([^\s()<>]+))(?:[ \t]+(?:\"[^\"]*\"|'[^']*'))?[ \t]*\)"
)
_REF_LINK_FULL_RE = re.compile(r"(?<!\!)\[[^\]]+\]\[([^\]]+)\]")
_REF_LINK_COLLAPSED_RE = re.compile(r"(?<!\!)\[([^\]]+)\]\[\]")
_REF_LINK_SHORTCUT_RE = re.compile(r"(?<!\!)\[([^\]]+)\](?![\[\(:])")


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = _LINE_SPLIT_RE.split(text)
    if text.endswith(("\r\n", "\n", "\r")) and lines and lines[-1] == "":
        lines.pop()
    return lines


def _expand_leading_indent(line: str) -> tuple[int, str]:
    col = 0
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
    return col, line[idx:]


def _strip_blockquotes(line: str) -> tuple[int, str]:
    depth = 0
    cur = line
    while True:
        match = _BLOCKQUOTE_RE.match(cur)
        if match is None:
            break
        depth += 1
        cur = match.group(1)
    return depth, cur


def _strip_fenced_code_blocks(text: str) -> str:
    """Blank CommonMark fenced code blocks at top level, in blockquotes, and in list items."""
    out: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    fence_bq_depth = 0
    fence_max_close_indent = 3
    # Stack of active list-item content columns at each blockquote depth.
    list_indents: list[int] = []
    prev_bq_depth = 0

    for line in _split_lines(text):
        bq_depth, inner = _strip_blockquotes(line)
        if fence_char is not None:
            if bq_depth < fence_bq_depth:
                # Lazy/closed blockquote terminates the inner fence before this line.
                fence_char = None
                fence_len = 0
                list_indents = []
            else:
                # Strip any extra blockquote markers if still inside same/deeper quote.
                close_col, close_rest = _expand_leading_indent(inner)
                close_match = _CLOSE_FENCE_RE.match(close_rest)
                if (
                    bq_depth == fence_bq_depth
                    and close_col <= fence_max_close_indent
                    and close_match is not None
                    and close_match.group(2)[0] == fence_char
                    and len(close_match.group(2)) >= fence_len
                ):
                    fence_char = None
                    fence_len = 0
                out.append("")
                continue

        if bq_depth != prev_bq_depth:
            list_indents = []
            prev_bq_depth = bq_depth

        if not inner.strip():
            out.append(line)
            continue

        col, rest = _expand_leading_indent(inner)
        while list_indents and col < list_indents[-1]:
            list_indents.pop()

        # Unwrap any list-item marker on this line to discover its content column.
        check_col = col
        check_rest = rest
        base_col = list_indents[-1] if list_indents else 0
        list_match = _LIST_ITEM_RE.match(inner)
        if list_match is not None and col <= base_col + 3:
            marker_end = len(list_match.group(1)) + len(list_match.group(0)) - len(list_match.group(3))
            # Recompute column width accounting for spaces/tabs in marker + gap.
            prefix = inner[:marker_end]
            content_col = 0
            for ch in prefix:
                content_col += (4 - (content_col % 4)) if ch == "\t" else 1
            list_indents.append(content_col)
            base_col = content_col
            sub_col, sub_rest = _expand_leading_indent(list_match.group(3))
            check_col = content_col + sub_col
            check_rest = sub_rest

        open_match = _OPEN_FENCE_RE.match(check_rest)
        if open_match is not None and check_col <= base_col + 3:
            marker = open_match.group(2)
            info = open_match.group(3)
            if not (marker[0] == "`" and "`" in info):
                fence_char = marker[0]
                fence_len = len(marker)
                fence_bq_depth = bq_depth
                fence_max_close_indent = base_col + 3
                out.append("")
                continue

        out.append(line)
    return "\n".join(out)


def _visible_prose(text: str) -> str:
    """Return Markdown text with fenced code blocks and HTML comments removed."""
    return _HTML_COMMENT_RE.sub("", _strip_fenced_code_blocks(text))


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


def _extract_markdown_section(text: str, *, level: int, title: str) -> str | None:
    """Extract the visible body of a Markdown ATX section (outside fences & HTML comments)."""
    visible = _visible_prose(text)
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

    workflow_body = _extract_markdown_section(skill_md_text, level=2, title=_WORKFLOW_HEADING)
    if workflow_body is None:
        findings.append(f"{label}/SKILL.md: missing `## {_WORKFLOW_HEADING}` section")
    else:
        subheadings = [(line_no, title) for line_no, lvl, title in _iter_atx_headings(workflow_body) if lvl == 3]
        by_title = {title: line_no for line_no, title in subheadings}
        gate_body = _extract_markdown_section(workflow_body, level=3, title=_SAFETY_GATE_HEADING)
        if gate_body is None:
            findings.append(
                f"{label}/SKILL.md: missing `### {_SAFETY_GATE_HEADING}` inside `## {_WORKFLOW_HEADING}`"
            )
        else:
            gate_pos = by_title[_SAFETY_GATE_HEADING]
            if _INTERACTIVE_STEPS_HEADING not in by_title or gate_pos < by_title[_INTERACTIVE_STEPS_HEADING]:
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

    pub_body = _extract_markdown_section(skill_md_text, level=2, title="Publication mode")
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
        preflight_body = _extract_markdown_section(
            interactive_steps_text, level=2, title="Step 2 — Preflight"
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


def _extract_code_spans_and_mask(prose: str) -> tuple[set[str], str]:
    """Scan CommonMark inline code spans per paragraph, returning exact ref paths and masked text."""
    code_refs: set[str] = set()
    masked_paragraphs: list[str] = []
    for paragraph in re.split(r"(\n[ \t]*\n)", prose):
        if re.fullmatch(r"\n[ \t]*\n", paragraph):
            masked_paragraphs.append(paragraph)
            continue
        out: list[str] = []
        i = 0
        n = len(paragraph)
        while i < n:
            if paragraph[i] == "`":
                j = i
                while j < n and paragraph[j] == "`":
                    j += 1
                tick_len = j - i
                k = j
                found_end = -1
                close_end = -1
                while k < n:
                    if paragraph[k] == "`":
                        m = k
                        while m < n and paragraph[m] == "`":
                            m += 1
                        if m - k == tick_len:
                            found_end = k
                            close_end = m
                            break
                        k = m
                    else:
                        k += 1
                if found_end != -1:
                    inner = paragraph[j:found_end]
                    if (
                        len(inner) >= 2
                        and inner.startswith(" ")
                        and inner.endswith(" ")
                        and inner.strip()
                    ):
                        inner = inner[1:-1]
                    candidate = inner[2:] if inner.startswith("./") else inner
                    if candidate.startswith("references/") and not any(
                        ch.isspace() for ch in candidate
                    ):
                        code_refs.add(candidate)
                    out.append(" " * (close_end - i))
                    i = close_end
                    continue
                out.append(paragraph[i:j])
                i = j
                continue
            out.append(paragraph[i])
            i += 1
        masked_paragraphs.append("".join(out))
    return code_refs, "".join(masked_paragraphs)


def _extract_linked_relative_paths(skill_md_text: str) -> set[str]:
    """Collect relative reference paths linked via Markdown links or exact inline code spans."""
    prose = _visible_prose(skill_md_text)
    linked, no_code = _extract_code_spans_and_mask(prose)

    # Collect link reference definitions and strip them before scanning link usages so a
    # bare definition line cannot count as a usage of itself.
    definitions: dict[str, str] = {}

    def _consume_link_def(match: re.Match[str]) -> str:
        label = _normalize_ref_label(match.group(1))
        dest = match.group(2) if match.group(2) is not None else match.group(3)
        if label and label not in definitions and dest:
            definitions[label] = _normalize_relative_target(dest)
        return ""

    body = _LINK_DEF_RE.sub(_consume_link_def, no_code)

    # 1. Inline Markdown links: [text](dest) or [text](<dest>) (images excluded).
    for match in _INLINE_LINK_RE.finditer(body):
        dest = match.group(1) if match.group(1) is not None else match.group(2)
        if dest:
            linked.add(_normalize_relative_target(dest))

    # 2. Used reference links: [text][label], [label][], and shortcut [label].
    used_labels: set[str] = set()
    for pattern in (_REF_LINK_FULL_RE, _REF_LINK_COLLAPSED_RE, _REF_LINK_SHORTCUT_RE):
        for match in pattern.finditer(body):
            used_labels.add(_normalize_ref_label(match.group(1)))
    for label in used_labels:
        target = definitions.get(label)
        if target:
            linked.add(target)

    return linked


def is_reference_linked_in_skill_md(skill_md_text: str, rel_ref_path: str) -> bool:
    """True if ``rel_ref_path`` (e.g. ``references/foo.md``) is linked outside code fences."""
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
            + f"### {_SAFETY_GATE_HEADING}\n\n<!--\n"
            + gate_block.split("\n", 1)[1]
            + "-->\n\n"
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

    def test_reference_link_checker_accepts_valid_links_and_rejects_orphans_fences_and_malformed(self) -> None:
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
                "orphan.md",
                "fenced-top.md",
                "fenced-list.md",
                "fenced-quote.md",
                "commented-only.md",
                "prefix-only.md",
                "image-only.md",
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
                "- Reference links: [the full guide][full-guide], [ref-collapsed][], and [ref-shortcut].\n"
                "- Wrong prefix: `other/references/prefix-only.md` and `references/prefix-only.md.bak`.\n"
                "- Image is not a doc link: ![img](references/image-only.md).\n"
                "- Malformed angle link: [bad](<references/malformed-angle.md).\n"
                "- Literal link inside code span is not a link: `[ex](references/code-link-example.md)`.\n"
                "<!-- [hidden](references/commented-only.md) `references/commented-only.md` -->\n\n"
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
                "[full-guide]: references/ref-full.md\n"
                "[ref-collapsed]: references/ref-collapsed.md#top\n"
                "[ref-shortcut]: <references/ref-shortcut.md>\n"
                "[unused-def]: references/unused-def.md\n",
                encoding="utf-8",
            )

            count, findings = unlinked_reference_findings_for_skill(skill, label_root=root)
            self.assertEqual(count, 19)
            self.assertEqual(
                findings,
                [
                    "demo-skill/SKILL.md: shipped `references/code-link-example.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/commented-only.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/fenced-list.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/fenced-quote.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/fenced-top.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/image-only.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/malformed-angle.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/orphan.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/prefix-only.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/unused-def.md` is not linked from SKILL.md",
                ],
            )


if __name__ == "__main__":
    unittest.main()
