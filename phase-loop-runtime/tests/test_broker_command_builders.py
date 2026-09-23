"""Pure-refactor guard for the two brokered command builders.

Extracting the argv construction out of `_default_spawn` must change NOTHING. This lands on
its own, ahead of the behavioural change, because the last time a behavioural change rode
inside a larger diff on this file the board found the central claim was false. The argv is
also the attested provider surface, so a silent drift here is not a style problem.

These tests pin today's bytes exactly. They should fail loudly if the extraction alters a
flag, an order, or a default.
"""

from __future__ import annotations


from phase_loop_runtime import panel_invoker
from phase_loop_runtime.advisor_board.backing import (
    HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES,
)


def test_brokered_codex_argv_is_unchanged(tmp_path):
    out_dir = tmp_path / "out"
    out_file = out_dir / "panel-codex.txt"
    cmd = panel_invoker._brokered_codex_command(
        model=None, out_dir=out_dir, out_file=out_file, codex_effort_args=(),
    )
    assert cmd == [
        "codex",
        *(i for f in panel_invoker._BROKER_CODEX_DISABLED_FEATURES for i in ("--disable", f)),
        "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
        "--cd", str(out_dir), "--skip-git-repo-check", "--sandbox", "read-only",
        "--model", HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["codex"],
        "--output-last-message", str(out_file), "-",
    ]


def test_brokered_codex_argv_threads_model_and_effort(tmp_path):
    out_dir = tmp_path / "out"
    cmd = panel_invoker._brokered_codex_command(
        model="gpt-5-codex", out_dir=out_dir, out_file=out_dir / "x.txt",
        codex_effort_args=("-c", "model_reasoning_effort=xhigh"),
    )
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"
    assert "-c" in cmd and "model_reasoning_effort=xhigh" in cmd
    # effort args sit between --model and --output-last-message, as before
    assert cmd.index("-c") > cmd.index("--model")
    assert cmd.index("-c") < cmd.index("--output-last-message")


def test_brokered_gemini_argv_is_unchanged():
    cmd = panel_invoker._brokered_gemini_command(
        model="gemini-3.8-flash", deadline_s=900.0,
    )
    assert cmd == [
        "agy", "--model", "gemini-3.8-flash", "--sandbox", "--mode", "plan",
        "--disable-slash-commands",
        "--input-format", "stream-json", "--output-format", "stream-json",
        "--print=",
        "--print-timeout", "900.0s",
    ]


def test_the_read_only_posture_is_still_the_default(tmp_path):
    """Until the delivery change lands, both seats stay exactly as confined as before."""
    codex = panel_invoker._brokered_codex_command(
        model=None, out_dir=tmp_path, out_file=tmp_path / "x", codex_effort_args=(),
    )
    assert codex[codex.index("--sandbox") + 1] == "read-only"
    assert "shell_tool" in panel_invoker._BROKER_CODEX_DISABLED_FEATURES
    assert "code_mode_host" in panel_invoker._BROKER_CODEX_DISABLED_FEATURES
    for disabled in ("shell_tool", "code_mode_host"):
        assert codex[codex.index(disabled) - 1] == "--disable"

    gemini = panel_invoker._brokered_gemini_command(model="m", deadline_s=1.0)
    assert "--add-dir" not in gemini
    assert "plan" in gemini
