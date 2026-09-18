"""Delivery: a brokered seat is told where its sandbox is, and can work in it.

Board round 1 established that staging alone delivers nothing. The `bwrap` child is a fixed
posture probe, not a seat; the seats run in the parent, where brokered codex was launched
with `--cd <out_dir>` and brokered gemini had its `--add-dir` removed. No argv, prompt or
instruction line named the sandbox, so the two seats whose blindness motivates
agent-harness#848 could read nothing.

**This relaxes a deliberate property, and says so.** `_render_broker_inline_prompt`
documents that the brokered provider is given "no path it can select, inspect, or mutate".
That was intentional. What changes is bounded and stated: a seat is given ONE path, to a
disposable clone that is not the live checkout, carries no credentials, and exists only for
the length of the round. The trust model is that a panelist is trusted like the agent that
wrote the code -- the sandbox protects the reviewed tree, not against the reviewer.

When no tree is authorized, every byte of the brokered surface is unchanged, and that is
pinned rather than asserted in prose.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker, review_stage


TREE = review_stage.REVIEW_STAGE_TREE_DIRNAME


def _sandbox(tmp_path: Path) -> Path:
    """A staged sandbox shaped like the real one: a clone with a `work/` sibling."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "src.py").write_text("code under review\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
        check=True,
    )
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    staged = review_stage.stage_review_tree(repo, tmp_path / "scratch")
    staged.rename(review_dir / TREE)
    return review_dir / TREE


# --- codex ----------------------------------------------------------------------

def test_brokered_codex_works_in_the_sandbox_when_one_is_authorized(tmp_path):
    tree = _sandbox(tmp_path)
    cmd = panel_invoker._brokered_codex_command(
        model=None, out_dir=tmp_path / "out", out_file=tmp_path / "out" / "x.txt",
        codex_effort_args=(), staged_tree=tree,
    )
    # The seat lands IN the code, not in an empty output folder.
    assert cmd[cmd.index("--cd") + 1] == str(tree)
    # It can run things: that is the entire point.
    assert "shell_tool" not in _disabled_features(cmd)
    assert cmd[cmd.index("--sandbox") + 1] != "read-only", (
        "a read-only sandbox cannot host a test run"
    )


def test_brokered_codex_is_byte_identical_when_no_tree_is_authorized(tmp_path):
    out = tmp_path / "out"
    legacy = panel_invoker._brokered_codex_command(
        model=None, out_dir=out, out_file=out / "x.txt", codex_effort_args=(),
    )
    explicit_none = panel_invoker._brokered_codex_command(
        model=None, out_dir=out, out_file=out / "x.txt", codex_effort_args=(),
        staged_tree=None,
    )
    assert legacy == explicit_none
    assert legacy[legacy.index("--cd") + 1] == str(out)
    assert legacy[legacy.index("--sandbox") + 1] == "read-only"
    assert "shell_tool" in _disabled_features(legacy)


def _disabled_features(cmd: list[str]) -> set[str]:
    return {cmd[i + 1] for i, a in enumerate(cmd) if a == "--disable"}


# --- gemini / agy ---------------------------------------------------------------

def test_brokered_gemini_is_given_the_sandbox_when_one_is_authorized(tmp_path):
    tree = _sandbox(tmp_path)
    cmd = panel_invoker._brokered_gemini_command(
        model="gemini-3.8-flash", deadline_s=900.0, staged_tree=tree,
    )
    assert "--add-dir" in cmd and str(tree) in cmd
    # The parent review dir holds the bundle and instructions; granting it would hand the
    # seat its own attested inputs to edit.
    assert str(tree.parent) not in cmd


def test_brokered_gemini_is_byte_identical_when_no_tree_is_authorized():
    legacy = panel_invoker._brokered_gemini_command(model="m", deadline_s=1.0)
    explicit_none = panel_invoker._brokered_gemini_command(
        model="m", deadline_s=1.0, staged_tree=None,
    )
    assert legacy == explicit_none
    assert "--add-dir" not in legacy


# --- the prompt -----------------------------------------------------------------

def test_the_prompt_names_the_sandbox_only_when_one_is_authorized(tmp_path):
    """A path in the argv that the prompt never mentions is a path no seat will use."""
    tree = _sandbox(tmp_path)
    without = panel_invoker._render_broker_inline_prompt("B", "I", "review", staged_tree=None)
    assert TREE not in without

    with_tree = panel_invoker._render_broker_inline_prompt(
        "B", "I", "review", staged_tree=tree,
    )
    assert str(tree) in with_tree
    lowered = with_tree.lower()
    assert "disposable" in lowered or "throwaway" in lowered, (
        "a seat must know edits are experiments, not deliverables"
    )


def test_the_prompt_is_byte_identical_when_staging_is_off():
    legacy = panel_invoker._render_broker_inline_prompt("B", "I", "review")
    explicit_none = panel_invoker._render_broker_inline_prompt(
        "B", "I", "review", staged_tree=None,
    )
    assert legacy == explicit_none


# --- the boundary that is NOT relaxed --------------------------------------------

@pytest.mark.parametrize(
    "builder,kwargs",
    [
        ("_brokered_gemini_command", {"model": "m", "deadline_s": 900.0}),
        ("_brokered_codex_command",
         {"model": None, "codex_effort_args": ()}),
    ],
)
def test_a_path_that_is_not_a_staged_sandbox_is_refused(tmp_path, builder, kwargs):
    """The relaxation is one path to a staged clone -- not a general path grant.

    Without this, the same argument becomes a back door to the live checkout.
    """
    live = tmp_path / "live-repo"
    live.mkdir()
    subprocess.run(["git", "init", "-q", str(live)], check=True)
    if builder == "_brokered_codex_command":
        kwargs = {**kwargs, "out_dir": tmp_path / "out", "out_file": tmp_path / "out" / "x"}

    with pytest.raises(ValueError, match="staged review tree"):
        getattr(panel_invoker, builder)(staged_tree=live, **kwargs)


def test_the_sandbox_is_a_clone_so_the_reviewed_tree_cannot_be_reached(tmp_path):
    """Defence in depth: even granted, the path leads to a copy with its own object store."""
    tree = _sandbox(tmp_path)
    assert (tree / ".git").is_dir()
    assert not (tree / ".git" / "objects" / "info" / "alternates").exists()
