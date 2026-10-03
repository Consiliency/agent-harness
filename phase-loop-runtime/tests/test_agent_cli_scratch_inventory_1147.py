"""Every process launch in the runtime has a stated scratch decision (agent-harness#1147).

Two board rounds found agent-CLI launches that skipped the scratch relocation, one site
at a time. This file closes the class in two parts:

* ONE choke point for review providers. ``panel_invoker.launch_provider`` /
  ``run_provider`` apply :func:`sandbox_policy.child_scratch_env` to every ``env`` they
  launch with, and only the two named exceptions can opt out. The tests below OBSERVE a
  real child's environment through that interface.
* An INVENTORY derived from the code, CONSERVATIVE by construction: unknown means fail.
  Every use of a launch-capable module (subprocess, os.exec*/spawn*/posix_spawn*/system/
  popen, pty, asyncio and asyncio.subprocess, multiprocessing, event-loop
  ``subprocess_exec``) is enumerated from the AST. A use resolves only when it is a known
  attribute of a known binding (an import, an alias by assignment, an attribute receiver,
  a literal ``getattr`` name). A launch whose program is a literal and whose literal
  words, with shell quoting and metacharacters stripped and every positional argument
  read, name no agent CLI and no wrapper of a computed word, needs nothing. Everything
  else needs an ``INVENTORY`` entry with a reason: an opaque program, a launch function
  used as a value, a computed ``getattr``, ``__dict__``, the module handed on as a value,
  a dynamic import or ``exec``/``eval``, a literal agent argv passed to a listed
  pass-through helper. Each
  entry carries its launch count, and stale entries fail. Provider entry points are held
  to the same rule: any use that does not hand them a decided ``env`` (a call without
  one or with ``env=None``, a rename, a value use, a ``getattr``) must be listed.
"""

from __future__ import annotations

import ast
import os
import re
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
    "asyncio.subprocess": {"create_subprocess_exec", "create_subprocess_shell"},
    "multiprocessing": {"Process", "Pool"},
}
#: NOT_AGENT helpers that launch an argv their CALLERS supply. Their classification covers
#: what they are called with today; a call that hands one a literal agent-CLI argv is a
#: new agent launch and is recorded at the caller.
PASS_THROUGH_HELPERS = frozenset({"_run_process", "_run_bounded", "_run_probe",
                                  "run_notification_command", "_git_run", "_github_run"})
#: Event-loop launch methods, whatever the receiver (``loop.subprocess_exec``).
LOOP_LAUNCH_METHODS = frozenset({"subprocess_exec", "subprocess_shell"})
#: Submodules reached as an attribute of a launch-capable module.
SUBMODULES = {("asyncio", "subprocess"): "asyncio.subprocess"}

#: Program names that are agent CLIs, including their npm package basenames.
AGENT_CLIS = frozenset({"claude", "codex", "agy", "gemini", "grok", "opencode", "cursor-agent",
                        "claude-code", "gemini-cli"})
