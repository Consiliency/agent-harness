"""The parallel-suite plumbing must stay identical in both CI consumers.

The hosted GitHub lane and the Dagger offload lane build their own environment
and spell their own pytest invocation. Nothing makes them agree, so a pin bumped
in one and not the other silently gives the two lanes different parallelism --
the class the chronology-node test already guards for the node id
(`test_ci_chronology_scope.py::test_every_consumer_spells_the_same_node_id`).

These assertions are bound to the actual COMMANDS, not to the files. An earlier
revision searched each whole file for the flag substring; review
(Consiliency/agent-harness#956, codex and grok independently) showed it passed
when the flags were moved from the suite invocation onto the `--collect-only`
probe, or when the xdist pin survived only in a comment. The
`*_is_rejected` tests below replay exactly those mutations against the checker
so that the binding cannot quietly loosen again.

Adoption measurement and the crash this configuration depends on:
`/mnt/workspace/archives/ci-audit-20260921/xdist/REPORT.md` (Consiliency/agent-harness#945),
and the worker-killing lease guard fixed in Consiliency/agent-harness#950.
"""
from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test.yml"
DAGGER_MODULE = REPO_ROOT / "ci" / "dagger" / "src" / "agent_harness_ci" / "main.py"

# The version this repository's xdist-cleanliness was actually measured against.
XDIST_PIN = "pytest-xdist==3.8.0"

# The suite's parallel configuration, as the exact token sequence it must carry.
REQUIRED_SUITE_ARGS = ("-n", "auto", "--dist", "loadfile", "--max-worker-restart=0")

# Workflows and the Dagger module are repository source, not package data, so
# Gate A's copied standalone tree cannot evaluate these assertions.
pytestmark = pytest.mark.skipif(
    not WORKFLOW_PATH.is_file() or not DAGGER_MODULE.is_file(),
    reason="CI plumbing is absent from the standalone consumer layout",
)


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _dagger() -> str:
    return DAGGER_MODULE.read_text(encoding="utf-8")


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _commands_only(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _is_comment(line))


def _logical_commands(text: str) -> list[tuple[int, str]]:
    """Join backslash-continued shell lines into (first_line_index, command).

    Handles both the workflow's literal `\\` continuation and the Dagger
    module's shell script held in a Python string, where each continuation is
    written `\\\\`. Comment lines are never commands.
    """
    lines = text.splitlines()
    commands: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        if _is_comment(lines[i]):
            i += 1
            continue
        start, parts = i, []
        while True:
            stripped = lines[i].rstrip()
            continued = stripped.endswith("\\")
            parts.append(stripped.rstrip("\\").strip())
            i += 1
            if not continued or i >= len(lines):
                break
        commands.append((start, " ".join(p for p in parts if p)))
    return commands


def suite_command(text: str) -> tuple[int, str]:
    """The ONE invocation that runs the suite (not the collect-only probe).

    It is the `PYTHONPATH=src:tests` pytest run without `--collect-only`. The
    copied-tree LEGIBLE run uses `PYTHONPATH="$suite_root/tests"` and is
    deliberately not matched. Exactly one match is required: an ambiguity reds
    rather than letting the check silently bind to whichever came first.
    """
    matches = [
        (start, cmd) for start, cmd in _logical_commands(text)
        if "PYTHONPATH=src:tests" in cmd and "python -m pytest" in cmd
        and "--collect-only" not in cmd
    ]
    assert len(matches) == 1, (
        f"expected exactly one suite invocation, found {len(matches)}: "
        f"{[cmd[:80] for _, cmd in matches]}"
    )
    return matches[0]


_CONTROL_OPERATORS = {"&&", "||", ";", "|", "&", ";;"}


