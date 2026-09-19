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


SPAWN_ATTRS = frozenset({
    "Popen", "run", "call", "check_call", "check_output",
    "create_subprocess_exec", "create_subprocess_shell",
    "execv", "execvp", "execvpe", "spawnv", "posix_spawn", "system",
})

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

PREFIX_EXPR = "_EGRESS_LAUNCH_PREFIX.get()"


def _spawn_sites() -> list[tuple[int, str, str]]:
    source = Path(panel_invoker.__file__).read_text(encoding="utf-8")
    sites = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        if func.rsplit(".", 1)[-1] not in SPAWN_ATTRS:
            continue
        if not any(func.startswith(mod) for mod in ("subprocess.", "os.", "asyncio.")):
            continue
        if not node.args:
            continue
        sites.append((node.lineno, func, ast.unparse(node.args[0])))
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
