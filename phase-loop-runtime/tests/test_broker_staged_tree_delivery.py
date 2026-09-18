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


def test_the_real_spawn_path_hands_a_seat_a_working_sandbox(tmp_path, monkeypatch):
    """End-to-end through `_default_spawn`, against the REAL command builders.

    The earlier version of this test asserted "the seat must be able to read the code"
    from inside a monkeypatched `_exec_leg`, which skips the brokered branch entirely --
    it pinned a capability of the fake while no brokered seat could read anything. This
    one intercepts at the last possible point instead: it captures the argv and prompt the
    real builders produced, then checks a command actually runs in that directory.
    """
    from phase_loop_runtime.advisor_board import backing

    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    (repo / "test_source.py").write_text(
        "from SOURCE import value\n\ndef test_value():\n    assert value == 42\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
        check=True,
    )
    source_digest = review_stage.review_tree_manifest_sha256(repo)

    seen: dict[str, object] = {}

    def _capture(leg, review_dir, out_dir, timeout_s, artifact, mode, model, **kwargs):
        review_dir = Path(review_dir)
        tree = panel_invoker._sandbox_in(review_dir)
        seen["tree"] = tree
        seen["codex_argv"] = panel_invoker._brokered_codex_command(
            model=None, out_dir=out_dir, out_file=Path(out_dir) / "x.txt",
            codex_effort_args=(), staged_tree=tree,
        )
        seen["gemini_argv"] = panel_invoker._brokered_gemini_command(
            model="gemini-3.8-flash", deadline_s=900.0, staged_tree=tree,
        )
        seen["prompt"] = panel_invoker._render_broker_inline_prompt(
            "B", "I", "review", staged_tree=tree,
        )
        # Run INSIDE the leg: the sandbox is disposable and `_default_spawn` correctly
        # reaps it on the way out, so anything checked afterwards is checking a corpse.
        if tree is not None:
            seen["red"] = subprocess.run(
                ["python3", "-m", "pytest", "test_source.py", "-q", "-p", "no:randomly"],
                cwd=tree, capture_output=True, text=True,
            )
            # Deliberately a DIFFERENT length: `41`->`42` is the same size and often the
            # same mtime second, so CPython's (mtime, size) pyc check does not fire and a
            # seat re-running a test would silently get its own stale bytecode. Worth
            # knowing about the sandbox, not a defect in it.
            (tree / "SOURCE.py").write_text("value = 42  # fixed\n", encoding="utf-8")
            seen["green"] = subprocess.run(
                ["python3", "-m", "pytest", "test_source.py", "-q", "-p", "no:randomly"],
                cwd=tree, capture_output=True, text=True,
            )
        return 0, "ok review", "log"

    monkeypatch.setattr(panel_invoker, "_exec_leg", _capture)

    auth = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL, staged_tree_sha256=source_digest,
    )
    panel_invoker._default_spawn(
        "gemini", "REVIEW BUNDLE BODY", repo_dir=repo,
        review_authorization=auth, canonical_repo_authority=repo,
    )

    tree = seen["tree"]
    assert tree is not None, "the real spawn path must produce a sandbox"

    # The seat is pointed at it, by both vendors and by the prompt.
    assert seen["codex_argv"][seen["codex_argv"].index("--cd") + 1] == str(tree)
    assert str(tree) in seen["gemini_argv"]
    assert str(tree) in seen["prompt"]

    # A command really ran there, and the failing test failed for its OWN reason.
    red = seen["red"]
    assert red.returncode != 0 and "assert 41 == 42" in red.stdout, (
        f"a seat must be able to run the code it reviews:\n{red.stdout}\n{red.stderr}"
    )
    # Editing the sandbox turned it green: the seat can TEST a hypothesis, not just read.
    assert seen["green"].returncode == 0, "a seat must be able to test a hypothesis"

    # None of it reached the reviewed tree, and the sandbox is gone afterwards.
    assert review_stage.review_tree_manifest_sha256(repo) == source_digest, (
        "nothing the seat did may reach the reviewed tree"
    )
    assert not tree.exists(), "the sandbox is disposable and must not survive the leg"


# --- all four seats, not just the two that were obviously blind ------------------

def test_every_seat_is_pointed_at_the_sandbox(tmp_path):
    """Harness-agnostic: codex, gemini, grok and the claude TUI adapter alike.

    The original defect was described as "codex and gemini cannot read", which is how the
    first pass came to wire only those two. grok is a fourth board seat, and the claude TUI
    adapter was the one leg that ALREADY had a path -- to the LIVE repo. Pointing it at the
    clone instead is a straight improvement, not a relaxation.
    """
    tree = _sandbox(tmp_path)

    codex = panel_invoker._brokered_codex_command(
        model=None, out_dir=tmp_path / "o", out_file=tmp_path / "o" / "x",
        codex_effort_args=(), staged_tree=tree,
    )
    assert codex[codex.index("--cd") + 1] == str(tree)

    gemini = panel_invoker._brokered_gemini_command(
        model="m", deadline_s=1.0, staged_tree=tree,
    )
    assert str(tree) in gemini

    grok = panel_invoker._brokered_grok_command(
        model=None, out_dir=tmp_path / "o", grok_effort_args=(), staged_tree=tree,
    )
    assert grok[grok.index("--cwd") + 1] == str(tree)
    # For grok the ALLOW-LIST is the enforcement lever, not a sandbox flag.
    assert "run_terminal_command" in grok[grok.index("--tools") + 1]

    claude = panel_invoker._claude_tui_command(tree.parent, tmp_path / "live-repo")
    assert str(tree) in claude
    assert str(tmp_path / "live-repo") not in claude, (
        "the TUI adapter must review the clone, not the live checkout"
    )


def test_grok_is_byte_identical_when_no_tree_is_authorized(tmp_path):
    legacy = panel_invoker._brokered_grok_command(
        model=None, out_dir=tmp_path / "o", grok_effort_args=(),
    )
    explicit_none = panel_invoker._brokered_grok_command(
        model=None, out_dir=tmp_path / "o", grok_effort_args=(), staged_tree=None,
    )
    assert legacy == explicit_none
    assert legacy[legacy.index("--tools") + 1] == "", "no sandbox means no tools"
    assert legacy[legacy.index("--cwd") + 1] == str(tmp_path / "o")


def test_the_claude_adapter_still_gets_the_live_repo_when_unsandboxed(tmp_path):
    """Byte-for-byte historical behaviour when nothing was staged."""
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    repo = tmp_path / "live-repo"
    repo.mkdir()
    cmd = panel_invoker._claude_tui_command(review_dir, repo)
    assert str(repo) in cmd


# --- the guard that makes the next harness safe ---------------------------------

def test_every_known_leg_has_sandbox_delivery_wired():
    """Adding a leg without a sandbox must fail here, not ship blind.

    The first pass covered codex and gemini and silently left grok out, because the defect
    had been described as "codex and gemini cannot read the code". `opencode` and `pi` are
    expected next -- the installer already targets five harnesses -- and the same omission
    would be just as invisible.
    """
    assert panel_invoker.legs_without_sandbox_delivery() == (), (
        "these legs would review code they cannot open: "
        f"{panel_invoker.legs_without_sandbox_delivery()}"
    )


def test_the_completeness_guard_would_actually_catch_a_missing_leg():
    """The instrument needs its own falsifier: a green guard and a vacuous one look alike."""
    assert panel_invoker.legs_without_sandbox_delivery(("codex", "opencode", "pi")) == (
        "opencode", "pi",
    )