def _tokens(command: str) -> list[str]:
    """Shell words as bash would see them for ONE simple command.

    `comments=True`: a `#` at word start ends the command, exactly as in bash --
    including a flag line commented out in the MIDDLE of a backslash
    continuation, which a comment-blind tokenizer would still count (grok r2).
    Tokens stop at the first control operator, so flags placed after
    `&& true` belong to another command, not to pytest (grok r2). The Dagger
    script is a Python f-string; `${{suite_args[@]}}` is literal text here.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    out: list[str] = []
    for tok in lexer:
        if tok in _CONTROL_OPERATORS:
            break
        out.append(tok)
    return out


_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# The options that decide parallelism, and the value each must EFFECTIVELY have.
# pytest/argparse is last-wins, so the LAST occurrence is the one that counts.
_EFFECTIVE = {"-n": "auto", "--dist": "loadfile", "--max-worker-restart": "0"}


def pytest_argv(command: str) -> list[str] | None:
    """The argv handed to pytest, or None if this command does not RUN pytest.

    Leading `VAR=value` assignments are skipped; the executable must then be
    exactly `python -m pytest`. `echo PYTHONPATH=... python -m pytest ...` prints
    the invocation instead of running it, and is therefore not a suite run.
    """
    toks = _tokens(command)
    i = 0
    while i < len(toks) and _ENV_ASSIGNMENT.match(toks[i]):
        i += 1
    if toks[i:i + 3] != ["python", "-m", "pytest"]:
        return None
    return toks[i + 3:]


def effective_parallelism(argv: list[str]) -> dict[str, str | None] | None:
    """The parallelism PYTEST ITSELF would run with for ``argv``, or None if it rejects it.

    A hand-written option scanner was the r2/r3 failure mode: every spelling it did not
    know (`-n0`, `-n=0`) kept the old value while pytest applied the new one. So ask
    pytest's own parser, with xdist loaded, for the parsed option values. A usage error
    (unknown option, `-n` after `-p no:xdist`, ...) returns None: the guard fails closed,
    and CI would fail loudly on the same argv anyway. `--noconftest` keeps this suite's
    conftest from being re-registered into a second in-process Config; `_prepareconfig`
    is private pytest API, acceptable in a test that pins its own pytest-xdist.
    """
    from _pytest.config import _prepareconfig

    try:
        config = _prepareconfig([*argv, "--noconftest"])
    except (pytest.UsageError, SystemExit):
        return None
    try:
        opt = config.option
        return {
            "-n": None if getattr(opt, "numprocesses", None) is None else str(opt.numprocesses),
            "--dist": getattr(opt, "dist", None),
            "--max-worker-restart": getattr(opt, "maxworkerrestart", None),
            "xdist_disabled": "yes" if config.pluginmanager.is_blocked("xdist") else None,
        }
    finally:
        config._ensure_unconfigure()


def carries_suite_args(command: str) -> bool:
    """The command RUNS pytest and its EFFECTIVE parallelism is the required one."""
    argv = pytest_argv(command)
    if argv is None:
        return False
    eff = effective_parallelism(argv)
    if eff is None:
        return False
    return eff.pop("xdist_disabled") is None and eff == _EFFECTIVE


# `"${suite_args[@]}"` is expanded into the suite command, so anything appended
# to it is part of the effective argv. Only these may be.
_SUITE_ARGS_ALLOWED = ("--junitxml=", "--deselect=")


def workflow_suite_args_additions(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'suite_args\+=\("([^"]*)"\)', _commands_only(text))]


def dagger_suite_args_additions(source: str) -> list[str]:
    """Leading literal text of each `suite_args.append(...)` argument (via ast)."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "suite_args" and node.args):
            arg = node.args[0]
            if isinstance(arg, ast.Constant):
                out.append(str(arg.value))
            elif isinstance(arg, ast.JoinedStr) and arg.values and isinstance(arg.values[0], ast.Constant):
                out.append(str(arg.values[0].value))
            else:
                out.append("<non-literal>")
    return out


def explains_restart_cap(text: str, command_start: int) -> bool:
    """The comment block DIRECTLY above the suite command names the restart cap.

    Prose elsewhere in the file does not count: a reader deciding whether to
    drop the flag looks at the lines above the command, not the rest of the file.
    """
    lines, i, block = text.splitlines(), command_start - 1, []
    while i >= 0 and _is_comment(lines[i]):
        block.append(lines[i])
        i -= 1
    text_block = "\n".join(block)
    # Both halves: that the cap exists, and that it is COUPLED to loadfile, so a
    # later switch of distribution mode is not read as making it droppable.
    return "--max-worker-restart=0" in text_block and "loadfile" in text_block


def hosted_install_pins(text: str) -> list[str]:
    """xdist pins in the hosted lane's suite-environment `pip install` COMMAND."""
    installs = [
        cmd for _, cmd in _logical_commands(text)
        if "pip install" in cmd and "./phase-loop-runtime" in cmd
    ]
    assert len(installs) == 1, f"expected one suite-environment install, found {len(installs)}"
    return [t for t in _tokens(installs[0].split("run:", 1)[-1]) if t.startswith("pytest-xdist")]


