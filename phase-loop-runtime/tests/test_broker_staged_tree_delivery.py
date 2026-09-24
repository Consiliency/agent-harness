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
    # It can run things: that is the entire point. codex runs commands through the
    # code-mode host, so enabling the bare shell alone is not enough ("code-mode host
    # is disabled" on every sandboxed seat before this was lifted too).
    assert "shell_tool" not in _disabled_features(cmd)
    assert "code_mode_host" not in _disabled_features(cmd)
    # Everything else stays disabled: exactly this literal pair is lifted, so widening
    # the constant later fails here rather than passing by construction.
    assert set(panel_invoker._BROKER_CODEX_DISABLED_FEATURES) - set(_disabled_features(cmd)) == {
        "shell_tool", "code_mode_host",
    }
    # /tmp and $TMPDIR are NOT writable: the round's scratch dir (every seat's verdict
    # file) lives under /tmp, and workspace-write leaves both writable by default.
    for setting in ("sandbox_workspace_write.exclude_slash_tmp=true",
                    "sandbox_workspace_write.exclude_tmpdir_env_var=true"):
        assert setting in cmd and cmd[cmd.index(setting) - 1] == "-c", setting
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

    # This test is about DELIVERY, not egress. Egress now fails CLOSED, so on a host
    # without user namespaces (a bare CI container) the leg would refuse before reaching
    # `_exec_leg` and this would fail for an unrelated reason. Declare the best-effort
    # posture explicitly rather than weakening the default; the refusal itself is asserted
    # by `test_a_host_that_cannot_isolate_refuses_the_leg` below.
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")

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


# --- the preamble must match what the seat can actually DO -----------------------

def test_a_seat_that_cannot_act_is_not_told_that_it_can(tmp_path):
    """Audit finding: the sandbox preamble reached seats with no way to use it.

    Brokered claude runs with `--tools "" --allowedTools ""` and an explicit disallow list,
    so every capability the preamble names is absent. Brokered agy is worse: its settings
    deny `read_file(*)` and `command(*)`, and the brokered argv omits
    `--dangerously-skip-permissions`, which this file documents as the difference between a
    review and a dead leg -- the FIRST auto-denied tool call destroys the entire response.

    So "run the test, check the history" is not a useless suggestion to those seats, it is
    an instruction to zero themselves.
    """
    assert panel_invoker.sandbox_usable_by("codex", brokered=True) is True
    assert panel_invoker.sandbox_usable_by("grok", brokered=True) is True
    assert panel_invoker.sandbox_usable_by("claude", brokered=True) is False
    assert panel_invoker.sandbox_usable_by("gemini", brokered=True) is False
    # Non-brokered routes are a different posture and keep their grant.
    assert panel_invoker.sandbox_usable_by("gemini", brokered=False) is True


def test_an_incapable_seat_gets_the_historical_sealed_preamble(tmp_path):
    """It must fall back cleanly, not receive a half-sandbox prompt."""
    tree = _sandbox(tmp_path)
    capable = panel_invoker._render_broker_inline_prompt("B", "I", "review", staged_tree=tree)
    incapable = panel_invoker._render_broker_inline_prompt("B", "I", "review", staged_tree=None)
    assert "You MAY run commands" in capable
    assert "You MAY run commands" not in incapable
    assert "Do not use or request tools" in incapable


def test_the_completeness_guard_covers_both_claude_routes():
    """The guard named only the non-brokered builder, so it passed while the route claude
    actually takes in production had no delivery at all. A completeness check that names
    the wrong function reports coverage it never had."""
    assert panel_invoker.legs_without_sandbox_delivery() == ()
    assert "claude:brokered" in panel_invoker._SANDBOX_DELIVERY_BUILDERS


def test_the_evidence_records_the_controls_actually_in_force(tmp_path):
    """Audit item 7: the tuples were hardcoded and went false under a sandbox.

    grok recorded `tools-empty` while its allow-list carried `run_terminal_command`; codex
    recorded `read-only` and a disabled `shell_tool` while running `workspace-write` with
    the shell enabled. A record that overstates the controls is the same fail-open as a
    sandbox claiming isolation it lacks: a reader cannot tell a confined seat from one that
    merely recorded itself as confined.
    """
    tree = _sandbox(tmp_path)

    codex_plain = panel_invoker._broker_tool_controls("codex", None)
    codex_boxed = panel_invoker._broker_tool_controls("codex", tree)
    assert "read-only" in codex_plain and "shell_tool" in codex_plain
    assert "read-only" not in codex_boxed, "it is workspace-write with a sandbox"
    assert "shell_tool" not in codex_boxed, "the shell is enabled with a sandbox"
    assert "code_mode_host" in codex_plain
    assert "code_mode_host" not in codex_boxed, "command execution is enabled with a sandbox"
    assert "tmp-not-writable" in codex_boxed, "the /tmp exclusion is a control in force"
    assert "tmp-not-writable" not in codex_plain, "read-only needs no /tmp exclusion"

    grok_plain = panel_invoker._broker_tool_controls("grok", None)
    grok_boxed = panel_invoker._broker_tool_controls("grok", tree)
    assert "tools-empty" in grok_plain
    assert "tools-empty" not in grok_boxed, "the allow-list is not empty with a sandbox"
    assert "tools-sandbox-allowlist" in grok_boxed


