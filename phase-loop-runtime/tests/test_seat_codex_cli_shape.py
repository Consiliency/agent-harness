"""SEATS CODEX SL-2: the codex CLI shape check that admits the jailed argv (IF-0-CODEX-1).

The recorded texts below are codex-cli 0.167.0's ``codex exec --help`` and the
``codex features list`` rows the jailed argv depends on, read offline (no provider call).
"""

from __future__ import annotations

import re

import pytest

from phase_loop_runtime import panel_invoker, seat_jail
from phase_loop_runtime.seat_codex_cli_shape import (
    CLI_SHAPE_CODE,
    JAILED_CODEX_DISABLED_FEATURES,
    JAILED_CODEX_EXEC_OPTIONS,
    JAILED_CODEX_SANDBOX,
    codex_cli_shape_problem,
)
from phase_loop_runtime.seat_route_contract import OD10_CLASSES


EXEC_HELP_0_167_0 = """\
Run Codex non-interactively

Usage: codex exec [OPTIONS] [PROMPT]
       codex exec [OPTIONS] <COMMAND> [ARGS]

Commands:
  resume  Resume a previous session by id or pick the most recent with --last
  fork    Fork a previous session by id into a new session
  review  Run a code review against the current repository
  help    Print this message or the help of the given subcommand(s)

Arguments:
  [PROMPT]
          Initial instructions for the agent. If not provided as an argument (or if `-` is used),
          instructions are read from stdin. If stdin is piped and a prompt is also provided, stdin
          is appended as a `<stdin>` block

Options:
  -c, --config <key=value>
          Override a configuration value that would otherwise be loaded from `~/.codex/config.toml`.
          Use a dotted path (`foo.bar.baz`) to override nested values. The `value` portion is parsed
          as TOML. If it fails to parse as TOML, the raw string is used as a literal.

          Examples: - `-c model="o3"` - `-c 'sandbox_permissions=["disk-full-read-access"]'` - `-c
          shell_environment_policy.inherit=all`

      --enable <FEATURE>
          Enable a feature (repeatable). Equivalent to `-c features.<name>=true`

      --disable <FEATURE>
          Disable a feature (repeatable). Equivalent to `-c features.<name>=false`

      --strict-config
          Error out when config.toml contains fields that are not recognized by this version of
          Codex

  -i, --image <FILE>...
          Optional image(s) to attach to the initial prompt

  -m, --model <MODEL>
          Model the agent should use

      --oss
          Use open-source provider

      --local-provider <OSS_PROVIDER>
          Specify which local provider to use (lmstudio or ollama). If not specified with --oss,
          will use config default or show selection

  -p, --profile <CONFIG_PROFILE_V2>
          Layer $CODEX_HOME/<name>.config.toml on top of the base user config

  -s, --sandbox <SANDBOX_MODE>
          Select the sandbox policy to use when executing model-generated shell commands

          [possible values: read-only, workspace-write, danger-full-access]

      --approve-for-me
          Route approval requests through automatic review using the workspace-write sandbox

      --dangerously-bypass-approvals-and-sandbox
          Skip all confirmation prompts and execute commands without sandboxing. EXTREMELY
          DANGEROUS. Intended solely for running in environments that are externally sandboxed

      --dangerously-bypass-hook-trust
          Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.
          Intended only for automation that already vets hook sources

  -C, --cd <DIR>
          Tell the agent to use the specified directory as its working root

      --worktree
          Run the session in a new managed Git worktree

      --add-dir <DIR>
          Additional directories that should be writable alongside the primary workspace

      --thread-source <SOURCE>
          Source classification for newly created or forked threads

      --cyber-access-program <PROGRAM>
          Request an experimental Cyber access program for this turn (OpenAI provider only). Omit to
          use server defaults. Not supported with review; fork requires a prompt

          [possible values: standard, daybreak_blue, daybreak_red]

      --skip-git-repo-check
          Allow running Codex outside a Git repository

      --ephemeral
          Run without persisting session files to disk

      --ignore-user-config
          Do not load `$CODEX_HOME/config.toml`; auth still uses `CODEX_HOME`

      --ignore-rules
          Do not load user or project execpolicy `.rules` files

      --output-schema <FILE>
          Path to a JSON Schema file describing the model's final response shape

      --color <COLOR>
          Specifies color settings for use in the output

          [default: auto]
          [possible values: always, never, auto]

      --json
          Print events to stdout as JSONL

  -o, --output-last-message <FILE>
          Specifies file where the last message from the agent should be written

  -h, --help
          Print help (see a summary with '-h')

  -V, --version
          Print version
"""

