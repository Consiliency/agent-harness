"""#36 — input-scaled leg timeout + argv assertions for ``panel_invoker._exec_leg``.

The previously-fixed 600s timeout silently timed out large-artifact frontier reviews,
degrading the panel to fewer legs (the failure that stayed hidden through the cross-repo
work because every test stubs the spawn boundary and none asserted the command / timeout).
These tests pin the input-scaling and the exact command construction (read-only sandbox +
``--output-last-message`` for codex; ``--add-dir`` + scaled ``--print-timeout`` for gemini).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from phase_loop_runtime import agy_canary_evidence as evidence
from phase_loop_runtime import panel_invoker as pi


def test_leg_timeout_scales_with_review_size():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # empty → base floor
        assert pi._leg_timeout_for(d) == pi._LEG_TIMEOUT_BASE_S
        # ~50 KB artifact → base + 50 * per-KB (below the cap), clearing codex-xhigh ~900s
        (d / "big.txt").write_text("x" * (50 * 1024))
        scaled = pi._leg_timeout_for(d)
        assert scaled == pi._LEG_TIMEOUT_BASE_S + 50 * pi._LEG_TIMEOUT_PER_KB_S
        assert scaled > pi._LEG_TIMEOUT_BASE_S
        assert scaled >= 900


def test_leg_timeout_is_capped():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "huge.txt").write_text("x" * (4 * 1024 * 1024))  # 4 MB → well over cap
        assert pi._leg_timeout_for(d) == pi._LEG_TIMEOUT_MAX_S


def _capture_run(monkeypatch, stdout: str = ""):
    """Capture the leg's ``_run_leg_with_liveness`` call.

    The leg exec no longer calls ``subprocess.run`` — it goes through the stall-aware
    ``_run_leg_with_liveness`` seam. We capture the ``cmd`` plus the ``deadline_s`` /
    ``stall_threshold_s`` / ``input_text`` kwargs. The codex auth preflight still uses
    ``subprocess.run``, so bypass it (fail-open logged-in) to reach the leg exec.
    """
    captured: dict = {}

    def fake_liveness(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["deadline_s"] = kwargs.get("deadline_s")
        captured["stall_threshold_s"] = kwargs.get("stall_threshold_s")
        captured["input_text"] = kwargs.get("input_text")
        return pi._LegRun(0, stdout, "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    return captured


def test_codex_leg_argv_is_read_only_with_output_last_message(monkeypatch):
    captured = _capture_run(monkeypatch)
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        pi._exec_leg("codex", Path(rd), Path(od))
    cmd = captured["cmd"]
    assert cmd[:2] == ["codex", "exec"]
    assert "--sandbox" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--output-last-message" in cmd
    # never the executor default that build_codex_command emits
    assert "danger-full-access" not in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    # Leg-liveness: the hard-kill is DECOUPLED from the input-scaled timeout and raised
    # to the _MAX_LEG_TIMEOUT_S backstop (a slow-but-streaming leg is no longer killed
    # at the 600s floor); stall detection uses the seam's _LEG_STALL_THRESHOLD_S default
    # (never overridden by the leg, so it is absent from the call kwargs).
    assert captured["deadline_s"] == pi._MAX_LEG_TIMEOUT_S
    assert captured["stall_threshold_s"] is None


def test_grok_leg_argv_is_headless_plain_with_reasoning_effort(monkeypatch):
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        rdp = Path(rd)
        pi._exec_leg("grok", rdp, Path(od))  # effort-absent → grok's max reasoning
    cmd = captured["cmd"]
    assert cmd[0] == "grok"
    assert "-p" in cmd  # single-turn headless prompt
    # plain headless output (stdout IS the review; no --output-last-message file)
    assert cmd[cmd.index("--output-format") + 1] == "plain"
    # runs the grok-4.5 default model at grok's MAX reasoning. The effort-absent default
    # renders through the SAME map as an explicit seat effort (ah#222): canonical ``max``
    # CLAMPS to grok's ``high`` ceiling (grok has no ``max``/``xhigh``), so the token the
    # CLI receives is a valid ``high`` — NOT the literal ``max`` that the grok CLI rejects
    # ("unknown effort level 'max'"), which used to ERROR the grok leg on every default run.
    assert cmd[cmd.index("-m") + 1] == "grok-4.5"
    assert cmd[cmd.index("--reasoning-effort") + 1] == "high"
    # regression guard: the invalid literal must never reach the CLI on the default path.
    assert "max" not in cmd
    # HARD READ-ONLY (GROKEXEC, agent-harness#147): headless `grok -p` auto-approves
    # writes, so the panel/CR reviewer leg is constrained by a `--tools` ALLOW-LIST of
    # read/search built-ins only. Assert EXACT equality with the shared allow-list —
    # because `--tools` is an allow-list, anything not named is excluded, so equality
    # is the airtight guard a regression cannot silently defeat.
    tools_value = cmd[cmd.index("--tools") + 1]
    assert tools_value == pi.GROK_REVIEW_READONLY_TOOLS == "read_file,grep,list_dir,search_tool"
    # Belt-and-suspenders: no write / privileged tool can appear in the allow-list.
    for forbidden in ("write", "search_replace", "run_terminal_command", "scheduler", "spawn_subagent", "memory", "image"):
        assert forbidden not in tools_value.split(","), f"{forbidden!r} must not be a grok reviewer tool"
    # The allow-list (not `--disable-web-search`) is the read-only lever, so that flag
    # is intentionally left off; assert it is not what enforces read-only here.
    assert "--disable-web-search" not in cmd
    # grok is a SLOW leg: the hard-kill is the raised _MAX_LEG_TIMEOUT_S backstop (no
    # longer a short input-scaled wall-clock); liveness rides the 180s stall default.
    assert captured["deadline_s"] == pi._MAX_LEG_TIMEOUT_S
    assert captured["stall_threshold_s"] is None


def test_grok_leg_renders_seat_effort_through_the_map(monkeypatch):
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        # a board seat's canonical effort reaches the CLI as --reasoning-effort <token>.
        pi._exec_leg("grok", Path(rd), Path(od), effort="high", model="grok-4.5")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--reasoning-effort") + 1] == "high"


def test_gemini_leg_argv_uses_add_dir_and_scaled_print_timeout(monkeypatch):
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        rdp = Path(rd)
        (rdp / "artifact.py").write_text("x" * (30 * 1024))
        pi._exec_leg("gemini", rdp, Path(od))
        expected_timeout = pi._leg_timeout_for(rdp)
    cmd = captured["cmd"]
    assert cmd[0] == "agy"
    assert "--add-dir" in cmd
    assert "--print-timeout" in cmd
    # --print-timeout is still the input-scaled timeout_s (agy's own internal budget)
    assert cmd[cmd.index("--print-timeout") + 1] == f"{expected_timeout}s"
    # ...but the process hard-kill is the raised _MAX_LEG_TIMEOUT_S backstop, decoupled
    # from that scaled value; liveness rides the 180s stall default (not overridden).
    assert captured["deadline_s"] == pi._MAX_LEG_TIMEOUT_S
    assert captured["stall_threshold_s"] is None


def test_gemini_leg_passes_prompt_inline_on_argv_not_stdin(monkeypatch):
    """Regression: ``agy -p -`` IGNORES stdin and runs an EMPTY prompt (it prints its
    "How can I help you today?" greeting), so the gemini leg silently returned a
    non-review on every run. The prompt MUST be the inline ``-p`` argv value, and the
    leg MUST NOT feed stdin. Mirrors the grok leg's inline-prompt convention."""
    captured = _capture_run(monkeypatch, stdout="AGREE")
    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as od:
        rdp = Path(rd)
        (rdp / "artifact.py").write_text("some code to review")
        pi._exec_leg("gemini", rdp, Path(od), artifact="REVIEW THIS ARTIFACT", mode="review")
    cmd = captured["cmd"]
    # the arg right after -p is the composed leg prompt (the staged-bundle pointer),
    # never the stdin sentinel "-" that made agy run an empty prompt.
    prompt_arg = cmd[cmd.index("-p") + 1]
    assert prompt_arg != "-"
    assert "review-bundle.md" in prompt_arg  # the real staged-bundle pointer prompt
    # and nothing is fed on stdin (feeding stdin was the empty-prompt bug): the gemini
    # leg passes NO input_text to the liveness seam, which then wires the child to DEVNULL.
    assert captured["input_text"] is None


