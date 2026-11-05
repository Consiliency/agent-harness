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

import os
import subprocess
import pytest
from pathlib import Path

from phase_loop_runtime import panel_invoker as pi
from phase_loop_runtime import review_stage


def test_seats_firstseat_tool_surface_image(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    binary_dir, native_dir = tmp_path / "bin", tmp_path / "native"
    binary_dir.mkdir()
    native_dir.mkdir()
    image = native_dir / "grok"
    image.write_bytes(b"\x7fELFfixture-one")
    image.chmod(0o700)
    wrapper = binary_dir / "grok"
    wrapper.write_text(f'#!/bin/sh\nexec {image} "$@"\n')
    wrapper.chmod(0o700)
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(binary_dir))
    command = ["grok", "-p", "fixture", "--tools", "fixture_read"]
    assert pi._grok_binary_identity(command)[0] == str(image)
    pi.record_tool_probe(command, {"tools": ["fixture_read"], "diagnostics": []},
                         allowed_tools={"fixture_read"}, version="fixture-v1")
    assert pi.grok_tool_gate(command, {"PATH": "/other"})
    image.write_bytes(b"\x7fELFfixture-two")
    assert not pi.grok_tool_gate(command)


def test_seats_firstseat_tool_surface_dependency_image(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from phase_loop_runtime import executable_dependency_startup as startup
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    image = tmp_path / "grok"
    image.write_bytes(b"fixture-image")
    dependency = SimpleNamespace(subject_source=image)
    monkeypatch.setattr(startup, "current_dependency_for_provider", lambda **kw: dependency)
    command = ["grok", "-p", "fixture", "--tools", "fixture_read"]
    def runner(argv, **kw):
        assert argv[0] == str(image)
        output = ("--list-tools Print tool definitions without running a model" if argv[-1] == "--help"
                  else "fixture-v1" if argv[-1] == "--version"
                  else '{"tools":["fixture_read"],"diagnostics":[]}')
        return subprocess.CompletedProcess(argv, 0, output, "")
    assert pi.probe_grok_tools(command, allowed_tools={"fixture_read"}, runner=runner)["passed"]
    assert pi.grok_tool_gate(command)


@pytest.mark.parametrize("value", [[], 1, None, {"tools": ["fixture_extra"]}])
def test_seats_firstseat_tool_surface_receipt_fields(tmp_path, monkeypatch, value):
    import json
    from phase_loop_runtime import president_adapter as pa
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    command = ["grok", "-p", "fixture", "--tools", "fixture_read"]
    receipt = pi.record_tool_probe(command, {"tools": ["fixture_read"], "diagnostics": []},
                                  allowed_tools={"fixture_read"}, version="fixture-v1")
    assert pi.grok_tool_gate(command)
    path = pa.private_record_root() / ("grok-probe-" + "1" * 64 + "-" + pi._grok_argv_digest(command) + ".json")
    path.write_text(json.dumps({**receipt, **value} if isinstance(value, dict) else value))
    assert not pi.grok_tool_gate(command)


@pytest.mark.parametrize("role", list(pi.SeatLaunchRole))
def test_seats_firstseat_tool_surface_launch_roles(tmp_path, monkeypatch, role):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    with pytest.raises(pi._seat_jail.SeatSandboxRefused) as refusal:
        pi.launch_owned(["grok", "--prompt", "fixture"], role=role, profile=pi.SeatProfile(env={}))
    assert refusal.value.code == "grok_tool_surface_unverified"


@pytest.mark.parametrize("definitions", [None, {}, {"tools": []},
    {"tools": ["fixture_extra"]}, {"tools": ["fixture_read"], "diagnostics": ["fixture"]},
    {"tools": ["fixture_read"], "diagnostics": []}])
def test_seats_firstseat_tool_surface_gate(tmp_path, monkeypatch, definitions):
    command = ["grok", "-p", "fixture", "--tools", "fixture_read"]
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    receipt = pi.record_tool_probe(command, definitions, allowed_tools={"fixture_read"}, version="fixture-v1")
    passed = definitions == {"tools": ["fixture_read"], "diagnostics": []}
    assert pi.grok_tool_gate(command) is passed
    assert ("tools" in receipt) is passed
    assert receipt["public_code"] == (None if passed else "grok_tool_surface_unverified")
    if passed:
        assert not pi.grok_tool_gate([*command, "--no-memory"])
        monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "2" * 64))
        assert not pi.grok_tool_gate(command)


@pytest.mark.parametrize("brokered", [False, True])
def test_seats_firstseat_tool_surface_unprobed_route(tmp_path, monkeypatch, brokered):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a: (True, ""))
    monkeypatch.setattr(pi, "_run_leg_with_liveness", lambda *a, **k: pytest.fail("provider launched"))
    out = tmp_path / "out"
    out.mkdir()
    result = pi._exec_leg("grok", tmp_path, out, artifact="fixture",
                          **({"broker_prompt": "fixture", "broker_evidence": {}} if brokered else {}))
    assert result == (1, "", "grok_tool_surface_unverified")


