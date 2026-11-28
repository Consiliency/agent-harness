"""Skill-text invariants for agent-harness#1699 (follow-up from agent-harness#1687).

1. Pin the ``claude-execute-phase`` merge-target safety gate in ``SKILL.md``
   (and its back-pointer in ``references/interactive-steps.md``) so mutations
   that weaken or relocate the gate cannot survive.
2. Assert that every shipped ``references/**/*.md`` file is linked by relative
   path from its owning ``SKILL.md`` outside fenced code blocks. Under the
   adapter bundle manifest read exception, an unlinked reference cannot be read.
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
_OPEN_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})([^\r\n]*)$")
_CLOSE_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_TRAILING_HASHES_RE = re.compile(r"(?:^|[ \t]+)#+$")


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = _LINE_SPLIT_RE.split(text)
    if text.endswith(("\r\n", "\n", "\r")) and lines and lines[-1] == "":
        lines.pop()
    return lines


def _strip_fenced_code_blocks(text: str) -> str:
    """Return Markdown text with CommonMark fenced code blocks blanked out."""
    out: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in _split_lines(text):
        if fence_char is not None:
            close_match = _CLOSE_FENCE_RE.match(line)
            if (
                close_match is not None
                and close_match.group(1)[0] == fence_char
                and len(close_match.group(1)) >= fence_len
            ):
                fence_char = None
                fence_len = 0
            out.append("")
            continue
        open_match = _OPEN_FENCE_RE.match(line)
        if open_match is not None:
            marker = open_match.group(2)
            info = open_match.group(3)
            if not (marker[0] == "`" and "`" in info):
                fence_char = marker[0]
                fence_len = len(marker)
                out.append("")
                continue
        out.append(line)
    return "\n".join(out)


def _extract_markdown_section(text: str, *, level: int, title: str) -> str | None:
    """Extract the body of a Markdown ATX section (outside fenced code blocks)."""
    stripped = _strip_fenced_code_blocks(text)
    lines = _split_lines(stripped)
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
    """Return missing/mutated invariants for the claude-execute-phase safety gate."""
    findings: list[str] = []

    gate_body = _extract_markdown_section(
        skill_md_text, level=3, title="Step 2 — Merge-target safety gate"
    )
    if gate_body is None:
        findings.append(f"{label}/SKILL.md: missing `### Step 2 — Merge-target safety gate` section")
    else:
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


def is_reference_linked_in_skill_md(skill_md_text: str, rel_ref_path: str) -> bool:
    """True if ``rel_ref_path`` (e.g. ``references/foo.md``) is linked outside code fences."""
    prose = _strip_fenced_code_blocks(skill_md_text)
    escaped = re.escape(rel_ref_path)
    # Inline Markdown link (excluding images ``![...](...)``):
    # [label](references/foo.md), [label](references/foo.md#anchor), [label](./references/foo.md)
    md_link_re = re.compile(
        r"(?<!\!)\[[^\]]+\]\(\s*<?(?:\./)?"
        + escaped
        + r"(?:#[^)\s>]+)?>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
    )
    if md_link_re.search(prose) is not None:
        return True
    # Exact inline code span referencing the relative path (e.g. `references/foo.md`).
    code_span_re = re.compile(r"(?<!`)`(?:\./)?" + escaped + r"`(?!`)")
    return code_span_re.search(prose) is not None


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
    skill_text = skill_md.read_text(encoding="utf-8")
    findings: list[str] = []
    for ref_file in md_files:
        rel_ref = f"references/{ref_file.relative_to(ref_root).as_posix()}"
        if not is_reference_linked_in_skill_md(skill_text, rel_ref):
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

        mutations: tuple[tuple[str, str, str], ...] = (
            (
                "heading removed",
                base_skill.replace("### Step 2 — Merge-target safety gate", "### Step 2 — Notes"),
                base_steps,
            ),
            (
                "STOP removed",
                base_skill.replace(", STOP —", ", warn and continue —"),
                base_steps,
            ),
            (
                "git merge prohibition removed",
                base_skill.replace("or run any\n`git merge` onto it.", "without caution."),
                base_steps,
            ),
            (
                "main target removed",
                base_skill.replace("target is `main` or a protected branch", "target is `release`"),
                base_steps,
            ),
            (
                "interactive remedy removed",
                base_skill.replace(
                    "Interactive: check out / create a dedicated feature branch first and\nre-resolve the merge target;",
                    "Interactive: proceed carefully;",
                ),
                base_steps,
            ),
            (
                "runner remedy removed",
                base_skill.replace(
                    "runner/adapter: the runner resolves a runner-managed branch.",
                    "runner/adapter: continue on current branch.",
                ),
                base_steps,
            ),
            (
                "Step 7 precedence removed",
                base_skill.replace(
                    "This gate precedes Step 7's auto-merge, which would otherwise mutate `main` directly.",
                    "",
                ),
                base_steps,
            ),
            (
                "Publication mode (c) weakened",
                base_skill.replace("never merge lanes onto `main`/protected.", "avoid merging to main."),
                base_steps,
            ),
            (
                "gate trapped inside code fence",
                base_skill.replace(
                    "### Step 2 — Merge-target safety gate",
                    "```markdown\n### Step 2 — Merge-target safety gate",
                )
                + "\n```\n",
                base_steps,
            ),
            (
                "interactive-steps back-pointer dropped",
                base_skill,
                base_steps.replace(_INTERACTIVE_STEPS_BACKPOINTER, "Continue directly to dispatch."),
            ),
        )
        for name, mutated_skill, mutated_steps in mutations:
            with self.subTest(mutation=name):
                self.assertTrue(
                    merge_target_safety_gate_findings(
                        mutated_skill, interactive_steps_text=mutated_steps
                    ),
                    f"mutation {name!r} was not caught",
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

    def test_reference_link_checker_accepts_valid_links_and_rejects_orphans_and_fences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "demo-skill"
            refs = skill / "references"
            (refs / "nested").mkdir(parents=True)
            (refs / "linked.md").write_text("# Linked\n", encoding="utf-8")
            (refs / "anchored.md").write_text("# Anchored\n", encoding="utf-8")
            (refs / "code-span.md").write_text("# Code Span\n", encoding="utf-8")
            (refs / "dot-rel.md").write_text("# Dot Rel\n", encoding="utf-8")
            (refs / "nested" / "deep.md").write_text("# Deep\n", encoding="utf-8")
            (refs / "orphan.md").write_text("# Orphan\n", encoding="utf-8")
            (refs / "fenced-only.md").write_text("# Fenced\n", encoding="utf-8")
            (refs / "prefix-only.md").write_text("# Prefix\n", encoding="utf-8")
            (refs / "image-only.md").write_text("# Image\n", encoding="utf-8")

            (skill / "SKILL.md").write_text(
                "# Demo\n\n"
                "- Read [linked](references/linked.md).\n"
                "- Jump to [section](references/anchored.md#details).\n"
                "- See `references/code-span.md` for details.\n"
                "- Also [dot](./references/dot-rel.md) and [deep](references/nested/deep.md).\n"
                "- Wrong prefix: `other/references/prefix-only.md` and `references/prefix-only.md.bak`.\n"
                "- Image is not a doc link: ![img](references/image-only.md).\n\n"
                "```markdown\n"
                "[example](references/fenced-only.md)\n"
                "`references/fenced-only.md`\n"
                "```\n",
                encoding="utf-8",
            )

            count, findings = unlinked_reference_findings_for_skill(skill, label_root=root)
            self.assertEqual(count, 9)
            self.assertEqual(
                findings,
                [
                    "demo-skill/SKILL.md: shipped `references/fenced-only.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/image-only.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/orphan.md` is not linked from SKILL.md",
                    "demo-skill/SKILL.md: shipped `references/prefix-only.md` is not linked from SKILL.md",
                ],
            )


if __name__ == "__main__":
    unittest.main()