#: Programs that run another program named later in their argv.
WRAPPERS = frozenset({"env", "sudo", "doas", "bwrap", "sh", "bash", "zsh", "dash", "nsenter",
                      "unshare", "setpriv", "timeout", "nice", "ionice", "stdbuf", "xargs",
                      "npx", "npm", "pnpm", "uvx", "runuser", "su", "script", "firejail"})

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
    # Launch functions passed as values (injectable runners); each one's callers launch
    # only what is named here.
    ("advisor_board/research.py", "probe_research_capability"): (
        NOT_AGENT, "runner default: the pmcp capability probe"),
    ("advisor_board/research.py", "materialize_research_run"): (
        NOT_AGENT, "runner default, handed to probe_research_capability"),
    ("agy_watch.py", "main"): (NOT_AGENT, "runner default: gh / git and the qualification script"),
    ("convergence/broker/credsep.py", "resolve_git_origin_url"): (NOT_AGENT, "runner default: git"),
    ("convergence/broker/credsep.py", "resolve_broker_repo_identity"): (
        NOT_AGENT, "runner default: git"),
    ("convergence/broker/credsep.py", "GitHubBrokerAdapter.__init__"): (
        NOT_AGENT, "runner default: gh / git"),
    ("convergence/broker/live.py", "<module>"): (
        NOT_AGENT, "identity of the canonical gh / git runner, compared, never called"),
    ("convergence/broker/live.py", "_test_only_repository_broker_client"): (
        NOT_AGENT, "runner default for the GitHub adapter: gh / git"),
    ("convergence/broker/live.py", "build_routing_broker_client"): (
        NOT_AGENT, "runner default for the GitHub adapter: gh / git"),
    ("convergence/broker/live.py", "build_github_broker_client"): (
        NOT_AGENT, "runner default for the GitHub adapter: gh / git"),
    ("train_runner.py", "_gh_repo_binding"): (NOT_AGENT, "runner handed to git origin resolution"),
    ("train_runner.py", "_live_post_merge_prune"): (
        NOT_AGENT, "bash running the generated post-merge git prune script"),
    # Dynamic imports: a computed module name may be any module, so each is classified.
    ("cli.py", "_profile_command_registrars"): (
        NOT_AGENT, "dynamic import of a registered CLI profile module; launches nothing"),
    ("closeout_validators.py", "_import_builtin_validator"): (
        NOT_AGENT, "dynamic import of a built-in validator in this package"),
    ("convergence/broker/live.py", "_module_digest"): (
        NOT_AGENT, "dynamic import to hash a module's source file"),
    ("convergence/broker/live.py", "fabpub_capability_active"): (
        NOT_AGENT, "dynamic import of the FABPUB activation marker module"),
    ("governed_premerge.py", "_fabreadmit_capability_active"): (
        NOT_AGENT, "dynamic import of the FABREADMIT activation marker module"),
    ("roadmap_assumptions.py", "_observe_repo_constant"): (
        NOT_AGENT, "dynamic import of a roadmap-declared module to read a constant"),
    ("roadmap_assumptions.py", "_observe_repo_digest"): (
        NOT_AGENT, "dynamic import of a roadmap-declared module to hash it"),
    ("roadmap_assumptions.py", "_read_surface_value"): (
        NOT_AGENT, "dynamic import of a roadmap-declared module to read a value"),
    ("skill_inventory.py", "_iter_skill_source_roots_cached"): (
        NOT_AGENT, "dynamic import of a skill-bundle package to locate its files"),
    ("publishing.py", "_source_path_evidence"): (
        NOT_AGENT, "compile() of a parsed AST to validate publication source; never executed"),
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