def test_seats_firstseat_tool_surface_reprobe(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    command = ["grok", "--tools", "fixture_read"]
    pi.record_tool_probe(command, {"tools": ["fixture_read"], "diagnostics": []},
                         allowed_tools={"fixture_read"}, version="fixture-v1")
    assert pi.grok_tool_gate(command)
    pi.record_tool_probe(command, None, allowed_tools={"fixture_read"})
    assert not pi.grok_tool_gate(command)


def test_seats_firstseat_tool_surface_workflow_route(tmp_path, monkeypatch):
    from phase_loop_runtime import seat_jail
    monkeypatch.setattr(pi, "_seat_provider_source", lambda *a: ("grok", "/fixture/grok"))
    calls = []
    def gate(command, env):
        calls.append(command)
        return False
    monkeypatch.setattr(pi, "grok_tool_gate", gate)
    command = ["grok", "-p", "fixture workflow", "--tools", "fixture_read"]
    with pytest.raises(seat_jail.SeatSandboxRefused) as refusal:
        with pi._seat_command_profile(command, env={}, cwd=tmp_path):
            pytest.fail("profile admitted")
    assert refusal.value.code == "grok_tool_surface_unverified"
    assert calls == [command]


@pytest.mark.parametrize("failure", ["timeout", "empty", "malformed", "diagnostic", "version_diagnostic"])
def test_seats_firstseat_tool_surface_probe(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    calls = []
    def runner(argv, **options):
        assert not list(Path(options["cwd"]).iterdir())
        calls.append(argv)
        if argv[-1] == "--help":
            return subprocess.CompletedProcess(argv, 0,
                "--list-tools Print tool definitions without running a model", "")
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "fixture-v1",
                "fixture" if failure == "version_diagnostic" else "")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 30)
        return subprocess.CompletedProcess(argv, 0,
            "" if failure == "empty" else "{" if failure == "malformed" else
            '{"tools":["fixture_read"],"diagnostics":[]}',
            "fixture" if failure == "diagnostic" else "")
    result = pi.probe_grok_tools(["grok", "--tools", "fixture_read"],
                                allowed_tools={"fixture_read"}, runner=runner)
    assert not result["passed"]
    assert result["public_code"] == "grok_tool_surface_unverified"
    assert "tools" not in result
    assert len(calls) == 3


@pytest.mark.parametrize("brokered", [False, True])
def test_seats_firstseat_tool_surface_passing_route(tmp_path, monkeypatch, brokered):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a: (True, ""))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    gate = pi.grok_tool_gate
    entered = []
    def measured(command, env=None):
        entered.append(command)
        allowed = pi._grok_allowed_tools(command)
        pi.record_tool_probe(command, {"tools": sorted(allowed), "diagnostics": []},
                             allowed_tools=allowed, version="fixture-v1")
        return gate(command, env)
    monkeypatch.setattr(pi, "grok_tool_gate", measured)
    launched = []
    def run(command, **kw):
        launched.append(command)
        return pi._LegRun(0, "AGREE", "")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    out = tmp_path / "out"
    out.mkdir()
    result = pi._exec_leg("grok", tmp_path, out, artifact="fixture",
        **({"broker_prompt": "fixture", "broker_evidence": {}} if brokered else {}))
    assert result[:2] == (0, "AGREE")
    assert launched == entered and len(launched) == 1


# Built-ins that act rather than read. Under a mode that asks first, a headless run cancels them.
_ACTING_TOOLS = {"run_terminal_command", "run_terminal_cmd", "write", "search_replace"}


@pytest.mark.parametrize("passing", [False, True])
def test_seats_firstseat_tool_surface_president(tmp_path, monkeypatch, passing):
    from phase_loop_runtime import president_adapter as pa
    from phase_loop_runtime.advisor_board.fixtures import DEFAULT_BOARD
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_parent_auth_state", lambda *a: "healthy")
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a: (True, ""))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    entered, launched = [], []
    gate = pi.grok_tool_gate
    def measured(command, env=None):
        entered.append(command)
        if passing:
            allowed = pi._grok_allowed_tools(command)
            pi.record_tool_probe(command, {"tools": sorted(allowed), "diagnostics": []},
                                 allowed_tools=allowed, version="fixture-v1")
        return gate(command, env)
    monkeypatch.setattr(pi, "grok_tool_gate", measured)
    def run(command, **kw):
        launched.append(command)
        return pi._LegRun(0, "FORCING DECISION: LAND", "")
    monkeypatch.setattr(pi, "_run_leg_with_liveness", run)
    seam = pa.PresidentInvoke(DEFAULT_BOARD, base_env={})
    result = seam._transport("grok", pi.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["grok"],
                             "fixture", tmp_path, tmp_path)
    assert entered
    assert bool(launched) is passing
    assert result[0] == (0 if passing else 1)
    if not passing:
        assert result[2] == "grok_tool_surface_unverified"