FEATURES_0_167_0 = """\
apps                                     stable             true
auth_elicitation                         stable             true
browser_use                              stable             true
browser_use_external                     stable             true
browser_use_full_cdp_access              stable             true
code_mode                                under development  false
code_mode_host                           stable             true
computer_use                             stable             true
daemon_auto_start                        stable             true
goals                                    stable             true
guardian_approval                        stable             true
guardianv2.thread_context                removed            false
hooks                                    stable             true
image_generation                         stable             true
in_app_browser                           stable             true
in_app_local_automation                  stable             true
memories                                 stable             false
multi_agent                              stable             true
plugin_discovery_prefetch                stable             true
plugin_sharing                           stable             true
plugins                                  stable             true
remote_plugin                            stable             true
responses_websockets                     removed            false
responses_websockets_v2                  removed            false
shell_snapshot                           stable             true
shell_tool                               stable             true
skill_mcp_dependency_install             stable             true
skill_search                             stable             true
tool_call_mcp_elicitation                stable             true
tool_suggest                             stable             true
unified_exec                             stable             true
use_legacy_landlock                      deprecated         false
view_image                               stable             true
workspace_dependencies                   stable             true
"""


def _without_line(text: str, needle: str) -> str:
    lines = text.splitlines()
    kept = [line for line in lines if line.strip() != needle]
    assert len(kept) == len(lines) - 1, needle
    return "\n".join(kept) + "\n"


def _declaration(long: str) -> str:
    pattern = re.compile(rf"(-[A-Za-z], )?{re.escape(long)}( <[^>]+>(\.\.\.)?)?")
    found = [line.strip() for line in EXEC_HELP_0_167_0.splitlines()
             if pattern.fullmatch(line.strip())]
    assert len(found) == 1, (long, found)
    return found[0]


def test_the_recorded_cli_accepts_the_jailed_argv():
    assert codex_cli_shape_problem(EXEC_HELP_0_167_0, FEATURES_0_167_0) is None


@pytest.mark.parametrize("long", [option[0] for option in JAILED_CODEX_EXEC_OPTIONS])
def test_each_missing_option_is_named(long):
    declaration = _declaration(long)
    problem = codex_cli_shape_problem(_without_line(EXEC_HELP_0_167_0, declaration),
                                      FEATURES_0_167_0)
    assert problem is not None
    assert f"lists no {long} option" in problem


def test_a_missing_short_alias_is_named():
    changed = EXEC_HELP_0_167_0.replace("  -c, --config <key=value>", "      --config <key=value>")
    assert changed != EXEC_HELP_0_167_0
    problem = codex_cli_shape_problem(changed, FEATURES_0_167_0)
    assert problem == "codex exec --help lists no -c alias for --config"


@pytest.mark.parametrize("before,after,named", [
    ("  -m, --model <MODEL>", "  -m, --model", "lists --model without a value"),
    ("      --json\n", "      --json <FORMAT>\n", "lists --json with a value"),
])
def test_a_changed_value_shape_is_named(before, after, named):
    changed = EXEC_HELP_0_167_0.replace(before, after)
    assert changed != EXEC_HELP_0_167_0
    assert codex_cli_shape_problem(changed, FEATURES_0_167_0) == f"codex exec --help {named}"


@pytest.mark.parametrize("values", [
    "[possible values: read-only, workspace-write]",
    "[possible values: read-only, workspace-write, danger-full-access-v2]",
    "",
])
def test_a_missing_sandbox_value_is_named(values):
    original = "[possible values: read-only, workspace-write, danger-full-access]"
    assert EXEC_HELP_0_167_0.count(original) == 1
    changed = EXEC_HELP_0_167_0.replace(original, values)
    problem = codex_cli_shape_problem(changed, FEATURES_0_167_0)
    assert problem == f"codex exec --help lists no --sandbox value {JAILED_CODEX_SANDBOX}"


