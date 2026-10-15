"""A sandboxed grok seat can run the tools its allow-list grants it.

In a board, grok ended DEGRADED (``process_exit_or_failure``, rc 0) after printing one
preamble line. The sandboxed seat's allow-list grants ``run_terminal_command``, ``write``
and ``search_replace``, but its argv also carried ``--permission-mode plan``. In headless
grok (1.0.52), plan mode sends every call to one of those tools to an approver, and a
headless run has none. The first shell call came back "User cancelled", the turn ended
with ``stop_reason: cancelled``, and grok exited 0 with only the preamble.

Grok run by hand did not show this, because a Claude Code compatibility settings file in
the operator's HOME approved the call. A seat's HOME is a fresh tmpfs and holds no such
file. Whether grok can use its tools therefore has to come from the argv the product builds,
not from whatever the host happens to hold.

The sandbox and the allow-list are the boundary for the sandboxed seat. The approval mode
is not, and both stay unchanged. The route without a sandbox keeps ``plan`` and an empty
allow-list, byte for byte.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import review_stage


# Built-ins that act rather than read. Under a mode that asks first, a headless run cancels them.
_ACTING_TOOLS = {"run_terminal_command", "run_terminal_cmd", "write", "search_replace"}
# Modes in which grok asks before it acts. With no approver, headless grok cancels the call.
_ASKING_MODES = {"plan", "default"}


def _staged_tree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@e.st"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "stats.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "c"],
                   check=True)
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    staged = review_stage.stage_review_tree(repo, tmp_path / "scratch")
    staged.rename(review_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME)
    return review_dir / review_stage.REVIEW_STAGE_TREE_DIRNAME


def _value(argv: list[str], flag: str) -> str:
    assert argv.count(flag) == 1, (flag, argv)
    return argv[argv.index(flag) + 1]


def _granted_acting_tools(argv: list[str]) -> set[str]:
    return set(_value(argv, "--tools").split(",")) & _ACTING_TOOLS


def _launched_grok_argv(monkeypatch, review_dir: Path, out_dir: Path) -> list[str]:
    """The argv the product hands the launch boundary for the brokered grok leg."""
    seen: list[list[str]] = []

    def fake_liveness(cmd, **_kwargs):
        seen.append(list(cmd))
        return pi._LegRun(0, "AGREE", "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    pi._exec_leg("grok", review_dir, out_dir, broker_prompt="P", broker_evidence={})
    assert len(seen) == 1, seen
    return seen[0]


def test_the_sandboxed_seat_launches_in_a_mode_that_runs_the_tools_it_is_granted(
        tmp_path, monkeypatch):
    tree = _staged_tree(tmp_path)
    argv = _launched_grok_argv(monkeypatch, tree.parent, tmp_path / "out")
    granted = _granted_acting_tools(argv)
    # The check's own premise: this seat really is granted tools that act. An empty set
    # here would make the assertion below vacuous.
    assert {"run_terminal_command", "write", "search_replace"} <= granted, argv
    mode = _value(argv, "--permission-mode")
    assert mode not in _ASKING_MODES, (
        f"--permission-mode {mode} asks before {sorted(granted)}, and a headless seat has "
        f"no approver: the first call is cancelled and the turn ends with rc 0")
    assert mode == "bypassPermissions", argv
    # The boundary is unchanged: the same allow-list, working in the clone.
    assert _value(argv, "--tools") == pi.GROK_SANDBOX_TOOLS
    assert _value(argv, "--cwd") == str(tree)


# The built-ins headless grok 1.0.52 offered a sandboxed seat with `--tools` set to the
# allow-list: 19 names, measured from the seat's own tool definitions. Under an approving mode
# every name here that the allow-list does not grant must be removed explicitly.
_GROK_1_0_52_OFFERED = {
    "ask_user_question", "enter_plan_mode", "exit_plan_mode", "grep", "image_edit",
    "image_gen", "image_to_video", "list_dir", "monitor", "read_file", "reference_to_video",
    "run_terminal_command", "search_replace", "search_tool", "send_feedback", "todo_write",
    "use_tool", "workflow", "write",
}


def test_the_approving_mode_ships_with_every_unlisted_builtin_removed(tmp_path, monkeypatch):
    tree = _staged_tree(tmp_path)
    argv = _launched_grok_argv(monkeypatch, tree.parent, tmp_path / "out")
    granted = set(_value(argv, "--tools").split(","))
    removed = set(_value(argv, "--disallowed-tools").split(","))
    assert granted <= _GROK_1_0_52_OFFERED, granted - _GROK_1_0_52_OFFERED
    assert _GROK_1_0_52_OFFERED - granted == removed, (
        f"left to the approving mode: {sorted(_GROK_1_0_52_OFFERED - granted - removed)}; "
        f"removing a granted tool: {sorted(removed & granted)}")
    # The exact sets, by name: widening the allow-list and shrinking the denylist together
    # keeps the partition above consistent, so it is pinned literally as well.
    assert granted == {
        "read_file", "grep", "list_dir", "search_tool", "write", "search_replace",
        "run_terminal_command",
    }
    assert removed == {
        "ask_user_question", "enter_plan_mode", "exit_plan_mode", "image_edit", "image_gen",
        "image_to_video", "reference_to_video", "monitor", "send_feedback", "todo_write",
        "use_tool", "workflow",
    }


def test_the_unsandboxed_seat_is_byte_for_byte_the_historical_argv(tmp_path):
    argv = pi._brokered_grok_command(model=None, out_dir=tmp_path / "o", grok_effort_args=())
    assert argv == [
        "grok", "--disable-web-search", "--no-memory", "--no-subagents",
        "--permission-mode", "plan", "--prompt-file", "/dev/stdin",
        "--output-format", "plain", "--cwd", str(tmp_path / "o"), "-m",
        pi.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["grok"], "--tools", "",
    ]
    assert "--disallowed-tools" not in argv


def test_the_unsandboxed_and_read_only_routes_still_deliver_a_verdict(tmp_path, monkeypatch):
    """Regression for the routes this change leaves alone: each still launches in its own
    mode and its review text still reaches the board as an OK verdict."""
    seen: list[list[str]] = []

    def fake_liveness(cmd, **_kwargs):
        seen.append(list(cmd))
        return pi._LegRun(0, "No blocking defect.\n\nAGREE", "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    review_dir = tmp_path / "sealed-review"
    review_dir.mkdir()
    for brokered, out in ((True, tmp_path / "o1"), (False, tmp_path / "o2")):
        out.mkdir()
        rc, text, _log = pi._exec_leg(
            "grok", review_dir, out, artifact="P",
            **({"broker_prompt": "P", "broker_evidence": {}} if brokered else {}))
        assert pi._classify_leg(rc, text, _log, "review") == "OK", (brokered, rc, text)
    brokered_argv, readonly_argv = seen
    assert _value(brokered_argv, "--permission-mode") == "plan"
    assert "--permission-mode" not in readonly_argv
    assert _value(readonly_argv, "--tools") == pi.GROK_REVIEW_READONLY_TOOLS
    assert "--disallowed-tools" not in brokered_argv + readonly_argv


def test_the_unsandboxed_seat_keeps_plan_and_no_tools(tmp_path, monkeypatch):
    review_dir = tmp_path / "sealed-review"
    review_dir.mkdir()
    argv = _launched_grok_argv(monkeypatch, review_dir, tmp_path / "out")
    assert _value(argv, "--permission-mode") == "plan"
    assert _value(argv, "--tools") == ""
    assert not _granted_acting_tools(argv)


def test_the_builder_never_pairs_an_asking_mode_with_acting_tools(tmp_path):
    tree = _staged_tree(tmp_path)
    for staged in (None, tree):
        argv = pi._brokered_grok_command(
            model=None, out_dir=tmp_path / "o", grok_effort_args=(), staged_tree=staged)
        if _granted_acting_tools(argv):
            assert _value(argv, "--permission-mode") not in _ASKING_MODES, argv


def test_the_evidence_records_the_approval_mode_actually_in_force(tmp_path):
    """The recorded controls follow the argv; a record that says ``permission-plan`` while
    the seat runs in an approving mode overstates its confinement."""
    tree = _staged_tree(tmp_path)
    plain = pi._broker_tool_controls("grok", None)
    boxed = pi._broker_tool_controls("grok", tree)
    assert "permission-plan" in plain
    assert "permission-plan" not in boxed
    assert "permission-bypass-inside-seat-sandbox" in boxed
    assert "permission-bypass-inside-seat-sandbox" not in plain
    assert "disallowed-unlisted-builtins" in boxed
    assert "disallowed-unlisted-builtins" not in plain
