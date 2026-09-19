"""Every provider launch goes through the namespace, or the build fails.

Egress isolation took four board rounds, and the finding that ended round 4 was not about
the mechanism -- the namespace works, the rules bind, the capability drop holds. It was
about REACH. The prefix was wired into one `subprocess.Popen` and the module had three
launch seams, so a TUI seat and an agent-view seat launched beside the namespace while the
evidence was assembled as though they had launched inside it.

A hand-check cannot hold that property: it is true of the file on the day someone reads it
and silently false the next time a seam is added. So the property is asserted by walking
the AST. A new spawn in `panel_invoker` is either prefixed, or named here with a reason.

The allowlist is the load-bearing half. Not every spawn belongs inside the namespace --
`claude auth status`, `git rev-parse`, the adapter's list/stop/logs calls are the PARENT
asking the host about itself, and running those through a filtered namespace would break
them for no security gain. Listing them by intent is what keeps this test from degenerating
into "wire everything".
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from phase_loop_runtime import panel_invoker


# Dotted names that start a process. `pty.spawn`/`pty.fork` are here because the module
# ALREADY imports `pty` (panel_invoker.py, the TUI seam), so that evasion is one refactor
# away rather than hypothetical.
SPAWN_FUNCTIONS = frozenset({
    "subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "os.execl", "os.execle", "os.execlp", "os.execlpe",
    "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe",
    "os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
    "os.posix_spawn", "os.posix_spawnp", "os.system", "os.popen",
    "os.fork", "os.forkpty",
    "pty.spawn", "pty.fork",
    "multiprocessing.Process",
    "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
})

# The bare attribute names above. A call we cannot RESOLVE but whose callee is spelled like
# one of these is reported as unresolved rather than dropped -- see `_spawn_sites`.
SPAWN_ATTRS = frozenset(name.rsplit(".", 1)[1] for name in SPAWN_FUNCTIONS)
# Keywords each spawn accepts for its argv. `subprocess.Popen(args=cmd)` passes NO
# positional argument, and an earlier version of this walker skipped any call with an
# empty `node.args` -- so that evasion worked against the shipped instrument, not merely
# against a future one (agent-harness#890 board round 5, claude seat).
ARGV_KEYWORDS = ("args", "argv", "cmd", "command", "program", "path", "file")

PREFIX_EXPR = "_EGRESS_LAUNCH_PREFIX.get()"

# Spawns that are the PARENT acting on its own host, not a reviewer executing. Keyed by the
# argv expression as it appears in the source, so renaming or re-pointing one at a provider
# drops it off the list and fails this test.
# Calls whose NAME collides with a spawn but which start no process. Kept separate from
# PARENT_SIDE_ALLOWLIST on purpose: that list means "the parent acting on its own host",
# and folding a different justification into it would quietly destroy what it asserts.
NOT_A_PROCESS_LAUNCH: dict[str, str] = {
    "<unresolved:spawn>": (
        "`spawn` is the injectable SpawnFn seam (panel_invoker.py:6547), not a process "
        "call; in production it IS `_default_spawn`, whose real launches are the three "
        "prefixed seams below it"
    ),
}

# The ONE sanctioned provider spawn, by site. Everything else in a leg-path module is
# either declared parent-side or a defect.
THE_LAUNCH_INTERFACE: dict[tuple[str, str], str] = {
    ("panel_invoker.py", "[*_EGRESS_LAUNCH_PREFIX.get(), *argv]"):
        "launch_provider -- the only Popen that may start a review provider",
}

PARENT_SIDE_ALLOWLIST: dict[tuple[str, str], str] = {
    # KEYED BY (module, argv). Keying on the argv expression ALONE exempted the same
    # spelling everywhere: the entry below for backing.py's bwrap probe is the bare name
    # `argv`, so board round 8 pointed out that ANY `subprocess.Popen(argv)` in any scanned
    # module inherited the exemption --
    #
    #     def launch_provider(command):
    #         argv = list(command)
    #         return subprocess.Popen(argv)
    #
    # -- confirmed by execution: seen by the walker, accepted by the assertion. An
    # exemption has to name the call site it excuses, not a string that might occur
    # anywhere.
    ("panel_invoker.py", "probe"): "capability probe for the harness itself",
    ("panel_invoker.py", "['claude', 'auth', 'status', '--json']"):
        "parent checks ITS OWN credentials",
    ("panel_invoker.py", "[claude_bin, '--version']"):
        "parent reads the installed CLI version",
    ("panel_invoker.py", "adapter.list_command()"): "parent enumerates sessions it owns",
    ("panel_invoker.py", "adapter.stop_command(session_id)"):
        "parent tears down a session it started",
    ("panel_invoker.py", "adapter.logs_command(session_id)"):
        "parent reads back a session's log",
    ("panel_invoker.py", "['git', '-C', str(tree), 'cat-file', '-e', f'{commit}^{{commit}}']"):
        "parent verifies a commit in the REVIEWED repo, not the sandbox",
    ("panel_invoker.py", "['git', '-C', str(candidate), 'rev-parse', '--show-toplevel']"):
        "parent resolves the repo root",
    ("backing.py", "['git', '-C', str(candidate), 'rev-parse', '--show-toplevel']"):
        "parent resolves the repo root",
    ("backing.py", "argv"):
        "the bwrap posture-probe child, launched --unshare-all so it has NO network; an "
        "egress prefix would be redundant and would fight bwrap",
    ("backing.py", "['git', '-C', str(self.canonical_repo), 'ls-files', '-z']"):
        "parent digests the canonical repo to bind the authorization",
    ("review_stage.py", "['git', '-C', str(repo), 'ls-files', '-z']"):
        "parent enumerates tracked files to stage",
    ("review_stage.py", "['git', '-C', str(repo), 'ls-files', '-z', '--others', '--exclude-standard']"):
        "parent enumerates untracked-but-not-ignored files to stage",
    ("review_stage.py", "['git', '-C', str(repo), *args]"):
        "parent runs git against the REVIEWED repo",
    ("review_stage.py", "['git', 'clone', '--quiet', '--depth', str(CLONE_DEPTH), '--no-single-branch', f'file://{root}', str(staged)]"):
        "parent creates the sandbox clone; it IS the staging step",
    ("review_stage.py", "['git', '-C', str(staged), 'checkout', '--quiet', '--detach', head]"):
        "parent pins the fresh clone to the reviewed commit",
    ("sandbox_egress.py", "['unshare', '--net', '--mount', '--map-root-user', 'bash', '-c', f'mount --bind {resolv} /etc/resolv.conf 2>/dev/null; echo $$ > {pidfile}; touch {ready}; sleep {timeout_s}']"):
        "the namespace HOLDER -- it creates the confinement, so it cannot be inside it",
    ("sandbox_egress.py", "['slirp4netns', '--configure', '--mtu=65520', '--disable-host-loopback', nspid, 'tap0']"):
        "the uplink for that namespace, run from OUTSIDE it by definition",
    ("sandbox_egress.py", "[*admin, 'bash', '-c', 'set -e\\nip link set lo up 2>/dev/null || true\\n' + rules]"):
        "installs the policy INSIDE the namespace; already carries the nsenter prefix",
    ("sandbox_egress.py", "['unshare', '--net', '--map-root-user', 'true']"):
        "capability probe: can this host make a namespace at all",
}



def _bindings(tree: ast.Module) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """What every name in this module actually refers to, and what we could not resolve.

    Board round 6 found nine further evasions of the previous version, and demonstrated one
    by adding a REAL unprefixed provider launch to `panel_invoker.py`:

        _LAUNCH = subprocess.Popen
        def _evil_provider_launch(cmd, cwd, env):
            return _LAUNCH(cmd, cwd=cwd, env=env)

    Site count stayed 12 and the coverage test passed. Two structural causes, both fixed
    here: only import-bound names were resolvable at all, and `import os.path` bound
    `modules["os"] = "os.path"`, so one innocuous import blinded every `os.*` spawn.

    Assignments are now followed, so aliasing a spawn does not hide it; and anything that
    cannot be resolved is RETURNED rather than dropped, because a launch we cannot read is
    more dangerous than one we can, not less.
    """
    modules: dict[str, str] = {}
    direct: dict[str, str] = {}
    unresolvable: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                else:
                    # `import os.path` binds the TOP-level name `os`, which still refers
                    # to the `os` module. Binding it to "os.path" was the blinding bug.
                    top = alias.name.split(".")[0]
                    modules.setdefault(top, top)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                if alias.name == "*":
                    if any(fn.startswith(f"{node.module}.") for fn in SPAWN_FUNCTIONS):
                        unresolvable.append(
                            f"line {node.lineno}: `from {node.module} import *` makes every "
                            f"spawn in {node.module} unresolvable by name"
                        )
                    continue
                direct[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    # Parameter DEFAULTS and ASSIGNMENTS both bind names, and either can depend on the
    # other, so neither may be resolved "first". An earlier version walked defaults and
    # then assignments once each, which board round 8 defeated with:
    #
    #     _LAUNCH = subprocess.Popen
    #     def launch_provider(command, make=_LAUNCH): return make(command)
    #
    # `make` was resolved against a binding table that did not yet contain `_LAUNCH`, and
    # nothing revisited it. Confirmed by execution: 0 sites. Iterating to a FIXPOINT
    # removes the ordering question entirely rather than swapping one order for another.
    for _pass in range(8):
        discovered = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                arguments = node.args
                positional = arguments.posonlyargs + arguments.args
                pairs: list[tuple[ast.arg, ast.expr]] = []
                if arguments.defaults:
                    pairs += list(zip(positional[-len(arguments.defaults):],
                                      arguments.defaults))
                pairs += [(a, d) for a, d in zip(arguments.kwonlyargs, arguments.kw_defaults)
                          if d]
                for argument, default in pairs:
                    resolved = _resolve(default, modules, direct)
                    if resolved in SPAWN_FUNCTIONS and direct.get(argument.arg) != resolved:
                        direct[argument.arg] = resolved
                        discovered += 1
            elif isinstance(node, ast.ClassDef):
                # `_R.mk = subprocess.Popen` called as `_R.mk(cmd)`. The bare-attribute
                # binding below records `mk`, but `_resolve` on `_R.mk` looks up `_R`,
                # which is neither a module nor an aliased spawn, so it returned None --
                # and `mk` is not spelled like a spawn, so the fail-closed net dropped it
                # too. Board round 8 executed this against the shipped walker: 0 sites.
                #
                # The existing "class-attribute alias" fixture passed only because it
                # happened to name the attribute `run`, which IS in SPAWN_ATTRS. It was
                # green for the wrong reason.
                for statement in node.body:
                    if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                        continue
                    value = statement.value
                    if value is None:
                        continue
                    resolved = _resolve(value, modules, direct)
                    if resolved not in SPAWN_FUNCTIONS:
                        continue
                    targets = (statement.targets if isinstance(statement, ast.Assign)
                               else [statement.target])
                    for target in targets:
                        if isinstance(target, ast.Name):
                            qualified = f"{node.name}.{target.id}"
                            if direct.get(qualified) != resolved:
                                direct[qualified] = resolved
                                discovered += 1
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if value is None:
                    continue
                resolved = _resolve(value, modules, direct)
                if resolved not in SPAWN_FUNCTIONS:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = (target.id if isinstance(target, ast.Name)
                            else target.attr if isinstance(target, ast.Attribute) else None)
                    if name and direct.get(name) != resolved:
                        direct[name] = resolved
                        discovered += 1
        if not discovered:
            break

    return modules, direct, unresolvable


def _resolve(func: ast.expr, modules: dict[str, str], direct: dict[str, str]) -> str | None:
    """The dotted name an expression resolves to, or None."""
    if isinstance(func, ast.Name):
        return direct.get(func.id)
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            qualified = direct.get(f"{func.value.id}.{func.attr}")
            if qualified:
                return qualified
            module = modules.get(func.value.id)
            if module:
                return f"{module}.{func.attr}"
            base = direct.get(func.value.id)
            if base:
                return f"{base}.{func.attr}"
        return None
    if isinstance(func, ast.Call):
        # getattr(subprocess, "Popen")(cmd)
        if getattr(func.func, "id", None) == "getattr" and len(func.args) >= 2:
            owner = _resolve(func.args[0], modules, direct) or (
                modules.get(getattr(func.args[0], "id", "")) or ""
            )
            attr = getattr(func.args[1], "value", None)
            if owner and isinstance(attr, str):
                return f"{owner}.{attr}"
    return None


def _argv_of(node: ast.Call) -> str | None:
    if node.args:
        return ast.unparse(node.args[0])
    for keyword in node.keywords:
        if keyword.arg in ARGV_KEYWORDS:
            return ast.unparse(keyword.value)
    return None


# Every module on the path from a review leg to a launched provider. Round 7 flagged that
# scanning `panel_invoker` alone left the rest of that path unchecked. The package has 248
# spawns across 68 modules; scanning all of them would need a ~240-entry allowlist that
# nobody would read, and most are git plumbing for unrelated subsystems. So the scope is
# the LEG PATH, named explicitly, rather than one module pretending to be it or the whole
# package pretending to be reviewable.
LEG_PATH_MODULES = ("panel_invoker", "advisor_board.backing", "review_stage", "sandbox_egress")


def _module_paths() -> list[tuple[str, Path]]:
    root = Path(panel_invoker.__file__).parent
    paths = [(name, root.joinpath(*name.split(".")).with_suffix(".py"))
             for name in LEG_PATH_MODULES]
    # Missing files are skipped so the evasion fixtures -- which point `__file__` at a
    # single synthetic module -- exercise the walker itself. `test_the_leg_path_modules_
    # all_exist` is what stops that tolerance from hiding a renamed or deleted module.
    return [(name, path) for name, path in paths if path.is_file()]


def test_the_leg_path_modules_all_exist():
    """Guard the tolerance above: every declared module must really be scanned."""
    root = Path(panel_invoker.__file__).parent
    missing = [name for name in LEG_PATH_MODULES
               if not root.joinpath(*name.split(".")).with_suffix(".py").is_file()]
    assert not missing, (
        f"these leg-path modules are not being scanned at all: {missing}. "
        "A rename silently narrows this guard to whatever still resolves."
    )


def _spawn_sites() -> list[tuple[str, int, str, str]]:
    return [site for _name, path in _module_paths() for site in _sites_in(path)]


def _sites_in(path: Path) -> list[tuple[str, int, str, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules, direct, unresolvable = _bindings(tree)
    sites: list[tuple[int, str, str]] = []

    for note in unresolvable:
        sites.append((path.name, 0, "<unresolvable-import>", f"<{note}>"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call = node
        resolved = _resolve(node.func, modules, direct)

        if resolved is None and ast.unparse(node.func).endswith("functools.partial"):
            resolved = "functools.partial"
        if resolved == "functools.partial" or ast.unparse(node.func) == "functools.partial":
            if not node.args:
                continue
            inner = _resolve(node.args[0], modules, direct)
            if inner not in SPAWN_FUNCTIONS:
                continue
            resolved = inner
            call = ast.Call(func=node.args[0], args=node.args[1:], keywords=node.keywords)

        if resolved in SPAWN_FUNCTIONS:
            argv = _argv_of(call)
            sites.append((path.name, node.lineno, resolved, argv if argv is not None
                          else f"<unreadable argv at line {node.lineno}>"))
            continue

        # FAIL CLOSED ON WHAT WE CANNOT RESOLVE. The previous walker returned None for any
        # binding it did not understand and silently dropped the call; that is how a real
        # `_LAUNCH = subprocess.Popen` shipped undetected. A callee SPELLED like a spawn
        # but not resolvable is reported for a human to triage.
        callee = ast.unparse(node.func)
        leaf = callee.rsplit(".", 1)[-1]
        if resolved is None and leaf in SPAWN_ATTRS:
            argv = _argv_of(call) or "<no argv>"
            sites.append((path.name, node.lineno, f"<unresolved:{callee}>", argv))

    return sites


def test_the_module_still_has_spawn_sites_to_check():
    """Guard the guard: a rename of `subprocess` would make every assertion below vacuous."""
    assert len(_spawn_sites()) >= 8, "the walker found almost nothing; it is not walking"


def test_every_provider_launch_carries_the_egress_prefix():
    """The invariant, restated so it can actually be established.

    It used to be "every spawn mentions `_EGRESS_LAUNCH_PREFIX.get()`", which is a claim
    about SOURCE TEXT, and seats evaded it twenty-three times across four rounds -- by
    aliasing, by parameter defaults, by class attributes, by an exemption keyed on a bare
    identifier. Pattern-matching call sites cannot establish it.

    It is now "the leg-path modules contain no provider spawn outside
    `launch_provider`/`run_provider`". One call site, so a new launch that forgets the
    prefix is not a spelling the walker must recognise -- it is an undeclared spawn, and
    it fails whatever it is called and however it is bound.
    """
    undeclared = [
        (module, lineno, func, argv)
        for module, lineno, func, argv in _spawn_sites()
        if (module, argv) not in PARENT_SIDE_ALLOWLIST
        and func not in NOT_A_PROCESS_LAUNCH
        and (module, argv) not in THE_LAUNCH_INTERFACE
    ]
    assert not undeclared, (
        "these spawns are neither the launch interface nor declared parent-side:\n"
        + "\n".join(f"  {m}:{n}  {f}({a})" for m, n, f, a in undeclared)
        + "\n\nStart providers through `panel_invoker.launch_provider` / `run_provider`, "
          "or add this site to PARENT_SIDE_ALLOWLIST with the reason it is the parent "
          "acting on its own host rather than a reviewer executing."
    )


def test_the_launch_interface_is_the_only_thing_that_prefixes():
    """And it must actually prefix. The rule above is worthless if it does not."""
    import inspect

    for name in ("launch_provider", "run_provider"):
        source = inspect.getsource(getattr(panel_invoker, name))
        assert "_EGRESS_LAUNCH_PREFIX.get()" in source, (
            f"{name} is the only sanctioned way to start a provider and it does not "
            "apply the egress prefix"
        )


def test_the_interface_actually_applies_the_prefix_when_called():
    """Executed, not read -- the lesson of the last two rounds."""

    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(("/bin/echo", "PREFIXED"))
    try:
        result = panel_invoker.run_provider(
            ["hello"], capture_output=True, text=True, timeout=30,
        )
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    assert result.stdout.strip() == "PREFIXED hello", (
        f"the interface did not prepend the prefix: {result.stdout!r}"
    )


def test_all_three_seats_start_through_the_interface():
    """A stale allowlist could satisfy the rule above by covering everything.

    The three provider launches -- CLI leg, TUI PTY, agent-view -- must each call the
    interface rather than build their own argv. Asserting "2 sites are prefixed" would now
    be satisfied by the two helper bodies alone while every seat bypassed them.
    """

    # Two of the three launches live in nested `_popen` closures, so this reads the
    # ENCLOSING functions -- naming `_exec_leg` and getting a pass from a docstring would
    # be the proxy trap again.
    import ast

    source_text = Path(panel_invoker.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    interface_calls = {
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) in ("launch_provider", "run_provider")
    }
    assert len(interface_calls) >= 3, (
        f"expected the CLI-leg, TUI-PTY and agent-view launches to route through the "
        f"interface; found {len(interface_calls)} call(s) at {sorted(interface_calls)}"
    )

    enclosing = set()
    for line in interface_calls:
        best = None
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.lineno <= line <= (node.end_lineno or 0)
                    and (best is None or node.lineno > best.lineno)):
                best = node
        if best is not None:
            enclosing.add(best.name)
    assert len(enclosing) >= 2, (
        f"all interface calls collapsed into one place: {enclosing}"
    )


def test_the_allowlist_does_not_rot():
    """An entry that no longer matches any spawn is a stale exemption -- delete it."""
    live = {(module, argv) for module, _lineno, _func, argv in _spawn_sites()}
    stale = sorted(set(PARENT_SIDE_ALLOWLIST) - live)
    assert not stale, f"these allowlist entries match no spawn any more: {stale}"


def test_the_walker_actually_fails_on_an_unwired_spawn(tmp_path, monkeypatch):
    """The falsifier. A guard that has never been seen to fail is not a guard."""
    # Named `panel_invoker.py` because the scanner resolves modules BY NAME now.
    fake = tmp_path / "panel_invoker.py"
    fake.write_text(
        "import subprocess\n"
        "def launch(cmd):\n"
        "    return subprocess.Popen(list(cmd))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(panel_invoker, "__file__", str(fake))

    sites = _spawn_sites()
    assert sites, "the fixture must present a spawn"
    assert all(PREFIX_EXPR not in argv for _m, _l, _f, argv in sites)
    assert all((m, argv) not in PARENT_SIDE_ALLOWLIST for m, _l, _f, argv in sites), (
        "the fixture's spawn must be caught, not exempted"
    )
    with pytest.raises(AssertionError, match="neither the launch interface nor declared"):
        test_every_provider_launch_carries_the_egress_prefix()


class TestTheWalkerResistsTheEvasionsTheBoardDemonstrated:
    """Board round 5, claude seat: 5 of 6 evasions were invisible to the shipped walker.

    Reported measurement, against the version that shipped in this PR:

        kwarg args=                              sites=0  CAUGHT=False
        from-import (from subprocess import Popen)  sites=0  CAUGHT=False
        aliased module (import subprocess as sp)    sites=0  CAUGHT=False
        functools.partial                        sites=0  CAUGHT=False
        pty.spawn                                sites=0  CAUGHT=False
        os.fork + os.execvp                      sites=1  CAUGHT=True

    `subprocess.Popen(args=cmd)` evaded it *today*, not hypothetically: the walker skipped
    any call with no positional argument. And `pty` is already imported by the module under
    inspection, so that route is one refactor away rather than theoretical.

    An instrument whose evasions are cheaper than the thing it guards is decoration. These
    are the evasions, as fixtures, each required to be seen.
    """

    EVASIONS = {
        "kwarg args=": (
            "import subprocess\n"
            "def launch(cmd):\n"
            "    return subprocess.Popen(args=cmd)\n"
        ),
        "from-import": (
            "from subprocess import Popen\n"
            "def launch(cmd):\n"
            "    return Popen(cmd)\n"
        ),
        "aliased module": (
            "import subprocess as sp\n"
            "def launch(cmd):\n"
            "    return sp.Popen(cmd)\n"
        ),
        "functools.partial": (
            "import functools, subprocess\n"
            "def launch(cmd):\n"
            "    return functools.partial(subprocess.Popen, cmd)()\n"
        ),
        "pty.spawn": (
            "import pty\n"
            "def launch(cmd):\n"
            "    return pty.spawn(cmd)\n"
        ),
        "os.execvp": (
            "import os\n"
            "def launch(cmd):\n"
            "    return os.execvp(cmd[0], cmd)\n"
        ),
        "aliased from-import": (
            "from subprocess import Popen as P\n"
            "def launch(cmd):\n"
            "    return P(cmd)\n"
        ),
        "os.posix_spawn": (
            "import os\n"
            "def launch(cmd):\n"
            "    return os.posix_spawn(cmd[0], cmd, {})\n"
        ),
        # --- round 6: nine further evasions, all invisible to the previous walker ------
        "os.path clobbers the os binding": (
            "import os.path\n"
            "def launch(cmd):\n"
            "    return os.system(cmd)\n"
        ),
        "module-level alias assignment": (
            "import subprocess\n"
            "_LAUNCH = subprocess.Popen\n"
            "def launch(cmd):\n"
            "    return _LAUNCH(cmd)\n"
        ),
        "chained alias": (
            "import subprocess\n"
            "_A = subprocess.Popen\n"
            "_B = _A\n"
            "def launch(cmd):\n"
            "    return _B(cmd)\n"
        ),
        "star import": (
            "from subprocess import *\n"
            "def launch(cmd):\n"
            "    return Popen(cmd)\n"
        ),
        "getattr indirection": (
            "import subprocess\n"
            "def launch(cmd):\n"
            "    return getattr(subprocess, 'Popen')(cmd)\n"
        ),
        "os.execle": (
            "import os\n"
            "def launch(cmd):\n"
            "    return os.execle(cmd[0], *cmd, {})\n"
        ),
        "os.spawnve": (
            "import os\n"
            "def launch(cmd):\n"
            "    return os.spawnve(os.P_NOWAIT, cmd[0], cmd, {})\n"
        ),
        "os.forkpty": (
            "import os\n"
            "def launch(cmd):\n"
            "    return os.forkpty()\n"
        ),
        "multiprocessing.Process": (
            "import multiprocessing\n"
            "def launch(cmd):\n"
            "    return multiprocessing.Process(target=cmd)\n"
        ),
        "parameter default": (
            "import subprocess\n"
            "def launch(cmd, make=subprocess.Popen):\n"
            "    return make(cmd)\n"
        ),
        "kwonly parameter default": (
            "import subprocess\n"
            "def launch(cmd, *, make=subprocess.Popen):\n"
            "    return make(cmd)\n"
        ),
        # --- round 8: both confirmed by execution against the shipped walker ---
        "default referencing an assignment alias": (
            "import subprocess\n"
            "_LAUNCH = subprocess.Popen\n"
            "def launch(command, make=_LAUNCH):\n"
            "    return make(command)\n"
        ),
        "argv rebound as a local": (
            # Not an evasion of the WALKER -- it sees this -- but of the ASSERTION, via an
            # exemption keyed on the bare expression `argv` that belonged to another module.
            "import subprocess\n"
            "def launch(command):\n"
            "    argv = list(command)\n"
            "    return subprocess.Popen(argv)\n"
        ),
        "class-attribute alias": (
            "import subprocess\n"
            "class Launcher:\n"
            "    run = subprocess.Popen\n"
            "def launch(cmd):\n"
            "    return Launcher.run(cmd)\n"
        ),
    }

    def _sites_for(self, tmp_path, monkeypatch, name, source):
        holder = tmp_path / name.replace(" ", "_").replace(".", "_")
        holder.mkdir(exist_ok=True)
        fake = holder / "panel_invoker.py"
        fake.write_text(source, encoding="utf-8")
        monkeypatch.setattr(panel_invoker, "__file__", str(fake))
        return _spawn_sites()

    @pytest.mark.parametrize("name", sorted(EVASIONS))
    def test_each_evasion_is_seen(self, name, tmp_path, monkeypatch):
        sites = self._sites_for(tmp_path, monkeypatch, name, self.EVASIONS[name])
        assert sites, f"{name!r} launches a process the walker cannot see"

    @pytest.mark.parametrize("name", sorted(EVASIONS))
    def test_each_evasion_is_REPORTED_not_merely_counted(self, name, tmp_path, monkeypatch):
        """Seeing it is not enough: an unprefixed, unallowlisted spawn must FAIL."""
        self._sites_for(tmp_path, monkeypatch, name, self.EVASIONS[name])
        with pytest.raises(AssertionError, match="neither the launch interface nor declared"):
            test_every_provider_launch_carries_the_egress_prefix()

    def test_an_unreadable_argv_fails_closed(self, tmp_path, monkeypatch):
        """A spawn whose argv the walker cannot parse is MORE dangerous, not less."""
        sites = self._sites_for(
            tmp_path, monkeypatch, "opaque",
            "import subprocess\ndef launch(**kw):\n    return subprocess.Popen(**kw)\n",
        )
        assert sites, "an argv-less spawn must still be reported"
        assert "unreadable" in sites[0][3]