def dagger_install_pins(source: str) -> list[str]:
    """xdist pins in the Dagger `with_exec([... pip install ...])` argv LIST.

    Parsed with `ast`, so only string literals that are elements of the real
    argv list count -- a comment or docstring mentioning the pin does not.
    """
    pins: list[str] = []
    installs = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.List):
            elts = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if "pip" in elts and "install" in elts and "./phase-loop-runtime[visual]" in elts:
                installs += 1
                pins.extend(e for e in elts if e.startswith("pytest-xdist"))
    assert installs == 1, f"expected one suite-environment install argv, found {installs}"
    return pins


CONSUMERS = (("test.yml", _workflow), ("ci/dagger main.py", _dagger))


def test_both_ci_consumers_pin_the_same_pytest_xdist() -> None:
    hosted, dagger = hosted_install_pins(_workflow()), dagger_install_pins(_dagger())
    assert hosted == [XDIST_PIN], f"hosted install command pins {hosted}"
    assert dagger == [XDIST_PIN], f"dagger install argv pins {dagger}"


@pytest.mark.parametrize("label,read", CONSUMERS)
def test_the_suite_invocation_itself_carries_the_parallel_args(label, read) -> None:
    _, command = suite_command(read())
    assert carries_suite_args(command), (
        f"{label}: the suite command does not carry `{' '.join(REQUIRED_SUITE_ARGS)}`: {command}"
    )


@pytest.mark.parametrize("label,read", CONSUMERS)
def test_the_restart_cap_is_explained_beside_the_command(label, read) -> None:
    """`--max-worker-restart=0` is the flag that makes a crash observable.

    Under the loadfile/loadscope schedulers, xdist's default of replacing a dead
    worker leaves the controller waiting with every worker idle, so the lane burns
    its whole timeout with no failing node named (`--dist load` recovers instead).
    """
    text = read()
    start, _ = suite_command(text)
    assert explains_restart_cap(text, start), (
        f"{label}: no comment directly above the suite command names "
        "--max-worker-restart=0; a later reader will take it for tidiness and drop it"
    )


def dagger_auto_worker_cap(source: str) -> list[str]:
    """Values `_base` passes to `.with_env_variable("PYTEST_XDIST_AUTO_NUM_WORKERS", ...)`.

    Read with `ast`, so a comment or string elsewhere cannot satisfy it.
    """
    values: list[str] = []
    # Bound to the body of `_base`, the container every suite stage and Gate A
    # inherit -- a call elsewhere in the module might never reach a suite run.
    bases = [n for n in ast.walk(ast.parse(source))
             if isinstance(n, ast.FunctionDef) and n.name == "_base"]
    assert len(bases) == 1, f"expected one `_base` builder, found {len(bases)}"
    for node in ast.walk(bases[0]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "with_env_variable" and len(node.args) == 2
                and all(isinstance(a, ast.Constant) for a in node.args)
                and node.args[0].value == "PYTEST_XDIST_AUTO_NUM_WORKERS"):
            values.append(node.args[1].value)
    return values


def test_the_offload_caps_auto_workers_without_changing_the_command() -> None:
    """`-n auto` on the offload host would be 32 per container, ~96 across the
    concurrent stages, and worker count scales the suite's cross-worker races.
    The cap lives in the container ENV so the suite command stays identical to
    the hosted lane's -- a per-consumer `-n 8` would break that contract.
    """
    assert dagger_auto_worker_cap(_dagger()) == ["8"]
    assert "-n auto" in suite_command(_dagger())[1], "the command must still say -n auto"


# --- The binding must reject the mutations review found it accepted. ---------

def test_moving_the_args_onto_the_collect_only_probe_is_rejected() -> None:
    """codex r1 counterexample: flags relocated to `--collect-only`, suite bare."""
    text = _workflow()
    flags = " ".join(REQUIRED_SUITE_ARGS)
    mutated = text.replace(f"            {flags} \\\n", "", 1).replace(
        "python -m pytest --collect-only -q", f"python -m pytest {flags} --collect-only -q", 1
    )
    assert mutated != text and flags in mutated
    _, command = suite_command(mutated)
    assert not carries_suite_args(command)


def test_a_pin_surviving_only_in_a_comment_is_rejected() -> None:
    text = _workflow()
    mutated = text.replace(f' "{XDIST_PIN}"', "", 1) + f"\n# formerly installed {XDIST_PIN}\n"
    assert XDIST_PIN in mutated
    assert hosted_install_pins(mutated) == []

    source = _dagger()
    mutated_src = source.replace(f'"{XDIST_PIN}",', "", 1) + f"\n# {XDIST_PIN}\n"
    assert XDIST_PIN in mutated_src
    assert dagger_install_pins(mutated_src) == []