def test_the_sandbox_value_is_read_from_the_sandbox_option_only():
    # Another option's possible values never stand in for --sandbox's.
    original = "[possible values: read-only, workspace-write, danger-full-access]"
    changed = EXEC_HELP_0_167_0.replace(original, "[possible values: read-only]").replace(
        "[possible values: always, never, auto]",
        "[possible values: always, never, auto, danger-full-access]")
    problem = codex_cli_shape_problem(changed, FEATURES_0_167_0)
    assert problem == f"codex exec --help lists no --sandbox value {JAILED_CODEX_SANDBOX}"


@pytest.mark.parametrize("name", JAILED_CODEX_DISABLED_FEATURES)
def test_each_missing_feature_is_named(name):
    row = next(line for line in FEATURES_0_167_0.splitlines() if line.split()[0] == name)
    problem = codex_cli_shape_problem(EXEC_HELP_0_167_0, _without_line(FEATURES_0_167_0, row))
    assert problem == f"codex features list lists no {name} feature"


def test_a_removed_or_disabled_feature_is_still_listed():
    # `--disable` of a removed feature starts; only an unknown name stops the CLI.
    rows = [line.replace("stable             true", "removed            false")
            if line.split()[0] == "daemon_auto_start" else line
            for line in FEATURES_0_167_0.splitlines()]
    assert codex_cli_shape_problem(EXEC_HELP_0_167_0, "\n".join(rows)) is None


def test_every_miss_is_named_in_argv_order():
    changed = _without_line(EXEC_HELP_0_167_0, "--ignore-rules")
    changed = _without_line(changed, "--ephemeral")
    features = _without_line(
        FEATURES_0_167_0,
        next(line for line in FEATURES_0_167_0.splitlines() if line.startswith("hooks ")))
    assert codex_cli_shape_problem(changed, features) == (
        "codex exec --help lists no --ignore-rules option; "
        "codex exec --help lists no --ephemeral option; "
        "codex features list lists no hooks feature")


@pytest.mark.parametrize("exec_help,features,named", [
    ("", FEATURES_0_167_0, "codex exec --help lists no options"),
    ("garbled output\n", FEATURES_0_167_0, "codex exec --help lists no options"),
    (EXEC_HELP_0_167_0, "", "codex features list lists no features"),
    (None, FEATURES_0_167_0, "codex exec --help lists no options"),
])
def test_unreadable_inputs_are_named(exec_help, features, named):
    assert codex_cli_shape_problem(exec_help, features) == named


def test_the_disabled_features_follow_the_broker_list():
    broker = panel_invoker._BROKER_CODEX_DISABLED_FEATURES
    expected = tuple(name for name in broker if name not in ("shell_tool", "code_mode_host"))
    assert JAILED_CODEX_DISABLED_FEATURES == (
        *expected, "daemon_auto_start", "plugin_discovery_prefetch")
    assert len(set(JAILED_CODEX_DISABLED_FEATURES)) == len(JAILED_CODEX_DISABLED_FEATURES)


def test_the_options_are_the_jailed_argv_options():
    longs = [option[0] for option in JAILED_CODEX_EXEC_OPTIONS]
    assert longs == [
        "--disable", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json", "--cd",
        "--skip-git-repo-check", "--sandbox", "--config", "--model", "--output-last-message",
    ]
    forbidden = {"--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust",
                 "--add-dir", "--worktree", "--oss", "--profile"}
    assert not forbidden & set(longs)


def test_the_shape_code_is_an_ordinary_codex_seat_code():
    assert CLI_SHAPE_CODE == "codex_seat_cli_shape"
    assert CLI_SHAPE_CODE in seat_jail.CODEX_SEAT_CODES
    assert OD10_CLASSES[CLI_SHAPE_CODE] == "ordinary"