#: How many launches that need a decision each INVENTORY function holds (1 unless listed).
#: A classification covers the launches it was made for: one more launch in a listed
#: function -- say a `claude` call added to a NOT_AGENT helper -- fails until reviewed.
LAUNCH_COUNTS: dict[tuple[str, str], int] = {
    ('agy_canary_evidence.py', '_bootstrap_attest_opened'): 2,
    ('agy_canary_evidence.py', 'probe_capability'): 3,
    ('launcher.py', 'launch'): 2,
    ('panel_invoker.py', '_exec_claude_agent_view_attempt'): 2,
    ('sandbox_egress.py', 'isolated_network'): 3,
    ('tdd_receipts.py', 'record_content_tdd_receipt'): 2,
    ('verification_evidence.py', 'execute_proofgate_mutation_manifest._execute_one._execute_worktree'): 2,
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
    """Every use of a provider entry point that does not hand it a decided env: a call
    with no ``env=`` or a literal ``env=None``, and -- conservatively -- any other use (an
    entry point used as a value, e.g. a runner default, or reached through ``getattr``),
    which may later be called with no env. Entry points renamed on import or by
    assignment are followed."""
    found = set()
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set(PROVIDER_ENTRY_POINTS)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names |= {a.asname for a in node.names
                          if a.asname and a.name in PROVIDER_ENTRY_POINTS}
        changed = True
        while changed:
            changed = False
            for node in ast.walk(tree):
                if (isinstance(node, ast.Assign) and isinstance(node.value, (ast.Name, ast.Attribute))
                        and _entry_name(node.value) in names):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id not in names:
                            names.add(target.id)
                            changed = True
        parents = _parents(tree)
        stack: list[str] = []

        class _Walker(ast.NodeVisitor):
            def _scope(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

            def _use(self, node):
                parent = parents.get(node)
                if isinstance(parent, ast.Call) and parent.func is node:
                    env = next((k.value for k in parent.keywords if k.arg == "env"), None)
                    if env is None or (isinstance(env, ast.Constant) and env.value is None):
                        found.add((rel, ".".join(stack) or "<module>"))
                elif isinstance(parent, ast.Assign) and parent.value is node:
                    pass  # a rename, followed above
                elif isinstance(parent, ast.Compare):
                    pass  # an identity check against the production seam, never a call
                else:
                    found.add((rel, ".".join(stack) or "<module>"))

            def visit_Name(self, node):
                if node.id in names and isinstance(node.ctx, ast.Load):
                    self._use(node)

            def visit_Attribute(self, node):
                if node.attr in names and isinstance(node.ctx, ast.Load):
                    self._use(node)
                self.generic_visit(node)

            def visit_Call(self, node):
                if (_is_getattr_call(node) and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value in PROVIDER_ENTRY_POINTS):
                    found.add((rel, ".".join(stack) or "<module>"))
                self.generic_visit(node)

        _Walker().visit(tree)
    return found


def _entry_name(node: ast.AST) -> str | None:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _module_aliases(tree: ast.AST) -> tuple[dict[str, str], list[str]]:
    """Names bound to a launch-capable module -- ``import subprocess as sp``, ``from
    asyncio import subprocess as asp``, and an assignment ``sp = subprocess`` at any
    scope -- and every from-import that would hide a launch from the walk (a named launch
    function, or ``*`` from a launch-capable module)."""
    aliases = {name: name for name in LAUNCHERS if "." not in name}
    hidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in LAUNCHERS:
                    aliases[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if full in LAUNCHERS:
                    aliases[alias.asname or alias.name] = full
                elif node.module in LAUNCHERS and (
                        alias.name == "*" or alias.name in LAUNCHERS[node.module]):
                    hidden.append(f"{node.module}.{alias.name}")
    changed = True
    while changed:  # `a = subprocess; b = a` -- to a fixed point
        changed = False
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
                    and node.value.id in aliases):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases[target.id] = aliases[node.value.id]
                        changed = True
    return aliases, hidden


def _module_of(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """The launch-capable module an expression denotes: an alias, ``x.subprocess``, or a
    submodule attribute (``asyncio.subprocess``)."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute):
        parent = _module_of(node.value, aliases)
        if parent is not None:
            return SUBMODULES.get((parent, node.attr))
        if node.attr in LAUNCHERS:
            return node.attr  # an attribute receiver: `lib.subprocess`
    return None


def _launch_fn(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """``subprocess.run`` / ``sp.run`` / ``x.subprocess.run`` / ``asyncio.subprocess.
    create_subprocess_exec`` / ``loop.subprocess_exec`` -> its name; else ``None``."""
    if not isinstance(node, ast.Attribute):
        return None
    module = _module_of(node.value, aliases)
    if module in LAUNCHERS and node.attr in LAUNCHERS[module]:
        return f"{module}.{node.attr}"
    if node.attr in LOOP_LAUNCH_METHODS:
        return f"loop.{node.attr}"
    return None


#: What a launch site records: the literal program, ``None`` when the AST cannot see it,
#: ``REFERENCE`` when a launch function is used as a VALUE (a default argument, an
#: assignment, a callback) and so may be called anywhere under another name, and
#: ``UNRESOLVED`` for a use of a launch-capable module the scanner cannot resolve to a
#: known attribute (``getattr(subprocess, name)``, ``vars(os)``, the module passed as a
#: value, ``subprocess.__dict__``, a dynamic import). Unknown is never assumed safe.
REFERENCE = "<launch function used as a value>"
UNRESOLVED = "<unresolved use of a launch-capable module>"
_SHELL_META = re.compile(r"""[;&|()<>`'"$={}\\]""")


def _words(text: str) -> list[str]:
    """A literal's words, with shell quoting and metacharacters removed (``sh -c
    "claude -p"``, ``x;claude``, ``(claude)`` all yield ``claude``)."""
    return [os.path.basename(w) for w in _SHELL_META.sub(" ", text).split()]


def _argv_facts(args: list[ast.AST]) -> tuple[object, bool]:
    """(the program, may this launch start an agent CLI). Every positional argument is
    read (``os.exec*`` / ``posix_spawn*`` carry the program in the second). An argv whose
    program is a WRAPPER and that holds any non-literal word may run anything."""
    literals: list[str] = []
    opaque = False
    program = None
    for index, arg in enumerate(args[:2]):
        elements = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
        for position, element in enumerate(elements):
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                literals.append(element.value)
                if index == 0 and position == 0:
                    program = element.value
            elif isinstance(element, ast.Starred) or not isinstance(element, ast.Constant):
                opaque = True
    if program is None:
        return None, False
    words = [w for text in literals for w in _words(text)]
    head = os.path.basename(program.split()[0]) if program.split() else ""
    if any(w in AGENT_CLIS for w in words):
        return program, True
    return program, head in WRAPPERS and opaque


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _is_dynamic_import(node: ast.Call) -> bool:
    """A computed import, or code compiled from a string (``exec``/``eval``/``compile``),
    may reach any module, so it is never assumed safe."""
    func = node.func
    if isinstance(func, ast.Name) and func.id in ("exec", "eval", "compile"):
        return True
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    if name not in ("__import__", "import_module"):
        return False
    first = node.args[0] if node.args else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.split(".")[0] in LAUNCHERS or first.value in LAUNCHERS
    return True  # a computed module name may be any module


def _launch_sites(package: Path | None = None) -> tuple[dict[tuple[str, str], list[object]], list[str]]:
    """(module, enclosing function) -> one entry per launch or unresolved use there: the
    literal program, ``None``, ``REFERENCE``, ``UNRESOLVED``, or ``"agent:<program>"``
    when the argv may start an agent CLI; and the hidden-import violations. Annotations
    are not launches and are not walked."""
    package = PACKAGE if package is None else package
    sites: dict[tuple[str, str], list[object]] = {}
    hidden_imports: list[str] = []
    for path in sorted(package.rglob("*.py")):
        rel = path.relative_to(package).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases, hidden = _module_aliases(tree)
        hidden_imports += [f"{rel}: from-import of {name}" for name in hidden]
        parents = _parents(tree)
        stack: list[str] = []

        def _record(entry):
            sites.setdefault((rel, ".".join(stack) or "<module>"), []).append(entry)

        class _Walker(ast.NodeVisitor):
            def _function(self, node):
                for item in node.decorator_list:
                    self.visit(item)
                stack.append(node.name)  # a default argument belongs to its function
                for item in [*node.args.defaults,
                             *[d for d in node.args.kw_defaults if d is not None], *node.body]:
                    self.visit(item)
                stack.pop()

            visit_FunctionDef = visit_AsyncFunctionDef = _function

            def visit_Lambda(self, node):
                for item in [*node.args.defaults,
                             *[d for d in node.args.kw_defaults if d is not None]]:
                    self.visit(item)
                self.visit(node.body)

            def visit_ClassDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_AnnAssign(self, node):
                if node.value is not None:
                    self.visit(node.value)

            def visit_Call(self, node):
                func = node.func
                getattr_target = _getattr_target(func)
                if _launch_fn(func, aliases) or getattr_target == "launch":
                    program, may_be_agent = _argv_facts(node.args)
                    _record(f"may-start-an-agent:{program}" if may_be_agent else program)
                    self.visit(func.value if isinstance(func, ast.Attribute) else func)
                else:
                    if _is_dynamic_import(node):
                        _record(UNRESOLVED)
                    if _entry_name(func) in PASS_THROUGH_HELPERS:
                        program, may_be_agent = _argv_facts(node.args)
                        if may_be_agent:
                            _record(f"may-start-an-agent:{program} via {_entry_name(func)}")
                    self.visit(func)
                for item in [*node.args, *node.keywords]:
                    self.visit(item)

            def visit_Attribute(self, node):
                if _launch_fn(node, aliases):
                    _record(REFERENCE)
                self.generic_visit(node)

            def visit_Name(self, node):
                if node.id in aliases and isinstance(node.ctx, ast.Load):
                    parent = parents.get(node)
                    if isinstance(parent, ast.Attribute) and parent.value is node:
                        if parent.attr.startswith("__"):
                            _record(UNRESOLVED)  # subprocess.__dict__ and the like
                    elif _is_getattr_of(parent, node):
                        verdict = _getattr_verdict(parent, aliases[node.id])
                        if verdict == "unresolved":
                            _record(UNRESOLVED)
                        elif verdict == "launch" and not isinstance(parents.get(parent), ast.Call):
                            _record(REFERENCE)
                    elif isinstance(parent, ast.Call) and parent.func is not node and (
                            isinstance(parent.func, ast.Name) and parent.func.id == "hasattr"):
                        pass  # `hasattr(os, "getuid")` touches nothing
                    elif isinstance(parent, ast.Assign) and parent.value is node:
                        pass  # an alias, modelled by `_module_aliases`
                    elif isinstance(parent, ast.Compare):
                        pass  # `pty is None`: an optional import, compared, never called
                    else:
                        _record(UNRESOLVED)  # the module itself handed on as a value

        def _getattr_target(func):
            if isinstance(func, ast.Call) and _is_getattr_call(func):
                module = _module_of(func.args[0], aliases)
                if module is not None:
                    return "launch" if _getattr_verdict(func, module) == "launch" else None
            return None

        _Walker().visit(tree)
    return sites, hidden_imports


def _is_getattr_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) >= 2)


def _is_getattr_of(parent: ast.AST | None, node: ast.AST) -> bool:
    return _is_getattr_call(parent) and parent.args[0] is node


def _getattr_verdict(call: ast.Call, module: str) -> str:
    """``getattr(<module>, name)``: "launch" when the name is a launch function, "ok" for
    another literal name, "unresolved" when the name is computed."""
    name = call.args[1]
    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
        return "unresolved"
    if name.value in LAUNCHERS.get(module, ()):
        return "launch"
    return "unresolved" if name.value.startswith("__") else "ok"


def _needs_a_decision(programs: list[object]) -> bool:
    return any(_one_needs_a_decision(p) for p in programs)


def _one_needs_a_decision(program: object) -> bool:
    return (program is None or program in (REFERENCE, UNRESOLVED)
            or str(program).startswith("may-start-an-agent:")
            or os.path.basename(str(program).split()[0] if str(program).split() else "")
            in AGENT_CLIS)


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


def test_each_listed_function_holds_exactly_its_counted_launches():
    sites, _ = _launch_sites()
    wrong = {key: n for key in INVENTORY
             if key in sites
             and (n := sum(map(_one_needs_a_decision, sites[key]))) != LAUNCH_COUNTS.get(key, 1)}
    assert not wrong, f"launch count changed in a listed function -- re-review it: {wrong}"


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


@pytest.mark.parametrize("key", sorted(k for k, v in INVENTORY.items()
                                       if v[0] in (RELOCATED, PROVIDER_INTERFACE)))
def test_each_relocated_site_names_its_decision(key):
    module, function, token = INVENTORY[key][1].split(":")
    assert token in _function_source(module, function.split(".")[-1]), INVENTORY[key]


def _undecided(package: Path) -> set[tuple[str, str]]:
    sites, _ = _launch_sites(package)
    return {k for k, v in sites.items() if _needs_a_decision(v)}


def test_the_scanner_sees_every_spelling_of_a_launch(tmp_path):
    """The inventory is only as good as its scanner. Every spelling below starts (or may
    start) an agent CLI and must be found, whatever API spawns it; the plain `git` call
    must not be."""
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "m.py").write_text(
        "import asyncio, os, pty, subprocess\n"
        "import subprocess as sp\n"
        "alias = subprocess\n"
        "def opaque(argv):\n    sp.Popen(argv)\n"
        "def named():\n    subprocess.run(['claude', '-p'])\n"
        "def wrapped():\n    subprocess.run(['env', 'X=1', 'claude', '-p'])\n"
        "def jailed():\n    subprocess.run(['bwrap', '--ro-bind', '/', '/', 'agy'])\n"
        "def shell():\n    subprocess.run(['sh', '-c', 'claude -p hi'])\n"
        "def injected(run=subprocess.run):\n    run(['claude', '--bg'])\n"
        "def assigned():\n    runner = subprocess.Popen\n    runner(['codex'])\n"
        "def by_alias():\n    alias.run(['claude'])\n"
        "def by_attribute(lib):\n    lib.subprocess.run(['claude'])\n"
        "def by_exec():\n    os.execvp('claude', ['claude'])\n"
        "def by_pty():\n    pty.spawn(['claude'])\n"
        "async def by_asyncio():\n    await asyncio.create_subprocess_exec('codex', 'exec')\n"
        "def annotated(p: subprocess.Popen) -> subprocess.CompletedProcess:\n    return p\n"
        "def plain():\n    subprocess.run(['git', 'status'])\n",
        encoding="utf-8")
    assert _undecided(fake) == {("m.py", name) for name in (
        "opaque", "named", "wrapped", "jailed", "shell", "injected", "assigned", "by_alias",
        "by_attribute", "by_exec", "by_pty", "by_asyncio")}


def test_unknown_is_never_assumed_safe(tmp_path):
    """Round 4 (agent-harness#1161): spellings that escaped a scanner which only modelled
    the spellings it knew. Every use of a launch-capable module the scanner cannot resolve
    to a known attribute now needs a decision; the controls at the end do not."""
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "m.py").write_text(
        "import asyncio, importlib, multiprocessing, os, pty, subprocess\n"
        "from asyncio import subprocess as asp\n"
        "_CLI = 'claude'\n"
        "def by_getattr():\n    getattr(subprocess, 'run')(['claude', '-p', 'hi'])\n"
        "def by_computed_getattr(name):\n    getattr(subprocess, name)\n"
        "def by_dunder_dict():\n    subprocess.__dict__['run'](['claude'])\n"
        "def by_module_value(f):\n    f(subprocess)\n"
        "def by_dunder_import():\n    __import__('subprocess')\n"
        "def by_import_module(name):\n    importlib.import_module(name)\n"
        "def by_quoted_shell():\n    subprocess.run('sh -c \"claude -p x\"', shell=True)\n"
        "def by_semicolon():\n    subprocess.run('cd /r;claude', shell=True)\n"
        "def by_and():\n    subprocess.run('true&&claude', shell=True)\n"
        "def by_subshell():\n    subprocess.run(['sh', '-c', '(claude -p)'])\n"
        "def by_wrapper_variable():\n    subprocess.run(['env', _CLI])\n"
        "def by_exec_argv():\n    os.execv('/usr/bin/env', ['env', 'claude'])\n"
        "def by_asyncio_submodule():\n    asyncio.subprocess.create_subprocess_exec('codex')\n"
        "def by_asyncio_alias():\n    asp.create_subprocess_exec('codex')\n"
        "def by_loop(loop, proto):\n    loop.subprocess_exec(proto, 'codex')\n"
        "def by_multiprocessing(target):\n    multiprocessing.Process(target=target)\n"
        "def by_npx():\n    subprocess.run(['npx', '@anthropic-ai/claude-code', '-p'])\n"
        "def by_helper(ev):\n    ev._run_process(['claude', '-p'])\n"
        "def by_exec_string():\n    exec('import subprocess')\n"
        "def control_helper(ev):\n    ev._run_process(['pytest', '-q'])\n"
        "def control_attributes():\n"
        "    return (subprocess.PIPE, os.path.join('a', 'b'), hasattr(os, 'getuid'),\n"
        "            getattr(os, 'O_NOFOLLOW', None), pty is None)\n"
        "def control_git(repo):\n    subprocess.run(['git', '-C', str(repo), 'status'])\n",
        encoding="utf-8")
    assert _undecided(fake) == {("m.py", name) for name in (
        "by_getattr", "by_computed_getattr", "by_dunder_dict", "by_module_value",
        "by_dunder_import", "by_import_module", "by_quoted_shell", "by_semicolon", "by_and",
        "by_subshell", "by_wrapper_variable", "by_exec_argv", "by_asyncio_submodule",
        "by_asyncio_alias", "by_loop", "by_multiprocessing", "by_npx", "by_helper",
        "by_exec_string")}


def test_a_star_import_of_a_launch_module_is_refused(tmp_path):
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "m.py").write_text("from subprocess import *\n", encoding="utf-8")
    assert _launch_sites(fake)[1] == ["m.py: from-import of subprocess.*"]


def test_every_use_of_a_provider_entry_point_without_a_decided_env_is_found(tmp_path):
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "m.py").write_text(
        "from .panel_invoker import run_provider as rp, launch_provider\n"
        "from . import panel_invoker\n"
        "def renamed():\n    rp(['claude'])\n"
        "def none_env():\n    launch_provider(['claude'], env=None)\n"
        "def as_runner(adapter):\n    adapter(runner=panel_invoker.run_provider)\n"
        "def by_getattr():\n    getattr(panel_invoker, 'run_provider')\n"
        "def assigned():\n    run = rp\n    run(['claude'])\n"
        "def identity():\n    return launch_provider is not None\n"
        "def decided(env):\n    rp(['claude'], env=env)\n",
        encoding="utf-8")
    assert _provider_calls_without_env(fake) == {("m.py", name) for name in (
        "renamed", "none_env", "as_runner", "by_getattr", "assigned")}


def test_an_unlisted_injected_runner_launch_in_the_real_package_fails_the_inventory(tmp_path):
    """The Agent View shape the board found (a launch function injected as a default and
    called through an attribute), added to a copy of the REAL package, is undecided."""
    import shutil

    copy = tmp_path / "phase_loop_runtime"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    with (copy / "claude_agent_view.py").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n\nclass _Mutant:\n"
            "    def __init__(self, runner=subprocess.run):\n        self._runner = runner\n"
            "    def go(self, argv):\n        return self._runner(argv)\n")
    assert _undecided(copy) - set(INVENTORY) == {("claude_agent_view.py", "_Mutant.__init__")}
    assert _undecided(PACKAGE) <= set(INVENTORY)


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
    with pytest.raises(ValueError, match="unknown child scratch decision"):
        sandbox_policy.child_scratch_env({}, "skip")


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
