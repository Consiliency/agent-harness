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
    "os.execv", "os.execve", "os.execvp", "os.execvpe", "os.execl", "os.execlp",
    "os.spawnv", "os.spawnvp", "os.posix_spawn", "os.posix_spawnp", "os.system",
    "os.popen", "pty.spawn", "pty.fork",
    "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
})

# Keywords each spawn accepts for its argv. `subprocess.Popen(args=cmd)` passes NO
# positional argument, and an earlier version of this walker skipped any call with an
# empty `node.args` -- so that evasion worked against the shipped instrument, not merely
# against a future one (agent-harness#890 board round 5, claude seat).
ARGV_KEYWORDS = ("args", "argv", "cmd", "command", "program", "path", "file")

PREFIX_EXPR = "_EGRESS_LAUNCH_PREFIX.get()"

# Spawns that are the PARENT acting on its own host, not a reviewer executing. Keyed by the
# argv expression as it appears in the source, so renaming or re-pointing one at a provider
# drops it off the list and fails this test.
PARENT_SIDE_ALLOWLIST: dict[str, str] = {
    "probe": "capability probe for the harness itself",
    "['claude', 'auth', 'status', '--json']": "parent checks ITS OWN credentials",
    "[claude_bin, '--version']": "parent reads the installed CLI version",
    "adapter.list_command()": "parent enumerates sessions it owns",
    "adapter.stop_command(session_id)": "parent tears down a session it started",
    "adapter.logs_command(session_id)": "parent reads back a session's log",
    "['git', '-C', str(tree), 'cat-file', '-e', f'{commit}^{{commit}}']":
        "parent verifies a commit in the REVIEWED repo, not the sandbox",
    "['git', '-C', str(candidate), 'rev-parse', '--show-toplevel']":
        "parent resolves the repo root",
}



def _import_bindings(tree: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve what names in this module actually refer to.

    `import subprocess as sp` and `from subprocess import Popen` both defeat a walker that
    matches the literal text `subprocess.Popen`. Five of six evasions the board
    demonstrated were of exactly this shape, so the names are resolved rather than matched.
    """
    modules: dict[str, str] = {}   # local alias -> module  ("sp" -> "subprocess")
    direct: dict[str, str] = {}    # local name   -> dotted ("Popen" -> "subprocess.Popen")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                direct[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return modules, direct


def _resolve(func: ast.expr, modules: dict[str, str], direct: dict[str, str]) -> str | None:
    """The dotted name a call expression actually resolves to, or None."""
    if isinstance(func, ast.Name):
        return direct.get(func.id)
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        module = modules.get(func.value.id)
        return f"{module}.{func.attr}" if module else None
    return None


def _argv_of(node: ast.Call) -> str | None:
    if node.args:
        return ast.unparse(node.args[0])
    for keyword in node.keywords:
        if keyword.arg in ARGV_KEYWORDS:
            return ast.unparse(keyword.value)
    return None


def _spawn_sites() -> list[tuple[int, str, str]]:
    source = Path(panel_invoker.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules, direct = _import_bindings(tree)
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target, call = node, node
        resolved = _resolve(node.func, modules, direct)
        if resolved == "functools.partial" or ast.unparse(node.func) == "functools.partial":
            # `functools.partial(subprocess.Popen, cmd)` defers the launch; the spawn is
            # the first argument and the argv is what follows.
            if not node.args:
                continue
            resolved = _resolve(node.args[0], modules, direct) or ast.unparse(node.args[0])
            call = ast.Call(func=node.args[0], args=node.args[1:], keywords=node.keywords)
        if resolved not in SPAWN_FUNCTIONS:
            continue
        argv = _argv_of(call)
        if argv is None:
            # A spawn we cannot read the argv of is MORE dangerous than one we can, not
            # less: fail closed and make someone look at it.
            argv = f"<unreadable argv at line {target.lineno}>"
        sites.append((target.lineno, resolved, argv))
    return sites


def test_the_module_still_has_spawn_sites_to_check():
    """Guard the guard: a rename of `subprocess` would make every assertion below vacuous."""
    assert len(_spawn_sites()) >= 8, "the walker found almost nothing; it is not walking"


def test_every_provider_launch_carries_the_egress_prefix():
    unprefixed = [
        (lineno, func, argv)
        for lineno, func, argv in _spawn_sites()
        if PREFIX_EXPR not in argv and argv not in PARENT_SIDE_ALLOWLIST
    ]
    assert not unprefixed, (
        "these spawns are neither egress-prefixed nor declared parent-side:\n"
        + "\n".join(f"  panel_invoker.py:{n}  {f}({a})" for n, f, a in unprefixed)
        + "\n\nWire it with [*_EGRESS_LAUNCH_PREFIX.get(), *argv], or add it to "
          "PARENT_SIDE_ALLOWLIST with the reason it is the parent acting, not a reviewer."
    )


def test_at_least_the_three_known_seats_are_wired():
    """A stale allowlist could satisfy the test above by covering everything."""
    prefixed = [s for s in _spawn_sites() if PREFIX_EXPR in s[2]]
    assert len(prefixed) >= 3, (
        f"expected the CLI-leg, TUI-PTY and agent-view launches to be wired; "
        f"found {len(prefixed)}"
    )


def test_the_allowlist_does_not_rot():
    """An entry that no longer matches any spawn is a stale exemption -- delete it."""
    live = {argv for _lineno, _func, argv in _spawn_sites()}
    stale = sorted(set(PARENT_SIDE_ALLOWLIST) - live)
    assert not stale, f"these allowlist entries match no spawn any more: {stale}"


def test_the_walker_actually_fails_on_an_unwired_spawn(tmp_path, monkeypatch):
    """The falsifier. A guard that has never been seen to fail is not a guard."""
    fake = tmp_path / "fake_invoker.py"
    fake.write_text(
        "import subprocess\n"
        "def launch(cmd):\n"
        "    return subprocess.Popen(list(cmd))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(panel_invoker, "__file__", str(fake))

    sites = _spawn_sites()
    assert sites, "the fixture must present a spawn"
    assert all(PREFIX_EXPR not in argv for _l, _f, argv in sites)
    assert all(argv not in PARENT_SIDE_ALLOWLIST for _l, _f, argv in sites), (
        "the fixture's spawn must be caught, not exempted"
    )
    with pytest.raises(AssertionError, match="neither egress-prefixed nor declared"):
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
    }

    def _sites_for(self, tmp_path, monkeypatch, name, source):
        fake = tmp_path / f"{name.replace(' ', '_').replace('.', '_')}.py"
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
        with pytest.raises(AssertionError, match="neither egress-prefixed nor declared"):
            test_every_provider_launch_carries_the_egress_prefix()

    def test_an_unreadable_argv_fails_closed(self, tmp_path, monkeypatch):
        """A spawn whose argv the walker cannot parse is MORE dangerous, not less."""
        sites = self._sites_for(
            tmp_path, monkeypatch, "opaque",
            "import subprocess\ndef launch(**kw):\n    return subprocess.Popen(**kw)\n",
        )
        assert sites, "an argv-less spawn must still be reported"
        assert "unreadable" in sites[0][2]
