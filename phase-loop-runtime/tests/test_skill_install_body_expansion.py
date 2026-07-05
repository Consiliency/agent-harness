"""#26 item 2 — install-time re-expansion of the ``<harness>-`` body placeholder.

The canonical bundle keeps skill-name references harness-neutral as
``<harness>-<skill>`` in prose (so the base collapses and avoids per-harness
override bloat). On install for a concrete harness, that placeholder must be
re-expanded to the real per-harness form (e.g. ``claude-execute-phase``) in the
SKILL.md BODY — not only in the ``name:`` frontmatter.

These tests build a minimal synthetic bundle so they run in standalone CI
(the real bundle-source install tests skip without the dotfiles tree).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from phase_loop_runtime.skill_install import (
    REQUIRED_SKILLS,
    SKILL_ALIASES,
    install_skills,
)


def _make_bundle(root: Path) -> Path:
    for name in REQUIRED_SKILLS:
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            "description: synthetic test skill\n"
            "---\n\n"
            "The prompt begins with `<harness>-execute-phase <plan>`; then run\n"
            "`<harness>-plan-phase` and `<harness>-skill-editor`.\n",
            encoding="utf-8",
        )
    return root


def test_install_expands_harness_placeholder_in_body_for_claude():
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
        _make_bundle(Path(src))
        install_skills(
            harness="claude", source=Path(src), destination=Path(dest), mode="copy", apply=True
        )
        body = (Path(dest) / "claude-execute-phase" / "SKILL.md").read_text(encoding="utf-8")
        assert "<harness>-" not in body, (
            "#26 item 2 VIOLATED: the <harness>- body placeholder was not re-expanded on install"
        )
        assert "claude-execute-phase" in body
        assert "claude-plan-phase" in body
        assert "claude-skill-editor" in body
        # name frontmatter is still rewritten to the installed name
        assert "name: claude-execute-phase" in body


def test_install_expands_harness_placeholder_for_non_claude_harness():
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
        _make_bundle(Path(src))
        install_skills(
            harness="codex", source=Path(src), destination=Path(dest), mode="copy", apply=True
        )
        body = (Path(dest) / "codex-execute-phase" / "SKILL.md").read_text(encoding="utf-8")
        assert "<harness>-" not in body
        assert "codex-execute-phase" in body
        assert "name: codex-execute-phase" in body


def test_alias_is_installed_as_prefixed_redirect_to_canonical_skill():
    # ABDRESOLVE CR: `/<harness>-advisor-panel` must resolve after reinstall. The
    # alias is installed FROM the canonical `advisor-board` source under the
    # prefixed alias name, so the maintainer's historical slash command runs
    # today's advisor-board skill (name frontmatter carries the alias name).
    assert SKILL_ALIASES.get("advisor-panel") == "advisor-board"
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
        _make_bundle(Path(src))
        actions = install_skills(
            harness="claude", source=Path(src), destination=Path(dest), mode="copy", apply=True
        )
        alias_dir = Path(dest) / "claude-advisor-panel"
        canonical_dir = Path(dest) / "claude-advisor-board"
        # both the canonical skill and its prefixed alias are installed
        assert canonical_dir.is_dir(), "canonical advisor-board not installed"
        assert alias_dir.is_dir(), "prefixed advisor-panel alias not installed"
        alias_body = (alias_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "name: claude-advisor-panel" in alias_body
        assert "<harness>-" not in alias_body  # body still re-expanded
        # the alias is recorded as an install action sourced from the canonical skill
        alias_action = next(a for a in actions if a.installed_name == "claude-advisor-panel")
        assert alias_action.source.endswith("advisor-board")


def test_alias_install_is_idempotent_and_refreshes_stale_dir():
    # A stale pre-rename dir must be overwritten by a reinstall, not orphaned.
    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
        _make_bundle(Path(src))
        alias_dir = Path(dest) / "claude-advisor-panel"
        alias_dir.mkdir(parents=True)
        (alias_dir / "SKILL.md").write_text(
            "---\nname: claude-advisor-panel\ndescription: STALE old body\n---\nSTALE\n",
            encoding="utf-8",
        )
        install_skills(
            harness="claude", source=Path(src), destination=Path(dest), mode="copy", apply=True
        )
        refreshed = (alias_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "STALE" not in refreshed, "stale alias dir was not refreshed on reinstall"
        assert "synthetic test skill" in refreshed  # now carries canonical content
