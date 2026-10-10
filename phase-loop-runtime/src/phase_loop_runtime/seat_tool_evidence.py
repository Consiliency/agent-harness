"""The typed result of probing a CLI seat's own command sandbox (agent-harness#1335).

codex runs each command inside its own bubblewrap sandbox. Where that sandbox cannot start
in the seat's view, the seat can run nothing, yet the CLI still exits 0 with a verdict.
Before a codex seat runs, the runtime therefore launches codex's sandbox once with the
command ``true`` (``panel_invoker._codex_command_sandbox_cannot_start``). This module holds
what that probe needs: the leg detail / notice code for a sandbox that cannot start, and
the test for a launcher's own fatal diagnostic in the probe's output.

Only the probe's output is ever read here, never a seat's transcript or reply. The probed
command prints nothing, so a line that starts with the launcher's name is the launcher's.

Nothing here launches a process or reads a file.
"""

from __future__ import annotations

__all__ = [
    "TOOL_SANDBOX_UNAVAILABLE",
    "launcher_diagnostic_in",
]

#: The leg detail and seat notice code (``seat_jail.NOTICES`` renders what / why / fix).
TOOL_SANDBOX_UNAVAILABLE = "seat_tool_sandbox_unavailable"

# How a sandbox launcher reports that it could not start. bubblewrap prefixes every fatal
# message with its own name, whatever the reason and whatever the version's wording ("No
# permissions to create new namespace" on 0.6, "... create a new namespace" on 0.11, "Can't
# mkdir ...: Read-only file system").
_LAUNCHER_DIAGNOSTIC_PREFIXES: tuple[str, ...] = ("bwrap: ",)


def launcher_diagnostic_in(output: str) -> bool:
    """Does this output carry a sandbox launcher's own fatal diagnostic (a line that STARTS
    with the launcher's name)? For output the runtime itself asked for -- a probe that runs
    ``true`` -- and never for a model's text."""
    return any(line.startswith(_LAUNCHER_DIAGNOSTIC_PREFIXES)
               for line in (output or "").splitlines())