def test_an_explanation_elsewhere_in_the_file_is_rejected() -> None:
    text = _workflow()
    start, _ = suite_command(text)
    lines = text.splitlines()
    i = start - 1
    while i >= 0 and _is_comment(lines[i]):
        i -= 1
    # Drop the block above the command, keep a far-away mention of the flag.
    mutated_lines = lines[: i + 1] + lines[start:] + ["# note: --max-worker-restart=0"]
    mutated = "\n".join(mutated_lines)
    new_start, _ = suite_command(mutated)
    assert not explains_restart_cap(mutated, new_start)


@pytest.mark.parametrize("label,additions", (
    ("test.yml", lambda: workflow_suite_args_additions(_workflow())),
    ("ci/dagger main.py", lambda: dagger_suite_args_additions(_dagger())),
))
def test_nothing_but_junit_and_deselect_is_smuggled_through_suite_args(label, additions) -> None:
    found = additions()
    assert found, f"{label}: no suite_args additions found -- the scan is not seeing the script"
    bad = [a for a in found if not a.startswith(_SUITE_ARGS_ALLOWED)]
    assert not bad, f"{label}: suite_args carries {bad}, which reaches the suite argv"


def test_a_later_overriding_worker_count_is_rejected() -> None:
    """codex r2: `-n 0` AFTER the required flags wins (last-wins) and disables xdist."""
    _, command = suite_command(_workflow())
    assert carries_suite_args(command)
    assert not carries_suite_args(command + " -n 0")
    assert not carries_suite_args(command + " --numprocesses=0")
    assert not carries_suite_args(command + " --dist load")
    assert not carries_suite_args(command + " -p no:xdist")
    # r3 (found before the cap round launched): the attached short forms. pytest
    # parses both as 0 workers; the hand scanner kept `auto` for `-n0`.
    assert not carries_suite_args(command + " -n0")
    assert not carries_suite_args(command + " -n=0")
    assert not carries_suite_args(command + " --dist=load")
    assert not carries_suite_args(command + " --max-worker-restart 4")


def test_a_command_that_does_not_run_pytest_is_rejected() -> None:
    """codex r2: `echo PYTHONPATH=... python -m pytest ...` prints, it does not run."""
    _, command = suite_command(_workflow())
    assert not carries_suite_args("echo " + command)
    assert pytest_argv("echo " + command) is None


def test_an_override_smuggled_through_suite_args_is_rejected() -> None:
    mutated = _workflow().replace('suite_args=()', 'suite_args=()\n          suite_args+=("-n")', 1)
    bad = [a for a in workflow_suite_args_additions(mutated) if not a.startswith(_SUITE_ARGS_ALLOWED)]
    assert bad == ["-n"]


def test_flags_commented_out_mid_continuation_are_rejected() -> None:
    """grok r2: bash drops everything after a word-initial `#`."""
    _, command = suite_command(_workflow())
    commented = command.replace("-n auto --dist loadfile --max-worker-restart=0",
                                "# -n auto --dist loadfile --max-worker-restart=0", 1)
    assert commented != command
    assert not carries_suite_args(commented)


def test_flags_after_a_second_command_are_rejected() -> None:
    """grok r2: `... && true -n auto ...` gives those flags to `true`, not pytest."""
    _, command = suite_command(_workflow())
    stripped = command.replace("-n auto --dist loadfile --max-worker-restart=0", "", 1)
    assert not carries_suite_args(stripped + " && true -n auto --dist loadfile --max-worker-restart=0")


def test_parallelism_is_not_moved_into_addopts() -> None:
    """`-n` in `addopts` would parallelise the suite's own nested pytest runs.

    Many tests in this suite spawn pytest as a subprocess. An ini-level `-n`
    applies to those children too, which both oversubscribes the host and makes
    a child's own worker crash indistinguishable from the parent's.
    """
    pyproject = (REPO_ROOT / "phase-loop-runtime" / "pyproject.toml").read_text(encoding="utf-8")
    ini = pyproject.partition("[tool.pytest.ini_options]")[2].partition("\n[")[0]
    assert "addopts" not in ini, (
        "pytest addopts now exists; -n must never live there (nested pytest runs)"
    )
