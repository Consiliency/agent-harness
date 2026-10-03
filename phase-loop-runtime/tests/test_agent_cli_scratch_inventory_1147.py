"""Every process launch in the runtime has a stated scratch decision (agent-harness#1147).

Two board rounds found agent-CLI launches that skipped the scratch relocation, one site
at a time. This file closes the class in two parts:

* ONE choke point for review providers. ``panel_invoker.launch_provider`` /
  ``run_provider`` apply :func:`sandbox_policy.child_scratch_env` to every ``env`` they
  launch with, and only the two named exceptions can opt out. The tests below OBSERVE a
  real child's environment through that interface.
* An INVENTORY derived from the code. Every subprocess / exec / spawn call in the package
  is enumerated from the AST. A call whose program is a literal that is not an agent CLI
  (``git``, ``bwrap``, ``sys.executable`` ...) needs nothing. Every other call -- an agent
  CLI by name, or a program the AST cannot see -- must be listed in ``INVENTORY`` with its
  decision. A new launch site therefore fails here until someone states whether it starts
  an agent CLI and, if so, how its scratch is decided. A listed site that disappears fails
  too, so the table cannot drift.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker, sandbox_policy

PACKAGE = Path(sandbox_policy.__file__).resolve().parent

#: Process-launch functions, by module.
LAUNCHERS = {
    "subprocess": {"Popen", "run", "call", "check_call", "check_output", "getoutput",
                   "getstatusoutput"},
    "os": {"execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
           "posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnvp", "spawnvpe",
           "spawnl", "spawnle", "spawnlp", "spawnlpe", "system", "popen"},
    "pty": {"spawn"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}

#: Program names that are agent CLIs.
AGENT_CLIS = frozenset({"claude", "codex", "agy", "gemini", "grok", "opencode", "cursor-agent"})

RELOCATED = "relocated"          # the env passes child_scratch_env / fill_child_tmp_env
PROVIDER_INTERFACE = "provider"  # the choke point itself
EXCEPTION = "named-exception"    # agent-harness#1179 / agent-harness#1181
NOT_AGENT = "not-agent-cli"

#: (module, enclosing function) -> (decision, evidence). For RELOCATED the evidence is
#: ``"<module>:<function>:<token>"``: the token, a call into the scratch decision, must
#: appear in that function's source.
INVENTORY: dict[tuple[str, str], tuple[str, str]] = {
    # -- the choke point -------------------------------------------------------------
    ("panel_invoker.py", "launch_provider"): (
        PROVIDER_INTERFACE, "panel_invoker.py:_child_scratch_kwargs:child_scratch_env"),
    ("panel_invoker.py", "run_provider"): (
        PROVIDER_INTERFACE, "panel_invoker.py:_child_scratch_kwargs:child_scratch_env"),
    # -- agent CLIs launched outside the provider interface ------------------------------
    ("convergence/adapters/base.py", "run_bounded"): (
        RELOCATED, "convergence/adapters/base.py:_child_environment:child_scratch_env"),
    ("launcher.py", "launch"): (
        RELOCATED, "harness_env_signatures.py:child_executor_env:fill_child_tmp_env"),
    ("lease_supervisor.py", "_exec_executor"): (
        RELOCATED, "launcher.py:launch:child_executor_env"),
    # The Claude agent-view list/logs/stop calls run with the TUI seat's env, built by
    # _broker_leg_env or _subscription_env.
    ("panel_invoker.py", "_exec_claude_agent_view_attempt"): (
        RELOCATED, "panel_invoker.py:_exec_claude_tui_leg:_subscription_env"),
    ("panel_invoker.py", "_stop_claude_agent"): (
        RELOCATED, "panel_invoker.py:_exec_claude_tui_leg:_broker_leg_env"),
    ("panel_invoker.py", "_cleanup_claude_launch_timeout"): (
        RELOCATED, "panel_invoker.py:_exec_claude_tui_leg:_broker_leg_env"),
    # -- the named exceptions --------------------------------------------------------
    ("agy_canary_evidence.py", "ProviderLaunchAuthority.preflight"): (
        EXCEPTION, "agy capture/qualification jail, frozen env (agent-harness#1179)"),
    ("agy_canary_evidence.py", "namespace_self_test"): (
        EXCEPTION, "agy capture/qualification jail, frozen env (agent-harness#1179)"),
    ("agy_canary_evidence.py", "probe_capability"): (
        EXCEPTION, "agy capture/qualification jail, frozen env (agent-harness#1179)"),
    ("agy_canary_evidence.py", "_launch_tree_snapshot_child"): (
        EXCEPTION, "agy capture/qualification jail, frozen env (agent-harness#1179)"),
    ("agy_canary_evidence.py", "_bootstrap_attest_opened"): (
        EXCEPTION, "agy capture/qualification jail, frozen env (agent-harness#1179)"),
    # -- short probes of an agent CLI: auth or version, no session scratch ---------------
    ("panel_invoker.py", "_leg_auth_ok"): (NOT_AGENT, "auth-status probe, no session"),
    ("panel_invoker.py", "_claude_subscription_auth_ok"): (
        NOT_AGENT, "`claude auth status` probe, no session"),
    ("panel_invoker.py", "_claude_code_support_status"): (
        NOT_AGENT, "`claude --version` probe, no session"),
    ("launcher.py", "run_auth_preflight"): (NOT_AGENT, "operator auth-preflight probes"),
    ("executor_availability.py", "_run_probe"): (NOT_AGENT, "executor availability probe"),
    # -- programs that are not agent CLIs (the AST cannot see the program) --------------
    ("panel_invoker.py", "_require_seat_identity"): (NOT_AGENT, "/bin/sh namespace probe"),
    ("advisor_board/backing.py", "ParentUnixBroker.run_credentialless_client"): (
        NOT_AGENT, "fixed python probe in the HARDEN broker jail"),
    ("agy_canary_evidence.py", "_uv_tool_dir"): (NOT_AGENT, "uv"),
    ("agy_canary_evidence.py", "_git_run"): (NOT_AGENT, "git"),
    ("agy_canary_evidence.py", "_github_run"): (NOT_AGENT, "gh"),
    ("conformance/outside_agent_conform_evidence.py", "_validate_chronology._run_git"): (
        NOT_AGENT, "git"),
    ("conformance/outside_agent_conform_evidence.py", "_validate_chronology"): (
        NOT_AGENT, "git"),
    ("conformance/outside_agent_conform_evidence.py", "_validate_chronology._git_blob_bytes"): (
        NOT_AGENT, "git"),
    ("generated_outputs.py", "_run_bounded"): (
        NOT_AGENT, "the repository's declared build-output producers (closeout audit)"),
    ("observability.py", "run_notification_command"): (
        NOT_AGENT, "the operator's notification hook"),
    ("repo_validation.py", "run_plan"): (NOT_AGENT, "the repository's validation commands"),
    ("review_stage.py", "_falsifier_interpreter_scope"): (NOT_AGENT, "python interpreter probe"),
    ("review_stage.py", "_run_bounded_falsifier_node"): (NOT_AGENT, "bwrap + pytest falsifier"),
    ("runner.py", "_run_legible_operational_attestation"): (NOT_AGENT, "python -m pytest"),
    ("sandbox_egress.py", "isolated_network"): (NOT_AGENT, "unshare / slirp4netns / nsenter"),
    ("tdd_receipts.py", "record_content_tdd_receipt"): (NOT_AGENT, "pytest / git"),
    ("train_runner.py", "_live_merge_pr"): (NOT_AGENT, "gh"),
    ("verification_evidence.py", "_interpreter_minor_version"): (NOT_AGENT, "python"),
    ("verification_evidence.py", "_interpreter_full_version"): (NOT_AGENT, "python"),
    ("verification_evidence.py",
     "execute_proofgate_mutation_manifest._execute_one._execute_worktree"): (
        NOT_AGENT, "pytest in a mutation worktree"),
    ("verification_evidence.py", "detect_changed_dependency_manifests"): (NOT_AGENT, "git"),
    ("verification_evidence.py", "_run_process"): (NOT_AGENT, "verification commands"),
}


#: The provider launch interface and its liveness wrapper. A call that passes no ``env``
#: inherits this process's own environment and so takes no scratch decision; each such
#: call must be listed here with the reason it is not an agent-CLI launch.
PROVIDER_ENTRY_POINTS = frozenset({"launch_provider", "run_provider", "_run_leg_with_liveness"})
PROVIDER_CALLS_WITHOUT_ENV: dict[tuple[str, str], str] = {
    ("agy_qualification.py", "inspect_network"): "iptables inspection, not an agent CLI",
    ("agy_qualification.py", "run_operation"): (
        "the qualification worker (python); its agy runs in the frozen jail (agent-harness#1179)"),
    ("sandbox_egress.py", "isolated_network"): "unshare / slirp4netns namespace holder",
}


def _provider_calls_without_env(package: Path) -> set[tuple[str, str]]:
    found = set()
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package).as_posix()
        stack: list[str] = []

        class _Walker(ast.NodeVisitor):
            def _scope(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

            def visit_Call(self, node):
                func = node.func
                name = (func.id if isinstance(func, ast.Name)
                        else func.attr if isinstance(func, ast.Attribute) else None)
                if name in PROVIDER_ENTRY_POINTS and not any(
                        k.arg == "env" for k in node.keywords):
                    found.add((rel, ".".join(stack) or "<module>"))
                self.generic_visit(node)

        _Walker().visit(ast.parse(path.read_text(encoding="utf-8")))
    return found


def _module_aliases(tree: ast.AST) -> tuple[dict[str, str], list[str]]:
    """``import subprocess as sp`` -> {"sp": "subprocess"}; and every ``from <launcher
    module> import <launch fn>``, which would hide a call from the attribute walk."""
    aliases = {name: name for name in LAUNCHERS}
    hidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in LAUNCHERS:
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in LAUNCHERS:
            hidden += [a.name for a in node.names if a.name in LAUNCHERS[node.module]]
    return aliases, hidden


def _launch_sites() -> tuple[dict[tuple[str, str], list[object]], list[str]]:
    """(module, enclosing function) -> the literal program of each launch call there
    (``None`` when the AST cannot see it); and the hidden-import violations."""
    sites: dict[tuple[str, str], list[object]] = {}
    hidden_imports: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases, hidden = _module_aliases(tree)
        hidden_imports += [f"{rel}: from-import of {name}" for name in hidden]
        stack: list[str] = []

        class _Walker(ast.NodeVisitor):
            def _scope(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

            def visit_Call(self, node):
                func = node.func
                if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                        and func.attr in LAUNCHERS.get(aliases.get(func.value.id, ""), ())):
                    first = node.args[0] if node.args else None
                    program = None
                    if (isinstance(first, (ast.List, ast.Tuple)) and first.elts
                            and isinstance(first.elts[0], ast.Constant)):
                        program = first.elts[0].value
                    elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                        program = first.value.split()[0] if first.value.split() else None
                    sites.setdefault((rel, ".".join(stack) or "<module>"), []).append(program)
                self.generic_visit(node)

        _Walker().visit(tree)
    return sites, hidden_imports


def _needs_a_decision(programs: list[object]) -> bool:
    return any(p is None or os.path.basename(str(p)) in AGENT_CLIS for p in programs)


def _function_source(module: str, qualname: str) -> str:
    tree = ast.parse((PACKAGE / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == qualname:
            return ast.get_source_segment((PACKAGE / module).read_text(encoding="utf-8"), node)
    raise AssertionError(f"{module}:{qualname} not found")


def test_no_launch_function_is_imported_by_name():
    _, hidden = _launch_sites()
    assert not hidden, f"import the module and call it by attribute instead: {hidden}"


def test_every_launch_that_may_start_an_agent_cli_has_a_stated_decision():
    sites, _ = _launch_sites()
    undecided = sorted(key for key, programs in sites.items()
                       if _needs_a_decision(programs) and key not in INVENTORY)
    assert not undecided, (
        "launch sites with no scratch decision -- add each to INVENTORY: relocated through "
        f"sandbox_policy.child_scratch_env, a named exception, or not an agent CLI: {undecided}")


def test_the_inventory_has_no_stale_entries():
    sites, _ = _launch_sites()
    stale = sorted(key for key in INVENTORY if key not in sites)
    assert not stale, f"INVENTORY lists launch sites that no longer exist: {stale}"


def test_every_provider_launch_without_an_env_is_accounted_for():
    """The choke point decides on the ``env`` it is given; a provider call that passes none
    would bypass it, so each one must be listed with its reason."""
    found = _provider_calls_without_env(PACKAGE)
    assert found == set(PROVIDER_CALLS_WITHOUT_ENV), (
        f"unlisted: {sorted(found - set(PROVIDER_CALLS_WITHOUT_ENV))}; "
        f"stale: {sorted(set(PROVIDER_CALLS_WITHOUT_ENV) - found)}")


def test_the_scanner_sees_a_provider_call_without_an_env(tmp_path):
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "m.py").write_text(
        "def a(p):\n    p.launch_provider(['agy'], cwd='.')\n"
        "def b(p, e):\n    p._run_leg_with_liveness(['agy'], cwd='.', env=e, deadline_s=1)\n"
        "def c():\n    run_provider(['agy'], **{})\n",
        encoding="utf-8")
    assert _provider_calls_without_env(fake) == {("m.py", "a"), ("m.py", "c")}


@pytest.mark.parametrize("key", sorted(k for k, v in INVENTORY.items()
                                       if v[0] in (RELOCATED, PROVIDER_INTERFACE)))
def test_each_relocated_site_names_its_decision(key):
    module, function, token = INVENTORY[key][1].split(":")
    assert token in _function_source(module, function.split(".")[-1]), INVENTORY[key]


def test_the_scanner_sees_a_hidden_launch(tmp_path, monkeypatch):
    """The inventory is only as good as its scanner: a launch of an unseen program, and an
    aliased module, must both be found."""
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "m.py").write_text(
        "import subprocess as sp\n"
        "def go(argv):\n    sp.Popen(argv)\n"
        "def named():\n    sp.run(['claude', '-p'])\n"
        "def plain():\n    sp.run(['git', 'status'])\n",
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE", fake)
    sites, _ = _launch_sites()
    assert {k for k, v in sites.items() if _needs_a_decision(v)} == {("m.py", "go"), ("m.py", "named")}


# -- the choke point, observed -----------------------------------------------------------


def _ram_tmp(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", raising=False)
    monkeypatch.setattr(sandbox_policy, "_mount_fstype",
                        lambda p: "tmpfs" if os.path.realpath(p) == "/tmp" else "ext4")
    return cache / "phase-loop" / "tmp"


def _observe(tmp_path, launch, **kwargs) -> list[str]:
    seen = tmp_path / "seen.txt"
    script = ["/bin/sh", "-c",
              'printf "%s\\n%s\\n" "${TMPDIR-unset}" "${CLAUDE_CODE_TMPDIR-unset}" > "$1"',
              "sh", str(seen)]
    result = launch(script, env={"PATH": "/usr/bin:/bin"}, **kwargs)
    if hasattr(result, "wait"):
        result.wait(timeout=30)
    return seen.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(not os.path.exists("/bin/sh"), reason="needs /bin/sh")
@pytest.mark.parametrize("launch", [panel_invoker.launch_provider, panel_invoker.run_provider])
def test_the_provider_interface_relocates_every_env_it_launches(tmp_path, monkeypatch, launch):
    scratch = _ram_tmp(monkeypatch, tmp_path)
    assert _observe(tmp_path, launch) == [str(scratch)] * 2


@pytest.mark.skipif(not os.path.exists("/bin/sh"), reason="needs /bin/sh")
@pytest.mark.parametrize("decision", [sandbox_policy.CHILD_SCRATCH_PRIVATE_TMP,
                                      sandbox_policy.CHILD_SCRATCH_FROZEN_CAPTURE])
def test_only_a_named_exception_keeps_the_env_as_built(tmp_path, monkeypatch, decision):
    _ram_tmp(monkeypatch, tmp_path)
    assert _observe(tmp_path, panel_invoker.run_provider,
                    child_scratch=decision) == ["unset", "unset"]


def test_an_unknown_decision_is_refused(tmp_path, monkeypatch):
    _ram_tmp(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="unknown child scratch decision"):
        panel_invoker.run_provider(["true"], env={}, child_scratch="skip")
    with pytest.raises(ValueError, match="unknown child scratch decision"):
        panel_invoker.run_provider(["true"], child_scratch="skip")


def test_a_launch_with_no_env_is_never_probed_or_refused(tmp_path, monkeypatch):
    """No `env` means the child inherits this process's own environment: nothing to decide,
    so nothing is probed -- not even under REFUSE_RAM with every candidate RAM-backed."""
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_REFUSE_RAM", "1")
    monkeypatch.setattr(sandbox_policy, "_mount_fstype", lambda p: "tmpfs")
    assert panel_invoker.run_provider(["true"]).returncode == 0


def test_a_bounded_leg_is_relocated_at_the_launch(tmp_path, monkeypatch):
    """Without a heartbeat profile, `_run_leg_with_liveness` asks the choke point to
    relocate; only the heartbeat profile (agent-harness#1181) may keep its private /tmp."""
    seen = {}

    def _launch(argv, **kwargs):
        seen["decision"] = kwargs.get("child_scratch")
        raise OSError("stop at the launch")

    monkeypatch.setattr(panel_invoker, "launch_provider", _launch)
    with pytest.raises(OSError):
        panel_invoker._run_leg_with_liveness(["true"], cwd=tmp_path, env={}, deadline_s=5)
    assert seen["decision"] == sandbox_policy.CHILD_SCRATCH_RELOCATE