def test_a_research_seat_gets_neither_the_live_repo_nor_the_sandbox(tmp_path):
    """Regression: the sandbox branch was placed AHEAD of an existing guard.

    `_claude_tui_command` withholds a source directory from a research seat because such a
    seat has network access AND pre-approved Write, and granting source combines them. My
    first version checked the sandbox before that guard, so research seats silently gained
    a directory the existing code deliberately withheld. Whether a disposable clone is safe
    enough for a research seat may well be true -- it is not a question to answer by
    accident.
    """
    import dataclasses
    from phase_loop_runtime.advisor_board.research import ResearchSeatConfig

    tree = _sandbox(tmp_path)
    review_dir = tree.parent
    repo = tmp_path / "live-repo"
    repo.mkdir()

    def _stub(field):
        return Path(tmp_path / field.name) if field.type in (Path, "Path") else "x"

    seat = ResearchSeatConfig(**{
        f.name: _stub(f) for f in dataclasses.fields(ResearchSeatConfig)
    })
    cmd = panel_invoker._claude_tui_command(review_dir, repo, research_seat=seat)

    assert str(tree) not in cmd, "a research seat must not receive the sandbox"
    assert str(repo) not in cmd, "nor the live repo, which was always the rule"

    # A normal seat still gets it.
    plain = panel_invoker._claude_tui_command(review_dir, repo)
    assert str(tree) in plain


def test_the_tui_prompt_names_the_sandbox_and_its_real_limits(tmp_path):
    """The TUI leg was granted the clone as an add-dir and never told it existed.

    It runs with `allowed_tools = "Read,Write"` and no `Bash`: it can open and edit the
    code, and cannot run it. A grant the seat is never told about is wasted; a grant
    described as more than it is produces a seat that reports checks it could not perform.
    """
    tree = _sandbox(tmp_path)
    with_box = panel_invoker._render_leg_prompt("BUNDLE", tree.parent, "review")
    assert str(tree) in with_box
    assert "cannot run commands" in with_box.lower(), "it must not imply execution"
    assert "deleted when this review ends" in with_box

    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    (plain_dir / "review-bundle.md").write_text("b\n", encoding="utf-8")
    without = panel_invoker._render_leg_prompt("BUNDLE", plain_dir, "review")
    assert "disposable copy" not in without, "unchanged when nothing is staged"


def test_a_fabricated_marker_no_longer_passes_provenance(tmp_path):
    """Board round 3: 40 zeroes plus an EMPTY `.git/objects` satisfied the check.

    A panelist can build that shape inside its own writable clone. Provenance must ask git
    whether the recorded commit actually exists, not whether a directory does.
    """
    fake = tmp_path / "review" / review_stage.REVIEW_STAGE_TREE_DIRNAME
    (fake / ".git" / "objects").mkdir(parents=True)
    (fake / ".git" / "phase-loop-source-commit").write_text("0" * 40 + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not present in it|not a git repository"):
        panel_invoker._require_staged_tree(fake)


def test_a_real_staged_tree_still_passes_provenance(tmp_path):
    """Negative control: tightening must not reject genuine sandboxes."""
    tree = _sandbox(tmp_path)
    assert panel_invoker._require_staged_tree(tree) == tree


def test_a_host_that_cannot_isolate_refuses_the_leg(tmp_path, monkeypatch):
    """The activation test for fail-closed: refusal reaches the real spawn path.

    Four board rounds produced a mechanism that refused correctly in isolation while the
    launch went ahead anyway, so asserting on `isolated_network` alone proves nothing about
    what a seat actually gets. This drives `_default_spawn` end to end with the mechanism
    absent and requires that no leg runs.
    """
    import subprocess
    from phase_loop_runtime import panel_invoker, review_stage, sandbox_egress
    from phase_loop_runtime.advisor_board import backing

    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
        check=True,
    )

    launched: list[str] = []
    monkeypatch.setattr(
        panel_invoker, "_exec_leg",
        lambda *a, **k: launched.append("leg") or (0, "ok", "log"),
    )
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", raising=False)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)

    auth = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=review_stage.review_tree_manifest_sha256(repo),
    )

    _result = panel_invoker._default_spawn(
        "gemini", "REVIEW BUNDLE BODY", repo_dir=repo,
        review_authorization=auth, canonical_repo_authority=repo,
    )
    # `_default_spawn` returns 2- or 3-tuples; the reason is always LAST.
    status, detail = _result[0], _result[-1]

    assert launched == [], (
        "the leg ran on a host that cannot enforce the policy -- this is the fail-open "
        "that survived four board rounds"
    )
    # `_default_spawn`'s fail-closed handler turns the refusal into a DEGRADED seat rather
    # than propagating: the round reports a seat it could not safely fill, which is what
    # the operator needs to see. What matters is that NOTHING ran, and that the reason is
    # legible rather than an anonymous failure.
    assert status == "DEGRADED"
    assert "network restriction" in detail, f"the operator cannot act on {detail!r}"


