"""Whether this codex CLI accepts the jailed Codex seat's argv (SEATS CODEX, IF-0-CODEX-1).

The jailed argv uses a fixed set of ``codex exec`` options, one ``--sandbox`` value and a
list of ``--disable`` features. :func:`codex_cli_shape_problem` reads the CLI's own
``codex exec --help`` and ``codex features list`` text and names every part of that argv
this CLI does not accept. ``None`` means the CLI accepts all of it.

On the jailed route this check replaces the ``codex sandbox`` shape binding
(agent-harness#1472). The Codex admission gate reports a miss as ``codex_seat_cli_shape``
(IF-0-CODEX-5); the non-brokered route keeps the agent-harness#1469 probe. Nothing here
runs the CLI: the caller supplies both texts.
"""

from __future__ import annotations

import re

__all__ = [
    "CLI_SHAPE_CODE",
    "JAILED_CODEX_DISABLED_FEATURES",
    "JAILED_CODEX_EXEC_OPTIONS",
    "JAILED_CODEX_SANDBOX",
    "codex_cli_shape_problem",
]

#: The IF-0-CODEX-5 code a shape miss refuses with.
CLI_SHAPE_CODE = "codex_seat_cli_shape"

#: Every ``codex exec`` option the jailed argv passes, in argv order, as
#: ``(long name, short alias or None, takes a value)``. The argv writes ``-c`` in its short
#: form, so that alias must be declared too.
JAILED_CODEX_EXEC_OPTIONS: tuple[tuple[str, str | None, bool], ...] = (
    ("--disable", None, True),
    ("--ignore-user-config", None, False),
    ("--ignore-rules", None, False),
    ("--ephemeral", None, False),
    ("--json", None, False),
    ("--cd", None, True),
    ("--skip-git-repo-check", None, False),
    ("--sandbox", None, True),
    ("--config", "-c", True),
    ("--model", None, True),
    ("--output-last-message", None, True),
)

#: The one ``--sandbox`` value the jailed argv passes: the codex inner sandbox is off and
#: the seat jail is the boundary (OD-4).
JAILED_CODEX_SANDBOX = "danger-full-access"

#: IF-0-CODEX-1: ``panel_invoker._BROKER_CODEX_DISABLED_FEATURES`` minus ``shell_tool`` and
#: ``code_mode_host``, plus ``daemon_auto_start`` and ``plugin_discovery_prefetch``. A
#: feature this CLI does not list makes it exit before the turn (``Unknown feature flag``).
JAILED_CODEX_DISABLED_FEATURES: tuple[str, ...] = (
    "auth_elicitation",
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "image_generation",
    "computer_use",
    "in_app_browser",
    "in_app_local_automation",
    "goals",
    "guardian_approval",
    "memories",
    "multi_agent",
    "hooks",
    "plugins",
    "plugin_sharing",
    "remote_plugin",
    "shell_snapshot",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
    "daemon_auto_start",
    "plugin_discovery_prefetch",
)

# One clap option declaration: indented, an optional short alias, the long name, and an
# optional ``<VALUE>`` placeholder; a short-help description may follow after two spaces.
_OPTION = re.compile(
    r"^[ \t]+(?:(?P<short>-[A-Za-z]),[ \t]+)?(?P<long>--[a-z0-9][a-z0-9-]*)"
    r"(?P<value>[ =]<[^>\n]+>(?:\.\.\.)?)?(?:[ \t]{2,}.*)?$"
)
_POSSIBLE = re.compile(r"\[possible values:[ \t]*(?P<values>[^\]]*)\]")
# One ``codex features list`` row: name, stage (one or two words), enabled.
_FEATURE = re.compile(r"^(?P<name>[a-z0-9][a-z0-9_.]*)[ \t]+\S.*?[ \t]+(?:true|false)[ \t]*$")


def _options(exec_help: str) -> dict[str, tuple[str | None, bool, str]]:
    """``long name -> (short alias, takes a value, its help block)``."""
    lines = exec_help.splitlines()
    found: list[tuple[int, re.Match[str]]] = [
        (index, match) for index, line in enumerate(lines)
        if (match := _OPTION.match(line)) is not None
    ]
    options: dict[str, tuple[str | None, bool, str]] = {}
    for position, (index, match) in enumerate(found):
        end = found[position + 1][0] if position + 1 < len(found) else len(lines)
        block = "\n".join(lines[index:end])
        options.setdefault(match["long"], (match["short"], match["value"] is not None, block))
    return options


def _features(features: str) -> frozenset[str]:
    return frozenset(
        match["name"] for line in features.splitlines()
        if (match := _FEATURE.match(line.strip())) is not None
    )


def codex_cli_shape_problem(exec_help: str, features: str) -> str | None:
    """``None`` when ``codex exec --help`` (``exec_help``) and ``codex features list``
    (``features``) accept the jailed argv; otherwise every missing option, alias, value
    or feature, named, in argv order."""
    options = _options(exec_help if isinstance(exec_help, str) else "")
    listed = _features(features if isinstance(features, str) else "")
    if not options:
        return "codex exec --help lists no options"
    problems: list[str] = []
    for long, short, takes_value in JAILED_CODEX_EXEC_OPTIONS:
        declared = options.get(long)
        if declared is None:
            problems.append(f"codex exec --help lists no {long} option")
            continue
        declared_short, declared_value, _block = declared
        if short is not None and declared_short != short:
            problems.append(f"codex exec --help lists no {short} alias for {long}")
        if declared_value != takes_value:
            problems.append(
                f"codex exec --help lists {long} "
                + ("without a value" if takes_value else "with a value"))
    sandbox = options.get("--sandbox")
    if sandbox is not None:
        possible = _POSSIBLE.search(sandbox[2])
        values = (frozenset(item.strip() for item in possible["values"].split(","))
                  if possible is not None else frozenset())
        if JAILED_CODEX_SANDBOX not in values:
            problems.append(f"codex exec --help lists no --sandbox value {JAILED_CODEX_SANDBOX}")
    if not listed:
        problems.append("codex features list lists no features")
    else:
        problems.extend(
            f"codex features list lists no {name} feature"
            for name in JAILED_CODEX_DISABLED_FEATURES if name not in listed)
    return "; ".join(problems) if problems else None
