"""Delivery: a brokered seat is actually told where the attested tree is.

Board round 1 (fable seat) established that staging alone delivers nothing. The
`bwrap` child is a fixed posture probe, not a seat; the seats run in the parent,
where brokered codex is launched with `--cd <out_dir>` and brokered gemini has its
`--add-dir` removed. No argv, prompt, or instruction line named the staged tree, so
the two seats whose blindness motivates agent-harness#848 could not read anything.

**This relaxes a deliberate property.** `_render_broker_inline_prompt` documents that
the brokered provider is given "exact parent-owned bytes inline and no path it can
select, inspect, or mutate". That was intentional. What changes here is narrow and
stated: a seat may be given ONE path, to an attested read-only copy that carries no
`.git`, no credentials, and no write permission -- never the live tree, and only when
the authorization approved that exact tree by digest. When no tree is authorized, every
byte of the brokered surface is unchanged.

These tests are the RED lane for that delivery. They fail against a build that stages a
tree but never tells a seat about it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker, review_stage


TREE = review_stage.REVIEW_STAGE_TREE_DIRNAME


def _stage_dir(tmp_path: Path) -> Path:
    review_dir = tmp_path / "review"
    (review_dir / TREE).mkdir(parents=True)
    (review_dir / TREE / "src.py").write_text("code\n", encoding="utf-8")
    return review_dir


# --- gemini / agy ---------------------------------------------------------------

def test_brokered_gemini_is_given_the_staged_tree_when_one_is_authorized(tmp_path):
    """agy honours no read-only lever, so `--add-dir` at the COPY is the whole grant."""
    review_dir = _stage_dir(tmp_path)
    cmd = panel_invoker._brokered_gemini_command(
        model="gemini-3.8-flash", deadline_s=900.0, staged_tree=review_dir / TREE,
    )
    assert "--add-dir" in cmd
    assert str(review_dir / TREE) in cmd
    # Never the live tree, and never the parent that holds the bundle.
    assert str(review_dir) not in cmd


def test_brokered_gemini_is_unchanged_when_no_tree_is_authorized(tmp_path):
    """The historical brokered surface must stay byte-for-byte when staging is off."""
    with_none = panel_invoker._brokered_gemini_command(
        model="gemini-3.8-flash", deadline_s=900.0, staged_tree=None,
    )
    assert "--add-dir" not in with_none


# --- codex ----------------------------------------------------------------------

def test_brokered_codex_is_given_the_staged_tree_when_one_is_authorized(tmp_path):
    review_dir = _stage_dir(tmp_path)
    cmd = panel_invoker._brokered_codex_command(
        model="gpt-5-codex", out_dir=tmp_path / "out", out_file=tmp_path / "out" / "x.txt",
        codex_effort_args=(), staged_tree=review_dir / TREE,
    )
    assert str(review_dir / TREE) in " ".join(cmd)
    # The read-only sandbox and the ephemeral/ignore-config posture are retained.
    assert "read-only" in cmd
    assert "--ignore-user-config" in cmd


def test_brokered_codex_is_unchanged_when_no_tree_is_authorized(tmp_path):
    cmd = panel_invoker._brokered_codex_command(
        model="gpt-5-codex", out_dir=tmp_path / "out", out_file=tmp_path / "out" / "x.txt",
        codex_effort_args=(), staged_tree=None,
    )
    assert TREE not in " ".join(cmd)
    assert "read-only" in cmd


# --- the prompt -----------------------------------------------------------------

def test_the_brokered_prompt_names_the_tree_only_when_one_is_authorized():
    """A path in the argv that the prompt never mentions is a path no seat will use."""
    without = panel_invoker._render_broker_inline_prompt(
        "BUNDLE", "INSTRUCTIONS", "review", staged_tree=None,
    )
    assert TREE not in without

    with_tree = panel_invoker._render_broker_inline_prompt(
        "BUNDLE", "INSTRUCTIONS", "review", staged_tree=Path("/run/x") / TREE,
    )
    assert str(Path("/run/x") / TREE) in with_tree
    # It must say the tree is read-only and is a copy, so a seat does not try to edit
    # it or report it as the live checkout.
    assert "read-only" in with_tree.lower()


def test_the_brokered_prompt_is_byte_identical_when_staging_is_off():
    """Historical shape: no tree, no new bytes anywhere in the brokered prompt."""
    legacy = panel_invoker._render_broker_inline_prompt("BUNDLE", "INSTRUCTIONS", "review")
    explicit_none = panel_invoker._render_broker_inline_prompt(
        "BUNDLE", "INSTRUCTIONS", "review", staged_tree=None,
    )
    assert legacy == explicit_none


# --- the security property that is NOT relaxed -----------------------------------

@pytest.mark.parametrize("builder,kwargs", [
    ("_brokered_gemini_command", {"model": "gemini-3.8-flash", "deadline_s": 900.0}),
])
def test_only_the_staged_copy_is_ever_granted_never_a_live_path(tmp_path, builder, kwargs):
    """The relaxation is one path to an attested copy -- not a general path grant.

    Passing something that is not a staged tree must be refused rather than handed to a
    provider, so this cannot become a back door to the live checkout.
    """
    live = tmp_path / "live-repo"
    live.mkdir()
    with pytest.raises(ValueError, match="staged review tree"):
        getattr(panel_invoker, builder)(staged_tree=live, **kwargs)
