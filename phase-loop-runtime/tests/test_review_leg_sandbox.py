"""IF-0-SANDBOX-1 — per-vendor review-leg sandbox regression (SANDBOX / REVIEWGOV D3).

A review leg must not be able to write the reviewed tree. The per-vendor
mechanism, FROZEN here, differs because the read-only lever differs per CLI:

  * codex  — honors ``--sandbox read-only`` (panel leg); ``as-is``.
  * claude  — plan/Read-only permission; ``as-is``.
  * grok    — headless ``grok -p`` auto-approves writes, so ``--sandbox`` is
              useless; the lever is a ``--tools`` read/search allow-list.
  * gemini  — ``agy`` honors NO read-only lever at all (``--sandbox`` still writes,
              no per-tool restriction), so the ONLY sound mechanism is a STAGED
              COPY of the tree — the ``review`` action points ``--add-dir`` at a
              throwaway gitignore-aware copy, never the live worktree.

These tests pin the launcher product-loop ``review`` surface (the one that pointed
agy at the live repo) and, as a second surface, that the panel/advisor-board legs
are confined to a bundle-only review dir that never contains the repo.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import launcher
from phase_loop_runtime.launcher import (
    GEMINI_REVIEW_STAGE_PREFIX,
    GROK_REVIEW_READONLY_TOOLS,
    _cleanup_paths,
    _resolve_gemini_review_stage,
    _review_stage_cleanup_paths,
    _stage_review_tree,
    build_gemini_command,
    build_grok_command,
)
from phase_loop_runtime.profiles import resolve_profile_for_executor


def _git_review_repo(tmp_path: Path) -> Path:
    """A git checkout with a modified tracked file, an untracked-non-ignored file,
    and an ignored build artifact — so a staged copy can be checked for exactly the
    working-tree state (committed + uncommitted, minus ignored)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "tracked.py").write_text("print('committed')\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "artifact.o").write_text("BUILD-JUNK\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    # Uncommitted working-tree state a reviewer must see:
    (repo / "tracked.py").write_text("print('dirty working tree')\n", encoding="utf-8")
    (repo / "uncommitted.py").write_text("print('new untracked')\n", encoding="utf-8")
    return repo


# --- gemini/agy: review points at a staged copy, execute at the live repo --------

def test_gemini_review_command_uses_stage_placeholder_not_live_repo():
    selection = resolve_profile_for_executor(action="review", executor="gemini")
    cmd = build_gemini_command(
        Path("/repo"), selection, action="review", context_file=launcher.GEMINI_CONTEXT_PLACEHOLDER
    )
    add_dir = cmd[cmd.index("--add-dir") + 1]
    assert add_dir == f"{GEMINI_REVIEW_STAGE_PREFIX}/repo"
    assert add_dir != "/repo", "review agy must NOT be handed the live repo path"
    # A review leg auto-approves nothing; omission is documented but the staged copy
    # is the load-bearing guarantee.
    assert "--dangerously-skip-permissions" not in cmd


def test_gemini_execute_command_uses_live_repo_unchanged():
    selection = resolve_profile_for_executor(action="execute", executor="gemini")
    cmd = build_gemini_command(
        Path("/repo"), selection, action="execute", context_file=launcher.GEMINI_CONTEXT_PLACEHOLDER
    )
    add_dir = cmd[cmd.index("--add-dir") + 1]
    assert add_dir == "/repo"
    assert not add_dir.startswith(GEMINI_REVIEW_STAGE_PREFIX)
    assert "--dangerously-skip-permissions" in cmd


def test_stage_review_tree_is_gitignore_aware_working_tree_copy(tmp_path):
    repo = _git_review_repo(tmp_path)
    staged = _stage_review_tree(repo, None)
    try:
        assert staged != repo
        assert Path(staged).name.startswith("pl-review-stage-")
        # working-tree content, including the uncommitted modification
        assert (staged / "tracked.py").read_text(encoding="utf-8") == "print('dirty working tree')\n"
        # untracked-but-not-ignored file is present
        assert (staged / "uncommitted.py").is_file()
        # ignored artifacts and VCS metadata are excluded
        assert not (staged / "ignored").exists()
        assert not (staged / ".git").exists()
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def test_review_leg_write_cannot_touch_the_reviewed_tree(tmp_path):
    """The core sandbox guarantee: a write-capable leg mutating its (staged)
    workspace leaves the live reviewed tree untouched."""
    repo = _git_review_repo(tmp_path)
    staged = _stage_review_tree(repo, None)
    try:
        # Simulate an unconstrained agy leg mutating + creating files in its workspace.
        (staged / "tracked.py").write_text("MALICIOUS OVERWRITE\n", encoding="utf-8")
        (staged / "evil.py").write_text("evil\n", encoding="utf-8")
        # The live worktree is unchanged.
        assert (repo / "tracked.py").read_text(encoding="utf-8") == "print('dirty working tree')\n"
        assert not (repo / "evil.py").exists()
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def test_resolve_gemini_review_stage_materializes_then_cleans(tmp_path):
    repo = _git_review_repo(tmp_path)
    command = ["agy", "--add-dir", f"{GEMINI_REVIEW_STAGE_PREFIX}{repo}", "-p", "review"]

    resolved = _resolve_gemini_review_stage(command, None, dry_run=False)
    staged = resolved[resolved.index("--add-dir") + 1]
    assert staged != str(repo)
    assert Path(staged).name.startswith("pl-review-stage-")
    assert (Path(staged) / "tracked.py").is_file()

    # Cleanup detection finds the staged dir, and _cleanup_paths removes a directory.
    paths = _review_stage_cleanup_paths(resolved)
    assert staged in paths
    evidence = _cleanup_paths(paths)
    assert evidence is not None and staged in evidence["removed"]
    assert not Path(staged).exists()


def test_resolve_gemini_review_stage_dry_run_does_not_materialize(tmp_path):
    repo = _git_review_repo(tmp_path)
    command = ["agy", "--add-dir", f"{GEMINI_REVIEW_STAGE_PREFIX}{repo}", "-p", "review"]
    before = set((tmp_path).iterdir())
    resolved = _resolve_gemini_review_stage(command, None, dry_run=True)
    # Dry-run resolves to the live path (nothing runs) and creates no staged copy.
    assert resolved[resolved.index("--add-dir") + 1] == str(repo)
    assert not _review_stage_cleanup_paths(resolved)
    assert set((tmp_path).iterdir()) == before


# --- grok: review carries the read-only tool allow-list --------------------------

def test_grok_review_command_read_only_tools_allow_list():
    selection = resolve_profile_for_executor(action="review", executor="grok")
    cmd = build_grok_command(
        Path("/repo"), selection, action="review", context_file=launcher.GROK_CONTEXT_PLACEHOLDER
    )
    assert cmd[cmd.index("--tools") + 1] == GROK_REVIEW_READONLY_TOOLS
    assert "--dangerously-skip-permissions" not in cmd
    # None of grok's write built-ins are in the allow-list.
    for write_tool in ("write", "search_replace", "run_terminal_command"):
        assert write_tool not in GROK_REVIEW_READONLY_TOOLS


def test_grok_execute_command_is_not_read_only():
    selection = resolve_profile_for_executor(action="execute", executor="grok")
    cmd = build_grok_command(
        Path("/repo"), selection, action="execute", context_file=launcher.GROK_CONTEXT_PLACEHOLDER
    )
    # execute must NOT carry the read-only review allow-list.
    if "--tools" in cmd:
        assert cmd[cmd.index("--tools") + 1] != GROK_REVIEW_READONLY_TOOLS


# --- panel/advisor-board surface: legs confined to a bundle-only review dir -------

def test_panel_leg_review_dir_never_contains_the_repo(tmp_path, monkeypatch):
    """The cross-vendor CR (invoke_panel) stages a bundle-only review dir; the repo
    is never mounted for a non-claude leg, so it cannot be written by construction."""
    from phase_loop_runtime import panel_invoker

    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    (repo / "SECRET_SOURCE.py").write_text("live tree file\n", encoding="utf-8")

    seen: dict[str, list[str]] = {}

    def _fake_exec_leg(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
        seen["entries"] = sorted(p.name for p in Path(review_dir).iterdir())
        return 0, "ok review", "log"

    monkeypatch.setattr(panel_invoker, "_exec_leg", _fake_exec_leg)
    status, _text = panel_invoker._default_spawn("gemini", "REVIEW BUNDLE BODY", repo_dir=repo)

    assert "SECRET_SOURCE.py" not in seen["entries"], "review dir must not contain the reviewed tree"
    assert seen["entries"] == ["review-bundle.md", "review-instructions.md"]
