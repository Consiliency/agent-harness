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
import posixpath
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

# Closed anchored message forms after ``bwrap: `` that distinguish the two known causes
# (agent-harness#1473). Anchoring prevents a pathname containing words such as
# ``user namespace`` from being misclassified as a namespace refusal.
_NESTED_NAMESPACE_PREFIXES: tuple[str, ...] = (
    "no permissions to create new namespace",
    "no permissions to create a new namespace",
    "creating new namespace failed",
    "setting up uid map",
    "setting up gid map",
)
_READ_ONLY_PATH_RE = re.compile(
    r"^(?:can't (?:mkdir|create file at|make symlink at|open|chdir to|mount .+ on|bind mount .+ on|remount)"
    r"|failed to (?:mkdir|create|mount .+ on))\s+"
    r"(?P<path>/[^\n:]+):\s*read-only file system\s*$",
    re.IGNORECASE,
)


def _strip_launcher_prefix(line: str) -> str | None:
    for prefix in _LAUNCHER_DIAGNOSTIC_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def _read_only_path_within_tree(message: str, workdir: str | os.PathLike[str]) -> bool:
    """True when ``message`` names a concrete failing path normalized inside ``workdir``.

    Pure POSIX path normalization only -- never touches the filesystem. Rejects
    parent traversals (``/tmp/staged/../other``), sibling space-prefixed paths
    (``/tmp/staged elsewhere/cache``), and ambiguous messages.
    """
    match = _READ_ONLY_PATH_RE.match(message)
    if match is None:
        return False
    raw_root = os.fspath(workdir)
    if not raw_root or not raw_root.startswith("/"):
        return False
    norm_root = posixpath.normpath(raw_root)
    if norm_root == "/":
        return False
    norm_path = posixpath.normpath(match.group("path"))
    return norm_path == norm_root or norm_path.startswith(norm_root + "/")


def classify_launcher_diagnostic(
    output: str,
    *,
    sandbox_mode: str | None = None,
    workdir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Classify a sandbox launcher's fatal diagnostic line in probe output (agent-harness#1473).

    Returns:
    - ``CAUSE_NESTED_NAMESPACE`` when a ``bwrap: `` message begins with a known namespace
      refusal form;
    - ``CAUSE_READ_ONLY_TREE`` ONLY when ``sandbox_mode == "workspace-write"``, ``workdir``
      is given, and a ``bwrap: `` message reports ``Read-only file system`` on a concrete
      normalized path inside ``workdir``;
    - ``CAUSE_UNKNOWN`` when a ``bwrap: `` line is present without matching a proven cause;
    - ``None`` when no launcher diagnostic line is present.

    Only ever inspect output from the runtime's own ``true`` probe.
    """
    matched_launcher = False
    for line in (output or "").splitlines():
        message = _strip_launcher_prefix(line)
        if message is None:
            continue
        matched_launcher = True
        lowered = message.lower()
        if lowered.startswith(_NESTED_NAMESPACE_PREFIXES):
            return CAUSE_NESTED_NAMESPACE
        if (
            sandbox_mode == "workspace-write"
            and workdir is not None
            and _read_only_path_within_tree(message, workdir)
        ):
            return CAUSE_READ_ONLY_TREE
    return CAUSE_UNKNOWN if matched_launcher else None


def launcher_diagnostic_in(output: str) -> bool:
    """Does this output carry a sandbox launcher's own fatal diagnostic (a line that STARTS
    with the launcher's name)? For output the runtime itself asked for -- a probe that runs
    ``true`` -- and never for a model's text."""
    return classify_launcher_diagnostic(output) is not None