def test_the_opt_out_lets_that_same_host_proceed(tmp_path, monkeypatch):
    """The falsifier for the test above: refusal must come from the POSTURE, not a
    fixture that was broken anyway."""
    import subprocess
    from phase_loop_runtime import panel_invoker, review_stage, sandbox_egress
    from phase_loop_runtime.advisor_board import backing

    repo = tmp_path / "reviewed-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "SOURCE.py").write_text("value = 41\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
        check=True,
    )

    launched: list[str] = []
    monkeypatch.setattr(
        panel_invoker, "_exec_leg",
        lambda *a, **k: launched.append("leg") or (0, "ok", "log"),
    )
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: False)

    auth = backing.ReviewIsolationAuthorization(
        operation="public_board_review.v1", purpose="t", input_sha256="0" * 64,
        instructions_sha256="1" * 64, broker_contract=backing.PARENT_UNIX_BROKER_V1,
        routes=(), readonly_tools=("Read",), child_credentialless=True,
        child_network_egress=False, live_tree_exposed=False, api_fallback=False,
        canonical_repo_sha256="2" * 64, issued_monotonic_ns=0,
        _seal=backing._AUTHORIZATION_SEAL,
        staged_tree_sha256=review_stage.review_tree_manifest_sha256(repo),
    )

    with pytest.warns(RuntimeWarning, match="refusing to launch WITHOUT"):
        panel_invoker._default_spawn(
            "gemini", "REVIEW BUNDLE BODY", repo_dir=repo,
            review_authorization=auth, canonical_repo_authority=repo,
        )

    assert launched == ["leg"], "the opt-out must let an unfilterable host still review"


def test_only_a_sandboxed_codex_seat_keeps_setfcap_at_launch(tmp_path, monkeypatch):
    """agent-harness#1003: the retained capability is scoped to the ONE seat that needs it.

    A sandboxed codex seat runs commands in codex's own bubblewrap, which needs CAP_SETFCAP
    to start inside the egress namespace. The sealed codex seat and every other seat keep
    an empty bounding set.
    """
    seen: list[tuple[str, tuple[str, ...]]] = []

    def fake_liveness(cmd, **kwargs):
        seen.append((cmd[0], tuple(kwargs.get("retain_caps", ()))))
        return panel_invoker._LegRun(0, "AGREE", "")

    monkeypatch.setattr(panel_invoker, "_run_leg_with_liveness", fake_liveness)
    monkeypatch.setattr(panel_invoker, "_leg_auth_ok", lambda *a, **k: (True, ""))

    tree = _sandbox(tmp_path)
    boxed_review = tree.parent
    sealed_review = tmp_path / "sealed-review"
    sealed_review.mkdir()
    for leg, review_dir in (("codex", boxed_review), ("codex", sealed_review), ("grok", boxed_review)):
        out = tmp_path / f"out-{leg}-{review_dir.name}"
        out.mkdir()
        panel_invoker._exec_leg(leg, review_dir, out, broker_prompt="P", broker_evidence={})

    # Distinct launches, in order: the leg may retry a soft-empty attempt, and every
    # attempt must carry the same decision, so dedupe rather than pin the retry count.
    assert list(dict.fromkeys(seen)) == [("codex", ("setfcap",)), ("codex", ()), ("grok", ())], seen
    assert panel_invoker._BROKER_CODEX_SANDBOX_RETAINED_CAPS == ("setfcap",)
    assert "bounding-set-setfcap-only" in panel_invoker._broker_tool_controls("codex", tree)
    assert "bounding-set-setfcap-only" not in panel_invoker._broker_tool_controls("codex", None)
