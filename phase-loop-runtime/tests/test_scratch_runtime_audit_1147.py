"""The runtime audit hook is the completeness check for scratch decisions
(agent-harness#1147). Each spelling here escaped a static scan in some board round; each
is executed as RUNTIME code and must be caught by the hook, whatever API spawns it. A
decided launch must not be."""

from __future__ import annotations

import importlib.util
import os
import sys
import textwrap
from pathlib import Path

import pytest

import _scratch_audit_hook as hook
from phase_loop_runtime import sandbox_policy

_RUNTIME_MODULE = textwrap.dedent('''
    import functools, os, subprocess, sys
    from phase_loop_runtime import sandbox_policy
    from phase_loop_runtime.claude_agent_view import ClaudeAgentViewAdapter

    CLAUDE = None  # set by the test

    def partial_getattr():
        functools.partial(getattr(subprocess, "run"), [CLAUDE])()

    def attribute_alias(holder):
        holder.sp = subprocess
        holder.sp.run([CLAUDE])

    def dict_alias():
        table = {"sp": subprocess}
        table["sp"].run([CLAUDE])

    def execl_via_env():
        # os.execl would replace this process; it raises exactly this audit event first.
        sys.audit("os.exec", "/usr/bin/env", ["env", CLAUDE, "-p"], dict(os.environ))

    def posix_spawn():
        pid = os.posix_spawn(CLAUDE, [CLAUDE], dict(os.environ))
        os.waitpid(pid, 0)

    def shell_string():
        subprocess.run(f'sh -c "{CLAUDE} -p hi"', shell=True)

    def injected_runner():
        ClaudeAgentViewAdapter(claude_bin=CLAUDE, runner=subprocess.run).list_sessions()

    def forked_child():
        pid = os.fork()
        if pid == 0:
            try:
                subprocess.run([CLAUDE])
            finally:
                os._exit(0)
        os.waitpid(pid, 0)

    def decided():
        subprocess.run([CLAUDE], env=sandbox_policy.child_scratch_env(
            os.environ, sandbox_policy.CHILD_SCRATCH_RELOCATE))

    def with_env(env):
        subprocess.run([CLAUDE], env=env)

    def thread_direct():
        import threading
        thread = threading.Thread(target=subprocess.run, args=([CLAUDE],))
        thread.start()
        thread.join()
''')


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A module that counts as runtime code, and a fake ``claude`` on disk."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    claude.chmod(0o755)
    root = tmp_path / "rt"
    root.mkdir()
    (root / "fake_runtime_1147.py").write_text(_RUNTIME_MODULE, encoding="utf-8")
    monkeypatch.setattr(hook, "RUNTIME_ROOTS", [*hook.RUNTIME_ROOTS, str(root) + os.sep])
    spec = importlib.util.spec_from_file_location("fake_runtime_1147", root / "fake_runtime_1147.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.CLAUDE = str(claude)
    yield module
    hook.drain()


@pytest.mark.parametrize("spelling", [
    "partial_getattr", "attribute_alias", "dict_alias", "execl_via_env", "posix_spawn",
    "shell_string", "forked_child",
])
def test_an_undecided_agent_spawn_is_caught_however_it_is_spelled(runtime, spelling):
    hook.drain()
    function = getattr(runtime, spelling)
    function(type("Holder", (), {})()) if spelling == "attribute_alias" else function()
    found = hook.drain()
    assert found and "fake_runtime_1147.py" in found[0] and "claude" in found[0], found


def test_an_injected_runner_in_the_real_package_is_caught(runtime):
    """The round-3 shape, at runtime: the spawn frame is inside the real adapter."""
    hook.drain()
    runtime.injected_runner()
    found = hook.drain()
    assert found and "claude_agent_view.py" in found[0], found


def test_a_decided_spawn_passes(runtime):
    hook.drain()
    runtime.decided()
    assert hook.drain() == []


def test_a_spawn_from_test_code_is_not_judged(tmp_path):
    import subprocess

    hook.drain()
    subprocess.run(["/bin/sh", "-c", "true", "claude"])
    assert hook.drain() == []


@pytest.mark.parametrize("program, argv, expected", [
    (None, ["claude", "-p"], {"claude"}),
    (None, ["/usr/bin/env", "claude"], {"claude"}),
    (None, ["bash", "-lc", "cd /r && codex exec"], {"codex"}),
    (None, ["git", "commit", "-m", "mention claude in a message"], set()),
    ("/opt/x/agy", ["agy"], {"agy"}),
    (None, "npx @anthropic-ai/claude-code -p", {"claude-code"}),
])
def test_agent_detection(program, argv, expected):
    assert hook.agent_words(program, argv) == expected


def test_the_marker_names_the_decision():
    for decision in sandbox_policy.CHILD_SCRATCH_DECISIONS:
        env = sandbox_policy.child_scratch_env({}, decision)
        assert env[sandbox_policy.CHILD_SCRATCH_MARKER].partition(":")[0] == decision
        assert sandbox_policy.scratch_stamp_valid(env) == decision


@pytest.mark.parametrize("site", [
    "executor", "availability_probe", "auth_preflight", "leg_auth", "claude_version",
    "claude_auth", "claude_stop", "claude_timeout_cleanup",
])
def test_each_runtime_launch_of_a_named_agent_carries_the_marker(tmp_path, monkeypatch, site):
    """Every launch site that starts a NAMED agent CLI outside the provider interface is
    observed carrying the decision: the executor, AUTOSEL's availability probe, the launch
    auth preflight, the leg and Claude auth / version probes, and the Claude stop and
    timeout-cleanup calls."""
    import subprocess

    from phase_loop_runtime import executor_availability, launcher, panel_invoker
    from phase_loop_runtime.claude_agent_view import ClaudeAgentViewAdapter

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "seen.txt"
    for name in ("claude", "codex"):
        cli = bin_dir / name
        cli.write_text(
            f'#!/bin/sh\nprintf "%s" "${{{sandbox_policy.CHILD_SCRATCH_MARKER}-unset}}" > {seen}\n',
            encoding="utf-8")
        cli.chmod(0o755)
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    monkeypatch.setenv("PATH", path)
    env = {"PATH": path}
    adapter = ClaudeAgentViewAdapter(claude_bin=str(bin_dir / "claude"))
    if site == "executor":
        launcher.launch([str(bin_dir / "claude")], env=env)
    elif site == "availability_probe":
        executor_availability._run_probe("claude --version")
    elif site == "auth_preflight":
        spec = type("Spec", (), {"auth_preflight_mode": "metadata_only", "executor": "claude",
                                 "auth_preflight_probes": ("claude --version",)})()
        launcher.run_auth_preflight(spec)
    elif site == "leg_auth":
        panel_invoker._leg_auth_ok("codex", env)
    elif site == "claude_version":
        panel_invoker._claude_code_support_status(str(bin_dir / "claude"))
    elif site == "claude_auth":
        panel_invoker._claude_subscription_auth_ok(env)
    elif site == "claude_stop":
        panel_invoker._stop_claude_agent(adapter, "agent-1", str(tmp_path), env)
    else:
        panel_invoker._cleanup_claude_launch_timeout(
            adapter, cwd=str(tmp_path), env=env,
            exc=subprocess.TimeoutExpired(["claude"], 1, output=b"", stderr=b""))
    assert seen.read_text(encoding="utf-8").partition(":")[0] == sandbox_policy.CHILD_SCRATCH_RELOCATE



# -- round 6: the stamp must PROVE a decision made for this env -------------------------


def _decided_env(decision=sandbox_policy.CHILD_SCRATCH_RELOCATE):
    return sandbox_policy.child_scratch_env({"PATH": os.environ["PATH"]}, decision)


@pytest.mark.parametrize("case", [
    "empty", "inherited_from_os_environ", "copied_exception", "values_changed_after",
    "forged", "minted_in_another_process",
])
def test_a_stamp_that_does_not_prove_a_decision_for_this_env_is_caught(runtime, monkeypatch, case):
    import subprocess

    env = _decided_env()
    marker = sandbox_policy.CHILD_SCRATCH_MARKER
    if case == "empty":
        env[marker] = ""
    elif case == "inherited_from_os_environ":
        monkeypatch.setenv(marker, env[marker])  # a valid stamp, but the process's own
    elif case == "copied_exception":
        env = _decided_env(sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP)  # valid, wrong site
    elif case == "values_changed_after":
        env["TMPDIR"] = "/somewhere/else"
    elif case == "forged":
        env[marker] = "relocate:" + "0" * 16 + ":" + "0" * 64
    else:
        src = str(Path(sandbox_policy.__file__).resolve().parents[1])
        minted = subprocess.run(
            [sys.executable, "-c",
             "import json,sys; from phase_loop_runtime import sandbox_policy as p; "
             "print(json.dumps(p.child_scratch_env({'PATH': sys.argv[1]}, p.CHILD_SCRATCH_RELOCATE)))",
             env["PATH"]],
            capture_output=True, text=True, check=True, env={**os.environ, "PYTHONPATH": src})
        env = __import__("json").loads(minted.stdout)
    hook.drain()
    if case == "inherited_from_os_environ":
        runtime.partial_getattr()  # inherits os.environ
        found = hook.drain()
        assert found and "no env was decided" in found[0], found
        hook.drain()
        runtime.with_env(dict(os.environ))  # an explicit copy of it: the stamp is the process's
        found = hook.drain()
        assert found and "inherited" in found[0], found
        return
    runtime.with_env(env)
    found = hook.drain()
    assert found, f"{case}: a stamp that proves nothing was accepted"


def test_a_fresh_relocate_decision_passes_and_a_reused_stamp_is_never_trusted(runtime):
    exception = _decided_env(sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP)
    decided = sandbox_policy.child_scratch_env(exception, sandbox_policy.CHILD_SCRATCH_RELOCATE)
    assert sandbox_policy.scratch_stamp_valid(decided) == sandbox_policy.CHILD_SCRATCH_RELOCATE
    assert decided[sandbox_policy.CHILD_SCRATCH_MARKER] != exception[sandbox_policy.CHILD_SCRATCH_MARKER]
    hook.drain()
    runtime.with_env(decided)
    assert hook.drain() == []


def test_an_exception_applied_at_the_launch_interface_passes(runtime, tmp_path):
    from phase_loop_runtime import panel_invoker

    hook.drain()
    panel_invoker.run_provider([runtime.CLAUDE], env={"PATH": os.environ["PATH"]},
                               child_scratch=sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP)
    assert hook.drain() == []


def test_an_unattributable_spawn_is_judged(runtime):
    hook.drain()
    runtime.thread_direct()
    found = hook.drain()
    assert found and "unattributed" in found[0], found


def test_the_hook_proves_it_is_live():
    assert hook._installed and hook._probe_seen


# -- round 6: agent-CLI names come from the runtime's registries ------------------------


def test_every_registered_harness_binary_is_watched():
    from phase_loop_runtime import panel_invoker
    from phase_loop_runtime.advisor_board import registries
    from phase_loop_runtime.capability_registry import capability_registry

    expected = {spec.cli for spec in registries._HARNESS_SPECS}
    expected |= set(panel_invoker._LEG_CLI.values())
    expected |= {p.split()[0] for r in capability_registry().values()
                 for p in (r.auth_preflight_probes or ()) if p.split()}
    assert expected <= hook.AGENT_CLIS, expected - hook.AGENT_CLIS
    assert {"pi", "pi-agent-watch", "cursor-agent", "opencode"} <= hook.AGENT_CLIS


def test_a_new_harness_in_the_registry_is_covered_without_editing_the_hook(monkeypatch):
    from phase_loop_runtime.advisor_board import registries

    spec = registries._HARNESS_SPECS[0]
    monkeypatch.setattr(registries, "_HARNESS_SPECS", (
        *registries._HARNESS_SPECS, type(spec)(name="newharness", cli="new-agent-cli",
                                               auth_lanes=spec.auth_lanes, backing=spec.backing)))
    assert "new-agent-cli" in hook.runtime_agent_binaries()


@pytest.mark.parametrize("binary", ["pi", "pi-agent-watch"])
def test_an_undecided_pi_launch_is_caught(runtime, tmp_path, binary):
    cli = tmp_path / binary
    cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    cli.chmod(0o755)
    runtime.CLAUDE = str(cli)
    hook.drain()
    runtime.partial_getattr()
    found = hook.drain()
    assert found and binary in found[0], found