def test_capture_enabled_gemini_translates_host_stage_in_prompt_and_argv(monkeypatch, tmp_path):
    """The production command exposes the host stage only as bwrap's bind source."""
    root = Path("/tmp") / f"phase-loop-agy-panel-{os.getpid()}-{tmp_path.name}"
    root.mkdir(mode=0o700)
    capture = evidence.AgyCanaryCapture(*evidence._validate_private_root(root))
    try:
        review_dir = tmp_path / "host-stage"
        review_dir.mkdir()
        instructions = review_dir / "review-instructions.md"
        bundle = review_dir / "review-bundle.md"
        instructions.write_text("read instructions\n")
        bundle.write_text("read bundle\n")
        instructions.chmod(0o600)
        bundle.chmod(0o600)
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "permissions": {"allow": []},
            "toolPermission": "request-review",
            "allowNonWorkspaceAccess": False,
        }))
        settings.chmod(0o600)
        evidence.create_capture(capture=capture, settings_path=settings, seat_key="gemini-primary")
        staged = evidence.retain_staged_files(capture=capture, review_dir=review_dir)
        home = tmp_path / "minimal-home"
        home.mkdir(mode=0o700)
        namespace = evidence.AgyCanaryNamespace(
            stage=review_dir,
            minimal_home=home,
            evidence_root=root,
            provider_hostname="example.invalid",
        )
        captured: dict[str, object] = {}
        stream = "\n".join(json.dumps(event) for event in [
            {"sequence": 0, "session_id": "s", "type": "tool_call", "call_id": "a", "tool": "read_file", "target": "/run/phase-loop-review/review-instructions.md"},
            {"sequence": 1, "session_id": "s", "type": "tool_result", "call_id": "a", "outcome": "success", "content": "read instructions\n"},
            {"sequence": 2, "session_id": "s", "type": "tool_call", "call_id": "b", "tool": "read_file", "target": "/run/phase-loop-review/review-bundle.md"},
            {"sequence": 3, "session_id": "s", "type": "tool_result", "call_id": "b", "outcome": "success", "content": "read bundle\n"},
            {"sequence": 4, "session_id": "s", "type": "terminal", "text": "AGREE"},
        ])

        def fake_liveness(cmd, **_kwargs):
            captured["cmd"] = list(cmd)
            return pi._LegRun(0, stream, "")

        monkeypatch.setattr(pi, "_leg_auth_ok", lambda *args, **kwargs: (True, ""))
        monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        rc, review, _log = pi._exec_leg(
            "gemini", review_dir, out_dir, artifact="artifact",
            agy_capture=capture, capture_staged=staged, seat_key="gemini-primary",
            agy_namespace=namespace,
        )
        command = captured["cmd"]
        assert rc == 0 and review == "AGREE"
        assert isinstance(command, list)
        assert command[0] == "/usr/bin/bwrap"
        add_dir = command.index("--add-dir")
        assert command[add_dir + 1] == "/run/phase-loop-review"
        prompt = command[-1]
        assert "/run/phase-loop-review" in prompt
        assert str(review_dir) not in prompt
        # The host path is present exactly once: bwrap's explicit source side.
        assert command.count(str(review_dir)) == 1
        bind = next(
            index for index, token in enumerate(command)
            if token == "--ro-bind" and command[index + 1] == str(review_dir)
        )
        assert command[bind + 1] == str(review_dir)
        assert command[bind + 2] == "/run/phase-loop-review"
    finally:
        capture.close()
        shutil.rmtree(root)