def test_seats_firstseat_tool_surface_probe_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    def runner(argv, **options):
        if argv[-1] == "--help":
            return subprocess.CompletedProcess(argv, 0, "--list-tools Print tool definitions without running a model", "")
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "fixture-v1", "")
        assert "--tools" in argv and argv[argv.index("--tools") + 1] == "fixture_read"
        assert "private-prompt" not in argv
        return subprocess.CompletedProcess(argv, 0, '{"tools":["fixture_read"],"diagnostics":[]}', "")
    command = ["grok", "-p", "private-prompt", "--tools", "fixture_read"]
    result = pi.probe_grok_tools(command, allowed_tools={"fixture_read"}, runner=runner)
    assert result["passed"] and pi.grok_tool_gate(command)
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


def _fixture_tool_probe(monkeypatch, root):
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "state"))
    monkeypatch.setattr(pi, "_grok_binary_identity", lambda *a: ("/fixture/grok", "1" * 64))
    gate = pi.grok_tool_gate
    def measured(command, env=None):
        allowed = pi._grok_allowed_tools(command)
        pi.record_tool_probe(command, {"tools": sorted(allowed), "diagnostics": []},
                             allowed_tools=allowed, version="fixture-v1")
        return gate(command, env)
    monkeypatch.setattr(pi, "grok_tool_gate", measured)


def _launched_grok_argv(monkeypatch, review_dir: Path, out_dir: Path) -> list[str]:
    """The argv the product hands the launch boundary for the brokered grok leg."""
    seen: list[list[str]] = []

    def fake_liveness(cmd, **_kwargs):
        seen.append(list(cmd))
        return pi._LegRun(0, "AGREE", "")

    monkeypatch.setattr(pi, "_run_leg_with_liveness", fake_liveness)
    monkeypatch.setattr(pi, "_leg_auth_ok", lambda *a, **k: (True, ""))
    _fixture_tool_probe(monkeypatch, out_dir.parent)
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
    _fixture_tool_probe(monkeypatch, tmp_path)
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


def _fixture_grok(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "launched"
    binary = bin_dir / "grok"
    binary.write_text(f"#!/bin/sh\necho launched >> {marker}\n")
    binary.chmod(0o755)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(pi, "_PROVIDER_SEARCH_PATH", str(bin_dir))
    return binary, marker


@pytest.mark.parametrize("action", ["execute", "plan", "repair"])
def test_seats_firstseat_tool_surface_supervised_workflow(tmp_path, monkeypatch, action):
    import fcntl
    from phase_loop_runtime import launcher, seat_jail

    class Lease:
        generation = identity = "fixture"
        def __init__(self, fd): self.fd = fd
        def fileno(self): return self.fd

    binary, marker = _fixture_grok(tmp_path, monkeypatch)
    selection = launcher.ModelSelection(model="grok-4.7", effort="high", profile="execute")
    command = launcher.build_grok_command(tmp_path, selection, action=action, context_file="bundle")
    fd = os.open(tmp_path / "lease.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(seat_jail.SeatSandboxRefused) as refusal:
            launcher.launch(command, action=action, cwd=str(tmp_path), env=dict(os.environ),
                            log_path=tmp_path / "log", lease_authority=Lease(fd))
        assert refusal.value.code == "grok_tool_surface_unverified"
        assert not marker.exists()
        offered = {"tools": ["read_file", "write", "run_terminal_command"], "diagnostics": []}
        assert pi.record_tool_probe(command, offered, allowed_tools=set(), version="fixture-v1")["passed"]
        result = launcher.launch(command, action=action, cwd=str(tmp_path), env=dict(os.environ),
                                 log_path=tmp_path / "log", lease_authority=Lease(fd))
        assert result.returncode == 0 and marker.read_text() == "launched\n"
        assert Path(result.command[0]) == binary.resolve()
    finally:
        os.close(fd)


def test_seats_firstseat_tool_surface_workflow_deny_list(tmp_path, monkeypatch):
    from phase_loop_runtime import launcher
    _fixture_grok(tmp_path, monkeypatch)
    selection = launcher.ModelSelection(model="grok-4.7", effort="high", profile="execute")
    command = launcher.build_grok_command(tmp_path, selection, action="execute", context_file="bundle")
    denied = command[command.index("--disallowed-tools") + 1].split(",")[0]
    assert not pi.record_tool_probe(command, {"tools": ["write", denied], "diagnostics": []},
                                    allowed_tools=set(), version="fixture-v1")["passed"]
    assert not pi.grok_tool_gate(command)
    assert not pi.record_tool_probe(command, {"tools": [], "diagnostics": []},
                                    allowed_tools=set(), version="fixture-v1")["passed"]
    assert pi.record_tool_probe(command, {"tools": ["write"], "diagnostics": []},
                                allowed_tools=set(), version="fixture-v1")["passed"]
    assert pi.grok_tool_gate(command)
