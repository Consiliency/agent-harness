"""The typed result of probing a CLI seat's own command sandbox (agent-harness#1335).

codex runs each command inside its own bubblewrap sandbox. Where that sandbox cannot start
in the seat's view, the seat can run nothing, yet the CLI still exits 0 with a verdict.
On the non-brokered route, outside capture-enabled launches, the runtime probes
codex's sandbox with ``true`` (``panel_invoker._codex_command_sandbox_cannot_start``).
Jailed review seats instead use the CLI-shape gate and a parent-held completed-command
record. This module holds
what that probe needs: the leg detail / notice code for a sandbox that cannot start, and
the test for a launcher's own fatal diagnostic in the probe's output.

Only the probe's output is ever read here, never a seat's transcript or reply. The probed
command prints nothing, so a line that starts with the launcher's name is the launcher's.

Nothing here launches a process or reads a file.
"""

from __future__ import annotations

import os
import re

__all__ = [
    "CAUSE_NESTED_NAMESPACE",
    "CAUSE_READ_ONLY_TREE",
    "CAUSE_UNKNOWN",
    "KNOWN_CAUSES",
    "TOOL_SANDBOX_UNAVAILABLE",
    "classify_launcher_diagnostic",
    "launcher_diagnostic_in",
]

#: The leg detail and seat notice code (``seat_jail.NOTICES`` renders what / why / fix).
TOOL_SANDBOX_UNAVAILABLE = "seat_tool_sandbox_unavailable"

#: Closed cause vocabulary for ``seat_tool_sandbox_unavailable`` notices (agent-harness#1473).
CAUSE_NESTED_NAMESPACE = "nested_namespace"
CAUSE_READ_ONLY_TREE = "read_only_tree"
CAUSE_UNKNOWN = "unknown"
KNOWN_CAUSES: frozenset[str] = frozenset({CAUSE_NESTED_NAMESPACE, CAUSE_READ_ONLY_TREE})

# How a sandbox launcher reports that it could not start. bubblewrap prefixes every fatal
# message with its own name, whatever the reason and whatever the version's wording ("No
# permissions to create new namespace" on 0.6, "... create a new namespace" on 0.11, "Can't
# mkdir ...: Read-only file system").
_LAUNCHER_DIAGNOSTIC_PREFIXES: tuple[str, ...] = ("bwrap: ",)

# Closed substrings within a ``bwrap: `` diagnostic line that distinguish the two known causes
# (agent-harness#1473). Never matched against lines without a launcher prefix.
_READ_ONLY_TREE_MARKERS: tuple[str, ...] = (
    "read-only file system",
)
_NESTED_NAMESPACE_MARKERS: tuple[str, ...] = (
    "create new namespace",
    "create a new namespace",
    "creating new namespace",
    "user namespace",
    "unprivileged_userns",
    "setting up uid map",
    "setting up gid map",
)


def _line_targets_tree(line: str, workdir: str | os.PathLike[str]) -> bool:
    """True when ``line`` names ``workdir`` (or a child path under it) as a path token.

    Pure string/path normalization only -- never touches the filesystem.
    """
    raw = os.fspath(workdir)
    if not raw:
        return False
    root = os.path.normpath(raw).rstrip("/")
    if not root:
        return False
    return re.search(r"(?:^|[\s'\":])" + re.escape(root) + r"(?:$|[/:\s'\"])", line) is not None


def classify_launcher_diagnostic(
    output: str,
    *,
    sandbox_mode: str | None = None,
    workdir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Classify a sandbox launcher's fatal diagnostic line in probe output (agent-harness#1473).

    Returns:
    - ``CAUSE_READ_ONLY_TREE`` ONLY when ``sandbox_mode == "workspace-write"``, ``workdir``
      is given, and a ``bwrap: `` line reports ``Read-only file system`` on a path inside
      ``workdir`` (never blaming a read-only staged tree for a ``read-only`` seat or an
      unrelated path such as ``/var/other``);
    - ``CAUSE_NESTED_NAMESPACE`` when a ``bwrap: `` line reports a refused user namespace;
    - ``CAUSE_UNKNOWN`` when a ``bwrap: `` line is present without matching a proven cause;
    - ``None`` when no launcher diagnostic line is present.

    Only ever inspect output from the runtime's own ``true`` probe.
    """
    matched_launcher = False
    for line in (output or "").splitlines():
        if not line.startswith(_LAUNCHER_DIAGNOSTIC_PREFIXES):
            continue
        matched_launcher = True
        lowered = line.lower()
        if any(marker in lowered for marker in _NESTED_NAMESPACE_MARKERS):
            return CAUSE_NESTED_NAMESPACE
        if (
            sandbox_mode == "workspace-write"
            and workdir is not None
            and any(marker in lowered for marker in _READ_ONLY_TREE_MARKERS)
            and _line_targets_tree(line, workdir)
        ):
            return CAUSE_READ_ONLY_TREE
    return CAUSE_UNKNOWN if matched_launcher else None


def launcher_diagnostic_in(output: str) -> bool:
    """Does this output carry a sandbox launcher's own fatal diagnostic (a line that STARTS
    with the launcher's name)? For output the runtime itself asked for -- a probe that runs
    ``true`` -- and never for a model's text."""
    return classify_launcher_diagnostic(output) is not None
